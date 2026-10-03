"""Phone and utility bills: a register of accounts, a month's bills entered
on one sheet, and a provider's batch paid on one voucher (owner 2026-10-03)."""
from datetime import date
from decimal import Decimal as D
from unittest import mock

from rest_framework.test import APIClient

from . import ledger, posting, vouchers
from .models import (BillAccount, BillCharge, CompanyBankAccount, CostPosting,
                     Document, LedgerAccount, Payable, User)
from .tests import make_user
from .tests_vouchers import VoucherBase

TODAY = date(2026, 10, 3)


class BillsBase(VoucherBase):
    def setUp(self):
        super().setUp()
        p = mock.patch("core.bills._today", return_value=TODAY)
        p.start()
        self.addCleanup(p.stop)
        self.ho = vouchers.ho_site()
        self.c = APIClient()
        self.c.force_authenticate(self.finance)

    def account(self, **kw):
        body = {"provider": "Dhiraagu", "kind": "MOBILE",
                "account_no": "7771234", "label": "Project Director",
                "site": self.ho.id}
        body.update(kw)
        return self.c.post("/api/v1/bills/accounts", body, format="json")

    def enter(self, period, rows):
        return self.c.post("/api/v1/bills/sheet",
                           {"period": period, "rows": rows}, format="json")


class RegisterTests(BillsBase):
    def test_an_account_takes_its_usual_head_and_gst(self):
        r = self.account()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["ref"], r.data["cost_head_name"],
                          r.data["gst_applicable"]),
                         ("UTL-001", "Telephone & internet", True))
        # electricity is exempt from GST and lands under utilities
        r = self.account(provider="STELCO", kind="ELECTRICITY",
                         account_no="M-44021", label="Head office meter")
        self.assertEqual((r.data["cost_head_name"], r.data["gst_applicable"]),
                         ("Electricity & water", False))
        # the same number is not listed twice
        self.assertIn("already on the list", self.account().data["detail"])
        for patch, msg in (({"provider": ""}, "provider"),
                           ({"account_no": ""}, "number"),
                           ({"site": None}, "site"),
                           ({"due_day": 30}, "between 1 and 28")):
            self.assertIn(msg, self.account(**{"account_no": "X1", **patch})
                          .data["detail"])
        d = self.c.get("/api/v1/bills/accounts").data
        self.assertEqual([(a["provider"], a["account_no"])
                          for a in d["accounts"]],
                         [("Dhiraagu", "7771234"), ("STELCO", "M-44021")])

    def test_many_numbers_pasted_at_once_all_or_none(self):
        body = {"provider": "Ooredoo", "kind": "MOBILE", "site": self.ho.id,
                "lines": "9601111, Site engineer SJR, 500\n"
                         "9602222\tStore keeper\n\n9603333"}
        r = self.c.post("/api/v1/bills/accounts", body, format="json")
        self.assertEqual((r.status_code, r.data["added"]), (201, 3))
        a = BillAccount.objects.get(account_no="9601111")
        self.assertEqual((a.label, a.monthly_limit, a.ref),
                         ("Site engineer SJR", D("500.00"), "UTL-001"))
        # one bad line and none go in
        body["lines"] = "9604444, New\n9602222, Twice"
        r = self.c.post("/api/v1/bills/accounts", body, format="json")
        self.assertIn("Line 2", r.data["detail"])
        self.assertIn("Nothing was added", r.data["detail"])
        self.assertEqual(BillAccount.objects.count(), 3)

    def test_who_may_see_and_who_may_change(self):
        self.account()
        sig = APIClient()
        sig.force_authenticate(self.signatory)
        self.assertEqual(sig.get("/api/v1/bills/accounts").status_code, 200)
        self.assertEqual(sig.get("/api/v1/bills/to-pay").status_code, 200)
        self.assertEqual(sig.post("/api/v1/bills/accounts", {},
                                  format="json").status_code, 403)
        self.assertEqual(sig.post("/api/v1/bills/sheet", {},
                                  format="json").status_code, 403)
        pm = APIClient()
        pm.force_authenticate(make_user("pm8", User.Role.PM))
        self.assertEqual(pm.get("/api/v1/bills/accounts").status_code, 403)


