"""Procurement Schedule — BOQ supplier quotes + award decision."""
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Project, ScheduleLine, ScheduleLineQuote, Site,
                     SitePmHistory, User)
from .tests import make_user


class ProcurementQuotesTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pq_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.project = Project.objects.create(
            site=self.site, code="SJR-01", title="Villa Upgrades", pm=self.pm)
        self.purch = make_user("pq_buy", User.Role.HO_PURCHASING)
        self.director = make_user("pq_dir", User.Role.DIRECTOR)
        self.se = make_user("pq_se", User.Role.SITE_ENGINEER, site=self.site)
        self.client = APIClient()
        self.client.force_authenticate(self.pm)
        self.pk = self.client.post(
            f"/api/v1/projects/{self.project.id}/procurement-schedule").data["id"]
        self.line_id = self.client.post(
            f"/api/v1/procurement-schedules/{self.pk}/lines",
            {"description": "Pump", "section_code": "A"},
            format="json").data["lines"][0]["id"]

    def _add_quote(self, **fields):
        return self.client.post(
            f"/api/v1/procurement-schedule-lines/{self.line_id}/quotes",
            fields, format="multipart")

    def _line(self, user=None):
        if user:
            self.client.force_authenticate(user)
        d = self.client.get(f"/api/v1/procurement-schedules/{self.pk}").data
        return d["lines"][0], d

    def test_add_quote_with_file(self):
        f = SimpleUploadedFile("quote.pdf", b"%PDF-1.4 quote",
                               content_type="application/pdf")
        r = self._add_quote(supplier_name="AquaPure", country="China",
                            quoted_value="4200", currency="USD",
                            lead_time_days="40", quote_file=f)
        self.assertEqual(r.status_code, 201, r.data)
        ln, _ = self._line()
        self.assertEqual(len(ln["quotes"]), 1)
        q = ln["quotes"][0]
        self.assertEqual(q["supplier_name"], "AquaPure")
        self.assertEqual(str(q["quoted_value"]), "4200.00")
        self.assertTrue(q["file_url"])

    def test_quotes_hidden_from_site_engineer(self):
        self._add_quote(supplier_name="AquaPure", quoted_value="4200")
        ln, d = self._line(self.se)
        self.assertFalse(d["show_values"])
        self.assertNotIn("quotes", ln)
        # and the SE can't add one
        self.client.force_authenticate(self.se)
        self.assertEqual(self._add_quote(supplier_name="X").status_code, 403)

    def test_recommended_is_exclusive(self):
        self._add_quote(supplier_name="A", quoted_value="100")
        self._add_quote(supplier_name="B", quoted_value="90",
                        is_recommended="true")
        ln, _ = self._line()
        recs = [q for q in ln["quotes"] if q["is_recommended"]]
        self.assertEqual([q["supplier_name"] for q in recs], ["B"])

    def test_purchasing_awards_a_quote(self):
        self._add_quote(supplier_name="A", quoted_value="100")
        ln, _ = self._line()
        qid = ln["quotes"][0]["id"]
        self.client.force_authenticate(self.purch)
        r = self.client.post(
            f"/api/v1/procurement-schedule-lines/{self.line_id}/award",
            {"action": "quote", "quote_id": qid}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        awarded = ScheduleLineQuote.objects.get(pk=qid)
        self.assertTrue(awarded.is_awarded)
        self.assertEqual(ScheduleLine.objects.get(pk=self.line_id).awarded_by,
                         self.purch)

    def test_award_new_supplier_needs_reason(self):
        self.client.force_authenticate(self.purch)
        bad = self.client.post(
            f"/api/v1/procurement-schedule-lines/{self.line_id}/award",
            {"action": "new"}, format="json")
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post(
            f"/api/v1/procurement-schedule-lines/{self.line_id}/award",
            {"action": "new", "note": "Cheaper local agent found"},
            format="json")
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertTrue(
            ScheduleLine.objects.get(pk=self.line_id).award_is_new_supplier)

    def test_pm_cannot_award(self):
        self._add_quote(supplier_name="A", quoted_value="100")
        ln, _ = self._line()
        r = self.client.post(   # still the PM
            f"/api/v1/procurement-schedule-lines/{self.line_id}/award",
            {"action": "quote", "quote_id": ln["quotes"][0]["id"]},
            format="json")
        self.assertEqual(r.status_code, 400)

    def test_awarded_quote_cannot_be_deleted(self):
        self._add_quote(supplier_name="A", quoted_value="100")
        ln, _ = self._line()
        qid = ln["quotes"][0]["id"]
        self.client.force_authenticate(self.purch)
        self.client.post(
            f"/api/v1/procurement-schedule-lines/{self.line_id}/award",
            {"action": "quote", "quote_id": qid}, format="json")
        r = self.client.delete(f"/api/v1/procurement-schedule-quotes/{qid}")
        self.assertEqual(r.status_code, 400)
