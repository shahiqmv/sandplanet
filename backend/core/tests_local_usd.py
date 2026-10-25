"""USD local purchases (owner 2026-10-25).

Some local suppliers quote in dollars. The quote's currency follows the
purchase — PR vendor row, order, payable, voucher — and the cost ledger keeps
it in dollars (reports convert at the company rate). It is paid from a USD
account only. A PR buys in one currency.
"""
from decimal import Decimal as D

from .models import (CompanyBankAccount, CostPosting, Document, Payable,
                     Quotation)
from .tests_purchase_advance import AdvanceBase


class UsdLocalPurchaseTests(AdvanceBase):
    def usd_pr(self, terms, advance=None, gst=False):
        self.hw.default_currency = "USD"
        self.hw.save()
        return self.pr_with(terms, advance, gst=gst)

    def test_a_usd_quote_makes_a_usd_purchase_end_to_end(self):
        pr = self.usd_pr("Credit", gst=True)
        self.assertEqual(Quotation.objects.get().currency, "USD")
        ln = self.row(pr)
        self.assertEqual(ln.currency, "USD")
        self.assertEqual(ln.gst_amount, D("1600.00"))          # 8% of 20,000
        doc = self.client.get(f"/api/v1/documents/{pr.ref}").data
        self.assertEqual(doc["currency"], "USD")
        # the order is in dollars and charges the GST it should
        po = Document.objects.get(doc_type="PO")
        self.assertEqual(po.current_revision.payload["currency"], "USD")
        self.assertEqual(po.current_revision.payload["tax_rate"], "8")
        self.as_user(self.signatory)
        self.assertEqual(self.act(po.ref, "authorise").status_code, 200)
        # the cost is recorded in dollars, input GST too
        rows = CostPosting.objects.filter(document=pr)
        self.assertTrue(rows.exists())
        self.assertEqual({r.currency for r in rows}, {"USD"})
        # we owe the supplier dollars
        p = Payable.objects.get(document=pr)
        self.assertEqual((p.amount, p.currency), (D("21600.00"), "USD"))
        self.as_user(self.finance)
        listed = self.client.get("/api/v1/finance/payables")
        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertEqual(listed.data["totals"]["USD"], D("21600.00"))
        self.assertEqual(listed.data["payables"][0]["currency"], "USD")
        # paid from a USD account only
        mvr_acct = CompanyBankAccount.objects.create(
            label="BML MVR", bank_name="BML", account_name="Sand Planet",
            account_no="7701", currency="MVR")
        usd_acct = CompanyBankAccount.objects.create(
            label="BML USD", bank_name="BML", account_name="Sand Planet",
            account_no="7702", currency="USD")
        self.as_user(self.finance)
        bad = self.client.post("/api/v1/payment-vouchers",
                               {"payable_ids": [p.id],
                                "bank_account_id": mvr_acct.id},
                               format="json")
        self.assertEqual(bad.status_code, 400)
        pv = self.voucher(payable_ids=[p.id], bank_account_id=usd_acct.id)
        self.assertEqual(pv["total"], D("21600.00"))
        self.as_user(self.finance)
        r = self.client.post(
            f"/api/v1/payment-vouchers/{pv['ref']}/actions/settle-payable",
            {"payable_id": p.id, "payment_ref": "TT-USD"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        paid = CostPosting.objects.filter(document=pr, state="PAID")
        self.assertEqual({r.currency for r in paid}, {"USD"})
        self.assertEqual(sum(r.amount for r in paid), D("21600.00"))

    def test_a_usd_cash_purchase_goes_on_a_usd_voucher(self):
        pr = self.usd_pr("Cash")
        self.assertEqual(self.row(pr).currency, "USD")
        pv = self.voucher(source_refs=[pr.ref])
        self.assertEqual(pv["total"], D("20000.00"))
        from .models import PaymentVoucherLine
        self.assertEqual(PaymentVoucherLine.objects.get().currency, "USD")
        # an MVR request cannot share that voucher
        self.hw.default_currency = ""
        self.hw.save()
        other = self.pr_with("Cash", None)
        self.as_user(self.finance)
        r = self.client.post("/api/v1/payment-vouchers",
                             {"source_refs": [pr.ref, other.ref]},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_a_request_buys_in_one_currency(self):
        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        self.as_user(self.purchasing)
        line = lambda i, desc: {"supplier_desc": desc, "qty": 1,  # noqa: E731
                                "rate": 100, "awarded": True,
                                "mr_line": mr["lines"][i]["id"]}
        r = self.client.post(f"/api/v1/pr/{pr['ref']}/quotations", {
            "supplier": self.hw.id, "currency": "MVR",
            "lines": [line(0, "cement")]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        # a dollar quote can be captured to compare...
        r = self.client.post(f"/api/v1/pr/{pr['ref']}/quotations", {
            "supplier": self.steel.id, "currency": "USD",
            "lines": [{**line(1, "rebar"), "awarded": False}]},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["currency"], "USD")
        # ...but not awarded beside a rufiyaa award
        r = self.client.patch(f"/api/v1/quotations/{r.data['id']}", {
            "lines": [line(1, "rebar")]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("one currency", r.data["detail"])
        self.assertFalse(Quotation.objects.get(currency="USD")
                         .lines.filter(awarded=True).exists())
        # and nothing else but MVR or USD
        r = self.client.post(f"/api/v1/pr/{pr['ref']}/quotations", {
            "supplier": self.steel.id, "currency": "EUR", "lines": []},
            format="json")
        self.assertEqual(r.status_code, 400)
