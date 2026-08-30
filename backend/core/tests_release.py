"""Telling people a new build exists.

The installed desktop app has no address bar and no refresh button, and people
leave it open for days — so a release could sit unused indefinitely with
nothing to say so (owner 2026-08-30)."""
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Notification, User
from .tests import make_user
from .version import build_id


class VersionEndpointTests(TestCase):
    def test_it_answers_without_a_login(self):
        """A tab left on the sign-in screen for a week should still be able to
        tell that it is stale."""
        r = APIClient().get("/api/v1/version")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["build"])

    def test_the_build_is_stable_within_a_process(self):
        self.assertEqual(build_id(), build_id())

    def test_it_carries_nothing_but_the_build(self):
        r = APIClient().get("/api/v1/version")
        self.assertEqual(list(r.data.keys()), ["build"])


class AnnounceReleaseTests(TestCase):
    def setUp(self):
        self.pm = make_user("pm_rel", User.Role.PM)
        self.se = make_user("se_rel", User.Role.SITE_ENGINEER)
        self.fin = make_user("fin_rel", User.Role.FINANCE)

    def _run(self, *args, **kw):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        call_command("announce_release", *args, stdout=out, **kw)
        return out.getvalue()

    def test_it_tells_everybody_by_default(self):
        self._run("Safety module is live", body="Report incidents on site.")
        self.assertEqual(Notification.objects.count(), 3)
        n = Notification.objects.first()
        self.assertEqual(n.title, "Safety module is live")

    def test_roles_narrow_it(self):
        self._run("For site teams", roles="PM,SITE_ENGINEER")
        told = set(Notification.objects.values_list("recipient__username",
                                                    flat=True))
        self.assertEqual(told, {"pm_rel", "se_rel"})

    def test_a_dry_run_sends_nothing(self):
        out = self._run("Nothing yet", dry_run=True)
        self.assertIn("Would tell 3 people", out)
        self.assertEqual(Notification.objects.count(), 0)

    def test_push_only_skips_people_without_a_subscription(self):
        from .models import PushSubscription
        PushSubscription.objects.create(
            user=self.pm, platform="DESKTOP",
            endpoint="https://push.example/rel", p256dh="k1", auth="k2")
        self._run("Only the subscribed", push_only=True)
        self.assertEqual(
            list(Notification.objects.values_list("recipient__username",
                                                  flat=True)),
            ["pm_rel"])

    def test_an_inactive_user_is_left_alone(self):
        self.fin.is_active = False
        self.fin.save(update_fields=["is_active"])
        self._run("Anyone there?")
        self.assertEqual(Notification.objects.count(), 2)


class ReleaseNotesTests(TestCase):
    """What changed, not just that something did."""

    def setUp(self):
        self.user = make_user("pm_note", User.Role.PM)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_announcing_records_a_note(self):
        from io import StringIO

        from django.core.management import call_command

        from .models import ReleaseNote
        call_command("announce_release", "Safety module is live",
                     body="Report incidents from the site page.",
                     area="HSE", stdout=StringIO())
        note = ReleaseNote.objects.get()
        self.assertEqual(note.title, "Safety module is live")
        self.assertEqual(note.area, "HSE")

    def test_no_note_skips_it(self):
        from io import StringIO

        from django.core.management import call_command

        from .models import ReleaseNote
        call_command("announce_release", "Quiet one", no_note=True,
                     stdout=StringIO())
        self.assertEqual(ReleaseNote.objects.count(), 0)

    def test_the_list_reads_newest_first(self):
        from datetime import date, timedelta

        from .models import ReleaseNote
        today = date.today()
        ReleaseNote.objects.create(title="Older", released_on=today
                                   - timedelta(days=5))
        ReleaseNote.objects.create(title="Newer", released_on=today)
        rows = self.client.get("/api/v1/releases").data
        self.assertEqual([r["title"] for r in rows], ["Newer", "Older"])

    def test_an_empty_list_is_not_an_error(self):
        r = self.client.get("/api/v1/releases")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, [])
