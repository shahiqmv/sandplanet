"""An advance to a supplier, and the balance later (owner 2026-10-04).

Two cases, both starting with an advance paid on Finance's voucher:
  * Cash terms — the balance is paid in cash before the goods are collected.
    Not credit: no purchase order, the balance waits on Payables.
  * Credit terms — the balance is owed on the supplier's credit period, on a
    purchase order the Signatory signs.
Either way the cost is counted once, for the whole order.
"""
from decimal import Decimal as D

from . import costing
from .models import CostPosting, Document, Payable
from .tests_quotes import QuoteBase


class AdvanceBase(QuoteBase):
    def pr_with(self, terms, advance, gst=False):
        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        self.as_user(self.purchasing)
        r = self.client.post(f"/api/v1/pr/{pr['ref']}/quotations", {
            "supplier": self.hw.id, "quote_ref": "QT-1",
            "payment_terms": terms, "advance_percent": advance,
            "gst_applicable": gst,
            "lines": [
                {"supplier_desc": "OPC cement 50kg", "unit": "bag",
                 "qty": 150, "rate": 100, "mr_line": mr["lines"][0]["id"],
                 "awarded": True},
                {"supplier_desc": "Rebar 12mm", "unit": "kg", "qty": 500,
                 "rate": 10, "mr_line": mr["lines"][1]["id"],
                 "awarded": True}]}, format="json")
        assert r.status_code == 201, r.data
        self.quote = r.data
        r = self.act(pr["ref"], "submit")
        assert r.status_code == 200, r.data
        self.as_user(self.director)
        r = self.act(pr["ref"], "approve")
        assert r.status_code == 200, r.data
        return Document.objects.get(ref=pr["ref"])

    def row(self, pr):
        return pr.current_revision.lines.get()

    def voucher(self, **body):
        self.as_user(self.finance)
        pv = self.client.post("/api/v1/payment-vouchers", body, format="json")
        assert pv.status_code == 201, pv.data
        ref = pv.data["ref"]
        self.client.post(f"/api/v1/payment-vouchers/{ref}/actions/submit", {},
                         format="json")
        self.as_user(self.signatory)
        r = self.client.post(f"/api/v1/payment-vouchers/{ref}/actions/approve",
                             {}, format="json")
        assert r.status_code == 200, r.data
        return pv.data

    def pay_advance(self, pr):
        self.as_user(self.finance)
        r = self.client.post(f"/api/v1/pr/{pr.ref}/vendor-payment",
                             {"line_id": self.row(pr).id,
                              "payment_ref": "TRF-ADV"}, format="multipart")
        assert r.status_code == 200, r.data
        pr.refresh_from_db()

    def paid(self, pr):
        return costing.document_net(pr, state="PAID")

    def queue(self):
        self.as_user(self.finance)
        return [x["ref"] for x in
                self.client.get("/api/v1/finance/awaiting-voucher").data]


