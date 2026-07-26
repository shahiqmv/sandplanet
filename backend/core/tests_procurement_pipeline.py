"""Procurement Schedule Phase 2 — doc linking + derived pipeline."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Document, Item, Project, Site, SitePmHistory, User)
from .tests import make_user


def _stage(payload, key):
    line = payload["lines"][0]
    return next(s for s in line["pipeline"] if s["key"] == key)


class ProcurementPipelineTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pp_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.project = Project.objects.create(
            site=self.site, code="SJR-01", title="Villa Upgrades", pm=self.pm)
        self.purch = make_user("pp_buy", User.Role.HO_PURCHASING)
        self.sig = make_user("pp_sig", User.Role.SIGNATORY)
        self.item = Item.objects.create(code="ITM-1", description="SS316 rail",
                                        unit="m")
        self.client = APIClient()
        self.client.force_authenticate(self.pm)
        self.pk = self.client.post(
            f"/api/v1/projects/{self.project.id}/procurement-schedule").data["id"]
        self.line_id = self.client.post(
            f"/api/v1/procurement-schedules/{self.pk}/lines",
            {"description": "SS316 handrail", "section_code": "A",
             "item_id": self.item.id, "quantity": "10", "uom": "m",
             "tds_required": True, "required_date": "2026-10-01"},
            format="json").data["lines"][0]["id"]

    def _doc(self, doc_type, status, ref):
        return Document.objects.create(
            doc_type=doc_type, ref=ref, site=self.site, project=self.project,
            doc_date=date(2026, 8, 1), status=status, created_by=self.pm)

    def _link(self, slot, ref):
        return self.client.post(
            f"/api/v1/procurement-schedule-lines/{self.line_id}/link",
            {"slot": slot, "ref": ref}, format="json")

    def test_tds_starts_none_when_required(self):
        d = self.client.get(f"/api/v1/procurement-schedules/{self.pk}").data
        self.assertEqual(_stage(d, "tds")["state"], "none")
        self.assertEqual(_stage(d, "order")["state"], "none")
        self.assertEqual(_stage(d, "eta")["state"], "none")

    def test_link_mar_drives_tds(self):
        self._doc("MAR", "APPROVED", "MAR-SJR-001")
        r = self._link("mar", "MAR-SJR-001")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(_stage(r.data, "tds")["state"], "done")
        self.assertEqual(r.data["lines"][0]["mar_ref"], "MAR-SJR-001")

    def test_mar_in_progress_is_pending(self):
        self._doc("MAR", "SUBMITTED", "MAR-SJR-002")
        r = self._link("mar", "MAR-SJR-002")
        self.assertEqual(_stage(r.data, "tds")["state"], "pending")

    def test_link_and_unlink_ipr(self):
        self._doc("IPR", "DRAFT", "IPR-HO-001")
        r = self._link("ipr", "IPR-HO-001")
        self.assertEqual(_stage(r.data, "order")["state"], "pending")
        # authorised order reads as done
        Document.objects.filter(ref="IPR-HO-001").update(status="AUTHORISED")
        r = self.client.get(f"/api/v1/procurement-schedules/{self.pk}")
        self.assertEqual(_stage(r.data, "order")["state"], "done")
        # unlink clears it
        r = self.client.delete(
            f"/api/v1/procurement-schedule-lines/{self.line_id}/link",
            {"slot": "ipr"}, format="json")
        self.assertEqual(_stage(r.data, "order")["state"], "none")

    def test_grn_complete_delivers_and_closes_eta(self):
        self._doc("GRN", "COMPLETE", "GRN-SJR-001")
        r = self._link("grn", "GRN-SJR-001")
        self.assertEqual(_stage(r.data, "delivery")["state"], "done")
        self.assertEqual(_stage(r.data, "eta")["state"], "done")

    def test_production_flag(self):
        r = self.client.post(
            f"/api/v1/procurement-schedule-lines/{self.line_id}/production",
            {"status": "IN_PRODUCTION"}, format="json")
        self.assertEqual(_stage(r.data, "production")["state"], "pending")

    def test_candidates_match_project(self):
        self._doc("MAR", "APPROVED", "MAR-SJR-010")
        self._doc("MAR", "SUBMITTED", "MAR-SJR-011")
        r = self.client.get(
            f"/api/v1/procurement-schedule-lines/{self.line_id}/candidates",
            {"slot": "mar"})
        refs = [c["ref"] for c in r.data]
        self.assertIn("MAR-SJR-010", refs)
        self.assertIn("MAR-SJR-011", refs)

    def test_signatory_cannot_link(self):
        self._doc("MAR", "APPROVED", "MAR-SJR-020")
        self.client.force_authenticate(self.sig)
        r = self._link("mar", "MAR-SJR-020")
        self.assertEqual(r.status_code, 400)

    def test_link_unknown_ref_errors(self):
        r = self._link("mar", "MAR-NOPE-999")
        self.assertEqual(r.status_code, 400)
