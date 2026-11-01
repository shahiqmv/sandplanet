"""A supplier's discount on a local quotation (owner 2026-11-01): a % or a
lump sum, off the awarded goods before GST, carried through the PR vendor
row, the order, the payable, the voucher and the cost ledger."""
from decimal import Decimal as D

from . import costing
from .models import Document, Payable
from .tests_quotes import QuoteBase


class DiscountTests(QuoteBase):
    def pr_with(self, terms="Cash", gst=False, award_rebar=True, **discount):
        """Cement 150 × 100 = 15,000 and rebar 500 × 10 = 5,000 — a 20,000
        quote — with the discount set on the quotation, then approved."""
        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        self.as_user(self.purchasing)
        r = self.client.post(f"/api/v1/pr/{pr['ref']}/quotations", {
            "supplier": self.hw.id, "quote_ref": "QT-1",
            "payment_terms": terms, "gst_applicable": gst,
            "lines": [
                {"supplier_desc": "OPC cement 50kg", "unit": "bag",
                 "qty": 150, "rate": 100, "mr_line": mr["lines"][0]["id"],
                 "awarded": True},
                {"supplier_desc": "Rebar 12mm", "unit": "kg", "qty": 500,
                 "rate": 10, "mr_line": mr["lines"][1]["id"],
                 "awarded": award_rebar}]}, format="json")
        assert r.status_code == 201, r.data
        self.quote = r.data
        if not award_rebar:      # the rebar is bought from someone else
            self.add_quote(pr["ref"], self.steel, [
                {"supplier_desc": "Rebar 12mm", "unit": "kg", "qty": 500,
                 "rate": 9, "mr_line": mr["lines"][1]["id"],
                 "awarded": True}], terms=terms)
        if discount:
            r = self.client.patch(f"/api/v1/quotations/{self.quote['id']}",
                                  discount, format="json")
            assert r.status_code == 200, r.data
            self.quote = r.data
        assert self.act(pr["ref"], "submit").status_code == 200
        self.as_user(self.director)
        assert self.act(pr["ref"], "approve").status_code == 200
        return Document.objects.get(ref=pr["ref"])

    def row(self, pr):
        return pr.current_revision.lines.get()

    def test_a_percent_comes_off_before_gst(self):
        pr = self.pr_with(gst=True, discount_percent="5")
        self.assertEqual(self.quote["discount"]["text"], "5% discount")
        self.assertEqual(D(str(self.quote["discount"]["net"])), D("19000.00"))
        ln = self.row(pr)
        # 20,000 less 5% = 19,000 net; GST 8% on that
        self.assertEqual((ln.amount_cash, ln.gst_amount),
                         (D("19000.00"), D("1520.00")))
        self.assertIn("less 5% discount (1,000.00)", ln.remarks)

    def test_the_ledger_and_the_voucher_carry_the_discounted_value(self):
        pr = self.pr_with(discount_percent="5")
        self.as_user(self.finance)
        pv = self.client.post("/api/v1/payment-vouchers",
                              {"source_refs": [pr.ref]}, format="json")
        self.assertEqual(pv.status_code, 201, pv.data)
        self.assertEqual(D(str(pv.data["total"])), D("19000.00"))
        ref = pv.data["ref"]
        self.client.post(f"/api/v1/payment-vouchers/{ref}/actions/submit", {},
                         format="json")
        self.as_user(self.signatory)
        self.client.post(f"/api/v1/payment-vouchers/{ref}/actions/approve", {},
                         format="json")
        self.assertEqual(costing.document_net(pr, state="COMMITTED"),
                         D("19000"))

    def test_a_lump_sum_is_shared_when_only_part_is_awarded(self):
        # 500 off the 20,000 quote; only the 15,000 of cement is bought
        pr = self.pr_with(award_rebar=False, discount_amount="500")
        row = pr.current_revision.lines.get(vendor=self.hw.name)
        self.assertEqual(row.amount_cash, D("14625.00"))

    def test_a_lump_sum_on_the_whole_quote(self):
        pr = self.pr_with(discount_amount="500")
        self.assertEqual(self.row(pr).amount_cash, D("19500.00"))

    def test_a_credit_order_shows_it_and_owes_the_discounted_total(self):
        pr = self.pr_with(terms="Credit", gst=True, discount_percent="5")
        po = Document.objects.get(doc_type="PO")
        payload = po.current_revision.payload
        self.assertEqual((D(payload["discount"]), payload["discount_label"]),
                         (D("1000.00"), "5% discount"))
        from .pdf import _po_context
        t = _po_context(po, po.current_revision)["totals"]
        self.assertEqual((t["untaxed"], t["discount"], t["gst"], t["total"]),
                         ("20,000.00", "1,000.00", "1,520.00", "20,520.00"))
        self.as_user(self.signatory)
        self.assertEqual(self.act(po.ref, "authorise").status_code, 200)
        self.assertEqual(Payable.objects.get(document=pr).amount,
                         D("20520.00"))

    def test_an_amendment_keeps_the_discount(self):
        from . import po_amend
        self.pr_with(terms="Credit", discount_amount="1000")
        po = Document.objects.get(doc_type="PO")
        self.as_user(self.signatory)
        self.act(po.ref, "authorise")
        po.refresh_from_db()
        self.assertEqual(po_amend.revision_total(po.current_revision),
                         D("19000.00"))

    def test_entering_it(self):
        mr = self.sent_mr()
        pr = self.draft_pr(mr)
        q = self.add_quote(pr["ref"], self.hw, [
            {"supplier_desc": "Cement", "unit": "bag", "qty": 10,
             "rate": 100, "mr_line": mr["lines"][0]["id"]}])
        url = f"/api/v1/quotations/{q['id']}"
        for body in ({"discount_percent": "5", "discount_amount": "10"},
                     {"discount_percent": "100"},
                     {"discount_amount": "1000"},
                     {"discount_amount": "abc"}):
            self.assertEqual(self.client.patch(url, body, format="json")
                             .status_code, 400, body)
        r = self.client.patch(url, {"discount_amount": "50"}, format="json")
        self.assertEqual((r.data["discount_amount"], r.data["discount_percent"]),
                         ("50.00", None))
        # a % replaces the lump sum; blank clears it
        r = self.client.patch(url, {"discount_percent": "2",
                                    "discount_amount": ""}, format="json")
        self.assertEqual((r.data["discount_amount"], r.data["discount_percent"]),
                         (None, "2.00"))
        r = self.client.patch(url, {"discount_percent": ""}, format="json")
        self.assertEqual(r.data["discount"]["amount"], D("0"))
