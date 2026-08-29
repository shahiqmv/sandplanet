"""Contract & time — correspondence, notices, delay events, EOT.

There was no notice document of any kind, no RFI register, no delay log and no
time-bar clock: when a client claimed delay we had photographs but no evidence
chain (conformance audit 2026-08-28)."""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from .models import ProgrammeActivity, Project, Site, User
from .tests import make_user


class CorrespondenceTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="CT1", name="Contract site",
                                        status=Site.Status.ACTIVE)
        self.se = make_user("se_ct1", User.Role.SITE_ENGINEER, site=self.site)
        self.project = Project.objects.create(
            site=self.site, code="P1", title="Villas", status="ACTIVE",
            notice_period_days=28, rfi_response_days=7)
        self.client = APIClient()
        self.client.force_authenticate(self.se)

    def _log(self, **extra):
        body = {"site_id": self.site.id, "project_id": self.project.id,
                "kind": "RFI", "direction": "OUT",
                "subject": "Ceiling void clearance at grid B",
                "dated_on": str(date.today())}
        body.update(extra)
        return self.client.post("/api/v1/contract/correspondence", body,
                                format="json")

    def test_an_rfi_gets_its_reply_clock_from_the_contract(self):
        r = self._log()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["ref"].startswith("RFI-"))
        self.assertEqual(r.data["response_due"],
                         str(date.today() + timedelta(days=7)))

    def test_a_project_with_no_period_gets_no_invented_deadline(self):
        """Time bars are configuration. Guessing one would be worse than
        having none."""
        bare = Project.objects.create(site=self.site, code="P2",
                                      title="Bare", status="ACTIVE")
        r = self._log(project_id=bare.id)
        self.assertIsNone(r.data["response_due"])

    def test_a_notice_carries_its_time_bar_from_the_aware_date(self):
        aware = date.today() - timedelta(days=10)
        r = self._log(kind="NTC", direction="OUT", clause="20.1",
                      aware_on=str(aware),
                      subject="Notice of delay — late information")
        self.assertEqual(r.data["time_bar_on"],
                         str(aware + timedelta(days=28)))
        self.assertFalse(r.data["served_late"])

    def test_a_notice_served_after_its_bar_is_recorded_not_blocked(self):
        """The fact it went late is exactly what a reviewer needs to see."""
        aware = date.today() - timedelta(days=40)
        r = self._log(kind="NTC", direction="OUT", aware_on=str(aware),
                      subject="Late notice")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["served_late"])

    def test_something_needing_no_reply_closes_on_arrival(self):
        r = self._log(kind="LTR", direction="IN", response_required=False)
        self.assertEqual(r.data["status"], "CLOSED")
        self.assertIsNone(r.data["response_due"])

    def test_outstanding_lists_what_is_owed_worst_first(self):
        self._log(subject="Old one",
                  dated_on=str(date.today() - timedelta(days=30)))
        self._log(subject="New one")
        rows = self.client.get("/api/v1/contract/outstanding").data
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["subject"], "Old one")
        self.assertGreater(rows[0]["days_outstanding"], 0)

    def test_recording_the_answer_stops_the_clock(self):
        ref = self._log().data["ref"]
        r = self.client.post(
            f"/api/v1/contract/correspondence/{ref}/respond",
            {"responded_on": str(date.today()),
             "response_summary": "Clearance confirmed at 450mm."},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "ANSWERED")
        self.assertIsNone(r.data["days_outstanding"])


class DelayEventTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="CT2", name="Delay site",
                                        status=Site.Status.ACTIVE)
        self.se = make_user("se_ct2", User.Role.SITE_ENGINEER, site=self.site)
        self.pm = make_user("pm_ct2", User.Role.PM, site=self.site)
        self.project = Project.objects.create(
            site=self.site, code="P1", title="Villas", status="ACTIVE",
            notice_period_days=28)
        self.activity = ProgrammeActivity.objects.create(
            project=self.project, sort_order=1, name="Roof sheeting")
        self.client = APIClient()
        self.client.force_authenticate(self.se)

    def _delay(self, **extra):
        body = {"project_id": self.project.id,
                "title": "Ceiling detail not issued",
                "cause": "LATE_INFORMATION",
                "started_on": str(date.today() - timedelta(days=9)),
                "activity_ids": [self.activity.id]}
        body.update(extra)
        return self.client.post("/api/v1/contract/delays", body,
                                format="json")

    def test_a_delay_records_what_it_hit(self):
        r = self._delay()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["ref"].startswith("DLY-"))
        self.assertEqual(r.data["activity_names"], ["Roof sheeting"])
        self.assertEqual(r.data["duration"], 10)

    def test_it_cannot_end_before_it_started(self):
        r = self._delay(ended_on=str(date.today() - timedelta(days=20)))
        self.assertEqual(r.status_code, 400)

    def test_a_site_engineer_cannot_decide_whose_risk_it_is(self):
        """Whose risk a delay is, is a commercial position."""
        ref = self._delay().data["ref"]
        r = self.client.patch(f"/api/v1/contract/delays/{ref}",
                              {"responsibility": "EMPLOYER"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_a_pm_decides_and_the_summary_follows(self):
        ref = self._delay().data["ref"]
        self.client.force_authenticate(self.pm)
        r = self.client.patch(f"/api/v1/contract/delays/{ref}",
                              {"responsibility": "EMPLOYER",
                               "days_lost": 10}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        summary = self.client.get(
            f"/api/v1/projects/{self.project.id}/entitlement").data
        self.assertEqual(summary["days_by_responsibility"]["EMPLOYER"], 10)

    def test_employer_risk_without_a_notice_is_surfaced(self):
        """The exposure this module exists to find."""
        ref = self._delay().data["ref"]
        self.client.force_authenticate(self.pm)
        self.client.patch(f"/api/v1/contract/delays/{ref}",
                          {"responsibility": "EMPLOYER"}, format="json")
        summary = self.client.get(
            f"/api/v1/projects/{self.project.id}/entitlement").data
        self.assertEqual(summary["employer_risk_without_notice"], 1)

    def test_linking_the_notice_clears_the_exposure(self):
        notice = self.client.post("/api/v1/contract/correspondence", {
            "site_id": self.site.id, "project_id": self.project.id,
            "kind": "NTC", "direction": "OUT", "clause": "20.1",
            "subject": "Notice of delay"}, format="json").data
        ref = self._delay().data["ref"]
        self.client.force_authenticate(self.pm)
        self.client.patch(f"/api/v1/contract/delays/{ref}",
                          {"responsibility": "EMPLOYER",
                           "notice_id": notice["id"]}, format="json")
        summary = self.client.get(
            f"/api/v1/projects/{self.project.id}/entitlement").data
        self.assertEqual(summary["employer_risk_without_notice"], 0)


class EotTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="CT3", name="EOT site",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pm_ct3", User.Role.PM, site=self.site)
        self.se = make_user("se_ct3", User.Role.SITE_ENGINEER, site=self.site)
        self.project = Project.objects.create(
            site=self.site, code="P1", title="Villas", status="ACTIVE")
        ProgrammeActivity.objects.create(
            project=self.project, sort_order=1, name="Roof",
            start=date(2026, 1, 1), finish=date(2026, 2, 1))
        self.client = APIClient()
        self.client.force_authenticate(self.pm)
        self.event = self.client.post("/api/v1/contract/delays", {
            "project_id": self.project.id, "title": "Access withheld",
            "cause": "ACCESS",
            "started_on": str(date.today() - timedelta(days=14)),
            "ended_on": str(date.today() - timedelta(days=5)),
            "days_lost": 10}, format="json").data

    def _eot(self, **extra):
        body = {"project_id": self.project.id,
                "delay_event_ids": [self.event["id"]],
                "grounds": "Access to the villa was withheld for ten days."}
        body.update(extra)
        return self.client.post("/api/v1/contract/eots", body, format="json")

    def test_an_application_is_built_from_delay_events(self):
        r = self._eot()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["days_claimed"], 10)
        self.assertEqual(r.data["event_refs"], [self.event["ref"]])

    def test_an_application_with_no_events_is_refused(self):
        """A claim assembled from memory is the one that fails."""
        r = self._eot(delay_event_ids=[])
        self.assertEqual(r.status_code, 400)
        self.assertIn("delay events", r.data["detail"])

    def test_a_site_engineer_cannot_prepare_one(self):
        self.client.force_authenticate(self.se)
        self.assertEqual(self._eot().status_code, 403)

    def test_it_must_be_submitted_before_it_can_be_decided(self):
        ref = self._eot().data["ref"]
        r = self.client.post(f"/api/v1/contract/eots/{ref}/decide",
                             {"days_awarded": 10}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_more_days_awarded_than_claimed_is_refused(self):
        ref = self._eot().data["ref"]
        self.client.post(f"/api/v1/contract/eots/{ref}/submit")
        r = self.client.post(f"/api/v1/contract/eots/{ref}/decide",
                             {"days_awarded": 40}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("check the figure", r.data["detail"])

    def test_an_award_rebaselines_the_programme(self):
        """The payoff of a baseline that survives revision."""
        ref = self._eot().data["ref"]
        self.client.post(f"/api/v1/contract/eots/{ref}/submit")
        r = self.client.post(f"/api/v1/contract/eots/{ref}/decide",
                             {"days_awarded": 10,
                              "decision_note": "Granted in full."},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "AWARDED")
        self.assertEqual(self.project.baselines.count(), 1)
        base = self.project.baselines.first()
        self.assertIn(ref, base.label)
        self.assertIn("10 days awarded", base.reason)

    def test_a_rejection_awards_nothing_and_does_not_rebaseline(self):
        ref = self._eot().data["ref"]
        self.client.post(f"/api/v1/contract/eots/{ref}/submit")
        r = self.client.post(f"/api/v1/contract/eots/{ref}/decide",
                             {"days_awarded": 0,
                              "decision_note": "No entitlement."},
                             format="json")
        self.assertEqual(r.data["status"], "REJECTED")
        self.assertEqual(self.project.baselines.count(), 0)

    def test_a_partial_award_is_marked_as_such(self):
        ref = self._eot().data["ref"]
        self.client.post(f"/api/v1/contract/eots/{ref}/submit")
        r = self.client.post(f"/api/v1/contract/eots/{ref}/decide",
                             {"days_awarded": 4}, format="json")
        self.assertEqual(r.data["status"], "PARTIALLY_AWARDED")
