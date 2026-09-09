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
from .models import (Document, DocumentRevision, Project, Site, Tender,
                     TenderQuery, TenderQueryItem, TenderSiteVisit, User)
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
    if not t.submit_our_format and not doc.attachments.filter(
            kind="TENDER_BILL").exists():
        # The lines are captured either way; what differs is the document that
        # goes out. Here it is the client's own file, so issuing without it
        # would record a submission the system cannot produce.
        return ("This offer is submitted on the client's own bill — upload "
                "that file under Documents before issuing it.")
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


# ---- the submission pack ----------------------------------------------

def _sections(boq):
    """The bill grouped by its own section headings, for the summary page.

    A client reads a summary before a bill; without one the covering letter
    hands them 300 lines and a total (owner 2026-09-08).
    """
    if boq is None:
        return [], Decimal("0")
    rows, total = [], Decimal("0")
    current = None
    for it in boq.items.all().order_by("sort_order", "id"):
        if it.is_heading:
            name = (it.section or it.description or "").strip()
            current = {"name": name or "—", "amount": Decimal("0"),
                       "lines": 0}
            rows.append(current)
            continue
        amount = it.amount or Decimal("0")
        total += amount
        if current is None:
            current = {"name": "—", "amount": Decimal("0"), "lines": 0}
            rows.append(current)
        current["amount"] += amount
        current["lines"] += 1
    # A heading nobody priced under is noise on a summary page.
    return [r for r in rows if r["lines"]], total


def submission_context(t):
    """Everything the covering letter and summary print."""
    from .commercial import amount_in_words
    from .pdf import _font_dir, company_info, mark_src

    doc = t.document
    rev = doc.current_revision
    boq = boq_for(t)
    sections, total = _sections(boq)
    offered = t.value_submitted if t.value_submitted is not None else total

    def fdate(d):
        return d.strftime("%d %b %Y") if d else ""

    return {
        "mark_src": mark_src(), "font_dir": _font_dir(),
        "co": company_info(), "ref": doc.ref,
        "issue_date": fdate((rev.issued_at.date() if rev and rev.issued_at
                             else doc.doc_date)),
        "value_words": amount_in_words(offered, t.currency),
        "due_date": fdate(t.due_date),
        "enquiry_date": fdate(t.enquiry_date),
        "tender": t, "doc": doc, "rev": rev, "site": doc.site,
        "boq": boq, "sections": sections,
        # The header value is what was actually offered; the bill's own total
        # is shown beside it so a divergence is visible rather than hidden.
        "bill_total": total,
        "offered": t.value_submitted,
        "diverges": (t.value_submitted is not None
                     and abs((t.value_submitted or Decimal("0")) - total)
                     >= Decimal("0.01")),
        "issued_on": rev.issued_at if rev else None,
        "our_bill": t.submit_our_format,
    }


# ---- what the price rests on ------------------------------------------

def request_visit(t, data, actor):
    """Ask the client for a look at the job.

    Requested and held are separate dates on purpose: a visit asked for and
    not yet given is a live reason pricing has not started, and reads that way
    on the register (owner 2026-09-09).
    """
    v = TenderSiteVisit.objects.create(
        tender=t, requested_on=data.get("requested_on") or date.today(),
        attendees=data.get("attendees", ""), notes=data.get("notes", ""),
        created_by=actor)
    audit("tender", t.id, "TENDER_VISIT_REQUESTED", actor=actor,
          detail={"ref": t.document.ref, "on": str(v.requested_on)})
    return v, None


def record_visit(t, visit_id, data, actor):
    """What was seen. The notes and the photos are as much of the price as
    the drawings are."""
    v = t.visits.filter(pk=visit_id).first()
    if v is None:
        return None, "That visit is not on this tender."
    v.visited_on = data.get("visited_on") or date.today()
    if "attendees" in data:
        v.attendees = data.get("attendees") or ""
    if "notes" in data:
        v.notes = data.get("notes") or ""
    v.save(update_fields=["visited_on", "attendees", "notes"])
    audit("tender", t.id, "TENDER_VISIT_HELD", actor=actor,
          detail={"ref": t.document.ref, "on": str(v.visited_on)})
    return v, None


# ---- tender queries (TQ) ----------------------------------------------
#
# The sheet of questions put to the client during the tender period. NOT an
# RFI — that name is taken twice over in this app, by the contract-stage
# request for information and by the inspection request. A TQ carries several
# numbered questions, goes out under its own reference in our format, and the
# answers come back written against each question (owner 2026-09-09).

