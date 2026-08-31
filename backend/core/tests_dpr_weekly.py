"""The weekly site report, rolled up from the daily ones.

The client asks for it every week and the sites have been typing it out by
hand from figures already in the system (owner 2026-08-31). Nothing in it is
a new fact: every number is read from that week's issued DPRs, so the weekly
and the dailies cannot disagree.
"""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from . import dpr_weekly as wk
from .models import Document, DocumentRevision, ManpowerCategory, Project, Site, User
from .tests import make_user


class DprWeeklyTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="WKY", name="Weekly site",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pm_wky", User.Role.PM, site=self.site)
        self.mason = ManpowerCategory.objects.create(
            name="Mason", list_type="DPR", grp="LABOUR", sort_order=2)
        self.eng = ManpowerCategory.objects.create(
            name="Site Engineer", list_type="DPR", grp="STAFF", sort_order=1)
        self.client = APIClient()
        self.client.force_authenticate(self.pm)
        self.sat = date(2026, 8, 22)          # a Saturday

    def _dpr(self, day, payload, status="VERIFIED", ref=None):
        doc = Document.objects.create(
            doc_type="DPR", ref=ref or f"DPR-WKY-{day.day:03d}",
            site=self.site, status=status, doc_date=day, created_by=self.pm)
        rev = DocumentRevision.objects.create(document=doc, rev_label="R0",
                                              payload=payload,
                                              created_by=self.pm)
        doc.current_revision = rev
        doc.save(update_fields=["current_revision"])
        return doc

    def _week(self, **kw):
        return wk.build(self.site, on=self.sat + timedelta(days=6), **kw)

    # ---- the window and coverage ----------------------------------------

    def test_the_week_is_saturday_to_friday(self):
        start, end = wk.week_window(date(2026, 8, 26))    # a Wednesday
        self.assertEqual((start, end), (date(2026, 8, 22), date(2026, 8, 28)))
        self.assertEqual(start.strftime("%A"), "Saturday")

    def test_a_missing_day_is_reported_not_skipped(self):
        """A week that quietly averages five days as though it were seven
        flatters the site, and the client is certain to notice."""
        for i in (0, 1, 2):
            self._dpr(self.sat + timedelta(days=i), {"manpower": {}})
        r = self._week()
        self.assertEqual(r["reported"], 3)
        self.assertEqual(r["expected"], 7)
        self.assertEqual([d["weekday"] for d in r["missing"]],
                         ["Tue", "Wed", "Thu", "Fri"])

    def test_a_draft_is_not_a_report(self):
        self._dpr(self.sat, {"manpower": {}}, status="DRAFT")
        self.assertEqual(self._week()["reported"], 0)

    # ---- manpower --------------------------------------------------------

    def test_manpower_totals_the_week(self):
        for i, n in enumerate((10, 12, 8)):
            self._dpr(self.sat + timedelta(days=i),
                      {"manpower": {str(self.mason.id): n,
                                    str(self.eng.id): 2}})
        mp = self._week()["manpower"]
        self.assertEqual(mp["man_days"], 10 + 12 + 8 + 6)
        self.assertEqual(mp["peak"], 14)
        self.assertEqual(mp["peak_on"], self.sat + timedelta(days=1))
        self.assertEqual(mp["average"], 12.0)

    def test_manpower_is_broken_down_by_trade(self):
        self._dpr(self.sat, {"manpower": {str(self.mason.id): 10,
                                          str(self.eng.id): 2}})
        rows = {r["name"]: r for r in self._week()["manpower"]["rows"]}
        self.assertEqual(rows["Mason"]["total"], 10)
        self.assertEqual(rows["Site Engineer"]["total"], 2)
        # Grouped the same way the daily DPR groups them, so the weekly and
        # the dailies read alike, and one cell per day of the week.
        names = [r["name"] for r in self._week()["manpower"]["rows"]]
        self.assertEqual(names, ["Mason", "Site Engineer"])
        self.assertEqual(len(self._week()["manpower"]["rows"][0]["cells"]), 7)

    def test_an_unknown_category_id_is_ignored_not_crashed_on(self):
        self._dpr(self.sat, {"manpower": {"999999": 5,
                                          str(self.mason.id): 3}})
        self.assertEqual(self._week()["manpower"]["man_days"], 3)

    # ---- work done -------------------------------------------------------

    def test_a_repeated_activity_is_one_line_with_its_days(self):
        """A client reading the report wants the shape of the period; the
        dailies are there for the detail."""
        for i in range(3):
            self._dpr(self.sat + timedelta(days=i), {"work_done": [
                {"trade": "Concrete", "activity": "Column pour",
                 "location": "V211"}]}, ref=f"DPR-R-{i}")
        blocks = self._week()["work_done"]
        self.assertEqual(len(blocks), 1)
        item = blocks[0]["items"][0]
        self.assertEqual(item["day_count"], 3)
        self.assertEqual(item["first"], self.sat)
        self.assertEqual(item["last"], self.sat + timedelta(days=2))

    def test_a_project_filter_narrows_the_activities(self):
        project, _ = Project.objects.get_or_create(
            site=self.site, code="P1",
            defaults={"title": "One", "status": "ACTIVE"})
        self._dpr(self.sat, {"work_done": [
            {"trade": "A", "activity": "Mine", "project": "P1"},
            {"trade": "B", "activity": "Theirs", "project": "P2"}]})
        acts = [i["activity"] for b in self._week(project=project)["work_done"]
                for i in b["items"]]
        self.assertEqual(acts, ["Mine"])

    # ---- weather, plant, materials --------------------------------------

    def test_rain_hours_add_up_across_the_week(self):
        self._dpr(self.sat, {"rain_from": "12:30", "rain_to": "14:00",
                             "weather_am": "Sunny", "weather_pm": "Rainy"})
        self._dpr(self.sat + timedelta(days=1),
                  {"rain_from": "09:00", "rain_to": "10:30"})
        w = self._week()["weather"]
        self.assertEqual(w["rain_hours"], 3.0)
        self.assertEqual(w["rain_days"], 2)
        self.assertIn(("Sunny", 1), w["halves"])

    def test_rain_past_midnight_is_not_negative(self):
        self._dpr(self.sat, {"rain_from": "23:00", "rain_to": "01:00"})
        self.assertEqual(self._week()["weather"]["rain_hours"], 2.0)

    def test_plant_shows_the_most_any_day_carried(self):
        """The daily return counts what stood on site, not what arrived."""
        self._dpr(self.sat, {"machinery": [{"item": "Excavator", "nos": 2}]})
        self._dpr(self.sat + timedelta(days=1),
                  {"machinery": [{"item": "Excavator", "nos": 3}]})
        self.assertEqual(self._week()["machinery"][0]["nos"], 3)

    # ---- exceptions ------------------------------------------------------

    def test_time_lost_and_safety_are_gathered(self):
        self._dpr(self.sat, {"work_time_lost": "3",
                             "time_lost_cause": "Rain",
                             "safety": {"incident": True,
                                        "details": "Minor cut"}})
        r = self._week()
        self.assertEqual(r["time_lost"]["hours"], 3.0)
        self.assertEqual(r["safety"][0]["details"], "Minor cut")

    def test_a_clean_week_reports_nothing_rather_than_a_blank(self):
        self._dpr(self.sat, {"safety": {"incident": False}})
        r = self._week()
        self.assertEqual(r["safety"], [])
        self.assertEqual(r["time_lost"]["rows"], [])

    def test_notes_carry_their_source_report(self):
        self._dpr(self.sat, {"matters_affecting": "Access blocked",
                             "visitors_instructions": "Consultant visited"})
        labels = [(n["label"], n["text"]) for n in self._week()["notes"]]
        self.assertIn(("Matters affecting progress", "Access blocked"), labels)
        self.assertIn(("Visitors / instructions", "Consultant visited"),
                      labels)

    # ---- the PDF ---------------------------------------------------------

    def test_the_pdf_renders(self):
        self._dpr(self.sat, {"manpower": {str(self.mason.id): 10},
                             "work_done": [{"trade": "C", "activity": "Pour"}]})
        r = self.client.get(f"/api/v1/sites/{self.site.id}/weekly.pdf"
                            f"?on=2026-08-24")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")

    def test_a_bad_date_is_refused(self):
        r = self.client.get(f"/api/v1/sites/{self.site.id}/weekly.pdf"
                            f"?on=last-week")
        self.assertEqual(r.status_code, 400)

    def test_another_sites_week_is_refused(self):
        other = Site.objects.create(code="OTH", name="Other",
                                    status=Site.Status.ACTIVE)
        r = self.client.get(f"/api/v1/sites/{other.id}/weekly.pdf")
        self.assertEqual(r.status_code, 403)

    def test_the_chart_is_svg(self):
        self._dpr(self.sat, {"manpower": {str(self.mason.id): 10}})
        self.assertIn("<svg", self._week()["manpower_chart"])


