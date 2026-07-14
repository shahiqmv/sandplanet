"""Planet Mobile API routes — mounted at /api/mobile/v1/."""
from django.urls import path

from . import views_mobile as m

urlpatterns = [
    path("auth/login", m.m_login, name="m-login"),
    path("auth/logout", m.m_logout, name="m-logout"),
    path("me", m.m_me, name="m-me"),
    path("queue", m.m_queue, name="m-queue"),
    path("actioned", m.m_actioned, name="m-actioned"),
    path("documents/<str:ref>", m.m_document, name="m-document"),
    path("documents/<str:ref>/approve", m.m_approve, name="m-approve"),
    path("documents/<str:ref>/return", m.m_return, name="m-return"),
    path("requests", m.m_requests, name="m-requests"),
    path("requests/<str:ref>/timeline", m.m_timeline, name="m-timeline"),
    path("alerts", m.m_alerts, name="m-alerts"),
    path("alerts/read", m.m_alerts_read, name="m-alerts-read"),
    path("push/vapid-key", m.m_vapid_key, name="m-vapid-key"),
    path("push/subscribe", m.m_push_subscribe, name="m-push-subscribe"),
    path("push/unsubscribe", m.m_push_unsubscribe, name="m-push-unsubscribe"),
]
