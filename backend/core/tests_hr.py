from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (
    Attendance,
    AuditLog,
    CompanyParameter,
    Employee,
    EmployeeSiteAllocation,
    ManpowerCategory,
    Site,
    SitePmHistory,
    User,
)
from .tests import make_user


def working_day(site, offset=0):
    """A recent working day (not in the future)."""
    d = date.today()
    skipped = 0
    while True:
        if d.isoweekday() in site.working_days:
            if skipped == offset:
                return d
            skipped += 1
        d -= timedelta(days=1)


class HrBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE)
        self.sa = make_user("sa1", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.hr = make_user("hr1", User.Role.HO_HR)
        self.mason_cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=10)
        CompanyParameter.objects.create(key="ot_multiplier", value=1.25)
        CompanyParameter.objects.create(key="hourly_rate_divisor", value=240)
        self.client = APIClient()
        self.as_user(self.hr)
        self.mason = self.make_employee("Kumar Perera", basic_pay=9600)

    def as_user(self, user):
        self.client.force_authenticate(user)

    def make_employee(self, name, basic_pay=None):
        r = self.client.post("/api/v1/employees", {
            "full_name": name, "passport_no": "N1234567",
            "nationality": "Sri Lankan", "job_category": self.mason_cat.id,
            "basic_pay": basic_pay, "join_date": "2025-01-01",
        }, format="json")
        assert r.status_code == 201, r.data
        employee = Employee.objects.get(pk=r.data["id"])
        self.client.post(f"/api/v1/employees/{employee.id}/allocate",
                         {"site_id": self.site.id}, format="json")
        return employee

    def save_attendance(self, day, ot=0, remark="PRESENT", user=None,
                        check_out="18:00"):
        self.as_user(user or self.sa)
        return self.client.put("/api/v1/attendance/bulk", {
            "site": self.site.id, "date": day.isoformat(),
            "rows": [{"employee_id": self.mason.id, "check_in": "07:00",
                      "check_out": check_out, "ot_requested": ot,
                      "remark": remark}],
        }, format="json")


class EmployeeSensitivityTests(HrBase):
    def test_emp_no_server_issued(self):
        self.assertTrue(self.mason.emp_no.startswith("EMP-"))
        self.assertEqual(len(self.mason.emp_no), 8)  # EMP-0001

    def test_site_user_sees_roster_without_pay_or_passport(self):
        self.as_user(self.sa)
        r = self.client.get("/api/v1/employees")
        self.assertEqual(len(r.data), 1)
        row = r.data[0]
        self.assertEqual(row["full_name"], "Kumar Perera")
        self.assertNotIn("basic_pay", row)
        self.assertNotIn("passport_no", row)
        self.assertNotIn("work_permit_no", row)

    def test_hr_sees_everything(self):
        self.as_user(self.hr)
        r = self.client.get(f"/api/v1/employees/{self.mason.id}")
        self.assertEqual(str(r.data["basic_pay"]), "9600.00")
        self.assertEqual(r.data["passport_no"], "N1234567")

    def test_site_user_cannot_edit_employees(self):
        self.as_user(self.sa)
        r = self.client.post("/api/v1/employees", {"full_name": "X"},
                             format="json")
        self.assertEqual(r.status_code, 403)

    def test_other_site_roster_hidden(self):
        other = Site.objects.create(code="VKR", name="Vakkaru",
                                    status="ACTIVE")
        outsider = make_user("sa2", User.Role.SITE_ADMIN, site=other)
        self.as_user(outsider)
        r = self.client.get("/api/v1/employees")
        self.assertEqual(len(r.data), 0)

    def test_sensitive_fields_never_in_audit_detail(self):
        self.as_user(self.hr)
        self.client.patch(f"/api/v1/employees/{self.mason.id}",
                          {"basic_pay": 10000, "nationality": "Indian"},
                          format="json")
        log = AuditLog.objects.filter(entity="employee",
                                      event="EMPLOYEE_UPDATED").first()
        self.assertNotIn("basic_pay", log.detail["fields"])
        self.assertIn("nationality", log.detail["fields"])


class AttendanceTests(HrBase):
    def test_grid_prefills_site_hours(self):
        self.as_user(self.sa)
        day = working_day(self.site)
        r = self.client.get(f"/api/v1/attendance?site={self.site.id}"
                            f"&date={day.isoformat()}")
        row = r.data["rows"][0]
        self.assertEqual(str(row["check_in"]), "07:00:00")
        self.assertFalse(row["saved"])

    def test_bulk_save_computes_normal_hours(self):
        day = working_day(self.site)
        r = self.save_attendance(day, ot=2)
        self.assertEqual(r.status_code, 200, r.data)
        att = Attendance.objects.get(employee=self.mason, day=day)
        self.assertEqual(att.normal_hours, Decimal("11.00"))  # 07:00-18:00
        self.assertEqual(att.ot_requested, Decimal("2"))
        self.assertIsNone(att.ot_approved)

    def test_half_day_and_absent_hours(self):
        d1, d2 = working_day(self.site, 0), working_day(self.site, 1)
        self.save_attendance(d1, remark="HALF_DAY")
        self.save_attendance(d2, remark="ABSENT")
        self.assertEqual(Attendance.objects.get(day=d1).normal_hours,
                         Decimal("5.50"))
        self.assertEqual(Attendance.objects.get(day=d2).normal_hours,
                         Decimal("0"))

    def test_future_day_rejected(self):
        r = self.save_attendance(date.today() + timedelta(days=2))
        self.assertEqual(r.status_code, 400)

    def test_late_edit_flagged_in_audit(self):
        past = working_day(self.site, 3)
        self.save_attendance(past)
        log = AuditLog.objects.filter(event="ATTENDANCE_SAVED").first()
        self.assertTrue(log.detail["late_edit"])