class MonthTests(BillsBase):
    def setUp(self):
        super().setUp()
        self.a1 = self.account(monthly_limit="500", due_day=15).data["id"]
        self.a2 = self.account(account_no="7775678",
                               label="Finance manager").data["id"]
        self.a3 = self.account(provider="STELCO", kind="ELECTRICITY",
                               account_no="M-44021",
                               label="Head office meter").data["id"]

    def september(self):
        return self.enter("2026-09", [
            {"account": self.a1, "total": "648", "bill_no": "D-1"},
            {"account": self.a2, "total": "324"},
            {"account": self.a3, "total": "12,500.00",
             "due_date": "2026-10-20"}])

    def test_a_months_bills_go_in_on_one_sheet(self):
        d = self.c.get("/api/v1/bills/sheet?period=2026-09").data
        self.assertEqual(len(d["rows"]), 3)
        self.assertEqual(str(d["rows"][0]["usual_due"]), "2026-10-15")
        r = self.september()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["entered"], r.data["total"]),
                         (3, D("13472.00")))
        # the phone bill's figure includes its GST; electricity has none
        c = BillCharge.objects.get(account_id=self.a1)
        self.assertEqual((c.amount, c.gst, c.total, c.due_date, c.period),
                         (D("600.00"), D("48.00"), D("648.00"),
                          date(2026, 10, 15), date(2026, 9, 1)))
        e = BillCharge.objects.get(account_id=self.a3)
        self.assertEqual((e.amount, e.gst, e.due_date),
                         (D("12500.00"), D("0.00"), date(2026, 10, 20)))
        p = c.payable
        self.assertEqual((p.vendor, p.amount, p.status, p.document,
                          p.ref_label),
                         ("Dhiraagu", D("648.00"), "OUTSTANDING", None,
                          "UTL-001"))
        self.assertIn("7771234 · Project Director · Sep 2026", p.terms)
        # cost for the bill, GST to the recoverable pool at head office
        rows = CostPosting.objects.filter(bill_charge=c, state="INCURRED")
        self.assertEqual(sorted((x.cost_head.code, x.amount) for x in rows),
                         [("INPUT_GST", D("48.00")), ("TELECOM", D("600.00"))])
        # the sheet now shows them, and flags the one over its limit
        d = self.c.get("/api/v1/bills/sheet?period=2026-09").data
        self.assertEqual(d["rows"][0]["charge"]["over_limit"], D("148.00"))
        self.assertIsNone(d["rows"][1]["charge"]["over_limit"])
        # next month's sheet shows what each was last month
        d = self.c.get("/api/v1/bills/sheet?period=2026-10"
                       "&provider=dhiraagu").data
        self.assertEqual([(x["previous"], x["charge"]) for x in d["rows"]],
                         [(D("648.00"), None), (D("324.00"), None)])

    def test_a_month_is_entered_once_and_all_or_none(self):
        self.september()
        r = self.enter("2026-09", [{"account": self.a2, "total": "10"}])
        self.assertIn("already has a bill for Sep 2026", r.data["detail"])
        r = self.enter("2026-10", [
            {"account": self.a1, "total": "100"},
            {"account": self.a2, "total": "abc"}])
        self.assertIn("is not a number", r.data["detail"])
        self.assertIn("Nothing was saved", r.data["detail"])
        self.assertEqual(BillCharge.objects.filter(
            period=date(2026, 10, 1)).count(), 0)
        self.assertIn("not started", self.enter(
            "2026-11", [{"account": self.a1, "total": "5"}]).data["detail"])
        self.assertIn("at least one", self.enter(
            "2026-10", [{"account": self.a1, "total": ""}]).data["detail"])

    def test_a_providers_batch_goes_on_one_voucher(self):
        self.september()
        groups = self.c.get("/api/v1/bills/to-pay").data["groups"]
        self.assertEqual([(g["provider"], g["count"], g["total"])
                          for g in groups],
                         [("Dhiraagu", 2, D("972.00")),
                          ("STELCO", 1, D("12500.00"))])
        ids = [b["payable"] for b in groups[0]["bills"]]
        # they are on Finance's payables list too, by account
        self.client.force_authenticate(self.finance)
        rows = self.client.get("/api/v1/finance/payables").data["payables"]
        self.assertEqual(sorted((x["ref"], x["cost_head"]) for x in rows)[0],
                         ("UTL-001", "Phone / utility bill"))
        pv = self.client.post("/api/v1/payment-vouchers",
                              {"payable_ids": ids}, format="json")
        self.assertEqual(pv.status_code, 201, pv.data)
        self.assertEqual((pv.data["total"], len(pv.data["lines"])),
                         (D("972.00"), 2))
        ref = pv.data["ref"]
        g = self.c.get("/api/v1/bills/to-pay?provider=dhiraagu").data["groups"]
        self.assertEqual((g[0]["bills"][0]["voucher"], g[0]["free_total"]),
                         (ref, D("0")))
        self.voucher_action(ref, "submit", self.finance)
        self.voucher_action(ref, "approve", self.signatory)
        for pid in ids:
            r = self.voucher_action(ref, "settle-payable", self.finance,
                                    payable_id=pid, payment_ref="TRF-55")
            self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(sorted(BillCharge.objects.filter(
            account__provider="Dhiraagu").values_list("status", "paid_ref")),
            [("PAID", "TRF-55"), ("PAID", "TRF-55")])
        self.assertEqual([g["provider"] for g in
                          self.c.get("/api/v1/bills/to-pay").data["groups"]],
                         ["STELCO"])
        x = self.c.get("/api/v1/bills/to-pay?export=xlsx")
        self.assertIn("spreadsheet", x["Content-Type"])
        # the account's own page keeps the history
        d = self.c.get("/api/v1/bills/accounts/UTL-001").data
        self.assertEqual([(h["period_label"], h["status"])
                          for h in d["history"]], [("Sep 2026", "PAID")])

    def test_a_bill_entered_wrongly_is_cancelled_and_entered_again(self):
        self.september()
        c = BillCharge.objects.get(account_id=self.a2)
        url = f"/api/v1/bills/charges/{c.id}/cancel"
        self.assertIn("Say why", self.c.post(url, {}, format="json")
                      .data["detail"])
        self.assertEqual(self.c.post(url, {"reason": "Typed 324 for 234"},
                                     format="json").status_code, 200)
        self.assertEqual(Payable.objects.get(bill_charge=c).status,
                         "CANCELLED")
        self.assertEqual(sum(x.amount for x in CostPosting.objects.filter(
            bill_charge=c, state="INCURRED")), D("0.00"))
        r = self.enter("2026-09", [{"account": self.a2, "total": "234"}])
        self.assertEqual(r.status_code, 201, r.data)
        # on a voucher, it comes off the voucher first
        live = BillCharge.objects.get(account_id=self.a2, status="RAISED")
        self.client.force_authenticate(self.finance)
        pv = self.client.post("/api/v1/payment-vouchers",
                              {"payable_ids": [live.payable.id]},
                              format="json").data["ref"]
        r = self.c.post(f"/api/v1/bills/charges/{live.id}/cancel",
                        {"reason": "x"}, format="json")
        self.assertIn(f"on voucher {pv}", r.data["detail"])

    def test_bills_reach_the_books_through_their_posting_rule(self):
        from . import brand
        brand.invalidate()
        self.addCleanup(brand.invalidate)
        bank = CompanyBankAccount.objects.create(label="BML MVR",
                                                 currency="MVR")
        ledger.setup_standard_chart(self.finance)
        self.september()
        r = posting.run(["utilities"], self.finance, commit=True)[0]
        self.assertEqual((r["post"], r["held"]), (3, []))

        def bal(code):
            return ledger.balance_of(LedgerAccount.objects.get(code=code))
        # 600 + 300 of phone, 12,500 of electricity, 72 of GST
        self.assertEqual((bal("6330"), bal("6310"), bal("1430"), bal("2010")),
                         (D("900.00"), D("12500.00"), D("72.00"),
                          D("-13472.00")))
        c = BillCharge.objects.get(account_id=self.a3)
        self.client.force_authenticate(self.finance)
        pv = self.client.post("/api/v1/payment-vouchers",
                              {"payable_ids": [c.payable.id]},
                              format="json").data["ref"]
        self.voucher_action(pv, "submit", self.finance)
        self.voucher_action(pv, "approve", self.signatory)
        Document.objects.filter(ref=pv).update(debit_account=bank)
        self.voucher_action(pv, "settle-payable", self.finance,
                            payable_id=c.payable.id, payment_ref="TRF-9")
        with mock.patch("core.ledger.timezone.localdate",
                        return_value=TODAY):
            r = posting.run(["utilities"], self.finance, commit=True)[0]
        self.assertEqual((r["post"], r["same"], r["held"]), (1, 3, []))
        self.assertEqual(bal("2010"), D("-972.00"))