class DateRangeAndPhotoTests(DprWeeklyTests):
    """Any range, not only a week — and the photos the client actually looks
    at first (owner 2026-08-31)."""

    def test_an_explicit_range_wins(self):
        a, b = wk.resolve_range(date(2026, 8, 3), date(2026, 8, 30))
        self.assertEqual((a, b), (date(2026, 8, 3), date(2026, 8, 30)))

    def test_a_backwards_range_is_put_the_right_way_round(self):
        a, b = wk.resolve_range(date(2026, 8, 30), date(2026, 8, 3))
        self.assertEqual((a, b), (date(2026, 8, 3), date(2026, 8, 30)))

    def test_one_date_alone_is_a_single_day(self):
        a, b = wk.resolve_range(start=date(2026, 8, 3))
        self.assertEqual((a, b), (date(2026, 8, 3), date(2026, 8, 3)))

    def test_no_dates_still_means_this_week(self):
        """The weekly button must keep meaning what it did."""
        a, b = wk.resolve_range(on=date(2026, 8, 26))
        self.assertEqual((a, b), (date(2026, 8, 22), date(2026, 8, 28)))

    def test_a_month_gathers_every_day_in_it(self):
        for i in range(0, 20, 2):
            day = date(2026, 8, 3) + timedelta(days=i)
            self._dpr(day, {"manpower": {str(self.mason.id): 5}},
                      ref=f"DPR-M-{i}")
        r = wk.build(self.site, start=date(2026, 8, 1), end=date(2026, 8, 31))
        self.assertEqual(r["reported"], 10)
        self.assertEqual(r["expected"], 31)
        self.assertEqual(r["days_covered"], 31)
        self.assertFalse(r["is_week"])
        self.assertEqual(r["manpower"]["man_days"], 50)

    def test_a_saturday_to_friday_range_still_reads_as_a_week(self):
        r = wk.build(self.site, start=date(2026, 8, 22),
                     end=date(2026, 8, 28))
        self.assertTrue(r["is_week"])

    def test_photos_come_from_the_days_reports(self):
        from django.core.files.base import ContentFile

        from .models import Attachment

        doc = self._dpr(self.sat, {"manpower": {}})
        for i in range(3):
            a = Attachment(document=doc, kind="PHOTO", caption=f"Pour {i}",
                           uploaded_by=self.pm)
            a.file.save(f"p{i}.jpg", ContentFile(b"x"), save=True)
        r = self._week()
        self.assertEqual(r["photos"]["total"], 3)
        self.assertEqual(len(r["photos"]["items"]), 3)
        self.assertEqual(r["photos"]["items"][0]["caption"], "Pour 0")
        self.assertEqual(r["photos"]["items"][0]["date"], self.sat)

    def test_photos_are_capped_and_the_rest_counted(self):
        """A client report that takes a minute to open is one nobody opens —
        but what was left out is said, not quietly dropped."""
        from django.core.files.base import ContentFile

        from .models import Attachment

        doc = self._dpr(self.sat, {"manpower": {}})
        for i in range(wk.MAX_PHOTOS + 5):
            a = Attachment(document=doc, kind="PHOTO", uploaded_by=self.pm)
            a.file.save(f"q{i}.jpg", ContentFile(b"x"), save=True)
        ph = self._week()["photos"]
        self.assertEqual(ph["total"], wk.MAX_PHOTOS + 5)
        self.assertEqual(len(ph["items"]), wk.MAX_PHOTOS)
        self.assertEqual(ph["omitted"], 5)

    def test_photos_can_be_switched_off(self):
        r = wk.build(self.site, on=self.sat, with_photos=False)
        self.assertEqual(r["photos"]["items"], [])

    def test_the_endpoint_takes_a_range(self):
        self._dpr(date(2026, 8, 5), {"manpower": {str(self.mason.id): 4}})
        r = self.client.get(f"/api/v1/sites/{self.site.id}/weekly.pdf"
                            "?from=2026-08-01&to=2026-08-31")
        self.assertEqual(r.status_code, 200)
        self.assertIn("2026-08-01-to-2026-08-31", r["Content-Disposition"])

    def test_a_bad_range_date_is_refused(self):
        r = self.client.get(f"/api/v1/sites/{self.site.id}/weekly.pdf"
                            "?from=august&to=2026-08-31")
        self.assertEqual(r.status_code, 400)
        self.assertIn("from", r.data["detail"])

    def test_a_range_longer_than_a_year_is_refused(self):
        r = self.client.get(f"/api/v1/sites/{self.site.id}/weekly.pdf"
                            "?from=2024-01-01&to=2026-08-31")
        self.assertEqual(r.status_code, 400)
        self.assertIn("longer than a year", r.data["detail"])


