"""M6c — PR signatory gate + cost postings (§6C.2, §4A, §7.5)."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import costing
from .models import (CostPosting, Document, Payable, Site, SitePmHistory,
                     User)
from .tests import make_user


class PrCostingBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE,
                                        start_date=date.today() -
                                        timedelta(days=30))
        self.sa = make_user("sa1", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.purchasing = make_user("hop", User.Role.HO_PURCHASING)
        self.director = make_user("dir", User.Role.DIRECTOR)
        self.signatory = make_user("sig", User.Role.SIGNATORY)
        self.finance = make_user("fin", User.Role.FINANCE)
        self.client = APIClient()

    def act(self, ref, action, user, **body):
        self.client.force_authenticate(user)
        return self.client.post(f"/api/v1/documents/{ref}/actions/{action}",
                                body, format="json")

    def authorise(self, ref, approver=None):
        """Authorise a Director-approved PR the M6d way: Finance builds a
        payment voucher, a signatory approves it."""
        self.client.force_authenticate(self.finance)
        pv = self.client.post("/api/v1/payment-vouchers",
                              {"source_refs": [ref]}, format="json")
        assert pv.status_code == 201, pv.data
        pref = pv.data["ref"]
        self.client.post(f"/api/v1/payment-vouchers/{pref}/actions/submit",
                         {}, format="json")
        self.client.force_authenticate(approver or self.signatory)
        return self.client.post(
            f"/api/v1/payment-vouchers/{pref}/actions/approve", {},
            format="json")

    def sign_orders(self, pr):
        """Walk the credit orders the award drafted through Purchasing and the
        Signatory — the step that used to happen inside Finance's voucher
        (owner 2026-08-22). Returns the issued POs."""
        from .models import Document
        pos = list(Document.objects.filter(doc_type="PO",
                                           links_from__to_document=pr,
                                           status="DRAFT").distinct())
        for po in pos:
            self.act(po.ref, "submit", self.purchasing)
            self.act(po.ref, "authorise", self.signatory)
            po.refresh_from_db()
        return pos

    def make_pr(self):
        # MR first (a PR answers an MR)
        self.client.force_authenticate(self.sa)
        mr = self.client.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id, "general_works": True, "payload": {},
            "lines": [{"free_text_desc": "Cement", "unit": "bag",
                       "qty_required": 100, "qty_to_order": 100}],
        }, format="json").data
        self.act(mr["ref"], "submit", self.sa)
        self.act(mr["ref"], "approve", self.pm)
        self.act(mr["ref"], "send", self.sa)
        self.client.force_authenticate(self.purchasing)
        pr = self.client.post("/api/v1/documents", {
            "doc_type": "PR", "site_id": self.site.id, "mr_refs": [mr["ref"]],
            "lines": [
                {"free_text_desc": "Vendor A", "vendor": "Vendor A",
                 "amount_cash": 5000},
                {"free_text_desc": "Vendor B", "vendor": "Vendor B",
                 "amount_credit": 7000},
            ],
        }, format="json").data
        self.act(pr["ref"], "submit", self.purchasing)
        self.act(pr["ref"], "approve", self.director)
        return Document.objects.get(ref=pr["ref"])


class PrMrPickerTests(PrCostingBase):
    """A new PR offers only MRs at HO with no active PR (owner workflow
    fix, 2026-07-09)."""

    def make_mr(self, sent=True):
        self.client.force_authenticate(self.sa)
        mr = self.client.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id, "general_works": True, "payload": {},
            "lines": [{"free_text_desc": "Sand", "unit": "m3",
                       "qty_required": 10, "qty_to_order": 10}],
        }, format="json").data
        if sent:
            self.act(mr["ref"], "submit", self.sa)
            self.act(mr["ref"], "approve", self.pm)
            self.act(mr["ref"], "send", self.sa)
        return mr

    def for_pr(self):
        self.client.force_authenticate(self.purchasing)
        return [m["ref"] for m in self.client.get(
            "/api/v1/documents/list?doc_type=MR&for_pr=1").data]

    def _mr_sent(self):
        self.client.force_authenticate(self.sa)
        mr = self.client.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id, "general_works": True, "payload": {},
            "lines": [{"free_text_desc": "Cement", "unit": "bag",
                       "qty_required": 100, "qty_to_order": 100},
                      {"free_text_desc": "Sand", "unit": "m3",
                       "qty_required": 10, "qty_to_order": 10}]},
            format="json").data
        self.act(mr["ref"], "submit", self.sa)
        self.act(mr["ref"], "approve", self.pm)
        self.act(mr["ref"], "send", self.sa)
        return mr

    def test_mr_locked_while_pr_in_progress(self):
        mr = self._mr_sent()
        # Purchasing raises a PR against the MR (claims its lines)
        self.client.force_authenticate(self.purchasing)
        pr = self.client.post("/api/v1/documents", {
            "doc_type": "PR", "site_id": self.site.id,
            "mr_refs": [mr["ref"]], "lines": []}, format="json").data
        # Site can't amend while the PR is live
        self.client.force_authenticate(self.sa)
        r = self.client.post(f"/api/v1/documents/{mr['ref']}/revisions",
                             {}, format="json")
        self.assertEqual(r.status_code, 409, r.data)
        self.assertIn(pr["ref"], r.data["detail"])
        # void the PR → the lock lifts
        self.act(pr["ref"], "void", self.purchasing, reason="not needed")
        self.client.force_authenticate(self.sa)
        r2 = self.client.post(f"/api/v1/documents/{mr['ref']}/revisions",
                             {}, format="json")
        self.assertEqual(r2.status_code, 201, r2.data)

    def test_unsent_mr_not_offered(self):
        draft_mr = self.make_mr(sent=False)  # still DRAFT
        sent_mr = self.make_mr(sent=True)
        refs = self.for_pr()
        self.assertIn(sent_mr["ref"], refs)
        self.assertNotIn(draft_mr["ref"], refs)

    def test_mr_with_ongoing_draft_pr_drops_out(self):
        mr = self.make_mr(sent=True)
        self.assertIn(mr["ref"], self.for_pr())
        # a draft PR against it links MR_PR immediately
        self.client.force_authenticate(self.purchasing)
        self.client.post("/api/v1/documents", {
            "doc_type": "PR", "site_id": self.site.id, "mr_refs": [mr["ref"]],
            "lines": [{"free_text_desc": "V", "vendor": "V",
                       "amount_cash": 100}],
        }, format="json")
        self.assertNotIn(mr["ref"], self.for_pr())


class PrAuthorisationTests(PrCostingBase):
    def test_draft_voucher_traps_pr_but_dashboard_surfaces_it(self):
        # An approved PR reaches Finance's awaiting-voucher queue; the moment a
        # voucher is started for it, it leaves that queue — so the dashboard
        # must show the in-flight voucher holding it, or the PR "disappears".
        pr = self.make_pr()
        self.client.force_authenticate(self.finance)
        self.assertIn(pr.ref, [x["ref"] for x in
                      self.client.get("/api/v1/finance/awaiting-voucher").data])
        self.client.post("/api/v1/payment-vouchers",
                         {"source_refs": [pr.ref]}, format="json")
        # gone from the awaiting queue …
        self.assertNotIn(pr.ref, [x["ref"] for x in
                         self.client.get("/api/v1/finance/awaiting-voucher").data])
        # … but visible as an in-flight draft voucher that holds it
        dash = self.client.get("/api/v1/finance/dashboard").data
        inflight = dash["vouchers"]["in_flight"]
        self.assertEqual(len(inflight), 1)
        self.assertEqual(inflight[0]["status"], "DRAFT")
        self.assertIn(pr.ref, inflight[0]["holds"])

    def test_each_side_commits_where_it_is_signed(self):
        """Cash commits when Finance's voucher is approved; credit commits
        when the Signatory signs its purchase order. A purchase order is a
        commitment, not a payment, so it no longer waits on a payment run
        (owner 2026-08-22)."""
        pr = self.make_pr()
        # Director-approved: nothing committed yet, either side.
        self.assertEqual(CostPosting.objects.filter(document=pr).count(), 0)
        self.assertEqual(Payable.objects.filter(document=pr).count(), 0)
        # The cash side, on the voucher — 5000, and nothing of the credit.
        r = self.authorise(pr.ref)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(costing.document_net(pr, state="COMMITTED"),
                         Decimal("5000"))
        self.assertEqual(costing.document_net(pr, state="INCURRED"),
                         Decimal("5000"))
        self.assertEqual(Payable.objects.filter(document=pr).count(), 0)
        # The credit side, on its own order.
        self.sign_orders(pr)
        self.assertEqual(costing.document_net(pr, state="COMMITTED"),
                         Decimal("12000"))
        self.assertEqual(costing.document_net(pr, state="INCURRED"),
                         Decimal("12000"))
        self.assertEqual(Payable.objects.filter(document=pr).count(), 1)
        self.assertEqual(Payable.objects.get(document=pr).amount,
                         Decimal("7000"))

    def test_a_fully_credit_pr_never_reaches_finance(self):
        """The complaint that started this: a credit purchase had to sit in
        Finance's voucher queue purely to be authorised (owner 2026-08-22)."""
        from .models import Document
        self.client.force_authenticate(self.sa)
        mr = self.client.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id, "general_works": True,
            "payload": {}, "lines": [{"free_text_desc": "Steel", "unit": "t",
                                      "qty_required": 5, "qty_to_order": 5}]},
            format="json").data
        self.act(mr["ref"], "submit", self.sa)
        self.act(mr["ref"], "approve", self.pm)
        self.act(mr["ref"], "send", self.sa)
        self.client.force_authenticate(self.purchasing)
        pr = self.client.post("/api/v1/documents", {
            "doc_type": "PR", "site_id": self.site.id, "mr_refs": [mr["ref"]],
            "lines": [{"free_text_desc": "Steel Co", "vendor": "Steel Co",
                       "amount_credit": 9000}]}, format="json").data
        self.act(pr["ref"], "submit", self.purchasing)
        self.act(pr["ref"], "approve", self.director)
        doc = Document.objects.get(ref=pr["ref"])
        # Not in Finance's queue at all — there is nothing to pay yet.
        self.client.force_authenticate(self.finance)
        self.assertNotIn(pr["ref"], [x["ref"] for x in self.client.get(
            "/api/v1/finance/awaiting-voucher").data])
        # The order carries it instead, and settles the PR when signed.
        self.sign_orders(doc)
        doc.refresh_from_db()
        self.assertEqual(doc.status, "PAID_PO_ISSUED")
        self.assertEqual(Payable.objects.get(document=doc).amount,
                         Decimal("9000"))

    def test_direct_authorise_action_is_retired(self):
        pr = self.make_pr()
        r = self.act(pr.ref, "authorise", self.signatory)
        self.assertEqual(r.status_code, 400)
        self.assertIn("payment voucher", r.data["detail"].lower())

    def test_finance_cannot_approve_own_voucher(self):
        pr = self.make_pr()
        self.client.force_authenticate(self.finance)
        pv = self.client.post("/api/v1/payment-vouchers",
                              {"source_refs": [pr.ref]},
                              format="json").data["ref"]
        self.client.post(f"/api/v1/payment-vouchers/{pv}/actions/submit", {},
                         format="json")
        r = self.client.post(
            f"/api/v1/payment-vouchers/{pv}/actions/approve", {},
            format="json")
        self.assertEqual(r.status_code, 403)

    def test_withdrawal_reverses_commitment(self):
        pr = self.make_pr()
        self.authorise(pr.ref)
        self.assertEqual(costing.document_net(pr, state="COMMITTED"),
                         Decimal("5000"))
        r = self.act(pr.ref, "withdraw-authorisation", self.finance,
                     comment="wrong vendor account")
        self.assertEqual(r.status_code, 200, r.data)
        pr.refresh_from_db()
        self.assertEqual(pr.status, "DRAFT")
        self.assertEqual(costing.document_net(pr), Decimal("0"))

    def test_finance_cannot_withdraw_behind_a_signed_order(self):
        """A signed order is with the supplier. Finance withdrawing the cash
        payment must not quietly cancel it (owner 2026-08-22)."""
        pr = self.make_pr()
        self.authorise(pr.ref)
        pos = self.sign_orders(pr)
        r = self.act(pr.ref, "withdraw-authorisation", self.finance,
                     comment="wrong vendor account")
        self.assertEqual(r.status_code, 400)
        self.assertIn(pos[0].ref, r.data["detail"])
        self.assertIn("amend the order", r.data["detail"])
        pr.refresh_from_db()
        self.assertNotEqual(pr.status, "DRAFT")
        self.assertEqual(Payable.objects.get(document=pr).status,
                         "OUTSTANDING")

    def test_payment_posts_paid_and_settles_payable(self):
        pr = self.make_pr()
        self.sign_orders(pr)           # the credit order books the payable
        lines = list(pr.current_revision.lines.all())
        credit_line = next(ln for ln in lines if (ln.amount_credit or 0) > 0)
        self.client.force_authenticate(self.finance)
        r = self.client.post(f"/api/v1/pr/{pr.ref}/vendor-payment",
                             {"line_id": credit_line.id,
                              "payment_ref": "VCH-9"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(costing.document_net(pr, state="PAID"),
                         Decimal("7000"))
        self.assertEqual(Payable.objects.get(document=pr).status, "SETTLED")

    def test_credit_payable_paid_via_new_voucher(self):
        """A credit payable can be pulled onto a fresh voucher; signatory
        approves, Finance settles → PAID posted + payable SETTLED."""
        pr = self.make_pr()
        self.sign_orders(pr)           # the order books the payable (7000)
        payable = Payable.objects.get(document=pr)
        self.assertEqual(payable.status, "OUTSTANDING")
        self.client.force_authenticate(self.finance)
        pv = self.client.post("/api/v1/payment-vouchers",
                              {"payable_ids": [payable.id]}, format="json")
        self.assertEqual(pv.status_code, 201, pv.data)
        pref = pv.data["ref"]
        self.client.post(f"/api/v1/payment-vouchers/{pref}/actions/submit",
                         {}, format="json")
        self.client.force_authenticate(self.signatory)
        self.client.post(f"/api/v1/payment-vouchers/{pref}/actions/approve",
                         {}, format="json")
        self.client.force_authenticate(self.finance)
        r = self.client.post(
            f"/api/v1/payment-vouchers/{pref}/actions/settle-payable",
            {"payable_id": payable.id, "payment_ref": "TT-77"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        payable.refresh_from_db()
        self.assertEqual(payable.status, "SETTLED")
        self.assertEqual(costing.document_net(pr, state="PAID"),
                         Decimal("7000"))

    def test_credit_terms_editable_until_authorisation(self):
        from datetime import date, timedelta
        pr = self.make_pr()            # Director-approved, no payable yet
        credit_line = next(ln for ln in pr.current_revision.lines.all()
                           if (ln.amount_credit or 0) > 0)
        self.client.force_authenticate(self.purchasing)
        r = self.client.post(f"/api/v1/pr/{pr.ref}/credit-terms",
                             {"rows": [{"line_id": credit_line.id,
                                        "credit_days": 45}]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        credit_line.refresh_from_db()
        self.assertEqual(credit_line.credit_days, 45)
        self.sign_orders(pr)           # payable due now follows the 45 days
        p = Payable.objects.get(document=pr)
        self.assertEqual(p.due_date, date.today() + timedelta(days=45))
        # once the payable exists the terms are locked
        self.client.force_authenticate(self.purchasing)
        r = self.client.post(f"/api/v1/pr/{pr.ref}/credit-terms",
                             {"rows": [{"line_id": credit_line.id,
                                        "credit_days": 10}]}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_payable_due_date_follows_credit_days(self):
        from datetime import date, timedelta
        pr = self.make_pr()
        credit_line = next(ln for ln in pr.current_revision.lines.all()
                           if (ln.amount_credit or 0) > 0)
        credit_line.credit_days = 60          # supplier gives 60-day terms
        credit_line.save(update_fields=["credit_days"])
        self.sign_orders(pr)
        p = Payable.objects.get(document=pr)
        self.assertEqual(p.due_date, date.today() + timedelta(days=60))
        self.assertIn("60", p.terms)
