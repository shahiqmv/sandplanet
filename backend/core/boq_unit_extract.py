"""Unit-based BOQ capture (owner 2026-07-30).

A different BOQ model: works are priced once per unit (a villa/room/area that
recurs), and the final summary multiplies each per-unit amount by its quantity,
plus lump-sum bills (Preliminaries, Provisional). This reads the summary page of
such a BOQ PDF into review-ready categories — strictly separate from the
conventional BOQ import (boq_extract), which is untouched.

Reuses boq_extract.pdf_pages; pages are grouped per-bill so each extraction
call is focused on one bill (no long-programme truncation). Extraction is the
shared, testable _call_claude, isolated for tests to monkeypatch.
"""
import os

from .audit import audit
from .boq_extract import ExtractionError, pdf_pages

DEFAULT_MODEL = "claude-sonnet-5"

_SYSTEM = (
    "You extract a unit-based Bill of Quantities. Return the bill(s) shown in "
    "the pages you're given.\n\n"
    "SUMMARY page (columns like 'No. of Villas' / 'Amount per Villa' / 'Total "
    "Amount'): return each Bill/category once — its bill ref (e.g. 'Bill No. "
    "02'), name, the number of units, the unit, and the Amount per unit. A "
    "lump-sum bill (Preliminaries, Provisional) has is_lump=true, quantity 1, "
    "and its total in amount_per_unit. Ignore sub-total / total / GST / "
    "grand-total rows.\n\n"
    "DETAILED bill pages (columns 'Rate: Material | Labour | Total' and 'Amount: "
    "Material | Labour | Total'): return the category (its bill ref + name) with "
    "EVERY numbered work line under it — do NOT skip any line. For each work "
    "give its code, full description, quantity, unit, and the MATERIAL rate and "
    "the LABOUR rate SEPARATELY (return the two split rates, NOT the combined "
    "total). A 'Rate only' provisional line has rates but no priced amount — set "
    "rate_only=true.\n\n"
    "ALWAYS include the bill ref (e.g. 'Bill No. 02') on every category so the "
    "summary line and its detail can be matched. Numbers may use thousands "
    "separators (commas) — return plain numbers (26491.41, not '26,491.41'). "
    "Never invent lines. The summary Amount per unit is authoritative even if "
    "the detailed works don't add up to it. Return the GST percentage if shown."
)

_TOOL = {
    "name": "emit_unit_boq",
    "description": "Return the unit-based BOQ categories with their detail works.",
    "input_schema": {
        "type": "object",
        "properties": {
            "categories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string",
                                "description": "Bill ref, e.g. 'Bill No. 02'."},
                        "name": {"type": "string"},
                        "quantity": {"type": "number"},
                        "unit": {"type": "string"},
                        "amount_per_unit": {"type": "number"},
                        "is_lump": {"type": "boolean"},
                        "items": {
                            "type": "array",
                            "description": "EVERY detailed work under this bill.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "code": {"type": "string"},
                                    "description": {"type": "string"},
                                    "quantity": {"type": "number"},
                                    "unit": {"type": "string"},
                                    "rate_material": {"type": "number"},
                                    "rate_labour": {"type": "number"},
                                    "rate_only": {"type": "boolean"},
                                },
                                "required": ["description"],
                            },
                        },
                    },
                    "required": ["name"],
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
            model=model, max_tokens=16000, system=_SYSTEM, tools=[_TOOL],
            tool_choice={"type": "tool", "name": "emit_unit_boq"},
            messages=[{"role": "user", "content": content}])
    except Exception as e:                        # pragma: no cover - network
        raise ExtractionError(f"The extraction model failed: {e}")
    if getattr(msg, "stop_reason", None) == "max_tokens":
        raise ExtractionError(
            "The summary was too long to read in one pass. Upload just the "
            "final-summary page of the BOQ rather than the full priced bills.")
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use":
            return block.input
    raise ExtractionError("The model returned no summary.")


def _key(c):
    return (c.get("ref") or c.get("name") or "").strip().lower()


