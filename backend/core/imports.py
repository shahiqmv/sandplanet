"""International purchase (IPR) service — Phase 1B (P1B-b).

Builds the overseas order from one or more sized-and-released PMRs, links the
demand to the order, and posts the commitment when a signatory authorises the
IPR on a Payment Voucher. The order is placed in the supplier's currency and
converted to MVR at the manually agreed rate (D4). Commitment splits per line:
each project allocation commits to that project's site; the general-stock
balance commits to the General Stock pool (never a project).
"""
import logging
from decimal import Decimal

from django.db import transaction

from . import costing
from .audit import audit
from .models import (Document, DocumentLink, DocumentRevision, ImportAllocation,
                     ImportOrder, ImportOrderLine, Item, Project, Supplier)
from .numbering import next_ref

log = logging.getLogger(__name__)
ZERO = Decimal("0")


def _dec(v):
    return Decimal(str(v)) if v not in (None, "") else ZERO


def _ho_site():
    from .vouchers import ho_site
    return ho_site()


def ipr_line_subtotal(order):
    """Sum of the line values in the order currency (before adjustments)."""
    return sum((ln.line_value for ln in order.lines.all()), ZERO)


def ipr_order_total(order):
    """Order value in the order currency: line subtotal − discount + supplier
    freight/handling + a miscellaneous supplier fee (owner 2026-07-21 / -08-06)."""
    return (ipr_line_subtotal(order) - (order.discount or ZERO)
            + (order.freight_handling or ZERO) + (order.misc_fee or ZERO))


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
        pi_ref=data.get("pi_ref", ""), notes=data.get("notes", ""),
        discount=_dec(data.get("discount")) or None,
        freight_handling=_dec(data.get("freight_handling")) or None,
        misc_fee=_dec(data.get("misc_fee")) or None)
    _save_lines(order, lines_data)

    for pmr in pmrs:
        DocumentLink.objects.get_or_create(from_document=doc, to_document=pmr,
                                           link_type="PMR_IPR")
    advance_linked_pmrs(doc, "SOURCING", actor)

    audit("document", doc.id, "DOC_CREATED", actor=actor, to_state="DRAFT",
          detail={"ref": ref, "supplier": supplier.name})
    return doc, None


@transaction.atomic
def update_ipr(doc, data, actor):
    """Edit a DRAFT overseas order in place — header + lines (owner 2026-07-14).
    Only a draft can be edited; nothing is committed yet, so replacing the lines
    is safe. PMR demand links are left as they are."""
    if doc.status != "DRAFT":
        return None, "Only a draft order can be edited."
    order = doc.import_order
    if data.get("supplier_id"):
        supplier = Supplier.objects.filter(pk=data["supplier_id"]).first()
        if not supplier:
            return None, "Choose the overseas supplier."
        order.supplier = supplier
    rate = _dec(data.get("exchange_rate"))
    if rate <= ZERO:
        return None, "Enter the agreed exchange rate (order currency → MVR)."
    lines_data = data.get("lines") or []
    err = _validate_lines(lines_data)
    if err:
        return None, err
    order.order_currency = (data.get("order_currency")
                            or order.order_currency)[:3].upper()
    order.exchange_rate = rate
    for f in ("incoterm", "loading_port", "discharge_port", "pi_ref", "notes"):
        if f in data:
            setattr(order, f, data.get(f) or "")
    for f in ("discount", "freight_handling", "misc_fee"):
        if f in data:
            setattr(order, f, _dec(data.get(f)) or None)
    order.save()
    _save_lines(order, lines_data)
    audit("document", doc.id, "IPR_EDITED", actor=actor,
          detail={"ref": doc.ref, "lines": len(lines_data)})
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


def _post_split(order, doc, state, fraction, rate, actor, milestone=None):
    """Post `state` rows for a fraction (0..1) of the order at `rate` MVR, split
    the same way the order is allocated: each project allocation to that
    project's site under the line's cost head; the general-stock balance to the
    General Stock pool (never a project). Shared by commitment and payment."""
    gs_head = costing.head("General Stock")
    ho = _ho_site()
    # Apportion the order-level discount / freight / misc fee across every line
    # so the committed MVR equals the real order value, not just the subtotal.
    subtotal = ipr_line_subtotal(order)
    net_factor = (ipr_order_total(order) / subtotal) if subtotal else Decimal("1")
    for line in order.lines.all():
        unit_mvr = (line.unit_price or ZERO) * rate * net_factor
        for alloc in line.allocations.select_related("project__site"):
            amount = (alloc.qty * unit_mvr * fraction).quantize(Decimal("0.01"))
            if not amount:   # charge corrections pass a signed fraction —
                continue     # negative rows are §4A mirrors, only zero skips
            if alloc.project_id:
                costing.post(site=alloc.project.site, cost_head=line.cost_head,
                             state=state, source="IPR", amount=amount,
                             currency="MVR", document=doc, ipr_line=line,
                             ipr_milestone=milestone, actor=actor)
            else:
                costing.post(site=ho, cost_head=gs_head, state=state,
                             source="IPR", amount=amount, currency="MVR",
                             document=doc, ipr_line=line, is_stock_pool=True,
                             ipr_milestone=milestone, actor=actor)


def generate_po_for_ipr(doc, actor):
    """Generate the supplier purchase order for an authorised import order —
    the overseas counterpart of a domestic PR's PO (owner 2026-07-16). One PO
    for the whole order, in the order currency, with no domestic GST. Created
    as a DRAFT PO; HO Purchasing issues it to the supplier (same as a PR PO)."""
    from datetime import date
    from .models import DocumentLine
    order = doc.import_order
    if doc.links_from.filter(link_type="IPR_PO").exists():
        return None                       # already generated (idempotent)
    with transaction.atomic():
        po = Document.objects.create(
            doc_type="PO", ref=next_ref("PO", doc.site), site=doc.site,
            doc_date=date.today(), status="DRAFT", created_by=actor,
            supplier=order.supplier)
        revision = DocumentRevision.objects.create(
            document=po, rev_label="R0", created_by=actor, payload={
                "ipr_ref": doc.ref,        # internal only — not on the PO PDF
                "supplier_name": order.supplier.name,
                "supplier_contact": order.supplier.contact_person,
                "currency": order.order_currency,
                "tax_rate": 0,             # imports: no domestic GST on the PO
                "payment_terms": order.incoterm or "",
                "pi_ref": order.pi_ref,
                # Order-level charges belong on the PO total (owner 2026-08-06):
                # a discount off the goods, supplier freight/handling, and a
                # miscellaneous fee (e.g. documentation).
                "discount": str(order.discount or 0),
                "freight": str(order.freight_handling or 0),
                "misc_fee": str(order.misc_fee or 0),
            })
        po.current_revision = revision
        po.save(update_fields=["current_revision"])
        for line in order.lines.all():
            DocumentLine.objects.create(
                revision=revision, line_no=line.line_no, item=line.item,
                free_text_desc="" if line.item else line.free_text_desc,
                unit=line.unit, spec=line.spec, qty_required=line.order_qty,
                rate=line.unit_price, amount=line.line_value,
                remarks=line.remarks)
        DocumentLink.objects.get_or_create(
            from_document=doc, to_document=po, link_type="IPR_PO")
    audit("document", po.id, "PO_GENERATED", actor=actor,
          detail={"ref": po.ref, "ipr": doc.ref, "supplier": order.supplier.name})
    return po


def authorise_ipr(doc, actor):
    """Commit the order when a signatory authorises it on a voucher (§6C.2).
    Posts COMMITTED in MVR at the agreed rate across the order's allocations,
    then raises the supplier PO (owner 2026-07-16)."""
    order = doc.import_order
    _post_split(order, doc, "COMMITTED", Decimal("1"), order.exchange_rate,
                actor)
    generate_po_for_ipr(doc, actor)


def withdraw_blocked(doc):
    """Why an authorised order can't have its authorisation withdrawn yet —
    anything downstream that a plain reversal would leave inconsistent. Returns
    a message, or None when it's safe."""
    order = doc.import_order
    if order.shipments.exists():
        return ("This order already has a shipment — cancel the shipment "
                "before withdrawing the authorisation.")
    # A milestone past PENDING has a payment voucher raised against it (a
    # voucher line PROTECT-references it), so it can't be unwound here.
    if order.milestones.exclude(status="PENDING").exists():
        return ("A payment voucher has been raised on this order's schedule — "
                "cancel/void those payment vouchers before withdrawing the "
                "authorisation.")
    return None


def reverse_ipr_authorisation(doc, actor):
    """Undo an order's authorisation (owner 2026-07-27, to fix an order
    authorised against the wrong supplier): reverse the COMMITTED ledger
    postings, delete the unpaid payment schedule, and void the supplier PO +
    drop its link so re-authorisation regenerates a fresh one. Callers must
    check withdraw_blocked() first; the IPR goes back to Draft to be edited and
    re-authorised."""
    from django.utils import timezone
    from .models import CostPosting
    order = doc.import_order
    # Delete the commitment postings outright rather than write net-zero
    # mirrors: authorisation was the only thing that posted them, nothing has
    # been paid or shipped (guarded), and keeping them would PROTECT-lock the
    # order lines against the edit that follows. The withdrawal itself is
    # audited (IPR_AUTH_WITHDRAWN + the Draft transition record).
    CostPosting.objects.filter(document=doc, state="COMMITTED").delete()
    # Only untouched (PENDING) schedule rows are removed; withdraw_blocked has
    # already refused if any milestone carries a voucher.
    order.milestones.filter(status="PENDING").delete()
    link = DocumentLink.objects.filter(
        from_document=doc, link_type="IPR_PO").select_related(
        "to_document").first()
    if link:
        po = link.to_document
        if not po.is_void:
            po.is_void = True
            po.void_reason = f"IPR {doc.ref} authorisation withdrawn"
            po.voided_by = actor
            po.voided_at = timezone.now()
            po.save(update_fields=["is_void", "void_reason", "voided_by",
                                   "voided_at"])
        link.delete()
    audit("document", doc.id, "IPR_AUTH_WITHDRAWN", actor=actor,
          detail={"ref": doc.ref})


