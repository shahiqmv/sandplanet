"""The client's attendance record: a date range, headcount and marks, and
nothing about pay (owner 2026-09-03 — the resort plans housekeeping and
food from it)."""
from datetime import date, timedelta

from . import attendance_report
from .models import Attendance, ManpowerCategory, Site, User
from .tests import make_user
from .tests_hr import HrBase, working_day


class AttendanceReportTests(HrBase):
    def _mark(self, day, remark="PRESENT", ot=0, emp=None):
        Attendance.objects.create(employee=emp or self.mason, site=self.site,
                                  day=day, remark=remark,
                                  ot_requested=ot, ot_approved=ot or None,
                                  entered_by=self.sa)

    def test_marks_and_counts_follow_the_register(self):
        d = working_day(self.site, 1)
        self._mark(d, "PRESENT", ot=3)
        self._mark(d + timedelta(days=1), "HALF_DAY")
        self._mark(d + timedelta(days=2), "ABSENT")
        self._mark(d + timedelta(days=3), "SICK")
        self._mark(d + timedelta(days=4), "LEAVE")
        ctx = attendance_report.build(self.site, d, d + timedelta(days=4))
        marks = [c for b in ctx["blocks"] for r in b["rows"]
                 if r["emp_no"] == self.mason.emp_no for c in (x["c"] for x in r["cells"]) if c]
        self.assertEqual(sorted(marks), sorted(["P", "½", "A", "S", "L"]))
        w = ctx["workers"][0]
        self.assertEqual((w["half"], w["absent"], w["sick"], w["leave"]),
                         (1, 1, 1, 1))
        self.assertEqual(w["on_site"], w["present"] + w["rest_worked"] + 1)

    def test_overtime_is_nowhere_in_the_record(self):
        d = working_day(self.site, 1)
        self._mark(d, "PRESENT", ot=6)
        ctx = attendance_report.build(self.site, d, d)
        text = str({k: v for k, v in ctx.items() if k != "site"})
        for banned in ("ot_", "overtime", "rate", "basic"):
            self.assertNotIn(banned, text.lower())

    def test_headcount_by_day_counts_half_days_as_on_site(self):
        second = self.make_employee("Nuwan Perera", basic_pay=9000,
                                    passport_no="N7654321")
        d = working_day(self.site, 1)
        self._mark(d, "PRESENT")
        self._mark(d, "HALF_DAY", emp=second)
        self._mark(d + timedelta(days=1), "ABSENT")
        ctx = attendance_report.build(self.site, d, d + timedelta(days=1))
        b = ctx["blocks"][0] if len(ctx["blocks"]) == 1 else \
            next(x for x in ctx["blocks"] if any(dd["date"] == d for dd in x["days"]))
        i = next(n for n, dd in enumerate(b["days"]) if dd["date"] == d)
        self.assertEqual(b["headcount"][i], 2)      # both on site that day
        self.assertEqual(b["peak"], 2)

    def test_a_range_across_two_months_gives_one_grid_per_month(self):
        last = date(2026, 8, 31)
        self._mark(last, "PRESENT")
        self._mark(date(2026, 9, 1), "PRESENT")
        ctx = attendance_report.build(self.site, date(2026, 8, 25),
                                      date(2026, 9, 3))
        self.assertEqual([b["label"] for b in ctx["blocks"]],
                         ["August 2026", "September 2026"])
        self.assertEqual(len(ctx["blocks"][0]["days"]), 7)
        self.assertEqual(len(ctx["blocks"][1]["days"]), 3)
        self.assertEqual(ctx["totals"]["on_site"], 2)

    def test_job_title_and_staff_or_worker_come_from_the_record(self):
        staff_cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="STAFF", name="Engineer", sort_order=1)
        eng = self.make_employee("Dilshan Silva", basic_pay=25000,
                                 passport_no="N1112223")
        eng.job_category = staff_cat
        eng.job_title = "Site Engineer"
        eng.save()
        d = working_day(self.site, 1)
        self._mark(d, "PRESENT")
        self._mark(d, "PRESENT", emp=eng)
        ctx = attendance_report.build(self.site, d, d)
        by = {w["emp_no"]: w for w in ctx["workers"]}
        self.assertEqual((by[eng.emp_no]["job_title"], by[eng.emp_no]["kind"]),
                         ("Site Engineer", "Staff"))
        self.assertEqual((by[self.mason.emp_no]["job_title"],
                          by[self.mason.emp_no]["kind"]), ("Mason", "Worker"))
        self.assertEqual((ctx["staff_count"], ctx["worker_count"]), (1, 1))

    def test_hr_can_type_the_job_title(self):
        self.as_user(self.hr)
        r = self.client.patch(f"/api/v1/employees/{self.mason.id}",
                              {"job_title": "Stone Mason"}, format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.mason.refresh_from_db()
        self.assertEqual(self.mason.job_title, "Stone Mason")

    def test_the_range_is_bounded(self):
        with self.assertRaises(ValueError):
            attendance_report.build(self.site, date(2026, 9, 3),
                                    date(2026, 9, 1))
        with self.assertRaises(ValueError):
            attendance_report.build(self.site, date(2026, 1, 1),
                                    date(2026, 6, 1))

    def test_the_pdf_is_served_to_the_site_team_and_scoped(self):
        d = working_day(self.site, 1)
        self._mark(d, "PRESENT")
        self.as_user(self.sa)
        r = self.client.get(f"/api/v1/sites/{self.site.id}/attendance.pdf"
                            f"?from={d}&to={d}")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn(f"{self.site.code}-attendance-{d}-to-{d}.pdf",
                      r["Content-Disposition"])
        r = self.client.get(f"/api/v1/sites/{self.site.id}/attendance.pdf"
                            f"?from={d}&to=bad")
        self.assertEqual(r.status_code, 400)
        other = Site.objects.create(code="OTH", name="Other",
                                    status=Site.Status.ACTIVE)
        stranger = make_user("oth_sa", User.Role.SITE_ADMIN, site=other)
        self.as_user(stranger)
        r = self.client.get(f"/api/v1/sites/{self.site.id}/attendance.pdf"
                            f"?from={d}&to={d}")
        self.assertEqual(r.status_code, 404)
