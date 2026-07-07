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
router.register("items", views.ItemViewSet, basename="item")

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
    path("documents/<str:ref>/revisions", docs.document_revise,
         name="document-revise"),
    path("registers/dpr-tws", docs.register_dpr_tws, name="register-dpr-tws"),
    path("registers/<str:doc_type>", docs.register_generic,
         name="register-generic"),
    path("pending-items", docs.pending_items, name="pending-items"),
    path("pending-items/<int:pk>", docs.pending_items, name="pending-item"),
    path("mr/<str:ref>/lm-prefill", docs.mr_lm_prefill, name="mr-lm-prefill"),
    path("lm/<str:ref>/grn-prefill", docs.lm_grn_prefill, name="lm-grn-prefill"),
    path("dashboards/site/<int:site_id>", docs.dashboard_site,
         name="dashboard-site"),
    path("dashboards/ho", docs.dashboard_ho, name="dashboard-ho"),
    path("", include(router.urls)),
]
