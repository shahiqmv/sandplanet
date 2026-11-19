"""M6d — Payment Voucher: Finance batches Director-approved requisitions,
a signatory approves the batch or queries individual lines (§6C.2)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import costing
from .models import (CostHead, CostPosting, Document, Notification, Site,
                     SitePmHistory, User)
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
        # two requests to the same payee share one voucher (one payee per
        # voucher, owner 2026-11-19)
        a = self.director_approved_pyr(amount=3000, payee="A")
        b = self.director_approved_pyr(amount=1500, payee="A")
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

    def test_voucher_picture(self):
        """The voucher as a picture for the payments group (owner
        2026-11-16): Finance/signatory only; a PNG, or a 503 where the PDF
        engine is missing — never a 500."""
        a = self.director_approved_pyr(amount=3000, payee="A")
        pv = self.create_voucher([a]).data["ref"]
        self.client.force_authenticate(self.sa)
        self.assertEqual(
            self.client.get(f"/api/v1/payment-vouchers/{pv}/png").status_code,
            403)
        self.client.force_authenticate(self.finance)
        r = self.client.get(f"/api/v1/payment-vouchers/{pv}/png")
        self.assertIn(r.status_code, (200, 503))
        if r.status_code == 200:
            self.assertEqual(r["Content-Type"], "image/png")
            self.assertTrue(r.content.startswith(b"\x89PNG"))
        self.assertEqual(
            self.client.get("/api/v1/payment-vouchers/PV-NOPE/png").status_code,
            404)


class VoucherQueryTests(VoucherBase):
    def test_queried_line_returns_source_others_commit(self):
        a = self.director_approved_pyr(amount=3000, payee="A")
        b = self.director_approved_pyr(amount=1500, payee="A")
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

    def test_voiding_a_paid_voucher_reverses_the_payment(self):
        """It used to refuse — "reverse the payment before voiding it" —
        with nothing anywhere to reverse one (owner 2026-10-27). The Paid
        rows come off, the paid marks clear, the request is back in
        Finance's queue and goes on a new voucher."""
        from . import vouchers
        a, pv = self._approved_voucher(1000)
        r = self.act(a, "pay", self.finance, amount_paid="1000",
                     payment_ref="TT-77")
        self.assertEqual(r.status_code, 200, r.data)
        pyr = Document.objects.get(ref=a)
        self.assertEqual(pyr.status, "PAID")
        self.assertEqual(costing.document_net(pyr, "PAID"), Decimal("1000"))
        self.voucher_action(pv, "request-void", self.finance,
                            reason="paid to the wrong account")
        r = self.voucher_action(pv, "void", self.signatory)
        self.assertEqual(r.status_code, 200, r.data)
        pyr.refresh_from_db()
        pyr.payment_request.refresh_from_db()
        self.assertEqual(pyr.status, "DIRECTOR_APPROVED")
        self.assertIsNone(pyr.payment_request.amount_paid)
        self.assertEqual(pyr.payment_request.payment_ref, "")
        for state in ("PAID", "INCURRED", "COMMITTED"):
            self.assertEqual(costing.document_net(pyr, state), Decimal("0"),
                             state)
        self.assertIn(pyr, vouchers.awaiting_voucher())
        self.assertEqual(self.create_voucher([a]).status_code, 201)
        # the Director hears of it
        self.assertTrue(Notification.objects.filter(
            recipient=self.director, title__contains="payment reversed").exists())

    def test_a_payment_with_effects_beyond_the_ledger_is_refused_by_name(self):
        a, pv = self._approved_voucher(1000)
        pyr = Document.objects.get(ref=a)
        pyr.payment_request.payment_type = "PERMIT_RENEWAL"
        pyr.payment_request.save(update_fields=["payment_type"])
        costing.post(site=self.site, cost_head=self.head, state="PAID",
                     source="PYR", amount=Decimal("1000"), document=pyr,
                     actor=self.finance)
        self.voucher_action(pv, "request-void", self.finance, reason="x")
        r = self.voucher_action(pv, "void", self.signatory)
        self.assertEqual(r.status_code, 400)
        self.assertIn("permit renewal", r.data["detail"])
        self.assertFalse(Document.objects.get(ref=pv).is_void)


