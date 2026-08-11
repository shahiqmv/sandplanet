"""Bill of Materials — the per-project QUANTITY budget and its variance
(owner 2026-08-11). The BOM is the material control document: the procurement
planner and MRs source from it, and at any point the variance shows, per
catalogue item, how much the project has requested (MR), ordered (awarded
domestic quotes + authorised import allocations) and issued from site stock —
including anything procured OUTSIDE the BOM.

Quantities only — money control stays with the cost ledger / claims."""
from collections import defaultdict
from decimal import Decimal

from django.db.models import F

from .audit import audit
from .models import (BomItem, DocumentLine, ImportAllocation, Item,
                     QuotationLine, StockMovement)

ZERO = Decimal("0")

# MR statuses that count as live demand (draft/cancelled/returned don't).
_MR_DEAD = ("DRAFT", "CANCELLED")
# PR statuses whose awarded quote lines count as ordered.
_PR_ORDERED = ("APPROVED", "PAYMENT_PROCESSING", "PAID_PO_ISSUED")
# IPR statuses whose allocations count as ordered.
_IPR_ORDERED = ("AUTHORISED", "CLOSED")


def _dec(v):
    try:
        return Decimal(str(v))
    except Exception:
        return ZERO


def _strip_section(desc):
    """Build-up descriptions may carry a '[SECTION] ' prefix (the BOQ loader
    keeps the sheet's section for readability) — the BOM aggregates on the
    bare description."""
    d = (desc or "").strip()
    if d.startswith("[") and "]" in d:
        d = d.split("]", 1)[1].strip()
    return d


def seed_from_boq(project):
    """Draft BOM rows from the unit BOQ's per-unit build-ups: every detail
    work × its category's unit count, aggregated by (description, unit).
    Returns review rows — nothing is written until the QS maps items and
    commits. A conventional BOQ (work-scope lines, not materials) returns
    none — the BOM is entered manually there."""
    boq = getattr(project, "boq", None)
    if not boq or boq.mode != "UNIT":
        return []
    agg = {}
    for cat in boq.categories.filter(is_lump=False).prefetch_related("items"):
        cat_qty = _dec(cat.qty)
        if cat_qty <= ZERO:
            continue
        for it in cat.items.all():
            qty = _dec(it.qty)
            if qty <= ZERO:
                continue
            desc = _strip_section(it.description)
            if not desc:
                continue
            key = (desc.lower(), (it.unit or "").strip().lower())
            row = agg.setdefault(key, {
                "description": desc, "unit": (it.unit or "").strip(),
                "qty": ZERO, "models": 0})
            row["qty"] += qty * cat_qty
            row["models"] += 1
    rows = sorted(agg.values(), key=lambda r: r["description"].lower())
    # suggest catalogue matches so mapping is one click where possible
    for r in rows:
        match = Item.objects.filter(description__iexact=r["description"],
                                    is_active=True,
                                    merged_into__isnull=True).first()
        r["item_id"] = match.id if match else None
        r["item_code"] = match.code if match else ""
        r["qty"] = str(r["qty"])
    return rows


def save_bom(project, rows, actor):
    """Replace the project's BOM with the reviewed rows:
    [{item_id, qty, source?, remarks?}]. Rows without a mapped item are
    refused — the BOM is the Item-Master-keyed budget the whole chain joins
    on. Returns (count, error)."""
    clean = []
    seen = set()
    for r in rows or []:
        item_id = r.get("item_id")
        qty = _dec(r.get("qty"))
        if not item_id:
            return None, ("Every BOM row must be mapped to an Item-Master "
                          "code — unmapped rows can't be tracked.")
        if qty <= ZERO:
            return None, "BOM quantities must be positive."
        if item_id in seen:
            return None, "The same item appears twice — combine the rows."
        seen.add(item_id)
        clean.append(r)
    items = {i.id: i for i in Item.objects.filter(
        id__in=[r["item_id"] for r in clean])}
    if len(items) != len(clean):
        return None, "Unknown item in the BOM rows."
    project.bom_items.all().delete()
    BomItem.objects.bulk_create([
        BomItem(project=project, item=items[r["item_id"]],
                qty=_dec(r["qty"]),
                source=(r.get("source") or "MANUAL")[:6],
                remarks=(r.get("remarks") or "")[:200],
                created_by=actor)
        for r in clean])
    audit("project", project.id, "BOM_SAVED", actor=actor,
          detail={"rows": len(clean)})
    return len(clean), None


