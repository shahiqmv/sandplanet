"""M6d — Payment Voucher: Finance batches Director-approved requisitions,
a signatory approves the batch or queries individual lines (§6C.2)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import costing
from .models import (CostHead, CostPosting, Document, Site, SitePmHistory, User)
from .tests import make_user


class VoucherBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.sa = make_user("sa1", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.director = make_user("dir", User.Role.DIRECTOR)
        self.signatory = make_user("sig", User.Role.SIGNATORY)
        self.finance = make_user("fin", User.Role.FINANCE)
        self.head = CostHead.objects.get(name="Transport & Freight")
        self.client = APIClient()

    def act(self, ref, action, user, **data):
        self.client.force_authenticate(user)
        return self.client.post(f"/api/v1/documents/{ref}/actions/{action}",
                                data, format="json")

    def director_approved_pyr(self, amount=3000, payee="Boat Co"):
        """Raise a PYR and walk it to DIRECTOR_APPROVED."""
        self.client.force_authenticate(self.sa)
        ref = self.client.post("/api/v1/documents", {
            "doc_type": "PYR", "site_id": self.site.id, "payload": {},
            "cost_head_id": self.head.id, "payee": payee,
            "payment_type": "DIRECT", "payment_method": "BANK",
            "amount_requested": amount, "purpose": "Boat hire",
            "has_supporting_doc": True,
        }, format="json").data["ref"]
        self.act(ref, "submit", self.sa)
        self.act(ref, "approve", self.pm)
        self.act(ref, "approve", self.director)
        return ref

    # --- voucher API helpers -------------------------------------------
    def create_voucher(self, refs, user=None):
        self.client.force_authenticate(user or self.finance)
        return self.client.post("/api/v1/payment-vouchers",
                                {"source_refs": refs}, format="json")

    def voucher_action(self, ref, action, user, **data):
        self.client.force_authenticate(user)
        return self.client.post(
            f"/api/v1/payment-vouchers/{ref}/actions/{action}", data,
            format="json")


class VoucherHappyPathTests(VoucherBase):
    def test_awaiting_lists_director_approved(self):
        a = self.director_approved_pyr(amount=3000, payee="A")
        b = self.director_approved_pyr(amount=1500, payee="B")
        self.client.force_authenticate(self.finance)
        refs = [r["ref"] for r in
                self.client.get("/api/v1/finance/awaiting-voucher").data]
        self.assertIn(a, refs)
        self.assertIn(b, refs)

    def test_mobile_voucher_summary_names_payee_and_purpose(self):
        # The signatory's mobile detail summarises each line so they know what
        # the payment is for — not just a document ref (owner 2026-07-19).
        from .views_mobile import _document_payload
        a = self.director_approved_pyr(amount=3000, payee="Boat Co")
        pv = self.create_voucher([a]).data["ref"]
        payload = _document_payload(Document.objects.get(ref=pv), None)
        self.assertEqual(payload["doc_type"], "PV")
        line = payload["lines"][0]
        self.assertEqual(line["kind"], "Payment request")
        self.assertEqual(line["title"], "Boat Co")
        self.assertIn("Boat hire", line["subtitle"])
        self.assertEqual(line["ref"], a)

    def test_create_submit_approve_commits_each_line(self):
        a = self.director_approved_pyr(amount=3000, payee="A")
        b = self.director_approved_pyr(amount=1500, payee="B")
        r = self.create_voucher([a, b])
        self.assertEqual(r.status_code, 201, r.data)
        pv = r.data["ref"]
        self.assertEqual(r.data["total"], Decimal("4500"))
        self.assertEqual(len(r.data["lines"]), 2)

        # once on a draft voucher, they drop out of the awaiting list
        self.client.force_authenticate(self.finance)
        awaiting = [x["ref"] for x in
                    self.client.get("/api/v1/finance/awaiting-voucher").data]
        self.assertNotIn(a, awaiting)

        self.assertEqual(self.voucher_action(pv, "submit",
                                             self.finance).status_code, 200)
        r = self.voucher_action(pv, "approve", self.signatory)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "APPROVED")
        # each source is now AUTHORISED and committed
        for ref, amt in ((a, "3000"), (b, "1500")):
            doc = Document.objects.get(ref=ref)
            self.assertEqual(doc.status, "AUTHORISED")
            self.assertEqual(costing.document_net(doc, state="COMMITTED"),
                             Decimal(amt))

    def test_finance_cannot_approve(self):
        a = self.director_approved_pyr()
        pv = self.create_voucher([a]).data["ref"]
        self.voucher_action(pv, "submit", self.finance)
        r = self.voucher_action(pv, "approve", self.finance)
        self.assertEqual(r.status_code, 403)

    def test_filing_pdf(self):
        a = self.director_approved_pyr(amount=3000, payee="A")
        pv = self.create_voucher([a]).data["ref"]
        self.voucher_action(pv, "submit", self.finance)
        self.voucher_action(pv, "approve", self.signatory)
        # a site user may not pull the filing PDF
        self.client.force_authenticate(self.sa)
        self.assertEqual(
            self.client.get(f"/api/v1/payment-vouchers/{pv}/pdf").status_code,
            403)
        # Finance gets a PDF (200) or a graceful 503 where the engine is
        # unavailable — never a 500
        self.client.force_authenticate(self.finance)
        r = self.client.get(f"/api/v1/payment-vouchers/{pv}/pdf")
        self.assertIn(r.status_code, (200, 503))
        if r.status_code == 200:
            self.assertEqual(r["Content-Type"], "application/pdf")


class VoucherQueryTests(VoucherBase):
    def test_queried_line_returns_source_others_commit(self):
        a = self.director_approved_pyr(amount=3000, payee="A")
        b = self.director_approved_pyr(amount=1500, payee="B")
        pv = self.create_voucher([a, b]).data["ref"]
        self.voucher_action(pv, "submit", self.finance)
        # find the line id for source a
        info = self.client.get(f"/api/v1/payment-vouchers/{pv}").data
        line_a = next(ln["line_id"] for ln in info["lines"] if ln["ref"] == a)

        r = self.voucher_action(pv, "approve", self.signatory,
                                queried_ids=[line_a],
                                note="Payee account looks wrong.")
        self.assertEqual(r.status_code, 200, r.data)
        # a went back to its raiser as a draft, nothing committed
        doc_a = Document.objects.get(ref=a)
        self.assertEqual(doc_a.status, "DRAFT")
        self.assertEqual(doc_a.payment_request.returned_reason,
                         "SIGNATORY_DECLINED")
        self.assertEqual(CostPosting.objects.filter(document=doc_a).count(), 0)
        # b committed
        doc_b = Document.objects.get(ref=b)
        self.assertEqual(doc_b.status, "AUTHORISED")
        self.assertEqual(costing.document_net(doc_b, state="COMMITTED"),
                         Decimal("1500"))

    def test_queried_source_can_go_on_a_later_voucher(self):
        a = self.director_approved_pyr(amount=3000, payee="A")
        pv = self.create_voucher([a]).data["ref"]
        self.voucher_action(pv, "submit", self.finance)
        info = self.client.get(f"/api/v1/payment-vouchers/{pv}").data
        line_a = info["lines"][0]["line_id"]
        self.voucher_action(pv, "approve", self.signatory,
                            queried_ids=[line_a], note="fix payee")
        # raiser fixes and re-walks it to DIRECTOR_APPROVED
        self.act(a, "submit", self.sa)
        self.act(a, "approve", self.pm)
        self.act(a, "approve", self.director)
        # it is awaiting a voucher again
        self.client.force_authenticate(self.finance)
        awaiting = [x["ref"] for x in
                    self.client.get("/api/v1/finance/awaiting-voucher").data]
        self.assertIn(a, awaiting)
        # and can be put on a fresh voucher
        r = self.create_voucher([a])
        self.assertEqual(r.status_code, 201, r.data)


class VoucherDisbursementTests(VoucherBase):
    """After approval Finance records the actual payments; the voucher
    surfaces paid/settled state (M6d disbursement)."""

    def _approved_voucher(self, amount=3000):
        a = self.director_approved_pyr(amount=amount, payee="A")
        pv = self.create_voucher([a]).data["ref"]
        self.voucher_action(pv, "submit", self.finance)
        self.voucher_action(pv, "approve", self.signatory)
        return pv, a

    def test_line_paid_flag_and_settled_progress(self):
        pv, a = self._approved_voucher(3000)
        info = self.client.get(f"/api/v1/payment-vouchers/{pv}").data
        line = info["lines"][0]
        self.assertFalse(line["paid"])
        self.assertFalse(info["settled"])
        self.assertEqual(info["approved_count"], 1)
        self.assertEqual(info["paid_count"], 0)
        # Finance records the payment on the PYR via the reused endpoint
        self.client.force_authenticate(self.finance)
        r = self.client.post(f"/api/v1/documents/{a}/actions/pay",
                             {"amount_paid": 3000, "payment_ref": "TRF-1"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        info = self.client.get(f"/api/v1/payment-vouchers/{pv}").data
        self.assertTrue(info["lines"][0]["paid"])
        self.assertEqual(info["lines"][0]["payment_ref"], "TRF-1")
        self.assertTrue(info["settled"])
        self.assertEqual(info["paid_count"], 1)


class FinanceDashboardTests(VoucherBase):
    def test_dashboard_aggregates(self):
        self.director_approved_pyr(amount=3000, payee="A")
        self.client.force_authenticate(self.finance)
        r = self.client.get("/api/v1/finance/dashboard")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["awaiting_voucher"]["count"], 1)
        self.assertEqual(r.data["awaiting_voucher"]["total"], Decimal("3000"))
        self.assertIn("petty_cash", r.data)
        # a site user cannot see the finance dashboard
        self.client.force_authenticate(self.sa)
        self.assertEqual(
            self.client.get("/api/v1/finance/dashboard").status_code, 403)


class VoucherGuardTests(VoucherBase):
    def test_cannot_add_non_approved_requisition(self):
        # a PYR only PM-approved is not eligible
        self.client.force_authenticate(self.sa)
        ref = self.client.post("/api/v1/documents", {
            "doc_type": "PYR", "site_id": self.site.id, "payload": {},
            "cost_head_id": self.head.id, "payee": "X",
            "payment_type": "DIRECT", "payment_method": "BANK",
            "amount_requested": 900, "purpose": "p",
            "has_supporting_doc": True,
        }, format="json").data["ref"]
        self.act(ref, "submit", self.sa)
        self.act(ref, "approve", self.pm)  # PM only
        r = self.create_voucher([ref])
        self.assertEqual(r.status_code, 400)

    def test_same_source_cannot_be_on_two_active_vouchers(self):
        a = self.director_approved_pyr()
        self.create_voucher([a])
        r = self.create_voucher([a])
        self.assertEqual(r.status_code, 400)

    def test_site_user_cannot_build_voucher(self):
        a = self.director_approved_pyr()
        r = self.create_voucher([a], user=self.sa)
        self.assertEqual(r.status_code, 403)


class VoucherVoidTests(VoucherBase):
    """Voiding a payment voucher unwinds its commitments (owner 2026-07-16)."""

    def _approved_voucher(self, amount=3000):
        a = self.director_approved_pyr(amount=amount, payee="A")
        pv = self.create_voucher([a]).data["ref"]
        self.voucher_action(pv, "submit", self.finance)
        self.voucher_action(pv, "approve", self.signatory)
        return a, pv

    def test_finance_requests_then_signatory_authorises_the_void(self):
        from django.db.models import Sum
        a, pv = self._approved_voucher(3000)
        pyr = Document.objects.get(ref=a)
        self.assertEqual(pyr.status, "AUTHORISED")
        committed = CostPosting.objects.filter(
            document=pyr, state="COMMITTED",
            reversal_of__isnull=True).aggregate(s=Sum("amount"))["s"]
        self.assertEqual(committed, Decimal("3000"))
        # a signatory can't void until Finance has requested it
        self.assertEqual(
            self.voucher_action(pv, "void", self.signatory).status_code, 400)
        # Finance raises the request (reason required)
        self.assertEqual(
            self.voucher_action(pv, "request-void", self.finance).status_code,
            400)
        r = self.voucher_action(pv, "request-void", self.finance,
                                reason="wrong batch")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["void_requested"])
        # signatory authorises the reversal
        r = self.voucher_action(pv, "void", self.signatory)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "VOID")
        # PYR returned to its pre-voucher state; commitment nets to zero
        pyr.refresh_from_db()
        self.assertEqual(pyr.status, "DIRECTOR_APPROVED")
        net = CostPosting.objects.filter(
            document=pyr, state="COMMITTED").aggregate(s=Sum("amount"))["s"]
        self.assertEqual(net or Decimal("0"), Decimal("0"))
        # and it's available to be vouchered again
        self.client.force_authenticate(self.finance)
        awaiting = [x["ref"] for x in
                    self.client.get("/api/v1/finance/awaiting-voucher").data]
        self.assertIn(a, awaiting)

    def test_authorised_void_needs_finance_request_and_a_signatory(self):
        a, pv = self._approved_voucher(1000)
        # Finance can't void an AUTHORISED voucher outright — only request it
        self.assertEqual(
            self.voucher_action(pv, "void", self.finance,
                                reason="x").status_code, 403)
        # a signatory can't request the void; that's Finance's step
        self.assertEqual(
            self.voucher_action(pv, "request-void", self.signatory,
                                reason="x").status_code, 403)
        # signatory can't authorise before a request exists
        self.assertEqual(
            self.voucher_action(pv, "void", self.signatory).status_code, 400)

    def test_signatory_can_decline_a_void_request(self):
        a, pv = self._approved_voucher(1000)
        self.voucher_action(pv, "request-void", self.finance, reason="oops")
        r = self.voucher_action(pv, "decline-void", self.signatory)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data["void_requested"])
        self.assertEqual(r.data["status"], "APPROVED")
        # and with the request gone, a bare void is blocked again
        self.assertEqual(
            self.voucher_action(pv, "void", self.signatory).status_code, 400)

    def test_finance_voids_an_unauthorised_voucher_with_a_reason(self):
        a = self.director_approved_pyr(amount=1000, payee="A")
        pv = self.create_voucher([a]).data["ref"]
        self.voucher_action(pv, "submit", self.finance)   # SUBMITTED, unapproved
        # reason is required
        self.assertEqual(
            self.voucher_action(pv, "void", self.finance).status_code, 400)
        # Finance voids the not-yet-authorised voucher with an explanation
        r = self.voucher_action(pv, "void", self.finance, reason="wrong payee")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "VOID")
        # nothing was committed, so the PYR is untouched and free to re-voucher
        self.assertEqual(Document.objects.get(ref=a).status,
                         "DIRECTOR_APPROVED")
        self.client.force_authenticate(self.finance)
        awaiting = [x["ref"] for x in
                    self.client.get("/api/v1/finance/awaiting-voucher").data]
        self.assertIn(a, awaiting)

    def test_cannot_void_after_a_payment_is_recorded(self):
        a, pv = self._approved_voucher(1000)
        pyr = Document.objects.get(ref=a)
        costing.post(site=self.site, cost_head=self.head, state="PAID",
                     source="PYR", amount=Decimal("1000"), document=pyr,
                     actor=self.finance)
        self.voucher_action(pv, "request-void", self.finance, reason="too late")
        r = self.voucher_action(pv, "void", self.signatory)
        self.assertEqual(r.status_code, 400)
        self.assertIn("payment", r.data["detail"].lower())
