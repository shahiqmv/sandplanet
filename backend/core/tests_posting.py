"""Posting Planet's operations to the books: each event gets one entry, a
changed event is re-posted, a vanished one reversed, and what can't be
posted is held back with the reason (FINANCE_BUILD_BRIEF.md, stage 3)."""
from datetime import date
from decimal import Decimal as D

from django.core.management import call_command
from rest_framework.test import APIClient

from . import costing, ledger, posting, vouchers
from .models import (Boq, CompanyBankAccount, CostHead, Customer, Document,
                     DocumentRevision, JournalEntry, LedgerAccount,
                     ManualInvoice, OfficialReceipt, PaymentVoucherLine,
                     ProgressClaim, Project, TradingInvoice, TradingReceipt,
                     TradingReceiptLine, User)
from .numbering import next_ref
from .tests import make_user
from .tests_vouchers import VoucherBase

ON = date(2026, 8, 10)


class PostingBase(VoucherBase):
    def setUp(self):
        super().setUp()
        from . import brand
        brand.invalidate()
        self.addCleanup(brand.invalidate)
        self.mvr_bank = CompanyBankAccount.objects.create(
            label="BML MVR", currency="MVR")
        self.usd_bank = CompanyBankAccount.objects.create(
            label="BML USD", currency="USD")
        ledger.setup_standard_chart(self.finance)
        self.acc = {a.code: a for a in LedgerAccount.objects.all()}
        self.bank = LedgerAccount.objects.get(bank_account=self.mvr_bank)
        self.usd = LedgerAccount.objects.get(bank_account=self.usd_bank)
        self.ho = vouchers.ho_site()
        self.c = APIClient()
        self.c.force_authenticate(self.finance)

    def bal(self, code_or_acc):
        a = (code_or_acc if hasattr(code_or_acc, "id")
             else LedgerAccount.objects.get(code=code_or_acc))
        return ledger.balance_of(a)

    def post(self, *rules):
        return {r["rule"]: r for r in posting.run(list(rules), self.finance,
                                                  commit=True)}

    def doc(self, doc_type, site=None, status="APPROVED", **kw):
        d = Document.objects.create(
            doc_type=doc_type, ref=next_ref(doc_type, None),
            site=site or self.site, doc_date=ON, status=status,
            created_by=self.finance, **kw)
        DocumentRevision.objects.create(document=d, rev_label="R0",
                                        payload={}, created_by=self.finance)
        return d

    def voucher_for(self, source, bank="mvr"):
        pv = self.doc("PV", site=self.ho, debit_account=(
            None if bank is None else
            self.mvr_bank if bank == "mvr" else self.usd_bank))
        PaymentVoucherLine.objects.create(
            voucher=pv, source_document=source, currency="MVR",
            amount=D("1"), status="APPROVED")
        return pv

    def cost(self, head, amount, state="INCURRED", source="PR", on=ON, **kw):
        return costing.post(
            site=kw.pop("site", self.site),
            cost_head=CostHead.objects.get(code=head), state=state,
            source=source, amount=amount, posted_on=on, actor=self.finance,
            **kw)


