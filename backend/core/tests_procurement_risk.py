"""Procurement Schedule Phase 3 — late-risk engine, alerts, PD digest."""
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from . import procurement_pipeline as pp
from .models import (Document, Notification, Project, ScheduleLine, Site,
                     SitePmHistory, User)
from .tests import make_user


class ProcurementRiskTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Jani",
                                        status=Site.Status.ACTIVE)
        self.pm = make_user("pr_pm", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date(2026, 1, 1))
        self.project = Project.objects.create(
            site=self.site, code="SJR-01", title="Villa Upgrades", pm=self.pm)
        self.purch = make_user("pr_buy", User.Role.HO_PURCHASING)
        self.director = make_user("pr_dir", User.Role.DIRECTOR)
        self.client = APIClient()
        self.today = timezone.localdate()

    # -- helpers -----------------------------------------------------------
    def _signed_line(self, commercial=None, eta=None, **fields):
        """A signed-off (operational) line via the real workflow. Planning
        fields via `fields`; commercial ones (lead_time_days…) set by
        Purchasing during the SUBMITTED stage via `commercial`.

        `eta` is the team's expected-on-site date. Since 2026-09-03 nothing
        computes one — a line without an entered ETA (and without a booked
        shipment) has no projection and so no risk verdict at all, which is
        the point: the client is shown the same date the risk is judged on."""
        self.client.force_authenticate(self.pm)
        pk = self.client.post(
            f"/api/v1/projects/{self.project.id}/procurement-schedule").data["id"]
        body = {"description": "SS316 handrail", "section_code": "A",
                "supply_by": "CONTRACTOR", **fields}
        line_id = self.client.post(
            f"/api/v1/procurement-schedules/{pk}/lines", body,
            format="json").data["lines"][0]["id"]
        self.client.post(f"/api/v1/procurement-schedules/{pk}/submit")
        self.client.force_authenticate(self.purch)
        if commercial:
            self.client.patch(
                f"/api/v1/procurement-schedule-lines/{line_id}", commercial,
                format="json")
        self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                         {"action": "confirm"}, format="json")
        self.client.force_authenticate(self.director)
        self.client.post(f"/api/v1/procurement-schedules/{pk}/action",
                         {"action": "sign_off"}, format="json")
        line = ScheduleLine.objects.get(pk=line_id)
        if eta is not None:
            line.eta_date = eta
            line.save(update_fields=["eta_date"])
        return line

    def _risk(self, line):
        return pp.line_risk(line)["level"]

    # -- risk classification ----------------------------------------------
    def test_late_when_unordered_cannot_make_date(self):
        line = self._signed_line(
            required_date=(self.today + timedelta(days=10)).isoformat(),
            eta=self.today + timedelta(days=20),
            commercial={"lead_time_days": 30})
        r = pp.line_risk(line)
        self.assertEqual(r["level"], "LATE")
        self.assertTrue(r["unordered"])

    def test_no_entered_eta_is_no_verdict(self):
        """A line nobody has dated cannot be judged. The old projection —
        today + lead time + a country guess — moved forward every day and
        reached the client as a commitment (owner 2026-09-03)."""
        line = self._signed_line(
            required_date=(self.today + timedelta(days=10)).isoformat(),
            commercial={"lead_time_days": 30})
        r = pp.line_risk(line)
        self.assertEqual((r["level"], r["projected"]), ("NONE", None))
        self.assertEqual(r["reason"], "No ETA entered")

    def test_a_required_date_gone_by_is_late_even_with_no_eta(self):
        line = self._signed_line(
            required_date=(self.today - timedelta(days=3)).isoformat(),
            commercial={"lead_time_days": 30})
        self.assertEqual(self._risk(line), "LATE")

    def test_on_track_when_far_out(self):
        line = self._signed_line(
            required_date=(self.today + timedelta(days=200)).isoformat(),
            eta=self.today + timedelta(days=60),
            commercial={"lead_time_days": 30})
        self.assertEqual(self._risk(line), "ON_TRACK")

    def test_at_risk_inside_window(self):
        # The ETA lands two days before the date it has to make: inside the
        # 14-day window, so at risk rather than on track.
        line = self._signed_line(
            required_date=(self.today + timedelta(days=75)).isoformat(),
            eta=self.today + timedelta(days=73),
            commercial={"lead_time_days": 30})
        self.assertEqual(self._risk(line), "AT_RISK")

    def test_the_customs_leg_is_counted_on_top_of_the_sail(self):
        """Clearance sits on top of the sail in the order-by arithmetic.

        Taken from a PM's own schedule, where every line reads "shipping 30
        days, customs 10 days": the shipping table had always been the SAIL,
        so clearance was simply missing and the suggestion ran about ten days
        optimistic (owner 2026-08-29). Since 2026-09-03 the legs no longer
        project an ETA — that is the team's own date — but they still work
        out the last day an order can go out."""
        line = self._signed_line(
            required_date=(self.today + timedelta(days=65)).isoformat(),
            commercial={"lead_time_days": 30, "shipping_days": 30,
                        "clearance_days": 10})
        legs = pp.lead_legs(line)
        self.assertEqual(legs["total_days"], 30 + 30 + 10 + 5)
        self.assertEqual(pp.suggested_order_by(line),
                         line.required_date - timedelta(days=75))

    def test_delivered_via_grn(self):
        line = self._signed_line(
            required_date=(self.today + timedelta(days=10)).isoformat(),
            commercial={"lead_time_days": 30})
        grn = Document.objects.create(
            doc_type="GRN", ref="GRN-SJR-001", site=self.site,
            project=self.project, doc_date=self.today, status="COMPLETE",
            created_by=self.pm)
        line.grn = grn
        line.save(update_fields=["grn"])
        self.assertEqual(self._risk(line), "DELIVERED")

    def test_client_line_overdue_is_late(self):
        line = self._signed_line(
            supply_by="CLIENT",
            required_date=(self.today - timedelta(days=3)).isoformat())
        self.assertEqual(self._risk(line), "LATE")

    def test_client_line_future_is_none(self):
        line = self._signed_line(
            supply_by="CLIENT",
            required_date=(self.today + timedelta(days=30)).isoformat())
        self.assertEqual(self._risk(line), "NONE")

    # -- sweep + watermark -------------------------------------------------
    def test_sweep_alerts_pm_purchasing_director_once(self):
        self._signed_line(
            required_date=(self.today + timedelta(days=10)).isoformat(),
            eta=self.today + timedelta(days=20),
            commercial={"lead_time_days": 30})
        sent = pp.sweep_risk_alerts()
        self.assertEqual(sent, 1)
        # LATE escalates to PM + Purchasing + Director
        recips = set(Notification.objects.values_list("recipient_id",
                                                       flat=True))
        self.assertEqual(recips, {self.pm.id, self.purch.id, self.director.id})
        # watermark stops a re-fire on the next run
        self.assertEqual(pp.sweep_risk_alerts(), 0)

    def test_sweep_ignores_draft_schedule(self):
        # a line that never reached sign-off isn't swept
        self.client.force_authenticate(self.pm)
        pk = self.client.post(
            f"/api/v1/projects/{self.project.id}/procurement-schedule").data["id"]
        self.client.post(f"/api/v1/procurement-schedules/{pk}/lines",
                         {"description": "X", "section_code": "A",
                          "required_date": (self.today + timedelta(days=5))
                          .isoformat(), "lead_time_days": 60}, format="json")
        self.assertEqual(pp.sweep_risk_alerts(), 0)

    def test_pd_digest_deduped_same_day(self):
        self._signed_line(
            required_date=(self.today + timedelta(days=10)).isoformat(),
            eta=self.today + timedelta(days=20),
            commercial={"lead_time_days": 30})
        self.assertEqual(pp.send_pd_digest(), 1)
        digests = Notification.objects.filter(
            recipient=self.director, title__startswith="Procurement digest:")
        self.assertEqual(digests.count(), 1)
        self.assertIn("1 late", digests.first().title)
        # same-day re-run doesn't double up
        self.assertEqual(pp.send_pd_digest(), 0)
