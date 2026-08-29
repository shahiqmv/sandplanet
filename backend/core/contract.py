"""Contract & time — correspondence, delay events, entitlement.

There was no notice document of any kind, no correspondence or RFI register,
no delay-event log and no time-bar clock (conformance audit 2026-08-28). When
a client claims delay we have daily reports and photographs but no structured
evidence chain, and under a FIDIC-derived form an entitlement not noticed
inside its window is an entitlement lost. That is money, not paperwork.

Two principles run through this module:

  * Time bars are CONFIGURATION, not code. Notice periods differ by contract
    form; a module that hard-codes one is wrong on every other. The days come
    off the project, and a project with none set gets no invented deadline.
  * A late notice is RECORDED, never blocked. The fact that it went out late
    is exactly what a reviewer needs to see, and software that refuses to
    record it just moves the problem off the system.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from .audit import audit
from .models import (Correspondence, DelayEvent, Document, DocumentRevision,
                     ExtensionOfTime, ProgrammeActivity)
from .notify import notify_user
from .numbering import next_ref

RAISER_ROLES = {"SITE_ADMIN", "SITE_ENGINEER", "PM", "DIRECTOR", "ADMIN",
                "QS", "PA"}
# Deciding that a delay is the employer's risk, and submitting an application
# on the back of it, is a commercial position — not a site data-entry task.
COMMERCIAL_ROLES = {"PM", "DIRECTOR", "ADMIN", "QS"}


def _as_date(value):
    if isinstance(value, str) and value:
        return parse_date(value)
    return value or None


def _new_document(doc_type, site, user, doc_date, status, project=None):
    ref = next_ref(doc_type, site)
    doc = Document.objects.create(
        doc_type=doc_type, ref=ref, site=site, project=project,
        doc_date=doc_date, status=status, created_by=user)
    revision = DocumentRevision.objects.create(
        document=doc, rev_label="R0", payload={}, created_by=user)
    doc.current_revision = revision
    doc.save(update_fields=["current_revision"])
    return doc


# ---- correspondence, RFIs, instructions, notices ------------------------

def default_response_due(project, kind, dated_on):
    """The reply clock, from the project's contract terms. No configured
    period means no deadline — the register says "none set" rather than
    inventing one."""
    if project is None:
        return None
    days = (project.rfi_response_days if kind == "RFI"
            else project.notice_period_days)
    return dated_on + timedelta(days=days) if days else None


def time_bar_for(project, aware_on):
    """When a notice had to be served by, counted from the date we became
    aware. Blank project setting = no bar recorded."""
    if project is None or not aware_on or not project.notice_period_days:
        return None
    return aware_on + timedelta(days=project.notice_period_days)


@transaction.atomic
def log_correspondence(*, site, data, user, project=None):
    kind = data.get("kind")
    if kind not in dict(Correspondence.Kind.choices):
        return None, "What kind of correspondence is this?"
    direction = data.get("direction")
    if direction not in dict(Correspondence.Direction.choices):
        return None, "Was it sent or received?"
    if not (data.get("subject") or "").strip():
        return None, "What is it about?"
    dated_on = _as_date(data.get("dated_on")) or timezone.localdate()

    doc = _new_document(kind, site, user, dated_on, "OPEN", project)
    response_required = data.get("response_required")
    response_required = True if response_required is None \
        else bool(response_required)
    aware_on = _as_date(data.get("aware_on"))
    record = Correspondence.objects.create(
        document=doc, kind=kind, direction=direction,
        party=data.get("party") or "CLIENT",
        party_name=(data.get("party_name") or "").strip(),
        their_ref=(data.get("their_ref") or "")[:80],
        subject=data["subject"].strip(),
        body=(data.get("body") or "").strip(),
        dated_on=dated_on,
        response_required=response_required,
        response_due=(_as_date(data.get("response_due"))
                      or (default_response_due(project, kind, dated_on)
                          if response_required else None)),
        clause=(data.get("clause") or "")[:80],
        aware_on=aware_on,
        time_bar_on=(_as_date(data.get("time_bar_on"))
                     or time_bar_for(project, aware_on)),
        raised_by=user)
    if not response_required:
        doc.status = "CLOSED"
        doc.save(update_fields=["status"])
    audit("document", doc.id, "CORRESPONDENCE_LOGGED", actor=user,
          to_state=doc.status,
          detail={"ref": doc.ref, "kind": kind, "direction": direction,
                  "due": str(record.response_due or ""),
                  "served_late": record.served_late()})
    return record, None


@transaction.atomic
def record_response(record, data, user):
    if record.document.status == "CLOSED":
        return "This is already closed."
    record.responded_on = _as_date(data.get("responded_on")) \
        or timezone.localdate()
    record.response_summary = (data.get("response_summary") or "").strip()
    record.save(update_fields=["responded_on", "response_summary"])
    late = record.response_due and record.responded_on > record.response_due
    doc = record.document
    doc.status = "ANSWERED"
    doc.save(update_fields=["status"])
    audit("document", doc.id, "CORRESPONDENCE_ANSWERED", actor=user,
          to_state="ANSWERED",
          detail={"on": str(record.responded_on), "late": bool(late),
                  "days_late": ((record.responded_on - record.response_due).days
                                if late else 0)})
    return None


def outstanding(site_ids=None, as_of=None):
    """Everything still awaiting a reply, worst first. An unanswered RFI is
    the commonest root of a delay claim, so it leads the register."""
    as_of = as_of or timezone.localdate()
    qs = Correspondence.objects.filter(
        response_required=True, responded_on__isnull=True).exclude(
        document__status="CLOSED").select_related("document",
                                                  "document__site")
    if site_ids is not None:
        qs = qs.filter(document__site_id__in=site_ids)
    rows = sorted(qs, key=lambda c: (c.response_due or as_of))
    return rows


# ---- delay events -------------------------------------------------------

@transaction.atomic
def log_delay(*, project, data, user):
    title = (data.get("title") or "").strip()
    if not title:
        return None, "What happened?"
    cause = data.get("cause")
    if cause not in dict(DelayEvent.Cause.choices):
        return None, "What caused the delay?"
    started_on = _as_date(data.get("started_on"))
    if not started_on:
        return None, "When did it start?"
    ended_on = _as_date(data.get("ended_on"))
    if ended_on and ended_on < started_on:
        return None, "It cannot end before it started."

    doc = _new_document("DLY", project.site, user, started_on, "OPEN",
                        project)
    event = DelayEvent.objects.create(
        document=doc, project=project, title=title,
        description=(data.get("description") or "").strip(),
        cause=cause,
        responsibility=data.get("responsibility") or "UNDECIDED",
        started_on=started_on, ended_on=ended_on,
        days_lost=data.get("days_lost"),
        mitigation=(data.get("mitigation") or "").strip(),
        raised_by=user)
    _link_delay(event, data, project)
    audit("document", doc.id, "DELAY_LOGGED", actor=user, to_state="OPEN",
          detail={"ref": doc.ref, "cause": cause,
                  "responsibility": event.responsibility,
                  "from": str(started_on)})
    return event, None


def _link_delay(event, data, project):
    """Attach the evidence that already exists rather than restating it."""
    activity_ids = data.get("activity_ids") or []
    if activity_ids:
        event.activities.set(ProgrammeActivity.objects.filter(
            pk__in=activity_ids, project=project))
    evidence_refs = data.get("evidence_refs") or []
    if evidence_refs:
        event.evidence.set(Document.objects.filter(
            ref__in=evidence_refs, site=project.site))
    if data.get("notice_id"):
        event.notice = Correspondence.objects.filter(
            pk=data["notice_id"], document__site=project.site).first()
        event.save(update_fields=["notice"])


def delay_summary(project):
    """Days of delay by who carries them — the shape of an entitlement
    argument before anyone writes it down."""
    out = {"EMPLOYER": 0, "CONTRACTOR": 0, "NEUTRAL": 0, "UNDECIDED": 0}
    open_events = 0
    without_notice = 0
    for event in project.delay_events.select_related("notice"):
        days = event.days_lost if event.days_lost is not None \
            else event.duration_days()
        out[event.responsibility] = out.get(event.responsibility, 0) + days
        if event.ended_on is None:
            open_events += 1
        # An employer-risk delay with no notice served is the exposure this
        # module exists to surface.
        if event.responsibility == "EMPLOYER" and event.notice_id is None:
            without_notice += 1
    return {"days_by_responsibility": out, "open_events": open_events,
            "employer_risk_without_notice": without_notice,
            "events": project.delay_events.count()}


# ---- extension of time --------------------------------------------------

@transaction.atomic
def create_eot(*, project, data, user):
    event_ids = data.get("delay_event_ids") or []
    if not event_ids:
        return None, ("An application is built from delay events. Log the "
                      "events first — a claim assembled from memory is the "
                      "one that fails.")
    events = list(DelayEvent.objects.filter(pk__in=event_ids,
                                            project=project))
    if not events:
        return None, "Those delay events do not belong to this project."

    doc = _new_document("EOT", project.site, user, timezone.localdate(),
                        "DRAFT", project)
    claimed = data.get("days_claimed")
    if claimed in (None, ""):
        claimed = sum(e.days_lost if e.days_lost is not None
                      else e.duration_days() for e in events)
    eot = ExtensionOfTime.objects.create(
        document=doc, project=project, days_claimed=int(claimed),
        grounds=(data.get("grounds") or "").strip(), raised_by=user)
    eot.delay_events.set(events)
    audit("document", doc.id, "EOT_DRAFTED", actor=user, to_state="DRAFT",
          detail={"ref": doc.ref, "events": len(events),
                  "days_claimed": eot.days_claimed})
    return eot, None


@transaction.atomic
def submit_eot(eot, user, submitted_on=None):
    doc = eot.document
    if doc.status != "DRAFT":
        return "This application has already been submitted."
    eot.submitted_on = _as_date(submitted_on) or timezone.localdate()
    eot.save(update_fields=["submitted_on"])
    doc.status = "SUBMITTED"
    doc.save(update_fields=["status"])
    audit("document", doc.id, "EOT_SUBMITTED", actor=user,
          from_state="DRAFT", to_state="SUBMITTED",
          detail={"on": str(eot.submitted_on),
                  "days_claimed": eot.days_claimed})
    for pm in eot.project.site.current_pms():
        if pm.is_active and pm.id != user.id:
            notify_user(pm, f"EOT submitted — {doc.ref}",
                        f"{eot.days_claimed} days claimed on "
                        f"{eot.project.code}.", doc=doc, category="approval")
    return None


@transaction.atomic
def decide_eot(eot, data, user):
    """Record the employer's decision — and, where days are awarded, re-set
    the programme baseline so the project is measured against the plan it now
    actually has."""
    from . import programme

    doc = eot.document
    if doc.status != "SUBMITTED":
        return None, "Only a submitted application can be decided."
    awarded = data.get("days_awarded")
    if awarded in (None, ""):
        return None, "How many days were awarded? Enter 0 for a rejection."
    awarded = int(awarded)
    if awarded < 0:
        return None, "Days awarded cannot be negative."
    if awarded > eot.days_claimed:
        return None, "More days awarded than were claimed — check the figure."

    eot.days_awarded = awarded
    eot.decided_on = _as_date(data.get("decided_on")) or timezone.localdate()
    eot.revised_completion = _as_date(data.get("revised_completion"))
    eot.decision_note = (data.get("decision_note") or "").strip()
    eot.save(update_fields=["days_awarded", "decided_on",
                            "revised_completion", "decision_note"])
    doc.status = ("REJECTED" if awarded == 0
                  else "AWARDED" if awarded == eot.days_claimed
                  else "PARTIALLY_AWARDED")
    doc.save(update_fields=["status"])

    baseline = None
    if awarded > 0 and data.get("rebaseline", True):
        baseline, err = programme.capture_baseline(
            eot.project, user, label=f"EOT {doc.ref}",
            reason=f"{awarded} days awarded on {doc.ref}")
        if baseline is not None:
            eot.baseline = baseline
            eot.save(update_fields=["baseline"])
    audit("document", doc.id, "EOT_DECIDED", actor=user,
          from_state="SUBMITTED", to_state=doc.status,
          detail={"days_awarded": awarded, "claimed": eot.days_claimed,
                  "rebaselined": baseline.rev_no if baseline else None})
    return eot, None


def entitlement_view(project):
    """What the project can currently argue: delay by responsibility, notices
    served and missing, and where the applications stand."""
    summary = delay_summary(project)
    applications = list(project.eot_applications.select_related("document"))
    return {
        **summary,
        "applications": len(applications),
        "days_claimed": sum(a.days_claimed for a in applications),
        "days_awarded": sum(a.days_awarded or 0 for a in applications),
        "awaiting_decision": sum(1 for a in applications
                                 if a.document.status == "SUBMITTED"),
    }