class OtAndLockTests(HrBase):
    def test_ot_approval_pm_only(self):
        day = working_day(self.site)
        self.save_attendance(day, ot=3)
        att = Attendance.objects.get(employee=self.mason, day=day)
        r = self.client.post("/api/v1/attendance/ot-approve",
                             {"ids": [att.id]}, format="json")  # site admin
        self.assertEqual(r.status_code, 403)
        self.as_user(self.pm)
        r = self.client.post("/api/v1/attendance/ot-approve",
                             {"ids": [att.id]}, format="json")
        self.assertEqual(r.status_code, 200)
        att.refresh_from_db()
        self.assertEqual(att.ot_approved, Decimal("3"))
        self.assertEqual(att.ot_approved_by, self.pm)

    def test_lock_blocks_edits_until_hr_reopens(self):
        day = working_day(self.site)
        self.save_attendance(day)
        # PM signs off the month
        self.as_user(self.pm)
        r = self.client.post(f"/api/v1/timesheets/{self.site.id}/"
                             f"{day.year}/{day.month}/lock")
        self.assertEqual(r.status_code, 200)
        # edits now blocked
        r = self.save_attendance(day, ot=1)
        self.assertEqual(r.status_code, 400)
        self.assertIn("locked", r.data["detail"].lower())
        # site admin cannot reopen
        r = self.client.post(f"/api/v1/timesheets/{self.site.id}/"
                             f"{day.year}/{day.month}/reopen",
                             {"reason": "x"}, format="json")
        self.assertEqual(r.status_code, 403)
        # HR reopen requires a reason and is audited
        self.as_user(self.hr)
        r = self.client.post(f"/api/v1/timesheets/{self.site.id}/"
                             f"{day.year}/{day.month}/reopen", {},
                             format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"/api/v1/timesheets/{self.site.id}/"
                             f"{day.year}/{day.month}/reopen",
                             {"reason": "Missed OT correction"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(AuditLog.objects.filter(
            event="TIMESHEET_REOPENED").exists())
        r = self.save_attendance(day, ot=1)
        self.assertEqual(r.status_code, 200)

    def test_lock_is_pm_gated(self):
        day = working_day(self.site)
        r = self.client.post(f"/api/v1/timesheets/{self.site.id}/"
                             f"{day.year}/{day.month}/lock")  # site admin
        self.assertEqual(r.status_code, 403)


class PayrollExportTests(HrBase):
    def test_only_approved_ot_reaches_export_and_gross_math(self):
        d1, d2 = working_day(self.site, 0), working_day(self.site, 1)
        self.save_attendance(d1, ot=4)
        self.save_attendance(d2, ot=2)
        # approve only day 1's OT
        att1 = Attendance.objects.get(day=d1)
        self.as_user(self.pm)
        self.client.post("/api/v1/attendance/ot-approve", {"ids": [att1.id]},
                         format="json")
        self.as_user(self.hr)
        r = self.client.get(f"/api/v1/payroll-export/{d1.year}/{d1.month}")
        row = r.data["rows"][0]
        self.assertEqual(float(row["ot_hours_approved"]), 4.0)  # not 6
        # gross = 9600 + 4 x (9600/240) x 1.25 = 9600 + 200 = 9800
        self.assertEqual(float(row["hourly_rate"]), 40.0)
        self.assertEqual(float(row["ot_amount"]), 200.0)
        self.assertEqual(float(row["gross"]), 9800.0)

    def test_export_hr_finance_only(self):
        self.as_user(self.sa)
        r = self.client.get("/api/v1/payroll-export/2026/7")
        self.assertEqual(r.status_code, 403)
        self.as_user(self.pm)
        r = self.client.get("/api/v1/payroll-export/2026/7")
        self.assertEqual(r.status_code, 403)
        finance = make_user("fin1", User.Role.FINANCE)
        self.as_user(finance)
        r = self.client.get("/api/v1/payroll-export/2026/7")
        self.assertEqual(r.status_code, 200)  # R3 addendum

    def test_finance_sees_pay_but_not_passport(self):
        finance = make_user("fin2", User.Role.FINANCE)
        self.as_user(finance)
        r = self.client.get(f"/api/v1/employees/{self.mason.id}")
        self.assertEqual(str(r.data["basic_pay"]), "9600.00")
        self.assertNotIn("passport_no", r.data)

    def test_xlsx_download(self):
        day = working_day(self.site)
        self.save_attendance(day)
        self.as_user(self.hr)
        r = self.client.get(f"/api/v1/payroll-export/{day.year}/{day.month}"
                            f"?export=xlsx")
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r["Content-Type"])
        self.assertIn("attachment", r["Content-Disposition"])
