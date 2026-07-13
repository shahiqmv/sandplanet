"""Payment Voucher (M6d) — batch authorisation.

Finance batches Director-approved PRs and PYRs onto a voucher; a signatory
approves the voucher (or queries individual lines). Signatory approval is
the commitment point — it replaces the per-document authorise step. Queried
lines return to their raiser; approved lines commit their source
requisition and become payable.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import costing
from .audit import audit
from .models import (Approval, Document, DocumentRevision, PaymentVoucherLine,
                     Site)
from .numbering import next_ref

# What is ready to go on a voucher, per source type
AWAITING_STATUS = {"PR": "APPROVED", "PYR": "DIRECTOR_APPROVED",
                   "IPR": "APPROVED"}


def ho_site():
    """The Head Office record a voucher is filed under (it batches many
    sites)."""
    site = Site.objects.filter(is_head_office=True).first()
    if site:
        return site
    site, _ = Site.objects.get_or_create(
        code="MLE", defaults={"name": "Head Office, Male'",
                              "is_head_office": True,
                              "status": Site.Status.ACTIVE})
    return site


def _source_amount(doc):
    if doc.doc_type == "PYR":
        return doc.payment_request.amount_requested
    if doc.doc_type == "PR":
        from .procurement import pr_grand_total
        return pr_grand_total(doc)
    if doc.doc_type == "IPR":
        from .imports import ipr_mvr_total
        return ipr_mvr_total(doc.import_order)
    return Decimal("0")


def _on_live_voucher():
    """Source docs sitting on a voucher that is still being processed
    (DRAFT or SUBMITTED). Approved/cancelled vouchers are historical, and a
    withdrawn authorisation frees the source to be vouchered again — the
    source's own status is what gates re-eligibility."""
    return PaymentVoucherLine.objects.filter(
        voucher__status__in=("DRAFT", "SUBMITTED")).values_list(
        "source_document_id", flat=True)


def awaiting_voucher():
    """Director-approved PR / PYR not already on a live voucher."""
    docs = Document.objects.filter(is_void=False).exclude(
        id__in=_on_live_voucher())
    out = []
    for doc in docs.filter(doc_type="PR", status="APPROVED") \
            .select_related("site"):
        out.append(doc)
    for doc in docs.filter(doc_type="PYR", status="DIRECTOR_APPROVED") \
            .select_related("site"):
        out.append(doc)
    for doc in docs.filter(doc_type="IPR", status="APPROVED") \
            .select_related("site"):
        out.append(doc)
    return out


def create_voucher(source_refs, actor):
    """Finance creates a draft voucher from chosen requisitions."""
    if not source_refs:
        return None, "Select at least one requisition."
    sources = list(Document.objects.filter(ref__in=source_refs,
                                           is_void=False))
    if len(sources) != len(set(source_refs)):
        return None, "One or more references are unknown."
    for doc in sources:
        want = AWAITING_STATUS.get(doc.doc_type)
        if want is None or doc.status != want:
            return None, (f"{doc.ref} is not a Director-approved PR/PYR "
                          "awaiting authorisation.")
        if PaymentVoucherLine.objects.filter(
                source_document=doc,
                voucher__status__in=("DRAFT", "SUBMITTED")).exists():
            return None, f"{doc.ref} is already on a voucher."
    with transaction.atomic():
        ref = next_ref("PV", None)
        pv = Document.objects.create(
            doc_type="PV", ref=ref, site=ho_site(),
            doc_date=timezone.now().date(), status="DRAFT", created_by=actor)
        revision = DocumentRevision.objects.create(
            document=pv, rev_label="R0", payload={}, created_by=actor)
        pv.current_revision = revision
        pv.save(update_fields=["current_revision"])
        for doc in sources:
            PaymentVoucherLine.objects.create(
                voucher=pv, source_document=doc, amount=_source_amount(doc))
    audit("document", pv.id, "PV_CREATED", actor=actor, to_state="DRAFT",
          detail={"ref": ref, "lines": len(sources)})
    return pv, None


