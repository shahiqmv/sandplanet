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
                                       parser_classes,
                                       permission_classes)
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
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
        source_url=(d.get("source_url") or "").strip(),
        client_visible=bool(d.get("client_visible")),
        created_by=request.user)
    ok, note = cam_svc.sync_relay_path(cam)
    audit("camera", cam.id, "CAMERA_ADDED", actor=request.user,
          detail={"site": site.code, "name": cam.name, "path": cam.path,
                  "mode": "PULL" if cam.source_url else "PUSH"})
    return Response({**cam_svc.camera_dict(cam, include_key=True),
                     "relay": note, "relay_ok": ok}, status=201)


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
        cam.source_url = ""          # so the relay stops pulling it
        cam_svc.sync_relay_path(cam)
        cam.delete()
        return Response(status=204)

    before = {"name": cam.name, "client_visible": cam.client_visible,
              "is_active": cam.is_active}
    for field in ("name", "location_note", "source_url"):
        if field in request.data:
            setattr(cam, field, (request.data.get(field) or "").strip())
    for field in ("is_active", "client_visible"):
        if field in request.data:
            setattr(cam, field, bool(request.data.get(field)))
    cam.save()
    ok, note = cam_svc.sync_relay_path(cam)
    audit("camera", cam.id, "CAMERA_UPDATED", actor=request.user,
          detail={"before": before, "after": {
              "name": cam.name, "client_visible": cam.client_visible,
              "is_active": cam.is_active}})
    return Response({**cam_svc.camera_dict(cam, cam_svc.relay_status(),
                                           include_key=True),
                     "relay": note, "relay_ok": ok})


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


# ---- site time-lapse: weekly uploads joined per camera (owner 2026-10-13) ----

def _tl_sites(request):
    return scoped_site_ids(request.user)


