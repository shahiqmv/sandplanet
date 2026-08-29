"""Programme baseline, actuals and slippage (owner 2026-08-29).

A revision used to delete the previous activities outright, so the plan the
company committed to was destroyed every time one arrived, and there was no
record of when work actually happened."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from . import programme
from .models import ProgrammeActivity, Project, Site, User
from .tests import make_user


class BaselineTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="BAS", name="Baseline site",
                                        status=Site.Status.ACTIVE)
        self.user = make_user("pm_base", User.Role.PM, site=self.site)
        self.project = Project.objects.create(
            site=self.site, code="P1", title="Villas", status="ACTIVE")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self._activity("Groundworks", date(2026, 1, 1), date(2026, 1, 31), 1)
        self._activity("Blockwork", date(2026, 2, 1), date(2026, 2, 28), 2)

    def _activity(self, name, start, finish, order, **kw):
        return ProgrammeActivity.objects.create(
            project=self.project, sort_order=order, name=name,
            start=start, finish=finish, duration_days=30, **kw)

    def _url(self):
        return f"/api/v1/projects/{self.project.id}/programme/baseline"

    def test_capturing_a_baseline_freezes_the_dates(self):
        r = self.client.post(self._url(), {}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["rev_no"], 0)
        self.assertEqual(r.data["activities"], 2)
        base = programme.current_baseline(self.project)
        self.assertEqual(base.activities.get(name="Blockwork").finish,
                         date(2026, 2, 28))

    def test_a_revision_no_longer_destroys_the_baseline(self):
        """The whole point: re-importing a revised programme must leave what
        we committed to intact."""
        self.client.post(self._url(), {}, format="json")
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/programme",
            {"replace": True, "activities": [
                {"name": "Groundworks", "start": "2026-01-15",
                 "finish": "2026-02-20", "duration_days": 36},
                {"name": "Blockwork", "start": "2026-02-21",
                 "finish": "2026-04-10", "duration_days": 48},
                {"name": "Roofing", "start": "2026-04-11",
                 "finish": "2026-05-01", "duration_days": 20},
            ]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        base = programme.current_baseline(self.project)
        self.assertEqual(base.activities.get(name="Blockwork").finish,
                         date(2026, 2, 28))          # untouched
        self.assertEqual(self.project.activities.get(name="Blockwork").finish,
                         date(2026, 4, 10))          # the new plan

    def test_actuals_and_progress_survive_a_revision(self):
        act = self.project.activities.get(name="Groundworks")
        act.actual_start = date(2026, 1, 5)
        act.progress = 40
        act.save()
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/programme",
            {"replace": True, "activities": [
                {"name": "GROUNDWORKS  ", "start": "2026-01-15",
                 "finish": "2026-02-20", "duration_days": 36},
            ]}, format="json")
        self.assertEqual(r.data["history_carried"], 1)
        fresh = self.project.activities.get()
        self.assertEqual(fresh.actual_start, date(2026, 1, 5))
        self.assertEqual(fresh.progress, 40)

    def test_comparison_reports_slippage_against_the_baseline(self):
        self.client.post(self._url(), {}, format="json")
        act = self.project.activities.get(name="Blockwork")
        act.actual_finish = date(2026, 3, 15)        # 15 days late
        act.save()
        data = self.client.get(self._url()).data
        row = next(r for r in data["rows"] if r["name"] == "Blockwork")
        self.assertEqual(row["days_late"], 15)
        self.assertTrue(row["in_baseline"])
        self.assertEqual(data["summary"]["slipped"], 1)

    def test_an_activity_added_after_the_baseline_is_flagged(self):
        self.client.post(self._url(), {}, format="json")
        self._activity("Extra works", date(2026, 3, 1), date(2026, 3, 20), 3)
        data = self.client.get(self._url()).data
        row = next(r for r in data["rows"] if r["name"] == "Extra works")
        self.assertFalse(row["in_baseline"])
        self.assertEqual(data["summary"]["not_in_baseline"], 1)

    def test_rebaselining_needs_a_reason_and_keeps_the_old_one(self):
        self.client.post(self._url(), {}, format="json")
        bad = self.client.post(self._url(), {}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("say why", bad.data["detail"])
        ok = self.client.post(self._url(),
                              {"reason": "EOT 1 awarded", "label": "EOT 1"},
                              format="json")
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(ok.data["rev_no"], 1)
        self.assertEqual(self.project.baselines.count(), 2)
        old = self.project.baselines.get(rev_no=0)
        self.assertIsNotNone(old.superseded_at)
        self.assertFalse(old.is_current)

    def test_baseline_is_absent_until_captured(self):
        data = self.client.get(self._url()).data
        self.assertIsNone(data["baseline"])
        self.assertEqual(data["summary"]["not_in_baseline"], 2)


class ActualsFromDprTests(TestCase):
    """Actual dates come from the daily report, because nobody remembers to
    set an actual date and everybody files the DPR (owner 2026-08-29)."""

    def setUp(self):
        from .models import Document, DocumentRevision
        self.site = Site.objects.create(code="ACT", name="Actuals site",
                                        status=Site.Status.ACTIVE)
        self.user = make_user("pm_act", User.Role.PM, site=self.site)
        self.project = Project.objects.create(
            site=self.site, code="P1", title="Villas", status="ACTIVE")
        self.activity = ProgrammeActivity.objects.create(
            project=self.project, sort_order=1, name="Groundworks",
            start=date(2026, 1, 1), finish=date(2026, 1, 31))
        self.Document, self.Revision = Document, DocumentRevision

    def _dpr(self, day, pct):
        from .views_documents import _update_programme_progress
        doc = self.Document.objects.create(
            doc_type="DPR", ref=f"DPR-ACT-{day.day:03d}", site=self.site,
            doc_date=day, status="ISSUED", created_by=self.user)
        rev = self.Revision.objects.create(
            document=doc, rev_label="R0", created_by=self.user,
            payload={"work_done": [{"activity_id": self.activity.id,
                                    "progress_todate": pct}]})
        doc.current_revision = rev
        doc.save(update_fields=["current_revision"])
        _update_programme_progress(doc, self.user)
        self.activity.refresh_from_db()
        return doc

    def test_first_progress_records_the_actual_start(self):
        self._dpr(date(2026, 1, 8), 10)
        self.assertEqual(self.activity.actual_start, date(2026, 1, 8))
        self.assertIsNone(self.activity.actual_finish)

    def test_the_start_is_not_moved_by_later_reports(self):
        self._dpr(date(2026, 1, 8), 10)
        self._dpr(date(2026, 1, 20), 60)
        self.assertEqual(self.activity.actual_start, date(2026, 1, 8))

    def test_reaching_100_records_the_actual_finish(self):
        self._dpr(date(2026, 1, 8), 10)
        self._dpr(date(2026, 2, 14), 100)
        self.assertEqual(self.activity.actual_finish, date(2026, 2, 14))

    def test_a_later_correction_below_100_does_not_unfinish_the_work(self):
        self._dpr(date(2026, 1, 8), 100)
        self._dpr(date(2026, 1, 20), 90)
        self.assertEqual(self.activity.actual_finish, date(2026, 1, 8))
