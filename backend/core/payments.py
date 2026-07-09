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
from .models import Approval, CostHead, Document, PaymentRequest, User

RAISER_ROLES = {"SITE_ADMIN", "SITE_ENGINEER", "PM", "ADMIN"}
RETURN_REASONS = {"SIGNATORY_DECLINED", "INCORRECT_DETAILS",
                  "MISSING_DOCUMENT", "DUPLICATE", "ON_HOLD", "OTHER"}


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
    try:
        amount = Decimal(str(data.get("amount_requested") or 0))
    except (TypeError, ValueError):
        return None, "Amount is invalid."
    if amount <= 0:
        return None, "Amount must be greater than zero."
    if not (data.get("payee") or "").strip():
        return None, "Payee is required."
    if not (data.get("purpose") or "").strip():
        return None, "Purpose is required."
    pr = PaymentRequest.objects.create(
        document=doc,
        payment_type=data.get("payment_type", "DIRECT"),
        cost_head=cost_head,
        payee=data.get("payee", "").strip(),
        payment_method=data.get("payment_method", "BANK"),
        payee_account=data.get("payee_account", ""),
        currency=data.get("currency", "MVR"),
        amount_requested=amount,
        required_by=data.get("required_by") or None,
        purpose=data.get("purpose", "").strip(),
        is_urgent=bool(data.get("is_urgent")),
        urgent_reason=data.get("urgent_reason", ""),
        has_supporting_doc=bool(data.get("has_supporting_doc")),
        no_doc_reason=data.get("no_doc_reason", ""),
    )
    return pr, None


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
        return None

    if action_name == "approve":
        if doc.status == "SUBMITTED":
            if not _is_pm_for(user, doc):
                return Response({"detail": "The site PM approves first."},
                                status=403)
            _set_status(doc, "PM_APPROVED", "PM_APPROVE", user, comment)
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
        if doc.status != "DIRECTOR_APPROVED":
            return Response({"detail": f"Cannot authorise from {doc.status}."},
                            status=400)
        if not costing.can_authorise(user, pr.amount_requested):
            return Response({
                "detail": "Above the signatory threshold, only a signatory "
                          "(executive director) may authorise — Finance "
                          "verifies and disburses."}, status=403)
        pr.authorised_by = user
        pr.authorised_at = timezone.now()
        pr.authorise_note = comment
        pr.authorised_under_threshold = (user.role == "FINANCE")
        pr.save(update_fields=["authorised_by", "authorised_at",
                               "authorise_note", "authorised_under_threshold"])
        # Commitment posts here — the single commitment point (§6C.2)
        costing.post(site=doc.site, cost_head=pr.cost_head, state="COMMITTED",
                     source="PYR", amount=pr.amount_requested,
                     currency=pr.currency, document=doc, actor=user)
        _set_status(doc, "AUTHORISED", "AUTHORISE", user, comment)
        return None

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
        pr.amount_paid = amount_paid
        pr.paid_date = data.get("paid_date") or date.today()
        pr.payment_ref = data.get("payment_ref", "")
        pr.payment_method = data.get("payment_method", pr.payment_method)
        pr.variance_reason = variance
        pr.paid_by = user
        pr.save(update_fields=["amount_paid", "paid_date", "payment_ref",
                               "payment_method", "variance_reason", "paid_by"])
        # Finance attaches the transfer slip / cheque copy (owner request)
        slip = getattr(request, "FILES", {}).get("file")
        if slip is not None:
            from .models import Attachment

            Attachment.objects.create(
                document=doc, revision=doc.current_revision,
                kind="PAYMENT_SLIP", file=slip, file_name=slip.name,
                content_type=slip.content_type or "", size_bytes=slip.size,
                caption=pr.payment_ref or "payment slip", uploaded_by=user)
        # Petty-cash replenishment posts PAID only — its expenses were
        # already INCURRED when approved, so never double-count (§4A)
        costing.post(site=doc.site, cost_head=pr.cost_head, state="PAID",
                     source="PYR", amount=amount_paid, currency=pr.currency,
                     document=doc, actor=user, posted_on=pr.paid_date)
        if pr.payment_type != "PETTY_CASH_REPLENISH":
            costing.post(site=doc.site, cost_head=pr.cost_head,
                         state="INCURRED", source="PYR", amount=amount_paid,
                         currency=pr.currency, document=doc, actor=user,
                         posted_on=pr.paid_date)
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