def _tl_site_choices(ids):
    """The sites this user works with — a site team's own site only — each
    with the projects a camera can be marked against."""
    from .models import Project
    sites = Site.objects.exclude(status=Site.Status.CLOSED).exclude(
        is_head_office=True).order_by("code")
    if ids is not None:
        sites = sites.filter(pk__in=ids)
    out = []
    for s in sites.prefetch_related("projects"):
        out.append({"id": s.id, "code": s.code, "name": s.name,
                    "projects": [{"id": p.id, "code": p.code,
                                  "title": p.title}
                                 for p in s.projects.all()
                                 if p.status in (Project.Status.AWARDED,
                                                 Project.Status.ACTIVE,
                                                 Project.Status.ON_HOLD)]})
    return out


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def timelapses(request):
    """Each camera's joined reel, the weekly uploads behind it and the camera
    register (?site=), or a new week's video (multipart: camera_id,
    week_from, week_to, file, note)."""
    from . import timelapse as tl
    from .models import SiteTimelapse, TimelapseCamera, TimelapseReel
    ids = _tl_sites(request)
    if request.method == "POST":
        cam = TimelapseCamera.objects.select_related("site").filter(
            pk=request.data.get("camera_id") or None).first()
        if cam is None:
            return Response({"detail": "Pick the camera."}, status=400)
        if ids is not None and cam.site_id not in ids:
            return Response({"detail": "Not your site."}, status=403)
        clip, msg = tl.create(cam, request.data, request.FILES.get("file"),
                              request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(tl.clip_dict(clip, request), status=201)
    reels = TimelapseReel.objects.select_related("site", "camera__project")
    clips = SiteTimelapse.objects.select_related("site", "camera",
                                                 "uploaded_by")
    cams = TimelapseCamera.objects.select_related("site", "project")
    if ids is not None:
        reels, clips, cams = (reels.filter(site_id__in=ids),
                              clips.filter(site_id__in=ids),
                              cams.filter(site_id__in=ids))
    if request.GET.get("site"):
        reels = reels.filter(site_id=request.GET["site"])
        clips = clips.filter(site_id=request.GET["site"])
        cams = cams.filter(site_id=request.GET["site"])
    lw_from, lw_to = tl.last_week()
    reel_rows = [tl.reel_dict(r, request) for r in reels]
    sites = _tl_site_choices(ids)
    default = sites[0]["id"] if len(sites) == 1 else None
    return Response({
        "reels": reel_rows,
        "uploads": [tl.clip_dict(c, request) for c in clips[:200]],
        "cameras": [tl.camera_dict(c) for c in cams],
        "sites": sites,
        # a site team uploads for its own site — chosen for them, not a pick
        "default_site_id": default,
        "site_locked": ids is not None and len(sites) == 1,
        "last_week": {"from": lw_from, "to": lw_to},
        # a live camera whose newest week is older than last week is behind
        "behind": sorted(f"{r['site_code']} · {r['camera_label']}"
                         for r in reel_rows
                         if r["camera_active"] and r["covers_to"]
                         and r["covers_to"] < lw_to),
        "can_upload": request.user.role in tl.UPLOAD_ROLES,
        "can_publish": request.user.role in tl.PUBLISH_ROLES,
        "can_manage_cameras": request.user.role in tl.CAMERA_ROLES,
    })


@api_view(["POST"])
def timelapse_upload_start(request):
    """Begin a week's video in chunks: camera_id, week_from, week_to, note,
    file_name, size → {token, chunk_size} (owner 2026-10-27)."""
    from . import timelapse as tl
    from .models import TimelapseCamera
    cam = TimelapseCamera.objects.select_related("site").filter(
        pk=request.data.get("camera_id") or None).first()
    if cam is None:
        return Response({"detail": "Pick the camera."}, status=400)
    ids = _tl_sites(request)
    if ids is not None and cam.site_id not in ids:
        return Response({"detail": "Not your site."}, status=403)
    token, chunk, msg = tl.start_upload(cam, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response({"token": token, "chunk_size": chunk}, status=201)


@api_view(["GET"])
def timelapse_upload_status(request, token):
    """Which chunks have arrived — to carry on after a dropped link."""
    from . import timelapse as tl
    d, meta = tl._meta(token)
    if meta is None or meta["user_id"] != request.user.id:
        return Response({"detail": "That upload has expired."}, status=404)
    return Response({"received": tl.received(d)})


@api_view(["POST"])
@parser_classes([MultiPartParser])
def timelapse_upload_chunk(request, token):
    from . import timelapse as tl
    n, msg = tl.put_chunk(token, request.data.get("index"),
                          request.FILES.get("chunk"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response({"received": n})


@api_view(["POST"])
def timelapse_upload_finish(request, token):
    from . import timelapse as tl
    clip, msg = tl.finish_upload(token, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(tl.clip_dict(clip, request), status=201)


@api_view(["POST"])
def timelapse_cameras(request):
    """Register a time-lapse camera: site_id, name, location, project_id."""
    from . import timelapse as tl
    ids = _tl_sites(request)
    site = Site.objects.filter(pk=request.data.get("site_id") or None).first()
    if site is None:
        return Response({"detail": "Choose the site."}, status=400)
    if ids is not None and site.id not in ids:
        return Response({"detail": "Not your site."}, status=403)
    cam, msg = tl.camera_create(site, request.data, request.user)
    if msg:
        return Response({"detail": msg},
                        status=403 if "registers" in msg else 400)
    return Response(tl.camera_dict(cam), status=201)


@api_view(["PATCH", "DELETE"])
def timelapse_camera_detail(request, pk):
    """Edit or retire a camera; remove one that never had an upload."""
    from . import timelapse as tl
    from .models import TimelapseCamera
    ids = _tl_sites(request)
    cam = TimelapseCamera.objects.select_related("site", "project") \
        .filter(pk=pk).first()
    if cam is None or (ids is not None and cam.site_id not in ids):
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in tl.CAMERA_ROLES:
        return Response({"detail": "The PM or the Director manages "
                                   "cameras."}, status=403)
    if request.method == "DELETE":
        msg = tl.camera_remove(cam, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(status=204)
    msg = tl.camera_update(cam, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(tl.camera_dict(cam))


@api_view(["DELETE"])
def timelapse_detail(request, pk):
    """Remove a week's upload — its reel is rebuilt without it."""
    from . import timelapse as tl
    from .models import SiteTimelapse
    ids = _tl_sites(request)
    clip = SiteTimelapse.objects.select_related("site", "camera") \
        .filter(pk=pk).first()
    if clip is None or (ids is not None and clip.site_id not in ids):
        return Response({"detail": "Not found."}, status=404)
    if not (request.user.role in tl.PUBLISH_ROLES
            or clip.uploaded_by_id == request.user.id):
        return Response({"detail": "Whoever uploaded it, the PM or the "
                                   "Director removes it."}, status=403)
    tl.remove(clip, request.user)
    return Response(status=204)


@api_view(["PATCH"])
def timelapse_reel(request, pk):
    """Publish a camera's reel to the client's portal, or take it back."""
    from . import timelapse as tl
    from .models import TimelapseReel
    ids = _tl_sites(request)
    reel = TimelapseReel.objects.select_related("site", "camera").filter(
        pk=pk).first()
    if reel is None or (ids is not None and reel.site_id not in ids):
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in tl.PUBLISH_ROLES:
        return Response({"detail": "The PM or the Director publishes to the "
                                   "client."}, status=403)
    reel.client_visible = bool(request.data.get("client_visible"))
    reel.save(update_fields=["client_visible"])
    audit("site", reel.site_id, "TIMELAPSE_PUBLISHED" if reel.client_visible
          else "TIMELAPSE_UNPUBLISHED", actor=request.user,
          detail={"site": reel.site.code, "camera": reel.camera.name})
    return Response(tl.reel_dict(reel, request))
