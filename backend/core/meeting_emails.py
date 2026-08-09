"""Send meeting requests and minutes by email (owner 2026-08-08).

A meeting request goes out as a real calendar invite: a text/HTML email plus a
`.ics` attachment (METHOD:REQUEST) so recipients one-click add it to Outlook /
Google / Apple, and a resend after a reschedule supersedes the old event
(bumped SEQUENCE). Each recipient gets personal one-click RSVP links. Minutes go
out with the branded minutes PDF attached, once the minutes are Final.

Delivery uses Django's configured backend — real SMTP in production, the console
backend in dev — so nothing actually sends until EMAIL_HOST is set.
"""
import secrets
from datetime import timedelta, timezone as _dtz

from django.conf import settings
from django.utils import timezone

from .audit import audit
from .emailing import build_email
from .meetings import when_mvt
from .models import Meeting, MeetingAttendee

_LOC = {"OFFICE": "Head office", "SITE": "At site",
        "CLIENT": "Client's office", "ONLINE": "Online", "OTHER": ""}


def email_configured():
    """True when real SMTP is set up; False in dev (console backend)."""
    return bool(getattr(settings, "EMAIL_HOST", ""))


def _utc_stamp(dt):
    return dt.astimezone(_dtz.utc).strftime("%Y%m%dT%H%M%SZ")


