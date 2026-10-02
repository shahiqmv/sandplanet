"""Buying and selling on credit in the books: bills and paying them, sales
invoices and receiving payment, suppliers and customers, aging
(FINANCE_BUILD_BRIEF.md, stage 2)."""
from decimal import Decimal as D

from rest_framework.test import APIClient

from .models import JournalEntry, LedgerParty, LedgerTxn, Supplier
from .tests_books import BooksBase


class CreditBase(BooksBase):
    def bill(self, **kw):
        base = {"party": "Manas Hardware", "reference": "MH-1001",
                "date": "2026-03-10",
                "lines": [{"account": self.acc["5110"].id, "amount": "1000",
                           "gst_treatment": "STANDARD",
                           "description": "Cement"}]}
        base.update(kw)
        return self.c.post("/api/v1/ledger/txns", {"type": "BILL", **base},
                           format="json")

    def invoice(self, **kw):
        base = {"party": "Soneva Fushi", "reference": "INV-2026-0007",
                "date": "2026-03-10",
                "lines": [{"account": self.acc["4120"].id, "amount": "50000",
                           "gst_treatment": "STANDARD"}]}
        base.update(kw)
        return self.c.post("/api/v1/ledger/txns", {"type": "INVOICE", **base},
                           format="json")

    def settle(self, typ, applies, **kw):
        base = {"type": typ, "date": "2026-03-20", "account": self.bank.id,
                "applies": [{"doc": d, "amount": a} for d, a in applies]}
        base.update(kw)
        return self.c.post("/api/v1/ledger/txns", base, format="json")

    def get(self, pk):
        return self.c.get(f"/api/v1/ledger/txns/{pk}").data


