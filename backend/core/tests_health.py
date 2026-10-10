"""Worker health log (SOP-HR-04, owner 2026-10-10): every complaint is a
case, every action a dated step, the referral ladder is computed, repeat
sickness and clusters are flagged, and nothing medical leaks."""
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from . import health
from .models import (Attendance, Employee, EmployeeSiteAllocation, HealthAlert,
                     HealthCase, ManpowerCategory, Notification, Site,
                     User)
from .tests import make_user


class HealthBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.other = Site.objects.create(code="VKR", name="Vakkaru",
                                         status=Site.Status.ACTIVE)
        self.sa = make_user("h_sa", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("h_pm", User.Role.PM, site=self.site)
        self.site.pm_history.create(pm_user=self.pm, from_date=date(2026, 1, 1))
        self.hr = make_user("h_hr", User.Role.HO_HR)
        self.director = make_user("h_dir", User.Role.DIRECTOR)
        self.far = make_user("h_far", User.Role.SITE_ADMIN, site=self.other)
        self.cat = ManpowerCategory.objects.create(name="Mason", sort_order=1)
        self.emps = []
        for i in range(1, 8):
            e = Employee.objects.create(
                emp_no=f"EMP-{i:04d}", full_name=f"Worker {i}",
                job_category=self.cat, nationality="Bangladeshi",
                join_date=date(2026, 1, 1))
            EmployeeSiteAllocation.objects.create(
                employee=e, site=self.site, from_date=date(2026, 1, 1))
            self.emps.append(e)
        self.emp = self.emps[0]
        self.c = APIClient()
        self.c.force_authenticate(self.sa)

    def report(self, emp=None, **extra):
        body = {"site_id": self.site.id, "employee_id": (emp or self.emp).id,
                "complaint": "FEVER", "symptoms": "fever since last night",
                "temperature": "38.4"}
        body.update(extra)
        return self.c.post("/api/v1/health/cases", body, format="json")

    def step(self, case_id, kind, **extra):
        return self.c.post(f"/api/v1/health/cases/{case_id}/events",
                           {"kind": kind, **extra}, format="json")


class CaseTests(HealthBase):
    def test_a_report_opens_a_case_and_the_ladder_says_what_is_due(self):
        r = self.report()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["ref"], "HLT-SJR-001")
        self.assertEqual(r.data["due_level"], 2)
        self.assertIn("Not yet attended", r.data["due"])
        # it sits on My Tasks for the site team until attended
        groups = self.c.get("/api/v1/approvals/pending").data["groups"]
        g = next(g for g in groups if g["title"].startswith("Health"))
        self.assertEqual(g["items"][0]["ref"], "HLT-SJR-001")
        self.assertEqual(g["items"][0]["doc_type"], "HLT")
        # first aid attends it; a fever still has to see a doctor today
        r = self.step(r.data["id"], "FIRST_AID", detail="Paracetamol, rest")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["attended"])
        self.assertIn("doctor", r.data["due"])
        groups = self.c.get("/api/v1/approvals/pending").data["groups"]
        self.assertFalse(any(g["title"].startswith("Health") for g in groups))

    def test_a_second_report_joins_the_open_case(self):
        a = self.report(complaint="UNKNOWN").data
        b = self.report(complaint="STOMACH")
        self.assertEqual(b.status_code, 200)
        self.assertEqual(b.data["id"], a["id"])
        self.assertEqual(b.data["complaint"], "STOMACH")
        self.assertEqual(HealthCase.objects.count(), 1)

    def test_a_referred_or_feverish_man_returns_only_with_a_clearance(self):
        cid = self.report().data["id"]
        self.step(cid, "FIRST_AID")
        r = self.c.post(f"/api/v1/health/cases/{cid}/close", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("clearance", r.data["detail"])
        r = self.step(cid, "DOCTOR", facility="Resort clinic",
                      detail="Viral fever, 2 days rest")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["referred"])
        self.assertIn("report", r.data["due"].lower())
        r = self.step(cid, "CLEARED", fit_on="2026-10-12", light_duties=True)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "CLOSED")
        self.assertEqual(str(r.data["fit_on"]), "2026-10-12")
        self.assertTrue(r.data["light_duties"])

    def test_a_minor_case_closes_by_hand_once_attended(self):
        cid = self.report(complaint="PAIN", temperature="").data["id"]
        r = self.c.post(f"/api/v1/health/cases/{cid}/close", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("what was done", r.data["detail"])
        self.step(cid, "FIRST_AID", detail="Ice pack")
        r = self.c.post(f"/api/v1/health/cases/{cid}/close",
                        {"note": "Better next morning"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "CLOSED")

    def test_male_and_evacuation_need_an_escort_and_tell_the_director(self):
        cid = self.report().data["id"]
        self.step(cid, "FIRST_AID")
        r = self.step(cid, "MALE", facility="IGMH")
        self.assertEqual(r.status_code, 400)
        self.assertIn("escort", r.data["detail"])
        r = self.step(cid, "MALE", facility="IGMH", escort="Foreman Rahim")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(Notification.objects.filter(
            recipient=self.director, title__contains="Malé").exists())
        self.assertTrue(Notification.objects.filter(
            recipient=self.pm, title__contains="Malé").exists())

    def test_the_ladder_escalates_on_repeat_and_long_sickness(self):
        # the same complaint twice in 7 days → doctor today
        first = self.report(complaint="STOMACH", temperature="").data["id"]
        self.step(first, "FIRST_AID")
        self.c.post(f"/api/v1/health/cases/{first}/close", {}, format="json")
        second = self.report(complaint="STOMACH", temperature="").data
        self.assertEqual(second["earlier_same"], 1)
        self.step(second["id"], "FIRST_AID")
        d = self.c.get(f"/api/v1/health/cases/{second['id']}").data
        self.assertIn("2nd complaint", d["due"])
        self.assertEqual(d["due_level"], 2)
        # a third → Malé within 24 hours
        self.c.post(f"/api/v1/health/cases/{second['id']}/close", {},
                    format="json")
        self.step(second["id"], "NOTE")           # closed: note allowed
        third = self.report(complaint="STOMACH", temperature="").data
        self.step(third["id"], "FIRST_AID")
        d = self.c.get(f"/api/v1/health/cases/{third['id']}").data
        self.assertEqual(d["due_level"], 3)
        self.assertIn("Malé", d["due"])

    def test_a_red_flag_is_an_evacuation_now(self):
        r = self.report(red_flag=True, symptoms="chest pain, collapsed")
        self.assertEqual(r.data["due_level"], 3)
        self.assertIn("evacuation", r.data["due"])
        self.assertTrue(Notification.objects.filter(
            recipient=self.director, title__startswith="RED FLAG").exists())

    def test_a_case_not_attended_for_a_day_is_overdue(self):
        cid = self.report().data["id"]
        HealthCase.objects.filter(pk=cid).update(
            created_at=timezone.now() - timedelta(hours=30))
        d = self.c.get(f"/api/v1/health/cases/{cid}").data
        self.assertEqual(d["due_level"], 3)
        self.assertIn("24 hours", d["due"])
        s = self.c.get(f"/api/v1/health/summary?site={self.site.id}").data
        self.assertEqual((s["open"], s["unattended"], s["overdue"]), (1, 1, 1))

    def test_follow_up_checks_after_return(self):
        cid = self.report().data["id"]
        self.step(cid, "DOCTOR", facility="Clinic")
        fit = date.today() - timedelta(days=4)
        self.step(cid, "CLEARED", fit_on=fit.isoformat())
        due = self.c.get(f"/api/v1/health/follow-ups?site={self.site.id}").data
        self.assertEqual(len(due), 1)
        self.assertIn("Day-3", due[0]["due"])
        self.step(cid, "FOLLOW_UP", detail="Fine")
        due = self.c.get(f"/api/v1/health/follow-ups?site={self.site.id}").data
        self.assertEqual(due, [])


class AttendanceLinkTests(HealthBase):
    def _save(self, rows, day=None):
        day = day or date.today()
        return self.c.put("/api/v1/attendance/bulk",
                          {"site": self.site.id, "date": day.isoformat(),
                           "rows": rows}, format="json")

    def test_a_sick_mark_opens_the_case_and_sick_days_are_counted(self):
        r = self._save([{"employee_id": self.emp.id, "remark": "SICK"}])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["health_cases_opened"]), 1)
        case = HealthCase.objects.get()
        self.assertEqual(case.source, "ATTENDANCE")
        self.assertEqual(case.complaint, "UNKNOWN")
        # the next morning's SICK mark joins the same case
        r = self._save([{"employee_id": self.emp.id, "remark": "SICK"}],
                       day=date.today() - timedelta(days=1))
        self.assertEqual(r.data["health_cases_opened"], [])
        self.assertEqual(HealthCase.objects.count(), 1)
        grid = self.c.get(f"/api/v1/attendance?site={self.site.id}"
                          f"&date={date.today().isoformat()}").data
        row = next(x for x in grid["rows"] if x["employee_id"] == self.emp.id)
        self.assertEqual(row["open_health_case"], case.id)
        case.refresh_from_db()
        self.assertEqual(health.days_sick(case), 2)

    def test_an_absence_needs_a_reason(self):
        r = self._save([{"employee_id": self.emp.id, "remark": "ABSENT"}])
        self.assertEqual(r.data["saved"], 0)
        self.assertIn("reason", r.data["refused"][0])
        r = self._save([{"employee_id": self.emp.id, "remark": "ABSENT",
                         "absence_reason": "no_show",
                         "absence_note": "not in camp"}])
        self.assertEqual(r.data["saved"], 1, r.data)
        a = Attendance.objects.get(employee=self.emp)
        self.assertEqual((a.absence_reason, a.absence_note),
                         ("NO_SHOW", "not in camp"))
        # the reason is cleared when the mark changes
        self._save([{"employee_id": self.emp.id, "remark": "PRESENT"}])
        a.refresh_from_db()
        self.assertEqual(a.absence_reason, "")


