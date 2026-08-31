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
        """A client reading a weekly report wants the shape of the week; the
        dailies are there for the detail."""
        for i in range(3):
            self._dpr(self.sat + timedelta(days=i), {"work_done": [
                {"trade": "Concrete", "activity": "Column pour",
                 "location": "V211"}]})
        blocks = self._week()["work_done"]
        self.assertEqual(len(blocks), 1)
        item = blocks[0]["items"][0]
        self.assertEqual(item["day_count"], 3)
        self.assertEqual(item["first"], self.sat)
        self.assertEqual(item["last"], self.sat + timedelta(days=2))

    def test_activities_group_by_trade(self):
        self._dpr(self.sat, {"work_done": [
            {"trade": "Concrete", "activity": "Pour", "location": "A"},
            {"trade": "MEP", "activity": "Conduits", "location": "B"}]})
        self.assertEqual([b["trade"] for b in self._week()["work_done"]],
                         ["Concrete", "MEP"])

    def test_a_project_filter_narrows_the_activities(self):
        project = Project.objects.create(site=self.site, code="P1",
                                         title="One", status="ACTIVE")
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

    def test_materials_show_the_weeks_movement(self):
        self._dpr(self.sat, {"materials": [
            {"material": "Cement", "unit": "bag", "opening": 100,
             "received": 50, "consumed": 20, "balance": 130}]})
        self._dpr(self.sat + timedelta(days=1), {"materials": [
            {"material": "Cement", "unit": "bag", "opening": 130,
             "received": 0, "consumed": 30, "balance": 100}]})
        m = self._week()["materials"][0]
        self.assertEqual(m["opening"], 100)     # the week's opening
        self.assertEqual(m["received"], 50)
        self.assertEqual(m["consumed"], 50)
        self.assertEqual(m["balance"], 100)     # the closing balance

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