class VoucherListPerfTests(VoucherBase):
    """Paginated/searchable list + trimmed dashboard + payables page endpoint
    (owner 2026-08-08)."""

    def test_list_is_paginated_and_searchable(self):
        a = self.create_voucher([self.director_approved_pyr(payee="A")]).data
        self.create_voucher([self.director_approved_pyr(payee="B")])
        self.client.force_authenticate(self.finance)
        # object shape with total + has_more
        r = self.client.get("/api/v1/payment-vouchers?limit=1")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["total"], 2)
        self.assertEqual(len(r.data["vouchers"]), 1)
        self.assertTrue(r.data["has_more"])
        # page 2
        r2 = self.client.get("/api/v1/payment-vouchers?limit=1&offset=1")
        self.assertEqual(len(r2.data["vouchers"]), 1)
        self.assertFalse(r2.data["has_more"])
        # ref search narrows to one
        # every page carries the per-state counts the tabs wear
        self.assertEqual(set(r.data["counts"]), {"DRAFT", "SUBMITTED",
                                                 "CHECKED", "APPROVED"})
        self.assertEqual(sum(r.data["counts"].values()), r.data["total"])
        r3 = self.client.get(f"/api/v1/payment-vouchers?q={a['ref']}")
        self.assertEqual(r3.data["total"], 1)
        self.assertEqual(r3.data["vouchers"][0]["ref"], a["ref"])

    def test_search_by_what_the_voucher_pays(self):
        # find the PV by the PYR on it, or its payee (owner 2026-10-31)
        pyr = self.director_approved_pyr(payee="Ocean Traders")
        a = self.create_voucher([pyr]).data["ref"]
        self.create_voucher([self.director_approved_pyr(payee="Someone")])
        self.client.force_authenticate(self.finance)
        for q in (pyr, pyr.lower(), "ocean trad"):
            r = self.client.get(f"/api/v1/payment-vouchers?q={q}")
            self.assertEqual([v["ref"] for v in r.data["vouchers"]], [a], q)
            self.assertEqual(r.data["total"], 1)

    def test_dashboard_returns_to_pay_count(self):
        pv = self.create_voucher(
            [self.director_approved_pyr(payee="C")]).data["ref"]
        self.voucher_action(pv, "submit", self.finance)
        self.voucher_action(pv, "approve", self.signatory)
        self.client.force_authenticate(self.finance)
        d = self.client.get("/api/v1/finance/dashboard").data
        self.assertIn("to_pay_count", d["vouchers"])
        self.assertIsInstance(d["vouchers"]["to_pay"], list)
        self.assertGreaterEqual(d["vouchers"]["to_pay_count"], 1)

    def test_payables_endpoint_shape_and_auth(self):
        self.client.force_authenticate(self.finance)
        r = self.client.get("/api/v1/finance/payables")
        self.assertEqual(r.status_code, 200)
        for k in ("payables", "total", "count", "overdue"):
            self.assertIn(k, r.data)
        # the signatory READS payables — they authorise what gets paid off it
        # (owner 2026-08-16) — but still cannot build a voucher
        self.client.force_authenticate(self.signatory)
        self.assertEqual(
            self.client.get("/api/v1/finance/payables").status_code, 200)
        self.assertEqual(
            self.client.post("/api/v1/payment-vouchers",
                             {"source_refs": []}, format="json").status_code,
            403)


