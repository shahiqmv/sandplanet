"""Site time-lapse: weekly uploads joined into one video per camera
(owner 2026-10-13).

The Brinno cameras record to an SD card and make the time-lapse themselves;
there is nothing to connect to. Each week someone uploads that week's video
against the site and the camera. A background job (timelapse_build, every
ten minutes) converts it to one standard MP4 — which also makes the camera's
AVI playable in a browser — and rebuilds the camera's reel: every week, in
date order, joined into a single continuous video. A week uploaded late
still lands in its place. "Per week videos will be messy" — so the reel is
what people watch; the weekly pieces are only its inputs.
"""
import os
import shutil
import subprocess
import tempfile
from datetime import date, timedelta
from decimal import Decimal

from django.core.files import File
from django.db import transaction
from django.utils import timezone

from .audit import audit
from .models import Project, SiteTimelapse, TimelapseCamera, TimelapseReel

UPLOAD_ROLES = ("SITE_ADMIN", "SITE_ENGINEER", "PM", "DIRECTOR", "ADMIN")
PUBLISH_ROLES = ("PM", "DIRECTOR", "ADMIN")
# the cameras are registered like the live ones — by whoever installs and
# answers for them, not by whoever happens to upload
CAMERA_ROLES = PUBLISH_ROLES
# A week off a Brinno card runs to a couple of gigabytes (SJR's first was
# 2 GB, 2026-10-24) — sent in chunks, so the size is not one long request.
# 4 GB keeps the final save to storage inside the server's time limit.
MAX_BYTES = 4 * 1024 * 1024 * 1024
CHUNK_BYTES = 8 * 1024 * 1024           # under the proxy's 16 MB buffer
UPLOAD_DIR = os.environ.get("TIMELAPSE_UPLOAD_DIR") or os.path.join(
    tempfile.gettempdir(), "planet-timelapse-uploads")
ALLOWED = (".mp4", ".m4v", ".mov", ".webm", ".avi", ".mkv")

# One standard every piece is converted to, so the pieces join without
# re-encoding: H.264, 1080p (letterboxed if the camera was set otherwise),
# 30 frames a second, no sound, quick-start for streaming.
_VF = ("scale=1920:1080:force_original_aspect_ratio=decrease,"
       "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30")


def last_week(today=None):
    """The last full Saturday-to-Friday week — the company's week."""
    today = today or date.today()
    fri = today - timedelta(days=((today.weekday() - 4) % 7) or 7)
    return fri - timedelta(days=6), fri


# ---- the camera register --------------------------------------------------------

def _camera_fields(site, data, cam=None):
    """Validated (name, location, project) or an error string."""
    name = (data.get("name", cam.name if cam else "") or "").strip()[:80]
    if not name:
        return "Name the camera, e.g. 'Brinno 1 — north side'."
    clash = TimelapseCamera.objects.filter(site=site, name__iexact=name)
    if cam:
        clash = clash.exclude(pk=cam.pk)
    if clash.exists():
        return f"{site.code} already has a camera called '{name}'."
    location = (data.get("location", cam.location if cam else "")
                or "").strip()[:200]
    if not location:
        return "Say where it is mounted and what it looks at."
    project = cam.project if cam else None
    if "project_id" in data:
        pid = data.get("project_id")
        project = None
        if pid not in (None, ""):
            project = Project.objects.filter(pk=pid, site=site).first()
            if project is None:
                return "That project is not on this site."
    return name, location, project


def camera_create(site, data, actor):
    if actor.role not in CAMERA_ROLES:
        return None, "The PM or the Director registers cameras."
    got = _camera_fields(site, data)
    if isinstance(got, str):
        return None, got
    name, location, project = got
    cam = TimelapseCamera.objects.create(site=site, name=name,
                                         location=location, project=project,
                                         created_by=actor)
    audit("site", site.id, "TIMELAPSE_CAMERA_ADDED", actor=actor,
          detail={"site": site.code, "camera": name,
                  "project": project.code if project else None})
    return cam, None


