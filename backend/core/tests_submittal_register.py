"""The submittal register: one paged query for all eight types.

The site dashboard used to fire a separate list request per submittal type,
which was four calls when there were four types and would have been eight by
the time the mock-up landed — each one serialising a full list before the site
page could paint (owner 2026-08-30: "the site page becomes heavier and
longer"). These tests hold the register to the shape that replaced it."""
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Document, Project, Site, User
from .pdf import _render_target
from .tests import make_user


class SubmittalRegisterTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="REG", name="Register site",
                                        status=Site.Status.ACTIVE)
        self.other = Site.objects.create(code="OTH", name="Other site",
                                         status=Site.Status.ACTIVE)
        self.se = make_user("se_reg", User.Role.SITE_ENGINEER, site=self.site)
        self.outsider = make_user("se_oth", User.Role.SITE_ENGINEER,
                                  site=self.other)
        self.project = Project.objects.create(
            site=self.site, code="P1", title="Villas", status="ACTIVE")
        self.client = APIClient()
        self.client.force_authenticate(self.se)

    def _create(self, doc_type, payload=None, site=None):
        return self.client.post("/api/v1/documents", {
            "doc_type": doc_type, "site_id": (site or self.site).id,
            "project_id": self.project.id if not site else None,
            "payload": payload or {}}, format="json")

    def _register(self, **params):
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return self.client.get(f"/api/v1/registers/submittals?site="
                               f"{self.site.id}&{qs}")

    def test_one_call_returns_every_submittal_type(self):
        """The point of the endpoint: eight types, one request."""
        for t in ("IR", "MAR", "SD", "MS", "MXD", "BBS", "TWD", "MOC", "ABD"):
            self.assertEqual(self._create(t).status_code, 201, t)
        r = self._register()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["total"], 9)
        self.assertEqual({d["doc_type"] for d in r.data["results"]},
                         {"IR", "MAR", "SD", "MS", "MXD", "BBS", "TWD", "MOC",
                          "ABD"})

    def test_it_pages_instead_of_returning_everything(self):
        for _ in range(5):
            self._create("IR")
        r = self._register(limit=2)
        self.assertEqual(r.data["total"], 5)
        self.assertEqual(len(r.data["results"]), 2)
        second = self._register(limit=2, offset=2)
        self.assertEqual(len(second.data["results"]), 2)
        # A page must not repeat what the previous page already showed.
        self.assertFalse({d["ref"] for d in r.data["results"]}
                         & {d["ref"] for d in second.data["results"]})

    def test_it_filters_by_type_and_by_state(self):
        ir = self._create("IR").data["ref"]
        self._create("MAR")
        self.assertEqual(self._register(types="IR").data["total"], 1)
        self.assertEqual(self._register(types="IR,MAR").data["total"], 2)
        # Both are still open — nothing has come back from the client.
        self.assertEqual(self._register(state="open").data["total"], 2)
        self.assertEqual(self._register(state="settled").data["total"], 0)
        Document.objects.filter(ref=ir).update(status="APPROVED")
        self.assertEqual(self._register(state="settled").data["total"], 1)
        self.assertEqual(self._register(state="open").data["total"], 1)

    def test_search_reaches_inside_the_payload(self):
        """People search for the thing, not the reference — and the thing
        lives in the payload, which is a JSON column."""
        self._create("MAR", {"material_description": "Vitrified floor tile"})
        self._create("MAR", {"material_description": "Sanitary ware"})
        r = self._register(q="vitrified")
        self.assertEqual(r.data["total"], 1)
        self.assertIn("Vitrified", str(r.data["results"][0]["payload"]))

    def test_search_also_matches_the_reference(self):
        ref = self._create("IR").data["ref"]
        self.assertEqual(self._register(q=ref).data["total"], 1)

    def test_counts_ride_along_with_the_page(self):
        self._create("IR")
        self._create("MAR")
        counts = self._register().data["counts"]
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["open"], 2)
        self.assertEqual({t["doc_type"] for t in counts["types"]},
                         {"IR", "MAR"})

    def test_a_void_submittal_is_not_open_work(self):
        ref = self._create("IR").data["ref"]
        Document.objects.filter(ref=ref).update(is_void=True)
        self.assertEqual(self._register(state="open").data["total"], 0)
        self.assertEqual(self._register().data["counts"]["total"], 0)

    def test_another_site_cannot_read_the_register(self):
        self._create("IR")
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self._register().status_code, 403)

    def test_the_site_dashboard_carries_the_summary_not_the_list(self):
        """The dashboard shows the state of the register without fetching
        it — that is what removed the per-type requests."""
        self._create("IR")
        self._create("MOC")
        r = self.client.get(f"/api/v1/dashboards/site/{self.site.id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["submittals"]["total"], 2)
        self.assertEqual(r.data["submittals"]["open"], 2)

    def test_bad_paging_is_rejected_not_ignored(self):
        self.assertEqual(self._register(limit="lots").status_code, 400)

    def test_the_site_is_required(self):
        r = self.client.get("/api/v1/registers/submittals")
        self.assertEqual(r.status_code, 400)


class MockUpTests(TestCase):
    """A mock-up approves the built result, not the product on paper."""

    def setUp(self):
        self.site = Site.objects.create(code="MOC", name="Mock site",
                                        status=Site.Status.ACTIVE)
        self.se = make_user("se_moc", User.Role.SITE_ENGINEER, site=self.site)
        self.pm = make_user("pm_moc", User.Role.PM, site=self.site)
        self.project = Project.objects.create(
            site=self.site, code="P1", title="Villas", status="ACTIVE",
            pm=self.pm)
        self.client = APIClient()
        self.client.force_authenticate(self.se)

    def _create(self, payload):
        return self.client.post("/api/v1/documents", {
            "doc_type": "MOC", "site_id": self.site.id,
            "project_id": self.project.id, "payload": payload}, format="json")

    def test_a_mock_up_can_be_raised(self):
        r = self._create({"mockup_title": "Bathroom wall tiling",
                          "location": "Villa 12, WC",
                          "represents": "All guest bathroom wall tiling"})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["ref"].startswith("MOC-"))

    def test_it_renders_its_own_form(self):
        ref = self._create({"mockup_title": "Timber decking",
                            "retained": True,
                            "retain_until": "2027-01-31"}).data["ref"]
        doc = Document.objects.get(ref=ref)
        template, context = _render_target(doc, doc.current_revision)
        self.assertEqual(template, "qa_form.html")
        self.assertEqual(context["form_title"], "SAMPLE / MOCK-UP APPROVAL")
        # Whether it is kept is the whole point — an argument about
        # workmanship later is settled by walking to it.
        body = str(context["sections"])
        self.assertIn("Retained on site as the benchmark", body)

    def test_every_submittal_type_can_actually_be_approved(self):
        """The civil types shipped able to be raised but not approved: the
        PM gate still listed only MR/IR/MAR/SD/MS/PMR, so the Approve button
        the screen offered returned a 400 (found 2026-08-30)."""
        for doc_type in ("SD", "MS", "MXD", "BBS", "TWD", "MOC", "ABD"):
            self.client.force_authenticate(self.se)
            r = self.client.post("/api/v1/documents", {
                "doc_type": doc_type, "site_id": self.site.id,
                "project_id": self.project.id,
                "payload": {"element": "Slab"}}, format="json")
            ref = r.data["ref"]
            sent = self.client.post(
                f"/api/v1/documents/{ref}/actions/submit")
            self.assertEqual(sent.status_code, 200,
                             f"{doc_type}: {sent.data}")
            self.client.force_authenticate(self.pm)
            got = self.client.post(
                f"/api/v1/documents/{ref}/actions/approve")
            self.assertEqual(got.status_code, 200,
                             f"{doc_type}: {got.data}")
            self.assertEqual(Document.objects.get(ref=ref).status,
                             "PM_APPROVED", doc_type)
            # ...and then issued to the client for a result.
            issued = self.client.post(
                f"/api/v1/documents/{ref}/actions/issue")
            self.assertEqual(issued.status_code, 200,
                             f"{doc_type}: {issued.data}")

    def test_it_follows_the_submittal_workflow(self):
        ref = self._create({"mockup_title": "Rendering sample"}).data["ref"]
        sent = self.client.post(f"/api/v1/documents/{ref}/actions/submit")
        self.assertEqual(sent.status_code, 200, sent.data)
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/approve")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Document.objects.get(ref=ref).status, "PM_APPROVED")


