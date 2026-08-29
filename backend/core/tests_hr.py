from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (
    Attendance,
    AuditLog,
    CompanyParameter,
    EmployeeSiteAllocation,
    Employee,
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

    def test_set_all_contract_command(self):
        from django.core.management import call_command
        # dry run changes nothing
        call_command("set_all_contract")
        self.mason.refresh_from_db()
        self.assertEqual(self.mason.employment_type, "PERMANENT")
        # --apply flips direct employees to CONTRACT
        call_command("set_all_contract", "--apply")
        self.mason.refresh_from_db()
        self.assertEqual(self.mason.employment_type, "CONTRACT")

    def test_usd_basic_is_permanent_only_and_zeroes_mvr_basic(self):
        self.as_user(self.hr)
        # setting a USD basic zeroes the MVR basic
        r = self.client.patch(f"/api/v1/employees/{self.mason.id}",
                              {"usd_basic_pay": "900"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.mason.refresh_from_db()
        self.assertEqual(float(self.mason.usd_basic_pay), 900.0)
        self.assertEqual(float(self.mason.basic_pay), 0.0)
        # a contract worker can't be given a USD basic
        r = self.client.patch(f"/api/v1/employees/{self.mason.id}",
                              {"employment_type": "CONTRACT",
                               "usd_basic_pay": "900"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("permanent", str(r.data).lower())

    def test_employee_export_xlsx_and_gating(self):
        self.as_user(self.hr)
        r = self.client.get("/api/v1/employees/export")
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r["Content-Type"])
        self.assertEqual(r.content[:2], b"PK")            # xlsx is a zip
        # a filter matching no one still returns a valid workbook
        self.assertEqual(self.client.get(
            "/api/v1/employees/export?employment=CONTRACT").status_code, 200)
        # the HR master export includes the sensitive identity columns
        import io

        import openpyxl
        self.as_user(self.hr)
        r = self.client.get("/api/v1/employees/export?full=1")
        self.assertEqual(r.status_code, 200)
        ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
        header = [c.value for c in ws[1]]
        self.assertIn("Passport No", header)
        self.assertIn("Date of Birth", header)
        # a non-pay role can't export the register at all
        self.as_user(self.pm)
        self.assertEqual(self.client.get(
            "/api/v1/employees/export").status_code, 403)


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

    def test_site_pm_can_reopen_own_month(self):
        """A site PM may unlock a month it locked by mistake (owner
        2026-07-14)."""
        day = working_day(self.site)
        self.save_attendance(day)
        self.as_user(self.pm)
        self.client.post(f"/api/v1/timesheets/{self.site.id}/"
                         f"{day.year}/{day.month}/lock")
        r = self.client.post(f"/api/v1/timesheets/{self.site.id}/"
                             f"{day.year}/{day.month}/reopen",
                             {"reason": "locked by mistake"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "OPEN")
        # edits work again
        self.assertEqual(self.save_attendance(day, ot=1).status_code, 200)

    def test_lock_is_pm_gated(self):
        day = working_day(self.site)
        self.as_user(self.sa)  # a site admin cannot sign off the month
        r = self.client.post(f"/api/v1/timesheets/{self.site.id}/"
                             f"{day.year}/{day.month}/lock")
        self.assertEqual(r.status_code, 403)

    def test_hr_can_lock_month(self):
        day = working_day(self.site)
        self.as_user(self.hr)  # HR signs off (Head Office / corrections)
        r = self.client.post(f"/api/v1/timesheets/{self.site.id}/"
                             f"{day.year}/{day.month}/lock")
        self.assertEqual(r.status_code, 200, r.data)


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


class HeadOfficeEmployeeTests(HrBase):
    def test_create_employee_posted_to_head_office(self):
        from .vouchers import ho_site
        ho = ho_site()
        r = self.client.post("/api/v1/employees", {
            "full_name": "Office Staff", "nationality": "Maldivian",
            "job_category": self.mason_cat.id, "site_id": ho.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        emp = Employee.objects.get(pk=r.data["id"])
        alloc = emp.site_allocations.get(to_date__isnull=True)
        self.assertEqual(alloc.site_id, ho.id)
        # HR can record attendance for the Head Office site
        r = self.client.get(
            f"/api/v1/attendance?site={ho.id}&date={date.today().isoformat()}")
        self.assertEqual(r.status_code, 200, r.data)

    def test_create_without_site_leaves_unallocated(self):
        r = self.client.post("/api/v1/employees", {
            "full_name": "Nobody", "nationality": "Maldivian",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        emp = Employee.objects.get(pk=r.data["id"])
        self.assertFalse(emp.site_allocations.filter(to_date__isnull=True)
                         .exists())


class DuplicatePassportTests(HrBase):
    """One passport, one record (owner 2026-08-15).

    Rakib Hossain sat on BVR's July run twice — as EMP-0020 with his 23 worked
    days, and again as a second record created for him in August with none of
    his history. The site reported the July attendance as lost; it had never
    moved.
    """

    def _payload(self, **kw):
        data = {"full_name": "Test Worker", "passport_no": "EK0658559",
                "nationality": "Bangladeshi", "basic_pay": "7000",
                "currency": "MVR", "employment_type": "CONTRACT"}
        data.update(kw)
        return data

    def test_a_second_record_for_the_same_passport_is_refused(self):
        self.as_user(self.hr)
        r = self.client.post("/api/v1/employees", self._payload(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        first = r.data["emp_no"]
        r2 = self.client.post("/api/v1/employees",
                              self._payload(full_name="Test Worker Again"),
                              format="json")
        self.assertEqual(r2.status_code, 400)
        self.assertIn(first, str(r2.data))

    def test_hr_may_override_when_the_other_record_holds_the_typo(self):
        self.as_user(self.hr)
        self.client.post("/api/v1/employees", self._payload(), format="json")
        r = self.client.post(
            "/api/v1/employees",
            self._payload(full_name="Genuinely Someone Else",
                          allow_duplicate_passport=True), format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_a_blank_passport_is_not_a_clash(self):
        self.as_user(self.hr)
        for name in ("No Passport One", "No Passport Two"):
            r = self.client.post("/api/v1/employees",
                                 self._payload(full_name=name, passport_no=""),
                                 format="json")
            self.assertEqual(r.status_code, 201, r.data)

    def test_editing_a_record_does_not_clash_with_itself(self):
        self.as_user(self.hr)
        r = self.client.post("/api/v1/employees", self._payload(), format="json")
        eid = r.data["id"]
        r2 = self.client.patch(f"/api/v1/employees/{eid}",
                               {"full_name": "Renamed"}, format="json")
        self.assertEqual(r2.status_code, 200, r2.data)


class MergeEmployeesTests(TestCase):
    """Merging a duplicate record and re-siting the days (owner 2026-08-15).

    Rakib Hosen moved from BVR to Malé and HR opened a second record instead
    of transferring him, so his July attendance sat on one record, his August
    days on another, and he reached a payroll run twice.
    """

    def setUp(self):
        from datetime import date
        from decimal import Decimal

        from .models import (Attendance, Employee, EmployeeSiteAllocation,
                             ManpowerCategory, Site, User)
        from . import merge_employees
        self.m = merge_employees
        self.date = date
        self.Att = Attendance
        self.Alloc = EmployeeSiteAllocation
        self.admin = make_user("mg_admin", User.Role.ADMIN)
        self.bvr = Site.objects.create(code="MBV", name="Bvr",
                                       status=Site.Status.ACTIVE,
                                       working_days=[1, 2, 3, 4, 6, 7])
        self.mle = Site.objects.create(code="MML", name="Male",
                                       status=Site.Status.ACTIVE,
                                       working_days=[1, 2, 3, 4, 6, 7])
        cat = ManpowerCategory.objects.create(list_type="DPR", grp="LABOUR",
                                              name="Mason", sort_order=10)
        self.keep = Employee.objects.create(
            emp_no="MG-0001", full_name="Rakib", job_category=cat,
            basic_pay=Decimal("7000"), currency="MVR", is_active=False,
            passport_no="EK1", join_date=date(2026, 1, 10))
        # deliberately the same passport — this is the mess being merged
        self.dup = Employee(
            emp_no="MG-0002", full_name="RAKIB", job_category=cat,
            currency="MVR", is_active=True, passport_no="EK1")
        self.dup._allow_duplicate_passport = True
        self.dup.save()
        self.Alloc.objects.create(employee=self.keep, site=self.bvr,
                                  from_date=date(2026, 7, 1),
                                  to_date=date(2026, 7, 24))
        self.Alloc.objects.create(employee=self.dup, site=self.bvr,
                                  from_date=date(2026, 8, 12))
        for d in (1, 2, 3):
            self.Att.objects.create(employee=self.keep, site=self.bvr,
                                    day=date(2026, 7, d), remark="PRESENT")
        for d in (12, 13, 14):
            self.Att.objects.create(employee=self.dup, site=self.bvr,
                                    day=date(2026, 8, d), remark="PRESENT")

    def test_plan_says_what_would_move_without_writing(self):
        p = self.m.plan(self.keep, self.dup)
        self.assertEqual(p["moves"]["Attendance"], 3)
        self.assertEqual(p["same_day_attendance"], [])
        self.assertEqual(p["blocked"], [])
        self.assertEqual(self.Att.objects.filter(employee=self.dup).count(), 3)

    def test_merge_brings_the_history_together(self):
        res, err = self.m.merge(self.keep, self.dup, self.admin)
        self.assertIsNone(err)
        self.keep.refresh_from_db(); self.dup.refresh_from_db()
        self.assertEqual(self.Att.objects.filter(employee=self.keep).count(), 6)
        self.assertEqual(self.Att.objects.filter(employee=self.dup).count(), 0)
        self.assertTrue(self.keep.is_active)
        self.assertFalse(self.dup.is_active)
        self.assertEqual(self.dup.passport_no, "")
        self.assertIn("merged into MG-0001", self.dup.full_name)

    def test_a_day_on_both_records_keeps_the_keepers_row(self):
        self.Att.objects.create(employee=self.dup, site=self.bvr,
                                day=self.date(2026, 7, 1), remark="ABSENT")
        p = self.m.plan(self.keep, self.dup)
        self.assertEqual(p["same_day_attendance"], ["2026-07-01"])
        res, err = self.m.merge(self.keep, self.dup, self.admin)
        self.assertIsNone(err)
        row = self.Att.objects.get(employee=self.keep, day=self.date(2026, 7, 1))
        self.assertEqual(row.remark, "PRESENT")      # the keeper's stands
        self.assertEqual(res["dropped_attendance"], 1)

    def test_transfer_moves_the_days_to_the_new_site(self):
        self.m.merge(self.keep, self.dup, self.admin)
        res = self.m.transfer_from(self.keep, self.mle,
                                   self.date(2026, 8, 12), self.admin)
        self.assertEqual(res["rows_moved"], 3)
        self.assertEqual(self.Att.objects.filter(
            employee=self.keep, site=self.mle).count(), 3)
        self.assertEqual(self.Att.objects.filter(
            employee=self.keep, site=self.bvr).count(), 3)   # July untouched
        self.assertTrue(self.Alloc.objects.filter(
            employee=self.keep, site=self.mle,
            from_date=self.date(2026, 8, 12)).exists())

    def test_merging_a_record_into_itself_is_refused(self):
        _, err = self.m.merge(self.keep, self.keep, self.admin)
        self.assertIn("same record", err.lower())


class TransferAllocationTidyTests(TestCase):
    """A transfer must not leave an allocation closed before it opens.

    The first live merge produced BVR 12 Aug -> 31 Jul, because the duplicate
    record's allocation had not started when the man moved (owner 2026-08-15).
    """

    def setUp(self):
        from datetime import date
        from decimal import Decimal

        from .models import (Employee, EmployeeSiteAllocation,
                             ManpowerCategory, Site, User)
        from . import merge_employees
        self.m = merge_employees
        self.date = date
        self.Alloc = EmployeeSiteAllocation
        self.admin = make_user("tt_admin", User.Role.ADMIN)
        self.old = Site.objects.create(code="TT1", name="Old",
                                       status=Site.Status.ACTIVE)
        self.new = Site.objects.create(code="TT2", name="New",
                                       status=Site.Status.ACTIVE)
        cat = ManpowerCategory.objects.create(list_type="DPR", grp="LABOUR",
                                              name="Mason", sort_order=10)
        self.emp = Employee.objects.create(
            emp_no="TT-0001", full_name="Mover", job_category=cat,
            basic_pay=Decimal("7000"), currency="MVR")

    def test_an_allocation_that_had_not_started_is_dropped_not_closed(self):
        self.Alloc.objects.create(employee=self.emp, site=self.old,
                                  from_date=self.date(2026, 8, 12))
        res = self.m.transfer_from(self.emp, self.new,
                                   self.date(2026, 8, 1), self.admin)
        self.assertEqual(res["voided_allocations"], ["TT1"])
        self.assertFalse(self.Alloc.objects.filter(
            employee=self.emp, site=self.old).exists())

    def test_a_running_allocation_is_closed_the_day_before(self):
        self.Alloc.objects.create(employee=self.emp, site=self.old,
                                  from_date=self.date(2026, 7, 1))
        res = self.m.transfer_from(self.emp, self.new,
                                   self.date(2026, 8, 1), self.admin)
        self.assertEqual(res["closed_allocations"], ["TT1"])
        a = self.Alloc.objects.get(employee=self.emp, site=self.old)
        self.assertEqual(a.to_date, self.date(2026, 7, 31))

    def test_no_allocation_ends_before_it_begins(self):
        self.Alloc.objects.create(employee=self.emp, site=self.old,
                                  from_date=self.date(2026, 7, 1))
        self.Alloc.objects.create(employee=self.emp, site=self.old,
                                  from_date=self.date(2026, 8, 12))
        self.m.transfer_from(self.emp, self.new, self.date(2026, 8, 1),
                             self.admin)
        for a in self.Alloc.objects.filter(employee=self.emp):
            if a.to_date:
                self.assertGreaterEqual(a.to_date, a.from_date,
                                        f"{a.site.code} ends before it begins")


class OnePassportOneRecordTests(TestCase):
    """A passport already on file is refused, whichever door it comes through.

    Four paths create employees — the HR screen, a site's own hire batch,
    subcontractor workers, and the onboarding handover — and only the HR
    screen was ever checking (owner 2026-08-16). A duplicate is invisible
    afterwards: it reads as a new man with no history, which is how one worker
    reached a payroll run twice.
    """

    def setUp(self):
        from decimal import Decimal
        from .models import (Employee, ManpowerCategory, Site, User)
        self.User = User
        self.Employee = Employee
        self.admin = make_user("pp_admin", User.Role.ADMIN)
        self.sa = make_user("pp_sa", User.Role.SITE_ADMIN)
        self.site = Site.objects.create(code="PPT", name="Passport Isle",
                                        status=Site.Status.ACTIVE)
        self.cat = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=1)
        self.existing = Employee.objects.create(
            emp_no="PP-0001", full_name="Already Here",
            passport_no="AB123456", job_category=self.cat,
            basic_pay=Decimal("7000"), currency="MVR")

    def test_the_model_itself_refuses_a_passport_on_file(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError) as cm:
            self.Employee.objects.create(
                emp_no="PP-0002", full_name="Someone Else",
                passport_no="AB123456")
        self.assertIn("PP-0001", str(cm.exception))

    def test_case_and_spacing_do_not_slip_past_it(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.Employee.objects.create(emp_no="PP-0003", full_name="X",
                                         passport_no="  ab123456 ")

    def test_an_existing_duplicate_can_still_be_edited(self):
        """The ones already on file must stay fixable — the guard fires on a
        change to the number, not on every save."""
        twin = self.Employee(emp_no="PP-0004", full_name="Twin",
                             passport_no="AB123456")
        twin._allow_duplicate_passport = True
        twin.save()
        twin.full_name = "Twin Renamed"
        twin.save()                      # no passport change → allowed
        twin.refresh_from_db()
        self.assertEqual(twin.full_name, "Twin Renamed")

    def test_a_site_hire_batch_names_the_record_that_holds_it(self):
        from . import worker_mgmt
        batch, err = worker_mgmt.create_add_batch(self.site, [{
            "full_name": "New Hire", "passport_no": "AB123456",
            "nationality": "Bangladeshi", "job_category_id": self.cat.id,
            "basic_pay": "7000"}], self.sa)
        self.assertIsNone(batch)
        self.assertIn("PP-0001", err)
        self.assertIn("Already Here", err)

    def test_a_site_hire_with_a_fresh_passport_still_works(self):
        from . import worker_mgmt
        batch, err = worker_mgmt.create_add_batch(self.site, [{
            "full_name": "Genuinely New", "passport_no": "ZZ999999",
            "nationality": "Bangladeshi", "job_category_id": self.cat.id,
            "basic_pay": "7000"}], self.sa)
        self.assertIsNone(err, err)
        self.assertIsNotNone(batch)

    def test_a_blank_passport_never_clashes(self):
        a = self.Employee.objects.create(emp_no="PP-0010", full_name="No Doc A")
        b = self.Employee.objects.create(emp_no="PP-0011", full_name="No Doc B")
        self.assertNotEqual(a.pk, b.pk)

    def test_the_onboarding_handover_links_instead_of_duplicating(self):
        """A returning man keeps the record that holds his history."""
        from datetime import date
        from . import onboarding
        from .models import Document, OnboardingCase
        doc = Document.objects.create(
            doc_type="OBR", ref="OBR-PPT-001", site=self.site,
            doc_date=date(2026, 8, 1), status="IN_PROGRESS",
            created_by=self.admin)
        case = OnboardingCase.objects.create(
            document=doc, full_name="Already Here", passport_no="AB123456",
            nationality="Bangladeshi")
        emp = onboarding._handover_employee(case, self.admin)
        self.assertEqual(emp.pk, self.existing.pk)
        case.refresh_from_db()
        self.assertEqual(case.employee_id, self.existing.pk)
        self.assertEqual(self.Employee.objects.filter(
            passport_no__iexact="AB123456").count(), 1)


class WorkerPhotoTests(TestCase):
    """Site team adds/replaces worker photos (owner 2026-08-26 — photo
    identity for big crews, adopted from the SFR spreadsheet)."""

    def setUp(self):
        from .tests import make_user
        self.site = Site.objects.create(code="WPH", name="Photo Site",
                                        status=Site.Status.ACTIVE)
        self.other = Site.objects.create(code="WPO", name="Other",
                                         status=Site.Status.ACTIVE)
        self.sa = make_user("wph_sa", User.Role.SITE_ADMIN, site=self.site)
        self.emp = Employee.objects.create(
            emp_no="EMP-0900", full_name="Photo Man", is_active=True,
            join_date=date(2026, 1, 1))
        EmployeeSiteAllocation.objects.create(
            employee=self.emp, site=self.site, from_date=date(2026, 1, 1))
        self.stranger = Employee.objects.create(
            emp_no="EMP-0901", full_name="Elsewhere Man", is_active=True,
            join_date=date(2026, 1, 1))
        EmployeeSiteAllocation.objects.create(
            employee=self.stranger, site=self.other, from_date=date(2026, 1, 1))
        from rest_framework.test import APIClient
        self.client = APIClient()
        self.client.force_authenticate(self.sa)

    def _file(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile("face.jpg", b"\xff\xd8\xff\xdbjpegish",
                                  content_type="image/jpeg")

    def test_site_admin_sets_a_photo_for_his_own_worker(self):
        r = self.client.post(f"/api/v1/workers/{self.emp.id}/photo",
                             {"photo": self._file()}, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.photo)
        self.assertIn("EMP-0900", self.emp.photo.name)

    def test_not_for_another_sites_worker(self):
        r = self.client.post(f"/api/v1/workers/{self.stranger.id}/photo",
                             {"photo": self._file()}, format="multipart")
        self.assertEqual(r.status_code, 403)

    def test_grid_and_roster_carry_the_photo_url(self):
        self.client.post(f"/api/v1/workers/{self.emp.id}/photo",
                         {"photo": self._file()}, format="multipart")
        row = next(x for x in self.client.get(
            f"/api/v1/attendance?site={self.site.id}&date={date.today()}")
            .data["rows"] if x["employee_id"] == self.emp.id)
        self.assertTrue(row["photo_url"])
        w = next(x for x in self.client.get(
            f"/api/v1/sites/{self.site.id}/direct-workers").data
            if x["id"] == self.emp.id)
        self.assertTrue(w["photo_url"])


class Wave1ControlsTests(TestCase):
    """Audit remediations (2026-08-28): attendance changes are recorded per
    employee including deletions, and repeated failed sign-ins are throttled."""

    def setUp(self):
        from .tests import make_user
        self.site = Site.objects.create(code="W1", name="Wave One",
                                        status=Site.Status.ACTIVE)
        self.hr = make_user("w1_hr", User.Role.HO_HR)
        self.emp = Employee.objects.create(
            emp_no="EMP-0950", full_name="Audit Man", is_active=True,
            join_date=date(2026, 1, 1))
        EmployeeSiteAllocation.objects.create(
            employee=self.emp, site=self.site, from_date=date(2026, 1, 1))
        from rest_framework.test import APIClient
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def _save(self, rows):
        return self.client.put("/api/v1/attendance/bulk", {
            "site": self.site.id, "date": date.today().isoformat(),
            "rows": rows}, format="json")

    def _last_detail(self):
        return AuditLog.objects.filter(
            event="ATTENDANCE_SAVED").order_by("-id").first().detail

    def test_edits_and_deletions_name_the_employee(self):
        self._save([{"employee_id": self.emp.id, "check_in": "08:00",
                     "check_out": "17:00", "remark": "PRESENT",
                     "ot_requested": 0}])
        d = self._last_detail()
        self.assertEqual(d["changes"][0]["emp"], "EMP-0950")
        self.assertEqual(d["changes"][0]["action"], "CREATED")

        # an edit records both sides
        self._save([{"employee_id": self.emp.id, "check_in": "08:00",
                     "check_out": "20:00", "remark": "PRESENT",
                     "ot_requested": "3"}])
        d = self._last_detail()
        ch = d["changes"][0]
        self.assertEqual(ch["action"], "EDITED")
        self.assertEqual(ch["was"]["out"], "17:00:00")
        self.assertEqual(str(ch["now"]["ot"]), "3")

        # marking OFF deletes the day — and that is no longer silent
        self._save([{"employee_id": self.emp.id, "remark": "OFF"}])
        d = self._last_detail()
        ch = d["changes"][0]
        self.assertEqual(ch["action"], "DELETED")
        self.assertEqual(ch["emp"], "EMP-0950")
        self.assertEqual(ch["was"]["remark"], "PRESENT")

    def test_repeated_failed_sign_ins_are_throttled(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        for _ in range(10):
            r = anon.post("/api/v1/auth/login",
                          {"username": "w1_hr", "password": "wrong"},
                          format="json")
            self.assertEqual(r.status_code, 400)
        r = anon.post("/api/v1/auth/login",
                      {"username": "w1_hr", "password": "wrong"},
                      format="json")
        self.assertEqual(r.status_code, 429)
        self.assertIn("Too many", r.data["detail"])


class DuplicateMergeImportTests(TestCase):
    """`User` was referenced in views_hr but never imported, so both
    duplicate-passport endpoints raised NameError and returned 500. Ruff had
    been reporting it as F821 for weeks into a CI run nobody could read,
    because the pipeline was already red (2026-08-29)."""

    def setUp(self):
        self.admin = make_user("adm_dup", User.Role.ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_the_duplicate_passport_list_answers(self):
        r = self.client.get("/api/v1/employees/duplicate-passports")
        self.assertEqual(r.status_code, 200, r.data)
