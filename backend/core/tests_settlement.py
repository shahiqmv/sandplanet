"""Final settlement for demobilised workers.

Modelled on the real case: twenty men left VKR with a last working day of 24
August, were only recorded on the system on the 29th, and were marked PRESENT
for four days in between. The whole of August was unpaid — the month's run had
never been generated (owner 2026-08-30).
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from .models import (Attendance, Document, Employee, EmployeeSiteAllocation,
                     ManpowerCategory, OvertimeRate, PayrollLine, PayrollRun,
                     SalaryAdvance, Site, User)
from .payroll import eligible_workers, lock_run
from .payroll_settlement import (generate_settlement, outstanding_balance,
                                 preview, register_conflicts, settled_through,
                                 unpaid_months)
from .tests import make_user


class SettlementTests(TestCase):
    def setUp(self):
        # Sat–Thu working week, Friday the rest day — VKR's own.
        self.site = Site.objects.create(code="STL", name="Settle site",
                                        status=Site.Status.ACTIVE,
                                        working_days=[6, 7, 1, 2, 3, 4])
        self.hr = make_user("hr_stl", User.Role.HO_HR)
        self.cat = ManpowerCategory.objects.create(name="Mason",
                                                   list_type="DPR",
                                                   sort_order=1)
        OvertimeRate.objects.create(category=self.cat, currency="MVR",
                                    rate_per_hour=Decimal("25"),
                                    applies_by_default=True)
        self.emp = self._worker("EMP-S1", Decimal("9300"))

    def _worker(self, no, basic, join=date(2026, 8, 1)):
        e = Employee.objects.create(
            emp_no=no, full_name=f"Worker {no}", basic_pay=basic,
            currency="MVR", job_category=self.cat, join_date=join,
            employment_type="CONTRACT", engagement_type="DIRECT")
        EmployeeSiteAllocation.objects.create(employee=e, site=self.site,
                                              from_date=join)
        return e

    def _mark(self, emp, days, remark="PRESENT", month=8):
        for d in days:
            Attendance.objects.get_or_create(
                employee=emp, site=self.site, day=date(2026, month, d),
                defaults={"remark": remark, "entered_by": self.hr})

    # ---- the cap ---------------------------------------------------------

    def test_the_last_working_day_caps_days_the_register_kept_marking(self):
        """The case exactly: marked to the 28th, really left on the 24th."""
        self._mark(self.emp, range(1, 29))          # 1–28 August
        rows = preview(self.site, [self.emp], date(2026, 8, 24))
        capped = rows[0]["months"][0]["days"]
        uncapped = preview(self.site, [self.emp], date(2026, 8, 28))
        self.assertLess(capped, uncapped[0]["months"][0]["days"])
        # 25, 26, 27 and 28 are all dropped.
        self.assertEqual(uncapped[0]["months"][0]["days"] - capped,
                         Decimal("4"))

    def test_days_marked_after_the_last_day_are_reported_not_swallowed(self):
        """The contradiction is the PM's to settle, not ours to hide — at
        VKR it was worth MVR 24,903."""
        self._mark(self.emp, range(1, 29))
        conflicts = register_conflicts(self.emp, self.site, date(2026, 8, 24))
        self.assertEqual(conflicts, [date(2026, 8, 25), date(2026, 8, 26),
                                     date(2026, 8, 27), date(2026, 8, 28)])
        self.assertEqual(preview(self.site, [self.emp],
                                 date(2026, 8, 24))[0]["conflicts"], conflicts)

    def test_a_settlement_pays_the_same_daily_rate_as_the_monthly_run(self):
        """A leaver must not be paid differently from the man beside him: the
        divisor stays the month's days, not the days he happened to work."""
        self._mark(self.emp, range(1, 25))
        run, msg = generate_settlement(
            site=self.site, employees=[self.emp],
            last_working_day=date(2026, 8, 24), reason="Demobilised",
            actor=self.hr)
        self.assertIsNone(msg, msg)
        line = run.lines.get()
        self.assertEqual(line.basic_pay, Decimal("9300"))
        self.assertEqual(run.working_days, 31)      # August, not days worked

    # ---- every unpaid month ---------------------------------------------

    def test_it_covers_every_month_still_unpaid_not_just_the_last(self):
        """A man leaving in August with July unlocked is owed both."""
        emp = self._worker("EMP-S2", Decimal("6200"), join=date(2026, 7, 1))
        self._mark(emp, range(1, 29), month=7)
        self._mark(emp, range(1, 25), month=8)
        months = unpaid_months(emp, self.site, date(2026, 8, 24))
        self.assertIn((2026, 7), months)
        self.assertIn((2026, 8), months)

    def test_a_locked_month_is_not_paid_again(self):
        emp = self._worker("EMP-S3", Decimal("6200"), join=date(2026, 7, 1))
        self._mark(emp, range(1, 29), month=7)
        run = PayrollRun.objects.create(site=self.site, currency="MVR",
                                        year=2026, month=7, working_days=31,
                                        status="LOCKED", created_by=self.hr)
        PayrollLine.objects.create(run=run, employee=emp, site=self.site,
                                   basic_pay=emp.basic_pay, days_worked=28)
        self.assertNotIn((2026, 7),
                         unpaid_months(emp, self.site, date(2026, 8, 24)))

    # ---- deductions ------------------------------------------------------

    def test_the_whole_loan_balance_is_recovered_not_one_installment(self):
        """After he flies there is nobody left to deduct from."""
        doc = Document.objects.create(doc_type="PYR", ref="PYR-STL-001",
                                      site=self.site, status="PAID",
                                      doc_date=date(2026, 8, 1),
                                      created_by=self.hr)
        SalaryAdvance.objects.create(document=doc, employee=self.emp,
                                     kind=SalaryAdvance.Kind.LOAN,
                                     amount=Decimal("6000"), months=6,
                                     period_year=2026, period_month=8)
        bal = outstanding_balance(self.emp)
        self.assertEqual(bal["loan"], Decimal("6000.00"))
        self._mark(self.emp, range(1, 25))
        row = preview(self.site, [self.emp], date(2026, 8, 24))[0]
        self.assertEqual(row["loan"], Decimal("6000.00"))
        self.assertEqual(row["net"], row["gross"] - Decimal("6000.00"))

    # ---- the double-pay guard -------------------------------------------

    def test_a_settled_worker_drops_off_the_monthly_run(self):
        """The guard that used to be a flag somebody had to remember."""
        self._mark(self.emp, range(1, 25))
        run, msg = generate_settlement(
            site=self.site, employees=[self.emp],
            last_working_day=date(2026, 8, 24), reason="Demobilised",
            actor=self.hr)
        self.assertIsNone(msg, msg)
        self.assertIn(self.emp,
                      list(eligible_workers(self.site, "MVR", 2026, 8)))
        lock_run(run, self.hr)
        self.assertNotIn(self.emp,
                         list(eligible_workers(self.site, "MVR", 2026, 8)))
        self.assertEqual(settled_through(self.emp), date(2026, 8, 24))

    def test_locking_records_the_exit_on_the_real_last_day(self):
        """Demobilisation recorded neither a date nor a reason, and closed
        allocations at today — five days late meant five days too many."""
        self._mark(self.emp, range(1, 25))
        run, _ = generate_settlement(
            site=self.site, employees=[self.emp],
            last_working_day=date(2026, 8, 24), reason="Contract ended",
            actor=self.hr)
        lock_run(run, self.hr)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.is_active)
        self.assertEqual(self.emp.left_on, date(2026, 8, 24))
        self.assertEqual(self.emp.left_reason, "Contract ended")
        alloc = EmployeeSiteAllocation.objects.get(employee=self.emp)
        self.assertEqual(alloc.to_date, date(2026, 8, 24))

    def test_a_late_closed_allocation_is_corrected_to_the_real_day(self):
        """VKR's allocations were closed on the 29th; the men left on the
        24th."""
        self._mark(self.emp, range(1, 25))
        EmployeeSiteAllocation.objects.filter(employee=self.emp).update(
            to_date=date(2026, 8, 29))
        run, _ = generate_settlement(
            site=self.site, employees=[self.emp],
            last_working_day=date(2026, 8, 24), reason="Demobilised",
            actor=self.hr)
        lock_run(run, self.hr)
        self.assertEqual(
            EmployeeSiteAllocation.objects.get(employee=self.emp).to_date,
            date(2026, 8, 24))

    # ---- guards ----------------------------------------------------------

    def test_a_future_last_working_day_is_refused(self):
        run, msg = generate_settlement(
            site=self.site, employees=[self.emp],
            last_working_day=date(2099, 1, 1), reason="", actor=self.hr)
        self.assertIsNone(run)
        self.assertIn("future", msg)

    def test_a_subcontract_worker_cannot_be_settled_through_payroll(self):
        sub = self._worker("EMP-S9", Decimal("5000"))
        Employee.objects.filter(pk=sub.pk).update(
            engagement_type=Employee.Engagement.SUBCONTRACT)
        sub.refresh_from_db()
        run, msg = generate_settlement(
            site=self.site, employees=[sub],
            last_working_day=date(2026, 8, 24), reason="", actor=self.hr)
        self.assertIsNone(run)
        self.assertIn("valuation", msg)

    def test_a_settlement_can_sit_alongside_the_months_own_run(self):
        """The unique constraint covers monthly runs only."""
        PayrollRun.objects.create(site=self.site, currency="MVR", year=2026,
                                  month=8, working_days=31, created_by=self.hr)
        self._mark(self.emp, range(1, 25))
        run, msg = generate_settlement(
            site=self.site, employees=[self.emp],
            last_working_day=date(2026, 8, 24), reason="", actor=self.hr)
        self.assertIsNone(msg, msg)
        self.assertEqual(run.kind, PayrollRun.Kind.SETTLEMENT)


