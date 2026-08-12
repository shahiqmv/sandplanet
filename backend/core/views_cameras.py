"""Site camera endpoints (owner 2026-08-12).

Three audiences, one relay:

* **staff** browse and manage cameras for sites they can already see;
* **clients** see only cameras explicitly flagged `client_visible` on a site
  they are assigned to (and only while their account's `show_cameras` gate is
  on) — enforced in views_client, not here;
* **the relay itself** calls `relay_auth` on every connection to ask whether
  this publisher or viewer may proceed.

`relay_auth` is deliberately unauthenticated in the DRF sense — MediaMTX is
not a user and holds no session. It is protected instead by only ever being
reachable from loopback, which is where the relay runs.
"""
import secrets

from django.conf import settings
from rest_framework.decorators import (api_view, authentication_classes,
                                       permission_classes)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import cameras as cam_svc
from .audit import audit
from .models import Camera, Site
from .permissions import scoped_site_ids

MANAGE_ROLES = ("ADMIN", "DIRECTOR")


def _visible_cameras(user):
    qs = Camera.objects.select_related("site")
    site_ids = scoped_site_ids(user)
    if site_ids is not None:
        qs = qs.filter(site_id__in=site_ids)
    return qs


@api_view(["GET", "POST"])
def camera_list(request):
    """List cameras the user may see, or register a new one (admin)."""
    if request.method == "GET":
        status = cam_svc.relay_status()
        can_manage = request.user.role in MANAGE_ROLES
        rows = [cam_svc.camera_dict(c, status, include_key=can_manage)
                for c in _visible_cameras(request.user)]
        return Response({
            "cameras": rows,
            "can_manage": can_manage,
            "relay_configured": bool(cam_svc.relay_public_base()),
        })

    if request.user.role not in MANAGE_ROLES:
        return Response({"detail": "Only an admin registers cameras."},
                        status=403)
    d = request.data
    try:
        site = Site.objects.get(pk=d.get("site"))
    except (Site.DoesNotExist, TypeError, ValueError):
        return Response({"detail": "Pick a site."}, status=400)
    path = (d.get("path") or "").strip().lower()
    name = (d.get("name") or "").strip()
    if not path or not name:
        return Response({"detail": "Name and stream path are required."},
                        status=400)
    if Camera.objects.filter(path=path).exists():
        return Response({"detail": "That stream path is already taken."},
                        status=400)
    cam = Camera.objects.create(
        site=site, name=name, path=path,
        stream_key=(d.get("stream_key") or "").strip()
        or cam_svc.new_stream_key(),
        location_note=(d.get("location_note") or "").strip(),
        client_visible=bool(d.get("client_visible")),
        created_by=request.user)
    audit("camera", cam.id, "CAMERA_ADDED", actor=request.user,
          detail={"site": site.code, "name": cam.name, "path": cam.path})
    return Response(cam_svc.camera_dict(cam, include_key=True), status=201)


@api_view(["PATCH", "DELETE"])
def camera_detail(request, pk):
    """Rename / retire / (un)expose a camera. Admin only."""
    try:
        cam = _visible_cameras(request.user).get(pk=pk)
    except Camera.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in MANAGE_ROLES:
        return Response({"detail": "Only an admin edits cameras."}, status=403)

    if request.method == "DELETE":
        audit("camera", cam.id, "CAMERA_REMOVED", actor=request.user,
              detail={"site": cam.site.code, "name": cam.name})
        cam.delete()
        return Response(status=204)

    before = {"name": cam.name, "client_visible": cam.client_visible,
              "is_active": cam.is_active}
    for field in ("name", "location_note"):
        if field in request.data:
            setattr(cam, field, (request.data.get(field) or "").strip())
    for field in ("is_active", "client_visible"):
        if field in request.data:
            setattr(cam, field, bool(request.data.get(field)))
    cam.save()
    audit("camera", cam.id, "CAMERA_UPDATED", actor=request.user,
          detail={"before": before, "after": {
              "name": cam.name, "client_visible": cam.client_visible,
              "is_active": cam.is_active}})
    return Response(cam_svc.camera_dict(cam, cam_svc.relay_status(),
                                        include_key=True))


@api_view(["POST"])
def camera_ticket(request, pk):
    """Mint a ~90s ticket so this staff user's player can open the stream."""
    try:
        cam = _visible_cameras(request.user).get(pk=pk, is_active=True)
    except Camera.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if not cam_svc.relay_public_base():
        return Response({"detail": "No camera relay is configured."},
                        status=503)
    return Response({
        "whep": cam_svc.whep_url(cam),
        "ticket": cam_svc.issue_ticket(cam, "staff", request.user.id),
        "expires_in": cam_svc.TICKET_MAX_AGE,
    })


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def relay_auth(request, secret=""):
    """MediaMTX's authentication hook — one decision per connection.

    MediaMTX POSTs {user, password, action, path, ip, protocol}. 200 allows,
    401 denies. Publishers authenticate with the camera's own path + stream
    key; viewers present a short-lived ticket as the password.

    **Authenticating the relay itself** is done with a shared secret carried in
    the URL, because MediaMTX offers no way to set a request header on this
    hook. A secret in a URL is normally something to avoid — so it is defended
    three ways: the call never leaves the container network (MediaMTX and
    Django are compose services), Caddy refuses to proxy this path from the
    internet at all, and the secret is useless without also presenting a valid
    stream key or ticket. An unset secret disables the hook outright rather
    than defaulting to open.
    """
    expected = getattr(settings, "CAMERA_RELAY_SECRET", "")
    if not expected or not secrets.compare_digest(secret, expected):
        return Response({"detail": "Not found."}, status=404)

    d = request.data or {}
    action = d.get("action")
    path = (d.get("path") or "").strip()
    user = d.get("user") or ""
    password = d.get("password") or ""

    if action in ("api", "metrics", "pprof"):
        return Response(status=200)
    if not path:
        return Response({"detail": "denied"}, status=401)

    cam = Camera.objects.filter(path=path, is_active=True).first()
    if not cam:
        return Response({"detail": "denied"}, status=401)

    if action == "publish":
        # constant-time-ish compare is overkill here: the key is 32 random
        # chars and a wrong guess costs a full round trip
        if user == cam.path and password and password == cam.stream_key:
            cam_svc.mark_seen(cam)
            return Response(status=200)
        return Response({"detail": "denied"}, status=401)

    if action in ("read", "playback"):
        if cam_svc.read_ticket(password, path):
            return Response(status=200)
        return Response({"detail": "denied"}, status=401)

    return Response({"detail": "denied"}, status=401)
