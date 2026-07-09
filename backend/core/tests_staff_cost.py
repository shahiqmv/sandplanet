"""M7 — staff cost posted at timesheet month lock (§6C.3.5)."""
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.test import TestCase
from rest_framework.test import APIClient

from . import staff_cost
from .models import (Attendance, CompanyParameter, CostPosting, Employee,
                     EmployeeSiteAllocation, ManpowerCategory, Site,
                     SitePmHistory, User)
from .tests import make_user


class StaffCostBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.hr = make_user("hr1", User.Role.HO_HR)
        CompanyParameter.objects.create(key="ot_multiplier", value=1.25)
        CompanyParameter.objects.create(key="hourly_rate_divisor", value=240)
        self.cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.emp = Employee.objects.create(
            emp_no="EMP-0001", full_name="Kumar Perera", basic_pay=9600,
            job_category=self.cat)
        EmployeeSiteAllocation.objects.create(
            employee=self.emp, site=self.site, from_date=date(2025, 1, 1))
        self.client = APIClient()

    def attend(self, y, m, days, ot_approved=0):
        for d in days:
            Attendance.objects.create(
                employee=self.emp, site=self.site, day=date(y, m, d),
                remark="PRESENT", ot_approved=ot_approved if d == days[0]
                else 0)

    def lock(self, y, m, user=None):
        self.client.force_authenticate(user or self.pm)
        return self.client.post(
            f"/api/v1/timesheets/{self.site.id}/{y}/{m}/lock")

    def reopen(self, y, m):
        self.client.force_authenticate(self.hr)
        return self.client.post(
            f"/api/v1/timesheets/{self.site.id}/{y}/{m}/reopen",
            {"reason": "correction"}, format="json")


class StaffCostPostingTests(StaffCostBase):
    def test_lock_posts_single_site_full_basic(self):
        self.attend(2026, 5, [5, 6, 7])
        r = self.lock(2026, 5)
        self.assertEqual(r.status_code, 200, r.data)
        posts = CostPosting.objects.filter(source="STAFF", state="INCURRED",
                                           staff_year=2026, staff_month=5,
                                           reversal_of__isnull=True)
        self.assertEqual(posts.count(), 1)
        # single site → full basic, no OT
        self.assertEqual(posts.first().amount, Decimal("9600.00"))
        self.assertEqual(posts.first().cost_head.name, "Labour & Staff")

    def test_lock_includes_approved_ot(self):
        # 10h approved OT: hourly = 9600/240 = 40; OT = 10*40*1.25 = 500
        self.attend(2026, 5, [5, 6], ot_approved=10)
        self.lock(2026, 5)
        net = CostPosting.objects.filter(
            source="STAFF", staff_year=2026, staff_month=5).aggregate(
            t=Sum("amount"))["t"]
        self.assertEqual(net, Decimal("10100.00"))  # 9600 + 500

    def test_lock_is_idempotent(self):
        self.attend(2026, 5, [5, 6])
        self.lock(2026, 5)
        # second lock attempt is rejected (already locked) — no double post
        self.assertEqual(self.lock(2026, 5).status_code, 400)
        self.assertEqual(CostPosting.objects.filter(
            source="STAFF", reversal_of__isnull=True).count(), 1)

    def test_reopen_reverses_relock_reposts(self):
        self.attend(2026, 5, [5, 6])
        self.lock(2026, 5)
        self.reopen(2026, 5)
        net = staff_cost.history(self.site)
        # net zero after reversal
        self.assertTrue(all(h["amount"] == 0 for h in net) or net == [])
        self.assertEqual(CostPosting.objects.filter(source="STAFF").count(), 2)
        # relock reposts a fresh original; net = one month's cost
        self.lock(2026, 5)
        total = CostPosting.objects.filter(
            source="STAFF").aggregate(t=Sum("amount"))["t"]
        self.assertEqual(total, Decimal("9600.00"))


class StaffCostReportingTests(StaffCostBase):
    def test_current_run_rate_from_headcount(self):
        rr = staff_cost.current_run_rate()
        self.assertEqual(rr["total_headcount"], 1)
        self.assertEqual(rr["total_monthly_basic"], Decimal("9600"))
        self.assertEqual(rr["sites"][0]["site"], "SJR")
        self.assertEqual(rr["sites"][0]["by_category"][0]["category"], "Mason")

    def test_history_lists_locked_months(self):
        self.attend(2026, 5, [5, 6])
        self.lock(2026, 5)
        h = staff_cost.history(self.site)
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["amount"], Decimal("9600.00"))
        self.assertEqual(h[0]["month"], 5)

    def test_current_endpoint_gated(self):
        # HR sees it; a site user does not (§6C.5)
        self.client.force_authenticate(self.hr)
        self.assertEqual(
            self.client.get("/api/v1/staff-cost/current").status_code, 200)
        sa = make_user("sa9", User.Role.SITE_ADMIN, site=self.site)
        self.client.force_authenticate(sa)
        self.assertEqual(
            self.client.get("/api/v1/staff-cost/current").status_code, 403)