class BillTests(CreditBase):
    def test_a_bill_is_owed_not_paid(self):
        Supplier.objects.create(name="Manas Hardware", credit_days=30)
        r = self.bill(tax_invoice_held=True, party_tin="1012345GST501")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["number"], r.data["amount"],
                          r.data["balance"]),
                         ("BILL-001", D("1080.00"), D("1080.00")))
        # nothing left the bank; the supplier is owed; GST is recoverable
        self.assertEqual(self.bal(self.bank), D("1000000.00"))
        self.assertEqual(self.bal("2010"), D("-1080.00"))
        self.assertEqual(self.bal("5110"), D("1000.00"))
        self.assertEqual(self.bal("1430"), D("80.00"))
        # the supplier is now in the books, tied to Purchasing's record, and
        # the bill falls due on their credit terms
        p = LedgerParty.objects.get(kind="SUPPLIER")
        self.assertEqual((p.name, p.credit_days, p.tin),
                         ("Manas Hardware", 30, "1012345GST501"))
        self.assertIsNotNone(p.supplier_id)
        self.assertEqual(str(r.data["due_date"]), "2026-04-09")
        self.assertEqual(r.data["tax_invoice_no"], "MH-1001")

    def test_gst_without_a_tax_invoice_stays_in_the_cost(self):
        self.assertEqual(self.bill().status_code, 201)
        self.assertEqual(self.bal("5110"), D("1080.00"))
        self.assertEqual(self.bal("1430"), D("0"))
        # and a tax invoice is not one without the supplier's TIN
        r = self.bill(reference="MH-1002", tax_invoice_held=True)
        self.assertIn("TIN", r.data["detail"])

    def test_the_same_bill_is_not_entered_twice(self):
        self.assertEqual(self.bill().status_code, 201)
        r = self.bill(reference="mh-1001")
        self.assertIn("already entered, as BILL-001", r.data["detail"])
        # the refused one took no number and left no supplier behind
        self.assertEqual(self.bill(party="Another Trader").data["number"],
                         "BILL-002")
        self.assertEqual(LedgerParty.objects.count(), 2)
        self.assertIn("bill or invoice number",
                      self.bill(reference="").data["detail"])

    def test_paying_bills_part_then_the_rest(self):
        b1 = self.bill().data["id"]
        b2 = self.bill(reference="MH-1002").data["id"]
        r = self.settle("BILL_PAY", [(b1, "1080"), (b2, "500")],
                        reference="CHQ 000123")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["number"], r.data["amount"],
                          r.data["party"]),
                         ("BPAY-001", D("1580.00"), "Manas Hardware"))
        self.assertEqual(len(r.data["applies"]), 2)
        self.assertEqual(self.bal(self.bank), D("998420.00"))
        self.assertEqual(self.bal("2010"), D("-580.00"))
        self.assertEqual(self.get(b1)["balance"], D("0.00"))
        self.assertEqual(self.get(b2)["balance"], D("580.00"))
        self.assertEqual(self.get(b2)["payments"][0]["number"], "BPAY-001")
        # only the unpaid one is still on the list to pay
        open_ = self.c.get("/api/v1/ledger/txns?type=BILL&open=1").data["txns"]
        self.assertEqual([t["id"] for t in open_], [b2])
        # no more than is owed; and not another supplier's bill with it
        self.assertIn("left to settle",
                      self.settle("BILL_PAY", [(b2, "600")]).data["detail"])
        other = self.bill(party="Another Trader").data["id"]
        self.assertIn("one supplier", self.settle(
            "BILL_PAY", [(b2, "100"), (other, "100")]).data["detail"])
        self.assertEqual(self.settle("BILL_PAY", [(b2, "580")]).status_code,
                         201)
        self.assertEqual(self.bal("2010"), D("-1080.00"))   # the other's
        # the register reads it like the bank statement
        reg = self.c.get(f"/api/v1/ledger/accounts/{self.bank.id}/register"
                         "?from=2026-01-01&to=2026-12-31").data
        row = reg["rows"][-2]
        self.assertEqual((row["number"], row["payee"], row["payment"],
                          row["split"]),
                         ("BPAY-001", "Manas Hardware", D("1580.00"),
                          "2010 Trade payables — local suppliers"))

    def test_a_payment_is_not_dated_before_its_bill(self):
        b = self.bill().data["id"]
        r = self.settle("BILL_PAY", [(b, "1080")], date="2026-03-01")
        self.assertIn("after this payment", r.data["detail"])
        self.assertIn("Tick at least one",
                      self.settle("BILL_PAY", []).data["detail"])

    def test_a_paid_bill_is_fixed_until_the_payment_is_voided(self):
        b = self.bill().data["id"]
        pay = self.settle("BILL_PAY", [(b, "500")]).data["id"]
        r = self.c.patch(f"/api/v1/ledger/txns/{b}", {
            "party": "Manas Hardware", "reference": "MH-1001",
            "date": "2026-03-10", "lines": [
                {"account": self.acc["5110"].id, "amount": "2000"}]},
            format="json")
        self.assertIn("void the payment first", r.data["detail"])
        r = self.c.post(f"/api/v1/ledger/txns/{b}/void", {"reason": "wrong"},
                        format="json")
        self.assertIn("BPAY-001", r.data["detail"])
        # a payment is voided, never edited
        self.assertEqual(self.c.patch(
            f"/api/v1/ledger/txns/{pay}", {}, format="json").status_code, 400)
        r = self.c.post(f"/api/v1/ledger/txns/{pay}/void",
                        {"reason": "Cheque returned"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.bal(self.bank), D("1000000.00"))
        self.assertEqual(self.get(b)["balance"], D("1080.00"))
        # now the bill can be corrected — reversed and posted again
        r = self.c.patch(f"/api/v1/ledger/txns/{b}", {
            "party": "Manas Hardware", "reference": "MH-1001",
            "date": "2026-03-10", "lines": [
                {"account": self.acc["5110"].id, "amount": "2000"}]},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((self.bal("2010"), self.bal("5110")),
                         (D("-2000.00"), D("2000.00")))


class ForeignBillTests(CreditBase):
    def usd_bill(self, **kw):
        return self.bill(party="Guangzhou Tiles Co", reference="GT-88",
                         currency="USD", fx_rate="15.42",
                         account=self.acc["2020"].id,
                         lines=[{"account": self.acc["5110"].id,
                                 "amount": "1000"}], **kw)

    def test_a_dollar_bill_paid_in_rufiyaa_at_another_rate(self):
        r = self.usd_bill()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["currency"], r.data["amount"],
                          r.data["amount_mvr"]),
                         ("USD", D("1000.00"), D("15420.00")))
        self.assertEqual(self.bal("2020"), D("-15420.00"))
        b = r.data["id"]
        # the bank took MVR 15,500 for the thousand dollars
        self.assertIn("rufiyaa amount",
                      self.settle("BILL_PAY", [(b, "1000")]).data["detail"])
        r = self.settle("BILL_PAY", [(b, "1000")], amount="15500")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.bal("2020"), D("0.00"))
        self.assertEqual(self.bal(self.bank), D("984500.00"))
        self.assertEqual(self.bal("9010"), D("80.00"))      # exchange loss

    def test_a_dollar_bill_paid_from_the_dollar_account_in_parts(self):
        self.txn("TRANSFER", to_account=self.usd.id, amount="30840",
                 amount_to="2000")
        b = self.usd_bill().data["id"]
        self.assertIn("rate", self.settle(
            "BILL_PAY", [(b, "400")], account=self.usd.id).data["detail"])
        r = self.settle("BILL_PAY", [(b, "400")], account=self.usd.id,
                        fx_rate="15.40")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["currency"], r.data["amount"],
                          r.data["amount_mvr"]),
                         ("USD", D("400.00"), D("6160.00")))
        self.assertEqual(self.bal("2020"), D("-9252.00"))
        self.assertEqual(self.bal("8020"), D("-8.00"))      # exchange gain
        r = self.settle("BILL_PAY", [(b, "600")], account=self.usd.id,
                        fx_rate="15.45", date="2026-03-25")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.bal("2020"), D("0.00"))       # to the laari
        self.assertEqual(self.bal("9010"), D("18.00"))
        reg = self.c.get(f"/api/v1/ledger/accounts/{self.usd.id}/register"
                         "?from=2026-01-01&to=2026-12-31").data
        self.assertEqual(reg["closing"], D("1000.00"))      # dollars


