"""Planet Mobile PWA shell resources — manifest + service worker.

These are served same-origin under /m/ (not through the DRF API): the web app
manifest, and the service worker (which must be served from /m/ with the
Service-Worker-Allowed header so its scope can cover the whole app).
"""
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string

MANIFEST = {
    "name": "Planet",
    "short_name": "Planet",
    "description": "Approvals & request tracking for Sand Planet.",
    "start_url": "/m/",
    "scope": "/m/",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#F6F2E9",
    "theme_color": "#16527E",
    "categories": ["business", "productivity"],
    "icons": [
        {"src": "/static/mobile/icon-192.png", "sizes": "192x192",
         "type": "image/png", "purpose": "any maskable"},
        {"src": "/static/mobile/icon-512.png", "sizes": "512x512",
         "type": "image/png", "purpose": "any maskable"},
    ],
}


def mobile_manifest(request):
    return JsonResponse(MANIFEST, content_type="application/manifest+json")


def mobile_service_worker(request):
    js = render_to_string("mobile/sw.js")
    resp = HttpResponse(js, content_type="application/javascript")
    # Let a /m/-served worker claim the whole /m/ scope.
    resp["Service-Worker-Allowed"] = "/m/"
    resp["Cache-Control"] = "no-cache"
    return resp
