"""The books: chart of accounts, balanced journals, reversal, trial balance
(FINANCE_BUILD_BRIEF.md, stage 1)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import ledger
from .models import (AuditLog, CompanyBankAccount, CompanyParameter,
                     JournalEntry, LedgerAccount, User)
from .tests import make_user


class LedgerBase(TestCase):
    def setUp(self):
        self.fin = make_user("lg_fin", User.Role.FINANCE)
        self.sig = make_user("lg_sig", User.Role.SIGNATORY)
        self.pm = make_user("lg_pm", User.Role.PM)
        CompanyBankAccount.objects.create(label="BML MVR", currency="MVR")
        CompanyBankAccount.objects.create(label="BML USD", currency="USD")
        self.c = APIClient()
        self.c.force_authenticate(self.fin)
        r = self.c.post("/api/v1/ledger/setup")
        assert r.status_code == 201, r.data
        self.acc = {a.code: a for a in LedgerAccount.objects.all()}
        self.bank = LedgerAccount.objects.get(name="BML MVR")
        self.usd = LedgerAccount.objects.get(name="BML USD")

    def line(self, code_or_acc, debit=0, credit=0, **kw):
        a = code_or_acc if hasattr(code_or_acc, "id") else self.acc[code_or_acc]
        return {"account": a.id, "debit": debit, "credit": credit, **kw}

    def journal(self, lines, post=True, **kw):
        body = {"date": "2026-03-10", "memo": "Office rent, March",
                "lines": lines, "post": post, **kw}
        return self.c.post("/api/v1/ledger/journals", body, format="json")


class ChartTests(LedgerBase):
    def test_the_standard_chart_follows_the_audited_statements(self):
        names = {a.name for a in self.acc.values()}
        for n in ("Property, plant and equipment", "Work in progress",
                  "Amounts due from directors", "Cash in hand",
                  "GST payable", "Income tax payable", "Share capital",
                  "Retained earnings", "Construction revenue",
                  "Resort supply sales", "Staff visa charges", "Bank charges"):
            self.assertIn(n, names)
        # one account per company bank account, the USD one held in USD
        self.assertEqual((self.bank.parent.name, self.bank.currency,
                          self.bank.type), ("Cash at banks", "", "BANK"))
        # QuickBooks' own types, so the auditors' copy maps one-to-one
        self.assertEqual({self.acc[c].type for c in
                          ("1210", "1430", "1710", "2010", "2210", "5110")},
                         {"AR", "OTHER_CURRENT_ASSET", "FIXED_ASSET", "AP",
                          "OTHER_CURRENT_LIABILITY", "COGS"})
        self.assertEqual(self.usd.currency, "USD")
        # set up once only
        self.assertEqual(self.c.post("/api/v1/ledger/setup").status_code, 400)

    def test_the_consultant_shapes_the_chart(self):
        r = self.c.post("/api/v1/ledger/accounts", {
            "code": "6395", "name": "Software subscriptions",
            "type": "EXPENSE", "parent": self.acc["6000"].id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        new = r.data["id"]
        # rename and re-code freely
        r = self.c.patch(f"/api/v1/ledger/accounts/{new}",
                         {"code": "6396", "name": "Software"}, format="json")
        self.assertEqual((r.data["code"], r.data["name"]), ("6396", "Software"))
        # a code is used once; a child matches its group's type
        self.assertEqual(self.c.post("/api/v1/ledger/accounts", {
            "code": "6396", "name": "Dup", "type": "EXPENSE"},
            format="json").status_code, 400)
        r = self.c.post("/api/v1/ledger/accounts", {
            "code": "6397", "name": "Wrong", "type": "FIXED_ASSET",
            "parent": self.acc["6000"].id}, format="json")
        self.assertIn("same type", r.data["detail"])
        # an unused ordinary account can go; one PLANET posts to cannot
        self.assertEqual(self.c.delete(
            f"/api/v1/ledger/accounts/{new}").status_code, 204)
        r = self.c.delete(f"/api/v1/ledger/accounts/{self.acc['2010'].id}")
        self.assertIn("automatically", r.data["detail"])
        # but it can be renamed and re-coded, and rules still find it
        self.c.patch(f"/api/v1/ledger/accounts/{self.acc['2010'].id}",
                     {"code": "2011", "name": "Creditors"}, format="json")
        self.assertEqual(ledger.account_for("AP_TRADE").code, "2011")

    def test_who_may_read_and_who_may_write(self):
        self.c.force_authenticate(self.pm)
        self.assertEqual(self.c.get("/api/v1/ledger/accounts").status_code, 403)
        self.c.force_authenticate(self.sig)
        self.assertEqual(self.c.get("/api/v1/ledger/accounts").status_code, 200)
        self.assertEqual(self.c.post("/api/v1/ledger/accounts", {
            "code": "1", "name": "x", "type": "BANK"},
            format="json").status_code, 403)


class JournalTests(LedgerBase):
    def test_a_balanced_entry_posts_and_gets_the_next_number(self):
        r = self.journal([self.line("6220", debit=15000),
                          self.line(self.bank, credit=15000)])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["status"], r.data["ref"]), ("POSTED", "JV-001"))
        r = self.journal([self.line("6220", debit=100),
                          self.line(self.bank, credit=100)])
        self.assertEqual(r.data["ref"], "JV-002")
        self.assertTrue(AuditLog.objects.filter(event="JOURNAL_POSTED").exists())

    def test_an_unbalanced_entry_is_refused_and_kept_as_a_draft(self):
        r = self.journal([self.line("6220", debit=15000),
                          self.line(self.bank, credit=14000)])
        self.assertEqual(r.status_code, 400)
        self.assertIn("out by 1,000.00", r.data["detail"])
        e = JournalEntry.objects.get()
        self.assertEqual((e.status, e.ref), ("DRAFT", ""))   # no number spent

    def test_what_a_line_must_be(self):
        for lines, word in (
            ([self.line("6000", debit=5), self.line(self.bank, credit=5)],
             "group"),
            ([self.line("6220", debit=5, credit=5),
              self.line(self.bank, credit=5)], "one of the two"),
            ([self.line("6220", debit=-5), self.line(self.bank, credit=5)],
             "negative"),
            ([self.line("6220", debit=5)], "at least two"),
        ):
            r = self.journal(lines)
            self.assertEqual(r.status_code, 400, word)
            self.assertIn(word, r.data["detail"])

    def test_dates_before_the_books_start_or_in_a_closed_period(self):
        r = self.journal([self.line("6220", debit=5),
                          self.line(self.bank, credit=5)], date="2025-12-31")
        self.assertIn("books start on 01 Jan 2026", r.data["detail"])
        self.c.post("/api/v1/ledger/settings", {"lock_date": "2026-03-31"},
                    format="json")
        r = self.journal([self.line("6220", debit=5),
                          self.line(self.bank, credit=5)], date="2026-03-31")
        self.assertIn("closed up to 31 Mar 2026", r.data["detail"])
        r = self.journal([self.line("6220", debit=5),
                          self.line(self.bank, credit=5)], date="2026-04-01")
        self.assertEqual(r.status_code, 201, r.data)

    def test_a_posted_entry_is_never_changed_only_reversed(self):
        jid = self.journal([self.line("6220", debit=15000),
                            self.line(self.bank, credit=15000)]).data["id"]
        url = f"/api/v1/ledger/journals/{jid}"
        self.assertEqual(self.c.patch(url, {"memo": "x", "date": "2026-03-10",
                                            "lines": []},
                                      format="json").status_code, 400)
        self.assertEqual(self.c.delete(url).status_code, 400)
        self.assertEqual(self.c.post(f"{url}/reverse", {},
                                     format="json").status_code, 400)  # reason
        r = self.c.post(f"{url}/reverse", {"reason": "Wrong month"},
                        format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["kind"], r.data["reversal_of"]),
                         ("REVERSAL", "JV-001"))
        self.assertEqual(ledger.balance_of(self.acc["6220"]), Decimal("0"))
        self.assertEqual(self.c.get(url).data["reversed_by"], r.data["ref"])
        # once only
        self.assertEqual(self.c.post(f"{url}/reverse", {"reason": "again"},
                                     format="json").status_code, 400)

    def test_a_draft_can_be_changed_and_deleted(self):
        jid = self.journal([self.line("6220", debit=10),
                            self.line(self.bank, credit=10)],
                           post=False).data["id"]
        url = f"/api/v1/ledger/journals/{jid}"
        r = self.c.patch(url, {"date": "2026-03-11", "memo": "Rent",
                               "lines": [self.line("6220", debit=20),
                                         self.line(self.bank, credit=20)],
                               "post": True}, format="json")
        self.assertEqual((r.data["status"], r.data["total"]),
                         ("POSTED", Decimal("20.00")))
        other = self.journal([self.line("6220", debit=1),
                              self.line(self.bank, credit=1)],
                             post=False).data["id"]
        self.assertEqual(self.c.delete(
            f"/api/v1/ledger/journals/{other}").status_code, 204)

    def test_a_foreign_currency_line_keeps_its_own_amount(self):
        # a USD account takes USD lines, with the rate that makes the rufiyaa
        r = self.journal([self.line(self.usd, debit=1542),
                          self.line("4110", credit=1542)])
        self.assertIn("USD amount and the rate", r.data["detail"])
        r = self.journal([
            self.line(self.usd, debit=1542, amount_fc=100, fx_rate="15.42"),
            self.line("4110", credit=1542)], memo="Client receipt")
        self.assertEqual(r.status_code, 201, r.data)
        ln = r.data["lines"][0]
        self.assertEqual((ln["currency"], ln["amount_fc"]),
                         ("USD", Decimal("100.00")))
        r = self.journal([
            self.line(self.usd, debit=2000, amount_fc=100, fx_rate="15.42"),
            self.line("4110", credit=2000)])
        self.assertIn("is 1542.00, not 2000.00", r.data["detail"])

    def test_only_finance_posts(self):
        self.c.force_authenticate(self.sig)
        r = self.journal([self.line("6220", debit=5),
                          self.line(self.bank, credit=5)])
        self.assertEqual(r.status_code, 403)


class ReportTests(LedgerBase):
    def setUp(self):
        super().setUp()
        # opening balances, the audited way: assets = equity + liabilities
        r = self.c.post("/api/v1/ledger/journals", {
            "kind": "OPENING", "memo": "Audited balances at 31 Dec 2025",
            "post": True, "lines": [
                self.line(self.bank, debit=2386168),
                self.line("1010", debit=38214),
                self.line("3100", credit=6000),
                self.line("3200", credit=2418382)]}, format="json")
        assert r.status_code == 201, r.data
        self.opening = r.data
        self.journal([self.line("6220", debit=15000),
                      self.line(self.bank, credit=15000)])
        self.journal([self.line(self.bank, debit=50000),
                      self.line("4110", credit=50000)], memo="Receipt",
                     date="2026-04-02")

    def test_opening_balances_sit_before_the_first_day(self):
        self.assertEqual(self.opening["date"], date(2025, 12, 31))
        self.assertEqual(self.opening["kind"], "OPENING")

    def test_the_trial_balance_balances(self):
        tb = self.c.get("/api/v1/ledger/trial-balance"
                        "?from=2026-01-01&to=2026-12-31").data
        self.assertTrue(tb["balanced"])
        rows = {r["code"]: r for r in tb["rows"]}
        bank = rows[self.bank.code]
        self.assertEqual((bank["opening_debit"], bank["debit"], bank["credit"],
                          bank["closing_debit"]),
                         (Decimal("2386168.00"), Decimal("50000.00"),
                          Decimal("15000.00"), Decimal("2421168.00")))
        self.assertEqual(rows["3200"]["opening_credit"], Decimal("2418382.00"))
        self.assertEqual(rows["4110"]["closing_credit"], Decimal("50000.00"))
        t = tb["totals"]
        self.assertEqual(t["closing_debit"], t["closing_credit"])
        self.assertEqual(t["opening_debit"], Decimal("2424382.00"))
        # a period that ends before April leaves the receipt out
        tb = self.c.get("/api/v1/ledger/trial-balance"
                        "?from=2026-01-01&to=2026-03-31").data
        self.assertNotIn("4110", {r["code"] for r in tb["rows"]})
        # drafts never count
        self.journal([self.line("6220", debit=999),
                      self.line(self.bank, credit=999)], post=False)
        tb2 = self.c.get("/api/v1/ledger/trial-balance"
                         "?from=2026-01-01&to=2026-03-31").data
        self.assertEqual(tb2["totals"], tb["totals"])

    def test_an_account_ledger_runs_a_balance_on_its_normal_side(self):
        led = self.c.get(f"/api/v1/ledger/accounts/{self.bank.id}/ledger"
                         "?from=2026-01-01&to=2026-12-31").data
        self.assertEqual(led["opening"], Decimal("2386168.00"))
        self.assertEqual([r["balance"] for r in led["rows"]],
                         [Decimal("2371168.00"), Decimal("2421168.00")])
        self.assertEqual(led["closing"], Decimal("2421168.00"))
        # income shows its credit balance as a positive figure
        rev = self.c.get(f"/api/v1/ledger/accounts/{self.acc['4110'].id}"
                         "/ledger?from=2026-01-01&to=2026-12-31").data
        self.assertEqual(rev["closing"], Decimal("50000.00"))
        self.assertEqual(self.c.get(
            f"/api/v1/ledger/accounts/{self.acc['6000'].id}/ledger"
        ).status_code, 400)                               # a group

    def test_excel_for_the_auditor(self):
        for url in ("/api/v1/ledger/trial-balance?export=xlsx",
                    f"/api/v1/ledger/accounts/{self.bank.id}/ledger?export=xlsx"):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.content.startswith(b"PK"))

    def test_an_account_with_entries_keeps_its_type_and_cannot_be_deleted(self):
        r = self.c.patch(f"/api/v1/ledger/accounts/{self.acc['6220'].id}",
                         {"type": "FIXED_ASSET"}, format="json")
        self.assertIn("entries posted", r.data["detail"])
        r = self.c.delete(f"/api/v1/ledger/accounts/{self.acc['6220'].id}")
        self.assertIn("close it instead", r.data["detail"])
        r = self.c.patch(f"/api/v1/ledger/accounts/{self.bank.id}",
                         {"is_active": False}, format="json")
        self.assertIn("carries a balance", r.data["detail"])

    def test_the_start_date_cannot_move_once_entries_are_posted(self):
        self.c.force_authenticate(make_user("lg_adm", User.Role.ADMIN))
        r = self.c.post("/api/v1/ledger/settings",
                        {"books_start_date": "2025-01-01"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(CompanyParameter.objects.filter(
            key="books_start_date").exists())


class FeatureTests(TestCase):
    def test_a_sister_company_keeps_no_books_until_it_says_so(self):
        from . import brand
        brand.invalidate()
        self.assertTrue(brand.brand(fresh=True)["features"]["books"])
        CompanyParameter.objects.create(
            key="features", value={"trading": False, "rental": True})
        self.assertFalse(brand.brand(fresh=True)["features"]["books"])
        apps = [a["key"] for a in brand.public_dict()["apps"]]
        self.assertNotIn("finance", apps)
        # and the API refuses there too, for Finance as for anyone
        c = APIClient()
        c.force_authenticate(make_user("lg_fin2", User.Role.FINANCE))
        self.assertEqual(c.get("/api/v1/ledger/accounts").status_code, 403)
        self.assertEqual(c.post("/api/v1/ledger/setup").status_code, 403)
        self.assertEqual(LedgerAccount.objects.count(), 0)
        brand.invalidate()
