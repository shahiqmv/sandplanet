"""Safety management — incidents, and the corrective actions that follow.

Before this, the app's whole safety functionality was one checkbox and one
free-text box on the daily report, and the checkbox failed OPEN: ticking
"accident today" notified nobody, escalated to nobody, and sat in an
unvalidated JSON blob, so a malformed report read as "no accident". You could
not answer "how many incidents last quarter?" without reading every daily
report by hand (conformance audit 2026-08-28).

Two rules carry most of the weight here:
  * an incident that hurt someone cannot be closed without an investigation,
  * an incident cannot be closed while a corrective action it raised is open.

Both are enforced server-side. A safety system whose closure rules live only
in the interface is a safety system that closes itself.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from .audit import audit
from .models import (CorrectiveAction, Document, DocumentRevision,
                     IncidentPerson, SafetyIncident, Site, User)
from .notify import notify_user
from .numbering import next_ref

# Who hears about an incident the moment it is reported, on top of the site's
# PMs. Severity decides how far up it goes: everything reaches the PM, the
# serious kinds reach the Director.
ESCALATE_KINDS = {"MEDICAL", "LOST_TIME", "FATALITY", "DANGEROUS"}
ESCALATE_SEVERITIES = {"HIGH", "CRITICAL"}

REPORTER_ROLES = {"SITE_ADMIN", "SITE_ENGINEER", "PM", "DIRECTOR", "ADMIN",
                  "HO_HR", "QS", "PA"}
INVESTIGATOR_ROLES = {"PM", "DIRECTOR", "ADMIN", "HO_HR"}


def _people(incident):
    return list(incident.people.select_related("employee"))


def open_actions(incident):
    return incident.document.corrective_actions.filter(
        status__in=["OPEN", "IN_PROGRESS", "DONE"])


@transaction.atomic
def create_incident(*, site, data, user, project=None):
    """Report an incident. Reporting is deliberately the easy part: the record
    is created at REPORTED with whatever is known, and the investigation
    fields are filled in later."""
    kind = data.get("kind")
    if kind not in dict(SafetyIncident.Kind.choices):
        return None, "Choose what kind of incident this was."
    occurred_at = data.get("occurred_at")
    if isinstance(occurred_at, str):
        occurred_at = parse_datetime(occurred_at)
    if not occurred_at:
        return None, "When did it happen?"
    if timezone.is_naive(occurred_at):
        occurred_at = timezone.make_aware(occurred_at)
    if occurred_at > timezone.now():
        return None, "An incident cannot be reported in the future."
    if not (data.get("description") or "").strip():
        return None, "Describe what happened."

    ref = next_ref("INC", site)
    doc = Document.objects.create(
        doc_type="INC", ref=ref, site=site, project=project,
        doc_date=timezone.localdate(), status="REPORTED", created_by=user)
    revision = DocumentRevision.objects.create(
        document=doc, rev_label="R0", payload={}, created_by=user)
    doc.current_revision = revision
    doc.save(update_fields=["current_revision"])

    incident = SafetyIncident.objects.create(
        document=doc, kind=kind,
        severity=data.get("severity") or "LOW",
        occurred_at=occurred_at,
        location=(data.get("location") or "").strip(),
        description=data["description"].strip(),
        immediate_action=(data.get("immediate_action") or "").strip(),
        work_stopped=bool(data.get("work_stopped")),
        is_reportable=bool(data.get("is_reportable")),
        reported_by=user)
    for row in data.get("people") or []:
        add_person(incident, row)

    audit("document", doc.id, "INCIDENT_REPORTED", actor=user,
          to_state="REPORTED",
          detail={"ref": ref, "kind": kind,
                  "severity": incident.severity,
                  "occurred_at": str(occurred_at)})
    _notify_reported(incident, user)
    return incident, None


def add_person(incident, row):
    employee_id = row.get("employee_id") or None
    return IncidentPerson.objects.create(
        incident=incident, employee_id=employee_id,
        name=(row.get("name") or "").strip(),
        employer=(row.get("employer") or "").strip(),
        involvement=row.get("involvement") or "INVOLVED",
        injury=(row.get("injury") or "").strip(),
        body_part=(row.get("body_part") or "")[:60],
        treatment=(row.get("treatment") or "").strip(),
        days_lost=int(row.get("days_lost") or 0),
        returned_to_work_on=row.get("returned_to_work_on") or None)


def _notify_reported(incident, actor):
    """Tell the people who must know, now. The old checkbox told nobody."""
    doc = incident.document
    seen, targets = set(), []
    for pm in (doc.site.current_pms() if doc.site_id else []):
        if pm.is_active:
            targets.append(pm)
    if (incident.kind in ESCALATE_KINDS
            or incident.severity in ESCALATE_SEVERITIES):
        targets += list(User.objects.filter(
            role__in=["DIRECTOR", "ADMIN"], is_active=True))
    label = incident.get_kind_display()
    title = f"{label} reported — {doc.site.code}"
    body = incident.description[:160]
    for u in targets:
        if u.id in seen or u.id == actor.id:
            continue
        seen.add(u.id)
        notify_user(u, title, body, doc=doc, category="approval")


@transaction.atomic
def start_investigation(incident, user):
    doc = incident.document
    if doc.status != "REPORTED":
        return "This incident is not awaiting investigation."
    incident.investigated_by = user
    incident.investigation_started_at = timezone.now()
    incident.save(update_fields=["investigated_by",
                                 "investigation_started_at"])
    doc.status = "INVESTIGATING"
    doc.save(update_fields=["status"])
    audit("document", doc.id, "INCIDENT_INVESTIGATION_STARTED", actor=user,
          from_state="REPORTED", to_state="INVESTIGATING")
    return None


@transaction.atomic
def close_incident(incident, user):
    """The two guards that make this a safety system rather than a form."""
    doc = incident.document
    if doc.status == "CLOSED":
        return "Already closed."
    if incident.kind in SafetyIncident.MUST_INVESTIGATE \
            and not (incident.root_cause or "").strip():
        return ("This kind of incident cannot be closed without an "
                "investigation — record the root cause first.")
    still_open = open_actions(incident).count()
    if still_open:
        return (f"{still_open} corrective action(s) raised by this incident "
                f"are still open. Close them before closing the incident.")
    incident.closed_at = timezone.now()
    incident.closed_by = user
    incident.save(update_fields=["closed_at", "closed_by"])
    was = doc.status
    doc.status = "CLOSED"
    doc.save(update_fields=["status"])
    audit("document", doc.id, "INCIDENT_CLOSED", actor=user,
          from_state=was, to_state="CLOSED",
          detail={"root_cause": incident.root_cause[:200]})
    return None


# ---- corrective actions -------------------------------------------------

@transaction.atomic
def raise_action(*, source_document, data, user):
    """Raise a corrective action against any document — an incident today, a
    non-conformance or an inspection finding later."""
    owner_id = data.get("owner_id")
    if not owner_id:
        return None, "Who owns this action?"
    due_date = data.get("due_date")
    if isinstance(due_date, str):
        due_date = parse_date(due_date)
    if not due_date:
        return None, "When is it due?"
    if not (data.get("description") or "").strip():
        return None, "Say what has to change."
    owner = User.objects.filter(pk=owner_id, is_active=True).first()
    if owner is None:
        return None, "Unknown owner."

    action = CorrectiveAction.objects.create(
        source_document=source_document, site=source_document.site,
        project=source_document.project,
        description=data["description"].strip(),
        is_preventive=bool(data.get("is_preventive")),
        owner=owner, due_date=due_date,
        priority=data.get("priority") or "MEDIUM", raised_by=user)
    # An incident with actions against it is not "investigated and done".
    doc = source_document
    if doc.doc_type == "INC" and doc.status == "INVESTIGATING":
        doc.status = "ACTIONS_OPEN"
        doc.save(update_fields=["status"])
    audit("corrective_action", action.id, "ACTION_RAISED", actor=user,
          to_state="OPEN",
          detail={"source": doc.ref, "owner": owner.username,
                  "due": str(action.due_date)})
    notify_user(owner, f"Corrective action — {doc.ref}",
                action.description[:160], doc=doc, category="approval")
    return action, None


@transaction.atomic
def complete_action(action, user, note=""):
    if action.status in ("VERIFIED", "CANCELLED"):
        return "This action is already closed."
    action.status = "DONE"
    action.completed_at = timezone.now()
    action.completed_by = user
    action.completion_note = (note or "").strip()
    action.save(update_fields=["status", "completed_at", "completed_by",
                               "completion_note"])
    audit("corrective_action", action.id, "ACTION_COMPLETED", actor=user,
          to_state="DONE", detail={"note": action.completion_note[:200]})
    notify_user(action.raised_by, f"Action done — {action.source_document.ref}",
                f"{action.owner.full_name} says it is done. Verify it.",
                doc=action.source_document, category="approval")
    return None


@transaction.atomic
def verify_action(action, user):
    """Someone other than the person who did it confirms it actually
    happened — an action verified by its own owner is an action nobody
    checked."""
    if action.status != "DONE":
        return "Only a completed action can be verified."
    if action.completed_by_id == user.id:
        return ("Someone other than the person who did the work has to "
                "verify it.")
    action.status = "VERIFIED"
    action.verified_at = timezone.now()
    action.verified_by = user
    action.save(update_fields=["status", "verified_at", "verified_by"])
    audit("corrective_action", action.id, "ACTION_VERIFIED", actor=user,
          from_state="DONE", to_state="VERIFIED")
    return None


def overdue_actions(site_ids=None):
    today = timezone.localdate()
    qs = CorrectiveAction.objects.filter(
        status__in=["OPEN", "IN_PROGRESS", "DONE"], due_date__lt=today)
    if site_ids is not None:
        qs = qs.filter(site_id__in=site_ids)
    return qs.select_related("owner", "site", "source_document")


def statistics(site_ids=None, date_from=None, date_to=None):
    """The numbers a client's HSE audit asks for, which previously could only
    be got by reading every daily report by hand."""
    qs = SafetyIncident.objects.select_related("document")
    if site_ids is not None:
        qs = qs.filter(document__site_id__in=site_ids)
    if date_from:
        qs = qs.filter(occurred_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(occurred_at__date__lte=date_to)
    rows = list(qs)
    by_kind = {}
    for r in rows:
        by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
    lost_days = sum(p.days_lost for r in rows for p in r.people.all())
    return {
        "total": len(rows),
        "by_kind": by_kind,
        "near_misses": by_kind.get("NEAR_MISS", 0),
        "injuries": sum(1 for r in rows if r.is_injury),
        "lost_time": by_kind.get("LOST_TIME", 0),
        "days_lost": lost_days,
        "open": sum(1 for r in rows if r.document.status != "CLOSED"),
        "reportable": sum(1 for r in rows if r.is_reportable),
    }


# ---- people records: toolbox talks, inductions, training, PPE -----------
# The records the HSE officer on a bigger site already keeps. These are
# registers rather than workflows — the officer runs the process, the app
# holds the evidence (owner 2026-08-29).

RECORDER_ROLES = {"SITE_ADMIN", "SITE_ENGINEER", "PM", "DIRECTOR", "ADMIN",
                  "HO_HR", "PA"}


def workers_present(site, day):
    """Everyone marked present at a site on a day. A toolbox talk is given to
    the men who are there, and they were all ticked into the attendance
    register that morning — asking for the same list twice is how a hundred
    checkboxes become nobody's job (owner 2026-08-29)."""
    from .models import Attendance
    rows = (Attendance.objects
            .filter(site=site, day=day,
                    remark__in=["PRESENT", "HALF_DAY"])
            .select_related("employee"))
    return [r.employee for r in rows]


