"""Errors carry a machine-readable code.

Session auth has no 401 to give: "you are not signed in" and "you are signed
in but may not do this" are both 403. The client could only tell them apart by
matching English, so it did not — and a PM whose 12-hour session had lapsed
spent a morning reading "Authentication credentials were not provided." inside
the attendance panel, with his own name in the corner, and reported it as
having lost access to attendance (owner 2026-09-02).
"""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Site, User
from .tests import make_user


class ErrorCodeTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="ERR", name="Err site",
                                        status=Site.Status.ACTIVE,
                                        start_date=date.today()
                                        - timedelta(days=10))
        self.client = APIClient()

    def test_a_lapsed_session_is_marked_not_authenticated(self):
        r = self.client.get(f"/api/v1/attendance?site={self.site.id}"
                            f"&date={date.today()}")
        self.assertIn(r.status_code, (401, 403))
        self.assertEqual(r.data["code"], "not_authenticated")

    def test_a_permission_refusal_is_not_a_lapsed_session(self):
        """The difference that matters: this user IS signed in. Signing them
        out over it would be a lie and would lose their work."""
        sa = make_user("err_sa", User.Role.SITE_ADMIN, site=self.site)
        self.client.force_authenticate(sa)
        r = self.client.post("/api/v1/users", {"username": "x"},
                             format="json")
        self.assertEqual(r.status_code, 403)
        self.assertNotEqual(r.data.get("code"), "not_authenticated")

    def test_a_validation_error_keeps_its_own_code(self):
        pm = make_user("err_pm", User.Role.PM, site=self.site)
        self.client.force_authenticate(pm)
        r = self.client.post("/api/v1/documents", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertNotEqual(r.data.get("code"), "not_authenticated")

    def test_a_404_still_reads_as_a_404(self):
        pm = make_user("err_pm2", User.Role.PM, site=self.site)
        self.client.force_authenticate(pm)
        r = self.client.get("/api/v1/documents/NOPE-999")
        self.assertEqual(r.status_code, 404)
        self.assertNotEqual(r.data.get("code"), "not_authenticated")

    def test_the_detail_message_is_left_alone(self):
        """The code is added beside the message, not instead of it — every
        panel that shows `detail` keeps working."""
        r = self.client.get("/api/v1/sites/summary")
        self.assertIn("detail", r.data)
        self.assertTrue(str(r.data["detail"]))
