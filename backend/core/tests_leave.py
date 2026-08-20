"""Worker leave: move him to Head Office, pay it or don't (owner 2026-08-20)."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import leave as lv_svc
from . import payroll
from .models import (Attendance, Employee, EmployeeSiteAllocation,
                     ManpowerCategory, Site, User, WorkerLeave)
from .tests import make_user


class LeaveBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE)
        self.ho = Site.objects.create(code="MLE", name="Head Office",
                                      status=Site.Status.ACTIVE,
                                      is_head_office=True)
        self.hr = make_user("hr1", User.Role.HO_HR)
        self.sa = make_user("sa1", User.Role.SITE_ADMIN, site=self.site)
        self.cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        self.emp = Employee.objects.create(
            emp_no="EMP-0001", full_name="Kumar", job_category=self.cat,
            basic_pay=Decimal("6200"), currency="MVR",
            join_date=date(2025, 1, 1))
        EmployeeSiteAllocation.objects.create(employee=self.emp, site=self.site,
                                              from_date=date(2025, 1, 1))
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def _grant(self, kind, start, end, **kw):
        return self.client.post("/api/v1/leaves", {
            "employee_id": self.emp.id, "kind": kind,
            "from_date": start.isoformat(), "to_date": end.isoformat(),
            **kw}, format="json")

    def current_site(self):
        row = self.emp.site_allocations.filter(to_date__isnull=True).first()
        return row.site if row else None


class GrantTests(LeaveBase):
    def test_paid_leave_moves_him_to_head_office_and_marks_the_days(self):
        r = self._grant("PAID", date(2026, 5, 4), date(2026, 5, 10),
                        reason="Annual leave")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.current_site(), self.ho)
        marks = Attendance.objects.filter(employee=self.emp,
                                          remark="PAID_LEAVE")
        # Every working day of the window is marked, and against Head Office —
        # he is not at his site, so his site must not count him as manpower.
        self.assertEqual(marks.count(),
                         len(lv_svc._working_days(self.ho, date(2026, 5, 4),
                                                  date(2026, 5, 10))))
        self.assertTrue(all(m.site_id == self.ho.id for m in marks))

    def test_unpaid_leave_marks_nothing_and_clears_what_was_there(self):
        # A PRESENT entered before the leave was granted would still pay him.
        Attendance.objects.create(employee=self.emp, site=self.site,
                                  day=date(2026, 5, 5), remark="PRESENT")
        r = self._grant("UNPAID", date(2026, 5, 4), date(2026, 5, 10))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.current_site(), self.ho)
        self.assertFalse(Attendance.objects.filter(
            employee=self.emp, day__gte=date(2026, 5, 4),
            day__lte=date(2026, 5, 10)).exists())

    def test_overlapping_leave_refused(self):
        self._grant("PAID", date(2026, 5, 4), date(2026, 5, 10))
        r = self._grant("UNPAID", date(2026, 5, 8), date(2026, 5, 12))
        self.assertEqual(r.status_code, 400)
        self.assertIn("already has leave", r.data["detail"])

    def test_end_before_start_refused(self):
        r = self._grant("PAID", date(2026, 5, 10), date(2026, 5, 4))
        self.assertEqual(r.status_code, 400)

    def test_site_team_cannot_grant_leave(self):
        self.client.force_authenticate(self.sa)
        r = self._grant("PAID", date(2026, 5, 4), date(2026, 5, 10))
        self.assertEqual(r.status_code, 403)


class AttendanceBlockTests(LeaveBase):
    def _mark(self, day, user=None):
        self.client.force_authenticate(user or self.sa)
        return self.client.put("/api/v1/attendance/bulk", {
            "site": self.site.id, "date": day.isoformat(),
            "rows": [{"employee_id": self.emp.id, "check_in": "07:00",
                      "check_out": "18:00", "remark": "PRESENT"}],
        }, format="json")

    def _recent_window(self):
        """A past window — attendance refuses future days."""
        end = date.today() - timedelta(days=1)
        return end - timedelta(days=4), end

    def test_unpaid_leave_days_cannot_be_marked(self):
        start, end = self._recent_window()
        self.assertEqual(self._grant("UNPAID", start, end).status_code, 201)
        r = self._mark(end)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["saved"], 0)
        self.assertIn("leave without pay", r.data["refused"][0])
        self.assertFalse(Attendance.objects.filter(employee=self.emp,
                                                   day=end).exists())

    def test_marking_resumes_after_the_leave_ends(self):
        start, end = self._recent_window()
        self.assertEqual(self._grant("UNPAID", start, end).status_code, 201)
        after = date.today()
        r = self._mark(after)
        self.assertEqual(r.data["saved"], 1, r.data)

    def test_paid_leave_stays_editable(self):
        # Paid days are pre-marked, not frozen — HR may need to correct one.
        start, end = self._recent_window()
        self.assertEqual(self._grant("PAID", start, end).status_code, 201)
        r = self._mark(end, user=self.hr)
        self.assertEqual(r.data["saved"], 1, r.data)


class PayrollEffectTests(LeaveBase):
    """The whole point: paid leave pays, leave without pay does not."""

    def _mark_month_present(self, skip=()):
        for d in range(1, 32):
            day = date(2026, 5, d)
            if day.isoweekday() not in self.site.working_days or day in skip:
                continue
            Attendance.objects.create(employee=self.emp, site=self.site,
                                      day=day, remark="PRESENT",
                                      normal_hours=8)

    def _days(self):
        run = payroll.generate_run(site=None, currency="MVR", year=2026,
                                   month=5, working_days=31, actor=self.hr)
        return float(run.lines.get(employee=self.emp).days_worked)

    def test_paid_leave_days_are_paid(self):
        self._mark_month_present()
        full = self._days()
        window = (date(2026, 5, 4), date(2026, 5, 10))
        self.assertEqual(self._grant("PAID", *window).status_code, 201)
        # Same day count: the PAID_LEAVE marks replaced the PRESENT ones.
        self.assertEqual(self._days(), full)

    def test_unpaid_leave_days_are_not_paid(self):
        self._mark_month_present()
        full = self._days()
        window = (date(2026, 5, 4), date(2026, 5, 10))
        lost = len(lv_svc._working_days(self.site, *window))
        self.assertEqual(self._grant("UNPAID", *window).status_code, 201)
        self.assertEqual(self._days(), full - lost)

    def test_blocked_days_lists_unpaid_only(self):
        self._grant("UNPAID", date(2026, 5, 4), date(2026, 5, 6))
        blocked = lv_svc.blocked_days(self.emp, 2026, 5)
        self.assertEqual(blocked, {date(2026, 5, 4), date(2026, 5, 5),
                                   date(2026, 5, 6)})
        self.assertEqual(lv_svc.blocked_days(self.emp, 2026, 6), set())


class ReturnTests(LeaveBase):
    def test_return_puts_him_back_on_his_own_site_from_that_day(self):
        r = self._grant("PAID", date(2026, 5, 4), date(2026, 5, 10))
        lv_id = r.data["id"]
        self.assertEqual(self.current_site(), self.ho)
        back = self.client.post(f"/api/v1/leaves/{lv_id}/return",
                                {"on": "2026-05-11"}, format="json")
        self.assertEqual(back.status_code, 200, back.data)
        self.assertEqual(self.current_site(), self.site)
        self.assertFalse(back.data["open"])
        # He is at the site ON his return date, not the day after — otherwise
        # his first day back cannot be marked.
        row = self.emp.site_allocations.filter(site=self.site,
                                               to_date__isnull=True).get()
        self.assertEqual(row.from_date, date(2026, 5, 11))

    def test_early_return_removes_the_paid_days_he_did_not_take(self):
        lv_id = self._grant("PAID", date(2026, 5, 4),
                            date(2026, 5, 20)).data["id"]
        self.client.post(f"/api/v1/leaves/{lv_id}/return",
                         {"on": "2026-05-11"}, format="json")
        left = Attendance.objects.filter(employee=self.emp,
                                         remark="PAID_LEAVE")
        # Days he was actually away stay paid; the rest are gone, or he would
        # be paid for them AND for the days he now works.
        self.assertTrue(left.exists())
        self.assertFalse(left.filter(day__gte=date(2026, 5, 11)).exists())

    def test_return_on_the_first_day_refused_as_a_cancel(self):
        lv_id = self._grant("PAID", date(2026, 5, 4),
                            date(2026, 5, 10)).data["id"]
        r = self.client.post(f"/api/v1/leaves/{lv_id}/return",
                             {"on": "2026-05-04"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cancel the leave", r.data["detail"])

    def test_return_twice_refused(self):
        lv_id = self._grant("PAID", date(2026, 5, 4), date(2026, 5, 10)).data["id"]
        self.client.post(f"/api/v1/leaves/{lv_id}/return",
                         {"on": "2026-05-11"}, format="json")
        again = self.client.post(f"/api/v1/leaves/{lv_id}/return",
                                 {"on": "2026-05-12"}, format="json")
        self.assertEqual(again.status_code, 400)

    def test_cancel_undoes_the_move_and_the_marks(self):
        lv_id = self._grant("PAID", date(2026, 5, 4), date(2026, 5, 10)).data["id"]
        r = self.client.post(f"/api/v1/leaves/{lv_id}/cancel", {},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.current_site(), self.site)
        self.assertFalse(Attendance.objects.filter(
            employee=self.emp, remark="PAID_LEAVE").exists())

    def test_cancel_leaves_no_head_office_spell_behind(self):
        lv_id = self._grant("PAID", date(2026, 5, 4), date(2026, 5, 10)).data["id"]
        self.client.post(f"/api/v1/leaves/{lv_id}/cancel", {}, format="json")
        rows = list(self.emp.site_allocations.all())
        # One unbroken posting to his own site, exactly as before the mistake —
        # not a Head Office stint overlapping the site he never left.
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].site_id, rows[0].from_date, rows[0].to_date),
                         (self.site.id, date(2025, 1, 1), None))

    def test_overdue_lists_leave_nobody_closed(self):
        past = date.today() - timedelta(days=30)
        self._grant("PAID", past, past + timedelta(days=5))
        self.assertEqual([x.employee_id for x in lv_svc.overdue()],
                         [self.emp.id])
        r = self.client.get("/api/v1/leaves/overdue")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data[0]["overdue"])
        # Closed, and it drops off the list.
        self.client.post(f"/api/v1/leaves/{r.data[0]['id']}/return", {},
                         format="json")   # no date given -> today
        self.assertEqual(list(lv_svc.overdue()), [])


class RegisterTests(LeaveBase):
    def test_register_lists_and_filters_open(self):
        self._grant("PAID", date(2026, 5, 4), date(2026, 5, 10))
        lv = WorkerLeave.objects.get()
        lv_svc.mark_returned(lv, self.hr, date(2026, 5, 11))
        self._grant("UNPAID", date(2026, 6, 1), date(2026, 6, 5))
        self.assertEqual(len(self.client.get("/api/v1/leaves").data), 2)
        open_rows = self.client.get("/api/v1/leaves?open=1").data
        self.assertEqual(len(open_rows), 1)
        self.assertEqual(open_rows[0]["kind"], "UNPAID")
        self.assertEqual(open_rows[0]["days"], 5)
