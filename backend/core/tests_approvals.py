"""R6 — per-role approvals queue ('waiting on you')."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Site, SitePmHistory, User
from .tests import make_user


class ApprovalsQueueTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.se = make_user("se1", User.Role.SITE_ENGINEER, site=self.site)
        self.sa = make_user("sa1", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.director = make_user("dir", User.Role.DIRECTOR)
        self.purchasing = make_user("pur", User.Role.HO_PURCHASING)
        self.finance = make_user("fin", User.Role.FINANCE)
        self.client = APIClient()

    def pending(self, user):
        self.client.force_authenticate(user)
        r = self.client.get("/api/v1/approvals/pending")
        assert r.status_code == 200, r.data
        return r.data

    def titles(self, data):
        return [g["title"] for g in data["groups"]]

    def test_pm_sees_submitted_ir_and_draft_dma(self):
        self.client.force_authenticate(self.se)
        ir = self.client.post("/api/v1/documents", {
            "doc_type": "IR", "site_id": self.site.id,
            "payload": {"discipline": "Civil", "work_description": "x"},
        }, format="json").data
        self.client.post(f"/api/v1/documents/{ir['ref']}/actions/submit")
        self.client.post("/api/v1/documents", {
            "doc_type": "DMA", "site_id": self.site.id,
            "payload": {"tasks": []},
        }, format="json")

        data = self.pending(self.pm)
        self.assertEqual(data["total"], 2)
        refs = [i["ref"] for g in data["groups"] for i in g["items"]]
        self.assertIn(ir["ref"], refs)
        self.assertIn("DMA-VKR-001", refs)
        # the SE has no queue of their own
        self.client.force_authenticate(self.se)
        r = self.client.get("/api/v1/approvals/pending")
        self.assertEqual(r.data["total"], 0)

    def test_director_and_finance_see_pr_stages(self):
        self.client.force_authenticate(self.purchasing)
        pr = self.client.post("/api/v1/documents", {
            "doc_type": "PR", "site_id": self.site.id, "payload": {},
            "lines": [{"free_text_desc": "Cement", "unit": "bags",
                       "qty_required": 10}],
        }, format="json").data
        self.client.post(f"/api/v1/documents/{pr['ref']}/actions/submit")

        d = self.pending(self.director)
        self.assertIn("To award — submitted PRs", self.titles(d))
        self.assertEqual(self.pending(self.finance)["total"], 0)

        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/documents/{pr['ref']}/actions/approve")
        # After Director approval the PR awaits a payment voucher (M6d):
        # Finance batches it, a signatory approves the voucher. Finance sees
        # it in "Awaiting a payment voucher"; the signatory sees nothing yet
        # (no submitted voucher), only PVs once Finance submits one.
        f = self.pending(self.finance)
        self.assertIn("Awaiting a payment voucher", self.titles(f))
        sig = self.pending(make_user("sig", User.Role.SIGNATORY))
        self.assertNotIn("To authorise — approved PRs", self.titles(sig))
        self.assertEqual(self.pending(self.director)["total"], 0)

    def test_purchasing_sees_mr_sent_to_ho(self):
        self.client.force_authenticate(self.sa)
        mr = self.client.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id,
            "payload": {},
            "lines": [{"free_text_desc": "Rebar 16mm", "unit": "len",
                       "qty_required": 40, "qty_to_order": 40}],
        }, format="json").data
        self.client.post(f"/api/v1/documents/{mr['ref']}/actions/submit")
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/documents/{mr['ref']}/actions/approve")
        self.client.force_authenticate(self.sa)
        r = self.client.post(f"/api/v1/documents/{mr['ref']}/actions/send")
        assert r.status_code == 200, r.data

        p = self.pending(self.purchasing)
        self.assertIn("To action — MRs at Head Office", self.titles(p))
        self.assertEqual([i["ref"] for i in p["groups"][0]["items"]],
                         [mr["ref"]])


class RoleDashboardTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.client = APIClient()

    def test_hr_dashboard_gated_and_shaped(self):
        hr = make_user("hr", User.Role.HO_HR)
        pm = make_user("pm9", User.Role.PM, site=self.site)
        self.client.force_authenticate(pm)
        self.assertEqual(self.client.get("/api/v1/dashboards/hr").status_code,
                         403)
        self.client.force_authenticate(hr)
        r = self.client.get("/api/v1/dashboards/hr")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["lock_board"][0]["code"], "VKR")
        self.assertFalse(r.data["all_locked"])

    def test_portfolio_gated_and_shaped(self):
        director = make_user("dir9", User.Role.DIRECTOR)
        purchasing = make_user("pur9", User.Role.HO_PURCHASING)
        from core.models import Project
        from datetime import timedelta
        Project.objects.create(
            site=self.site, code="POOLS17", title="17 Pools",
            start_date=date.today() - timedelta(days=50),
            planned_completion=date.today() + timedelta(days=50))
        self.client.force_authenticate(purchasing)
        self.assertEqual(
            self.client.get("/api/v1/dashboards/portfolio").status_code, 403)
        self.client.force_authenticate(director)
        r = self.client.get("/api/v1/dashboards/portfolio")
        self.assertEqual(r.status_code, 200)
        row = r.data["projects"][0]
        self.assertEqual(row["code"], "POOLS17")
        self.assertEqual(row["pct_time_elapsed"], 50.0)
        # zero programme progress at 50% time elapsed = attention
        self.assertEqual(row["health"], "attention")
