"""The bridge between the two instances (Sand Planet and Sandplanet Marine,
owner 2026-09-26): separate databases, one trust.

* Handoff — a signed-in user switching apps carries a short-lived token the
  other instance redeems for a session of its own (no second sign-in).
* Peer verify — someone signing in cold on an instance that does not hold
  their password is checked against the sister instance over the private
  network; the password never leaves the instance that owns it.

Both need PEER_AUTH_SECRET (the same value in both .env files). A user who
arrives over the bridge is MIRRORED: same username, name, email and phone,
an unusable local password, `home_instance` naming where the password
lives. Roles are this instance's own business — the arriving user keeps the
sister role as a starting point and the admin changes it here."""
import hashlib
import hmac
import json
import urllib.error
import urllib.request

from django.conf import settings
from django.core import signing

SALT = "planet-peer-sso"
MAX_AGE = 90            # seconds a handoff token lives


def enabled():
    return bool(getattr(settings, "PEER_AUTH_SECRET", ""))


def instance_name():
    return (getattr(settings, "APP_PREFIX", "") or "").strip("/") or "planet"


def _profile(user):
    return {"u": user.username, "n": user.full_name, "e": user.email or "",
            "p": user.phone or "", "r": user.role, "src": instance_name()}


def issue_handoff(user):
    return signing.dumps(_profile(user), key=settings.PEER_AUTH_SECRET, salt=SALT)


def redeem_handoff(token):
    """The profile inside a valid, fresh token, or None."""
    try:
        p = signing.loads(token, key=settings.PEER_AUTH_SECRET, salt=SALT, max_age=MAX_AGE)
    except (signing.BadSignature, signing.SignatureExpired):
        return None
    if not isinstance(p, dict) or not p.get("u") or p.get("src") == instance_name():
        return None
    return p


def sign_body(body: bytes) -> str:
    return hmac.new(settings.PEER_AUTH_SECRET.encode(), body, hashlib.sha256).hexdigest()


def signature_ok(body: bytes, given: str) -> bool:
    return bool(given) and hmac.compare_digest(sign_body(body), given)


def verify_at_peer(username, password):
    """Ask the sister instance whether these credentials are its own. The
    profile on success; None on refusal, silence or no peer configured."""
    base = (getattr(settings, "PEER_URL", "") or "").rstrip("/")
    if not enabled() or not base or not username or not password:
        return None
    body = json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        f"{base}/auth/peer-verify", data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Peer-Signature": sign_body(body),
                 "Host": "localhost"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, ValueError, OSError):
        return None
    return data if isinstance(data, dict) and data.get("u") else None


def mirror(profile, actor=None):
    """The local user for a profile from the sister instance — found by
    username, or created here with an unusable password. None when the
    local record has been deactivated here."""
    from .models import User
    from .audit import audit
    username = profile["u"]
    user = User.objects.filter(username=username).first()
    created = False
    if user is None:
        role = profile.get("r") if profile.get("r") in User.Role.values else User.Role.SITE_ADMIN
        user = User(username=username, role=role, home_instance=profile.get("src") or "peer")
        user.set_unusable_password()
        created = True
    elif not user.is_active:
        return None
    changed = []
    for attr, key in (("full_name", "n"), ("email", "e"), ("phone", "p")):
        v = profile.get(key) or ""
        if v and getattr(user, attr) != v:
            setattr(user, attr, v)
            changed.append(attr)
    if created or changed:
        user.save()
    if created:
        audit("user", user.id, "USER_MIRRORED", actor=actor,
              detail={"username": username, "from": profile.get("src"), "role": user.role})
    return user
