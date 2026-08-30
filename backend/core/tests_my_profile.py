"""A person's own employment and salary record.

The security model is the absence of a parameter: nothing in views_me takes
an employee id, so the record returned is always the signed-in user's. These
tests exist to keep it that way, and to hold the two rules that are easy to
lose — only locked runs, and never anyone else's slip.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Document, Employee, EmployeeSiteAllocation,
                     ManpowerCategory, OvertimeRate, PayrollLine, PayrollRun,
                     SalaryAdvance, Site, User, WorkerLeave)
from .tests import make_user


class MyProfileTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="MEP", name="Me site",
                                        status=Site.Status.ACTIVE)
        self.cat = ManpowerCategory.objects.create(name="Mason",
                                                   list_type="DPR",
                                                   sort_order=1)
        OvertimeRate.objects.create(category=self.cat, currency="MVR",
                                    rate_per_hour=Decimal("25"),
                                    applies_by_default=True)
        self.emp = Employee.objects.create(
            emp_no="EMP-M01", full_name="Me Myself", basic_pay=Decimal("9300"),
            currency="MVR", job_category=self.cat, join_date=date(2026, 1, 5),
            employment_type="CONTRACT", engagement_type="DIRECT",
            passport_expiry=date(2029, 3, 1),
            work_permit_expiry=date(2027, 2, 1))
        EmployeeSiteAllocation.objects.create(employee=self.emp,
                                              site=self.site,
                                              from_date=date(2026, 1, 5))
        self.other_emp = Employee.objects.create(
            emp_no="EMP-M02", full_name="Someone Else",
            basic_pay=Decimal("20000"), currency="MVR",
            employment_type="PERMANENT", engagement_type="DIRECT")

        self.me = make_user("me_user", User.Role.SITE_ENGINEER, site=self.site)
        self.me.employee = self.emp
        self.me.save(update_fields=["employee"])
        self.stranger = make_user("nobody", User.Role.SITE_ADMIN,
                                  site=self.site)
        self.hr = make_user("hr_me", User.Role.HO_HR)

        self.client = APIClient()
        self.client.force_authenticate(self.me)
        # Pay is hidden by default now, so these tests — which are about
        # scoping, not the gate — open it once up front.
        self.me.set_password("correct-horse")
        self.me.save()
        self.client.post("/api/v1/me/pin/set",
                         {"pin": "4917", "password": "correct-horse"},
                         format="json")

    def _run(self, year, month, status, employee=None, kind="MONTHLY"):
        run = PayrollRun.objects.create(
            site=self.site, currency="MVR", year=year, month=month,
            working_days=31, status=status, kind=kind, created_by=self.hr)
        return PayrollLine.objects.create(
            run=run, employee=employee or self.emp, site=self.site,
            basic_pay=Decimal("9300"), ot_rate=Decimal("25"),
            days_worked=Decimal("26"), ot_hours=Decimal("10"))

    # ---- profile ---------------------------------------------------------

    def test_i_see_my_own_employment_and_pay(self):
        r = self.client.get("/api/v1/me/profile")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["linked"])
        self.assertEqual(r.data["employment"]["emp_no"], "EMP-M01")
        self.assertEqual(r.data["employment"]["site"]["code"], "MEP")
        self.assertEqual(r.data["pay"]["basic_pay"], Decimal("9300"))
        self.assertEqual(r.data["pay"]["ot_rate"], Decimal("25"))
        self.assertEqual(r.data["documents"]["work_permit_expiry"],
                         date(2027, 2, 1))

    def test_an_unlinked_login_is_told_what_to_do_not_given_an_error(self):
        self.client.force_authenticate(self.stranger)
        self.client.post("/api/v1/me/pin/lock")
        r = self.client.get("/api/v1/me/profile")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["linked"])
        self.assertIn("Ask HR", r.data["detail"])

    def test_the_profile_needs_a_login(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/v1/me/profile").status_code,
                         403)

    # ---- payslips --------------------------------------------------------

    def test_only_locked_runs_are_shown(self):
        """A draft figure is a working number nobody has signed."""
        self._run(2026, 7, "LOCKED")
        self._run(2026, 8, "DRAFT")
        r = self.client.get("/api/v1/me/payslips")
        self.assertEqual([p["month"] for p in r.data["payslips"]], [7])

    def test_my_payslip_shows_what_i_was_paid(self):
        line = self._run(2026, 7, "LOCKED")
        r = self.client.get("/api/v1/me/payslips")
        row = r.data["payslips"][0]
        self.assertEqual(row["line_id"], line.id)
        self.assertGreater(row["gross"], 0)
        self.assertEqual(row["net"], row["gross"] - row["deductions"])

    def test_a_settlement_appears_alongside_the_monthly_runs(self):
        self._run(2026, 8, "LOCKED", kind="SETTLEMENT")
        r = self.client.get("/api/v1/me/payslips")
        self.assertEqual(r.data["payslips"][0]["kind"], "SETTLEMENT")

    def test_i_cannot_open_somebody_elses_payslip(self):
        """The whole point: a guessed id must not return another man's wage."""
        theirs = self._run(2026, 7, "LOCKED", employee=self.other_emp)
        r = self.client.get(f"/api/v1/me/payslips/{theirs.id}.pdf")
        self.assertEqual(r.status_code, 404)

    def test_i_cannot_open_my_own_unlocked_payslip(self):
        mine = self._run(2026, 8, "DRAFT")
        r = self.client.get(f"/api/v1/me/payslips/{mine.id}.pdf")
        self.assertEqual(r.status_code, 404)

    def test_my_own_locked_payslip_renders(self):
        mine = self._run(2026, 7, "LOCKED")
        r = self.client.get(f"/api/v1/me/payslips/{mine.id}.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")

    def test_an_unlinked_login_gets_no_payslip(self):
        mine = self._run(2026, 7, "LOCKED")
        self.client.force_authenticate(self.stranger)
        self.assertEqual(
            self.client.get(f"/api/v1/me/payslips/{mine.id}.pdf").status_code,
            403)

    # ---- money and leave -------------------------------------------------

    def test_i_see_what_i_still_owe(self):
        doc = Document.objects.create(doc_type="PYR", ref="PYR-ME-001",
                                      site=self.site, status="PAID",
                                      doc_date=date(2026, 8, 1),
                                      created_by=self.hr)
        SalaryAdvance.objects.create(document=doc, employee=self.emp,
                                     kind=SalaryAdvance.Kind.LOAN,
                                     amount=Decimal("6000"), months=6,
                                     period_year=2026, period_month=8)
        r = self.client.get("/api/v1/me/money")
        self.assertEqual(r.data["advances"][0]["ref"], "PYR-ME-001")
        self.assertEqual(r.data["advances"][0]["installment"],
                         Decimal("1000.00"))
        self.assertEqual(r.data["outstanding"]["loan"], Decimal("6000.00"))

    def test_another_persons_advance_is_not_mine(self):
        doc = Document.objects.create(doc_type="PYR", ref="PYR-ME-002",
                                      site=self.site, status="PAID",
                                      doc_date=date(2026, 8, 1),
                                      created_by=self.hr)
        SalaryAdvance.objects.create(document=doc, employee=self.other_emp,
                                     amount=Decimal("500"), months=1,
                                     period_year=2026, period_month=8)
        r = self.client.get("/api/v1/me/money")
        self.assertEqual(r.data["advances"], [])

    def test_i_see_my_own_leave(self):
        WorkerLeave.objects.create(employee=self.emp, kind="PAID",
                                   from_date=date(2026, 6, 1),
                                   to_date=date(2026, 6, 10),
                                   from_site=self.site, granted_by=self.hr)
        WorkerLeave.objects.create(employee=self.other_emp, kind="PAID",
                                   from_date=date(2026, 6, 1),
                                   to_date=date(2026, 6, 10),
                                   from_site=self.site, granted_by=self.hr)
        r = self.client.get("/api/v1/me/leave")
        self.assertEqual(len(r.data["leave"]), 1)
        self.assertEqual(r.data["leave"][0]["from_date"], date(2026, 6, 1))