def camera_update(cam, data, actor):
    if actor.role not in CAMERA_ROLES:
        return "The PM or the Director edits cameras."
    got = _camera_fields(cam.site, data, cam)
    if isinstance(got, str):
        return got
    cam.name, cam.location, cam.project = got
    if "is_active" in data:
        cam.is_active = bool(data.get("is_active"))
    cam.save()
    audit("site", cam.site_id, "TIMELAPSE_CAMERA_UPDATED", actor=actor,
          detail={"site": cam.site.code, "camera": cam.name,
                  "active": cam.is_active})
    return None


def camera_remove(cam, actor):
    """Only a camera nothing was ever uploaded for; otherwise retire it."""
    if actor.role not in CAMERA_ROLES:
        return "The PM or the Director removes cameras."
    if cam.uploads.exists():
        return ("Weeks have been uploaded for this camera — retire it "
                "instead, so its video is kept.")
    audit("site", cam.site_id, "TIMELAPSE_CAMERA_REMOVED", actor=actor,
          detail={"site": cam.site.code, "camera": cam.name})
    cam.delete()
    return None


def camera_dict(cam):
    return {"id": cam.id, "site_id": cam.site_id, "site_code": cam.site.code,
            "name": cam.name, "location": cam.location,
            "project_id": cam.project_id,
            "project_code": cam.project.code if cam.project_id else "",
            "project_title": cam.project.title if cam.project_id else "",
            "is_active": cam.is_active,
            "uploads": cam.uploads.count()}


# ---- uploads -------------------------------------------------------------------

@transaction.atomic
def create(camera, data, upload, actor):
    """Returns (clip, error)."""
    site = camera.site
    if actor.role not in UPLOAD_ROLES:
        return None, "The site team, PM or Director uploads time-lapses."
    if upload is None:
        return None, "Attach the week's video from the camera's card."
    if not (upload.name or "").lower().endswith(ALLOWED):
        return None, "Upload the camera's video file (AVI or MP4)."
    if upload.size > MAX_BYTES:
        return None, ("That video is over 4 GB — split the week on the "
                      "card and upload it in two.")
    if not camera.is_active:
        return None, "That camera is retired — pick the one now in its place."
    try:
        wf = date.fromisoformat(str(data.get("week_from"))[:10])
        wt = date.fromisoformat(str(data.get("week_to"))[:10])
    except ValueError:
        return None, "Give the week the video covers."
    if wt < wf:
        return None, "The week ends before it starts."
    if wf > date.today():
        return None, "That week has not started yet."
    clip = SiteTimelapse.objects.create(
        site=site, camera=camera, week_from=wf, week_to=wt,
        file=upload, file_name=upload.name[:200], size_bytes=upload.size,
        note=(data.get("note") or "")[:300].strip(), uploaded_by=actor)
    reel, _ = TimelapseReel.objects.get_or_create(camera=camera,
                                                  defaults={"site": site})
    TimelapseReel.objects.filter(pk=reel.pk).update(needs_build=True)
    audit("site", site.id, "TIMELAPSE_ADDED", actor=actor,
          detail={"site": site.code, "camera": camera.name,
                  "week": f"{wf}..{wt}"})
    return clip, None


# ---- uploading a big video in chunks (owner 2026-10-27) ----------------------
# A week's video went up in one request, and a 2 GB file over an island link
# never arrived: the server gave up part way and answered "500" (SJR, 24 Oct).
# The browser now sends it in 8 MB chunks, each its own short request and
# retried on its own; the chunks wait on the server's disk until the last
# arrives, are joined, and the week is saved as before.

def _session_dir(token):
    if not token or not all(c in "0123456789abcdef" for c in token) \
            or len(token) != 32:
        return None
    return os.path.join(UPLOAD_DIR, token)


