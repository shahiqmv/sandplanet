"""The cost head master page (owner 2026-09-07).

Two things these pin down. A head the code depends on may be RENAMED without
breaking the posting path that reaches for it — that was the whole reason
there had never been a screen. And a head marked as a company overhead leaves
the project cost reports and is counted on its own instead.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import costing
from .models import CompanyParameter, CostHead, CostPosting, Site, User
from .tests import make_user


class CostHeadMasterTests(TestCase):
    def setUp(self):
        CompanyParameter.objects.update_or_create(
            key="usd_mvr_rate", defaults={"value": "1"})
        self.site = Site.objects.create(
            code="SJR", name="Soneva Jani", status=Site.Status.ACTIVE,
            contract_value=Decimal("1000000"),
            start_date=date.today() - timedelta(days=50),
            planned_completion=date.today() + timedelta(days=50))
        self.finance = make_user("ch_fin", User.Role.FINANCE)
        self.admin = make_user("ch_adm", User.Role.ADMIN)
        self.pm = make_user("ch_pm", User.Role.PM, site=self.site)
        self.director = make_user("ch_dir", User.Role.DIRECTOR)
        self.client = APIClient()
        self.client.force_authenticate(self.finance)

    def head(self, code):
        return CostHead.objects.get(code=code)

    # ---- the master list -------------------------------------------------

    def test_every_seeded_head_carries_a_code(self):
        self.assertEqual(CostHead.objects.filter(code="").count(), 0)
        self.assertTrue(self.head("MATERIALS").is_system)
        self.assertTrue(self.head("INPUT_GST").is_system)

    def test_only_the_heads_the_code_reaches_for_are_locked(self):
        """Plant & Equipment and the rest are part of the default chart, but
        nothing looks them up — a head nobody uses stays switchable off."""
        for code in ("PLANT", "TRANSPORT", "OTHER", "STOCK_ADJUSTMENT"):
            self.assertFalse(self.head(code).is_system, code)
        r = self.client.patch(
            f"/api/v1/cost-head-master/{self.head('PLANT').id}",
            {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data["is_active"])

    def test_a_head_can_be_added_and_removed_while_unused(self):
        r = self.client.post("/api/v1/cost-head-master",
                             {"name": "Office Rent", "overhead": True},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["code"], "OFFICE_RENT")
        self.assertTrue(r.data["overhead"])
        self.assertTrue(r.data["can_delete"])
        self.assertEqual(self.client.delete(
            f"/api/v1/cost-head-master/{r.data['id']}").status_code, 204)

    def test_two_heads_cannot_share_a_name(self):
        r = self.client.post("/api/v1/cost-head-master",
                             {"name": "materials"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already exists", r.data["detail"])

    def test_only_finance_and_admin_may_change_the_chart(self):
        h = self.head("OTHER")
        for user in (self.pm, self.director):
            self.client.force_authenticate(user)
            r = self.client.patch(f"/api/v1/cost-head-master/{h.id}",
                                  {"name": "Anything"}, format="json")
            self.assertEqual(r.status_code, 403)
        h.refresh_from_db()
        self.assertEqual(h.name, "Other")
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.patch(
            f"/api/v1/cost-head-master/{h.id}", {"sort_order": 20},
            format="json").status_code, 200)

    # ---- what makes the rename safe --------------------------------------

    def test_renaming_a_system_head_does_not_break_the_posting_path(self):
        """The reason there was never a screen: the code looked heads up by
        their display text, so this rename used to be a crash waiting."""
        r = self.client.patch(
            f"/api/v1/cost-head-master/{self.head('MATERIALS').id}",
            {"name": "Materials & Consumables"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        found = costing.by_code(costing.MATERIALS)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "Materials & Consumables")
        self.assertEqual(found.code, "MATERIALS")

    def test_a_system_head_cannot_be_switched_off_or_removed(self):
        h = self.head("LABOUR")
        off = self.client.patch(f"/api/v1/cost-head-master/{h.id}",
                                {"is_active": False}, format="json")
        self.assertEqual(off.status_code, 400)
        gone = self.client.delete(f"/api/v1/cost-head-master/{h.id}")
        self.assertEqual(gone.status_code, 400)
        h.refresh_from_db()
        self.assertTrue(h.is_active)

    def test_a_head_that_carried_money_is_switched_off_never_deleted(self):
        h = CostHead.objects.create(code="OLD_THING", name="Old thing")
        costing.post(site=self.site, cost_head=h, state="INCURRED",
                     source="PR", amount=Decimal("500"))
        r = self.client.delete(f"/api/v1/cost-head-master/{h.id}")
        self.assertEqual(r.status_code, 400)
        self.assertIn("erase cost history", r.data["detail"])
        self.assertEqual(self.client.patch(
            f"/api/v1/cost-head-master/{h.id}", {"is_active": False},
            format="json").data["is_active"], False)

    # ---- overheads leave the project reports ------------------------------

    def test_an_overhead_head_leaves_the_project_cost_report(self):
        materials = self.head("MATERIALS")
        rent = CostHead.objects.create(code="RENT", name="Office Rent")
        costing.post(site=self.site, cost_head=materials, state="INCURRED",
                     source="PR", amount=Decimal("100000"))
        costing.post(site=self.site, cost_head=rent, state="INCURRED",
                     source="PR", amount=Decimal("40000"))

        self.client.force_authenticate(self.director)
        before = self.client.get(f"/api/v1/cost/site/{self.site.id}").data
        self.assertEqual(before["incurred"], Decimal("140000.00"))

        self.client.force_authenticate(self.finance)
        self.client.patch(f"/api/v1/cost-head-master/{rent.id}",
                          {"overhead": True}, format="json")

        self.client.force_authenticate(self.director)
        after = self.client.get(f"/api/v1/cost/site/{self.site.id}").data
        self.assertEqual(after["incurred"], Decimal("100000.00"))
        self.assertNotIn("Office Rent",
                         [r["cost_head"] for r in after["by_cost_head"]])
        # and the drill-down agrees with the total it sits under
        rows = self.client.get(
            f"/api/v1/cost/site/{self.site.id}/postings").data
        self.assertNotIn("Office Rent", [r["cost_head"] for r in rows])

    def test_the_money_taken_out_is_counted_somewhere(self):
        """An overhead leaves every project report, so without this it would
        be money that left the company and appeared nowhere."""
        rent = CostHead.objects.create(code="RENT", name="Office Rent",
                                       overhead=True)
        costing.post(site=self.site, cost_head=rent, state="PAID",
                     source="PR", amount=Decimal("40000"))
        self.client.force_authenticate(self.director)
        r = self.client.get("/api/v1/cost-heads/overheads")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["totals"]["paid"], 40000.0)
        self.assertEqual(r.data["by_cost_head"][0]["cost_head"],
                         "Office Rent")

    def test_a_project_head_is_not_in_the_overheads_summary(self):
        costing.post(site=self.site, cost_head=self.head("MATERIALS"),
                     state="PAID", source="PR", amount=Decimal("9000"))
        self.client.force_authenticate(self.director)
        r = self.client.get("/api/v1/cost-heads/overheads")
        self.assertEqual(r.data["totals"]["paid"], 0.0)

    def test_nothing_is_an_overhead_until_someone_says_so(self):
        """The migration marks none: which costs leave the project reports is
        the owner's call, not a migration's."""
        self.assertEqual(CostHead.objects.filter(overhead=True).count(), 0)
        self.assertEqual(CostPosting.objects.filter(
            cost_head__overhead=True).count(), 0)