class VoucherBatchApproveTests(VoucherBase):
    """The signatory ticks several vouchers and approves them together
    (owner 2026-09-30). Every line is approved; a voucher that needs a line
    queried is still opened and decided on its own."""

    def _submitted(self, amount, payee):
        src = self.director_approved_pyr(amount=amount, payee=payee)
        r = self.create_voucher([src])
        self.voucher_action(r.data["ref"], "submit", self.finance)
        return r.data["ref"], src

    def _batch(self, user, items):
        self.client.force_authenticate(user)
        return self.client.post("/api/v1/payment-vouchers/batch-approve",
                                {"items": items}, format="json")

    def test_signatory_approves_several_at_once(self):
        (a, sa), (b, sb) = self._submitted(3000, "A"), self._submitted(1500, "B")
        r = self._batch(self.signatory, [
            {"ref": a, "total": "3000.00", "lines": 1},
            {"ref": b, "total": "1500", "lines": 1}])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["approved"], r.data["failed"]), ([a, b], []))
        for pv, src, amt in ((a, sa, "3000"), (b, sb, "1500")):
            self.assertEqual(Document.objects.get(ref=pv).status, "APPROVED")
            doc = Document.objects.get(ref=src)
            self.assertEqual(doc.status, "AUTHORISED")
            self.assertEqual(costing.document_net(doc, state="COMMITTED"),
                             Decimal(amt))
        # each voucher carries its own approval record
        self.assertEqual(Document.objects.get(ref=a).approvals.filter(
            action="APPROVE", actor=self.signatory).count(), 1)

    def test_only_a_signatory(self):
        a, _ = self._submitted(3000, "A")
        r = self._batch(self.finance, [{"ref": a, "total": "3000", "lines": 1}])
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Document.objects.get(ref=a).status, "CHECKED")

    def test_one_that_cannot_go_does_not_hold_the_rest(self):
        (a, _), (b, _) = self._submitted(3000, "A"), self._submitted(1500, "B")
        self.voucher_action(a, "approve", self.signatory)   # already done
        r = self._batch(self.signatory, [
            {"ref": a, "total": "3000", "lines": 1},
            {"ref": b, "total": "1500", "lines": 1},
            {"ref": "PV-999", "total": "1", "lines": 1}])
        self.assertEqual(r.data["approved"], [b])
        self.assertEqual([f["ref"] for f in r.data["failed"]], [a, "PV-999"])

    def test_a_voucher_that_changed_since_the_list_loaded_is_refused(self):
        a, _ = self._submitted(3000, "A")
        r = self._batch(self.signatory, [{"ref": a, "total": "2500", "lines": 1}])
        self.assertEqual(r.data["approved"], [])
        self.assertIn("Changed since", r.data["failed"][0]["detail"])
        self.assertEqual(Document.objects.get(ref=a).status, "CHECKED")

    def test_empty_and_oversized_batches(self):
        self.assertEqual(self._batch(self.signatory, []).status_code, 400)
        self.assertEqual(self._batch(self.signatory, [
            {"ref": f"PV-{i}", "total": "1", "lines": 1}
            for i in range(101)]).status_code, 400)


class VoidReversesOtherPaymentsTests(VoucherBase):
    """The same for an overseas TT and a payable (owner 2026-10-27)."""

    def _pv(self, status="APPROVED"):
        return Document.objects.create(
            doc_type="PV", ref=f"PV-T{Document.objects.count()}", status=status,
            site=self.site, doc_date=date.today(), created_by=self.finance)

    def test_a_paid_overseas_tt_goes_back_to_due(self):
        from . import vouchers
        from .models import (ImportOrder, ImportPaymentMilestone,
                             PaymentVoucherLine, Supplier)
        ipr = Document.objects.create(
            doc_type="IPR", ref="IPR-VD-001", status="AUTHORISED",
            site=self.site, doc_date=date.today(), created_by=self.finance)
        order = ImportOrder.objects.create(
            document=ipr, supplier=Supplier.objects.create(name="Overseas"),
            exchange_rate=Decimal("15.42"))
        m = ImportPaymentMilestone.objects.create(
            order=order, seq=1, label="Advance", trigger="ADVANCE",
            percent=Decimal("100"), status="PAID", tt_ref="TT1",
            mvr_paid=Decimal("1542"))
        pv = self._pv()
        PaymentVoucherLine.objects.create(voucher=pv, source_milestone=m,
                                          amount=Decimal("100"),
                                          currency="USD", status="APPROVED")
        costing.post(site=self.site, cost_head=self.head, state="PAID",
                     source="IPR", amount=Decimal("1542"), document=ipr,
                     ipr_milestone=m, actor=self.finance)
        self.assertIsNone(vouchers.void_voucher(pv, self.signatory, "wrong"))
        m.refresh_from_db()
        self.assertEqual((m.status, m.tt_ref, m.mvr_paid), ("DUE", "", None))
        self.assertEqual(costing.document_net(ipr, "PAID"), Decimal("0"))

    def test_a_settled_payable_is_outstanding_again(self):
        from . import vouchers
        from .models import Payable, PaymentVoucherLine
        svc = Document.objects.create(
            doc_type="SVC", ref="SVC-VD-001", status="AUTHORISED",
            site=self.site, doc_date=date.today(), created_by=self.finance)
        p = Payable.objects.create(document=svc, site=self.site,
                                   vendor="Atoll Civil", amount=Decimal("800"))
        pv = self._pv()
        PaymentVoucherLine.objects.create(voucher=pv, source_payable=p,
                                          amount=Decimal("800"),
                                          status="APPROVED")
        self.assertIsNone(vouchers.settle_payable(p, self.finance, "TT9"))
        svc.refresh_from_db()
        self.assertEqual(svc.status, "PAID")
        self.assertIsNone(vouchers.void_voucher(pv, self.signatory, "dup"))
        p.refresh_from_db()
        svc.refresh_from_db()
        self.assertEqual((p.status, p.settled_ref, svc.status),
                         ("OUTSTANDING", "", "AUTHORISED"))
        self.assertEqual(costing.document_net(svc, "PAID"), Decimal("0"))
        self.assertIn(p, list(vouchers.awaiting_payables()))


