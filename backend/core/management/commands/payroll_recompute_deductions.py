"""Re-read the advance and loan deductions on the runs of a month that are
not yet locked (owner 2026-11-08).

    manage.py payroll_recompute_deductions --year 2026 --month 10 [--apply]

A dollar advance was coming off a USD run as if it had been lent in rufiyaa,
divided by the rate: USD 667 became USD 43. The rule is fixed in
payroll.deductions_for; this brings the lines already drawn up into line
with it, and says what it changed. Locked runs are left alone: they are paid.
Without --apply it only reports.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core import payroll
from core.audit import audit
from core.models import PayrollRun


class Command(BaseCommand):
    help = "Re-read advance and loan deductions on a month's unlocked runs."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True)
        parser.add_argument("--month", type=int, required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, year, month, apply, **options):
        changes = []
        runs = (PayrollRun.objects.filter(year=year, month=month)
                .exclude(status="LOCKED").select_related("site")
                .order_by("currency", "id"))
        for run in runs:
            for line in run.lines.filter(excluded=False).select_related(
                    "employee"):
                ded = payroll.deductions_on_run(line.employee, run,
                                                usd=run.currency == "USD")
                if (ded["advance"] != line.advance
                        or ded["loan"] != line.loan):
                    changes.append((run, line, ded))
        for run, line, ded in changes:
            self.stdout.write(
                f"{run.ref} {run.currency} {line.employee.emp_no}: advance "
                f"{line.advance} -> {ded['advance']}, loan {line.loan} -> "
                f"{ded['loan']}")
        if not changes:
            self.stdout.write("Nothing to change.")
            return
        if not apply:
            self.stdout.write(f"{len(changes)} line(s) would change. Run "
                              "with --apply to change them.")
            return
        with transaction.atomic():
            for run, line, ded in changes:
                was = {"advance": str(line.advance), "loan": str(line.loan)}
                line.advance, line.loan = ded["advance"], ded["loan"]
                line.save(update_fields=["advance", "loan"])
                audit("payroll_run", run.id, "PAYROLL_DEDUCTION_RECOMPUTED",
                      actor=None,
                      detail={"line": line.id, "emp_no": line.employee.emp_no,
                              "was": was,
                              "now": {"advance": str(ded["advance"]),
                                      "loan": str(ded["loan"])},
                              "note": "advances recovered in the currency "
                                      "lent (owner 2026-11-08)"})
        self.stdout.write(f"{len(changes)} line(s) changed.")
