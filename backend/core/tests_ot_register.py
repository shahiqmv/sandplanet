"""The OT register's month view, and half a Friday (owner 2026-11-01)."""
from datetime import date
from decimal import Decimal as D

from django.test import TestCase
from rest_framework.test import APIClient

from . import payroll
from .models import (Attendance, Employee, EmployeeSiteAllocation,
                     ManpowerCategory, PayrollLine, PayrollRun, Site, User)
from .tests import make_user

# 2026-10: the 2nd, 9th, 16th, 23rd and 30th are Fridays
FRI, FRI2, MON = date(2026, 10, 2), date(2026, 10, 9), date(2026, 10, 5)


class Base(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="OTR", name="OT site")
        self.other = Site.objects.create(code="OTX", name="Elsewhere")
        cat = ManpowerCategory.objects.create(name="Mason", list_type="DPR",
                                              grp="LABOUR", sort_order=1)
        self.emp = Employee.objects.create(
            emp_no="EMP-T01", full_name="Person T", basic_pay=D("9000"),
            currency="MVR", job_category=cat, employment_type="PERMANENT",
            engagement_type="DIRECT", join_date=date(2026, 1, 1))
        EmployeeSiteAllocation.objects.create(employee=self.emp, site=self.site,
                                              from_date=date(2026, 1, 1))
        self.pm = make_user("otr_pm", User.Role.PM, site=self.site)
        self.hr = make_user("otr_hr", User.Role.HO_HR)
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def mark(self, day, remark="PRESENT", req=0, appr=None, by=None):
        return Attendance.objects.create(
            employee=self.emp, site=self.site, day=day, remark=remark,
            ot_requested=req, ot_approved=appr, ot_approved_by=by)


class HalfFridayTests(Base):
    def prefill(self):
        return payroll._attendance_prefill(self.emp, self.site, 2026, 10, 31)

    def test_half_a_friday_counts_half(self):
        self.mark(FRI, "HALF_DAY")
        self.mark(FRI2)
        _days, _ot, fridays, _rest = self.prefill()
        self.assertEqual(fridays, D("1.5"))

    def test_it_pays_half_the_flat_hours(self):
        self.mark(FRI, "HALF_DAY")
        run = PayrollRun(working_days=31)
        pay = payroll.compute_line(PayrollLine(
            run=run, employee=self.emp, basic_pay=0, ot_rate=D("50"),
            days_worked=0, ot_hours=0,
            fridays_worked=self.prefill()[2]), fri_hours=D("12"))
        self.assertEqual(pay["friday_pay"], D("300.00"))     # 6 h × 50

    def test_the_flat_pay_covers_its_hours_as_on_a_whole_friday(self):
        self.mark(FRI, "HALF_DAY", req=5, appr=5)
        self.mark(MON, req=2, appr=2)
        self.assertEqual(self.prefill()[1], D("2"))

    def test_the_rest_day_itself_is_still_paid_whole(self):
        self.mark(FRI, "HALF_DAY")
        with_half = self.prefill()[0]
        Attendance.objects.filter(employee=self.emp).update(remark="PRESENT")
        self.assertEqual(with_half, self.prefill()[0])

    def test_a_weekday_half_day_is_no_friday(self):
        self.mark(MON, "HALF_DAY")
        self.assertEqual(self.prefill()[2], D("0"))

    def test_a_split_across_sites_shares_the_half(self):
        split = [{"site": self.site.id, "days": "10", "ot_hours": "0",
                  "fridays": 0.5},
                 {"site": self.other.id, "days": "10", "ot_hours": "0",
                  "fridays": 1.5}]
        run = PayrollRun(working_days=30)
        line = PayrollLine(run=run, employee=self.emp, site_id=self.site.id,
                           basic_pay=0, ot_rate=D("10"), days_worked=0,
                           fridays_worked=D("2"), ot_hours=0, site_split=split)
        money = {"ot_pay": D("0"), "friday_pay": D("240.00")}
        out = payroll.cost_split(line, money, D("240.00"))
        self.assertEqual((out[self.site.id], out[self.other.id]),
                         (D("60.00"), D("180.00")))


class OtRegisterTests(Base):
    def get(self, **kw):
        return self.client.get("/api/v1/attendance/ot-register", {
            "site": self.site.id, "year": 2026, "month": 10, **kw})

    def test_requested_approved_and_waiting(self):
        self.mark(MON, req=3, appr=D("2.5"), by=self.pm)
        self.mark(date(2026, 10, 6), req=4)
        self.mark(date(2026, 10, 7), req=1, appr=0, by=self.pm)   # refused
        self.mark(date(2026, 10, 8))                              # no OT
        r = self.get()
        self.assertEqual(r.status_code, 200, r.data)
        row = r.data["rows"][0]
        self.assertEqual((row["requested"], row["approved"], row["waiting"]),
                         (D("8.00"), D("2.50"), D("4.00")))
        self.assertEqual(sorted(row["days"]), ["5", "6", "7"])
        self.assertEqual(row["days"]["5"]["a"], "2.5")
        self.assertEqual(row["days"]["5"]["by"], self.pm.full_name)
        self.assertIsNone(row["days"]["6"]["a"])
        self.assertEqual(row["days"]["7"]["a"], "0")

    def test_approved_matches_what_payroll_pays(self):
        self.mark(MON, req=3, appr=3, by=self.pm)
        self.mark(FRI, req=5, appr=5, by=self.pm)
        self.mark(FRI2, "HALF_DAY", req=4, appr=4, by=self.pm)
        row = self.get().data["rows"][0]
        self.assertTrue(row["days"][str(FRI.day)]["flat"])
        self.assertTrue(row["days"][str(FRI2.day)]["flat"])
        ot = payroll._attendance_prefill(self.emp, self.site, 2026, 10, 31)[1]
        self.assertEqual(row["approved"], ot)

    def test_nobody_without_overtime_is_listed(self):
        self.mark(MON)
        self.assertEqual(self.get().data["rows"], [])

    def test_another_sites_pm_cannot_read_it(self):
        self.client.force_authenticate(
            make_user("otr_pm2", User.Role.PM, site=self.other))
        self.assertEqual(self.get().status_code, 404)

    def test_no_pay_in_the_register(self):
        self.mark(MON, req=3, appr=3, by=self.pm)
        body = str(self.get().data)
        self.assertNotIn("cost", body)
        self.assertNotIn("rate", body)
