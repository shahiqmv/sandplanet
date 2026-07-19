"""Shipment-tracking core: key validation, ShipsGo normalisation, and
idempotent snapshot application. No live HTTP — payloads mirror the ShipsGo v2
schema (see api-1.json)."""
import json
from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import imports as ipr_svc
from .models import (Document, ImportOrder, ImportShipment, ShipmentTracking,
                     Site, Supplier, TrackingEvent, User)
from .tests import make_user
from . import tracking
from .tracking import NormEvent, Snapshot
from .tracking_shipsgo import ShipsGoProvider


def _make_shipment(mode="SEA", bl_no="", container="", awb=""):
    site = Site.objects.create(code="HO", name="Head Office",
                               status=Site.Status.ACTIVE)
    actor = make_user("ho1", User.Role.HO_PURCHASING)
    supplier = Supplier.objects.create(name="Guangzhou Pumps Co",
                                       category="INTERNATIONAL",
                                       default_currency="USD")
    doc = Document.objects.create(doc_type="IPR", ref="IPR-HO-001", site=site,
                                  doc_date=date.today(), status="AUTHORISED",
                                  created_by=actor)
    order = ImportOrder.objects.create(document=doc, supplier=supplier,
                                       order_currency="USD", exchange_rate=15)
    ship = ImportShipment.objects.create(
        order=order, seq=1, mode=mode, status="BOOKED", bl_no=bl_no,
        container_awb=(awb if mode == "AIR" else container))
    return ship, actor


class KeyValidationTests(TestCase):
    def test_container_format(self):
        self.assertTrue(tracking.is_valid_container("MSCU1234567"))
        self.assertFalse(tracking.is_valid_container("MSCU123456"))   # 6 digits
        self.assertFalse(tracking.is_valid_container("1234MSCU567"))

    def test_awb_checksum(self):
        # 176 + serial 1234567 (mod 7 = 5) + check 5 → valid
        self.assertTrue(tracking.is_valid_awb("17612345675"))
        self.assertFalse(tracking.is_valid_awb("17612345676"))  # wrong check
        self.assertFalse(tracking.is_valid_awb("1761234567"))   # 10 digits

    def test_validate_per_mode(self):
        self.assertIsNone(tracking.validate_shipment_keys(
            "SEA", "MEDUQY000000", "MSCU1234567", "MSCU"))
        self.assertIn("container", tracking.validate_shipment_keys(
            "SEA", "", "BADCONTAINER", "").lower())
        self.assertIn("awb", tracking.validate_shipment_keys(
            "AIR", "", "17612345676", "").lower())


def _ocean_payload():
    return {"id": 123456, "reference": "IPR-HO-001-S1",
            "booking_number": "MEDUQY000000", "status": "SAILING",
            "route": {
                "port_of_loading": {"location": {"code": "CNSHA",
                                                 "name": "Shanghai"}},
                "port_of_discharge": {
                    "location": {"code": "MVMLE", "name": "Male"},
                    "date_of_discharge": "2026-08-01T10:00:00Z",
                    "date_of_discharge_initial": "2026-07-25T10:00:00Z"},
                "ts_count": 1},
            "tokens": {"map": "https://shipsgo.com/live/abc"},
            "containers": [{"number": "MSCU1234567", "movements": [
                {"event": "DEPA", "status": "ACT",
                 "location": {"code": "CNSHA", "name": "Shanghai"},
                 "vessel": {"name": "MSC ISABELLA"},
                 "timestamp": "2026-07-10T08:00:00Z"},
                {"event": "DISC", "status": "ACT",
                 "location": {"code": "LKCMB", "name": "Colombo"},
                 "vessel": {"name": "MSC ISABELLA"},
                 "timestamp": "2026-07-20T08:00:00Z"},
                {"event": "ARRV", "status": "EST",
                 "location": {"code": "MVMLE", "name": "Male"},
                 "vessel": {"name": "MSC FEEDER"},
                 "timestamp": "2026-08-01T10:00:00Z"},
            ]}]}


