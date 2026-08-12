from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView

from core import (views_cameras, views_procurement_public, views_pwa,
                  views_tracking)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("core.urls")),
    path("api/mobile/v1/", include("core.urls_mobile")),
    path("api/client/", include("core.urls_client")),
    # Public, secret-verified provider webhook (outside the session-auth API).
    path("api/webhooks/tracking/shipsgo/", views_tracking.shipsgo_webhook,
         name="shipsgo-webhook"),
    # The camera relay's auth hook. Not session-authenticated (MediaMTX is not
    # a user); the relay proves itself with a shared secret in the path, since
    # MediaMTX cannot set a header on this call. Caddy refuses to proxy
    # /api/relay/ from the internet, so this is container-network only.
    path("api/relay/auth/<str:secret>", views_cameras.relay_auth,
         name="relay-auth"),
    # Public, token-gated client view of a procurement schedule (no login).
    path("share/procurement/<str:token>",
         views_procurement_public.client_plan_page, name="psc-client-plan"),
    path("share/procurement/<str:token>/plan.xlsx",
         views_procurement_public.client_plan_xlsx, name="psc-client-xlsx"),
]

if settings.DEBUG:  # local-disk media fallback only (DECISIONS.md D3)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Planet Mobile PWA shell (frontend/dist/m.html) + its manifest / service
# worker. Deep-link paths like /m/track/<ref> also render the shell; the app
# reads the path client-side. Guarded on the built file like the SPA below.
if (settings.BASE_DIR.parent / "frontend" / "dist" / "m.html").exists():
    urlpatterns += [
        path("m/manifest.webmanifest", views_pwa.mobile_manifest,
             name="mobile-manifest"),
        path("m/sw.js", views_pwa.mobile_service_worker, name="mobile-sw"),
        re_path(r"^m(/.*)?$",
                TemplateView.as_view(template_name="m.html"),
                name="mobile-shell"),
    ]

# Client Portal shell (frontend/dist/portal.html) — the isolated external
# realm at /portal/. A separate Vite entry; the app talks only to /api/client.
if (settings.BASE_DIR.parent / "frontend" / "dist" / "portal.html").exists():
    urlpatterns.append(
        re_path(r"^portal(/.*)?$",
                TemplateView.as_view(template_name="portal.html"),
                name="client-portal-shell"))

# Serve the built SPA (frontend/dist) same-origin — used by the team-review
# tunnel and by production; harmless in dev (dist may not exist).
if (settings.BASE_DIR.parent / "frontend" / "dist" / "index.html").exists():
    urlpatterns.append(
        path("", TemplateView.as_view(template_name="index.html"),
             name="spa-index")
    )
