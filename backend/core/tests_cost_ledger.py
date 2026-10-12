"""The project cost ledger counts everything once (owner 2026-10-12).

Three gaps the cost-control page showed: locked payroll wiped by a later run
of the same month, salaries never reaching Paid, and imports never reaching
Incurred because the store issue that would post them is not how goods move.
"""
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.test import TestCase
from rest_framework.test import APIClient

from . import payroll, staff_cost
from .models import (CostPosting, Document, DocumentRevision, Employee,
                     EmployeeSiteAllocation, ManpowerCategory, Site,
                     TimesheetMonth, User)
from .tests import make_user
from .tests_imports import IprBase


def labour(site, ccy, state="INCURRED", year=2026, month=5):
    return CostPosting.objects.filter(
        site=site, source="STAFF", currency=ccy, state=state,
        staff_year=year, staff_month=month).aggregate(
        t=Sum("amount"))["t"] or Decimal("0")


class PayrollLedgerTests(TestCase):
    def setUp(self):
        self.hr = make_user("cl_hr", User.Role.HO_HR)
        self.fin = make_user("cl_fin", User.Role.FINANCE)
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        Site.objects.create(code="MLE", name="Head Office", is_head_office=True,
                            status=Site.Status.ACTIVE)
        TimesheetMonth.objects.create(site=self.site, year=2026, month=5,
                                      status="LOCKED")
        cat = ManpowerCategory.objects.create(list_type="DPR", grp="LABOUR",
                                              name="Mason", sort_order=1)
        self.mvr = Employee.objects.create(
            emp_no="EMP-0001", full_name="Kumar", job_category=cat,
            basic_pay=Decimal("6200"), currency="MVR",
            join_date=date(2026, 1, 1))
        self.usd = Employee.objects.create(
            emp_no="EMP-0002", full_name="Rahul", job_category=cat,
            basic_pay=Decimal("1000"), usd_basic_pay=Decimal("1000"),
            currency="USD", join_date=date(2026, 1, 1))
        for e in (self.mvr, self.usd):
            EmployeeSiteAllocation.objects.create(
                employee=e, site=self.site, from_date=date(2026, 1, 1))
        from .models import Attendance
        for d in range(1, 32):
            day = date(2026, 5, d)
            if day.isoweekday() in self.site.working_days:
                Attendance.objects.create(employee=self.mvr, site=self.site,
                                          day=day, remark="PRESENT",
                                          normal_hours=8)

    def _run(self, currency):
        run = payroll.generate_run(
            site=self.site if currency == "MVR" else None, currency=currency,
            year=2026, month=5, working_days=31, actor=self.hr)
        run.round_to = 0
        run.save()
        return run

    def test_a_second_run_of_the_month_keeps_the_first_runs_payroll(self):
        """The USD run used to wipe the site's rufiyaa payroll: SJR lost
        USD 153,000 of August salaries that way."""
        mvr = self._run("MVR")
        payroll.lock_run(mvr, self.hr)
        self.assertEqual(labour(self.site, "MVR"), Decimal("6200.00"))
        usd = self._run("USD")
        payroll.lock_run(usd, self.hr)
        self.assertEqual(labour(self.site, "MVR"), Decimal("6200.00"))
        self.assertEqual(labour(self.site, "USD"), Decimal("1000.00"))

    def test_reopening_and_relocking_a_run_counts_it_once_in_its_currency(self):
        """Approved three times on 14 September, the USD run tripled its
        dollars and took the same numbers off the rufiyaa."""
        payroll.lock_run(self._run("MVR"), self.hr)
        usd = self._run("USD")
        for _ in range(3):
            payroll.lock_run(usd, self.hr)
            run, err = payroll.reopen_run(usd, self.hr)
            self.assertIsNone(err)
            usd.refresh_from_db()
            self.assertEqual(labour(self.site, "USD"), Decimal("0"))
            self.assertEqual(labour(self.site, "MVR"), Decimal("6200.00"))
        payroll.lock_run(usd, self.hr)
        self.assertEqual(labour(self.site, "USD"), Decimal("1000.00"))
        self.assertEqual(labour(self.site, "MVR"), Decimal("6200.00"))

    def test_the_lock_replaces_the_estimate_and_an_attendance_reopen_spares_it(self):
        staff_cost.post_staff_cost(self.site, 2026, 5, self.hr)   # estimate
        est = labour(self.site, "MVR")
        self.assertGreater(est, 0)
        payroll.lock_run(self._run("MVR"), self.hr)
        self.assertEqual(labour(self.site, "MVR"), Decimal("6200.00"))
        # HR reopens the attendance month: only an estimate would go
        staff_cost.reverse_staff_cost(self.site, 2026, 5, self.hr)
        self.assertEqual(labour(self.site, "MVR"), Decimal("6200.00"))

    def test_paying_the_run_posts_its_salaries_as_paid(self):
        run = self._run("MVR")
        payroll.lock_run(run, self.hr)
        doc, err = payroll.raise_payroll_pyr(run, self.hr)
        self.assertIsNone(err, err)
        run.refresh_from_db()
        doc.status = "AUTHORISED"
        doc.save()
        net = payroll.compute_line(run.lines.first())["net"]
        c = APIClient()
        c.force_authenticate(self.fin)
        r = c.post(f"/api/v1/documents/{doc.ref}/actions/pay",
                   {"amount_paid": str(net), "payment_ref": "CASH-1"},
                   format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(labour(self.site, "MVR", "PAID"), net)
        # still counted once as Incurred
        self.assertEqual(labour(self.site, "MVR"), Decimal("6200.00"))

    def test_a_salary_transferred_person_by_person_is_paid_as_each_goes(self):
        usd = self._run("USD")
        payroll.lock_run(usd, self.hr)
        doc, err = payroll.raise_payroll_pyr(usd, self.hr)
        self.assertIsNone(err, err)
        usd.refresh_from_db()
        made, err = payroll.raise_salary_payables(usd, self.hr)
        self.assertEqual(made, 1, err)
        payable = doc.payables.get()
        payroll.settle_salary_payable(payable, self.fin, "TT-1")
        self.assertEqual(labour(self.site, "USD", "PAID"), payable.amount)


class ClearedImportTests(IprBase):
    """10 pumps at USD 100 at 15 = MVR 15,000; 6 for the project, 4 for
    general stock; MVR 1,500 of charges on the shipment."""

    def _cleared(self):
        ref = self.create_and_authorise()
        self.client.force_authenticate(self.ho)
        sid = self.client.post(f"/api/v1/ipr/{ref}/shipments", {"mode": "SEA"},
                               format="json").data["shipments"][0]["id"]
        self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/charges",
                         {"freight": "1000", "customs_duty": "500"},
                         format="json")
        irn = self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/receive",
                               {"location": "Bay 3"}, format="json").data
        r = self.client.post(f"/api/v1/irn/{irn['ref']}/post", {},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        return ref, sid

    def _site_incurred(self):
        return CostPosting.objects.filter(
            site=self.site, state="INCURRED").aggregate(
            t=Sum("amount"))["t"] or Decimal("0")

    def test_a_cleared_shipment_is_incurred_at_the_projects_site(self):
        ref, sid = self._cleared()
        # 6 of 10 at landed 16,500 → 9,900 at the project's site
        self.assertEqual(self._site_incurred(), Decimal("9900.00"))
        # general stock waits for a store issue: nothing at Head Office
        self.assertFalse(CostPosting.objects.filter(
            state="INCURRED", source="IPR").exclude(site=self.site).exists())
        # a charge entered after clearance follows into the cost
        self.client.post(f"/api/v1/ipr/{ref}/shipments/{sid}/charges",
                         {"freight": "2500", "customs_duty": "500"},
                         format="json")   # charges 3,000 → landed 18,000
        self.assertEqual(self._site_incurred(), Decimal("10800.00"))

    def test_project_goods_issued_through_the_store_are_still_counted_once(self):
        from .imports import receive_store_issue_line
        from .models import StockLot, StoreIssue, StoreIssueLine
        self._cleared()
        lot = StockLot.objects.get(project=self.project)
        doc = Document.objects.create(doc_type="SIN", ref="SIN-T-1",
                                      site=self.site, doc_date=date.today(),
                                      status="ISSUED", created_by=self.ho)
        DocumentRevision.objects.create(document=doc, rev_label="R0",
                                        payload={}, created_by=self.ho)
        sin = StoreIssue.objects.create(document=doc, to_site=self.site,
                                        to_project=self.project)
        sil = StoreIssueLine.objects.create(issue=sin, lot=lot, qty=2,
                                            unit_landed_cost=lot.unit_landed_cost)
        lot.qty_on_hand -= 2
        lot.qty_in_transit = 2
        lot.save()
        receive_store_issue_line(sil, 2, self.site, doc, self.ho)
        self.assertEqual(CostPosting.objects.filter(
            site=self.site, source="STORE_ISSUE").aggregate(
            t=Sum("amount"))["t"], Decimal("3300.00"))    # 2 @ 1,650
        self.assertEqual(self._site_incurred(), Decimal("9900.00"))

    def test_the_repair_posts_cleared_shipments_already_on_file(self):
        """Shipments cleared before the rule have nothing posted; the repair
        command catches them up and is a no-op the second time."""
        from django.core.management import call_command
        self._cleared()
        CostPosting.objects.filter(source="IPR", state="INCURRED").delete()
        self.assertEqual(self._site_incurred(), Decimal("0"))
        make_user("admin_cl", User.Role.ADMIN)
        call_command("repair_cost_ledger", apply=True, actor="admin_cl",
                     stdout=open("/dev/null", "w"))
        self.assertEqual(self._site_incurred(), Decimal("9900.00"))
        call_command("repair_cost_ledger", apply=True, actor="admin_cl",
                     stdout=open("/dev/null", "w"))
        self.assertEqual(self._site_incurred(), Decimal("9900.00"))


class RepairLabourTests(PayrollLedgerTests):
    """The August state on production, rebuilt: a run's payroll wiped by a
    later lock and a USD reversal booked in rufiyaa."""

    def test_the_repair_rebuilds_each_locked_runs_labour(self):
        from django.core.management import call_command
        mvr = self._run("MVR")
        payroll.lock_run(mvr, self.hr)
        usd = self._run("USD")
        payroll.lock_run(usd, self.hr)
        # what the old code left: the MVR payroll reversed, and a USD
        # posting "reversed" in rufiyaa
        live = CostPosting.objects.get(site=self.site, payroll_run=mvr)
        staff_cost.costing.post(
            site=self.site, cost_head=live.cost_head, state="INCURRED",
            source="STAFF", amount=-live.amount, currency="MVR",
            staff_year=2026, staff_month=5, reversal_of=live, actor=self.hr)
        u = CostPosting.objects.get(site=self.site, payroll_run=usd)
        staff_cost.costing.post(
            site=self.site, cost_head=u.cost_head, state="INCURRED",
            source="STAFF", amount=-u.amount, currency="MVR",
            staff_year=2026, staff_month=5, reversal_of=u, actor=self.hr)
        self.assertEqual(labour(self.site, "MVR"), Decimal("-1000.00"))
        make_user("admin_rl", User.Role.ADMIN)
        call_command("repair_cost_ledger", apply=True, actor="admin_rl",
                     stdout=open("/dev/null", "w"))
        self.assertEqual(labour(self.site, "MVR"), Decimal("6200.00"))
        self.assertEqual(labour(self.site, "USD"), Decimal("1000.00"))
        # a later attendance reopen leaves the rebuilt payroll alone
        staff_cost.reverse_staff_cost(self.site, 2026, 5, self.hr)
        self.assertEqual(labour(self.site, "MVR"), Decimal("6200.00"))

    # the base class's tests are not repeated here
    test_a_second_run_of_the_month_keeps_the_first_runs_payroll = None
    test_reopening_and_relocking_a_run_counts_it_once_in_its_currency = None
    test_the_lock_replaces_the_estimate_and_an_attendance_reopen_spares_it = None
    test_paying_the_run_posts_its_salaries_as_paid = None
    test_a_salary_transferred_person_by_person_is_paid_as_each_goes = None

