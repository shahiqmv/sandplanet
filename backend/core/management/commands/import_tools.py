"""Bulk-load existing site tools into the Tools & Equipment register.

    python manage.py import_tools tools.csv            # import
    python manage.py import_tools tools.csv --dry-run  # preview

CSV columns (header row required; order doesn't matter, extras ignored):
    site_code   required — the site the tool is at (e.g. SJR, CNR, MLE)
    name        required — the tool name (e.g. Battery drill)
    category    optional — e.g. Tools & Equipment
    serial_no   optional — used to avoid duplicate imports
    model       optional
    brand       optional
    state       optional — IN_USE (default) / FAULTY / UNDER_REPAIR / RETIRED
    notes       optional

Each row is one physical tool. A row whose (site + serial no.) already exists is
skipped, so re-running the same file won't duplicate. These come in as
"Mobilisation" source; tools received later via GRN are added automatically.
"""
import csv

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Import existing tools into the register from a CSV."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        from core.models import Site, ToolAsset

        states = set(ToolAsset.State.values)
        sites = {s.code.lower(): s for s in Site.objects.all()}
        seen = {(t.site_id, t.serial_no.strip().lower())
                for t in ToolAsset.objects.all() if t.serial_no.strip()}

        try:
            fh = open(opts["csv_path"], newline="", encoding="utf-8-sig")
        except OSError as exc:
            raise CommandError(str(exc))

        created = skipped = 0
        with fh:
            reader = csv.DictReader(fh)
            reader.fieldnames = [(f or "").split("(")[0].strip().lower()
                                 for f in (reader.fieldnames or [])]
            for req in ("site_code", "name"):
                if req not in reader.fieldnames:
                    raise CommandError(f"CSV needs a '{req}' column.")
            for n, row in enumerate(reader, 2):
                g = lambda k: (row.get(k) or "").strip()  # noqa: E731
                name, code = g("name"), g("site_code")
                if not name:
                    continue
                site = sites.get(code.lower())
                if site is None:
                    self.stderr.write(
                        f"  row {n}: site '{code}' unknown — skipped ({name})")
                    skipped += 1
                    continue
                serial = g("serial_no")
                if serial and (site.id, serial.lower()) in seen:
                    skipped += 1
                    continue
                state = (g("state") or "IN_USE").upper()
                if state not in states:
                    state = "IN_USE"
                if not opts["dry_run"]:
                    ToolAsset.objects.create(
                        site=site, name=name, category=g("category"),
                        serial_no=serial, model=g("model"), brand=g("brand"),
                        notes=g("notes"), state=state,
                        source=ToolAsset.Source.MOBILISATION)
                if serial:
                    seen.add((site.id, serial.lower()))
                created += 1

        verb = "Would import" if opts["dry_run"] else "Imported"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {created} tool(s); {skipped} skipped."))
