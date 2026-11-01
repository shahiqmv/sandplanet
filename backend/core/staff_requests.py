"""Asking for an advance, or for leave.

Both flows end in machinery that already exists and is already trusted:

  * an advance becomes an HR-origin PYR — the same document HR raises today,
    on the same cost head, recovered by the same SalaryAdvance rows. Nothing
    here creates money; Finance raises that PYR through the normal form and
    the request records which one settled it.
  * leave becomes a WorkerLeave through core.leave.grant, which moves the man
    to Head Office and pre-marks the days. Nothing here touches a roster.

What was missing was the front of both: today HR raises an advance on
somebody's behalf, and HR grants leave with no approval step at all. The ask
and the Director's decision are what this module adds (owner 2026-08-30).

Two restrictions the owner set:
  * leave is for STAFF, not workers — 33 people, not 555. Site labour keeps
    the HR-driven route it has now.
  * an advance is always recovered in one month, so there is no instalment
    plan to argue about.
"""
import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .audit import audit
from .models import StaffRequest, WorkerLeave

log = logging.getLogger(__name__)

DECIDE_ROLES = ("DIRECTOR", "ADMIN")        # the PD gate, on both kinds
LEAVE_DO_ROLES = ("HO_HR", "ADMIN", "PA")   # who grants it afterwards
PAY_DO_ROLES = ("FINANCE", "ADMIN")         # who raises the PYR
AUTHORISE_ROLES = ("SIGNATORY", "ADMIN")    # who authorises a loan

# A staff loan (owner 2026-11-01): asked with an amount, a purpose and how
# many months to repay it over; the Director approves an amount and a term
# (and the first payroll month it comes off), a Signatory authorises it, and
# that raises the payment request for Finance — the loan rides on it as a
# SalaryAdvance(kind=LOAN), which payroll already deducts month by month.
LOAN_MAX_MONTHS = 24


def _loan_check(emp, amount, months, show_pay=True):
    """Why a loan of `amount` over `months` can't be given, or None. The
    person asking sees their own pay in the message; the Director is not to
    see pay at all (owner 2026-08-16, permissions.PAY_ROLES), so is told only
    that it doesn't fit."""
    if amount is None or amount <= 0:
        return "Give the amount of the loan."
    if not months or months < 1 or months > LOAN_MAX_MONTHS:
        return f"Repay it over 1 to {LOAN_MAX_MONTHS} months."
    # each month's deduction must leave a salary to deduct it from
    basic = emp.basic_pay or Decimal("0")
    instalment = (amount / months).quantize(Decimal("0.01"))
    if basic and instalment > basic:
        pay = f" ({emp.currency} {basic:,.2f})" if show_pay else ""
        return (f"That is {emp.currency} {instalment:,.2f} a month — more than "
                f"the monthly pay{pay}. Spread it over more months.")
    return None


def _repaying(emp):
    """A loan still being deducted from this person's salary."""
    from .models import SalaryAdvance
    from .payroll import RECOVERABLE_ADVANCE_STATUSES
    today = _today()
    now = today.year * 12 + (today.month - 1)
    for a in SalaryAdvance.objects.filter(
            employee=emp, kind="LOAN",
            document__status__in=RECOVERABLE_ADVANCE_STATUSES
            + ("DIRECTOR_APPROVED", "PART_PAID")):
        if a.period_year * 12 + (a.period_month - 1) + max(a.months, 1) > now:
            return a
    return None


def _months_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _money(v):
    try:
        return Decimal(str(v)).quantize(Decimal("0.01"))
    except (TypeError, ValueError, ArithmeticError, InvalidOperation):
        return None


def next_month(today=None):
    today = today or _today()
    return (today.year + (1 if today.month == 12 else 0),
            1 if today.month == 12 else today.month + 1)


