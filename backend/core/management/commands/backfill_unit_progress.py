"""Seed the unit-progress history from where the board stands today.

UnitProgressEvent starts empty, so the first weekly report would show every
unit moving from zero to its current figure — a jump that never happened. This
writes one opening event per live figure, dated to the day the board says it
was last updated, so the history begins at the truth instead of at zero.

Run once, after deploying the history table. Idempotent: it skips any unit
and stage that already has an event.

    manage.py backfill_unit_progress --dry-run
"""
from django.core.management.base import BaseCommand

from core.models import UnitProgressEvent, UnitStageProgress


class Command(BaseCommand):
    help = "Seed unit-progress history from the current board figures."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        have = set(UnitProgressEvent.objects.values_list("unit_id",
                                                         "stage_id"))
        rows = (UnitStageProgress.objects.filter(percent__gt=0)
                .select_related("unit", "unit__project", "stage")
                .order_by("unit__project__code", "unit__ref"))
        made = skipped = 0
        for r in rows:
            if (r.unit_id, r.stage_id) in have:
                skipped += 1
                continue
            on = r.updated_on or r.updated_at.date()
            if not dry:
                UnitProgressEvent.objects.create(
                    unit=r.unit, stage=r.stage, percent=r.percent,
                    # previous == percent: an opening balance, not a move, so
                    # the first report credits nobody with progress that was
                    # made before the history existed.
                    previous=r.percent, on=on, source=r.updated_from)
            made += 1
        self.stdout.write(f"{made} opening events, {skipped} already had one.")
        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing written."))