class ManHourTests(DprWeeklyTests):
    """The team's own weekly report carries this table and computes it by
    hand from the same dailies (owner 2026-08-31)."""

    def test_man_hours_are_attendance_times_the_days_hours(self):
        self._dpr(self.sat, {"manpower": {str(self.mason.id): 50,
                                          str(self.eng.id): 8},
                             "working_hours": "07:00 – 22:00"})
        mh = self._week()["man_hours"]
        self.assertEqual(mh["rows"][0]["heads"], 58)
        self.assertEqual(mh["rows"][0]["hours"], 15.0)
        self.assertEqual(mh["rows"][0]["man_hours"], 870.0)
        self.assertEqual(mh["total"], 870.0)

    def test_the_total_runs_across_the_period(self):
        for i in range(3):
            self._dpr(self.sat + timedelta(days=i),
                      {"manpower": {str(self.mason.id): 10},
                       "working_hours": "08:00 - 17:00"})
        self.assertEqual(self._week()["man_hours"]["total"], 270.0)

    def test_a_missing_working_window_costs_the_hours_not_the_row(self):
        """The day still shows its attendance; the hours are simply zero and
        the blank window says why."""
        self._dpr(self.sat, {"manpower": {str(self.mason.id): 10}})
        row = self._week()["man_hours"]["rows"][0]
        self.assertEqual(row["heads"], 10)
        self.assertEqual(row["man_hours"], 0.0)

    def test_a_shift_past_midnight_is_not_negative(self):
        self._dpr(self.sat, {"manpower": {str(self.mason.id): 4},
                             "working_hours": "20:00 – 04:00"})
        self.assertEqual(self._week()["man_hours"]["rows"][0]["hours"], 8.0)

    def test_the_designation_chart_carries_a_series_per_trade(self):
        self._dpr(self.sat, {"manpower": {str(self.mason.id): 10,
                                          str(self.eng.id): 2}})
        chart = self._week()["designation_chart"]
        self.assertIn("<svg", chart)
        self.assertIn("Mason", chart)
        self.assertIn("Site Engineer", chart)


