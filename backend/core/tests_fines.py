"""Worker fines: site records, PM approves, payroll deducts (owner 2026-09-29)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core import payroll
from .models import (Attendance, Employee, EmployeeSiteAllocation, FineOffence,
                     ManpowerCategory, OvertimeRate, PayrollRun, Site,
                     SitePmHistory, User, WorkerFine)
from .tests import make_user

TODAY = date.today()
Y, M = TODAY.year, TODAY.month
BREACH = date(Y, M, 1)


class FineTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="FNS", name="Fine Isle",
                                        status=Site.Status.ACTIVE)
        self.other = Site.objects.create(code="FNO", name="Other Isle",
                                         status=Site.Status.ACTIVE)
        self.sa = make_user("fn_sa", User.Role.SITE_ADMIN, self.site)
        self.se = make_user("fn_se", User.Role.SITE_ENGINEER, self.site)
        self.pm = make_user("fn_pm", User.Role.PM, self.site)
        self.pm2 = make_user("fn_pm2", User.Role.PM, self.other)
        self.hr = make_user("fn_hr", User.Role.HO_HR)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        SitePmHistory.objects.create(site=self.other, pm_user=self.pm2,
                                     from_date=date(2026, 1, 1))
        cat = ManpowerCategory.objects.create(list_type="DPR", grp="LABOUR",
                                              name="Mason", sort_order=1)
        OvertimeRate.objects.create(category=cat, currency="MVR",
                                    rate_per_hour=Decimal("25"),
                                    applies_by_default=True)
        self.emp = Employee.objects.create(
            emp_no="EMP-7201", full_name="Fined Worker", basic_pay=6000,
            currency="MVR", job_category=cat, join_date=date(2026, 1, 1))
        EmployeeSiteAllocation.objects.create(employee=self.emp, site=self.site,
                                              from_date=date(2026, 1, 1))
        Attendance.objects.create(employee=self.emp, site=self.site,
                                  day=BREACH, remark="PRESENT")
        self.helmet = FineOffence.objects.create(
            name="No helmet", category="SAFETY", default_amount=100)
        self.c = APIClient()

    def as_(self, u):
        self.c.force_authenticate(u)
        return self.c

    def record(self, user=None, **kw):
        body = {"site": self.site.id, "employee": self.emp.id,
                "violation_date": BREACH.isoformat(), "offence": self.helmet.id,
                "amount": "100", "description": "No helmet on level 3"}
        body.update(kw)
        return self.as_(user or self.sa).post("/api/v1/fines", body,
                                              format="multipart")

    def make_run(self):
        return payroll.generate_run(site=self.site, currency="MVR", year=Y,
                                    month=M, working_days=30, actor=self.hr)

    # ---- recording --------------------------------------------------------

    def test_site_team_records_and_it_waits_for_the_pm(self):
        r = self.record()
        self.assertEqual(r.status_code, 201, r.data)
        f = r.data["results"][0]
        self.assertEqual(f["status"], "PENDING")
        self.assertTrue(f["ref"].startswith("FIN-FNS-"))
        self.assertEqual(f["category"], "SAFETY")
        tasks = self.as_(self.pm).get("/api/v1/approvals/pending").data
        items = [i for g in tasks["groups"] for i in g["items"]
                 if i["doc_type"] == "FINE"]
        self.assertEqual([i["ref"] for i in items], [f["ref"]])

    def test_several_men_ticked_get_a_fine_each(self):
        two = Employee.objects.create(
            emp_no="EMP-7202", full_name="Second Worker", basic_pay=6000,
            currency="MVR", join_date=date(2026, 1, 1))
        EmployeeSiteAllocation.objects.create(employee=two, site=self.site,
                                              from_date=date(2026, 1, 1))
        r = self.as_(self.sa).post("/api/v1/fines", {
            "site": self.site.id, "employees": [self.emp.id, two.id],
            "violation_date": BREACH.isoformat(), "offence": self.helmet.id,
            "amount": "100", "description": "Both without helmets"},
            format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual([x["emp_no"] for x in r.data["results"]],
                         ["EMP-7201", "EMP-7202"])
        self.assertEqual(len({x["ref"] for x in r.data["results"]}), 2)
        # One man not at the site → nothing is recorded for either
        stranger = Employee.objects.create(emp_no="EMP-7203",
                                           full_name="Elsewhere", basic_pay=1)
        r = self.as_(self.sa).post("/api/v1/fines", {
            "site": self.site.id, "employees": [self.emp.id, stranger.id],
            "violation_date": BREACH.isoformat(), "amount": "50",
            "category": "OTHER", "description": "x"}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(WorkerFine.objects.count(), 2)

    def test_engineer_can_record_too(self):
        self.assertEqual(self.record(self.se).status_code, 201)

    def test_another_sites_team_cannot(self):
        other_sa = make_user("fn_osa", User.Role.SITE_ADMIN, self.other)
        self.assertEqual(self.record(other_sa).status_code, 400)

    def test_worker_must_be_at_the_site_that_day(self):
        r = self.record(violation_date="2025-12-31")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not allocated", r.data["detail"])

    def test_no_future_breach_no_zero_fine(self):
        self.assertEqual(self.record(violation_date="2099-01-01").status_code, 400)
        self.assertEqual(self.record(amount="0").status_code, 400)

    def test_subcontract_worker_is_refused(self):
        self.emp.engagement_type = "SUBCONTRACT"
        self.emp.save(update_fields=["engagement_type"])
        self.assertIn("subcontract", self.record().data["detail"])

    # ---- deciding ---------------------------------------------------------

    def test_only_the_sites_pm_decides_never_the_recorder(self):
        fid = self.record().data["results"][0]["id"]
        self.assertEqual(self.as_(self.sa).post(f"/api/v1/fines/{fid}/approve").status_code, 400)
        self.assertEqual(self.as_(self.pm2).post(f"/api/v1/fines/{fid}/approve").status_code, 404)
        r = self.as_(self.pm).post(f"/api/v1/fines/{fid}/approve")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "APPROVED")
        pm_fid = self.record(self.pm).data["results"][0]["id"]
        self.assertIn("never the person",
                      self.as_(self.pm).post(f"/api/v1/fines/{pm_fid}/approve").data["detail"])

    def test_reject_needs_a_reason(self):
        fid = self.record().data["results"][0]["id"]
        self.assertEqual(self.as_(self.pm).post(f"/api/v1/fines/{fid}/reject").status_code, 400)
        r = self.as_(self.pm).post(f"/api/v1/fines/{fid}/reject", {"note": "Had a helmet"})
        self.assertEqual(r.data["status"], "REJECTED")

    # ---- payroll ----------------------------------------------------------

    def test_approved_fine_is_the_payroll_penalty(self):
        fid = self.record().data["results"][0]["id"]
        self.record(amount="50", offence="", category="DISCIPLINARY",
                    description="Late back from break")   # still pending
        self.as_(self.pm).post(f"/api/v1/fines/{fid}/approve")
        run = self.make_run()
        line = run.lines.get(employee=self.emp)
        self.assertEqual(line.penalty, Decimal("100"))
        self.assertEqual(payroll.compute_line(line)["deductions"], Decimal("100.00"))

    def test_approval_reaches_a_draft_run_at_once(self):
        run = self.make_run()
        fid = self.record().data["results"][0]["id"]
        self.as_(self.pm).post(f"/api/v1/fines/{fid}/approve")
        self.assertEqual(run.lines.get(employee=self.emp).penalty, Decimal("100"))
        self.as_(self.pm).post(f"/api/v1/fines/{fid}/cancel", {"reason": "Appeal upheld"})
        self.assertEqual(run.lines.get(employee=self.emp).penalty, Decimal("0"))

    def test_a_run_already_signed_off_is_left_alone(self):
        run = self.make_run()
        PayrollRun.objects.filter(pk=run.pk).update(status="PD_REVIEW")
        fid = self.record().data["results"][0]["id"]
        r = self.as_(self.pm).post(f"/api/v1/fines/{fid}/approve")
        nxt = (Y + 1, 1) if M == 12 else (Y, M + 1)
        f = WorkerFine.objects.get(pk=fid)
        self.assertEqual((f.deduct_year, f.deduct_month), nxt)
        self.assertEqual(run.lines.get(employee=self.emp).penalty, Decimal("0"))
        self.assertTrue(r.data["deduct_period"])

    def test_hr_can_no_longer_type_a_penalty(self):
        run = self.make_run()
        line = run.lines.get(employee=self.emp)
        r = self.as_(self.hr).patch(f"/api/v1/payroll/lines/{line.id}",
                                    {"penalty": "500", "allowance": "10"},
                                    format="json")
        self.assertEqual(r.status_code, 200, r.data)
        line.refresh_from_db()
        self.assertEqual(line.allowance, Decimal("10"))
        self.assertEqual(line.penalty, Decimal("0"))

    def test_lock_spends_the_fine_and_refresh_keeps_it(self):
        fid = self.record().data["results"][0]["id"]
        self.as_(self.pm).post(f"/api/v1/fines/{fid}/approve")
        run = self.make_run()
        payroll.refresh_run(run, self.hr)
        self.assertEqual(run.lines.get(employee=self.emp).penalty, Decimal("100"))
        run.status = "APPROVED"
        run.save(update_fields=["status"])
        payroll.lock_run(run, self.hr)
        f = WorkerFine.objects.get(pk=fid)
        self.assertEqual(f.payroll_line.run_id, run.id)
        r = self.as_(self.pm).post(f"/api/v1/fines/{fid}/cancel", {"reason": "x"})
        self.assertEqual(r.status_code, 400)

    def test_a_man_not_on_the_run_carries_to_next_month(self):
        fid = self.record().data["results"][0]["id"]
        self.as_(self.pm).post(f"/api/v1/fines/{fid}/approve")
        run = self.make_run()
        run.lines.filter(employee=self.emp).delete()     # moved away
        run.status = "APPROVED"
        run.save(update_fields=["status"])
        payroll.lock_run(run, self.hr)
        f = WorkerFine.objects.get(pk=fid)
        nxt = (Y + 1, 1) if M == 12 else (Y, M + 1)
        self.assertIsNone(f.payroll_line)
        self.assertEqual((f.deduct_year, f.deduct_month), nxt)
        self.assertIn("carried", f.carried_note)

    def test_offence_list_is_hr_only(self):
        r = self.as_(self.sa).post("/api/v1/fines/offences",
                                   {"name": "Smoking", "category": "SAFETY",
                                    "default_amount": "200"}, format="json")
        self.assertEqual(r.status_code, 403)
        r = self.as_(self.hr).post("/api/v1/fines/offences",
                                   {"name": "Smoking", "category": "SAFETY",
                                    "default_amount": "200"}, format="json")
        self.assertEqual(r.status_code, 201)
