"""Putting a head-office payment where it belongs (owner 2026-11-10): a
request becomes a currency exchange, a tax payment or a prior-period
creditor (pool postings the cost reports ignore), moves to another head or
site, or is applied to the payables it paid."""
from datetime import date
from decimal import Decimal

from . import costing, report_cost
from .models import (CostHead, CostPosting, Document, DocumentLine,
                     DocumentRevision, Payable, Site)
from .tests_vouchers import VoucherBase


class ReclassifyBase(VoucherBase):
    def setUp(self):
        super().setUp()
        self.mle = Site.objects.create(code="MLE", name="Head Office",
                                       status=Site.Status.ACTIVE,
                                       is_head_office=True)
        self.other = CostHead.objects.get(name="Materials")

    def paid_ho_pyr(self, amount=1000, payee="Global Exchange",
                    purpose="Dollar exchange", head=None, **extra):
        """A head-office request raised by Finance, authorised on a voucher
        and paid."""
        self.client.force_authenticate(self.finance)
        body = {"doc_type": "PYR", "site_id": self.mle.id, "payload": {},
                "cost_head_id": (head or self.head).id, "payee": payee,
                "payment_type": "DIRECT", "payment_method": "BANK",
                "amount_requested": amount, "purpose": purpose,
                "has_supporting_doc": True}
        body.update(extra)
        r = self.client.post("/api/v1/documents", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        ref = r.data["ref"]
        self.act(ref, "submit", self.finance)
        self.act(ref, "approve", self.director)
        pv = self.create_voucher([ref]).data["ref"]
        self.voucher_action(pv, "submit", self.finance)
        self.voucher_action(pv, "approve", self.signatory)
        r = self.act(ref, "pay", self.finance, payment_ref="CHQ-1",
                     amount_paid=amount)
        self.assertEqual(r.status_code, 200, r.data)
        return Document.objects.get(ref=ref)

    def credit_order(self, vendor="Sonee Hardware Pvt Ltd", amount=600,
                     currency="MVR"):
        """A signed order at the site with its credit payable outstanding,
        the cost already committed there."""
        n = Document.objects.filter(doc_type="PR").count() + 1
        pr = Document.objects.create(
            doc_type="PR", ref=f"PR-{n:03d}", status="AUTHORISED",
            site=self.site, doc_date=date.today(), created_by=self.finance)
        rev = DocumentRevision.objects.create(document=pr, rev_label="R0",
                                              payload={},
                                              created_by=self.finance)
        pr.current_revision = rev
        pr.save(update_fields=["current_revision"])
        line = DocumentLine.objects.create(
            revision=rev, line_no=1, free_text_desc="Cement", unit="bag",
            qty_required=10, vendor=vendor, amount_credit=amount,
            cost_head=self.other, purchase_type="CREDIT", currency=currency,
            po_ref=f"PO-{n:03d}")
        costing.post(site=self.site, cost_head=self.other, state="COMMITTED",
                     source="PR", amount=amount, currency=currency,
                     document=pr, document_line=line, actor=self.signatory)
        p = Payable.objects.create(document=pr, document_line=line,
                                   site=self.site, vendor=vendor,
                                   amount=amount, currency=currency,
                                   due_date=date.today())
        return pr, line, p

    def live(self, doc, state):
        return costing.document_net(doc, state)

    def site_cost(self, site):
        """MVR recognised cost at a site, the way the cost report counts it
        (it reports in USD; the ledger is checked in its own currency)."""
        from django.db.models import Sum
        qs = report_cost.site_postings([site.id]).filter(
            report_cost.recognised_q())
        return qs.aggregate(t=Sum("amount"))["t"] or Decimal("0")


class NonCostRequestTests(ReclassifyBase):
    def test_head_office_raises_a_currency_exchange_that_is_no_cost(self):
        doc = self.paid_ho_pyr(booking="CURRENCY_EXCHANGE")
        pr = doc.payment_request
        self.assertEqual(pr.booking, "CURRENCY_EXCHANGE")
        self.assertEqual(pr.cost_head.code, "CURRENCY_EXCHANGE")
        self.assertTrue(pr.cost_head.is_pool)
        # it posted — the money trail is kept — but as a pool
        rows = CostPosting.objects.filter(document=doc)
        self.assertEqual(rows.count(), 3)      # committed, paid, incurred
        self.assertTrue(all(r.is_stock_pool for r in rows))
        self.assertEqual(self.site_cost(self.mle), Decimal("0"))

    def test_a_site_cannot_raise_one(self):
        self.client.force_authenticate(self.sa)
        r = self.client.post("/api/v1/documents", {
            "doc_type": "PYR", "site_id": self.site.id, "payload": {},
            "cost_head_id": self.head.id, "payee": "Cash Corp",
            "payment_type": "DIRECT", "payment_method": "BANK",
            "amount_requested": 500, "purpose": "Dollar sell",
            "has_supporting_doc": True, "booking": "CURRENCY_EXCHANGE",
        }, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("head office", r.data["detail"].lower())

    def test_the_detail_carries_the_booking(self):
        doc = self.paid_ho_pyr(booking="GST_SETTLEMENT", payee="MIRA",
                               purpose="GST for October")
        self.client.force_authenticate(self.finance)
        r = self.client.get(f"/api/v1/documents/{doc.ref}")
        self.assertEqual(r.data["payment_request"]["booking"],
                         "GST_SETTLEMENT")


class ReclassifyTests(ReclassifyBase):
    def test_a_paid_cost_becomes_a_currency_exchange(self):
        doc = self.paid_ho_pyr(amount=1000)
        self.assertEqual(self.site_cost(self.mle), Decimal("1000"))
        self.client.force_authenticate(self.finance)
        r = self.client.post(f"/api/v1/documents/{doc.ref}/reclassify",
                             {"booking": "CURRENCY_EXCHANGE",
                              "reason": "Dollars bought for salaries"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        doc.refresh_from_db()
        self.assertEqual(doc.payment_request.booking, "CURRENCY_EXCHANGE")
        # the originals are reversed, the pool rows carry the same money
        self.assertEqual(self.site_cost(self.mle), Decimal("0"))
        self.assertEqual(self.live(doc, "PAID"), Decimal("1000"))
        pool = CostPosting.objects.filter(document=doc, is_stock_pool=True,
                                          reversal_of__isnull=True)
        self.assertEqual(pool.count(), 3)
        self.assertTrue(all(p.cost_head.code == "CURRENCY_EXCHANGE"
                            for p in pool))
        reversals = CostPosting.objects.filter(document=doc,
                                               reversal_of__isnull=False)
        self.assertEqual(reversals.count(), 3)
        from .models import AuditLog
        a = AuditLog.objects.filter(event="PYR_RECLASSIFIED").last()
        self.assertEqual(a.detail["to"]["booking"], "CURRENCY_EXCHANGE")
        self.assertEqual(a.detail["reason"], "Dollars bought for salaries")

    def test_a_cost_moves_to_another_site_and_head(self):
        doc = self.paid_ho_pyr(amount=800, payee="Faruk",
                               purpose="Conrad chair covers")
        self.client.force_authenticate(self.finance)
        r = self.client.post(f"/api/v1/documents/{doc.ref}/reclassify",
                             {"site_id": self.site.id,
                              "cost_head_id": self.other.id,
                              "reason": "Raised without a project"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        doc.refresh_from_db()
        self.assertEqual(doc.site, self.site)
        self.assertEqual(doc.payment_request.cost_head, self.other)
        self.assertEqual(self.site_cost(self.mle), Decimal("0"))
        self.assertEqual(self.site_cost(self.site), Decimal("800"))
        # the ref is history: it keeps the code it was raised under
        self.assertTrue(doc.ref.startswith("PYR-MLE-"))

    def test_a_non_cost_kind_stays_at_head_office(self):
        doc = self.paid_ho_pyr()
        self.client.force_authenticate(self.finance)
        r = self.client.post(f"/api/v1/documents/{doc.ref}/reclassify",
                             {"booking": "GST_SETTLEMENT",
                              "site_id": self.site.id, "reason": "x"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("head office", r.data["detail"].lower())

    def test_reason_and_role_are_required(self):
        doc = self.paid_ho_pyr()
        self.client.force_authenticate(self.finance)
        r = self.client.post(f"/api/v1/documents/{doc.ref}/reclassify",
                             {"booking": "GST_SETTLEMENT"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.client.force_authenticate(self.signatory)
        r = self.client.post(f"/api/v1/documents/{doc.ref}/reclassify",
                             {"booking": "GST_SETTLEMENT", "reason": "x"},
                             format="json")
        self.assertEqual(r.status_code, 403)

    def test_a_request_not_yet_authorised_is_refused(self):
        ref = self.director_approved_pyr()
        self.client.force_authenticate(self.finance)
        r = self.client.post(f"/api/v1/documents/{ref}/reclassify",
                             {"cost_head_id": self.other.id, "reason": "x"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("authorised", r.data["detail"])

    def test_the_backlog_suggests_what_each_request_is(self):
        self.paid_ho_pyr(payee="Cash Corp", purpose="Dollar Exchange - 50k")
        self.paid_ho_pyr(payee="MIRA", purpose="GST Payment - Oct")
        self.credit_order(vendor="Sonee Hardware")
        self.paid_ho_pyr(payee="SONEE HARDWARE PVT LTD",
                         purpose="Outstanding payment as per SOA")
        self.paid_ho_pyr(payee="Manas", purpose="Balance payment - 2025")
        self.paid_ho_pyr(payee="White Diamond", purpose="Office rent Sep")
        self.client.force_authenticate(self.finance)
        r = self.client.get("/api/v1/finance/pyr-backlog")
        self.assertEqual(r.status_code, 200)
        by = {x["payee"]: x for x in r.data["rows"]}
        self.assertEqual(by["Cash Corp"]["suggestion"], "CURRENCY_EXCHANGE")
        self.assertEqual(by["MIRA"]["suggestion"], "GST_SETTLEMENT")
        self.assertEqual(by["SONEE HARDWARE PVT LTD"]["suggestion"],
                         "PAYABLES")
        self.assertEqual(by["SONEE HARDWARE PVT LTD"]["open_payables"], 1)
        self.assertEqual(by["Manas"]["suggestion"], "PRIOR_PERIOD")
        self.assertEqual(by["White Diamond"]["suggestion"], "")
        # a batch of the same kind goes in one go
        r = self.client.post("/api/v1/finance/pyr-backlog", {
            "refs": [by["Cash Corp"]["ref"]], "booking": "CURRENCY_EXCHANGE",
            "reason": "Backlog cleanup"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["done"], 1)
        rows = self.client.get("/api/v1/finance/pyr-backlog").data["rows"]
        self.assertNotIn("Cash Corp", [x["payee"] for x in rows])


class ApplyToPayablesTests(ReclassifyBase):
    def test_a_cheque_settles_the_orders_payables_at_the_site(self):
        pr, line, p1 = self.credit_order(amount=600)
        pr2, line2, p2 = self.credit_order(amount=400)
        doc = self.paid_ho_pyr(amount=1000, payee="Sonee Hardware",
                               purpose="Due cheque payment (Chq# 517)",
                               head=self.other)
        self.assertEqual(self.site_cost(self.mle), Decimal("1000"))
        self.client.force_authenticate(self.finance)
        r = self.client.get(f"/api/v1/documents/{doc.ref}/apply-to-payables")
        self.assertEqual(r.status_code, 200)
        ids = [x["payable_id"] for x in r.data["payables"]]
        self.assertEqual(set(ids), {p1.id, p2.id})
        self.assertTrue(all(x["vendor_match"] for x in r.data["payables"]))
        r = self.client.post(f"/api/v1/documents/{doc.ref}/apply-to-payables",
                             {"payable_ids": ids, "reason": "Per statement"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["difference"], "0.00")
        # the request's own cost is gone; the orders are paid at the site
        self.assertEqual(self.site_cost(self.mle), Decimal("0"))
        self.assertEqual(self.live(doc, "PAID"), Decimal("0"))
        doc.refresh_from_db()
        self.assertEqual(doc.payment_request.booking, "PAYABLE_SETTLEMENT")
        for p in (p1, p2):
            p.refresh_from_db()
            self.assertEqual(p.status, "SETTLED")
            self.assertEqual(p.settled_ref, doc.ref)
            self.assertEqual(p.settled_by_request, doc)
            self.assertEqual(p.settled_on, doc.payment_request.paid_date)
        paid = CostPosting.objects.filter(document=pr, state="PAID")
        self.assertEqual(paid.count(), 1)
        self.assertEqual((paid[0].site, paid[0].cost_head,
                          paid[0].posted_on),
                         (self.site, self.other,
                          doc.payment_request.paid_date))
        # the site's recognised cost is the order's commitment, once
        self.assertEqual(self.site_cost(self.site), Decimal("1000"))
        r = self.client.get(f"/api/v1/documents/{doc.ref}")
        self.assertEqual(len(r.data["payment_request"]["settled_payables"]),
                         2)

    def test_more_than_the_cheque_is_refused(self):
        _, _, p = self.credit_order(amount=1500)
        doc = self.paid_ho_pyr(amount=1000, payee="Sonee Hardware")
        self.client.force_authenticate(self.finance)
        r = self.client.post(f"/api/v1/documents/{doc.ref}/apply-to-payables",
                             {"payable_ids": [p.id], "reason": "x"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("more than", r.data["detail"])
        p.refresh_from_db()
        self.assertEqual(p.status, "OUTSTANDING")
        self.assertEqual(self.site_cost(self.mle), Decimal("1000"))

    def test_a_payable_on_a_voucher_or_in_another_currency_is_not_offered(self):
        _, _, on_pv = self.credit_order(amount=300)
        self.client.force_authenticate(self.finance)
        r = self.client.post("/api/v1/payment-vouchers",
                             {"payable_ids": [on_pv.id]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        _, _, usd = self.credit_order(amount=300, currency="USD")
        _, _, free = self.credit_order(amount=300)
        doc = self.paid_ho_pyr(amount=1000, payee="Sonee Hardware")
        r = self.client.get(f"/api/v1/documents/{doc.ref}/apply-to-payables")
        self.assertEqual([x["payable_id"] for x in r.data["payables"]],
                         [free.id])
        r = self.client.post(f"/api/v1/documents/{doc.ref}/apply-to-payables",
                             {"payable_ids": [usd.id], "reason": "x"},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_once_applied_it_is_not_reclassified_again(self):
        _, _, p = self.credit_order(amount=1000)
        doc = self.paid_ho_pyr(amount=1000, payee="Sonee Hardware")
        self.client.force_authenticate(self.finance)
        self.client.post(f"/api/v1/documents/{doc.ref}/apply-to-payables",
                         {"payable_ids": [p.id], "reason": "x"},
                         format="json")
        r = self.client.post(f"/api/v1/documents/{doc.ref}/reclassify",
                             {"booking": "GST_SETTLEMENT", "reason": "x"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already settles", r.data["detail"])
