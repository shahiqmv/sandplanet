"""Site-to-site transfer of materials and tools (MTN).

Sites had no way to hand anything to each other. Stock could only arrive from
a GRN or the Head Office store, and a tool belonged to whichever site first
recorded it — so when a project was split onto its own site there was no
honest way to move its材 materials across (owner 2026-08-16).

The lifecycle has two halves on purpose:

    raise  →  the sending site's PM approves  →  DESPATCH (stock leaves)
                                              →  the far site counts it in

Between despatch and receipt the stock is on neither ledger, which is the
truthful position for something on a boat. The far site enters what it
actually counted; a shortfall is recorded against the transfer and left
visible rather than written off by either side.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .audit import audit
from .models import (Document, DocumentRevision, Item, SiteTransfer,
                     SiteTransferLine, StockMovement, ToolAsset)
from .numbering import next_ref
from .stock import balance

ZERO = Decimal("0")
RAISE_ROLES = ("SITE_ADMIN", "SITE_ENGINEER", "PM", "ADMIN")
RECEIVE_ROLES = ("SITE_ADMIN", "SITE_ENGINEER", "PM", "ADMIN")


def _dec(v):
    return v if isinstance(v, Decimal) else Decimal(str(v or 0))


def create_transfer(from_site, to_site, lines, actor, reason="",
                    to_project=None):
    """Raise a draft MTN. `lines` are {item_id, qty} and/or {tool_id}."""
    if from_site.id == to_site.id:
        return None, "A transfer needs two different sites."
    if not lines:
        return None, "Add at least one material or tool to transfer."

    parsed = []
    for row in lines:
        if row.get("tool_id"):
            tool = ToolAsset.objects.filter(pk=row["tool_id"],
                                            site=from_site).first()
            if tool is None:
                return None, "That tool is not at this site."
            if tool.state == ToolAsset.State.RETIRED:
                return None, f"{tool.name} is retired — it cannot be sent."
            parsed.append({"tool": tool, "item": None, "qty": Decimal("1")})
            continue
        item = Item.objects.filter(pk=row.get("item_id")).first()
        if item is None:
            return None, "Unknown item on one of the lines."
        qty = _dec(row.get("qty"))
        if qty <= 0:
            return None, f"Enter a quantity for {item.description}."
        on_hand = balance(from_site, item)
        if qty > on_hand:
            return None, (f"{item.description}: only {on_hand:g} {item.unit or ''} "
                          f"on hand at {from_site.code}.")
        parsed.append({"tool": None, "item": item, "qty": qty})

    with transaction.atomic():
        ref = next_ref("MTN", from_site)
        doc = Document.objects.create(
            doc_type="MTN", ref=ref, site=from_site,
            doc_date=timezone.localdate(), status="DRAFT", created_by=actor)
        rev = DocumentRevision.objects.create(
            document=doc, rev_label="R0", created_by=actor,
            payload={"kind": "site_transfer", "to_site": to_site.code,
                     "reason": reason})
        doc.current_revision = rev
        doc.save(update_fields=["current_revision"])
        tr = SiteTransfer.objects.create(document=doc, to_site=to_site,
                                         to_project=to_project, reason=reason)
        for p in parsed:
            SiteTransferLine.objects.create(transfer=tr, item=p["item"],
                                            tool=p["tool"], qty=p["qty"])
    audit("document", doc.id, "MTN_RAISED", actor=actor,
          detail={"ref": doc.ref, "from": from_site.code,
                  "to": to_site.code, "lines": len(parsed)})
    return tr, None


def approve(tr, actor):
    """The sending site's PM releases their own material."""
    if tr.status != SiteTransfer.Status.DRAFT:
        return None, "Only a draft transfer can be approved."
    site = tr.from_site
    if not (actor.role == "ADMIN" or site.is_current_pm(actor)):
        return None, f"Only {site.code}'s PM approves material leaving it."
    tr.status = SiteTransfer.Status.APPROVED
    tr.approved_by, tr.approved_at = actor, timezone.now()
    tr.save(update_fields=["status", "approved_by", "approved_at"])
    audit("document", tr.document_id, "MTN_APPROVED", actor=actor,
          detail={"ref": tr.document.ref})
    return tr, None


