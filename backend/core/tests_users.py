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

    def test_admin_resets_password(self):
        u = make_user("frank", User.Role.FINANCE)
        r = self.client.patch(f"/api/v1/users/{u.id}",
                              {"password": "brandNew99"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        u.refresh_from_db()
        self.assertTrue(u.check_password("brandNew99"))

    def test_admin_deletes_user(self):
        u = make_user("gary", User.Role.FINANCE)
        r = self.client.delete(f"/api/v1/users/{u.id}")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(User.objects.filter(pk=u.id).exists())

    def test_cannot_delete_self(self):
        r = self.client.delete(f"/api/v1/users/{self.admin.id}")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.admin.id).exists())

    def test_duplicate_username_blocked_case_insensitive(self):
        make_user("pubudu", User.Role.SITE_ENGINEER)
        r = self.client.post("/api/v1/users", {
            "username": "Pubudu", "full_name": "Pubudu Two",
            "role": "SITE_ENGINEER", "password": "chosen-pass-9"},
            format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("username", r.data)
        self.assertEqual(User.objects.filter(username__iexact="pubudu").count(),
                         1)

    def test_deactivated_username_stays_reserved(self):
        u = make_user("pubudu", User.Role.SITE_ENGINEER)
        u.is_active = False
        u.save()
        r = self.client.post("/api/v1/users", {
            "username": "pubudu", "full_name": "New Pubudu",
            "role": "SITE_ENGINEER", "password": "chosen-pass-9"},
            format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("username", r.data)


class ChangeRoleTests(TestCase):
    def setUp(self):
        from datetime import date

        from .models import Site, SitePmHistory, UserSiteAllocation
        self.admin = make_user("adm_role", User.Role.ADMIN)
        self.site = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.eng = make_user("eng1", User.Role.SITE_ENGINEER, site=self.site)
        UserSiteAllocation.objects.create(user=self.eng, site=self.site,
                                          from_date=date(2026, 1, 1))
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self._SitePmHistory = SitePmHistory

    def test_promote_engineer_to_pm_and_assign_site(self):
        r = self.client.post(f"/api/v1/users/{self.eng.id}/change-role",
                             {"role": "PM", "assign_site_id": self.site.id},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["assigned_pm_site"], "SJR")
        self.eng.refresh_from_db()
        self.assertEqual(self.eng.role, "PM")
        self.assertTrue(self.site.is_current_pm(self.eng))     # now the site PM

    def test_promote_without_assign_leaves_no_pm_history(self):
        r = self.client.post(f"/api/v1/users/{self.eng.id}/change-role",
                             {"role": "PM"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIsNone(r.data["assigned_pm_site"])
        self.assertFalse(self.site.is_current_pm(self.eng))    # role only

    def test_demoting_a_pm_closes_site_pm_assignment(self):
        from datetime import date
        pm = make_user("pmx", User.Role.PM, site=self.site)
        self._SitePmHistory.objects.create(site=self.site, pm_user=pm,
                                            from_date=date(2026, 1, 1))
        self.assertTrue(self.site.is_current_pm(pm))
        r = self.client.post(f"/api/v1/users/{pm.id}/change-role",
                             {"role": "SITE_ENGINEER"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(self.site.is_current_pm(pm))          # PM row closed

    def test_cannot_change_own_role_or_unknown_role(self):
        self.assertEqual(self.client.post(
            f"/api/v1/users/{self.admin.id}/change-role",
            {"role": "PM"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(
            f"/api/v1/users/{self.eng.id}/change-role",
            {"role": "WIZARD"}, format="json").status_code, 400)

    def test_non_admin_cannot_change_roles(self):
        self.client.force_authenticate(self.eng)
        self.assertIn(self.client.post(
            f"/api/v1/users/{self.eng.id}/change-role",
            {"role": "PM"}, format="json").status_code, (403, 404))
