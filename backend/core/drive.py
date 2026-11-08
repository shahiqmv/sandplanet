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
from datetime import date, datetime, timedelta, timezone

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

STAMP = re.compile(r"(\d{1,2})/(\d{1,2})/(20\d\d)")


def _frame_text(path, last=False):
    """The bottom strip of the first (or last) frame, read by tesseract.
    The Brinno writes 'TLC300 10/28/2026 06:00:04' into every frame, so the
    file says its own day whatever its name and metadata say (owner
    2026-11-07)."""
    work = tempfile.mkdtemp(prefix="stamp-")
    try:
        png = os.path.join(work, "strip.png")
        seek = ["-sseof", "-0.3"] if last else []
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", *seek, "-i", path,
             "-update", "1", "-frames:v", "1",
             "-vf", "crop=iw:ih/8:0:ih-ih/8,scale=iw*2:ih*2", png],
            capture_output=True, timeout=120)
        if r.returncode != 0 or not os.path.exists(png):
            return ""
        r = subprocess.run(
            ["tesseract", png, "stdout", "--psm", "7"],
            capture_output=True, text=True, timeout=60)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""
    finally:
        shutil.rmtree(work, ignore_errors=True)


def stamp_dates(path):
    """(from, to) from the timestamp burned into the first and last frames,
    month/day/year as the camera writes it; None where it reads nothing."""
    found = []
    for last in (False, True):
        m = STAMP.search(_frame_text(path, last))
        if m:
            try:
                found.append(date(int(m.group(3)), int(m.group(1)),
                                  int(m.group(2))))
            except ValueError:
                pass
    if not found:
        return None, None
    return min(found), max(found)


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


def dates_from_name(name, today=None):
    """(from, to) from a file named by its day, the way the sites already
    name them: 18_10.MP4, 18-10-2026.MP4, 2026-10-18.MP4, 18_10 to 23_10.MP4.
    None where the name says nothing (TLC00005.MP4)."""
    today = today or djtz.localdate()
    stem = os.path.splitext(name)[0]
    found = []
    for m in re.finditer(r"(?<!\d)(\d{4})[-_.](\d{1,2})[-_.](\d{1,2})(?!\d)"
                         r"|(?<!\d)(\d{1,2})[-_.](\d{1,2})(?:[-_.](\d{2,4}))?(?!\d)",
                         stem):
        try:
            if m.group(1):
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            else:
                y = m.group(6)
                y = (int(y) + (2000 if len(y) == 2 else 0)) if y else today.year
                d = date(y, int(m.group(5)), int(m.group(4)))
                if not m.group(6) and d > today + timedelta(days=7):
                    d = d.replace(year=y - 1)     # a January file in December
        except ValueError:
            continue
        if date(2020, 1, 1) <= d <= today + timedelta(days=7):
            found.append(d)
    if not found:
        return None, None
    return min(found), max(found)


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
        if f["size"] <= 0:
            # OneDrive lists a file the app is still carrying up as 0 bytes
            # (DTE, 2026-11-08: six of eight); it is not here yet
            continue
        item = seen.get(f["name"])
        if item is None:
            TimelapseDriveItem.objects.create(
                camera=cam, name=f["name"], size_bytes=f["size"],
                modified_at=f["modified"], content_hash=f["hash"])
            continue
        if item.status not in ("SEEN", "NEEDS_DATES"):
            continue
        changed = (item.size_bytes != f["size"] or item.content_hash != f["hash"])
        if changed or now - item.first_seen_at < SETTLE:
            item.size_bytes, item.content_hash = f["size"], f["hash"]
            item.modified_at = f["modified"]
            if changed:
                # a different file under the same name: start again, a
                # verdict on the old bytes says nothing about the new
                item.first_seen_at = now
                item.status, item.attempts, item.note = "SEEN", 0, ""
            item.save()
            continue
        if item.status == "NEEDS_DATES" and not item.week_from:
            continue                    # still waiting for someone to say
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
        # the days it covers: what the site said, else the name, else what
        # the file itself says; a file with none of those waits for the site
        start, end = item.week_from, item.week_to
        if start is None:
            start, end = dates_from_name(f["name"])
        if start is None:
            fetch(cam.drive_folder, f["name"], dest)
            start, end = stamp_dates(dest)
        if start is None:
            start, end = probe_dates(dest, None)
        if start is None:
            item.status, item.attempts = "NEEDS_DATES", 0
            item.note = ("The file carries no date. Say which days it covers "
                         "and it will be brought in.")
            item.save()
            return False
        if not os.path.exists(dest):
            fetch(cam.drive_folder, f["name"], dest)
        with open(dest, "rb") as fh, transaction.atomic():
            clip, err = tl.create(cam, {"week_from": str(start),
                                        "week_to": str(end),
                                        "note": "From OneDrive"},
                                  File(fh, name=f["name"]), actor=None)
            if err:
                raise DriveError(str(err))
            item.clip, item.status, item.note = clip, "IMPORTED", ""
            item.week_from, item.week_to, item.done_at = start, end, now
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


def set_dates(item, data, actor):
    """The site says which days a dateless file covers; the next pass brings
    it in. Also re-dates one not yet imported."""
    if item.status not in ("NEEDS_DATES", "SEEN", "FAILED", "IGNORED",
                           "DUPLICATE"):
        return "That file is already in."
    try:
        wf = date.fromisoformat(str(data.get("week_from"))[:10])
        wt = date.fromisoformat(str(data.get("week_to") or data.get("week_from"))[:10])
    except ValueError:
        return "Give the days the file covers."
    if wt < wf:
        return "The clip ends before it starts."
    if wf > djtz.localdate():
        return "Those days have not come yet."
    item.week_from, item.week_to = wf, wt
    if item.status != "SEEN":
        item.status, item.attempts, item.note = "SEEN", 0, ""
        item.first_seen_at = djtz.now() - SETTLE
        item.done_at = None
    item.save()
    audit("site", item.camera.site_id, "TIMELAPSE_DRIVE_DATED", actor=actor,
          detail={"camera": item.camera.name, "file": item.name,
                  "dates": f"{wf}..{wt}"})
    return None


def import_again(item, actor):
    if item.status not in ("IGNORED", "FAILED", "DUPLICATE", "NEEDS_DATES"):
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
            "week_from": d.week_from, "week_to": d.week_to,
            "done_at": d.done_at}
