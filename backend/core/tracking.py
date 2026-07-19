"""Shipment tracking — provider-agnostic core (D40/D41).

All carrier-API specifics live behind the `TrackingProvider` interface and its
concrete adapters (e.g. `tracking_shipsgo`). Planet core here only ever deals in
normalised `Snapshot` / `NormEvent` values and persists them onto the
`ShipmentTracking` / `TrackingEvent` models. Swapping or adding a provider means
adding an adapter, nothing here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from django.utils import timezone

# ---- Validation of tracking keys (checked at data entry, not registration) ---

_CONTAINER_RE = re.compile(r"^[A-Z]{4}[0-9]{7}$")
_BOOKING_RE = re.compile(r"^[A-Za-z0-9/-]{5,}$")


def normalise_key(value: str) -> str:
    return (value or "").strip().upper().replace(" ", "")


def is_valid_container(value: str) -> bool:
    return bool(_CONTAINER_RE.match(normalise_key(value)))


def is_valid_booking(value: str) -> bool:
    return bool(_BOOKING_RE.match((value or "").strip()))


def is_valid_awb(value: str) -> bool:
    """IATA 11-digit AWB: 3-digit airline prefix + 7-digit serial + check
    digit, where the check digit = serial mod 7."""
    v = normalise_key(value).replace("-", "")
    if not (len(v) == 11 and v.isdigit()):
        return False
    serial = int(v[3:10])
    return serial % 7 == int(v[10])


def validate_shipment_keys(mode: str, bl_no: str, container_awb: str,
                           carrier_scac: str = "") -> Optional[str]:
    """Return an error string for a malformed tracking key, else None. Empty
    keys are allowed (a shipment may be entered before its docs are in)."""
    if mode == "AIR":
        if container_awb and not is_valid_awb(container_awb):
            return ("The AWB must be 11 digits (3-digit airline prefix + "
                    "7-digit serial + check digit).")
        return None
    # sea
    if bl_no and not is_valid_booking(bl_no):
        return "The booking / B/L number looks malformed."
    if container_awb and not is_valid_container(container_awb):
        return ("The container number must be 4 letters + 7 digits, "
                "e.g. MSCU1234567.")
    if carrier_scac and not re.match(r"^(SG_)?[A-Z0-9]{4}$", carrier_scac):
        return "The carrier code (SCAC) looks malformed."
    return None


# ---- Normalised value objects the adapters return ---------------------------

@dataclass
class NormEvent:
    code: str                      # TrackingEvent.Code
    provider_event_code: str = ""  # DEPA / ARR / …
    provider_event_id: str = ""    # stable id for idempotency
    description: str = ""
    location: str = ""
    vessel_flight: str = ""
    event_time: Optional[datetime] = None
    is_actual: bool = True
    eta_at_event: Optional[datetime] = None
    raw: dict = field(default_factory=dict)


@dataclass
class Snapshot:
    """The normalised state of one shipment as seen by a provider."""
    provider_tracking_id: str = ""
    raw_status: str = ""
    eta: Optional[datetime] = None
    eta_initial: Optional[datetime] = None
    map_url: str = ""
    arrived: bool = False
    untracked: bool = False
    events: list = field(default_factory=list)   # [NormEvent]


class TrackingProvider:
    """Adapter interface. Concrete providers implement all three."""

    name = "base"

    def register(self, tracking) -> Snapshot:            # pragma: no cover
        raise NotImplementedError

    def fetch(self, tracking) -> Snapshot:               # pragma: no cover
        raise NotImplementedError

    def parse_webhook(self, request):                    # pragma: no cover
        """Verify authenticity and return (ref_or_provider_id, Snapshot) or
        raise PermissionError on a bad secret."""
        raise NotImplementedError


def get_provider(name: str = "shipsgo") -> TrackingProvider:
    from . import tracking_shipsgo
    if name == "shipsgo":
        return tracking_shipsgo.ShipsGoProvider()
    raise ValueError(f"Unknown tracking provider '{name}'")


# ---- Persisting a snapshot onto the models (idempotent) ----------------------

def apply_snapshot(tracking, snapshot: Snapshot, source: str):
    """Fold a provider Snapshot into the tracking + its events. Idempotent on
    provider_event_id. Returns the list of TrackingEvent rows newly created and
    whether the ETA slipped past the configured threshold — the caller decides
    on notifications so this stays free of notification plumbing."""
    from django.conf import settings

    from .models import TrackingEvent

    created = []
    for ev in snapshot.events:
        if ev.provider_event_id and TrackingEvent.objects.filter(
                tracking=tracking,
                provider_event_id=ev.provider_event_id).exists():
            continue
        row = TrackingEvent.objects.create(
            tracking=tracking, code=ev.code,
            provider_event_code=ev.provider_event_code,
            provider_event_id=ev.provider_event_id,
            description=ev.description, location=ev.location,
            vessel_flight=ev.vessel_flight, event_time=ev.event_time,
            is_actual=ev.is_actual, eta_at_event=ev.eta_at_event,
            source=source, raw=ev.raw)
        created.append(row)

    # ETA-slip detection (compare against what we last held)
    slip_hours = getattr(settings, "TRACKING_ETA_SLIP_HOURS", 24)
    eta_slipped = False
    if snapshot.eta and tracking.current_eta:
        delta = abs((snapshot.eta - tracking.current_eta).total_seconds())
        if delta >= slip_hours * 3600:
            eta_slipped = True
            TrackingEvent.objects.create(
                tracking=tracking, code=TrackingEvent.Code.ETA_UPDATED,
                description=f"ETA updated to {snapshot.eta:%Y-%m-%d}",
                event_time=timezone.now(), is_actual=False,
                eta_at_event=snapshot.eta, source=source,
                provider_event_id=f"eta:{snapshot.eta.isoformat()}",
                raw={"eta": snapshot.eta.isoformat()})

    # update header fields
    if snapshot.provider_tracking_id:
        tracking.provider_tracking_id = snapshot.provider_tracking_id
    if snapshot.raw_status:
        tracking.raw_status = snapshot.raw_status
    if snapshot.map_url:
        tracking.map_url = snapshot.map_url
    if snapshot.eta:
        if tracking.eta_initial is None:
            tracking.eta_initial = snapshot.eta_initial or snapshot.eta
        tracking.current_eta = snapshot.eta
    if created:
        tracking.last_event_at = max(
            (e.event_time for e in created if e.event_time),
            default=tracking.last_event_at) or timezone.now()
    if snapshot.arrived and tracking.state == tracking.State.ACTIVE:
        tracking.state = tracking.State.ARRIVED
    elif tracking.state == tracking.State.PENDING and not snapshot.untracked:
        tracking.state = tracking.State.ACTIVE
    tracking.save()
    # mirror the live ETA onto the shipment for existing views
    if snapshot.eta and tracking.shipment_id:
        sh = tracking.shipment
        sh.eta = snapshot.eta.date()
        if snapshot.map_url:
            sh.carrier_link = snapshot.map_url
        sh.save(update_fields=["eta", "carrier_link"])
    return {"created": created, "eta_slipped": eta_slipped}
