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
                     TenderEvent, TenderQuery, TenderQueryItem, User)
from .numbering import next_ref

# QS prices them and the Director decides; Admin keeps the register. A
# signatory reads every module and writes none. A site PM sees the enquiries
# for their own site — they are the ones who walked the job (owner
# 2026-09-08).
MANAGE_ROLES = ("QS", "DIRECTOR", "ADMIN")
VIEW_ROLES = MANAGE_ROLES + ("SIGNATORY", "PM")
# Everything before the client has answered. Pricing, the approval chain, and
# the spell after it has gone out.
OPEN_STATUSES = ("DRAFT", "PD_REVIEW", "SIGNATORY_REVIEW", "CLEARED",
                 "ISSUED")
# Still being worked on — a bill can be changed and a query raised here.
WORKING_STATUSES = ("DRAFT", "PD_REVIEW", "SIGNATORY_REVIEW", "CLEARED")
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
    # The site knows who the client is — SFR and SSR are both Bunny Holdings
    # (BVI) Limited — so typing it again was work the system could do. Still
    # editable: a few sites have no client on file, and the party who invites
    # a tender is not always the one on the site record (owner 2026-09-09).
    client = (data.get("client_name") or site.client_name or "").strip()
    title = (data.get("title") or "").strip()
    if not client:
        return None, ("This site has no client on file — enter who the "
                      "enquiry came from.")
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
        # The usual terms, so a tender starts where the last one ended. Each
        # is editable before it goes out (owner 2026-09-09).
        payment_terms=data.get("payment_terms")
        or DEFAULT_TERMS["payment_terms"],
        client_provides=data.get("client_provides")
        or DEFAULT_TERMS["client_provides"],
        exclusions=data.get("exclusions") or DEFAULT_TERMS["exclusions"],
        variations=data.get("variations") or DEFAULT_TERMS["variations"],
        warranty_terms=data.get("warranty_terms")
        or DEFAULT_TERMS["warranty_terms"],
        client_contact=(data.get("client_contact")
                        or site.client_contact or ""),
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
    # What the commercial proposal prints.
    for f in ("doc_ref", "payment_terms", "client_provides", "exclusions",
              "variations", "warranty_terms", "prepared_by", "reviewed_by",
              "approved_by"):
        if f in data:
            setattr(t, f, data.get(f) or "")
    for f in ("validity_days", "duration_days"):
        if f in data:
            try:
                setattr(t, f, int(data[f]) if data[f] not in (None, "")
                        else None)
            except (TypeError, ValueError):
                return f"{f.replace('_', ' ')} must be a number of days."
    if "validity_days" in data and t.validity_days is None:
        t.validity_days = 30
    for f in ("discount_amount", "gst_percent"):
        if f in data:
            v = _dec(data[f])
            if v is None and data[f] not in (None, ""):
                return f"{f.replace('_', ' ')} must be a number."
            setattr(t, f, v if v is not None
                    else (None if f == "discount_amount" else Decimal("0")))
    if (t.discount_amount or Decimal("0")) < 0:
        return "A discount is entered as a positive figure — it comes off."
    if "discount_label" in data:
        t.discount_label = (data.get("discount_label") or "").strip()[:80]
    if not t.client_name.strip() or not t.title.strip():
        return "A tender needs a client and a title."
    if "provisional_items" in data:
        err = set_provisional_items(t, data.get("provisional_items"))
        if err:
            return err
    t.save()
    audit("tender", t.id, "TENDER_EDITED", actor=actor,
          detail={"ref": t.document.ref})
    return None


