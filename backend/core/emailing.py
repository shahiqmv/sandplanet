"""Shared outbound-email builder (owner 2026-08-08).

Every app email goes out From a single fixed sender (DEFAULT_FROM_EMAIL, e.g.
notifications@sandplanet.mv — an alias of the authenticated mailbox, so SPF/DKIM
stay aligned and Zoho accepts it), but the DISPLAY NAME is the acting user and
Reply-To is that user's email — so recipients see who it's from and a reply
reaches that person directly. When the user has no email, Reply-To falls back to
the office inbox (REPLY_TO_FALLBACK), so no reply is ever lost.
"""
from email.utils import formataddr

from django.conf import settings
from django.core.mail import EmailMultiAlternatives


def reply_fallback():
    return getattr(settings, "REPLY_TO_FALLBACK", None) \
        or settings.DEFAULT_FROM_EMAIL


def build_email(subject, body, to, *, from_user=None, reply_to=None,
                html=None):
    """An EmailMultiAlternatives with the shared From/Reply-To scheme. Attach
    files/alternatives on the returned object as usual, then .send()."""
    sender = settings.DEFAULT_FROM_EMAIL
    name = ""
    if from_user is not None:
        name = (getattr(from_user, "full_name", "") or "").strip()
    from_header = formataddr((f"{name} · Sand Planet", sender)) if name \
        else sender
    reply = reply_to \
        or (getattr(from_user, "email", "") if from_user else "") \
        or reply_fallback()
    msg = EmailMultiAlternatives(subject, body, from_header, list(to),
                                 reply_to=[reply])
    if html:
        msg.attach_alternative(html, "text/html")
    return msg
