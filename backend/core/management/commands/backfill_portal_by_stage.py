"""Attribute each onboarding case's portal reference / status to the stage it
was actually recorded at.

A case can lodge TWO applications — a business visa to fly in on, then a work
permit once here — but until now there was one portal_ref / portal_status pair
for the whole case. The business visa's reference and its APPROVED status
therefore followed the case into the work-permit stage, which made an unlodged
WP application read as approved and let the gate holding the case there be
walked straight past (owner 2026-08-18, on OBR-SJR-006).

The audit trail can tell them apart. `OBR_STAGE` says which stage the case moved
into; `OBR_STAGE_DATA` says when a portal field was written. Replaying both in
order gives the stage each value was set at.

Where the trail does not reach — a value written before OBR_STAGE_DATA recorded
its fields — the value is attributed to the LAST application stage the case had
entered at that point, which is the only stage it could have belonged to.

Idempotent: a case that already has `portal_by_stage` is skipped.

    python manage.py backfill_portal_by_stage [--dry-run]
"""
from django.core.management.base import BaseCommand

APPLICATION_STAGES = ("WP_APPLICATION", "BV_APPLICATION")
# The two portals number their applications differently: business visas come
# back GSR/2026/27757, work permits WR1/2026/73059. Every reference in the live
# data follows it. Used ONLY here, to tell a genuine work-permit reference from
# a business-visa number that was re-typed into the work-permit stage because
# the form demanded one — never as a validation rule.
WP_REF_PREFIXES = ("WR",)


class Command(BaseCommand):
    help = "Split portal_ref / portal_status across the stages they belong to."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        from core.models import AuditLog, OnboardingCase

        dry = opts["dry_run"]
        cases = (OnboardingCase.objects.select_related("document")
                 .order_by("document__ref"))
        touched = skipped = 0

        for case in cases:
            if case.portal_by_stage:
                skipped += 1
                continue
            if not (case.portal_ref or case.portal_status):
                continue

            events = AuditLog.objects.filter(
                entity="document", entity_id=case.document_id,
                event__in=("OBR_STAGE", "OBR_STAGE_DATA")).order_by("at")

            # Replay: track the stage, and note the last application stage the
            # case was sitting at when a portal field was written.
            stage = ""
            owner = ""          # stage the portal values belong to
            for e in events:
                detail = e.detail or {}
                if e.event == "OBR_STAGE":
                    stage = detail.get("stage") or stage
                elif e.event == "OBR_STAGE_DATA":
                    fields = detail.get("fields") or []
                    if any(f.startswith("portal_") for f in fields) \
                            and stage in APPLICATION_STAGES:
                        owner = stage
            if not owner:
                # No recorded write we can place. Fall back to the last
                # application stage the case reached — the only one the value
                # could have come from.
                seen = [d.get("stage") for d in
                        (e.detail or {} for e in events
                         if e.event == "OBR_STAGE")]
                owner = next((s for s in reversed(seen)
                              if s in APPLICATION_STAGES), "")
            if not owner:
                self.stdout.write(
                    f"  ? {case.document.ref:16} no application stage in the "
                    f"trail — left alone (ref={case.portal_ref!r})")
                continue

            ref = case.portal_ref or ""
            # A business-visa number sitting on the work-permit stage is the
            # carry-over this whole change is about: HR re-typed the BV's
            # reference because entering the stage demanded one. It belongs to
            # the business visa, and the work permit has not been lodged.
            if (owner == "WP_APPLICATION" and ref
                    and not ref.upper().startswith(WP_REF_PREFIXES)
                    and any((e.detail or {}).get("stage") == "BV_APPLICATION"
                            for e in events if e.event == "OBR_STAGE")):
                self.stdout.write(
                    f"  ! {case.document.ref:16} {ref} is a business-visa "
                    "reference on the work-permit stage — filing it under the "
                    "BV application; the WP application is NOT lodged")
                owner = "BV_APPLICATION"

            row = {"ref": ref, "status": case.portal_status or ""}
            stale = owner != case.stage and case.stage in APPLICATION_STAGES
            self.stdout.write(
                f"    {case.document.ref:16}{owner:16}"
                f"ref={row['ref'] or '-':18}status={row['status'] or '-':16}"
                + ("  <== was leaking into " + case.stage if stale else ""))
            if not dry:
                case.portal_by_stage = {owner: row}
                fields = ["portal_by_stage"]
                if owner != case.stage:
                    # The current stage has no application of its own yet.
                    case.portal_ref = ""
                    case.portal_status = ""
                    fields += ["portal_ref", "portal_status"]
                case.save(update_fields=fields)
            touched += 1

        verb = "would move" if dry else "moved"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} portal data onto its own stage for {touched} case(s); "
            f"{skipped} already done."))
