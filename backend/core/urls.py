from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

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
    path("", include(router.urls)),
]
