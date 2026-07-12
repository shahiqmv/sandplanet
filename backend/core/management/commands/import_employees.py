"""Bulk-load employees from a CSV (avoids manual entry).

    python manage.py import_employees staff.csv
    python manage.py import_employees staff.csv --dry-run

CSV columns (header row required; order doesn't matter, extras ignored):
    full_name           required
    site_code           optional — the worker's current site (e.g. SJR); the
                        code must exist. Creates their site allocation.
    job_category        optional — must match a worker category (e.g. Mason)
    nationality         optional
    basic_pay           optional — monthly salary
    currency            optional — MVR (default) or USD
    passport_no         optional
    date_of_birth       optional — YYYY-MM-DD or DD/MM/YYYY
    join_date           optional — YYYY-MM-DD or DD/MM/YYYY
    work_permit_no      optional
    work_permit_expiry  optional — YYYY-MM-DD or DD/MM/YYYY
    emergency_contact   optional

Emp numbers (EMP-0001…) are assigned automatically. A row whose passport_no
already exists is skipped, so re-running the same file won't duplicate.
"""
import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


def _parse_date(value):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return "BAD"


class Command(BaseCommand):
    help = "Import employees from a CSV."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        from core.models import (Employee, EmployeeSiteAllocation,
                                 ManpowerCategory, Site)
        from core.numbering import next_ref

        cats = {c.name.lower(): c for c in ManpowerCategory.objects.filter(
            list_type="DPR")}
        sites = {s.code.lower(): s for s in Site.objects.all()}
        seen_passports = {e.passport_no.strip().lower()
                          for e in Employee.objects.all()
                          if e.passport_no.strip()}

        try:
            fh = open(opts["csv_path"], newline="", encoding="utf-8-sig")
        except OSError as exc:
            raise CommandError(str(exc))

        created = skipped = 0
        with fh:
            reader = csv.DictReader(fh)
            reader.fieldnames = [(f or "").split("(")[0].strip().lower()
                                 for f in (reader.fieldnames or [])]
            if "full_name" not in reader.fieldnames:
                raise CommandError("CSV needs a 'full_name' column.")
            for n, row in enumerate(reader, 2):
                g = lambda k: (row.get(k) or "").strip()  # noqa: E731
                name = g("full_name")
                if not name:
                    continue
                passport = g("passport_no")
                if passport and passport.lower() in seen_passports:
                    skipped += 1
                    continue

                cat = None
                if g("job_category"):
                    cat = cats.get(g("job_category").lower())
                    if cat is None:
                        self.stderr.write(
                            f"  row {n}: category '{g('job_category')}' unknown "
                            f"— left blank ({name})")
                site = sites.get(g("site_code").lower()) if g("site_code") \
                    else None
                if g("site_code") and site is None:
                    self.stderr.write(
                        f"  row {n}: site '{g('site_code')}' unknown — no "
                        f"allocation ({name})")

                pay = None
                if g("basic_pay"):
                    try:
                        pay = Decimal(g("basic_pay").replace(",", ""))
                    except InvalidOperation:
                        self.stderr.write(
                            f"  row {n}: basic_pay '{g('basic_pay')}' invalid "
                            f"({name})")
                dates = {}
                for f in ("date_of_birth", "join_date", "work_permit_expiry"):
                    d = _parse_date(g(f))
                    if d == "BAD":
                        self.stderr.write(
                            f"  row {n}: {f} '{g(f)}' unreadable — left blank "
                            f"({name})")
                        d = None
                    dates[f] = d

                currency = (g("currency") or "MVR").upper()
                if currency not in ("MVR", "USD"):
                    currency = "MVR"

                etype = g("employment_type").upper()
                if etype not in Employee.EmploymentType.values:
                    etype = Employee.EmploymentType.PERMANENT

                if not opts["dry_run"]:
                    with transaction.atomic():
                        emp = Employee.objects.create(
                            emp_no=f"EMP-{int(next_ref('EMP', None).split('-')[1]):04d}",
                            full_name=name, nationality=g("nationality"),
                            job_category=cat, basic_pay=pay, currency=currency,
                            passport_no=passport, employment_type=etype,
                            date_of_birth=dates["date_of_birth"],
                            join_date=dates["join_date"],
                            work_permit_no=g("work_permit_no"),
                            work_permit_expiry=dates["work_permit_expiry"],
                            emergency_contact=g("emergency_contact"))
                        if site is not None:
                            EmployeeSiteAllocation.objects.create(
                                employee=emp, site=site,
                                from_date=dates["join_date"] or date.today())
                if passport:
                    seen_passports.add(passport.lower())
                created += 1

        verb = "Would import" if opts["dry_run"] else "Imported"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {created} employee(s); {skipped} skipped."))
