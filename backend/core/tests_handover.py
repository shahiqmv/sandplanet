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
from .models import Document, Project, Site, User
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

    def _ready_item(self, ref="LAB-1", title="Cube test report — pour 14"):
        """An item with evidence attached — ready to go on a transmittal."""
        upload = SimpleUploadedFile("r.pdf", b"%PDF-1.4 x",
                                    content_type="application/pdf")
        return self.client.post(f"{self.url}/upload", {
            "title": title, "section": "TEST", "discipline": "CIVIL",
            "reference": ref, "file": upload}, format="multipart").data

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

    def test_pulling_a_record_in_readies_it_but_does_not_submit_it(self):
        """An approved INSPECTION went to nobody outside the company, so
        holding it is not submitting it — it is ready to go on a transmittal
        and nothing more (owner 2026-09-01). A record the client already
        approved is the other case: see ClientApprovedOnPullTests."""
        self._open()
        doc = Document.objects.create(
            doc_type="IR", ref="IR-HO1-001", site=self.site,
            project=self.project, doc_date=date.today(), status="APPROVED",
            created_by=self.se)
        r = self.client.post(f"{self.url}/items",
                             {"document_id": doc.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "REQUIRED")
        self.assertTrue(r.data["has_evidence"])
        self.assertEqual(r.data["section"], "INSPECTION")
        self.assertEqual(r.data["document_ref"], "IR-HO1-001")

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
        self.assertEqual(r.data["status"], "REQUIRED")
        self.assertTrue(r.data["has_evidence"])
        self.assertIsNotNone(r.data["file_url"])

    def test_a_status_the_client_owns_cannot_be_typed_in(self):
        """Submitted, accepted and returned are what HAPPENED to a document.
        The pack used to let staff pick "Accepted by the client" from a
        dropdown, recording our opinion of the client's opinion (owner
        2026-09-01)."""
        self._open()
        item_id = self.client.get(self.url).data["items"][0]["id"]
        for status in ("SUBMITTED", "ACCEPTED", "RETURNED"):
            r = self.client.patch(f"/api/v1/handover/items/{item_id}",
                                  {"status": status}, format="json")
            self.assertEqual(r.status_code, 400, status)
            self.assertIn("through a transmittal", r.data["detail"])

    def test_not_applicable_items_leave_the_denominator(self):
        """A pond wall does not owe MEP commissioning records."""
        self._open()
        data = self.client.get(self.url).data
        before = data["completeness"]["required"]
        self.client.patch(f"/api/v1/handover/items/{data['items'][0]['id']}",
                          {"status": "NOT_APPLICABLE"}, format="json")
        after = self.client.get(self.url).data
        self.assertEqual(after["completeness"]["required"], before - 1)

    def test_a_site_engineer_cannot_issue_to_the_client(self):
        """Issuing to the client, and recording what they said, is not data
        entry."""
        self._open()
        item = self._ready_item()
        t = self.client.post(f"{self.url}/transmittals",
                             {"addressed_to": "The Engineer",
                              "item_ids": [item["id"]]},
                             format="json").data
        self.client.force_authenticate(self.se)
        r = self.client.post(f"/api/v1/handover/transmittals/{t['id']}/issue",
                             {}, format="json")
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


class TransmittalTests(DossierTests):
    """The submission itself — the step the pack was missing. A document is
    not provided because somebody ticked it; it is provided when it goes to
    the Engineer under a reference, on a date, with a review period running
    (owner 2026-09-01)."""

    def setUp(self):
        super().setUp()
        self._open()

    def _draft(self, **extra):
        item = self._ready_item()
        body = {"addressed_to": "R. Fernando", "organisation": "Engineer Co",
                "subject": "Handover documents — batch 1",
                "item_ids": [item["id"]]}
        body.update(extra)
        r = self.client.post(f"{self.url}/transmittals", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data, item

    def _issue(self, tid, **body):
        return self.client.post(
            f"/api/v1/handover/transmittals/{tid}/issue", body, format="json")

    def _respond(self, line_id, result, **extra):
        body = {"result": result, "reviewed_by": "R. Fernando",
                "position": "Resident Engineer", "reply_ref": "ENG-LTR-88"}
        body.update(extra)
        return self.client.post(
            f"/api/v1/handover/transmittal-lines/{line_id}/response",
            body, format="json")

    # ---- assembling ----------------------------------------------------
    def test_a_transmittal_is_numbered_per_project(self):
        first, _ = self._draft()
        self.assertEqual(first["ref"], "HO-TR-01")
        self.assertEqual(first["status"], "DRAFT")
        second, _ = self._draft()
        self.assertEqual(second["ref"], "HO-TR-02")

    def test_only_evidenced_documents_can_be_sent(self):
        """You cannot transmit a line that has no document behind it."""
        empty = self.client.get(self.url).data["items"][0]
        self.assertFalse(empty["has_evidence"])
        cands = self.client.get(
            f"{self.url}/transmittals/candidates").data
        self.assertNotIn(empty["id"], [c["id"] for c in cands])
        r = self.client.post(f"{self.url}/transmittals",
                             {"addressed_to": "x",
                              "item_ids": [empty["id"]]}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["lines"], [])      # silently not included

    def test_an_empty_transmittal_cannot_be_issued(self):
        r = self.client.post(f"{self.url}/transmittals",
                             {"addressed_to": "x"}, format="json")
        out = self._issue(r.data["id"])
        self.assertEqual(out.status_code, 400)
        self.assertIn("at least one document", out.data["detail"])

    def test_a_transmittal_must_be_addressed_to_somebody(self):
        item = self._ready_item()
        t = self.client.post(f"{self.url}/transmittals",
                             {"item_ids": [item["id"]]}, format="json").data
        r = self._issue(t["id"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("addressed to", r.data["detail"])

    # ---- issuing -------------------------------------------------------
    def test_issuing_submits_the_documents_and_starts_the_clock(self):
        t, item = self._draft()
        r = self._issue(t["id"], issued_on="2026-09-01", response_days=14)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "ISSUED")
        self.assertEqual(r.data["response_due_on"], "2026-09-15")
        after = self.client.get(self.url).data
        row = next(i for i in after["items"] if i["id"] == item["id"])
        self.assertEqual(row["status"], "SUBMITTED")
        self.assertEqual(row["provided_on"], "2026-09-01")

    def test_an_issued_transmittal_is_fixed(self):
        t, _ = self._draft()
        self._issue(t["id"])
        r = self.client.patch(f"/api/v1/handover/transmittals/{t['id']}",
                              {"subject": "changed"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("contents are fixed", r.data["detail"])
        d = self.client.delete(f"/api/v1/handover/transmittals/{t['id']}")
        self.assertEqual(d.status_code, 400)

    def test_a_document_out_with_the_client_cannot_be_sent_twice(self):
        t, item = self._draft()
        self._issue(t["id"])
        cands = self.client.get(f"{self.url}/transmittals/candidates").data
        self.assertNotIn(item["id"], [c["id"] for c in cands])

    def test_a_document_out_with_the_client_cannot_be_stood_down(self):
        t, item = self._draft()
        self._issue(t["id"])
        r = self.client.patch(f"/api/v1/handover/items/{item['id']}",
                              {"status": "NOT_APPLICABLE"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("out with the client", r.data["detail"])

    # ---- the response --------------------------------------------------
    def test_recording_approval_accepts_the_document(self):
        t, item = self._draft()
        issued = self._issue(t["id"]).data
        line = issued["lines"][0]
        r = self._respond(line["id"], "APPROVED", result_on="2026-09-10")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["item_status"], "ACCEPTED")
        # who decided, and who wrote it down — the client has no login here
        self.assertEqual(r.data["reviewed_by"], "R. Fernando")
        self.assertEqual(r.data["recorded_by_name"], self.pm.full_name)
        row = next(i for i in self.client.get(self.url).data["items"]
                   if i["id"] == item["id"])
        self.assertEqual(row["accepted_on"], "2026-09-10")

    def test_a_rejected_document_comes_back_as_the_next_revision(self):
        t, item = self._draft()
        issued = self._issue(t["id"]).data
        self.assertEqual(issued["lines"][0]["revision"], 0)
        r = self._respond(issued["lines"][0]["id"], "REJECTED",
                          comments="As-built does not match the survey.")
        self.assertEqual(r.data["item_status"], "RETURNED")
        row = next(i for i in self.client.get(self.url).data["items"]
                   if i["id"] == item["id"])
        self.assertEqual(row["revision"], 1)        # resubmit as Rev 1
        # ...and it is owed again, so it comes back round as a candidate
        cands = self.client.get(f"{self.url}/transmittals/candidates").data
        self.assertIn(item["id"], [c["id"] for c in cands])

    def test_a_returned_document_can_be_stood_down(self):
        """It is back in our hands, so the PM may decide it is not owed after
        all — unlike one still out with the client."""
        t, item = self._draft()
        issued = self._issue(t["id"]).data
        self._respond(issued["lines"][0]["id"], "REJECTED")
        r = self.client.patch(f"/api/v1/handover/items/{item['id']}",
                              {"status": "NOT_APPLICABLE"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "NOT_APPLICABLE")

    def test_a_resubmission_carries_the_new_revision(self):
        t, item = self._draft()
        issued = self._issue(t["id"]).data
        self._respond(issued["lines"][0]["id"], "REJECTED")
        again = self.client.post(f"{self.url}/transmittals",
                                 {"addressed_to": "R. Fernando",
                                  "item_ids": [item["id"]]},
                                 format="json").data
        out = self._issue(again["id"]).data
        self.assertEqual(out["lines"][0]["revision"], 1)

    def test_a_transmittal_closes_when_every_document_is_answered(self):
        a, b = self._ready_item("L1", "Doc A"), self._ready_item("L2", "Doc B")
        t = self.client.post(f"{self.url}/transmittals",
                             {"addressed_to": "R. Fernando",
                              "item_ids": [a["id"], b["id"]]},
                             format="json").data
        issued = self._issue(t["id"]).data
        self.assertEqual(len(issued["lines"]), 2)
        self._respond(issued["lines"][0]["id"], "APPROVED")
        mid = self.client.get(
            f"/api/v1/handover/transmittals/{t['id']}").data
        self.assertEqual(mid["status"], "ISSUED")   # still one outstanding
        self._respond(issued["lines"][1]["id"], "APPROVED_WITH_COMMENTS")
        end = self.client.get(
            f"/api/v1/handover/transmittals/{t['id']}").data
        self.assertEqual(end["status"], "CLOSED")

    def test_a_response_cannot_be_recorded_before_issue(self):
        t, _ = self._draft()
        full = self.client.get(
            f"/api/v1/handover/transmittals/{t['id']}").data
        r = self._respond(full["lines"][0]["id"], "APPROVED")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not been issued", r.data["detail"])

    # ---- what the numbers mean ----------------------------------------
    def test_accepted_is_reported_apart_from_merely_submitted(self):
        """"Provided" only means it left the building. At taking-over the
        number that matters is what the client has signed off."""
        t, _ = self._draft()
        issued = self._issue(t["id"]).data
        c = self.client.get(self.url).data["completeness"]
        self.assertEqual(c["provided"], 1)
        self.assertEqual(c["accepted"], 0)
        self.assertGreater(c["pct"], 0)
        self.assertEqual(c["accepted_pct"], 0)
        self._respond(issued["lines"][0]["id"], "APPROVED")
        c = self.client.get(self.url).data["completeness"]
        self.assertEqual(c["accepted"], 1)
        self.assertGreater(c["accepted_pct"], 0)

    def test_a_returned_document_stops_counting_as_done(self):
        t, _ = self._draft()
        issued = self._issue(t["id"]).data
        self.assertEqual(
            self.client.get(self.url).data["completeness"]["provided"], 1)
        self._respond(issued["lines"][0]["id"], "REJECTED")
        c = self.client.get(self.url).data["completeness"]
        self.assertEqual(c["provided"], 0)      # back with us
        self.assertEqual(c["returned"], 1)

    def test_an_unanswered_transmittal_goes_overdue(self):
        t, _ = self._draft()
        self._issue(t["id"], issued_on=str(date.today() - timedelta(days=30)),
                    response_days=14)
        row = self.client.get(self.url).data["transmittals"][0]
        self.assertTrue(row["overdue"])
        self.assertEqual(row["answered"], 0)

    def test_an_answered_transmittal_is_not_overdue(self):
        t, _ = self._draft()
        issued = self._issue(
            t["id"], issued_on=str(date.today() - timedelta(days=30)),
            response_days=14).data
        self._respond(issued["lines"][0]["id"], "APPROVED")
        row = self.client.get(self.url).data["transmittals"][0]
        self.assertFalse(row["overdue"])

    def test_the_transmittal_prints_for_the_engineer_to_sign(self):
        t, _ = self._draft()
        self._issue(t["id"])
        r = self.client.get(
            f"/api/v1/handover/transmittals/{t['id']}/transmittal.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")


class ClientApprovedOnPullTests(TestCase):
    """A record the client already approved is accepted on arrival; one we
    still have to hand over is not (owner 2026-09-03)."""

    def setUp(self):
        self.site = Site.objects.create(code="HO2", name="Handover site 2",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pm_ho2", User.Role.PM, site=self.site)
        self.se = make_user("se_ho2", User.Role.SITE_ENGINEER, site=self.site)
        self.project = Project.objects.create(
            site=self.site, code="P2", title="Villas", status="ACTIVE",
            defects_liability_months=12)
        self.client = APIClient()
        self.client.force_authenticate(self.pm)
        self.url = f"/api/v1/projects/{self.project.id}/handover"

    def _open(self):
        return self.client.post(self.url)

    def _doc(self, doc_type, status, ref, discipline=""):
        from .models import DocumentRevision
        d = Document.objects.create(
            doc_type=doc_type, ref=ref, site=self.site, project=self.project,
            doc_date=date.today(), status=status, created_by=self.se)
        rev = DocumentRevision.objects.create(
            document=d, rev_label="R0", created_by=self.se,
            payload={"discipline": discipline,
                     "client_result": {"result": status,
                                       "approval_date": "2026-08-20"}})
        d.current_revision = rev
        d.save(update_fields=["current_revision"])
        return d

    def _pull(self, doc):
        return self.client.post(f"{self.url}/items",
                                {"document_id": doc.id}, format="json")

    def test_an_approved_as_built_lands_in_the_as_built_section_accepted(self):
        self._open()
        d = self._doc("ABD", "APPROVED", "ABD-HO1-001", "MEP")
        cands = self.client.get(f"{self.url}/candidates").data
        self.assertEqual([c["suggested_section"] for c in cands
                          if c["ref"] == d.ref], ["AS_BUILT"])
        r = self._pull(d)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["section"], "AS_BUILT")
        self.assertEqual(r.data["status"], "ACCEPTED")
        self.assertEqual(r.data["accepted_on"], "2026-08-20")

    def test_it_fills_the_placeholder_the_pack_was_holding_open(self):
        """Not a second row beside 'As-built drawings — MEP'."""
        self._open()
        before = self.client.get(self.url).data
        mep = next(i for i in before["items"]
                   if i["section"] == "AS_BUILT" and i["discipline"] == "MEP")
        d = self._doc("ABD", "APPROVED", "ABD-HO1-002", "MEP services")
        r = self._pull(d)
        self.assertEqual(r.data["id"], mep["id"])          # same row
        after = self.client.get(self.url).data
        as_built = [i for i in after["items"] if i["section"] == "AS_BUILT"]
        self.assertEqual(len(as_built), 2)                  # still two
        c = after["completeness"]
        self.assertEqual(c["accepted"], 1)

    def test_approved_with_comments_still_counts_as_accepted(self):
        self._open()
        d = self._doc("ABD", "APPROVED_WITH_COMMENTS", "ABD-HO1-003")
        self.assertEqual(self._pull(d).data["status"], "ACCEPTED")

    def test_an_internal_record_is_still_ours_to_hand_over(self):
        """An approved inspection went to nobody outside; it stays Required
        until it goes out on a handover transmittal."""
        self._open()
        d = self._doc("IR", "APPROVED", "IR-HO1-009")
        r = self._pull(d)
        self.assertEqual(r.data["status"], "REQUIRED")
        self.assertTrue(r.data["has_evidence"])

    def test_a_second_pull_adds_a_row_once_the_placeholder_is_used(self):
        self._open()
        a = self._doc("ABD", "APPROVED", "ABD-HO1-004", "MEP")
        b = self._doc("ABD", "APPROVED", "ABD-HO1-005", "MEP")
        self._pull(a); self._pull(b)
        rows = [i for i in self.client.get(self.url).data["items"]
                if i["section"] == "AS_BUILT"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(sorted(r["document_ref"] for r in rows
                                if r["document_ref"]),
                         ["ABD-HO1-004", "ABD-HO1-005"])