def _merge(cats, incoming):
    """Merge a batch's categories into the running list, keyed by bill ref (or
    name). The summary page carries the authoritative amount_per_unit; each bill
    batch carries the detail works — combine both onto one category, and never
    let a later batch overwrite a rate already captured from the summary."""
    index = {_key(c): c for c in cats}
    for c in incoming:
        k = _key(c)
        if k and k in index:
            ex = index[k]
            ex.setdefault("items", []).extend(c.get("items") or [])
            for f in ("quantity", "unit", "amount_per_unit", "ref", "name"):
                if ex.get(f) in (None, "") and c.get(f) not in (None, ""):
                    ex[f] = c[f]
            if not ex.get("is_lump") and c.get("is_lump"):
                ex["is_lump"] = True
        else:
            cats.append(c)
            if k:
                index[k] = c
    return cats


def _bill_batches(pages):
    """Group pages so each model call sees one bill's header + its detail (the
    summary page falls in its own leading batch). Small, focused calls so no
    work line is missed and every item carries its bill's context."""
    batches, cur = [], []
    for n, text in enumerate(pages, 1):
        if text.strip().lower().startswith("bill no") and cur:
            batches.append(cur)
            cur = []
        cur.append((n, text))
    if cur:
        batches.append(cur)
    return batches


def structure(pages, model=None):
    model = model or _model_name()
    cats, gst = [], 0
    for batch in _bill_batches(pages):
        body = ("Extract this part of a unit-based BOQ — the summary line(s) "
                "and/or a bill's detailed works. Capture EVERY numbered work "
                "line. Page markers are [PAGE n].\n\n"
                + "\n\n".join(f"[PAGE {n}]\n{t}" for n, t in batch))
        out = _call_claude(body, model) or {}
        _merge(cats, out.get("categories") or [])
        gst = gst or out.get("gst_percent") or 0
    return cats, gst


def _dec(v):
    from decimal import Decimal, InvalidOperation
    if v is None:
        return None
    # BOQ amounts arrive comma-formatted ("26,491.41") and sometimes with a
    # currency mark; strip those so a thousands separator doesn't drop the line.
    s = (str(v).strip().replace(",", "").replace("$", "")
         .replace("USD", "").replace("usd", "").strip())
    if not s:
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _item_amount(it):
    """The line amount for a detail work = qty × (material + labour) rate; a
    'Rate only' provisional line contributes 0 (its rate is kept for a later
    variation). Returns a Decimal."""
    from decimal import Decimal
    if it.get("rate_only"):
        return Decimal("0")
    rm = _dec(it.get("rate_material"))
    rl = _dec(it.get("rate_labour"))
    if rm is None and rl is None:
        rm = _dec(it.get("rate"))              # legacy single rate → material
    rm = rm or Decimal("0")
    rl = rl or Decimal("0")
    qty = _dec(it.get("quantity"))
    if qty is None:
        qty = Decimal("1")
    return qty * (rm + rl)


def _norm_items(raw):
    """Clean a bill's detail works — material and labour rates kept SEPARATE,
    like a conventional split-rate BOQ."""
    out = []
    for it in (raw or []):
        desc = str(it.get("description") or "").strip()
        if not desc:
            continue
        rm = _dec(it.get("rate_material"))
        rl = _dec(it.get("rate_labour"))
        # accept a legacy single 'rate' as material if that's all we got
        if rm is None and rl is None and _dec(it.get("rate")) is not None:
            rm = _dec(it.get("rate"))
        qty = _dec(it.get("quantity"))
        out.append({
            "code": str(it.get("code") or "").strip()[:30],
            "description": desc[:2000],
            "unit": str(it.get("unit") or "").strip()[:20],
            "quantity": (str(qty) if qty is not None else ""),
            "rate_material": (str(rm) if rm is not None else ""),
            "rate_labour": (str(rl) if rl is not None else ""),
            "rate_only": bool(it.get("rate_only")),
            "amount": str(_item_amount(it)),
        })
    return out


