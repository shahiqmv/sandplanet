from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from .models import AuditLog, Site, SitePmHistory, User, UserSiteAllocation


def make_user(username, role, site=None):
    user = User.objects.create_user(
        username=username, password="pw-test-123", full_name=username.title(), role=role
    )
    if site:
        UserSiteAllocation.objects.create(user=user, site=site, from_date=date.today())
    return user


class BaseCase(TestCase):
    def setUp(self):
        self.sjr = Site.objects.create(code="SJR", name="Soneva Jani",
                                       status=Site.Status.ACTIVE, contract_value=1000000)
        self.vkr = Site.objects.create(code="VKR", name="Vakkaru",
                                       status=Site.Status.ACTIVE, contract_value=2000000)
        self.admin = make_user("admin1", User.Role.ADMIN)
        self.engineer = make_user("se1", User.Role.SITE_ENGINEER, site=self.sjr)
        self.pm = make_user("pm1", User.Role.PM, site=self.sjr)
        SitePmHistory.objects.create(site=self.sjr, pm_user=self.pm,
                                     from_date=date.today())
        self.client = APIClient()

    def login(self, user):
        self.client.force_authenticate(user)


class SiteLifecycleTests(BaseCase):
    def test_valid_transition_with_reason(self):
        self.login(self.admin)
        r = self.client.post(f"/api/v1/sites/{self.sjr.id}/status",
                             {"status": "ON_HOLD", "reason": "Client suspension"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "ON_HOLD")

    def test_invalid_transition_rejected(self):
        self.login(self.admin)
        awarded = Site.objects.create(code="NEW", name="New", status="AWARDED")
        r = self.client.post(f"/api/v1/sites/{awarded.id}/status",
                             {"status": "CLOSED", "reason": "x"})
        self.assertEqual(r.status_code, 400)

    def test_reason_required(self):
        self.login(self.admin)
        r = self.client.post(f"/api/v1/sites/{self.sjr.id}/status",
                             {"status": "ON_HOLD"})
        self.assertEqual(r.status_code, 400)

    def test_close_sets_actual_completion_and_audits(self):
        self.login(self.admin)
        r = self.client.post(f"/api/v1/sites/{self.sjr.id}/status",
                             {"status": "CLOSED", "reason": "Project complete"})
        self.assertEqual(r.status_code, 200)
        self.sjr.refresh_from_db()
        self.assertIsNotNone(self.sjr.actual_completion)
        log = AuditLog.objects.filter(entity="site", entity_id=self.sjr.id,
                                      event="SITE_STATUS_CHANGED").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.from_state, "ACTIVE")
        self.assertEqual(log.to_state, "CLOSED")
        self.assertEqual(log.detail["reason"], "Project complete")

    def test_site_user_cannot_change_status(self):
        self.login(self.engineer)
        r = self.client.post(f"/api/v1/sites/{self.sjr.id}/status",
                             {"status": "ON_HOLD", "reason": "x"})
        self.assertEqual(r.status_code, 403)

    def test_site_code_immutable(self):
        self.login(self.admin)
        r = self.client.patch(f"/api/v1/sites/{self.sjr.id}", {"code": "XXX"})
        self.assertEqual(r.status_code, 400)


class SiteScopingTests(BaseCase):
    def test_site_user_sees_only_allocated_site(self):
        self.login(self.engineer)
        r = self.client.get("/api/v1/sites")
        codes = [s["code"] for s in r.data]
        self.assertEqual(codes, ["SJR"])

    def test_site_user_404_on_other_site(self):
        self.login(self.engineer)
        r = self.client.get(f"/api/v1/sites/{self.vkr.id}")
        self.assertEqual(r.status_code, 404)

    def test_ho_role_sees_all_sites(self):
        purchasing = make_user("hop1", User.Role.HO_PURCHASING)
        self.login(purchasing)
        r = self.client.get("/api/v1/sites")
        self.assertEqual(len(r.data), 2)


class ContractValueSensitivityTests(BaseCase):
    def test_hidden_from_site_engineer(self):
        self.login(self.engineer)
        r = self.client.get(f"/api/v1/sites/{self.sjr.id}")
        self.assertNotIn("contract_value", r.data)

    def test_visible_to_admin(self):
        self.login(self.admin)
        r = self.client.get(f"/api/v1/sites/{self.sjr.id}")
        self.assertEqual(str(r.data["contract_value"]), "1000000.00")

    def test_visible_to_assigned_pm_only(self):
        self.login(self.pm)
        r = self.client.get(f"/api/v1/sites/{self.sjr.id}")
        self.assertIn("contract_value", r.data)
        # Same PM, unassigned site: allocate read access but no PM assignment
        UserSiteAllocation.objects.create(user=self.pm, site=self.vkr,
                                          from_date=date.today())
        r = self.client.get(f"/api/v1/sites/{self.vkr.id}")
        self.assertNotIn("contract_value", r.data)


