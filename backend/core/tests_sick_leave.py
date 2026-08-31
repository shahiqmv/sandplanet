"""Sick leave is paid.

It sat in ABSENT_MARKS and so was deducted, which the sites reported after
the July run: 55 sick days across 34 men, MVR 11,911 withheld from people who
were ill. A man granted sick leave is entitled to his day (owner 2026-08-31).
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from . import payroll, staff_cost
from .models import (Attendance, Employee, EmployeeSiteAllocation,
                     ManpowerCategory, Site, User)
from .tests import make_user


class SickLeaveIsPaidTests(TestCase):
    def setUp(self):
        # Sat–Thu working week, Friday the rest day.
        self.site = Site.objects.create(code="SKL", name="Sick site",
                                        status=Site.Status.ACTIVE,
                                        working_days=[6, 7, 1, 2, 3, 4])
        self.hr = make_user("hr_sick", User.Role.HO_HR)
        self.cat = ManpowerCategory.objects.create(name="Mason",
                                                   list_type="DPR",
                                                   grp="LABOUR", sort_order=1)
        self.emp = Employee.objects.create(
            emp_no="EMP-S1", full_name="Ill Worker",
            basic_pay=Decimal("9300"), currency="MVR", job_category=self.cat,
            join_date=date(2026, 7, 1), employment_type="CONTRACT",
            engagement_type="DIRECT")
        EmployeeSiteAllocation.objects.create(employee=self.emp,
                                              site=self.site,
                                              from_date=date(2026, 7, 1))

    def _mark(self, days, remark):
        for d in days:
            Attendance.objects.update_or_create(
                employee=self.emp, site=self.site, day=date(2026, 7, d),
                defaults={"remark": remark, "entered_by": self.hr})

    def _days(self):
        d, _ot, _fri, _rest = payroll._attendance_prefill(
            self.emp, self.site, 2026, 7, 31)
        return d

    def test_a_sick_day_is_paid(self):
        self._mark(range(1, 32), "PRESENT")
        full = self._days()
        self._mark([8, 9, 10], "SICK")
        self.assertEqual(self._days(), full)

    def test_an_absent_day_is_still_deducted(self):
        """Only sick moved. Absence and unpaid leave are unchanged."""
        self._mark(range(1, 32), "PRESENT")
        full = self._days()
        self._mark([8, 9, 10], "ABSENT")
        self.assertEqual(self._days(), full - 3)

    def test_unpaid_leave_is_still_deducted(self):
        self._mark(range(1, 32), "PRESENT")
        full = self._days()
        self._mark([8, 9], "LEAVE")
        self.assertEqual(self._days(), full - 2)

    def test_sick_no_longer_counts_toward_the_rest_day_limit(self):
        """A man off sick all week must not also lose his Friday."""
        self._mark(range(1, 32), "PRESENT")
        full = self._days()
        self._mark([4, 5, 6, 7], "SICK")     # a whole working week
        self.assertEqual(self._days(), full)

    def test_the_cost_ledger_pays_for_it_too(self):
        """Payroll paying a day the cost ledger records as free would
        understate the project's labour by exactly that."""
        self.assertEqual(staff_cost._day_weight("SICK"), Decimal("1"))
        self.assertEqual(staff_cost._day_weight("ABSENT"), Decimal("0"))
        self.assertEqual(staff_cost._day_weight("LEAVE"), Decimal("0"))
        self.assertEqual(staff_cost._day_weight("HALF_DAY"), Decimal("0.5"))

    def test_sick_sits_with_the_paid_marks_not_the_absent_ones(self):
        self.assertIn("SICK", payroll.PAID_MARKS)
        self.assertNotIn("SICK", payroll.ABSENT_MARKS)


