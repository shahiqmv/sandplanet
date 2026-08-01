"""Unit-based BOQ capture (owner 2026-07-30).

A different BOQ model: works are priced once per unit (a villa/room/area that
recurs), and the final summary multiplies each per-unit amount by its quantity,
plus lump-sum bills (Preliminaries, Provisional). This reads the summary page of
such a BOQ PDF into review-ready categories — strictly separate from the
conventional BOQ import (boq_extract), which is untouched.

Reuses boq_extract.pdf_pages/_batches; extraction is the shared, testable
_call_claude, isolated for tests to monkeypatch.
"""
import os

from .audit import audit
from .boq_extract import ExtractionError, _batches, pdf_pages

DEFAULT_MODEL = "claude-sonnet-5"

_SYSTEM = (
    "You extract the FINAL SUMMARY of a unit-based Bill of Quantities. Each "
    "summary line is either:\n"
    "- a priced category that recurs: a description, a quantity (number of "
    "units, e.g. villas), a unit, and an amount PER UNIT; or\n"
    "- a lump-sum bill (e.g. Preliminaries, Provisional Sum): a single total "
    "amount, no per-unit build-up.\n"
    "Return every summary line in order. Set is_lump=true for lump bills and "
    "put their total in amount_per_unit with quantity=1. Never invent lines; "
    "use only what the summary shows. Also return the GST percentage if shown."
)

_TOOL = {
    "name": "emit_unit_boq",
    "description": "Return the unit-based BOQ summary categories.",
    "input_schema": {
        "type": "object",
        "properties": {
            "categories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string"},
                        "name": {"type": "string"},
                        "quantity": {"type": "number"},
                        "unit": {"type": "string"},
                        "amount_per_unit": {"type": "number"},
                        "is_lump": {"type": "boolean"},
                    },
                    "required": ["name", "amount_per_unit"],
                },
            },
            "gst_percent": {"type": "number"},
        },
        "required": ["categories"],
    },
}


def _model_name():
    from .models import CompanyParameter
    try:
        v = CompanyParameter.objects.get(key="boq_extract_model").value
        return (v or "").strip() or DEFAULT_MODEL
    except CompanyParameter.DoesNotExist:
        return DEFAULT_MODEL


