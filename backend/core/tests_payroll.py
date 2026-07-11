"""Payroll build — overtime rate master + per-worker resolution."""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Employee, ManpowerCategory, OvertimeRate, User
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