class PurchaseTests(PostingBase):
    def purchase(self):
        pr = self.doc("PR")
        self.cost("MATERIALS", "1000", document=pr)
        self.cost("INPUT_GST", "80", document=pr, site=self.ho,
                  is_stock_pool=True)
        return pr

    def test_a_purchase_is_a_cost_and_a_payable_then_a_payment(self):
        pr = self.purchase()
        r = self.post("purchases")["purchases"]
        self.assertEqual((r["post"], r["held"]), (1, []))
        self.assertEqual((self.bal("5110"), self.bal("1430"),
                          self.bal("2010")),
                         (D("1000.00"), D("80.00"), D("-1080.00")))
        e = JournalEntry.objects.get(source_type="P_PR")
        self.assertEqual((e.kind, e.date, e.source_ref),
                         ("AUTO", ON, f"PRI:{pr.id}:{ON}"))
        # the cost keeps its site, so the site's result shows it
        self.assertEqual(e.lines.get(account__code="5110").site, self.site)
        # paid a week later, from the bank on its voucher
        pay = date(2026, 8, 17)
        self.cost("MATERIALS", "1000", state="PAID", document=pr, on=pay)
        self.cost("INPUT_GST", "80", state="PAID", document=pr, on=pay,
                  site=self.ho)
        # … which is not yet known: held back, not guessed
        r = self.post("purchases")["purchases"]
        self.assertEqual((r["post"], r["same"]), (0, 1))
        self.assertIn("no payment voucher", r["held"][0]["why"])
        pv = self.voucher_for(pr, bank=None)
        self.assertIn("names no bank account",
                      self.post("purchases")["purchases"]["held"][0]["why"])
        pv.debit_account = self.mvr_bank
        pv.save()
        r = self.post("purchases")["purchases"]
        self.assertEqual((r["post"], r["held"]), (1, []))
        self.assertEqual((self.bal("2010"), self.bal(self.bank)),
                         (D("0.00"), D("-1080.00")))

    def test_running_it_again_changes_nothing(self):
        self.purchase()
        self.post("purchases")
        n = JournalEntry.objects.count()
        r = self.post("purchases")["purchases"]
        self.assertEqual((r["post"], r["reverse"], r["same"]), (0, 0, 1))
        self.assertEqual(JournalEntry.objects.count(), n)

    def test_a_change_in_planet_is_reposted_and_a_reversal_mirrored(self):
        pr = self.purchase()
        self.post("purchases")
        # the same day's figure grows: the old entry goes, a new one comes
        self.cost("MATERIALS", "500", document=pr)
        r = self.post("purchases")["purchases"]
        self.assertEqual((r["post"], r["reverse"]), (1, 1))
        self.assertEqual(self.bal("5110"), D("1500.00"))
        # Planet reverses the purchase on a later day: its mirror is posted
        later = date(2026, 8, 20)
        for head, amt, site in (("MATERIALS", "-1500", self.site),
                                ("INPUT_GST", "-80", self.ho)):
            self.cost(head, amt, document=pr, on=later, site=site)
        self.post("purchases")
        self.assertEqual((self.bal("5110"), self.bal("2010")),
                         (D("0.00"), D("0.00")))
        self.assertEqual(JournalEntry.objects.filter(
            source_type="P_PR", kind="AUTO", reversed_by__isnull=True)
            .count(), 2)

    def test_a_cost_head_with_no_account_waits_for_the_accountant(self):
        head = CostHead.objects.create(code="DIVING", name="Diving works")
        pr = self.doc("PR")
        costing.post(site=self.site, cost_head=head, state="INCURRED",
                     source="PR", amount="700", posted_on=ON, document=pr)
        r = self.post("purchases")["purchases"]
        self.assertEqual(r["post"], 0)
        self.assertIn("“Diving works” has no account", r["held"][0]["why"])
        d = self.c.get("/api/v1/ledger/posting").data
        row = next(h for h in d["heads"] if h["code"] == "DIVING")
        self.assertIsNone(row["account"])
        self.assertEqual(next(h for h in d["heads"]
                              if h["code"] == "MATERIALS")["account_label"],
                         "5110 Materials")
        r = self.c.patch(f"/api/v1/ledger/posting/heads/{head.id}",
                         {"account": self.acc["5180"].id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.post("purchases")["purchases"]["post"], 1)
        self.assertEqual(self.bal("5180"), D("700.00"))
        self.assertEqual(self.c.patch(
            f"/api/v1/ledger/posting/heads/{head.id}",
            {"account": self.acc["6000"].id}, format="json").status_code, 400)

    def test_what_the_bank_has_agreed_is_not_reversed_under_it(self):
        from . import reconcile
        pr = self.purchase()
        self.voucher_for(pr)
        self.cost("MATERIALS", "1080", state="PAID", document=pr)
        self.post("purchases")
        rec, _ = reconcile.start(self.bank, {
            "statement_date": "2026-08-31", "statement_balance": "-1080"},
            self.finance)
        d = reconcile.detail(rec)
        reconcile.tick(rec, [x["id"] for x in d["rows"]], True)
        self.assertIsNone(reconcile.finish(rec, self.finance))
        # Planet's figure changes after the statement was reconciled
        self.cost("MATERIALS", "20", state="PAID", document=pr)
        r = self.post("purchases")["purchases"]
        self.assertIn("Reopen that reconciliation", r["held"][0]["why"])
        self.assertEqual(self.bal(self.bank), D("-1080.00"))


class PaymentTests(PostingBase):
    def paid_pyr(self, amount=3000):
        ref = self.director_approved_pyr(amount=amount, payee="Boat Co")
        pv = self.create_voucher([ref]).data["ref"]
        self.voucher_action(pv, "submit", self.finance)
        self.voucher_action(pv, "approve", self.signatory)
        Document.objects.filter(ref=pv).update(debit_account=self.mvr_bank)
        self.client.force_authenticate(self.finance)
        r = self.client.post(f"/api/v1/documents/{ref}/actions/pay",
                             {"amount_paid": amount, "payment_ref": "TRF-1",
                              "paid_date": str(ON)}, format="json")
        assert r.status_code == 200, r.data
        return Document.objects.get(ref=ref)

    def test_a_requisition_paid_is_its_cost_out_of_the_bank(self):
        doc = self.paid_pyr()
        r = self.post("payment_requests")["payment_requests"]
        self.assertEqual((r["post"], r["held"]), (1, []))
        # Transport & Freight lands in site transport, at the site
        self.assertEqual((self.bal("5160"), self.bal(self.bank)),
                         (D("3000.00"), D("-3000.00")))
        e = JournalEntry.objects.get(source_type="P_PYR")
        self.assertIn(doc.ref, e.memo)
        self.assertIn("Boat Co", e.memo)
        self.assertEqual(e.lines.get(account__code="5160").site, self.site)

    def test_petty_cash_and_wages(self):
        self.cost("SITE_OVERHEADS", "450", source="PETTY_CASH")
        self.cost("TRANSPORT", "150", source="PETTY_CASH")
        self.cost("LABOUR", "90000", source="STAFF", staff_year=2026,
                  staff_month=7)
        self.cost("LABOUR", "1000", source="STAFF", staff_year=2026,
                  staff_month=7, currency="USD")
        out = self.post("petty_cash", "payroll")
        self.assertEqual((out["petty_cash"]["post"], out["payroll"]["post"]),
                         (1, 2))
        self.assertEqual((self.bal("1020"), self.bal("5180"),
                          self.bal("5160")),
                         (D("-600.00"), D("450.00"), D("150.00")))
        # dollars at the company rate
        self.assertEqual((self.bal("5130"), self.bal("2140")),
                         (D("105420.00"), D("-105420.00")))


class SalesTests(PostingBase):
    def setUp(self):
        super().setUp()
        self.site.client_name = "Vakkaru Maldives Pvt Ltd"
        self.site.save()
        self.project = Project.objects.create(
            site=self.site, code="POOLS", title="Pools", status="ACTIVE",
            contract_value=D("100000"), output_gst_pct="8")
        Boq.objects.create(project=self.project, currency="USD")

    def test_an_advance_invoice_is_a_liability_not_income(self):
        ProgressClaim.objects.create(
            project=self.project, seq=1, ref="IPA-01", claim_type="ADVANCE",
            basis="PERCENT", status="CERTIFIED", invoice_no="INV-2026-0001",
            advance_pct=D("10"), gst_pct=D("8"),
            certified_at="2026-08-10T06:00:00Z", created_by=self.finance)
        r = self.post("claims")["claims"]
        self.assertEqual((r["post"], r["held"]), (1, []))
        # USD 10,000 advance + 8% GST, at 15.42
        self.assertEqual((self.bal("1210"), self.bal("2160"),
                          self.bal("2210"), self.bal("4110")),
                         (D("166536.00"), D("-154200.00"), D("-12336.00"),
                          D("0")))
        ln = JournalEntry.objects.get(source_type="P_CLAIM").lines.get(
            account__code="1210")
        self.assertEqual((ln.currency, ln.amount_fc, ln.project, ln.party),
                         ("USD", D("10800.00"), self.project,
                          "Vakkaru Maldives Pvt Ltd"))
        # reopened by the Admin: the invoice leaves the books
        ProgressClaim.objects.update(status="DRAFT")
        r = self.post("claims")["claims"]
        self.assertEqual((r["post"], r["reverse"]), (0, 1))
        self.assertEqual(self.bal("1210"), D("0.00"))

    def invoice(self, **kw):
        base = dict(project=self.project, origin="ISSUED",
                    invoice_no="INV-2026-0002", invoice_date=ON,
                    currency="MVR", gst_pct=D("8"), net_amount=D("5000"),
                    gst_amount=D("400"), amount=D("5400"),
                    created_by=self.finance)
        base.update(kw)
        return ManualInvoice.objects.create(**base)

    def test_an_invoice_its_receipt_and_their_undoing(self):
        mi = self.invoice()
        self.post("manual_invoices")
        self.assertEqual((self.bal("1210"), self.bal("4110"),
                          self.bal("2210")),
                         (D("5400.00"), D("-5000.00"), D("-400.00")))
        from .models import ClientReceipt
        rc = OfficialReceipt.objects.create(
            site=self.site, receipt_no="OR-0001", receipt_date=ON,
            method="TT", reference="TT 5512", bank_account=self.mvr_bank,
            currency="MVR", recorded_by=self.finance)
        ClientReceipt.objects.create(
            project=self.project, manual_invoice=mi, official_receipt=rc,
            amount=D("5400"), currency="MVR", received_on=ON,
            recorded_by=self.finance)
        r = self.post("receipts")["receipts"]
        self.assertEqual((r["post"], r["held"]), (1, []))
        self.assertEqual((self.bal("1210"), self.bal(self.bank)),
                         (D("0.00"), D("5400.00")))
        # the receipt is deleted in Planet, then the invoice voided
        rc.delete()
        self.assertEqual(self.post("receipts")["receipts"]["reverse"], 1)
        mi.is_void = True
        mi.save()
        self.assertEqual(
            self.post("manual_invoices")["manual_invoices"]["reverse"], 1)
        self.assertEqual((self.bal("1210"), self.bal(self.bank),
                          self.bal("4110")), (D("0.00"), D("0.00"), D("0.00")))

    def test_what_is_dated_before_the_start_is_left_alone(self):
        self.invoice(invoice_date=date(2025, 11, 30), origin="HISTORICAL")
        self.invoice(invoice_no="INV-2026-0003", invoice_date=date(2026, 3, 1))
        self.assertEqual(
            self.post("manual_invoices")["manual_invoices"]["post"], 1)
        # and the accountant can start later than the books do
        self.assertIsNone(posting.save_settings({"from": "2026-07-01"},
                                                self.finance))
        r = self.post("manual_invoices")["manual_invoices"]
        self.assertEqual((r["post"], r["reverse"]), (0, 1))
        self.assertIn("books start", posting.save_settings(
            {"from": "2025-06-01"}, self.finance))

    def test_a_trading_invoice_and_money_with_no_bank_named(self):
        cust = Customer.objects.create(name="Kuramathi Maldives")
        inv = TradingInvoice.objects.create(
            customer=cust, ref="INV-2026-0010", status="ISSUED",
            invoice_date=ON, currency="MVR", subtotal=D("1000"),
            gst_percent=D("8"), gst=D("80"), total=D("1080"),
            advance_applied=D("200"), created_by=self.finance)
        rc = TradingReceipt.objects.create(
            customer=cust, receipt_no="OR-0009", receipt_date=ON,
            method="CASH", currency="MVR", recorded_by=self.finance)
        TradingReceiptLine.objects.create(receipt=rc, invoice=inv,
                                          amount=D("880"))
        out = self.post("trading_invoices", "receipts")
        self.assertEqual((out["trading_invoices"]["post"],
                          out["receipts"]["post"]), (1, 1))
        self.assertEqual((self.bal("4120"), self.bal("2210"),
                          self.bal("2160"), self.bal("1220")),
                         (D("-1000.00"), D("-80.00"), D("200.00"),
                          D("0.00")))
        # no bank on the receipt: it waits in "not yet banked", an account
        # added to the chart the first time it is needed
        waiting = LedgerAccount.objects.get(system_key="UNDEPOSITED")
        self.assertEqual(self.bal(waiting), D("880.00"))


class ControlTests(PostingBase):
    def setUp(self):
        super().setUp()
        pr = self.doc("PR")
        self.cost("MATERIALS", "1000", document=pr)

    def test_nothing_posts_until_a_rule_is_switched_on(self):
        d = self.c.get("/api/v1/ledger/posting").data
        self.assertEqual(len(d["rules"]), 10)
        self.assertFalse(any(r["on"] for r in d["rules"]))
        call_command("post_books", stdout=open("/dev/null", "w"))
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertIn("No rule is switched on", self.c.post(
            "/api/v1/ledger/posting/run", {}, format="json").data["detail"])
        # a preview shows what would happen and saves nothing
        r = self.c.post("/api/v1/ledger/posting/preview",
                        {"rules": ["purchases"]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        rep = r.data["report"][0]
        self.assertEqual((rep["name"], rep["post"], rep["post_mvr"]),
                         ("Local purchases", 1, D("1000.00")))
        self.assertEqual(rep["sample"][0]["lines"][0]["account"],
                         "5110 Materials")
        self.assertEqual(JournalEntry.objects.count(), 0)
        # switched on, the scheduled job keeps it in step
        r = self.c.post("/api/v1/ledger/posting", {"on": ["purchases"]},
                        format="json")
        self.assertTrue(next(x for x in r.data["rules"]
                             if x["key"] == "purchases")["on"])
        call_command("post_books", stdout=open("/dev/null", "w"))
        self.assertEqual(self.bal("5110"), D("1000.00"))
        d = self.c.get("/api/v1/ledger/posting").data
        self.assertEqual(next(x for x in d["rules"]
                              if x["key"] == "purchases")["entries"], 1)
        self.assertIn("Unknown rule", self.c.post(
            "/api/v1/ledger/posting", {"on": ["nonsense"]},
            format="json").data["detail"])

    def test_a_rule_is_taken_out_whole_once_it_is_off(self):
        self.c.post("/api/v1/ledger/posting", {"on": ["purchases"]},
                    format="json")
        self.c.post("/api/v1/ledger/posting/run", {}, format="json")
        r = self.c.post("/api/v1/ledger/posting/take-out",
                        {"rule": "purchases"}, format="json")
        self.assertIn("Switch the rule off first", r.data["detail"])
        self.c.post("/api/v1/ledger/posting", {"on": []}, format="json")
        r = self.c.post("/api/v1/ledger/posting/take-out",
                        {"rule": "purchases"}, format="json")
        self.assertEqual(r.data["reversed"], 1)
        # the reply is the whole screen again, cost heads included
        self.assertTrue(r.data["heads"])
        self.assertTrue(r.data["can_edit"])
        self.assertEqual((self.bal("5110"), self.bal("2010")),
                         (D("0.00"), D("0.00")))

    def test_who_may_look_and_who_may_switch(self):
        sig = APIClient()
        sig.force_authenticate(self.signatory)
        self.assertEqual(sig.get("/api/v1/ledger/posting").status_code, 200)
        self.assertEqual(sig.post("/api/v1/ledger/posting", {"on": []},
                                  format="json").status_code, 403)
        self.assertEqual(sig.post("/api/v1/ledger/posting/preview",
                                  {"rules": ["purchases"]},
                                  format="json").status_code, 403)
        pm = APIClient()
        pm.force_authenticate(make_user("pm9", User.Role.PM))
        self.assertEqual(pm.get("/api/v1/ledger/posting").status_code, 403)
