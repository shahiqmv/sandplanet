"""Civil submittals: concrete mix design, bar bending schedule, temporary
works design.

The submittal family covered materials, drawings and method statements but
nothing a civil engineer actually sends for approval before a pour — the mix
it is batched from, the schedule the steel is cut to, or the falsework it is
poured against (owner 2026-08-30)."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Document, Project, Site, User
from .pdf import _render_target
from .tests import make_user


class CivilSubmittalTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="CIV", name="Civil site",
                                        status=Site.Status.ACTIVE)
        self.se = make_user("se_civ", User.Role.SITE_ENGINEER, site=self.site)
        self.pm = make_user("pm_civ", User.Role.PM, site=self.site)
        self.project = Project.objects.create(
            site=self.site, code="P1", title="Villas", status="ACTIVE")
        self.client = APIClient()
        self.client.force_authenticate(self.se)

    def _create(self, doc_type, payload):
        return self.client.post("/api/v1/documents", {
            "doc_type": doc_type, "site_id": self.site.id,
            "project_id": self.project.id, "payload": payload},
            format="json")

    def test_a_mix_design_can_be_raised(self):
        r = self._create("MXD", {
            "grade": "C30/20", "mix_ref": "MX-114",
            "application": "Ground floor slabs",
            "cement_content": "340", "wc_ratio": "0.48",
            "design_strength": "30"})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["ref"].startswith("MXD-"))
        self.assertEqual(r.data["status"], "DRAFT")

    def test_a_bar_bending_schedule_can_be_raised(self):
        r = self._create("BBS", {
            "element": "Villa 3 ground floor slab",
            "drawing_ref": "S-201", "drawing_rev": "C",
            "steel_grade": "B500B", "total_weight": "4820"})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["ref"].startswith("BBS-"))

    def test_a_temporary_works_design_can_be_raised(self):
        r = self._create("TWD", {
            "tw_type": "Falsework", "location": "Villa 3 first floor",
            "designed_by": "In-house", "checked_by": "External engineer",
            "design_loading": "5 kN/m²"})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["ref"].startswith("TWD-"))

    def test_they_belong_to_a_project_like_every_other_submittal(self):
        ref = self._create("MXD", {"grade": "C30/20"}).data["ref"]
        self.assertEqual(Document.objects.get(ref=ref).project_id,
                         self.project.id)

    def test_a_site_admin_cannot_raise_one(self):
        """Same hands as a shop drawing: the engineer or the PM."""
        sa = make_user("sa_civ", User.Role.SITE_ADMIN, site=self.site)
        self.client.force_authenticate(sa)
        self.assertEqual(self._create("BBS", {"element": "x"}).status_code,
                         403)

    def test_each_renders_its_own_form(self):
        for doc_type, title in (("MXD", "CONCRETE MIX DESIGN SUBMITTAL"),
                                ("BBS", "BAR BENDING SCHEDULE SUBMITTAL"),
                                ("TWD", "TEMPORARY WORKS SUBMITTAL")):
            ref = self._create(doc_type, {"grade": "C30/20",
                                          "element": "Slab",
                                          "tw_type": "Falsework"}).data["ref"]
            doc = Document.objects.get(ref=ref)
            template, context = _render_target(doc, doc.current_revision)
            self.assertEqual(template, "qa_form.html")
            self.assertEqual(context["form_title"], title)

    def test_the_temporary_works_form_carries_the_independent_check(self):
        """Temporary works fail while people are standing on them, and the
        check is what a consultant asks for first."""
        ref = self._create("TWD", {
            "tw_type": "Falsework", "designed_by": "In-house",
            "checked_by": "Dr Rasheed, external"}).data["ref"]
        doc = Document.objects.get(ref=ref)
        _, context = _render_target(doc, doc.current_revision)
        self.assertIn("Dr Rasheed, external", str(context["sections"]))
        self.assertIn("Independently checked by", str(context["sections"]))

    def test_the_mix_design_form_shows_the_proportions(self):
        ref = self._create("MXD", {"grade": "C30/20", "wc_ratio": "0.48",
                                   "cement_content": "340"}).data["ref"]
        doc = Document.objects.get(ref=ref)
        _, context = _render_target(doc, doc.current_revision)
        blob = str(context["sections"])
        self.assertIn("0.48", blob)
        self.assertIn("340", blob)

    def test_a_cube_test_can_name_the_mix_it_was_poured_from(self):
        """32 N/mm² passes a C30 mix and fails a C40 one — the consultant
        will ask which was poured."""
        mix = Document.objects.get(
            ref=self._create("MXD", {"grade": "C30/20"}).data["ref"])
        r = self.client.post("/api/v1/quality/tests", {
            "site_id": self.site.id, "project_id": self.project.id,
            "kind": "CUBE", "element": "Villa 3 slab",
            "sampled_on": str(date.today()),
            "required_value": "30", "unit": "N/mm2",
            "mix_design_id": mix.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["mix_design_ref"], mix.ref)
