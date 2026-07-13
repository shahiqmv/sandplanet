"""PYR (Payment Request) service + workflow (§5.9, §7.1, §7.5).

Chain: Draft → Submitted → PM Approved → Director Approved → Signatory
Authorised → Paid. Commitment posts at authorisation; a return before
authorisation posts nothing; a Finance withdrawal after authorisation
posts reversals. All cost postings go through core.costing.
"""
from datetime import date
from decimal import Decimal

from django.utils import timezone
from rest_framework.response import Response

from . import costing
from .audit import audit
from .models import Approval, CostHead, Document, PaymentRequest

SITE_RAISERS = {"SITE_ADMIN", "SITE_ENGINEER", "PM"}
CENTRAL_RAISERS = {"HO_PURCHASING", "HO_HR", "DIRECTOR", "SIGNATORY", "QS"}
FINANCE_RAISERS = {"FINANCE"}
RAISER_ROLES = SITE_RAISERS | CENTRAL_RAISERS | FINANCE_RAISERS | {"ADMIN"}
# Only Head-Office centres may raise a foreign-currency request; site teams
# request in MVR only (owner 2026-07-13).
USD_RAISERS = CENTRAL_RAISERS | FINANCE_RAISERS | {"ADMIN"}
RETURN_REASONS = {"SIGNATORY_DECLINED", "INCORRECT_DETAILS",
                  "MISSING_DOCUMENT", "DUPLICATE", "ON_HOLD", "OTHER"}


def origin_for(role):
    """The approval chain a raiser's role puts a PYR on."""
    if role in FINANCE_RAISERS:
        return "FINANCE"
    if role in SITE_RAISERS:
        return "SITE"
    return "CENTRAL"      # HO Purchasing / HR / Director / Signatory / QS / Admin


def _param(key, default):
    from .models import CompanyParameter

    try:
        return CompanyParameter.objects.get(key=key).value
    except CompanyParameter.DoesNotExist:
        return default


def pyr_doc_threshold():
    """Above this a PYR needs an attachment or a PM override (§5.9).
    Default MVR 5,000."""
    return Decimal(str(_param("pyr_doc_threshold", 5000)))


def create_payment_request(doc, data, user):
    """Create the typed PaymentRequest row alongside the PYR document
    (called from document_create). Validation of the supporting-document
    rule happens at submit, not here."""
    try:
        cost_head = CostHead.objects.get(pk=data.get("cost_head_id"),
                                         is_active=True)
    except CostHead.DoesNotExist:
        return None, "A valid cost head is required."
    if cost_head.is_pool:
        return None, "That cost head is a Head Office pool, not a project head."
    # Salary advance/loan: a worker breakdown drives the amount and payee
    salary_lines = data.get("salary_lines") or []
    # Work-permit renewal: a per-worker fee breakdown drives the amount
    permit_lines = data.get("permit_lines") or []
    payee = (data.get("payee") or "").strip()
    purpose = (data.get("purpose") or "").strip()
    if salary_lines:
        parsed, err = _parse_salary_lines(salary_lines)
        if err:
            return None, err
        amount = sum((ln["amount"] for ln in parsed), Decimal("0"))
        payee = payee or f"Salary advances — {doc.site.code}"
        purpose = purpose or "Staff salary advance / loan"
    elif permit_lines:
        parsed_permits, err = _parse_permit_lines(permit_lines)
        if err:
            return None, err
        amount = sum((ln["fee"] for ln in parsed_permits), Decimal("0"))
        payee = payee or "Work-permit renewals"
        purpose = purpose or "Work-permit renewals"
    else:
        try:
            amount = Decimal(str(data.get("amount_requested") or 0))
        except (TypeError, ValueError):
            return None, "Amount is invalid."
    if amount <= 0:
        return None, "Amount must be greater than zero."
    if not payee:
        return None, "Payee is required."
    if not purpose:
        return None, "Purpose is required."
    # Currency: MVR always allowed; USD only for Head-Office centres.
    currency = (data.get("currency") or "MVR").upper()[:3]
    if currency not in ("MVR", "USD"):
        return None, "Currency must be MVR or USD."
    if currency != "MVR" and user.role not in USD_RAISERS:
        return None, "Site payment requests are in MVR only."
    origin = origin_for(user.role)
    pr = PaymentRequest.objects.create(
        document=doc,
        payment_type="ADVANCE" if salary_lines
        else "PERMIT_RENEWAL" if permit_lines
        else data.get("payment_type", "DIRECT"),
        cost_head=cost_head,
        payee=payee,
        payment_method=data.get("payment_method", "BANK"),
        payee_account=data.get("payee_account", ""),
        currency=currency,
        origin=origin,
        amount_requested=amount,
        required_by=data.get("required_by") or None,
        purpose=purpose,
        is_urgent=bool(data.get("is_urgent")),
        urgent_reason=data.get("urgent_reason", ""),
        has_supporting_doc=bool(data.get("has_supporting_doc")),
        no_doc_reason=data.get("no_doc_reason", ""),
    )
    if salary_lines:
        _create_salary_advances(doc, parsed, data)
    if permit_lines:
        _create_permit_renewals(doc, parsed_permits, user)
    return pr, None


