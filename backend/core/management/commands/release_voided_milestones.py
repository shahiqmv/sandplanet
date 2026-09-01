"""Let go of milestones still held by vouchers that were voided.

Voiding now releases the milestone a line points at, but vouchers voided
before that fix still hold theirs — and the FK is PROTECT, so those orders'
payment schedules cannot be changed at all. IPR-047 was one: PV-593 was
voided while still submitted, so its line was never approved, and the old
void path only unwound approved lines (owner 2026-08-31).

Only voided vouchers are touched. A live voucher holding a milestone is
holding it for a reason, and set_milestones now says so by name.

    manage.py release_voided_milestones --dry-run
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import PaymentVoucherLine


class Command(BaseCommand):
    help = "Release milestones held by already-voided payment vouchers."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        dry = options["dry_run"]
        lines = (PaymentVoucherLine.objects
                 .exclude(source_milestone__isnull=True)
                 .filter(voucher__is_void=True)
                 .select_related("voucher",
                                 "source_milestone__order__document"))
        n = 0
        for ln in lines:
            m = ln.source_milestone
            note = ln.source_note or f"{m.order.document.ref} — {m.label}"
            self.stdout.write(
                f"   {ln.voucher.ref} line {ln.id} ({ln.currency} "
                f"{ln.amount}) releases {m.order.document.ref} "
                f"milestone {m.id} — {m.label}")
            if not dry:
                ln.source_note = note
                ln.source_milestone = None
                ln.save(update_fields=["source_note", "source_milestone"])
            n += 1
        self.stdout.write(f"\n{n} line(s) released.")
        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing written."))
            transaction.set_rollback(True)
