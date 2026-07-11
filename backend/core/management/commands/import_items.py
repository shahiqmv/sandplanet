"""Bulk-load the item catalogue from a CSV (avoids manual entry).

    python manage.py import_items items.csv            # import
    python manage.py import_items items.csv --dry-run  # preview only

CSV columns (header row required; order doesn't matter, extras ignored):
    description   required — the item name / spec
    unit          required — bag, kg, nos, m, ...
    category      optional — must match an existing Item Category name
    brand         optional
    spec_ref      optional
    is_major      optional — yes/true/1 to flag as a key (DPR) material

Codes (ITM-00001…) are assigned automatically. A row whose description already
exists is skipped, so re-running the same file won't create duplicates.
"""
import csv

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

TRUE = {"1", "y", "yes", "true", "t", "x", "✓"}


class Command(BaseCommand):
    help = "Import catalogue items from a CSV."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--dry-run", action="store_true",
                            help="Validate and report without saving.")

    def handle(self, *args, **opts):
        from core.models import Item, ItemCategory
        from core.procurement import next_item_code

        cats = {c.name.lower(): c.name for c in ItemCategory.objects.all()}
        existing = {i.description.strip().lower()
                    for i in Item.objects.all()}

        try:
            fh = open(opts["csv_path"], newline="", encoding="utf-8-sig")
        except OSError as exc:
            raise CommandError(str(exc))

        created = skipped = 0
        with fh:
            reader = csv.DictReader(fh)
            reader.fieldnames = [(f or "").split("(")[0].strip().lower()
                                 for f in (reader.fieldnames or [])]
            if "description" not in reader.fieldnames:
                raise CommandError("CSV needs a 'description' column.")
            for n, row in enumerate(reader, 2):  # row 1 is the header
                g = lambda k: (row.get(k) or "").strip()  # noqa: E731
                desc, unit = g("description"), g("unit")
                if not desc:
                    continue
                if not unit:
                    self.stderr.write(f"  row {n}: no unit — skipped ({desc})")
                    skipped += 1
                    continue
                if desc.lower() in existing:
                    skipped += 1
                    continue
                cat = g("category")
                if cat and cat.lower() not in cats:
                    self.stderr.write(
                        f"  row {n}: category '{cat}' is not a known Item "
                        f"Category — importing with no category ({desc})")
                    cat = ""
                elif cat:
                    cat = cats[cat.lower()]
                if not opts["dry_run"]:
                    with transaction.atomic():
                        Item.objects.create(
                            code=next_item_code(), description=desc, unit=unit,
                            category=cat, brand=g("brand"),
                            spec_ref=g("spec_ref"),
                            is_major=g("is_major").lower() in TRUE)
                existing.add(desc.lower())
                created += 1

        verb = "Would import" if opts["dry_run"] else "Imported"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {created} item(s); {skipped} skipped."))
