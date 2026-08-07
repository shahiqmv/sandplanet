"""Local-vessel tracking endpoints (FollowMe) — Planet proxies the provider so
the API key never reaches the browser (owner 2026-08-07). Read-only; any signed-in
internal user (sites + purchasing) may look up vessels."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import followme


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def vessels_list(request):
    """Search/browse public vessels — filter by name (q), type and atoll. Feeds
    the Loading-Manifest vessel picker and the 'vessels nearby' browse."""
    try:
        vessels = followme.list_vessels()
    except followme.FollowMeError as e:
        return Response({"detail": str(e)}, status=503)
    q = (request.GET.get("q") or "").strip().lower()
    vtype = (request.GET.get("type") or "").strip().lower()
    atoll = (request.GET.get("atoll") or "").strip().upper()
    supply = request.GET.get("supply") == "1"
    out = []
    for v in vessels:
        if q and q not in v["name"].lower():
            continue
        if vtype and vtype not in v["type"].lower():
            continue
        if atoll and v["atoll"] != atoll:
            continue
        if supply and not _is_supply(v["type"]):
            continue
        out.append(v)
    atolls = sorted({v["atoll"] for v in vessels if v["atoll"]})
    types = sorted({v["type"] for v in vessels if v["type"]})
    return Response({"vessels": out[:500], "total": len(out),
                     "atolls": atolls, "types": types})


_SUPPLY = ("supply", "cargo", "landing craft", "tug", "dhoni")


def _is_supply(vtype):
    t = (vtype or "").lower()
    return any(k in t for k in _SUPPLY)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def vessel_detail(request, vid):
    """One vessel's live position (lat/lon/course/speed/last-seen)."""
    try:
        v = followme.vessel(vid)
    except followme.FollowMeError as e:
        return Response({"detail": str(e)}, status=503)
    if not v:
        return Response({"detail": "Vessel not found."}, status=404)
    return Response(v)
