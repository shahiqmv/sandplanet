"""Rent the company pays: a register of rentals, each period's rent raised
by itself as a payable Finance puts on a voucher (owner 2026-10-02)."""
from datetime import date
from decimal import Decimal as D
from unittest import mock

from django.core.management import call_command
from rest_framework.test import APIClient

from . import ledger, posting, rent, vouchers
from .models import (CompanyBankAccount, CostHead, CostPosting, Document,
                     LedgerAccount, Payable, RentContract, RentDue, User)
from .tests import make_user
from .tests_vouchers import VoucherBase

TODAY = date(2026, 10, 2)


class RentBase(VoucherBase):
    def setUp(self):
        super().setUp()
        # the tests stand on a fixed day, so they read the same every day
        p = mock.patch("core.rent._today", return_value=TODAY)
        p.start()
        self.addCleanup(p.stop)
        self.ho = vouchers.ho_site()
        self.c = APIClient()
        self.c.force_authenticate(self.finance)

    def rental(self, **kw):
        body = {"title": "Head office, H. Sunny Villa, 3rd floor",
                "kind": "OFFICE", "landlord": "Ahmed Ali", "site": self.ho.id,
                "amount": "15000", "start_date": "2026-01-01"}
        body.update(kw)
        return self.c.post("/api/v1/rent/contracts", body, format="json")

    def cost(self, due_id, state):
        return sum((r.amount for r in CostPosting.objects.filter(
            rent_due_id=due_id, state=state)), D("0"))


class RaisingTests(RentBase):
    def test_a_rental_raises_its_current_period_as_a_payable(self):
        r = self.rental()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["ref"], r.data["cost_head_name"],
                          r.data["frequency_label"]),
                         ("RENT-001", "Rent", "Monthly"))
        # under way since January: only this month is raised — the earlier
        # ones were paid before the rental was put into Planet
        self.assertEqual([(d["period"], d["total"], d["status"])
                          for d in r.data["dues"]],
                         [("Oct 2026", D("15000.00"), "RAISED")])
        due = RentDue.objects.get()
        p = Payable.objects.get()
        self.assertEqual((p.rent_due, p.document, p.vendor, p.amount,
                          p.due_date, p.status, p.site),
                         (due, None, "Ahmed Ali", D("15000.00"),
                          date(2026, 10, 1), "OUTSTANDING", self.ho))
        self.assertEqual(p.ref_label, "RENT-001")
        # the cost is in Planet's cost ledger for the month it pays for
        rows = CostPosting.objects.filter(rent_due=due)
        self.assertEqual(sorted(rows.values_list("state", flat=True)),
                         ["COMMITTED", "INCURRED"])
        self.assertEqual({(x.source, x.posted_on, x.cost_head.code, x.site)
                          for x in rows},
                         {("RENT", date(2026, 10, 1), "RENT", self.ho)})
        # the next one shows as coming
        self.assertEqual((r.data["next"]["period"],
                          str(r.data["next"]["due_date"])),
                         ("Nov 2026", "2026-11-01"))

    def test_the_daily_job_raises_each_period_once(self):
        self.rental()
        call_command("rent_dues", stdout=open("/dev/null", "w"))
        self.assertEqual(RentDue.objects.count(), 1)       # nothing new yet
        # a week before the first of November, November comes up
        self.assertEqual(rent.raise_dues(today=date(2026, 10, 24)), [])
        made = rent.raise_dues(today=date(2026, 10, 25))
        self.assertEqual([(d.period_start, d.due_date) for d in made],
                         [(date(2026, 11, 1), date(2026, 11, 1))])
        self.assertEqual(rent.raise_dues(today=date(2026, 10, 26)), [])
        self.assertEqual(Payable.objects.filter(
            status="OUTSTANDING").count(), 2)

    def test_dues_from_an_earlier_date_catches_up(self):
        r = self.rental(dues_from="2026-08-01")
        self.assertEqual([d["period"] for d in r.data["dues"]],
                         ["Oct 2026", "Sep 2026", "Aug 2026"])
        self.assertEqual(r.data["overdue_count"], 3)

    def test_quarterly_in_arrears_on_an_agreed_day(self):
        r = self.rental(title="Yard at Thilafushi", kind="LAND",
                        frequency="QUARTERLY", in_advance=False, due_day=25,
                        start_date="2026-07-01", dues_from="2026-07-01",
                        amount="30000")
        # Jul–Sep fell due on 25 Sep; Oct–Dec is not up until December
        self.assertEqual([(d["period"], str(d["due_date"]))
                          for d in r.data["dues"]],
                         [("01 Jul 2026 – 30 Sep 2026", "2026-09-25")])
        self.assertEqual(str(r.data["next"]["due_date"]), "2026-12-25")

    def test_an_agreed_increase_and_a_last_part_month(self):
        r = self.rental(steps=[{"from": "2026-11-01", "amount": "16500"}],
                        end_date="2026-12-10")
        c = RentContract.objects.get()
        self.assertEqual(r.data["current_amount"], D("15000.00"))
        made = rent.raise_dues(today=date(2026, 12, 1))
        self.assertEqual([(d.period_start, d.amount, d.period_end)
                          for d in made],
                         [(date(2026, 11, 1), D("16500.00"),
                           date(2026, 11, 30)),
                          # ten days of December's thirty-one
                          (date(2026, 12, 1), D("5322.58"),
                           date(2026, 12, 10))])
        # nothing after the end
        self.assertEqual(rent.raise_dues(today=date(2027, 3, 1)), [])
        self.assertIsNone(rent.contract_dict(
            c, today=date(2027, 3, 1))["next"])

    def test_gst_and_dollars(self):
        r = self.rental(title="Excavator on hire", kind="VEHICLE",
                        landlord="Heavy Load Pvt Ltd", gst_applicable=True,
                        site=self.site.id, amount="1000", currency="USD",
                        cost_head=CostHead.objects.get(code="PLANT").id)
        self.assertEqual(r.status_code, 201, r.data)
        d = r.data["dues"][0]
        self.assertEqual((d["amount"], d["gst"], d["total"], d["currency"]),
                         (D("1000.00"), D("80.00"), D("1080.00"), "USD"))
        p = Payable.objects.get()
        self.assertEqual((p.amount, vouchers.payable_currency(p)),
                         (D("1080.00"), "USD"))
        # the GST sits in the recoverable pool at head office
        gst = CostPosting.objects.get(rent_due_id=d["id"], state="INCURRED",
                                      cost_head__code="INPUT_GST")
        self.assertEqual((gst.amount, gst.site, gst.is_stock_pool),
                         (D("80.00"), self.ho, True))

    def test_what_a_rental_needs(self):
        for patch, msg in (({"title": ""}, "what is rented"),
                           ({"landlord": ""}, "landlord"),
                           ({"amount": "0"}, "rent per period"),
                           ({"site": None}, "site"),
                           ({"start_date": ""}, "starts"),
                           ({"end_date": "2025-01-01"}, "ends before"),
                           ({"due_day": 31}, "between 1 and 28"),
                           ({"currency": "EUR"}, "MVR or USD")):
            self.assertIn(msg, self.rental(**patch).data["detail"])
        self.assertEqual(RentContract.objects.count(), 0)