class RepeatAndClusterTests(HealthBase):
    def test_three_cases_in_ninety_days_is_a_repeat(self):
        for i in range(3):
            HealthCase.objects.create(
                ref=f"HLT-SJR-{i:03d}", employee=self.emp, site=self.site,
                reported_on=date.today() - timedelta(days=20 * i),
                complaint="FEVER", status="CLOSED")
        rep = self.c.get(f"/api/v1/health/repeat?site={self.site.id}").data
        self.assertEqual([r["emp_no"] for r in rep], ["EMP-0001"])
        self.assertEqual(rep[0]["cases"], 3)
        w = self.c.get(f"/api/v1/health/workers?site={self.site.id}").data
        self.assertEqual(next(x for x in w if x["id"] == self.emp.id)
                         ["repeat_cases"], 3)
        grid = self.c.get(f"/api/v1/attendance?site={self.site.id}"
                          f"&date={date.today().isoformat()}").data
        row = next(x for x in grid["rows"] if x["employee_id"] == self.emp.id)
        self.assertEqual(row["repeat_sick"], 3)

    def test_five_of_a_kind_in_a_week_is_an_outbreak_told_once(self):
        for e in self.emps[:4]:
            self.report(emp=e, complaint="STOMACH", temperature="")
        self.assertEqual(HealthAlert.objects.count(), 0)
        self.report(emp=self.emps[4], complaint="STOMACH", temperature="")
        self.assertEqual(HealthAlert.objects.count(), 1)
        self.assertTrue(Notification.objects.filter(
            recipient=self.hr, title__contains="outbreak").exists())
        n = Notification.objects.filter(title__contains="outbreak").count()
        self.report(emp=self.emps[5], complaint="STOMACH", temperature="")
        self.assertEqual(HealthAlert.objects.count(), 1)      # same cluster
        self.assertEqual(Notification.objects.filter(
            title__contains="outbreak").count(), n)
        s = self.c.get(f"/api/v1/health/summary?site={self.site.id}").data
        self.assertEqual(s["alerts"][0]["count"], 6)
        # quiet for 14 days → closed by the daily sweep
        HealthCase.objects.update(reported_on=date.today() - timedelta(days=20))
        self.assertEqual(health.sweep_alerts(), 1)

    def test_any_suspected_dengue_is_an_alert(self):
        self.report(complaint="DENGUE")
        self.assertEqual(HealthAlert.objects.count(), 1)


