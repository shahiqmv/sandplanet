"""The tenders & offers register (owner 2026-09-08).

What it is for: the system held the awarded bills and no record of a single
submission. The rule that makes the record worth having is that a revision is
internal working until it is ISSUED — and an issued one is a submission that
stays on the record whatever is priced afterwards.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Document, Site, SitePmHistory, Tender, User
from .tests import make_user


class GateMixin:
    """Walking the approval chain, which every issued offer now goes through.

    A price does not leave the building on the QS's say-so: the Director
    reviews it, a signatory clears it, and only then may the QS submit it
    (owner 2026-09-09).
    """

    def make_approvers(self, prefix):
        self.director = make_user(f"{prefix}_dir", User.Role.DIRECTOR)
        self.sig = make_user(f"{prefix}_sig", User.Role.SIGNATORY)

    def clear(self, tid, value="500"):
        """Up to CLEARED, ready to submit."""
        self.client.force_authenticate(self.qs)
        r = self.client.post(f"/api/v1/tenders/{tid}/send-for-approval",
                             {"value": value}, format="json")
        assert r.status_code == 200, r.data
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/tenders/{tid}/approve", {},
                             format="json")
        assert r.status_code == 200, r.data
        self.client.force_authenticate(self.sig)
        r = self.client.post(f"/api/v1/tenders/{tid}/approve", {},
                             format="json")
        assert r.status_code == 200, r.data
        self.client.force_authenticate(self.qs)
        return r

    def approve_through(self, tid):
        """From PD_REVIEW to submitted, for an offer already sent up."""
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/tenders/{tid}/approve", {}, format="json")
        self.client.force_authenticate(self.sig)
        self.client.post(f"/api/v1/tenders/{tid}/approve", {}, format="json")
        self.client.force_authenticate(self.qs)
        return self.client.post(f"/api/v1/tenders/{tid}/issue", {},
                                format="json")

    def issue(self, tid, value="500"):
        """The whole road: priced, reviewed, cleared, submitted."""
        self.clear(tid, value)
        return self.client.post(f"/api/v1/tenders/{tid}/issue", {},
                                format="json")


class TenderRegisterTests(GateMixin, TestCase):
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

    def test_the_client_comes_from_the_site(self):
        """The site record already knows who it is — SFR and SSR are both
        Bunny Holdings (BVI) Limited (owner 2026-09-09)."""
        self.site.client_name = "Bunny Holdings (BVI) Limited"
        self.site.client_contact = "Attn: Projects"
        self.site.save(update_fields=["client_name", "client_contact"])
        r = self.client.post("/api/v1/tenders",
                             {"site_id": self.site.id, "title": "Jetty"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["client_name"],
                         "Bunny Holdings (BVI) Limited")
        self.assertEqual(r.data["client_contact"], "Attn: Projects")

    def test_a_typed_client_still_wins(self):
        """The party inviting a tender is not always the one on the site."""
        self.site.client_name = "Bunny Holdings (BVI) Limited"
        self.site.save(update_fields=["client_name"])
        r = self.client.post("/api/v1/tenders",
                             {"site_id": self.site.id, "title": "Jetty",
                              "client_name": "Soneva Management Pvt Ltd"},
                             format="json")
        self.assertEqual(r.data["client_name"], "Soneva Management Pvt Ltd")

    def test_a_site_with_no_client_on_file_asks_for_one(self):
        r = self.client.post("/api/v1/tenders",
                             {"site_id": self.site.id, "title": "Jetty"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("no client on file", r.data["detail"])

    def test_a_client_and_a_title_are_required(self):
        r = self.client.post("/api/v1/tenders",
                             {"site_id": self.site.id, "title": "x"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("client", r.data["detail"].lower())

    # ---- working vs sending -------------------------------------------

    def test_issuing_a_revision_is_the_submission(self):
        t = self.open_one()
        r = self.issue(t["id"], "125000.00")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "ISSUED")
        self.assertEqual(str(r.data["value_submitted"]), "125000.00")
        self.assertTrue(r.data["revisions"][0]["issued"])

    def test_an_issued_revision_cannot_be_issued_twice(self):
        t = self.open_one()
        self.issue(t["id"], "100")
        again = self.client.post(f"/api/v1/tenders/{t['id']}/issue", {},
                                 format="json")
        self.assertEqual(again.status_code, 400)
        self.assertIn("already gone to the client",
                      again.data["detail"])

    def test_a_further_price_is_a_further_revision(self):
        t = self.open_one()
        self.issue(t["id"], "100000")
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
        r = self.client.post(f"/api/v1/tenders/{t['id']}/send-for-approval",
                             {"value": "90000"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("upload that file", r.data["detail"].lower())

    def test_a_value_is_required_before_it_goes_up(self):
        """The Director and the signatory are approving a NUMBER."""
        t = self.open_one()
        r = self.client.post(f"/api/v1/tenders/{t['id']}/send-for-approval",
                             {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("value", r.data["detail"].lower())

    # ---- the approval gate ----------------------------------------------

    def test_a_price_walks_the_chain_before_it_leaves_the_building(self):
        """QS prices, Director reviews, signatory clears, QS submits."""
        t = self.open_one()
        r = self.client.post(f"/api/v1/tenders/{t['id']}/send-for-approval",
                             {"value": "125000"}, format="json")
        self.assertEqual(r.data["status"], "PD_REVIEW")
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/tenders/{t['id']}/approve", {},
                             format="json")
        self.assertEqual(r.data["status"], "SIGNATORY_REVIEW")
        self.client.force_authenticate(self.sig)
        r = self.client.post(f"/api/v1/tenders/{t['id']}/approve", {},
                             format="json")
        self.assertEqual(r.data["status"], "CLEARED")
        self.client.force_authenticate(self.qs)
        r = self.client.post(f"/api/v1/tenders/{t['id']}/issue", {},
                             format="json")
        self.assertEqual(r.data["status"], "ISSUED")

    def test_the_qs_cannot_submit_an_unapproved_price(self):
        t = self.open_one()
        r = self.client.post(f"/api/v1/tenders/{t['id']}/issue", {},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Send the offer for approval first", r.data["detail"])

    def test_the_signatory_cannot_clear_before_the_director_has_looked(self):
        t = self.open_one()
        self.client.post(f"/api/v1/tenders/{t['id']}/send-for-approval",
                         {"value": "1000"}, format="json")
        self.client.force_authenticate(self.sig)
        r = self.client.post(f"/api/v1/tenders/{t['id']}/approve", {},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Director", r.data["detail"])

    def test_the_qs_cannot_approve_their_own_price(self):
        t = self.open_one()
        self.client.post(f"/api/v1/tenders/{t['id']}/send-for-approval",
                         {"value": "1000"}, format="json")
        r = self.client.post(f"/api/v1/tenders/{t['id']}/approve", {},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Director", r.data["detail"])

    def test_an_approver_sends_it_back_with_a_reason(self):
        t = self.open_one()
        self.client.post(f"/api/v1/tenders/{t['id']}/send-for-approval",
                         {"value": "1000"}, format="json")
        self.client.force_authenticate(self.director)
        bare = self.client.post(f"/api/v1/tenders/{t['id']}/return", {},
                                format="json")
        self.assertEqual(bare.status_code, 400)
        r = self.client.post(f"/api/v1/tenders/{t['id']}/return",
                             {"comment": "Rates look light on piling"},
                             format="json")
        self.assertEqual(r.data["status"], "DRAFT")

    def test_a_further_revision_walks_the_chain_again(self):
        """The gate is on the PRICE, so a new one is a new decision."""
        t = self.open_one()
        self.issue(t["id"], "100000")
        self.client.post(f"/api/v1/tenders/{t['id']}/revision",
                         {"note": "Scope cut"}, format="json")
        blocked = self.client.post(f"/api/v1/tenders/{t['id']}/issue", {},
                                   format="json")
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("Send the offer for approval first",
                      blocked.data["detail"])
        r = self.issue(t["id"], "88000")
        self.assertEqual(r.data["status"], "ISSUED")
        self.assertEqual(str(r.data["value_submitted"]), "88000.00")

    def test_the_approvers_see_it_in_their_queue(self):
        t = self.open_one()
        self.client.post(f"/api/v1/tenders/{t['id']}/send-for-approval",
                         {"value": "1000"}, format="json")
        self.client.force_authenticate(self.director)
        titles = [g["title"] for g in
                  self.client.get("/api/v1/approvals/pending").data["groups"]]
        self.assertIn("To review — tender prices", titles)
        self.client.force_authenticate(self.sig)
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/tenders/{t['id']}/approve", {},
                         format="json")
        self.client.force_authenticate(self.sig)
        titles = [g["title"] for g in
                  self.client.get("/api/v1/approvals/pending").data["groups"]]
        self.assertIn("To clear — tender prices", titles)

    # ---- how it ends ---------------------------------------------------

    def test_an_award_is_recorded_with_their_reference(self):
        t = self.open_one()
        self.issue(t["id"], "125000")
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
        self.issue(t["id"], "125000")
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
        """Called directly, not through the chain helper — that helper
        authenticates as the QS, so routing this through it would have
        stopped testing a PM at all."""
        t = self.open_one()
        self.client.force_authenticate(self.pm)
        for action, body in (("send-for-approval", {"value": "1"}),
                             ("issue", {}), ("revision", {})):
            r = self.client.post(f"/api/v1/tenders/{t['id']}/{action}", body,
                                 format="json")
            self.assertEqual(r.status_code, 403, action)

    def test_the_director_runs_it_too(self):
        t = self.open_one()
        self.client.force_authenticate(self.director)
        r = self.issue(t["id"], "5000")
        self.assertEqual(r.status_code, 200, r.data)

    def test_the_document_underneath_is_a_real_tdr(self):
        t = self.open_one()
        doc = Document.objects.get(ref=t["ref"])
        self.assertEqual(doc.doc_type, "TDR")
        self.assertEqual(Tender.objects.get(pk=t["id"]).document_id, doc.id)


class TenderBoqTests(GateMixin, TestCase):
    """The offer's priced bill, and what an award does with it.

    A BOQ belongs to a project or to a tender, never both and never neither.
    Winning hands it over rather than copying it, so there is never a second
    priced bill to disagree with the first (owner 2026-09-08).
    """

    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE)
        self.qs = make_user("tb_qs", User.Role.QS)
        self.make_approvers("tb")
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
        self.issue(self.t["id"], "50000")
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
        self.issue(self.t["id"], "50000")
        r = self.client.post(f"/api/v1/tenders/{self.t['id']}/awarded", {},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("code", r.data["detail"].lower())

    def test_a_code_already_used_on_that_site_is_refused(self):
        from .models import Project
        Project.objects.create(site=self.site, code="SOUT JT", title="x",
                               status="ACTIVE")
        self.issue(self.t["id"], "1")
        r = self.client.post(f"/api/v1/tenders/{self.t['id']}/awarded",
                             {"project_code": "SOUT JT"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already has a project", r.data["detail"])

    def test_a_lost_tender_keeps_its_bill(self):
        """It is how the next enquiry from the same client gets priced."""
        from .models import Boq
        self._price()
        self.issue(self.t["id"], "50000")
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


class TenderProcessTests(GateMixin, TestCase):
    """The process as it is actually run: assigned, visited, queried, priced.

    The query is a TQ, not an RFI — that name is taken twice over in this app
    (contract-stage request for information, and inspection request). A TQ
    carries several numbered questions on one sheet and the client answers
    them one at a time (owner 2026-09-09).
    """

    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE)
        self.qs = make_user("tp_qs", User.Role.QS)
        self.make_approvers("tp")
        self.qs2 = make_user("tp_qs2", User.Role.QS)
        self.pm = make_user("tp_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.client = APIClient()
        self.client.force_authenticate(self.qs)
        self.t = self.client.post("/api/v1/tenders", {
            "site_id": self.site.id, "client_name": "Soneva",
            "title": "Jetty extension"}, format="json").data

    def act(self, action, body=None):
        return self.client.post(f"/api/v1/tenders/{self.t['id']}/{action}",
                                body or {}, format="json")


    # ---- whose job it is -------------------------------------------------

    def test_a_tender_is_carried_by_someone(self):
        r = self.act("assign", {"user_id": self.qs2.id})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["assigned_to"], self.qs2.full_name)
        self.assertEqual(self.act("assign", {"user_id": None})
                         .data["assigned_to"], None)

    def test_the_assignee_list_is_not_the_staff_register(self):
        r = self.client.get("/api/v1/tenders/assignees")
        self.assertEqual(r.status_code, 200)
        roles = {p["role"] for p in r.data}
        self.assertTrue(roles <= {"QS", "DIRECTOR", "ADMIN"}, roles)
        self.client.force_authenticate(self.pm)
        self.assertEqual(self.client.get("/api/v1/tenders/assignees")
                         .status_code, 403)

    # ---- the visit -------------------------------------------------------

    def test_a_visit_is_scheduled_then_written_up(self):
        r = self.act("event", {"kind": "VISIT",
                               "scheduled_on": str(date.today()),
                               "attendees": "Shahiq, Malith",
                               "location": "North jetty"})
        self.assertEqual(r.status_code, 200, r.data)
        e = r.data["events"][0]
        self.assertEqual(e["kind"], "VISIT")
        self.assertFalse(e["held"])
        self.assertEqual(e["location"], "North jetty")

        r = self.act("event-record", {"event_id": e["id"],
                                      "held_on": str(date.today()),
                                      "notes": "No barge access at low tide"})
        held = r.data["events"][0]
        self.assertTrue(held["held"])
        self.assertIn("low tide", held["notes"])

    def test_a_meeting_records_who_was_in_the_room(self):
        """A tender meeting is worth little as a record without the client's
        side of the table (owner 2026-09-09)."""
        e = self.act("event", {"kind": "MEETING",
                               "scheduled_on": str(date.today()),
                               "attendees": "Shahiq"}).data["events"][0]
        r = self.act("event-record",
                     {"event_id": e["id"], "held_on": str(date.today()),
                      "client_attendees": "Ms Fathimath, Projects",
                      "notes": "Client to confirm the crane"})
        got = r.data["events"][0]
        self.assertEqual(got["kind"], "MEETING")
        self.assertEqual(got["client_attendees"], "Ms Fathimath, Projects")
        self.assertIn("crane", got["notes"])

    def test_an_event_needs_a_date(self):
        self.assertEqual(self.act("event", {"kind": "VISIT"}).status_code,
                         400)

    def test_a_visit_carries_photos(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        e = self.act("event", {"scheduled_on": str(date.today())}
                     ).data["events"][0]
        self.act("event-record", {"event_id": e["id"],
                                  "held_on": str(date.today())})
        r = self.client.post(
            f"/api/v1/tenders/{self.t['id']}/events/{e['id']}/photo",
            {"file": SimpleUploadedFile("wall.jpg", b"\xff\xd8jpeg",
                                        content_type="image/jpeg")},
            format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data["events"][0]["photos"]), 1)

    def test_one_that_did_not_happen_can_go_but_a_record_stays(self):
        e = self.act("event", {"scheduled_on": str(date.today())}
                     ).data["events"][0]
        self.assertEqual(self.act("event-cancel", {"event_id": e["id"]})
                         .data["events"], [])
        e2 = self.act("event", {"scheduled_on": str(date.today())}
                      ).data["events"][0]
        self.act("event-record", {"event_id": e2["id"],
                                  "notes": "Held and noted"})
        r = self.act("event-cancel", {"event_id": e2["id"]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("record stays", r.data["detail"])

    # ---- the query sheet -------------------------------------------------

    def test_a_query_carries_several_questions_under_one_reference(self):
        q = self.act("query", {"subject": "Piling"}).data["queries"][0]
        self.assertEqual(q["ref"], "TDR-SJR-001-TQ01")
        self.act("query-question", {"query_id": q["id"],
                                    "question": "Is the crane ours?",
                                    "reference": "Dwg C-101"})
        r = self.act("query-question", {"query_id": q["id"],
                                        "question": "Who pays the ferry?"})
        items = r.data["queries"][0]["items"]
        self.assertEqual([i["number"] for i in items], [1, 2])
        self.assertEqual(items[0]["reference"], "Dwg C-101")

    def test_a_query_needs_a_question_before_it_is_issued(self):
        q = self.act("query", {}).data["queries"][0]
        r = self.act("query-issue", {"query_id": q["id"]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("at least one question", r.data["detail"])

    def test_an_issued_query_is_closed_to_further_questions(self):
        """It is what the client holds; anything further is a new sheet."""
        q = self.act("query", {}).data["queries"][0]
        self.act("query-question", {"query_id": q["id"], "question": "A?"})
        self.act("query-issue", {"query_id": q["id"]})
        r = self.act("query-question", {"query_id": q["id"], "question": "B?"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("already gone to the client", r.data["detail"])

    def test_answers_land_per_question_not_per_sheet(self):
        """A client commonly answers three of five, and a sheet marked simply
        'answered' would hide that."""
        q = self.act("query", {}).data["queries"][0]
        self.act("query-question", {"query_id": q["id"], "question": "A?"})
        self.act("query-question", {"query_id": q["id"], "question": "B?"})
        q = self.act("query-issue", {"query_id": q["id"]}).data["queries"][0]
        first = q["items"][0]["id"]
        r = self.act("query-answer", {"query_id": q["id"], "item_id": first,
                                      "answer": "Client provides the crane",
                                      "client_ref": "SJ/TQ/014"})
        got = r.data["queries"][0]
        self.assertEqual(got["answered"], 1)
        self.assertEqual(len(got["items"]), 2)
        self.assertTrue(got["items"][0]["is_answered"])
        self.assertFalse(got["items"][1]["is_answered"])
        self.assertEqual(got["client_ref"], "SJ/TQ/014")

    def test_query_sheets_are_numbered_within_the_tender(self):
        self.act("query", {})
        r = self.act("query", {})
        self.assertEqual([q["ref"] for q in r.data["queries"]],
                         ["TDR-SJR-001-TQ01", "TDR-SJR-001-TQ02"])

    def test_the_query_sheet_renders_in_our_format(self):
        from django.template.loader import render_to_string

        from . import tenders as svc
        from .models import TenderQuery
        q = self.act("query", {"subject": "Piling"}).data["queries"][0]
        self.act("query-question", {"query_id": q["id"],
                                    "question": "Is the crane ours?"})
        html = render_to_string(
            "pdf/tender_query.html",
            svc.query_context(TenderQuery.objects.get(pk=q["id"])))
        self.assertIn("TDR-SJR-001-TQ01", html)
        self.assertIn("Is the crane ours?", html)
        self.assertIn("Tender Query", html)

    def test_a_pm_reads_the_queries_but_raises_none(self):
        self.act("query", {"subject": "Piling"})
        self.client.force_authenticate(self.pm)
        got = self.client.get(f"/api/v1/tenders/{self.t['id']}").data
        self.assertEqual(len(got["queries"]), 1)
        self.assertEqual(self.act("query", {}).status_code, 403)

    # ---- the pack --------------------------------------------------------

    def test_the_pack_says_when_the_offer_and_the_bill_disagree(self):
        from . import tenders as svc
        from .models import Tender
        self.client.post(f"/api/v1/tenders/{self.t['id']}/boq/items",
                         {"rows": [{"description": "Excavate", "unit": "m3",
                                    "qty": "100", "rate_combined": "5"}]},
                         format="json")
        self.issue(self.t["id"], "900")
        ctx = svc.submission_context(Tender.objects.get(pk=self.t["id"]))
        self.assertTrue(ctx["diverges"])
        self.assertEqual(float(ctx["offered"]), 900.0)
        self.assertEqual(float(ctx["bill_total"]), 500.0)

    def test_the_money_stack_follows_the_workbook(self):
        """Sub total, provisional sum, GST, grand total — built on the value
        offered, which is what the client was told (owner 2026-09-09)."""
        from decimal import Decimal

        from . import tenders as svc
        from .models import Tender
        from .models import TenderProvisionalItem
        t = Tender.objects.get(pk=self.t["id"])
        t.value_submitted = Decimal("856898.17")
        t.gst_percent = Decimal("8")
        t.save()
        TenderProvisionalItem.objects.create(
            tender=t, label="Landscaping", amount=Decimal("100000"))
        st = svc.money_stack(t, Decimal("856898.17"))
        self.assertEqual(st["net"], Decimal("956898.17"))
        self.assertEqual(st["gst"], Decimal("76551.85"))
        self.assertEqual(st["grand_total"], Decimal("1033450.02"))

    def test_the_summary_lists_the_bills_in_order(self):
        from . import tenders as svc
        from .models import Tender
        self.client.post(f"/api/v1/tenders/{self.t['id']}/boq/items",
                         {"rows": [
                             {"description": "Preliminaries"},
                             {"description": "Site setup", "unit": "item",
                              "qty": "1", "rate_combined": "1000"},
                             {"description": "Structural works"},
                             {"description": "Concrete", "unit": "m3",
                              "qty": "10", "rate_combined": "200"},
                         ]}, format="json")
        ctx = svc.submission_context(Tender.objects.get(pk=self.t["id"]))
        self.assertEqual([(b["no"], b["name"], float(b["amount"]))
                          for b in ctx["bills"]],
                         [(1, "Preliminaries", 1000.0),
                          (2, "Structural works", 2000.0)])

    def test_trade_headings_inside_a_bill_do_not_split_it(self):
        """A real bill is a sheet of trades. The summary is one row per bill,
        so the bill each priced line names is what groups it — not every
        heading above it, which would list forty trades as forty bills."""
        from . import tenders as svc
        from .models import Tender
        self.client.post(f"/api/v1/tenders/{self.t['id']}/boq/items",
                         {"rows": [
                             {"description": "BILL NO. 1"},
                             {"description": "PRELIMINARIES"},
                             {"section": "Preliminaries",
                              "description": "Site setup", "unit": "item",
                              "qty": "1", "rate_combined": "1000"},
                             {"description": "SERVICES AND FACILITIES"},
                             {"section": "Preliminaries",
                              "description": "Water", "unit": "item",
                              "qty": "1", "rate_combined": "500"},
                             {"description": "BILL NO. 2"},
                             {"section": "Mechanical Works",
                              "description": "Pumps", "unit": "no",
                              "qty": "2", "rate_combined": "250"},
                         ]}, format="json")
        ctx = svc.submission_context(Tender.objects.get(pk=self.t["id"]))
        self.assertEqual([(b["no"], b["name"], b["lines"], float(b["amount"]))
                          for b in ctx["bills"]],
                         [(1, "Preliminaries", 2, 1500.0),
                          (2, "Mechanical Works", 1, 500.0)])

    def test_a_new_tender_starts_with_the_usual_terms(self):
        """Blank boxes on every tender is retyping by another name."""
        from .models import Tender
        t = Tender.objects.get(pk=self.t["id"])
        self.assertIn("40% advance", t.payment_terms)
        self.assertIn("defects liability", t.warranty_terms)
        self.assertEqual(t.validity_days, 30)

    def test_the_terms_are_editable(self):
        r = self.client.patch(f"/api/v1/tenders/{self.t['id']}",
                              {"validity_days": 45,
                               "duration_days": 150,
                               "doc_ref": "SP-BOQ-2026-SJR-OPO-O1",
                               "payment_terms": "50% advance"},
                              format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["validity_days"], 45)
        self.assertEqual(r.data["doc_ref"], "SP-BOQ-2026-SJR-OPO-O1")

    # ---- the discount and the provisional sums ------------------------

    def _patch(self, **body):
        return self.client.patch(f"/api/v1/tenders/{self.t['id']}", body,
                                 format="json")

    def test_a_client_can_be_given_more_than_one_provisional_sum(self):
        """One figure is fine for one allowance and wrong the moment there
        are two — three separate items used to be added together under one
        unexplained line (owner 2026-09-10)."""
        r = self._patch(provisional_items=[
            {"label": "Landscaping", "amount": "60000"},
            {"label": "Signage", "amount": "25000"},
            {"label": "Artwork", "amount": "15000"}])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([(p["label"], str(p["amount"]))
                          for p in r.data["provisional_items"]],
                         [("Landscaping", "60000.00"), ("Signage", "25000.00"),
                          ("Artwork", "15000.00")])
        from . import tenders as svc
        from .models import Tender
        st = svc.money_stack(Tender.objects.get(pk=self.t["id"]),
                             Decimal("0"))
        self.assertEqual(st["provisional"], Decimal("100000"))
        self.assertEqual(len(st["provisional_items"]), 3)

    def test_the_list_is_replaced_wholesale(self):
        """The screen edits them as one list; a half-applied list is a wrong
        total on a client-facing offer."""
        self._patch(provisional_items=[{"label": "Landscaping",
                                        "amount": "60000"}])
        r = self._patch(provisional_items=[{"label": "Signage",
                                            "amount": "25000"}])
        self.assertEqual([p["label"] for p in r.data["provisional_items"]],
                         ["Signage"])

    def test_a_blank_row_is_not_an_error(self):
        r = self._patch(provisional_items=[
            {"label": "Landscaping", "amount": "60000"},
            {"label": "", "amount": ""}])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["provisional_items"]), 1)

    def test_a_provisional_sum_needs_a_description(self):
        r = self._patch(provisional_items=[{"label": "", "amount": "60000"}])
        self.assertEqual(r.status_code, 400)
        self.assertIn("description", r.data["detail"])

    def test_a_lump_sum_discount_comes_off_before_gst(self):
        """Some revisions are won on a discount rather than a re-price. GST
        is charged on what the client actually pays."""
        from . import tenders as svc
        from .models import Tender
        r = self._patch(discount_amount="50000",
                        discount_label="Negotiation discount")
        self.assertEqual(r.status_code, 200, r.data)
        t = Tender.objects.get(pk=self.t["id"])
        t.value_submitted = Decimal("1000000")
        t.gst_percent = Decimal("8")
        t.save()
        st = svc.money_stack(t, Decimal("1000000"))
        self.assertEqual(st["subtotal"], Decimal("1000000"))
        self.assertEqual(st["discount"], Decimal("50000"))
        self.assertEqual(st["discount_label"], "Negotiation discount")
        self.assertEqual(st["after_discount"], Decimal("950000"))
        self.assertEqual(st["gst"], Decimal("76000.00"))     # 8% of 950,000
        self.assertEqual(st["grand_total"], Decimal("1026000.00"))

    def test_the_discount_does_not_eat_the_provisional_sums(self):
        """A provisional sum is an allowance to be spent, not our price —
        discounting it would be discounting the client's own money."""
        from . import tenders as svc
        from .models import Tender
        self._patch(discount_amount="50000",
                    provisional_items=[{"label": "Landscaping",
                                        "amount": "100000"}])
        t = Tender.objects.get(pk=self.t["id"])
        t.value_submitted = Decimal("1000000")
        t.gst_percent = Decimal("8")
        t.save()
        st = svc.money_stack(t, Decimal("1000000"))
        self.assertEqual(st["net"], Decimal("1050000"))   # 950,000 + 100,000
        self.assertEqual(st["grand_total"], Decimal("1134000.00"))

    def test_a_discount_is_entered_as_a_positive_figure(self):
        r = self._patch(discount_amount="-50000")
        self.assertEqual(r.status_code, 400)
        self.assertIn("comes off", r.data["detail"])

    def test_the_cover_prints_their_reference_when_they_keep_one(self):
        from . import tenders as svc
        from .models import Tender
        t = Tender.objects.get(pk=self.t["id"])
        self.assertEqual(svc.submission_context(t)["ref"], "TDR-SJR-001")
        t.doc_ref = "SP-BOQ-2026-SJR-OPO-O1"
        t.save(update_fields=["doc_ref"])
        ctx = svc.submission_context(Tender.objects.get(pk=t.pk))
        self.assertEqual(ctx["ref"], "SP-BOQ-2026-SJR-OPO-O1")
        self.assertEqual(ctx["system_ref"], "TDR-SJR-001")

    def test_the_cover_and_summary_render(self):
        from django.template.loader import render_to_string

        from . import tenders as svc
        from .models import Tender
        t = Tender.objects.get(pk=self.t["id"])
        t.doc_ref = "SP-BOQ-2026-SJR-OPO-O1"
        t.duration_days = 150
        t.prepared_by = "Sanjula"
        t.save()
        self.client.post(f"/api/v1/tenders/{self.t['id']}/boq/items",
                         {"rows": [
                             {"description": "Preliminaries"},
                             {"description": "Site setup", "unit": "item",
                              "qty": "1", "rate_combined": "1000"},
                         ]}, format="json")
        html = render_to_string(
            "pdf/tender_submission.html",
            svc.submission_context(Tender.objects.get(pk=t.pk)))
        # Money is grouped: a proposal that prints 1033450.02 for its grand
        # total reads as a spreadsheet dump, not an offer (owner 2026-09-09).
        self.assertIn("1,000.00", html)
        for needle in ["Bill of Quantities and Commercial Proposal",
                       "SP-BOQ-2026-SJR-OPO-O1", "Final Summary",
                       "Preliminaries", "Terms and Conditions",
                       "Acknowledgement", "Sanjula",
                       "150 calendar days", "Grand total"]:
            self.assertIn(needle, html, needle)

    def test_the_pack_renders(self):
        from django.template.loader import render_to_string

        from . import tenders as svc
        from .models import Tender
        self.client.post(f"/api/v1/tenders/{self.t['id']}/boq/items",
                         {"rows": [{"description": "Excavate", "unit": "m3",
                                    "qty": "100", "rate_combined": "5"}]},
                         format="json")
        self.issue(self.t["id"], "500")
        html = render_to_string(
            "pdf/tender_submission.html",
            svc.submission_context(Tender.objects.get(pk=self.t["id"])))
        self.assertIn("TDR-SJR-001", html)
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
        self.assertIn("on the client's own form", html)
        self.assertNotIn("Secret rate", html)


