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
        # A PULL camera is idle until somebody watches, so "ready" being false
        # means nothing is being viewed — NOT that the camera is down. Saying
        # "Offline" there would be a lie, so the mode travels with it and the
        # UI says "On demand" instead.
        "mode": "PULL" if camera.source_url else "PUSH",
        "online": bool(st.get("ready")),
        "viewers": st.get("readers", 0),
        "last_seen_at": camera.last_seen_at,
    }
    if include_key:
        out["stream_key"] = camera.stream_key
        out["source_url"] = camera.source_url
    return out


# --- pull mode -----------------------------------------------------------
# A site with a routable address forwards its camera port to the droplet, and
# the relay fetches the stream itself. Nothing runs at the site, and because
# the path is on-demand the relay only holds the connection while somebody is
# watching — an unwatched camera costs the site's uplink nothing.

def _api(method, path, body=None):
    url = f"{relay_api_base()}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=STATUS_TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return None, str(e)


def sync_relay_path(camera):
    """Teach the relay how to reach a PULL camera (or forget a PUSH one).

    Returns (ok, message). A relay that is down must not block saving a
    camera — the row is the source of truth and `resync_all` puts the relay
    back in step.
    """
    name = camera.path
    if not camera.source_url or not camera.is_active:
        code, _ = _api("POST", f"/v3/config/paths/delete/{name}")
        return True, ("stopped pulling" if code == 200 else "not pulling")
    body = {
        "source": camera.source_url,
        "sourceOnDemand": True,
        # Give a distant camera time to answer over a slow island link before
        # the relay gives up on the viewer's behalf.
        "sourceOnDemandStartTimeout": "15s",
        "sourceOnDemandCloseAfter": "20s",
    }
    code, msg = _api("POST", f"/v3/config/paths/add/{name}", body)
    if code == 400 and "already exists" in msg:
        code, msg = _api("PATCH", f"/v3/config/paths/patch/{name}", body)
    if code == 200:
        return True, "relay will pull this camera on demand"
    return False, f"relay refused the path ({code}): {msg[:120]}"


def resync_all():
    """Reconcile every pull camera with the relay — after a relay restart, or
    a deploy that recreated the container."""
    from .models import Camera
    done = []
    for cam in Camera.objects.exclude(source_url=""):
        ok, msg = sync_relay_path(cam)
        done.append((cam.path, ok, msg))
    return done