@transaction.atomic
def create_toolbox_talk(*, site, data, user, project=None):
    from .models import ToolboxAttendee, ToolboxTalk

    topic = (data.get("topic") or "").strip()
    if not topic:
        return None, "What was the talk about?"
    delivered_at = data.get("delivered_at")
    if isinstance(delivered_at, str):
        delivered_at = parse_datetime(delivered_at)
    if not delivered_at:
        return None, "When was it given?"
    if timezone.is_naive(delivered_at):
        delivered_at = timezone.make_aware(delivered_at)

    ref = next_ref("TBT", site)
    doc = Document.objects.create(
        doc_type="TBT", ref=ref, site=site, project=project,
        doc_date=timezone.localdate(delivered_at),
        status="RECORDED", created_by=user)
    revision = DocumentRevision.objects.create(
        document=doc, rev_label="R0", payload={}, created_by=user)
    doc.current_revision = revision
    doc.save(update_fields=["current_revision"])

    talk = ToolboxTalk.objects.create(
        document=doc, topic=topic, delivered_by=user,
        presenter_name=(data.get("presenter_name") or "").strip(),
        delivered_at=delivered_at,
        duration_min=data.get("duration_min") or None,
        location=(data.get("location") or "").strip(),
        key_points=(data.get("key_points") or "").strip())

    seen = set()
    for row in data.get("attendees") or []:
        emp_id = row.get("employee_id") or None
        if emp_id and emp_id in seen:
            continue
        if emp_id:
            seen.add(emp_id)
        ToolboxAttendee.objects.create(
            talk=talk, employee_id=emp_id,
            name=(row.get("name") or "").strip(),
            employer=(row.get("employer") or "").strip())

    audit("document", doc.id, "TOOLBOX_TALK_RECORDED", actor=user,
          to_state="RECORDED",
          detail={"ref": ref, "topic": topic[:80],
                  "attendees": talk.attendees.count()})
    return talk, None