# ---- commercial-charge correction on an authorised order ---------------------
# The full withdraw path (above) needs the order untouched downstream; once a
# shipment is booked or a milestone paid, a wrong discount/freight/misc fee can
# only be fixed forward. Purchasing proposes the corrected charges with a
# reason, the Director approves, a Signatory authorises — the same chain that
# authorised the original total (owner 2026-08-10).

CORRECTION_FIELDS = ("discount", "freight_handling", "misc_fee")


def pending_charge_correction(order):
    return order.charge_corrections.filter(
        status__in=("PENDING_DIRECTOR", "PENDING_SIGNATORY")).first()


def propose_charge_correction(doc, data, actor):
    from .models import ImportChargeCorrection
    order = doc.import_order
    if doc.status != "AUTHORISED":
        return None, ("Only an authorised order needs a correction — a draft "
                      "is edited directly.")
    if pending_charge_correction(order):
        return None, "A correction is already awaiting approval."
    reason = (data.get("reason") or "").strip()
    if not reason:
        return None, ("Give the reason for the correction (e.g. the PI "
                      "includes freight)."   )
    new = {f: (_dec(data.get(f)) if data.get(f) not in (None, "") else None)
           for f in CORRECTION_FIELDS}
    fold_ids, fold_err = _validate_fold_lines(order, data.get("fold_line_ids"))
    if fold_err:
        return None, fold_err
    if not fold_ids and all((new[f] or ZERO) == (getattr(order, f) or ZERO)
                            for f in CORRECTION_FIELDS):
        return None, "Nothing changed — the charges are already these values."
    subtotal_after = sum((ln.line_value for ln in order.lines.all()
                          if ln.id not in fold_ids), ZERO)
    if subtotal_after <= ZERO:
        return None, "Folding every line would leave no goods on the order."
    new_total = (subtotal_after - (new["discount"] or ZERO)
                 + (new["freight_handling"] or ZERO)
                 + (new["misc_fee"] or ZERO))
    if new_total <= ZERO:
        return None, "The corrected charges wipe out the order value."
    # Only money the company is actually committed to blocks a reduction:
    # milestones paid, authorised, or sitting on a voucher. A merely-DUE
    # milestone with no voucher rescales with the correction instead of
    # blocking it (owner 2026-08-27, IPR-037 — the guard counted a DUE
    # advance as "settled" and dead-locked the correction).
    from .models import PaymentVoucherLine
    old_total = ipr_order_total(order)
    settled = ZERO
    holders = []
    for m in order.milestones.all():
        line = (PaymentVoucherLine.objects
                .filter(source_milestone=m, status="INCLUDED")
                .select_related("voucher").first())
        committed = (m.status in ("AUTHORISED", "PAID") or m.voucher_id
                     or line is not None)
        if committed:
            settled += m.due_amount(old_total)
            if m.status == "PAID":
                holders.append(f"{m.label} (paid)")
            elif line is not None:
                holders.append(f"{m.label} on {line.voucher.ref}")
            else:
                holders.append(f"{m.label} ({m.status.lower()})")
    if new_total < settled:
        return None, (f"The corrected total ({new_total}) is below what is "
                      f"already vouchered or paid ({settled}): "
                      + "; ".join(holders) + ". Query or cancel the voucher "
                      "line first, then propose the correction.")
    corr = ImportChargeCorrection.objects.create(
        order=order, reason=reason, created_by=actor,
        fold_line_ids=sorted(fold_ids), **new)
    audit("document", doc.id, "IPR_CORRECTION_PROPOSED", actor=actor,
          detail={"ref": doc.ref, "reason": reason,
                  "fold_lines": sorted(fold_ids),
                  **{f: str(new[f] or 0) for f in CORRECTION_FIELDS}})
    return corr, None


def _validate_fold_lines(order, ids):
    """Lines proposed to fold into supplier freight: must be live lines of
    this order and not already counted into stock by an IRN."""
    from .models import ImportReceiptLine
    if not ids:
        return set(), None
    try:
        fold_ids = {int(i) for i in ids}
    except (TypeError, ValueError):
        return None, "Bad fold_line_ids."
    lines = {ln.id: ln for ln in order.lines.all()}
    for i in fold_ids:
        ln = lines.get(i)
        if not ln:
            return None, "A folded line does not belong to this order."
        if not ln.line_value:
            return None, (f"Line {ln.line_no} has no value — it is already "
                          f"folded or empty.")
        if ImportReceiptLine.objects.filter(ipr_line=ln).exists():
            return None, (f"Line {ln.line_no} has been received on an IRN — "
                          f"it can no longer be folded into freight.")
    return fold_ids, None


def decide_charge_correction(doc, action, actor, reason=""):
    """Advance or reject the pending correction. Director approves first,
    then a Signatory authorises (which applies it); either can reject."""
    from django.utils import timezone
    order = doc.import_order
    corr = pending_charge_correction(order)
    if not corr:
        return "No correction is awaiting approval."
    if action == "reject":
        if actor.role not in ("DIRECTOR", "QS", "SIGNATORY", "ADMIN"):
            return "Only the approvers can reject a correction."
        corr.status = "REJECTED"
        corr.reject_reason = reason or ""
        corr.decided_by, corr.decided_at = actor, timezone.now()
        corr.save(update_fields=["status", "reject_reason", "decided_by",
                                 "decided_at"])
        audit("document", doc.id, "IPR_CORRECTION_REJECTED", actor=actor,
              detail={"ref": doc.ref, "reason": reason})
        return None
    if corr.status == "PENDING_DIRECTOR":
        # QS shares the Director's overseas-procurement authority
        if actor.role not in ("DIRECTOR", "QS", "ADMIN"):
            return "The Director approves the correction first."
        corr.status = "PENDING_SIGNATORY"
        corr.director_by, corr.director_at = actor, timezone.now()
        corr.save(update_fields=["status", "director_by", "director_at"])
        audit("document", doc.id, "IPR_CORRECTION_APPROVED", actor=actor,
              detail={"ref": doc.ref})
        return None
    if actor.role not in ("SIGNATORY", "ADMIN"):
        return "A signatory authorises the corrected total."
    try:
        with transaction.atomic():
            _apply_charge_correction(doc, corr, actor)
    except ValueError as e:
        return str(e)
    return None


def _apply_charge_correction(doc, corr, actor):
    """Write the corrected charges, fold any freight-typed lines, then
    reconcile the COMMITTED ledger to the corrected total; revise the PO so
    the supplier-facing total matches. All ledger moves are append-only —
    negative rows are §4A mirrors, never deletes."""
    from django.utils import timezone
    from .models import CostPosting, ImportReceiptLine, ImportShipmentLine
    order = corr.order
    old_total = ipr_order_total(order)
    for line in order.lines.filter(id__in=corr.fold_line_ids or []):
        # re-check receipt inside the transaction; the IRN may have landed
        # between propose and authorise
        if ImportReceiptLine.objects.filter(ipr_line=line).exists():
            raise ValueError(f"Line {line.line_no} has been received on an "
                             f"IRN — the correction can no longer be applied.")
        ImportShipmentLine.objects.filter(ipr_line=line).delete()
        for p in CostPosting.objects.filter(
                document=doc, ipr_line=line, state="COMMITTED",
                reversal_of__isnull=True):
            costing.post(site=p.site, cost_head=p.cost_head, state="COMMITTED",
                         source="IPR", amount=-p.amount, document=doc,
                         ipr_line=line, is_stock_pool=p.is_stock_pool,
                         reversal_of=p, actor=actor)
        line.allocations.all().delete()
        line.order_qty = ZERO
        line.save(update_fields=["order_qty"])
    for f in CORRECTION_FIELDS:
        setattr(order, f, getattr(corr, f))
    order.save(update_fields=list(CORRECTION_FIELDS))
    # Reconcile: whatever history got the ledger here (original commitment,
    # earlier deltas, the mirrors above), one spread brings the committed sum
    # to exactly the corrected MVR total.
    target = ipr_mvr_total(order)
    posted = sum((p.amount for p in CostPosting.objects.filter(
        document=doc, state="COMMITTED")), ZERO)
    if target and target != posted:
        _post_split(order, doc, "COMMITTED", (target - posted) / target,
                    order.exchange_rate, actor)
    _revise_po_charges(doc, order, actor)
    _rescale_fixed_milestones(order, old_total, actor)
    corr.status = "APPLIED"
    corr.decided_by, corr.decided_at = actor, timezone.now()
    corr.save(update_fields=["status", "decided_by", "decided_at"])
    audit("document", doc.id, "IPR_CORRECTION_APPLIED", actor=actor,
          detail={"ref": doc.ref, "old_total": str(old_total),
                  "new_total": str(ipr_order_total(order)),
                  "folded_lines": corr.fold_line_ids or []})


