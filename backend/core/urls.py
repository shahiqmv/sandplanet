from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views, views_documents as docs, views_hr as hr, \
    views_projects as projects, views_quotes as quotes

router = DefaultRouter(trailing_slash=False)  # API surface per design §3
router.register("sites", views.SiteViewSet, basename="site")
router.register("users", views.UserViewSet, basename="user")
router.register(
    "manpower-categories", views.ManpowerCategoryViewSet, basename="manpowercategory"
)
router.register("holidays", views.HolidayViewSet, basename="holiday")
router.register("items", views.ItemViewSet, basename="item")
router.register("suppliers", quotes.SupplierViewSet, basename="supplier")
router.register("employees", hr.EmployeeViewSet, basename="employee")

urlpatterns = [
    path("health", views.health, name="health"),
    path("auth/login", views.auth_login, name="auth-login"),
    path("auth/logout", views.auth_logout, name="auth-logout"),
    path("auth/me", views.auth_me, name="auth-me"),
    path("parameters/<str:key>", views.parameter_detail, name="parameter-detail"),
    path("pms", views.pm_list, name="pm-list"),
    path("pm-overview", views.pm_overview, name="pm-overview"),
    path("dma-prefill", docs.dma_prefill, name="dma-prefill"),
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
    path("mr/<str:ref>/related", docs.mr_related, name="mr-related"),
    path("lm/<str:ref>/grn-prefill", docs.lm_grn_prefill, name="lm-grn-prefill"),
    path("po/<str:ref>/lm-prefill", docs.po_lm_prefill, name="po-lm-prefill"),
    path("pr/<str:ref>/quotations", quotes.pr_quotations, name="pr-quotations"),
    path("pr/<str:ref>/coverage", quotes.pr_coverage, name="pr-coverage"),
    path("pr/<str:ref>/sync-vendor-rows", quotes.pr_sync_vendor_rows,
         name="pr-sync-vendor-rows"),
    path("pr/<str:ref>/vendor-payment", quotes.pr_vendor_payment,
         name="pr-vendor-payment"),
    path("quotations/<int:pk>", quotes.quotation_detail, name="quotation-detail"),
    path("quotations/<int:pk>/file", quotes.quotation_file,
         name="quotation-file"),
    path("dashboards/site/<int:site_id>", docs.dashboard_site,
         name="dashboard-site"),
    path("dashboards/ho", docs.dashboard_ho, name="dashboard-ho"),
    path("sites/<int:site_id>/projects", projects.site_projects,
         name="site-projects"),
    path("projects/<int:pk>", projects.project_detail, name="project-detail"),
    path("projects/<int:pk>/programme", projects.project_programme,
         name="project-programme"),
    path("programme-activities/<int:pk>", projects.activity_detail,
         name="activity-detail"),
    path("attendance", hr.attendance_grid, name="attendance-grid"),
    path("attendance/bulk", hr.attendance_bulk, name="attendance-bulk"),
    path("attendance/ot-approve", hr.ot_approve, name="ot-approve"),
    path("timesheets/<int:site_id>/<int:year>/<int:month>/lock",
         hr.timesheet_lock, name="timesheet-lock"),
    path("timesheets/<int:site_id>/<int:year>/<int:month>/reopen",
         hr.timesheet_reopen, name="timesheet-reopen"),
    path("payroll-export/<int:year>/<int:month>", hr.payroll_export,
         name="payroll-export"),
    path("", include(router.urls)),
]