class InvoiceTests(CreditBase):
    def test_an_invoice_is_income_now_and_money_later(self):
        r = self.invoice(due_date="2026-04-09")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["number"], r.data["amount"]),
                         ("SALE-001", D("54000.00")))
        self.assertEqual(self.bal("1210"), D("54000.00"))
        self.assertEqual(self.bal("4120"), D("-50000.00"))
        self.assertEqual(self.bal("2210"), D("-4000.00"))   # output GST
        self.assertEqual(self.bal(self.bank), D("1000000.00"))
        inv = r.data["id"]
        r = self.settle("RECEIPT", [(inv, "30000")], reference="TT 5512")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["number"], "RCPT-001")
        self.assertEqual(self.bal(self.bank), D("1030000.00"))
        self.assertEqual(self.bal("1210"), D("24000.00"))
        self.assertEqual(self.get(inv)["balance"], D("24000.00"))
        # income is not counted twice by being paid
        self.assertEqual(self.bal("4120"), D("-50000.00"))
        # the same invoice number is not entered twice
        self.assertIn("already entered", self.invoice().data["detail"])
        # a bill is not settled by a receipt
        b = self.bill().data["id"]
        self.assertIn("void or gone",
                      self.settle("RECEIPT", [(b, "100")]).data["detail"])

    def test_dollars_received_for_a_rufiyaa_invoice(self):
        inv = self.invoice().data["id"]
        self.assertIn("USD amount", self.settle(
            "RECEIPT", [(inv, "54000")], account=self.usd.id).data["detail"])
        r = self.settle("RECEIPT", [(inv, "54000")], account=self.usd.id,
                        amount="3500")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.bal("1210"), D("0.00"))
        self.assertEqual(self.bal(self.usd), D("54000.00"))
        self.assertEqual(r.data["amount"], D("3500.00"))

    def test_aging_by_due_date_agrees_with_the_books(self):
        a = self.invoice(due_date="2026-04-09").data["id"]
        self.invoice(reference="INV-2026-0008", date="2026-01-05",
                     due_date="2026-01-20",
                     lines=[{"account": self.acc["4120"].id,
                             "amount": "10000"}])
        self.invoice(party="Kuramathi", reference="INV-2026-0009",
                     date="2026-03-01", due_date="2026-03-01",
                     lines=[{"account": self.acc["4120"].id,
                             "amount": "2000"}])
        self.settle("RECEIPT", [(a, "4000")])
        r = self.c.get("/api/v1/ledger/reports/aging?kind=CUSTOMER"
                       "&as_of=2026-04-30").data
        soneva = next(x for x in r["rows"] if x["name"] == "Soneva Fushi")
        self.assertEqual((soneva["d30"], soneva["older"], soneva["total"]),
                         (D("50000.00"), D("10000.00"), D("60000.00")))
        self.assertEqual(r["rows"][0]["name"], "Kuramathi")
        self.assertEqual(r["rows"][0]["d60"], D("2000.00"))
        self.assertEqual((r["total"]["total"], r["per_books"],
                          r["difference"]),
                         (D("62000.00"), D("62000.00"), D("0.00")))
        # as at a date before the receipt, the whole invoice was still open
        early = self.c.get("/api/v1/ledger/reports/aging?kind=CUSTOMER"
                           "&as_of=2026-03-15").data
        self.assertEqual(early["total"]["total"], D("66000.00"))
        self.assertEqual(early["total"]["current"], D("54000.00"))
        x = self.c.get("/api/v1/ledger/reports/aging?kind=CUSTOMER&export=xlsx")
        self.assertIn("spreadsheet", x["Content-Type"])

    def test_an_invoice_unpaid_when_the_books_opened(self):
        # the audited receivables went in with the opening balances
        r = self.c.post("/api/v1/ledger/journals", {
            "kind": "OPENING", "memo": "Receivables", "post": True, "lines": [
                self.line("1210", debit=8000),
                self.line("3200", credit=8000)]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        entries = JournalEntry.objects.count()
        # a dated-2025 invoice is refused as an ordinary one …
        r = self.invoice(reference="INV-2025-0412", date="2025-11-30")
        self.assertIn("books start", r.data["detail"])
        # … and goes in as an opening item, which posts nothing
        r = self.invoice(reference="INV-2025-0412", date="2025-11-30",
                         is_opening=True, amount="8000", lines=[])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["balance"], r.data["journal"]),
                         (D("8000.00"), None))
        self.assertEqual(JournalEntry.objects.count(), entries)
        self.assertEqual(self.bal("1210"), D("8000.00"))
        self.assertIn("before the books start", self.invoice(
            reference="X", is_opening=True, amount="5").data["detail"])
        # the customer pays in 2026: the receivable clears
        r = self.settle("RECEIPT", [(r.data["id"], "8000")])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.bal("1210"), D("0.00"))
        ag = self.c.get("/api/v1/ledger/reports/aging?kind=CUSTOMER").data
        self.assertEqual((ag["total"]["total"], ag["difference"]),
                         (D("0"), D("0.00")))


