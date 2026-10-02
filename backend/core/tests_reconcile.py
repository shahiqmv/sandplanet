"""Bank reconciliation: ticking a bank account off against its statement,
reading the bank's file, and what a reconciled statement then protects
(FINANCE_BUILD_BRIEF.md, stage 2)."""
import io
from decimal import Decimal as D

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from .models import BankReconciliation, JournalLine
from .tests_books import BooksBase

CSV = """Bank of Maldives,,,,,
Account statement 7730000012345 MVR,,,,,
,,,,,
Date,Description,Cheque No,Debit,Credit,Balance
31-12-2025,Balance brought forward,,,"1,000,000.00","1,000,000.00"
11-03-2026,POS STELCO TRF-991,,"1,080.00",,"998,920.00"
12-03-2026,Transfer from SONEVA FUSHI,,,"54,000.00","1,052,920.00"
31-03-2026,Service charge,,25.00,,"1,052,895.00"
02-04-2026,Cheque 000123,000123,500.00,,"1,052,395.00"
"""


class ReconcileBase(BooksBase):
    def setUp(self):
        super().setUp()
        self.exp = self.spend("1000", "STELCO", "2026-03-10",
                              gst="STANDARD", reference="TRF-991")
        self.dep = self.txn("DEPOSIT", date="2026-03-12", party="Soneva Fushi",
                            lines=[{"account": self.acc["4120"].id,
                                    "amount": "54000"}]).data
        # a cheque written in March the bank has not yet paid
        self.chq = self.spend("500", "Manas Hardware", "2026-03-28",
                              reference="000123")
        self.url = f"/api/v1/ledger/accounts/{self.bank.id}/reconciliations"

    def spend(self, amount, party, on, gst="NONE", **kw):
        r = self.txn("EXPENSE", date=on, party=party, lines=[
            {"account": self.acc["6320"].id, "amount": amount,
             "gst_treatment": gst}], **kw)
        assert r.status_code == 201, r.data
        return r.data

    def start(self, on="2026-03-31", balance="1052920"):
        return self.c.post(self.url, {"statement_date": on,
                                      "statement_balance": balance},
                           format="json")

    def act(self, rec, action, **body):
        return self.c.post(f"/api/v1/ledger/reconciliations/{rec}/{action}",
                           body, format="json")

    def row(self, d, number):
        return next(r for r in d["rows"] if r["number"] == number)

    def upload(self, rec, text=CSV, name="statement.csv"):
        f = SimpleUploadedFile(name, text.encode() if isinstance(text, str)
                               else text)
        return self.c.post(f"/api/v1/ledger/reconciliations/{rec}/import",
                           {"file": f}, format="multipart")


