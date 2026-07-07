from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views, views_documents as docs

router = DefaultRouter(trailing_slash=False)  # API surface per design §3
router.register("sites", views.SiteViewSet, basename="site")
router.register("users", views.UserViewSet, basename="user")
router.register(
    "manpower-categories", views.ManpowerCategoryViewSet, basename="manpowercategory"
)
router.register("holidays", views.HolidayViewSet, basename="holiday")

urlpatterns = [
    path("health", views.health, name="health"),
    path("auth/login", views.auth_login, name="auth-login"),
    path("auth/logout", views.auth_logout, name="auth-logout"),
    path("auth/me", views.auth_me, name="auth-me"),
    path("parameters/<str:key>", views.parameter_detail, name="parameter-detail"),
    path("documents", docs.document_create, name="document-create"),
    path("documents/list", docs.documents_list, name="documents-list"),
    path("documents/<str:ref>", docs.document_detail, name="document-detail"),
    path("documents/<str:ref>/actions/<str:action_name>", docs.document_action,
         name="document-action"),
    path("documents/<str:ref>/attachments", docs.document_attachments,
         name="document-attachments"),
    path("registers/dpr-tws", docs.register_dpr_tws, name="register-dpr-tws"),
    path("dashboards/site/<int:site_id>", docs.dashboard_site,
         name="dashboard-site"),
    path("", include(router.urls)),
]
