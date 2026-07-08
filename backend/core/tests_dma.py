"""R5 — Daily Manpower Allocation + PM assignments board."""
from datetime import date

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Site, SitePmHistory, User
from .tests import make_user
from .tests_projects import ProjectBase

DMA_TASKS = [
    {"task": "Footing rebar — Pool 3", "location": "Pool 3", "project": "POOLS17",
     "category": "Steel Fixer", "workers": 4, "remarks": ""},
    {"task": "Material unloading (dhoni)", "location": "Jetty", "project": "",
     "category": "Labourer", "workers": 6, "remarks": "General task"},
    {"task": "Site cleaning", "location": "Whole site", "project": "",
     "category": "Labourer", "workers": 2, "remarks": ""},
]


@override_settings(MEDIA_ROOT="test-media")
class DmaTests(ProjectBase):
    def make_dma(self, doc_date=None, tasks=None):
        return self.client.post("/api/v1/documents", {
            "doc_type": "DMA", "site_id": self.site.id,
            "doc_date": (doc_date or date.today()).isoformat(),
            "payload": {"tasks": tasks or DMA_TASKS},
        }, format="json")

    def test_one_dma_per_site_per_day(self):
        r1 = self.make_dma()
        self.assertEqual(r1.status_code, 201, r1.data)
        self.assertEqual(r1.data["ref"], "DMA-VKR-001")
        self.assertIsNone(r1.data["project"])  # site-wide, never project-bound
        r2 = self.make_dma()
        self.assertEqual(r2.status_code, 400)
        self.assertIn("DMA-VKR-001", r2.data["detail"])

    def test_se_prepares_but_only_pm_issues(self):
        ref = self.make_dma().data["ref"]
        r = self.client.post(f"/api/v1/documents/{ref}/actions/issue")
        self.assertEqual(r.status_code, 403)  # SE cannot issue
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/issue")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "ISSUED")

    def test_prefill_pulls_same_day_tws_tasks(self):
        day = date.today()
        tws = self.client.post("/api/v1/documents", {
            "doc_type": "TWS", "site_id": self.site.id,
            "doc_date": day.isoformat(),
            # TWS is site-wide (R8): rows carry their own project tag
            "payload": {"activities": [
                {"activity": "Footing rebar", "location": "Pool 3",
                 "trade": "Steel Fixer", "remarks": "",
                 "project": "POOLS17"},
            ]},
        }, format="json").data
        self.client.post(f"/api/v1/documents/{tws['ref']}/actions/issue")
        r = self.client.get(
            f"/api/v1/dma-prefill?site={self.site.id}&date={day.isoformat()}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["tws_refs"], [tws["ref"]])
        task = r.data["tasks"][0]
        self.assertEqual(task["task"], "Footing rebar")
        self.assertEqual(task["category"], "Steel Fixer")
        self.assertEqual(task["project"], "POOLS17")
        # a draft (unissued) TWS contributes nothing
        r = self.client.get(
            f"/api/v1/dma-prefill?site={self.site.id}"
            f"&date={date(2000, 1, 1).isoformat()}")
        self.assertEqual(r.data["tasks"], [])


class PmOverviewTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.admin = make_user("adm", User.Role.ADMIN)
        self.client = APIClient()

    def test_admin_sees_assignments_pm_does_not(self):
        self.client.force_authenticate(self.pm)
        self.assertEqual(self.client.get("/api/v1/pm-overview").status_code, 403)
        self.client.force_authenticate(self.admin)
        r = self.client.get("/api/v1/pm-overview")
        self.assertEqual(r.status_code, 200)
        row = next(p for p in r.data["pms"] if p["id"] == self.pm.id)
        self.assertEqual(row["sites"][0]["code"], "VKR")
        self.assertEqual(r.data["history"][0]["site_code"], "VKR")
