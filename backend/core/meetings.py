"""Meetings — client / site / BD meeting log with a calendar, minutes and
action-item follow-up (owner 2026-07-31).

The PD is the custodian (delegatable to a PD assistant later); custodians see
and manage everything, other roles create meetings in their domain and see the
ones they're part of. A recurring meeting forms a series — closing an
occurrence can spawn the next and roll its open action items forward.
"""
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone

from .audit import audit
from .models import (Meeting, MeetingActionItem, MeetingAttendee, Project,
                     Site, User)

# The company runs on Maldives time (fixed UTC+5, no DST). Instants are stored
# in UTC; every attendee-facing time (notices, reminders) is rendered in MVT so
# the server's UTC clock never leaks into what people read (owner 2026-08-08).
MALE_TZ = ZoneInfo("Indian/Maldives")


def when_mvt(dt):
    """Format a stored (UTC) datetime as Maldives local wall-clock."""
    return dt.astimezone(MALE_TZ).strftime("%d %b %Y, %H:%M") + " MVT"

# The meeting custodian(s) — the PD owns the module; Admin too. Extend this
# with the PD's assistant (an EA role or a per-user flag) once she is onboarded.
# PA = the Director's Personal Assistant, the delegated meeting custodian.
CUSTODIAN_ROLES = ("DIRECTOR", "ADMIN", "PA")
# Who may schedule a meeting at all (custodians + the domain roles: PM/QS for
# project reviews, Marketing for BD, site team for site meetings).
CREATE_ROLES = ("DIRECTOR", "ADMIN", "PM", "QS", "MARKETING", "SITE_ADMIN",
                "SITE_ENGINEER", "HO_PURCHASING", "PA")

_CADENCE_DAYS = {"WEEKLY": 7, "FORTNIGHTLY": 14}


def is_custodian(user):
    return user.role in CUSTODIAN_ROLES


# ---- visibility ----------------------------------------------------------

def visible_meetings(user):
    """Who sees what (owner 2026-07-31):
      * Custodian (PD/Director + Admin): every meeting.
      * Site Admin / Site Engineer / PM: meetings on their allocated site(s);
        PM also the meetings of projects they run.
      * Marketing: all prospective-client (BD) meetings.
      * Everyone: meetings they organise, created, or are invited to.
    Prospective-client meetings carry no site, so site roles don't see them —
    only the custodian, organiser, invitees and Marketing."""
    qs = Meeting.objects.select_related("project", "site", "organiser")
    if is_custodian(user):
        return qs
    site_ids = list(user.allocated_site_ids() or [])
    q = (Q(organiser=user) | Q(created_by=user) | Q(attendees__user=user)
         | Q(site_id__in=site_ids) | Q(project__pm=user))
    if user.role == "MARKETING":
        q |= Q(meeting_type="PROSPECT")
    return qs.filter(q).distinct()


def can_manage(user, meeting):
    return (is_custodian(user) or meeting.organiser_id == user.id
            or meeting.created_by_id == user.id)


# ---- create / update -----------------------------------------------------

