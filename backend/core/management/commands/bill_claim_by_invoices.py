"""Record that manual invoices billed a certified claim (owner 2026-10-24).

    python manage.py bill_claim_by_invoices --project 56 --claim IPA-01 \\
        --invoices INV-2026-0029,INV-2026-0055 --drop-claim-invoice   # dry run
    ... --apply

A dry run does it inside a transaction, prints the receivables before and
after, and rolls back — asserting nothing changed.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core import manual_invoices, receivables
from core.models import ManualInvoice, ProgressClaim, User


class _Rollback(Exception):
    pass


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--project", type=int, required=True)
        parser.add_argument("--claim", required=True)
        parser.add_argument("--invoices", required=True)
        parser.add_argument("--drop-claim-invoice", action="store_true")
        parser.add_argument("--apply", action="store_true")

    def _rows(self, claim):
        return [(r["invoice_no"], str(r["amount"]), str(r["received"]),
                 str(r["outstanding"]))
                for r in receivables.invoice_rows(claim.project.site_id)
                if r["project_id"] == claim.project_id]

    def _snap(self, claim):
        claim.refresh_from_db()
        return (claim.status, claim.invoice_no, self._rows(claim),
                sorted(ManualInvoice.objects.filter(bills_claim=claim)
                       .values_list("invoice_no", flat=True)))

    def handle(self, **o):
        claim = ProgressClaim.objects.filter(project_id=o["project"],
                                             ref=o["claim"]).first()
        if claim is None:
            raise CommandError("No such claim on that project.")
        nos = [x.strip() for x in o["invoices"].split(",") if x.strip()]
        invs = list(ManualInvoice.objects.filter(
            project_id=o["project"], invoice_no__in=nos, is_void=False))
        if len(invs) != len(nos):
            raise CommandError("Not every invoice was found (live) on that "
                               "project.")
        actor = User.objects.filter(role="ADMIN", is_active=True) \
            .order_by("id").first()
        before = self._snap(claim)
        self.stdout.write(f"BEFORE {claim.ref} {before[0]} invoice "
                          f"{before[1] or '—'}")
        for r in before[2]:
            self.stdout.write(f"  {r[0]}: amount {r[1]}, received {r[2]}, "
                              f"outstanding {r[3]}")
        try:
            with transaction.atomic():
                err = manual_invoices.bill_claim_by(
                    claim, invs, actor, o["drop_claim_invoice"])
                if err:
                    raise CommandError(err)
                after = self._snap(claim)
                self.stdout.write(f"AFTER  {claim.ref} {after[0]} invoice "
                                  f"{after[1] or '—'} | billed by "
                                  f"{', '.join(after[3])}")
                for r in after[2]:
                    self.stdout.write(f"  {r[0]}: amount {r[1]}, received "
                                      f"{r[2]}, outstanding {r[3]}")
                if not o["apply"]:
                    raise _Rollback()
        except _Rollback:
            assert self._snap(claim) == before, "dry run changed data!"
            self.stdout.write("DRY RUN — rolled back. Add --apply.")
            return
        self.stdout.write("APPLIED.")
