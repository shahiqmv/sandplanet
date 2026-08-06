"""Bulk-set every direct (HR-managed) employee's employment type to CONTRACT,
so HR can then re-mark the genuine permanent workers against the government
work-permit report (owner 2026-08-06).

Dry run by default — pass --apply to actually write. Leaves every other field
untouched (including usd_basic_pay), so a worker re-marked Permanent keeps their
split-pay setup.
"""
from django.core.management.base import BaseCommand

from core.audit import audit
from core.models import Employee


class Command(BaseCommand):
    help = ("Set all direct employees to CONTRACT (dry run unless --apply). "
            "HR then re-marks the permanent ones from the govt WP report.")

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Write the change (default is a dry run).")

    def handle(self, *args, **opts):
        qs = Employee.objects.hr_managed()          # direct workers only
        total = qs.count()
        to_change = qs.exclude(employment_type="CONTRACT")
        n = to_change.count()
        with_usd = to_change.filter(usd_basic_pay__gt=0).count()
        self.stdout.write(f"Direct employees: {total}. "
                          f"Not yet CONTRACT: {n} (of which {with_usd} have a "
                          f"USD split-basic).")
        if with_usd:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ {with_usd} split-pay workers will pause their USD "
                "basic until re-marked Permanent. Don't run payroll until HR "
                "finishes. Their usd_basic_pay is kept, not cleared."))
        if not opts["apply"]:
            self.stdout.write(self.style.WARNING(
                "DRY RUN — nothing changed. Re-run with --apply to write."))
            return
        changed = to_change.update(employment_type="CONTRACT")
        audit("employee", 0, "BULK_SET_CONTRACT", detail={"changed": changed})
        self.stdout.write(self.style.SUCCESS(
            f"Done — set {changed} employees to CONTRACT."))