class PayingTests(RentBase):
    def setUp(self):
        super().setUp()
        self.rental()
        self.due = RentDue.objects.get()
        self.payable = self.due.payable

    def voucher(self):
        self.client.force_authenticate(self.finance)
        r = self.client.post("/api/v1/payment-vouchers",
                             {"payable_ids": [self.payable.id]},
                             format="json")
        assert r.status_code == 201, r.data
        return r.data

    def test_finance_finds_it_puts_it_on_a_voucher_and_pays_it(self):
        self.client.force_authenticate(self.finance)
        rows = self.client.get("/api/v1/finance/payables").data["payables"]
        self.assertEqual([(x["ref"], x["payee"], x["cost_head"],
                           x["amount"]) for x in rows],
                         [("RENT-001", "Ahmed Ali", "Rent", D("15000.00"))])
        self.assertIn("Rent · Oct 2026", rows[0]["purpose"])
        self.assertEqual(rows[0]["rent_contract"], self.due.contract_id)
        pv = self.voucher()
        self.assertEqual((pv["total"], pv["lines"][0]["ref"]),
                         (D("15000.00"), "RENT-001"))
        self.assertIn("Rent · Oct 2026", pv["lines"][0]["purpose"])
        self.voucher_action(pv["ref"], "submit", self.finance)
        r = self.voucher_action(pv["ref"], "approve", self.signatory)
        self.assertEqual(r.data["status"], "APPROVED")
        r = self.voucher_action(pv["ref"], "settle-payable", self.finance,
                                payable_id=self.payable.id,
                                payment_ref="TRF-7781")
        self.assertEqual(r.status_code, 200, r.data)
        self.due.refresh_from_db()
        self.payable.refresh_from_db()
        self.assertEqual((self.due.status, self.due.paid_on,
                          self.due.paid_ref, self.payable.status),
                         ("PAID", TODAY, "TRF-7781", "SETTLED"))
        self.assertEqual(self.cost(self.due.id, "PAID"), D("15000.00"))
        d = self.c.get("/api/v1/rent/contracts/RENT-001").data
        self.assertEqual((d["dues"][0]["status"], d["dues"][0]["voucher"],
                          d["open_count"]), ("PAID", pv["ref"], 0))

    def test_a_due_is_cancelled_and_not_raised_again_by_itself(self):
        url = f"/api/v1/rent/dues/{self.due.id}"
        self.assertIn("Say why", self.c.post(f"{url}/cancel", {},
                                             format="json").data["detail"])
        # on a voucher, it comes off the voucher first
        pv = self.voucher()
        r = self.c.post(f"{url}/cancel", {"reason": "Wrong amount"},
                        format="json")
        self.assertIn(f"on voucher {pv['ref']}", r.data["detail"])
        Document.objects.filter(ref=pv["ref"]).update(status="CANCELLED")
        r = self.c.post(f"{url}/cancel", {"reason": "Wrong amount"},
                        format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.payable.refresh_from_db()
        self.assertEqual(self.payable.status, "CANCELLED")
        self.assertEqual((self.cost(self.due.id, "INCURRED"),
                          self.cost(self.due.id, "COMMITTED")),
                         (D("0.00"), D("0.00")))
        # the daily job leaves that month alone …
        self.assertEqual(rent.raise_dues(today=TODAY), [])
        # … until, the rent corrected, it is raised again on purpose
        self.c.patch("/api/v1/rent/contracts/RENT-001", {"amount": "14000"},
                     format="json")
        r = self.c.post(f"{url}/raise-again", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(sorted((d["status"], d["total"])
                                for d in r.data["dues"]),
                         [("CANCELLED", D("15000.00")),
                          ("RAISED", D("14000.00"))])
        live = RentDue.objects.get(status="RAISED")
        self.assertEqual(live.total, D("14000.00"))
        self.assertIn("already has a due", self.c.post(
            f"{url}/raise-again", {}, format="json").data["detail"])

    def test_an_ended_rental_raises_nothing_and_a_period_can_go_early(self):
        r = self.c.post("/api/v1/rent/contracts/RENT-001/raise",
                        {"ahead": True}, format="json")
        self.assertEqual((r.data["raised"], r.data["dues"][0]["period"]),
                         (1, "Nov 2026"))
        self.c.patch("/api/v1/rent/contracts/RENT-001", {"status": "ENDED"},
                     format="json")
        self.assertEqual(rent.raise_dues(today=date(2027, 1, 5)), [])
        r = self.c.post("/api/v1/rent/contracts/RENT-001/raise", {},
                        format="json")
        self.assertIn("has ended", r.data["detail"])
        # ended rentals drop off the list unless asked for
        self.assertEqual(self.c.get("/api/v1/rent/contracts")
                         .data["contracts"], [])
        self.assertEqual(len(self.c.get("/api/v1/rent/contracts?status=all")
                             .data["contracts"]), 1)

    def test_who_may_see_and_who_may_change(self):
        sig = APIClient()
        sig.force_authenticate(self.signatory)
        self.assertEqual(sig.get("/api/v1/rent/contracts").status_code, 200)
        self.assertEqual(sig.get(
            "/api/v1/rent/contracts/RENT-001").status_code, 200)
        self.assertEqual(sig.post("/api/v1/rent/contracts", {},
                                  format="json").status_code, 403)
        self.assertEqual(sig.post("/api/v1/rent/raise", {},
                                  format="json").status_code, 403)
        self.assertEqual(sig.post(f"/api/v1/rent/dues/{self.due.id}/cancel",
                                  {"reason": "x"},
                                  format="json").status_code, 403)
        pm = APIClient()
        pm.force_authenticate(make_user("pm7", User.Role.PM))
        self.assertEqual(pm.get("/api/v1/rent/contracts").status_code, 403)


class RentInTheBooksTests(RentBase):
    def test_rent_posts_as_a_cost_and_a_payable_then_a_payment(self):
        from . import brand
        brand.invalidate()
        self.addCleanup(brand.invalidate)
        bank = CompanyBankAccount.objects.create(label="BML MVR",
                                                 currency="MVR")
        ledger.setup_standard_chart(self.finance)
        self.rental()
        due = RentDue.objects.get()
        r = posting.run(["rent"], self.finance, commit=True)[0]
        self.assertEqual((r["post"], r["held"]), (1, []))

        def bal(code):
            return ledger.balance_of(LedgerAccount.objects.get(code=code))
        self.assertEqual((bal("6220"), bal("2010")),
                         (D("15000.00"), D("-15000.00")))
        # paid off a voucher drawn on the rufiyaa account
        self.client.force_authenticate(self.finance)
        pv = self.client.post("/api/v1/payment-vouchers",
                              {"payable_ids": [due.payable.id]},
                              format="json").data["ref"]
        self.voucher_action(pv, "submit", self.finance)
        self.voucher_action(pv, "approve", self.signatory)
        Document.objects.filter(ref=pv).update(debit_account=bank)
        self.voucher_action(pv, "settle-payable", self.finance,
                            payable_id=due.payable.id, payment_ref="TRF-1")
        with mock.patch("core.ledger.timezone.localdate",
                        return_value=TODAY):
            r = posting.run(["rent"], self.finance, commit=True)[0]
        self.assertEqual((r["post"], r["same"], r["held"]), (1, 1, []))
        self.assertEqual(bal("2010"), D("0.00"))
        self.assertEqual(ledger.balance_of(
            LedgerAccount.objects.get(bank_account=bank)), D("-15000.00"))
