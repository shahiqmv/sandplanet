"""Onboarding cases (expat recruitment / visa / mobilisation).

An OBR is a Document subtype (doc_type="OBR", site-scoped) with an
OnboardingCase sidecar — same shape as a PYR. PM/HR raise it, the Director (PD)
is the single approval gate, HR processes the visa/permit stages, and on
completion it becomes a DIRECT employee. This module owns the case spine:
create → checklist-gated submit → PD approve / return / reject. The per-track
stage machines, fee PYRs, letters, clocks and handover build on top of it.
"""
import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .audit import audit
from .models import (Approval, Document, DocumentRevision, OnboardingCase)
from .numbering import next_ref

log = logging.getLogger(__name__)

RAISE_ROLES = ("PM", "HO_HR", "ADMIN")          # who logs a case
APPROVE_ROLES = ("DIRECTOR", "ADMIN")            # the PD gate
OPEN = ("DRAFT", "SUBMITTED", "RETURNED")
# Mandatory checklist documents (Attachment kinds) before an OBR can be submitted
REQUIRED_DOCS = [
    ("PASSPORT_COPY", "Passport copy"),
    ("PASSPORT_PHOTO", "Passport photo"),
    ("PASSPORT_OBS", "Passport observation page"),
    ("CV", "CV"),
]