def _meta(token):
    import json
    d = _session_dir(token)
    if d is None or not os.path.exists(os.path.join(d, "meta.json")):
        return None, None
    with open(os.path.join(d, "meta.json")) as f:
        return d, json.load(f)


def _validate(camera, data, name, size, actor):
    """The checks a week's upload must pass, before a byte is sent."""
    if actor.role not in UPLOAD_ROLES:
        return "The site team, PM or Director uploads time-lapses."
    if not (name or "").lower().endswith(ALLOWED):
        return "Upload the camera's video file (AVI or MP4)."
    if not size or size <= 0:
        return "Choose the week's video."
    if size > MAX_BYTES:
        return ("That video is over 4 GB — split the week on the card and "
                "upload it in two.")
    if not camera.is_active:
        return "That camera is retired — pick the one now in its place."
    try:
        wf = date.fromisoformat(str(data.get("week_from"))[:10])
        wt = date.fromisoformat(str(data.get("week_to"))[:10])
    except ValueError:
        return "Give the week the video covers."
    if wt < wf:
        return "The week ends before it starts."
    if wf > date.today():
        return "That week has not started yet."
    return None


def start_upload(camera, data, actor):
    """(token, chunk_size, error) for a new chunked upload."""
    import json
    import uuid
    name = (data.get("file_name") or "").strip()[:200]
    try:
        size = int(data.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    err = _validate(camera, data, name, size, actor)
    if err:
        return None, None, err
    _sweep()
    token = uuid.uuid4().hex
    d = os.path.join(UPLOAD_DIR, token)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "meta.json"), "w") as f:
        json.dump({"camera_id": camera.id, "file_name": name, "size": size,
                   "chunk": CHUNK_BYTES, "user_id": actor.id,
                   "week_from": str(data.get("week_from"))[:10],
                   "week_to": str(data.get("week_to"))[:10],
                   "note": (data.get("note") or "")[:300]}, f)
    return token, CHUNK_BYTES, None


def _expected(meta):
    return max(1, -(-meta["size"] // meta["chunk"]))


def received(d):
    return sorted(int(n.split(".")[0]) for n in os.listdir(d)
                  if n.endswith(".part"))


def put_chunk(token, index, chunk, actor):
    """Store one chunk; sending the same one twice is harmless. Returns
    (received count, error)."""
    d, meta = _meta(token)
    if meta is None:
        return None, "That upload has expired — start it again."
    if meta["user_id"] != actor.id:
        return None, "That upload is someone else's."
    try:
        index = int(index)
    except (TypeError, ValueError):
        return None, "Bad chunk."
    if not 0 <= index < _expected(meta) or chunk is None:
        return None, "Bad chunk."
    if chunk.size > CHUNK_BYTES:
        return None, "Chunk too large."
    tmp = os.path.join(d, f"{index:06d}.tmp")
    with open(tmp, "wb") as out:
        for piece in chunk.chunks():
            out.write(piece)
    os.replace(tmp, os.path.join(d, f"{index:06d}.part"))
    return len(received(d)), None


def finish_upload(token, actor):
    """Join the chunks and save the week. Returns (clip, error)."""
    d, meta = _meta(token)
    if meta is None:
        return None, "That upload has expired — start it again."
    if meta["user_id"] != actor.id:
        return None, "That upload is someone else's."
    have = received(d)
    if have != list(range(_expected(meta))):
        return None, (f"{_expected(meta) - len(have)} piece(s) of the video "
                      "did not arrive — send it again.")
    camera = TimelapseCamera.objects.select_related("site").filter(
        pk=meta["camera_id"]).first()
    if camera is None:
        return None, "That camera is no longer on the register."
    whole = os.path.join(d, "whole")
    with open(whole, "wb") as out:
        for i in have:
            with open(os.path.join(d, f"{i:06d}.part"), "rb") as part:
                shutil.copyfileobj(part, out, 1024 * 1024)
    if os.path.getsize(whole) != meta["size"]:
        shutil.rmtree(d, ignore_errors=True)
        return None, "The video arrived damaged — send it again."
    try:
        with open(whole, "rb") as f:
            clip, err = create(camera, meta, File(f, name=meta["file_name"]),
                               actor)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return clip, err


def _sweep(days=2):
    """Uploads abandoned part way are cleared after two days."""
    import time
    if not os.path.isdir(UPLOAD_DIR):
        return
    cutoff = time.time() - days * 86400
    for name in os.listdir(UPLOAD_DIR):
        path = os.path.join(UPLOAD_DIR, name)
        try:
            if os.path.getmtime(path) < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


@transaction.atomic
def remove(clip, actor):
    site, camera = clip.site, clip.camera
    if clip.file:
        clip.file.delete(save=False)
    clip.delete()
    reel = TimelapseReel.objects.filter(camera=camera).first()
    if reel:
        if not SiteTimelapse.objects.filter(camera=camera).exists():
            if reel.file:
                reel.file.delete(save=False)
            reel.delete()
        else:
            TimelapseReel.objects.filter(pk=reel.pk).update(needs_build=True)
    audit("site", site.id, "TIMELAPSE_REMOVED", actor=actor,
          detail={"site": site.code, "camera": camera.name})


# ---- the video work (ffmpeg) -----------------------------------------------------

def _bin(name):
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} is not installed on this server")
    return path


def _run(args, timeout):
    r = subprocess.run(args, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or b"").decode("utf-8", "replace")
                           .strip().splitlines()[-1:] or ["ffmpeg failed"])
    return r


