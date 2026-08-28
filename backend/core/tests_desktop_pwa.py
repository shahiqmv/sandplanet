"""Planet Desktop — the installable-app shell (manifest, service worker) and
the desktop web-push registration that goes with it (owner 2026-08-28)."""
from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from .models import PushSubscription, User
from .tests import make_user


def _built():
    return (settings.BASE_DIR.parent / "frontend" / "dist"
            / "index.html").exists()


class DesktopPwaShellTests(TestCase):
    """Guarded on frontend/dist/index.html existing — the routes are only
    wired when the SPA has been built, so skip cleanly in a bare checkout."""

    def test_manifest_is_served_at_the_root_scope(self):
        r = self.client.get("/manifest.webmanifest")
        if not _built():
            return
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/manifest+json")
        body = r.json()
        self.assertEqual(body["scope"], "/")
        self.assertEqual(body["start_url"], "/")
        # A distinct start_url from Planet Mobile keeps the two installed
        # apps separate on a laptop that has both.
        self.assertNotEqual(body["start_url"], "/m/")

    def test_service_worker_claims_the_whole_site(self):
        r = self.client.get("/sw.js")
        if not _built():
            return
        self.assertEqual(r.status_code, 200)
        self.assertIn("javascript", r["Content-Type"])
        self.assertEqual(r["Service-Worker-Allowed"], "/")

    def test_service_worker_never_caches_navigations(self):
        """A cached shell would leave installed windows running an old build
        against a new server — the version skew we deliberately avoided."""
        r = self.client.get("/sw.js")
        if not _built():
            return
        self.assertIn('req.mode === "navigate"', r.content.decode())


class DesktopPushTests(TestCase):
    def setUp(self):
        self.user = make_user("qs_desk", User.Role.QS)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_vapid_key_reports_disabled_without_env(self):
        r = self.client.get("/api/v1/push/key")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["enabled"])

    def test_subscribe_tags_the_platform_and_is_idempotent(self):
        body = {"endpoint": "https://push.example/desk",
                "keys": {"p256dh": "k1", "auth": "k2"}}
        self.assertEqual(
            self.client.post("/api/v1/push/subscribe", body,
                             format="json").status_code, 201)
        sub = PushSubscription.objects.get(endpoint=body["endpoint"])
        self.assertEqual(sub.platform, "DESKTOP")
        self.assertEqual(sub.user, self.user)
        self.client.post("/api/v1/push/subscribe", body, format="json")
        self.assertEqual(PushSubscription.objects.count(), 1)
        self.client.post("/api/v1/push/unsubscribe",
                         {"endpoint": body["endpoint"]}, format="json")
        self.assertFalse(PushSubscription.objects.exists())

    def test_subscribe_rejects_a_body_without_keys(self):
        r = self.client.post("/api/v1/push/subscribe",
                             {"endpoint": "https://push.example/x"},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_each_platform_gets_its_own_deep_link(self):
        from .models import Notification
        from .push import push_url
        n = Notification(title="Approval", body="", doc_ref="IPR-021")
        self.assertEqual(push_url(n, "DESKTOP"), "/#/open/IPR-021")
        self.assertEqual(push_url(n, "MOBILE"), "/m/track/IPR-021")
        blank = Notification(title="Hi", body="", doc_ref="")
        self.assertEqual(push_url(blank, "DESKTOP"), "/")
        self.assertEqual(push_url(blank, "MOBILE"), "/m")

    def test_dispatch_sends_each_device_its_own_url(self):
        from unittest import mock

        from .models import Notification
        from .push import dispatch_push
        PushSubscription.objects.create(
            user=self.user, platform="DESKTOP",
            endpoint="https://push.example/d", p256dh="k1", auth="k2")
        PushSubscription.objects.create(
            user=self.user, platform="MOBILE",
            endpoint="https://push.example/m", p256dh="k1", auth="k2")
        n = Notification(title="Approval", body="IPR-021 needs you",
                         doc_ref="IPR-021")
        with mock.patch("core.push.send_push", return_value=True) as snd:
            dispatch_push(n, self.user)
        urls = sorted(call.args[3] for call in snd.call_args_list)
        self.assertEqual(urls, ["/#/open/IPR-021", "/m/track/IPR-021"])
