"""Payroll build — overtime rate master + per-worker resolution + advances."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import payroll
from .models import (CostHead, Document, Employee, ManpowerCategory,
                     OvertimeRate, SalaryAdvance, Site, SitePmHistory, User)
from .tests import make_user


class OvertimeRateTests(TestCase):
    def setUp(self):
        self.hr = make_user("hr1", User.Role.HO_HR)
        self.mason = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def _emp(self, **kw):
        return Employee.objects.create(
            emp_no=kw.pop("emp_no", "EMP-0001"), full_name="Test",
            job_category=self.mason, **kw)

    def test_upsert_and_list_rates(self):
        r = self.client.post("/api/v1/overtime-rates", {
            "category_id": self.mason.id, "currency": "MVR",
            "rate_per_hour": 25, "applies_by_default": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        # upsert again updates in place, not duplicates
        self.client.post("/api/v1/overtime-rates", {
            "category_id": self.mason.id, "currency": "MVR",
            "rate_per_hour": 30}, format="json")
        self.assertEqual(OvertimeRate.objects.filter(
            category=self.mason, currency="MVR").count(), 1)
        listing = self.client.get("/api/v1/overtime-rates").data
        mason = next(c for c in listing if c["category_id"] == self.mason.id)
        self.assertEqual(float(mason["rates"]["MVR"]["rate_per_hour"]), 30.0)

    def test_worker_inherits_category_default(self):
        OvertimeRate.objects.create(category=self.mason, currency="MVR",
                                    rate_per_hour=Decimal("25"),
                                    applies_by_default=True)
        emp = self._emp(currency="MVR")  # ot_applies None -> inherit
        self.assertEqual(emp.ot_rate(), Decimal("25"))

    def test_worker_override_off(self):
        OvertimeRate.objects.create(category=self.mason, currency="MVR",
                                    rate_per_hour=Decimal("25"),
                                    applies_by_default=True)
        emp = self._emp(currency="MVR", ot_applies=False)
        self.assertEqual(emp.ot_rate(), Decimal("0"))

    def test_category_default_off_but_worker_on(self):
        OvertimeRate.objects.create(category=self.mason, currency="MVR",
                                    rate_per_hour=Decimal("25"),
                                    applies_by_default=False)
        # inherit -> off
        self.assertEqual(self._emp(emp_no="EMP-0002").ot_rate(), Decimal("0"))
        # explicit on -> gets the rate
        emp = self._emp(emp_no="EMP-0003", ot_applies=True)
        self.assertEqual(emp.ot_rate(), Decimal("25"))

    def test_currency_specific_rate(self):
        OvertimeRate.objects.create(category=self.mason, currency="USD",
                                    rate_per_hour=Decimal("3"),
                                    applies_by_default=True)
        # an MVR worker has no MVR rate -> 0
        self.assertEqual(self._emp(emp_no="EMP-0004", currency="MVR").ot_rate(),
                         Decimal("0"))
        self.assertEqual(self._emp(emp_no="EMP-0005", currency="USD").ot_rate(),
                         Decimal("3"))


class SalaryAdvanceTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.sa = make_user("sa1", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.head = CostHead.objects.get(name="Transport & Freight")
        self.e1 = Employee.objects.create(emp_no="EMP-0001", full_name="A")
        self.e2 = Employee.objects.create(emp_no="EMP-0002", full_name="B")
        self.client = APIClient()
        self.client.force_authenticate(self.sa)

    def _raise(self):
        return self.client.post("/api/v1/documents", {
            "doc_type": "PYR", "site_id": self.site.id, "payload": {},
            "cost_head_id": self.head.id, "payment_method": "CASH",
            "has_supporting_doc": True,
            "salary_lines": [
                {"employee_id": self.e1.id, "kind": "ADVANCE", "amount": 2000},
                {"employee_id": self.e2.id, "kind": "LOAN", "amount": 6000,
                 "months": 3},
            ],
            "deduct_year": 2026, "deduct_month": 6,
        }, format="json")

    def test_advance_pyr_creates_lines_and_totals(self):
        r = self._raise()
        self.assertEqual(r.status_code, 201, r.data)
        pr = r.data["payment_request"]
        self.assertEqual(pr["payment_type"], "ADVANCE")
        self.assertEqual(float(pr["amount_requested"]), 8000.0)  # 2000 + 6000
        self.assertEqual(len(pr["salary_advances"]), 2)
        self.assertEqual(SalaryAdvance.objects.count(), 2)

    def test_deductions_only_after_paid(self):
        ref = self._raise().data["ref"]
        doc = Document.objects.get(ref=ref)
        # not paid yet -> nothing deducted
        self.assertEqual(payroll.deductions_for(self.e1, 2026, 6),
                         {"advance": Decimal("0"), "loan": Decimal("0")})
        doc.status = "PAID"
        doc.save(update_fields=["status"])
        # advance: full 2000 in June only
        self.assertEqual(payroll.deductions_for(self.e1, 2026, 6)["advance"],
                         Decimal("2000.00"))
        self.assertEqual(payroll.deductions_for(self.e1, 2026, 7)["advance"],
                         Decimal("0"))

    def test_loan_spreads_over_months(self):
        ref = self._raise().data["ref"]
        doc = Document.objects.get(ref=ref)
        doc.status = "PAID"
        doc.save(update_fields=["status"])
        # 6000 / 3 = 2000 per month, June..August
        for m in (6, 7, 8):
            self.assertEqual(payroll.deductions_for(self.e2, 2026, m)["loan"],
                             Decimal("2000.00"))
        self.assertEqual(payroll.deductions_for(self.e2, 2026, 9)["loan"],
                         Decimal("0"))


class PayrollRunTests(TestCase):
    def setUp(self):
        from datetime import date

        from .models import CostPosting, EmployeeSiteAllocation, TimesheetMonth
        self.CostPosting = CostPosting
        self.hr = make_user("hr1", User.Role.HO_HR)
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        # Draft salary verification (owner 2026-08-12): HR submits, the site
        # PM verifies, the PD approves, only then may HR lock.
        from .models import SitePmHistory
        self.pm = make_user("pay_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.director = make_user("pay_pd", User.Role.DIRECTOR)
        # A site's payroll can only run once its attendance is locked.
        TimesheetMonth.objects.create(site=self.site, year=2026, month=5,
                                      status="LOCKED")
        self.mason = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        OvertimeRate.objects.create(category=self.mason, currency="MVR",
                                    rate_per_hour=Decimal("25"),
                                    applies_by_default=True)
        self.emp = Employee.objects.create(
            emp_no="EMP-0001", full_name="Kumar", job_category=self.mason,
            basic_pay=Decimal("6200"), currency="MVR")
        EmployeeSiteAllocation.objects.create(employee=self.emp, site=self.site,
                                              from_date=date(2026, 1, 1))
        self._mark_month(2026, 5)
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def _mark_month(self, year, month, emp=None, day_from=1, day_to=31):
        """A full PRESENT register for the month. These cases used to leave
        attendance empty to mean "no absences"; an empty register now pays
        nothing (owner 2026-08-14), so the days have to actually be there."""
        from datetime import date

        from .models import Attendance
        for d in range(day_from, day_to + 1):
            day = date(year, month, d)
            if day.isoweekday() not in self.site.working_days:
                continue        # a rest day is blank in the register, and
                                # marking it would pay 7th-day Friday money
            Attendance.objects.create(employee=emp or self.emp, site=self.site,
                                      day=day, remark="PRESENT",
                                      normal_hours=8)

    def test_generate_prefills_line(self):
        r = self.client.post("/api/v1/payroll/runs", {
            "site_id": self.site.id, "currency": "MVR",
            "year": 2026, "month": 5, "working_days": 31}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        line = r.data["lines"][0]
        self.assertEqual(float(line["basic_pay"]), 6200.0)
        self.assertEqual(float(line["ot_rate"]), 25.0)
        self.assertEqual(float(line["days_worked"]), 31.0)  # no absences
        self.assertEqual(float(line["earned_basic"]), 6200.0)

    def test_site_run_blocked_until_attendance_locked(self):
        # A month whose attendance isn't locked can't be run for the site.
        r = self.client.post("/api/v1/payroll/runs", {
            "site_id": self.site.id, "currency": "MVR",
            "year": 2026, "month": 6, "working_days": 30}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("attendance", r.data["detail"].lower())
        # Lock it, and the run goes through.
        from .models import TimesheetMonth
        TimesheetMonth.objects.create(site=self.site, year=2026, month=6,
                                      status="LOCKED")
        r = self.client.post("/api/v1/payroll/runs", {
            "site_id": self.site.id, "currency": "MVR",
            "year": 2026, "month": 6, "working_days": 30}, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_mid_month_joiner_is_prorated_from_join_date(self):
        from datetime import date
        # Kumar joins 20 May 2026 (a 31-day month) → 12 billable days (20–31),
        # not the full month; the pre-join days are neither worked nor absent.
        self.emp.join_date = date(2026, 5, 20)
        self.emp.save(update_fields=["join_date"])
        # He is marked from the day he joined — the register and the join date
        # agree here, unlike Sahajalal at BVR.
        from .models import Attendance
        Attendance.objects.filter(employee=self.emp,
                                  day__lt=date(2026, 5, 20)).delete()
        r = self.client.post("/api/v1/payroll/runs", {
            "site_id": self.site.id, "currency": "MVR",
            "year": 2026, "month": 5, "working_days": 31}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        line = r.data["lines"][0]
        self.assertEqual(float(line["days_worked"]), 12.0)     # 20..31 inclusive
        # paid pro-rata on the full-month daily rate: 6200/31 × 12 = 2400
        self.assertEqual(float(line["earned_basic"]), 2400.0)

    def test_split_pay_basic_in_usd_remainder_in_mvr(self):
        # A split-pay worker: attendance-based basic in USD (combined USD run),
        # OT + everything else in MVR with the site team (owner 2026-08-06).
        from datetime import date

        from core import payroll
        from core.models import Attendance, EmployeeSiteAllocation
        emp = Employee.objects.create(
            emp_no="EMP-0009", full_name="Split", job_category=self.mason,
            currency="MVR", usd_basic_pay=Decimal("1000"))
        EmployeeSiteAllocation.objects.create(employee=emp, site=self.site,
                                              from_date=date(2026, 1, 1))
        Attendance.objects.create(employee=emp, site=self.site,
                                  day=date(2026, 5, 6), remark="PRESENT",
                                  ot_approved=Decimal("2"))
        # site MVR run: no basic, OT in MVR (2h × 25)
        mvr = payroll.generate_run(site=self.site, currency="MVR", year=2026,
                                   month=5, working_days=31, actor=self.hr)
        line = mvr.lines.get(employee=emp)
        m = payroll.compute_line(line)
        self.assertEqual(float(line.basic_pay), 0.0)
        self.assertEqual(float(m["earned_basic"]), 0.0)
        self.assertEqual(float(m["ot_pay"]), 50.0)
        self.assertEqual(float(m["net"]), 50.0)
        # combined USD run: basic only, attendance-based (1000/31 × 31 = 1000)
        usd = payroll.generate_run(site=None, currency="USD", year=2026,
                                   month=5, working_days=31, actor=self.hr)
        uline = usd.lines.get(employee=emp)
        um = payroll.compute_line(uline)
        self.assertEqual(float(uline.basic_pay), 1000.0)
        self.assertEqual(float(um["ot_pay"]), 0.0)
        self.assertAlmostEqual(float(um["earned_basic"]), 1000.0, places=1)
        self.assertAlmostEqual(float(um["net"]), 1000.0, places=1)
        # the full-USD gate now also waits on the split worker's site
        self.assertNotIn(self.site.code,
                         payroll.unlocked_sites(2026, 5, currency="USD"))

    def test_edit_and_compute(self):
        run = self.client.post("/api/v1/payroll/runs", {
            "site_id": self.site.id, "year": 2026, "month": 5,
            "working_days": 31}, format="json").data
        line_id = run["lines"][0]["id"]
        r = self.client.patch(f"/api/v1/payroll/lines/{line_id}", {
            "days_worked": 19, "ot_hours": 49, "allowance": 2000,
            "penalty": 500, "fridays_worked": 2}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        d = r.data
        self.assertEqual(float(d["earned_basic"]), 3800.0)   # 6200*19/31
        # A Friday pays 12h × the OT rate, NOT a day of basic (owner
        # 2026-08-12): 2 Fridays × 12h × 25 = 600
        self.assertEqual(float(d["friday_pay"]), 600.0)
        self.assertEqual(float(d["ot_pay"]), 1225.0)         # 49 * 25
        self.assertEqual(float(d["gross"]), 7625.0)          # 3800+600+1225+2000
        self.assertEqual(float(d["net"]), 7125.0)            # gross - 500

    def _approve_chain(self, run_id):
        """HR submits → PM verifies → PD approves, so the run may be locked."""
        self.client.post(f"/api/v1/payroll/runs/{run_id}",
                         {"action": "submit"}, format="json")
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/payroll/runs/{run_id}",
                         {"action": "verify"}, format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/payroll/runs/{run_id}",
                         {"action": "approve"}, format="json")
        self.client.force_authenticate(self.hr)

    def test_lock_posts_labour_cost(self):
        run = self.client.post("/api/v1/payroll/runs", {
            "site_id": self.site.id, "year": 2026, "month": 5,
            "working_days": 31}, format="json").data
        self._approve_chain(run["id"])
        r = self.client.post(f"/api/v1/payroll/runs/{run['id']}", {},
                             format="json")
        self.assertEqual(r.data["status"], "LOCKED")
        posted = self.CostPosting.objects.filter(
            site=self.site, source="STAFF", staff_year=2026, staff_month=5)
        self.assertTrue(posted.exists())
        # gross for a full month = full basic 6200
        self.assertEqual(float(sum(p.amount for p in posted)), 6200.0)

    def test_locked_line_is_immutable(self):
        run = self.client.post("/api/v1/payroll/runs", {
            "site_id": self.site.id, "year": 2026, "month": 5,
            "working_days": 31}, format="json").data
        line_id = run["lines"][0]["id"]
        self._approve_chain(run["id"])
        self.client.post(f"/api/v1/payroll/runs/{run['id']}", {}, format="json")
        r = self.client.patch(f"/api/v1/payroll/lines/{line_id}",
                             {"allowance": 100}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_report_and_payslip_pdf(self):
        run = self.client.post("/api/v1/payroll/runs", {
            "site_id": self.site.id, "year": 2026, "month": 5,
            "working_days": 31}, format="json").data
        line_id = run["lines"][0]["id"]
        r = self.client.get(f"/api/v1/payroll/runs/{run['id']}/report.pdf")
        p = self.client.get(f"/api/v1/payroll/lines/{line_id}/payslip.pdf")
        # 200 with a PDF, or 503 if WeasyPrint is absent on this box
        for resp in (r, p):
            self.assertIn(resp.status_code, (200, 503))
            if resp.status_code == 200:
                self.assertEqual(resp["Content-Type"], "application/pdf")
                self.assertTrue(resp.content[:4] == b"%PDF")


class GenerateMonthTests(TestCase):
    def setUp(self):
        from datetime import date

        from .models import (EmployeeSiteAllocation, TimesheetMonth)
        self.hr = make_user("hr1", User.Role.HO_HR)
        self.cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.locked = Site.objects.create(code="VKR", name="Vakkaru",
                                          status=Site.Status.ACTIVE)
        self.open_site = Site.objects.create(code="SJR", name="Soneva Jani",
                                             status=Site.Status.ACTIVE)
        self.ho = Site.objects.create(code="MLE", name="Head Office",
                                      status=Site.Status.ACTIVE,
                                      is_head_office=True)
        for i, site in enumerate((self.locked, self.open_site, self.ho), 1):
            e = Employee.objects.create(emp_no=f"EMP-000{i}", full_name=f"W{i}",
                                        job_category=self.cat,
                                        basic_pay=6000, currency="MVR")
            EmployeeSiteAllocation.objects.create(employee=e, site=site,
                                                  from_date=date(2026, 1, 1))
        self.usd = Employee.objects.create(emp_no="EMP-0009", full_name="Mgr",
                                           job_category=self.cat,
                                           basic_pay=2000, currency="USD")
        EmployeeSiteAllocation.objects.create(employee=self.usd,
                                              site=self.locked,
                                              from_date=date(2026, 1, 1))
        TimesheetMonth.objects.create(site=self.locked, year=2026, month=5,
                                      status="LOCKED")
        TimesheetMonth.objects.create(site=self.ho, year=2026, month=5,
                                      status="LOCKED")
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def _lock(self, site):
        from .models import TimesheetMonth
        TimesheetMonth.objects.get_or_create(site=site, year=2026, month=5,
                                             defaults={"status": "LOCKED"})

    def test_blocked_until_every_site_locked(self):
        # SJR is still open -> generation is blocked and lists it
        r = self.client.post("/api/v1/payroll/generate",
                             {"year": 2026, "month": 5}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["unlocked"], ["SJR"])

    def test_generate_all_sites_when_locked(self):
        self._lock(self.open_site)  # now every staffed site is locked
        r = self.client.post("/api/v1/payroll/generate",
                             {"year": 2026, "month": 5}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        made = {c["site"] for c in r.data["created"]}
        # one combined MVR run + one combined USD run — all sites in each
        self.assertEqual(made, {"MVR — all sites", "USD — all sites"})
        from .models import PayrollLine, PayrollRun
        mvr = PayrollRun.objects.get(site__isnull=True, currency="MVR")
        sites = set(PayrollLine.objects.filter(run=mvr)
                    .values_list("site__code", flat=True))
        self.assertEqual(sites, {"VKR", "SJR", "MLE"})  # grouped site-wise

    def test_generate_month_is_idempotent(self):
        self._lock(self.open_site)
        self.client.post("/api/v1/payroll/generate",
                        {"year": 2026, "month": 5}, format="json")
        r = self.client.post("/api/v1/payroll/generate",
                            {"year": 2026, "month": 5}, format="json")
        self.assertEqual(len(r.data["created"]), 0)
        reasons = {s["reason"] for s in r.data["skipped"]}
        self.assertIn("already generated", reasons)

    def test_hr_can_lock_attendance(self):
        r = self.client.post(
            f"/api/v1/timesheets/{self.open_site.id}/2026/5/lock", {},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "LOCKED")


class FridayPrefillTests(TestCase):
    def setUp(self):
        from datetime import date

        from .models import (Attendance, EmployeeSiteAllocation)
        self.hr = make_user("hr1", User.Role.HO_HR)
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.emp = Employee.objects.create(emp_no="EMP-0001", full_name="A",
                                           basic_pay=6000, currency="MVR")
        EmployeeSiteAllocation.objects.create(employee=self.emp, site=self.site,
                                              from_date=date(2026, 1, 1))
        # May 2026: 1st is Friday; mark it PRESENT (a worked rest day)
        self.friday = date(2026, 5, 1)
        assert self.friday.isoweekday() == 5
        Attendance.objects.create(employee=self.emp, site=self.site,
                                  day=self.friday, remark="PRESENT")
        # a normal absent day (Sat 2 May)
        Attendance.objects.create(employee=self.emp, site=self.site,
                                  day=date(2026, 5, 2), remark="ABSENT")
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def test_friday_present_prefills_fridays_worked(self):
        from core import payroll
        run = payroll.generate_run(site=self.site, currency="MVR", year=2026,
                                   month=5, working_days=31, actor=self.hr)
        line = run.lines.get(employee=self.emp)
        self.assertEqual(line.fridays_worked, 1)     # the worked Friday
        self.assertEqual(float(line.days_worked), 30.0)  # 31 - 1 absent

    def test_register_shows_friday_code_and_totals(self):
        r = self.client.get(
            f"/api/v1/attendance/register?site={self.site.id}&year=2026&month=5")
        self.assertEqual(r.status_code, 200, r.data)
        row = r.data["rows"][0]
        self.assertEqual(row["days"]["1"], "F")   # Friday worked
        self.assertEqual(row["days"]["2"], "A")   # absent
        self.assertEqual(row["fridays"], 1)
        self.assertEqual(row["absent"], 1)
        self.assertEqual(r.data["totals"]["fridays"], 1)

    def test_rest_day_off_clears_record(self):
        # marking OFF on the Friday removes the record
        r = self.client.put("/api/v1/attendance/bulk", {
            "site": self.site.id, "date": "2026-05-01",
            "rows": [{"employee_id": self.emp.id, "remark": "OFF"}]},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        from .models import Attendance
        self.assertFalse(Attendance.objects.filter(
            employee=self.emp, day=self.friday).exists())


class PayrollAttendanceReviewTests(TestCase):
    """The pre-run attendance + OT review HR checks before generating."""

    def setUp(self):
        from datetime import date

        from .models import Attendance, EmployeeSiteAllocation, TimesheetMonth
        self.hr = make_user("hr1", User.Role.HO_HR)
        self.pm = make_user("pm1", User.Role.PM)
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.emp = Employee.objects.create(emp_no="EMP-0001", full_name="Kumar",
                                           basic_pay=6000, currency="MVR")
        EmployeeSiteAllocation.objects.create(employee=self.emp, site=self.site,
                                              from_date=date(2026, 1, 1))
        # Mon 4 May: worked 3h OT; Tue 5 May: absent; Fri 1 May (rest): worked.
        Attendance.objects.create(employee=self.emp, site=self.site,
                                  day=date(2026, 5, 4), remark="PRESENT",
                                  ot_approved=Decimal("3"), ot_approved_by=self.pm)
        Attendance.objects.create(employee=self.emp, site=self.site,
                                  day=date(2026, 5, 5), remark="ABSENT")
        Attendance.objects.create(employee=self.emp, site=self.site,
                                  day=date(2026, 5, 1), remark="PRESENT")
        TimesheetMonth.objects.create(site=self.site, year=2026, month=5,
                                      status="LOCKED")
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def test_summary_totals_per_site_and_company_wide(self):
        r = self.client.get(
            "/api/v1/payroll/attendance-summary?year=2026&month=5")
        self.assertEqual(r.status_code, 200, r.data)
        row = next(s for s in r.data["sites"] if s["site_code"] == "VKR")
        self.assertEqual(row["workers"], 1)
        self.assertEqual(row["days_worked"], 1)       # Mon 4 May
        self.assertEqual(row["rest_day_work"], 1)     # Fri 1 May
        self.assertEqual(row["absences"], 1)          # Tue 5 May
        self.assertEqual(float(row["ot_hours"]), 3.0)
        self.assertTrue(row["locked"])
        self.assertEqual(r.data["totals"]["ot_hours"], 3
                         if isinstance(r.data["totals"]["ot_hours"], int)
                         else float(r.data["totals"]["ot_hours"]))
        self.assertTrue(r.data["all_locked"])

    def test_ot_breakdown_lists_days_and_approver(self):
        r = self.client.get("/api/v1/payroll/ot-breakdown?year=2026&month=5")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["worker_count"], 1)
        w = r.data["workers"][0]
        self.assertEqual(w["emp_no"], "EMP-0001")
        self.assertEqual(float(w["total_ot"]), 3.0)
        self.assertEqual(len(w["days"]), 1)
        self.assertEqual(w["days"][0]["day"], "2026-05-04")
        self.assertEqual(w["days"][0]["approved_by"], self.pm.full_name)

    def test_review_is_hr_finance_admin_only(self):
        self.client.force_authenticate(self.pm)
        self.assertEqual(self.client.get(
            "/api/v1/payroll/attendance-summary?year=2026&month=5").status_code,
            403)


class SubcontractorPayrollExclusionTests(TestCase):
    """Acceptance #2 — a subcontract worker is structurally excluded from
    payroll and absent from the HR register (subcontractor module Phase 1)."""

    def setUp(self):
        from .models import (EmployeeSiteAllocation, PayrollLine, PayrollRun,
                             Subcontractor, TimesheetMonth)
        self.PayrollLine, self.PayrollRun = PayrollLine, PayrollRun
        self.hr = make_user("hr1", User.Role.HO_HR)
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        TimesheetMonth.objects.create(site=self.site, year=2026, month=5,
                                      status="LOCKED")
        self.mason = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.sub = Subcontractor.objects.create(
            site=self.site, name="Alif Gang", status="APPROVED")
        self.direct = Employee.objects.create(
            emp_no="EMP-0001", full_name="Direct", job_category=self.mason,
            basic_pay=Decimal("6000"), currency="MVR")
        self.subw = Employee.objects.create(
            emp_no="EMP-0002", full_name="SubWorker", job_category=self.mason,
            currency="MVR", engagement_type="SUBCONTRACT", subcontractor=self.sub)
        for e in (self.direct, self.subw):
            EmployeeSiteAllocation.objects.create(
                employee=e, site=self.site, from_date=date(2026, 1, 1))
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def test_manager_excludes_subcontract(self):
        ids = set(Employee.objects.payroll_eligible()
                  .values_list("id", flat=True))
        self.assertIn(self.direct.id, ids)
        self.assertNotIn(self.subw.id, ids)

    def _run(self):
        r = self.client.post("/api/v1/payroll/runs", {
            "site_id": self.site.id, "currency": "MVR",
            "year": 2026, "month": 5, "working_days": 31}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return self.PayrollRun.objects.get(
            site=self.site, currency="MVR", year=2026, month=5)

    def test_payroll_run_has_no_line_for_subcontract(self):
        run = self._run()
        lines = self.PayrollLine.objects.filter(run=run)
        self.assertTrue(lines.filter(employee=self.direct).exists())
        self.assertFalse(lines.filter(employee=self.subw).exists())

    def test_forcing_a_line_for_a_subcontract_worker_raises(self):
        run = self._run()
        with self.assertRaises(ValueError):
            self.PayrollLine.objects.create(run=run, employee=self.subw,
                                            basic_pay=0)

    def test_hr_register_omits_subcontract_unless_opted_in(self):
        data = self.client.get("/api/v1/employees").data
        rows = data.get("results", data) if isinstance(data, dict) else data
        nos = {r["emp_no"] for r in rows}
        self.assertIn("EMP-0001", nos)
        self.assertNotIn("EMP-0002", nos)
        data2 = self.client.get("/api/v1/employees?include_subcontract=1").data
        rows2 = data2.get("results", data2) if isinstance(data2, dict) else data2
        self.assertIn("EMP-0002", {r["emp_no"] for r in rows2})


class FridayOtPolicyTests(TestCase):
    """A worked Friday pays 12h × the worker's OT rate — not a day of basic
    (owner 2026-08-12). Workers with no OT rate earn nothing extra for it,
    and OT hours recorded on the Friday itself are never paid twice."""

    def setUp(self):
        from .models import (Attendance, EmployeeSiteAllocation,
                             ManpowerCategory, OvertimeRate)
        self.hr = make_user("fri_hr", User.Role.HO_HR)
        self.site = Site.objects.create(code="FRI", name="Friday Isle",
                                        status=Site.Status.ACTIVE)
        self.cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        OvertimeRate.objects.create(category=self.cat, currency="MVR",
                                    rate_per_hour=Decimal("25"),
                                    applies_by_default=True)
        self.emp = Employee.objects.create(
            emp_no="EMP-9001", full_name="OT Worker", basic_pay=6200,
            currency="MVR", job_category=self.cat)
        self.plain = Employee.objects.create(
            emp_no="EMP-9002", full_name="No OT Worker", basic_pay=6200,
            currency="MVR")                       # no category → no OT rate
        for e in (self.emp, self.plain):
            EmployeeSiteAllocation.objects.create(
                employee=e, site=self.site, from_date=date(2026, 1, 1))
            # Friday 1 May 2026 worked, with 3h OT also recorded on it
            Attendance.objects.create(employee=e, site=self.site,
                                      day=date(2026, 5, 1), remark="PRESENT",
                                      ot_approved=Decimal("3"))
            # a normal working day with 2h OT
            Attendance.objects.create(employee=e, site=self.site,
                                      day=date(2026, 5, 4), remark="PRESENT",
                                      ot_approved=Decimal("2"))

    def test_friday_pays_twelve_hours_at_the_ot_rate(self):
        from core import payroll
        run = payroll.generate_run(site=self.site, currency="MVR", year=2026,
                                   month=5, working_days=31, actor=self.hr)
        line = run.lines.get(employee=self.emp)
        self.assertEqual(line.fridays_worked, 1)
        # the Friday's own 3h OT is excluded — only the working day's 2h count
        self.assertEqual(float(line.ot_hours), 2.0)
        m = payroll.compute_line(line)
        self.assertEqual(float(m["friday_pay"]), 300.0)      # 12 × 25
        self.assertEqual(float(m["ot_pay"]), 50.0)           # 2 × 25

    def test_worker_without_an_ot_rate_gets_nothing_for_friday(self):
        from core import payroll
        run = payroll.generate_run(site=self.site, currency="MVR", year=2026,
                                   month=5, working_days=31, actor=self.hr)
        line = run.lines.get(employee=self.plain)
        self.assertEqual(line.fridays_worked, 1)
        self.assertEqual(float(line.ot_rate), 0.0)
        m = payroll.compute_line(line)
        self.assertEqual(float(m["friday_pay"]), 0.0)

    def test_hours_come_from_the_company_parameter(self):
        from core import payroll
        from .models import CompanyParameter
        CompanyParameter.objects.update_or_create(
            key="friday_ot_hours", defaults={"value": "8"})
        run = payroll.generate_run(site=self.site, currency="MVR", year=2026,
                                   month=5, working_days=31, actor=self.hr)
        line = run.lines.get(employee=self.emp)
        self.assertEqual(float(payroll.compute_line(line)["friday_pay"]),
                         200.0)                                  # 8 × 25


class PayrollRefreshTests(TestCase):
    """A draft run can be re-pulled from attendance / rates / policy until it
    is locked (owner 2026-08-12: the Friday policy changed after BVR's July
    run was generated, and sites are re-checking attendance)."""

    def setUp(self):
        from .models import (Attendance, EmployeeSiteAllocation,
                             ManpowerCategory, OvertimeRate)
        self.hr = make_user("rf_hr", User.Role.HO_HR)
        self.site = Site.objects.create(code="RFS", name="Refresh Isle",
                                        status=Site.Status.ACTIVE)
        self.cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        OvertimeRate.objects.create(category=self.cat, currency="MVR",
                                    rate_per_hour=Decimal("25"),
                                    applies_by_default=True)
        self.emp = Employee.objects.create(
            emp_no="EMP-7001", full_name="Worker One", basic_pay=6200,
            currency="MVR", job_category=self.cat)
        EmployeeSiteAllocation.objects.create(
            employee=self.emp, site=self.site, from_date=date(2026, 1, 1))
        Attendance.objects.create(employee=self.emp, site=self.site,
                                  day=date(2026, 5, 4), remark="PRESENT",
                                  ot_approved=Decimal("2"))
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def _run(self):
        from core import payroll
        return payroll.generate_run(site=self.site, currency="MVR", year=2026,
                                    month=5, working_days=31, actor=self.hr)

    def test_refresh_picks_up_corrected_attendance(self):
        from core import payroll
        from .models import Attendance
        run = self._run()
        line = run.lines.get(employee=self.emp)
        self.assertEqual(float(line.ot_hours), 2.0)
        # the site corrects the day and adds a worked Friday
        Attendance.objects.filter(employee=self.emp,
                                  day=date(2026, 5, 4)).update(
            ot_approved=Decimal("5"))
        Attendance.objects.create(employee=self.emp, site=self.site,
                                  day=date(2026, 5, 1), remark="PRESENT")
        summary, err = payroll.refresh_run(run, self.hr)
        self.assertIsNone(err)
        line.refresh_from_db()
        self.assertEqual(float(line.ot_hours), 5.0)
        self.assertEqual(line.fridays_worked, 1)
        self.assertIn("EMP-7001", summary["changed"])
        self.assertEqual(float(payroll.compute_line(line)["friday_pay"]),
                         300.0)                       # 12h × 25

    def test_refresh_keeps_manual_allowance_and_penalty(self):
        from core import payroll
        run = self._run()
        line = run.lines.get(employee=self.emp)
        line.allowance, line.penalty = Decimal("1500"), Decimal("200")
        line.save()
        payroll.refresh_run(run, self.hr)
        line.refresh_from_db()
        self.assertEqual(line.allowance, Decimal("1500.00"))
        self.assertEqual(line.penalty, Decimal("200.00"))

    def test_refresh_adds_a_newly_eligible_worker(self):
        from core import payroll
        from .models import EmployeeSiteAllocation
        run = self._run()
        newbie = Employee.objects.create(
            emp_no="EMP-7002", full_name="Late Joiner", basic_pay=5000,
            currency="MVR", job_category=self.cat)
        EmployeeSiteAllocation.objects.create(
            employee=newbie, site=self.site, from_date=date(2026, 5, 1))
        summary, err = payroll.refresh_run(run, self.hr)
        self.assertIsNone(err)
        self.assertIn("EMP-7002", summary["added"])
        self.assertTrue(run.lines.filter(employee=newbie).exists())

    def test_refresh_reports_but_keeps_an_ineligible_line(self):
        from core import payroll
        run = self._run()
        self.emp.is_active = False
        self.emp.save(update_fields=["is_active"])
        summary, err = payroll.refresh_run(run, self.hr)
        self.assertEqual(summary["no_longer_eligible"], ["EMP-7001"])
        self.assertTrue(run.lines.filter(employee=self.emp).exists())

    def test_locked_run_refuses_refresh(self):
        from core import payroll
        run = self._run()
        run.status = "LOCKED"
        run.save(update_fields=["status"])
        summary, err = payroll.refresh_run(run, self.hr)
        self.assertIsNone(summary)
        self.assertIn("locked", err.lower())

    def test_refresh_endpoint(self):
        run = self._run()
        r = self.client.post(f"/api/v1/payroll/runs/{run.id}",
                             {"action": "refresh"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("refresh", r.data)


class PayrollReportFridayColumnTests(TestCase):
    """The register has no Friday-money column, so Friday pay is folded into
    the allowance column — otherwise the printed columns don't add up to
    Gross (owner 2026-08-12)."""

    def setUp(self):
        from .models import (Attendance, EmployeeSiteAllocation,
                             ManpowerCategory, OvertimeRate)
        self.hr = make_user("rep_hr", User.Role.HO_HR)
        self.site = Site.objects.create(code="REP", name="Report Isle",
                                        status=Site.Status.ACTIVE)
        cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        OvertimeRate.objects.create(category=cat, currency="MVR",
                                    rate_per_hour=Decimal("25"),
                                    applies_by_default=True)
        self.emp = Employee.objects.create(
            emp_no="EMP-6001", full_name="Fri Worker", basic_pay=6200,
            currency="MVR", job_category=cat)
        EmployeeSiteAllocation.objects.create(
            employee=self.emp, site=self.site, from_date=date(2026, 1, 1))
        Attendance.objects.create(employee=self.emp, site=self.site,
                                  day=date(2026, 5, 1), remark="PRESENT")
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def test_allowance_column_carries_friday_pay(self):
        from core import payroll
        run = payroll.generate_run(site=self.site, currency="MVR", year=2026,
                                   month=5, working_days=31, actor=self.hr)
        line = run.lines.get(employee=self.emp)
        line.allowance = Decimal("500")
        line.save()
        money = payroll.compute_line(line)
        self.assertEqual(float(money["friday_pay"]), 300.0)      # 12h × 25
        from core.views_payroll import _line_info
        info = _line_info(line)
        # the register adds friday_pay into allowance, so the printed
        # Earned + Allow. + OT pay reconciles with Gross
        shown_allow = Decimal(info["allowance"]) + Decimal(info["friday_pay"])
        self.assertEqual(float(shown_allow), 800.0)              # 500 + 300
        self.assertEqual(
            float(Decimal(info["earned_basic"]) + shown_allow
                  + Decimal(info["ot_pay"])), float(info["gross"]))


class PayrollVerificationTests(TestCase):
    """Draft salary verification (owner 2026-08-12): HR submits, the site PM
    verifies their own site, the PD approves, and only then may HR lock."""

    def setUp(self):
        from .models import (EmployeeSiteAllocation, ManpowerCategory,
                             SitePmHistory, TimesheetMonth)
        self.hr = make_user("v_hr", User.Role.HO_HR)
        self.site = Site.objects.create(code="VER", name="Verify Isle",
                                        status=Site.Status.ACTIVE)
        TimesheetMonth.objects.create(site=self.site, year=2026, month=5,
                                      status="LOCKED")
        self.pm = make_user("v_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.other_pm = make_user("v_pm2", User.Role.PM)
        self.pd = make_user("v_pd", User.Role.DIRECTOR)
        cat = ManpowerCategory.objects.create(list_type="DPR", grp="LABOUR",
                                              name="Mason", sort_order=10)
        self.emp = Employee.objects.create(
            emp_no="EMP-5001", full_name="Verify Worker", job_category=cat,
            basic_pay=Decimal("6200"), currency="MVR")
        EmployeeSiteAllocation.objects.create(
            employee=self.emp, site=self.site, from_date=date(2026, 1, 1))
        self.client = APIClient()
        self.client.force_authenticate(self.hr)
        self.run = self.client.post("/api/v1/payroll/runs", {
            "site_id": self.site.id, "year": 2026, "month": 5,
            "working_days": 31}, format="json").data
        self.rid = self.run["id"]

    def _post(self, user, action, **body):
        self.client.force_authenticate(user)
        return self.client.post(f"/api/v1/payroll/runs/{self.rid}",
                                {"action": action, **body}, format="json")

    def test_full_chain_hr_pm_pd_then_lock(self):
        self.assertEqual(self.run["status"], "DRAFT")
        self.assertEqual(self._post(self.hr, "submit").data["status"],
                         "PM_REVIEW")
        self.assertEqual(self._post(self.pm, "verify").data["status"],
                         "PD_REVIEW")
        r = self._post(self.pd, "approve")
        self.assertEqual(r.data["status"], "APPROVED")
        self.assertEqual(r.data["verified_by"], self.pm.full_name)
        self.assertEqual(r.data["approved_by"], self.pd.full_name)
        self.client.force_authenticate(self.hr)
        r = self.client.post(f"/api/v1/payroll/runs/{self.rid}", {},
                             format="json")
        self.assertEqual(r.data["status"], "LOCKED")

    def test_cannot_lock_before_approval(self):
        self.client.force_authenticate(self.hr)
        r = self.client.post(f"/api/v1/payroll/runs/{self.rid}", {},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("approved", r.data["detail"])

    def test_only_the_sites_own_pm_may_verify(self):
        self._post(self.hr, "submit")
        self.assertEqual(self._post(self.other_pm, "verify").status_code, 403)
        self.assertEqual(self._post(self.pm, "verify").data["status"],
                         "PD_REVIEW")

    def test_pm_cannot_approve_as_the_director(self):
        self._post(self.hr, "submit")
        self._post(self.pm, "verify")
        self.assertEqual(self._post(self.pm, "approve").status_code, 403)

    def test_return_needs_a_reason_and_clears_signoffs(self):
        self._post(self.hr, "submit")
        self._post(self.pm, "verify")
        self.assertEqual(self._post(self.pd, "return").status_code, 400)
        r = self._post(self.pd, "return", reason="OT hours look wrong")
        self.assertEqual(r.data["status"], "RETURNED")
        self.assertIsNone(r.data["verified_by"])
        self.assertEqual(r.data["return_reason"], "OT hours look wrong")

    def test_editing_a_line_sends_it_back_to_draft(self):
        self._post(self.hr, "submit")
        self._post(self.pm, "verify")
        self._post(self.pd, "approve")
        self.client.force_authenticate(self.hr)
        line_id = self.run["lines"][0]["id"]
        self.client.patch(f"/api/v1/payroll/lines/{line_id}",
                          {"allowance": 500}, format="json")
        d = self.client.get(f"/api/v1/payroll/runs/{self.rid}").data
        self.assertEqual(d["status"], "DRAFT")
        self.assertIsNone(d["approved_by"])      # the sign-off is void

    def test_pm_and_pd_can_open_the_run_they_must_verify(self):
        self._post(self.hr, "submit")
        self.client.force_authenticate(self.pm)
        self.assertEqual(
            self.client.get(f"/api/v1/payroll/runs/{self.rid}").status_code, 200)
        self.client.force_authenticate(self.pd)
        self.assertEqual(
            self.client.get(f"/api/v1/payroll/runs/{self.rid}").status_code, 200)
        self.client.force_authenticate(self.other_pm)
        self.assertEqual(
            self.client.get(f"/api/v1/payroll/runs/{self.rid}").status_code, 403)

    def test_usd_run_skips_the_pm_and_goes_to_the_director(self):
        from core import payroll
        run = payroll.generate_run(site=None, currency="USD", year=2026,
                                   month=6, working_days=30, actor=self.hr)
        r, err = payroll.set_run_status(run, "submit", self.hr)
        self.assertIsNone(err)
        self.assertEqual(r.status, "PD_REVIEW")

    def test_pending_queue_shows_the_run_to_pm_then_pd(self):
        self._post(self.hr, "submit")
        self.client.force_authenticate(self.pm)
        groups = self.client.get("/api/v1/approvals/pending").data["groups"]
        self.assertTrue(any("verify" in g["title"].lower() for g in groups))
        self._post(self.pm, "verify")
        self.client.force_authenticate(self.pd)
        groups = self.client.get("/api/v1/approvals/pending").data["groups"]
        self.assertTrue(any("salary" in g["title"].lower() for g in groups))

    def test_queue_row_carries_the_run_id(self):
        """A run isn't a Document, so its `ref` can't be opened by the document
        viewer — PMs got "Not found." until the row carried the id (owner
        2026-08-12). The id is also what keeps two sites' same-month runs from
        colliding in the list."""
        self._post(self.hr, "submit")
        self.client.force_authenticate(self.pm)
        groups = self.client.get("/api/v1/approvals/pending").data["groups"]
        rows = [i for g in groups for i in g["items"]
                if i["doc_type"] == "PAY"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["run_id"], self.rid)
        # and that id opens the run the PM was sent to verify
        self.assertEqual(self.client.get(
            f"/api/v1/payroll/runs/{rows[0]['run_id']}").status_code, 200)

    def test_two_sites_same_month_are_distinguishable(self):
        """Same label, different rows — the UI keys on run_id, so both must be
        present and separable."""
        from core import payroll
        other = Site.objects.create(code="ZZZ", name="Other site",
                                    status=Site.Status.ACTIVE)
        SitePmHistory.objects.create(site=other, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        # same period as the fixture run, which is what makes the labels clash
        run2 = payroll.generate_run(site=other, currency="MVR", year=2026,
                                    month=5, working_days=31, actor=self.hr)
        payroll.set_run_status(run2, "submit", self.hr)
        self._post(self.hr, "submit")
        self.client.force_authenticate(self.pm)
        groups = self.client.get("/api/v1/approvals/pending").data["groups"]
        rows = [i for g in groups for i in g["items"]
                if i["doc_type"] == "PAY"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({r["ref"] for r in rows}), 1)      # same label…
        self.assertEqual(len({r["run_id"] for r in rows}), 2)   # …distinct ids


class PaidWindowTests(TestCase):
    """Joining, leaving and transferring mid-month (owner 2026-08-13).

    Sites reported full salaries paid to workers who joined mid-July, and to
    workers who had not joined until August. Membership of a run used to be
    "whoever is allocated to this site today", which ignored the month
    entirely in both directions.
    """

    def setUp(self):
        from .models import (EmployeeSiteAllocation, ManpowerCategory,
                             TimesheetMonth)
        self.hr = make_user("w_hr", User.Role.HO_HR)
        self.site = Site.objects.create(code="WIN", name="Window Isle",
                                        status=Site.Status.ACTIVE)
        self.other = Site.objects.create(code="WIN2", name="Other Isle",
                                         status=Site.Status.ACTIVE)
        TimesheetMonth.objects.create(site=self.site, year=2026, month=7,
                                      status="LOCKED")
        self.cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.alloc = EmployeeSiteAllocation
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def _worker(self, emp_no, from_date, to_date=None, join_date=None,
                site=None, mark=True):
        emp = Employee.objects.filter(emp_no=emp_no).first() or (
            Employee.objects.create(
                emp_no=emp_no, full_name=emp_no, job_category=self.cat,
                basic_pay=Decimal("3100"), currency="MVR",
                join_date=join_date))
        self.alloc.objects.create(employee=emp, site=site or self.site,
                                  from_date=from_date, to_date=to_date)
        if mark:
            self._mark(emp, from_date, to_date, join_date, site or self.site)
        return emp

    def _mark(self, emp, from_date, to_date, join_date, site):
        """Give the worker the register their scenario implies.

        These cases are about the *window*, and used to lean on "no
        attendance at all" to mean "no absences". That is no longer the same
        thing: an empty register now pays nothing, because two BVR men were
        each paid a full month on one (owner 2026-08-14). Marking the days the
        scenario says they worked keeps each test testing what it means to.
        """
        from .models import Attendance

        start = max(from_date, date(2026, 7, 1))
        if join_date:
            start = max(start, join_date)
        end = min(to_date or date(2026, 7, 31), date(2026, 7, 31))
        day = start
        while day <= end:
            if day.isoweekday() in site.working_days:
                Attendance.objects.create(employee=emp, site=site, day=day,
                                          remark="PRESENT", normal_hours=8)
            day += timedelta(days=1)

    def _run(self):
        return payroll.generate_run(site=self.site, currency="MVR", year=2026,
                                    month=7, working_days=31, actor=self.hr)

    def _days(self, run, emp_no):
        line = run.lines.filter(employee__emp_no=emp_no).first()
        return None if line is None else float(line.days_worked)

    def test_full_month_worker_gets_the_whole_month(self):
        self._worker("W-FULL", date(2026, 6, 1))
        self.assertEqual(self._days(self._run(), "W-FULL"), 31.0)

    def test_mid_month_joiner_is_pro_rated_from_the_allocation(self):
        """Allocated on the 16th → 16 payable days (16th–31st), not 31."""
        self._worker("W-MID", date(2026, 7, 16))
        self.assertEqual(self._days(self._run(), "W-MID"), 16.0)

    def test_join_date_wins_when_it_is_later_than_the_allocation(self):
        self._worker("W-JD", date(2026, 7, 1), join_date=date(2026, 7, 22))
        self.assertEqual(self._days(self._run(), "W-JD"), 10.0)

    def test_worker_allocated_next_month_is_not_on_this_run(self):
        """The August joiner who was paid for July."""
        self._worker("W-AUG", date(2026, 8, 12))
        self.assertIsNone(self._days(self._run(), "W-AUG"))

    def test_worker_who_joined_the_company_next_month_is_excluded(self):
        self._worker("W-AUGJD", date(2026, 7, 1), join_date=date(2026, 8, 3))
        self.assertIsNone(self._days(self._run(), "W-AUGJD"))

    def test_mid_month_leaver_is_still_paid_for_the_days_worked(self):
        """Previously dropped from the run entirely — paid nothing."""
        emp = self._worker("W-LEFT", date(2026, 7, 1),
                           to_date=date(2026, 7, 10))
        emp.is_active = False           # leavers get deactivated
        emp.save()
        self.assertEqual(self._days(self._run(), "W-LEFT"), 10.0)

    def test_a_transfer_is_split_between_the_two_sites(self):
        """Neither site pays a whole month for the same person."""
        self._worker("W-XFER", date(2026, 7, 1), to_date=date(2026, 7, 11))
        self._worker("W-XFER", date(2026, 7, 12), site=self.other)
        here = self._days(self._run(), "W-XFER")
        there_run = payroll.generate_run(site=self.other, currency="MVR",
                                         year=2026, month=7, working_days=31,
                                         actor=self.hr)
        there = self._days(there_run, "W-XFER")
        self.assertEqual((here, there), (11.0, 20.0))
        self.assertEqual(here + there, 31.0)      # exactly one month, once

    def test_long_gone_worker_with_an_untidied_allocation_stays_out(self):
        emp = self._worker("W-GONE", date(2025, 1, 1))
        emp.is_active = False
        emp.save()
        self.assertIsNone(self._days(self._run(), "W-GONE"))

    def test_refresh_applies_the_same_window_as_generate(self):
        """The two used to keep their own copy of the rule and drifted."""
        self._worker("W-MID2", date(2026, 7, 16))
        run = self._run()
        run.lines.update(days_worked=Decimal("31"))    # pretend a stale line
        summary, err = payroll.refresh_run(run, self.hr)
        self.assertIsNone(err)
        self.assertEqual(self._days(run, "W-MID2"), 16.0)


class RestDayForfeitTests(TestCase):
    """A rest day is unmarked and normally paid as part of the month, but a
    worker absent most of the week has not earned it (owner 2026-08-13:
    "if worker was absent for more than 3 days during the week then his rest
    day will not be counted as pay day"). EMP-0078 drew 8 days' pay for 5
    days of work in July because three unworked Fridays came free."""

    def setUp(self):
        from .models import (Attendance, EmployeeSiteAllocation,
                             ManpowerCategory, TimesheetMonth)
        self.Att = Attendance
        self.hr = make_user("rd_hr", User.Role.HO_HR)
        # Mon-Thu, Sat, Sun — Friday (5) is the rest day, as at SSR.
        self.site = Site.objects.create(code="RST", name="Rest Isle",
                                        status=Site.Status.ACTIVE,
                                        working_days=[1, 2, 3, 4, 6, 7])
        TimesheetMonth.objects.create(site=self.site, year=2026, month=7,
                                      status="LOCKED")
        cat = ManpowerCategory.objects.create(list_type="DPR", grp="LABOUR",
                                              name="Mason", sort_order=10)
        self.emp = Employee.objects.create(
            emp_no="RD-0001", full_name="Rest Worker", job_category=cat,
            basic_pay=Decimal("3100"), currency="MVR")
        EmployeeSiteAllocation.objects.create(
            employee=self.emp, site=self.site, from_date=date(2026, 7, 1))

    def _mark(self, days, remark):
        for d in days:
            self.Att.objects.create(employee=self.emp, site=self.site,
                                    day=date(2026, 7, d), remark=remark,
                                    normal_hours=8)

    def _days(self):
        d, _, _, _ = payroll._attendance_prefill(self.emp, self.site, 2026, 7,
                                                 31)
        return float(d)

    def test_a_good_attender_keeps_the_unworked_rest_day(self):
        """The whole month bar the Fridays — all 31 days paid."""
        fridays = {3, 10, 17, 24, 31}
        self._mark([d for d in range(1, 32) if d not in fridays], "PRESENT")
        self.assertEqual(self._days(), 31.0)

    def test_a_week_with_three_absences_still_keeps_its_rest_day(self):
        """Three is not 'more than three'."""
        fridays = {3, 10, 17, 24, 31}
        self._mark([d for d in range(1, 32) if d not in fridays], "PRESENT")
        self.Att.objects.filter(day__in=[date(2026, 7, d)
                                         for d in (6, 7, 8)]).update(
            remark="ABSENT")
        self.assertEqual(self._days(), 28.0)     # 31 − 3 absences, Friday kept

    def test_a_week_with_four_absences_forfeits_its_rest_day(self):
        fridays = {3, 10, 17, 24, 31}
        self._mark([d for d in range(1, 32) if d not in fridays], "PRESENT")
        self.Att.objects.filter(day__in=[date(2026, 7, d)
                                         for d in (6, 7, 8, 9)]).update(
            remark="ABSENT")
        # 31 − 4 absences − the 10th (that week's unworked Friday)
        self.assertEqual(self._days(), 26.0)

    def test_a_worked_rest_day_is_never_forfeited(self):
        """If he turned up on the Friday it is his, however the week went."""
        fridays = {3, 10, 17, 24, 31}
        self._mark([d for d in range(1, 32) if d not in fridays], "PRESENT")
        self._mark([10], "PRESENT")              # worked that Friday
        self.Att.objects.filter(day__in=[date(2026, 7, d)
                                         for d in (6, 7, 8, 9)]).update(
            remark="ABSENT")
        self.assertEqual(self._days(), 27.0)     # 32 marked − 4 − 1 unworked

    def test_leave_and_sick_do_not_cost_the_rest_day(self):
        """They already cost the day itself; they are not misconduct."""
        fridays = {3, 10, 17, 24, 31}
        self._mark([d for d in range(1, 32) if d not in fridays], "PRESENT")
        self.Att.objects.filter(day__in=[date(2026, 7, d)
                                         for d in (6, 7, 8, 9)]).update(
            remark="LEAVE")
        self.assertEqual(self._days(), 27.0)     # 31 − 4, Friday kept

    def test_the_limit_is_a_company_parameter(self):
        from .models import CompanyParameter
        fridays = {3, 10, 17, 24, 31}
        self._mark([d for d in range(1, 32) if d not in fridays], "PRESENT")
        self.Att.objects.filter(day__in=[date(2026, 7, d)
                                         for d in (6, 7)]).update(
            remark="ABSENT")
        self.assertEqual(self._days(), 29.0)          # 2 absences, Friday kept
        CompanyParameter.objects.update_or_create(
            key="rest_day_absence_limit", defaults={"value": "1"})
        self.assertEqual(self._days(), 28.0)          # now 2 > 1, Friday gone

    def test_the_pm_can_strike_the_rest_day_for_one_worker(self):
        """EMP-0078's case: absent through the week, so no rest day at all —
        the site PM makes that call, not a global threshold (owner
        2026-08-13)."""
        fridays = {3, 10, 17, 24, 31}
        self._mark([d for d in range(1, 32) if d not in fridays], "PRESENT")
        run = payroll.generate_run(site=self.site, currency="MVR", year=2026,
                                   month=7, working_days=31, actor=self.hr)
        line = run.lines.get(employee=self.emp)
        self.assertEqual(float(line.days_worked), 31.0)   # 26 marked + 5 rest
        payroll.set_rest_day_revoked(line, True, self.hr)
        line.refresh_from_db()
        self.assertEqual(float(line.days_worked), 26.0)   # the 5 Fridays gone
        self.assertTrue(line.rest_day_revoked)

    def test_a_refresh_does_not_undo_the_pm_decision(self):
        """The reason it is a flag and not a hand-edited day count."""
        fridays = {3, 10, 17, 24, 31}
        self._mark([d for d in range(1, 32) if d not in fridays], "PRESENT")
        run = payroll.generate_run(site=self.site, currency="MVR", year=2026,
                                   month=7, working_days=31, actor=self.hr)
        line = run.lines.get(employee=self.emp)
        payroll.set_rest_day_revoked(line, True, self.hr)
        payroll.refresh_run(run, self.hr)
        line.refresh_from_db()
        self.assertEqual(float(line.days_worked), 26.0)
        self.assertTrue(line.rest_day_revoked)

    def test_restoring_puts_the_rest_days_back(self):
        fridays = {3, 10, 17, 24, 31}
        self._mark([d for d in range(1, 32) if d not in fridays], "PRESENT")
        run = payroll.generate_run(site=self.site, currency="MVR", year=2026,
                                   month=7, working_days=31, actor=self.hr)
        line = run.lines.get(employee=self.emp)
        payroll.set_rest_day_revoked(line, True, self.hr)
        payroll.set_rest_day_revoked(line, False, self.hr)
        line.refresh_from_db()
        self.assertEqual(float(line.days_worked), 31.0)
        self.assertFalse(line.rest_day_revoked)

    def test_a_locked_run_cannot_be_touched(self):
        fridays = {3, 10, 17, 24, 31}
        self._mark([d for d in range(1, 32) if d not in fridays], "PRESENT")
        run = payroll.generate_run(site=self.site, currency="MVR", year=2026,
                                   month=7, working_days=31, actor=self.hr)
        run.status = "LOCKED"
        run.save(update_fields=["status"])
        line = run.lines.get(employee=self.emp)
        _, err = payroll.set_rest_day_revoked(line, True, self.hr)
        self.assertIsNotNone(err)


class RegisterOutranksPaperworkTests(TestCase):
    """The paid window may not throw away a day the site actually marked.

    BVR's July run came back wrong in both directions (owner 2026-08-14):
    twenty-nine workers carried an allocation `from_date` of 2026-07-12 — the
    day the site was loaded into the app, not the day anyone started — so
    eleven worked days vanished off every one of them; and two men with no
    attendance row at all were each paid a full 31 days.
    """

    def setUp(self):
        from .models import (Attendance, EmployeeSiteAllocation,
                             ManpowerCategory)
        self.Att = Attendance
        self.hr = make_user("reg_hr", User.Role.HO_HR)
        # Fri (5) is the rest day.
        self.site = Site.objects.create(code="REG", name="Register Isle",
                                        status=Site.Status.ACTIVE,
                                        working_days=[1, 2, 3, 4, 6, 7])
        self.other = Site.objects.create(code="RG2", name="Register Two",
                                         status=Site.Status.ACTIVE,
                                         working_days=[1, 2, 3, 4, 6, 7])
        self.cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.Alloc = EmployeeSiteAllocation

    def _emp(self, no, **kw):
        return Employee.objects.create(
            emp_no=no, full_name=f"Worker {no}", job_category=self.cat,
            basic_pay=Decimal("3100"), currency="MVR", **kw)

    def _mark(self, emp, days, remark="PRESENT", site=None):
        for d in days:
            self.Att.objects.create(employee=emp, site=site or self.site,
                                    day=date(2026, 7, d), remark=remark,
                                    normal_hours=8)

    def _days(self, emp, site=None):
        d, _, _, _ = payroll._attendance_prefill(
            emp, self.site if site is None else site, 2026, 7, 31)
        return float(d)

    def test_a_late_allocation_does_not_erase_days_already_marked(self):
        """The BVR fault: allocated on the 12th, marked from the 1st."""
        e = self._emp("REG-0001")
        self.Alloc.objects.create(employee=e, site=self.site,
                                  from_date=date(2026, 7, 12))
        self._mark(e, [d for d in range(1, 32) if d not in (3, 10, 17, 24, 31)])
        start, end = payroll.paid_window(e, self.site, 2026, 7)
        self.assertEqual((start, end), (date(2026, 7, 1), date(2026, 7, 31)))
        self.assertEqual(self._days(e), 31.0)

    def test_a_join_date_after_the_month_cannot_unpay_a_worked_month(self):
        """Sahajalal: join date 1 August, 28 days of July attendance."""
        e = self._emp("REG-0002", join_date=date(2026, 8, 1))
        self.Alloc.objects.create(employee=e, site=self.site,
                                  from_date=date(2026, 7, 12))
        self._mark(e, [d for d in range(1, 29) if d not in (3, 10, 17, 24)])
        self.assertGreaterEqual(self._days(e), 28.0)

    def test_an_empty_register_pays_nothing_rather_than_a_full_month(self):
        """EMP-0404 and EMP-0405 drew MVR 16,500 between them on no rows."""
        e = self._emp("REG-0003")
        self.Alloc.objects.create(employee=e, site=self.site,
                                  from_date=date(2026, 7, 1))
        days, ot, fridays, rest = payroll._attendance_prefill(
            e, self.site, 2026, 7, 31)
        self.assertEqual((float(days), float(ot), fridays, rest), (0.0, 0.0, 0, 0))

    def test_a_genuine_transfer_still_splits_between_the_two_sites(self):
        """The case the clamp was built for must survive the widening: the
        register itself stops at the old site and starts at the new one."""
        e = self._emp("REG-0004")
        self.Alloc.objects.create(employee=e, site=self.site,
                                  from_date=date(2026, 7, 1),
                                  to_date=date(2026, 7, 11))
        self.Alloc.objects.create(employee=e, site=self.other,
                                  from_date=date(2026, 7, 12))
        self._mark(e, [d for d in range(1, 12) if d != 3])
        self._mark(e, [d for d in range(12, 32) if d not in (17, 24, 31)],
                   site=self.other)
        self.assertEqual(payroll.paid_window(e, self.site, 2026, 7),
                         (date(2026, 7, 1), date(2026, 7, 11)))
        self.assertEqual(payroll.paid_window(e, self.other, 2026, 7),
                         (date(2026, 7, 12), date(2026, 7, 31)))
        self.assertEqual(self._days(e) + self._days(e, self.other), 31.0)

    def test_a_stray_mark_at_the_old_site_does_not_double_pay_the_month(self):
        """Widening follows the register, so a wrongly-marked day after a
        transfer is visible as days on both runs — but it is one day, not a
        second month."""
        e = self._emp("REG-0005")
        self.Alloc.objects.create(employee=e, site=self.site,
                                  from_date=date(2026, 7, 1),
                                  to_date=date(2026, 7, 11))
        self._mark(e, list(range(1, 12)) + [20])
        self.assertEqual(payroll.paid_window(e, self.site, 2026, 7),
                         (date(2026, 7, 1), date(2026, 7, 20)))
        self.assertLess(self._days(e), 31.0)

    def test_the_run_reports_what_the_register_holds(self):
        from .models import PayrollRun
        e = self._emp("REG-0006")
        self.Alloc.objects.create(employee=e, site=self.site,
                                  from_date=date(2026, 7, 1))
        self._mark(e, [1, 2, 4, 5])
        self._mark(e, [6, 7], remark="ABSENT")
        run = payroll.generate_run(site=self.site, currency="MVR", year=2026,
                                   month=7, working_days=31, actor=self.hr)
        summary = payroll.register_summary(run)
        self.assertEqual(summary[e.id],
                         {"marked": 6, "present": 4, "absent": 2})

    def test_generate_run_keeps_a_worker_the_paperwork_would_have_dropped(self):
        """paid_window decides who is skipped at generate time too."""
        from .models import PayrollRun
        e = self._emp("REG-0007", join_date=date(2026, 8, 1))
        self.Alloc.objects.create(employee=e, site=self.site,
                                  from_date=date(2026, 8, 1))
        self._mark(e, [d for d in range(1, 29) if d not in (3, 10, 17, 24)])
        run = payroll.generate_run(site=self.site, currency="MVR", year=2026,
                                   month=7, working_days=31, actor=self.hr)
        self.assertEqual(run.lines.count(), 1)
        self.assertGreaterEqual(float(run.lines.first().days_worked), 28.0)