class PrivacyAndScopeTests(HealthBase):
    def test_another_sites_admin_sees_nothing(self):
        cid = self.report().data["id"]
        self.c.force_authenticate(self.far)
        self.assertEqual(self.c.get(f"/api/v1/health/cases/{cid}")
                         .status_code, 404)
        self.assertEqual(self.c.get("/api/v1/health/cases").data, [])
        self.assertEqual(self.c.post("/api/v1/health/cases", {
            "site_id": self.site.id, "employee_id": self.emp.id,
            "complaint": "FEVER"}, format="json").status_code, 403)

    def test_the_profile_is_for_hr_the_director_and_the_sites_pm(self):
        self.c.force_authenticate(self.hr)
        r = self.c.patch(f"/api/v1/health/employees/{self.emp.id}",
                         {"blood_group": "O+", "allergies": "Penicillin"},
                         format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["profile"]["allergies"], "Penicillin")
        self.c.force_authenticate(self.pm)
        r = self.c.get(f"/api/v1/health/employees/{self.emp.id}")
        self.assertEqual(r.data["profile"]["blood_group"], "O+")
        self.c.force_authenticate(self.sa)
        r = self.c.get(f"/api/v1/health/employees/{self.emp.id}")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("profile", r.data)
        self.assertEqual(self.c.patch(
            f"/api/v1/health/employees/{self.emp.id}",
            {"blood_group": "A+"}, format="json").status_code, 403)
        # never on the employee serializer
        r = self.c.get(f"/api/v1/employees/{self.emp.id}")
        self.assertNotIn("allergies", r.data)
        self.assertNotIn("blood_group", r.data)

    def test_symptoms_stay_off_the_audit_trail(self):
        from .models import AuditLog
        self.report(symptoms="bloody stools, severe pain")
        for log in AuditLog.objects.filter(event__startswith="HEALTH"):
            self.assertNotIn("bloody", str(log.detail))

    def test_the_case_has_a_discussion_thread(self):
        cid = self.report().data["id"]
        r = self.c.post(f"/api/v1/discussion/health:{cid}",
                        {"body": "PM, boat at 4?", "to": [self.pm.id]},
                        format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["about"]["doc_type"], "HLT")
        self.c.force_authenticate(self.far)
        self.assertEqual(self.c.get(f"/api/v1/discussion/health:{cid}")
                         .status_code, 404)

    def test_the_monthly_log_prints(self):
        self.report()
        today = date.today()
        r = self.c.get(f"/api/v1/health/log.pdf?site={self.site.id}"
                       f"&year={today.year}&month={today.month}")
        self.assertIn(r.status_code, (200, 503))
        if r.status_code == 200:
            self.assertEqual(r["Content-Type"], "application/pdf")

    def test_the_plan_and_the_daily_summary(self):
        self.c.force_authenticate(self.pm)
        r = self.c.put(f"/api/v1/health/plan/{self.site.id}", {
            "focal_point_id": self.sa.id, "hotline": "+960 777 0000",
            "nearest_health_centre": "Noonu Manadhoo health centre",
            "travel_time": "40 min by speedboat",
            "male_hospitals": "IGMH / ADK"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["focal_point"], self.sa.full_name)
        self.c.force_authenticate(self.sa)
        self.assertEqual(self.c.put(f"/api/v1/health/plan/{self.site.id}",
                                    {"hotline": "x"}, format="json")
                         .status_code, 403)
        self.report()
        sent = health.daily_summary()
        self.assertGreaterEqual(sent, 3)      # PM, Director, HR
        self.assertTrue(Notification.objects.filter(
            recipient=self.pm, title__startswith="Health today").exists())


class IncidentLinkTests(HealthBase):
    def test_an_injured_employee_on_an_incident_gets_a_case(self):
        r = self.c.post("/api/v1/hse/incidents", {
            "site_id": self.site.id, "kind": "FIRST_AID", "severity": "LOW",
            "occurred_at": timezone.now().isoformat(),
            "description": "Cut hand on rebar", "location": "Villa 2",
            "people": [{"employee_id": self.emp.id, "involvement": "INJURED",
                        "injury": "cut", "body_part": "left hand"}]},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        case = HealthCase.objects.get()
        self.assertEqual((case.complaint, case.source), ("INJURY", "INCIDENT"))
        self.assertEqual(case.incident.document.ref, r.data["ref"])
        self.assertIn("left hand", case.symptoms)


