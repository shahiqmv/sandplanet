"""Approval / attention notifications.

When a document transitions into a state that blocks a specific person or role,
we create a Notification for each target (surfaced by the in-app bell) and — if
that user has a phone and external delivery is configured — push it by
SMS/WhatsApp. Creating a notification must never break the transition that
triggered it, so everything here is wrapped defensively.

External delivery mirrors the email pattern: it is a no-op until the provider
env vars are set, so nothing is sent in dev or before Twilio is configured.
Configure in the environment (.env):
    NOTIFY_PROVIDER=twilio
    TWILIO_ACCOUNT_SID=AC...
    TWILIO_AUTH_TOKEN=...
    TWILIO_FROM=+9607...            (or a WhatsApp sender)
    TWILIO_CHANNEL=sms             (or "whatsapp")
"""
import logging
import os
import urllib.parse
import urllib.request
from base64 import b64encode

from django.utils import timezone

from .models import Notification, User

log = logging.getLogger(__name__)


def _role_users(*roles):
    return list(User.objects.filter(role__in=roles, is_active=True))


def _pm_for(doc):
    """The project's PM if the document belongs to a project that has one, else
    the site's current PM."""
    if doc.project_id and getattr(doc.project, "pm_id", None):
        u = User.objects.filter(pk=doc.project.pm_id, is_active=True).first()
        if u:
            return [u]
    pm = doc.site.current_pm() if doc.site_id else None
    return [pm] if pm else []


def targets_for(doc):
    """(user, hint) pairs who must act on `doc` in its current state. Mirrors
    the per-role 'waiting on you' queue (approvals_pending)."""
    t, s = doc.doc_type, doc.status
    if t in ("MR", "IR", "MAR", "PMR", "PYR") and s == "SUBMITTED":
        return [(u, "needs your approval") for u in _pm_for(doc)]
    if t == "PMR" and s == "PM_APPROVED":
        return [(u, "to review") for u in _role_users("HO_PURCHASING")]
    if t == "PMR" and s == "HO_REVIEWED":
        return [(u, "to size & release") for u in _role_users("DIRECTOR")]
    if t == "DPR" and s == "ISSUED":
        return [(u, "to verify") for u in _pm_for(doc)]
    if t == "GRN" and s == "COUNTED":
        return [(u, "to verify") for u in _pm_for(doc)]
    if t in ("PR", "IPR") and s == "SUBMITTED":
        return [(u, "to award") for u in _role_users("DIRECTOR")]
    if t == "PR" and s == "APPROVED":
        return [(u, "awaiting a payment voucher")
                for u in _role_users("FINANCE")]
    if t == "IPR" and s == "APPROVED":
        # placing the order is the commitment, not a payment — a signatory
        # authorises the order directly (no voucher)
        return [(u, "to authorise") for u in _role_users("SIGNATORY")]
    if t == "PYR" and s == "PM_APPROVED":
        return [(u, "needs Director approval") for u in _role_users("DIRECTOR")]
    if t == "PYR" and s == "DIRECTOR_APPROVED":
        return [(u, "awaiting a payment voucher")
                for u in _role_users("FINANCE")]
    if t == "PYR" and s == "AUTHORISED":
        return [(u, "to pay") for u in _role_users("FINANCE")]
    if t == "PV" and s == "SUBMITTED":
        return [(u, "to approve") for u in _role_users("SIGNATORY")]
    return []


def _body(doc):
    site = doc.site.code if doc.site_id else ""
    parts = [p for p in (site, str(doc.doc_date))
             if p and p != "None"]
    return " · ".join(parts)


def notify_document(doc, actor=None):
    """Create + dispatch notifications for whoever the document now blocks.
    Never raises — a notification failure must not roll back the transition."""
    try:
        for user, hint in targets_for(doc):
            if actor and user.id == actor.id:
                continue
            if Notification.objects.filter(
                    recipient=user, doc_ref=doc.ref, doc_status=doc.status,
                    read_at__isnull=True).exists():
                continue
            n = Notification.objects.create(
                recipient=user,
                title=f"{doc.doc_type} {doc.ref} {hint}",
                body=_body(doc), doc_ref=doc.ref, doc_type=doc.doc_type,
                doc_status=doc.status)
            _dispatch_external(n, user)
    except Exception:                       # pragma: no cover - defensive
        log.exception("notify_document failed for %s", getattr(doc, "ref", "?"))


def notify_user(user, title, body="", doc=None, category="alert"):
    """Ad-hoc notification (e.g. an import payment falling due)."""
    try:
        n = Notification.objects.create(
            recipient=user, title=title, body=body, category=category,
            doc_ref=getattr(doc, "ref", "") or "",
            doc_type=getattr(doc, "doc_type", "") or "",
            doc_status=getattr(doc, "status", "") or "")
        _dispatch_external(n, user)
        return n
    except Exception:                       # pragma: no cover - defensive
        log.exception("notify_user failed")
        return None


# ---- External delivery (SMS / WhatsApp via Twilio) -----------------------

def _twilio_config():
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    sender = os.environ.get("TWILIO_FROM")
    if not (sid and token and sender):
        return None
    channel = (os.environ.get("TWILIO_CHANNEL") or "sms").lower()
    return {"sid": sid, "token": token, "from": sender, "channel": channel}


def _dispatch_external(notification, user):
    """Send the notification by SMS/WhatsApp if the user opted in, has a phone,
    and a provider is configured. No-op otherwise."""
    if not user.notify_external or not user.phone:
        return
    cfg = _twilio_config()
    if not cfg:
        return
    try:
        _twilio_send(cfg, user.phone,
                     f"{notification.title}\n{notification.body}".strip())
        notification.external_sent_at = timezone.now()
        notification.save(update_fields=["external_sent_at"])
    except Exception:                       # pragma: no cover - network
        log.exception("SMS/WhatsApp send failed for %s", user.username)


def _twilio_send(cfg, to_phone, message):
    prefix = "whatsapp:" if cfg["channel"] == "whatsapp" else ""
    data = urllib.parse.urlencode({
        "From": f"{prefix}{cfg['from']}",
        "To": f"{prefix}{to_phone}",
        "Body": message,
    }).encode()
    url = (f"https://api.twilio.com/2010-04-01/Accounts/{cfg['sid']}"
           f"/Messages.json")
    auth = b64encode(f"{cfg['sid']}:{cfg['token']}".encode()).decode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310
        return resp.status