class ProgrammeAndUnitWorkTests(DprWeeklyTests):
    """Shaped against the report the team actually issues (owner 2026-08-31):
    it opens with the planned programme, and its body is a table per villa —
    activity, dates, percent — not a list of what the trades were busy with.
    """

    def setUp(self):
        super().setUp()
        from .models import ProjectUnit, UnitStage
        self.project = Project.objects.create(site=self.site, code="P1",
                                              title="Pools", status="ACTIVE")
        self.unit = ProjectUnit.objects.create(project=self.project,
                                               ref="V211", name="Villa 211")
        self.other = ProjectUnit.objects.create(project=self.project,
                                                ref="V215")
        self.stage = UnitStage.objects.create(project=self.project,
                                              name="Waterproofing",
                                              sort_order=1, weight=1)

    def _work(self, day, unit, activity, pct=None, **kw):
        row = {"trade": "Civil", "activity": activity,
               "unit_id": str(unit.id), "stage_id": str(self.stage.id)}
        row.update(kw)
        if pct is not None:
            row["progress_todate"] = pct
        self._dpr(day, {"work_done": [row]}, ref=f"DPR-{unit.ref}-{day.day}")

    # ---- work done, unit-wise -------------------------------------------

    def test_work_is_grouped_by_unit_not_by_trade(self):
        self._work(self.sat, self.unit, "1st coat")
        self._work(self.sat + timedelta(days=1), self.other, "Surface prep")
        blocks = self._week()["work_done"]
        self.assertEqual([b["ref"] for b in blocks], ["V211", "V215"])
        self.assertEqual(blocks[0]["name"], "Villa 211")

    def test_each_activity_carries_its_date_range_and_percent(self):
        self._work(self.sat, self.unit, "1st coat", pct=40)
        self._work(self.sat + timedelta(days=2), self.unit, "1st coat",
                   pct=85)
        item = self._week()["work_done"][0]["items"][0]
        self.assertEqual(item["first"], self.sat)
        self.assertEqual(item["last"], self.sat + timedelta(days=2))
        self.assertEqual(item["day_count"], 2)
        self.assertEqual(item["percent"], 85.0)      # the latest reported

    def test_work_with_no_unit_is_kept_under_general_and_last(self):
        """Not lost — a DPR row without a unit is still work that happened."""
        self._work(self.sat, self.unit, "1st coat")
        self._dpr(self.sat + timedelta(days=1),
                  {"work_done": [{"trade": "Civil", "activity": "Site clean"}]},
                  ref="DPR-GEN-1")
        refs = [b["ref"] for b in self._week()["work_done"]]
        self.assertEqual(refs, ["V211", "General"])

    # ---- the programme summary ------------------------------------------

    def test_the_programme_summary_is_the_top_of_the_wbs(self):
        from .models import ProgrammeActivity

        ProgrammeActivity.objects.create(
            project=self.project, sort_order=1, indent=0, name="Piling",
            start=date(2026, 7, 1), finish=date(2026, 7, 20), progress=100)
        ProgrammeActivity.objects.create(
            project=self.project, sort_order=2, indent=1, name="Batch 1",
            start=date(2026, 8, 1), finish=date(2026, 8, 20), progress=30)
        ProgrammeActivity.objects.create(
            project=self.project, sort_order=3, indent=4, name="Deep detail",
            start=date(2026, 8, 1), finish=date(2026, 8, 5), progress=0)
        rows = wk.build(self.site, on=self.sat,
                        project=self.project)["programme"]
        self.assertEqual([r["name"] for r in rows], ["Piling", "Batch 1"])

    def test_the_programme_says_what_is_overdue(self):
        from .models import ProgrammeActivity

        ProgrammeActivity.objects.create(
            project=self.project, sort_order=1, indent=0, name="Late one",
            start=date(2026, 7, 1), finish=date(2026, 8, 1), progress=40)
        ProgrammeActivity.objects.create(
            project=self.project, sort_order=2, indent=0, name="Done one",
            start=date(2026, 7, 1), finish=date(2026, 8, 1), progress=100)
        rows = {r["name"]: r["state"] for r in
                wk.build(self.site, start=date(2026, 8, 22),
                         end=date(2026, 8, 28),
                         project=self.project)["programme"]}
        self.assertEqual(rows["Late one"], "Overdue")
        self.assertEqual(rows["Done one"], "Complete")

    def test_no_project_means_no_programme_rather_than_a_crash(self):
        self.assertEqual(self._week()["programme"], [])

    # ---- materials are gone ---------------------------------------------

    def test_materials_are_no_longer_reported(self):
        """This is a progress report (owner 2026-08-31)."""
        self._dpr(self.sat, {"materials": [
            {"material": "Cement", "opening": 100, "balance": 90}]})
        self.assertNotIn("materials", self._week())