def _call_claude(content, model):
    """One structured extraction call. Isolated so tests can monkeypatch it."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ExtractionError(
            "BOQ capture needs an ANTHROPIC_API_KEY — ask the administrator "
            "to set it in the server environment.")
    try:
        import anthropic
    except ImportError:                          # pragma: no cover - env dep
        raise ExtractionError("The anthropic SDK isn't installed on the server.")
    client = anthropic.Anthropic(api_key=key)
    try:
        msg = client.messages.create(
            model=model, max_tokens=4000, system=_SYSTEM, tools=[_TOOL],
            tool_choice={"type": "tool", "name": "emit_unit_boq"},
            messages=[{"role": "user", "content": content}])
    except Exception as e:                        # pragma: no cover - network
        raise ExtractionError(f"The extraction model failed: {e}")
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use":
            return block.input
    raise ExtractionError("The model returned no summary.")


def structure(pages, model=None):
    model = model or _model_name()
    cats, gst = [], 0
    for batch in _batches(pages):
        body = ("Extract the unit-based BOQ final summary from this document. "
                "Page markers are [PAGE n].\n\n"
                + "\n\n".join(f"[PAGE {n}]\n{t}" for n, t in batch))
        out = _call_claude(body, model) or {}
        cats.extend(out.get("categories") or [])
        gst = gst or out.get("gst_percent") or 0
    return cats, gst


def _dec(v):
    from decimal import Decimal, InvalidOperation
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def normalise(cats):
    """Coerce model rows to review-ready categories."""
    out = []
    for c in cats:
        name = str(c.get("name") or "").strip()
        amt = _dec(c.get("amount_per_unit"))
        if not name or amt is None:
            continue
        is_lump = bool(c.get("is_lump"))
        qty = _dec(c.get("quantity")) if not is_lump else _dec(1)
        if qty is None or qty <= 0:
            qty = _dec(1)
        out.append({
            "ref": str(c.get("ref") or "").strip()[:20],
            "name": name[:200],
            "unit": (str(c.get("unit") or "").strip() or "no")[:20],
            "quantity": str(qty),
            "amount_per_unit": str(amt),
            "is_lump": is_lump,
            "line_total": str((amt if is_lump else amt * qty)),
        })
    return out


def run_capture(upload, model=None):
    """Read + extract an uploaded unit-BOQ PDF into review-ready categories.
    Returns (categories, gst_percent, error)."""
    name = (getattr(upload, "name", "") or "").lower()
    if not name.endswith(".pdf"):
        return None, 0, "Upload the unit BOQ as a PDF."
    cats, gst = structure(pdf_pages(upload), model)
    cats = normalise(cats)
    if not cats:
        return None, 0, ("No summary categories were found — check it's the "
                         "final-summary page of a unit-based BOQ.")
    try:
        gst = float(gst or 0)
    except (TypeError, ValueError):
        gst = 0
    return cats, gst, None


def commit(project, categories, actor):
    """Create (replace) the project's BOQ in UNIT mode from reviewed summary
    categories. Each priced category carries a single per-unit line = its
    amount; lump bills carry lump_amount. Returns (boq, error)."""
    from decimal import Decimal
    from .models import Boq, BoqCategory, BoqItem
    if not categories:
        return None, "No categories to load."
    boq, _ = Boq.objects.get_or_create(project=project)
    if boq.is_locked:
        return None, "The BOQ is locked; unlock it before replacing."
    boq.mode = Boq.Mode.UNIT
    boq.save(update_fields=["mode", "updated_at"])
    boq.categories.all().delete()          # replace
    boq.items.all().delete()
    for i, c in enumerate(categories, 1):
        amt = Decimal(str(c.get("amount_per_unit") or 0))
        is_lump = bool(c.get("is_lump"))
        qty = Decimal(str(c.get("quantity") or 1))
        cat = BoqCategory.objects.create(
            boq=boq, sort_order=i * 10, ref=str(c.get("ref") or "")[:20],
            name=str(c.get("name") or "")[:200],
            unit=str(c.get("unit") or "no")[:20], qty=qty, is_lump=is_lump,
            lump_amount=amt if is_lump else None)
        if not is_lump:
            BoqItem.objects.create(
                boq=boq, category=cat, sort_order=1,
                description=f"{cat.name} — per {cat.unit}", qty=Decimal("1"),
                rate_supply=amt)
    return boq, None


def set_category_items(project, cat_id, rows, actor):
    """Replace a priced category's detail line items — the works that build up
    its per-unit rate (description · unit · qty · rate → amount). The category's
    per-unit total then derives from these. Blocked once the BOQ is locked.
    Returns (category, error)."""
    from decimal import Decimal, InvalidOperation
    from .models import BoqCategory, BoqItem

    boq = getattr(project, "boq", None)
    if boq is None or boq.mode != boq.Mode.UNIT:
        return None, "This project doesn't have a unit-based BOQ."
    if boq.is_locked:
        return None, "The BOQ is locked — a claim has already started."
    cat = BoqCategory.objects.filter(pk=cat_id, boq=boq).first()
    if cat is None:
        return None, "That category isn't on this BOQ."
    if cat.is_lump:
        return None, "A lump-sum bill has no per-unit build-up."

    def _dec(v):
        try:
            return Decimal(str(v))
        except (InvalidOperation, TypeError, ValueError):
            return None

    items = []
    for i, r in enumerate(rows, 1):
        desc = str(r.get("description") or "").strip()
        rate = _dec(r.get("rate"))
        if not desc or rate is None:
            continue
        qty = _dec(r.get("quantity") if "quantity" in r else r.get("qty"))
        items.append(BoqItem(
            boq=boq, category=cat, sort_order=i,
            description=desc[:2000], unit=str(r.get("unit") or "")[:20],
            qty=qty if qty is not None else Decimal("1"), rate_supply=rate))
    if not items:
        return None, "Add at least one line with a description and rate."
    cat.items.all().delete()
    BoqItem.objects.bulk_create(items)
    audit("project", project.id, "BOQ_CATEGORY_DETAIL_SET", actor=actor,
          detail={"category": cat.name, "lines": len(items),
                  "per_unit": str(cat.per_unit_total)})
    return cat, None
