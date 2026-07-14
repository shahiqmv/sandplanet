"""Planet Mobile API (R6) — /api/mobile/v1/.

A thin, token-authenticated client surface over the existing business logic.
No new rules live here: queues reuse the desktop 'waiting on you' computation,
actions call the same transition service, and scoping is server-enforced.
"""
from django.contrib.auth import authenticate as dj_authenticate
from rest_framework.decorators import (api_view, authentication_classes,
                                       permission_classes)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .audit import audit
from .mobile import MobileTokenAuthentication, new_token
from .models import MobileDevice
from .permissions import scoped_site_ids

MOBILE_AUTH = [MobileTokenAuthentication]


def me_payload(user):
    sids = scoped_site_ids(user)
    return {
        "id": user.id, "username": user.username,
        "full_name": user.full_name, "role": user.role,
        "role_label": user.get_role_display(),
        "is_signatory": user.role == "SIGNATORY",
        "all_sites": sids is None,
        "sites": [] if sids is None else sorted(sids),
    }


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def m_login(request):
    """Sign in with the existing Planet username + password; returns a device
    token to carry as a Bearer header."""
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""
    user = dj_authenticate(username=username, password=password)
    if not user or not user.is_active:
        return Response({"detail": "Wrong username or password."}, status=401)
    device = MobileDevice.objects.create(
        user=user, token=new_token(),
        label=(request.META.get("HTTP_USER_AGENT") or "")[:120])
    audit("user", user.id, "MOBILE_SIGN_IN", actor=user,
          detail={"device": device.id})
    return Response({"token": device.token, "user": me_payload(user)},
                    status=201)


@api_view(["POST"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_logout(request):
    """Revoke this device's token (and, later, its push subscription)."""
    device = getattr(request, "mobile_device", None)
    if device:
        MobileDevice.objects.filter(pk=device.pk).update(revoked=True)
    return Response({"detail": "Signed out."})


@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_me(request):
    return Response(me_payload(request.user))
