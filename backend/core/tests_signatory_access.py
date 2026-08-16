"""The authorised signatory reads every module and writes none of them.

Owner, 2026-08-16: "signatories need to have access across whole app. right now
I see some limitations like HR, procurement etc." They sign every rufiyaa out of
the company, so being shut out of the HR, payroll, procurement and finance
screens behind the payments they authorise was wrong. Widening a read gate is
easy to do and easy to overshoot, so this file pins BOTH halves — the doors that
opened and the ones that stayed shut.
"""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Site, User
from .tests import make_user


class SignatoryReadAccessTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.sig = make_user("sig", User.Role.SIGNATORY)
        self.client = APIClient()
        self.client.force_authenticate(self.sig)

    def test_reads_every_module(self):
        y, m = date.today().year, date.today().month
        for url in (
            "/api/v1/dashboards/hr",                      # HR dashboard
            "/api/v1/payroll/runs",                       # payroll register
            f"/api/v1/payroll/readiness?year={y}&month={m}",
            "/api/v1/onboarding",                         # onboarding
            "/api/v1/onboarding/bv-register",
            "/api/v1/dashboards/ho",                      # purchasing
            "/api/v1/items",
            "/api/v1/suppliers",
            "/api/v1/finance/dashboard",                  # finance
            "/api/v1/finance/payables",
            "/api/v1/ipr/payments-due",
            "/api/v1/receivables/aging",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_writes_stay_shut(self):
        """Reading the module is not authority to run it — the roles that own
        each write keep it."""
        cases = [
            # generating a payroll run stays with HR
            ("post", "/api/v1/payroll/runs",
             {"year": 2026, "month": 7, "site_id": self.site.id}),
            # so does building a voucher (Finance)
            ("post", "/api/v1/payment-vouchers", {"source_refs": []}),
            # and maintaining the item catalogue (HO Purchasing)
            ("post", "/api/v1/items", {"code": "X1", "description": "x",
                                       "unit": "no"}),
        ]
        for method, url, body in cases:
            with self.subTest(url=url):
                r = getattr(self.client, method)(url, body, format="json")
                self.assertEqual(r.status_code, 403, f"{url} -> {r.status_code}")