def is_staff(employee):
    """Staff, not labour. The leave system is theirs (owner 2026-08-30).

    Two ways to be staff, because the categories are site-shaped. A
    ManpowerCategory in the STAFF group covers the people on a site —
    engineers, foremen, supervisors — but there is no category for a
    Signatory, HR, Finance or Purchasing, and inventing one would be worse
    than the gap: those rows feed the DPR and TWS manpower pickers, so a
    "Finance" category would turn up in the daily report as somebody to
    allocate to a task.

    Head Office is the app's own marker for those people already — HO staff
    are the employees allocated to the head-office site — so being allocated
    there is the second way in. Seven of the first nine linked head-office
    logins had no usable category and would otherwise have been refused
    (found 2026-08-30, checking the real links)."""
    if employee.job_category_id and employee.job_category.grp == "STAFF":
        return True
    alloc = (employee.site_allocations.filter(to_date__isnull=True)
             .select_related("site").first())
    return bool(alloc and alloc.site.is_head_office)


def create(user, data):
    """Raise a request for yourself."""
    emp = getattr(user, "employee", None)
    if emp is None:
        return None, ("Your login isn't linked to an employee record yet. "
                      "Ask HR to link it.")
    if not emp.is_active:
        return None, "Your employee record is not active."

    kind = data.get("kind")
    if kind not in StaffRequest.Kind.values:
        return None, "Choose what you are asking for."
    reason = (data.get("reason") or "").strip()

    if kind == StaffRequest.Kind.ADVANCE:
        # Decimal, not float: this is money, and it is compared against a
        # salary and later recovered from one.
        try:
            amount = Decimal(str(data.get("amount") or "0")).quantize(
                Decimal("0.01"))
        except (TypeError, ValueError, ArithmeticError, InvalidOperation):
            return None, "The amount is not a number."
        if amount <= 0:
            return None, "Give the amount you are asking for."
        # An advance is recovered from the next salary run in one go, so
        # asking for more than a month's pay would leave nothing to live on.
        basic = emp.basic_pay or Decimal("0")
        if basic and amount > basic:
            return None, (f"An advance is recovered from your next salary in "
                          f"one go, so it can't be more than your monthly pay "
                          f"({emp.currency} {basic:,.2f}).")
        if not reason:
            return None, "Say what the advance is for."
        req = StaffRequest.objects.create(
            kind=kind, employee=emp, raised_by=user, amount=amount,
            reason=reason)
    elif kind == StaffRequest.Kind.LOAN:
        amount = _money(data.get("amount") or "0")
        months = _months_int(data.get("months"))
        if amount is None:
            return None, "The amount is not a number."
        err = _loan_check(emp, amount, months)
        if err:
            return None, err
        if not reason:
            return None, "Say what the loan is for."
        if StaffRequest.objects.filter(
                employee=emp, kind=kind,
                status__in=("SUBMITTED", "APPROVED")).exists():
            return None, "You already have a loan request waiting."
        if _repaying(emp):
            return None, ("You are still repaying a loan — ask again once it "
                          "is cleared.")
        req = StaffRequest.objects.create(
            kind=kind, employee=emp, raised_by=user, amount=amount,
            months=months, reason=reason)
    else:
        if not is_staff(emp):
            return None, ("Leave requests are for staff. Site workers' leave "
                          "is arranged through HR.")
        try:
            start = date.fromisoformat(str(data.get("from_date")))
            end = date.fromisoformat(str(data.get("to_date")))
        except (TypeError, ValueError):
            return None, "Give the dates you want to be away."
        if end < start:
            return None, "The end date is before the start date."
        if kind == StaffRequest.Kind.LEAVE_ANNUAL and start <= _today():
            return None, ("Annual leave is planned ahead — pick a start date "
                          "in the future, or ask for emergency leave.")
        clash = WorkerLeave.objects.filter(
            employee=emp, cancelled_at__isnull=True,
            from_date__lte=end, to_date__gte=start).first()
        if clash:
            return None, (f"You already have leave {clash.from_date} to "
                          f"{clash.to_date}.")
        pending = StaffRequest.objects.filter(
            employee=emp, status__in=("SUBMITTED", "APPROVED"),
            kind__in=StaffRequest.LEAVE_KINDS,
            from_date__lte=end, to_date__gte=start).first()
        if pending:
            return None, ("You already have a leave request covering those "
                          "days.")
        req = StaffRequest.objects.create(
            kind=kind, employee=emp, raised_by=user, from_date=start,
            to_date=end, reason=reason)

    audit("staff_request", req.id, "STAFF_REQUEST_RAISED", actor=user,
          detail={"kind": kind, "employee": emp.emp_no})
    _notify_decider(req)
    return req, None


