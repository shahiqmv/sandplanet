"""Approval / attention notifications.

When a document transitions into a state that blocks a specific person or role,
we create a Notification for each target, surfaced by the in-app bell (and,
once Planet Mobile ships, delivered by web push). Creating a notification must
never break the transition that triggered it, so everything here is wrapped
defensively. (The SMS/WhatsApp delivery track was dropped — superseded by the
mobile companion, owner 2026-07-14.)
"""
import logging

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
    if t in ("MR", "IR", "MAR", "PMR") and s == "SUBMITTED":
        return [(u, "needs your approval") for u in _pm_for(doc)]
    if t == "PYR" and s == "SUBMITTED":
        # Site requests go to the PM; Head-Office (central) requests have no
        # site PM and go straight to the Director (owner 2026-07-13).
        pr = getattr(doc, "payment_request", None)
        if pr and pr.origin != "SITE":
            return [(u, "needs Director approval")
                    for u in _role_users("DIRECTOR")]
        return [(u, "needs your approval") for u in _pm_for(doc)]
    if t == "PMR" and s == "PM_APPROVED":
        return [(u, "to review") for u in _role_users("HO_PURCHASING")]
    if t == "PMR" and s == "HO_REVIEWED":
        return [(u, "to size & release") for u in _role_users("DIRECTOR")]
    if t == "PMR" and s == "SIZED_RELEASED":
        # sized & released — Purchasing must now place the overseas order
        return [(u, "to order") for u in _role_users("HO_PURCHASING")]
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
            Notification.objects.create(
                recipient=user,
                title=f"{doc.doc_type} {doc.ref} {hint}",
                body=_body(doc), doc_ref=doc.ref, doc_type=doc.doc_type,
                doc_status=doc.status)
    except Exception:                       # pragma: no cover - defensive
        log.exception("notify_document failed for %s", getattr(doc, "ref", "?"))


def notify_user(user, title, body="", doc=None, category="alert"):
    """Ad-hoc notification (e.g. an import payment falling due)."""
    try:
        return Notification.objects.create(
            recipient=user, title=title, body=body, category=category,
            doc_ref=getattr(doc, "ref", "") or "",
            doc_type=getattr(doc, "doc_type", "") or "",
            doc_status=getattr(doc, "status", "") or "")
    except Exception:                       # pragma: no cover - defensive
        log.exception("notify_user failed")
        return None
