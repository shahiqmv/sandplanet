from django.test import TestCase
from rest_framework.test import APIClient

from .audit import audit
from .models import LoginEvent, User
from .tests import make_user


class LoginActivityTests(TestCase):
    def setUp(self):
        self.admin = make_user("adm", User.Role.ADMIN)
        self.pm = make_user("pmx", User.Role.PM)
        self.client = APIClient()

    def test_login_records_failed_then_success(self):
        bad = self.client.post("/api/v1/auth/login",
                               {"username": "pmx", "password": "nope"},
                               format="json")
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post("/api/v1/auth/login",
                              {"username": "pmx", "password": "pw-test-123"},
                              format="json")
        self.assertEqual(ok.status_code, 200)
        kinds = list(LoginEvent.objects.order_by("id")
                     .values_list("kind", flat=True))
        self.assertEqual(kinds, ["FAILED", "LOGIN"])
        good = LoginEvent.objects.get(kind="LOGIN")
        self.assertEqual(good.user_id, self.pm.id)
        self.assertEqual(good.source, "WEB")
        # a failed attempt keeps the typed username but no user
        bad_row = LoginEvent.objects.get(kind="FAILED")
        self.assertEqual(bad_row.username, "pmx")
        self.assertIsNone(bad_row.user_id)

    def test_endpoints_are_admin_only(self):
        self.client.force_authenticate(self.pm)
        self.assertEqual(self.client.get(
            "/api/v1/admin/login-activity").status_code, 403)
        self.assertEqual(self.client.get(
            "/api/v1/admin/audit-trail").status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(
            "/api/v1/admin/login-activity").status_code, 200)
        self.assertEqual(self.client.get(
            "/api/v1/admin/audit-trail").status_code, 200)

    def test_login_activity_filters_and_payload(self):
        LoginEvent.objects.create(user=self.pm, username="pmx", kind="LOGIN",
                                  ip_address="1.2.3.4")
        LoginEvent.objects.create(username="ghost", kind="FAILED")
        self.client.force_authenticate(self.admin)
        d = self.client.get("/api/v1/admin/login-activity?kind=FAILED").data
        self.assertEqual(d["total"], 1)
        self.assertEqual(d["items"][0]["username"], "ghost")
        d2 = self.client.get("/api/v1/admin/login-activity?q=pmx").data
        self.assertEqual(d2["items"][0]["ip_address"], "1.2.3.4")

    def test_audit_trail_filters_and_entities(self):
        audit("payment_request", 5, "PAID", actor=self.admin)
        audit("document", 9, "APPROVE", actor=self.pm)
        self.client.force_authenticate(self.admin)
        d = self.client.get("/api/v1/admin/audit-trail?entity=document").data
        self.assertTrue(d["items"])
        self.assertTrue(all(i["entity"] == "document" for i in d["items"]))
        self.assertIn("document", d["entities"])
