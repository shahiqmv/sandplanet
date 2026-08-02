"""Staff-side management of Client Portal accounts (HO admin only). Runs in the
STAFF realm (session auth) — creating/assigning client logins is a staff act;
the client realm itself lives in views_client.py."""
import secrets

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .audit import audit
from .models import ClientUser, Site
from .permissions import IsAdmin


def _dict(c):
    return {
        "id": c.id, "org_name": c.org_name, "full_name": c.full_name,
        "email": c.email, "is_active": c.is_active,
        "must_change_password": c.must_change_password,
        "last_login": c.last_login,
        "sites": [{"id": s.id, "code": s.code, "name": s.name}
                  for s in c.sites.all().order_by("code")],
    }


def _set_sites(client, site_ids):
    if site_ids is None:
        return
    sites = Site.objects.filter(id__in=[int(s) for s in site_ids if s])
    client.sites.set(sites)


@api_view(["GET", "POST"])
@permission_classes([IsAdmin])
def client_users(request):
    if request.method == "POST":
        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"detail": "Email is required."}, status=400)
        if ClientUser.objects.filter(email__iexact=email).exists():
            return Response({"detail": "A client with that email exists."},
                            status=400)
        temp = secrets.token_urlsafe(9)
        client = ClientUser(
            org_name=(request.data.get("org_name") or "").strip(),
            full_name=(request.data.get("full_name") or "").strip(),
            email=email, must_change_password=True)
        client.set_password(temp)
        client.save()
        _set_sites(client, request.data.get("site_ids"))
        audit("client_user", client.id, "CLIENT_USER_CREATED",
              actor=request.user, detail={"email": email})
        # Return the temp password once so the admin can hand it over.
        return Response({**_dict(client), "temp_password": temp}, status=201)
    return Response([_dict(c) for c in ClientUser.objects.prefetch_related(
        "sites").all()])


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAdmin])
def client_user_detail(request, pk):
    client = ClientUser.objects.filter(pk=pk).first()
    if client is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "DELETE":
        client.is_active = False
        client.sessions.update(revoked=True)
        client.save(update_fields=["is_active"])
        audit("client_user", client.id, "CLIENT_USER_DEACTIVATED",
              actor=request.user)
        return Response(status=204)
    for f in ("org_name", "full_name"):
        if f in request.data:
            setattr(client, f, (request.data.get(f) or "").strip())
    if "is_active" in request.data:
        client.is_active = bool(request.data["is_active"])
        if not client.is_active:
            client.sessions.update(revoked=True)
    client.save()
    _set_sites(client, request.data.get("site_ids"))
    audit("client_user", client.id, "CLIENT_USER_UPDATED", actor=request.user)
    return Response(_dict(client))


@api_view(["POST"])
@permission_classes([IsAdmin])
def client_user_password(request, pk):
    """Reset a client's password to a fresh temp; revoke live sessions."""
    client = ClientUser.objects.filter(pk=pk).first()
    if client is None:
        return Response({"detail": "Not found."}, status=404)
    temp = secrets.token_urlsafe(9)
    client.set_password(temp)
    client.must_change_password = True
    client.save(update_fields=["password", "must_change_password"])
    client.sessions.update(revoked=True)
    audit("client_user", client.id, "CLIENT_USER_PW_RESET", actor=request.user)
    return Response({"temp_password": temp})
