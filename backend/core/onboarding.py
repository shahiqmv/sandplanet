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
OPEN = ("DRAFT", "SUBMITTED", "RETURNED")        # editable / pre-approval
TERMINAL = ("COMPLETED", "REJECTED", "CANCELLED")  # closed
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


# ---- track stage machines (Phase 2) --------------------------------------

PROCESS_ROLES = ("HO_HR", "ADMIN")

# Track A (WP): endorsement is inserted only for Sri Lankan nationals.
_WP_HEAD = ["WP_APPOINTMENT", "WP_APPLICATION", "WP_APPROVED", "WP_DEPOSIT"]
_WP_TAIL = ["WP_TICKET", "WP_ARRIVED", "WP_MEDICAL", "WP_ISSUED"]
# Track B (BV): the BV chain, then the in-country WP conversion — appointment
# letter onward, no ticketing, no endorsement (arrival/medical already done).
_BV = ["BV_SPONSOR", "BV_INSURANCE", "BV_APPLICATION", "BV_APPROVED",
       "BV_VISA_FEE", "BV_TICKET", "BV_ARRIVED", "BV_MEDICAL"]
_BV_CONVERSION = ["WP_APPOINTMENT", "WP_APPLICATION", "WP_APPROVED",
                  "WP_DEPOSIT", "WP_ISSUED"]

STAGE_LABEL = {
    "WP_APPOINTMENT": "Appointment letter issued",
    "WP_APPLICATION": "WP application (portal)",
    "WP_APPROVED": "WP approved on portal",
    "WP_DEPOSIT": "WP deposit paid",
    "WP_ENDORSEMENT": "SL Embassy endorsement",
    "WP_TICKET": "Ticketed",
    "WP_ARRIVED": "Arrived",
    "WP_MEDICAL": "Medical",
    "WP_ISSUED": "Work permit issued",
    "BV_SPONSOR": "Sponsor letter issued",
    "BV_INSURANCE": "Insurance policy",
    "BV_APPLICATION": "BV application (portal)",
    "BV_APPROVED": "BV approved",
    "BV_VISA_FEE": "Visa fee paid",
    "BV_TICKET": "Ticketed",
    "BV_ARRIVED": "Arrived (BV clock starts)",
    "BV_MEDICAL": "Medical",
}
APPLICATION_STAGES = {"WP_APPLICATION", "BV_APPLICATION"}
ARRIVAL_STAGES = {"WP_ARRIVED", "BV_ARRIVED"}
MEDICAL_STAGES = {"WP_MEDICAL", "BV_MEDICAL"}
# Payment-gated stages — Phase 3 will require a PAID PYR to leave these.
PAYMENT_STAGES = {"WP_DEPOSIT", "WP_TICKET", "BV_INSURANCE", "BV_VISA_FEE",
                  "BV_TICKET"}


def _is_sri_lankan(case):
    return "sri lank" in (case.nationality or "").lower()


def sequence(case):
    """The ordered stages for a case, factoring the route, the SL-only embassy
    endorsement, and the BV→WP in-country conversion tail."""
    if case.route == "WP":
        seq = list(_WP_HEAD)
        if _is_sri_lankan(case):
            seq.append("WP_ENDORSEMENT")
        return seq + _WP_TAIL
    return list(_BV) + list(_BV_CONVERSION)


def _can_leave(case, stage):
    if stage in APPLICATION_STAGES and case.portal_status != "APPROVED":
        return "The government portal must show APPROVED before advancing."
    if stage in MEDICAL_STAGES:
        if case.medical_result == "FAIL":
            return "Medical failed — the case is with the Director to decide."
        if case.medical_result != "PASS":
            return "Record the medical result (PASS) before advancing."
    if stage in PAYMENT_STAGES:
        fee = fee_for(case, stage)
        if fee is None:
            return "Raise the fee PYR for this stage first."
        if fee.document.status != "PAID":
            return (f"Awaiting payment of {fee.document.ref} before "
                    "advancing.")
    return None


def _on_enter(case, stage, data):
    from datetime import date, timedelta
    if stage in ARRIVAL_STAGES:
        d = data.get("arrived_date")
        if not d:
            return "Enter the arrival date."
        try:
            ad = date.fromisoformat(str(d))
        except ValueError:
            return "Invalid arrival date."
        case.arrived_date = ad
        case.medical_due = ad + timedelta(days=14)   # company 14-day rule
        if stage == "BV_ARRIVED":
            if not data.get("bv_expiry"):
                return "Enter the BV expiry date shown on the visa."
            case.bv_expiry = data["bv_expiry"]
    return None


