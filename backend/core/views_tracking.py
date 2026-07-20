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
        health = t.state
        if t.state == ShipmentTracking.State.ACTIVE and trk.is_stale(t):
            health = "STALE"
        rows.append({
            "ipr_ref": doc.ref, "shipment_seq": t.shipment.seq,
            "mode": t.mode, "carrier_scac": t.carrier_scac,
            "tracking_key": t.tracking_key, "state": t.state,
            "health": health, "raw_status": t.raw_status,
            "current_eta": t.current_eta, "last_event_at": t.last_event_at,
            "provider_tracking_id": t.provider_tracking_id,
            "map_url": t.map_url, "last_error": t.last_error,
            "register_attempts": t.register_attempts})
    return Response({"items": rows})


@api_view(["POST"])
def tracking_retry(request, pk):
    """Re-attempt registration of a PENDING/FAILED tracking."""
    if request.user.role not in MANAGE:
        return Response({"detail": "Head Office manages tracking."}, status=403)
    t = ShipmentTracking.objects.filter(shipment_id=pk).first()
    if t is None:
        t = trk.ensure_tracking(_shipment_for(request, pk))
    if t is None:
        return Response({"detail": "No tracking key on this shipment."},
                        status=400)
    if t.state == ShipmentTracking.State.FAILED:
        t.state = ShipmentTracking.State.PENDING
        t.save(update_fields=["state", "updated_at"])
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