def _rescale_fixed_milestones(order, old_total, actor):
    """Bring FIXED milestones along with a charge correction (owner
    2026-08-27, IPR-037): percent milestones follow the total by
    construction, but a fixed advance kept its old amount and the schedule
    no longer summed to the corrected total — dead-locking the schedule
    editor. Milestones already committed (paid / authorised / on a voucher)
    are never touched; the still-movable fixed ones scale proportionally,
    with the last one absorbing rounding so the schedule sums exactly."""
    from .models import PaymentVoucherLine
    new_total = ipr_order_total(order)
    ms = list(order.milestones.all())

    def committed(m):
        return (m.status in ("AUTHORISED", "PAID") or m.voucher_id
                or PaymentVoucherLine.objects.filter(
                    source_milestone=m, status="INCLUDED").exists())

    kept = sum((m.due_amount(old_total) for m in ms if committed(m)), ZERO)
    pct_due = sum((m.due_amount(new_total) for m in ms
                   if not committed(m) and m.fixed_amount is None), ZERO)
    movable = [m for m in ms
               if not committed(m) and m.fixed_amount is not None]
    if not movable:
        return
    target = new_total - kept - pct_due
    if target < ZERO:
        target = ZERO
    base = sum((m.fixed_amount for m in movable), ZERO)
    running = ZERO
    for i, m in enumerate(movable):
        if i == len(movable) - 1:
            amount = (target - running).quantize(Decimal("0.01"))
        else:
            share = (m.fixed_amount / base) if base else \
                Decimal("1") / len(movable)
            amount = (target * share).quantize(Decimal("0.01"))
        running += amount
        if amount != m.fixed_amount:
            audit("document", order.document_id, "IPR_MILESTONE_RESCALED",
                  actor=actor, detail={"milestone": m.id, "label": m.label,
                                       "from": str(m.fixed_amount),
                                       "to": str(amount)})
            m.fixed_amount = amount
            m.save(update_fields=["fixed_amount"])


def _revise_po_charges(doc, order, actor):
    """New PO revision carrying the corrected order-level charges — the lines
    are unchanged; only the charge block (and so the PO total) moves."""
    from .models import DocumentLine, DocumentRevision
    link = doc.links_from.filter(link_type="IPR_PO").select_related(
        "to_document").first()
    if not link or link.to_document.is_void:
        return
    po = link.to_document
    old = po.current_revision
    payload = dict(old.payload or {})
    payload.update({"discount": str(order.discount or 0),
                    "freight": str(order.freight_handling or 0),
                    "misc_fee": str(order.misc_fee or 0)})
    old.is_current = False
    old.save(update_fields=["is_current"])
    revision = DocumentRevision.objects.create(
        document=po, rev_label=f"R{int(old.rev_label[1:]) + 1}",
        payload=payload, created_by=actor)
    for line in old.lines.all():
        DocumentLine.objects.create(
            revision=revision, line_no=line.line_no, item=line.item,
            free_text_desc=line.free_text_desc, unit=line.unit,
            spec=line.spec, qty_required=line.qty_required, rate=line.rate,
            amount=line.amount, remarks=line.remarks)
    po.current_revision = revision
    po.save(update_fields=["current_revision", "updated_at"])
    audit("document", po.id, "PO_CHARGES_CORRECTED", actor=actor,
          detail={"ref": po.ref, "rev": revision.rev_label,
                  "ipr": doc.ref})


def set_milestones(order, rows):
    """Replace the order's payment schedule. Each row: {label, trigger,
    percent|fixed_amount, due_date}. The scheduled amounts must sum to the
    order total (in the order currency)."""
    from .models import ImportPaymentMilestone
    if order.milestones.filter(status="PAID").exists():
        return "Some milestones are already paid — the schedule is locked."
    total = ipr_order_total(order)
    scheduled = ZERO
    cleaned = []
    for i, r in enumerate(rows, 1):
        label = (r.get("label") or "").strip()
        if not label:
            return f"Milestone {i}: give it a name."
        pct = _dec(r.get("percent")) if r.get("percent") not in (None, "") \
            else None
        fixed = _dec(r.get("fixed_amount")) if r.get("fixed_amount") not in \
            (None, "") else None
        if pct is None and fixed is None:
            return f"Milestone {i}: set a percent or a fixed amount."
        amt = fixed if fixed is not None else (total * pct / Decimal("100"))
        scheduled += amt
        # Credit after the trigger: the row's own figure, else the supplier's
        # agreed period, else none (pay on the trigger).
        raw_cd = r.get("credit_days")
        cd = (int(raw_cd) if str(raw_cd if raw_cd is not None else "").strip()
              .isdigit() else None)
        if cd is None:
            cd = order.supplier.credit_days if order.supplier_id else None
        cleaned.append({"label": label,
                        "trigger": r.get("trigger") or "BALANCE",
                        "percent": pct, "fixed_amount": fixed,
                        "due_date": r.get("due_date") or None,
                        "credit_days": cd})
    if abs(scheduled.quantize(Decimal("0.01")) - total.quantize(
            Decimal("0.01"))) > Decimal("0.01"):
        return (f"The schedule ({scheduled.quantize(Decimal('0.01'))}) must "
                f"sum to the order total ({total.quantize(Decimal('0.01'))} "
                f"{order.order_currency}).")
    order.milestones.exclude(status="PAID").delete()
    for i, c in enumerate(cleaned, 1):
        ImportPaymentMilestone.objects.create(order=order, seq=i, **c)
    return None


def _stamp_due(m):
    """The day a milestone fell due, and the day it must be paid by — the
    trigger date plus whatever credit the supplier gives on it. Stamped once;
    Finance may move pay_by afterwards with a reason."""
    from datetime import timedelta
    from django.utils import timezone
    today = timezone.localdate()
    m.status = "DUE"
    m.fell_due_on = today
    m.pay_by = today + timedelta(days=m.credit_days or 0)
    m.save(update_fields=["status", "fell_due_on", "pay_by"])


def mark_milestone_due(milestone, actor):
    """Purchasing flags a milestone due (its trigger has been met) — it then
    enters Finance's international-payables register."""
    if milestone.status != "PENDING":
        return "Only a pending milestone can be marked due."
    _stamp_due(milestone)
    audit("document", milestone.order.document_id, "IPR_MILESTONE_DUE",
          actor=actor, detail={"milestone": milestone.label,
                               "pay_by": str(milestone.pay_by)})
    return None


def move_pay_by(milestone, on, reason, actor):
    """Finance moves the pay-by date — a supplier extended, or a related party
    is happy to wait. Reason required, audited, and the milestone stays where
    it is otherwise (owner 2026-08-23)."""
    from datetime import date as _date
    if milestone.status != "DUE":
        return "Only a due milestone has a pay-by date to move."
    try:
        new = _date.fromisoformat(str(on))
    except (TypeError, ValueError):
        return "Give the new pay-by date."
    if not (reason or "").strip():
        return "Say why the pay-by date is moving."
    old = milestone.pay_by
    milestone.pay_by = new
    milestone.save(update_fields=["pay_by"])
    audit("document", milestone.order.document_id, "IPR_MILESTONE_PAY_BY_MOVED",
          actor=actor, detail={"milestone": milestone.label, "from": str(old),
                               "to": str(new), "reason": reason.strip()})
    return None


def pay_milestone(milestone, mvr_paid, tt_ref, actor):
    """Finance executes the TT for a voucher-authorised milestone. The
    committed-value share posts PAID to the projects/stock at the agreed rate;
    the difference between the actual MVR paid and that committed value is
    realised FX, posted to the Foreign Exchange pool (never a project). The
    milestone already carries the authorising voucher reference (§6C.2)."""
    from django.utils import timezone
    if milestone.status != "AUTHORISED":
        return ("This payment must be authorised on a Payment Voucher before "
                "the TT can be recorded.")
    mvr_paid = _dec(mvr_paid)
    if mvr_paid <= ZERO:
        return "Enter the MVR amount actually paid."
    order = milestone.order
    doc = order.document
    total = ipr_order_total(order)
    due_ccy = milestone.due_amount(total)
    if due_ccy <= ZERO:
        return "This milestone has no amount."
    fraction = due_ccy / total
    committed_mvr = (due_ccy * order.exchange_rate).quantize(Decimal("0.01"))
    with transaction.atomic():
        _post_split(order, doc, "PAID", fraction, order.exchange_rate, actor,
                    milestone=milestone)
        fx_delta = (mvr_paid - committed_mvr).quantize(Decimal("0.01"))
        if fx_delta != ZERO:
            costing.post(site=_ho_site(), cost_head=costing.head(
                "Foreign Exchange"), state="PAID", source="FX",
                amount=fx_delta, currency="MVR", document=doc,
                ipr_milestone=milestone, is_stock_pool=True, actor=actor)
        milestone.status = "PAID"
        milestone.tt_ref = tt_ref or ""
        milestone.mvr_paid = mvr_paid
        milestone.actual_rate = (mvr_paid / due_ccy).quantize(Decimal("0.0001"))
        milestone.paid_by = actor
        milestone.paid_at = timezone.now()
        milestone.save(update_fields=["status", "tt_ref", "mvr_paid",
                                      "actual_rate", "paid_by", "paid_at"])
    audit("document", doc.id, "IPR_MILESTONE_PAID", actor=actor,
          detail={"milestone": milestone.label, "mvr": str(mvr_paid),
                  "tt_ref": tt_ref})
    return None