def _today():
    return timezone.localdate()


def decide(req, actor, approve, note="", terms=None):
    """The Director's call on a request. A loan is approved WITH its terms:
    the amount and months the Director agrees to (the ask, unless changed)
    and the payroll month the first instalment comes off."""
    if actor.role not in DECIDE_ROLES:
        return "Only the Director decides these."
    if req.status != StaffRequest.Status.SUBMITTED:
        return "This request has already been decided."
    if not approve and not (note or "").strip():
        return "Give a reason when declining."
    fields = ["status", "decided_by", "decided_at", "decision_note"]
    if approve and req.kind == StaffRequest.Kind.LOAN:
        terms = terms or {}
        amount = _money(terms.get("approved_amount") or req.amount)
        months = _months_int(terms.get("approved_months") or req.months)
        if amount is None:
            return "The approved amount is not a number."
        from .permissions import sees_pay
        err = _loan_check(req.employee, amount, months,
                          show_pay=sees_pay(actor))
        if err:
            return err
        fy, fm = next_month()
        if terms.get("first_month"):
            try:
                fy, fm = (int(x) for x in
                          str(terms["first_month"])[:7].split("-"))
                date(fy, fm, 1)
            except (TypeError, ValueError):
                return "Give the first deduction month as YYYY-MM."
        today = _today()
        if fy * 12 + fm < today.year * 12 + today.month:
            return "The first deduction can't be in a month already gone."
        req.approved_amount, req.approved_months = amount, months
        req.first_year, req.first_month = fy, fm
        fields += ["approved_amount", "approved_months", "first_year",
                   "first_month"]
    req.status = (StaffRequest.Status.APPROVED if approve
                  else StaffRequest.Status.DECLINED)
    req.decided_by = actor
    req.decided_at = timezone.now()
    req.decision_note = (note or "").strip()
    req.save(update_fields=fields)
    audit("staff_request", req.id, "STAFF_REQUEST_DECIDED", actor=actor,
          detail={"approved": approve, "note": req.decision_note,
                  **({"amount": str(req.approved_amount),
                      "months": req.approved_months,
                      "first": f"{req.first_year}-{req.first_month:02d}"}
                     if approve and req.kind == StaffRequest.Kind.LOAN
                     else {})})
    _notify_raiser(req)
    if approve and req.kind == StaffRequest.Kind.LOAN:
        _notify_signatories(req)
    return None


def authorise_loan(req, actor, approve, note=""):
    """The Signatory authorises a loan the Director approved — or declines
    it, with the reason. Authorising raises the payment request: Head Office,
    Labour & Staff, the loan on it for the approved amount and months, and
    already approved, so it goes straight to Finance's voucher queue (the
    Director and the Signatory have both decided it)."""
    if actor.role not in AUTHORISE_ROLES:
        return None, "A Signatory authorises staff loans."
    if req.kind != StaffRequest.Kind.LOAN:
        return None, "That request is not for a loan."
    if req.status != StaffRequest.Status.APPROVED:
        return None, "The Director has not approved this loan."
    note = (note or "").strip()
    if not approve:
        if not note:
            return None, "Give a reason when declining."
        req.status = StaffRequest.Status.DECLINED
        req.authorised_by, req.authorised_at = actor, timezone.now()
        req.authorisation_note = note
        req.decision_note = note
        req.save(update_fields=["status", "authorised_by", "authorised_at",
                                "authorisation_note", "decision_note"])
        audit("staff_request", req.id, "STAFF_LOAN_DECLINED", actor=actor,
              detail={"note": note})
        _notify_raiser(req)
        return None, None
    with transaction.atomic():
        doc, err = _raise_loan_pyr(req, actor)
        if err:
            transaction.set_rollback(True)
            return None, err
        req.status = StaffRequest.Status.DONE
        req.authorised_by, req.authorised_at = actor, timezone.now()
        req.authorisation_note = note
        req.payment_request = doc
        req.done_by, req.done_at = actor, timezone.now()
        req.save(update_fields=["status", "authorised_by", "authorised_at",
                                "authorisation_note", "payment_request",
                                "done_by", "done_at"])
    audit("staff_request", req.id, "STAFF_LOAN_AUTHORISED", actor=actor,
          detail={"pyr": doc.ref, "amount": str(req.approved_amount),
                  "months": req.approved_months})
    _notify_raiser(req)
    _notify_finance(req)
    return doc, None