class AsBuiltTests(TestCase):
    """The record drawing: reviewed like a shop drawing, filed by link."""

    def setUp(self):
        self.site = Site.objects.create(code="ABD", name="Record site",
                                        status=Site.Status.ACTIVE)
        self.se = make_user("se_abd", User.Role.SITE_ENGINEER, site=self.site)
        self.pm = make_user("pm_abd", User.Role.PM, site=self.site)
        self.project = Project.objects.create(
            site=self.site, code="P1", title="Villas", status="ACTIVE",
            pm=self.pm)
        self.client = APIClient()
        self.client.force_authenticate(self.se)

    def test_an_as_built_can_be_raised_and_has_its_own_form(self):
        r = self.client.post("/api/v1/documents", {
            "doc_type": "ABD", "site_id": self.site.id,
            "project_id": self.project.id, "payload": {
                "drawing_title": "Villa 3 — drainage as built",
                "drawing_no": "AB-DR-003", "supersedes_drawing": "SD-DR-003",
                "verified_against": "Site survey 2026-08-20"}},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["ref"].startswith("ABD-"))
        doc = Document.objects.get(ref=r.data["ref"])
        template, context = _render_target(doc, doc.current_revision)
        self.assertEqual(template, "qa_form.html")
        self.assertEqual(context["form_title"], "AS-BUILT DRAWING SUBMITTAL")
        body = str(context["sections"])
        self.assertIn("Supersedes Drawing No.", body)
        self.assertIn("SD-DR-003", body)
