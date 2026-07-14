"""Planet Mobile (R6) — device-token auth for the PWA companion.

The desktop SPA uses session auth; the mobile app is a separate origin and
needs a long-lived, per-device token it can hold for ~30 days and that an
admin can revoke if a phone is lost. A single sliding-expiry `MobileDevice`
token gives the "30-day rolling" behaviour without a JWT dependency. All
business rules stay server-side — the token only identifies the user; role and
site scoping are enforced exactly as on desktop.
"""
import secrets

from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import MobileDevice


def new_token():
    return secrets.token_urlsafe(32)


class MobileTokenAuthentication(authentication.BaseAuthentication):
    """`Authorization: Bearer <token>` → the device's user. Bumps last_seen so
    the 30-day idle window rolls forward on use."""

    keyword = b"bearer"

    def authenticate(self, request):
        parts = authentication.get_authorization_header(request).split()
        if not parts or parts[0].lower() != self.keyword:
            return None
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Malformed token header.")
        try:
            device = MobileDevice.objects.select_related("user").get(
                token=parts[1].decode())
        except (MobileDevice.DoesNotExist, UnicodeDecodeError):
            raise exceptions.AuthenticationFailed("Invalid token.")
        if not device.is_active or not device.user.is_active:
            raise exceptions.AuthenticationFailed(
                "Session expired — please sign in again.")
        MobileDevice.objects.filter(pk=device.pk).update(
            last_seen=timezone.now())
        request.mobile_device = device
        return (device.user, device)

    def authenticate_header(self, request):
        return "Bearer"
