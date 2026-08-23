"""Mark import milestones PAID for payments made before Planet existed.

Two orders were entered for tracking after their TTs had already gone —
Anhui Qiaoyuan IPR-009 (paid in full) and Kelani Cables IPR-014 (advance
paid, balance settled later through the app). Raising a Payment Voucher for
them now would read as a fresh payment and raise questions with the
accountants (owner 2026-08-23).

This marks them paid through the SAME code path as a recorded TT — the PAID
legs post to the projects/stock at the order's committed rate, so no FX
gain or loss is invented — but with no voucher, a "historical" TT reference,
and the payment date you give. Dry run by default; --apply writes.
"""
from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.audit import audit
from core.imports import ipr_order_total, pay_milestone
from core.models import ImportPaymentMilestone, User

HISTORICAL_REF = "Paid before Planet — historical"


class Command(BaseCommand):
    help = "Mark milestones PAID for TTs made before the app (no voucher)."

    def add_arguments(self, parser):
        parser.add_argument("--ids", required=True,
                            help="Comma-separated milestone ids")
        parser.add_argument("--date", default="",
                            help="Payment date YYYY-MM-DD (default: today)")
        parser.add_argument("--tt-ref", default=HISTORICAL_REF)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **o):
        ids = [int(x) for x in o["ids"].split(",") if x.strip()]
        actor = (User.objects.filter(role="ADMIN", is_active=True).first()
                 or User.objects.filter(is_superuser=True).first())
        paid_at = None
        if o["date"]:
            try:
                paid_at = timezone.make_aware(
                    datetime.strptime(o["date"], "%Y-%m-%d"))
            except ValueError:
                raise CommandError("--date must be YYYY-MM-DD")
        done = 0
        for m in ImportPaymentMilestone.objects.filter(
                id__in=ids).select_related("order__document",
                                           "order__supplier").order_by("id"):
            o_ = m.order
            if m.status == "PAID":
                self.stdout.write(self.style.WARNING(
                    f"  {o_.document.ref} #{m.id} {m.label!r}: already PAID "
                    f"(TT {m.tt_ref}) — skipped"))
                continue
            total = ipr_order_total(o_)
            due = m.due_amount(total)
            committed_mvr = (due * o_.exchange_rate).quantize(Decimal("0.01"))
            self.stdout.write(
                f"  {o_.document.ref} {o_.supplier.name} #{m.id} {m.label!r}: "
                f"{m.status} -> PAID  {o_.order_currency} {due} at "
                f"{o_.exchange_rate} = MVR {committed_mvr} (no FX), "
                f"TT ref {o['tt_ref']!r}"
                + (f", paid {o['date']}" if o["date"] else ""))
            if not o["apply"]:
                continue
            # The normal TT path insists on a voucher-authorised milestone;
            # this payment predates vouchers, so step it there and let the
            # same posting logic run.
            m.status = "AUTHORISED"
            m.save(update_fields=["status"])
            err = pay_milestone(m, committed_mvr, o["tt_ref"], actor)
            if err:
                raise CommandError(f"{o_.document.ref} #{m.id}: {err}")
            if paid_at:
                m.paid_at = paid_at
                m.save(update_fields=["paid_at"])
            audit("document", o_.document_id, "IPR_MILESTONE_PAID_HISTORICAL",
                  actor=actor,
                  detail={"milestone": m.label, "mvr": str(committed_mvr),
                          "note": "paid before the app; marked paid at the "
                                  "committed rate, no voucher"})
            done += 1
        self.stdout.write("")
        if o["apply"]:
            self.stdout.write(self.style.SUCCESS(f"Marked {done} paid."))
        else:
            self.stdout.write(self.style.WARNING(
                "DRY RUN — nothing written. Re-run with --apply."))
