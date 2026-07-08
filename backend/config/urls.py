from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("core.urls")),
]

if settings.DEBUG:  # local-disk media fallback only (DECISIONS.md D3)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Serve the built SPA (frontend/dist) same-origin — used by the team-review
# tunnel and by production; harmless in dev (dist may not exist).
if (settings.BASE_DIR.parent / "frontend" / "dist" / "index.html").exists():
    urlpatterns.append(
        path("", TemplateView.as_view(template_name="index.html"),
             name="spa-index")
    )
