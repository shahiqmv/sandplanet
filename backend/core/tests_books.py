"""QuickBooks-style working: expense, deposit, transfer, the register and
the two statements (FINANCE_BUILD_BRIEF.md, stage 2)."""
from decimal import Decimal as D

from . import books, ledger
from .models import JournalEntry, LedgerTxn
from .tests_ledger import LedgerBase


class BooksBase(LedgerBase):
    def setUp(self):
        super().setUp()
        # opening: 1,000,000 in the rufiyaa bank, funded by equity
        r = self.c.post("/api/v1/ledger/journals", {
            "kind": "OPENING", "memo": "Opening", "post": True, "lines": [
                self.line(self.bank, debit=1000000),
                self.line("3200", credit=1000000)]}, format="json")
        assert r.status_code == 201, r.data

    def txn(self, typ, **kw):
        body = {"type": typ, "date": "2026-03-10", "account": self.bank.id,
                **kw}
        return self.c.post("/api/v1/ledger/txns", body, format="json")

    def bal(self, code_or_acc):
        a = code_or_acc if hasattr(code_or_acc, "id") else self.acc[code_or_acc]
        return ledger.balance_of(a)


class ExpenseTests(BooksBase):
    def expense(self, **kw):
        base = {"party": "STELCO", "reference": "TRF-991", "memo": "March",
                "party_tin": "1000001GST501", "tax_invoice_no": "INV-77",
                "lines": [{"account": self.acc["6320"].id, "amount": "1000",
                           "gst_treatment": "STANDARD",
                           "description": "Office electricity"}]}
        base.update(kw)
        return self.txn("EXPENSE", **base)

    def test_an_expense_posts_its_own_balanced_entry(self):
        r = self.expense(tax_invoice_held=True, tax_invoice_no="INV-77",
                         party_tin="1000001GST501")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["number"], r.data["amount"],
                          r.data["amount_mvr"]),
                         ("EXP-001", D("1080.00"), D("1080.00")))
        e = JournalEntry.objects.get(pk=r.data["journal"])
        self.assertEqual((e.kind, e.source_ref, e.status),
                         ("TXN", "EXP-001", "POSTED"))
        # cost net, GST to the recoverable account, bank down by the gross
        self.assertEqual(self.bal("6320"), D("1000.00"))
        self.assertEqual(self.bal("1430"), D("80.00"))
        self.assertEqual(self.bal(self.bank), D("998920.00"))

    def test_gst_without_a_valid_tax_invoice_stays_in_the_cost(self):
        """MIRA: input tax is claimable only against a valid tax invoice."""
        r = self.expense(tax_invoice_held=False)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.bal("6320"), D("1080.00"))
        self.assertEqual(self.bal("1430"), D("0"))
        self.assertEqual(self.bal(self.bank), D("998920.00"))

    def test_exempt_and_zero_rated_lines_carry_no_tax(self):
        r = self.expense(tax_invoice_held=True, lines=[
            {"account": self.acc["6320"].id, "amount": "500",
             "gst_treatment": "EXEMPT"},
            {"account": self.acc["6290"].id, "amount": "200",
             "gst_treatment": "ZERO"},
            {"account": self.acc["6280"].id, "amount": "100",
             "gst_treatment": "STANDARD", "gst_amount": "8"}])
        self.assertEqual(r.data["amount"], D("808.00"))
        self.assertEqual(self.bal("1430"), D("8.00"))

    def test_what_an_expense_needs(self):
        self.assertIn("who was paid", self.expense(party="").data["detail"])
        self.assertIn("at least one line", self.expense(lines=[]).data["detail"])
        r = self.expense(account=self.acc["6320"].id)      # not a bank account
        self.assertIn("bank or cash account", r.data["detail"])
        r = self.expense(date="2025-12-31")
        self.assertIn("books start", r.data["detail"])
        self.assertEqual(LedgerTxn.objects.count(), 0)     # nothing half-saved

    def test_a_gst_claim_needs_the_tin_and_the_invoice_number(self):
        # MIRA's input tax statement lists both for every claim
        for gap in ({"party_tin": ""}, {"tax_invoice_no": ""}):
            r = self.expense(tax_invoice_held=True, **gap)
            self.assertIn("To claim the GST", r.data["detail"])
        # without the tax invoice there is no claim, so nothing is asked
        r = self.expense(party_tin="", tax_invoice_no="")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.bal("6320"), D("1080.00"))

    def test_changing_a_transaction_keeps_the_history(self):
        r = self.expense(tax_invoice_held=True)
        tid, first = r.data["id"], r.data["journal_ref"]
        r = self.c.patch(f"/api/v1/ledger/txns/{tid}", {
            "date": "2026-03-10", "account": self.bank.id, "party": "STELCO",
            "tax_invoice_held": True, "party_tin": "1000001GST501",
            "tax_invoice_no": "INV-77",
            "lines": [{"account": self.acc["6320"].id, "amount": "2000",
                       "gst_treatment": "STANDARD"}]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["number"], "EXP-001")          # same number
        self.assertNotEqual(r.data["journal_ref"], first)      # a new entry
        self.assertEqual(self.bal("6320"), D("2000.00"))       # only the new
        self.assertEqual(self.bal(self.bank), D("997840.00"))
        # the first entry and its reversal are still in the journals
        old = JournalEntry.objects.get(ref=first)
        self.assertEqual(old.reversed_by.kind, "REVERSAL")
        # but the register reads like the statement: one payment
        reg = self.c.get(f"/api/v1/ledger/accounts/{self.bank.id}/register"
                         "?from=2026-01-01&to=2026-12-31").data
        self.assertEqual([(x["number"], x["payment"]) for x in reg["rows"]],
                         [("EXP-001", D("2160.00"))])

    def test_voiding_reverses_it(self):
        tid = self.expense(tax_invoice_held=True).data["id"]
        url = f"/api/v1/ledger/txns/{tid}/void"
        self.assertEqual(self.c.post(url, {}, format="json").status_code, 400)
        r = self.c.post(url, {"reason": "Entered twice"}, format="json")
        self.assertEqual(r.data["status"], "VOID")
        self.assertEqual(self.bal(self.bank), D("1000000.00"))
        self.assertEqual(self.bal("6320"), D("0"))
        self.assertEqual(self.c.patch(f"/api/v1/ledger/txns/{tid}", {},
                                      format="json").status_code, 400)

    def test_a_closed_period_cannot_be_changed(self):
        tid = self.expense(tax_invoice_held=True).data["id"]
        self.c.post("/api/v1/ledger/settings", {"lock_date": "2026-03-31"},
                    format="json")
        r = self.c.post(f"/api/v1/ledger/txns/{tid}/void", {"reason": "x"},
                        format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("closed up to", r.data["detail"])
        self.assertEqual(self.bal("6320"), D("1000.00"))

    def test_only_finance_enters_transactions(self):
        self.c.force_authenticate(self.sig)
        self.assertEqual(self.expense().status_code, 403)
        self.assertEqual(self.c.get("/api/v1/ledger/txns").status_code, 200)


class DepositAndTransferTests(BooksBase):
    def test_a_deposit_of_a_standard_rated_sale(self):
        r = self.txn("DEPOSIT", party="Resort A", reference="SLIP-4", lines=[
            {"account": self.acc["4120"].id, "amount": "5000",
             "gst_treatment": "STANDARD"}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["number"], r.data["amount"]),
                         ("DEP-001", D("5400.00")))
        self.assertEqual(self.bal(self.bank), D("1005400.00"))
        self.assertEqual(self.bal("4120"), D("-5000.00"))     # income, a credit
        self.assertEqual(self.bal("2210"), D("-400.00"))      # GST payable

    def test_a_transfer_between_rufiyaa_and_dollars(self):
        r = self.txn("TRANSFER", to_account=self.usd.id, amount="15420")
        self.assertIn("different currencies", r.data["detail"])
        r = self.txn("TRANSFER", to_account=self.usd.id, amount="15420",
                     amount_to="1000", memo="Buy USD")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["number"], "TRF-001")
        self.assertEqual(self.bal(self.bank), D("984580.00"))
        self.assertEqual(self.bal(self.usd), D("15420.00"))   # in rufiyaa
        # the dollar register runs in dollars
        reg = self.c.get(f"/api/v1/ledger/accounts/{self.usd.id}/register"
                         "?from=2026-01-01&to=2026-12-31").data
        self.assertEqual((reg["account"]["currency"], reg["closing"]),
                         ("USD", D("1000.00")))
        # and the list of accounts says what it holds in dollars
        row = next(a for a in self.c.get("/api/v1/ledger/accounts")
                   .data["accounts"] if a["id"] == self.usd.id)
        self.assertEqual((row["balance"], row["balance_fc"]),
                         (D("15420.00"), D("1000.00")))
        self.assertEqual(self.txn("TRANSFER", to_account=self.bank.id,
                                  amount="5").status_code, 400)   # same account

    def test_a_dollar_expense_is_booked_at_its_rate(self):
        self.txn("TRANSFER", to_account=self.usd.id, amount="15420",
                 amount_to="1000")
        r = self.txn("EXPENSE", account=self.usd.id, party="Supplier X",
                     lines=[{"account": self.acc["5110"].id, "amount": "100"}])
        self.assertIn("rate", r.data["detail"])
        r = self.txn("EXPENSE", account=self.usd.id, party="Supplier X",
                     fx_rate="15.42",
                     lines=[{"account": self.acc["5110"].id, "amount": "100"}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["currency"], r.data["amount"],
                          r.data["amount_mvr"]),
                         ("USD", D("100.00"), D("1542.00")))
        self.assertEqual(self.bal("5110"), D("1542.00"))
        self.assertEqual(self.bal(self.usd), D("13878.00"))


class StatementTests(BooksBase):
    def setUp(self):
        super().setUp()
        self.txn("DEPOSIT", party="Client", lines=[
            {"account": self.acc["4110"].id, "amount": "100000"}])
        self.txn("EXPENSE", party="Supplier", lines=[
            {"account": self.acc["5110"].id, "amount": "40000"}])
        self.txn("EXPENSE", party="Landlord", lines=[
            {"account": self.acc["6220"].id, "amount": "15000"},
            {"account": self.acc["6150"].id, "amount": "5000"}])
        self.txn("EXPENSE", party="Bank", lines=[
            {"account": self.acc["7510"].id, "amount": "500"}])

    def test_profit_and_loss(self):
        r = self.c.get("/api/v1/ledger/reports/pnl"
                       "?from=2026-01-01&to=2026-12-31").data
        s = r["sections"]
        self.assertEqual((s["INCOME"]["total"], s["COGS"]["total"],
                          r["gross_profit"]),
                         (D("100000.00"), D("40000.00"), D("60000.00")))
        self.assertEqual((s["EXPENSE"]["total"], r["operating_profit"],
                          r["net_profit"]),
                         (D("20500.00"), D("39500.00"), D("39500.00")))
        # sub-accounts roll up into their parent, as on the audited statement
        rows = {x["name"]: x for x in s["EXPENSE"]["rows"]}
        self.assertEqual(rows["Administrative expenses"]["amount"],
                         D("20000.00"))
        self.assertEqual(rows["Employees salaries and benefits"]["amount"],
                         D("5000.00"))
        self.assertEqual((rows["Staff visa charges"]["amount"],
                          rows["Staff visa charges"]["depth"]),
                         (D("5000.00"), 2))
        self.assertNotIn("Audit fee", rows)              # nothing posted to it

    def test_the_balance_sheet_balances_with_profit_in_equity(self):
        r = self.c.get("/api/v1/ledger/reports/balance-sheet"
                       "?as_of=2026-12-31").data
        self.assertTrue(r["balanced"])
        self.assertEqual((r["total_assets"], r["total_liabilities"],
                          r["net_profit_this_year"], r["total_equity"]),
                         (D("1039500.00"), D("0"), D("39500.00"),
                          D("1039500.00")))
        self.assertEqual(r["sections"]["BANK"]["total"], D("1039500.00"))
        # before any 2026 activity it is the opening position
        r = self.c.get("/api/v1/ledger/reports/balance-sheet"
                       "?as_of=2026-01-01").data
        self.assertEqual((r["total_assets"], r["net_profit_this_year"]),
                         (D("1000000.00"), D("0")))

    def test_statements_and_register_export_to_excel(self):
        for url in ("/api/v1/ledger/reports/pnl?export=xlsx",
                    "/api/v1/ledger/reports/balance-sheet?export=xlsx",
                    f"/api/v1/ledger/accounts/{self.bank.id}/register?export=xlsx"):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertTrue(r.content.startswith(b"PK"))

    def test_the_register_runs_a_balance(self):
        reg = self.c.get(f"/api/v1/ledger/accounts/{self.bank.id}/register"
                         "?from=2026-01-01&to=2026-12-31").data
        self.assertEqual(reg["opening"], D("1000000.00"))
        self.assertEqual([x["balance"] for x in reg["rows"]],
                         [D("1100000.00"), D("1060000.00"), D("1040000.00"),
                          D("1039500.00")])
        self.assertEqual(reg["rows"][2]["split"], "— split —")
        self.assertEqual(reg["rows"][1]["payee"], "Supplier")
        self.assertEqual(self.c.get(
            f"/api/v1/ledger/accounts/{self.acc['6220'].id}/register"
        ).status_code, 400)

    def test_meta_gives_the_rate_from_the_company_setting(self):
        m = self.c.get("/api/v1/ledger/meta").data
        self.assertEqual(m["gst_rate"], books.gst_rate())
        self.assertIn("Supplier", m["payees"])


class SiteResultTests(BooksBase):
    def test_one_sites_profit_and_loss(self):
        from .models import Site
        sjr = Site.objects.create(code="SJR", name="SJR")
        self.txn("EXPENSE", party="STELCO", lines=[
            {"account": self.acc["6320"].id, "amount": "1000",
             "site": sjr.id},
            {"account": self.acc["6320"].id, "amount": "400"}])
        self.txn("DEPOSIT", party="Client", lines=[
            {"account": self.acc["4120"].id, "amount": "5000",
             "site": sjr.id}])
        url = "/api/v1/ledger/reports/pnl?from=2026-01-01&to=2026-12-31"
        whole = self.c.get(url).data
        self.assertEqual(whole["net_profit"], D("3600.00"))
        one = self.c.get(f"{url}&site={sjr.id}").data
        self.assertEqual((one["net_profit"], one["site"]["code"]),
                         (D("4000.00"), "SJR"))
        self.assertEqual(self.c.get(f"{url}&site=99999").status_code, 404)
        self.assertIn("spreadsheet", self.c.get(
            f"{url}&site={sjr.id}&export=xlsx")["Content-Type"])
