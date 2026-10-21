"""Bringing back a worker who left (owner 2026-10-21).

EMP-0867 left MXR on 1 October and came back; the site's hire form refused
his passport ("ask HR to transfer him") and HR had no way to bring him back
either. Now the hire form offers him back on his own record, through the
same PM → Director approval, and HR can re-engage him directly.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Employee, EmployeeSiteAllocation, ManpowerCategory, Site,
                     SitePmHistory, User)
from .tests import make_user


class RehireTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="MXR", name="Max Royal",
                                        status=Site.Status.ACTIVE)
        self.other = Site.objects.create(code="SJR", name="Jani",
                                         status=Site.Status.ACTIVE)
        self.cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Skilled Labour",
            sort_order=10)
        self.mason = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=20)
        self.sa = make_user("rh_sa", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("rh_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.director = make_user("rh_dir", User.Role.DIRECTOR)
        self.hr = make_user("rh_hr", User.Role.HO_HR)
        left = date.today() - timedelta(days=20)
        self.gone = Employee.objects.create(
            emp_no="EMP-0867", full_name="Asamrat Hossan",
            passport_no="EK0720872", nationality="Bangladeshi",
            job_category=self.cat, basic_pay=Decimal("8000"),
            is_active=False, left_on=left,
            join_date=left - timedelta(days=7))
        EmployeeSiteAllocation.objects.create(
            employee=self.gone, site=self.site,
            from_date=left - timedelta(days=7), to_date=left)
        self.c = APIClient()

    def post_hire(self, row):
        self.c.force_authenticate(self.sa)
        return self.c.post(f"/api/v1/sites/{self.site.id}/worker-batches",
                           {"kind": "ADD", "workers": [row]}, format="json")

    def act(self, user, bid):
        self.c.force_authenticate(user)
        return self.c.post(f"/api/v1/worker-batches/{bid}/action",
                           {"action": "approve"}, format="json")

    def row(self, **kw):
        return {"full_name": "Shamrat Hossain", "passport_no": "EK0720872",
                "nationality": "Bangladeshi", "job_category_id": self.mason.id,
                "basic_pay": "8500", "currency": "MVR", **kw}

    def test_the_hire_form_offers_him_back_and_approval_restores_him(self):
        r = self.post_hire(self.row())
        self.assertEqual(r.status_code, 400)
        self.assertIn("left MXR", r.data["detail"])
        self.assertEqual(r.data["rehire"]["emp_no"], "EMP-0867")
        self.assertEqual(r.data["rehire"]["row"], 0)
        n = Employee.objects.count()
        r = self.post_hire(self.row(rehire_employee_id=self.gone.id))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Employee.objects.count(), n)        # no new record
        self.assertTrue(r.data["workers"][0]["is_rehire"])
        self.gone.refresh_from_db()
        self.assertFalse(self.gone.is_active)                # until approved
        self.assertTrue(self.gone.hire_pending)
        bid = r.data["id"]
        self.assertEqual(self.act(self.pm, bid).data["status"], "PM_APPROVED")
        self.assertEqual(self.act(self.director, bid).data["status"],
                         "APPROVED")
        self.gone.refresh_from_db()
        self.assertTrue(self.gone.is_active)
        self.assertFalse(self.gone.hire_pending)
        self.assertIsNone(self.gone.left_on)
        self.assertEqual(self.gone.join_date, date.today())  # pay from return
        # his name stays as recorded; the terms he returns on are taken
        self.assertEqual(self.gone.full_name, "Asamrat Hossan")
        self.assertEqual(self.gone.job_category_id, self.mason.id)
        self.assertEqual(self.gone.basic_pay, Decimal("8500"))
        allocs = list(self.gone.site_allocations.order_by("from_date")
                      .values_list("site__code", "to_date"))
        self.assertEqual(len(allocs), 2)
        self.assertIsNotNone(allocs[0][1])                   # old one closed
        self.assertEqual(allocs[1], ("MXR", None))

    def test_cancelling_a_return_leaves_him_as_he_was(self):
        r = self.post_hire(self.row(rehire_employee_id=self.gone.id))
        self.c.force_authenticate(self.sa)
        self.c.post(f"/api/v1/worker-batches/{r.data['id']}/action",
                    {"action": "cancel"}, format="json")
        self.gone.refresh_from_db()
        self.assertFalse(self.gone.hire_pending)
        self.assertFalse(self.gone.is_active)
        self.assertEqual(self.gone.passport_no, "EK0720872")  # not released
        self.assertNotIn("cancelled", self.gone.full_name)

    def test_an_active_man_is_still_a_transfer_not_a_return(self):
        self.gone.is_active = True
        self.gone.left_on = None
        self.gone.save()
        r = self.post_hire(self.row())
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("rehire", r.data)
        self.assertIn("transfer", r.data["detail"])

    def test_hr_re_engages_him_directly(self):
        self.c.force_authenticate(self.sa)
        url = f"/api/v1/employees/{self.gone.id}/reengage"
        self.assertEqual(self.c.post(url, {"site_id": self.other.id},
                                     format="json").status_code, 403)
        self.c.force_authenticate(self.hr)
        # not before his last allocation ended
        r = self.c.post(url, {"site_id": self.other.id,
                              "from_date": str(self.gone.left_on)},
                        format="json")
        self.assertEqual(r.status_code, 400)
        r = self.c.post(url, {"site_id": self.other.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.gone.refresh_from_db()
        self.assertTrue(self.gone.is_active)
        self.assertIsNone(self.gone.left_on)
        self.assertEqual(self.gone.current_site_id(), self.other.id)
        # and not twice
        self.assertEqual(self.c.post(url, {"site_id": self.other.id},
                                     format="json").status_code, 400)
