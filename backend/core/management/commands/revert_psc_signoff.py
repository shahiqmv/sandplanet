"""Withdraw a procurement schedule's sign-off.

The admin account can submit, confirm and sign off a plan on its own, so a
mis-click approves a whole baseline that nobody reviewed. BVR's PSC was
signed off that way on 2026-09-03 (submit → confirm → sign-off in 42
seconds, all by admin) and the owner asked for it back the way it was.

Lines go back to PROPOSED, the baseline stamp is cleared, and the
withdrawal is recorded against the actor with its reason.

    manage.py revert_psc_signoff --ref PSC-BVR-001 --actor admin \
        --reason "Signed off in error" --dry-run
"""
from django.core.management.base import BaseCommand

from core.models import ProcurementSchedule, User
from core.procurement_schedule import withdraw_signoff


class Command(BaseCommand):
    help = "Withdraw a mistaken sign-off on a procurement schedule."

    def add_arguments(self, parser):
        parser.add_argument("--ref", required=True,
                            help="schedule document ref, e.g. PSC-BVR-001")
        parser.add_argument("--actor", required=True,
                            help="username withdrawing it (a Director/admin)")
        parser.add_argument("--reason", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        sched = (ProcurementSchedule.objects
                 .select_related("document", "project")
                 .filter(document__ref=o["ref"]).first())
        if sched is None:
            self.stderr.write(f"No schedule with ref {o['ref']}.")
            return
        try:
            actor = User.objects.get(username=o["actor"])
        except User.DoesNotExist:
            self.stderr.write(f"No user {o['actor']}.")
            return
        doc = sched.document
        signed = sched.lines.filter(state="SIGNED_OFF").count()
        self.stdout.write(
            f"{doc.ref} — status {doc.status}, baseline "
            f"{sched.baseline_signed_at}, {signed} signed-off line(s) of "
            f"{sched.lines.count()}")
        if o["dry_run"]:
            self.stdout.write("Dry run — would revert those lines to PROPOSED "
                              "and clear the baseline. Nothing written.")
            return
        err = withdraw_signoff(sched, actor, o["reason"])
        if err:
            self.stderr.write(err)
            return
        sched.refresh_from_db()
        doc.refresh_from_db()
        self.stdout.write(self.style.SUCCESS(
            f"Withdrawn. {doc.ref} is {doc.status}; baseline "
            f"{sched.baseline_signed_at}; proposed lines "
            f"{sched.lines.filter(state='PROPOSED').count()}."))