class AllowanceTests(BillsBase):
    """A phone has a person and an allowance the company bears; what the
    bill runs over it comes off that person's salary."""

    def setUp(self):
        super().setUp()
        from .models import Employee, EmployeeSiteAllocation
        self.emp = Employee.objects.create(
            emp_no="EMP-7301", full_name="Hassan Manik", basic_pay=12000,
            currency="MVR", join_date=date(2026, 1, 1))
        EmployeeSiteAllocation.objects.create(
            employee=self.emp, site=self.site, from_date=date(2026, 1, 1))
        self.acct = self.account(emp_no="emp-7301", label="",
                                 site=self.site.id, monthly_limit="500").data

    def test_the_person_and_the_allowance_are_on_the_account(self):
        self.assertEqual((self.acct["employee"], self.acct["label"],
                          self.acct["employee_name"],
                          self.acct["monthly_limit"]),
                         (self.emp.id, "Hassan Manik",
                          "EMP-7301 · Hassan Manik", D("500.00")))
        self.assertIn("no employee", self.account(
            account_no="7770000", emp_no="EMP-0000").data["detail"])
        r = self.c.get("/api/v1/bills/people?q=hassan").data["people"]
        self.assertEqual([(x["emp_no"], x["name"]) for x in r],
                         [("EMP-7301", "Hassan Manik")])
        # pasted in bulk, an employee number ties the person
        r = self.c.post("/api/v1/bills/accounts", {
            "provider": "Ooredoo", "kind": "MOBILE", "site": self.site.id,
            "lines": "9605555, EMP-7301, 300"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        a = BillAccount.objects.get(account_no="9605555")
        self.assertEqual((a.employee, a.label, a.monthly_limit),
                         (self.emp, "Hassan Manik", D("300.00")))

    def test_what_runs_over_the_allowance_comes_off_his_salary(self):
        from . import payroll
        r = self.enter("2026-09", [{"account": self.acct["id"],
                                    "total": "648"}])
        self.assertEqual(r.status_code, 201, r.data)
        c = BillCharge.objects.get()
        self.assertEqual((c.recover_amount, c.recover_from, c.deduct_year,
                          c.deduct_month), (D("148.00"), self.emp, 2026, 9))
        # the provider is still owed the whole bill …
        self.assertEqual(c.payable.amount, D("648.00"))
        # … the company's cost is the allowance, with its share of the GST
        rows = CostPosting.objects.filter(bill_charge=c, state="INCURRED")
        self.assertEqual(sorted((x.cost_head.code, x.amount) for x in rows),
                         [("INPUT_GST", D("37.04")), ("TELECOM", D("462.96"))])
        # … and payroll recovers the rest, with whatever advance he has
        self.assertEqual(payroll.deductions_for(self.emp, 2026, 9),
                         {"advance": D("148.00"), "loan": D("0")})
        self.assertEqual(payroll.deductions_for(self.emp, 2026, 10)["advance"],
                         D("0"))
        d = self.c.get("/api/v1/bills/sheet?period=2026-09").data
        rec = d["rows"][0]["charge"]["recovery"]
        self.assertEqual((rec["amount"], rec["from"], rec["note"],
                          rec["deducted"]),
                         (D("148.00"), "Hassan Manik",
                          "comes off the Sep 2026 salary", False))
        self.assertEqual(len(self.c.get("/api/v1/bills/recoveries")
                             .data["recoveries"]), 1)
        # under the allowance, nothing is recovered
        self.enter("2026-10", [{"account": self.acct["id"], "total": "400"}])
        self.assertEqual(BillCharge.objects.get(
            period=date(2026, 10, 1)).recover_amount, D("0"))
        # a cancelled bill takes its recovery with it
        self.c.post(f"/api/v1/bills/charges/{c.id}/cancel",
                    {"reason": "Wrong number"}, format="json")
        self.assertEqual(payroll.deductions_for(self.emp, 2026, 9)["advance"],
                         D("0"))

    def test_a_prepaid_number_is_a_recharge_with_nothing_to_recover(self):
        from . import payroll
        r = self.account(account_no="7909090", emp_no="EMP-7301",
                         site=self.site.id, prepaid=True, fixed_amount="300",
                         monthly_limit="100")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["prepaid"], r.data["fixed_amount"]),
                         (True, D("300.00")))
        d = self.c.get("/api/v1/bills/sheet?period=2026-10").data
        row = next(x for x in d["rows"] if x["account_no"] == "7909090")
        # the sheet offers the recharge, due as the month starts
        self.assertEqual((row["fixed_amount"], str(row["usual_due"])),
                         (D("300.00"), "2026-10-01"))
        self.enter("2026-10", [{"account": r.data["id"], "total": "300"}])
        c = BillCharge.objects.get(account_id=r.data["id"])
        self.assertEqual((c.recover_amount, c.recover_from, c.due_date),
                         (D("0"), None, date(2026, 10, 1)))
        self.assertEqual(payroll.deductions_for(self.emp, 2026, 10)["advance"],
                         D("0"))
        # the whole recharge is the company's cost
        self.assertEqual(sum(x.amount for x in CostPosting.objects.filter(
            bill_charge=c, state="INCURRED")), D("300.00"))
        # pasted in bulk as prepaid, the third column is the recharge
        r = self.c.post("/api/v1/bills/accounts", {
            "provider": "Ooredoo", "kind": "MOBILE", "site": self.site.id,
            "prepaid": True, "lines": "9606666, Driver, 150"}, format="json")
        a = BillAccount.objects.get(account_no="9606666")
        self.assertEqual((a.prepaid, a.fixed_amount, a.monthly_limit),
                         (True, D("150.00"), None))

    def test_a_month_already_drawn_up_is_left_and_the_next_one_takes_it(self):
        from .models import PayrollLine, PayrollRun
        run = PayrollRun.objects.create(
            ref="PAY-VKR-2026-09", site=self.site, kind="MONTHLY",
            currency="MVR", year=2026, month=9, working_days=26,
            status="LOCKED", created_by=self.finance)
        self.enter("2026-09", [{"account": self.acct["id"], "total": "648"}])
        c = BillCharge.objects.get()
        self.assertEqual((c.deduct_year, c.deduct_month), (2026, 10))
        rec = self.c.get("/api/v1/bills/recoveries").data["recoveries"][0]
        self.assertIn("comes off the Oct 2026 salary",
                      rec["recovery"]["note"])
        # once October's run is locked with him on it, the bill is fixed
        octo = PayrollRun.objects.create(
            ref="PAY-VKR-2026-10", site=self.site, kind="MONTHLY",
            currency="MVR", year=2026, month=10, working_days=27,
            status="LOCKED", created_by=self.finance)
        PayrollLine.objects.create(run=octo, employee=self.emp,
                                   site=self.site, basic_pay=12000,
                                   advance=D("148"))
        r = self.c.post(f"/api/v1/bills/charges/{c.id}/cancel",
                        {"reason": "x"}, format="json")
        self.assertIn("already been deducted on payroll PAY-VKR-2026-10",
                      r.data["detail"])
        self.assertEqual(run.status, "LOCKED")

    def test_in_the_books_the_excess_is_owed_by_him_not_a_cost(self):
        from . import brand
        brand.invalidate()
        self.addCleanup(brand.invalidate)
        ledger.setup_standard_chart(self.finance)
        self.enter("2026-09", [{"account": self.acct["id"], "total": "648"}])
        r = posting.run(["utilities"], self.finance, commit=True)[0]
        self.assertEqual((r["post"], r["held"]), (1, []))

        def bal(code):
            return ledger.balance_of(LedgerAccount.objects.get(code=code))
        self.assertEqual((bal("6330"), bal("1430"), bal("1350"), bal("2010")),
                         (D("462.96"), D("37.04"), D("148.00"),
                          D("-648.00")))

