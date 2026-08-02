"""Client Portal endpoints — the external read-only realm (owner 2026-08-02).

Every view here authenticates ONLY with a client token and permits ONLY a
ClientUser. Content is served through explicit allowlist dicts — adding a field
is a deliberate code change, never inherited — and scoped to the client's own
sites (a site outside their set is a 404, never a 403).
"""
from django.utils import timezone
from rest_framework.decorators import (api_view, authentication_classes,
                                        permission_classes)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .client_portal import (ClientTokenAuthentication, IsClient,
                            client_site_ids, new_token)
from .models import ClientSession, ClientUser


def _client_dict(c):
    return {
        "full_name": c.full_name, "org_name": c.org_name, "email": c.email,
        "must_change_password": c.must_change_password,
        "sites": [{"id": s.id, "code": s.code, "name": s.name}
                  for s in c.sites.all().order_by("code")],
    }


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def client_login(request):
    """Email + password → a client session token. Deliberately vague on
    failure (no user enumeration)."""
    email = (request.data.get("email") or "").strip().lower()
    password = request.data.get("password") or ""
    client = ClientUser.objects.filter(email__iexact=email,
                                       is_active=True).first()
    if not client or not client.check_password(password):
        return Response({"detail": "Wrong email or password."}, status=401)
    session = ClientSession.objects.create(client=client, token=new_token())
    client.last_login = timezone.now()
    client.save(update_fields=["last_login"])
    return Response({"token": session.token, **_client_dict(client)})


@api_view(["POST"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_logout(request):
    s = getattr(request, "client_session", None)
    if s:
        ClientSession.objects.filter(pk=s.pk).update(revoked=True)
    return Response(status=204)


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_me(request):
    return Response(_client_dict(request.user))


@api_view(["POST"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_change_password(request):
    client = request.user
    if not client.check_password(request.data.get("current_password") or ""):
        return Response({"detail": "Current password is wrong."}, status=400)
    new = request.data.get("new_password") or ""
    if len(new) < 8:
        return Response({"detail": "Use at least 8 characters."}, status=400)
    client.set_password(new)
    client.must_change_password = False
    client.save(update_fields=["password", "must_change_password"])
    return Response({"detail": "Password changed."})


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_sites(request):
    """The client's assigned sites — minimal, allowlisted."""
    return Response([
        {"id": s.id, "code": s.code, "name": s.name,
         "status": s.status,
         "has_cameras": False}          # cameras: Phase-later, always false now
        for s in request.user.sites.all().order_by("code")])
