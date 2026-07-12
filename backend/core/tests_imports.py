"""Phase 1B — International procurement. P1B-a: Supplier categories + the PMR
(Project Material Requisition) requirement raised and tracked project→PM→HO→
Director."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Document, Project, SitePmHistory, Site, Supplier, User)
from .tests import make_user


class PmrBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE)
        self.sa = make_user("sa", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.ho = make_user("ho", User.Role.HO_PURCHASING)
        self.director = make_user("dir", User.Role.DIRECTOR)
        self.project = Project.objects.create(site=self.site, code="P1",
                                              title="Overwater villas",
                                              pm=self.pm)
        self.client = APIClient()

    def create_pmr(self):
        self.client.force_authenticate(self.sa)
        r = self.client.post("/api/v1/documents", {
            "doc_type": "PMR", "site_id": self.site.id,
            "project_id": self.project.id,
            "payload": {"discipline": "MEP", "justification": "long lead"},
            "lines": [{"free_text_desc": "Chilled-water pump", "qty_required": 4,
                       "unit": "nos", "spec": "50 m3/h, 4 bar",
                       "mar_ref": "MAR-SJR-002"}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data


class PmrWorkflowTests(PmrBase):
    def test_pmr_is_per_site_and_project_scoped(self):
        pmr = self.create_pmr()
        self.assertTrue(pmr["ref"].startswith("PMR-SJR-"))
        doc = Document.objects.get(ref=pmr["ref"])
        self.assertEqual(doc.project_id, self.project.id)
        line = doc.current_revision.lines.first()
        self.assertEqual(line.spec, "50 m3/h, 4 bar")
        self.assertEqual(line.mar_ref, "MAR-SJR-002")

    def test_full_thread_site_to_director(self):
        pmr = self.create_pmr()
        ref = pmr["ref"]

        def act(user, action, **body):
            self.client.force_authenticate(user)
            return self.client.post(
                f"/api/v1/documents/{ref}/actions/{action}", body,
                format="json")

        self.assertEqual(act(self.sa, "submit").data["status"], "SUBMITTED")
        self.assertEqual(act(self.pm, "approve").data["status"], "PM_APPROVED")
        self.assertEqual(act(self.ho, "ho-review").data["status"],
                         "HO_REVIEWED")
        r = act(self.director, "size-release", comment="Order 10 (MOQ)")
        self.assertEqual(r.data["status"], "SIZED_RELEASED")
        doc = Document.objects.get(ref=ref)
        self.assertEqual((doc.current_revision.payload or {})
                         .get("sizing", {}).get("note"), "Order 10 (MOQ)")

    def test_wrong_role_cannot_advance(self):
        pmr = self.create_pmr()
        ref = pmr["ref"]
        self.client.force_authenticate(self.sa)
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        # HO cannot PM-approve; Director cannot ho-review
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                             format="json")
        self.assertEqual(r.status_code, 403)

    def test_return_to_draft_from_ho(self):
        pmr = self.create_pmr()
        ref = pmr["ref"]
        self.client.force_authenticate(self.sa)
        self.client.post(f"/api/v1/documents/{ref}/actions/submit", {},
                         format="json")
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/documents/{ref}/actions/approve", {},
                         format="json")
        self.client.force_authenticate(self.ho)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/return",
                             {"comment": "spec unclear"}, format="json")
        self.assertEqual(r.data["status"], "DRAFT")


class SupplierCategoryTests(PmrBase):
    def test_category_filter_and_bank_visibility(self):
        Supplier.objects.create(name="Local Hardware",
                                category=Supplier.Category.LOCAL)
        Supplier.objects.create(name="Guangzhou Pumps Co",
                                category=Supplier.Category.INTERNATIONAL,
                                country="China", default_currency="USD",
                                bank_details="ICBC ...acct 123")
        # category filter
        self.client.force_authenticate(self.ho)
        r = self.client.get("/api/v1/suppliers?category=INTERNATIONAL")
        names = [s["name"] for s in r.data]
        self.assertEqual(names, ["Guangzhou Pumps Co"])
        self.assertIn("bank_details", r.data[0])   # HO sees bank details
        # site staff never see bank details
        self.client.force_authenticate(self.sa)
        r = self.client.get("/api/v1/suppliers?category=INTERNATIONAL")
        self.assertNotIn("bank_details", r.data[0])
