"""Site worker-management tool: SA/SE add/remove/transfer DIRECT workers with
PM (and, for a new hire, Director) approval."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Employee, EmployeeSiteAllocation, ManpowerCategory, Site,
                     SitePmHistory, User)
from .models import WorkerChangeRequest as WCR
from .tests import make_user


class WorkerManagementTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.dest = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.mason = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.sa = make_user("sa", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.director = make_user("dir", User.Role.DIRECTOR)
        self.client = APIClient()
        self.client.force_authenticate(self.sa)

    ADD = {"full_name": "New Guy", "passport_no": "P123", "nationality": "IND",
           "basic_pay": "6000", "currency": "MVR"}

    def _auth(self, u):
        self.client.force_authenticate(u)

    def _add(self, extra=None):
        body = {**self.ADD, **(extra or {})}
        return self.client.post(
            f"/api/v1/sites/{self.site.id}/worker-requests/add", body,
            format="json")

    # ---- ADD -----------------------------------------------------------------

    def test_add_requires_passport_and_nationality(self):
        r = self._add({"passport_no": ""})
        self.assertEqual(r.status_code, 400)
        r = self._add({"nationality": ""})
        self.assertEqual(r.status_code, 400)

    def test_add_lifecycle_pm_then_director(self):
        r = self._add({"job_category_id": self.mason.id})
        self.assertEqual(r.status_code, 201, r.data)
        req_id = r.data["id"]
        emp_id = r.data["employee"]["id"]
        # pending hire is inactive → out of attendance + payroll
        emp = Employee.objects.get(pk=emp_id)
        self.assertFalse(emp.is_active)
        self.assertTrue(emp.hire_pending)
        self.assertNotIn(emp.id, Employee.objects.payroll_eligible()
                         .filter(is_active=True).values_list("id", flat=True))

        # SA cannot approve
        r = self.client.post(f"/api/v1/worker-requests/{req_id}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 400)

        # PM approves → PM_APPROVED (still inactive)
        self._auth(self.pm)
        r = self.client.post(f"/api/v1/worker-requests/{req_id}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.data["status"], "PM_APPROVED")
        self.assertFalse(Employee.objects.get(pk=emp_id).is_active)

        # PM cannot also do the Director step
        r = self.client.post(f"/api/v1/worker-requests/{req_id}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 400)

        # Director activates → APPROVED, live + allocated to the site
        self._auth(self.director)
        r = self.client.post(f"/api/v1/worker-requests/{req_id}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.data["status"], "APPROVED")
        emp = Employee.objects.get(pk=emp_id)
        self.assertTrue(emp.is_active)
        self.assertFalse(emp.hire_pending)
        self.assertEqual(emp.current_site_id(), self.site.id)
        self.assertIn(emp.id, Employee.objects.payroll_eligible()
                      .filter(is_active=True).values_list("id", flat=True))

    def test_edit_returned_add_resubmits(self):
        req_id = self._add().data["id"]
        self._auth(self.pm)
        self.client.post(f"/api/v1/worker-requests/{req_id}/action",
                         {"action": "return", "note": "wrong pay"},
                         format="json")
        self._auth(self.sa)
        r = self.client.patch(f"/api/v1/worker-requests/{req_id}",
                              {"basic_pay": "7000"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "SUBMITTED")
        self.assertEqual(Decimal(r.data["employee"]["basic_pay"]),
                         Decimal("7000"))

    # ---- REMOVE / TRANSFER ---------------------------------------------------

    def _direct_worker(self, site):
        e = Employee.objects.create(
            emp_no=f"EMP-{Employee.objects.count()+1:04d}", full_name="Worker",
            job_category=self.mason, basic_pay=Decimal("6000"), is_active=True)
        EmployeeSiteAllocation.objects.create(
            employee=e, site=site, from_date=date(2026, 1, 1))
        return e

    def test_remove_deactivates_on_pm_approval(self):
        emp = self._direct_worker(self.site)
        r = self.client.post(
            f"/api/v1/workers/{emp.id}/worker-requests/remove",
            {"reason": "left"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        rid = r.data["id"]
        self._auth(self.pm)
        r = self.client.post(f"/api/v1/worker-requests/{rid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.data["status"], "APPROVED")
        emp.refresh_from_db()
        self.assertFalse(emp.is_active)
        self.assertIsNone(emp.current_site_id())

    def test_transfer_moves_allocation_on_pm_approval(self):
        emp = self._direct_worker(self.site)
        r = self.client.post(
            f"/api/v1/workers/{emp.id}/worker-requests/transfer",
            {"to_site_id": self.dest.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        rid = r.data["id"]
        self._auth(self.pm)
        r = self.client.post(f"/api/v1/worker-requests/{rid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.data["status"], "APPROVED")
        emp.refresh_from_db()
        self.assertEqual(emp.current_site_id(), self.dest.id)

    def test_one_open_request_per_worker(self):
        emp = self._direct_worker(self.site)
        self.client.post(f"/api/v1/workers/{emp.id}/worker-requests/remove",
                         {}, format="json")
        r = self.client.post(
            f"/api/v1/workers/{emp.id}/worker-requests/transfer",
            {"to_site_id": self.dest.id}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_other_site_pm_cannot_approve(self):
        req_id = self._add().data["id"]
        other_pm = make_user("pm2", User.Role.PM, site=self.dest)
        SitePmHistory.objects.create(site=self.dest, pm_user=other_pm,
                                     from_date=date(2026, 1, 1))
        self._auth(other_pm)
        r = self.client.post(f"/api/v1/worker-requests/{req_id}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 400)
