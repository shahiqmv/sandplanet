"""Bulk catalogue import shared by the CLI command and the Items-page upload.

One row per catalogue item; codes (ITM-…) are assigned automatically and a row
whose description already exists is skipped, so re-running a file is safe.
"""
from django.db import transaction

TRUE = {"1", "y", "yes", "true", "t", "x", "✓"}

# Spreadsheet header (normalised) → model field
HEADER_ALIASES = {
    "description": "description", "item": "description", "name": "description",
    "unit": "unit", "uom": "unit",
    "category": "category", "trade": "category",
    "brand": "brand",
    "spec ref": "spec_ref", "spec_ref": "spec_ref", "spec": "spec_ref",
    "key material": "is_major", "is_major": "is_major", "major": "is_major",
    "dpr": "is_major",
}


def normalise_header(h):
    """A header cell → its field key (or None). Ignores a trailing '(...)' hint."""
    text = str(h or "").split("(")[0].strip().lower()
    return HEADER_ALIASES.get(text)


def import_item_rows(rows):
    """`rows`: list of dicts keyed by field name (description/unit/category/
    brand/spec_ref/is_major). Creates items; returns a summary dict."""
    from .models import Item, ItemCategory
    from .procurement import next_item_code

    cats = {c.name.lower(): c.name for c in ItemCategory.objects.all()}
    existing = {i.description.strip().lower() for i in Item.objects.all()}
    created = skipped = 0
    errors = []
    for n, row in enumerate(rows, 2):          # row 1 is the header
        def g(k):
            return str(row.get(k) or "").strip()
        desc, unit = g("description"), g("unit")
        if not desc:
            continue                            # blank row
        if not unit:
            errors.append({"row": n,
                           "message": f"“{desc}” — no unit, skipped"})
            skipped += 1
            continue
        if desc.lower() in existing:
            skipped += 1
            continue
        cat = g("category")
        if cat and cat.lower() not in cats:
            errors.append({"row": n, "message": f"“{desc}” — category “{cat}” "
                           "is not a known Item Category; imported with no "
                           "category"})
            cat = ""
        elif cat:
            cat = cats[cat.lower()]
        with transaction.atomic():
            Item.objects.create(
                code=next_item_code(), description=desc, unit=unit,
                category=cat, brand=g("brand"), spec_ref=g("spec_ref"),
                is_major=g("is_major").lower() in TRUE)
        existing.add(desc.lower())
        created += 1
    return {"created": created, "skipped": skipped, "errors": errors}