class TenderDocumentTests(GateMixin, TestCase):
    """The files an enquiry arrives with and produces. The client's own bill
    is the one that matters: where we submit on their form, that file IS the
    submission (owner 2026-09-09)."""

    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE)
        self.qs = make_user("tdoc_qs", User.Role.QS)
        self.make_approvers("tdoc")
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

    def test_their_bill_is_what_unblocks_the_offer(self):
        """The check bites when the price goes up for approval — there is no
        sense putting an offer in front of the Director when the document it
        is made on is missing."""
        def send():
            return self.client.post(
                f"/api/v1/tenders/{self.t['id']}/send-for-approval",
                {"value": "1000"}, format="json")

        blocked = send()
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("upload that file", blocked.data["detail"])
        # An enquiry document is not their bill and must not unblock it.
        self._upload(kind="TENDER_ENQUIRY", name="enquiry.pdf")
        self.assertEqual(send().status_code, 400)
        self._upload(kind="TENDER_BILL")
        self.assertEqual(send().status_code, 200)
        # It is with the Director now, so carry on from there rather than
        # sending it up a second time.
        self.assertEqual(self.approve_through(self.t["id"]).data["status"],
                         "ISSUED")

    def test_a_file_that_went_to_the_client_stays_on_the_record(self):
        r = self._upload(kind="TENDER_BILL")
        att = r.data["attachments"][0]["id"]
        self.issue(self.t["id"], "1000")
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