def set_provisional_items(t, rows):
    """Replace the tender's provisional sums with the rows given.

    Replaced wholesale rather than patched line by line: the screen edits them
    as one list, and a half-applied list is a wrong total on a client-facing
    offer. A row with no label and no amount is a blank the editor left
    behind, not a deletion to argue about.
    """
    from .models import TenderProvisionalItem
    clean = []
    for i, r in enumerate(rows or []):
        label = (r.get("label") or "").strip()
        amount = _dec(r.get("amount"))
        if not label and amount in (None, Decimal("0")):
            continue
        if not label:
            return "Give each provisional sum a description."
        if amount is None:
            return f"'{label}' needs an amount."
        if amount < 0:
            return f"'{label}' cannot be negative."
        clean.append(TenderProvisionalItem(
            tender=t, sort_order=i, label=label[:160], amount=amount))
    with transaction.atomic():
        t.provisional_items.all().delete()
        TenderProvisionalItem.objects.bulk_create(clean)
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
    # submission is undone — it stays issued, on the record. And it walks the
    # approval chain again: the gate is on the PRICE, so a new one is a new
    # decision (owner 2026-09-09).
    doc.status = "DRAFT"
    doc.save(update_fields=["current_revision", "status"])
    audit("tender", t.id, "TENDER_REVISION_ADDED", actor=actor,
          detail={"ref": doc.ref, "rev": rev.rev_label})
    return rev, None


# Who may take each step of the chain. The QS prices and sends; the Director
# reviews the price; a signatory clears it to leave the building (owner
# 2026-09-09).
APPROVAL_CHAIN = {
    "PD_REVIEW": ("DIRECTOR", "SIGNATORY_REVIEW", "TENDER_PD_APPROVED"),
    "SIGNATORY_REVIEW": ("SIGNATORY", "CLEARED", "TENDER_CLEARED"),
}


def _tell(doc, actor):
    """Alert whoever the offer now waits on. Never raises — a notification
    failure must not undo a status change."""
    from .notify import notify_document
    notify_document(doc, actor)


def send_for_approval(t, data, actor):
    """Put the priced offer in front of the Director.

    The value is fixed here rather than at issue: the Director and the
    signatory are approving a NUMBER, and one that could still change
    afterwards would make their approval meaningless.
    """
    doc = t.document
    if doc.status != "DRAFT":
        return "Only a tender being priced can be sent for approval."
    rev = doc.current_revision
    if rev is None:
        return "There is nothing to approve."
    value = _dec(data.get("value"))
    if value is None or value <= 0:
        return "Enter the value being offered before sending it up."
    if not t.submit_our_format and not doc.attachments.filter(
            kind="TENDER_BILL").exists():
        return ("This offer is submitted on the client's own bill — upload "
                "that file under Documents first.")
    rev.payload = {**(rev.payload or {}), "value": str(value)}
    rev.save(update_fields=["payload"])
    t.value_submitted = value
    t.save(update_fields=["value_submitted"])
    doc.status = "PD_REVIEW"
    doc.save(update_fields=["status"])
    _tell(doc, actor)
    audit("tender", t.id, "TENDER_SENT_FOR_APPROVAL", actor=actor,
          detail={"ref": doc.ref, "rev": rev.rev_label,
                  "currency": t.currency})
    return None


def approve(t, actor):
    """The Director's review, then the signatory's clearance."""
    doc = t.document
    step = APPROVAL_CHAIN.get(doc.status)
    if step is None:
        return "There is nothing awaiting approval on this tender."
    role, nxt, event = step
    if actor.role not in (role, "ADMIN"):
        who = "the Director" if role == "DIRECTOR" else "a signatory"
        return f"This step is {who}'s."
    doc.status = nxt
    doc.save(update_fields=["status"])
    _tell(doc, actor)
    audit("tender", t.id, event, actor=actor,
          detail={"ref": doc.ref,
                  "value": str(t.value_submitted or ""),
                  "currency": t.currency})
    return None