def submit_voucher(pv, actor):
    if pv.status != "DRAFT":
        return "Only a draft voucher can be submitted."
    if not pv.voucher_lines.filter(status="INCLUDED").exists():
        return "The voucher has no requisitions."
    pv.status = "SUBMITTED"
    pv.save(update_fields=["status", "updated_at"])
    Approval.objects.create(document=pv, revision=pv.current_revision,
                            action="SUBMIT", actor=actor,
                            actor_role=actor.role)
    audit("document", pv.id, "PV_SUBMITTED", actor=actor,
          from_state="DRAFT", to_state="SUBMITTED", detail={"ref": pv.ref})
    from .notify import notify_document
    notify_document(pv, actor)  # a signatory must approve the voucher
    return None


def authorise_source(doc, actor):
    """Commit a requisition when its voucher line is approved — the logic
    that used to live in the per-document authorise action (§6C.2)."""
    if doc.doc_type == "PR":
        from .procurement import advance_pr_settlement, authorise_pr

        doc.status = "AUTHORISED"
        doc.save(update_fields=["status", "updated_at"])
        authorise_pr(doc, actor)  # COMMITTED + payables + credit POs
        # rows already settled by a PO advance the PR (R3 addendum) — a
        # cash vendor with no slip keeps it in PAYMENT_PROCESSING
        advance_pr_settlement(doc, actor)
    elif doc.doc_type == "PYR":
        pr = doc.payment_request
        pr.authorised_by = actor
        pr.authorised_at = timezone.now()
        pr.save(update_fields=["authorised_by", "authorised_at"])
        costing.post(site=doc.site, cost_head=pr.cost_head, state="COMMITTED",
                     source="PYR", amount=pr.amount_requested,
                     currency=pr.currency, document=doc, actor=actor)
        doc.status = "AUTHORISED"
        doc.save(update_fields=["status", "updated_at"])
    elif doc.doc_type == "IPR":
        from .imports import authorise_ipr

        authorise_ipr(doc, actor)  # COMMITTED split projects + General Stock
        doc.status = "AUTHORISED"
        doc.save(update_fields=["status", "updated_at"])
    Approval.objects.create(document=doc, revision=doc.current_revision,
                            action="AUTHORISE", actor=actor,
                            actor_role=actor.role,
                            comment="Authorised on voucher")
    audit("document", doc.id, "AUTHORISE", actor=actor,
          to_state="AUTHORISED", detail={"ref": doc.ref})
    from .notify import notify_document
    notify_document(doc, actor)  # an authorised PYR is Finance's to pay


def _return_source(doc, actor, note):
    """A queried line's requisition goes back to its raiser as a draft."""
    if doc.doc_type == "PYR":
        pr = doc.payment_request
        pr.returned_reason = "SIGNATORY_DECLINED"
        pr.returned_note = note
        pr.returned_by = actor
        pr.returned_at = timezone.now()
        pr.save(update_fields=["returned_reason", "returned_note",
                               "returned_by", "returned_at"])
    doc.status = "DRAFT"
    doc.save(update_fields=["status", "updated_at"])
    Approval.objects.create(document=doc, revision=doc.current_revision,
                            action="RETURN", actor=actor,
                            actor_role=actor.role,
                            comment=f"Queried on voucher: {note}")
    audit("document", doc.id, "RETURN", actor=actor, to_state="DRAFT",
          detail={"ref": doc.ref, "note": note})


def approve_voucher(pv, actor, queried_ids=None, note=""):
    """Signatory approves the voucher. Queried lines return to their
    raiser; the rest commit their source requisition."""
    if pv.status != "SUBMITTED":
        return "Only a submitted voucher can be approved."
    queried_ids = set(queried_ids or [])
    with transaction.atomic():
        for line in pv.voucher_lines.filter(status="INCLUDED") \
                .select_related("source_document"):
            if line.id in queried_ids:
                line.status = "QUERIED"
                line.query_note = note
                line.save(update_fields=["status", "query_note"])
                _return_source(line.source_document, actor, note or "queried")
            else:
                line.status = "APPROVED"
                line.save(update_fields=["status"])
                authorise_source(line.source_document, actor)
        pv.status = "APPROVED"
        pv.save(update_fields=["status", "updated_at"])
        Approval.objects.create(document=pv, revision=pv.current_revision,
                                action="APPROVE", actor=actor,
                                actor_role=actor.role, comment=note)
    audit("document", pv.id, "PV_APPROVED", actor=actor,
          from_state="SUBMITTED", to_state="APPROVED",
          detail={"ref": pv.ref, "queried": len(queried_ids)})
    return None
