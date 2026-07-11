"""Payroll build — overtime rate master + per-worker resolution + advances."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import payroll
from .models import (CostHead, Document, Employee, ManpowerCategory,
                     OvertimeRate, SalaryAdvance, Site, SitePmHistory, User)
from .tests import make_user


class OvertimeRateTests(TestCase):
    def setUp(self):
        self.hr = make_user("hr1", User.Role.HO_HR)
        self.mason = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def _emp(self, **kw):
        return Employee.objects.create(
            emp_no=kw.pop("emp_no", "EMP-0001"), full_name="Test",
            job_category=self.mason, **kw)

    def test_upsert_and_list_rates(self):
        r = self.client.post("/api/v1/overtime-rates", {
            "category_id": self.mason.id, "currency": "MVR",
            "rate_per_hour": 25, "applies_by_default": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        # upsert again updates in place, not duplicates
        self.client.post("/api/v1/overtime-rates", {
            "category_id": self.mason.id, "currency": "MVR",
            "rate_per_hour": 30}, format="json")
        self.assertEqual(OvertimeRate.objects.filter(
            category=self.mason, currency="MVR").count(), 1)
        listing = self.client.get("/api/v1/overtime-rates").data
        mason = next(c for c in listing if c["category_id"] == self.mason.id)
        self.assertEqual(float(mason["rates"]["MVR"]["rate_per_hour"]), 30.0)

    def test_worker_inherits_category_default(self):
        OvertimeRate.objects.create(category=self.mason, currency="MVR",
                                    rate_per_hour=Decimal("25"),
                                    applies_by_default=True)
        emp = self._emp(currency="MVR")  # ot_applies None -> inherit
        self.assertEqual(emp.ot_rate(), Decimal("25"))

    def test_worker_override_off(self):
        OvertimeRate.objects.create(category=self.mason, currency="MVR",
                                    rate_per_hour=Decimal("25"),
                                    applies_by_default=True)
        emp = self._emp(currency="MVR", ot_applies=False)
        self.assertEqual(emp.ot_rate(), Decimal("0"))

    def test_category_default_off_but_worker_on(self):
        OvertimeRate.objects.create(category=self.mason, currency="MVR",
                                    rate_per_hour=Decimal("25"),
                                    applies_by_default=False)
        # inherit -> off
        self.assertEqual(self._emp(emp_no="EMP-0002").ot_rate(), Decimal("0"))
        # explicit on -> gets the rate
        emp = self._emp(emp_no="EMP-0003", ot_applies=True)
        self.assertEqual(emp.ot_rate(), Decimal("25"))

    def test_currency_specific_rate(self):
        OvertimeRate.objects.create(category=self.mason, currency="USD",
                                    rate_per_hour=Decimal("3"),
                                    applies_by_default=True)
        # an MVR worker has no MVR rate -> 0
        self.assertEqual(self._emp(emp_no="EMP-0004", currency="MVR").ot_rate(),
                         Decimal("0"))
        self.assertEqual(self._emp(emp_no="EMP-0005", currency="USD").ot_rate(),
                         Decimal("3"))


class SalaryAdvanceTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.sa = make_user("sa1", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.head = CostHead.objects.get(name="Transport & Freight")
        self.e1 = Employee.objects.create(emp_no="EMP-0001", full_name="A")
        self.e2 = Employee.objects.create(emp_no="EMP-0002", full_name="B")
        self.client = APIClient()
        self.client.force_authenticate(self.sa)

    def _raise(self):
        return self.client.post("/api/v1/documents", {
            "doc_type": "PYR", "site_id": self.site.id, "payload": {},
            "cost_head_id": self.head.id, "payment_method": "CASH",
            "has_supporting_doc": True,
            "salary_lines": [
                {"employee_id": self.e1.id, "kind": "ADVANCE", "amount": 2000},
                {"employee_id": self.e2.id, "kind": "LOAN", "amount": 6000,
                 "months": 3},
            ],
            "deduct_year": 2026, "deduct_month": 6,
        }, format="json")

    def test_advance_pyr_creates_lines_and_totals(self):
        r = self._raise()
        self.assertEqual(r.status_code, 201, r.data)
        pr = r.data["payment_request"]
        self.assertEqual(pr["payment_type"], "ADVANCE")
        self.assertEqual(float(pr["amount_requested"]), 8000.0)  # 2000 + 6000
        self.assertEqual(len(pr["salary_advances"]), 2)
        self.assertEqual(SalaryAdvance.objects.count(), 2)

    def test_deductions_only_after_paid(self):
        ref = self._raise().data["ref"]
        doc = Document.objects.get(ref=ref)
        # not paid yet -> nothing deducted
        self.assertEqual(payroll.deductions_for(self.e1, 2026, 6),
                         {"advance": Decimal("0"), "loan": Decimal("0")})
        doc.status = "PAID"
        doc.save(update_fields=["status"])
        # advance: full 2000 in June only
        self.assertEqual(payroll.deductions_for(self.e1, 2026, 6)["advance"],
                         Decimal("2000.00"))
        self.assertEqual(payroll.deductions_for(self.e1, 2026, 7)["advance"],
                         Decimal("0"))

    def test_loan_spreads_over_months(self):
        ref = self._raise().data["ref"]
        doc = Document.objects.get(ref=ref)
        doc.status = "PAID"
        doc.save(update_fields=["status"])
        # 6000 / 3 = 2000 per month, June..August
        for m in (6, 7, 8):
            self.assertEqual(payroll.deductions_for(self.e2, 2026, m)["loan"],
                             Decimal("2000.00"))
        self.assertEqual(payroll.deductions_for(self.e2, 2026, 9)["loan"],
                         Decimal("0"))