@transaction.atomic
def record_induction(*, employee, site, data, user):
    from .models import SafetyInduction

    inducted_on = data.get("inducted_on")
    if isinstance(inducted_on, str):
        inducted_on = parse_date(inducted_on)
    if not inducted_on:
        return None, "When were they inducted?"
    induction = SafetyInduction.objects.create(
        employee=employee, site=site, inducted_on=inducted_on,
        inducted_by=user, topics=(data.get("topics") or "").strip(),
        valid_until=parse_date(data["valid_until"])
        if isinstance(data.get("valid_until"), str) and data["valid_until"]
        else data.get("valid_until") or None,
        notes=(data.get("notes") or "").strip())
    audit("employee", employee.id, "INDUCTION_RECORDED", actor=user,
          detail={"site": site.code, "on": str(inducted_on)})
    return induction, None


@transaction.atomic
def record_training(*, employee, data, user):
    from .models import TrainingRecord

    title = (data.get("title") or "").strip()
    if not title:
        return None, "What training was it?"
    record = TrainingRecord.objects.create(
        employee=employee, title=title,
        category=data.get("category") or "GENERAL",
        issuer=(data.get("issuer") or "").strip(),
        reference=(data.get("reference") or "")[:60],
        issued_on=_as_date(data.get("issued_on")),
        expires_on=_as_date(data.get("expires_on")),
        notes=(data.get("notes") or "").strip(),
        recorded_by=user)
    audit("employee", employee.id, "TRAINING_RECORDED", actor=user,
          detail={"title": title[:80], "expires": str(record.expires_on or "")})
    return record, None


