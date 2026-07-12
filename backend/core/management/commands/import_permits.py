"""Bulk-update work-permit data on EXISTING employees.

    python manage.py import_permits permits.csv
    python manage.py import_permits permits.csv --dry-run

Matches each row to an existing employee by emp_no (preferred) or passport_no,
then updates their permit fields. Use import_employees to create new workers;
this only updates people already on the roster.

CSV columns (header row required; order doesn't matter, extras ignored):
    emp_no              match key (e.g. EMP-0231) — use this if you have it
    passport_no         alternative match key if emp_no is blank
    employment_type     optional — PERMANENT (default) or CONTRACT
    work_permit_no      optional
    work_permit_expiry  optional — YYYY-MM-DD or DD/MM/YYYY

A row that matches no employee is reported and skipped.
"""
import csv
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError


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
    help = "Update work-permit fields on existing employees from a CSV."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        from core.models import Employee

        by_emp = {e.emp_no.lower(): e for e in Employee.objects.all()}
        by_pp = {e.passport_no.strip().lower(): e
                 for e in Employee.objects.all() if e.passport_no.strip()}
        valid_types = set(Employee.EmploymentType.values)

        try:
            fh = open(opts["csv_path"], newline="", encoding="utf-8-sig")
        except OSError as exc:
            raise CommandError(str(exc))

        updated = skipped = 0
        with fh:
            reader = csv.DictReader(fh)
            reader.fieldnames = [(f or "").split("(")[0].strip().lower()
                                 for f in (reader.fieldnames or [])]
            if not ({"emp_no", "passport_no"} & set(reader.fieldnames)):
                raise CommandError(
                    "CSV needs an 'emp_no' or 'passport_no' column to match on.")
            for n, row in enumerate(reader, 2):
                g = lambda k: (row.get(k) or "").strip()  # noqa: E731
                emp = (by_emp.get(g("emp_no").lower())
                       or by_pp.get(g("passport_no").lower()))
                if emp is None:
                    self.stderr.write(
                        f"  row {n}: no employee for "
                        f"emp_no='{g('emp_no')}' passport='{g('passport_no')}' "
                        "— skipped")
                    skipped += 1
                    continue

                fields = []
                etype = g("employment_type").upper()
                if etype:
                    if etype not in valid_types:
                        self.stderr.write(
                            f"  row {n}: employment_type '{etype}' invalid "
                            f"({emp.emp_no}) — left unchanged")
                    else:
                        emp.employment_type = etype
                        fields.append("employment_type")
                if g("work_permit_no"):
                    emp.work_permit_no = g("work_permit_no")
                    fields.append("work_permit_no")
                expiry = _parse_date(g("work_permit_expiry"))
                if expiry == "BAD":
                    self.stderr.write(
                        f"  row {n}: work_permit_expiry "
                        f"'{g('work_permit_expiry')}' unreadable ({emp.emp_no})")
                elif expiry is not None:
                    emp.work_permit_expiry = expiry
                    fields.append("work_permit_expiry")

                if not fields:
                    skipped += 1
                    continue
                if not opts["dry_run"]:
                    emp.save(update_fields=fields + ["updated_at"])
                updated += 1

        verb = "Would update" if opts["dry_run"] else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {updated} employee(s); {skipped} skipped."))
