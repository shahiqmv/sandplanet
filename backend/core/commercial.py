"""Project commercial — the QS side: BOQ → variations → progress claims.

This is the client-revenue counterpart to the cost-control ledger: the QS
prices the contract (BOQ), values work done progressively, and claims it from
the client. Slice 1 is the BOQ itself.
"""
from decimal import Decimal, InvalidOperation

from django.db.models import Max

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


# ---- Variations (VOs) ----------------------------------------------------

def _variation_items(variation, rows):
    from .models import VariationItem
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
            supply = _dec(r.get("rate_combined"))
        has_rate = supply is not None or install is not None
        is_heading = bool(r.get("is_heading")) or (
            qty is None and not has_rate and not unit)
        out.append(VariationItem(
            variation=variation, sort_order=i, section=section, item_code=code,
            description=desc, unit=unit, qty=qty, rate_supply=supply,
            rate_install=install, is_heading=is_heading))
    return out


def create_variation(project, data, actor):
    from .models import Variation
    seq = (project.variations.aggregate(m=Max("seq"))["m"] or 0) + 1
    v = Variation.objects.create(
        project=project, seq=seq, ref=(data.get("ref") or f"VO-{seq:02d}"),
        title=data.get("title") or "",
        kind=data.get("kind") or "ADDITION",
        ref_date=data.get("ref_date") or None, created_by=actor)
    if data.get("rows"):
        set_variation_items(v, data["rows"], actor)
    audit("project", project.id, "VARIATION_CREATED", actor=actor,
          detail={"ref": v.ref})
    return v, None


def set_variation_items(variation, rows, actor):
    from .models import VariationItem
    if variation.status not in ("DRAFT",):
        return None, "Only a draft variation can be edited."
    items = _variation_items(variation, rows)
    variation.items.all().delete()
    VariationItem.objects.bulk_create(items)
    audit("project", variation.project_id, "VARIATION_SAVED", actor=actor,
          detail={"ref": variation.ref, "gross": str(variation.gross)})
    return variation, None


def set_variation_meta(variation, data, actor):
    """Edit a draft variation's header (title/kind/ref/date)."""
    if variation.status != "DRAFT":
        return None, "Only a draft variation can be edited."
    for f in ("ref", "title", "kind"):
        if f in data:
            setattr(variation, f, data.get(f) or getattr(variation, f))
    if "ref_date" in data:
        variation.ref_date = data.get("ref_date") or None
    variation.save(update_fields=["ref", "title", "kind", "ref_date"])
    return variation, None


VARIATION_FLOW = {
    "DRAFT": {"SUBMITTED"},
    "SUBMITTED": {"APPROVED", "REJECTED", "DRAFT"},
    "APPROVED": set(),          # locked once approved (feeds claims)
    "REJECTED": {"DRAFT"},
}


def set_variation_status(variation, to_status, actor):
    from .models import Variation
    allowed = VARIATION_FLOW.get(variation.status, set())
    if to_status not in allowed:
        return None, f"Cannot move a {variation.status} variation to {to_status}."
    if to_status == "SUBMITTED" and not variation.items.exists():
        return None, "Add at least one variation item before submitting."
    variation.status = to_status
    variation.save(update_fields=["status"])
    audit("project", variation.project_id, f"VARIATION_{to_status}",
          actor=actor, detail={"ref": variation.ref})
    return variation, None


def contract_summary(project):
    """The IPA contract block: original sum + approved VOs = revised sum;
    submitted-not-approved VOs are provisions in the forecast (IPA §C–E)."""
    from decimal import Decimal
    original = Decimal(str(project.contract_value or 0))
    approved = project.variations.filter(status="APPROVED")
    submitted = project.variations.filter(status="SUBMITTED")

    def signed(qs):
        return sum((v.signed_total for v in qs), Decimal("0"))

    approved_net = signed(approved)
    pending_net = signed(submitted)
    revised = original + approved_net
    return {
        "original": original,
        "approved_net": approved_net,
        "revised": revised,
        "pending_net": pending_net,
        "forecast": revised + pending_net,
    }
