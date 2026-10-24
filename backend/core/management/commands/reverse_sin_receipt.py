"""Put a directly-received store issue back in transit (owner 2026-10-24).

    python manage.py reverse_sin_receipt SIN-002 --reason "..."          # dry run
    python manage.py reverse_sin_receipt SIN-002 --reason "..." --apply

A dry run does the whole reversal inside a transaction, prints what moved,
and rolls back — asserting afterwards that nothing changed.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from core import imports
from core.models import CostPosting, Document, User


class _Rollback(Exception):
    pass


class Command(BaseCommand):
    help = "Reverse the direct receipt of a store issue (SIN)."

    def add_arguments(self, parser):
        parser.add_argument("ref")
        parser.add_argument("--reason", required=True)
        parser.add_argument("--apply", action="store_true")

    def _state(self, doc):
        site_totals = dict(CostPosting.objects.filter(
            site=doc.store_issue.to_site, state="INCURRED")
            .values_list("source").annotate(t=Sum("amount")))
        lines = [(ln.id, ln.received_qty, ln.lot.qty_in_transit)
                 for ln in doc.store_issue.lines.select_related("lot")
                 .order_by("id")]
        return doc.status, site_totals, lines

    def handle(self, ref, reason, apply, **opts):
        try:
            doc = Document.objects.get(ref=ref, doc_type="SIN")
        except Document.DoesNotExist:
            raise CommandError(f"No store issue {ref}.")
        actor = User.objects.filter(role="ADMIN", is_active=True) \
            .order_by("id").first()
        before = self._state(doc)
        try:
            with transaction.atomic():
                err = imports.reverse_store_issue_receipt(doc, actor, reason)
                if err:
                    raise CommandError(err)
                doc.refresh_from_db()
                status, totals, lines = self._state(doc)
                self.stdout.write(f"{ref}: {before[0]} -> {status}")
                for src in sorted(set(before[1]) | set(totals)):
                    a, b = before[1].get(src) or 0, totals.get(src) or 0
                    if a != b:
                        self.stdout.write(f"  {doc.store_issue.to_site.code} "
                                          f"INCURRED {src}: {a} -> {b}")
                self.stdout.write(
                    f"  site total INCURRED: {sum(before[1].values())} -> "
                    f"{sum(totals.values())}")
                self.stdout.write(f"  lines back in transit: "
                                  f"{sum(1 for x in lines if not x[1])}"
                                  f"/{len(lines)}")
                if not apply:
                    raise _Rollback()
        except _Rollback:
            doc.refresh_from_db()
            assert self._state(doc) == before, "dry run changed data!"
            self.stdout.write("DRY RUN — rolled back, nothing changed. "
                              "Add --apply to do it.")
            return
        self.stdout.write("APPLIED.")
