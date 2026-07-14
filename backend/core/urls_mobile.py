"""Planet Mobile API routes — mounted at /api/mobile/v1/."""
from django.urls import path

from . import views_mobile as m

urlpatterns = [
    path("auth/login", m.m_login, name="m-login"),
    path("auth/logout", m.m_logout, name="m-logout"),
    path("me", m.m_me, name="m-me"),
]
