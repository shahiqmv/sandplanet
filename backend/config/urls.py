from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("core.urls")),
]

if settings.DEBUG:  # local-disk media fallback only (DECISIONS.md D3)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