class ByHandTests(ReconcileBase):
    def test_ticking_off_until_it_agrees(self):
        r = self.start()
        self.assertEqual(r.status_code, 201, r.data)
        d = r.data
        # the opening balance, the two March movements and the cheque
        self.assertEqual(len(d["rows"]), 4)
        self.assertEqual((d["opening_balance"], d["cleared_balance"],
                          d["difference"]),
                         (D("0"), D("0"), D("1052920.00")))
        self.assertIn("doesn't agree", self.act(d["id"], "finish")
                      .data["detail"])
        ids = [x["id"] for x in d["rows"] if x["number"] != "EXP-002"]
        d = self.act(d["id"], "tick", lines=ids, on=True).data
        self.assertEqual((d["cleared_balance"], d["difference"]),
                         (D("1052920.00"), D("0.00")))
        self.assertEqual((d["ticked_payments"], d["ticked_deposits"]),
                         (D("1080.00"), D("1054000.00")))
        # unticking and ticking again
        d = self.act(d["id"], "tick", lines=ids[:1], on=False).data
        self.assertNotEqual(d["difference"], D("0.00"))
        self.act(d["id"], "tick", lines=ids[:1], on=True)
        r = self.act(d["id"], "finish")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "DONE")
        # the proof: books = statement less the cheque still out
        self.assertEqual((r.data["book_balance"],
                          r.data["outstanding_payments"],
                          r.data["outstanding_deposits"]),
                         (D("1052420.00"), D("500.00"), D("0")))
        acc = next(a for a in self.c.get("/api/v1/ledger/accounts")
                   .data["accounts"] if a["id"] == self.bank.id)
        self.assertEqual(str(acc["reconciled_to"]), "2026-03-31")
        x = self.c.get(f"/api/v1/ledger/reconciliations/{d['id']}?export=xlsx")
        self.assertIn("spreadsheet", x["Content-Type"])

    def test_a_reconciled_line_is_fixed_and_the_next_statement_carries_on(self):
        d = self.start().data
        ids = [x["id"] for x in d["rows"] if x["number"] != "EXP-002"]
        self.act(d["id"], "tick", lines=ids, on=True)
        self.act(d["id"], "finish")
        # what the bank has agreed can't be changed or voided under it
        r = self.c.post(f"/api/v1/ledger/txns/{self.exp['id']}/void",
                        {"reason": "wrong"}, format="json")
        self.assertIn("reconciled to 31 Mar 2026", r.data["detail"])
        r = self.c.patch(f"/api/v1/ledger/txns/{self.exp['id']}", {
            "date": "2026-03-10", "account": self.bank.id, "party": "STELCO",
            "lines": [{"account": self.acc["6320"].id, "amount": "9"}]},
            format="json")
        self.assertIn("Reopen that reconciliation", r.data["detail"])
        # the next statement starts where this one ended and offers only
        # what is still out
        self.assertIn("already reconciled to 31 Mar 2026",
                      self.start("2026-03-31", "1").data["detail"])
        self.assertIn("in the future",
                      self.start("2099-01-31", "1").data["detail"])
        r = self.start("2026-04-30", "1052420")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["opening_balance"], D("1052920.00"))
        self.assertEqual([x["number"] for x in r.data["rows"]], ["EXP-002"])
        self.assertIn("already in progress",
                      self.start("2026-05-31", "1").data["detail"])
        # only the latest finished one reopens, and not beside a draft
        self.assertIn("in progress",
                      self.act(d["id"], "reopen").data["detail"])
        self.assertEqual(self.c.delete(
            f"/api/v1/ledger/reconciliations/{r.data['id']}").status_code, 204)
        r = self.act(d["id"], "reopen")
        self.assertEqual(r.data["status"], "DRAFT")
        # reopened, the expense can be corrected — and leaves the statement
        r = self.c.post(f"/api/v1/ledger/txns/{self.exp['id']}/void",
                        {"reason": "Entered twice"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        d = self.c.get(f"/api/v1/ledger/reconciliations/{d['id']}").data
        self.assertNotIn("EXP-001", [x["number"] for x in d["rows"]])
        self.assertEqual(d["cleared_balance"], D("1054000.00"))

    def test_discarding_a_draft_unticks_everything(self):
        d = self.start().data
        self.act(d["id"], "tick", lines=[x["id"] for x in d["rows"]], on=True)
        self.assertEqual(JournalLine.objects.filter(
            cleared_in__isnull=False).count(), 4)
        self.assertEqual(self.c.delete(
            f"/api/v1/ledger/reconciliations/{d['id']}").status_code, 204)
        self.assertEqual(JournalLine.objects.filter(
            cleared_in__isnull=False).count(), 0)
        self.assertEqual(BankReconciliation.objects.count(), 0)

    def test_a_shorter_statement_drops_later_ticks(self):
        d = self.start().data
        self.act(d["id"], "tick", lines=[x["id"] for x in d["rows"]], on=True)
        r = self.c.patch(f"/api/v1/ledger/reconciliations/{d['id']}", {
            "statement_date": "2026-03-15", "statement_balance": "1052920"},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["rows"]), 3)        # the cheque is later
        self.assertEqual(r.data["difference"], D("0.00"))

    def test_the_dollar_account_reconciles_in_dollars(self):
        self.txn("TRANSFER", to_account=self.usd.id, amount="15420",
                 amount_to="1000", date="2026-03-15")
        r = self.c.post(
            f"/api/v1/ledger/accounts/{self.usd.id}/reconciliations",
            {"statement_date": "2026-03-31", "statement_balance": "1000"},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["account"]["currency"],
                          r.data["rows"][0]["amount"]),
                         ("USD", D("1000.00")))
        self.act(r.data["id"], "tick", lines=[r.data["rows"][0]["id"]],
                 on=True)
        self.assertEqual(self.act(r.data["id"], "finish").status_code, 200)
        # a posting account that is not money is not reconciled
        r = self.c.post(
            f"/api/v1/ledger/accounts/{self.acc['6320'].id}/reconciliations",
            {"statement_date": "2026-03-31", "statement_balance": "0"},
            format="json")
        self.assertIn("bank, cash or card", r.data["detail"])

    def test_the_signatory_reads_and_only_finance_reconciles(self):
        d = self.start().data
        sig = APIClient()
        sig.force_authenticate(self.sig)
        self.assertEqual(sig.get(self.url).status_code, 200)
        self.assertEqual(sig.get(
            f"/api/v1/ledger/reconciliations/{d['id']}").status_code, 200)
        self.assertEqual(sig.post(self.url, {}, format="json").status_code, 403)
        self.assertEqual(sig.post(
            f"/api/v1/ledger/reconciliations/{d['id']}/finish", {},
            format="json").status_code, 403)
        self.assertEqual(sig.delete(
            f"/api/v1/ledger/reconciliations/{d['id']}").status_code, 403)


