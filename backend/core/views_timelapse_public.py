"""Public, token-gated view of one camera's time-lapse (no login).

For a client whose portal is not live yet (owner 2026-11-01): an unguessable
link opens the video and nothing else. It always shows the latest build, and
stopping the link ends it for good.
"""
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from . import timelapse as tl
from .pdf import company_info
from .models import TimelapseReel


def _resolve(token):
    reel = (TimelapseReel.objects
            .select_related("site", "camera__project")
            .filter(share_token=token).first() if token else None)
    if reel is None:
        raise Http404
    return reel


def _private(resp):
    resp["X-Robots-Tag"] = "noindex, nofollow"
    resp["Referrer-Policy"] = "no-referrer"
    return resp


def shared_reel(request, token):
    reel = _resolve(token)
    cam = reel.camera
    return _private(render(request, "timelapse/shared.html", {
        "title": cam.project.title if cam.project_id else reel.site.name,
        "location": cam.location, "reel": reel,
        "contractor": company_info()["legal_name"],
        "video_url": (reverse("timelapse-share-video", args=[token])
                      if reel.file else None),
        "download_url": (reverse("timelapse-share-download", args=[token])
                         if reel.file else None)}))


def shared_reel_video(request, token):
    """To the stored file by a freshly signed address, so the page's own link
    never carries one that expires."""
    reel = _resolve(token)
    if not reel.file:
        raise Http404
    resp = _private(HttpResponseRedirect(reel.file.url))
    resp["Cache-Control"] = "no-store"
    return resp


def shared_reel_download(request, token):
    """The same video to save, addressed the same way."""
    reel = _resolve(token)
    if not reel.file:
        raise Http404
    resp = _private(HttpResponseRedirect(tl.download_url(reel, request)))
    resp["Cache-Control"] = "no-store"
    return resp
