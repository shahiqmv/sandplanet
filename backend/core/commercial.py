"""Project commercial — the QS side: BOQ → variations → progress claims.

This is the client-revenue counterpart to the cost-control ledger: the QS
prices the contract (BOQ), values work done progressively, and claims it from
the client. Slice 1 is the BOQ itself.
"""
from decimal import Decimal, InvalidOperation

from .audit import audit

ZERO = Decimal("0")


def _dec(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def normalise_header(h):
    """Map a spreadsheet header cell to a canonical BOQ field key. Supply
    (material) and installation (labour) rates map to distinct keys; a lone
    'rate'/'total' column maps to the combined rate."""
    key = str(h or "").strip().lower()
    return {
        "section": "section", "bill": "section", "trade": "section",
        "code": "item_code", "item": "item_code", "item code": "item_code",
        "ref": "item_code", "no": "item_code", "item no": "item_code",
        "description": "description", "desc": "description",
        "unit": "unit", "uom": "unit",
        "qty": "qty", "quantity": "qty",
        "material": "rate_supply", "supply": "rate_supply",
        "supply rate": "rate_supply", "material rate": "rate_supply",
        "labor": "rate_install", "labour": "rate_install",
        "install": "rate_install", "installation": "rate_install",
        "install rate": "rate_install", "labour rate": "rate_install",
        "rate": "rate_combined", "price": "rate_combined",
        "unit rate": "rate_combined", "total": "rate_combined",
        "total rate": "rate_combined",
    }.get(key, "")


def _row_items(boq, rows):
    """Turn cleaned dict rows into (unsaved) BoqItem instances. A supply/labour
    split is used when either is present; a lone combined rate goes on the
    supply leg. A row with no qty, rate or unit is treated as a heading."""
    from .models import BoqItem
    out = []
    for i, r in enumerate(rows):
        desc = str(r.get("description") or "").strip()
        section = str(r.get("section") or "").strip()
        code = str(r.get("item_code") or "").strip()
        unit = str(r.get("unit") or "").strip()
        if not (desc or section or code):
            continue
        qty = _dec(r.get("qty"))
        supply = _dec(r.get("rate_supply"))
        install = _dec(r.get("rate_install"))
        if supply is None and install is None:
            supply = _dec(r.get("rate_combined"))   # combined rate → supply leg
        has_rate = supply is not None or install is not None
        is_heading = bool(r.get("is_heading")) or (
            qty is None and not has_rate and not unit)
        out.append(BoqItem(
            boq=boq, sort_order=i, section=section, item_code=code,
            description=desc, unit=unit, qty=qty, rate_supply=supply,
            rate_install=install, is_heading=is_heading))
    return out


def set_boq_items(project, rows, actor):
    """Replace the project's BOQ lines. Creates the BOQ on first save; blocked
    once it's locked (a claim has started). Records whether the schedule prices
    supply and installation separately. Returns (boq, error)."""
    from .models import Boq, BoqItem
    boq, _ = Boq.objects.get_or_create(
        project=project, defaults={"created_by": actor})
    if boq.is_locked:
        return None, "The BOQ is locked — a claim has already started."
    items = _row_items(boq, rows)
    split = any(i.rate_install is not None for i in items)
    boq.items.all().delete()
    BoqItem.objects.bulk_create(items)
    if boq.split_rates != split:
        boq.split_rates = split
        boq.save(update_fields=["split_rates"])
    audit("project", project.id, "BOQ_SAVED", actor=actor,
          detail={"items": len(items), "total": str(boq.total),
                  "split": split})
    return boq, None


def import_boq_rows(project, rows, actor):
    """Import BOQ rows (already parsed from the uploaded sheet)."""
    return set_boq_items(project, rows, actor)


def set_boq_lock(project, locked, actor):
    from .models import Boq
    boq = getattr(project, "boq", None)
    if boq is None:
        return None, "There's no BOQ to lock yet."
    boq.is_locked = bool(locked)
    boq.save(update_fields=["is_locked"])
    audit("project", project.id,
          "BOQ_LOCKED" if locked else "BOQ_UNLOCKED", actor=actor)
    return boq, None
