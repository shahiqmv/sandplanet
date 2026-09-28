"""Individual staff cost report over a date range (owner 2026-09-28)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Attendance, Document, Employee, EmployeeSiteAllocation,
                     ManpowerCategory, OvertimeRate, SalaryAdvance, Site, User)
from .tests import make_user


class StaffCostReportTests(TestCase):
    def setUp(self):
        from core import payroll
        self.hr = make_user("scr_hr", User.Role.HO_HR)
        self.site = Site.objects.create(code="SCR", name="Cost Isle",
                                        status=Site.Status.ACTIVE)
        cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        OvertimeRate.objects.create(category=cat, currency="MVR",
                                    rate_per_hour=Decimal("25"),
                                    applies_by_default=True)
        self.emp = Employee.objects.create(
            emp_no="EMP-7101", full_name="Worker Cost", basic_pay=6200,
            currency="MVR", job_category=cat, join_date=date(2026, 1, 1))
        EmployeeSiteAllocation.objects.create(
            employee=self.emp, site=self.site, from_date=date(2026, 1, 1))
        mk = lambda d, remark="PRESENT", **kw: Attendance.objects.create(  # noqa: E731
            employee=self.emp, site=self.site, day=d, remark=remark, **kw)
        mk(date(2026, 5, 4), ot_requested=2, ot_approved=Decimal("2"))
        mk(date(2026, 5, 5), "HALF_DAY")
        mk(date(2026, 5, 6), "ABSENT")
        mk(date(2026, 5, 7), ot_requested=3)                  # not decided
        mk(date(2026, 5, 8), ot_requested=12, ot_approved=Decimal("12"))  # Friday
        self.run = payroll.generate_run(site=self.site, currency="MVR",
                                        year=2026, month=5, working_days=31,
                                        actor=self.hr)
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def url(self, extra=""):
        return (f"/api/v1/employees/{self.emp.id}/cost-report"
                f"?from=2026-05-01&to=2026-05-10{extra}")

    def test_attendance_ot_and_pay_in_one_place(self):
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200, r.data)
        att, ot = r.data["attendance"], r.data["ot"]
        counts = {c["key"]: c["days"] for c in att["counts"]}
        self.assertEqual((counts["PRESENT"], counts["HALF_DAY"],
                          counts["ABSENT"]), (3, 1, 1))
        self.assertEqual(att["worked"], Decimal("3.5"))
        self.assertEqual(att["rest_days_worked"], 1)
        self.assertEqual(att["unmarked"], 5)
        # Friday OT is shown apart: the flat Friday pay covers that day
        self.assertEqual((ot["approved"], ot["workday"], ot["rest_day"],
                          ot["pending"], ot["pending_days"]),
                         (Decimal("14"), Decimal("2"), Decimal("12"),
                          Decimal("3"), 1))
        self.assertEqual(len(r.data["pay"]), 1)
        p = r.data["pay"][0]
        self.assertTrue(p["part_month"])
        self.assertEqual(p["ot_pay"], Decimal("50.00"))
        self.assertEqual(r.data["not_run"], [])

    def test_an_advance_raised_in_the_range_is_listed(self):
        doc = Document.objects.create(doc_type="PYR", ref="PYR-SCR-001",
                                      site=self.site, status="PAID",
                                      doc_date=date(2026, 5, 3),
                                      created_by=self.hr)
        SalaryAdvance.objects.create(document=doc, employee=self.emp,
                                     amount=Decimal("1000"), period_year=2026,
                                     period_month=5)
        r = self.client.get("/api/v1/employees/%d/cost-report?from=%s&to=%s"
                            % (self.emp.id, date.today(), date.today()))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([(a["ref"], a["status"]) for a in r.data["advances"]],
                         [("PYR-SCR-001", "Paid")])

    def test_months_without_a_run_are_named(self):
        r = self.client.get(f"/api/v1/employees/{self.emp.id}/cost-report"
                            "?from=2026-05-01&to=2026-06-30")
        self.assertEqual(r.data["not_run"], ["Jun 2026"])

    def test_pdf_and_workbook(self):
        r = self.client.get(self.url("&export=xlsx"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"PK"))
        r = self.client.get(self.url("&export=pdf"))
        self.assertIn(r.status_code, (200, 503))   # 503 = no PDF engine here

    def test_site_roles_cannot_see_pay(self):
        c = APIClient()
        c.force_authenticate(make_user("scr_pm", User.Role.PM))
        self.assertEqual(c.get(self.url()).status_code, 403)

    def test_bad_range_is_refused(self):
        r = self.client.get(f"/api/v1/employees/{self.emp.id}/cost-report"
                            "?from=2026-05-10&to=2026-05-01")
        self.assertEqual(r.status_code, 400)
