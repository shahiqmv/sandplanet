"""Put July's withheld sick pay onto the August run.

Sick leave sat with the absent marks and was deducted: 55 sick days across 34
men in July, on nine runs that are all locked. Locked is the point — the
money went out, the labour cost posted, and reopening nine runs to re-cut
them would rewrite history that people were paid against.

So it is paid forward instead, as an allowance line on each man's August
row, which is how a correction should read on a payslip: an amount, with a
reason, in the month it is actually paid (owner 2026-08-31).

Requires the August runs to exist and still be open — an allowance added to
a locked run would not reach anyone.

    manage.py backpay_july_sick --dry-run
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Attendance, PayrollLine, User
from core.payroll import reset_to_draft

YEAR, MONTH = 2026, 7
NOTE = "July sick leave paid (system deducted it in error)"


class Command(BaseCommand):
    help = "Add July's withheld sick pay as an allowance on the August run."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--year", type=int, default=2026)
        parser.add_argument("--month", type=int, default=8,
                            help="The run to pay it on (default August).")

    @transaction.atomic
    def handle(self, *args, **options):
        dry = options["dry_run"]
        pay_y, pay_m = options["year"], options["month"]

        sick = {}
        for a in Attendance.objects.filter(day__year=YEAR, day__month=MONTH,
                                           remark="SICK"):
            sick[a.employee_id] = sick.get(a.employee_id, 0) + 1
        self.stdout.write(f"{sum(sick.values())} sick days across "
                          f"{len(sick)} workers in {MONTH}/{YEAR}")

        july = {ln.employee_id: ln for ln in PayrollLine.objects.filter(
            run__year=YEAR, run__month=MONTH,
            run__status="LOCKED").select_related("run")}
        # Where each man's back-pay goes. A man still working is credited on
        # the MONTHLY run. A man who has been demobilised will never have
        # another monthly run, so his settlement — his last payment — is the
        # only place it can reach him, and it is credited there instead. The
        # two are never mixed silently: the output says which each was
        # (owner 2026-08-31, VKR's settlement for the batch of 20).
        target, kind_of = {}, {}
        for ln in PayrollLine.objects.filter(
                run__year=pay_y, run__month=pay_m).select_related(
                "run", "employee"):
            existing = target.get(ln.employee_id)
            if existing is None or (
                    ln.run.kind == "MONTHLY" and existing.run.kind !=
                    "MONTHLY"):
                target[ln.employee_id] = ln
                kind_of[ln.employee_id] = ln.run.kind

        paid = skipped = 0
        total = Decimal("0")
        reopened = set()
        actor = (User.objects.filter(role="HO_HR", is_active=True).first()
                 or User.objects.filter(is_superuser=True).first())
        for emp_id, days in sorted(sick.items()):
            was = july.get(emp_id)
            now = target.get(emp_id)
            if was is None:
                self.stdout.write(f"   skip {emp_id}: no locked July line")
                skipped += 1
                continue
            if now is None:
                self.stdout.write(f"   skip {emp_id}: no {pay_m}/{pay_y} line")
                skipped += 1
                continue
            if now.run.status == "LOCKED":
                self.stdout.write(f"   skip {emp_id}: the {pay_m}/{pay_y} run "
                                  "is already locked")
                skipped += 1
                continue
            if NOTE in (now.remarks or ""):
                skipped += 1            # already carried — safe to re-run
                continue

            daily = Decimal(was.basic_pay) / Decimal(was.run.working_days or 1)
            owed = (daily * days).quantize(Decimal("0.01"))
            total += owed
            paid += 1
            where = ("settlement" if kind_of.get(emp_id) == "SETTLEMENT"
                     else "monthly")
            self.stdout.write(
                f"   {now.employee.emp_no:<10} {now.employee.full_name[:24]:<24}"
                f" {days}d  +{owed:<9} on the {where} run")
            if not dry:
                now.allowance = (now.allowance or Decimal("0")) + owed
                now.remarks = " · ".join(
                    x for x in [(now.remarks or "").strip(),
                                f"{NOTE}: {days} day(s), {owed}"] if x)
                now.save(update_fields=["allowance", "remarks"])
                # An approval must never outlive the numbers it was given: a
                # run already with the PM or the Director goes back to draft
                # so it is signed again on the figures now in it.
                if now.run.status not in ("DRAFT", "LOCKED"):
                    reset_to_draft(now.run, actor, f"{NOTE} added")
                    reopened.add(now.run_id)

        self.stdout.write(f"\n{paid} lines credited, {skipped} skipped. "
                          f"Total {total}")
        settled = sum(1 for e in kind_of
                      if kind_of[e] == "SETTLEMENT" and e in sick)
        if settled:
            self.stdout.write(
                f"{settled} of these are demobilised men credited on their "
                "settlement — they have no later monthly run.")
        if reopened:
            self.stdout.write(self.style.WARNING(
                f"{len(reopened)} run(s) returned to draft for re-approval — "
                "their figures changed after they were signed."))
        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing written."))
            transaction.set_rollback(True)
