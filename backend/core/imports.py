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


def _post_split(order, doc, state, fraction, rate, actor, milestone=None):
    """Post `state` rows for a fraction (0..1) of the order at `rate` MVR, split
    the same way the order is allocated: each project allocation to that
    project's site under the line's cost head; the general-stock balance to the
    General Stock pool (never a project). Shared by commitment and payment."""
    gs_head = costing.head("General Stock")
    ho = _ho_site()
    for line in order.lines.all():
        unit_mvr = (line.unit_price or ZERO) * rate
        for alloc in line.allocations.select_related("project__site"):
            amount = (alloc.qty * unit_mvr * fraction).quantize(Decimal("0.01"))
            if amount <= ZERO:
                continue
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


def authorise_ipr(doc, actor):
    """Commit the order when a signatory authorises it on a voucher (§6C.2).
    Posts COMMITTED in MVR at the agreed rate across the order's allocations."""
    order = doc.import_order
    _post_split(order, doc, "COMMITTED", Decimal("1"), order.exchange_rate,
                actor)


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
        cleaned.append({"label": label,
                        "trigger": r.get("trigger") or "BALANCE",
                        "percent": pct, "fixed_amount": fixed,
                        "due_date": r.get("due_date") or None})
    if abs(scheduled.quantize(Decimal("0.01")) - total.quantize(
            Decimal("0.01"))) > Decimal("0.01"):
        return (f"The schedule ({scheduled.quantize(Decimal('0.01'))}) must "
                f"sum to the order total ({total.quantize(Decimal('0.01'))} "
                f"{order.order_currency}).")
    order.milestones.exclude(status="PAID").delete()
    for i, c in enumerate(cleaned, 1):
        ImportPaymentMilestone.objects.create(order=order, seq=i, **c)
    return None


def mark_milestone_due(milestone, actor):
    """Purchasing flags a milestone due (its trigger has been met) — it then
    enters Finance's import-payments queue."""
    if milestone.status != "PENDING":
        return "Only a pending milestone can be marked due."
    milestone.status = "DUE"
    milestone.save(update_fields=["status"])
    audit("document", milestone.order.document_id, "IPR_MILESTONE_DUE",
          actor=actor, detail={"milestone": milestone.label})
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
    """Overseas TT milestones in Finance's queue: DUE ones (awaiting voucher
    authorisation) and AUTHORISED ones (voucher-approved, ready for the TT)."""
    from .models import ImportPaymentMilestone
    return ImportPaymentMilestone.objects.filter(
        status__in=("DUE", "AUTHORISED"),
        order__document__status="AUTHORISED").select_related(
        "order__document", "order__supplier", "voucher")


# ---- Shipments + shipping documents (P1B-d) ------------------------------

REQUIRED_FOR_CLEARING = ["BL_AWB", "PACKING_LIST", "COMMERCIAL_INVOICE"]
CHARGE_FIELDS = ("freight", "insurance", "customs_duty", "import_gst",
                 "port_handling", "agent_charges", "local_transport")


def fire_milestones(order, trigger, actor):
    """A shipping event met a trigger — move matching pending milestones to DUE
    so they enter Finance's queue (§5.10.7)."""
    fired = []
    for m in order.milestones.filter(trigger=trigger, status="PENDING"):
        m.status = "DUE"
        m.save(update_fields=["status"])
        fired.append(m)
    if fired:
        audit("document", order.document_id, "IPR_MILESTONES_FIRED",
              actor=actor, detail={"trigger": trigger,
                                   "milestones": [m.label for m in fired]})
    return fired


def create_shipment(order, data, actor):
    from .models import ImportShipment, Supplier
    seq = (order.shipments.count() or 0) + 1
    forwarder = None
    if data.get("forwarder_id"):
        forwarder = Supplier.objects.filter(pk=data["forwarder_id"]).first()
    return ImportShipment.objects.create(
        order=order, seq=seq, mode=(data.get("mode") or "SEA"),
        forwarder=forwarder, forwarder_name=data.get("forwarder_name", ""),
        vessel_flight=data.get("vessel_flight", ""),
        container_awb=data.get("container_awb", ""),
        etd=data.get("etd") or None, eta=data.get("eta") or None,
        tracking_ref=data.get("tracking_ref", ""),
        carrier_link=data.get("carrier_link", ""),
        notes=data.get("notes", ""), created_by=actor)


def missing_clearing_docs(shipment):
    have = set(shipment.documents.values_list("doc_type", flat=True))
    return [d for d in REQUIRED_FOR_CLEARING if d not in have]


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
    if to_status == "ARRIVED":
        fire_milestones(shipment.order, "ARRIVAL", actor)
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


def add_shipment_document(shipment, doc_type, upload, actor, notes=""):
    """Attach a typed shipping document. A B/L (or AWB) upload fires
    BL-triggered payment milestones (§5.10.7)."""
    from .models import ShipmentDocument
    doc = ShipmentDocument.objects.create(
        shipment=shipment, doc_type=doc_type, file=upload,
        file_name=upload.name, notes=notes, uploaded_by=actor)
    if doc_type == "BL_AWB":
        fire_milestones(shipment.order, "BL", actor)
    return doc


def share_with_agent(shipment, actor):
    from django.utils import timezone
    shipment.shared_with_agent_at = timezone.now()
    shipment.save(update_fields=["shared_with_agent_at"])
    audit("document", shipment.order.document_id, "SHIPMENT_SHARED_AGENT",
          actor=actor, detail={"shipment": shipment.seq})


# ---- Landed cost + IRN receipt + stock lots (P1B-e) ----------------------

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
    total_charges = sum((s.clearing_total for s in order.shipments.all()),
                        ZERO)
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
    for line in order.lines.all():
        ImportReceiptLine.objects.create(
            receipt=receipt, ipr_line=line, expected_qty=line.order_qty,
            received_qty=line.order_qty)
    audit("document", doc.id, "DOC_CREATED", actor=actor, to_state="DRAFT",
          detail={"ref": doc.ref, "shipment": shipment.seq})
    return doc


def save_receipt_counts(receipt, rows, actor):
    from .models import ImportReceiptLine
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
