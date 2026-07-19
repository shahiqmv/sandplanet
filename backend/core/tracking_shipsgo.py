"""ShipsGo API v2 adapter (D40). Ocean + air share one host and token.

Docs: https://api.shipsgo.com/v2 — auth header `X-Shipsgo-User-Token`.
This module is the ONLY place ShipsGo request/response shapes appear; it returns
provider-agnostic `Snapshot`/`NormEvent` values to `tracking.py`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.request
from datetime import timezone as _tz

from django.conf import settings
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_naive, make_aware

from .models import TrackingEvent
from .tracking import NormEvent, Snapshot, TrackingProvider

# ShipsGo movement code → normalised milestone. Location context (origin /
# discharge / transshipment) refines DEPARTED vs ARRIVED vs TRANSSHIPMENT.
_OCEAN_ARRIVAL = {"ARRV", "DISC"}
_OCEAN_DEPART = {"DEPA"}
_OCEAN_TS = {"DISC", "LOAD"}
_AIR_ARRIVAL = {"ARR", "RCF", "DLV"}
_AIR_DEPART = {"DEP"}
_OCEAN_ARRIVED_STATUS = {"ARRIVED", "DISCHARGED"}
_AIR_ARRIVED_STATUS = {"LANDED", "DELIVERED"}


class ShipsGoError(Exception):
    def __init__(self, message, status=None, insufficient_credits=False):
        super().__init__(message)
        self.status = status
        self.insufficient_credits = insufficient_credits


def _dt(value):
    if not value:
        return None
    d = parse_datetime(value)
    if d is None:
        return None
    return make_aware(d, _tz.utc) if is_naive(d) else d


class ShipsGoProvider(TrackingProvider):
    name = "shipsgo"

    def _base(self):
        return getattr(settings, "SHIPSGO_BASE_URL",
                       "https://api.shipsgo.com/v2").rstrip("/")

    def _request(self, method, path, body=None):
        key = getattr(settings, "SHIPSGO_API_KEY", "")
        if not key:
            raise ShipsGoError("SHIPSGO_API_KEY is not configured.")
        url = f"{self._base()}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-Shipsgo-User-Token", key)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            payload = ""
            try:
                payload = e.read().decode()
            except Exception:               # pragma: no cover - defensive
                pass
            low = payload.lower()
            credits = e.code in (402, 403) and "credit" in low
            raise ShipsGoError(f"ShipsGo {e.code}: {payload[:300]}",
                               status=e.code, insufficient_credits=credits)
        except urllib.error.URLError as e:  # pragma: no cover - network
            raise ShipsGoError(f"ShipsGo unreachable: {e.reason}")

    # -- adapter interface ---------------------------------------------------

    def register(self, tracking) -> Snapshot:
        if tracking.mode == "AIR":
            body = {"reference": tracking.provider_ref,
                    "awb_number": tracking.tracking_key}
            resp = self._request("POST", "/air/shipments", body)
        else:
            body = {"reference": tracking.provider_ref}
            if tracking.carrier_scac:
                body["carrier"] = tracking.carrier_scac
            # a container number is a stronger key than a booking/BL
            key = tracking.tracking_key
            from .tracking import is_valid_container
            if is_valid_container(key):
                body["container_number"] = key
            else:
                body["booking_number"] = key
            resp = self._request("POST", "/ocean/shipments", body)
        return self._normalise(resp.get("shipment") or {}, tracking.mode)

    def fetch(self, tracking) -> Snapshot:
        leg = "air" if tracking.mode == "AIR" else "ocean"
        sid = tracking.provider_tracking_id
        resp = self._request("GET", f"/{leg}/shipments/{sid}")
        return self._normalise(resp.get("shipment") or {}, tracking.mode)

    def parse_webhook(self, request):
        # ShipsGo signs each delivery with HMAC-SHA256 over the raw body using
        # the dashboard Secret Key, in the X-Shipsgo-Webhook-Signature header.
        secret = getattr(settings, "SHIPSGO_WEBHOOK_SECRET", "")
        signature = request.headers.get("X-Shipsgo-Webhook-Signature", "")
        raw = request.body                                  # bytes, verbatim
        if not secret or not signature:
            raise PermissionError("Missing webhook secret or signature.")
        expected = hmac.new(secret.encode(), raw,
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):   # constant-time
            raise PermissionError("Bad webhook signature.")
        body = json.loads(raw.decode() or "{}")
        shipment = body.get("shipment") or {}
        mode = "AIR" if "awb_number" in shipment else "SEA"
        snap = self._normalise(shipment, mode)
        ref = shipment.get("reference") or str(shipment.get("id") or "")
        return ref, snap

    # -- normalisation -------------------------------------------------------

    def _normalise(self, s: dict, mode: str) -> Snapshot:
        return (self._normalise_air(s) if mode == "AIR"
                else self._normalise_ocean(s))

    def _normalise_ocean(self, s: dict) -> Snapshot:
        route = s.get("route") or {}
        pol = (((route.get("port_of_loading") or {}).get("location")) or {})
        pod = (((route.get("port_of_discharge") or {}).get("location")) or {})
        pol_code, pod_code = pol.get("code"), pod.get("code")
        disc = route.get("port_of_discharge") or {}
        status = s.get("status") or ""
        snap = Snapshot(
            provider_tracking_id=str(s.get("id") or ""), raw_status=status,
            eta=_dt(disc.get("date_of_discharge")),
            eta_initial=_dt(disc.get("date_of_discharge_initial")),
            map_url=((s.get("tokens") or {}).get("map") or ""),
            arrived=status in _OCEAN_ARRIVED_STATUS,
            untracked=status == "UNTRACKED")
        for cont in s.get("containers") or []:
            cno = cont.get("number") or ""
            for mv in cont.get("movements") or []:
                ev = mv.get("event") or ""
                loc = mv.get("location") or {}
                code = loc.get("code")
                name = loc.get("name") or code or ""
                norm = TrackingEvent.Code.OTHER
                if ev in _OCEAN_DEPART and code == pol_code:
                    norm = TrackingEvent.Code.DEPARTED
                elif ev in _OCEAN_ARRIVAL and code == pod_code:
                    norm = TrackingEvent.Code.ARRIVED
                elif ev in _OCEAN_TS and code not in (pol_code, pod_code):
                    norm = TrackingEvent.Code.TRANSSHIPMENT
                snap.events.append(NormEvent(
                    code=norm, provider_event_code=ev,
                    provider_event_id=f"{cno}:{ev}:{code}:"
                                      f"{mv.get('timestamp')}",
                    description=f"{ev} at {name}",
                    location=name,
                    vessel_flight=((mv.get("vessel") or {}).get("name") or ""),
                    event_time=_dt(mv.get("timestamp")),
                    is_actual=mv.get("status") == "ACT",
                    raw=mv))
        return snap

    def _normalise_air(self, s: dict) -> Snapshot:
        route = s.get("route") or {}
        origin = (route.get("origin") or {})
        dest = (route.get("destination") or {})
        o_code = (origin.get("location") or origin).get("iata") \
            if isinstance(origin, dict) else None
        d_code = (dest.get("location") or dest).get("iata") \
            if isinstance(dest, dict) else None
        status = s.get("status") or ""
        snap = Snapshot(
            provider_tracking_id=str(s.get("id") or ""), raw_status=status,
            eta=_dt(dest.get("date_of_arrival") or dest.get("date")),
            map_url=((s.get("tokens") or {}).get("map") or ""),
            arrived=status in _AIR_ARRIVED_STATUS,
            untracked=status == "UNTRACKED")
        for mv in s.get("movements") or []:
            ev = mv.get("event") or ""
            loc = mv.get("location") or {}
            code = loc.get("iata")
            name = loc.get("name") or code or ""
            norm = TrackingEvent.Code.OTHER
            if ev in _AIR_DEPART and code == o_code:
                norm = TrackingEvent.Code.DEPARTED
            elif ev in _AIR_ARRIVAL and code == d_code:
                norm = TrackingEvent.Code.ARRIVED
            elif ev in (_AIR_ARRIVAL | _AIR_DEPART) \
                    and code not in (o_code, d_code):
                norm = TrackingEvent.Code.TRANSSHIPMENT
            snap.events.append(NormEvent(
                code=norm, provider_event_code=ev,
                provider_event_id=f"{ev}:{code}:{mv.get('timestamp')}",
                description=f"{ev} at {name}", location=name,
                vessel_flight=(mv.get("flight") or ""),
                event_time=_dt(mv.get("timestamp")),
                is_actual=mv.get("status") == "ACT", raw=mv))
        return snap