def _dec(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


# ---- transitions (mirrors payments.py) -----------------------------------

def _transition(doc, new_status):
    return new_status in Document.TRANSITIONS["OBR"].get(doc.status, set())


def _record(doc, action, user, comment=""):
    Approval.objects.create(
        document=doc, revision=doc.current_revision, action=action,
        actor=user, actor_role=user.role, comment=comment)


def _set_status(doc, new_status, action, user, comment=""):
    old = doc.status
    doc.status = new_status
    doc.save(update_fields=["status", "updated_at"])
    _record(doc, action, user, comment=comment)
    audit("document", doc.id, f"OBR_{action}", actor=user,
          from_state=old, to_state=new_status, detail={"ref": doc.ref})
    from .notify import notify_document
    try:
        notify_document(doc, user)
    except Exception:                       # pragma: no cover - defensive
        log.exception("notify_document(OBR) failed")


# ---- create / edit -------------------------------------------------------

_FIELDS = ("full_name", "nationality", "gender", "passport_no",
           "trade_designation", "permanent_address", "mobile",
           "emergency_contact", "bv_justification")
_DATE_FIELDS = ("date_of_birth", "passport_expiry", "mobilisation_date")


def _apply_fields(case, data):
    for f in _FIELDS:
        if f in data:
            setattr(case, f, (data.get(f) or "").strip())
    for f in _DATE_FIELDS:
        if f in data:
            setattr(case, f, data.get(f) or None)
    if "category" in data:
        case.category = data.get("category") or ""
    if "route" in data:
        case.route = data.get("route") or ""
    if "currency" in data:
        case.currency = (data.get("currency") or "MVR")[:3].upper()
    if "job_category_id" in data:
        case.job_category_id = data.get("job_category_id") or None
    if "proposed_salary" in data:
        case.proposed_salary = _dec(data.get("proposed_salary"))


def _validate(case):
    if not case.full_name.strip():
        return "Candidate full name is required."
    if not case.nationality.strip():
        return "Nationality is required."
    if not case.passport_no.strip():
        return "Passport number is required."
    if case.route not in ("WP", "BV"):
        return "Choose a route — Work Permit or Business Visa."
    if case.route == "BV" and not case.bv_justification.strip():
        return "A Business Visa needs a justification note (it is urgent-track)."
    if not case.category:
        return "Choose the category — Skilled / Unskilled / Staff."
    if not case.trade_designation.strip():
        return "Trade / designation is required."
    if case.proposed_salary is None or case.proposed_salary <= 0:
        return "Proposed salary is required (it goes on the appointment letter)."
    return None


def create_case(site, data, actor):
    if actor.role not in RAISE_ROLES:
        return None, "Only a PM or HR can raise an onboarding request."
    with transaction.atomic():
        doc = Document.objects.create(
            doc_type="OBR", ref=next_ref("OBR", site), site=site,
            doc_date=timezone.localdate(), status="DRAFT", created_by=actor)
        rev = DocumentRevision.objects.create(
            document=doc, rev_label="R0", payload={}, created_by=actor)
        doc.current_revision = rev
        doc.save(update_fields=["current_revision"])
        case = OnboardingCase(document=doc)
        _apply_fields(case, data)
        case.save()
    audit("document", doc.id, "OBR_CREATED", actor=actor,
          detail={"ref": doc.ref, "candidate": case.full_name})
    return case, None


def update_case(case, data, actor):
    if case.document.status not in ("DRAFT", "RETURNED"):
        return "This case can no longer be edited."
    _apply_fields(case, data)
    case.save()
    audit("document", case.document_id, "OBR_EDITED", actor=actor)
    return None


# ---- submit / decide -----------------------------------------------------

def missing_documents(case):
    have = set(case.document.attachments.values_list("kind", flat=True))
    return [label for kind, label in REQUIRED_DOCS if kind not in have]


def submit_case(case, actor):
    doc = case.document
    if doc.status not in ("DRAFT", "RETURNED"):
        return "Only a draft / returned case can be submitted."
    if actor.role not in RAISE_ROLES:
        return "Only the site team / HR can submit this case."
    err = _validate(case)
    if err:
        return err
    missing = missing_documents(case)
    if missing:
        return "Attach all required documents before submitting: " \
            + ", ".join(missing) + "."
    if not _transition(doc, "SUBMITTED"):
        return f"Cannot submit a {doc.status} case."
    _set_status(doc, "SUBMITTED", "SUBMIT", actor)
    return None


def decide_case(case, action, actor, note=""):
    doc = case.document
    if action == "approve":
        if actor.role not in APPROVE_ROLES:
            return "Only the Director (PD) approves an onboarding case."
        if not _transition(doc, "APPROVED"):
            return f"Cannot approve a {doc.status} case."
        _set_status(doc, "APPROVED", "APPROVE", actor, comment=note)
        return None
    if action == "return":
        if actor.role not in APPROVE_ROLES:
            return "Only the Director can return a case."
        if not note.strip():
            return "A reason is required to return the case."
        if not _transition(doc, "RETURNED"):
            return f"Cannot return a {doc.status} case."
        _set_status(doc, "RETURNED", "RETURN", actor, comment=note)
        return None
    if action == "reject":
        if actor.role not in APPROVE_ROLES:
            return "Only the Director can reject a case."
        if not _transition(doc, "REJECTED"):
            return f"Cannot reject a {doc.status} case."
        _set_status(doc, "REJECTED", "REJECT", actor, comment=note)
        return None
    if action == "cancel":
        if actor.role not in RAISE_ROLES:
            return "Only the site team / HR can cancel a case."
        if not _transition(doc, "CANCELLED"):
            return f"Cannot cancel a {doc.status} case."
        _set_status(doc, "CANCELLED", "CANCEL", actor, comment=note)
        return None
    return "Unknown action."


# ---- serialisation -------------------------------------------------------

def checklist(case):
    have = set(case.document.attachments.values_list("kind", flat=True))
    return [{"kind": k, "label": label, "present": k in have}
            for k, label in REQUIRED_DOCS]


def case_dict(case):
    doc = case.document
    return {
        "id": doc.id, "ref": doc.ref, "status": doc.status,
        "site_code": doc.site.code, "doc_date": doc.doc_date,
        "route": case.route, "category": case.category,
        "full_name": case.full_name, "nationality": case.nationality,
        "date_of_birth": case.date_of_birth, "gender": case.gender,
        "passport_no": case.passport_no, "passport_expiry": case.passport_expiry,
        "trade_designation": case.trade_designation,
        "job_category_id": case.job_category_id,
        "proposed_salary": case.proposed_salary, "currency": case.currency,
        "permanent_address": case.permanent_address, "mobile": case.mobile,
        "emergency_contact": case.emergency_contact,
        "mobilisation_date": case.mobilisation_date,
        "bv_justification": case.bv_justification,
        "stage": case.stage, "bv_expiry": case.bv_expiry,
        "medical_due": case.medical_due,
        "created_by": doc.created_by.full_name if doc.created_by_id else "",
        "checklist": checklist(case),
        "missing_docs": missing_documents(case),
        "approvals": [{"action": a.action, "by": a.actor.full_name,
                       "role": a.actor_role, "at": a.acted_at,
                       "comment": a.comment}
                      for a in doc.approvals.select_related("actor")
                      .order_by("acted_at")],
    }
