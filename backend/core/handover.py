"""Handover — the dossier, assembled as the job runs.

There was no snag list, no taking-over or making-good record and no handover
pack, and `defects_liability_months` sat on the project unread by anything, so
the DLP clock did not exist (conformance audit 2026-08-28).

The design point, from the external review and confirmed by the owner
(2026-08-29): the dossier is created WITH the project. Records the app already
holds — an approved inspection request, an approved material submittal, a
passed test point — become CANDIDATES for it as they are produced. Handover is
then assembled by construction rather than reconstructed in the last
fortnight, which is when it is always reconstructed badly.
"""
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from .audit import audit
from .models import Document, HandoverDossier, HandoverItem, SnagItem

RECORDER_ROLES = {"SITE_ADMIN", "SITE_ENGINEER", "PM", "DIRECTOR", "ADMIN",
                  "QS", "PA"}
# Accepting the dossier on the client's behalf, and closing snags, is not a
# data-entry task.
CLOSER_ROLES = {"PM", "DIRECTOR", "ADMIN", "QS"}

# What a resort client asks for, as the starting checklist. Deliberately a
# default rather than a rule — a fit-out job and a pond wall do not owe the
# same pack, and the PM edits it.
DEFAULT_REQUIREMENTS = [
    ("AS_BUILT", "GENERAL", "As-built drawings — architectural"),
    ("AS_BUILT", "MEP", "As-built drawings — MEP"),
    ("INSPECTION", "CIVIL", "Inspection requests — civil / structural"),
    ("INSPECTION", "MEP", "Inspection requests — MEP"),
    ("INSPECTION", "FINISHES", "Inspection requests — finishes"),
    ("INSPECTION", "GENERAL", "Pre-handover checklists"),
    ("TEST", "CIVIL", "Concrete cube test reports"),
    ("TEST", "MEP", "MEP testing & commissioning records"),
    ("TEST", "MEP", "Water pressure / leak test certificates"),
    ("SUBMITTAL", "GENERAL", "Approved material submittals"),
    ("OM_MANUAL", "MEP", "O&M manuals"),
    ("WARRANTY", "GENERAL", "Warranties & guarantees"),
    ("CERTIFICATE", "GENERAL", "Statutory & authority certificates"),
    ("TRAINING", "MEP", "Client training records"),
    ("SPARES", "GENERAL", "Spares & attic stock schedule"),
]

# Which section a finished record naturally belongs in.
DOC_SECTION = {
    "IR": "INSPECTION",
    "MAR": "SUBMITTAL",
    "SD": "SUBMITTAL",
    "MS": "SUBMITTAL",
    "ITP": "TEST",
}
ACCEPTED_STATUSES = {"APPROVED", "APPROVED_WITH_COMMENTS", "VERIFIED",
                     "CLOSED", "RECORDED"}


def _as_date(value):
    if isinstance(value, str) and value:
        return parse_date(value)
    return value or None


@transaction.atomic
def open_dossier(project, user, seed=True):
    """Create the dossier, with the standard checklist unless told not to."""
    dossier, created = HandoverDossier.objects.get_or_create(
        project=project, defaults={"created_by": user})
    if created and seed:
        HandoverItem.objects.bulk_create([
            HandoverItem(dossier=dossier, section=section,
                         discipline=discipline, title=title, sort_order=i)
            for i, (section, discipline, title)
            in enumerate(DEFAULT_REQUIREMENTS)])
        audit("project", project.id, "HANDOVER_OPENED", actor=user,
              detail={"items": len(DEFAULT_REQUIREMENTS)})
    return dossier, created


def candidates(dossier, limit=200):
    """Records already produced on this project that belong in the pack and
    are not in it yet. This is what makes the dossier assemble itself."""
    project = dossier.project
    already = set(dossier.items.filter(document__isnull=False)
                  .values_list("document_id", flat=True))
    docs = (Document.objects
            .filter(project=project, doc_type__in=DOC_SECTION.keys(),
                    is_void=False)
            .exclude(id__in=already)
            .order_by("doc_type", "ref")[:limit])
    out = []
    for doc in docs:
        if doc.status not in ACCEPTED_STATUSES:
            continue
        out.append({
            "document_id": doc.id, "ref": doc.ref, "doc_type": doc.doc_type,
            "status": doc.status, "doc_date": doc.doc_date,
            "suggested_section": DOC_SECTION.get(doc.doc_type, "OTHER"),
        })
    return out


@transaction.atomic
def add_item(dossier, data, user, file=None):
    title = (data.get("title") or "").strip()
    document = None
    if data.get("document_id"):
        document = Document.objects.filter(
            pk=data["document_id"], project=dossier.project).first()
        if document is None:
            return None, "That record does not belong to this project."
        if dossier.items.filter(document=document).exists():
            return None, f"{document.ref} is already in the pack."
        title = title or f"{document.doc_type} {document.ref}"
    if not title:
        return None, "What is this document?"

    section = data.get("section")
    if section not in dict(HandoverItem.Section.choices):
        section = (DOC_SECTION.get(document.doc_type, "OTHER")
                   if document else "OTHER")
    item = HandoverItem.objects.create(
        dossier=dossier, section=section,
        discipline=data.get("discipline") or "GENERAL",
        title=title, reference=(data.get("reference") or "")[:80],
        description=(data.get("description") or "").strip(),
        document=document, file=file,
        status=("PROVIDED" if (document or file) else "REQUIRED"),
        provided_on=(timezone.localdate() if (document or file) else None),
        provided_by=(user if (document or file) else None),
        notes=(data.get("notes") or "").strip())
    audit("project", dossier.project_id, "HANDOVER_ITEM_ADDED", actor=user,
          detail={"section": section, "title": title[:80],
                  "document": document.ref if document else ""})
    return item, None