class BackpayJulySickTests(TestCase):
    """Paying July's withheld sick pay forward onto a later run.

    The July runs are locked — the money went out and the labour cost posted
    — so the correction reads as an allowance in the month it is actually
    paid, rather than a rewrite of a month people were already paid against
    (owner 2026-08-31).
    """

    def setUp(self):
        from io import StringIO

        from .models import PayrollLine, PayrollRun

        self.StringIO = StringIO
        self.site = Site.objects.create(code="BPY", name="Backpay site",
                                        status=Site.Status.ACTIVE)
        self.hr = make_user("hr_bp", User.Role.HO_HR)
        self.emp = Employee.objects.create(
            emp_no="EMP-B1", full_name="Ill Worker",
            basic_pay=Decimal("9300"), currency="MVR",
            employment_type="CONTRACT", engagement_type="DIRECT",
            join_date=date(2026, 7, 1))
        for d in (8, 9, 10):
            Attendance.objects.create(employee=self.emp, site=self.site,
                                      day=date(2026, 7, d), remark="SICK",
                                      entered_by=self.hr)
        self.july = PayrollRun.objects.create(
            site=self.site, currency="MVR", year=2026, month=7,
            working_days=31, status="LOCKED", created_by=self.hr)
        PayrollLine.objects.create(run=self.july, employee=self.emp,
                                   site=self.site,
                                   basic_pay=Decimal("9300"))
        self.aug = PayrollRun.objects.create(
            site=self.site, currency="MVR", year=2026, month=8,
            working_days=31, status="DRAFT", created_by=self.hr)
        self.line = PayrollLine.objects.create(
            run=self.aug, employee=self.emp, site=self.site,
            basic_pay=Decimal("9300"))
        self.Line = PayrollLine

    def _run(self, **kw):
        from django.core.management import call_command

        out = self.StringIO()
        call_command("backpay_july_sick", stdout=out, **kw)
        return out.getvalue()

    def test_it_credits_the_withheld_days_as_an_allowance(self):
        self._run()
        self.line.refresh_from_db()
        # 3 days at 9300/31 = 300 a day.
        self.assertEqual(self.line.allowance, Decimal("900.00"))
        self.assertIn("July sick leave", self.line.remarks)

    def test_a_dry_run_writes_nothing(self):
        out = self._run(dry_run=True)
        self.assertIn("DRY RUN", out)
        self.line.refresh_from_db()
        self.assertEqual(self.line.allowance, Decimal("0"))

    def test_running_it_twice_does_not_pay_twice(self):
        self._run()
        self._run()
        self.line.refresh_from_db()
        self.assertEqual(self.line.allowance, Decimal("900.00"))

    def test_it_will_not_credit_a_locked_run(self):
        """An allowance added to a locked run reaches nobody."""
        self.aug.status = "LOCKED"
        self.aug.save(update_fields=["status"])
        self._run()
        self.line.refresh_from_db()
        self.assertEqual(self.line.allowance, Decimal("0"))

    def test_an_existing_allowance_is_added_to_not_replaced(self):
        self.line.allowance = Decimal("500")
        self.line.save(update_fields=["allowance"])
        self._run()
        self.line.refresh_from_db()
        self.assertEqual(self.line.allowance, Decimal("1400.00"))

    def test_a_worker_with_no_august_line_is_skipped_not_crashed_on(self):
        self.line.delete()
        out = self._run()
        self.assertIn("skip", out)

    def test_a_signed_run_goes_back_for_re_approval(self):
        """An approval must never outlive the numbers it was given."""
        self.aug.status = "PD_REVIEW"
        self.aug.verified_by = self.hr
        self.aug.save(update_fields=["status", "verified_by"])
        out = self._run()
        self.aug.refresh_from_db()
        self.assertEqual(self.aug.status, "DRAFT")
        self.assertIsNone(self.aug.verified_by)
        self.assertIn("returned to draft", out)

    def test_a_draft_run_is_left_where_it_is(self):
        self._run()
        self.aug.refresh_from_db()
        self.assertEqual(self.aug.status, "DRAFT")

    def test_a_leaver_is_credited_on_his_settlement(self):
        """He will never have another monthly run — the settlement is his
        last payment and the only place it can reach him."""
        from .models import PayrollLine, PayrollRun

        self.line.delete()                      # no monthly August line
        stl = PayrollRun.objects.create(
            site=self.site, currency="MVR", year=2026, month=8,
            working_days=31, status="DRAFT", kind="SETTLEMENT",
            last_working_day=date(2026, 8, 24), created_by=self.hr)
        line = PayrollLine.objects.create(run=stl, employee=self.emp,
                                          site=self.site,
                                          basic_pay=Decimal("9300"))
        out = self._run()
        line.refresh_from_db()
        self.assertEqual(line.allowance, Decimal("900.00"))
        self.assertIn("settlement run", out)

    def test_the_monthly_run_wins_when_a_man_has_both(self):
        """A settlement for somebody else's batch must not divert a working
        man's back-pay."""
        from .models import PayrollLine, PayrollRun

        stl = PayrollRun.objects.create(
            site=self.site, currency="MVR", year=2026, month=8,
            working_days=31, status="DRAFT", kind="SETTLEMENT",
            last_working_day=date(2026, 8, 24), created_by=self.hr)
        odd = PayrollLine.objects.create(run=stl, employee=self.emp,
                                         site=self.site,
                                         basic_pay=Decimal("9300"))
        self._run()
        self.line.refresh_from_db()
        odd.refresh_from_db()
        self.assertEqual(self.line.allowance, Decimal("900.00"))
        self.assertEqual(odd.allowance, Decimal("0"))