def normalise(cats):
    """Coerce model rows to review-ready categories with their detail works."""
    from decimal import Decimal
    out = []
    for c in cats:
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        items = _norm_items(c.get("items"))
        items_sum = sum((_dec(i["amount"]) or Decimal("0") for i in items),
                        Decimal("0"))
        amt = _dec(c.get("amount_per_unit"))
        # The SUMMARY rate is the contract figure and is authoritative — the
        # detail works are only a breakdown and often don't sum to it. Fall back
        # to the breakdown sum only when the summary gave no rate.
        per_unit = amt if amt is not None else (items_sum if items else None)
        if per_unit is None:
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
            "amount_per_unit": str(per_unit),      # contract rate (authoritative)
            "items_total": str(items_sum),          # breakdown sum (reconcile)
            "is_lump": is_lump,
            "items": items,
            "line_total": str(per_unit * qty),      # lump qty = 1
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
        # _dec strips commas/currency so a reviewed value like "26,491.41"
        # can't 500 the commit.
        amt = _dec(c.get("amount_per_unit")) or Decimal("0")
        is_lump = bool(c.get("is_lump"))
        qty = _dec(c.get("quantity")) or Decimal("1")
        cat = BoqCategory.objects.create(
            boq=boq, sort_order=i * 10, ref=str(c.get("ref") or "")[:20],
            name=str(c.get("name") or "")[:200],
            unit=str(c.get("unit") or "no")[:20], qty=qty, is_lump=is_lump,
            lump_amount=amt if is_lump else None,
            # The summary rate is the contract figure (authoritative); the
            # detail works below are only a breakdown that may not sum to it.
            unit_amount=None if is_lump else amt)
        detail = c.get("items") or []
        if detail:
            _make_items(cat, detail, boq)
        elif not is_lump:
            # No detail captured — one per-unit line so the category is still
            # claimable; its amount equals the summary rate.
            BoqItem.objects.create(
                boq=boq, category=cat, sort_order=1,
                description=f"{cat.name} — per {cat.unit}", qty=Decimal("1"),
                rate_supply=amt)
    return boq, None


def _make_items(cat, rows, boq):
    """Persist a category's detail works as BoqItems, keeping MATERIAL and
    LABOUR rates separate (rate_supply / rate_install), like a conventional
    split-rate BOQ. A 'Rate only' provisional line keeps its rate(s) but qty 0,
    so it stays out of the priced total until a variation calls it up."""
    from decimal import Decimal
    from .models import BoqItem
    out = []
    for j, it in enumerate(rows, 1):
        rm = _dec(it.get("rate_material"))
        rl = _dec(it.get("rate_labour"))
        # legacy single 'rate' → material
        if rm is None and rl is None and _dec(it.get("rate")) is not None:
            rm = _dec(it.get("rate"))
        if rm is None and rl is None:
            continue
        iqty = _dec(it.get("quantity"))
        sq = Decimal("0") if it.get("rate_only") else (
            iqty if iqty is not None else Decimal("1"))
        out.append(BoqItem(
            boq=boq, category=cat, sort_order=j,
            item_code=str(it.get("code") or "")[:30],
            description=str(it.get("description") or "")[:2000],
            unit=str(it.get("unit") or "")[:20], qty=sq,
            rate_supply=rm, rate_install=rl))
    BoqItem.objects.bulk_create(out)


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
        rm = _dec(r.get("rate_material"))
        rl = _dec(r.get("rate_labour"))
        if rm is None and rl is None and _dec(r.get("rate")) is not None:
            rm = _dec(r.get("rate"))          # legacy single-rate row
        if not desc or (rm is None and rl is None):
            continue
        qty = _dec(r.get("quantity") if "quantity" in r else r.get("qty"))
        items.append(BoqItem(
            boq=boq, category=cat, sort_order=i,
            description=desc[:2000], unit=str(r.get("unit") or "")[:20],
            qty=qty if qty is not None else Decimal("1"),
            rate_supply=rm, rate_install=rl))
    if not items:
        return None, "Add at least one line with a description and rate."
    cat.items.all().delete()
    BoqItem.objects.bulk_create(items)
    audit("project", project.id, "BOQ_CATEGORY_DETAIL_SET", actor=actor,
          detail={"category": cat.name, "lines": len(items),
                  "per_unit": str(cat.per_unit_total)})
    return cat, None
