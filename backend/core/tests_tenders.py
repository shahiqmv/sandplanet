"""The tenders & offers register (owner 2026-09-08).

What it is for: the system held the awarded bills and no record of a single
submission. The rule that makes the record worth having is that a revision is
internal working until it is ISSUED — and an issued one is a submission that
stays on the record whatever is priced afterwards.
"""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Document, Site, SitePmHistory, Tender, User
from .tests import make_user


class TenderRegisterTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE)
        self.other = Site.objects.create(code="VKR", name="Velaa",
                                         status=Site.Status.ACTIVE)
        self.qs = make_user("td_qs", User.Role.QS)
        self.director = make_user("td_dir", User.Role.DIRECTOR)
        self.sig = make_user("td_sig", User.Role.SIGNATORY)
        self.pm = make_user("td_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.other_pm = make_user("td_pm2", User.Role.PM, site=self.other)
        SitePmHistory.objects.create(site=self.other, pm_user=self.other_pm,
                                     from_date=date.today())
        self.sa = make_user("td_sa", User.Role.SITE_ADMIN, site=self.site)
        self.client = APIClient()
        self.client.force_authenticate(self.qs)

    def open_one(self, site=None, **extra):
        body = {"site_id": (site or self.site).id,
                "client_name": "Soneva Fushi Resort",
                "title": "Jetty extension — civil works",
                "enquiry_date": str(date.today()),
                "due_date": str(date.today() + timedelta(days=14))}
        body.update(extra)
        r = self.client.post("/api/v1/tenders", body, format="json")
        assert r.status_code == 201, r.data
        return r.data

    # ---- the reference, which is the point ----------------------------

    def test_the_system_issues_the_reference(self):
        """Nothing was issuing it, so every submission invented its own."""
        a, b = self.open_one(), self.open_one()
        self.assertEqual(a["ref"], "TDR-SJR-001")
        self.assertEqual(b["ref"], "TDR-SJR-002")
        self.assertEqual(self.open_one(site=self.other)["ref"],
                         "TDR-VKR-001")

    def test_a_tender_starts_priceable_at_r0(self):
        t = self.open_one()
        self.assertEqual(t["status"], "DRAFT")
        self.assertEqual(t["rev_label"], "R0")
        self.assertEqual(len(t["revisions"]), 1)
        self.assertFalse(t["revisions"][0]["issued"])

    def test_a_client_and_a_title_are_required(self):
        r = self.client.post("/api/v1/tenders",
                             {"site_id": self.site.id, "title": "x"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("client", r.data["detail"].lower())

    # ---- working vs sending -------------------------------------------

    def test_issuing_a_revision_is_the_submission(self):
        t = self.open_one()
        r = self.client.post(f"/api/v1/tenders/{t['id']}/issue",
                             {"value": "125000.00"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "SUBMITTED")
        self.assertEqual(str(r.data["value_submitted"]), "125000.00")
        self.assertTrue(r.data["revisions"][0]["issued"])

    def test_an_issued_revision_cannot_be_issued_twice(self):
        t = self.open_one()
        self.client.post(f"/api/v1/tenders/{t['id']}/issue",
                         {"value": "100"}, format="json")
        again = self.client.post(f"/api/v1/tenders/{t['id']}/issue",
                                 {"value": "200"}, format="json")
        self.assertEqual(again.status_code, 400)
        self.assertIn("already been issued", again.data["detail"])

    def test_a_further_price_is_a_further_revision(self):
        t = self.open_one()
        self.client.post(f"/api/v1/tenders/{t['id']}/issue",
                         {"value": "100000"}, format="json")
        r = self.client.post(f"/api/v1/tenders/{t['id']}/revision",
                             {"note": "Client cut the scope"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["rev_label"], "R1")
        self.assertEqual(r.data["status"], "DRAFT")   # working again
        # ...and the first submission is untouched on the record.
        r0 = next(x for x in r.data["revisions"] if x["rev_label"] == "R0")
        self.assertTrue(r0["issued"])
        self.assertEqual(r0["value"], "100000.00")
        self.assertEqual(str(r.data["value_submitted"]), "100000.00")

    def test_you_cannot_open_a_revision_on_top_of_unissued_work(self):
        t = self.open_one()
        r = self.client.post(f"/api/v1/tenders/{t['id']}/revision", {},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not been issued", r.data["detail"])

    def test_a_client_format_offer_needs_their_bill_attached(self):
        """Their file IS the submission — issuing without it would record a
        submission the system cannot produce."""
        t = self.open_one(submit_our_format=False)
        r = self.client.post(f"/api/v1/tenders/{t['id']}/issue",
                             {"value": "90000"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("attach", r.data["detail"].lower())

    def test_a_value_is_required_to_issue(self):
        t = self.open_one()
        r = self.client.post(f"/api/v1/tenders/{t['id']}/issue", {},
                             format="json")
        self.assertEqual(r.status_code, 400)

    # ---- how it ends ---------------------------------------------------

    def test_an_award_is_recorded_with_their_reference(self):
        t = self.open_one()
        self.client.post(f"/api/v1/tenders/{t['id']}/issue",
                         {"value": "125000"}, format="json")
        r = self.client.post(f"/api/v1/tenders/{t['id']}/awarded",
                             {"outcome_ref": "LOA/2026/014",
                              "value_awarded": "119500",
                              "project_code": "JETTY X"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "AWARDED")
        self.assertEqual(r.data["outcome_ref"], "LOA/2026/014")
        self.assertEqual(str(r.data["value_awarded"]), "119500.00")

    def test_a_loss_records_the_reason_and_who_won(self):
        t = self.open_one()
        self.client.post(f"/api/v1/tenders/{t['id']}/issue",
                         {"value": "125000"}, format="json")
        r = self.client.post(f"/api/v1/tenders/{t['id']}/lost",
                             {"lost_reason": "Price", "lost_to": "Rasheed Co"},
                             format="json")
        self.assertEqual(r.data["status"], "LOST")
        self.assertEqual(r.data["lost_to"], "Rasheed Co")

    def test_an_award_cannot_be_recorded_before_anything_was_sent(self):
        t = self.open_one()
        r = self.client.post(f"/api/v1/tenders/{t['id']}/awarded", {},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Issue the offer", r.data["detail"])

    def test_a_withdrawal_needs_no_submission(self):
        t = self.open_one()
        r = self.client.post(f"/api/v1/tenders/{t['id']}/withdrawn", {},
                             format="json")
        self.assertEqual(r.data["status"], "WITHDRAWN")

    def test_a_decided_tender_is_closed_to_edits(self):
        t = self.open_one()
        self.client.post(f"/api/v1/tenders/{t['id']}/withdrawn", {},
                         format="json")
        r = self.client.patch(f"/api/v1/tenders/{t['id']}",
                              {"title": "changed"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("closed", r.data["detail"])

    # ---- who sees it ----------------------------------------------------

    def test_the_signatory_reads_it_and_writes_nothing(self):
        self.open_one()
        self.client.force_authenticate(self.sig)
        self.assertEqual(self.client.get("/api/v1/tenders").status_code, 200)
        r = self.client.post("/api/v1/tenders",
                             {"site_id": self.site.id, "client_name": "X",
                              "title": "Y"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_a_pm_sees_only_their_own_sites_tenders(self):
        """A tender carries a price we have not won; another resort's PM has
        no business reading it."""
        mine = self.open_one()
        theirs = self.open_one(site=self.other)
        self.client.force_authenticate(self.pm)
        refs = [row["ref"] for row in self.client.get("/api/v1/tenders").data]
        self.assertIn(mine["ref"], refs)
        self.assertNotIn(theirs["ref"], refs)
        self.assertEqual(self.client.get(
            f"/api/v1/tenders/{theirs['id']}").status_code, 404)

    def test_a_site_admin_sees_none_of_it(self):
        self.open_one()
        self.client.force_authenticate(self.sa)
        self.assertEqual(self.client.get("/api/v1/tenders").status_code, 403)

    def test_a_pm_cannot_price_or_issue(self):
        t = self.open_one()
        self.client.force_authenticate(self.pm)
        r = self.client.post(f"/api/v1/tenders/{t['id']}/issue",
                             {"value": "1"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_the_director_runs_it_too(self):
        t = self.open_one()
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/tenders/{t['id']}/issue",
                             {"value": "5000"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

    def test_the_document_underneath_is_a_real_tdr(self):
        t = self.open_one()
        doc = Document.objects.get(ref=t["ref"])
        self.assertEqual(doc.doc_type, "TDR")
        self.assertEqual(Tender.objects.get(pk=t["id"]).document_id, doc.id)


class TenderBoqTests(TestCase):
    """The offer's priced bill, and what an award does with it.

    A BOQ belongs to a project or to a tender, never both and never neither.
    Winning hands it over rather than copying it, so there is never a second
    priced bill to disagree with the first (owner 2026-09-08).
    """

    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE)
        self.qs = make_user("tb_qs", User.Role.QS)
        self.client = APIClient()
        self.client.force_authenticate(self.qs)
        self.t = self.client.post("/api/v1/tenders", {
            "site_id": self.site.id, "client_name": "Soneva",
            "title": "Jetty extension"}, format="json").data

    def _price(self, amount="50000"):
        return self.client.post(f"/api/v1/tenders/{self.t['id']}/boq/items",
                                {"rows": [{"description": "Piling",
                                           "unit": "m", "qty": "100",
                                           "rate_combined": "500"}]},
                                format="json")

    def test_a_tender_can_hold_a_priced_bill(self):
        r = self._price()
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["exists"])
        self.assertEqual(float(r.data["total"]), 50000.0)

    def test_the_bill_belongs_to_the_tender_and_no_project(self):
        from .models import Boq
        self._price()
        boq = Boq.objects.get(tender_id=self.t["id"])
        self.assertIsNone(boq.project_id)

    def test_winning_hands_the_bill_to_the_new_project(self):
        from .models import Boq, Project
        self._price()
        self.client.post(f"/api/v1/tenders/{self.t['id']}/issue",
                         {"value": "50000"}, format="json")
        r = self.client.post(f"/api/v1/tenders/{self.t['id']}/awarded",
                             {"outcome_ref": "LOA/9", "value_awarded": "48000",
                              "project_code": "SOUT JT"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["awarded_project"], "SOUT JT")
        p = Project.objects.get(site=self.site, code="SOUT JT")
        self.assertEqual(str(p.contract_value), "48000.00")
        self.assertEqual(p.loa_ref, "LOA/9")
        # The SAME bill, moved — not a copy.
        self.assertEqual(Boq.objects.count(), 1)
        boq = Boq.objects.get()
        self.assertEqual(boq.project_id, p.id)
        self.assertIsNone(boq.tender_id)
        self.assertEqual(float(boq.total), 50000.0)

    def test_an_award_needs_a_project_code(self):
        self._price()
        self.client.post(f"/api/v1/tenders/{self.t['id']}/issue",
                         {"value": "50000"}, format="json")
        r = self.client.post(f"/api/v1/tenders/{self.t['id']}/awarded", {},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("code", r.data["detail"].lower())

    def test_a_code_already_used_on_that_site_is_refused(self):
        from .models import Project
        Project.objects.create(site=self.site, code="SOUT JT", title="x",
                               status="ACTIVE")
        self.client.post(f"/api/v1/tenders/{self.t['id']}/issue",
                         {"value": "1"}, format="json")
        r = self.client.post(f"/api/v1/tenders/{self.t['id']}/awarded",
                             {"project_code": "SOUT JT"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already has a project", r.data["detail"])

    def test_a_lost_tender_keeps_its_bill(self):
        """It is how the next enquiry from the same client gets priced."""
        from .models import Boq
        self._price()
        self.client.post(f"/api/v1/tenders/{self.t['id']}/issue",
                         {"value": "50000"}, format="json")
        self.client.post(f"/api/v1/tenders/{self.t['id']}/lost",
                         {"lost_reason": "Price"}, format="json")
        boq = Boq.objects.get(tender_id=self.t["id"])
        self.assertEqual(float(boq.total), 50000.0)

    def test_a_closed_tenders_bill_cannot_be_changed(self):
        self._price()
        self.client.post(f"/api/v1/tenders/{self.t['id']}/withdrawn", {},
                         format="json")
        r = self._price()
        self.assertEqual(r.status_code, 400)
        self.assertIn("closed", r.data["detail"])

    def test_a_bill_cannot_have_two_owners_or_none(self):
        from django.db import IntegrityError, transaction
        from .models import Boq, Project, Tender
        self._price()
        boq = Boq.objects.get()
        p = Project.objects.create(site=self.site, code="P1", title="x",
                                   status="ACTIVE")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                boq.project = p
                boq.save()          # tender still set — two owners
        boq.refresh_from_db()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Boq.objects.create(project=None, tender=None)
        self.assertEqual(Tender.objects.count(), 1)


class TenderTrailAndPackTests(TestCase):
    """The RFI trail, the visit notes, and the pack that goes to the client."""

    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE)
        self.qs = make_user("tp_qs", User.Role.QS)
        self.pm = make_user("tp_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.client = APIClient()
        self.client.force_authenticate(self.qs)
        self.t = self.client.post("/api/v1/tenders", {
            "site_id": self.site.id, "client_name": "Soneva",
            "title": "Jetty extension"}, format="json").data

    def act(self, action, body):
        return self.client.post(f"/api/v1/tenders/{self.t['id']}/{action}",
                                body, format="json")

    def test_rfis_are_numbered_within_the_tender(self):
        """So one can be cited as 'our RFI 2 against TDR-SJR-001'."""
        a = self.act("rfi", {"question": "Is the crane ours?"})
        b = self.act("rfi", {"question": "Who pays the ferry?"})
        self.assertEqual(a.status_code, 200, a.data)
        self.assertEqual([r["number"] for r in b.data["rfis"]], [1, 2])

    def test_an_rfi_keeps_the_clients_answer_beside_the_question(self):
        r = self.act("rfi", {"question": "Is the crane ours?"})
        rfi_id = r.data["rfis"][0]["id"]
        r = self.act("rfi-answer", {"rfi_id": rfi_id,
                                    "answer": "Client provides it"})
        self.assertEqual(r.status_code, 200, r.data)
        got = r.data["rfis"][0]
        self.assertEqual(got["answer"], "Client provides it")
        self.assertTrue(got["answered"])
        self.assertIsNotNone(got["answered_on"])

    def test_an_answer_needs_words(self):
        r = self.act("rfi", {"question": "?"})
        rfi_id = r.data["rfis"][0]["id"]
        self.assertEqual(self.act("rfi-answer",
                                  {"rfi_id": rfi_id, "answer": "  "})
                         .status_code, 400)

    def test_an_rfi_from_another_tender_is_refused(self):
        other = self.client.post("/api/v1/tenders", {
            "site_id": self.site.id, "client_name": "X",
            "title": "Y"}, format="json").data
        r = self.client.post(f"/api/v1/tenders/{other['id']}/rfi",
                             {"question": "q"}, format="json")
        rfi_id = r.data["rfis"][0]["id"]
        self.assertEqual(self.act("rfi-answer",
                                  {"rfi_id": rfi_id, "answer": "a"})
                         .status_code, 400)

    def test_a_visit_is_recorded_with_who_went(self):
        r = self.act("visit", {"visited_on": str(date.today()),
                               "attendees": "Shahiq, Malith",
                               "notes": "No barge access at low tide"})
        self.assertEqual(r.status_code, 200, r.data)
        v = r.data["visits"][0]
        self.assertEqual(v["attendees"], "Shahiq, Malith")
        self.assertIn("barge", v["notes"])

    def test_a_visit_needs_a_date(self):
        self.assertEqual(self.act("visit", {"notes": "x"}).status_code, 400)

    def test_a_pm_reads_the_trail_but_does_not_write_it(self):
        self.act("rfi", {"question": "Is the crane ours?"})
        self.client.force_authenticate(self.pm)
        got = self.client.get(f"/api/v1/tenders/{self.t['id']}").data
        self.assertEqual(len(got["rfis"]), 1)
        self.assertEqual(self.client.post(
            f"/api/v1/tenders/{self.t['id']}/rfi", {"question": "q"},
            format="json").status_code, 403)

    def test_the_pack_summarises_the_bill_by_section(self):
        from . import tenders as svc
        from .models import Tender
        self.client.post(f"/api/v1/tenders/{self.t['id']}/boq/items",
                         {"rows": [
                             {"description": "Bill 1 — Substructure"},
                             {"description": "Excavate", "unit": "m3",
                              "qty": "100", "rate_combined": "5"},
                             {"description": "Blinding", "unit": "m3",
                              "qty": "10", "rate_combined": "80"},
                         ]}, format="json")
        ctx = svc.submission_context(Tender.objects.get(pk=self.t["id"]))
        self.assertEqual(len(ctx["sections"]), 1)
        self.assertEqual(ctx["sections"][0]["lines"], 2)
        self.assertEqual(float(ctx["sections"][0]["amount"]), 1300.0)
        self.assertEqual(float(ctx["bill_total"]), 1300.0)

    def test_the_pack_says_when_the_offer_and_the_bill_disagree(self):
        """The offered figure is what the client was told; a bill that totals
        something else is worth showing, not hiding."""
        from . import tenders as svc
        from .models import Tender
        self.client.post(f"/api/v1/tenders/{self.t['id']}/boq/items",
                         {"rows": [{"description": "Excavate", "unit": "m3",
                                    "qty": "100", "rate_combined": "5"}]},
                         format="json")
        self.act("issue", {"value": "900"})
        ctx = svc.submission_context(Tender.objects.get(pk=self.t["id"]))
        self.assertTrue(ctx["diverges"])
        self.assertEqual(float(ctx["offered"]), 900.0)
        self.assertEqual(float(ctx["bill_total"]), 500.0)

    def test_the_pack_renders(self):
        from django.template.loader import render_to_string

        from . import tenders as svc
        from .models import Tender
        self.client.post(f"/api/v1/tenders/{self.t['id']}/boq/items",
                         {"rows": [{"description": "Excavate", "unit": "m3",
                                    "qty": "100", "rate_combined": "5"}]},
                         format="json")
        self.act("issue", {"value": "500"})
        html = render_to_string(
            "pdf/tender_submission.html",
            svc.submission_context(Tender.objects.get(pk=self.t["id"])))
        self.assertIn("TDR-SJR-001", html)
        self.assertIn("Jetty extension", html)
        self.assertIn("Excavate", html)

    def test_a_clients_own_bill_prints_the_letter_without_our_schedule(self):
        from django.template.loader import render_to_string

        from . import tenders as svc
        from .models import Tender
        t = self.client.post("/api/v1/tenders", {
            "site_id": self.site.id, "client_name": "Soneva",
            "title": "Spa works", "submit_our_format": False},
            format="json").data
        self.client.post(f"/api/v1/tenders/{t['id']}/boq/items",
                         {"rows": [{"description": "Secret rate", "unit": "m",
                                    "qty": "1", "rate_combined": "9"}]},
                         format="json")
        html = render_to_string(
            "pdf/tender_submission.html",
            svc.submission_context(Tender.objects.get(pk=t["id"])))
        self.assertIn("on your own form", html)
        # Our schedule is NOT appended — they are getting their own bill.
        self.assertNotIn("Secret rate", html)


class TenderDocumentTests(TestCase):
    """The files an enquiry arrives with and produces. The client's own bill
    is the one that matters: where we submit on their form, that file IS the
    submission (owner 2026-09-09)."""

    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE)
        self.qs = make_user("tdoc_qs", User.Role.QS)
        self.pm = make_user("tdoc_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.client = APIClient()
        self.client.force_authenticate(self.qs)
        self.t = self.client.post("/api/v1/tenders", {
            "site_id": self.site.id, "client_name": "Soneva",
            "title": "Jetty", "submit_our_format": False}, format="json").data

    def _file(self, name="their-boq.xlsx"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(name, b"x,y\n1,2\n",
                                  content_type="text/csv")

    def _upload(self, kind="TENDER_BILL", name="their-boq.xlsx"):
        return self.client.post(f"/api/v1/tenders/{self.t['id']}/documents",
                                {"file": self._file(name), "kind": kind},
                                format="multipart")

    def test_a_document_can_be_filed_against_a_tender(self):
        r = self._upload(kind="TENDER_ENQUIRY", name="enquiry.pdf")
        self.assertEqual(r.status_code, 201, r.data)
        got = r.data["attachments"][0]
        self.assertEqual(got["file_name"], "enquiry.pdf")
        self.assertEqual(got["kind"], "TENDER_ENQUIRY")
        self.assertFalse(got["issued"])

    def test_their_bill_is_what_unblocks_issuing(self):
        blocked = self.client.post(f"/api/v1/tenders/{self.t['id']}/issue",
                                   {"value": "1000"}, format="json")
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("upload that file", blocked.data["detail"])
        # An enquiry document is not their bill and must not unblock it.
        self._upload(kind="TENDER_ENQUIRY", name="enquiry.pdf")
        still = self.client.post(f"/api/v1/tenders/{self.t['id']}/issue",
                                 {"value": "1000"}, format="json")
        self.assertEqual(still.status_code, 400)
        self._upload(kind="TENDER_BILL")
        ok = self.client.post(f"/api/v1/tenders/{self.t['id']}/issue",
                              {"value": "1000"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)

    def test_a_file_that_went_to_the_client_stays_on_the_record(self):
        r = self._upload(kind="TENDER_BILL")
        att = r.data["attachments"][0]["id"]
        self.client.post(f"/api/v1/tenders/{self.t['id']}/issue",
                         {"value": "1000"}, format="json")
        gone = self.client.delete(
            f"/api/v1/tenders/{self.t['id']}/documents/{att}")
        self.assertEqual(gone.status_code, 400)
        self.assertIn("stays on the record", gone.data["detail"])

    def test_a_file_filed_by_mistake_can_go(self):
        r = self._upload(kind="TENDER_ENQUIRY", name="wrong.pdf")
        att = r.data["attachments"][0]["id"]
        gone = self.client.delete(
            f"/api/v1/tenders/{self.t['id']}/documents/{att}")
        self.assertEqual(gone.status_code, 200, gone.data)
        self.assertEqual(gone.data["attachments"], [])

    def test_an_unknown_kind_is_refused(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        r = self.client.post(f"/api/v1/tenders/{self.t['id']}/documents",
                             {"file": SimpleUploadedFile("x.pdf", b"x"),
                              "kind": "PASSPORT_COPY"}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_a_pm_reads_the_documents_but_files_none(self):
        self._upload(kind="TENDER_ENQUIRY", name="enquiry.pdf")
        self.client.force_authenticate(self.pm)
        got = self.client.get(f"/api/v1/tenders/{self.t['id']}").data
        self.assertEqual(len(got["attachments"]), 1)
        r = self.client.post(f"/api/v1/tenders/{self.t['id']}/documents",
                             {"file": self._file(), "kind": "TENDER_BILL"},
                             format="multipart")
        self.assertEqual(r.status_code, 403)
