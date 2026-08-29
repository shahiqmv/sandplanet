"""HSE — the incident register and the corrective actions that follow.

Before this the app's whole safety functionality was one checkbox on the daily
report that notified nobody (conformance audit 2026-08-28)."""
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from . import hse
from .models import (CorrectiveAction, Document, DocumentRevision, Notification,
                     Project, SafetyIncident, Site, User)
from .tests import make_user


class IncidentTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="HSE", name="Safety site",
                                        status=Site.Status.ACTIVE)
        self.project = Project.objects.create(site=self.site, code="P1",
                                              title="Villas", status="ACTIVE")
        self.sa = make_user("sa_hse", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm_hse", User.Role.PM, site=self.site)
        self.director = make_user("dir_hse", User.Role.DIRECTOR)
        self.site.pm_history.create(pm_user=self.pm, from_date=date.today())
        self.client = APIClient()
        self.client.force_authenticate(self.sa)

    def _report(self, **extra):
        body = {"site_id": self.site.id, "kind": "NEAR_MISS",
                "severity": "LOW",
                "occurred_at": timezone.now().isoformat(),
                "description": "Scaffold board slipped, nobody underneath.",
                "location": "Villa 3 north face"}
        body.update(extra)
        return self.client.post("/api/v1/hse/incidents", body, format="json")

    def test_reporting_creates_a_numbered_record(self):
        r = self._report()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["ref"].startswith("INC-"))
        self.assertEqual(r.data["status"], "REPORTED")

    def test_description_is_required(self):
        r = self._report(description="")
        self.assertEqual(r.status_code, 400)

    def test_a_serious_incident_escalates_to_the_director(self):
        """The old checkbox notified nobody. This is the point of the module."""
        self._report(kind="LOST_TIME", severity="HIGH",
                     description="Fall from height, ankle fracture.")
        self.assertTrue(Notification.objects.filter(
            recipient=self.director).exists())

    def test_a_low_near_miss_does_not_wake_the_director(self):
        self._report()
        self.assertFalse(Notification.objects.filter(
            recipient=self.director).exists())

    def test_an_injury_cannot_be_closed_without_a_root_cause(self):
        ref = self._report(kind="LOST_TIME", severity="HIGH").data["ref"]
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/hse/incidents/{ref}/investigate")
        r = self.client.post(f"/api/v1/hse/incidents/{ref}/close")
        self.assertEqual(r.status_code, 400)
        self.assertIn("root cause", r.data["detail"])

    def test_it_closes_once_the_investigation_is_recorded(self):
        ref = self._report(kind="LOST_TIME").data["ref"]
        self.client.force_authenticate(self.pm)
        self.client.post(f"/api/v1/hse/incidents/{ref}/investigate")
        self.client.patch(f"/api/v1/hse/incidents/{ref}",
                          {"root_cause": "Board not tied."}, format="json")
        r = self.client.post(f"/api/v1/hse/incidents/{ref}/close")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "CLOSED")

    def test_a_site_admin_cannot_close_an_incident(self):
        ref = self._report().data["ref"]
        r = self.client.post(f"/api/v1/hse/incidents/{ref}/close")
        self.assertEqual(r.status_code, 403)

    def test_another_site_cannot_see_it(self):
        ref = self._report().data["ref"]
        other_site = Site.objects.create(code="OTH", name="Other",
                                         status=Site.Status.ACTIVE)
        outsider = make_user("sa_other", User.Role.SITE_ADMIN,
                             site=other_site)
        self.client.force_authenticate(outsider)
        self.assertEqual(
            self.client.get(f"/api/v1/hse/incidents/{ref}").status_code, 404)


class CorrectiveActionTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="CAP", name="Action site",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pm_cap", User.Role.PM, site=self.site)
        self.sa = make_user("sa_cap", User.Role.SITE_ADMIN, site=self.site)
        self.client = APIClient()
        self.client.force_authenticate(self.pm)
        r = self.client.post("/api/v1/hse/incidents", {
            "site_id": self.site.id, "kind": "MEDICAL", "severity": "HIGH",
            "occurred_at": timezone.now().isoformat(),
            "description": "Cut hand on rebar."}, format="json")
        self.ref = r.data["ref"]
        self.client.post(f"/api/v1/hse/incidents/{self.ref}/investigate")

    def _raise(self, **extra):
        body = {"description": "Cap all protruding rebar.",
                "owner_id": self.sa.id,
                "due_date": str(date.today() + timedelta(days=7))}
        body.update(extra)
        return self.client.post(
            f"/api/v1/hse/incidents/{self.ref}/actions", body, format="json")

    def test_raising_an_action_notifies_its_owner(self):
        r = self._raise()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(Notification.objects.filter(recipient=self.sa)
                        .exists())

    def test_an_action_moves_the_incident_to_actions_open(self):
        self._raise()
        self.assertEqual(Document.objects.get(ref=self.ref).status,
                         "ACTIONS_OPEN")

    def test_an_incident_cannot_close_with_an_open_action(self):
        self._raise()
        self.client.patch(f"/api/v1/hse/incidents/{self.ref}",
                          {"root_cause": "Rebar left uncapped."},
                          format="json")
        r = self.client.post(f"/api/v1/hse/incidents/{self.ref}/close")
        self.assertEqual(r.status_code, 400)
        self.assertIn("still open", r.data["detail"])

    def test_the_doer_cannot_verify_their_own_action(self):
        """An action verified by the person who did it is an action nobody
        checked."""
        action_id = self._raise().data["id"]
        self.client.force_authenticate(self.sa)
        self.client.post(f"/api/v1/hse/actions/{action_id}/complete",
                         {"note": "Caps fitted."}, format="json")
        self.client.force_authenticate(self.pm)
        # PM completes on the owner's behalf, then tries to verify
        CorrectiveAction.objects.filter(pk=action_id).update(
            completed_by=self.pm)
        r = self.client.post(f"/api/v1/hse/actions/{action_id}/verify")
        self.assertEqual(r.status_code, 400)
        self.assertIn("other than the person", r.data["detail"])

    def test_verified_action_lets_the_incident_close(self):
        action_id = self._raise().data["id"]
        self.client.force_authenticate(self.sa)
        self.client.post(f"/api/v1/hse/actions/{action_id}/complete",
                         {"note": "Caps fitted."}, format="json")
        self.client.force_authenticate(self.pm)
        self.assertEqual(
            self.client.post(f"/api/v1/hse/actions/{action_id}/verify")
            .status_code, 200)
        self.client.patch(f"/api/v1/hse/incidents/{self.ref}",
                          {"root_cause": "Rebar left uncapped."},
                          format="json")
        self.assertEqual(
            self.client.post(f"/api/v1/hse/incidents/{self.ref}/close")
            .status_code, 200)

    def test_overdue_actions_are_listed(self):
        self._raise(due_date=str(date.today() - timedelta(days=3)))
        rows = self.client.get("/api/v1/hse/actions?overdue=1").data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["days_overdue"], 3)