def _raise_loan_pyr(req, actor):
    """The payment request for an authorised loan."""
    from . import costing
    from .models import (Approval, Document, DocumentRevision, PaymentRequest,
                         Site)
    from .numbering import next_ref
    from .payments import create_payment_request
    site = Site.objects.filter(is_head_office=True).first()
    if site is None:
        return None, "No Head Office site is configured."
    head = costing.by_code(costing.LABOUR)
    emp = req.employee
    start = date(req.first_year, req.first_month, 1)
    purpose = (f"Staff loan — {emp.full_name} ({emp.emp_no}), repaid over "
               f"{req.approved_months} month"
               f"{'s' if req.approved_months != 1 else ''} from "
               f"{start:%b %Y}: {req.reason}")[:500]
    ref = next_ref("PYR", site)
    doc = Document.objects.create(
        doc_type="PYR", ref=ref, site=site, doc_date=_today(),
        status="DRAFT", created_by=actor)
    rev = DocumentRevision.objects.create(
        document=doc, rev_label="R0", created_by=actor,
        payload={"purpose": purpose, "payee": emp.full_name,
                 "kind": "staff_loan", "staff_request": req.id})
    doc.current_revision = rev
    doc.save(update_fields=["current_revision"])
    pr, err = create_payment_request(doc, {
        "cost_head_id": head.id if head else None,
        "salary_lines": [{"employee_id": emp.id, "kind": "LOAN",
                          "amount": str(req.approved_amount),
                          "months": req.approved_months}],
        "deduct_year": req.first_year, "deduct_month": req.first_month,
        "payee": emp.full_name, "purpose": purpose,
        "currency": (emp.currency or "MVR").upper(),
        "payment_method": "BANK"}, actor)
    if err:
        return None, err
    PaymentRequest.objects.filter(pk=pr.pk).update(origin="HR")
    # The Director decided it on the request, the Signatory authorised it:
    # it is cleared to Finance as any approved request is.
    doc.status = "DIRECTOR_APPROVED"
    doc.save(update_fields=["status", "updated_at"])
    for who, action, comment in (
            (req.raised_by, "SUBMIT", f"Staff loan request #{req.id}"),
            (req.decided_by, "DIRECTOR_APPROVE",
             req.decision_note or "Approved on the staff loan request"),
            (actor, "LOAN_AUTHORISE", req.authorisation_note
             or "Loan authorised by the Signatory")):
        Approval.objects.create(document=doc, revision=rev, action=action,
                                actor=who, actor_role=who.role,
                                comment=comment[:500])
    audit("document", doc.id, "DOC_CREATED", actor=actor,
          to_state="DIRECTOR_APPROVED",
          detail={"ref": ref, "kind": "staff_loan", "request": req.id})
    from .notify import notify_document
    notify_document(doc, actor)
    return doc, None


def cancel(req, actor):
    """Withdraw your own request, while it is still undecided."""
    if req.raised_by_id != actor.id and actor.role not in DECIDE_ROLES:
        return "You can only withdraw your own request."
    if req.status != StaffRequest.Status.SUBMITTED:
        return "Only a request still waiting for a decision can be withdrawn."
    req.status = StaffRequest.Status.CANCELLED
    req.save(update_fields=["status"])
    audit("staff_request", req.id, "STAFF_REQUEST_CANCELLED", actor=actor)
    return None


