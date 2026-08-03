"""Salary revisions — site PM proposes a worker's category/salary change, a
Director approves, and the new pay applies to the whole month it was initiated
(re-syncing a draft payroll line for that month)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (Employee, EmployeeSiteAllocation, ManpowerCategory,
                     PayrollLine, PayrollRun, Site,
                     SitePmHistory, User)
from .tests import make_user


class SalaryRevisionTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.mason = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.helper = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Helper", sort_order=20)
        self.pm = make_user("pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.sa = make_user("sa", User.Role.SITE_ADMIN, site=self.site)
        self.director = make_user("dir", User.Role.DIRECTOR)
        self.worker = Employee.objects.create(
            emp_no="EMP-0001", full_name="Ali", job_category=self.mason,
            basic_pay=Decimal("6000"), currency="MVR", is_active=True)
        EmployeeSiteAllocation.objects.create(
            employee=self.worker, site=self.site, from_date=date(2026, 1, 1))
        self.client = APIClient()

    def _create(self, actor=None, **kw):
        self.client.force_authenticate(actor or self.pm)
        body = {"site_id": self.site.id, "employee_id": self.worker.id,
                "to_category_id": self.helper.id, "to_basic_pay": "4500",
                "reason": "Below standard on finishing work", **kw}
        return self.client.post("/api/v1/salary-revisions", body, format="json")

    def _act(self, rid, action, actor):
        self.client.force_authenticate(actor)
        return self.client.post(f"/api/v1/salary-revisions/{rid}/action",
                                {"action": action}, format="json")

    def test_non_site_team_cannot_create(self):
        fin = make_user("fin", User.Role.FINANCE)
        r = self._create(actor=fin)
        self.assertEqual(r.status_code, 400)
        self.assertIn("site team", r.data["detail"])

    def test_site_admin_initiates_pm_then_director(self):
        # SA raises → awaits the PM
        r = self._create(actor=self.sa)
        self.assertEqual(r.status_code, 201, r.data)
        rid = r.data["id"]
        self.assertEqual(r.data["status"], "SUBMITTED")
        # a Director can't jump the PM step
        self.assertEqual(self._act(rid, "approve", self.director).status_code,
                         400)
        # PM approves → awaits the Director
        a = self._act(rid, "approve", self.pm)
        self.assertEqual(a.status_code, 200, a.data)
        self.assertEqual(a.data["status"], "PM_APPROVED")
        # Director approves → applied
        a = self._act(rid, "approve", self.director)
        self.assertEqual(a.data["status"], "APPROVED")
        self.worker.refresh_from_db()
        self.assertEqual(float(self.worker.basic_pay), 4500.0)
        self.assertEqual(self.worker.job_category_id, self.helper.id)

    def test_pm_initiates_straight_to_director(self):
        r = self._create(actor=self.pm)
        self.assertEqual(r.status_code, 201, r.data)
        rid = r.data["id"]
        self.assertEqual(r.data["status"], "PM_APPROVED")   # skips PM step
        # the PM cannot also clear the Director step
        self.assertEqual(self._act(rid, "approve", self.pm).status_code, 400)
        a = self._act(rid, "approve", self.director)
        self.assertEqual(a.data["status"], "APPROVED")
        self.worker.refresh_from_db()
        self.assertEqual(float(self.worker.basic_pay), 4500.0)

    def test_reject_leaves_worker_unchanged(self):
        rid = self._create().data["id"]
        self.assertEqual(self._act(rid, "reject", self.director).status_code, 200)
        self.worker.refresh_from_db()
        self.assertEqual(float(self.worker.basic_pay), 6000.0)   # unchanged
        self.assertEqual(self.worker.job_category_id, self.mason.id)

    def test_one_open_revision_per_worker(self):
        self._create()
        r2 = self._create()
        self.assertEqual(r2.status_code, 400)
        self.assertIn("in progress", r2.data["detail"])

    def _run(self, status):
        t = timezone.localdate()
        run = PayrollRun.objects.create(
            site=self.site, currency="MVR", year=t.year, month=t.month,
            working_days=26, created_by=self.director, status=status)
        return PayrollLine.objects.create(
            run=run, employee=self.worker, site=self.site,
            basic_pay=Decimal("6000"), ot_rate=Decimal("0"),
            days_worked=Decimal("26"), ot_hours=Decimal("0"),
            fridays_worked=0)

    def test_approval_resyncs_a_draft_run_whole_month(self):
        line = self._run("DRAFT")
        rid = self._create().data["id"]
        self._act(rid, "approve", self.director)
        line.refresh_from_db()
        self.assertEqual(float(line.basic_pay), 4500.0)   # whole month re-synced

    def test_locked_run_is_not_touched(self):
        line = self._run("LOCKED")
        rid = self._create().data["id"]
        self._act(rid, "approve", self.director)
        line.refresh_from_db()
        self.assertEqual(float(line.basic_pay), 6000.0)   # a paid month is frozen
        self.worker.refresh_from_db()
        self.assertEqual(float(self.worker.basic_pay), 4500.0)  # but live updates

    def test_notifies_director_then_requester(self):
        from .models import Notification
        rid = self._create().data["id"]
        self.assertTrue(Notification.objects.filter(
            recipient=self.director, category="approval").exists())
        self._act(rid, "approve", self.director)
        self.assertTrue(Notification.objects.filter(
            recipient=self.pm).exists())