def duration(path):
    r = _run([_bin("ffprobe"), "-v", "error", "-show_entries",
              "format=duration", "-of", "csv=p=0", path], 60)
    try:
        return Decimal(r.stdout.decode().strip()).quantize(Decimal("0.01"))
    except Exception:
        return None


def normalize(src, dst):
    """Any camera video → the reel's standard MP4."""
    _run([_bin("ffmpeg"), "-y", "-v", "error", "-i", src, "-an",
          "-vf", _VF, "-c:v", "libx264", "-preset", "veryfast",
          "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
          dst], 3600)


def concat(paths, dst):
    """Join standard MP4s end to end — no re-encoding, so it is quick."""
    lst = dst + ".txt"
    with open(lst, "w") as f:
        for p in paths:
            f.write("file '" + p.replace("'", "'\\''") + "'\n")
    try:
        _run([_bin("ffmpeg"), "-y", "-v", "error", "-f", "concat",
              "-safe", "0", "-i", lst, "-c", "copy", "-movflags",
              "+faststart", dst], 3600)
    finally:
        os.remove(lst)


def _download(field, path):
    field.open("rb")
    try:
        with open(path, "wb") as out:
            shutil.copyfileobj(field, out, 1024 * 1024)
    finally:
        field.close()


def normalize_clip(clip, workdir):
    """Convert one upload; the original is replaced by the standard MP4."""
    src = os.path.join(workdir, f"in-{clip.id}")
    dst = os.path.join(workdir, f"std-{clip.id}.mp4")
    _download(clip.file, src)
    try:
        normalize(src, dst)
    except Exception as e:                       # unreadable / not a video
        clip.status = "FAILED"
        clip.error = str(e)[:300]
        clip.save(update_fields=["status", "error"])
        return False
    old = clip.file.name
    base = os.path.splitext(os.path.basename(clip.file_name or "week"))[0]
    with open(dst, "rb") as f:
        clip.file.save(f"{base}.mp4", File(f), save=False)
    clip.normalized = True
    clip.duration_s = duration(dst)
    clip.size_bytes = os.path.getsize(dst)
    clip.error = ""
    clip.save(update_fields=["file", "normalized", "duration_s",
                             "size_bytes", "error"])
    if old and old != clip.file.name:
        clip.file.storage.delete(old)
    return True