class AccountantCheckTests(VoucherBase):
    """The accountant's check between the accounts officer and the signatory
    (owner 2026-11-16). The layer is on while someone holds the access."""

    def setUp(self):
        super().setUp()
        self.accountant = make_user("acct", User.Role.FINANCE)
        self.accountant.extra_roles = ["ACCOUNTANT"]
        self.accountant.save()

    def submitted(self):
        a = self.director_approved_pyr(amount=3000, payee="A")
        pv = self.create_voucher([a]).data["ref"]
        self.voucher_action(pv, "submit", self.finance)
        return pv

    def status(self, ref):
        return Document.objects.get(ref=ref).status

    def test_submission_waits_on_the_accountant(self):
        pv = self.submitted()
        self.assertEqual(self.status(pv), "SUBMITTED")
        # the signatory cannot jump the queue
        r = self.voucher_action(pv, "approve", self.signatory)
        self.assertEqual(r.status_code, 400)
        self.assertIn("accountant", r.data["detail"])
        # the accountant checks it on, with a stamp of their own
        r = self.voucher_action(pv, "check", self.accountant, note="ok")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.status(pv), "CHECKED")
        doc = Document.objects.get(ref=pv)
        self.assertTrue(doc.approvals.filter(action="CHECK",
                                             actor=self.accountant).exists())
        # a second check is refused; the signatory now approves
        self.assertEqual(
            self.voucher_action(pv, "check", self.accountant).status_code, 400)
        r = self.voucher_action(pv, "approve", self.signatory)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.status(pv), "APPROVED")

    def test_only_the_accountant_checks_and_never_their_own(self):
        pv = self.submitted()
        # plain Finance and the signatory may not check
        self.assertEqual(
            self.voucher_action(pv, "check", self.finance).status_code, 400)
        self.assertEqual(
            self.voucher_action(pv, "check", self.signatory).status_code, 400)
        # four eyes on a manual check: a voucher the accountant built but a
        # colleague submitted is not theirs to check
        a = self.director_approved_pyr(amount=500, payee="B")
        own = self.create_voucher([a], user=self.accountant).data["ref"]
        self.voucher_action(own, "submit", self.finance)
        self.assertEqual(self.status(own), "SUBMITTED")
        r = self.voucher_action(own, "check", self.accountant)
        self.assertEqual(r.status_code, 400)
        self.assertIn("someone other", r.data["detail"])

    def test_the_accountants_own_submission_is_checked_on_submission(self):
        a = self.director_approved_pyr(amount=700, payee="C")
        pv = self.create_voucher([a], user=self.accountant).data["ref"]
        r = self.voucher_action(pv, "submit", self.accountant)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.status(pv), "CHECKED")
        doc = Document.objects.get(ref=pv)
        self.assertEqual(
            list(doc.approvals.order_by("id").values_list("action", flat=True)),
            ["SUBMIT", "CHECK"])
        self.assertTrue(doc.approvals.filter(action="CHECK",
                                             actor=self.accountant).exists())
        # straight into the signatory's hands
        r = self.voucher_action(pv, "approve", self.signatory)
        self.assertEqual(r.status_code, 200, r.data)

    def test_return_to_preparer_needs_a_note(self):
        pv = self.submitted()
        r = self.voucher_action(pv, "return", self.accountant, note="  ")
        self.assertEqual(r.status_code, 400)
        r = self.voucher_action(pv, "return", self.accountant,
                                note="Wrong payee on line 1")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.status(pv), "DRAFT")
        doc = Document.objects.get(ref=pv)
        self.assertEqual(doc.approvals.filter(action="RETURN").count(), 1)
        # the preparer hears why
        from .models import Notification
        self.assertTrue(Notification.objects.filter(
            recipient=self.finance, doc_ref=pv,
            title__contains="returned").exists())
        # and can submit again
        self.assertEqual(
            self.voucher_action(pv, "submit", self.finance).status_code, 200)
        self.assertEqual(self.status(pv), "SUBMITTED")

    def test_queue_and_counts_follow_the_layer(self):
        pv = self.submitted()
        self.client.force_authenticate(self.accountant)
        r = self.client.get("/api/v1/payment-vouchers?limit=5")
        self.assertTrue(r.data["check_required"])
        self.assertEqual(r.data["counts"]["SUBMITTED"], 1)
        self.client.force_authenticate(self.signatory)
        groups = self.client.get("/api/v1/approvals/pending").data["groups"]
        titles = {g["title"]: [i["ref"] for i in g["items"]] for g in groups}
        self.assertNotIn(pv, titles.get("To approve — payment vouchers", []))
        self.client.force_authenticate(self.accountant)
        groups = self.client.get("/api/v1/approvals/pending").data["groups"]
        titles = {g["title"]: [i["ref"] for i in g["items"]] for g in groups}
        self.assertIn(pv, titles.get("To check — payment vouchers", []))

    def test_without_an_accountant_submission_reaches_the_signatory(self):
        self.accountant.is_active = False
        self.accountant.save()
        pv = self.submitted()
        self.assertEqual(self.status(pv), "CHECKED")
        self.client.force_authenticate(self.finance)
        self.assertFalse(
            self.client.get("/api/v1/payment-vouchers?limit=5")
            .data["check_required"])
        r = self.voucher_action(pv, "approve", self.signatory)
        self.assertEqual(r.status_code, 200, r.data)

    def test_accountant_leaving_does_not_strand_a_submitted_voucher(self):
        pv = self.submitted()
        self.assertEqual(self.status(pv), "SUBMITTED")
        self.accountant.is_active = False
        self.accountant.save()
        r = self.voucher_action(pv, "approve", self.signatory)
        self.assertEqual(r.status_code, 200, r.data)


