"""FollowMe (followme.mv) local-vessel tracking adapter.

Almost every Maldivian supply vessel carries a FollowMe tracking device, so we
use their public API to (1) pick a vessel name onto a Loading Manifest,
(2) show a vessel's live position, and (3) browse vessels near an atoll
(owner 2026-08-07). The API key is part of the URL path and lives in the env,
never in the repo — Planet proxies every call so the key never reaches a browser.

Response shapes (both wrapped in an HTML page; the JSON is extracted):
  list   GET /public/{key}/        → {"<id>": {name,speed,time,type,image,port}, …}
  detail GET /public/{key}/{id}/   → {status, data:{"<id>":{…,course,lat,lon}}}
The list carries no coordinates (only `port`, a reverse-geocoded place name);
the detail adds lat/lon/course for a live map pin.
"""
import json
import re
import time
import urllib.error
import urllib.request

from django.conf import settings

_LIST_TTL = 60                      # seconds — the fleet list is heavy; cache it
_cache = {"at": 0.0, "vessels": None}
_ATOLL = re.compile(r"^([A-Za-z]{1,3})\.\s")


class FollowMeError(Exception):
    pass


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def atoll_of(port):
    """The atoll code prefixing a port name ('K. Thilafushi' → 'K'), or '' for
    named harbours/resorts without one ('Hulhumale', 'Soneva Jani …')."""
    m = _ATOLL.match(port or "")
    return m.group(1).upper() if m else ""


def _http_get(path):
    key = getattr(settings, "FOLLOWME_API_KEY", "")
    if not key:
        raise FollowMeError("FOLLOWME_API_KEY is not configured.")
    base = getattr(settings, "FOLLOWME_BASE_URL",
                   "https://followme.mv/api/v5").rstrip("/")
    url = f"{base}/public/{key}/{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as e:
        raise FollowMeError(f"FollowMe {e.code}")
    except urllib.error.URLError as e:                  # pragma: no cover
        raise FollowMeError(f"FollowMe unreachable: {e.reason}")


def _request(path):
    raw = _http_get(path)
    # the API returns JSON inside an HTML page — pull out the JSON object
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        raise FollowMeError("Unexpected response from FollowMe.")
    data = json.loads(raw[start:end + 1])
    return data.get("data", data) if isinstance(data, dict) else {}


def _norm(vid, v):
    v = v or {}
    return {
        "id": str(vid), "name": (v.get("name") or "").strip(),
        "type": v.get("type") or "", "port": v.get("port") or "",
        "atoll": atoll_of(v.get("port")),
        "speed": _f(v.get("speed")), "course": _f(v.get("course")),
        "lat": _f(v.get("lat")), "lon": _f(v.get("lon")),
        "time": v.get("time") or "", "image": v.get("image") or "",
    }


def list_vessels():
    """Every public vessel (id/name/type/port/speed/last-seen), name-sorted.
    Cached briefly — the list is large and changes slowly."""
    now = time.time()
    if _cache["vessels"] is not None and now - _cache["at"] < _LIST_TTL:
        return _cache["vessels"]
    d = _request("")
    vessels = [_norm(k, val) for k, val in (d or {}).items()
               if isinstance(val, dict)]
    vessels.sort(key=lambda x: x["name"].lower())
    _cache.update(at=now, vessels=vessels)
    return vessels


def vessel(vid):
    """One vessel's live snapshot, including lat/lon/course for a map pin."""
    d = _request(f"{vid}/")
    if not isinstance(d, dict) or not d:
        return None
    v = d.get(str(vid)) or next(iter(d.values()))
    return _norm(vid, v)
