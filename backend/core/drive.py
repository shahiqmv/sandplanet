"""Time-lapse intake from OneDrive (owner 2026-11-07).

The islands' links kept dropping the upload page's multi-gigabyte sends, and
the same clip went up three times. Now the site copies the card's files into
the camera's OneDrive folder and the OneDrive app carries them up in the
background, resuming on its own; Planet lists each camera's folder every ten
minutes, fetches what is new and adds it to the camera's video.

rclone does the talking to OneDrive. It was authorised once by the owner
(`manage.py onedrive_connect`) and keeps its own access fresh in the config
file; Planet runs it as a subprocess and parses its JSON. A plain directory
path works as the remote too, which is how the tests run without OneDrive.

Rules:
- A file is imported once, recognised by OneDrive's own checksum. A second
  copy, under any name, is recorded as a repeat and skipped.
- A file first seen is left for one more pass, so one still being uploaded
  is not fetched half-done; the OneDrive app commits whole files, but the
  wait costs ten minutes and saves a broken clip.
- A file whose upload someone deleted in Planet is left alone until they
  ask for it again.
- Nothing in OneDrive is ever moved or deleted.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.utils import timezone as djtz

from .audit import audit
from .models import TimelapseCamera, TimelapseDriveItem

REMOTE = os.environ.get("TIMELAPSE_DRIVE_REMOTE", "onedrive:")
RCLONE = os.environ.get("RCLONE", "rclone")
SETTLE = timedelta(minutes=8)       # a file must sit unchanged this long
MAX_ATTEMPTS = 3
VIDEO = (".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm")


class DriveError(Exception):
    pass


def _run(args, timeout):
    env = dict(os.environ)
    cfg = getattr(settings, "RCLONE_CONFIG", None)
    if cfg:
        env["RCLONE_CONFIG"] = cfg
    try:
        return subprocess.run([RCLONE, *args], capture_output=True, text=True,
                              timeout=timeout, env=env, check=False)
    except FileNotFoundError:
        raise DriveError("rclone is not installed on this server.")
    except subprocess.TimeoutExpired:
        raise DriveError("OneDrive did not answer in time.")


def _path(folder, name=None):
    base = REMOTE if REMOTE.endswith((":", "/")) else REMOTE + "/"
    p = base + folder.strip("/ ")
    return f"{p}/{name}" if name else p


def connected():
    """Is a remote configured at all? (A directory path always is.)"""
    if not REMOTE.endswith(":"):
        return os.path.isdir(REMOTE)
    r = _run(["listremotes"], 20)
    return r.returncode == 0 and REMOTE in r.stdout.split()


def list_folder(folder):
    """[{name, size, modified, hash}] of the files in a camera's folder."""
    r = _run(["lsjson", "--hash", "--files-only", "--no-mimetype",
              _path(folder)], 120)
    if r.returncode != 0:
        raise DriveError((r.stderr or "listing failed").strip()[-300:])
    out = []
    for it in json.loads(r.stdout or "[]"):
        hashes = it.get("Hashes") or {}
        out.append({
            "name": it["Name"], "size": int(it.get("Size") or 0),
            "modified": _when(it.get("ModTime")),
            "hash": hashes.get("sha1") or hashes.get("quickxor") or "",
        })
    return out


def _list_dirs(folder):
    r = _run(["lsjson", "--dirs-only", _path(folder)], 120)
    if r.returncode != 0:
        raise DriveError((r.stderr or "listing failed").strip()[-300:])
    return [{"name": it["Name"]} for it in json.loads(r.stdout or "[]")]


def fetch(folder, name, dest):
    r = _run(["copyto", "--no-traverse", _path(folder, name), dest], 3600)
    if r.returncode != 0 or not os.path.exists(dest):
        raise DriveError((r.stderr or "download failed").strip()[-300:])


def _when(iso):
    if not iso:
        return None
    iso = re.sub(r"(\.\d{6})\d+", r"\1", iso)      # rclone gives nanoseconds
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---- dates in the file ---------------------------------------------------------

def probe_dates(path, modified=None):
    """(from, to) the clip covers, from what the file itself says: the
    recording's creation time as the start, the file's own modified time (the
    moment the camera closed it) as the end. Both are the camera's clock. A
    file that says nothing falls back to the modified day alone."""
    start = None
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format_tags=creation_time:stream_tags=creation_time",
             "-of", "json", path], capture_output=True, text=True, timeout=60)
        info = json.loads(r.stdout or "{}")
        tags = [info.get("format", {}).get("tags", {})] + [
            s.get("tags", {}) for s in info.get("streams", [])]
        for t in tags:
            if t.get("creation_time"):
                start = _when(t["creation_time"])
                break
    except (OSError, ValueError, subprocess.TimeoutExpired):
        start = None
    end = modified
    if start and start.year < 2000:          # an unset camera clock
        start = None
    if start and end and end < start:
        end = start
    if start is None and end is None:
        return None, None
    s = (start or end).astimezone(timezone(timedelta(hours=5))).date()
    e = (end or start).astimezone(timezone(timedelta(hours=5))).date()
    return s, e


