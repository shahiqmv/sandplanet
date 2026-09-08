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
        t = self.open_one(our_format=False)
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
                              "value_awarded": "119500"}, format="json")
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
