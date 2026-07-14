"""Approval notifications — the in-app bell."""
from .models import Notification
from .tests_procurement import ProcBase


class NotificationTests(ProcBase):
    def test_mr_submit_notifies_pm(self):
        mr = self.make_mr()
        self.act(mr["ref"], "submit")   # sa submits → PM must approve
        n = Notification.objects.filter(recipient=self.pm, doc_ref=mr["ref"])
        self.assertTrue(n.exists())
        self.assertIn("needs your approval", n.first().title)
        # the submitter is not notified about their own action
        self.assertFalse(Notification.objects.filter(
            recipient=self.sa, doc_ref=mr["ref"]).exists())

    def test_bell_lists_and_marks_read(self):
        mr = self.make_mr()
        self.act(mr["ref"], "submit")
        self.as_user(self.pm)
        r = self.client.get("/api/v1/notifications")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.data["unread"], 1)
        self.assertTrue(any(mr["ref"] in i["title"] for i in r.data["items"]))
        r = self.client.post("/api/v1/notifications/read", {}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/notifications").data["unread"],
                         0)

    def test_not_duplicated_on_repeat(self):
        mr = self.make_mr()
        self.act(mr["ref"], "submit")
        # returning then resubmitting is a fresh block, but a second submit of
        # the same state must not stack duplicates while still unread
        before = Notification.objects.filter(recipient=self.pm).count()
        from .notify import notify_document
        from .models import Document
        notify_document(Document.objects.get(ref=mr["ref"]), self.sa)
        self.assertEqual(Notification.objects.filter(recipient=self.pm).count(),
                         before)

    def test_pr_submit_notifies_director(self):
        mr_ref = self.mr_to_sent()
        pr = self.make_pr(mr_ref)
        self.act(pr["ref"], "submit")
        self.assertTrue(Notification.objects.filter(
            recipient=self.director, doc_ref=pr["ref"]).exists())


class NotifyDeliveryTests(ProcBase):
    """Self-service SMS opt-in + admin delivery config/test (owner 2026-07-14)."""

    def test_self_service_notification_settings(self):
        self.as_user(self.sa)
        r = self.client.post("/api/v1/auth/notification-settings",
                             {"phone": "+9607778888", "notify_external": False},
                             format="json")
        self.assertEqual(r.status_code, 200)
        self.sa.refresh_from_db()
        self.assertEqual(self.sa.phone, "+9607778888")
        self.assertFalse(self.sa.notify_external)

    def test_config_and_test_are_admin_only(self):
        from .models import User
        from .tests import make_user
        admin = make_user("admin_n", User.Role.ADMIN)
        self.as_user(self.sa)
        self.assertEqual(
            self.client.get("/api/v1/notify/config").status_code, 403)
        self.assertEqual(self.client.post(
            "/api/v1/notify/test", {}, format="json").status_code, 403)
        self.as_user(admin)
        cfg = self.client.get("/api/v1/notify/config")
        self.assertEqual(cfg.status_code, 200)
        self.assertFalse(cfg.data["configured"])          # no env set
        r = self.client.post("/api/v1/notify/test",
                             {"phone": "+9607778888"}, format="json")
        self.assertEqual(r.status_code, 400)              # not configured

    def test_config_and_test_send_when_configured(self):
        from unittest import mock

        from .models import User
        from .tests import make_user
        admin = make_user("admin_n2", User.Role.ADMIN)
        self.as_user(admin)
        env = {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "tok",
               "TWILIO_FROM": "+12025550123", "TWILIO_CHANNEL": "whatsapp"}
        with mock.patch.dict("os.environ", env), \
                mock.patch("core.notify._twilio_send", return_value=201) as snd:
            cfg = self.client.get("/api/v1/notify/config")
            self.assertTrue(cfg.data["configured"])
            self.assertEqual(cfg.data["channel"], "whatsapp")
            r = self.client.post("/api/v1/notify/test",
                                 {"phone": "+9607778888"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        snd.assert_called_once()