class DprChecklistTests(TestCase):
    """The daily report's safety checkbox used to fail OPEN — it notified
    nobody and left nothing countable behind."""

    def setUp(self):
        self.site = Site.objects.create(code="DPR", name="DPR site",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pm_dpr", User.Role.PM, site=self.site)

    def _issue_dpr(self, safety):
        from .views_documents import _raise_incident_from_dpr
        doc = Document.objects.create(
            doc_type="DPR", ref="DPR-DPR-001", site=self.site,
            doc_date=date.today(), status="ISSUED", created_by=self.pm)
        rev = DocumentRevision.objects.create(
            document=doc, rev_label="R0", created_by=self.pm,
            payload={"safety": safety})
        doc.current_revision = rev
        doc.save(update_fields=["current_revision"])
        return doc, _raise_incident_from_dpr(doc, self.pm)

    def test_ticking_the_box_opens_a_real_incident(self):
        doc, inc = self._issue_dpr({"incident": True,
                                    "details": "Man struck by falling plank."})
        self.assertIsNotNone(inc)
        self.assertEqual(inc.status, "REPORTED")
        self.assertIn("falling plank",
                      SafetyIncident.objects.get().description)
        self.assertIn(doc.ref, SafetyIncident.objects.get().description)

    def test_no_tick_raises_nothing(self):
        _, inc = self._issue_dpr({"incident": False, "details": ""})
        self.assertIsNone(inc)
        self.assertFalse(SafetyIncident.objects.exists())

    def test_a_malformed_safety_block_raises_nothing_and_does_not_crash(self):
        """It used to read as 'no accident'. It still cannot invent one — but
        it must not take the DPR down either."""
        _, inc = self._issue_dpr("not a dict")
        self.assertIsNone(inc)

    def test_re_issuing_does_not_duplicate_the_incident(self):
        doc, first = self._issue_dpr({"incident": True, "details": "Slip."})
        from .views_documents import _raise_incident_from_dpr
        again = _raise_incident_from_dpr(doc, self.pm)
        self.assertEqual(SafetyIncident.objects.count(), 1)
        self.assertEqual(again.ref, first.ref)


class StatisticsTests(TestCase):
    def test_the_numbers_an_hse_audit_asks_for(self):
        site = Site.objects.create(code="ST8", name="Stats",
                                   status=Site.Status.ACTIVE)
        user = make_user("pm_st8", User.Role.PM, site=site)
        for kind in ("NEAR_MISS", "NEAR_MISS", "LOST_TIME"):
            hse.create_incident(site=site, user=user, data={
                "kind": kind, "severity": "LOW",
                "occurred_at": timezone.now(),
                "description": "x"})
        data = hse.statistics([site.id])
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["near_misses"], 2)
        self.assertEqual(data["lost_time"], 1)
        self.assertEqual(data["injuries"], 1)
        self.assertEqual(data["open"], 3)


