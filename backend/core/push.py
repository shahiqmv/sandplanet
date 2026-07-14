"""Web Push (VAPID) delivery for Planet Mobile (R6).

A no-op until VAPID keys are set and `pywebpush` is installed (same defensive
pattern as the old external channel), so dev and tests never send. Configure in
the environment (.env):
    VAPID_PUBLIC_KEY=<base64url uncompressed public key>
    VAPID_PRIVATE_KEY=<base64url / PEM private key>
    VAPID_SUBJECT=mailto:it@sandplanet.mv
Generate a key pair once with: `python -m py_vapid --gen` (from pywebpush) or
any VAPID generator; the public key is handed to the browser to subscribe.
"""
import json
import logging
import os

log = logging.getLogger(__name__)


def vapid_public_key():
    return os.environ.get("VAPID_PUBLIC_KEY", "")


def _vapid():
    priv = os.environ.get("VAPID_PRIVATE_KEY")
    if not (priv and os.environ.get("VAPID_PUBLIC_KEY")):
        return None
    return {"private_key": priv,
            "sub": os.environ.get("VAPID_SUBJECT", "mailto:it@sandplanet.mv")}


def send_push(subscription, title, body, url=""):
    """Deliver one push; drop the subscription if the endpoint is gone (410).
    Returns True on success, False on a handled failure, None if not configured.
    """
    cfg = _vapid()
    if not cfg:
        return None
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:                     # pragma: no cover - dep optional
        return None
    info = {"endpoint": subscription.endpoint,
            "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}}
    payload = json.dumps({"title": title, "body": body, "url": url})
    try:
        webpush(subscription_info=info, data=payload,
                vapid_private_key=cfg["private_key"],
                vapid_claims={"sub": cfg["sub"]})
        from django.utils import timezone
        subscription.last_success = timezone.now()
        subscription.save(update_fields=["last_success"])
        return True
    except WebPushException as exc:         # pragma: no cover - network
        resp = getattr(exc, "response", None)
        if resp is not None and resp.status_code in (404, 410):
            subscription.delete()           # gone — stop trying this endpoint
        else:
            log.warning("push failed for %s: %s", subscription.user_id, exc)
        return False


def dispatch_push(notification, user):
    """Push a Notification to all of a user's subscribed devices. Never raises."""
    from .models import PushSubscription
    url = f"/m/track/{notification.doc_ref}" if notification.doc_ref else "/m"
    for sub in PushSubscription.objects.filter(user=user):
        try:
            send_push(sub, notification.title, notification.body, url)
        except Exception:                   # pragma: no cover - defensive
            log.exception("dispatch_push failed")
