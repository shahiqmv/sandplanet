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


def decide(req, actor, approve, note=""):
    """The Director's call on a request."""
    if actor.role not in DECIDE_ROLES:
        return "Only the Director decides these."
    if req.status != StaffRequest.Status.SUBMITTED:
        return "This request has already been decided."
    if not approve and not (note or "").strip():
        return "Give a reason when declining."
    req.status = (StaffRequest.Status.APPROVED if approve
                  else StaffRequest.Status.DECLINED)
    req.decided_by = actor
    req.decided_at = timezone.now()
    req.decision_note = (note or "").strip()
    req.save(update_fields=["status", "decided_by", "decided_at",
                            "decision_note"])
    audit("staff_request", req.id, "STAFF_REQUEST_DECIDED", actor=actor,
          detail={"approved": approve, "note": req.decision_note})
    _notify_raiser(req)
    return None


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
    if user.role in DECIDE_ROLES:
        return qs.filter(status=StaffRequest.Status.SUBMITTED)
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
            else "leave")
    for u in User.objects.filter(role="DIRECTOR", is_active=True):
        notify_user(u, f"{req.employee.full_name} has asked for {what}",
                    req.reason[:120], category="approval")


def _notify_raiser(req):
    from .notify import notify_user

    notify_user(req.raised_by,
                f"Your request was {req.get_status_display().lower()}",
                req.decision_note[:120], category="alert")
