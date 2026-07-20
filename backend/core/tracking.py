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


def _iso6346_check_digit(container: str) -> int:
    """The ISO 6346 check digit for the first 10 chars of a container number.
    Letters map A=10,B=12,… skipping every multiple of 11; each of the 10 chars
    is weighted by 2**position; the check digit is the weighted sum mod 11
    (10 wraps to 0)."""
    letters, v = {}, 10
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if v % 11 == 0:
            v += 1
        letters[ch] = v
        v += 1
    total = 0
    for i, ch in enumerate(container[:10]):
        n = letters[ch] if ch.isalpha() else int(ch)
        total += n * (2 ** i)
    return total % 11 % 10


def is_valid_container(value: str) -> bool:
    """4 letters + 7 digits with a correct ISO 6346 check digit."""
    v = normalise_key(value)
    if not _CONTAINER_RE.match(v):
        return False
    try:
        return int(v[10]) == _iso6346_check_digit(v)
    except (KeyError, ValueError):          # pragma: no cover - regex guards
        return False


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
        return ("The container number must be 4 letters + 7 digits with a "
                "valid ISO 6346 check digit (e.g. CSQU3054383).")
    if (bl_no and container_awb
            and normalise_key(bl_no) == normalise_key(container_awb)):
        return ("The B/L field holds the same value as the container — the "
                "B/L field is for the carrier's master B/L only.")
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

    def list_carriers(self):                             # pragma: no cover
        """[{scac, name, status}, …] — the full carrier list."""
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


# ---- Registration + lifecycle service ---------------------------------------

def _sea_key(shipment):
    """Prefer the booking / master B/L (one credit per B/L) over a container."""
    return (shipment.bl_no or "").strip() or normalise_key(
        shipment.container_awb)


def ensure_tracking(shipment):
    """Create the PENDING ShipmentTracking for a shipment from its entered keys
    (if it has none and a key is present). Idempotent."""
    from .models import ShipmentTracking
    existing = ShipmentTracking.objects.filter(shipment=shipment).first()
    if existing:
        return existing
    key = (shipment.container_awb.strip() if shipment.mode == "AIR"
           else _sea_key(shipment))
    if not key:
        return None
    return ShipmentTracking.objects.create(
        shipment=shipment, mode=shipment.mode,
        carrier_scac=(shipment.carrier_scac or "").strip().upper(),
        tracking_key=normalise_key(key),
        provider_ref=f"{shipment.order.document.ref}-S{shipment.seq}",
        state=ShipmentTracking.State.PENDING)


def register_tracking(tracking, max_attempts=5):
    """Call the provider to register the tracking. On success → ACTIVE + fold
    the first snapshot. On insufficient credits or after max_attempts → FAILED.
    Never raises — registration must not break the shipment workflow."""
    from .models import ShipmentTracking
    from .tracking_shipsgo import ShipsGoError
    if tracking.state not in (ShipmentTracking.State.PENDING,):
        return {"skipped": True}
    tracking.register_attempts += 1
    try:
        snap = get_provider(tracking.provider).register(tracking)
    except ShipsGoError as e:
        tracking.last_error = str(e)[:300]
        if e.insufficient_credits or tracking.register_attempts >= max_attempts:
            tracking.state = ShipmentTracking.State.FAILED
        tracking.save()
        if tracking.state == ShipmentTracking.State.FAILED:
            from . import notify
            notify.notify_tracking_problem(tracking, "failed")
        return {"error": str(e), "credits": e.insufficient_credits,
                "failed": tracking.state == ShipmentTracking.State.FAILED}
    except Exception as e:                  # pragma: no cover - defensive
        tracking.last_error = str(e)[:300]
        tracking.save()
        return {"error": str(e)}
    tracking.credits_consumed = True
    tracking.last_error = ""
    tracking.state = ShipmentTracking.State.ACTIVE
    tracking.save()
    return ingest_snapshot(tracking, snap, source="POLL")


def ingest_snapshot(tracking, snapshot, source):
    """apply_snapshot + fire the milestone notifications for anything new."""
    from . import notify
    result = apply_snapshot(tracking, snapshot, source)
    if result["created"] or result["eta_slipped"]:
        notify.notify_tracking(tracking, result)
    return result


def switch_manual(tracking):
    tracking.state = tracking.State.MANUAL
    tracking.save(update_fields=["state", "updated_at"])


def add_manual_event(tracking, code, description, location="",
                     vessel_flight="", event_time=None):
    """Purchasing logs a milestone by hand (gapped carrier / mid-voyage
    failure). Renders identically to an automatic one."""
    from .models import TrackingEvent
    return TrackingEvent.objects.create(
        tracking=tracking, code=code, description=description,
        location=location, vessel_flight=vessel_flight,
        event_time=event_time or timezone.now(), is_actual=True,
        source=TrackingEvent.Source.MANUAL)


def is_stale(tracking, days=7):
    """No event in `days` and not yet arrived — a candidate for a stale alert."""
    if tracking.state != tracking.State.ACTIVE:
        return False
    ref = tracking.last_event_at or tracking.created_at
    return (timezone.now() - ref).days >= days
