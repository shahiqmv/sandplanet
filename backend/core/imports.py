"""International purchase (IPR) service — Phase 1B (P1B-b).

Builds the overseas order from one or more sized-and-released PMRs, links the
demand to the order, and posts the commitment when a signatory authorises the
IPR on a Payment Voucher. The order is placed in the supplier's currency and
converted to MVR at the manually agreed rate (D4). Commitment splits per line:
each project allocation commits to that project's site; the general-stock
balance commits to the General Stock pool (never a project).
"""
from decimal import Decimal

from django.db import transaction

from . import costing
from .audit import audit
from .models import (Document, DocumentLink, DocumentRevision, ImportAllocation,
                     ImportOrder, ImportOrderLine, Item, Project, Supplier)
from .numbering import next_ref

ZERO = Decimal("0")


def _dec(v):
    return Decimal(str(v)) if v not in (None, "") else ZERO


def _ho_site():
    from .vouchers import ho_site
    return ho_site()


def ipr_order_total(order):
    """Order value in the order currency (sum of line values)."""
    return sum((ln.line_value for ln in order.lines.all()), ZERO)


def ipr_mvr_total(order):
    """Order value in MVR at the agreed rate — the voucher/commitment amount."""
    return (ipr_order_total(order) * order.exchange_rate).quantize(
        Decimal("0.01"))


def _validate_lines(lines_data):
    if not lines_data:
        return "Add at least one order line."
    for i, ln in enumerate(lines_data, 1):
        if not ln.get("item_id") and not (ln.get("free_text_desc") or "").strip():
            return f"Line {i}: choose an item or describe it."
        order_qty = _dec(ln.get("order_qty"))
        if order_qty <= ZERO:
            return f"Line {i}: order quantity must be greater than zero."
        if not ln.get("cost_head_id"):
            return f"Line {i}: choose a cost head."
        allocs = ln.get("allocations") or []
        if not allocs:
            return f"Line {i}: allocate the quantity to project(s) / stock."
        total = sum(_dec(a.get("qty")) for a in allocs)
        if total != order_qty:
            return (f"Line {i}: allocations ({total}) must sum to the order "
                    f"quantity ({order_qty}).")
        for a in allocs:
            if _dec(a.get("qty")) <= ZERO:
                return f"Line {i}: every allocation needs a quantity."
    return None


@transaction.atomic
def create_ipr(data, actor):
    """Create a draft IPR from the posted header + lines + PMR demand refs.
    Returns (document, error)."""
    try:
        supplier = Supplier.objects.get(pk=data.get("supplier_id"))
    except Supplier.DoesNotExist:
        return None, "Choose the overseas supplier."
    rate = _dec(data.get("exchange_rate"))
    if rate <= ZERO:
        return None, "Enter the agreed exchange rate (order currency → MVR)."
    lines_data = data.get("lines") or []
    err = _validate_lines(lines_data)
    if err:
        return None, err

    # Resolve PMR demand refs (must be sized-and-released or already sourcing)
    pmr_refs = [r for r in (data.get("pmr_refs") or []) if r]
    pmrs = list(Document.objects.filter(ref__in=pmr_refs, doc_type="PMR",
                                        is_void=False))
    if len(pmrs) != len(set(pmr_refs)):
        return None, "One or more PMR references are unknown."
    for pmr in pmrs:
        if pmr.status not in ("SIZED_RELEASED", "SOURCING"):
            return None, (f"{pmr.ref} is {pmr.status} — only a sized-and-"
                          "released requirement can be ordered.")

    from datetime import date
    ref = next_ref("IPR", None)
    doc = Document.objects.create(
        doc_type="IPR", ref=ref, site=_ho_site(),
        doc_date=data.get("doc_date") or date.today(), status="DRAFT",
        created_by=actor)
    DocumentRevision.objects.create(document=doc, rev_label="R0", payload={},
                                    created_by=actor)
    doc.current_revision = doc.revisions.first()
    doc.save(update_fields=["current_revision"])

    order = ImportOrder.objects.create(
        document=doc, supplier=supplier,
        order_currency=(data.get("order_currency") or "USD")[:3].upper(),
        exchange_rate=rate, incoterm=data.get("incoterm", ""),
        loading_port=data.get("loading_port", ""),
        discharge_port=data.get("discharge_port", ""),
        pi_ref=data.get("pi_ref", ""), notes=data.get("notes", ""))
    _save_lines(order, lines_data)

    for pmr in pmrs:
        DocumentLink.objects.get_or_create(from_document=doc, to_document=pmr,
                                           link_type="PMR_IPR")
    advance_linked_pmrs(doc, "SOURCING", actor)

    audit("document", doc.id, "DOC_CREATED", actor=actor, to_state="DRAFT",
          detail={"ref": ref, "supplier": supplier.name})
    return doc, None


