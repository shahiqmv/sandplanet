"""Roll back variation orders marked Approved that the Employer never saw.

Until 2026-08-22 a VO went Draft -> Submitted -> Approved and the QS could
press Approve; four HRDL VOs were marked Approved as an INTERNAL sign-off and
sat in the revised contract sum without ever going to the client. The flow
now has the Director's internal approval as its own state. This moves such VOs
back to PD_APPROVED ("ready to send") -- never where a claim beyond draft has
already valued against the VO, which would mean unwinding certified money.

Dry run by default; --apply writes. Audited per VO.
"""
from django.core.management.base import BaseCommand

from core.audit import audit
from core.models import ProgressClaimItem, User, Variation


class Command(BaseCommand):
    help = "Move never-sent 'Approved' VOs back to PD approved - ready to send."

    def add_arguments(self, parser):
        parser.add_argument("--project", required=True, help="Project code")
        parser.add_argument("--refs", default="",
                            help="Comma-separated VO refs; default = all")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **o):
        actor = (User.objects.filter(role="ADMIN", is_active=True).first()
                 or User.objects.filter(is_superuser=True).first())
        qs = Variation.objects.filter(project__code=o["project"],
                                      status="APPROVED").order_by("seq")
        refs = [r.strip() for r in o["refs"].split(",") if r.strip()]
        if refs:
            qs = qs.filter(ref__in=refs)
        done = skipped = 0
        for v in qs:
            claimed = ProgressClaimItem.objects.filter(
                variation_item__variation=v).exclude(
                claim__status__in=("DRAFT", "REJECTED")).exists()
            if claimed:
                skipped += 1
                self.stdout.write(self.style.WARNING(
                    f"  {v.ref} {v.signed_total}: a submitted/certified claim "
                    f"values against it - LEFT APPROVED"))
                continue
            self.stdout.write(f"  {v.ref} {v.signed_total}: APPROVED -> "
                              f"PD_APPROVED (ready to send to the Employer)")
            if o["apply"]:
                v.status = "PD_APPROVED"
                v.employer_approved_on = None
                v.employer_ref = ""
                v.save(update_fields=["status", "employer_approved_on",
                                      "employer_ref"])
                audit("project", v.project_id,
                      "VARIATION_EMPLOYER_APPROVAL_ROLLED_BACK", actor=actor,
                      detail={"ref": v.ref,
                              "reason": "marked approved internally before "
                                        "the Employer saw it"})
                done += 1
        self.stdout.write("")
        if o["apply"]:
            self.stdout.write(self.style.SUCCESS(
                f"Rolled back {done}; left {skipped} with claims against them."))
        else:
            self.stdout.write(self.style.WARNING(
                f"DRY RUN - {qs.count()} examined, {skipped} would be left. "
                "Re-run with --apply."))