def payments_due():
    """The international-payables register: every unpaid milestone on an
    authorised order — PENDING (coming: the balance on arrival Finance wants to
    see ahead of time), DUE (payable, with a pay-by date) and AUTHORISED
    (voucher-approved, ready for the TT). Owner 2026-08-23."""
    from .models import ImportPaymentMilestone
    return ImportPaymentMilestone.objects.filter(
        status__in=("PENDING", "DUE", "AUTHORISED"),
        order__document__status="AUTHORISED",
        order__document__is_void=False).select_related(
        "order__document", "order__supplier", "voucher").order_by(
        "order__supplier__name", "order__document__ref", "seq")


# ---- Shipments + shipping documents (P1B-d) ------------------------------

REQUIRED_FOR_CLEARING = ["BL_AWB", "PACKING_LIST", "COMMERCIAL_INVOICE"]
CHARGE_FIELDS = ("freight", "insurance", "customs_duty", "import_gst",
                 "port_handling", "agent_charges", "local_transport")


def fire_milestones(order, trigger, actor):
    """A shipping event met a trigger — move matching pending milestones to DUE
    so they enter Finance's queue (§5.10.7)."""
    fired = []
    for m in order.milestones.filter(trigger=trigger, status="PENDING"):
        _stamp_due(m)
        fired.append(m)
    if fired:
        audit("document", order.document_id, "IPR_MILESTONES_FIRED",
              actor=actor, detail={"trigger": trigger,
                                   "milestones": [m.label for m in fired]})
    return fired


def line_shipped(ipr_line):
    """Quantity of this order line already allocated to shipments."""
    from django.db.models import Sum
    from .models import ImportShipmentLine
    return (ImportShipmentLine.objects.filter(ipr_line=ipr_line)
            .aggregate(s=Sum("qty"))["s"] or ZERO)


def line_remaining(ipr_line):
    """Quantity of this order line still to be put on a shipment."""
    return (ipr_line.order_qty or ZERO) - line_shipped(ipr_line)


@transaction.atomic
def create_shipment(order, data, actor):
    """Book a shipment. `data['lines']` optionally allocates order-line
    quantities to this shipment ([{ipr_line_id, qty}]); each quantity must be
    within that line's still-to-ship balance. With no allocation given, the
    shipment carries the whole remaining order (single-shipment / 'ship the
    rest' default)."""
    from . import tracking as trk
    from .models import ImportShipment, ImportShipmentLine, Supplier
    # Reject a malformed tracking key at data entry (D40, AC5).
    mode = data.get("mode") or "SEA"
    key_err = trk.validate_shipment_keys(
        mode, data.get("bl_no", ""), data.get("container_awb", ""),
        data.get("carrier_scac", ""))
    if key_err:
        return None, key_err
    seq = (order.shipments.count() or 0) + 1
    forwarder = None
    if data.get("forwarder_id"):
        forwarder = Supplier.objects.filter(pk=data["forwarder_id"]).first()

    # Resolve the allocation (explicit rows, else the whole remaining order).
    order_lines = {ln.id: ln for ln in order.lines.all()}
    rows = data.get("lines")
    alloc = []                                   # [(ipr_line, qty)]
    if rows:
        for r in rows:
            ln = order_lines.get(r.get("ipr_line_id"))
            qty = _dec(r.get("qty"))
            if ln is None or qty <= ZERO:
                continue
            remaining = line_remaining(ln)
            if qty > remaining:
                return None, (f"{ln.description or ('line ' + str(ln.line_no))}"
                              f": only {remaining} left to ship "
                              f"(you entered {qty}).")
            alloc.append((ln, qty))
        if not alloc:
            return None, "Add at least one item quantity to this shipment."
    else:
        for ln in order.lines.all():
            remaining = line_remaining(ln)
            if remaining > ZERO:
                alloc.append((ln, remaining))
        if not alloc:
            return None, "The whole order is already on shipments."

    with transaction.atomic():
        shipment = _new_shipment_row(order, mode, forwarder, data, actor)
        shipment.seq = seq
        shipment.save(update_fields=["seq"])
        for ln, qty in alloc:
            ImportShipmentLine.objects.create(shipment=shipment, ipr_line=ln,
                                              qty=qty)
    # A key entered AT BOOKING starts tracking right away — only edits and
    # the Shipped move registered before, so an air shipment booked with its
    # AWB sat untracked until someone touched it (IPR-024, 2026-08-26).
    _register_tracking(shipment)
    return shipment, None


def missing_clearing_docs(shipment):
    have = set(shipment.documents.values_list("doc_type", flat=True))
    return [d for d in REQUIRED_FOR_CLEARING if d not in have]


def _new_shipment_row(primary, mode, forwarder, data, actor):
    """The ImportShipment row itself — shared by both booking paths so the
    SHP reference is issued the same way (2026-08-28)."""
    from .models import ImportShipment
    return ImportShipment.objects.create(
        ref=next_ref("SHP", None),
        order=primary, seq=(primary.shipments.count() or 0) + 1, mode=mode,
        forwarder=forwarder, forwarder_name=data.get("forwarder_name", ""),
        vessel_flight=data.get("vessel_flight", ""),
        carrier_scac=(data.get("carrier_scac", "") or "").strip().upper(),
        bl_no=data.get("bl_no", ""),
        container_awb=data.get("container_awb", ""),
        etd=data.get("etd") or None, eta=data.get("eta") or None,
        tracking_ref=data.get("tracking_ref", ""),
        carrier_link=data.get("carrier_link", ""),
        notes=data.get("notes", ""), created_by=actor)


def create_consolidated_shipment(data, actor):
    """Book a shipment whose cargo spans ANY authorised orders (owner
    2026-08-28): a supplier clubbing several of our orders, or our forwarder
    consolidating several suppliers into one container.
    data["rows"] = [{ipr_line_id, qty}] across orders."""
    from . import tracking as trk
    from .models import (ImportOrderLine, ImportShipment, ImportShipmentLine,
                         Supplier)
    mode = data.get("mode") or "SEA"
    key_err = trk.validate_shipment_keys(
        mode, data.get("bl_no", ""), data.get("container_awb", ""),
        data.get("carrier_scac", ""))
    if key_err:
        return None, key_err
    alloc = []
    for r in data.get("rows") or []:
        ln = (ImportOrderLine.objects
              .select_related("order__document")
              .filter(pk=r.get("ipr_line_id")).first())
        qty = _dec(r.get("qty"))
        if ln is None or qty <= ZERO:
            continue
        if ln.order.document.is_void \
                or ln.order.document.status != "AUTHORISED":
            return None, (f"{ln.order.document.ref} is not an authorised "
                          f"order.")
        remaining = line_remaining(ln)
        if qty > remaining:
            return None, (f"{ln.order.document.ref} line {ln.line_no}: only "
                          f"{remaining} left to ship (you entered {qty}).")
        alloc.append((ln, qty))
    if not alloc:
        return None, "Add at least one order line to the shipment."
    primary = alloc[0][0].order
    forwarder = None
    if data.get("forwarder_id"):
        forwarder = Supplier.objects.filter(pk=data["forwarder_id"]).first()
    # next_ref locks the counter FOR UPDATE, so the whole booking runs in one
    # transaction — a failed create rolls the number back (2026-08-28).
    with transaction.atomic():
        shipment = _new_shipment_row(
            primary, mode, forwarder, data, actor)
        for ln, qty in alloc:
            ImportShipmentLine.objects.create(shipment=shipment, ipr_line=ln,
                                              qty=qty)
    _register_tracking(shipment)
    audit("document", primary.document_id, "SHIPMENT_BOOKED", actor=actor,
          detail={"ref": shipment.ref,
                  "orders": [o.document.ref for o in shipment.orders()]})
    return shipment, None


def advance_shipment(shipment, to_status, actor):
    """Move a shipment forward. Arrival fires arrival-triggered milestones;
    the move to Under Clearing needs the core documents (§5.10.7/8)."""
    from .models import ImportShipment
    if to_status not in ImportShipment.NEXT.get(shipment.status, set()):
        return f"Cannot move from {shipment.status} to {to_status}."
    if to_status == "UNDER_CLEARING":
        missing = missing_clearing_docs(shipment)
        if missing:
            return ("Upload the clearing documents first — missing: "
                    + ", ".join(missing))
    old = shipment.status
    shipment.status = to_status
    shipment.save(update_fields=["status"])
    audit("document", shipment.order.document_id, "SHIPMENT_STATUS",
          actor=actor, from_state=old, to_state=to_status,
          detail={"shipment": shipment.seq})
    if to_status == "SHIPPED":
        _register_tracking(shipment)
    if to_status == "ARRIVED":
        # a consolidated shipment arrives for every order aboard
        for o in shipment.orders():
            fire_milestones(o, "ARRIVAL", actor)
    return None


