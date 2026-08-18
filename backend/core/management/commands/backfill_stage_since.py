"""Date every open onboarding case's current stage from the audit trail.

`stage_since` was added after these cases were already running, so it is null on
almost all of them and the screens that answer "how long has this been sitting?"
had nothing to print — half of why a lodged application still read as untouched
(owner 2026-08-17).

The audit log already knows: an `OBR_STAGE` event records the stage the case
moved INTO, so the newest such event naming the case's CURRENT stage is the day
it arrived there. A case still on its first stage never got that event, so it
falls back to `OBR_BEGIN` — the day processing started.

Idempotent: a case that already carries a `stage_since` is left alone, so this
is safe to re-run and will not overwrite a date the app itself set.

    python manage.py backfill_stage_since [--dry-run]
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Set stage_since on open onboarding cases from the audit trail."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change, write nothing.")

    def handle(self, *args, **opts):
        from core.models import AuditLog, OnboardingCase

        dry = opts["dry_run"]
        cases = (OnboardingCase.objects
                 .select_related("document")
                 .exclude(document__status__in=("COMPLETED", "REJECTED",
                                                "CANCELLED"))
                 .filter(stage_since__isnull=True)
                 .order_by("document__ref"))

        set_ = fell_back = unknown = 0
        for case in cases:
            events = AuditLog.objects.filter(
                entity="document", entity_id=case.document_id,
                event="OBR_STAGE").order_by("-at")
            when = next((e.at for e in events
                         if (e.detail or {}).get("stage") == case.stage), None)
            source = "OBR_STAGE"
            if when is None:      # still on the first stage of the route
                begin = AuditLog.objects.filter(
                    entity="document", entity_id=case.document_id,
                    event="OBR_BEGIN").order_by("-at").first()
                when, source = (begin.at if begin else None), "OBR_BEGIN"
                if when is not None:
                    fell_back += 1
            if when is None:
                unknown += 1
                self.stdout.write(
                    f"  ? {case.document.ref:16}{case.stage:18}"
                    "no audit trail — left null")
                continue
            day = when.date()
            self.stdout.write(f"    {case.document.ref:16}{case.stage:18}"
                              f"{day}  ({source})")
            if not dry:
                case.stage_since = day
                case.save(update_fields=["stage_since"])
            set_ += 1

        verb = "would set" if dry else "set"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} stage_since on {set_} case(s) "
            f"({fell_back} from OBR_BEGIN); {unknown} with no audit trail."))
