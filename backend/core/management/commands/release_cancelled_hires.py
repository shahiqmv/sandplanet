"""Free the passports held by placeholders whose ADD batch was cancelled.

A pending site hire is created as an INACTIVE placeholder and only goes live when
the batch is approved. Cancelling used to clear `hire_pending` and nothing else,
so the record became invisible — off every roster, not a pending hire — while
still holding the passport number. The site could then not re-add the same man:
the duplicate-passport guard named a record they had no way to reach.

Reported on AMILA CHINTHANA SUNIL KARUNATHILAKALAGE (EMP-0638), whose SSL hire
batch was cancelled on 2026-08-17 (owner 2026-08-18). 21 records were stuck.

`cancel_batch` now does this at the moment of cancelling; this clears the ones
that were cancelled before the fix.

Only touches records that plainly never went live: inactive, not a pending hire,
no site allocation, no attendance, no payroll line, and whose ONLY batch history
is a cancelled ADD. Nothing is deleted — the emp_no still resolves and the batch
still shows whom the site asked for.

    python manage.py release_cancelled_hires [--dry-run]
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Release passports from cancelled-ADD placeholder employees."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        from core.models import (Attendance, Employee, PayrollLine,
                                 WorkerChangeItem)
        from core import worker_mgmt as wm

        dry = opts["dry_run"]
        freed = skipped = 0
        for emp in Employee.objects.filter(is_active=False,
                                           hire_pending=False).order_by("emp_no"):
            items = list(WorkerChangeItem.objects.filter(employee=emp)
                         .select_related("request"))
            if not items:
                continue
            if {(i.request.kind, i.request.status) for i in items} != \
                    {("ADD", "CANCELLED")}:
                continue
            if emp.site_allocations.exists():
                continue
            # Belt and braces: a placeholder that ever earned or was marked
            # present is NOT a placeholder, whatever its flags say.
            if Attendance.objects.filter(employee=emp).exists() \
                    or PayrollLine.objects.filter(employee=emp).exists():
                self.stdout.write(f"  ! {emp.emp_no} has history — left alone")
                skipped += 1
                continue
            if not emp.passport_no and wm.CANCELLED_HIRE_TAG in emp.full_name:
                continue                      # already released
            self.stdout.write(f"    {emp.emp_no:10} freed {emp.passport_no:14}"
                              f" {emp.full_name[:44]}")
            if not dry:
                wm.release_cancelled_hire(emp)
            freed += 1

        verb = "would free" if dry else "freed"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {freed} passport(s); {skipped} left alone with history."))
