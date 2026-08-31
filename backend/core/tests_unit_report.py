"""The weekly unit-progress report.

The board keeps only where a unit stands now, so "what moved this week" needs
history — UnitProgressEvent, written as each figure is reported. Reconstructing
it from DPRs was the obvious alternative and does not work: of 106 live
figures on 17POOL, 104 were typed on the board by hand (owner 2026-08-31).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from . import units as svc
from .models import (Project, ProjectUnit, Site, UnitProgressEvent, UnitStage,
                     User)
from .tests import make_user
from .unit_report import build, week_window


class UnitReportTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="UPR", name="Unit site",
                                        status=Site.Status.ACTIVE)
        self.project = Project.objects.create(
            site=self.site, code="POOLS", title="17 Overwater pools",
            status="ACTIVE")
        self.s1 = UnitStage.objects.create(project=self.project,
                                           name="Columns", sort_order=1,
                                           weight=1)
        self.s2 = UnitStage.objects.create(project=self.project,
                                           name="Finishes", sort_order=2,
                                           weight=1)
        self.units = [ProjectUnit.objects.create(project=self.project,
                                                 ref=f"V{200 + i}")
                      for i in range(3)]
        self.pm = make_user("pm_upr", User.Role.PM, site=self.site)
        self.client = APIClient()
        self.client.force_authenticate(self.pm)
        self.today = date.today()

    def _report(self, on=None, pct=50, unit=0, stage=None):
        svc.report_progress(self.units[unit], stage or self.s1, pct,
                            on=on or self.today, actor=self.pm)

    # ---- history ---------------------------------------------------------

    def test_reporting_progress_writes_history(self):
        self._report(pct=40)
        e = UnitProgressEvent.objects.get()
        self.assertEqual(e.percent, Decimal("40.00"))
        self.assertEqual(e.previous, Decimal("0.00"))
        self.assertEqual(e.on, self.today)

    def test_an_unchanged_figure_does_not_pile_up_events(self):
        """A stage re-confirmed daily must not fill the table."""
        self._report(pct=40)
        self._report(pct=40)
        self._report(pct=40)
        self.assertEqual(UnitProgressEvent.objects.count(), 1)

    def test_a_correction_is_a_second_event_not_an_edit(self):
        """A client report that quietly rewrites last week's number is worse
        than one that shows the correction."""
        self._report(pct=40)
        self._report(pct=35)
        self.assertEqual(UnitProgressEvent.objects.count(), 2)
        last = UnitProgressEvent.objects.order_by("id").last()
        self.assertEqual(last.previous, Decimal("40.00"))
        self.assertEqual(last.percent, Decimal("35.00"))

    # ---- the week --------------------------------------------------------

    def test_a_midweek_day_gives_the_week_so_far(self):
        """Monday 31 August sits in the week that began Saturday 29th — not
        a rolling seven days back to the Tuesday before."""
        start, end = week_window(date(2026, 8, 31))
        self.assertEqual(start, date(2026, 8, 29))
        self.assertEqual(start.strftime("%A"), "Saturday")
        self.assertLessEqual(end, date(2026, 8, 31))

    def test_movement_is_measured_from_the_start_of_the_week(self):
        self._report(on=self.today - timedelta(days=20), pct=20)
        self._report(on=self.today - timedelta(days=2), pct=60)
        r = build(self.project)
        row = [x for x in r["rows"] if x["ref"] == "V200"][0]
        # Two equal stages: 20% of one stage is 10% of the unit, 60% is 30%.
        self.assertEqual(row["was"], 10.0)
        self.assertEqual(row["now"], 30.0)
        self.assertEqual(row["moved"], 20.0)

    def test_work_before_the_week_is_not_counted_as_this_weeks(self):
        self._report(on=self.today - timedelta(days=30), pct=80)
        r = build(self.project)
        row = [x for x in r["rows"] if x["ref"] == "V200"][0]
        self.assertEqual(row["moved"], 0.0)
        self.assertEqual(row["now"], row["was"])

    def test_a_unit_with_no_history_shows_no_movement(self):
        """History started after the work did. Showing a jump from zero
        would credit this week with months of work."""
        from .models import UnitStageProgress

        # Straight onto the board, with no event behind it — the state every
        # unit was in the day the history table was created.
        UnitStageProgress.objects.create(unit=self.units[1], stage=self.s1,
                                         percent=Decimal("70"))
        svc.recalc(self.units[1])
        self.units[1].refresh_from_db()
        r = build(self.project)
        row = [x for x in r["rows"] if x["ref"] == "V201"][0]
        self.assertEqual(row["now"], 35.0)
        self.assertEqual(row["moved"], 0.0)

    def test_the_summary_counts_what_moved(self):
        self._report(on=self.today - timedelta(days=1), pct=50, unit=0)
        self._report(on=self.today - timedelta(days=1), pct=30, unit=1)
        s = build(self.project)["summary"]
        self.assertEqual(s["units"], 3)
        self.assertEqual(s["moved_count"], 2)
        self.assertEqual(s["still_count"], 1)
        self.assertGreater(s["overall_moved"], 0)

    # ---- charts and the PDF ---------------------------------------------

    def test_the_charts_are_svg_not_a_script(self):
        """WeasyPrint runs no JavaScript, so a chart library would render an
        empty box."""
        self._report(pct=50)
        r = build(self.project)
        self.assertIn("<svg", r["bar_chart"])
        self.assertIn("<svg", r["milestone_chart"])
        self.assertNotIn("<script", r["bar_chart"])

    def test_every_unit_appears_on_the_chart(self):
        r = build(self.project)
        for u in self.units:
            self.assertIn(u.ref, r["bar_chart"])

    def test_the_pdf_renders(self):
        self._report(pct=50)
        r = self.client.get(
            f"/api/v1/projects/{self.project.id}/units/weekly.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")

    def test_an_earlier_week_can_be_reported(self):
        r = self.client.get(
            f"/api/v1/projects/{self.project.id}/units/weekly.pdf"
            "?week_ending=2026-08-24")
        self.assertEqual(r.status_code, 200)

    def test_a_bad_date_is_refused(self):
        r = self.client.get(
            f"/api/v1/projects/{self.project.id}/units/weekly.pdf"
            "?week_ending=last-tuesday")
        self.assertEqual(r.status_code, 400)

    def test_a_project_outside_my_sites_is_not_found(self):
        other = Site.objects.create(code="OTH", name="Other",
                                    status=Site.Status.ACTIVE)
        theirs = Project.objects.create(site=other, code="X", title="X",
                                        status="ACTIVE")
        r = self.client.get(
            f"/api/v1/projects/{theirs.id}/units/weekly.pdf")
        self.assertEqual(r.status_code, 404)

    def test_the_report_agrees_with_the_board(self):
        """The client reads both. Two ways of averaging the same numbers is
        how a PDF says 30% while the portal says 28% (owner 2026-08-31)."""
        self._report(pct=80, unit=0, stage=self.s1)
        self._report(pct=40, unit=0, stage=self.s2)
        self._report(pct=25, unit=1, stage=self.s1)

        board = svc.board(self.project)
        by_ref = {row["ref"]: row for row in board["units"]}

        report = build(self.project)
        # The headline figure too, not just the rows.
        self.assertEqual(report["summary"]["overall_now"],
                         round(float(board["overall_percent"]), 1))
        self.assertEqual(report["summary"]["units"], board["unit_count"])
        self.assertEqual(report["summary"]["complete"], board["complete"])

        for row in report["rows"]:
            b = by_ref[row["ref"]]
            self.assertEqual(row["now"], round(float(b["percent"]), 1),
                             f'{row["ref"]} percent')
            self.assertEqual(row["milestone"], b["current_stage"] or "Not started",
                             f'{row["ref"]} milestone')

    def test_the_milestone_is_what_is_next_not_what_was_touched(self):
        """A later stage often starts before an earlier one finishes."""
        self._report(pct=50, unit=0, stage=self.s1)   # Columns, unfinished
        self._report(pct=90, unit=0, stage=self.s2)   # Finishes, further on
        row = [r for r in build(self.project)["rows"] if r["ref"] == "V200"][0]
        self.assertEqual(row["milestone"], "Columns")

    def test_the_week_runs_saturday_to_friday(self):
        """Maldives, not Monday — and the site working week is Sat–Thu with
        Friday the rest day (owner 2026-08-31)."""
        from .unit_report import week_is_complete

        start, end = week_window(date(2026, 8, 28))       # a Friday
        self.assertEqual(start.strftime("%A"), "Saturday")
        self.assertEqual(end.strftime("%A"), "Friday")
        self.assertEqual((start, end), (date(2026, 8, 22), date(2026, 8, 28)))
        self.assertTrue(week_is_complete(start, end))

    def test_any_day_lands_in_its_own_saturday_week(self):
        for day, sat in ((date(2026, 8, 29), date(2026, 8, 29)),   # Sat
                         (date(2026, 8, 31), date(2026, 8, 29)),   # Mon
                         (date(2026, 9, 3), date(2026, 8, 29)),    # Thu
                         (date(2026, 9, 4), date(2026, 8, 29))):   # Fri
            self.assertEqual(week_window(day)[0], sat, day.strftime("%A"))

    def test_a_report_never_covers_days_that_have_not_happened(self):
        from django.utils import timezone

        from .unit_report import week_is_complete

        start, end = week_window()
        self.assertLessEqual(end, timezone.localdate())
        # Mid-week it is a week to date, and says so.
        if end < start + timedelta(days=6):
            self.assertFalse(week_is_complete(start, end))
