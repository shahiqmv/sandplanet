"""Blank leftover quantities on %-basis claims.

A quantity keyed during a measured phase survived the switch to % and was
printed on the application beside amounts computed from the percentage.
IPA-02 on MXR A,C&F carried 268 such lines (owner 2026-09-03). Money is
unaffected — valuation on a %-claim never read them — so this changes what
the document SAYS, not what it is worth.

    manage.py clear_stale_claim_qty --project "MXR - A,C &F" --claim IPA-02 --dry-run
    manage.py clear_stale_claim_qty --all --dry-run
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from core.commercial import clear_other_basis
from core.models import ProgressClaim, ProgressClaimItem


class Command(BaseCommand):
    help = "Clear quantities left on %-basis claim lines."

    def add_arguments(self, parser):
        parser.add_argument("--project", help="project code")
        parser.add_argument("--claim", help="claim ref, e.g. IPA-02")
        parser.add_argument("--all", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, *args, **o):
        qs = ProgressClaim.objects.filter(basis="PERCENT").exclude(
            status="PAID").select_related("project")
        if not o["all"]:
            if not (o["project"] and o["claim"]):
                self.stderr.write("Give --project and --claim, or --all.")
                return
            qs = qs.filter(project__code=o["project"], ref=o["claim"])
        total = 0
        for claim in qs.order_by("project__code", "seq"):
            stale = ProgressClaimItem.objects.filter(claim=claim).filter(
                Q(cumulative_qty__isnull=False)
                | Q(cumulative_qty_install__isnull=False)).count()
            if not stale:
                continue
            self.stdout.write(f"  {claim.project.code} {claim.ref} "
                              f"({claim.status}): {stale} line(s) carry a "
                              f"leftover quantity")
            total += stale
            if not o["dry_run"]:
                clear_other_basis(claim)
        self.stdout.write(f"\n{total} line(s) "
                          + ("would be " if o["dry_run"] else "")
                          + "cleared.")
        if o["dry_run"]:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing written."))
            transaction.set_rollback(True)
