"""Meetings — client / site / BD meeting log with a calendar, minutes and
action-item follow-up (owner 2026-07-31).

The PD is the custodian (delegatable to a PD assistant later); custodians see
and manage everything, other roles create meetings in their domain and see the
ones they're part of. A recurring meeting forms a series — closing an
occurrence can spawn the next and roll its open action items forward.
"""
from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone

from .audit import audit
from .models import (Meeting, MeetingActionItem, MeetingAttendee, Project,
                     Site, User)

# The meeting custodian(s) — the PD owns the module; Admin too. Extend this
# with the PD's assistant (an EA role or a per-user flag) once she is onboarded.
CUSTODIAN_ROLES = ("DIRECTOR", "ADMIN")
# Who may schedule a meeting at all (custodians + the domain roles: PM/QS for
# project reviews, Marketing for BD, site team for site meetings).
CREATE_ROLES = ("DIRECTOR", "ADMIN", "PM", "QS", "MARKETING", "SITE_ADMIN",
                "SITE_ENGINEER", "HO_PURCHASING")

_CADENCE_DAYS = {"WEEKLY": 7, "FORTNIGHTLY": 14}


def is_custodian(user):
    return user.role in CUSTODIAN_ROLES


# ---- visibility ----------------------------------------------------------

def visible_meetings(user):
    """Custodians see every meeting; everyone else sees the meetings they
    organise, created or attend, plus site meetings for their allocated
    sites."""
    qs = Meeting.objects.select_related("project", "site", "organiser")
    if is_custodian(user):
        return qs
    site_ids = list(user.allocated_site_ids() or [])
    return qs.filter(
        Q(organiser=user) | Q(created_by=user)
        | Q(attendees__user=user) | Q(site_id__in=site_ids)
    ).distinct()


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
              "location_note"):
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
            val = timezone.make_aware(val)
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
    _set_attendees(meeting, data.get("attendees") or [])
    audit("meeting", meeting.id, "MEETING_CREATED", actor=actor,
          detail={"title": meeting.title, "type": meeting.meeting_type})
    return meeting, None


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
        _set_attendees(meeting, data["attendees"])
    meeting.save()
    audit("meeting", meeting.id, "MEETING_UPDATED", actor=actor)
    return meeting, None


def _set_attendees(meeting, rows):
    meeting.attendees.all().delete()
    for r in rows:
        uid = r.get("user_id")
        MeetingAttendee.objects.create(
            meeting=meeting,
            user=(User.objects.filter(pk=uid).first() if uid else None),
            name=(r.get("name") or "").strip(),
            org=(r.get("org") or "").strip(),
            role=(r.get("role") or "").strip(),
            is_external=bool(r.get("is_external") or (not uid)),
            present=bool(r.get("present", True)))


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
            "org": a.org, "role": a.role, "is_external": a.is_external,
            "present": a.present}


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
        "status": meeting.status, "cadence": meeting.cadence,
        "series_parent_id": meeting.series_parent_id,
        "minutes_status": meeting.minutes_status,
        "organiser": meeting.organiser.full_name if meeting.organiser_id else "",
        "open_actions": meeting.action_items.filter(
            status__in=("OPEN", "IN_PROGRESS")).count(),
    }
    if detail:
        d.update({
            "agenda": meeting.agenda, "minutes": meeting.minutes,
            "notes": meeting.notes,
            "attendees": [attendee_dict(a) for a in meeting.attendees.all()],
            "action_items": [action_item_dict(a)
                             for a in meeting.action_items.all()],
        })
    return d