@transaction.atomic
def update_item(item, data, user, file=None):
    changed = []
    for field in ("section", "discipline", "title", "reference",
                  "description", "notes", "status"):
        if field in data:
            setattr(item, field, data[field])
            changed.append(field)
    if file is not None:
        item.file = file
        changed.append("file")
    if item.status in ("PROVIDED", "ACCEPTED") and item.provided_on is None:
        item.provided_on = timezone.localdate()
        item.provided_by = user
        changed += ["provided_on", "provided_by"]
    if item.status == "ACCEPTED" and item.accepted_on is None:
        item.accepted_on = _as_date(data.get("accepted_on")) \
            or timezone.localdate()
        changed.append("accepted_on")
    if changed:
        item.save()
        audit("project", item.dossier.project_id, "HANDOVER_ITEM_UPDATED",
              actor=user, detail={"item": item.title[:60],
                                  "fields": sorted(set(changed))})
    return item


def completeness(dossier):
    """How ready the pack is, by section — the number a PM is asked for at
    every progress meeting in the last month of a job."""
    rows = {}
    total = satisfied = 0
    for item in dossier.items.all():
        bucket = rows.setdefault(item.section, {"required": 0, "provided": 0,
                                                "accepted": 0})
        if item.status == "NOT_APPLICABLE":
            continue
        bucket["required"] += 1
        total += 1
        if item.is_satisfied:
            bucket["provided"] += 1
            satisfied += 1
        if item.status == "ACCEPTED":
            bucket["accepted"] += 1
    for bucket in rows.values():
        bucket["pct"] = (round(100 * bucket["provided"] / bucket["required"])
                         if bucket["required"] else 0)
    return {
        "sections": rows,
        "required": total, "provided": satisfied,
        "pct": round(100 * satisfied / total) if total else 0,
    }


# ---- snags --------------------------------------------------------------

def next_snag_ref(dossier):
    last = dossier.snags.order_by("-id").first()
    n = 1
    if last is not None:
        try:
            n = int(str(last.ref_no).rsplit("-", 1)[-1]) + 1
        except ValueError:
            n = dossier.snags.count() + 1
    return f"SNG-{n:04d}"


@transaction.atomic
def raise_snag(dossier, data, user, photo=None):
    if not (data.get("description") or "").strip():
        return None, "What is the defect?"
    if not (data.get("location") or "").strip():
        return None, "Where is it? A snag without a location cannot be found."
    snag = SnagItem.objects.create(
        dossier=dossier, ref_no=next_snag_ref(dossier),
        location=data["location"].strip(),
        discipline=data.get("discipline") or "GENERAL",
        description=data["description"].strip(),
        raised_on=_as_date(data.get("raised_on")) or timezone.localdate(),
        raised_by=user, owner_id=data.get("owner_id") or None,
        owner_note=(data.get("owner_note") or "").strip(),
        due_date=_as_date(data.get("due_date")),
        photo=photo,
        in_dlp=bool(dossier.taking_over_on))
    audit("project", dossier.project_id, "SNAG_RAISED", actor=user,
          detail={"ref": snag.ref_no, "location": snag.location[:60],
                  "in_dlp": snag.in_dlp})
    return snag, None


@transaction.atomic
def update_snag(snag, data, user):
    changed = []
    for field in ("status", "location", "description", "discipline",
                  "owner_note", "due_date"):
        if field in data:
            setattr(snag, field, data[field] or None
                    if field == "due_date" else data[field])
            changed.append(field)
    if "owner_id" in data:
        snag.owner_id = data["owner_id"] or None
        changed.append("owner")
    if snag.status == "FIXED" and snag.fixed_on is None:
        snag.fixed_on = timezone.localdate()
        changed.append("fixed_on")
    if snag.status == "CLOSED" and snag.closed_on is None:
        snag.closed_on = timezone.localdate()
        snag.closed_by = user
        changed += ["closed_on", "closed_by"]
    if changed:
        snag.save()
        audit("project", snag.dossier.project_id, "SNAG_UPDATED", actor=user,
              detail={"ref": snag.ref_no, "fields": sorted(set(changed))})
    return snag


def snag_summary(dossier):
    rows = list(dossier.snags.all())
    today = timezone.localdate()
    return {
        "total": len(rows),
        "open": sum(1 for s in rows if s.is_open),
        "overdue": sum(1 for s in rows
                       if s.is_open and s.due_date and s.due_date < today),
        "in_dlp": sum(1 for s in rows if s.in_dlp),
        "closed": sum(1 for s in rows if s.status == "CLOSED"),
    }


@transaction.atomic
def record_milestone(dossier, data, user):
    """Taking-over and making-good. Recording taking-over starts the
    defects-liability clock, which previously did not exist."""
    changed = []
    for field in ("taking_over_on", "making_good_on"):
        if field in data:
            setattr(dossier, field, _as_date(data[field]))
            changed.append(field)
    for field in ("taking_over_ref", "making_good_ref", "notes"):
        if field in data:
            setattr(dossier, field, data[field])
            changed.append(field)
    if "target_date" in data:
        dossier.target_date = _as_date(data["target_date"])
        changed.append("target_date")
    if changed:
        dossier.save()
        audit("project", dossier.project_id, "HANDOVER_MILESTONE",
              actor=user,
              detail={"fields": sorted(changed),
                      "dlp_ends": str(dossier.defects_liability_ends() or "")})
    return dossier