def _parse_salary_lines(raw):
    """Validate advance/loan lines: {employee_id, kind, amount, months}."""
    from .models import Employee

    out = []
    for ln in raw:
        try:
            emp = Employee.objects.get(pk=ln.get("employee_id"))
        except Employee.DoesNotExist:
            return None, "Unknown employee in a salary-advance line."
        try:
            amt = Decimal(str(ln.get("amount") or 0))
        except (TypeError, ValueError):
            return None, "A salary-advance amount is invalid."
        if amt <= 0:
            return None, "Salary-advance amounts must be positive."
        kind = "LOAN" if ln.get("kind") == "LOAN" else "ADVANCE"
        months = int(ln.get("months") or 1) if kind == "LOAN" else 1
        if months < 1:
            months = 1
        out.append({"employee": emp, "amount": amt, "kind": kind,
                    "months": months})
    if not out:
        return None, "Add at least one worker."
    return out, None


def _parse_permit_lines(raw):
    """Validate permit-renewal lines: {employee_id, months, fee}."""
    from .models import Employee

    out = []
    for ln in raw:
        try:
            emp = Employee.objects.get(pk=ln.get("employee_id"))
        except Employee.DoesNotExist:
            return None, "Unknown employee in a permit-renewal line."
        try:
            months = int(ln.get("months") or 0)
        except (TypeError, ValueError):
            return None, "Renewal months must be a whole number."
        if months < 1:
            return None, "Renewal months must be at least 1."
        try:
            fee = Decimal(str(ln.get("fee") or 0))
        except (TypeError, ValueError):
            return None, "A renewal fee is invalid."
        if fee < 0:
            return None, "Renewal fees cannot be negative."
        out.append({"employee": emp, "months": months, "fee": fee})
    if not out:
        return None, "Select at least one worker to renew."
    return out, None


def _create_permit_renewals(doc, parsed, user):
    """Record each renewal as PENDING against this PYR — the expiries move
    forward only when Finance pays it (see permits.apply_for_document)."""
    from . import permits

    for ln in parsed:
        permits.schedule(ln["employee"], ln["months"], ln["fee"],
                         f"Batch renewal {doc.ref}", user, document=doc)


def _create_salary_advances(doc, parsed, data):
    from datetime import date

    from .models import SalaryAdvance

    # First deduction period: caller may name it; else the month after the PYR
    y = data.get("deduct_year")
    m = data.get("deduct_month")
    if not (y and m):
        base = doc.doc_date or date.today()
        m = base.month + 1
        y = base.year + (1 if m > 12 else 0)
        m = 1 if m > 12 else m
    for ln in parsed:
        SalaryAdvance.objects.create(
            document=doc, employee=ln["employee"], kind=ln["kind"],
            amount=ln["amount"], months=ln["months"],
            period_year=int(y), period_month=int(m))


