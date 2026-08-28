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


# ---- Planet Desktop ------------------------------------------------------
# The same SPA, made installable: its own Dock/taskbar icon, a standalone
# window, and desktop push. Scope is the whole site (the app navigates by
# hash), so the worker is served from / with Service-Worker-Allowed:/.
# Distinct start_url from /m/ = a distinct installed app, so a laptop that
# also installed Planet Mobile keeps two separate entries (owner 2026-08-28).
DESKTOP_MANIFEST = {
    "id": "/",
    "name": "Sand Planet — Project Management",
    "short_name": "Sand Planet",
    "description": "Sand Planet project management: sites, procurement, "
                   "approvals and finance.",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#F6F2E9",
    "theme_color": "#16527E",
    "categories": ["business", "productivity"],
    "icons": [
        {"src": "/static/desktop/icon-192.png", "sizes": "192x192",
         "type": "image/png", "purpose": "any"},
        {"src": "/static/desktop/icon-512.png", "sizes": "512x512",
         "type": "image/png", "purpose": "any"},
        {"src": "/static/desktop/icon-512.png", "sizes": "512x512",
         "type": "image/png", "purpose": "maskable"},
    ],
    # Dock / taskbar right-click menu. Only pages every role can reach.
    "shortcuts": [
        {"name": "My Tasks", "url": "/#/ho/approvals",
         "icons": [{"src": "/static/desktop/icon-192.png", "sizes": "192x192"}]},
        {"name": "Sites", "url": "/#/ho/sites",
         "icons": [{"src": "/static/desktop/icon-192.png", "sizes": "192x192"}]},
    ],
}


def desktop_manifest(request):
    return JsonResponse(DESKTOP_MANIFEST,
                        content_type="application/manifest+json")


def desktop_service_worker(request):
    js = render_to_string("desktop/sw.js")
    resp = HttpResponse(js, content_type="application/javascript")
    resp["Service-Worker-Allowed"] = "/"
    resp["Cache-Control"] = "no-cache"
    return resp