def _register_tracking(shipment):
    """Best-effort live-tracking (re)registration whenever a shipment carries a
    usable key (D40). Handles the common case where the B/L is entered after
    the shipment already left — a pending/failed tracking is refreshed with
    the new key and retried. Never raises: tracking must not break the
    shipment workflow.

    Registration does NOT wait for the SHIPPED transition (owner 2026-08-11):
    the carrier assigns the container at booking and the box is often already
    sailing while the app still reads BOOKED, so a container number entered on
    a booked shipment silently tracked nothing. The provider is the authority
    on whether the key resolves yet; an unresolvable one simply reads
    UNTRACKED and re-registers on the next edit."""
    from . import tracking as trk
    from .models import ShipmentTracking
    try:
        t = ShipmentTracking.objects.filter(shipment=shipment).first()
        if t is None:
            t = trk.ensure_tracking(shipment)
            if t and t.state == t.State.PENDING:
                trk.register_tracking(t)
            return
        key = (shipment.container_awb.strip() if shipment.mode == "AIR"
               else trk._sea_key(shipment))
        if not key:
            return
        new_key = trk.normalise_tracking_key(shipment.mode, key)
        new_scac = (shipment.carrier_scac or "").strip().upper()
        key_changed = new_key != t.tracking_key or new_scac != t.carrier_scac
        # Re-register a pending/failed tracking — but ALSO an active one whose
        # keys changed (the common "entered the container number later" fix) or
        # that the provider still can't resolve. Never disturb an arrived or
        # manual shipment (owner 2026-08-06 — a container edit was being ignored
        # because the untracked shipment sat in ACTIVE).
        stuck = t.state == t.State.ACTIVE and trk.health_for(t) == "UNTRACKED"
        if t.state in (t.State.PENDING, t.State.FAILED) or (
                t.state == t.State.ACTIVE and (key_changed or stuck)):
            t.mode = shipment.mode
            t.carrier_scac = new_scac
            t.tracking_key = new_key
            t.raw_status = ""
            t.last_error = ""
            if key_changed:
                t.register_attempts = 0      # a new key gets a fresh budget
            t.state = t.State.PENDING
            t.save()
            trk.register_tracking(t)
    except Exception:                   # pragma: no cover - defensive
        log.exception("tracking (re)registration failed for shipment %s",
                      shipment.id)


def update_shipment_details(shipment, data, actor):
    """Edit a shipment's carrier / routing metadata after it has been booked
    (owner 2026-07-20). Real imports enter the B/L after departure and split an
    order across several shipments, so each shipment's tracking keys must be
    editable and (re)register tracking when they change."""
    from . import tracking as trk
    from .models import Supplier
    if shipment.status == "CLEARED":
        return "This shipment is already cleared — nothing to edit."
    mode = data.get("mode") or shipment.mode
    err = trk.validate_shipment_keys(
        mode, data.get("bl_no", shipment.bl_no),
        data.get("container_awb", shipment.container_awb),
        data.get("carrier_scac", shipment.carrier_scac))
    if err:
        return err
    if "forwarder_id" in data:
        # blank = remove the forwarder (supplier ships on their own PI)
        shipment.forwarder = (Supplier.objects.filter(
            pk=data["forwarder_id"]).first()
            if data.get("forwarder_id") else None)
    shipment.mode = mode
    for f in ("forwarder_name", "vessel_flight", "carrier_scac", "bl_no",
              "container_awb", "tracking_ref"):
        if f in data:
            val = (data.get(f) or "")
            setattr(shipment, f, val.strip().upper() if f == "carrier_scac"
                    else val)
    if "etd" in data:
        shipment.etd = data.get("etd") or None
    if "eta" in data:
        shipment.eta = data.get("eta") or None
    shipment.save()
    audit("document", shipment.order.document_id, "SHIPMENT_UPDATED",
          actor=actor, detail={"shipment": shipment.seq})
    _register_tracking(shipment)
    return None


def delete_shipment(shipment, actor):
    """Delete a booked shipment (admin correction — a duplicate, a test, or a
    wrong booking). Frees its allocated quantities back to the order and drops
    its tracking. Blocked once an IRN has counted it into stock, so inventory
    can't be corrupted (owner 2026-07-20)."""
    from .models import ImportReceipt
    if ImportReceipt.objects.filter(shipment=shipment).exists():
        return ("This shipment has already been received (IRN) — void the "
                "receipt before deleting the shipment.")
    seq = shipment.seq
    order_doc_id = shipment.order.document_id
    # cascades its lines, shipping documents, tracking + tracking events
    shipment.delete()
    audit("document", order_doc_id, "SHIPMENT_DELETED", actor=actor,
          detail={"shipment": seq})
    return None


def set_clearing_charges(shipment, data, actor):
    for f in CHARGE_FIELDS:
        if f in data:
            setattr(shipment, f, _dec(data.get(f)) if data.get(f) not in
                    (None, "") else None)
    shipment.save(update_fields=list(CHARGE_FIELDS))
    audit("document", shipment.order.document_id, "SHIPMENT_CHARGES",
          actor=actor, detail={"shipment": shipment.seq,
                               "total": str(shipment.clearing_total)})


# ---- import-charge payments (forwarder / DO / port / duty) -------------------

def set_shipment_payment(shipment, kind, data, actor):
    """Create or edit a shipment charge (payee, amount, invoice ref) before its
    PYR is raised. The charge itself is a landed cost; this row tracks who it's
    paid to."""
    from .models import ShipmentPayment, Supplier
    if kind not in ShipmentPayment.Kind.values:
        return None, "Unknown charge type."
    payment, _ = ShipmentPayment.objects.get_or_create(
        shipment=shipment, kind=kind, defaults={"created_by": actor})
    if payment.pyr_id:
        return None, "This charge already has a PYR — it can't be edited."
    # A charge is paid EITHER to an agent on file (payee_id) OR directly to a
    # named body — the port, customs — typed as payee_name. The two must never
    # both be set: the supplier FK would silently win over the typed name
    # (owner 2026-08-24, IPR-020's port charge).
    if "payee_id" in data and data.get("payee_id"):
        payment.payee = Supplier.objects.filter(pk=data["payee_id"]).first()
        payment.payee_name = ""
    elif "payee_name" in data and (data.get("payee_name") or "").strip():
        payment.payee_name = (data.get("payee_name") or "").strip()[:160]
        payment.payee = None
    elif "payee_id" in data or "payee_name" in data:
        payment.payee = None
        payment.payee_name = ""
    if "amount" in data:
        payment.amount = _dec(data.get("amount"))
    if "currency" in data:
        payment.currency = (data.get("currency") or "MVR")[:3].upper()
    if "invoice_ref" in data:
        payment.invoice_ref = data.get("invoice_ref") or ""
    if "notes" in data:
        payment.notes = data.get("notes") or ""
    # Forwarder freight is always paid to the shipment's forwarder — no need to
    # re-enter the payee (owner 2026-07-23).
    if (payment.kind == ShipmentPayment.Kind.FREIGHT
            and payment.shipment.forwarder_id):
        payment.payee = payment.shipment.forwarder
        payment.payee_name = ""
    payment.save()
    _mirror_charge_to_landed_cost(payment)
    return payment, None


# Each charge capitalizes into the material's landed cost. The existing
# landed_cost / clearing_total reads the shipment's charge fields, so mirror the
# charge's MVR amount into the field it maps to — this keeps capitalization
# working without changing landed_cost, and never double-counts (the payment is
# the single source; a USD charge converts at the order's agreed rate).
_LANDED_FIELD = {"FREIGHT": "freight", "DO": "agent_charges",
                 "PORT": "port_handling", "DUTY": "customs_duty"}


def _mirror_charge_to_landed_cost(payment):
    field = _LANDED_FIELD.get(payment.kind)
    if not field:
        return
    amt = payment.amount
    if amt is not None and payment.currency != "MVR":
        amt = (amt * payment.shipment.order.exchange_rate).quantize(
            Decimal("0.01"))
    setattr(payment.shipment, field, amt)
    payment.shipment.save(update_fields=[field])


