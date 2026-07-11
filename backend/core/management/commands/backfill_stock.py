"""Seed site inventory from GRNs that were verified before the stock ledger
existed. Idempotent: a GRN that already has RECEIPT movements is skipped, so
this is safe to re-run.

    python manage.py backfill_stock
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create opening stock receipts from already-verified GRNs."

    def handle(self, *args, **opts):
        from core import stock
        from core.models import Document, StockMovement

        grns = (Document.objects.filter(
            doc_type="GRN", is_void=False,
            status__in=["COMPLETE", "SHORTAGE_REPORTED"])
            .order_by("doc_date", "ref"))

        done = lines = 0
        for grn in grns:
            if StockMovement.objects.filter(document=grn).exists():
                continue  # already backfilled
            rev = grn.current_revision
            if rev is None:
                continue
            n = 0
            for line in rev.lines.all():
                if line.item_id and (line.qty_received or 0) > 0:
                    stock.record_receipt(grn.site, line.item, line.qty_received,
                                         document=grn, actor=None,
                                         movement_date=grn.doc_date)
                    n += 1
            if n:
                done += 1
                lines += n
                self.stdout.write(f"  [ok] {grn.ref} — {n} line(s)")

        self.stdout.write(self.style.SUCCESS(
            f"Backfilled {done} GRN(s), {lines} receipt line(s)."))