def advance_stage(case, data, actor):
    if actor.role not in PROCESS_ROLES:
        return "Only HR processes onboarding stages."
    doc = case.document
    seq = sequence(case)
    if doc.status == "APPROVED":                     # begin processing
        case.stage = seq[0]
        case.save(update_fields=["stage", "updated_at"])
        _set_status(doc, "IN_PROGRESS", "BEGIN", actor,
                    comment=STAGE_LABEL.get(seq[0], seq[0]))
        _stage_notify(case, seq[0])
        return None
    if doc.status != "IN_PROGRESS":
        return "This case is not in processing."
    if case.stage not in seq:
        return "The case stage is out of sync."
    err = _can_leave(case, case.stage)
    if err:
        return err
    idx = seq.index(case.stage)
    if idx + 1 >= len(seq):                          # past the last stage
        _set_status(doc, "COMPLETED", "COMPLETE", actor)
        audit("document", doc.id, "OBR_COMPLETED", actor=actor,
              detail={"ref": doc.ref})
        return None
    nxt = seq[idx + 1]
    err = _on_enter(case, nxt, data)
    if err:
        return err
    case.stage = nxt
    case.save()
    audit("document", doc.id, "OBR_STAGE", actor=actor,
          detail={"ref": doc.ref, "stage": nxt})
    _stage_notify(case, nxt)
    return None


def set_stage_data(case, data, actor):
    """HR mirrors the portal status / records the medical result without
    advancing the stage."""
    if actor.role not in PROCESS_ROLES:
        return "Only HR updates case processing data."
    if case.document.status != "IN_PROGRESS":
        return "The case is not in processing."
    changed = []
    if "portal_status" in data and case.stage in APPLICATION_STAGES:
        ps = (data.get("portal_status") or "").upper()
        if ps not in ("SUBMITTED", "ADDITIONAL_INFO", "APPROVED", "REJECTED"):
            return "Invalid portal status."
        case.portal_status = ps
        changed.append("portal_status")
    if "medical_result" in data and case.stage in MEDICAL_STAGES:
        mr = (data.get("medical_result") or "").upper()
        if mr not in ("PASS", "FAIL"):
            return "Medical result must be PASS or FAIL."
        case.medical_result = mr
        changed.append("medical_result")
        if mr == "FAIL":
            _notify_medical_fail(case)
    if not changed:
        return "Nothing to update at this stage."
    case.save()
    audit("document", case.document_id, "OBR_STAGE_DATA", actor=actor,
          detail={"fields": changed})
    return None


def _stage_notify(case, stage):
    from . import notify
    doc = case.document
    msg = {"WP_APPROVED": "permit approved on the portal",
           "BV_APPROVED": "business visa approved",
           "WP_TICKET": "ticketed", "BV_TICKET": "ticketed",
           "WP_ARRIVED": "arrived", "BV_ARRIVED": "arrived",
           "WP_ISSUED": "work permit issued"}.get(stage)
    if not msg:
        return
    body = f"{case.full_name} · {doc.site.code}"
    recips = list(notify._role_users("HO_HR"))
    pm = doc.site.current_pm()
    if pm:
        recips.append(pm)
    for u in recips:
        notify.notify_user(u, f"Onboarding {doc.ref} — {msg}",
                           body=body, category="alert")


def _notify_medical_fail(case):
    from . import notify
    doc = case.document
    for u in notify._role_users("DIRECTOR", "HO_HR"):
        notify.notify_user(u, f"Onboarding {doc.ref} — medical FAILED",
                           body=f"{case.full_name} · {doc.site.code}",
                           category="approval")


# ---- fee PYRs + payment gate (Phase 3) -----------------------------------

# stage -> (purpose label, refundable). The WP deposit is refundable (a deposit,
# not a cost), so its PYR posts nothing to the ledger.
FEE_META = {
    "WP_DEPOSIT": ("Work-permit deposit", True),
    "WP_TICKET": ("Air ticket", False),
    "BV_INSURANCE": ("Travel insurance premium", False),
    "BV_VISA_FEE": ("Business visa fee", False),
    "BV_TICKET": ("Air ticket", False),
}


def fee_for(case, stage):
    return case.fees.filter(stage=stage).select_related("document").first()


