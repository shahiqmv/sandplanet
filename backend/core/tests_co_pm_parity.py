"""A co-PM has the same authority as the PM assigned first.

A busy site carries more than one current PM and they share full PM authority.
Several gates asked the site for `current_pm()`, which answers "the earliest
assigned", and compared ids — so the second PM was refused on his own site
(owner 2026-09-08). Documents were already right; these were not.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Attendance, CompanyParameter, Employee, ManpowerCategory,
                     Project, Site, SitePmHistory, User)
from .tests import make_user


class CoPmParityTests(TestCase):
    def setUp(self):
        CompanyParameter.objects.update_or_create(
            key="usd_mvr_rate", defaults={"value": "1"})
        self.site = Site.objects.create(
            code="SJR", name="Soneva Jani", status=Site.Status.ACTIVE,
            contract_value=Decimal("1000000"),
            start_date=date.today() - timedelta(days=60))
        self.first = make_user("pm_first", User.Role.PM, site=self.site)
        self.second = make_user("pm_second", User.Role.PM, site=self.site)
        self.stranger = make_user("pm_other", User.Role.PM)
        # The order matters: `current_pm()` returns whoever came first.
        SitePmHistory.objects.create(site=self.site, pm_user=self.first,
                                     from_date=date.today() - timedelta(days=30))
        SitePmHistory.objects.create(site=self.site, pm_user=self.second,
                                     from_date=date.today())
        self.hr = make_user("copm_hr", User.Role.HO_HR)
        self.client = APIClient()

    def test_the_site_really_has_two_current_pms(self):
        self.assertEqual(self.site.current_pm(), self.first)
        self.assertTrue(self.site.is_current_pm(self.second))

    def test_both_pms_see_the_site_cost(self):
        for pm in (self.first, self.second):
            self.client.force_authenticate(pm)
            r = self.client.get(f"/api/v1/cost/site/{self.site.id}")
            self.assertEqual(r.status_code, 200, f"{pm.username}: {r.data}")
        self.client.force_authenticate(self.stranger)
        self.assertEqual(self.client.get(
            f"/api/v1/cost/site/{self.site.id}").status_code, 403)

    def test_both_pms_see_a_projects_contract_value(self):
        from .views_projects import _can_view_value
        p = Project.objects.create(site=self.site, code="SJR-01",
                                   title="Jetty", status="ACTIVE")
        self.assertTrue(_can_view_value(self.first, p))
        self.assertTrue(_can_view_value(self.second, p))
        self.assertFalse(_can_view_value(self.stranger, p))

    def _ot_row(self):
        cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        emp = Employee.objects.create(
            emp_no="EMP-9001", full_name="OT Man", job_category=cat,
            is_active=True, join_date=date(2026, 1, 1))
        return Attendance.objects.create(
            employee=emp, site=self.site, day=date.today(), remark="PRESENT",
            ot_requested=Decimal("2"))

    def test_the_second_pm_can_approve_overtime(self):
        row = self._ot_row()
        self.client.force_authenticate(self.second)
        r = self.client.post("/api/v1/attendance/ot-approve",
                             {"ids": [row.id]}, format="json")
        self.assertNotEqual(r.status_code, 403, r.data)

    def test_a_pm_from_another_site_still_cannot(self):
        row = self._ot_row()
        self.client.force_authenticate(self.stranger)
        r = self.client.post("/api/v1/attendance/ot-approve",
                             {"ids": [row.id]}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_the_second_pm_can_sign_off_and_reopen_the_month(self):
        t = date.today()
        base = f"/api/v1/timesheets/{self.site.id}/{t.year}/{t.month}"
        self.client.force_authenticate(self.second)
        self.assertNotEqual(self.client.post(f"{base}/lock", {},
                                             format="json").status_code, 403)
        r = self.client.post(f"{base}/reopen", {"reason": "correction"},
                             format="json")
        self.assertNotEqual(r.status_code, 403, r.data)

    def test_a_pm_from_another_site_cannot_sign_off(self):
        t = date.today()
        self.client.force_authenticate(self.stranger)
        r = self.client.post(
            f"/api/v1/timesheets/{self.site.id}/{t.year}/{t.month}/lock", {},
            format="json")
        self.assertEqual(r.status_code, 403)

    def test_every_current_pm_is_alerted_not_only_the_first(self):
        from .notify import _pm_for

        class Doc:
            project_id = None
            site_id = 1
        d = Doc()
        d.site = self.site
        self.assertEqual(set(_pm_for(d)), {self.first, self.second})