class SettlementApiTests(TestCase):
    """The endpoints the screen drives."""

    def setUp(self):
        from rest_framework.test import APIClient
        self.site = Site.objects.create(code="API", name="Api site",
                                        status=Site.Status.ACTIVE,
                                        working_days=[6, 7, 1, 2, 3, 4])
        self.hr = make_user("hr_api", User.Role.HO_HR)
        self.pm = make_user("pm_api", User.Role.PM, site=self.site)
        self.cat = ManpowerCategory.objects.create(name="Carpenter",
                                                   list_type="DPR",
                                                   sort_order=1)
        self.emp = Employee.objects.create(
            emp_no="EMP-A1", full_name="Api Worker",
            basic_pay=Decimal("9300"), currency="MVR", job_category=self.cat,
            join_date=date(2026, 8, 1), employment_type="CONTRACT",
            engagement_type="DIRECT")
        EmployeeSiteAllocation.objects.create(employee=self.emp,
                                              site=self.site,
                                              from_date=date(2026, 8, 1))
        for d in range(1, 29):
            Attendance.objects.create(employee=self.emp, site=self.site,
                                      day=date(2026, 8, d), remark="PRESENT",
                                      entered_by=self.hr)
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def _body(self, **extra):
        body = {"site_id": self.site.id, "employee_ids": [self.emp.id],
                "last_working_day": "2026-08-24", "reason": "Demobilised"}
        body.update(extra)
        return body

    def test_preview_writes_nothing_and_reports_the_contradiction(self):
        r = self.client.post("/api/v1/payroll/settlements/preview",
                             self._body(), format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["conflict_count"], 1)
        self.assertEqual(len(r.data["rows"][0]["conflicts"]), 4)
        self.assertFalse(PayrollRun.objects.filter(
            kind=PayrollRun.Kind.SETTLEMENT).exists())

    def test_the_pm_may_preview_but_not_raise(self):
        self.client.force_authenticate(self.pm)
        self.assertEqual(
            self.client.post("/api/v1/payroll/settlements/preview",
                             self._body(), format="json").status_code, 200)
        self.assertEqual(
            self.client.post("/api/v1/payroll/settlements",
                             self._body(), format="json").status_code, 403)

    def test_creating_returns_a_settlement_run(self):
        r = self.client.post("/api/v1/payroll/settlements", self._body(),
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["kind"], "SETTLEMENT")
        self.assertEqual(str(r.data["last_working_day"]), "2026-08-24")
        self.assertEqual(r.data["status"], "DRAFT")

    def test_a_missing_last_working_day_is_refused(self):
        r = self.client.post("/api/v1/payroll/settlements",
                             self._body(last_working_day=""), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("last working day", r.data["detail"])

    def test_candidates_exclude_the_already_settled(self):
        r = self.client.get(
            f"/api/v1/payroll/settlements/candidates?site={self.site.id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["emp_no"] for x in r.data], ["EMP-A1"])
        run, _ = generate_settlement(
            site=self.site, employees=[self.emp],
            last_working_day=date(2026, 8, 24), reason="", actor=self.hr)
        lock_run(run, self.hr)
        r = self.client.get(
            f"/api/v1/payroll/settlements/candidates?site={self.site.id}")
        self.assertEqual(r.data, [])