def _next_dt(dt, cadence):
    if cadence in _CADENCE_DAYS:
        return dt + timedelta(days=_CADENCE_DAYS[cadence])
    if cadence == "MONTHLY":
        # same day next month, clamped to the month length
        y, m = dt.year + (dt.month // 12), (dt.month % 12) + 1
        import calendar
        d = min(dt.day, calendar.monthrange(y, m)[1])
        return dt.replace(year=y, month=m, day=d)
    return None


def _apply(meeting, data):
    for f in ("title", "agenda", "notes", "org_name", "org_contact",
              "location_note", "meeting_link"):
        if f in data:
            setattr(meeting, f, (data.get(f) or "").strip())
    if "meeting_type" in data and data["meeting_type"] in Meeting.Type.values:
        meeting.meeting_type = data["meeting_type"]
    if "location_kind" in data and data["location_kind"] in \
            Meeting.Location.values:
        meeting.location_kind = data["location_kind"]
    if "cadence" in data and data["cadence"] in Meeting.Cadence.values:
        meeting.cadence = data["cadence"]
    if "scheduled_at" in data and data["scheduled_at"]:
        val = data["scheduled_at"]
        if isinstance(val, str):
            from django.utils.dateparse import parse_datetime
            val = parse_datetime(val) or val
        if val and not isinstance(val, str) and timezone.is_naive(val):
            val = timezone.make_aware(val, MALE_TZ)   # a bare time = Maldives
        meeting.scheduled_at = val
    if "duration_minutes" in data:
        try:
            meeting.duration_minutes = int(data["duration_minutes"]) or 60
        except (TypeError, ValueError):
            pass
    if "project_id" in data:
        meeting.project = (Project.objects.filter(pk=data["project_id"]).first()
                           if data["project_id"] else None)
        if meeting.project and not meeting.site_id:
            meeting.site = meeting.project.site
    if "site_id" in data:
        meeting.site = (Site.objects.filter(pk=data["site_id"]).first()
                        if data["site_id"] else None)


def attendee_conflicts(scheduled_at, duration_minutes, user_ids,
                       exclude_id=None):
    """Internal attendees who already have a SCHEDULED meeting overlapping the
    proposed [start, end) window. Returns
    [{user_id, name, meetings: [{id, title, scheduled_at, duration_minutes}]}].
    Meeting volumes are small, so we refine the overlap in Python rather than
    build a per-backend duration expression."""
    user_ids = [int(u) for u in (user_ids or []) if u]
    if not scheduled_at or not user_ids:
        return []
    end = scheduled_at + timedelta(minutes=int(duration_minutes or 60))
    names = dict(User.objects.filter(id__in=user_ids)
                 .values_list("id", "full_name"))
    qs = (Meeting.objects
          .filter(status="SCHEDULED", attendees__user_id__in=user_ids)
          .exclude(pk=exclude_id or 0)
          .prefetch_related("attendees").distinct())
    by_user = {}
    for m in qs:
        m_end = m.scheduled_at + timedelta(minutes=m.duration_minutes or 60)
        if m.scheduled_at < end and m_end > scheduled_at:      # true overlap
            for a in m.attendees.all():
                if a.user_id in names:
                    by_user.setdefault(a.user_id, []).append(m)
    return [{"user_id": uid, "name": names.get(uid, ""),
             "meetings": [{"id": m.id, "title": m.title,
                           "scheduled_at": m.scheduled_at.isoformat(),
                           "duration_minutes": m.duration_minutes}
                          for m in sorted(mtgs, key=lambda x: x.scheduled_at)]}
            for uid, mtgs in by_user.items()]


def create_meeting(data, actor):
    if actor.role not in CREATE_ROLES:
        return None, "You can't schedule meetings."
    if not (data.get("title") or "").strip():
        return None, "Give the meeting a title."
    if data.get("meeting_type") not in Meeting.Type.values:
        return None, "Choose the meeting type."
    if not data.get("scheduled_at"):
        return None, "Set the date and time."
    organiser = User.objects.filter(pk=data.get("organiser_id")).first() \
        or actor
    meeting = Meeting(status=data.get("status") or "SCHEDULED",
                      organiser=organiser, created_by=actor)
    _apply(meeting, data)
    meeting.save()
    # Add attendees without the per-invite ping — a single "meeting scheduled"
    # notification below covers all participants at once.
    _set_attendees(meeting, data.get("attendees") or [], actor, notify=False)
    notify_meeting_created(meeting, actor)
    audit("meeting", meeting.id, "MEETING_CREATED", actor=actor,
          detail={"title": meeting.title, "type": meeting.meeting_type})
    return meeting, None


def notify_meeting_created(meeting, actor):
    """On scheduling, ping every participant — the internal attendees and the
    organiser — so anyone with the mobile app gets an in-app + web-push alert.
    Skips whoever created it (they know)."""
    from .notify import notify_user
    ids = set(meeting.attendees.filter(user__isnull=False)
              .values_list("user_id", flat=True))
    if meeting.organiser_id:
        ids.add(meeting.organiser_id)
    ids.discard(actor.id if actor else None)
    if not ids:
        return
    when = when_mvt(meeting.scheduled_at)
    type_label = dict(Meeting.Type.choices).get(meeting.meeting_type, "")
    body = f"{when}{f' · {type_label}' if type_label else ''}. " \
           f"Organiser: {meeting.organiser.full_name if meeting.organiser_id else '—'}"
    for u in User.objects.filter(id__in=ids, is_active=True):
        notify_user(u, f"Meeting scheduled — {meeting.title}", body=body,
                    category="info")


def reschedule_meeting(meeting, data, actor):
    """Move a meeting to a new date/time (and optional duration) and ping the
    participants. A postponed meeting becomes scheduled again."""
    if not can_manage(actor, meeting):
        return None, "Only the organiser or a custodian can reschedule this."
    if meeting.status in ("HELD", "CANCELLED"):
        return None, "A held or cancelled meeting can't be rescheduled."
    val = data.get("scheduled_at")
    if not val:
        return None, "Set the new date and time."
    if isinstance(val, str):
        from django.utils.dateparse import parse_datetime
        val = parse_datetime(val)
    if not val:
        return None, "Couldn't read the new date and time."
    if timezone.is_naive(val):
        val = timezone.make_aware(val, MALE_TZ)
    old = meeting.scheduled_at
    meeting.scheduled_at = val
    if data.get("duration_minutes"):
        try:
            meeting.duration_minutes = int(data["duration_minutes"])
        except (TypeError, ValueError):
            pass
    meeting.status = "SCHEDULED"
    meeting.reminded_at = None              # remind again for the new time
    meeting.ics_sequence += 1              # a resent invite supersedes the old
    meeting.save(update_fields=["scheduled_at", "duration_minutes", "status",
                                "reminded_at", "ics_sequence", "updated_at"])
    _notify_rescheduled(meeting, actor)
    audit("meeting", meeting.id, "MEETING_RESCHEDULED", actor=actor,
          detail={"from": old.isoformat() if old else "",
                  "to": val.isoformat()})
    return meeting, None


def send_due_reminders(now=None):
    """Sweep for scheduled meetings coming up within the reminder window that
    haven't been reminded yet, and ping their participants. Run periodically by
    the `meeting_reminders` management command (cron). Idempotent — each meeting
    reminds once (reminded_at), reset on reschedule. Returns the count sent."""
    from datetime import timedelta

    from .models import CompanyParameter
    now = now or timezone.now()
    try:
        hours = int(CompanyParameter.objects.get(
            key="meeting_reminder_hours").value)
    except (CompanyParameter.DoesNotExist, ValueError, TypeError):
        hours = 2                           # default lead time (owner-tunable)
    window = now + timedelta(hours=hours)
    due = Meeting.objects.filter(
        status="SCHEDULED", reminded_at__isnull=True,
        scheduled_at__gt=now, scheduled_at__lte=window)
    sent = 0
    for m in due:
        _remind(m)
        m.reminded_at = now
        m.save(update_fields=["reminded_at"])
        sent += 1
    return sent


def _remind(meeting):
    from .notify import notify_user
    ids = set(meeting.attendees.filter(user__isnull=False)
              .values_list("user_id", flat=True))
    if meeting.organiser_id:
        ids.add(meeting.organiser_id)
    if not ids:
        return
    when = when_mvt(meeting.scheduled_at)
    extra = meeting.meeting_link or meeting.location_note
    body = f"Coming up: {when}." + (f" {extra}" if extra else "")
    for u in User.objects.filter(id__in=ids, is_active=True):
        notify_user(u, f"Reminder — {meeting.title}", body=body,
                    category="info")


def _notify_rescheduled(meeting, actor):
    from .notify import notify_user
    ids = set(meeting.attendees.filter(user__isnull=False)
              .values_list("user_id", flat=True))
    if meeting.organiser_id:
        ids.add(meeting.organiser_id)
    ids.discard(actor.id if actor else None)
    if not ids:
        return
    when = when_mvt(meeting.scheduled_at)
    for u in User.objects.filter(id__in=ids, is_active=True):
        notify_user(u, f"Meeting rescheduled — {meeting.title}",
                    body=f"New time: {when}.", category="info")


def add_audio(meeting, upload, note, actor):
    """Attach an audio recording to a meeting."""
    if not can_manage(actor, meeting):
        return None, "Only the organiser or a custodian can add a recording."
    if not upload:
        return None, "Attach an audio file."
    from .models import MeetingAudio
    audio = MeetingAudio.objects.create(
        meeting=meeting,
        file_name=(getattr(upload, "name", "") or "recording")[:255],
        content_type=(getattr(upload, "content_type", "") or "")[:100],
        size_bytes=getattr(upload, "size", 0) or 0,
        note=(note or "").strip()[:200], uploaded_by=actor)
    audio.file = upload           # pk now set → unique upload path
    audio.save(update_fields=["file"])
    audit("meeting", meeting.id, "MEETING_AUDIO_ADDED", actor=actor,
          detail={"file": audio.file_name})
    return audio, None


def delete_audio(meeting, audio_id, actor):
    if not can_manage(actor, meeting):
        return "Only the organiser or a custodian can remove a recording."
    from .models import MeetingAudio
    a = MeetingAudio.objects.filter(pk=audio_id, meeting=meeting).first()
    if a is None:
        return "That recording isn't on this meeting."
    if a.file:
        a.file.delete(save=False)
    a.delete()
    audit("meeting", meeting.id, "MEETING_AUDIO_REMOVED", actor=actor)
    return None


def add_attachment(meeting, upload, actor):
    """Attach a pre-read document to a meeting (goes out with the invite email)."""
    if not can_manage(actor, meeting):
        return None, "Only the organiser or a custodian can add a file."
    if not upload:
        return None, "Attach a file."
    from .models import MeetingAttachment
    att = MeetingAttachment.objects.create(
        meeting=meeting,
        file_name=(getattr(upload, "name", "") or "file")[:255],
        content_type=(getattr(upload, "content_type", "") or "")[:100],
        size_bytes=getattr(upload, "size", 0) or 0, uploaded_by=actor)
    att.file = upload             # pk now set → unique upload path
    att.save(update_fields=["file"])
    audit("meeting", meeting.id, "MEETING_FILE_ADDED", actor=actor,
          detail={"file": att.file_name})
    return att, None


def delete_attachment(meeting, file_id, actor):
    if not can_manage(actor, meeting):
        return "Only the organiser or a custodian can remove a file."
    from .models import MeetingAttachment
    a = MeetingAttachment.objects.filter(pk=file_id, meeting=meeting).first()
    if a is None:
        return "That file isn't on this meeting."
    if a.file:
        a.file.delete(save=False)
    a.delete()
    audit("meeting", meeting.id, "MEETING_FILE_REMOVED", actor=actor)
    return None


def list_contacts(query=""):
    """The reusable external-guest contact book, optionally filtered by name /
    org / email."""
    from .models import MeetingContact
    qs = MeetingContact.objects.all()
    q = (query or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(org__icontains=q)
                       | Q(email__icontains=q))
    return list(qs[:50])


def upsert_contact(data, actor):
    """Save (or update by email) an external guest for reuse."""
    from .models import MeetingContact
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    if not name:
        return None, "Give the contact a name."
    existing = (MeetingContact.objects.filter(email__iexact=email).first()
                if email else None)
    c = existing or MeetingContact(created_by=actor)
    c.name = name
    c.email = email
    c.org = (data.get("org") or "").strip()
    c.role = (data.get("role") or "").strip()
    c.save()
    return c, None


def contact_dict(c):
    return {"id": c.id, "name": c.name, "email": c.email, "org": c.org,
            "role": c.role}


def delete_meeting(meeting, actor):
    """Permanently remove a meeting (and its attendees/action items, via
    cascade). Restricted to the organiser, its creator, or a custodian. Use
    this for a mistaken entry; to keep it on record instead, cancel it."""
    if not can_manage(actor, meeting):
        return "Only the organiser or a custodian can delete this meeting."
    audit("meeting", meeting.id, "MEETING_DELETED", actor=actor,
          detail={"title": meeting.title})
    meeting.delete()
    return None


def update_meeting(meeting, data, actor):
    if not can_manage(actor, meeting):
        return None, "Only the organiser or a custodian can edit this meeting."
    _apply(meeting, data)
    if "status" in data and data["status"] in Meeting.Status.values:
        meeting.status = data["status"]
    if "minutes" in data:
        meeting.minutes = data["minutes"]
        if meeting.minutes_status == "NONE" and meeting.minutes.strip():
            meeting.minutes_status = "DRAFT"
    if "minutes_status" in data and data["minutes_status"] in \
            Meeting.Minutes.values:
        meeting.minutes_status = data["minutes_status"]
    if "attendees" in data:
        _set_attendees(meeting, data["attendees"], actor)
    meeting.save()
    audit("meeting", meeting.id, "MEETING_UPDATED", actor=actor)
    return meeting, None


def _set_attendees(meeting, rows, actor=None, notify=True):
    """Replace the attendee list; newly-added internal people get an invite
    notification (notify-only — no RSVP, no external email). Pass notify=False
    at creation, where a single 'meeting scheduled' ping covers everyone.
    Preserves each surviving attendee's RSVP + token (keyed by user or email) so
    re-saving the list doesn't wipe replies already given."""
    prior = {}
    for a in meeting.attendees.all():
        key = f"u{a.user_id}" if a.user_id else f"e{(a.email or '').lower()}"
        prior[key] = (a.rsvp, a.rsvp_token, a.responded_at)
    already = set(meeting.attendees.filter(user__isnull=False)
                  .values_list("user_id", flat=True))
    meeting.attendees.all().delete()
    fresh = []
    for r in rows:
        uid = r.get("user_id")
        email = (r.get("email") or "").strip()
        key = f"u{uid}" if uid else f"e{email.lower()}"
        rsvp, token, responded = prior.get(key, ("NONE", "", None))
        MeetingAttendee.objects.create(
            meeting=meeting,
            user=(User.objects.filter(pk=uid).first() if uid else None),
            name=(r.get("name") or "").strip(), email=email,
            org=(r.get("org") or "").strip(),
            role=(r.get("role") or "").strip(),
            is_external=bool(r.get("is_external") or (not uid)),
            present=bool(r.get("present", True)),
            rsvp=rsvp, rsvp_token=token, responded_at=responded)
        if uid and uid not in already:
            fresh.append(uid)
    if notify:
        _invite(meeting, fresh, actor)


def _invite(meeting, user_ids, actor):
    """Ping newly-invited internal people (skip the organiser doing the adding)."""
    if not user_ids:
        return
    from .notify import notify_user
    actor_id = actor.id if actor else None
    when = when_mvt(meeting.scheduled_at)
    for u in User.objects.filter(id__in=user_ids).exclude(id=actor_id):
        notify_user(u, f"Meeting invite — {meeting.title}",
                    body=f"{when}. Organiser: "
                         f"{meeting.organiser.full_name if meeting.organiser_id else '—'}",
                    category="info")


# ---- action items (follow-up) -------------------------------------------

def set_action_items(meeting, rows, actor):
    """Replace the meeting's action items from the reviewed rows."""
    if not can_manage(actor, meeting):
        return "Only the organiser or a custodian can edit follow-ups."
    keep = []
    for i, r in enumerate(rows, 1):
        desc = (r.get("description") or "").strip()
        if not desc:
            continue
        item = (MeetingActionItem.objects.filter(pk=r.get("id"),
                                                 meeting=meeting).first()
                if r.get("id") else MeetingActionItem(meeting=meeting))
        item.description = desc
        item.owner = (User.objects.filter(pk=r.get("owner_id")).first()
                      if r.get("owner_id") else None)
        item.owner_name = (r.get("owner_name") or "").strip()
        item.due_date = r.get("due_date") or None
        if r.get("status") in MeetingActionItem.Status.values:
            was_done = item.status == "DONE"
            item.status = r["status"]
            if item.status == "DONE" and not was_done:
                item.completed_at = timezone.now()
        item.sort_order = i * 10
        item.save()
        keep.append(item.id)
    meeting.action_items.exclude(id__in=keep).delete()
    audit("meeting", meeting.id, "MEETING_ACTIONS_SET", actor=actor,
          detail={"count": len(keep)})
    return None


def my_action_items(user):
    """Open follow-ups owned by this user, soonest-due first."""
    items = (MeetingActionItem.objects
             .filter(owner=user, status__in=("OPEN", "IN_PROGRESS"))
             .select_related("meeting").order_by("due_date", "id"))
    return [action_item_dict(a) for a in items]


# ---- recurrence ----------------------------------------------------------

def close_meeting(meeting, actor, spawn_next=True):
    """Mark the meeting held; for a recurring meeting, spawn the next occurrence
    and roll its still-open action items forward. Returns (meeting, next|None,
    error)."""
    if not can_manage(actor, meeting):
        return None, None, "Only the organiser or a custodian can close this."
    meeting.status = "HELD"
    meeting.save(update_fields=["status", "updated_at"])
    nxt = None
    if spawn_next and meeting.cadence != "ONE_OFF":
        nxt = create_next_occurrence(meeting, actor)
    audit("meeting", meeting.id, "MEETING_HELD", actor=actor)
    return meeting, nxt, None


def create_next_occurrence(meeting, actor):
    """Clone a recurring meeting to its next date, carrying open action items
    forward as fresh open items on the new occurrence."""
    when = _next_dt(meeting.scheduled_at, meeting.cadence)
    if when is None:
        return None
    parent = meeting.series_parent or meeting
    nxt = Meeting.objects.create(
        title=meeting.title, meeting_type=meeting.meeting_type,
        project=meeting.project, site=meeting.site, org_name=meeting.org_name,
        org_contact=meeting.org_contact, scheduled_at=when,
        duration_minutes=meeting.duration_minutes,
        location_kind=meeting.location_kind, location_note=meeting.location_note,
        status="SCHEDULED", cadence=meeting.cadence, series_parent=parent,
        agenda=meeting.agenda, organiser=meeting.organiser, created_by=actor)
    for a in meeting.attendees.all():
        MeetingAttendee.objects.create(
            meeting=nxt, user=a.user, name=a.name, org=a.org, role=a.role,
            is_external=a.is_external, present=True)
    for a in meeting.action_items.filter(status__in=("OPEN", "IN_PROGRESS")):
        MeetingActionItem.objects.create(
            meeting=nxt, description=a.description, owner=a.owner,
            owner_name=a.owner_name, due_date=a.due_date, status="OPEN",
            carried_from=a, sort_order=a.sort_order)
    audit("meeting", nxt.id, "MEETING_NEXT_SPAWNED", actor=actor,
          detail={"from": meeting.id})
    return nxt


# ---- serialisation -------------------------------------------------------

def attendee_dict(a):
    return {"id": a.id, "user_id": a.user_id,
            "name": (a.user.full_name if a.user_id else a.name),
            "email": (a.user.email if a.user_id else a.email),
            "org": a.org, "role": a.role, "is_external": a.is_external,
            "present": a.present, "rsvp": a.rsvp,
            "responded_at": a.responded_at}


def audio_dict(a):
    return {
        "id": a.id, "file_name": a.file_name, "note": a.note,
        "size_bytes": a.size_bytes, "content_type": a.content_type,
        "uploaded_by": a.uploaded_by.full_name if a.uploaded_by_id else "",
        "uploaded_at": a.uploaded_at,
    }


def attachment_dict(a):
    return {
        "id": a.id, "file_name": a.file_name, "size_bytes": a.size_bytes,
        "content_type": a.content_type,
        "url": a.file.url if a.file else "",
        "uploaded_by": a.uploaded_by.full_name if a.uploaded_by_id else "",
    }


def action_item_dict(a):
    return {
        "id": a.id, "meeting_id": a.meeting_id,
        "meeting_title": a.meeting.title if a.meeting_id else "",
        "description": a.description,
        "owner_id": a.owner_id,
        "owner": (a.owner.full_name if a.owner_id else a.owner_name),
        "due_date": a.due_date, "status": a.status,
        "overdue": bool(a.due_date and a.is_open and a.due_date < date.today()),
        "carried": a.carried_from_id is not None,
    }


_AI_LABEL = {"OPEN": "Open", "IN_PROGRESS": "In progress", "DONE": "Done",
             "CANCELLED": "Cancelled"}


def minutes_pdf_context(meeting):
    """Context for the branded meeting-minutes PDF."""
    from .pdf import company_info, logo_src
    type_label = dict(Meeting.Type.choices).get(meeting.meeting_type,
                                                meeting.meeting_type)
    loc_label = dict(Meeting.Location.choices).get(meeting.location_kind,
                                                   meeting.location_kind)
    who = (f"{meeting.project.code} — {meeting.project.title}"
           if meeting.project_id else meeting.org_name
           or (meeting.site.name if meeting.site_id else ""))
    return {
        "logo_src": logo_src(), "co": company_info(), "m": meeting,
        "type_label": type_label, "loc_label": loc_label, "who": who,
        "attendees": [attendee_dict(a) for a in meeting.attendees.all()],
        "actions": [{**action_item_dict(a),
                     "status_label": _AI_LABEL.get(a.status, a.status)}
                    for a in meeting.action_items.all()],
    }


def meeting_dict(meeting, detail=False):
    d = {
        "id": meeting.id, "title": meeting.title,
        "meeting_type": meeting.meeting_type,
        "project_id": meeting.project_id,
        "project_code": meeting.project.code if meeting.project_id else "",
        "site_id": meeting.site_id,
        "site_code": meeting.site.code if meeting.site_id else "",
        "org_name": meeting.org_name, "org_contact": meeting.org_contact,
        "scheduled_at": meeting.scheduled_at,
        "duration_minutes": meeting.duration_minutes,
        "location_kind": meeting.location_kind,
        "location_note": meeting.location_note,
        "meeting_link": meeting.meeting_link,
        "status": meeting.status, "cadence": meeting.cadence,
        "series_parent_id": meeting.series_parent_id,
        "minutes_status": meeting.minutes_status,
        "organiser": meeting.organiser.full_name if meeting.organiser_id else "",
        "open_actions": meeting.action_items.filter(
            status__in=("OPEN", "IN_PROGRESS")).count(),
        "invite_sent_at": meeting.invite_sent_at,
        "minutes_sent_at": meeting.minutes_sent_at,
    }
    if detail:
        attendees = list(meeting.attendees.select_related("user").all())
        reachable = sum(1 for a in attendees
                        if ((a.user.email if a.user_id else a.email) or "").strip())
        d.update({
            "agenda": meeting.agenda, "minutes": meeting.minutes,
            "notes": meeting.notes,
            "attendees": [attendee_dict(a) for a in attendees],
            "action_items": [action_item_dict(a)
                             for a in meeting.action_items.all()],
            "recordings": [audio_dict(a) for a in meeting.recordings.all()],
            "files": [attachment_dict(a) for a in meeting.files.all()],
            "email_recipients": reachable,
            "email_configured": _email_configured(),
        })
    return d


def _email_configured():
    from django.conf import settings
    return bool(getattr(settings, "EMAIL_HOST", ""))
