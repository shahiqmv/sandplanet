"""Planet Mobile (R6) — device-token auth."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Document, MobileDevice, User
from .tests import make_user


class MobileAuthTests(TestCase):
    def setUp(self):
        self.user = make_user("pm_m", User.Role.PM)
        self.user.set_password("verify-123")
        self.user.save()
        self.client = APIClient()

    def _login(self, pw="verify-123"):
        return self.client.post("/api/mobile/v1/auth/login",
                                {"username": "pm_m", "password": pw},
                                format="json")

    def test_login_returns_token_then_me_works(self):
        r = self._login()
        self.assertEqual(r.status_code, 201, r.data)
        token = r.data["token"]
        self.assertEqual(r.data["user"]["role"], "PM")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        me = self.client.get("/api/mobile/v1/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["username"], "pm_m")

    def test_wrong_password_rejected(self):
        self.assertEqual(self._login("nope").status_code, 401)

    def test_no_token_is_unauthorised(self):
        self.assertEqual(self.client.get("/api/mobile/v1/me").status_code, 401)

    def test_logout_revokes_the_device(self):
        token = self._login().data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(
            self.client.post("/api/mobile/v1/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/mobile/v1/me").status_code, 401)

    def test_idle_token_expires(self):
        token = self._login().data["token"]
        MobileDevice.objects.filter(token=token).update(
            last_seen=timezone.now() - timedelta(days=31))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.client.get("/api/mobile/v1/me").status_code, 401)

    def test_desktop_session_api_still_session_auth(self):
        # the mobile token must NOT authenticate the desktop API
        token = self._login().data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertIn(self.client.get("/api/v1/auth/me").status_code,
                      (200, 403))  # session endpoint ignores the bearer token
        self.assertFalse(self.client.get("/api/v1/auth/me")
                         .data.get("authenticated", False))


from .tests_procurement import ProcBase  # noqa: E402


class MobileQueueTests(ProcBase):
    """Approver queue + approve/return over the mobile API (R6 slice 2)."""

    def setUp(self):
        super().setUp()
        self.pm.set_password("verify-123")
        self.pm.save()
        self.m = APIClient()
        tok = self.m.post("/api/mobile/v1/auth/login",
                          {"username": self.pm.username,
                           "password": "verify-123"}, format="json").data["token"]
        self.m.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")

    def test_pm_sees_and_approves_mr_then_409(self):
        mr = self.make_mr()
        self.act(mr["ref"], "submit")               # sa submits → waits on PM
        q = self.m.get("/api/mobile/v1/queue")
        self.assertEqual(q.status_code, 200)
        self.assertIn(mr["ref"], [i["ref"] for i in q.data["items"]])
        r = self.m.post(f"/api/mobile/v1/documents/{mr['ref']}/approve", {},
                        format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Document.objects.get(ref=mr["ref"]).status,
                         "PM_APPROVED")
        # second tap (or the other approver) → 409 already actioned
        r2 = self.m.post(f"/api/mobile/v1/documents/{mr['ref']}/approve", {},
                         format="json")
        self.assertEqual(r2.status_code, 409)

    def test_return_requires_reason(self):
        mr = self.make_mr()
        self.act(mr["ref"], "submit")
        self.assertEqual(self.m.post(
            f"/api/mobile/v1/documents/{mr['ref']}/return", {},
            format="json").status_code, 400)
        r = self.m.post(f"/api/mobile/v1/documents/{mr['ref']}/return",
                        {"comment": "Quantities don't match the GRN"},
                        format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Document.objects.get(ref=mr["ref"]).status, "DRAFT")

    def test_actioned_lists_the_approval(self):
        mr = self.make_mr()
        self.act(mr["ref"], "submit")
        self.m.post(f"/api/mobile/v1/documents/{mr['ref']}/approve", {},
                    format="json")
        done = self.m.get("/api/mobile/v1/actioned").data["items"]
        self.assertIn(mr["ref"], [i["ref"] for i in done])


class MobileOriginatorTests(ProcBase):
    """My Requests, tracking timeline, alerts feed (R6 slice 3)."""

    def setUp(self):
        super().setUp()
        self.sa.set_password("verify-123")
        self.sa.save()
        self.m = APIClient()
        tok = self.m.post("/api/mobile/v1/auth/login",
                          {"username": self.sa.username,
                           "password": "verify-123"}, format="json").data["token"]
        self.m.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")

    def test_requests_lists_my_mr_with_timeline(self):
        mr = self.make_mr()                 # raised by sa
        self.act(mr["ref"], "submit")
        self.as_user(self.pm)
        self.act(mr["ref"], "approve")
        reqs = self.m.get("/api/mobile/v1/requests").data["items"]
        self.assertIn(mr["ref"], [r["ref"] for r in reqs])
        tl = self.m.get(
            f"/api/mobile/v1/requests/{mr['ref']}/timeline").data
        self.assertEqual(tl["steps"][0]["label"], "Raised")
        self.assertGreaterEqual(len(tl["steps"]), 2)   # raised + approvals

    def test_alerts_feed_and_mark_read(self):
        from .models import Notification
        Notification.objects.create(recipient=self.sa, title="MR-X approved",
                                    body="", doc_ref="MR-X", doc_type="MR")
        a = self.m.get("/api/mobile/v1/alerts").data
        self.assertEqual(a["unread"], 1)
        self.assertEqual(len(a["items"]), 1)
        self.assertEqual(
            self.m.post("/api/mobile/v1/alerts/read", {},
                        format="json").status_code, 200)
        self.assertEqual(self.m.get("/api/mobile/v1/alerts").data["unread"], 0)


class MobilePushTests(MobileAuthTests):
    """Web-push subscription lifecycle + gated delivery (R6 slice 4a)."""

    def _auth(self):
        c = APIClient()
        tok = c.post("/api/mobile/v1/auth/login",
                     {"username": "pm_m", "password": "verify-123"},
                     format="json").data["token"]
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")
        return c

    def test_vapid_key_disabled_without_env(self):
        c = self._auth()
        r = c.get("/api/mobile/v1/push/vapid-key")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["enabled"])          # no VAPID_* configured

    def test_subscribe_and_unsubscribe(self):
        from .models import PushSubscription
        c = self._auth()
        body = {"endpoint": "https://push.example/abc",
                "keys": {"p256dh": "k1", "auth": "k2"}}
        self.assertEqual(
            c.post("/api/mobile/v1/push/subscribe", body,
                   format="json").status_code, 201)
        self.assertTrue(PushSubscription.objects.filter(
            endpoint=body["endpoint"], user=self.user).exists())
        # re-subscribing the same endpoint updates, not duplicates
        c.post("/api/mobile/v1/push/subscribe", body, format="json")
        self.assertEqual(PushSubscription.objects.filter(
            endpoint=body["endpoint"]).count(), 1)
        c.post("/api/mobile/v1/push/unsubscribe",
               {"endpoint": body["endpoint"]}, format="json")
        self.assertFalse(PushSubscription.objects.filter(
            endpoint=body["endpoint"]).exists())

    def test_notification_dispatches_push_when_configured(self):
        from unittest import mock

        from .models import Notification, PushSubscription
        from .notify import notify_user
        PushSubscription.objects.create(
            user=self.user, endpoint="https://push.example/x",
            p256dh="k1", auth="k2")
        with mock.patch("core.push.send_push", return_value=True) as snd:
            n = notify_user(self.user, "Hi", "there")
        self.assertIsInstance(n, Notification)
        snd.assert_called_once()

    def test_notification_is_noop_when_push_unconfigured(self):
        # no VAPID env → send_push returns None, no error, alert still written
        from .models import Notification, PushSubscription
        from .notify import notify_user
        PushSubscription.objects.create(
            user=self.user, endpoint="https://push.example/y",
            p256dh="k1", auth="k2")
        n = notify_user(self.user, "Hi", "there")
        self.assertTrue(Notification.objects.filter(pk=n.pk).exists())
