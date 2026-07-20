"""Carrier list sync — pulls the full ShipsGo ocean-carrier list into the local
`TrackingCarrier` table so the shipment form can offer all ~130+ lines.

ShipsGo v2 `GET /ocean/carriers` is paginated (skip/take, take max 100, response
`meta.more`). Names/SCACs are stored verbatim — the provider requires the
carrier value in tracking requests to match its list, so we never normalise.

Failures never wipe the existing list or fall back to a stub: the caller alerts
an admin and the UI keeps showing the last good list with a stale banner.
"""
import logging

from django.utils import timezone

log = logging.getLogger(__name__)

SYNC_KEY = "tracking_carriers_sync"
_TAKE = 100


def sync_state():
    """The last sync result: {at, ok, count, error} — or None if never run."""
    from .models import CompanyParameter
    row = CompanyParameter.objects.filter(key=SYNC_KEY).first()
    return row.value if row else None


def _save_state(ok, count, error=""):
    from .models import CompanyParameter
    CompanyParameter.objects.update_or_create(
        key=SYNC_KEY, defaults={"value": {
            "at": timezone.now().isoformat(), "ok": ok,
            "count": count, "error": error[:300]},
            "description": "Last tracking-carrier sync result."})


def sync_carriers(provider_name="shipsgo"):
    """Fetch every page of the provider's ocean carriers and upsert them.
    Returns (ok: bool, count_or_error). Existing rows are preserved on failure.
    """
    from .models import TrackingCarrier
    from .tracking import get_provider
    provider = get_provider(provider_name)
    try:
        rows = provider.list_carriers()          # [{scac, name, status}, …]
    except Exception as e:                        # network / auth / provider
        log.exception("carrier sync failed")
        _save_state(False, TrackingCarrier.objects.filter(
            provider=provider_name).count(), str(e))
        return False, str(e)

    seen = set()
    for c in rows:
        scac = (c.get("scac") or "").strip()
        name = (c.get("name") or "").strip()
        if not scac or not name:
            continue
        TrackingCarrier.objects.update_or_create(
            provider=provider_name, scac=scac,
            defaults={"name": name, "status": c.get("status") or "ACTIVE"})
        seen.add(scac)
    # drop carriers the provider no longer lists (kept the table in step with it)
    TrackingCarrier.objects.filter(provider=provider_name).exclude(
        scac__in=seen).delete()
    _save_state(True, len(seen))
    return True, len(seen)