class StatementFileTests(ReconcileBase):
    def test_the_banks_file_ticks_what_it_can(self):
        d = self.start("2026-03-31", "1052895").data
        r = self.upload(d["id"])
        self.assertEqual(r.status_code, 200, r.data)
        # the April line is after the statement date and left out
        self.assertEqual(r.data["imported"], {
            "lines": 4, "matched": 3, "skipped_after_date": 1,
            "file_closing_balance": D("1052895.00")})
        self.assertTrue(self.row(r.data, "EXP-001")["ticked"])
        self.assertTrue(self.row(r.data, "DEP-001")["on_statement"])
        self.assertFalse(self.row(r.data, "EXP-002")["ticked"])
        # the bank's charge is not in the books yet
        self.assertEqual([(u["description"], u["amount"])
                          for u in r.data["unmatched"]],
                         [("Service charge", D("-25.00"))])
        self.assertEqual(r.data["difference"], D("-25.00"))
        # entered, then paired
        self.txn("EXPENSE", date="2026-03-31", party="Bank of Maldives",
                 lines=[{"account": self.acc["7510"].id, "amount": "25"}])
        r = self.act(d["id"], "match")
        self.assertEqual((r.data["matched_now"], r.data["unmatched"],
                          r.data["difference"]), (1, [], D("0.00")))
        self.assertEqual(self.act(d["id"], "finish").status_code, 200)

    def test_one_amount_column_with_a_dr_cr_marker(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["Statement of account"])
        ws.append(["Transaction Date", "Narration", "Amount", "Dr/Cr",
                   "Running Balance"])
        from datetime import datetime
        ws.append([datetime(2026, 3, 11), "STELCO", 1080, "DR", 998920])
        ws.append([datetime(2026, 3, 12), "SONEVA", 54000, "CR", 1052920])
        buf = io.BytesIO()
        wb.save(buf)
        d = self.start().data
        r = self.upload(d["id"], buf.getvalue(), "statement.xlsx")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["imported"]["lines"],
                          r.data["imported"]["matched"]), (2, 2))
        self.assertEqual([s["amount"] for s in r.data["statement"]],
                         [D("-1080.00"), D("54000.00")])

    def test_a_cheque_is_paired_by_its_number_not_the_nearest_date(self):
        # two payments of the same amount; the bank quotes the cheque number
        other = self.spend("500", "Someone Else", "2026-04-01")
        d = self.start("2026-04-30", "0").data
        r = self.upload(d["id"], "Date,Description,Debit,Credit\n"
                        "02/04/2026,Cheque 000123 paid,500.00,\n")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(self.row(r.data, self.chq["number"])["ticked"])
        self.assertFalse(self.row(r.data, other["number"])["ticked"])

    def test_a_file_that_cannot_be_read_says_why(self):
        d = self.start().data
        self.assertIn("header row", self.upload(
            d["id"], "just,some,words\n1,2,3\n").data["detail"])
        self.assertIn("old Excel format", self.upload(
            d["id"], b"\xd0\xcf", "statement.xls").data["detail"])
        self.assertIn("PDF", self.upload(
            d["id"], b"%PDF-1.4", "statement.pdf").data["detail"])
        self.assertIn("after the statement date", self.upload(
            d["id"], "Date,Details,Debit,Credit\n01/05/2026,x,5,\n")
            .data["detail"])
        self.assertIn("Attach the statement", self.c.post(
            f"/api/v1/ledger/reconciliations/{d['id']}/import", {},
            format="multipart").data["detail"])