class UserAdminTests(BaseCase):
    def test_non_admin_cannot_create_users(self):
        self.login(self.pm)
        r = self.client.post("/api/v1/users", {"username": "x", "full_name": "X",
                                               "role": "SITE_ADMIN", "password": "p"})
        self.assertEqual(r.status_code, 403)

    def test_admin_creates_user_and_audit_written(self):
        self.login(self.admin)
        r = self.client.post("/api/v1/users", {
            "username": "sa9", "full_name": "Store Keeper", "role": "SITE_ADMIN",
            "password": "strong-pw-9",
        })
        self.assertEqual(r.status_code, 201)
        self.assertTrue(AuditLog.objects.filter(entity="user", event="USER_CREATED")
                        .exists())

    def test_deactivate_closes_allocations(self):
        self.login(self.admin)
        r = self.client.post(f"/api/v1/users/{self.engineer.id}/deactivate")
        self.assertEqual(r.status_code, 200)
        self.engineer.refresh_from_db()
        self.assertFalse(self.engineer.is_active)
        self.assertFalse(self.engineer.site_allocations.filter(
            to_date__isnull=True).exists())


class AuthTests(BaseCase):
    def test_login_and_me_landing_site(self):
        r = self.client.post("/api/v1/auth/login",
                             {"username": "se1", "password": "pw-test-123"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["landing_site_id"], self.sjr.id)

    def test_bad_password_rejected(self):
        r = self.client.post("/api/v1/auth/login",
                             {"username": "se1", "password": "wrong"})
        self.assertEqual(r.status_code, 400)

    def test_inactive_user_rejected(self):
        self.engineer.is_active = False
        self.engineer.save()
        r = self.client.post("/api/v1/auth/login",
                             {"username": "se1", "password": "pw-test-123"})
        self.assertEqual(r.status_code, 400)


class SitesSummaryTests(TestCase):
    """The landing page carries live signal, not just names (2026-08-15)."""

    def setUp(self):
        from datetime import date, timedelta
        from .models import (Attendance, Document, Employee,
                             EmployeeSiteAllocation, ManpowerCategory, Site,
                             User)
        self.today = date.today()
        self.admin = make_user("ss_admin", User.Role.ADMIN)
        self.site = Site.objects.create(code="SUM", name="Summary Isle",
                                        status=Site.Status.ACTIVE)
        self.quiet = Site.objects.create(code="QUI", name="Quiet Isle",
                                         status=Site.Status.ACTIVE)
        Site.objects.create(code="SHU", name="Shut Isle",
                            status=Site.Status.CLOSED)
        cat = ManpowerCategory.objects.create(list_type="DPR", grp="LABOUR",
                                              name="Mason", sort_order=1)
        for i in range(3):
            e = Employee.objects.create(emp_no=f"SUM-{i}", full_name=f"W{i}",
                                        job_category=cat, currency="MVR")
            EmployeeSiteAllocation.objects.create(
                employee=e, site=self.site, from_date=self.today)
            Attendance.objects.create(employee=e, site=self.site,
                                      day=self.today,
                                      remark="PRESENT" if i else "ABSENT")
        Document.objects.create(doc_type="DPR", ref="DPR-SUM-001",
                                site=self.site, doc_date=self.today,
                                status="ISSUED", created_by=self.admin)
        Document.objects.create(doc_type="MR", ref="MR-SUM-001",
                                site=self.site, doc_date=self.today,
                                status="SUBMITTED", created_by=self.admin)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _rows(self):
        r = self.client.get("/api/v1/sites/summary")
        self.assertEqual(r.status_code, 200, r.data)
        return {s["code"]: s for s in r.data["sites"]}

    def test_it_counts_who_was_actually_present(self):
        row = self._rows()["SUM"]
        self.assertEqual(row["manpower"], 2)      # the third was absent
        self.assertFalse(row["manpower_stale"])

    def test_it_carries_only_what_the_card_shows(self):
        """Pending paperwork and days-since-DPR were dropped: they made the
        cards tall enough to scroll past your own sites (owner 2026-08-15)."""
        row = self._rows()["SUM"]
        self.assertNotIn("open_docs", row)
        self.assertNotIn("last_dpr", row)
        self.assertEqual(set(row) - {"id", "code", "name", "status",
                                     "is_head_office", "pms", "manpower",
                                     "manpower_day", "manpower_stale"}, set())

    def test_a_closed_site_is_left_off(self):
        self.assertNotIn("SHU", self._rows())

    def test_stale_attendance_is_flagged(self):
        from datetime import timedelta
        from .models import Attendance
        Attendance.objects.filter(site=self.site).update(
            day=self.today - timedelta(days=4))
        row = self._rows()["SUM"]
        self.assertTrue(row["manpower_stale"])
