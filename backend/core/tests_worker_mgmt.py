"""Site worker-management tool: SA/SE add/remove/transfer DIRECT workers in
approval BATCHES; PM (and, for new hires, Director) approve the whole batch."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Employee, EmployeeSiteAllocation, ManpowerCategory, Site,
                     SitePmHistory, User)
from .tests import make_user


class WorkerBatchTests(TestCase):
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

    def _auth(self, u):
        self.client.force_authenticate(u)

    def _worker(self, name, **kw):
        return {"full_name": name, "passport_no": f"P-{name}",
                "nationality": "IND", "basic_pay": "6000",
                "job_category_id": self.mason.id, **kw}

    def _add_batch(self, workers):
        return self.client.post(f"/api/v1/sites/{self.site.id}/worker-batches",
                                {"kind": "ADD", "workers": workers},
                                format="json")

    def _direct(self, site, n=1):
        out = []
        for _ in range(n):
            e = Employee.objects.create(
                emp_no=f"EMP-{Employee.objects.count()+1:04d}",
                full_name=f"W{Employee.objects.count()}",
                job_category=self.mason, basic_pay=Decimal("6000"),
                is_active=True)
            EmployeeSiteAllocation.objects.create(
                employee=e, site=site, from_date=date(2026, 1, 1))
            out.append(e)
        return out

    # ---- ADD -----------------------------------------------------------------

    def test_add_batch_lifecycle(self):
        r = self._add_batch([self._worker("Aay"), self._worker("Bee")])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["worker_count"], 2)
        bid = r.data["id"]
        emp_ids = [w["id"] for w in r.data["workers"]]
        # both pending + inactive → out of payroll
        for eid in emp_ids:
            e = Employee.objects.get(pk=eid)
            self.assertFalse(e.is_active)
            self.assertTrue(e.hire_pending)
            self.assertNotIn(eid, Employee.objects.payroll_eligible()
                             .filter(is_active=True).values_list("id",
                                                                 flat=True))
        # SA can't approve
        r = self.client.post(f"/api/v1/worker-batches/{bid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 400)
        # PM → PM_APPROVED (still inactive)
        self._auth(self.pm)
        r = self.client.post(f"/api/v1/worker-batches/{bid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.data["status"], "PM_APPROVED")
        self.assertFalse(Employee.objects.get(pk=emp_ids[0]).is_active)
        # PM can't do the Director step
        r = self.client.post(f"/api/v1/worker-batches/{bid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 400)
        # Director activates the whole batch
        self._auth(self.director)
        r = self.client.post(f"/api/v1/worker-batches/{bid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.data["status"], "APPROVED")
        for eid in emp_ids:
            e = Employee.objects.get(pk=eid)
            self.assertTrue(e.is_active)
            self.assertFalse(e.hire_pending)
            self.assertEqual(e.current_site_id(), self.site.id)

    def test_add_validates_each_worker(self):
        r = self._add_batch([self._worker("Ok"),
                            self._worker("Bad", passport_no="")])
        self.assertEqual(r.status_code, 400)
        self.assertIn("Worker 2", r.data["detail"])

    def test_edit_pending_hire_then_resubmit(self):
        r = self._add_batch([self._worker("Cee")])
        bid, eid = r.data["id"], r.data["workers"][0]["id"]
        self._auth(self.pm)
        self.client.post(f"/api/v1/worker-batches/{bid}/action",
                         {"action": "return", "note": "fix pay"},
                         format="json")
        self._auth(self.sa)
        r = self.client.patch(f"/api/v1/worker-hires/{eid}",
                              {"basic_pay": "9000"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Decimal(r.data["basic_pay"]), Decimal("9000"))
        r = self.client.post(f"/api/v1/worker-batches/{bid}/action",
                             {"action": "resubmit"}, format="json")
        self.assertEqual(r.data["status"], "SUBMITTED")

    # ---- REMOVE / TRANSFER ---------------------------------------------------

    def test_remove_batch(self):
        emps = self._direct(self.site, 2)
        r = self.client.post(f"/api/v1/sites/{self.site.id}/worker-batches",
                             {"kind": "REMOVE",
                              "employee_ids": [e.id for e in emps],
                              "reason": "done"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        bid = r.data["id"]
        self._auth(self.pm)
        r = self.client.post(f"/api/v1/worker-batches/{bid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.data["status"], "APPROVED")
        for e in emps:
            e.refresh_from_db()
            self.assertFalse(e.is_active)

    def test_transfer_batch(self):
        emps = self._direct(self.site, 2)
        r = self.client.post(f"/api/v1/sites/{self.site.id}/worker-batches",
                             {"kind": "TRANSFER",
                              "employee_ids": [e.id for e in emps],
                              "to_site_id": self.dest.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        bid = r.data["id"]
        self._auth(self.pm)
        self.client.post(f"/api/v1/worker-batches/{bid}/action",
                         {"action": "approve"}, format="json")
        for e in emps:
            e.refresh_from_db()
            self.assertEqual(e.current_site_id(), self.dest.id)

    def test_worker_cannot_be_in_two_open_batches(self):
        emp = self._direct(self.site, 1)[0]
        self.client.post(f"/api/v1/sites/{self.site.id}/worker-batches",
                         {"kind": "REMOVE", "employee_ids": [emp.id]},
                         format="json")
        r = self.client.post(f"/api/v1/sites/{self.site.id}/worker-batches",
                             {"kind": "TRANSFER", "employee_ids": [emp.id],
                              "to_site_id": self.dest.id}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_other_site_pm_cannot_approve(self):
        bid = self._add_batch([self._worker("Dee")]).data["id"]
        other = make_user("pm2", User.Role.PM, site=self.dest)
        SitePmHistory.objects.create(site=self.dest, pm_user=other,
                                     from_date=date(2026, 1, 1))
        self._auth(other)
        r = self.client.post(f"/api/v1/worker-batches/{bid}/action",
                             {"action": "approve"}, format="json")
        self.assertEqual(r.status_code, 400)
