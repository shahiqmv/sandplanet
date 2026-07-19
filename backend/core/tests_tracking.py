"""Shipment-tracking core: key validation, ShipsGo normalisation, and
idempotent snapshot application. No live HTTP — payloads mirror the ShipsGo v2
schema (see api-1.json)."""
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from .models import (Document, ImportOrder, ImportShipment, ShipmentTracking,
                     Site, Supplier, TrackingEvent, User)
from .tests import make_user
from . import tracking
from .tracking import NormEvent, Snapshot
from .tracking_shipsgo import ShipsGoProvider


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