# ---- the sweep -------------------------------------------------------------------

def sync_all():
    """Every active camera with a folder. Returns (imported, skipped, failed)."""
    imported = skipped = failed = 0
    for cam in TimelapseCamera.objects.filter(is_active=True) \
            .exclude(drive_folder="").select_related("site"):
        try:
            i, s, f = sync_camera(cam)
        except DriveError as e:
            audit("site", cam.site_id, "TIMELAPSE_DRIVE_ERROR", actor=None,
                  detail={"camera": cam.name, "error": str(e)[:200]})
            failed += 1
            continue
        imported, skipped, failed = imported + i, skipped + s, failed + f
    return imported, skipped, failed


def sync_camera(cam, now=None):
    now = now or djtz.now()
    imported = skipped = failed = 0
    seen = {d.name: d for d in cam.drive_items.all()}
    for f in list_folder(cam.drive_folder):
        if not f["name"].lower().endswith(VIDEO):
            continue
        item = seen.get(f["name"])
        if item is None:
            TimelapseDriveItem.objects.create(
                camera=cam, name=f["name"], size_bytes=f["size"],
                modified_at=f["modified"], content_hash=f["hash"])
            continue
        if item.status != "SEEN":
            continue
        changed = (item.size_bytes != f["size"] or item.content_hash != f["hash"])
        if changed or now - item.first_seen_at < SETTLE:
            item.size_bytes, item.content_hash = f["size"], f["hash"]
            item.modified_at = f["modified"]
            if changed:
                item.first_seen_at = now
            item.save()
            continue
        if item.attempts >= MAX_ATTEMPTS:
            continue
        twin = (TimelapseDriveItem.objects
                .filter(content_hash=f["hash"], status="IMPORTED")
                .exclude(pk=item.pk).select_related("camera").first()
                if f["hash"] else None)
        if twin:
            item.status, item.note = "DUPLICATE", (
                f"Same file as {twin.name} on {twin.camera.name}, already in.")
            item.done_at = now
            item.save()
            skipped += 1
            continue
        if _import(cam, item, f, now):
            imported += 1
        else:
            failed += 1
    return imported, skipped, failed


def _import(cam, item, f, now):
    from . import timelapse as tl
    item.attempts += 1
    item.save(update_fields=["attempts"])
    work = tempfile.mkdtemp(prefix="drive-")
    try:
        dest = os.path.join(work, f["name"])
        fetch(cam.drive_folder, f["name"], dest)
        start, end = probe_dates(dest, f["modified"])
        if start is None:
            raise DriveError("The file carries no date; give it one on the "
                             "upload page instead.")
        with open(dest, "rb") as fh, transaction.atomic():
            clip, err = tl.create(cam, {"week_from": str(start),
                                        "week_to": str(end),
                                        "note": "From OneDrive"},
                                  File(fh, name=f["name"]), actor=None)
            if err:
                raise DriveError(str(err))
            item.clip, item.status, item.note = clip, "IMPORTED", ""
            item.done_at = now
            item.save()
        audit("site", cam.site_id, "TIMELAPSE_DRIVE_IMPORTED", actor=None,
              detail={"camera": cam.name, "file": f["name"],
                      "dates": f"{start}..{end}", "bytes": f["size"]})
        return True
    except DriveError as e:
        item.note = str(e)[:300]
        if item.attempts >= MAX_ATTEMPTS:
            item.status, item.done_at = "FAILED", now
        item.save()
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)


def clip_deleted(clip):
    """A drive-imported upload someone deleted: leave its file alone."""
    TimelapseDriveItem.objects.filter(clip=clip).update(
        status="IGNORED", clip=None,
        note="Its upload was deleted in Planet; press Import again to bring "
             "it back.")


def import_again(item, actor):
    if item.status not in ("IGNORED", "FAILED", "DUPLICATE"):
        return "That file is already in, or on its way."
    item.status, item.attempts, item.note = "SEEN", 0, ""
    item.first_seen_at = djtz.now() - SETTLE
    item.done_at = None
    item.save()
    audit("site", item.camera.site_id, "TIMELAPSE_DRIVE_RETRY", actor=actor,
          detail={"camera": item.camera.name, "file": item.name})
    return None


def item_dict(d):
    return {"id": d.id, "camera_id": d.camera_id, "name": d.name,
            "size_mb": round(d.size_bytes / 1048576, 1),
            "modified_at": d.modified_at, "status": d.status,
            "status_label": d.get_status_display(), "note": d.note,
            "clip_id": d.clip_id, "first_seen_at": d.first_seen_at,
            "done_at": d.done_at}