def return_for_rework(t, data, actor):
    """Send it back to the QS. Nothing has gone to the client, so there is
    nothing to unwind — only a price to think again about."""
    doc = t.document
    if doc.status not in ("PD_REVIEW", "SIGNATORY_REVIEW", "CLEARED"):
        return "This tender is not with an approver."
    expected = {"PD_REVIEW": "DIRECTOR", "SIGNATORY_REVIEW": "SIGNATORY",
                "CLEARED": "SIGNATORY"}[doc.status]
    if actor.role not in (expected, "ADMIN", "QS"):
        return "Only the approver holding it, or the QS, can pull it back."
    reason = (data.get("comment") or "").strip()
    if not reason:
        return "Say why it is going back."
    doc.status = "DRAFT"
    doc.save(update_fields=["status"])
    audit("tender", t.id, "TENDER_RETURNED", actor=actor,
          detail={"ref": doc.ref, "reason": reason[:300]})
    return None


@transaction.atomic
def issue_revision(t, data, actor):
    """Send the current revision to the client. This is the submission.

    The revision is stamped issued and becomes immutable; the value goes on
    the header so a later revision cannot restate what the client was already
    sent.
    """
    doc = t.document
    # The gate: a price does not leave the building until the Director has
    # reviewed it and a signatory has cleared it (owner 2026-09-09).
    if doc.status != "CLEARED":
        if doc.status in ("PD_REVIEW", "SIGNATORY_REVIEW"):
            with_who = ("the Director" if doc.status == "PD_REVIEW"
                        else "a signatory")
            return f"This offer is still with {with_who}."
        if doc.status == "DRAFT":
            return ("Send the offer for approval first — the Director and a "
                    "signatory clear the price before it goes out.")
        if doc.status == "ISSUED":
            return ("This offer has already gone to the client. Open a new "
                    "revision to send a further price.")
        return "This tender is closed."
    rev = doc.current_revision
    if rev is None:
        return "There is nothing to issue."
    if rev.issued_at is not None:
        return (f"{rev.rev_label} has already been issued. Open a new "
                "revision to send a further price.")
    # The value was fixed when it went up for approval; that is the figure
    # they approved and it is not re-entered here.
    if not t.value_submitted:
        return "This offer has no approved value on it."
    from django.utils import timezone
    rev.issued_at = timezone.now()
    rev.payload = {**(rev.payload or {}), "value": str(t.value_submitted)}
    rev.save(update_fields=["issued_at", "payload"])
    t.submitted_at = rev.issued_at
    t.save(update_fields=["submitted_at"])
    doc.status = "ISSUED"
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
    if outcome != "WITHDRAWN" and doc.status != "ISSUED":
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

# The offer's default terms. Lifted from the owner's own SJR Operation Office
# workbook so a new tender starts where the last one ended rather than blank
# (owner 2026-09-09). Each is editable per tender.
DEFAULT_TERMS = {
    "payment_terms": ("40% advance with Letter of Award; 50% on progress "
                      "monthly payment; 5% on completion and handover; 5% "
                      "after the defects liability period"),
    "client_provides": ("Transport of materials and workers to site, "
                        "accommodation, meals and drinking water for workers, "
                        "power and lighting for the works, storage space"),
    "exclusions": ("Any works, permits or approvals not expressly described "
                   "in this bill of quantities"),
    "variations": ("Any change to scope, quantity or specification will be "
                   "priced and agreed in writing before execution"),
    "warranty_terms": ("12 months defects liability period from the date of "
                       "handover, covering workmanship and installed "
                       "materials"),
}


def _bills(boq):
    """The priced bills, in order, for the summary page.

    A client reads a summary before a bill. The owner's workbook lists them as
    Bill No. 1..n with a description and a total, and a captured bill names
    itself on its own lines — every priced row carries its bill in `section`,
    so the section is what groups them. Headings inside a bill are trades, not
    bills. Only where the rows carry no section at all does the last heading
    stand in for the bill name, which is how a hand-typed BOQ of one heading
    per bill reads (owner 2026-09-09).
    """
    if boq is None:
        return [], Decimal("0")
    rows, total = [], Decimal("0")
    current, heading = None, ""
    for it in boq.items.all().order_by("sort_order", "id"):
        if it.is_heading:
            heading = (it.section or it.description or "").strip()
            continue
        amount = it.amount or Decimal("0")
        total += amount
        name = (it.section or "").strip() or heading or "Works"
        if current is None or current["name"] != name:
            current = {"no": len(rows) + 1, "name": name,
                       "amount": Decimal("0"), "lines": 0}
            rows.append(current)
        current["amount"] += amount
        current["lines"] += 1
    return rows, total


