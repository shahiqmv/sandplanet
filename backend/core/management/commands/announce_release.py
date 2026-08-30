"""Tell people about a release, deliberately.

The in-app banner already appears on its own whenever the client code changes,
and that covers routine deploys without asking anyone for anything. This is
for the releases worth an interruption — a new module, a workflow that has
moved — and it is a command rather than a deploy hook precisely so that it
stays a decision. A push on every deploy is a push people switch off.

    manage.py announce_release "Safety module is live" \
        --body "Report incidents and near misses from the site page." \
        --roles PM,SITE_ENGINEER,SITE_ADMIN

    manage.py announce_release "..." --dry-run
"""
from django.core.management.base import BaseCommand

from core.models import PushSubscription, ReleaseNote, User
from core.notify import notify_user


class Command(BaseCommand):
    help = "Notify staff about a release (in-app alert + push where enabled)."

    def add_arguments(self, parser):
        parser.add_argument("title")
        parser.add_argument("--body", default="", help="One line of detail.")
        parser.add_argument("--roles", default="",
                            help="Comma-separated roles; default everyone.")
        parser.add_argument("--push-only", action="store_true",
                            help="Only people who have push switched on.")
        parser.add_argument("--area", default="",
                            help='Which part moved — "HSE", "Quality".')
        parser.add_argument("--no-note", action="store_true",
                            help="Notify without recording a release note.")
        parser.add_argument("--dry-run", action="store_true",
                            help="List who would be told, and send nothing.")

    def handle(self, *args, **options):
        people = User.objects.filter(is_active=True)
        roles = [r.strip().upper()
                 for r in (options["roles"] or "").split(",") if r.strip()]
        if roles:
            people = people.filter(role__in=roles)
        if options["push_only"]:
            subscribed = set(
                PushSubscription.objects.values_list("user_id", flat=True))
            people = people.filter(id__in=subscribed)
        people = list(people.order_by("username"))

        pushable = set(
            PushSubscription.objects.values_list("user_id", flat=True))

        if options["dry_run"]:
            self.stdout.write(f"Would tell {len(people)} people:")
            for u in people:
                mark = " (push)" if u.id in pushable else ""
                self.stdout.write(f"   {u.username:<18} {u.role:<16}{mark}")
            return

        # The announcement IS the note: writing it twice is how the "what's
        # new" list ends up empty three releases in.
        if not options["no_note"]:
            from django.utils import timezone
            ReleaseNote.objects.create(
                title=options["title"], body=options["body"],
                area=options["area"], released_on=timezone.localdate())
            self.stdout.write("Release note recorded.")

        sent = 0
        for u in people:
            # notify_user writes the in-app alert AND pushes to whichever of
            # their devices are subscribed, so one call covers both.
            if notify_user(u, options["title"], options["body"],
                           category="alert"):
                sent += 1
        self.stdout.write(f"Announced to {sent} of {len(people)} people.")