class VoucherPdfLinesTests(TestCase):
    """The voucher as it prints (owner 2026-11-19): one line per PR supplier,
    the payee in the header, the sum in words."""

    def context(self, info):
        from unittest import mock

        from .views_vouchers import _pv_pdf_context
        pv = mock.Mock(approvals=mock.Mock(select_related=lambda *a: []),
                       debit_account=None, created_by=None)
        with mock.patch("core.views_vouchers._voucher_info",
                        return_value=info):
            return _pv_pdf_context(pv)

    def info(self, amount, rows):
        return {"settled": False, "currency": "MVR", "lines": [{
            "ref": "PR-457", "site_code": "SFR", "status": "APPROVED",
            "amount": Decimal(amount), "payee": "A, B",
            "purpose": "Procurement", "cost_head": "Materials",
            "doc_type": "PR", "paid": False, "vendor_rows": rows}]}

    def row(self, vendor, gross, gst="0", advance=False, ref=""):
        return {"line_id": None, "vendor": vendor, "gross": Decimal(gross),
                "gst_amount": Decimal(gst), "is_advance": advance,
                "payment_ref": ref}

    def test_one_payee_in_the_header_with_the_sum_in_words(self):
        c = self.context(self.info("24408.00",
                                   [self.row("MANAS HARDWARE", "24408.00")]))
        self.assertEqual(c["payee"], "MANAS HARDWARE")
        self.assertEqual(c["total_words"],
                         "Rufiyaa Twenty-Four Thousand Four Hundred Eight "
                         "only")
        self.assertNotIn("prepared_by", c)

    def test_an_older_voucher_with_two_payees_names_them_per_line(self):
        c = self.context(self.info("1100.00", [
            self.row("A", "1000.00", ref="TT-1"),
            self.row("B", "100.00", gst="6.00", advance=True)]))
        self.assertEqual([(r["no"], r["amount"], r["payment"])
                          for r in c["lines"]],
                         [(1, "1,000.00", "TT-1"), (2, "100.00", "")])
        self.assertEqual(c["payee"], "2 payees — see each line")
        self.assertTrue(c["lines"][0]["description"].startswith("A — "))
        self.assertIn("advance", c["lines"][1]["note"])
        self.assertIn("GST 6.00", c["lines"][1]["note"])
        self.assertEqual(c["total"], "1,100.00")

    def test_amount_in_words(self):
        from .views_vouchers import amount_in_words
        self.assertEqual(amount_in_words(Decimal("28470.38"), "MVR"),
                         "Rufiyaa Twenty-Eight Thousand Four Hundred Seventy "
                         "and Laari 38 only")
        self.assertEqual(amount_in_words(Decimal("920.59"), "USD"),
                         "US Dollars Nine Hundred Twenty and Cents 59 only")