def money_stack(t, bill_total):
    """Subtotal, discount, provisional sums, GST, grand total.

    Built on the OFFERED figure, because that is what the client was told; the
    bill's own total is shown beside it when they differ rather than quietly
    reconciled.

    The discount comes off the priced work, before the provisional sums are
    added: a provisional sum is an allowance to be spent, not our price, and
    discounting it would be discounting the client's own money. GST is charged
    on what is left, because GST is charged on what the client actually pays
    (owner 2026-09-10).
    """
    sub = (t.value_submitted if t.value_submitted is not None
           else bill_total) or Decimal("0")
    discount = t.discount_amount or Decimal("0")
    after_discount = sub - discount
    items = [{"label": i.label, "amount": i.amount}
             for i in t.provisional_items.all()]
    prov = sum((i["amount"] for i in items), Decimal("0"))
    net = after_discount + prov
    pct = t.gst_percent or Decimal("0")
    gst = (net * pct / Decimal("100")).quantize(Decimal("0.01"))
    return {"subtotal": sub,
            "discount": discount,
            "discount_label": t.discount_label or "Discount",
            "after_discount": after_discount,
            "provisional_items": items,
            "provisional": prov, "net": net,
            "gst_percent": pct, "gst": gst, "grand_total": net + gst}


def _money(v):
    """Grouped to thousands. A proposal that prints 1033450.02 for its grand
    total looks like a spreadsheet dump, not an offer (owner 2026-09-09)."""
    return f"{Decimal(v or 0).quantize(Decimal('0.01')):,}"


def submission_context(t):
    """Everything the cover, the summary and the bill print."""
    from .commercial import amount_in_words
    from .pdf import _font_dir, company_info, mark_src

    doc = t.document
    rev = doc.current_revision
    boq = boq_for(t)
    bills, bill_total = _bills(boq)
    stack = money_stack(t, bill_total)

    def fdate(d):
        return d.strftime("%d %B %Y") if d else ""

    terms = [
        ("Offer validity", f"{t.validity_days} days from the date of issue"),
        ("Project duration",
         f"{t.duration_days} calendar days from site handover and receipt of "
         "advance payment" if t.duration_days else ""),
        ("Payment terms", t.payment_terms or DEFAULT_TERMS["payment_terms"]),
        ("Currency",
         f"{t.currency}. GST at {t.gst_percent:g}% shown separately"),
        ("By client", t.client_provides or DEFAULT_TERMS["client_provides"]),
        ("Exclusions", t.exclusions or DEFAULT_TERMS["exclusions"]),
        ("Variations", t.variations or DEFAULT_TERMS["variations"]),
        ("Warranty / DLP",
         t.warranty_terms or DEFAULT_TERMS["warranty_terms"]),
    ]
    return {
        "mark_src": mark_src(), "font_dir": _font_dir(),
        "co": company_info(),
        # The cover's reference: theirs if they keep one, ours otherwise.
        "ref": t.doc_ref or doc.ref,
        "system_ref": doc.ref,
        "rev_label": rev.rev_label if rev else "R0",
        "issue_date": fdate((rev.issued_at.date() if rev and rev.issued_at
                             else doc.doc_date)),
        "value_words": amount_in_words(stack["grand_total"], t.currency),
        "due_date": fdate(t.due_date),
        "enquiry_date": fdate(t.enquiry_date),
        "tender": t, "doc": doc, "rev": rev, "site": doc.site,
        "boq": boq, "bills": [{**b, "amount_fmt": _money(b["amount"])}
                              for b in bills],
        "bill_total": bill_total, "bill_total_fmt": _money(bill_total),
        # Pre-formatted so the document does not print a raw decimal at a
        # client. Only the money — the rate, the label and the provisional
        # rows are not amounts and must not go through the formatter.
        "stack_fmt": {k: _money(v) for k, v in stack.items()
                      if k not in ("gst_percent", "discount_label",
                                   "provisional_items")},
        "prov_rows": [{**p, "amount_fmt": _money(p["amount"])}
                      for p in stack["provisional_items"]],
        # The bill itself, with its money already grouped.
        "boq_rows": ([{
            "is_heading": it.is_heading,
            "section": it.section or it.description,
            "item_code": it.item_code, "description": it.description,
            "unit": it.unit,
            "qty": (f"{it.qty:,}" if it.qty is not None else ""),
            "rate": _money(it.rate_supply) if it.rate_supply is not None
            else "",
            "amount": _money(it.amount),
        } for it in boq.items.all().order_by("sort_order", "id")]
            if boq is not None else []),
        "offered": stack["subtotal"],
        "diverges": (t.value_submitted is not None
                     and abs(t.value_submitted - bill_total)
                     >= Decimal("0.01")),
        "stack": stack,
        "terms": [(k, v) for k, v in terms if v],
        "prepared_by": (t.prepared_by
                        or (t.assigned_to.full_name if t.assigned_to_id
                            else "")),
        "reviewed_by": t.reviewed_by,
        "approved_by": t.approved_by,
        "issued_on": rev.issued_at if rev else None,
        "our_bill": t.submit_our_format,
    }


