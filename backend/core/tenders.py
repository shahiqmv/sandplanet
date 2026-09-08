"""Tenders & offers — the work before there is a project.

A BOQ is priced by the QS outside the system and used to reach it only once
won, so the system held 23 priced bills and no record of a single submission.
Nothing issued the reference, so every submission invented its own — which is
where the drift in format and numbering came from (owner 2026-09-08).

The document underneath a tender does the heavy lifting: a gap-free reference
from the same counter as every other register, revisions, attachments and the
workflow trail. What this module adds is the rule that separates working from
sending: **a revision is internal until it is issued, and issuing one is a
submission**. Once issued it is immutable, and a further price is a further
revision — the first submission stays on the record either way.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .audit import audit
from .models import Document, DocumentRevision, Project, Site, Tender
from .numbering import next_ref

# QS prices them and the Director decides; Admin keeps the register. A
# signatory reads every module and writes none. A site PM sees the enquiries
# for their own site — they are the ones who walked the job (owner
# 2026-09-08).
MANAGE_ROLES = ("QS", "DIRECTOR", "ADMIN")
VIEW_ROLES = MANAGE_ROLES + ("SIGNATORY", "PM")
OPEN_STATUSES = ("DRAFT", "SUBMITTED")
DECIDED = {"AWARDED": Tender.Outcome.AWARDED,
           "LOST": Tender.Outcome.LOST,
           "WITHDRAWN": Tender.Outcome.WITHDRAWN}


def can_manage(user):
    return user.role in MANAGE_ROLES


def can_view(user):
    return user.role in VIEW_ROLES


def visible_to(user, qs=None):
    """A PM sees their own site's tenders; everyone else with access sees all.

    Scoping the PM matters: a tender carries a price we have not won yet, and
    a PM at another resort has no business reading it.
    """
    qs = qs if qs is not None else Tender.objects.all()
    qs = qs.select_related("document", "document__site", "awarded_project")
    if user.role != "PM":
        return qs
    from .models import SitePmHistory
    sites = SitePmHistory.objects.filter(
        pm_user=user, to_date__isnull=True).values_list("site_id", flat=True)
    return qs.filter(document__site_id__in=list(sites))


def _dec(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _payload(data, base=None):
    """What a revision records about the offer as priced at that moment."""
    out = dict(base or {})
    for k in ("note", "value", "basis", "validity_days", "payment_terms",
              "programme_weeks", "exclusions", "qualifications"):
        if k in data:
            out[k] = data[k]
    return out


@transaction.atomic
def create_tender(data, actor):
    """Open an enquiry. R0 exists from the start — pricing IS a revision."""
    site = Site.objects.filter(pk=data.get("site_id")).first()
    if site is None:
        return None, "Pick the site this enquiry is for."
    client = (data.get("client_name") or "").strip()
    title = (data.get("title") or "").strip()
    if not client:
        return None, "The client's name is required."
    if not title:
        return None, "Give the tender a title."
    doc = Document.objects.create(
        doc_type="TDR", ref=next_ref("TDR", site), site=site,
        doc_date=data.get("enquiry_date") or date.today(),
        status="DRAFT", created_by=actor)
    rev = DocumentRevision.objects.create(
        document=doc, rev_label="R0", created_by=actor,
        payload=_payload(data))
    doc.current_revision = rev
    doc.save(update_fields=["current_revision"])
    t = Tender.objects.create(
        document=doc, client_name=client[:160], title=title,
        client_contact=data.get("client_contact", ""),
        scope=data.get("scope", ""),
        enquiry_date=data.get("enquiry_date") or None,
        due_date=data.get("due_date") or None,
        submit_our_format=bool(data.get("submit_our_format", True)),
        currency=(data.get("currency") or "USD").upper()[:3])
    audit("tender", t.id, "TENDER_OPENED", actor=actor,
          detail={"ref": doc.ref, "site": site.code, "client": t.client_name})
    return t, None


def edit_tender(t, data, actor):
    """Correct the enquiry's own facts. Never the reference, never the site —
    the reference has been quoted to the client and the site is what the
    number was issued against."""
    if t.document.status not in OPEN_STATUSES:
        return "This tender is closed — its details cannot be changed."
    if "client_name" in data:
        t.client_name = (data.get("client_name") or "").strip()[:160]
    if "title" in data:
        t.title = (data.get("title") or "").strip()
    if "client_contact" in data:
        t.client_contact = data.get("client_contact") or ""
    if "scope" in data:
        t.scope = data.get("scope") or ""
    if "enquiry_date" in data:
        t.enquiry_date = data.get("enquiry_date") or None
    if "due_date" in data:
        t.due_date = data.get("due_date") or None
    if "submit_our_format" in data:
        t.submit_our_format = bool(data.get("submit_our_format"))
    if "currency" in data:
        t.currency = (data.get("currency") or "USD").upper()[:3]
    if not t.client_name.strip() or not t.title.strip():
        return "A tender needs a client and a title."
    t.save()
    audit("tender", t.id, "TENDER_EDITED", actor=actor,
          detail={"ref": t.document.ref})
    return None


@transaction.atomic
def add_revision(t, data, actor):
    """Start a further price. The current revision must already be issued —
    otherwise the QS is simply still working on it and should edit that one."""
    doc = t.document
    if doc.status not in OPEN_STATUSES:
        return None, "This tender is closed."
    cur = doc.current_revision
    if cur is not None and cur.issued_at is None:
        return None, (f"{cur.rev_label} has not been issued yet — price it "
                      "and issue that, rather than opening another.")
    try:
        n = int((cur.rev_label or "R0")[1:]) + 1 if cur else 0
    except (TypeError, ValueError):
        n = doc.revisions.count()
    doc.revisions.update(is_current=False)
    rev = DocumentRevision.objects.create(
        document=doc, rev_label=f"R{n}", created_by=actor,
        payload=_payload(data, base=(cur.payload if cur else None)))
    doc.current_revision = rev
    # A further price means we are working again, not that the last
    # submission is undone — it stays issued, on the record.
    doc.status = "DRAFT"
    doc.save(update_fields=["current_revision", "status"])
    audit("tender", t.id, "TENDER_REVISION_ADDED", actor=actor,
          detail={"ref": doc.ref, "rev": rev.rev_label})
    return rev, None


@transaction.atomic
def issue_revision(t, data, actor):
    """Send the current revision to the client. This is the submission.

    The revision is stamped issued and becomes immutable; the value goes on
    the header so a later revision cannot restate what the client was already
    sent.
    """
    doc = t.document
    if doc.status not in OPEN_STATUSES:
        return "This tender is closed."
    rev = doc.current_revision
    if rev is None:
        return "There is nothing to issue."
    if rev.issued_at is not None:
        return (f"{rev.rev_label} has already been issued. Open a new "
                "revision to send a further price.")
    value = _dec(data.get("value"))
    if value is None or value <= 0:
        return "Enter the value being offered."
    if not t.submit_our_format and not doc.attachments.exists():
        # The lines are captured either way; what differs is the document that
        # goes out. Here it is the client's own file, so issuing without it
        # would record a submission the system cannot produce.
        return ("This offer is submitted on the client's own bill — attach "
                "the file being sent before issuing it.")
    from django.utils import timezone
    rev.issued_at = timezone.now()
    rev.payload = {**(rev.payload or {}), "value": str(value)}
    rev.save(update_fields=["issued_at", "payload"])
    t.value_submitted = value
    t.submitted_at = rev.issued_at
    t.save(update_fields=["value_submitted", "submitted_at"])
    doc.status = "SUBMITTED"
    doc.save(update_fields=["status"])
    audit("tender", t.id, "TENDER_ISSUED", actor=actor,
          detail={"ref": doc.ref, "rev": rev.rev_label,
                  "currency": t.currency})
    return None


def boq_for(t):
    """The tender's BOQ, or None. Created on first save, as a project's is."""
    return getattr(t, "boq", None)


@transaction.atomic
def award_to_project(t, data, actor):
    """Turn a won offer into the job, and hand the BOQ over.

    The BOQ is REASSIGNED, not copied: a copy would leave two priced bills
    that can drift apart, and the whole point of pricing inside the system is
    that the awarded bill is the one that was offered (owner 2026-09-08).
    """
    code = (data.get("project_code") or "").strip()[:12]
    if not code:
        return None, "Give the new project a code (e.g. SOUT JT)."
    site = t.document.site
    if Project.objects.filter(site=site, code=code).exists():
        return None, f"{site.code} already has a project coded {code}."
    project = Project.objects.create(
        site=site, code=code,
        title=(data.get("project_title") or t.title).strip(),
        scope=t.scope,
        status=Project.Status.AWARDED,
        contract_value=t.value_awarded or t.value_submitted,
        loa_date=t.outcome_date,
        loa_ref=t.outcome_ref or "",
    )
    boq = boq_for(t)
    if boq is not None:
        boq.tender = None
        boq.project = project
        boq.save(update_fields=["tender", "project"])
    t.awarded_project = project
    t.save(update_fields=["awarded_project"])
    audit("tender", t.id, "TENDER_BECAME_PROJECT", actor=actor,
          detail={"ref": t.document.ref, "project": project.code,
                  "boq_moved": boq is not None})
    return project, None


@transaction.atomic
def record_outcome(t, outcome, data, actor):
    """How it ended. Awarded, lost or withdrawn — never left hanging."""
    doc = t.document
    if outcome not in DECIDED:
        return "The outcome must be awarded, lost or withdrawn."
    if doc.status not in OPEN_STATUSES:
        return "This tender already has an outcome."
    if outcome != "WITHDRAWN" and doc.status != "SUBMITTED":
        return ("Issue the offer before recording what the client decided "
                "about it.")
    t.outcome_date = data.get("outcome_date") or date.today()
    t.outcome_ref = (data.get("outcome_ref") or "")[:60]
    if outcome == "AWARDED":
        t.value_awarded = _dec(data.get("value_awarded")) or t.value_submitted
    else:
        t.lost_reason = data.get("lost_reason", "")
        t.lost_to = (data.get("lost_to") or "")[:160]
    t.save()
    doc.status = outcome
    doc.save(update_fields=["status"])
    audit("tender", t.id, f"TENDER_{outcome}", actor=actor,
          detail={"ref": doc.ref, "on": str(t.outcome_date),
                  "their_ref": t.outcome_ref})
    if outcome == "AWARDED":
        # A won offer becomes the job. Asking for the code here rather than
        # inventing one keeps the project register readable — the codes are a
        # human convention (SOUT JT, NORTH JT), not a serial.
        _p, msg = award_to_project(t, data, actor)
        if msg:
            return msg
    return None