def build_reel(reel, workdir):
    """Join every converted week of this camera, in date order."""
    clips = list(SiteTimelapse.objects.filter(
        camera_id=reel.camera_id, normalized=True)
        .order_by("week_from", "id"))
    if not clips:
        TimelapseReel.objects.filter(pk=reel.pk).update(needs_build=False)
        return False
    parts = []
    for c in clips:
        p = os.path.join(workdir, f"part-{c.id}.mp4")
        _download(c.file, p)
        parts.append(p)
    out = os.path.join(workdir, f"reel-{reel.id}.mp4")
    if len(parts) == 1:
        shutil.copyfile(parts[0], out)
    else:
        concat(parts, out)
    old = reel.file.name if reel.file else ""
    name = f"{reel.site.code}-{reel.camera.name}".replace(" ", "-")[:60]
    with open(out, "rb") as f:
        reel.file.save(f"{name}.mp4", File(f), save=False)
    reel.covers_from = clips[0].week_from
    reel.covers_to = max(c.week_to for c in clips)
    reel.weeks = len(clips)
    reel.duration_s = duration(out)
    reel.size_bytes = os.path.getsize(out)
    reel.built_at = timezone.now()
    reel.needs_build = False
    reel.save()
    if old and old != reel.file.name:
        reel.file.storage.delete(old)
    SiteTimelapse.objects.filter(pk__in=[c.id for c in clips]).update(
        status="JOINED")
    return True


def build_pending():
    """Convert waiting uploads, then rebuild every reel that changed.
    Returns (converted, failed, reels_built)."""
    converted = failed = built = 0
    with tempfile.TemporaryDirectory(prefix="timelapse-") as work:
        for clip in SiteTimelapse.objects.filter(
                normalized=False, status="PENDING").order_by("id"):
            if normalize_clip(clip, work):
                converted += 1
                TimelapseReel.objects.filter(camera_id=clip.camera_id) \
                    .update(needs_build=True)
            else:
                failed += 1
            for name in os.listdir(work):
                os.remove(os.path.join(work, name))
        for reel in TimelapseReel.objects.filter(needs_build=True) \
                .select_related("site", "camera"):
            if build_reel(reel, work):
                built += 1
            for name in os.listdir(work):
                os.remove(os.path.join(work, name))
    return converted, failed, built


# ---- what the screens get --------------------------------------------------------

def _url(f, request):
    if not f:
        return None
    u = f.url
    return request.build_absolute_uri(u) if request and u.startswith("/") else u


def reel_dict(reel, request=None, staff=True):
    cam = reel.camera
    waiting = SiteTimelapse.objects.filter(camera=cam,
                                           status="PENDING").count()
    out = {"id": reel.id, "site_code": reel.site.code,
           "camera_label": cam.name, "location": cam.location,
           "project_code": cam.project.code if cam.project_id else "",
           "project_title": cam.project.title if cam.project_id else "",
           "play_url": _url(reel.file, request),
           "covers_from": reel.covers_from, "covers_to": reel.covers_to,
           "weeks": reel.weeks,
           "duration_s": reel.duration_s, "updated": reel.built_at}
    if staff:
        out.update({"site_id": reel.site_id, "camera_id": cam.id,
                    "camera_active": cam.is_active,
                    "client_visible": reel.client_visible,
                    "waiting": waiting,
                    "size_mb": (round(reel.size_bytes / 1048576, 1)
                                if reel.size_bytes else None)})
    return out


def clip_dict(clip, request=None):
    return {"id": clip.id, "site_code": clip.site.code,
            "camera_label": clip.camera.name,
            "week_from": clip.week_from, "week_to": clip.week_to,
            "status": clip.status, "status_label": clip.get_status_display(),
            "error": clip.error, "note": clip.note,
            "file_name": clip.file_name,
            "play_url": _url(clip.file, request) if clip.normalized else None,
            "uploaded_by": (clip.uploaded_by.full_name
                            if clip.uploaded_by_id else ""),
            "created_at": clip.created_at}