def _save_lines(order, lines_data):
    order.lines.all().delete()
    from .models import CostHead
    for i, ln in enumerate(lines_data, 1):
        item = None
        if ln.get("item_id"):
            item = Item.objects.filter(pk=ln["item_id"]).first()
        line = ImportOrderLine.objects.create(
            order=order, line_no=i, item=item,
            free_text_desc="" if item else (ln.get("free_text_desc") or ""),
            unit=(item.unit if item else ln.get("unit", "")) or "",
            spec=ln.get("spec", ""), order_qty=_dec(ln.get("order_qty")),
            unit_price=_dec(ln.get("unit_price")),
            cost_head=CostHead.objects.get(pk=ln["cost_head_id"]),
            remarks=ln.get("remarks", ""))
        for a in ln.get("allocations") or []:
            project = None
            if a.get("project_id"):
                project = Project.objects.filter(pk=a["project_id"]).first()
            ImportAllocation.objects.create(line=line, project=project,
                                            qty=_dec(a.get("qty")))


def linked_pmrs(ipr_doc):
    return Document.objects.filter(
        links_to__from_document=ipr_doc,
        links_to__link_type="PMR_IPR").distinct()


def advance_linked_pmrs(ipr_doc, to_status, actor):
    """Move each PMR this IPR answers to `to_status` when the transition is
    valid (SIZED_RELEASED→SOURCING on order draft, SOURCING→ORDERED on award)."""
    for pmr in linked_pmrs(ipr_doc):
        if to_status in Document.TRANSITIONS["PMR"].get(pmr.status, set()):
            old = pmr.status
            pmr.status = to_status
            pmr.save(update_fields=["status", "updated_at"])
            audit("document", pmr.id, f"PMR_{to_status}", actor=actor,
                  from_state=old, to_state=to_status,
                  detail={"ref": pmr.ref, "ipr": ipr_doc.ref})


def authorise_ipr(doc, actor):
    """Commit the order when a signatory authorises it on a voucher (§6C.2).
    Posts COMMITTED in MVR at the agreed rate: each project allocation to that
    project's site under the line's cost head; the general-stock balance to the
    General Stock pool (never a project)."""
    order = doc.import_order
    rate = order.exchange_rate
    gs_head = costing.head("General Stock")
    ho = _ho_site()
    for line in order.lines.all():
        unit_mvr = (line.unit_price or ZERO) * rate
        for alloc in line.allocations.select_related("project__site"):
            amount = (alloc.qty * unit_mvr).quantize(Decimal("0.01"))
            if amount <= ZERO:
                continue
            if alloc.project_id:
                costing.post(site=alloc.project.site, cost_head=line.cost_head,
                             state="COMMITTED", source="IPR", amount=amount,
                             currency="MVR", document=doc, ipr_line=line,
                             actor=actor)
            else:
                costing.post(site=ho, cost_head=gs_head, state="COMMITTED",
                             source="IPR", amount=amount, currency="MVR",
                             document=doc, ipr_line=line, is_stock_pool=True,
                             actor=actor)
