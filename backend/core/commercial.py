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
    """Map a spreadsheet header cell to a canonical BOQ field key."""
    key = str(h or "").strip().lower()
    return {
        "section": "section", "bill": "section", "trade": "section",
        "code": "item_code", "item": "item_code", "item code": "item_code",
        "ref": "item_code", "no": "item_code", "item no": "item_code",
        "description": "description", "desc": "description",
        "unit": "unit", "uom": "unit",
        "qty": "qty", "quantity": "qty",
        "rate": "rate", "price": "rate", "unit rate": "rate",
    }.get(key, "")


def _row_items(boq, rows):
    """Turn cleaned dict rows into (unsaved) BoqItem instances. A row with no
    qty, rate or unit is treated as a heading/preamble line."""
    from .models import BoqItem
    out = []
    for i, r in enumerate(rows):
        desc = str(r.get("description") or "").strip()
        section = str(r.get("section") or "").strip()
        code = str(r.get("item_code") or "").strip()
        unit = str(r.get("unit") or "").strip()
        if not (desc or section or code):
            continue
        qty, rate = _dec(r.get("qty")), _dec(r.get("rate"))
        is_heading = bool(r.get("is_heading")) or (
            qty is None and rate is None and not unit)
        out.append(BoqItem(
            boq=boq, sort_order=i, section=section, item_code=code,
            description=desc, unit=unit, qty=qty, rate=rate,
            is_heading=is_heading))
    return out


def set_boq_items(project, rows, actor):
    """Replace the project's BOQ lines. Creates the BOQ on first save; blocked
    once it's locked (a claim has started). Returns (boq, error)."""
    from .models import Boq
    boq, _ = Boq.objects.get_or_create(
        project=project, defaults={"created_by": actor})
    if boq.is_locked:
        return None, "The BOQ is locked — a claim has already started."
    items = _row_items(boq, rows)
    boq.items.all().delete()
    from .models import BoqItem
    BoqItem.objects.bulk_create(items)
    audit("project", project.id, "BOQ_SAVED", actor=actor,
          detail={"items": len(items), "total": str(boq.total)})
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