class SalaryPinTests(TestCase):
    """A PIN in front of your own pay, and a window that closes itself.

    A privacy screen, not an auth boundary: the session is already signed in.
    It stops the person standing behind you on a shared site tablet, which is
    the actual threat (owner 2026-08-30).
    """

    def setUp(self):
        self.site = Site.objects.create(code="PIN", name="Pin site",
                                        status=Site.Status.ACTIVE)
        self.emp = Employee.objects.create(
            emp_no="EMP-P01", full_name="Pin Person",
            basic_pay=Decimal("9300"), currency="MVR",
            employment_type="CONTRACT", engagement_type="DIRECT",
            join_date=date(2026, 1, 1))
        self.hr = make_user("hr_pin", User.Role.HO_HR)
        self.me = make_user("pin_user", User.Role.SITE_ENGINEER,
                            site=self.site)
        self.me.employee = self.emp
        self.me.set_password("correct-horse")
        self.me.save()
        run = PayrollRun.objects.create(site=self.site, currency="MVR",
                                        year=2026, month=7, working_days=31,
                                        status="LOCKED", created_by=self.hr)
        PayrollLine.objects.create(run=run, employee=self.emp, site=self.site,
                                   basic_pay=Decimal("9300"),
                                   days_worked=Decimal("26"))
        self.client = APIClient()
        self.client.force_authenticate(self.me)

    def _set_pin(self, pin="4917", password="correct-horse"):
        return self.client.post("/api/v1/me/pin/set",
                                {"pin": pin, "password": password},
                                format="json")

    # ---- hidden by default -----------------------------------------------

    def test_pay_is_hidden_before_any_pin_exists(self):
        """An opt-in screen protects the people who think to switch it on,
        which is not the person carrying a shared site tablet."""
        r = self.client.get("/api/v1/me/payslips")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.data["pin_required"])
        self.assertFalse(r.data["has_pin"])
        self.assertIn("Create a PIN", r.data["detail"])
        self.assertTrue(self.client.get("/api/v1/me/profile").data
                        ["pay_locked"])

    def test_creating_the_pin_is_what_opens_it_the_first_time(self):
        r = self._set_pin()
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["has_pin"])
        self.assertEqual(self.client.get("/api/v1/me/payslips").status_code,
                         200)

    def test_you_cannot_unlock_before_creating_a_pin(self):
        r = self.client.post("/api/v1/me/pin/unlock", {"pin": "4917"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("create one", r.data["detail"])

    def test_setting_a_pin_needs_the_account_password(self):
        """A session left open on a site tablet must not be able to quietly
        rewrite the PIN that defends it."""
        r = self._set_pin(password="wrong")
        self.assertEqual(r.status_code, 400)
        self.assertIn("password", r.data["detail"])
        self.me.refresh_from_db()
        self.assertEqual(self.me.salary_pin, "")

    def test_a_weak_pin_is_refused(self):
        for bad in ("1111", "1234", "12", "abcd"):
            r = self._set_pin(pin=bad)
            self.assertEqual(r.status_code, 400, bad)

    def test_the_pin_is_stored_hashed(self):
        self._set_pin()
        self.me.refresh_from_db()
        self.assertNotIn("4917", self.me.salary_pin)
        self.assertTrue(len(self.me.salary_pin) > 20)

    # ---- the gate --------------------------------------------------------

    def test_with_a_pin_set_the_pay_is_hidden_until_unlocked(self):
        self._set_pin()
        self.client.post("/api/v1/me/pin/lock")
        r = self.client.get("/api/v1/me/payslips")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.data["pin_required"])
        self.assertEqual(self.client.get("/api/v1/me/money").status_code, 403)

    def test_employment_and_documents_stay_readable_behind_the_pin(self):
        """The gate has to be tolerable to live with, so it withholds the
        pay and nothing else."""
        self._set_pin()
        self.client.post("/api/v1/me/pin/lock")
        r = self.client.get("/api/v1/me/profile")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["pay_locked"])
        self.assertIsNone(r.data["pay"])
        self.assertEqual(r.data["employment"]["emp_no"], "EMP-P01")
        self.assertEqual(r.data["documents"]["passport_no"], "")

    def test_the_right_pin_opens_it(self):
        self._set_pin()
        self.client.post("/api/v1/me/pin/lock")
        r = self.client.post("/api/v1/me/pin/unlock", {"pin": "4917"},
                             format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["seconds_left"], 180)
        self.assertEqual(self.client.get("/api/v1/me/payslips").status_code,
                         200)

    def test_a_wrong_pin_does_not_open_it(self):
        self._set_pin()
        self.client.post("/api/v1/me/pin/lock")
        r = self.client.post("/api/v1/me/pin/unlock", {"pin": "9999"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["attempts_left"], 4)
        self.assertEqual(self.client.get("/api/v1/me/payslips").status_code,
                         403)

    def test_repeated_wrong_pins_lock_it_out(self):
        self._set_pin()
        self.client.post("/api/v1/me/pin/lock")
        for _ in range(5):
            self.client.post("/api/v1/me/pin/unlock", {"pin": "9999"},
                             format="json")
        r = self.client.post("/api/v1/me/pin/unlock", {"pin": "4917"},
                             format="json")
        self.assertEqual(r.status_code, 429)

    def test_the_window_closes_on_its_own(self):
        """The clock is the server's — a client that keeps its own countdown
        can be told to stop counting."""
        from datetime import timedelta

        from django.utils import timezone

        self._set_pin()
        self.client.post("/api/v1/me/pin/unlock", {"pin": "4917"},
                         format="json")
        self.assertEqual(self.client.get("/api/v1/me/payslips").status_code,
                         200)
        s = self.client.session
        s["salary_unlocked_until"] = (
            timezone.now() - timedelta(seconds=1)).isoformat()
        s.save()
        self.assertEqual(self.client.get("/api/v1/me/payslips").status_code,
                         403)

    def test_the_payslip_pdf_is_behind_the_pin_too(self):
        """The list being hidden means nothing if the document is not."""
        line = PayrollLine.objects.get(employee=self.emp)
        self._set_pin()
        self.client.post("/api/v1/me/pin/lock")
        self.assertEqual(
            self.client.get(f"/api/v1/me/payslips/{line.id}.pdf").status_code,
            403)
        self.client.post("/api/v1/me/pin/unlock", {"pin": "4917"},
                         format="json")
        self.assertEqual(
            self.client.get(f"/api/v1/me/payslips/{line.id}.pdf").status_code,
            200)

    def test_the_gate_cannot_be_switched_off(self):
        """There is no "no PIN" state to fall back to — an empty PIN is just
        an invalid one."""
        self._set_pin()
        r = self.client.post("/api/v1/me/pin/set",
                             {"pin": "", "password": "correct-horse"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.me.refresh_from_db()
        self.assertTrue(self.me.salary_pin)

    def test_the_password_is_the_forgotten_pin_path(self):
        """Changing needs the account password, not the old PIN — so a
        forgotten PIN is recoverable without an admin."""
        self._set_pin(pin="4917")
        r = self._set_pin(pin="8253")
        self.assertEqual(r.status_code, 200, r.data)
        self.client.post("/api/v1/me/pin/lock")
        self.assertEqual(
            self.client.post("/api/v1/me/pin/unlock", {"pin": "8253"},
                             format="json").status_code, 200)

    def test_status_reports_the_time_left(self):
        self._set_pin()
        r = self.client.get("/api/v1/me/pin")
        self.assertTrue(r.data["has_pin"])
        self.assertGreater(r.data["seconds_left"], 0)
        self.assertEqual(r.data["window_seconds"], 180)

    def test_an_open_window_dies_with_the_pin_behind_it(self):
        """If the PIN is cleared out from under a session, that session's
        remaining minutes must not keep the pay on screen."""
        self._set_pin()
        self.assertEqual(self.client.get("/api/v1/me/payslips").status_code,
                         200)
        self.me.salary_pin = ""
        self.me.save(update_fields=["salary_pin"])
        self.assertEqual(self.client.get("/api/v1/me/payslips").status_code,
                         403)