def despatch(tr, actor):
    """Stock leaves the sending site. Tools stay put until counted in, so a
    tool lost in transit is not silently already at the far end."""
    if tr.status != SiteTransfer.Status.APPROVED:
        return None, "The transfer must be approved before it is sent."
    if actor.role not in RAISE_ROLES:
        return None, "Site team or Admin despatch a transfer."
    site = tr.from_site
    with transaction.atomic():
        for ln in tr.lines.select_related("item"):
            if not ln.item_id:
                continue
            on_hand = balance(site, ln.item)
            if ln.qty > on_hand:
                transaction.set_rollback(True)
                return None, (f"{ln.item.description}: only {on_hand:g} left at "
                              f"{site.code} — re-check the transfer.")
            StockMovement.objects.create(
                site=site, item=ln.item,
                kind=StockMovement.Kind.TRANSFER_OUT, qty=-ln.qty,
                document=tr.document, movement_date=timezone.localdate(),
                reason=f"Transferred to {tr.to_site.code} ({tr.document.ref})",
                created_by=actor)
        tr.status = SiteTransfer.Status.DESPATCHED
        tr.despatched_by, tr.despatched_at = actor, timezone.now()
        tr.save(update_fields=["status", "despatched_by", "despatched_at"])
    audit("document", tr.document_id, "MTN_DESPATCHED", actor=actor,
          detail={"ref": tr.document.ref, "to": tr.to_site.code})
    return tr, None


def receive(tr, counts, actor, note=""):
    """The far site counts it in. `counts` maps line id -> quantity actually
    received; a line left out is taken as received in full."""
    if tr.status != SiteTransfer.Status.DESPATCHED:
        return None, "Only a despatched transfer can be received."
    to_site = tr.to_site
    if not (actor.role == "ADMIN" or actor.role in RECEIVE_ROLES):
        return None, "Site team or Admin receive a transfer."

    shortages = []
    with transaction.atomic():
        for ln in tr.lines.select_related("item", "tool"):
            got = counts.get(str(ln.id), counts.get(ln.id))
            got = ln.qty if got is None else _dec(got)
            if got < 0 or got > ln.qty:
                transaction.set_rollback(True)
                return None, ("Received quantity must be between zero and "
                              "what was sent.")
            ln.received_qty = got
            ln.save(update_fields=["received_qty"])
            if got < ln.qty:
                shortages.append(
                    f"{(ln.tool.name if ln.tool_id else ln.item.description)}: "
                    f"{ln.qty - got:g} short")
            if ln.item_id and got > 0:
                StockMovement.objects.create(
                    site=to_site, item=ln.item,
                    kind=StockMovement.Kind.TRANSFER_IN, qty=got,
                    document=tr.document, project=tr.to_project,
                    movement_date=timezone.localdate(),
                    reason=(f"Transferred from {tr.from_site.code} "
                            f"({tr.document.ref})"),
                    created_by=actor)
            # A tool only changes hands once someone has it in their hand.
            if ln.tool_id and got > 0:
                ln.tool.site = to_site
                ln.tool.save(update_fields=["site"])
        tr.status = SiteTransfer.Status.RECEIVED
        tr.received_by, tr.received_at = actor, timezone.now()
        tr.receipt_note = note
        tr.save(update_fields=["status", "received_by", "received_at",
                               "receipt_note"])
    audit("document", tr.document_id, "MTN_RECEIVED", actor=actor,
          detail={"ref": tr.document.ref, "at": to_site.code,
                  "shortages": shortages})
    return tr, None


def cancel(tr, actor, reason=""):
    """Only before anything has moved."""
    if tr.status not in (SiteTransfer.Status.DRAFT,
                         SiteTransfer.Status.APPROVED):
        return None, ("This transfer has already been sent — receive it and "
                      "transfer anything spare back.")
    tr.status = SiteTransfer.Status.CANCELLED
    tr.reason = (tr.reason + f"\nCancelled: {reason}").strip()
    tr.save(update_fields=["status", "reason"])
    audit("document", tr.document_id, "MTN_CANCELLED", actor=actor,
          detail={"ref": tr.document.ref, "reason": reason})
    return tr, None
