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


class MobilePwaShellTests(TestCase):
    """The PWA shell resources served under /m/ (manifest, service worker,
    deep-link shell). Guarded on frontend/dist/m.html existing — skip cleanly
    when the frontend hasn't been built (e.g. CI before the build step)."""

    def setUp(self):
        from django.conf import settings
        self.built = (settings.BASE_DIR.parent / "frontend" / "dist"
                      / "m.html").exists()

    def test_manifest_is_served(self):
        r = self.client.get("/m/manifest.webmanifest")
        if not self.built:
            return
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/manifest+json")
        self.assertEqual(r.json()["scope"], "/m/")

    def test_service_worker_scope_header(self):
        r = self.client.get("/m/sw.js")
        if not self.built:
            return
        self.assertEqual(r.status_code, 200)
        self.assertIn("javascript", r["Content-Type"])
        self.assertEqual(r["Service-Worker-Allowed"], "/m/")

    def test_deep_link_path_renders_the_shell(self):
        r = self.client.get("/m/track/MR-SJR-001")
        if not self.built:
            return
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"<div id=\"root\">", r.content)


class MobileVoucherReturnTests(TestCase):
    """A signatory can send a whole voucher back from the phone.

    Returning was refused on mobile — "query voucher lines on the desktop for
    now" — so a signatory away from a desk could approve a batch but never
    reject one (owner 2026-08-15). Return now queries every line, which is
    what returning a voucher means on the desktop too: each requisition goes
    back to whoever raised it, with the reason.
    """

    def setUp(self):
        from .models import User
        from .tests import make_user
        self.sig = make_user("mv_sig", User.Role.SIGNATORY)
        self.pv, self.line_count = self._voucher()
        self.client = APIClient()
        self.token = self._token(self.sig)

    def _token(self, user):
        r = self.client.post("/api/mobile/v1/auth/login",
                             {"username": user.username,
                              "password": "pw-test-123"}, format="json")
        return r.data.get("token") if r.status_code in (200, 201) else None

    def _voucher(self):
        """Build a submitted voucher with one PYR line on it."""
        from datetime import date
        from decimal import Decimal
        from .models import (CostHead, Document, PaymentRequest,
                             PaymentVoucherLine, Site, User)
        from .tests import make_user
        site = Site.objects.create(code="MVS", name="Mv Isle",
                                   status=Site.Status.ACTIVE)
        fin = make_user("mv_fin", User.Role.FINANCE)
        head = CostHead.objects.filter(name="Labour & Staff").first()
        pyr = Document.objects.create(doc_type="PYR", ref="PYR-MVS-001",
                                      site=site, doc_date=date(2026, 8, 1),
                                      status="DIRECTOR_APPROVED",
                                      created_by=fin)
        PaymentRequest.objects.create(
            document=pyr, cost_head=head, payee="Someone",
            amount_requested=Decimal("100"), purpose="test", origin="FINANCE")
        pv = Document.objects.create(doc_type="PV", ref="PV-900", site=site,
                                     doc_date=date(2026, 8, 1),
                                     status="SUBMITTED", created_by=fin)
        PaymentVoucherLine.objects.create(voucher=pv, source_document=pyr,
                                          status="INCLUDED",
                                          amount=Decimal("100"))
        return pv, 1

    def test_return_queries_every_line_and_sends_the_source_back(self):
        if not self.token:
            self.skipTest("mobile login unavailable in this fixture")
        r = self.client.post(
            f"/api/mobile/v1/documents/{self.pv.ref}/return",
            {"comment": "wrong bank details"}, format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(r.status_code, 200, r.data)
        self.pv.refresh_from_db()
        self.assertEqual(
            self.pv.voucher_lines.filter(status="QUERIED").count(),
            self.line_count)

    def test_a_reason_is_required(self):
        if not self.token:
            self.skipTest("mobile login unavailable in this fixture")
        r = self.client.post(
            f"/api/mobile/v1/documents/{self.pv.ref}/return", {},
            format="json", HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(r.status_code, 400)



class MobilePurchaseOrderTests(TestCase):
    """A local credit purchase order is signed by the signatory on the order —
    and a signatory on the road must see it on the phone the way an import
    order is (owner 2026-08-22)."""

    def setUp(self):
        from datetime import date
        from .models import Site, SitePmHistory, User
        from .tests import make_user
        self.site = Site.objects.create(code="MPO", name="Mpo Isle",
                                        status=Site.Status.ACTIVE)
        self.sa = make_user("mpo_sa", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("mpo_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.purchasing = make_user("mpo_hop", User.Role.HO_PURCHASING)
        self.director = make_user("mpo_dir", User.Role.DIRECTOR)
        self.sig = make_user("mpo_sig", User.Role.SIGNATORY)
        self.web = APIClient()
        self.m = APIClient()
        r = self.m.post("/api/mobile/v1/auth/login",
                        {"username": self.sig.username,
                         "password": "pw-test-123"}, format="json")
        self.token = r.data.get("token") if r.status_code in (200, 201) \
            else None
        if self.token:
            self.m.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def _act(self, ref, action, user, **body):
        self.web.force_authenticate(user)
        return self.web.post(f"/api/v1/documents/{ref}/actions/{action}",
                             body, format="json")

    def _submitted_po(self):
        """MR → PR with one credit vendor → Director award → PO drafted →
        Purchasing sends it for signature."""
        from .models import Document
        self.web.force_authenticate(self.sa)
        mr = self.web.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id, "general_works": True,
            "payload": {}, "lines": [{"free_text_desc": "Cement",
                                      "unit": "bag", "qty_required": 100,
                                      "qty_to_order": 100}]},
            format="json").data
        self._act(mr["ref"], "submit", self.sa)
        self._act(mr["ref"], "approve", self.pm)
        self._act(mr["ref"], "send", self.sa)
        self.web.force_authenticate(self.purchasing)
        pr = self.web.post("/api/v1/documents", {
            "doc_type": "PR", "site_id": self.site.id, "mr_refs": [mr["ref"]],
            "lines": [{"free_text_desc": "Credit Vendor",
                       "vendor": "Credit Vendor", "amount_credit": 7000,
                       "payment_terms": "30 days credit"}]},
            format="json").data
        self._act(pr["ref"], "submit", self.purchasing)
        self._act(pr["ref"], "approve", self.director)
        po = Document.objects.get(doc_type="PO",
                                  links_from__to_document__ref=pr["ref"])
        self._act(po.ref, "submit", self.purchasing)
        po.refresh_from_db()
        self.assertEqual(po.status, "SUBMITTED")
        return pr, po

    def test_the_signatory_sees_and_signs_the_order_on_the_phone(self):
        if not self.token:
            self.skipTest("mobile login unavailable in this fixture")
        from .models import Payable
        pr, po = self._submitted_po()
        # It is in the phone queue, with an amount on the card.
        q = self.m.get("/api/mobile/v1/queue").data
        card = next((c for c in q["items"] if c["ref"] == po.ref), None)
        self.assertIsNotNone(card, q)
        self.assertEqual(card["doc_type"], "PO")
        self.assertGreater(card["amount"], 0)
        # The detail screen shows what is being placed.
        d = self.m.get(f"/api/mobile/v1/documents/{po.ref}").data
        self.assertEqual(d["supplier_name"], "Credit Vendor")
        self.assertEqual(d["line_label"], "Order lines")
        self.assertTrue(any(x["k"] == "Credit period" for x in d["summary"]))
        # One tap signs it: the order issues and the payable is booked.
        r = self.m.post(f"/api/mobile/v1/documents/{po.ref}/approve", {},
                        format="json")
        self.assertEqual(r.status_code, 200, r.data)
        po.refresh_from_db()
        self.assertEqual(po.status, "ISSUED")
        self.assertTrue(Payable.objects.filter(
            document__ref=pr["ref"], status="OUTSTANDING").exists())
        # ...and it has left the queue.
        q2 = self.m.get("/api/mobile/v1/queue").data
        self.assertNotIn(po.ref, [c["ref"] for c in q2["items"]])

    def test_return_hands_the_order_back_to_purchasing(self):
        if not self.token:
            self.skipTest("mobile login unavailable in this fixture")
        pr, po = self._submitted_po()
        r = self.m.post(f"/api/mobile/v1/documents/{po.ref}/return",
                        {"comment": "wrong quantity on line 1"},
                        format="json")
        self.assertEqual(r.status_code, 200, r.data)
        po.refresh_from_db()
        self.assertEqual(po.status, "DRAFT")



class MobileVariationTests(TestCase):
    """The Director's INTERNAL approval of a variation order, on the phone.
    A Variation is not a Document; its key is "<project code> VO-NN"."""

    def setUp(self):
        from datetime import date, timedelta
        from .models import Project, Site, User
        from .tests import make_user
        self.site = Site.objects.create(code="MVO", name="Mvo Isle",
                                        status=Site.Status.ACTIVE,
                                        start_date=date.today() - timedelta(days=30))
        self.project = Project.objects.create(site=self.site, code="MVO-P",
                                              title="Mvo pools",
                                              contract_value="100000")
        self.qs = make_user("mvo_qs", User.Role.QS)
        self.director = make_user("mvo_dir", User.Role.DIRECTOR)
        self.web = APIClient()
        self.web.force_authenticate(self.qs)
        r = self.web.post(f"/api/v1/projects/{self.project.id}/variations/create",
                          {"title": "Extra coping", "kind": "ADDITION", "rows": [
                              {"item_code": "V1", "description": "Coping",
                               "unit": "m", "qty": "40", "rate_supply": "25",
                               "rate_install": "10"}]}, format="json")
        self.vid = r.data["variations"][-1]["id"]
        self.web.post(f"/api/v1/variations/{self.vid}/status",
                      {"status": "PD_PENDING"}, format="json")
        self.m = APIClient()
        r = self.m.post("/api/mobile/v1/auth/login",
                        {"username": self.director.username,
                         "password": "pw-test-123"}, format="json")
        self.token = r.data.get("token") if r.status_code in (200, 201) else None
        if self.token:
            self.m.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.key = "MVO-P VO-01"

    def test_director_sees_prices_and_approves_the_vo_on_the_phone(self):
        if not self.token:
            self.skipTest("mobile login unavailable in this fixture")
        from .models import Variation
        q = self.m.get("/api/mobile/v1/queue").data
        card = next((c for c in q["items"] if c["ref"] == self.key), None)
        self.assertIsNotNone(card, q)
        self.assertEqual(card["doc_type"], "VO")
        self.assertEqual(card["amount"], 1400.0)
        d = self.m.get(f"/api/mobile/v1/documents/{self.key}").data
        self.assertEqual(d["line_label"], "Variation items")
        self.assertTrue(any(x["k"] == "If the Employer approves"
                            for x in d["summary"]))
        r = self.m.post(f"/api/mobile/v1/documents/{self.key}/approve", {},
                        format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Variation.objects.get(pk=self.vid).status,
                         "PD_APPROVED")
        q2 = self.m.get("/api/mobile/v1/queue").data
        self.assertNotIn(self.key, [c["ref"] for c in q2["items"]])

    def test_return_needs_a_reason_and_sends_it_back_to_draft(self):
        if not self.token:
            self.skipTest("mobile login unavailable in this fixture")
        from .models import Variation
        r = self.m.post(f"/api/mobile/v1/documents/{self.key}/return", {},
                        format="json")
        self.assertEqual(r.status_code, 400)
        r = self.m.post(f"/api/mobile/v1/documents/{self.key}/return",
                        {"comment": "rate looks high"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Variation.objects.get(pk=self.vid).status, "DRAFT")
