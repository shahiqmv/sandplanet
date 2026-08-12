"""Site cameras: short-lived view tickets and relay status.

The app never reaches a camera. A site box publishes the camera's stream to
our MediaMTX relay, and every viewer — staff or client — reads it back off the
relay. Two consequences shape this module:

* **Viewers must never hold a durable credential.** A page asks for a ticket,
  gets one good for ~90 seconds, and the relay checks it back with us on the
  way in (`views_cameras.relay_auth`). A leaked ticket is worthless in a
  minute and a half, and it is scoped to one camera.
* **The relay is dumb on purpose.** It knows nothing about sites, clients or
  visibility flags; it asks us on every connection. That keeps one place —
  Django — deciding who may see what.
"""
import json
import secrets
import urllib.error
import urllib.request

from django.conf import settings
from django.core import signing
from django.utils import timezone

TICKET_SALT = "core.cameras.view"
TICKET_MAX_AGE = 90          # seconds; a player only needs it once, at connect
STATUS_TIMEOUT = 3


def relay_public_base():
    """Public origin the browser fetches WHEP from."""
    return getattr(settings, "CAMERA_RELAY_URL", "").rstrip("/")


def relay_api_base():
    """MediaMTX control API — loopback on the relay host, never public."""
    return getattr(settings, "CAMERA_RELAY_API",
                   "http://127.0.0.1:9997").rstrip("/")


def whep_url(camera):
    """Endpoint a browser POSTs its WebRTC offer to."""
    base = relay_public_base()
    return f"{base}/{camera.path}/whep" if base else ""


def new_stream_key():
    """Publish secret for a site box. Generated, never chosen — a camera key
    typed by a person is the one that ends up as the site code twice."""
    return secrets.token_urlsafe(24)[:32]


def issue_ticket(camera, kind, viewer_id):
    """A signed capability to read ONE camera, for ~90s.

    `kind`/`viewer_id` are carried so an audit of relay hits can say which
    staff user or client user opened a feed.
    """
    return signing.dumps(
        {"p": camera.path, "k": kind, "u": viewer_id}, salt=TICKET_SALT)


def read_ticket(token, path):
    """Return the ticket payload if it is valid, unexpired and for `path`."""
    try:
        data = signing.loads(token, salt=TICKET_SALT, max_age=TICKET_MAX_AGE)
    except signing.BadSignature:
        return None
    return data if data.get("p") == path else None


def relay_status():
    """{path: {"ready": bool, "readers": int}} straight from MediaMTX.

    Returns {} when the relay is unreachable — callers show cameras as
    offline rather than failing the page, because a relay outage should not
    take a site's whole dashboard down with it.
    """
    url = f"{relay_api_base()}/v3/paths/list"
    try:
        with urllib.request.urlopen(url, timeout=STATUS_TIMEOUT) as r:
            payload = json.load(r)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return {}
    out = {}
    for item in payload.get("items", []):
        out[item.get("name")] = {
            "ready": bool(item.get("ready")),
            "readers": len(item.get("readers") or []),
        }
    return out


def mark_seen(camera):
    """Record that the site box published — drives the offline badge."""
    camera.last_seen_at = timezone.now()
    camera.save(update_fields=["last_seen_at"])


def camera_dict(camera, status=None, include_key=False):
    """Allowlisted camera payload. `stream_key` is admin-only and never
    reaches a client payload — see views_client."""
    st = (status or {}).get(camera.path) or {}
    out = {
        "id": camera.id,
        "site": camera.site_id,
        "site_code": camera.site.code,
        "name": camera.name,
        "path": camera.path,
        "location_note": camera.location_note,
        "is_active": camera.is_active,
        "client_visible": camera.client_visible,
        "online": bool(st.get("ready")),
        "viewers": st.get("readers", 0),
        "last_seen_at": camera.last_seen_at,
    }
    if include_key:
        out["stream_key"] = camera.stream_key
    return out
