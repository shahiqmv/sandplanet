"""Shipment-tracking API + ShipsGo webhook (D40).

- Purchasing-facing: carrier picklist, tracking-health screen, retry, and the
  manual-fallback controls (switch to manual, log a milestone).
- The ShipsGo webhook is a public, secret-verified endpoint (no session auth).
"""
import json

from rest_framework.decorators import (api_view, authentication_classes,
                                        permission_classes)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import tracking as trk
from .models import ImportShipment, ShipmentTracking, TrackingEvent

MANAGE = ("HO_PURCHASING", "ADMIN")


def _shipment_for(request, pk):
    return ImportShipment.objects.filter(pk=pk).select_related(
        "order__document").first()


@api_view(["GET"])
def tracking_carriers(request):
    """The full ocean-carrier picklist for the shipment form, read from the
    locally-synced table (ShipsGo v2 list, ~130+ lines). Never substitutes a
    stub list: if the sync has never run or last failed, we say so and return
    whatever we have, so the UI can show a stale banner instead of pretending."""
    from . import carriers as csvc
    from .models import TrackingCarrier
    rows = [{"scac": c.scac, "name": c.name, "status": c.status}
            for c in TrackingCarrier.objects.all()]
    state = csvc.sync_state()
    return Response({
        "carriers": rows, "count": len(rows),
        "synced_at": (state or {}).get("at"),
        "sync_ok": bool(state and state.get("ok")),
        "sync_error": (state or {}).get("error", "") if state else "",
        "never_synced": state is None,
    })


@api_view(["POST"])
def tracking_carriers_refresh(request):
    """Admin 'refresh now' — re-sync the carrier list from the provider.
    On failure the existing list is kept and Purchasing/admin are alerted."""
    if request.user.role != "ADMIN":
        return Response({"detail": "Only an administrator can refresh the "
                                   "carrier list."}, status=403)
    from . import carriers as csvc
    ok, result = csvc.sync_carriers()
    if not ok:
        from . import notify
        notify.notify_carrier_sync_failed(str(result))
        return Response({"detail": f"Carrier sync failed: {result}"},
                        status=502)
    return Response({"count": result})


@api_view(["GET"])
def tracking_health(request):
    """Admin health screen: one row per tracked shipment with its live state."""
    if request.user.role not in MANAGE:
        return Response({"detail": "Head Office manages tracking."}, status=403)
    rows = []
    qs = ShipmentTracking.objects.select_related(
        "shipment__order__document").order_by("-updated_at")
    for t in qs:
        doc = t.shipment.order.document
        health = trk.health_for(t)
        rows.append({
            "ipr_ref": doc.ref, "shipment_seq": t.shipment.seq,
            "shipment_id": t.shipment_id,
            "mode": t.mode, "carrier_scac": t.carrier_scac,
            "tracking_key": t.tracking_key, "state": t.state,
            "health": health, "raw_status": t.raw_status,
            "reason": trk.reason_for(t, health),
            "current_eta": t.current_eta, "last_event_at": t.last_event_at,
            "last_polled_at": t.last_polled_at, "registered_at": t.created_at,
            "provider_tracking_id": t.provider_tracking_id,
            "map_url": t.map_url, "last_error": t.last_error,
            "register_attempts": t.register_attempts,
            "movements": trk.movements_for(t)})
    return Response({"items": rows})


@api_view(["POST"])
def tracking_retry(request, pk):
    """Re-attempt tracking: re-sync the shipment's current keys and force a fresh
    registration — for a failed/pending tracking OR an active one the provider
    can't resolve (owner 2026-08-06). Arrived / manual shipments are left alone."""
    if request.user.role not in MANAGE:
        return Response({"detail": "Head Office manages tracking."}, status=403)
    ship = _shipment_for(request, pk)
    if ship is None:
        return Response({"detail": "Not found."}, status=404)
    t = ShipmentTracking.objects.filter(shipment_id=pk).first() \
        or trk.ensure_tracking(ship)
    if t is None:
        return Response({"detail": "No tracking key on this shipment."},
                        status=400)
    if t.state in (ShipmentTracking.State.ARRIVED, ShipmentTracking.State.MANUAL):
        return Response({"state": t.state, "error": ""})
    key = (ship.container_awb.strip() if ship.mode == "AIR"
           else trk._sea_key(ship))
    new_key = trk.normalise_key(key) if key else t.tracking_key
    new_scac = (ship.carrier_scac or "").strip().upper()
    # A genuinely new key/carrier earns a fresh attempt budget; retrying the same
    # key doesn't, so a persistent provider error still surfaces as Failed.
    if new_key != t.tracking_key or new_scac != t.carrier_scac:
        t.register_attempts = 0
    t.tracking_key = new_key
    t.carrier_scac = new_scac
    t.mode = ship.mode
    t.raw_status = ""
    t.last_error = ""
    t.state = ShipmentTracking.State.PENDING
    t.save()
    trk.register_tracking(t)
    t.refresh_from_db()
    return Response({"state": t.state, "error": t.last_error})


@api_view(["POST"])
def tracking_manual(request, pk):
    """Switch a tracking to MANUAL, or log a manual milestone on it."""
    if request.user.role not in MANAGE:
        return Response({"detail": "Head Office manages tracking."}, status=403)
    sh = _shipment_for(request, pk)
    if sh is None:
        return Response({"detail": "Not found."}, status=404)
    t = trk.ensure_tracking(sh)
    if t is None:
        return Response({"detail": "No tracking key on this shipment."},
                        status=400)
    action = request.data.get("action")
    if action == "switch":
        trk.switch_manual(t)
        return Response({"state": t.state})
    if action == "event":
        code = request.data.get("code")
        if code not in TrackingEvent.Code.values:
            return Response({"detail": "Unknown milestone."}, status=400)
        et = request.data.get("event_time")
        trk.add_manual_event(
            t, code, request.data.get("description", ""),
            location=request.data.get("location", ""),
            vessel_flight=request.data.get("vessel_flight", ""),
            event_time=et or timezone.now())
        if t.state == ShipmentTracking.State.PENDING:
            t.state = ShipmentTracking.State.MANUAL
            t.save(update_fields=["state", "updated_at"])
        return Response({"ok": True})
    return Response({"detail": "action must be 'switch' or 'event'."},
                    status=400)


@csrf_exempt
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def shipsgo_webhook(request):
    """ShipsGo posts shipment create/update events here. Secret-verified,
    idempotent on provider event id. Matches the tracking by our reference
    (preferred) or the provider tracking id."""
    provider = trk.get_provider("shipsgo")
    try:
        ref, snapshot = provider.parse_webhook(request)
    except PermissionError:
        return Response({"detail": "Unauthorised."}, status=401)
    except (json.JSONDecodeError, ValueError):
        return Response({"detail": "Bad payload."}, status=400)
    t = (ShipmentTracking.objects.filter(provider_ref=ref).first()
         or ShipmentTracking.objects.filter(
             provider_tracking_id=snapshot.provider_tracking_id).first())
    if t is None:
        # unknown shipment (e.g. registered outside Planet) — ack so ShipsGo
        # doesn't retry forever, but do nothing.
        return Response({"detail": "No matching tracking."}, status=202)
    if t.state == ShipmentTracking.State.PENDING:
        t.state = ShipmentTracking.State.ACTIVE
    trk.ingest_snapshot(t, snapshot, source=TrackingEvent.Source.WEBHOOK)
    return Response({"ok": True})