class OceanNormaliseTests(TestCase):
    def test_movements_map_to_milestones(self):
        snap = ShipsGoProvider()._normalise(_ocean_payload(), "SEA")
        self.assertEqual(snap.provider_tracking_id, "123456")
        self.assertEqual(snap.map_url, "https://shipsgo.com/live/abc")
        self.assertEqual(snap.eta.date(), date(2026, 8, 1))
        by_code = [(e.provider_event_code, e.code) for e in snap.events]
        self.assertIn(("DEPA", TrackingEvent.Code.DEPARTED), by_code)
        self.assertIn(("DISC", TrackingEvent.Code.TRANSSHIPMENT), by_code)
        self.assertIn(("ARRV", TrackingEvent.Code.ARRIVED), by_code)
        arr = next(e for e in snap.events if e.provider_event_code == "ARRV")
        self.assertFalse(arr.is_actual)   # EST
        self.assertEqual(arr.vessel_flight, "MSC FEEDER")


class AirNormaliseTests(TestCase):
    def test_air_departed_and_arrived(self):
        payload = {"id": 999, "awb_number": "17612345675", "status": "LANDED",
                   "route": {"origin": {"iata": "PVG"},
                             "destination": {"iata": "MLE"}},
                   "tokens": {"map": "https://shipsgo.com/live/air"},
                   "movements": [
                       {"event": "DEP", "status": "ACT",
                        "location": {"iata": "PVG", "name": "Shanghai"},
                        "flight": "EK305",
                        "timestamp": "2026-07-10T02:00:00Z"},
                       {"event": "ARR", "status": "ACT",
                        "location": {"iata": "MLE", "name": "Male"},
                        "flight": "EK654",
                        "timestamp": "2026-07-11T06:00:00Z"}]}
        snap = ShipsGoProvider()._normalise(payload, "AIR")
        self.assertTrue(snap.arrived)
        codes = {e.code for e in snap.events}
        self.assertIn(TrackingEvent.Code.DEPARTED, codes)
        self.assertIn(TrackingEvent.Code.ARRIVED, codes)


class ApplySnapshotTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="HO", name="Head Office",
                                        status=Site.Status.ACTIVE)
        self.actor = make_user("ho1", User.Role.HO_PURCHASING)
        supplier = Supplier.objects.create(name="Guangzhou Pumps Co",
                                           category="INTERNATIONAL",
                                           default_currency="USD")
        doc = Document.objects.create(doc_type="IPR", ref="IPR-HO-001",
                                      site=self.site, doc_date=date.today(),
                                      status="AUTHORISED", created_by=self.actor)
        order = ImportOrder.objects.create(document=doc, supplier=supplier,
                                           order_currency="USD",
                                           exchange_rate=15)
        self.ship = ImportShipment.objects.create(order=order, seq=1,
                                                   mode="SEA")
        self.tr = ShipmentTracking.objects.create(
            shipment=self.ship, mode="SEA",
            state=ShipmentTracking.State.ACTIVE,
            provider_tracking_id="123456")

    def test_apply_is_idempotent_and_updates_eta(self):
        snap = ShipsGoProvider()._normalise(_ocean_payload(), "SEA")
        out = tracking.apply_snapshot(self.tr, snap, source="POLL")
        self.assertEqual(len(out["created"]), 3)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.current_eta.date(), date(2026, 8, 1))
        self.assertEqual(self.tr.map_url, "https://shipsgo.com/live/abc")
        # the shipment mirrors the live ETA + map link
        self.ship.refresh_from_db()
        self.assertEqual(self.ship.eta, date(2026, 8, 1))
        # re-applying the same snapshot creates nothing new
        out2 = tracking.apply_snapshot(self.tr, snap, source="POLL")
        self.assertEqual(len(out2["created"]), 0)
        self.assertEqual(TrackingEvent.objects.filter(
            tracking=self.tr, code=TrackingEvent.Code.OTHER).count(), 0)

    def test_arrival_moves_state_and_eta_slip_flags(self):
        # first apply with an early ETA
        self.tr.current_eta = timezone.now()
        self.tr.save()
        snap = ShipsGoProvider()._normalise(_ocean_payload(), "SEA")
        out = tracking.apply_snapshot(self.tr, snap, source="WEBHOOK")
        self.assertTrue(out["eta_slipped"])
        self.assertTrue(TrackingEvent.objects.filter(
            tracking=self.tr, code=TrackingEvent.Code.ETA_UPDATED).exists())
        # a DISCHARGED status arrives the tracking
        arrived = _ocean_payload()
        arrived["status"] = "DISCHARGED"
        snap2 = ShipsGoProvider()._normalise(arrived, "SEA")
        tracking.apply_snapshot(self.tr, snap2, source="WEBHOOK")
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.state, ShipmentTracking.State.ARRIVED)


