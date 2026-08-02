"""Client Portal (owner 2026-08-02) — the external, read-only realm.

The client is a SEPARATE principal (`ClientUser`), never the staff `User`.
Isolation is structural, not conventional:
  * client endpoints attach ONLY `ClientTokenAuthentication` — a staff session
    cookie is never read there, so staff can't reach client APIs;
  * staff endpoints never attach `ClientTokenAuthentication`, and a `ClientUser`
    has no `.role`, so a client token can never satisfy a staff endpoint.
All content is served through allowlist serialisers elsewhere; this file only
identifies the client and gates access.
"""
import secrets

from django.utils import timezone
from rest_framework import authentication, exceptions
from rest_framework.permissions import BasePermission

from .models import ClientSession, ClientUser


def new_token():
    return secrets.token_urlsafe(32)


class ClientTokenAuthentication(authentication.BaseAuthentication):
    """`Authorization: Bearer <token>` → the ClientUser. Sliding 30-day idle."""

    keyword = b"bearer"

    def authenticate(self, request):
        parts = authentication.get_authorization_header(request).split()
        if not parts or parts[0].lower() != self.keyword:
            return None
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Malformed token header.")
        try:
            session = ClientSession.objects.select_related("client").get(
                token=parts[1].decode())
        except (ClientSession.DoesNotExist, UnicodeDecodeError):
            raise exceptions.AuthenticationFailed("Invalid session.")
        if not session.is_active or not session.client.is_active:
            raise exceptions.AuthenticationFailed(
                "Session expired — please sign in again.")
        ClientSession.objects.filter(pk=session.pk).update(
            last_seen=timezone.now())
        request.client_session = session
        return (session.client, session)

    def authenticate_header(self, request):
        return "Bearer"


class IsClient(BasePermission):
    """Only an authenticated ClientUser — never a staff principal."""

    def has_permission(self, request, view):
        return isinstance(getattr(request, "user", None), ClientUser)


def client_site_ids(client):
    """The site ids a client may see — their assigned sites only. Anything
    outside this is a 404 (never 403 — don't reveal a site exists)."""
    return set(client.sites.values_list("id", flat=True))