def grant_leave(req, actor, kind, note=""):
    """HR turns an approved leave request into actual leave.

    Paid or unpaid is HR's call at this point, not the requester's — it is
    the one decision that changes what payroll does, and the requester is not
    the person who should be making it."""
    from . import leave

    if actor.role not in LEAVE_DO_ROLES:
        return None, "Only HR grants leave."
    if not req.is_leave:
        return None, "That request is not for leave."
    if req.status != StaffRequest.Status.APPROVED:
        return None, "The Director has not approved this yet."

    lv, err = leave.grant({"employee_id": req.employee_id,
                           "from_date": req.from_date.isoformat(),
                           "to_date": req.to_date.isoformat(),
                           "kind": kind,
                           "reason": req.reason or note}, actor)
    if err:
        return None, err
    with transaction.atomic():
        req.worker_leave = lv
        req.status = StaffRequest.Status.DONE
        req.done_by = actor
        req.done_at = timezone.now()
        req.save(update_fields=["worker_leave", "status", "done_by",
                                "done_at"])
    audit("staff_request", req.id, "STAFF_REQUEST_LEAVE_GRANTED", actor=actor,
          detail={"leave": lv.id, "kind": kind})
    _notify_raiser(req)
    return lv, None


def link_payment(req, document, actor):
    """Record the PYR Finance raised against an approved advance.

    The PYR itself is created through the ordinary payment-request form, so
    the money path is the one already in use — this only ties the two
    together so the trail runs from the ask to the payment."""
    if actor.role not in PAY_DO_ROLES:
        return "Only Finance records the payment."
    if req.kind != StaffRequest.Kind.ADVANCE:
        return "That request is not for an advance."
    if req.status != StaffRequest.Status.APPROVED:
        return "The Director has not approved this yet."
    if document.doc_type != "PYR":
        return "That is not a payment request."
    req.payment_request = document
    req.status = StaffRequest.Status.DONE
    req.done_by = actor
    req.done_at = timezone.now()
    req.save(update_fields=["payment_request", "status", "done_by", "done_at"])
    audit("staff_request", req.id, "STAFF_REQUEST_PAID", actor=actor,
          detail={"pyr": document.ref})
    _notify_raiser(req)
    return None


def queue_for(user):
    """What this person has to act on."""
    qs = StaffRequest.objects.select_related(
        "employee", "raised_by", "decided_by", "payment_request")
    if user.role in DECIDE_ROLES and user.role != "ADMIN":
        return qs.filter(status=StaffRequest.Status.SUBMITTED)
    if user.role == "ADMIN":
        return qs.filter(status__in=(StaffRequest.Status.SUBMITTED,
                                     StaffRequest.Status.APPROVED))
    if user.role in AUTHORISE_ROLES:
        return qs.filter(status=StaffRequest.Status.APPROVED,
                         kind=StaffRequest.Kind.LOAN)
    if user.role in LEAVE_DO_ROLES:
        return qs.filter(status=StaffRequest.Status.APPROVED,
                         kind__in=StaffRequest.LEAVE_KINDS)
    if user.role in PAY_DO_ROLES:
        return qs.filter(status=StaffRequest.Status.APPROVED,
                         kind=StaffRequest.Kind.ADVANCE)
    return qs.none()


def _notify_decider(req):
    from .models import User
    from .notify import notify_user

    what = ("an advance" if req.kind == StaffRequest.Kind.ADVANCE
            else "a loan" if req.kind == StaffRequest.Kind.LOAN
            else "leave")
    for u in User.objects.filter(role="DIRECTOR", is_active=True):
        notify_user(u, f"{req.employee.full_name} has asked for {what}",
                    req.reason[:120], category="approval")


def _notify_signatories(req):
    from .models import User
    from .notify import notify_user
    for u in User.objects.filter(role="SIGNATORY", is_active=True):
        notify_user(u, f"Staff loan to authorise: {req.employee.full_name}",
                    f"{req.employee.currency} {req.approved_amount:,.2f} over "
                    f"{req.approved_months} months — approved by "
                    f"{req.decided_by.full_name}. My Tasks.",
                    category="approval")


def _notify_finance(req):
    from .models import User
    from .notify import notify_user
    for u in User.objects.filter(role="FINANCE", is_active=True):
        notify_user(u, f"Staff loan to pay: {req.employee.full_name}",
                    f"{req.payment_request.ref} · {req.employee.currency} "
                    f"{req.approved_amount:,.2f} — authorised, ready for a "
                    "voucher.")


def _notify_raiser(req):
    from .notify import notify_user

    notify_user(req.raised_by,
                f"Your request was {req.get_status_display().lower()}",
                req.decision_note[:120], category="alert")
