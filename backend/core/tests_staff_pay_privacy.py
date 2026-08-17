"""A MANAGEMENT salary is head-office business, never site business.

Owner, 2026-08-16: "PM sees fellow management staff (not workers) salaries on
workforce page and on onboarding page (new management staff hires) and this is
causing some trouble." Viewing is now limited to Finance/HR/Admin/PA and the
signatory — the Director included in the exclusion, at the owner's word — and
raising a management hire moved off site entirely.

Site roles keep seeing their WORKERS' pay: they hire them, re-grade them and
verify the payroll days. Both halves are pinned here, because a redaction that
also hides the labour pay would break the site's own job.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import onboarding as ob
from .models import (Employee, EmployeeSiteAllocation, ManpowerCategory, Site,
                     SitePmHistory, User)
from .tests import make_user

PAY = Decimal("25000.00")


class StaffPayBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.se = make_user("se1", User.Role.SITE_ENGINEER, site=self.site)
        self.hr = make_user("hr1", User.Role.HO_HR)
        self.director = make_user("pd1", User.Role.DIRECTOR)
        self.staff_cat = ManpowerCategory.objects.filter(
            grp="STAFF").first() or ManpowerCategory.objects.create(
            list_type="TWS", grp="STAFF", name="Site Engineer", sort_order=1)
        self.labour_cat = ManpowerCategory.objects.filter(
            grp="LABOUR").first() or ManpowerCategory.objects.create(
            list_type="TWS", grp="LABOUR", name="Mason", sort_order=2)
        self.manager = self._employee("EMP-9001", "Fellow Engineer",
                                      self.staff_cat)
        self.worker = self._employee("EMP-9002", "A Mason", self.labour_cat)
        self.client = APIClient()

    def _employee(self, emp_no, name, cat):
        e = Employee.objects.create(
            emp_no=emp_no, full_name=name, nationality="Maldivian",
            job_category=cat, basic_pay=PAY, currency="MVR",
            engagement_type=Employee.Engagement.DIRECT, is_active=True,
            join_date=date(2026, 1, 1))
        EmployeeSiteAllocation.objects.create(employee=e, site=self.site,
                                              from_date=date(2026, 1, 1))
        return e

    def roster(self, user):
        self.client.force_authenticate(user)
        r = self.client.get(f"/api/v1/sites/{self.site.id}/direct-workers")
        self.assertEqual(r.status_code, 200)
        return {row["emp_no"]: row for row in r.data}


class WorkforceRosterTests(StaffPayBase):
    def test_site_roles_see_worker_pay_but_not_management_pay(self):
        for user in (self.pm, self.se):
            with self.subTest(role=user.role):
                rows = self.roster(user)
                self.assertIsNone(rows["EMP-9001"]["basic_pay"])
                self.assertTrue(rows["EMP-9001"]["pay_hidden"])
                # the worker they actually manage is untouched
                self.assertEqual(Decimal(rows["EMP-9002"]["basic_pay"]), PAY)
                self.assertFalse(rows["EMP-9002"]["pay_hidden"])

    def test_hr_sees_both(self):
        rows = self.roster(self.hr)
        self.assertEqual(Decimal(rows["EMP-9001"]["basic_pay"]), PAY)
        self.assertEqual(Decimal(rows["EMP-9002"]["basic_pay"]), PAY)

    def test_director_is_excluded_too(self):
        """Owner was explicit: the PD is not a pay-seeing role."""
        self.assertTrue(self.roster(self.director)["EMP-9001"]["pay_hidden"])

    def test_pm_cannot_revise_a_management_salary(self):
        self.client.force_authenticate(self.pm)
        r = self.client.post("/api/v1/salary-revisions", {
            "site_id": self.site.id, "employee_id": self.manager.id,
            "to_basic_pay": "30000", "reason": "performance"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("HR", r.data["detail"])
        # but a worker's revision still goes through
        r = self.client.post("/api/v1/salary-revisions", {
            "site_id": self.site.id, "employee_id": self.worker.id,
            "to_basic_pay": "30000", "reason": "performance"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Decimal(r.data["to_basic_pay"]), Decimal("30000"))


class OnboardingStaffCaseTests(StaffPayBase):
    def _case(self, actor, category="STAFF"):
        case, msg = ob.create_case(self.site, {
            "full_name": "New Manager", "nationality": "Sri Lankan",
            "passport_no": "N7788991", "category": category,
            "trade_designation": "MEP Engineer", "route": "WP",
            "proposed_salary": "32000", "currency": "MVR"}, actor)
        return case, msg

    def test_pm_cannot_raise_a_management_hire(self):
        case, msg = self._case(self.pm)
        self.assertIsNone(case)
        self.assertIn("HR", msg)

    def test_pm_can_still_raise_a_worker(self):
        case, msg = self._case(self.pm, category="SKILLED")
        self.assertIsNone(msg)
        self.assertIsNotNone(case)

    def test_pm_reading_a_management_case_gets_no_salary(self):
        case, msg = self._case(self.hr)
        self.assertIsNone(msg)
        self.client.force_authenticate(self.pm)
        r = self.client.get("/api/v1/onboarding")
        self.assertEqual(r.status_code, 200)
        row = next(c for c in r.data if c["id"] == case.document_id)
        self.assertIsNone(row["proposed_salary"])
        self.assertEqual(row["allowances"], [])
        self.assertTrue(row["pay_hidden"])
        # and on the case detail, not only the list
        d = self.client.get(f"/api/v1/onboarding/{case.document_id}")
        self.assertIsNone(d.data["proposed_salary"])
        self.assertTrue(d.data["pay_hidden"])

    def test_hr_still_reads_the_salary(self):
        case, _ = self._case(self.hr)
        self.client.force_authenticate(self.hr)
        d = self.client.get(f"/api/v1/onboarding/{case.document_id}")
        self.assertEqual(Decimal(d.data["proposed_salary"]),
                         Decimal("32000"))
        self.assertFalse(d.data.get("pay_hidden", False))

    def test_a_worker_case_keeps_its_salary_visible_to_the_pm(self):
        case, _ = self._case(self.hr, category="SKILLED")
        self.client.force_authenticate(self.pm)
        d = self.client.get(f"/api/v1/onboarding/{case.document_id}")
        self.assertEqual(Decimal(d.data["proposed_salary"]),
                         Decimal("32000"))

    def test_an_editor_without_pay_sight_cannot_blank_the_salary(self):
        """The Director raises management hires but does not see pay — echoing
        the redacted form back must not wipe the real figure."""
        case, _ = self._case(self.hr)
        msg = ob.update_case(case, {"proposed_salary": None, "allowances": [],
                                    "mobile": "7777777"}, self.director)
        self.assertIsNone(msg)
        case.refresh_from_db()
        self.assertEqual(case.proposed_salary, Decimal("32000"))
        self.assertEqual(case.mobile, "7777777")   # the rest of the edit stuck
