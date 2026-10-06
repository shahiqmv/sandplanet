"""What the one-run-per-month rule changes on a month's existing runs — read
only, nothing written (owner 2026-10-06: "report any mismatch in terms of
work days and all" before HR refreshes September).

For every rufiyaa site run of the month: who would leave it (paid elsewhere
now), who would join it, and whose days, overtime or Fridays would move.
Hand entries on a line that would go are called out so HR can carry them.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from core import payroll
from core.models import PayrollRun, Site


class Command(BaseCommand):
    help = "Preview the pay-site rule against a month's runs (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True)
        parser.add_argument("--month", type=int, required=True)

    def handle(self, *args, **opts):
        year, month = opts["year"], opts["month"]
        codes = dict(Site.objects.values_list("id", "code"))
        runs = (PayrollRun.objects.filter(year=year, month=month,
                                          currency="MVR", kind="MONTHLY",
                                          site__isnull=False)
                .select_related("site").order_by("site__code"))
        pay_site = payroll.pay_site_map(year, month)
        for run in runs:
            site = run.site
            lines = {ln.employee_id: ln for ln in
                     run.lines.select_related("employee")}
            eligible = {e.id: e for e in payroll.eligible_workers(
                site, "MVR", year, month)}
            self.stdout.write(f"\n== {run.ref} {site.code} [{run.status}] "
                              f"{len(lines)} lines")
            leaving, joining, moving = [], [], []
            for emp_id, ln in lines.items():
                if emp_id in eligible:
                    continue
                to = codes.get(pay_site.get(emp_id), "—")
                hand = []
                if ln.allowance:
                    hand.append(f"allowance {ln.allowance}")
                if (ln.remarks or "").strip():
                    hand.append(f"remark '{ln.remarks[:40]}'")
                if ln.excluded:
                    hand.append("excluded")
                leaving.append((ln.employee.emp_no, to, ln.days_worked,
                                ln.ot_hours, hand))
            for emp_id, emp in eligible.items():
                if emp_id not in lines:
                    d, o, f, _r, split = payroll.month_prefill(
                        emp, site, year, month, run.working_days)
                    joining.append((emp.emp_no, d, o, f, split))
                    continue
                ln = lines[emp_id]
                if ln.excluded:
                    continue
                d, o, f, r, split = payroll.month_prefill(
                    emp, site, year, month, run.working_days)
                if ln.rest_day_revoked:
                    d = max(d - r, 0)
                if (Decimal(str(ln.days_worked)), Decimal(str(ln.ot_hours)),
                        ln.fridays_worked) != (d, o, f):
                    moving.append((emp.emp_no, ln.days_worked, d,
                                   ln.ot_hours, o, ln.fridays_worked, f,
                                   split))

            def origin(split):
                return (" — from " + " + ".join(
                    f"{codes.get(p['site'])} {p['days']}d" for p in split)
                    if split else "")

            for emp_no, to, d, o, hand in leaving:
                self.stdout.write(
                    f"  LEAVES  {emp_no}: paid by {to} now "
                    f"(had {d} days, {o} OT h here)"
                    + (f" — CARRY: {', '.join(hand)}" if hand else ""))
            for emp_no, d, o, f, split in joining:
                self.stdout.write(
                    f"  JOINS   {emp_no}: {d} days, {o} OT h, {f} Fri"
                    + origin(split))
            for emp_no, d0, d1, o0, o1, f0, f1, split in moving:
                self.stdout.write(
                    f"  CHANGES {emp_no}: days {d0} -> {d1}, OT {o0} -> {o1}, "
                    f"Fri {f0} -> {f1}" + origin(split))
            if not (leaving or joining or moving):
                self.stdout.write("  no change")
        self.stdout.write("\nRead-only: nothing was changed. HR applies this "
                          "with Refresh from attendance on each run.")
