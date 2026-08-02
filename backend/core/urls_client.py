"""Client Portal URL space (`/api/client/`) — the isolated external realm.
Only ClientUser tokens authenticate here; staff sessions never reach it."""
from django.urls import path

from . import views_client

urlpatterns = [
    path("auth/login", views_client.client_login, name="client-login"),
    path("auth/logout", views_client.client_logout, name="client-logout"),
    path("auth/change-password", views_client.client_change_password,
         name="client-change-password"),
    path("me", views_client.client_me, name="client-me"),
    path("sites", views_client.client_sites, name="client-portal-sites"),
    path("sites/<int:pk>", views_client.client_site, name="client-portal-site"),
    path("sites/<int:pk>/procurement", views_client.client_site_procurement,
         name="client-portal-procurement"),
    path("sites/<int:pk>/procurement.xlsx",
         views_client.client_site_procurement_xlsx,
         name="client-portal-procurement-xlsx"),
]
