"""M7 — project cost view + portfolio roll-up (§6C.4, §6C.5)."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import costing
from .models import CompanyParameter, CostHead, Site, SitePmHistory, User
from .tests import make_user


class CostViewTests(TestCase):
    def setUp(self):
        # rate 1 → USD figures equal the MVR postings, so these aggregation
        # tests stay about the maths; conversion is checked separately below.
        CompanyParameter.objects.update_or_create(
            key="usd_mvr_rate", defaults={"value": "1"})
        self.site = Site.objects.create(
            code="SJR", name="Soneva Jani", status=Site.Status.ACTIVE,
            contract_value=Decimal("1000000"),
            start_date=date.today() - timedelta(days=50),
            planned_completion=date.today() + timedelta(days=50))
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.director = make_user("dir", User.Role.DIRECTOR)
        self.sa = make_user("sa1", User.Role.SITE_ADMIN, site=self.site)
        self.materials = CostHead.objects.get(name="Materials")
        # some cost across the three states
        costing.post(site=self.site, cost_head=self.materials,
                     state="COMMITTED", source="PR", amount=200000)
        costing.post(site=self.site, cost_head=self.materials,
                     state="INCURRED", source="PR", amount=150000)
        costing.post(site=self.site, cost_head=self.materials,
                     state="PAID", source="PR", amount=100000)
        self.client = APIClient()

    def test_costs_convert_to_usd(self):
        CompanyParameter.objects.update_or_create(
            key="usd_mvr_rate", defaults={"value": "10"})
        self.client.force_authenticate(self.director)
        r = self.client.get(f"/api/v1/cost/site/{self.site.id}")
        self.assertEqual(r.data["currency"], "USD")
        self.assertEqual(r.data["committed"], Decimal("20000.00"))  # 200k / 10
        self.assertEqual(r.data["incurred"], Decimal("15000.00"))

    def test_qs_can_set_rate_and_see_cost(self):
        qs = make_user("qs1", User.Role.QS)
        self.client.force_authenticate(qs)
        r = self.client.put("/api/v1/fx/usd-rate", {"rate": "16.5"},
                            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(str(r.data["rate"]), "16.5")
        r = self.client.get(f"/api/v1/cost/site/{self.site.id}")
        self.assertEqual(r.status_code, 200)  # QS may see cost

    def test_site_cost_aggregation(self):
        self.client.force_authenticate(self.director)
        r = self.client.get(f"/api/v1/cost/site/{self.site.id}")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["committed"], Decimal("200000"))
        self.assertEqual(r.data["incurred"], Decimal("150000"))
        self.assertEqual(r.data["paid"], Decimal("100000"))
        self.assertEqual(r.data["remaining"], Decimal("850000"))
        self.assertEqual(r.data["pct_consumed"], 15.0)   # 150k / 1m
        self.assertIsNotNone(r.data["pct_elapsed"])       # ~50%

    def test_site_user_blocked(self):
        self.client.force_authenticate(self.sa)
        self.assertEqual(
            self.client.get(f"/api/v1/cost/site/{self.site.id}").status_code,
            403)

    def test_pm_sees_own_site(self):
        self.client.force_authenticate(self.pm)
        self.assertEqual(
            self.client.get(f"/api/v1/cost/site/{self.site.id}").status_code,
            200)

    def test_portfolio_flags_outpacing(self):
        self.client.force_authenticate(self.director)
        r = self.client.get("/api/v1/cost/portfolio")
        self.assertEqual(r.status_code, 200, r.data)
        row = next(s for s in r.data["sites"]
                   if s["site_code"] == "SJR")
        # 15% consumed vs ~50% elapsed → not outpacing
        self.assertFalse(row["outpacing"])
        self.assertEqual(r.data["totals"]["committed"], Decimal("200000"))

    def test_drilldown_lists_postings(self):
        self.client.force_authenticate(self.director)
        r = self.client.get(
            f"/api/v1/cost/site/{self.site.id}/postings"
            "?head=Materials&state=COMMITTED")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data), 1)
        self.assertEqual(r.data[0]["amount"], Decimal("200000"))