def raise_charge_pyr(payment, actor):
    """Raise a PAYMENT-ONLY PYR to pay this shipment charge to its agent. The
    charge already rides the material's landed cost, so the PYR is capitalized —
    it pays the agent but posts nothing to the cost ledger (owner 2026-07-23)."""
    from datetime import date

    from .models import (CostHead, Document, DocumentLink, DocumentRevision)
    from .payments import create_payment_request
    if payment.pyr_id:
        return None, "A PYR has already been raised for this charge."
    if not payment.amount or payment.amount <= ZERO:
        return None, "Enter the charge amount first."
    if not payment.resolved_payee():
        return None, ("Choose who this charge is paid to first — the agent, "
                      "or the port / customs directly.")
    if not payment.invoice:
        return None, "Upload the agent's invoice before raising the PYR."
    head, _ = CostHead.objects.get_or_create(
        name="Import Charges", defaults={"sort_order": 90})
    site = _ho_site()
    order_doc = payment.shipment.order.document
    with transaction.atomic():
        doc = Document.objects.create(
            doc_type="PYR", ref=next_ref("PYR", site), site=site,
            doc_date=date.today(), status="DRAFT", created_by=actor)
        DocumentRevision.objects.create(document=doc, rev_label="R0",
                                        payload={}, created_by=actor)
        doc.current_revision = doc.revisions.first()
        doc.save(update_fields=["current_revision"])
        pr, err = create_payment_request(doc, {
            "cost_head_id": head.id,
            "amount_requested": str(payment.amount),
            "currency": payment.currency,
            "payee": payment.resolved_payee(),
            "payment_method": "BANK",
            "purpose": (f"{payment.get_kind_display()} — "
                        + ", ".join(o.document.ref
                                    for o in payment.shipment.orders())
                        + f" · {payment.shipment.ref or payment.shipment.seq}"),
            "has_supporting_doc": True,
        }, actor)
        if err:
            transaction.set_rollback(True)
            return None, err
        pr.is_capitalized = True    # payment-only — never from arbitrary input
        pr.save(update_fields=["is_capitalized"])
        DocumentLink.objects.get_or_create(
            from_document=doc, to_document=order_doc,
            link_type="IPR_CHARGE_PYR")
        payment.pyr = doc
        payment.save(update_fields=["pyr", "updated_at"])
        # Submit it straight away — a raised charge goes into the approval queue
        # (no orphan drafts for the user to chase). A capitalized import charge
        # skips the Director (like an accounts-initiated PYR) and clears
        # straight to a Payment Voucher for signatory approval, so routine
        # freight/duty/port payments don't pile on the Director (owner
        # 2026-07-23).
        from .payments import _set_status
        _set_status(doc, "SUBMITTED", "SUBMIT", actor,
                    "Import charge — submitted for approval")
        _set_status(doc, "DIRECTOR_APPROVED", "CLEAR_TO_VOUCHER", actor,
                    "Import charge — authorised on a Payment Voucher "
                    "(no Director step)")
    audit("document", doc.id, "SHIPMENT_CHARGE_PYR", actor=actor,
          detail={"ref": doc.ref, "kind": payment.kind,
                  "shipment": payment.shipment.seq})
    from .notify import notify_document
    notify_document(doc, actor)     # alert whoever now approves it
    return doc, None


def add_shipment_document(shipment, doc_type, upload, actor, notes=""):
    """Attach a typed shipping document. A B/L (or AWB) upload fires
    BL-triggered payment milestones (§5.10.7)."""
    from .models import ShipmentDocument
    doc = ShipmentDocument.objects.create(
        shipment=shipment, doc_type=doc_type, file=upload,
        file_name=upload.name, notes=notes, uploaded_by=actor)
    if doc_type == "BL_AWB":
        for o in shipment.orders():
            fire_milestones(o, "BL", actor)
    return doc


SHARE_ATTACH_CAP = 20 * 1024 * 1024   # most mailboxes bounce past ~25 MB
SHARE_CC_PARAM = "clearance_share_cc"


def share_cc_list():
    """Who is copied on every clearing-agent document share. Editable on the
    Clearance page (owner 2026-08-26: cargoclearance@sandplanet.mv, a
    dedicated group); the env IMPORT_SHARE_CC is only the fallback."""
    from django.conf import settings
    from .models import CompanyParameter
    row = CompanyParameter.objects.filter(key=SHARE_CC_PARAM).first()
    raw = (row.value if row and row.value
           else getattr(settings, "IMPORT_SHARE_CC", ""))
    return [a.strip() for a in str(raw).replace(";", ",").split(",")
            if a.strip()]


def share_with_agent(shipment, actor):
    """Email every shipping document on this shipment to the company's
    clearing agent (owner 2026-08-24: ONE agent company-wide, flagged on the
    supplier). Stamps shared_with_agent_at only when the send succeeds."""
    import mimetypes

    from django.conf import settings
    from django.core.mail import EmailMessage
    from django.utils import timezone

    from .models import Supplier

    agent = Supplier.objects.filter(is_clearing_agent=True,
                                    is_active=True).first()
    if not agent:
        # The likely miss: the supplier was CATEGORISED "Clearing agent" but
        # the company-wide flag was never clicked (happened 2026-08-25).
        candidate = Supplier.objects.filter(category="CLEARING_AGENT",
                                            is_active=True).first()
        if candidate:
            return (f"No clearing agent is set. {candidate.name} is "
                    "categorised as a clearing agent, but the category alone "
                    "isn't enough — open it on the Suppliers page and click "
                    f"\"Make {candidate.name} the clearing agent\".")
        return ("No clearing agent is set. Open Suppliers and mark one "
                "supplier as the clearing agent first.")
    to_addrs = [a.strip() for a in (agent.email or "").replace(";", ",")
                .split(",") if a.strip()]
    if not to_addrs:
        return (f"{agent.name} has no email address on file. Add one on the "
                "supplier before sharing.")
    docs = list(shipment.documents.order_by("doc_type", "id"))
    if not docs:
        return "Upload the shipping documents first — there is nothing to send."

    aboard = shipment.orders()
    refs = ", ".join(o.document.ref for o in aboard)
    suppliers = ", ".join(dict.fromkeys(
        o.supplier.name for o in aboard if o.supplier_id))
    lines = [
        f"Dear {agent.contact_person or agent.name},",
        "",
        f"Please find attached the shipping documents for our import "
        f"shipment {shipment.ref or shipment.seq} ({refs}) for clearance.",
        "",
        f"    Supplier(s) : {suppliers or '-'}",
    ]
    if shipment.vessel_flight:
        lines.append(f"    Vessel / flight : {shipment.vessel_flight}")
    if shipment.bl_no:
        lines.append(f"    B/L no. : {shipment.bl_no}")
    if shipment.container_awb:
        lines.append(f"    Container / AWB : {shipment.container_awb}")
    if shipment.eta:
        lines.append(f"    ETA Male' : {shipment.eta:%d %b %Y}")
    lines += ["", "Documents attached:"]
    lines += [f"    - {d.get_doc_type_display()}: {d.file_name or d.file.name}"
              for d in docs]
    lines += ["",
              "Please proceed with clearance and revert with the duty and "
              "charge figures.",
              "",
              f"Best regards,",
              f"{actor.full_name or actor.username}",
              "Sand Planet Pvt Ltd"]

    reply_to = actor.email or settings.REPLY_TO_FALLBACK
    sender_name = actor.full_name or actor.username
    msg = EmailMessage(
        subject=(f"Shipping documents — {shipment.ref or shipment.seq} "
                 f"({refs})"
                 + (f" ({shipment.container_awb})"
                    if shipment.container_awb else "")),
        body="\n".join(lines),
        from_email=f"{sender_name} <{settings.DEFAULT_FROM_EMAIL}>",
        to=to_addrs,
        cc=share_cc_list(),
        reply_to=[reply_to],
    )
    total = 0
    for d in docs:
        name = d.file_name or d.file.name.rsplit("/", 1)[-1]
        try:
            with d.file.open("rb") as fh:
                content = fh.read()
        except Exception:
            return (f"Could not read the file for "
                    f"{d.get_doc_type_display()} ({name}). Re-upload it and "
                    "try again.")
        total += len(content)
        if total > SHARE_ATTACH_CAP:
            return ("The documents together exceed the 20 MB email limit. "
                    "Replace the largest file with a compressed copy and "
                    "try again.")
        ctype = (mimetypes.guess_type(name)[0]
                 or "application/octet-stream")
        msg.attach(name, content, ctype)
    try:
        msg.send(fail_silently=False)
    except Exception as e:
        return f"The email could not be sent: {e}"
    shipment.shared_with_agent_at = timezone.now()
    shipment.save(update_fields=["shared_with_agent_at"])
    audit("document", shipment.order.document_id, "SHIPMENT_SHARED_AGENT",
          actor=actor,
          detail={"shipment": shipment.seq, "agent": agent.name,
                  "to": to_addrs, "documents": len(docs)})
    return None


# ---- Landed cost + IRN receipt + stock lots (P1B-e) ----------------------

def order_shipments(order):
    """Every shipment carrying this order's cargo — primary-FK ones plus any
    consolidated shipment whose lines span it (owner 2026-08-28)."""
    from .models import ImportShipment
    return (ImportShipment.objects
            .filter(models_q_order(order))
            .distinct().order_by("id"))


def models_q_order(order):
    from django.db.models import Q
    return Q(order=order) | Q(lines__ipr_line__order=order)


def _shipment_goods_split(shipment):
    """MVR goods value aboard, per order — the apportionment base for a
    consolidated shipment's clearing charges (owner 2026-08-28: split by
    goods value). Cross-currency safe: each line converts at ITS order's
    agreed rate."""
    split, total = {}, ZERO
    for sl in shipment.lines.select_related("ipr_line__order"):
        o = sl.ipr_line.order
        v = ((sl.qty or ZERO) * (sl.ipr_line.unit_price or ZERO)
             * o.exchange_rate)
        split[o.id] = split.get(o.id, ZERO) + v
        total += v
    return split, total


def shipment_charge_share(shipment, order):
    """This order's slice of the shipment's clearing charges."""
    charges = shipment.clearing_total
    if not charges:
        return ZERO
    split, total = _shipment_goods_split(shipment)
    if not total or order.id not in split:
        # no lines recorded (legacy whole-order shipment) — all to primary
        return charges if shipment.order_id == order.id else ZERO
    return charges * split[order.id] / total