class PartyTests(CreditBase):
    def test_suppliers_with_what_is_owed_and_their_account(self):
        b = self.bill().data["id"]
        self.bill(reference="MH-1002", date="2026-03-12")
        self.settle("BILL_PAY", [(b, "1000")])
        r = self.c.get("/api/v1/ledger/parties?kind=SUPPLIER").data
        self.assertEqual([(p["name"], p["balance"], p["open"])
                          for p in r["parties"]],
                         [("Manas Hardware", D("1160.00"), 2)])
        pid = r["parties"][0]["id"]
        st = self.c.get(f"/api/v1/ledger/parties/{pid}").data
        self.assertEqual([(x["number"], x["change"], x["balance"])
                          for x in st["rows"]],
                         [("BILL-001", D("1080.00"), D("1080.00")),
                          ("BILL-002", D("1080.00"), D("2160.00")),
                          ("BPAY-001", D("-1000.00"), D("1160.00"))])
        # corrected in one place; the list keeps one of each name
        r = self.c.patch(f"/api/v1/ledger/parties/{pid}", {
            "name": "Manas Hardware Pvt Ltd", "tin": "1012345GST501",
            "credit_days": 45}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["party"]["credit_days"], 45)
        r = self.c.post("/api/v1/ledger/parties", {
            "kind": "SUPPLIER", "name": "manas hardware pvt ltd"},
            format="json")
        self.assertIn("already on the list", r.data["detail"])
        r = self.c.post("/api/v1/ledger/parties", {
            "kind": "CUSTOMER", "name": "Soneva Fushi", "credit_days": 30},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        # an invoice to them takes their terms
        self.assertEqual(str(self.invoice().data["due_date"]), "2026-04-09")
        x = self.c.get(f"/api/v1/ledger/parties/{pid}?export=xlsx")
        self.assertIn("spreadsheet", x["Content-Type"])

    def test_the_signatory_reads_and_only_finance_writes(self):
        self.bill()
        sig = APIClient()
        sig.force_authenticate(self.sig)
        self.assertEqual(sig.get(
            "/api/v1/ledger/parties?kind=SUPPLIER").status_code, 200)
        self.assertEqual(sig.get(
            "/api/v1/ledger/reports/aging?kind=SUPPLIER").status_code, 200)
        self.assertEqual(sig.post("/api/v1/ledger/parties", {
            "kind": "SUPPLIER", "name": "X"}, format="json").status_code, 403)
        self.assertEqual(sig.post("/api/v1/ledger/txns", {
            "type": "BILL"}, format="json").status_code, 403)
        pm = APIClient()
        pm.force_authenticate(self.pm)
        self.assertEqual(pm.get(
            "/api/v1/ledger/parties?kind=SUPPLIER").status_code, 403)
        self.assertEqual(LedgerTxn.objects.filter(type="BILL").count(), 1)
