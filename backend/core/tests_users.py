"""User onboarding — invite email with temp password + forced first-login
password change."""
from django.core import mail
from django.test import TestCase
from rest_framework.test import APIClient

from .models import User
from .tests import make_user


class UserInviteTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin1", User.Role.ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_create_with_email_issues_temp_and_sends_invite(self):
        r = self.client.post("/api/v1/users", {
            "username": "jdoe", "full_name": "J Doe",
            "email": "j@example.com", "role": "FINANCE"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["invite_sent"])
        u = User.objects.get(username="jdoe")
        self.assertTrue(u.must_change_password)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("j@example.com", mail.outbox[0].to)
        self.assertIn("jdoe", mail.outbox[0].body)      # username in the email
        self.assertIn("sslip.io", mail.outbox[0].body)  # login link

    def test_explicit_password_does_not_force_change_or_email(self):
        r = self.client.post("/api/v1/users", {
            "username": "kdoe", "full_name": "K Doe", "role": "FINANCE",
            "password": "chosen-pass-9"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(r.data["invite_sent"])
        u = User.objects.get(username="kdoe")
        self.assertFalse(u.must_change_password)
        self.assertEqual(len(mail.outbox), 0)

    def test_change_password_clears_flag(self):
        u = make_user("bob", User.Role.FINANCE)
        u.set_password("temp1234")
        u.must_change_password = True
        u.save()
        self.client.force_authenticate(u)
        r = self.client.post("/api/v1/auth/change-password", {
            "current_password": "temp1234", "new_password": "myNewPass9"},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        u.refresh_from_db()
        self.assertFalse(u.must_change_password)
        self.assertTrue(u.check_password("myNewPass9"))

    def test_change_password_rejects_wrong_current(self):
        u = make_user("carol", User.Role.FINANCE)
        u.set_password("temp1234")
        u.save()
        self.client.force_authenticate(u)
        r = self.client.post("/api/v1/auth/change-password", {
            "current_password": "wrong", "new_password": "myNewPass9"},
            format="json")
        self.assertEqual(r.status_code, 400)

    def test_me_reports_must_change(self):
        u = make_user("dan", User.Role.FINANCE)
        u.must_change_password = True
        u.save()
        self.client.force_authenticate(u)
        r = self.client.get("/api/v1/auth/me")
        self.assertTrue(r.data["must_change_password"])

    def test_resend_invite(self):
        u = make_user("erin", User.Role.FINANCE)
        u.email = "erin@example.com"
        u.save()
        r = self.client.post(f"/api/v1/users/{u.id}/resend_invite")
        self.assertEqual(r.status_code, 200, r.data)
        u.refresh_from_db()
        self.assertTrue(u.must_change_password)
        self.assertEqual(len(mail.outbox), 1)
