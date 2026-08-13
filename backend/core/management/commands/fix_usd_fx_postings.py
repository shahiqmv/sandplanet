"""Correct cost postings booked at a mistyped MVR/USD rate.

    python manage.py fix_usd_fx_postings            # dry run (default)
    python manage.py fix_usd_fx_postings --apply

Finance entered the CONVERTED MVR AMOUNT into the per-payment rate box on 18
of 24 USD payments — 462,600 for a $30,000 payment, and so on — and the ledger
multiplied by it, booking billions of rufiyaa of phantom project cost. The
rate box is gone (the peg is a company setting), but the postings it produced
remain.

The ledger is append-only by design, so nothing here edits or deletes a row: a
wrong posting is reversed with a matching negative row and the correct amount
posted fresh, leaving the mistake and its correction both visible.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from core import costing, fx
from core.audit import audit
from core.models import CostPosting, PaymentRequest, User

# A real rate sits at the peg; anything far off it is a mistyped amount.
LOW, HIGH = Decimal("3"), Decimal("3")


class Command(BaseCommand):
    help = "Reverse and re-post USD cost postings made at a mistyped rate."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="write the corrections (default is a dry run)")
        parser.add_argument("--actor", default="",
                            help="username to record against the corrections")

    def handle(self, *args, **o):
        rate = fx.usd_rate()
        actor = (User.objects.filter(username=o["actor"]).first()
                 if o["actor"] else User.objects.filter(role="ADMIN").first())
        self.stdout.write(f"Company rate: {rate} MVR per 1 USD")

        suspects = []
        for pr in PaymentRequest.objects.filter(currency="USD").exclude(
                fx_rate=None).select_related("document", "document__site"):
            r = Decimal(pr.fx_rate)
            if rate / LOW <= r <= rate * HIGH:
                continue                      # a plausible rate — leave it
            suspects.append((pr, r))

        if not suspects:
            self.stdout.write("Nothing to correct.")
            return

        self.stdout.write(
            f"\n{len(suspects)} payment(s) booked at a mistyped rate"
            f"{'' if o['apply'] else ' — DRY RUN'}\n")
        head = (f"  {'Document':16} {'Site':5} {'Paid USD':>12} "
                f"{'Rate used':>14} {'MVR booked':>18} {'MVR correct':>14}")
        self.stdout.write(head)
        total_wrong = total_right = Decimal("0")
        fixed = 0

        for pr, bad_rate in sorted(suspects,
                                   key=lambda x: -(x[0].amount_paid or 0)):
            doc = pr.document
            paid = Decimal(pr.amount_paid or 0)
            right = (paid * rate).quantize(Decimal("0.01"))
            # Only the legs actually posted for this document, and never a
            # reversal row or something already reversed.
            legs = [p for p in CostPosting.objects.filter(
                document=doc, reversal_of__isnull=True)
                if p.state in ("PAID", "INCURRED")
                and not CostPosting.objects.filter(reversal_of=p).exists()]
            booked = sum((p.amount for p in legs), Decimal("0"))
            self.stdout.write(
                f"  {doc.ref:16} {doc.site.code:5} {paid:12,.2f} "
                f"{bad_rate:14,.2f} {booked:18,.2f} {right:14,.2f}")
            for p in legs:
                if p.amount == right:
                    continue                  # already correct, leave alone
                total_wrong += p.amount
                total_right += right
                if not o["apply"]:
                    continue
                with transaction.atomic():
                    costing.post(site=p.site, cost_head=p.cost_head,
                                 state=p.state, source=p.source,
                                 amount=-p.amount, posted_on=p.posted_on,
                                 document=doc, reversal_of=p, actor=actor,
                                 currency=p.currency)
                    costing.post(site=p.site, cost_head=p.cost_head,
                                 state=p.state, source=p.source,
                                 amount=right, posted_on=p.posted_on,
                                 document=doc, actor=actor,
                                 currency=p.currency)
                    fixed += 1
            if o["apply"] and Decimal(pr.fx_rate) != rate:
                pr.fx_rate = rate
                pr.save(update_fields=["fx_rate"])
                audit("document", doc.id, "FX_RATE_CORRECTED", actor=actor,
                      detail={"ref": doc.ref, "was": str(bad_rate),
                              "now": str(rate), "mvr_was": str(booked),
                              "mvr_now": str(right)})

        self.stdout.write(
            f"\n  MVR booked in error : {total_wrong:20,.2f}"
            f"\n  MVR it should be    : {total_right:20,.2f}"
            f"\n  Correction          : {total_right - total_wrong:20,.2f}"
            f"  (USD {(total_right - total_wrong) / rate:,.2f})")
        if o["apply"]:
            self.stdout.write(f"\n{fixed} posting(s) reversed and re-posted.")
        else:
            self.stdout.write("\nDry run — nothing written. "
                              "Re-run with --apply.")