@transaction.atomic
def open_query(t, data, actor):
    """Start a new query sheet. Questions are added to it before it goes."""
    if t.document.status not in OPEN_STATUSES:
        return None, "This tender is closed."
    n = (t.queries.order_by("-number").values_list("number", flat=True)
         .first() or 0) + 1
    q = TenderQuery.objects.create(
        tender=t, number=n, subject=(data.get("subject") or "")[:200],
        raised_on=data.get("raised_on") or date.today(), created_by=actor)
    audit("tender", t.id, "TENDER_QUERY_OPENED", actor=actor,
          detail={"ref": q.ref})
    return q, None


@transaction.atomic
def add_question(t, query_id, data, actor):
    """Put another question on a sheet that has not gone out yet."""
    q = t.queries.filter(pk=query_id).first()
    if q is None:
        return None, "That query is not on this tender."
    if q.is_issued:
        return None, (f"{q.ref} has already gone to the client. Open a new "
                      "query for anything further.")
    text = (data.get("question") or "").strip()
    if not text:
        return None, "What is the question?"
    n = (q.items.order_by("-number").values_list("number", flat=True)
         .first() or 0) + 1
    item = TenderQueryItem.objects.create(
        query=q, number=n, question=text,
        reference=(data.get("reference") or "")[:160])
    return item, None


def remove_question(t, query_id, item_id, actor):
    q = t.queries.filter(pk=query_id).first()
    if q is None:
        return "That query is not on this tender."
    if q.is_issued:
        return f"{q.ref} has already gone to the client."
    item = q.items.filter(pk=item_id).first()
    if item is None:
        return "That question is not on this query."
    item.delete()
    return None


def issue_query(t, query_id, actor):
    """Send the sheet. After this it is what the client holds: questions are
    not reworded, and anything further is a new query."""
    q = t.queries.filter(pk=query_id).first()
    if q is None:
        return None, "That query is not on this tender."
    if q.is_issued:
        return None, f"{q.ref} has already been issued."
    if not q.items.exists():
        return None, "Add at least one question before issuing it."
    from django.utils import timezone
    q.issued_at = timezone.now()
    q.save(update_fields=["issued_at"])
    audit("tender", t.id, "TENDER_QUERY_ISSUED", actor=actor,
          detail={"ref": q.ref, "questions": q.items.count()})
    return q, None


def answer_question(t, query_id, item_id, data, actor):
    """Record the client's answer to ONE question.

    Per question, not per sheet: a client commonly answers three of five and
    leaves the rest, and a sheet marked simply "answered" would hide that.
    """
    q = t.queries.filter(pk=query_id).first()
    if q is None:
        return None, "That query is not on this tender."
    item = q.items.filter(pk=item_id).first()
    if item is None:
        return None, "That question is not on this query."
    answer = (data.get("answer") or "").strip()
    if not answer:
        return None, "Enter the client's answer."
    item.answer = answer
    item.answered_on = data.get("answered_on") or date.today()
    item.save(update_fields=["answer", "answered_on"])
    if "client_ref" in data:
        q.client_ref = (data.get("client_ref") or "")[:60]
    q.responded_on = item.answered_on
    q.save(update_fields=["client_ref", "responded_on"])
    audit("tender", t.id, "TENDER_QUERY_ANSWERED", actor=actor,
          detail={"ref": q.ref, "question": item.number})
    return item, None


def assign(t, user_id, actor):
    """Whose job this is. Read off the register far more often than edited."""
    if not user_id:
        t.assigned_to = None
    else:
        u = User.objects.filter(pk=user_id, is_active=True).first()
        if u is None:
            return "That person is not on the system."
        t.assigned_to = u
    t.save(update_fields=["assigned_to"])
    audit("tender", t.id, "TENDER_ASSIGNED", actor=actor,
          detail={"ref": t.document.ref,
                  "to": t.assigned_to.full_name if t.assigned_to else None})
    return None


def query_context(q):
    """What the TQ sheet prints."""
    from .pdf import _font_dir, company_info, mark_src

    t = q.tender
    def fdate(d):
        return d.strftime("%d %b %Y") if d else ""
    return {
        "mark_src": mark_src(), "font_dir": _font_dir(),
        "co": company_info(), "ref": q.ref,
        "issue_date": fdate(q.issued_at.date() if q.issued_at else q.raised_on),
        "q": q, "tender": t, "site": t.document.site,
        "items": list(q.items.all()),
        "tender_ref": t.document.ref,
    }