class BalanceBeforeCollectionTests(AdvanceBase):
    def test_the_advance_is_vouchered_and_the_balance_waits_on_payables(self):
        pr = self.pr_with("Cash", "50")
        ln = self.row(pr)
        self.assertEqual((ln.amount_cash, ln.amount_credit,
                          ln.balance_before_collection),
                         (D("10000.00"), D("10000.00"), True))
        self.assertIn("50% advance, balance before collection",
                      ln.payment_terms)
        # not credit: no purchase order is cut
        self.assertFalse(Document.objects.filter(doc_type="PO").exists())
        # Finance vouchers the advance only
        pv = self.voucher(source_refs=[pr.ref])
        self.assertEqual(pv["total"], D("10000.00"))
        # the whole order is committed once, and the balance is owed
        self.assertEqual(costing.document_net(pr, state="COMMITTED"),
                         D("20000"))
        p = Payable.objects.get(document=pr)
        self.assertEqual((p.amount, p.status), (D("10000.00"), "OUTSTANDING"))
        self.assertIn("before collection", p.terms)
        # paying the advance pays half, and leaves the balance owed
        self.pay_advance(pr)
        self.assertEqual(self.paid(pr), D("10000"))
        p.refresh_from_db()
        self.assertEqual(p.status, "OUTSTANDING")
        self.assertEqual(pr.status, "PAID_PO_ISSUED")
        # ready to collect: the balance goes on a second voucher
        pv2 = self.voucher(payable_ids=[p.id])
        self.assertEqual(pv2["total"], D("10000.00"))
        self.as_user(self.finance)
        r = self.client.post(
            f"/api/v1/payment-vouchers/{pv2['ref']}/actions/settle-payable",
            {"payable_id": p.id, "payment_ref": "TRF-BAL"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        p.refresh_from_db()
        self.assertEqual(p.status, "SETTLED")
        self.assertEqual(self.paid(pr), D("20000"))
        self.assertEqual(costing.document_net(pr, state="COMMITTED"),
                         D("20000"))

    def test_gst_is_shared_between_the_advance_and_the_balance(self):
        pr = self.pr_with("Cash", "25", gst=True)
        ln = self.row(pr)
        self.assertEqual((ln.amount_cash, ln.amount_credit, ln.gst_amount),
                         (D("5000.00"), D("15000.00"), D("1600.00")))
        pv = self.voucher(source_refs=[pr.ref])
        self.assertEqual(pv["total"], D("5400.00"))
        self.assertEqual(Payable.objects.get(document=pr).amount,
                         D("16200.00"))
        gst = sum(c.amount for c in CostPosting.objects.filter(
            document=pr, state="COMMITTED", is_stock_pool=True))
        self.assertEqual(gst, D("1600.00"))

    def test_the_advance_is_changed_on_the_quotation(self):
        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        q = self.add_quote(pr["ref"], self.hw, [
            {"supplier_desc": "OPC cement", "unit": "bag", "qty": 100,
             "rate": 100, "mr_line": mr["lines"][0]["id"], "awarded": True}],
            terms="Cash")
        url = f"/api/v1/quotations/{q['id']}"
        self.assertEqual(self.client.patch(
            url, {"advance_percent": "120"}, format="json").status_code, 400)
        r = self.client.patch(url, {"advance_percent": "30"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["terms_text"],
                         "Cash — 30% advance, balance before collection")
        ln = Document.objects.get(ref=pr["ref"]).current_revision.lines.get()
        self.assertEqual((ln.amount_cash, ln.amount_credit),
                         (D("3000.00"), D("7000.00")))
        # and taken off again
        self.client.patch(url, {"advance_percent": ""}, format="json")
        ln.refresh_from_db()
        self.assertEqual((ln.amount_cash, ln.amount_credit,
                          ln.balance_before_collection),
                         (D("10000.00"), None, False))


class BalanceOnCreditTests(AdvanceBase):
    def test_the_advance_is_cash_and_the_balance_is_on_the_order(self):
        pr = self.pr_with("Credit", "40")
        ln = self.row(pr)
        self.assertEqual((ln.amount_cash, ln.amount_credit,
                          ln.balance_before_collection),
                         (D("8000.00"), D("12000.00"), False))
        po = Document.objects.get(doc_type="PO")
        self.assertEqual(po.status, "SUBMITTED")
        self.assertIn("40% advance, balance on credit",
                      po.current_revision.payload["payment_terms"])
        # the order is for the whole purchase
        self.assertEqual(sum(x.amount for x in po.current_revision.lines.all()),
                         D("20000.00"))
        # The Signatory signs the order BEFORE Finance has paid the advance:
        # the PR must stay with Finance, not close on the order alone.
        self.as_user(self.signatory)
        self.assertEqual(self.act(po.ref, "authorise").status_code, 200)
        pr.refresh_from_db()
        self.assertNotEqual(pr.status, "PAID_PO_ISSUED")
        self.assertIn(pr.ref, self.queue())
        p = Payable.objects.get(document=pr)
        self.assertEqual(p.amount, D("12000.00"))
        # the advance, on the voucher
        pv = self.voucher(source_refs=[pr.ref])
        self.assertEqual(pv["total"], D("8000.00"))
        self.assertEqual(costing.document_net(pr, state="COMMITTED"),
                         D("20000"))
        self.pay_advance(pr)
        self.assertEqual(self.paid(pr), D("8000"))
        p.refresh_from_db()
        self.assertEqual(p.status, "OUTSTANDING")    # the balance is still owed
        self.assertEqual(pr.status, "PAID_PO_ISSUED")
        # the balance, when its credit falls due
        pv2 = self.voucher(payable_ids=[p.id])
        self.as_user(self.finance)
        r = self.client.post(
            f"/api/v1/payment-vouchers/{pv2['ref']}/actions/settle-payable",
            {"payable_id": p.id, "payment_ref": "TRF-BAL"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.paid(pr), D("20000"))

    def test_plain_cash_and_plain_credit_are_as_they_were(self):
        pr = self.pr_with("Cash", "")
        ln = self.row(pr)
        self.assertEqual((ln.amount_cash, ln.amount_credit),
                         (D("20000.00"), None))
        self.voucher(source_refs=[pr.ref])
        self.assertFalse(Payable.objects.filter(document=pr).exists())
        self.pay_advance(pr)
        self.assertEqual(self.paid(pr), D("20000"))