class OnePayeePerVoucherTests(VoucherBase):
    """Finance ticks what to pay; a voucher is raised for each payee (owner
    2026-11-19)."""

    def pr_with_suppliers(self, *vendors):
        """A PR at the stage Finance vouchers it, one cash row per vendor."""
        from .models import DocumentLine, DocumentRevision
        pr = Document.objects.create(
            doc_type="PR", ref=f"PR-T{Document.objects.count() + 1}",
            site=self.site, doc_date=date.today(), status="APPROVED",
            created_by=self.director)
        rev = DocumentRevision.objects.create(document=pr, rev_label="R0",
                                              payload={}, is_current=True,
                                              created_by=self.director)
        pr.current_revision = rev
        pr.save(update_fields=["current_revision"])
        for i, (vendor, amount) in enumerate(vendors, 1):
            DocumentLine.objects.create(revision=rev, line_no=i,
                                        vendor=vendor, amount_cash=amount,
                                        free_text_desc=f"goods {i}")
        return pr.ref

    def test_two_payees_get_two_vouchers(self):
        a = self.director_approved_pyr(amount=3000, payee="Boat Co")
        b = self.director_approved_pyr(amount=1500, payee="Fuel Co")
        c = self.director_approved_pyr(amount=500, payee="BOAT CO PVT LTD")
        r = self.create_voucher([a, b, c])
        self.assertEqual(r.status_code, 201, r.data)
        made = {x["payee"]: x for x in r.data["created"]}
        self.assertEqual(len(r.data["created"]), 2)
        boat = Document.objects.get(ref=next(
            x["ref"] for x in r.data["created"] if x["payee"] == "Boat Co"))
        self.assertEqual(sorted(ln.source_document.ref
                                for ln in boat.voucher_lines.all()),
                         sorted([a, c]))
        self.assertIn("Fuel Co", made)

    def test_a_pr_with_three_suppliers_makes_three_vouchers(self):
        pr = self.pr_with_suppliers(("STO", 191.94), ("Sonee Hardware", 3870.44),
                                    ("Manas Hardware", 24408))
        r = self.create_voucher([pr])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data["created"]), 3)
        totals = sorted(Decimal(str(x["total"])) for x in r.data["created"])
        self.assertEqual(totals, [Decimal("191.94"), Decimal("3870.44"),
                                  Decimal("24408.00")])
        # every supplier is now on a voucher: the PR cannot be vouchered again
        again = self.create_voucher([pr])
        self.assertEqual(again.status_code, 400)

    def test_all_or_nothing(self):
        a = self.director_approved_pyr(amount=3000, payee="Boat Co")
        b = self.director_approved_pyr(amount=1500, payee="Fuel Co")
        self.create_voucher([b])                  # b is now on a voucher
        before = Document.objects.filter(doc_type="PV").count()
        r = self.create_voucher([a, b])
        self.assertEqual(r.status_code, 400)
        self.assertIn("already on a voucher", r.data["detail"])
        self.assertEqual(Document.objects.filter(doc_type="PV").count(), before)