class _Fake:
    """Stub provider returning a canned snapshot from _ocean_payload()."""
    def register(self, tr):
        return ShipsGoProvider()._normalise(_ocean_payload(), "SEA")

    def fetch(self, tr):
        return ShipsGoProvider()._normalise(_ocean_payload(), "SEA")


class RegistrationTests(TestCase):
    def test_ensure_prefers_bl_then_registers_active(self):
        ship, _ = _make_shipment(bl_no="MEDUQY000000",
                                 container="MSCU1234567")
        t = tracking.ensure_tracking(ship)
        self.assertEqual(t.state, "PENDING_REGISTRATION")
        self.assertEqual(t.tracking_key, "MEDUQY000000")   # B/L preferred
        self.assertEqual(t.provider_ref, "IPR-HO-001-S1")
        with patch("core.tracking.get_provider", return_value=_Fake()):
            tracking.register_tracking(t)
        t.refresh_from_db()
        self.assertEqual(t.state, "ACTIVE")
        self.assertTrue(t.credits_consumed)
        self.assertTrue(t.events.exists())

    def test_shipped_transition_creates_tracking(self):
        ship, actor = _make_shipment(bl_no="MEDUQY000000")
        # no API key configured → registration fails gracefully, row stays
        err = ipr_svc.advance_shipment(ship, "SHIPPED", actor)
        self.assertIsNone(err)
        t = ShipmentTracking.objects.get(shipment=ship)
        self.assertIn(t.state, ("PENDING_REGISTRATION", "FAILED"))
        self.assertTrue(t.last_error)   # "SHIPSGO_API_KEY is not configured"

    def test_air_awb_validation_blocks_bad_key(self):
        ship, actor = _make_shipment(mode="AIR")
        _, msg = ipr_svc.create_shipment(
            ship.order, {"mode": "AIR", "container_awb": "17612345676"}, actor)
        self.assertIn("awb", (msg or "").lower())


@override_settings(SHIPSGO_WEBHOOK_SECRET="s3cr3t")
class WebhookTests(TestCase):
    def setUp(self):
        ship, _ = _make_shipment(bl_no="MEDUQY000000")
        self.tr = ShipmentTracking.objects.create(
            shipment=ship, mode="SEA", state="ACTIVE",
            provider_ref="IPR-HO-001-S1", provider_tracking_id="123456")
        self.client = APIClient()

    def _post(self, token="s3cr3t"):
        body = {"event": {"id": "evt-1", "name": "OCEAN.SHIPMENTS."
                          "SHIPMENT_UPDATED"},
                "shipment": _ocean_payload()}
        return self.client.post(
            f"/api/webhooks/tracking/shipsgo/?token={token}",
            data=json.dumps(body), content_type="application/json")

    def test_bad_secret_rejected(self):
        self.assertEqual(self._post(token="wrong").status_code, 401)
        self.assertFalse(self.tr.events.exists())

    def test_valid_webhook_ingests_and_is_idempotent(self):
        r = self._post()
        self.assertEqual(r.status_code, 200, r.data)
        n = self.tr.events.filter(code="ARRIVED").count()
        self.assertEqual(n, 1)
        self._post()   # redelivery
        self.assertEqual(self.tr.events.filter(code="ARRIVED").count(), 1)


class ManualFallbackTests(TestCase):
    def test_switch_manual_and_log_event(self):
        ship, _ = _make_shipment(bl_no="MEDUQY000000")
        t = tracking.ensure_tracking(ship)
        tracking.switch_manual(t)
        self.assertEqual(t.state, "MANUAL")
        ev = tracking.add_manual_event(
            t, TrackingEvent.Code.DEPARTED, "Left Shanghai", location="Shanghai")
        self.assertEqual(ev.source, "MANUAL")
        self.assertEqual(t.events.filter(code="DEPARTED").count(), 1)