def raise_fee(case, data, actor):
    """HR raises the fee PYR for the case's current payment stage. It rides the
    normal PYR approval → voucher → paid chain; the case can't advance until
    it's paid."""
    from django.db import transaction
    from .models import (CostHead, Document, DocumentRevision, OnboardingFee)
    from .payments import _set_status, create_payment_request
    if actor.role not in PROCESS_ROLES:
        return None, "Only HR raises an onboarding fee."
    doc = case.document
    if doc.status != "IN_PROGRESS":
        return None, "The case is not in processing."
    stage = case.stage
    if stage not in PAYMENT_STAGES:
        return None, "This stage has no fee."
    if fee_for(case, stage) is not None:
        return None, "A fee PYR has already been raised for this stage."
    amount = _dec(data.get("amount"))
    if amount is None or amount <= Decimal("0"):
        return None, "Enter the fee amount."
    payee = (data.get("payee") or "").strip()
    if not payee:
        return None, "Enter the payee."
    label, refundable = FEE_META[stage]
    head, _ = CostHead.objects.get_or_create(
        name="Recruitment & Mobilisation", defaults={"sort_order": 95})
    with transaction.atomic():
        pyr = Document.objects.create(
            doc_type="PYR", ref=next_ref("PYR", doc.site), site=doc.site,
            doc_date=timezone.localdate(), status="DRAFT", created_by=actor)
        rev = DocumentRevision.objects.create(
            document=pyr, rev_label="R0", payload={}, created_by=actor)
        pyr.current_revision = rev
        pyr.save(update_fields=["current_revision"])
        pr, err = create_payment_request(pyr, {
            "cost_head_id": head.id, "amount_requested": str(amount),
            "currency": "MVR", "payee": payee, "payment_method": "BANK",
            "purpose": f"{label} — {doc.ref} · {case.full_name}"
                       + (" (refundable deposit)" if refundable else ""),
            "has_supporting_doc": bool(data.get("has_supporting_doc")),
        }, actor)
        if err:
            transaction.set_rollback(True)
            return None, err
        if refundable:                          # deposit posts nothing
            pr.is_capitalized = True
            pr.save(update_fields=["is_capitalized"])
        OnboardingFee.objects.create(case=case, document=pyr, stage=stage,
                                     refundable=refundable)
        _set_status(pyr, "SUBMITTED", "SUBMIT", actor,
                    f"{label} — onboarding {doc.ref}")
    audit("document", doc.id, "OBR_FEE_RAISED", actor=actor,
          detail={"stage": stage, "pyr": pyr.ref, "amount": str(amount)})
    return pyr, None


def on_fee_paid(pyr_doc, actor):
    """Called from the PYR pay action when an onboarding fee is paid — tells HR
    the case's payment gate is now clear."""
    fee = getattr(pyr_doc, "onboarding_fee", None)
    if fee is None:
        return
    from . import notify
    case = fee.case
    doc = case.document
    label = FEE_META.get(fee.stage, (fee.stage,))[0]
    for u in notify._role_users("HO_HR"):
        notify.notify_user(u, f"Onboarding {doc.ref} — {label} paid",
                           body=f"{case.full_name} · {doc.site.code} — "
                                "the case can now advance", category="alert")


# ---- serialisation -------------------------------------------------------

def checklist(case):
    have = set(case.document.attachments.values_list("kind", flat=True))
    return [{"kind": k, "label": label, "present": k in have}
            for k, label in REQUIRED_DOCS]


def stage_view(case):
    """The ordered stage stepper for the case + what the next advance needs."""
    seq = sequence(case)
    idx = seq.index(case.stage) if case.stage in seq else -1
    stages = [{"key": s, "label": STAGE_LABEL.get(s, s),
               "state": "done" if i < idx else "current" if i == idx
               else "future", "payment": s in PAYMENT_STAGES}
              for i, s in enumerate(seq)]
    nxt = seq[idx + 1] if 0 <= idx < len(seq) - 1 else None
    needs = None
    if nxt == "WP_ARRIVED":
        needs = "arrival"
    elif nxt == "BV_ARRIVED":
        needs = "arrival_bv"
    fee = None
    if case.stage in PAYMENT_STAGES:
        f = fee_for(case, case.stage)
        label, refundable = FEE_META.get(case.stage, ("", False))
        fee = {"label": label, "refundable": refundable, "raised": bool(f),
               "pyr_ref": f.document.ref if f else None,
               "pyr_status": f.document.status if f else None,
               "paid": bool(f) and f.document.status == "PAID"}
    return {"stages": stages, "next_stage": nxt,
            "next_label": STAGE_LABEL.get(nxt) if nxt else None,
            "next_needs": needs,
            "at_application": case.stage in APPLICATION_STAGES,
            "at_medical": case.stage in MEDICAL_STAGES,
            "at_payment": case.stage in PAYMENT_STAGES, "fee": fee,
            "at_last": idx == len(seq) - 1}


def case_dict(case):
    doc = case.document
    sv = stage_view(case)
    return {
        "id": doc.id, "ref": doc.ref, "status": doc.status,
        "site_code": doc.site.code, "doc_date": doc.doc_date,
        "stage": case.stage, "stage_label": STAGE_LABEL.get(case.stage, ""),
        "portal_status": case.portal_status,
        "medical_result": case.medical_result,
        "arrived_date": case.arrived_date, "medical_due": case.medical_due,
        "bv_expiry": case.bv_expiry, **sv,
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
