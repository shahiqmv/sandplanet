"""Procurement Schedule — spine + propose/confirm/sign-off workflow (Phase 1)."""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Document, Project, ProcurementSchedule, ScheduleLine,
                     Site, SitePmHistory, User)
from .tests import make_user


class ProcurementScheduleTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("psched_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.project = Project.objects.create(
            site=self.site, code="SJR-01", title="Villa Upgrades", pm=self.pm)
        self.purch = make_user("psched_buy", User.Role.HO_PURCHASING)
        self.director = make_user("psched_dir", User.Role.DIRECTOR)
        self.se = make_user("psched_se", User.Role.SITE_ENGINEER, site=self.site)
        self.qs = make_user("psched_qs", User.Role.QS)
        self.client = APIClient()

    def _open(self):
        self.client.force_authenticate(self.pm)
        r = self.client.post(
            f"/api/v1/projects/{self.project.id}/procurement-schedule")
        assert r.status_code == 201, r.data
        return r.data["id"]

    def _add_line(self, pk, **kw):
        self.client.force_authenticate(self.pm)
        body = {"description": "SS316 handrail", "section_code": "A",
                "section_title": "Villa Upgrades", "trade": "Metalwork",
                "required_date": "2026-10-01", **kw}
        return self.client.post(
            f"/api/v1/procurement-schedules/{pk}/lines", body, format="json")

    def test_open_is_site_scoped_ref(self):
        pk = self._open()
        d = self.client.get(f"/api/v1/procurement-schedules/{pk}").data
        self.assertTrue(d["ref"].startswith("PSC-SJR-"))
        self.assertEqual(d["status"], "DRAFT")
        # one schedule per project — reopening returns the same one
        r2 = self.client.post(
            f"/api/v1/projects/{self.project.id}/procurement-schedule")
        self.assertEqual(r2.data["id"], pk)

    def test_qs_and_site_engineer_can_also_propose(self):
        # QS opens the schedule (starts from the commercial side)
        self.client.force_authenticate(self.qs)
        pk = self.client.post(
            f"/api/v1/projects/{self.project.id}/procurement-schedule").data["id"]
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/lines",
                             {"description": "Chiller unit", "section_code": "B"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        # a site engineer can add a line too (no over-segregation)
        self.client.force_authenticate(self.se)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/lines",
                             {"description": "Cable tray", "section_code": "B"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(r.data["show_values"])          # SE still no values
        # Purchasing is the gate, not a proposer
        self.client.force_authenticate(self.purch)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/lines",
                             {"description": "x", "section_code": "B"},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_line_links_to_item_master(self):
        from .models import Item
        item = Item.objects.create(code="ITM-90001", description="SS316 rail",
                                   unit="m", category="Steel & Metalwork")
        pk = self._open()
        r = self._add_line(pk, item_id=item.id, quantity="12", uom="m",
                           category="Steel & Metalwork")
        self.assertEqual(r.status_code, 201, r.data)
        ln = r.data["lines"][0]
        self.assertEqual(ln["item_id"], item.id)
        self.assertEqual(ln["item_code"], "ITM-90001")
        self.assertEqual(str(ln["quantity"]), "12.00")
        self.assertEqual(ln["uom"], "m")
        self.assertEqual(ln["category"], "Steel & Metalwork")

    def test_propose_confirm_signoff(self):
        pk = self._open()
        r = self._add_line(pk)
        self.assertEqual(r.status_code, 201, r.data)
        line_id = r.data["lines"][0]["id"]
        # PM submits → SUBMITTED (Purchasing queue)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.assertEqual(r.data["status"], "SUBMITTED")
        # Purchasing edits a commercial field then confirms
        self.client.force_authenticate(self.purch)
        self.client.patch(
            f"/api/v1/procurement-schedule-lines/{line_id}",
            {"planned_supplier": "Reef Steel", "source_country": "India",
             "estimated_value": "4200", "lead_time_days": 45}, format="json")
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                             {"action": "confirm"}, format="json")
        self.assertEqual(r.data["status"], "CONFIRMED")
        self.assertEqual(r.data["lines"][0]["state"], "CONFIRMED")
        self.assertEqual(r.data["lines"][0]["lead_time_days"], 45)
        # Director signs off → SIGNED_OFF + baseline stamped
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                             {"action": "sign_off"}, format="json")
        self.assertEqual(r.data["status"], "SIGNED_OFF")
        self.assertEqual(r.data["lines"][0]["state"], "SIGNED_OFF")
        self.assertTrue(r.data["baseline_signed_at"])

    def test_purchasing_returns_to_pm(self):
        pk = self._open()
        self._add_line(pk)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.client.force_authenticate(self.purch)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                             {"action": "return", "note": "Confirm the brand"},
                             format="json")
        self.assertEqual(r.data["status"], "DRAFT")
        self.assertEqual(r.data["lines"][0]["state"], "PROPOSED")

    def test_return_needs_reason(self):
        pk = self._open()
        self._add_line(pk)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.client.force_authenticate(self.purch)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                             {"action": "return"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_only_purchasing_confirms_only_director_signs(self):
        pk = self._open()
        self._add_line(pk)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        # PM cannot confirm
        self.client.force_authenticate(self.pm)
        self.assertEqual(self.client.post(
            f"/api/v1/procurement-schedules/{pk}/action",
            {"action": "confirm"}, format="json").status_code, 400)
        # Purchasing confirms; a non-director cannot sign off
        self.client.force_authenticate(self.purch)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                         {"action": "confirm"}, format="json")
        self.assertEqual(self.client.post(
            f"/api/v1/procurement-schedules/{pk}/action",
            {"action": "sign_off"}, format="json").status_code, 400)

    def test_director_can_confirm_and_push_through(self):
        # Option B (owner 2026-08-01): the Director can confirm a submitted
        # schedule directly — no waiting on Purchasing — then sign it off.
        pk = self._open()
        self._add_line(pk)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.client.force_authenticate(self.director)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                             {"action": "confirm"}, format="json")
        self.assertEqual(r.data["status"], "CONFIRMED", r.data)
        r = self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                             {"action": "sign_off"}, format="json")
        self.assertEqual(r.data["status"], "SIGNED_OFF", r.data)
        self.assertTrue(r.data["baseline_signed_at"])

    def test_values_hidden_from_site_engineer(self):
        pk = self._open()
        self._add_line(pk)
        # PM sees estimated_value key; SE never does
        pm_line = self.client.get(
            f"/api/v1/procurement-schedules/{pk}").data["lines"][0]
        self.assertIn("estimated_value", pm_line)
        self.client.force_authenticate(self.se)
        d = self.client.get(f"/api/v1/procurement-schedules/{pk}").data
        self.assertFalse(d["show_values"])
        self.assertNotIn("estimated_value", d["lines"][0])

    def test_adding_line_after_signoff_reopens_batch(self):
        pk = self._open()
        r = self._add_line(pk)
        first_line = r.data["lines"][0]["id"]
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.client.force_authenticate(self.purch)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                         {"action": "confirm"}, format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                         {"action": "sign_off"}, format="json")
        # PM adds a second line to the signed schedule → reopens to DRAFT
        r = self._add_line(pk, description="Pump valve")
        self.assertEqual(r.data["status"], "DRAFT")
        states = {ln["id"]: ln["state"] for ln in r.data["lines"]}
        self.assertEqual(states[first_line], "SIGNED_OFF")   # baseline stays
        new_line = next(i for i in states if i != first_line)
        self.assertEqual(states[new_line], "PROPOSED")

    def test_director_signs_off_on_mobile(self):
        pk = self._open()
        ref = self.client.get(
            f"/api/v1/procurement-schedules/{pk}").data["ref"]
        self._add_line(pk)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.client.force_authenticate(self.purch)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                         {"action": "confirm"}, format="json")
        # Director on mobile
        self.director.set_password("verify-123")
        self.director.save()
        m = APIClient()
        tok = m.post("/api/mobile/v1/auth/login",
                     {"username": self.director.username,
                      "password": "verify-123"}, format="json").data["token"]
        m.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")
        q = m.get("/api/mobile/v1/queue")
        self.assertIn(ref, [i["ref"] for i in q.data["items"]])
        detail = m.get(f"/api/mobile/v1/documents/{ref}")
        self.assertTrue(any(f["k"] == "Project"
                            for f in detail.data["summary"]))
        a = m.post(f"/api/mobile/v1/documents/{ref}/approve", {}, format="json")
        self.assertEqual(a.status_code, 200, a.data)
        self.assertEqual(Document.objects.get(ref=ref).status, "SIGNED_OFF")
