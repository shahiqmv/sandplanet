"""Management reports (owner 2026-11-07): read by the named ExCom members
company-wide and by a PM for their own sites; nobody else."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (AuditLog, Boq, Employee, ManpowerCategory, PayrollLine,
                     PayrollRun, ProgrammeActivity, Project, Site,
                     SitePmHistory, User, Variation, VariationItem)
from .tests import make_user

D = Decimal


class ReportCase(TestCase):
    def setUp(self):
        self.sjr = Site.objects.create(code="SJR", name="Soneva Jani",
                                       status=Site.Status.ACTIVE)
        self.vkr = Site.objects.create(code="VKR", name="Vakkaru",
                                       status=Site.Status.ACTIVE)
        self.director = make_user("rp_pd", User.Role.DIRECTOR)
        self.qs = make_user("rp_qs", User.Role.QS)
        self.fin = make_user("rp_fin", User.Role.FINANCE)
        self.admin = make_user("rp_admin", User.Role.ADMIN)
        for u in (self.director, self.qs):
            u.excom = True
            u.save(update_fields=["excom"])
        self.pm = make_user("rp_pm", User.Role.PM)
        SitePmHistory.objects.create(site=self.sjr, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.c = APIClient()

    def get(self, user, path, **params):
        self.c.force_authenticate(user)
        return self.c.get(path, params)

    def report(self, user, key, site, start="2026-10-01", end="2026-10-31",
            **extra):
        return self.get(user, f"/api/v1/reports/{key}", site=site,
                        **{"from": start, "to": end}, **extra)


class AccessTests(ReportCase):
    def test_only_excom_and_pms_read_reports(self):
        for u in (self.fin, self.admin):
            self.assertEqual(self.get(u, "/api/v1/reports").status_code, 403)
            self.assertEqual(self.report(u, "revenue", self.sjr.id).status_code,
                             403)

    def test_excom_sees_every_site_and_the_company(self):
        d = self.get(self.qs, "/api/v1/reports").data
        self.assertTrue(d["company"])
        self.assertEqual([s["code"] for s in d["sites"]], ["SJR", "VKR"])
        self.assertEqual({r["key"] for r in d["reports"]},
                         {"revenue", "manpower", "progress"})
        self.assertEqual(self.report(self.qs, "revenue", "all").status_code, 200)

    def test_a_pm_sees_only_their_own_sites_and_nothing_company_wide(self):
        d = self.get(self.pm, "/api/v1/reports").data
        self.assertFalse(d["company"])
        self.assertEqual([s["code"] for s in d["sites"]], ["SJR"])
        self.assertEqual(self.report(self.pm, "progress", "all").status_code, 403)
        self.assertEqual(self.report(self.pm, "progress", self.vkr.id)
                         .status_code, 400)
        self.assertEqual(self.report(self.pm, "progress", self.sjr.id)
                         .status_code, 200)

    def test_a_pm_who_has_moved_on_loses_the_site(self):
        SitePmHistory.objects.filter(pm_user=self.pm).update(
            to_date=date(2026, 10, 1))
        self.assertEqual(self.get(self.pm, "/api/v1/reports").data["sites"],
                         [])

    def test_every_run_is_audited(self):
        self.report(self.qs, "revenue", "all")
        a = AuditLog.objects.get(event="REPORT_RUN")
        self.assertEqual((a.detail["report"], a.detail["scope"]),
                         ("revenue", "all"))

    def test_bad_periods_are_refused(self):
        self.assertEqual(self.report(self.qs, "revenue", "all", start="x")
                         .status_code, 400)
        self.assertEqual(self.report(self.qs, "revenue", "all",
                                  start="2026-10-31", end="2026-10-01")
                         .status_code, 400)

    def test_only_admin_sets_excom_and_it_is_audited(self):
        self.c.force_authenticate(self.fin)
        self.assertEqual(self.c.post(f"/api/v1/users/{self.fin.id}/excom",
                                     {"on": True}, format="json").status_code,
                         403)
        self.c.force_authenticate(self.admin)
        r = self.c.post(f"/api/v1/users/{self.fin.id}/excom", {"on": True},
                        format="json")
        self.assertTrue(r.data["excom"])
        self.assertTrue(AuditLog.objects.filter(event="USER_EXCOM").exists())
        # a plain edit cannot set it
        self.c.patch(f"/api/v1/users/{self.pm.id}", {"excom": True},
                     format="json")
        self.pm.refresh_from_db()
        self.assertFalse(self.pm.excom)


class RevenueTests(ReportCase):
    def test_contract_variations_and_what_is_with_the_client(self):
        p = Project.objects.create(site=self.sjr, code="P1", title="Villas",
                                   status="ACTIVE",
                                   contract_value=D("100000"))
        Boq.objects.create(project=p, currency="USD")
        for seq, status, rate in ((1, "APPROVED", "5000"),
                                  (2, "SUBMITTED", "2000")):
            v = Variation.objects.create(project=p, seq=seq,
                                         ref=f"VO-0{seq}", title="Extra",
                                         status=status,
                                         sent_at=date(2026, 10, 1))
            VariationItem.objects.create(variation=v, qty=1,
                                         rate_supply=D(rate))
        rep = self.report(self.qs, "revenue", "all").data
        row = rep["sections"][0]["rows"][0]
        self.assertEqual((row["original"], row["approved_vos"], row["revised"],
                          row["pending_vos"]),
                         (D("100000.00"), D("5000.00"), D("105000.00"),
                          D("2000.00")))
        vos = rep["sections"][2]["rows"]
        self.assertEqual([(v["vo"], v["waiting"]) for v in vos],
                         [("VO-02", 30)])

    def test_a_closed_project_with_nothing_on_it_is_left_out(self):
        """BVR's fish pond and kids' club: closed, never certified or paid —
        their contract value is not revenue (owner 2026-11-07)."""
        from .models import ClientReceipt
        for code, status in (("RUN", "ACTIVE"), ("GONE", "CLOSED"),
                             ("DONE", "CLOSED"), ("BID", "POTENTIAL")):
            Project.objects.create(site=self.sjr, code=code, title=code,
                                   status=status, contract_value=D("1000"))
        ClientReceipt.objects.create(
            project=Project.objects.get(code="DONE"), amount=D("500"),
            received_on=date(2026, 9, 1))
        rep = self.report(self.qs, "revenue", "all").data
        rows = rep["sections"][0]["rows"]
        self.assertEqual([r["project"].split(" ")[0] for r in rows],
                         ["DONE", "RUN"])
        self.assertEqual(rep["kpis"][0]["value"], D("2000.00"))

    def test_a_pm_report_holds_only_their_site(self):
        for site, code in ((self.sjr, "A"), (self.vkr, "B")):
            Project.objects.create(site=site, code=code, title=code,
                                   status="ACTIVE",
                                   contract_value=D("1000"))
        rep = self.report(self.pm, "revenue", self.sjr.id).data
        self.assertEqual([r["site"] for r in rep["sections"][0]["rows"]],
                         ["SJR"])


class ManpowerTests(ReportCase):
    def setUp(self):
        super().setUp()
        mason = ManpowerCategory.objects.create(
            list_type="DPR", grp="LABOUR", name="Mason", sort_order=1)
        eng = ManpowerCategory.objects.create(
            list_type="DPR", grp="STAFF", name="Site Engineer", sort_order=2)
        self.run_oct = PayrollRun.objects.create(
            ref="PAY-SJR-2026-10", site=self.sjr, kind="MONTHLY",
            currency="USD", year=2026, month=10, working_days=26, created_by=self.fin,
            status="LOCKED")
        w = Employee.objects.create(emp_no="EMP-9001", full_name="Mason One",
                                    basic_pay=2600, currency="USD",
                                    job_category=mason)
        e = Employee.objects.create(emp_no="EMP-9002", full_name="Eng One",
                                    basic_pay=5200, currency="USD",
                                    job_category=eng)
        # the mason worked 13 days at VKR then 13 at SJR, his OT all at SJR
        PayrollLine.objects.create(
            run=self.run_oct, employee=w, site=self.sjr, basic_pay=2600,
            ot_rate=10, days_worked=26, ot_hours=10,
            site_split=[{"site": self.vkr.id, "days": "13", "ot_hours": "0",
                         "fridays": 0},
                        {"site": self.sjr.id, "days": "13",
                         "ot_hours": "10", "fridays": 0}])
        PayrollLine.objects.create(run=self.run_oct, employee=e,
                                   site=self.sjr, basic_pay=5200,
                                   days_worked=26)

    def test_cost_lands_where_the_work_was_done(self):
        rep = self.report(self.qs, "manpower", "all").data
        by_site = {r["site"][:3]: r for r in rep["sections"][0]["rows"]}
        # mason: basic 2600 split by days, OT 100 to SJR; engineer 5200 at SJR
        self.assertEqual(by_site["VKR"]["cost"], D("1300.00"))
        self.assertEqual(by_site["SJR"]["cost"], D("6600.00"))
        self.assertEqual(by_site["SJR"]["ot_cost"], D("100.00"))
        self.assertEqual(by_site["SJR"]["days"], D("39"))
        self.assertEqual(rep["kpis"][0]["value"], D("7900.00"))

    def test_a_pm_sees_staff_as_one_line_and_no_person(self):
        rep = self.report(self.pm, "manpower", self.sjr.id).data
        titles = [s["title"] for s in rep["sections"]]
        self.assertNotIn("By person", titles)
        self.assertNotIn("By site", titles)
        trades = [r["trade"] for r in rep["sections"][-1]["rows"]]
        self.assertIn("Staff — all grades", trades)
        self.assertNotIn("Site Engineer", trades)

    def test_the_director_sees_people_and_qs_does_not(self):
        pd = self.report(self.director, "manpower", "all").data
        people = next(s for s in pd["sections"] if s["title"] == "By person")
        self.assertEqual(people["rows"][0]["emp_no"], "EMP-9002")
        qs = self.report(self.qs, "manpower", "all").data
        self.assertNotIn("By person", [s["title"] for s in qs["sections"]])

    def test_a_run_not_yet_locked_is_named_not_counted(self):
        PayrollRun.objects.filter(pk=self.run_oct.pk).update(
            status="PD_REVIEW")
        rep = self.report(self.qs, "manpower", "all").data
        self.assertEqual(rep["kpis"][0]["value"], 0)
        self.assertIn("SJR Oct 2026", " ".join(rep["notes"]))


class ProgressTests(ReportCase):
    def test_rating_and_missed_milestones(self):
        end = date(2026, 10, 31)
        p = Project.objects.create(
            site=self.sjr, code="P1", title="Pools", status="ACTIVE",
            start_date=end - timedelta(days=100),
            planned_completion=end + timedelta(days=100))
        ProgrammeActivity.objects.create(project=p, sort_order=1,
                                         name="Shell", duration_days=10,
                                         progress=20)
        ProgrammeActivity.objects.create(
            project=p, sort_order=2, name="Handover A", is_milestone=True,
            finish=date(2026, 10, 15), progress=0)
        rep = self.report(self.qs, "progress", "all").data
        row = rep["sections"][0]["rows"][0]
        self.assertEqual((row["elapsed"], row["progress"], row["rating"],
                          row["missed"]), (50.0, 20.0, "Attention", 1))
        ms = rep["sections"][1]["rows"]
        self.assertEqual([(m["milestone"], m["state"]) for m in ms],
                         [("Handover A", "Missed")])


class ExportTests(ReportCase):
    def test_excel_and_pdf_come_out(self):
        Project.objects.create(site=self.sjr, code="P1", title="Villas",
                               status="ACTIVE", contract_value=D("1000"))
        r = self.report(self.qs, "revenue", "all", export="xlsx")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"PK"))
        r = self.report(self.qs, "progress", self.sjr.id, export="pdf")
        self.assertIn(r.status_code, (200, 503))   # 503: no PDF engine