def landed_cost(order):
    """Per-line landed cost for the order (§5.10.9): goods at the agreed rate
    plus every shipment charge (freight/insurance/duty/GST/clearing…)
    apportioned across the lines by goods value. Returns per-line unit landed
    cost + order totals and the uplift over the order value."""
    rate = order.exchange_rate
    lines = list(order.lines.all())
    goods = {ln.id: (ln.order_qty or ZERO) * (ln.unit_price or ZERO) * rate
             for ln in lines}
    total_goods = sum(goods.values(), ZERO)
    total_charges = sum((shipment_charge_share(sh, order)
                         for sh in order_shipments(order)), ZERO)
    per_line = {}
    for ln in lines:
        g = goods[ln.id]
        share = (total_charges * g / total_goods) if total_goods else ZERO
        line_landed = g + share
        unit = (line_landed / ln.order_qty) if ln.order_qty else ZERO
        per_line[ln.id] = {
            "goods": g.quantize(Decimal("0.01")),
            "charge_share": share.quantize(Decimal("0.01")),
            "line_landed": line_landed.quantize(Decimal("0.01")),
            "unit_landed": unit.quantize(Decimal("0.0001")),
        }
    total_landed = (total_goods + total_charges)
    uplift = ((total_charges / total_goods * 100) if total_goods else ZERO)
    return {
        "lines": per_line,
        "total_goods": total_goods.quantize(Decimal("0.01")),
        "total_charges": total_charges.quantize(Decimal("0.01")),
        "total_landed": total_landed.quantize(Decimal("0.01")),
        "uplift_pct": uplift.quantize(Decimal("0.01")),
    }


@transaction.atomic
def create_receipt(shipment, data, actor):
    """Open an IRN for a shipment — one receipt line per order line, expected
    quantity prefilled from the order."""
    from datetime import date
    from .models import (Document, DocumentRevision, ImportReceipt,
                         ImportReceiptLine)
    order = shipment.order
    doc = Document.objects.create(
        doc_type="IRN", ref=next_ref("IRN", None), site=_ho_site(),
        doc_date=data.get("doc_date") or date.today(), status="DRAFT",
        created_by=actor)
    DocumentRevision.objects.create(document=doc, rev_label="R0", payload={},
                                    created_by=actor)
    doc.current_revision = doc.revisions.first()
    doc.save(update_fields=["current_revision"])
    receipt = ImportReceipt.objects.create(
        document=doc, shipment=shipment, location=data.get("location", ""),
        notes=data.get("notes", ""))
    # Seed one receipt line per item ON THIS SHIPMENT; legacy/whole-order
    # shipments (no allocation) fall back to the full order.
    alloc = list(shipment.lines.select_related("ipr_line").all())
    if alloc:
        for sl in alloc:
            ImportReceiptLine.objects.create(
                receipt=receipt, ipr_line=sl.ipr_line, expected_qty=sl.qty,
                received_qty=sl.qty)
    else:
        for line in order.lines.all():
            ImportReceiptLine.objects.create(
                receipt=receipt, ipr_line=line, expected_qty=line.order_qty,
                received_qty=line.order_qty)
    audit("document", doc.id, "DOC_CREATED", actor=actor, to_state="DRAFT",
          detail={"ref": doc.ref, "shipment": shipment.seq})
    return doc


def save_receipt_counts(receipt, rows, actor):
    by_id = {r.get("id"): r for r in rows}
    for line in receipt.lines.all():
        r = by_id.get(line.id)
        if r is None:
            continue
        line.received_qty = _dec(r.get("received_qty"))
        line.damaged_qty = (_dec(r.get("damaged_qty"))
                            if r.get("damaged_qty") not in (None, "") else None)
        line.condition_note = r.get("condition_note", "")
        line.save(update_fields=["received_qty", "damaged_qty",
                                 "condition_note"])


@transaction.atomic
def post_receipt(irn_doc, actor):
    """Post the IRN: create stock lots at unit landed cost, splitting each
    line's received quantity across its IPR allocations (reserved projects +
    general stock). A count discrepancy notifies the Director."""
    from datetime import date
    from .models import StockLot
    receipt = irn_doc.import_receipt
    order = receipt.order
    lc = landed_cost(order)
    discrepancy = False
    for rline in receipt.lines.select_related("ipr_line").all():
        received = rline.received_qty or ZERO
        if rline.variance != ZERO or (rline.damaged_qty or ZERO) > ZERO:
            discrepancy = True
        if received <= ZERO:
            continue
        ipr_line = rline.ipr_line
        unit = lc["lines"].get(ipr_line.id, {}).get("unit_landed", ZERO)
        order_qty = ipr_line.order_qty or ZERO
        allocs = list(ipr_line.allocations.all())
        assigned = ZERO
        for i, alloc in enumerate(allocs):
            if i == len(allocs) - 1:
                qty = received - assigned          # remainder to the last
            else:
                qty = (received * alloc.qty / order_qty).quantize(
                    Decimal("0.01")) if order_qty else ZERO
                assigned += qty
            if qty <= ZERO:
                continue
            StockLot.objects.create(
                item=ipr_line.item, free_text_desc=ipr_line.free_text_desc,
                unit=ipr_line.unit, source_receipt=receipt,
                source_ipr_line=ipr_line, project=alloc.project,
                qty_received=qty, qty_on_hand=qty, unit_landed_cost=unit,
                location=receipt.location, received_date=date.today())
    irn_doc.status = "RECEIVED"
    irn_doc.save(update_fields=["status", "updated_at"])
    # the shipment is cleared/received once counted at the store
    if receipt.shipment.status != "CLEARED":
        receipt.shipment.status = "CLEARED"
        receipt.shipment.save(update_fields=["status"])
    audit("document", irn_doc.id, "IRN_POSTED", actor=actor,
          to_state="RECEIVED", detail={"ref": irn_doc.ref})
    if discrepancy:
        from .models import User
        from .notify import notify_user
        for director in User.objects.filter(role="DIRECTOR", is_active=True):
            notify_user(director,
                        f"IRN {irn_doc.ref} received with a discrepancy",
                        body=f"{order.document.ref} · {order.supplier.name}",
                        doc=irn_doc, category="alert")


def store_lots(project_id=None, in_stock_only=True):
    from .models import StockLot
    qs = StockLot.objects.select_related(
        "item", "project__site", "source_receipt__document").all()
    if in_stock_only:
        qs = qs.filter(qty_on_hand__gt=0)
    if project_id:
        qs = qs.filter(project_id=project_id)
    return qs


@transaction.atomic
def receive_opening_stock(lines, actor, received_date=None):
    """Seed the HO store with existing / opening stock — one valued StockLot
    per line at its stated unit cost, with no import origin. It is a company
    asset from day one and becomes project cost only when later issued to a
    site and received there (owner 2026-07-14)."""
    from datetime import date

    from .models import Item, Project, StockLot
    rows = []
    for i, ln in enumerate(lines or [], 1):
        if not ln.get("item_id"):
            return None, f"Line {i}: choose a catalog item."
        qty = _dec(ln.get("qty"))
        if qty <= ZERO:
            return None, f"Line {i}: quantity must be greater than zero."
        cost = _dec(ln.get("unit_cost"))
        if cost < ZERO:
            return None, f"Line {i}: unit cost cannot be negative."
        try:
            item = Item.objects.get(pk=ln["item_id"])
        except Item.DoesNotExist:
            return None, f"Line {i}: item not found."
        project = None
        if ln.get("project_id"):
            try:
                project = Project.objects.get(pk=ln["project_id"])
            except Project.DoesNotExist:
                return None, f"Line {i}: project not found."
        note = (ln.get("note") or "").strip()
        rows.append((item, qty, cost, project, ln.get("location") or "", note))
    if not rows:
        return None, "Add at least one stock line."
    rdate = received_date or date.today()
    created = []
    for item, qty, cost, project, location, note in rows:
        origin = "Opening stock" + (f" · {note}" if note else "")
        created.append(StockLot.objects.create(
            item=item, unit=item.unit, project=project,
            qty_received=qty, qty_on_hand=qty, unit_landed_cost=cost,
            location=location, received_date=rdate, origin_note=origin[:120]))
    total = sum((lot.qty_on_hand * lot.unit_landed_cost for lot in created),
                ZERO)
    audit("stock_lot", created[0].id, "OPENING_STOCK_RECEIVED", actor=actor,
          detail={"lots": len(created), "value": str(total)})
    return {"lots": len(created), "total_value": total}, None


# ---- SIN — store issue to site (P1B-f) -----------------------------------

def pick_lots_fifo(item, project, qty):
    """Choose lots to satisfy `qty` of an item, FIFO within a reservation:
    the project's reserved lots first (oldest first), then general stock.
    Returns [(lot, take_qty)] or (None, error)."""
    from .models import StockLot
    need = _dec(qty)
    if need <= ZERO:
        return None, "Quantity must be greater than zero."
    reserved = StockLot.objects.filter(item=item, project=project,
                                       qty_on_hand__gt=0).order_by(
        "received_date", "id") if project else StockLot.objects.none()
    general = StockLot.objects.filter(item=item, project__isnull=True,
                                      qty_on_hand__gt=0).order_by(
        "received_date", "id")
    picks, remaining = [], need
    for lot in list(reserved) + list(general):
        if remaining <= ZERO:
            break
        take = min(lot.qty_on_hand, remaining)
        if take > ZERO:
            picks.append((lot, take))
            remaining -= take
    if remaining > ZERO:
        return None, f"Not enough stock — short {remaining} of {need}."
    return picks, None


