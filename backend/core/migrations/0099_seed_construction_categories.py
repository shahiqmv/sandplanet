"""Seed common construction trades/categories into the Item Master's category
list (owner 2026-07-26) so the procurement-schedule category dropdown is
populated. Idempotent get_or_create — existing categories are untouched."""
from django.db import migrations

CATEGORIES = [
    "Concrete & Masonry", "Steel & Metalwork", "Timber & Joinery",
    "Doors & Windows", "Glass & Glazing", "Roofing", "Waterproofing",
    "Insulation", "Tile & Stone Finishes", "Flooring",
    "Ceiling & Partitions", "Paint & Coatings", "Plumbing & Sanitaryware",
    "Electrical", "HVAC & MEP", "Lighting", "Hardware & Fixings",
    "Kitchen Equipment", "Furniture & Fit-out (FF&E)",
    "Pool & Water Features", "Landscaping & External", "Signage",
]


def seed(apps, schema_editor):
    ItemCategory = apps.get_model("core", "ItemCategory")
    for i, name in enumerate(CATEGORIES):
        ItemCategory.objects.get_or_create(
            name=name, defaults={"sort_order": 200 + i * 5})


def unseed(apps, schema_editor):
    # Leave categories in place on reverse — they may now be referenced.
    pass


class Migration(migrations.Migration):
    dependencies = [("core", "0098_scheduleline_item")]
    operations = [migrations.RunPython(seed, unseed)]
