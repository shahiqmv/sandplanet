"""What build the browser is running, so the app can say when it is stale.

The desktop app's service worker never caches a navigation, so a reload always
lands on the current build — but an installed window has no address bar and no
visible refresh, and people leave it open for days. Nothing told them a new
release existed (owner 2026-08-30).

The id is a hash of the built index.html. It changes exactly when the client
code changes, which is the only thing a reload actually fixes: a backend-only
deploy needs nothing from the browser, and prompting for one would train
people to ignore the prompt.
"""
import hashlib
from pathlib import Path

from django.conf import settings
from rest_framework.decorators import (api_view, authentication_classes,
                                       permission_classes)
from rest_framework.response import Response

_cached = None


def _index_html():
    return Path(settings.BASE_DIR).parent / "frontend" / "dist" / "index.html"


def build_id():
    """Computed once per process. A deploy restarts the container, so the
    value is always the one being served."""
    global _cached
    if _cached is None:
        try:
            _cached = hashlib.sha256(
                _index_html().read_bytes()).hexdigest()[:12]
        except OSError:
            _cached = "dev"
    return _cached


@api_view(["GET"])
def release_notes(request):
    """The last few releases, newest first — the "what changed" behind the
    reload prompt."""
    from .models import ReleaseNote

    try:
        limit = min(int(request.GET.get("limit", 12)), 50)
    except (TypeError, ValueError):
        limit = 12
    rows = ReleaseNote.objects.all()[:limit]
    return Response([{
        "id": n.id, "title": n.title, "body": n.body, "area": n.area,
        "released_on": n.released_on,
        "published_by": n.published_by.full_name if n.published_by_id else "",
    } for n in rows])


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def app_version(request):
    """Open deliberately: it carries no data, and a signed-out tab that has
    been sitting for a week should still be able to tell it is stale."""
    return Response({"build": build_id()})