def _sum_by_item(pairs):
    out = defaultdict(lambda: ZERO)
    for item_id, qty in pairs:
        if item_id and qty:
            out[item_id] += qty
    return out


def requested_by_item(project):
    """Live MR demand: qty_to_order on the current revision of every
    non-draft, non-cancelled MR raised for this project."""
    lines = (DocumentLine.objects
             .filter(revision__document__doc_type="MR",
                     revision__document__project=project,
                     revision__document__current_revision_id=F("revision_id"),
                     item__isnull=False)
             .exclude(revision__document__status__in=_MR_DEAD)
             .exclude(revision__document__is_void=True)
             .values_list("item_id", "qty_to_order"))
    return _sum_by_item((i, _dec(q)) for i, q in lines)


def ordered_by_item(project):
    """Committed orders: awarded domestic quote lines (via their matched MR
    line's project) on approved PRs, plus authorised import allocations."""
    dom = (QuotationLine.objects
           .filter(awarded=True,
                   mr_line__item__isnull=False,
                   mr_line__revision__document__project=project,
                   quotation__document__status__in=_PR_ORDERED)
           .exclude(quotation__document__is_void=True)
           .values_list("mr_line__item_id", "qty"))
    imp = (ImportAllocation.objects
           .filter(project=project, line__item__isnull=False,
                   line__order__document__status__in=_IPR_ORDERED)
           .exclude(line__order__document__is_void=True)
           .values_list("line__item_id", "qty"))
    out = _sum_by_item((i, _dec(q)) for i, q in dom)
    for item_id, qty in _sum_by_item((i, _dec(q)) for i, q in imp).items():
        out[item_id] += qty
    return out


def issued_by_item(project):
    """Site-stock issues charged to this project (manual issues + DPR-reported
    consumption; ISSUE movements are negative, so flip the sign)."""
    rows = (StockMovement.objects
            .filter(project=project, kind=StockMovement.Kind.ISSUE)
            .values_list("item_id", "qty"))
    return _sum_by_item((i, -_dec(q)) for i, q in rows)


def variance(project):
    """The control report: one row per item touched by the BOM or by any
    activity, split into on-BOM rows (with the variance against budget) and
    OFF-BOM rows (procured/issued with no budget line at all)."""
    bom = {b.item_id: b for b in
           project.bom_items.select_related("item").all()}
    requested = requested_by_item(project)
    ordered = ordered_by_item(project)
    issued = issued_by_item(project)
    item_ids = set(bom) | set(requested) | set(ordered) | set(issued)
    items = {i.id: i for i in Item.objects.filter(id__in=item_ids)}
    on_bom, off_bom = [], []
    for item_id in item_ids:
        it = items.get(item_id)
        if it is None:
            continue
        b = bom.get(item_id)
        row = {
            "item_id": item_id, "code": it.code,
            "description": it.description, "unit": it.unit,
            "bom_qty": b.qty if b else None,
            "requested": requested.get(item_id, ZERO),
            "ordered": ordered.get(item_id, ZERO),
            "issued": issued.get(item_id, ZERO),
            "remarks": b.remarks if b else "",
            "source": b.source if b else None,
        }
        if b:
            row["variance"] = b.qty - row["ordered"]     # +ve = budget left
            row["over"] = row["ordered"] > b.qty
            on_bom.append(row)
        else:
            row["variance"] = None
            row["over"] = True                            # all off-BOM is over
            off_bom.append(row)
    on_bom.sort(key=lambda r: r["code"])
    off_bom.sort(key=lambda r: r["code"])
    return {"rows": on_bom, "off_bom": off_bom,
            "totals": {
                "bom_items": len(on_bom),
                "off_bom_items": len(off_bom),
                "over_count": sum(1 for r in on_bom if r["over"])
                              + len(off_bom)}}


def bom_balance(project, item):
    """Remaining orderable balance for one item — BOM qty less committed
    orders. None = the item isn't on the BOM at all (an off-BOM order)."""
    b = project.bom_items.filter(item=item).first()
    if b is None:
        return None
    return b.qty - ordered_by_item(project).get(item.id, ZERO)