@transaction.atomic
def create_store_issue(to_site, to_project, rows, actor, notes=""):
    """Open a SIN issuing chosen lots to a site. `rows` = [{lot_id, qty}].
    Validates each quantity against the lot's on-hand balance."""
    from datetime import date

    from .models import (Document, DocumentRevision, StockLot, StoreIssue,
                         StoreIssueLine)
    cleaned = []
    for r in rows or []:
        lot = StockLot.objects.filter(pk=r.get("lot_id")).first()
        if not lot:
            return None, "One or more lots are unknown."
        qty = _dec(r.get("qty"))
        if qty <= ZERO:
            return None, f"{lot.description}: quantity must be greater than zero."
        if qty > lot.qty_on_hand:
            return None, (f"{lot.description}: only {lot.qty_on_hand} on hand, "
                          f"cannot issue {qty}.")
        cleaned.append((lot, qty))
    if not cleaned:
        return None, "Add at least one lot to issue."
    doc = Document.objects.create(
        doc_type="SIN", ref=next_ref("SIN", None), site=_ho_site(),
        doc_date=date.today(), status="DRAFT", created_by=actor)
    DocumentRevision.objects.create(document=doc, rev_label="R0", payload={},
                                    created_by=actor)
    doc.current_revision = doc.revisions.first()
    doc.save(update_fields=["current_revision"])
    issue = StoreIssue.objects.create(document=doc, to_site=to_site,
                                      to_project=to_project, notes=notes)
    for lot, qty in cleaned:
        StoreIssueLine.objects.create(issue=issue, lot=lot, qty=qty,
                                      unit_landed_cost=lot.unit_landed_cost)
    audit("document", doc.id, "DOC_CREATED", actor=actor, to_state="DRAFT",
          detail={"ref": doc.ref, "to_site": to_site.code})
    return doc, None


@transaction.atomic
def issue_store_issue(sin_doc, actor):
    """Post the SIN: move each lot's issued quantity from on-hand to in-transit
    (it has physically left the store; project cost lands at the site GRN)."""
    from django.utils import timezone
    issue = sin_doc.store_issue
    for line in issue.lines.select_related("lot"):
        lot = line.lot
        if line.qty > lot.qty_on_hand:
            return (f"{lot.description}: only {lot.qty_on_hand} on hand now — "
                    "re-open the SIN.")
        lot.qty_on_hand -= line.qty
        lot.qty_in_transit = (lot.qty_in_transit or ZERO) + line.qty
        lot.save(update_fields=["qty_on_hand", "qty_in_transit"])
    issue.issued_by = actor
    issue.issued_at = timezone.now()
    issue.save(update_fields=["issued_by", "issued_at"])
    sin_doc.status = "ISSUED"
    sin_doc.save(update_fields=["status", "updated_at"])
    audit("document", sin_doc.id, "SIN_ISSUED", actor=actor, to_state="ISSUED",
          detail={"ref": sin_doc.ref})
    return None


def cancel_store_issue(sin_doc, actor):
    if sin_doc.status != "DRAFT":
        return "Only a draft SIN can be cancelled."
    sin_doc.status = "CANCELLED"
    sin_doc.save(update_fields=["status", "updated_at"])
    audit("document", sin_doc.id, "SIN_CANCELLED", actor=actor,
          to_state="CANCELLED", detail={"ref": sin_doc.ref})
    return None


def receive_store_issue_line(sil, qty, to_site, document, actor):
    """Receive `qty` of a store-issued line at site — the import cost event
    (§5.10.11): post INCURRED at landed cost, clear the lot's in-transit
    balance, and advance the SIN once all its lines are received. Idempotent
    via received_qty, so a GRN receipt and a direct SIN receipt never
    double-post (P1B-f3). Returns the amount posted."""
    from . import costing
    from .models import CostHead
    remaining = (sil.qty or ZERO) - (sil.received_qty or ZERO)
    take = min(_dec(qty), remaining) if remaining > ZERO else ZERO
    if take <= ZERO:
        return ZERO
    lot = sil.lot
    lot.qty_in_transit = max(ZERO, (lot.qty_in_transit or ZERO) - take)
    lot.save(update_fields=["qty_in_transit"])
    sil.received_qty = (sil.received_qty or ZERO) + take
    sil.save(update_fields=["received_qty"])
    amount = (take * sil.unit_landed_cost).quantize(Decimal("0.01"))
    if amount > ZERO:
        costing.post(site=to_site, cost_head=CostHead.objects.get(
            name="Materials"), state="INCURRED", source="STORE_ISSUE",
            amount=amount, document=document, actor=actor)
    sin = sil.issue
    if all((ln.received_qty or ZERO) >= (ln.qty or ZERO)
           for ln in sin.lines.all()):
        doc = sin.document
        if doc.status == "ISSUED":
            doc.status = "RECEIVED"
            doc.save(update_fields=["status", "updated_at"])
            audit("document", doc.id, "SIN_RECEIVED", actor=actor,
                  to_state="RECEIVED", detail={"ref": doc.ref,
                                               "via": document.ref})
    return amount


@transaction.atomic
def receive_store_issue(sin_doc, actor):
    """Direct receipt of a whole SIN (for store issues not carried on an LM) —
    receives every remaining line. Store issues loaded onto a Loading Manifest
    are received on the site GRN instead (P1B-f3)."""
    if sin_doc.status != "ISSUED":
        return "Only an issued SIN can be received."
    for line in sin_doc.store_issue.lines.select_related("lot"):
        remaining = (line.qty or ZERO) - (line.received_qty or ZERO)
        if remaining > ZERO:
            receive_store_issue_line(line, remaining, sin_doc.store_issue.to_site,
                                     sin_doc, actor)
    return None


def loadable_store_lines(lm):
    """Issued SIN lines bound for the LM's site, not yet loaded onto a live LM
    nor received — available to load onto this manifest (P1B-f3)."""
    from django.db.models import F

    from .models import DocumentLine, StoreIssueLine
    on_lm = set(DocumentLine.objects.filter(
        store_issue_line__isnull=False, revision__document__doc_type="LM",
        revision__document__is_void=False).values_list(
        "store_issue_line_id", flat=True))
    qs = StoreIssueLine.objects.filter(
        issue__document__doc_type="SIN", issue__document__status="ISSUED",
        issue__to_site=lm.site).select_related(
        "lot__item", "issue__document").exclude(
        id__in=on_lm).filter(received_qty__lt=F("qty"))
    return list(qs)


@transaction.atomic
def load_store_issues_onto_lm(lm, actor):
    """Append every loadable store-issued line for the LM's site to the
    manifest as store lines (P1B-f3)."""
    from django.db.models import Max

    from .models import DocumentLine
    lines = loadable_store_lines(lm)
    if not lines:
        return 0
    rev = lm.current_revision
    start = rev.lines.aggregate(m=Max("line_no"))["m"] or 0
    for i, sil in enumerate(lines, 1):
        remaining = (sil.qty or ZERO) - (sil.received_qty or ZERO)
        DocumentLine.objects.create(
            revision=rev, line_no=start + i, item=sil.lot.item,
            free_text_desc=sil.lot.free_text_desc, unit=sil.lot.unit,
            qty_loaded=remaining, qty_pending=ZERO,
            fulfil_source="STORE", store_issue_line=sil)
    audit("document", lm.id, "LM_STORE_LOADED", actor=actor,
          detail={"ref": lm.ref, "lines": len(lines)})
    return len(lines)


# ---- MR fulfilment from store (P1B-f2) -----------------------------------

def mr_store_availability(mr):
    """Per MR line, how much of the item is on hand in the HO store —
    reserved to the MR's project first, then general stock (owner 2026-07-13)."""
    from .models import StockLot
    rev = mr.current_revision
    project = mr.project
    out = {}
    for ln in rev.lines.all():
        if not ln.item_id:
            out[ln.id] = ZERO
            continue
        qs = StockLot.objects.filter(item_id=ln.item_id, qty_on_hand__gt=0)
        avail = ZERO
        for lot in qs:
            if lot.project_id in ((project.id if project else None), None):
                avail += lot.qty_on_hand
        out[ln.id] = avail
    return out


@transaction.atomic
def fulfil_mr_from_store(mr, line_ids, actor):
    """Issue a SIN drawing the chosen MR lines' order quantities from store
    stock (FIFO), mark those lines store-fulfilled, and link SIN↔MR."""
    from .models import DocumentLink
    wanted = set(line_ids or [])
    lines = [ln for ln in mr.current_revision.lines.all()
             if ln.id in wanted and ln.item_id]
    if not lines:
        return None, "Select at least one catalog-item line to fulfil from store."
    rows, picked = [], []
    for ln in lines:
        qty = ln.qty_to_order or ZERO
        if qty <= ZERO:
            continue
        picks, err = pick_lots_fifo(ln.item, mr.project, qty)
        if err:
            return None, f"{ln.item.description}: {err}"
        for lot, take in picks:
            rows.append({"lot_id": lot.id, "qty": take})
        picked.append(ln)
    if not rows:
        return None, "Nothing to issue — the selected lines have no order qty."
    doc, err = create_store_issue(mr.site, mr.project, rows, actor,
                                  notes=f"Store issue for {mr.ref}")
    if err:
        return None, err
    issue_store_issue(doc, actor)
    for ln in picked:
        ln.fulfil_source = "STORE"
        ln.save(update_fields=["fulfil_source"])
    DocumentLink.objects.get_or_create(from_document=doc, to_document=mr,
                                       link_type="MR_SIN")
    return doc, None
