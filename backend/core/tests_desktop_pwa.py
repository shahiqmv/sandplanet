"""Planet Desktop — the installable-app shell (manifest, service worker) and
the desktop web-push registration that goes with it (owner 2026-08-28)."""
from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Document, PushSubscription, User
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


class PyrProjectCaptureTests(TestCase):
    """A payment request has to say which job it is for. Cost was otherwise
    filed against the site alone, and on a multi-project site nobody could say
    afterwards which project it belonged to (owner 2026-08-29)."""

    def setUp(self):
        from .models import Project, Site
        self.site = Site.objects.create(code="TST", name="Test site",
                                        status=Site.Status.ACTIVE)
        self.user = make_user("sa_pyr", User.Role.SITE_ADMIN, site=self.site)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.p1 = Project.objects.create(site=self.site, code="P1",
                                         title="Villa 1", status="ACTIVE")
        self.head = self._head()

    def _head(self):
        from .models import CostHead
        head, _ = CostHead.objects.get_or_create(
            name="Transport & Freight")
        return head

    def _body(self, **extra):
        body = {"doc_type": "PYR", "site_id": self.site.id, "payload": {},
                "cost_head_id": self.head.id, "payee": "A Vendor",
                "payment_type": "DIRECT", "payment_method": "BANK",
                "amount_requested": "1000.00", "purpose": "Freight",
                "has_supporting_doc": False, "no_doc_reason": "test"}
        body.update(extra)
        return body

    def _post(self, **extra):
        return self.client.post("/api/v1/documents", self._body(**extra),
                                format="json")

    def test_single_project_site_fills_it_in_silently(self):
        r = self._post()
        self.assertEqual(r.status_code, 201, r.data)
        doc = Document.objects.get(ref=r.data["ref"])
        self.assertEqual(doc.project_id, self.p1.id)
        self.assertFalse(doc.shared_cost)

    def test_multi_project_site_must_choose(self):
        from .models import Project
        Project.objects.create(site=self.site, code="P2", title="Villa 2",
                               status="ACTIVE")
        r = self._post()
        self.assertEqual(r.status_code, 400)
        self.assertIn("project", r.data["detail"].lower())

    def test_multi_project_site_accepts_an_explicit_project(self):
        from .models import Project
        p2 = Project.objects.create(site=self.site, code="P2",
                                    title="Villa 2", status="ACTIVE")
        r = self._post(project_id=p2.id)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Document.objects.get(ref=r.data["ref"]).project_id,
                         p2.id)

    def test_common_cost_is_declared_not_merely_blank(self):
        """The flag is what separates a shared cost from an unknown one — the
        apportionment engine reads it, so a bare null must never qualify."""
        from .models import Project
        Project.objects.create(site=self.site, code="P2", title="Villa 2",
                               status="ACTIVE")
        r = self._post(general_works=True)
        self.assertEqual(r.status_code, 201, r.data)
        doc = Document.objects.get(ref=r.data["ref"])
        self.assertIsNone(doc.project_id)
        self.assertTrue(doc.shared_cost)

    def test_a_project_from_another_site_is_refused(self):
        from .models import Project, Site
        other = Site.objects.create(code="OTH", name="Other")
        alien = Project.objects.create(site=other, code="X1", title="X",
                                       status="ACTIVE")
        r = self._post(project_id=alien.id)
        self.assertEqual(r.status_code, 400)


class ErrorAlertTests(TestCase):
    """Server failures have to reach a person. One broken page hit by a dozen
    users must not send a dozen emails, or alerting gets muted (2026-08-29)."""

    def setUp(self):
        from . import alerting
        alerting._seen.clear()

    def _record(self, msg="boom", lineno=10):
        import logging
        return logging.LogRecord("django.request", logging.ERROR, "/app/x.py",
                                 lineno, msg, None, None)

    def test_repeat_of_the_same_error_is_folded_into_one_email(self):
        from django.core import mail
        from django.test import override_settings

        from .alerting import ThrottledAdminEmailHandler
        h = ThrottledAdminEmailHandler()
        with override_settings(ADMINS=[("A", "a@example.com")]):
            for _ in range(5):
                h.emit(self._record())
        self.assertEqual(len(mail.outbox), 1)

    def test_a_different_error_still_gets_through(self):
        from django.core import mail
        from django.test import override_settings

        from .alerting import ThrottledAdminEmailHandler
        h = ThrottledAdminEmailHandler()
        with override_settings(ADMINS=[("A", "a@example.com")]):
            h.emit(self._record(lineno=10))
            h.emit(self._record(lineno=99))
        self.assertEqual(len(mail.outbox), 2)

    def test_nothing_is_sent_when_no_recipient_is_configured(self):
        from django.core import mail
        from django.test import override_settings

        from .alerting import ThrottledAdminEmailHandler
        h = ThrottledAdminEmailHandler()
        with override_settings(ADMINS=[]):
            h.emit(self._record())
        self.assertEqual(len(mail.outbox), 0)
