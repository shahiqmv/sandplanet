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
    def test_container_iso6346_check_digit(self):
        self.assertTrue(tracking.is_valid_container("CSQU3054383"))    # canonical
        self.assertTrue(tracking.is_valid_container("MSCU1234566"))
        self.assertFalse(tracking.is_valid_container("MSCU1234567"))  # bad check
        self.assertFalse(tracking.is_valid_container("MSCU123456"))   # 6 digits
        self.assertFalse(tracking.is_valid_container("1234MSCU567"))

    def test_awb_checksum(self):
        # 176 + serial 1234567 (mod 7 = 5) + check 5 → valid
        self.assertTrue(tracking.is_valid_awb("17612345675"))
        self.assertFalse(tracking.is_valid_awb("17612345676"))  # wrong check
        self.assertFalse(tracking.is_valid_awb("1761234567"))   # 10 digits

    def test_validate_per_mode(self):
        self.assertIsNone(tracking.validate_shipment_keys(
            "SEA", "MEDUQY000000", "MSCU1234566", "MSCU"))
        self.assertIn("container", tracking.validate_shipment_keys(
            "SEA", "", "BADCONTAINER", "").lower())
        self.assertIn("awb", tracking.validate_shipment_keys(
            "AIR", "", "17612345676", "").lower())

    def test_bl_equal_to_container_is_rejected(self):
        msg = tracking.validate_shipment_keys(
            "SEA", "MSCU1234566", "MSCU1234566", "MSCU")
        self.assertIn("b/l", (msg or "").lower())


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

    def test_adding_bl_after_shipping_registers_a_multishipment_leg(self):
        # A shipment booked + shipped with no key (common: B/L arrives later).
        ship, actor = _make_shipment()
        ipr_svc.advance_shipment(ship, "SHIPPED", actor)
        self.assertFalse(ShipmentTracking.objects.filter(shipment=ship)
                         .exists())      # nothing to track yet
        # editing in the carrier + B/L now spins up + registers tracking
        with patch("core.tracking.get_provider", return_value=_Fake()):
            err = ipr_svc.update_shipment_details(
                ship, {"carrier_scac": "MSCU", "bl_no": "MEDUQY000009"}, actor)
        self.assertIsNone(err)
        t = ShipmentTracking.objects.get(shipment=ship)
        self.assertEqual(t.state, "ACTIVE")
        self.assertEqual(t.tracking_key, "MEDUQY000009")

    def test_update_rejects_bad_key(self):
        ship, actor = _make_shipment()
        err = ipr_svc.update_shipment_details(
            ship, {"mode": "AIR", "container_awb": "17612345676"}, actor)
        self.assertIn("awb", err.lower())


class WebhookSignatureTests(TestCase):
    def test_matches_shipsgo_reference_vector(self):
        # ShipsGo's documented test vector — proves our HMAC-SHA256 hex digest
        # is computed exactly as they sign it.
        import hashlib
        import hmac
        sig = hmac.new(b"SUPER_LONG_AND_SECURE_SECRET_KEY",
                       b'{"message":"You shall not pass!"}',
                       hashlib.sha256).hexdigest()
        self.assertEqual(
            sig, "9527e0c9463e6f5b01a0af50aecb4658ff50c6b25d3efa8e5c8dea7"
                 "e4b763772")


@override_settings(SHIPSGO_WEBHOOK_SECRET="s3cr3t")
class WebhookTests(TestCase):
    def setUp(self):
        ship, _ = _make_shipment(bl_no="MEDUQY000000")
        self.tr = ShipmentTracking.objects.create(
            shipment=ship, mode="SEA", state="ACTIVE",
            provider_ref="IPR-HO-001-S1", provider_tracking_id="123456")
        self.client = APIClient()

    def _post(self, secret="s3cr3t"):
        import hashlib
        import hmac
        body = json.dumps({"event": {"id": "evt-1", "name": "OCEAN.SHIPMENTS."
                           "SHIPMENT_UPDATED"},
                           "shipment": _ocean_payload()}).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(
            "/api/webhooks/tracking/shipsgo/", data=body,
            content_type="application/json",
            HTTP_X_SHIPSGO_WEBHOOK_SIGNATURE=sig)

    def test_bad_signature_rejected(self):
        self.assertEqual(self._post(secret="wrong").status_code, 401)
        self.assertFalse(self.tr.events.exists())

    def test_valid_webhook_ingests_and_is_idempotent(self):
        r = self._post()
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.tr.events.filter(code="ARRIVED").count(), 1)
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


class _FakeCarriers:
    def __init__(self, rows):
        self.rows = rows

    def list_carriers(self):
        return self.rows


class CarrierSyncTests(TestCase):
    def test_sync_upserts_prunes_and_records_state(self):
        from core import carriers as csvc
        from core.models import TrackingCarrier
        rows = [{"scac": "MSCU", "name": "MSC", "status": "ACTIVE"},
                {"scac": "RCLU", "name": "Regional Container Lines",
                 "status": "ACTIVE"}]
        with patch("core.tracking.get_provider",
                   return_value=_FakeCarriers(rows)):
            ok, n = csvc.sync_carriers()
        self.assertTrue(ok)
        self.assertEqual(n, 2)
        self.assertTrue(TrackingCarrier.objects.filter(scac="RCLU").exists())
        self.assertTrue(csvc.sync_state()["ok"])
        # a later, shorter list prunes carriers the provider dropped
        with patch("core.tracking.get_provider",
                   return_value=_FakeCarriers(rows[:1])):
            csvc.sync_carriers()
        self.assertFalse(TrackingCarrier.objects.filter(scac="RCLU").exists())

    def test_sync_failure_keeps_list_and_flags_state(self):
        from core import carriers as csvc
        from core.models import TrackingCarrier
        TrackingCarrier.objects.create(scac="MSCU", name="MSC")

        class Boom:
            def list_carriers(self):
                raise RuntimeError("ShipsGo 401 TOKEN_MISSING")

        with patch("core.tracking.get_provider", return_value=Boom()):
            ok, err = csvc.sync_carriers()
        self.assertFalse(ok)
        self.assertEqual(TrackingCarrier.objects.count(), 1)   # NOT wiped
        self.assertFalse(csvc.sync_state()["ok"])


class CarrierEndpointTests(TestCase):
    def setUp(self):
        from core.models import TrackingCarrier
        TrackingCarrier.objects.create(scac="MSCU", name="MSC")
        self.admin = make_user("adm", User.Role.ADMIN)
        self.ho = make_user("ho2", User.Role.HO_PURCHASING)
        self.client = APIClient()

    def test_list_reads_the_synced_table_no_fallback(self):
        self.client.force_authenticate(self.ho)
        r = self.client.get("/api/v1/tracking/carriers")
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["carriers"][0]["scac"], "MSCU")

    def test_refresh_is_admin_only(self):
        self.client.force_authenticate(self.ho)
        self.assertEqual(
            self.client.post("/api/v1/tracking/carriers/refresh").status_code,
            403)
