from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView

from core import views_pwa

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("core.urls")),
    path("api/mobile/v1/", include("core.urls_mobile")),
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

# Serve the built SPA (frontend/dist) same-origin — used by the team-review
# tunnel and by production; harmless in dev (dist may not exist).
if (settings.BASE_DIR.parent / "frontend" / "dist" / "index.html").exists():
    urlpatterns.append(
        path("", TemplateView.as_view(template_name="index.html"),
             name="spa-index")
    )