# ---- what the price rests on ------------------------------------------
#
# A site visit and a tender meeting are the same shape of thing: arranged for
# a date with a team going, then written up afterwards. There is no
# request-and-wait step — that was invented, and is not how it is run (owner
# 2026-09-09).

def schedule_event(t, data, actor):
    """Put a visit or a meeting in the diary."""
    if t.document.status not in OPEN_STATUSES:
        return None, "This tender is closed."
    when = data.get("scheduled_on")
    if not when:
        return None, "When is it?"
    kind = (data.get("kind") or "VISIT").upper()
    if kind not in dict(TenderEvent.Kind.choices):
        return None, "A tender event is a site visit or a meeting."
    e = TenderEvent.objects.create(
        tender=t, kind=kind, scheduled_on=when,
        attendees=data.get("attendees", ""),
        client_attendees=data.get("client_attendees", ""),
        location=(data.get("location") or "")[:160],
        notes=data.get("notes", ""), created_by=actor)
    audit("tender", t.id, "TENDER_EVENT_SCHEDULED", actor=actor,
          detail={"ref": t.document.ref, "kind": kind,
                  "on": str(e.scheduled_on)})
    return e, None


def record_event(t, event_id, data, actor):
    """Write it up afterwards: what was seen, or what was discussed.

    A meeting's value is in the note; a visit's is in the note and the photos.
    Either way it is the half of the price that is not in the drawings.
    """
    e = t.events.filter(pk=event_id).first()
    if e is None:
        return None, "That is not on this tender."
    e.held_on = data.get("held_on") or e.scheduled_on
    for f in ("attendees", "client_attendees", "notes"):
        if f in data:
            setattr(e, f, data.get(f) or "")
    if "location" in data:
        e.location = (data.get("location") or "")[:160]
    e.save()
    audit("tender", t.id, "TENDER_EVENT_RECORDED", actor=actor,
          detail={"ref": t.document.ref, "kind": e.kind,
                  "on": str(e.held_on)})
    return e, None


def cancel_event(t, event_id, actor):
    """One that did not happen. Only before it is written up — a record of a
    meeting that took place is not deleted."""
    e = t.events.filter(pk=event_id).first()
    if e is None:
        return "That is not on this tender."
    if e.is_held:
        return ("This one has been written up. Its record stays; edit the "
                "notes if they are wrong.")
    e.delete()
    return None


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