def _transition(doc, new_status):
    return new_status in Document.TRANSITIONS["PYR"].get(doc.status, set())

  # noqa: E305


def _record(doc, action, user, comment="", result=""):
    Approval.objects.create(
        document=doc, revision=doc.current_revision, action=action,
        result=result, actor=user, actor_role=user.role, comment=comment)


def _set_status(doc, new_status, action, user, comment=""):
    old = doc.status
    doc.status = new_status
    doc.save(update_fields=["status", "updated_at"])
    _record(doc, action, user, comment=comment)
    audit("document", doc.id, f"PYR_{action}", actor=user,
          from_state=old, to_state=new_status, detail={"ref": doc.ref})
    from .notify import notify_document
    notify_document(doc, user)  # alert whoever it now blocks


def _is_pm_for(user, doc):
    if user.role == "ADMIN":
        return True
    if user.role != "PM":
        return False
    pm = doc.site.current_pm()
    return pm is not None and pm.id == user.id


# ---- Actions --------------------------------------------------------------

def pyr_action(request, doc, action_name):
    """PYR-specific action dispatcher, called from document_action for PYR
    documents. Returns a Response (error or serialized doc handled by the
    caller); returning None means success."""
    pr = doc.payment_request
    user = request.user
    data = request.data
    comment = data.get("comment", "")

    if action_name == "submit":
        if user.role not in RAISER_ROLES:
            return Response({"detail": "Only the site team raises a PYR."},
                            status=403)
        if not _transition(doc, "SUBMITTED"):
            return Response({"detail": f"Cannot submit from {doc.status}."},
                            status=400)
        # Supporting-document control (§5.9)
        has_doc = pr.has_supporting_doc or doc.attachments.filter(
            kind__in=("EVIDENCE", "QUOTATION", "ENCLOSURE")).exists()
        if not has_doc and not pr.no_doc_reason.strip():
            return Response({"detail": "Attach a bill/quotation, or give a "
                                       "reason for no supporting document."},
                            status=400)
        if (pr.amount_requested >= pyr_doc_threshold() and not has_doc
                and not pr.override_by_id):
            return Response({
                "detail": f"Above MVR {pyr_doc_threshold():,.0f} a PYR needs "
                          "a supporting document or a PM override with reason.",
                "needs_override": True}, status=400)
        _set_status(doc, "SUBMITTED", "SUBMIT", user, comment)
        if pr.origin == "FINANCE":
            # Accounts-initiated (rent, salaries, utilities…): no Director step
            # — cleared straight to a Payment Voucher for signatory approval.
            _set_status(doc, "DIRECTOR_APPROVED", "CLEAR_TO_VOUCHER", user,
                        "Accounts-initiated — authorised on a Payment Voucher")
        return None

    if action_name == "approve":
        if doc.status == "SUBMITTED":
            if pr.origin == "SITE":
                if not _is_pm_for(user, doc):
                    return Response({"detail": "The site PM approves first."},
                                    status=403)
                _set_status(doc, "PM_APPROVED", "PM_APPROVE", user, comment)
                return None
            # CENTRAL (HO Purchasing / HR): the Director approves directly —
            # there is no site PM in the chain.
            if user.role not in ("DIRECTOR", "ADMIN"):
                return Response({"detail": "Director approval required."},
                                status=403)
            if doc.created_by_id == user.id and user.role != "ADMIN":
                return Response({"detail": "You cannot approve your own "
                                           "request."}, status=403)
            _set_status(doc, "DIRECTOR_APPROVED", "DIRECTOR_APPROVE", user,
                        comment)
            return None
        if doc.status == "PM_APPROVED":
            if user.role not in ("DIRECTOR", "ADMIN"):
                return Response({"detail": "Director approval required."},
                                status=403)
            _set_status(doc, "DIRECTOR_APPROVED", "DIRECTOR_APPROVE", user,
                        comment)
            return None
        return Response({"detail": f"Cannot approve from {doc.status}."},
                        status=400)

    if action_name == "authorise":
        # Authorisation now happens ONLY on a Payment Voucher (M6d) — a
        # signatory approves a batch, not each PYR individually.
        return Response({"detail": "Payment requests are authorised on a "
                                   "Payment Voucher (Finance builds it, a "
                                   "signatory approves it)."}, status=400)

    if action_name == "pay":
        if doc.status != "AUTHORISED":
            return Response({"detail": f"Cannot pay from {doc.status}."},
                            status=400)
        if user.role not in ("FINANCE", "ADMIN"):
            return Response({"detail": "Finance executes payment."},
                            status=403)
        try:
            amount_paid = Decimal(str(data.get("amount_paid",
                                                pr.amount_requested)))
        except (TypeError, ValueError):
            return Response({"detail": "Amount paid is invalid."}, status=400)
        variance = data.get("variance_reason", "")
        if amount_paid != pr.amount_requested and not variance.strip():
            return Response({"detail": "A variance reason is required when "
                                       "the paid amount differs."}, status=400)
        # A USD request posts to the (MVR) cost ledger converted at the rate
        # applied when paying — entered, else the company MVR-per-USD rate.
        if pr.currency == "USD":
            from . import fx
            try:
                rate = Decimal(str(data.get("fx_rate") or fx.usd_rate()))
            except (TypeError, ValueError):
                return Response({"detail": "The MVR/USD rate is invalid."},
                                status=400)
            if rate <= 0:
                return Response({"detail": "Enter the MVR/USD rate applied."},
                                status=400)
            pr.fx_rate = rate
            ledger_amount = (amount_paid * rate).quantize(Decimal("0.01"))
        else:
            ledger_amount = amount_paid
        pr.amount_paid = amount_paid
        pr.paid_date = data.get("paid_date") or date.today()
        pr.payment_ref = data.get("payment_ref", "")
        pr.payment_method = data.get("payment_method", pr.payment_method)
        pr.variance_reason = variance
        pr.paid_by = user
        pr.save(update_fields=["amount_paid", "fx_rate", "paid_date",
                               "payment_ref", "payment_method",
                               "variance_reason", "paid_by"])
        # Finance attaches the transfer slip / cheque copy (owner request)
        slip = getattr(request, "FILES", {}).get("file")
        if slip is not None:
            from .models import Attachment

            Attachment.objects.create(
                document=doc, revision=doc.current_revision,
                kind="PAYMENT_SLIP", file=slip, file_name=slip.name,
                content_type=slip.content_type or "", size_bytes=slip.size,
                caption=pr.payment_ref or "payment slip", uploaded_by=user)
        if pr.payment_type == "PETTY_CASH_REPLENISH":
            # The Paid leg is posted per expense (under each entry's cost
            # head) and the float restored — never double-counting the
            # already-Incurred expenses (§6B.3.4, §6C.3.3)
            from . import petty_cash

            petty_cash.on_replenish_paid(doc, user)
        elif doc.salary_advances.exists():
            # A salary advance/loan is a prepayment recouped from payroll — the
            # labour expense is recognised in the payroll month-lock, so this
            # PYR posts nothing to the cost ledger to avoid double counting.
            pass
        else:
            costing.post(site=doc.site, cost_head=pr.cost_head, state="PAID",
                         source="PYR", amount=ledger_amount,
                         currency="MVR", document=doc, actor=user,
                         posted_on=pr.paid_date)
            costing.post(site=doc.site, cost_head=pr.cost_head,
                         state="INCURRED", source="PYR", amount=ledger_amount,
                         currency="MVR", document=doc, actor=user,
                         posted_on=pr.paid_date)
        # Work-permit renewals extend the expiries only now, on payment
        if pr.payment_type == "PERMIT_RENEWAL":
            from . import permits

            permits.apply_for_document(doc, user)
        _set_status(doc, "PAID", "PAY", user, comment)
        return None

    if action_name == "return":
        if doc.status not in ("SUBMITTED", "PM_APPROVED", "DIRECTOR_APPROVED"):
            return Response({"detail": f"Cannot return from {doc.status}."},
                            status=400)
        reason = data.get("reason_category", "")
        note = data.get("note", "") or comment
        if reason not in RETURN_REASONS or not note.strip():
            return Response({"detail": "A reason category and a note to the "
                                       "raiser are required."}, status=400)
        # Only the approver at (or above) the current stage may return
        if not _may_act_at_stage(user, doc):
            return Response({"detail": "You are not an approver for this "
                                       "PYR at its current stage."},
                            status=403)
        pr.returned_reason = reason
        pr.returned_note = note
        pr.returned_by = user
        pr.returned_at = timezone.now()
        pr.save(update_fields=["returned_reason", "returned_note",
                               "returned_by", "returned_at"])
        # No cost reversal — nothing was committed before authorisation
        _set_status(doc, "DRAFT", "RETURN", user, f"[{reason}] {note}")
        return None

    if action_name == "withdraw-authorisation":
        if doc.status != "AUTHORISED":
            return Response({"detail": "Only an authorised, unpaid PYR can "
                                       "have its authorisation withdrawn."},
                            status=400)
        if user.role not in ("FINANCE", "ADMIN"):
            return Response({"detail": "Finance withdraws authorisation."},
                            status=403)
        note = data.get("note", "") or comment
        if not note.strip():
            return Response({"detail": "A reason note is required."},
                            status=400)
        pr.withdrawn_by = user
        pr.withdrawn_at = timezone.now()
        pr.withdrawn_reason = note
        pr.save(update_fields=["withdrawn_by", "withdrawn_at",
                               "withdrawn_reason"])
        costing.reverse_document(doc, actor=user)  # reverse the COMMITTED row
        _set_status(doc, "DRAFT", "WITHDRAW_AUTHORISATION", user, note)
        return None

    if action_name == "reject":
        if doc.status not in ("SUBMITTED", "PM_APPROVED", "DIRECTOR_APPROVED"):
            return Response({"detail": f"Cannot reject from {doc.status}."},
                            status=400)
        if not _may_act_at_stage(user, doc):
            return Response({"detail": "Not an approver for this PYR."},
                            status=403)
        _set_status(doc, "REJECTED", "REJECT", user, comment)
        return None

    if action_name == "cancel":
        if doc.status != "DRAFT":
            return Response({"detail": "Only a draft PYR can be cancelled."},
                            status=400)
        if doc.created_by_id != user.id and user.role != "ADMIN":
            return Response({"detail": "Only the raiser cancels a draft."},
                            status=403)
        _set_status(doc, "CANCELLED", "CANCEL", user, comment)
        return None

    return Response({"detail": f"Unknown PYR action '{action_name}'."},
                    status=400)


def _may_act_at_stage(user, doc):
    """Whether the user is an approver for the PYR's current stage (used by
    return/reject, which any current-or-later approver may do)."""
    if user.role == "ADMIN":
        return True
    if doc.status == "SUBMITTED":
        return _is_pm_for(user, doc) or user.role in ("DIRECTOR", "SIGNATORY",
                                                      "FINANCE")
    if doc.status == "PM_APPROVED":
        return user.role in ("DIRECTOR", "SIGNATORY", "FINANCE")
    if doc.status == "DIRECTOR_APPROVED":
        return user.role in ("SIGNATORY", "FINANCE")
    return False