class PeopleRecordTests(TestCase):
    """Toolbox talks, inductions, training and PPE — the records an HSE
    officer already keeps on the bigger sites (owner 2026-08-29)."""

    def setUp(self):
        from .models import Employee
        self.site = Site.objects.create(code="PPL", name="People site",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pm_ppl", User.Role.PM, site=self.site)
        self.client = APIClient()
        self.client.force_authenticate(self.pm)
        self.workers = []
        for i in range(3):
            e = Employee.objects.create(emp_no=f"E{i:03d}",
                                        full_name=f"Worker {i}")
            e.site_allocations.create(site=self.site, from_date=date.today())
            self.workers.append(e)

    def _talk(self, **extra):
        body = {"site_id": self.site.id, "topic": "Working at height",
                "delivered_at": timezone.now().isoformat(),
                "duration_min": 15,
                "attendees": [{"employee_id": w.id} for w in self.workers]}
        body.update(extra)
        return self.client.post("/api/v1/hse/toolbox-talks", body,
                                format="json")

    def test_a_talk_records_who_was_there(self):
        r = self._talk()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["ref"].startswith("TBT-"))
        self.assertEqual(r.data["attendee_count"], 3)

    def test_a_talk_needs_a_topic(self):
        self.assertEqual(self._talk(topic="").status_code, 400)

    def test_the_same_worker_is_not_counted_twice(self):
        w = self.workers[0]
        r = self._talk(attendees=[{"employee_id": w.id},
                                  {"employee_id": w.id}])
        self.assertEqual(r.data["attendee_count"], 1)

    def test_a_subcontractors_man_can_attend_without_being_an_employee(self):
        r = self._talk(attendees=[{"name": "Ali", "employer": "ABC Sub"}])
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["attendees"][0]["display_name"], "Ali")

    def test_the_attendance_register_supplies_the_attendee_list(self):
        """Asking for the same list twice is how a hundred checkboxes become
        nobody's job."""
        from .models import Attendance
        today = date.today()
        for w in self.workers[:2]:
            Attendance.objects.create(employee=w, site=self.site, day=today,
                                      remark="PRESENT")
        Attendance.objects.create(employee=self.workers[2], site=self.site,
                                  day=today, remark="ABSENT")
        rows = self.client.get(
            f"/api/v1/hse/present?site={self.site.id}&day={today}").data
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["emp_no"] for r in rows}, {"E000", "E001"})

    def test_induction_is_recorded_against_the_worker_and_site(self):
        r = self.client.post("/api/v1/hse/inductions", {
            "site_id": self.site.id, "employee_id": self.workers[0].id,
            "inducted_on": str(date.today()),
            "topics": "Site rules, PPE, emergency muster"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["emp_no"], "E000")

    def test_training_with_an_expiry_is_listed_as_expiring(self):
        self.client.post("/api/v1/hse/training", {
            "employee_id": self.workers[0].id, "category": "PLANT",
            "title": "Excavator operator",
            "expires_on": str(date.today() + timedelta(days=20))},
            format="json")
        rows = self.client.get("/api/v1/hse/training?expiring=30").data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["days_to_expiry"], 20)

    def test_ppe_is_kept_per_issue_not_as_a_balance(self):
        for _ in range(2):
            self.client.post("/api/v1/hse/ppe", {
                "site_id": self.site.id, "employee_id": self.workers[0].id,
                "item": "Safety harness", "qty": 1,
                "issued_on": str(date.today())}, format="json")
        rows = self.client.get(
            f"/api/v1/hse/ppe?employee={self.workers[0].id}").data
        self.assertEqual(len(rows), 2)

    def test_another_site_cannot_read_the_records(self):
        self._talk()
        other = Site.objects.create(code="OT2", name="Other",
                                    status=Site.Status.ACTIVE)
        outsider = make_user("sa_ot2", User.Role.SITE_ADMIN, site=other)
        self.client.force_authenticate(outsider)
        self.assertEqual(len(self.client.get("/api/v1/hse/toolbox-talks").data),
                         0)


class TrainingExpiryTests(TestCase):
    def setUp(self):
        from .models import Employee
        self.site = Site.objects.create(code="TRN", name="Training site",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pm_trn", User.Role.PM, site=self.site)
        self.site.pm_history.create(pm_user=self.pm, from_date=date.today())
        self.emp = Employee.objects.create(emp_no="T001", full_name="Driver")
        self.emp.site_allocations.create(site=self.site,
                                         from_date=date.today())

    def _record(self, days):
        from .models import TrainingRecord
        return TrainingRecord.objects.create(
            employee=self.emp, category="PLANT", title="Excavator",
            expires_on=date.today() + timedelta(days=days),
            recorded_by=self.pm)

    def test_an_expiring_ticket_alerts_the_pm(self):
        self._record(20)
        self.assertEqual(hse.sweep_training_expiry(), 1)
        self.assertTrue(Notification.objects.filter(recipient=self.pm)
                        .exists())

    def test_the_same_reminder_does_not_fire_twice(self):
        self._record(20)
        hse.sweep_training_expiry()
        self.assertEqual(hse.sweep_training_expiry(), 0)

    def test_it_re_fires_as_the_date_gets_closer(self):
        record = self._record(20)
        hse.sweep_training_expiry()
        record.expires_on = date.today() + timedelta(days=3)
        record.save(update_fields=["expires_on"])
        self.assertEqual(hse.sweep_training_expiry(), 1)

    def test_training_far_out_is_left_alone(self):
        self._record(200)
        self.assertEqual(hse.sweep_training_expiry(), 0)
