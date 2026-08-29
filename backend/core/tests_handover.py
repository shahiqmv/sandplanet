"""Handover — the dossier assembled as the job runs, and the snag list.

There was no snag list, no taking-over record and no handover pack, and
defects_liability_months was read by nothing so the DLP clock did not exist
(conformance audit 2026-08-28). Owner 2026-08-29 asked specifically for IRs
including MEP, checklists, cube test reports and as-builts to be attachable."""
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from . import handover
from .models import Document, HandoverItem, Project, Site, User
from .tests import make_user


class DossierTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="HO1", name="Handover site",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pm_ho1", User.Role.PM, site=self.site)
        self.se = make_user("se_ho1", User.Role.SITE_ENGINEER, site=self.site)
        self.project = Project.objects.create(
            site=self.site, code="P1", title="Villas", status="ACTIVE",
            defects_liability_months=12)
        self.client = APIClient()
        self.client.force_authenticate(self.pm)
        self.url = f"/api/v1/projects/{self.project.id}/handover"

    def _open(self):
        return self.client.post(self.url)

    def test_opening_a_dossier_seeds_the_standard_pack(self):
        r = self._open()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data["items"]),
                         len(handover.DEFAULT_REQUIREMENTS))
        self.assertEqual(r.data["completeness"]["pct"], 0)

    def test_the_pack_asks_for_the_things_a_resort_client_wants(self):
        """Cube tests, MEP inspections and as-builts by name."""
        titles = [t for _, _, t in handover.DEFAULT_REQUIREMENTS]
        self.assertIn("Concrete cube test reports", titles)
        self.assertIn("Inspection requests — MEP", titles)
        self.assertIn("As-built drawings — MEP", titles)
        self.assertIn("Pre-handover checklists", titles)

    def test_an_approved_inspection_request_becomes_a_candidate(self):
        """The dossier assembles itself from records already produced."""
        self._open()
        Document.objects.create(
            doc_type="IR", ref="IR-HO1-001", site=self.site,
            project=self.project, doc_date=date.today(), status="APPROVED",
            created_by=self.se)
        rows = self.client.get(f"{self.url}/candidates").data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ref"], "IR-HO1-001")
        self.assertEqual(rows[0]["suggested_section"], "INSPECTION")

    def test_an_unapproved_record_is_not_offered(self):
        self._open()
        Document.objects.create(
            doc_type="IR", ref="IR-HO1-002", site=self.site,
            project=self.project, doc_date=date.today(), status="SUBMITTED",
            created_by=self.se)
        self.assertEqual(
            len(self.client.get(f"{self.url}/candidates").data), 0)

    def test_pulling_a_record_in_marks_it_provided(self):
        self._open()
        doc = Document.objects.create(
            doc_type="MAR", ref="MAR-HO1-001", site=self.site,
            project=self.project, doc_date=date.today(), status="APPROVED",
            created_by=self.se)
        r = self.client.post(f"{self.url}/items",
                             {"document_id": doc.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "PROVIDED")
        self.assertEqual(r.data["section"], "SUBMITTAL")
        self.assertEqual(r.data["document_ref"], "MAR-HO1-001")

    def test_the_same_record_cannot_be_added_twice(self):
        self._open()
        doc = Document.objects.create(
            doc_type="IR", ref="IR-HO1-003", site=self.site,
            project=self.project, doc_date=date.today(), status="APPROVED",
            created_by=self.se)
        self.client.post(f"{self.url}/items", {"document_id": doc.id},
                         format="json")
        r = self.client.post(f"{self.url}/items", {"document_id": doc.id},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already in the pack", r.data["detail"])

    def test_a_record_from_another_project_is_refused(self):
        self._open()
        other = Project.objects.create(site=self.site, code="P2",
                                       title="Other", status="ACTIVE")
        doc = Document.objects.create(
            doc_type="IR", ref="IR-HO1-004", site=self.site, project=other,
            doc_date=date.today(), status="APPROVED", created_by=self.se)
        r = self.client.post(f"{self.url}/items", {"document_id": doc.id},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_a_cube_test_report_can_be_uploaded(self):
        """The parts of the pack that arrive as paper."""
        self._open()
        upload = SimpleUploadedFile("cube-28day.pdf", b"%PDF-1.4 test",
                                    content_type="application/pdf")
        r = self.client.post(f"{self.url}/upload", {
            "title": "Cube test report — 28 day, pour 14",
            "section": "TEST", "discipline": "CIVIL",
            "reference": "LAB-2291", "file": upload},
            format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "PROVIDED")
        self.assertIsNotNone(r.data["file_url"])

    def test_completeness_climbs_as_the_pack_fills(self):
        self._open()
        first = self.client.get(self.url).data
        self.assertEqual(first["completeness"]["pct"], 0)
        item_id = first["items"][0]["id"]
        self.client.patch(f"/api/v1/handover/items/{item_id}",
                          {"status": "PROVIDED"}, format="json")
        after = self.client.get(self.url).data
        self.assertGreater(after["completeness"]["pct"], 0)

    def test_not_applicable_items_leave_the_denominator(self):
        """A pond wall does not owe MEP commissioning records."""
        self._open()
        data = self.client.get(self.url).data
        before = data["completeness"]["required"]
        self.client.patch(f"/api/v1/handover/items/{data['items'][0]['id']}",
                          {"status": "NOT_APPLICABLE"}, format="json")
        after = self.client.get(self.url).data
        self.assertEqual(after["completeness"]["required"], before - 1)

    def test_a_site_engineer_cannot_record_client_acceptance(self):
        self._open()
        item_id = self.client.get(self.url).data["items"][0]["id"]
        self.client.force_authenticate(self.se)
        r = self.client.patch(f"/api/v1/handover/items/{item_id}",
                              {"status": "ACCEPTED"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_taking_over_starts_the_defects_liability_clock(self):
        """The clock the audit found did not exist."""
        self._open()
        taken = date(2026, 3, 1)
        r = self.client.post(f"{self.url}/milestones",
                             {"taking_over_on": str(taken),
                              "taking_over_ref": "TOC-001"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(str(r.data["dlp_ends"]), "2027-03-01")

    def test_no_clock_without_a_taking_over_date(self):
        self._open()
        self.assertIsNone(self.client.get(self.url).data["dlp_ends"])

    def test_another_site_cannot_see_the_pack(self):
        self._open()
        other = Site.objects.create(code="HO9", name="Other",
                                    status=Site.Status.ACTIVE)
        outsider = make_user("pm_ho9", User.Role.PM, site=other)
        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get(self.url).status_code, 404)


class SnagTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="HO2", name="Snag site",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pm_ho2", User.Role.PM, site=self.site)
        self.se = make_user("se_ho2", User.Role.SITE_ENGINEER, site=self.site)
        self.project = Project.objects.create(
            site=self.site, code="P1", title="Villas", status="ACTIVE")
        self.client = APIClient()
        self.client.force_authenticate(self.pm)
        self.url = f"/api/v1/projects/{self.project.id}/handover"
        self.client.post(self.url)

    def _snag(self, **extra):
        body = {"location": "Villa 3 bathroom", "discipline": "FINISHES",
                "description": "Tile grout cracked along the shower kerb",
                "due_date": str(date.today() + timedelta(days=7))}
        body.update(extra)
        return self.client.post(f"{self.url}/snags", body, format="json")

    def test_a_snag_gets_a_sequential_reference(self):
        first = self._snag()
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data["ref_no"], "SNG-0001")
        self.assertEqual(self._snag().data["ref_no"], "SNG-0002")

    def test_a_snag_without_a_location_cannot_be_found(self):
        r = self._snag(location="")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cannot be found", r.data["detail"])

    def test_snags_raised_after_taking_over_are_marked_as_dlp(self):
        """The distinction the client cares about."""
        self.client.post(f"{self.url}/milestones",
                         {"taking_over_on": str(date.today())},
                         format="json")
        self.assertTrue(self._snag().data["in_dlp"])

    def test_a_site_engineer_cannot_close_a_snag(self):
        snag_id = self._snag().data["id"]
        self.client.force_authenticate(self.se)
        r = self.client.patch(f"/api/v1/handover/snags/{snag_id}",
                              {"status": "CLOSED"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_marking_it_fixed_then_closed_stamps_both_dates(self):
        snag_id = self._snag().data["id"]
        self.client.patch(f"/api/v1/handover/snags/{snag_id}",
                          {"status": "FIXED"}, format="json")
        r = self.client.patch(f"/api/v1/handover/snags/{snag_id}",
                              {"status": "CLOSED"}, format="json")
        self.assertIsNotNone(r.data["fixed_on"])
        self.assertIsNotNone(r.data["closed_on"])

    def test_the_summary_counts_what_is_still_owed(self):
        self._snag()
        self._snag(due_date=str(date.today() - timedelta(days=3)))
        summary = self.client.get(self.url).data["snags"]
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["open"], 2)
        self.assertEqual(summary["overdue"], 1)