def _as_date(value):
    if isinstance(value, str) and value:
        return parse_date(value)
    return value or None


@transaction.atomic
def issue_ppe(*, employee, site, data, user):
    from .models import PpeIssue

    item = (data.get("item") or "").strip()
    if not item:
        return None, "What was issued?"
    issue = PpeIssue.objects.create(
        employee=employee, site=site, item=item[:80],
        qty=int(data.get("qty") or 1),
        issued_on=_as_date(data.get("issued_on")) or timezone.localdate(),
        issued_by=user, replacement=bool(data.get("replacement")),
        notes=(data.get("notes") or "").strip())
    audit("employee", employee.id, "PPE_ISSUED", actor=user,
          detail={"item": item[:60], "qty": issue.qty})
    return issue, None


# ---- training expiry sweep ---------------------------------------------
# An expired plant-operator ticket is a man on an excavator he is no longer
# certified to drive — an operational risk today, not only a certification
# one. Escalating stages, watermarked so a reminder does not repeat daily.

# Ascending, because the sweep takes the FIRST threshold the record falls
# inside — ordered the other way every record matches "60 days" and the
# reminder never escalates as the date closes in.
TRAINING_STAGES = [(0, "OVERDUE"), (7, "D7"), (30, "D30"), (60, "D60")]


def sweep_training_expiry():
    """Fire renewal reminders for training that is running out. Returns how
    many fired. Run daily from cron."""
    from .models import TrainingRecord

    today = timezone.localdate()
    fired = 0
    qs = (TrainingRecord.objects
          .filter(expires_on__isnull=False,
                  expires_on__lte=today + timedelta(days=60))
          .select_related("employee"))
    for record in qs:
        days = record.days_to_expiry(today)
        stage = None
        for threshold, name in TRAINING_STAGES:
            if days <= threshold:
                stage = name
                break
        if stage is None or record.last_alert_stage == stage:
            continue
        site_id = record.employee.current_site_id()
        targets = []
        if site_id:
            site = Site.objects.filter(pk=site_id).first()
            if site is not None:
                targets += [p for p in site.current_pms() if p.is_active]
        targets += list(User.objects.filter(role="HO_HR", is_active=True))
        when = ("has expired" if days < 0 else
                "expires today" if days == 0 else f"expires in {days} days")
        for u in {t.id: t for t in targets}.values():
            notify_user(
                u, f"Training {when} — {record.employee.full_name}",
                f"{record.get_category_display()}: {record.title}",
                category="alert")
        record.last_alert_stage = stage
        record.save(update_fields=["last_alert_stage"])
        fired += 1
    return fired