def _esc(text):
    """Escape a value for an iCalendar text field."""
    return (str(text or "").replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def _location_str(meeting):
    if meeting.location_kind == "ONLINE":
        return meeting.meeting_link or "Online"
    base = _LOC.get(meeting.location_kind, "")
    if meeting.location_kind == "SITE" and meeting.site_id:
        base = meeting.site.name
    return " · ".join(x for x in (base, meeting.location_note) if x)


def _recipients(meeting):
    """(attendee, email, name) for every attendee we can reach by email —
    internal users by their account email, external guests by their own."""
    out = []
    for a in meeting.attendees.select_related("user").all():
        email = (a.user.email if a.user_id else a.email) or ""
        name = a.user.full_name if a.user_id else a.name
        if email.strip():
            out.append((a, email.strip(), name or email.strip()))
    return out


def _ensure_token(attendee):
    if not attendee.rsvp_token:
        attendee.rsvp_token = secrets.token_hex(16)
        attendee.save(update_fields=["rsvp_token"])
    return attendee.rsvp_token


def _rsvp_links(token):
    base = f"{settings.APP_BASE_URL.rstrip('/')}/api/v1/meetings/rsvp/{token}"
    return (f"{base}?r=yes", f"{base}?r=no", f"{base}?r=maybe")


def build_ics(meeting, method="REQUEST"):
    """A METHOD:REQUEST (or CANCEL) VEVENT for this meeting."""
    start = meeting.scheduled_at
    end = start + timedelta(minutes=meeting.duration_minutes or 60)
    org_email = (meeting.organiser.email if meeting.organiser_id else "") \
        or settings.DEFAULT_FROM_EMAIL
    org_name = meeting.organiser.full_name if meeting.organiser_id else "Sand Planet"
    desc_parts = []
    if meeting.agenda:
        desc_parts.append(meeting.agenda)
    if meeting.meeting_link:
        desc_parts.append(f"Join: {meeting.meeting_link}")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//Sand Planet//Meetings//EN", "CALSCALE:GREGORIAN",
        f"METHOD:{method}", "BEGIN:VEVENT",
        f"UID:meeting-{meeting.id}@sandplanet.mv",
        f"SEQUENCE:{meeting.ics_sequence}",
        f"DTSTAMP:{_utc_stamp(timezone.now())}",
        f"DTSTART:{_utc_stamp(start)}", f"DTEND:{_utc_stamp(end)}",
        f"SUMMARY:{_esc(meeting.title)}",
        f"DESCRIPTION:{_esc(chr(10).join(desc_parts))}",
        f"LOCATION:{_esc(_location_str(meeting))}",
        f"ORGANIZER;CN={_esc(org_name)}:mailto:{org_email}",
        "STATUS:" + ("CANCELLED" if method == "CANCEL" else "CONFIRMED"),
    ]
    for _a, email, name in _recipients(meeting):
        lines.append(
            f"ATTENDEE;CN={_esc(name)};RSVP=TRUE:mailto:{email}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines)


def send_invite(meeting, actor):
    """Email the meeting request (+ .ics + pre-read files) to every attendee we
    can reach. Returns (sent_count, skipped_names, error)."""
    recips = _recipients(meeting)
    if not recips:
        return 0, [], ("No attendee has an email address. Add emails to the "
                       "external guests (or internal users) first.")
    when = when_mvt(meeting.scheduled_at)
    where = _location_str(meeting)
    ics = build_ics(meeting, "REQUEST")
    files = list(meeting.files.all())
    # Replies to the invite reach the organiser (fallback: the office inbox).
    organiser = meeting.organiser if meeting.organiser_id else None
    subject = f"Meeting invitation — {meeting.title}"
    for attendee, email, name in recips:
        token = _ensure_token(attendee)
        yes, no, maybe = _rsvp_links(token)
        body = (
            f"Hello {name},\n\n"
            f"You're invited to: {meeting.title}\n"
            f"    When    : {when}\n"
            f"    Where   : {where or '—'}\n"
            + (f"    Join    : {meeting.meeting_link}\n"
               if meeting.meeting_link else "")
            + (f"\nAgenda:\n{meeting.agenda}\n" if meeting.agenda else "")
            + "\nPlease respond:\n"
            f"    Accept    : {yes}\n"
            f"    Decline   : {no}\n"
            f"    Tentative : {maybe}\n\n"
            "The calendar invite is attached — open it to add this to your "
            "calendar.\n\n— Sand Planet Pvt Ltd"
        )
        msg = build_email(subject, body, [email], from_user=organiser)
        msg.attach("invite.ics", ics, "text/calendar; method=REQUEST")
        msg.attach_alternative(ics, "text/calendar; method=REQUEST")
        for f in files:
            try:
                f.file.open("rb")
                msg.attach(f.file_name or "attachment",
                           f.file.read(), f.content_type or None)
            finally:
                f.file.close()
        msg.send(fail_silently=False)
    meeting.invite_sent_at = timezone.now()
    meeting.save(update_fields=["invite_sent_at", "updated_at"])
    audit("meeting", meeting.id, "MEETING_INVITE_SENT", actor=actor,
          detail={"recipients": len(recips)})
    skipped = [a.name or (a.user.full_name if a.user_id else "?")
               for a in meeting.attendees.all()
               if not ((a.user.email if a.user_id else a.email) or "").strip()]
    return len(recips), skipped, None


def send_minutes(meeting, actor):
    """Email the branded minutes PDF to every reachable attendee. Requires the
    minutes to be Final. Returns (sent_count, error)."""
    if meeting.minutes_status != "FINAL":
        return 0, ("Mark the minutes Final before emailing them.")
    recips = _recipients(meeting)
    if not recips:
        return 0, "No attendee has an email address."
    from .meetings import minutes_pdf_context
    from .views_commercial import pdf_bytes
    try:
        pdf = pdf_bytes("pdf/meeting_minutes.html",
                        minutes_pdf_context(meeting))
    except Exception as e:                       # pragma: no cover - env dep
        return 0, f"Couldn't render the minutes PDF: {e}"
    when = when_mvt(meeting.scheduled_at)
    organiser = meeting.organiser if meeting.organiser_id else None
    subject = f"Minutes — {meeting.title}"
    for _a, email, name in recips:
        body = (f"Hello {name},\n\nPlease find attached the minutes of "
                f"{meeting.title} held on {when}.\n\n— Sand Planet Pvt Ltd")
        msg = build_email(subject, body, [email], from_user=organiser)
        msg.attach(f"minutes-{meeting.id}.pdf", pdf, "application/pdf")
        msg.send(fail_silently=False)
    meeting.minutes_sent_at = timezone.now()
    meeting.save(update_fields=["minutes_sent_at", "updated_at"])
    audit("meeting", meeting.id, "MEETING_MINUTES_SENT", actor=actor,
          detail={"recipients": len(recips)})
    return len(recips), None


def record_rsvp(token, reply):
    """Capture a one-click RSVP from an invite email. Returns (attendee, error)."""
    choice = {"yes": MeetingAttendee.Rsvp.ACCEPTED,
              "no": MeetingAttendee.Rsvp.DECLINED,
              "maybe": MeetingAttendee.Rsvp.TENTATIVE}.get((reply or "").lower())
    if not choice:
        return None, "Unknown response."
    attendee = MeetingAttendee.objects.filter(rsvp_token=token).first()
    if not attendee:
        return None, "This response link is no longer valid."
    attendee.rsvp = choice
    attendee.responded_at = timezone.now()
    attendee.save(update_fields=["rsvp", "responded_at"])
    return attendee, None
