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
from .permissions import is_staff_grade, sees_staff_pay
from .models import (Approval, Document, DocumentRevision, OnboardingCase)
from .numbering import next_ref

log = logging.getLogger(__name__)

# The Director and his PA both log onboarding cases (owner 2026-08-02); HR/PM
# too. Approval is a separate gate below.
RAISE_ROLES = ("PM", "HO_HR", "ADMIN", "PA", "DIRECTOR")   # who logs a case
# A MANAGEMENT hire is head office's to raise, not a site's — the PM had no
# business setting a management salary, and now cannot see one either (owner
# 2026-08-16). Sites still raise their own skilled/unskilled workers.
STAFF_RAISE_ROLES = ("HO_HR", "ADMIN", "PA", "DIRECTOR")
APPROVE_ROLES = ("DIRECTOR", "ADMIN")            # the PD gate
OPEN = ("DRAFT", "SUBMITTED", "RETURNED")        # editable / pre-approval
TERMINAL = ("COMPLETED", "REJECTED", "CANCELLED")  # closed
# Mandatory checklist documents (Attachment kinds) before an OBR can be submitted
# (kind, label, required). The CV is optional — everything else gates submit.
CHECKLIST_DOCS = [
    ("PASSPORT_COPY", "Passport copy", True),
    ("PASSPORT_PHOTO", "Passport photo", True),
    ("PASSPORT_OBS", "Passport observation page", True),
    ("CV", "CV", False),
]
REQUIRED_DOCS = [(k, label) for k, label, req in CHECKLIST_DOCS if req]


def _dec(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


# Monthly allowances offered in the case form's dropdown (HR can also type a
# custom name via "Other"). Amounts are in the case currency and land on the LOA.
ALLOWANCE_TYPES = ["Food", "Accommodation", "Transport"]


def _clean_allowances(raw, default_currency="MVR"):
    """Sanitise allowance lines to [{type, amount, currency}] — a non-empty type,
    a positive amount and an MVR/USD currency (each line chooses its own,
    defaulting to the case currency); blank/invalid rows are dropped."""
    out = []
    for a in raw or []:
        if not isinstance(a, dict):
            continue
        typ = str(a.get("type") or "").strip()[:40]
        amt = _dec(a.get("amount"))
        cur = str(a.get("currency") or default_currency)[:3].upper()
        if cur not in ("MVR", "USD"):
            cur = default_currency
        if typ and amt is not None and amt > 0:
            out.append({"type": typ, "amount": str(amt), "currency": cur})
    return out


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

_FIELDS = ("full_name", "nationality", "gender", "marital_status",
           "passport_no", "old_passport_no",
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
    if "quota_pool" in data:
        pool = (data.get("quota_pool") or "").upper()
        if pool in ("SANDPLANET", "MARINE"):
            case.quota_pool = pool
    if "bv_purpose" in data:
        p = (data.get("bv_purpose") or "").upper()
        case.bv_purpose = p if p in ("RECRUITMENT", "SUBCONTRACT") else ""
    if "subcontractor_id" in data:
        case.subcontractor_id = data.get("subcontractor_id") or None
    if ("route" in data or "bv_purpose" in data) and not _is_subcontract(case):
        case.subcontractor_id = None             # only subcontract BV keeps one
    if "currency" in data:
        case.currency = (data.get("currency") or "MVR")[:3].upper()
    if "job_category_id" in data:
        case.job_category_id = data.get("job_category_id") or None
    if "proposed_salary" in data:
        case.proposed_salary = _dec(data.get("proposed_salary"))
    if "allowances" in data:
        case.allowances = _clean_allowances(data.get("allowances"),
                                            case.currency or "MVR")


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
    if case.route == "BV":
        if case.bv_purpose not in ("RECRUITMENT", "SUBCONTRACT"):
            return ("Choose the business-visa purpose — recruitment or a "
                    "subcontractor's worker.")
        if case.bv_purpose == "SUBCONTRACT":
            if not case.subcontractor_id:
                return "Pick the subcontractor this worker belongs to."
            from .models import Subcontractor
            sub = Subcontractor.objects.filter(pk=case.subcontractor_id).first()
            if not sub or sub.site_id != case.document.site_id:
                return "Pick a subcontractor at the destination site."
    if not case.category:
        return "Choose the category — Skilled / Unskilled / Staff."
    if not case.trade_designation.strip():
        return "Trade / designation is required."
    if not _is_subcontract(case) and (case.proposed_salary is None
                                      or case.proposed_salary <= 0):
        return "Proposed salary is required (it goes on the appointment letter)."
    return None


def _staff_gate(case, actor):
    """A management case is head office's. Checked on create, on edit and again
    on submit, because the category can be changed after the case is open."""
    if case.category == "STAFF" and actor.role not in STAFF_RAISE_ROLES:
        return ("A management (Staff) hire is raised by HR, not by a site. "
                "Choose Skilled or Unskilled, or ask HR to log this one.")
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
        err = _staff_gate(case, actor)
        if err:
            transaction.set_rollback(True)
            return None, err
        case.save()
    audit("document", doc.id, "OBR_CREATED", actor=actor,
          detail={"ref": doc.ref, "candidate": case.full_name})
    return case, None


def update_case(case, data, actor):
    if case.document.status not in ("DRAFT", "RETURNED"):
        return "This case can no longer be edited."
    # An editor who cannot SEE the salary cannot overwrite it: their form was
    # seeded from a redacted payload, so echoing those keys back would blank
    # the real figure. The Director is exactly this case — they raise a
    # management hire but do not see pay (owner 2026-08-16).
    if is_staff_grade(category=case.category) and not sees_staff_pay(actor):
        data = {k: v for k, v in data.items()
                if k not in ("proposed_salary", "allowances")}
    _apply_fields(case, data)
    err = _staff_gate(case, actor)
    if err:
        return err
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
    err = _staff_gate(case, actor) or _validate(case)
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


_DEAD_FEE = ("CANCELLED", "REJECTED", "VOID")


def _post_approval_return_block(case):
    """Why an approved / in-progress case can't be sent back for edits — None if
    it can. Blocks once processing has real side effects."""
    if case.employee_id:
        return ("This worker is already mobilised — their details live on the "
                "Employee record now, so the case can't be sent back. Edit the "
                "employee instead.")
    if case.fees.exclude(document__status__in=_DEAD_FEE).exists():
        return ("A payment request has already been raised in processing. "
                "Cancel that PYR (or the whole case) rather than sending it "
                "back for edits.")
    if case.letters.exists():
        return ("A letter has already been issued for this case. Send-back is "
                "blocked to avoid an inconsistent letter — cancel and re-raise "
                "if the details are wrong.")
    return None


def can_send_back(case):
    """A Director can return an approved / in-progress case to edits when
    processing hasn't produced side effects yet (drives the UI button)."""
    return (case.document.status in ("APPROVED", "IN_PROGRESS")
            and _post_approval_return_block(case) is None)


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
        prev = doc.status
        # Sending an already-approved / in-progress case back for edits is
        # allowed, but not once processing has produced side effects — a raised
        # fee, an issued letter, or a mobilised worker (owner 2026-08-06).
        if prev in ("APPROVED", "IN_PROGRESS"):
            block = _post_approval_return_block(case)
            if block:
                return block
        if not _transition(doc, "RETURNED"):
            return f"Cannot return a {doc.status} case."
        # Re-editing means re-approval: clear the processing stage so the track
        # restarts cleanly when it's approved again.
        if prev in ("APPROVED", "IN_PROGRESS") and (case.stage
                                                    or case.portal_status):
            case.stage = ""
            case.portal_status = ""
            case.save(update_fields=["stage", "portal_status"])
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

PROCESS_ROLES = ("HO_HR", "ADMIN", "PA")   # PA = full HR (owner 2026-08-03)

# Track A (WP): endorsement is inserted only for Sri Lankan nationals.
_WP_HEAD = ["WP_APPOINTMENT", "WP_APPLICATION", "WP_APPROVED", "WP_DEPOSIT"]
_WP_TAIL = ["WP_TICKET", "WP_ARRIVED", "WP_MEDICAL", "WP_ISSUED"]
# Track B (BV): no medical on the business visa itself (owner) — a recruitment
# BV does the medical only during the in-country WP conversion; a subcontract BV
# has no conversion and no medical at all.
_BV = ["BV_SPONSOR", "BV_INSURANCE", "BV_APPLICATION", "BV_APPROVED",
       "BV_VISA_FEE", "BV_TICKET", "BV_ARRIVED"]
_BV_CONVERSION = ["WP_APPOINTMENT", "WP_APPLICATION", "WP_APPROVED",
                  "WP_DEPOSIT", "WP_MEDICAL", "WP_ISSUED"]

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
}

# What is actually PENDING while a case sits at a stage — the stage labels above
# are past-tense milestones ("Visa fee paid") which read as done even when the
# case is still working on them, so the status summary uses these instead.
PENDING_LABEL = {
    "WP_APPOINTMENT": "Appointment letter", "WP_APPLICATION": "WP application",
    "WP_APPROVED": "WP portal approval", "WP_DEPOSIT": "WP deposit",
    "WP_ENDORSEMENT": "Embassy endorsement", "WP_TICKET": "Ticketing",
    "WP_ARRIVED": "Arrival", "WP_MEDICAL": "Medical", "WP_ISSUED": "Work permit",
    "BV_SPONSOR": "Sponsor letter", "BV_INSURANCE": "Insurance",
    "BV_APPLICATION": "BV application", "BV_APPROVED": "BV portal approval",
    "BV_VISA_FEE": "Visa fee", "BV_TICKET": "Ticketing", "BV_ARRIVED": "Arrival",
}
APPLICATION_STAGES = {"WP_APPLICATION", "BV_APPLICATION"}


def pending_summary(case):
    """What is pending, and — where the label alone misleads — a note saying
    what it really means.

    A recruitment business visa converts to a work permit in-country, and the
    conversion opens at WP_APPOINTMENT. "Appointment letter pending" is the
    true next action, but it reads like a piece of filing and hides the fact
    that the work-permit process has not started at all — on a visa that is
    already counting down (owner 2026-08-18, on OBR-SJR-004). On a straight WP
    case the same stage genuinely is just the letter, so the note is not shown
    there.
    """
    label = PENDING_LABEL.get(case.stage, "")
    note = ""
    if case.stage == "WP_APPOINTMENT" and case.route == "BV":
        label = "Work-permit conversion"
        note = "not started — the appointment letter begins it"
    return label, note


def portal_for(case, stage=None):
    """The portal reference + status for ONE application stage.

    A BV→WP case lodges two applications, so asking the case for "the" portal
    reference is the wrong question — it has to be asked per stage.
    """
    stage = stage or case.stage
    row = (case.portal_by_stage or {}).get(stage) or {}
    return {"ref": row.get("ref") or "", "status": row.get("status") or ""}


def set_portal(case, stage, ref=None, status=None):
    """Record a reference / status against a stage. Mirrors into the flat
    columns while `stage` is the case's current one, so everything reading
    case.portal_ref keeps seeing the application actually in hand."""
    by = dict(case.portal_by_stage or {})
    row = dict(by.get(stage) or {})
    if ref is not None:
        row["ref"] = ref
    if status is not None:
        row["status"] = status
    by[stage] = row
    case.portal_by_stage = by
    fields = ["portal_by_stage"]
    if stage == case.stage:
        case.portal_ref = row.get("ref") or ""
        case.portal_status = row.get("status") or ""
        fields += ["portal_ref", "portal_status"]
    return fields


def _load_portal_for_stage(case):
    """Point the flat columns at the stage the case has just entered. A fresh
    application stage starts blank even though an earlier one was approved."""
    cur = portal_for(case, case.stage)
    case.portal_ref, case.portal_status = cur["ref"], cur["status"]
    return ["portal_ref", "portal_status"]


def application_state(case):
    """What is ACTUALLY being waited for at an application stage.

    "BV application pending" covered two opposite situations — we still have to
    lodge it, and we lodged it days ago and the portal has not answered — and
    hid a third that needs us back at the keyboard, the portal asking for more
    information. Fourteen live cases sat at an application stage reading
    identically (owner 2026-08-17, on OBR-SFR-008).

    `state` is what the screen colours on: WAIT_US = ours to move, WAIT_PORTAL =
    theirs, READY = clear to advance.
    """
    if case.stage not in APPLICATION_STAGES:
        return None
    cur = portal_for(case, case.stage)
    ref, status = cur["ref"], cur["status"]
    if status == "APPROVED":
        return {"state": "READY", "note": "approved — ready to advance",
                "ref": ref, "portal_status": status}
    if status == "ADDITIONAL_INFO":
        return {"state": "WAIT_US",
                "note": "the portal asked for more information",
                "ref": ref, "portal_status": status}
    if status == "REJECTED":
        return {"state": "WAIT_US", "note": "the portal rejected it",
                "ref": ref, "portal_status": status}
    if not ref:
        return {"state": "WAIT_US", "note": "not lodged on the portal yet",
                "ref": "", "portal_status": status}
    # Lodged. A reference with no status recorded is still with them, but say
    # so rather than implying we know more than we do.
    return {"state": "WAIT_PORTAL",
            "note": ("awaiting the portal" if status else
                     "awaiting the portal — portal status not recorded"),
            "ref": ref, "portal_status": status}
ARRIVAL_STAGES = {"WP_ARRIVED", "BV_ARRIVED"}
MEDICAL_STAGES = {"WP_MEDICAL"}          # medical is a work-permit step only
# Payment-gated stages — Phase 3 will require a PAID PYR to leave these.
PAYMENT_STAGES = {"WP_DEPOSIT", "WP_TICKET", "BV_INSURANCE", "BV_VISA_FEE",
                  "BV_TICKET"}

# Authorisation on a payment voucher is the commitment point — the money goes
# out there, and Finance's PAID stamp is bookkeeping that follows it, often by
# weeks. Waiting for the stamp left seven of the eight live cases parked at an
# insurance or visa-fee stage that had already been settled (owner 2026-08-16,
# the same rule already applied to salary-advance recovery).
FEE_SETTLED = ("PAID", "AUTHORISED")


def _is_sri_lankan(case):
    return "sri lank" in (case.nationality or "").lower()


def _is_subcontract(case):
    return case.route == "BV" and case.bv_purpose == "SUBCONTRACT"


def sequence(case):
    """The ordered stages for a case, factoring the route, the SL-only embassy
    endorsement, the BV purpose, and the BV→WP in-country conversion tail."""
    if case.route == "WP":
        seq = list(_WP_HEAD)
        if _is_sri_lankan(case):
            seq.append("WP_ENDORSEMENT")
        return seq + _WP_TAIL
    if _is_subcontract(case):            # subcontract BV ends on arrival
        return list(_BV)
    return list(_BV) + list(_BV_CONVERSION)   # recruitment BV converts to WP


def set_hold(case, reason, actor):
    """Stop a case until something outside the process is resolved.

    The portal answers an application with things like "the candidate already
    holds an active visa pending cancellation" — nothing in the onboarding
    machine can clear that, and the case must wait. Without somewhere to say
    so it just sat at the application stage looking slow, and only the person
    who read the portal knew why (owner 2026-08-16).
    """
    from django.utils import timezone

    if actor.role not in PROCESS_ROLES:
        return "Only HR holds a case."
    reason = (reason or "").strip()
    if not reason:
        return "Say what the case is waiting on."
    if case.document.status != "IN_PROGRESS":
        return "Only a case in processing can be held."
    case.hold_reason = reason
    case.hold_since = case.hold_since or timezone.localdate()
    case.hold_by = actor
    case.save(update_fields=["hold_reason", "hold_since", "hold_by",
                             "updated_at"])
    audit("document", case.document_id, "OBR_HELD", actor=actor,
          detail={"ref": case.document.ref, "stage": case.stage,
                  "reason": reason})
    _notify_hold(case, held=True)
    return None


def clear_hold(case, actor, note=""):
    """The blockage is resolved — the case rejoins the process."""
    if actor.role not in PROCESS_ROLES:
        return "Only HR releases a case."
    if not case.hold_reason:
        return "This case is not on hold."
    was = case.hold_reason
    case.hold_reason = ""
    case.hold_since = None
    case.hold_by = None
    case.save(update_fields=["hold_reason", "hold_since", "hold_by",
                             "updated_at"])
    audit("document", case.document_id, "OBR_HOLD_CLEARED", actor=actor,
          detail={"ref": case.document.ref, "was": was, "note": note})
    _notify_hold(case, held=False)
    return None


def _notify_hold(case, held):
    """Everyone with a stake hears it: HR, and the site expecting the man."""
    from . import notify

    doc = case.document
    title = (f"Onboarding {doc.ref} — on hold" if held
             else f"Onboarding {doc.ref} — hold lifted")
    body = (f"{case.full_name} · {doc.site.code} — "
            + (case.hold_reason if held else "back in process"))
    seen = set()
    for u in list(notify._role_users("HO_HR")) + list(
            doc.site.current_pms() if hasattr(doc.site, "current_pms") else []):
        if u.id in seen:
            continue
        seen.add(u.id)
        notify.notify_user(u, title, body=body,
                           category="alert" if held else "info")


def _can_leave(case, stage):
    if case.hold_reason:
        return f"On hold — {case.hold_reason}"
    # Nothing moves before the signatory signs the case off (owner 2026-08-11):
    # staff were generating the LOA and lodging the work-permit application
    # while the sign-off was still pending. The signatory's approval is the
    # start line for the whole case, not a later formality.
    if case.signatory_approved_at is None:
        return ("Awaiting the signatory's sign-off — no letter or application "
                "can go out before the case is signed.")
    if stage in APPLICATION_STAGES:
        # THIS stage's application, not whichever one was approved last. A
        # business visa approved in July was letting the work-permit stage be
        # walked straight past without an application (owner 2026-08-18).
        cur = portal_for(case, stage)
        if not cur["ref"]:
            return ("Record the portal reference for this application before "
                    "advancing.")
        if cur["status"] != "APPROVED":
            return "The government portal must show APPROVED before advancing."
    if stage in MEDICAL_STAGES:
        if case.medical_result == "FAIL":
            return "Medical failed — the case is with the Director to decide."
        if case.medical_result != "PASS":
            return "Record the medical result (PASS) before advancing."
    if stage in PAYMENT_STAGES and stage not in (case.waived_stages or []):
        fee = active_fee_for(case, stage)
        if fee is None:
            return "Raise the fee PYR for this stage first."
        if fee.document.status not in FEE_SETTLED:
            return (f"Awaiting payment of {fee.document.ref} before "
                    "advancing.")
    return None


def _on_enter(case, stage, data):
    from datetime import date, timedelta
    if stage in APPLICATION_STAGES:
        # The portal issues a reference the moment the application is lodged.
        # Without it the application cannot be found again, and HR was keeping
        # them on paper (owner 2026-08-16).
        # Fall back to THIS stage's own reference (so re-entering it is fine),
        # never to case.portal_ref — on a BV→WP case that holds the business
        # visa's number, which was quietly accepted as the work permit's
        # (owner 2026-08-18).
        ref = (data.get("portal_ref")
               or portal_for(case, stage)["ref"] or "").strip()
        if not ref:
            return ("Enter the government portal reference for this "
                    "application (e.g. GSR/2026/27757).")
        set_portal(case, stage, ref=ref)
    if stage in ARRIVAL_STAGES:
        d = data.get("arrived_date")
        if not d:
            return "Enter the arrival date."
        try:
            ad = date.fromisoformat(str(d))
        except ValueError:
            return "Invalid arrival date."
        case.arrived_date = ad
        # A medical clock only makes sense when the track actually has a medical
        # step (WP, or a recruitment BV that converts). Subcontract BV has none.
        if "WP_MEDICAL" in sequence(case):
            case.medical_due = ad + timedelta(days=14)   # company 14-day rule
        if stage == "BV_ARRIVED":
            if not data.get("bv_expiry"):
                return "Enter the BV expiry date shown on the visa."
            case.bv_expiry = data["bv_expiry"]
    return None


def advance_stage(case, data, actor, system=False):
    """Move a case on a stage. `system=True` is the app itself acting — used
    when a fee payment clears the gate the case was waiting on, where the
    actor is Finance rather than HR (owner 2026-08-16). Every other gate
    still applies."""
    if not system and actor.role not in PROCESS_ROLES:
        return "Only HR processes onboarding stages."
    doc = case.document
    seq = sequence(case)
    if doc.status == "APPROVED":                     # begin processing
        case.stage = seq[0]
        case.stage_since = timezone.localdate()
        case.save(update_fields=["stage", "stage_since", "updated_at"])
        _set_status(doc, "IN_PROGRESS", "BEGIN", actor,
                    comment=STAGE_LABEL.get(seq[0], seq[0]))
        _stage_notify(case, seq[0])
        return None
    if doc.status != "IN_PROGRESS":
        return "This case is not in processing."
    if case.stage not in seq:
        return "The case stage is out of sync."
    # HR marked this fee "not applicable" (e.g. Indian nationals pay no visa
    # fee) — record it so the stage can advance without a PYR.
    if data.get("waive_fee") and case.stage in PAYMENT_STAGES \
            and case.stage not in (case.waived_stages or []):
        if active_fee_for(case, case.stage):
            return "A fee has already been raised for this stage — pay or void it."
        case.waived_stages = list(case.waived_stages or []) + [case.stage]
        case.save(update_fields=["waived_stages", "updated_at"])
        audit("document", doc.id, "OBR_FEE_WAIVED", actor=actor,
              detail={"ref": doc.ref, "stage": case.stage})
    err = _can_leave(case, case.stage)
    if err:
        return err
    idx = seq.index(case.stage)
    if idx + 1 >= len(seq):                          # past the last stage
        if _is_subcontract(case):
            return ("A subcontract worker's case closes when they leave — use "
                    "'Worker departed' to close it.")
        created = case.employee_id is None
        with transaction.atomic():
            _set_status(doc, "COMPLETED", "COMPLETE", actor)
            emp = _handover_employee(case, actor)    # safety net (usually a no-op)
        audit("document", doc.id, "OBR_COMPLETED", actor=actor,
              detail={"ref": doc.ref, "emp_no": emp.emp_no if emp else ""})
        if created:
            _notify_handover(case, emp)
        return None
    nxt = seq[idx + 1]
    err = _on_enter(case, nxt, data)
    if err:
        return err
    case.stage = nxt
    case.stage_since = timezone.localdate()
    # A new application stage is a NEW application: point the flat portal
    # columns at this stage's own (usually empty) reference and status, so an
    # earlier route's approval cannot stand in for one nobody has lodged.
    _load_portal_for_stage(case)
    case.save()
    audit("document", doc.id, "OBR_STAGE", actor=actor,
          detail={"ref": doc.ref, "stage": nxt})
    _stage_notify(case, nxt)
    # Salary + site manpower start on arrival (owner): mobilise into the
    # Employee DB the moment the worker lands, not at case completion.
    if nxt in ARRIVAL_STAGES and case.employee_id is None:
        emp = _handover_employee(case, actor)
        _notify_handover(case, emp)
    return None


def set_stage_data(case, data, actor):
    """HR mirrors the portal status / records the medical result without
    advancing the stage."""
    if actor.role not in PROCESS_ROLES:
        return "Only HR updates case processing data."
    if case.document.status != "IN_PROGRESS":
        return "The case is not in processing."
    changed = []
    # Both are recorded against the CURRENT application stage — a work permit
    # applied for after a business visa is its own application with its own
    # reference (owner 2026-08-18).
    if "portal_ref" in data and case.stage in APPLICATION_STAGES:
        ref = (data.get("portal_ref") or "").strip()
        if not ref:
            return "The portal reference cannot be blanked out."
        set_portal(case, case.stage, ref=ref)
        changed.append("portal_ref")
    if "portal_status" in data and case.stage in APPLICATION_STAGES:
        ps = (data.get("portal_status") or "").upper()
        if ps not in ("SUBMITTED", "ADDITIONAL_INFO", "APPROVED", "REJECTED"):
            return "Invalid portal status."
        if ps != "SUBMITTED" and not portal_for(case, case.stage)["ref"]:
            return ("Record the portal reference for this application before "
                    "setting its outcome.")
        set_portal(case, case.stage, status=ps)
        changed.append("portal_status")
    if "medical_result" in data and case.stage in MEDICAL_STAGES:
        mr = (data.get("medical_result") or "").upper()
        if mr not in ("PASS", "FAIL"):
            return "Medical result must be PASS or FAIL."
        case.medical_result = mr
        changed.append("medical_result")
        if mr == "FAIL":
            _notify_medical_fail(case)
    # Correct the arrival date after the fact — HR often records the arrival a
    # few days late, but salary counts from the day the worker actually landed,
    # so the original date must be enterable and editable. Moving it realigns
    # the medical window and the employee's join date + site allocation.
    if "arrived_date" in data and case.arrived_date:
        from datetime import date, timedelta
        try:
            ad = date.fromisoformat(str(data["arrived_date"]))
        except (ValueError, TypeError):
            return "Invalid arrival date."
        case.arrived_date = ad
        if not case.medical_result:
            case.medical_due = ad + timedelta(days=14)
        if case.employee_id:
            _realign_join_date(case, ad)
        case.medical_alert = ""            # window moved — let clocks re-alert
        changed.append("arrived_date")
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
    recips = list(notify._role_users("HO_HR")) + doc.site.current_pms()
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


# A fee PYR in one of these states is dead — it no longer counts as "the fee for
# this stage", so HR can raise a fresh one after a wrong PYR was cancelled,
# returned-then-cancelled, or voided (owner 2026-08-04).
_DEAD_PYR = ("CANCELLED", "REJECTED", "VOID")


def _stage_fees(case, stage):
    return (case.fees.filter(stage=stage).select_related("document")
            .order_by("-id"))


def active_fee_for(case, stage):
    """The live fee PYR for a stage, if any — ignoring cancelled/rejected/voided
    attempts so a fresh PYR can be raised (or the stage waived) after a wrong one
    is scrapped. Drives the raise/pay/advance gates."""
    for fee in _stage_fees(case, stage):
        if fee.document.status not in _DEAD_PYR:
            return fee
    return None


def fee_for(case, stage):
    """The fee PYR to display for a stage: the live one if there is one, else the
    most recent attempt (e.g. a cancelled one) so its status stays visible."""
    fees = list(_stage_fees(case, stage))
    for fee in fees:
        if fee.document.status not in _DEAD_PYR:
            return fee
    return fees[0] if fees else None


def _att_ref(att):
    return {"id": att.id, "name": att.file_name} if att else None


# ---- stage documents (Task B) --------------------------------------------

# Uploadable documents, each anchored to the stage it belongs to. A slot shows
# once its anchor stage is in the case's sequence AND reached. Fee-linked slots
# (fee_stage set) also surface Finance's payment slip off the fee PYR. The BV→WP
# conversion means a business-visa case also gets ENTRY_PASS / DEPOSIT_RECEIPT.
DOC_SLOTS = [
    {"key": "ENTRY_PASS", "label": "Work Permit Entry Pass",
     "anchor": "WP_APPROVED", "fee_stage": None},
    {"key": "DEPOSIT_RECEIPT", "label": "Deposit receipt",
     "anchor": "WP_DEPOSIT", "fee_stage": "WP_DEPOSIT"},
    {"key": "WP_TICKET_DOC", "label": "Air ticket",
     "anchor": "WP_TICKET", "fee_stage": "WP_TICKET"},
    {"key": "BV_CERTIFICATE", "label": "Business Visa Certificate",
     "anchor": "BV_APPROVED", "fee_stage": None},
    {"key": "INSURANCE_POLICY", "label": "Insurance policy",
     "anchor": "BV_INSURANCE", "fee_stage": "BV_INSURANCE"},
    {"key": "VISA_FEE_RECEIPT", "label": "Visa fee receipt",
     "anchor": "BV_VISA_FEE", "fee_stage": "BV_VISA_FEE"},
    {"key": "BV_TICKET_DOC", "label": "Air ticket",
     "anchor": "BV_TICKET", "fee_stage": "BV_TICKET"},
]
_SLOT_BY_KEY = {s["key"]: s for s in DOC_SLOTS}


def _slot_reached(case, seq, idx, slot):
    a = slot["anchor"]
    return a in seq and idx >= seq.index(a)


def documents_list(case):
    """Every stage-document slot the case has reached, in workflow order, each
    with its uploaded file (if any) and the Finance payment slip for fee slots."""
    seq = sequence(case)
    idx = seq.index(case.stage) if case.stage in seq else -1
    uploaded = {d.slot: d for d in
                case.documents.select_related("attachment")}
    out = []
    slots = [s for s in DOC_SLOTS if _slot_reached(case, seq, idx, s)]
    slots.sort(key=lambda s: seq.index(s["anchor"]))
    for s in slots:
        row = {"slot": s["key"], "label": s["label"], "anchor": s["anchor"],
               "anchor_label": STAGE_LABEL.get(s["anchor"], s["anchor"]),
               "doc": _att_ref(uploaded[s["key"]].attachment)
               if s["key"] in uploaded else None,
               "pyr_ref": None, "pyr_status": None, "paid": False, "slip": None}
        if s["fee_stage"]:
            fee = fee_for(case, s["fee_stage"])
            if fee:
                row["pyr_ref"] = fee.document.ref
                row["pyr_status"] = fee.document.status
                row["paid"] = fee.document.status == "PAID"
                slip = (fee.document.attachments.filter(kind="PAYMENT_SLIP")
                        .order_by("id").last())
                row["slip"] = _att_ref(slip)
        out.append(row)
    return out


def upload_document(case, slot_key, upload, actor):
    """HR attaches (or replaces) the document for a stage slot."""
    from .models import Attachment, OnboardingDocument
    if actor.role not in PROCESS_ROLES:
        return None, "Only HR uploads onboarding documents."
    slot = _SLOT_BY_KEY.get(slot_key)
    if slot is None:
        return None, "Unknown document type."
    seq = sequence(case)
    idx = seq.index(case.stage) if case.stage in seq else -1
    if not _slot_reached(case, seq, idx, slot):
        return None, "The case hasn't reached this stage yet."
    if upload is None:
        return None, "Attach a file."
    doc = case.document
    att = Attachment.objects.create(
        document=doc, revision=doc.current_revision, kind="EVIDENCE",
        file=upload, file_name=upload.name,
        content_type=upload.content_type or "", size_bytes=upload.size,
        caption=slot["label"], uploaded_by=actor)
    existing = case.documents.filter(slot=slot_key).first()
    old_att = existing.attachment if existing else None
    if existing:
        existing.attachment = att
        existing.created_by = actor
        existing.save(update_fields=["attachment", "created_by"])
    else:
        OnboardingDocument.objects.create(case=case, slot=slot_key,
                                          attachment=att, created_by=actor)
    if old_att:
        old_att.delete()
    audit("document", doc.id, "OBR_STAGE_DOC", actor=actor,
          detail={"slot": slot_key, "att": att.id})
    return att, None


def case_attachment(case, att_id):
    """An attachment the case may expose for download — one on the OBR itself,
    or a payment slip on one of its fee PYRs. Returns None otherwise."""
    from .models import Attachment
    att = Attachment.objects.filter(pk=att_id).select_related("document").first()
    if att is None or not att.file:
        return None
    if att.document_id == case.document_id:
        return att
    if case.fees.filter(document_id=att.document_id).exists():
        return att
    return None


# The supplier invoice each fee PYR should carry, so Finance has the bill.
INVOICE_LABEL = {
    "WP_DEPOSIT": "Deposit fee invoice",
    "WP_TICKET": "Air ticket invoice",
    "BV_INSURANCE": "Insurance company invoice",
    "BV_VISA_FEE": "Visa payment invoice",
    "BV_TICKET": "Air ticket invoice",
}


def _build_fee_pyr(case, stage, label, amount, payee, actor, invoice=None,
                   refundable=False, invoice_label="Invoice"):
    """Shared builder: draft + submit a purpose-coded fee PYR, link an
    OnboardingFee, and attach the supplier invoice. Returns (pyr, err). Must be
    called with validated inputs."""
    from django.db import transaction
    from .models import (Attachment, CostHead, Document, DocumentRevision,
                         OnboardingFee)
    from .payments import _set_status, create_payment_request
    doc = case.document
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
            "has_supporting_doc": bool(invoice is not None),
        }, actor)
        if err:
            transaction.set_rollback(True)
            return None, err
        # Onboarding fees carry NO approval layer — not the site PM and not the
        # Director. A recruitment cost, not a site spend; it clears straight to
        # Finance (owner 2026-08-05, revised from the earlier Director step).
        # Same end state as a CENTRAL/FINANCE request: DIRECTOR_APPROVED = ready
        # for the payment voucher.
        pr.origin = "ONBOARDING"
        pr.save(update_fields=["origin"])
        if refundable:                          # deposit posts nothing
            pr.is_capitalized = True
            pr.save(update_fields=["is_capitalized"])
        if invoice is not None:                 # the supplier invoice for Finance
            Attachment.objects.create(
                document=pyr, revision=rev, kind="QUOTATION",
                file=invoice, file_name=invoice.name,
                content_type=getattr(invoice, "content_type", "") or "",
                size_bytes=getattr(invoice, "size", 0),
                caption=f"{invoice_label} — {label}", uploaded_by=actor)
            pr.has_supporting_doc = True
            pr.save(update_fields=["has_supporting_doc"])
        # One fee tracker per (case, stage). If a prior attempt was cancelled/
        # voided the raise gate has already cleared it, so repoint the tracker at
        # the fresh PYR (the old Document stays for the audit trail).
        OnboardingFee.objects.update_or_create(
            case=case, stage=stage,
            defaults={"document": pyr, "refundable": refundable})
        _set_status(pyr, "SUBMITTED", "SUBMIT", actor,
                    f"{label} — onboarding {doc.ref}")
        # No PM / Director step — clear straight to Finance's payment voucher.
        _set_status(pyr, "DIRECTOR_APPROVED", "CLEAR_TO_VOUCHER", actor,
                    "Onboarding fee — no approval step; cleared to Finance")
    return pyr, None


def raise_fee(case, data, actor, invoice=None):
    """HR raises the fee PYR for the case's current payment stage, optionally
    attaching the supplier invoice for Finance. It rides the normal PYR approval
    → voucher → paid chain; the case can't advance until it's paid."""
    if actor.role not in PROCESS_ROLES:
        return None, "Only HR raises an onboarding fee."
    doc = case.document
    if doc.status != "IN_PROGRESS":
        return None, "The case is not in processing."
    stage = case.stage
    if stage not in PAYMENT_STAGES:
        return None, "This stage has no fee."
    if active_fee_for(case, stage) is not None:
        return None, "A fee PYR has already been raised for this stage."
    amount = _dec(data.get("amount"))
    if amount is None or amount <= Decimal("0"):
        return None, "Enter the fee amount."
    payee = (data.get("payee") or "").strip()
    if not payee:
        return None, "Enter the payee."
    label, refundable = FEE_META[stage]
    pyr, err = _build_fee_pyr(
        case, stage, label, amount, payee, actor, invoice=invoice,
        refundable=refundable, invoice_label=INVOICE_LABEL.get(stage, "Invoice"))
    if err:
        return None, err
    audit("document", doc.id, "OBR_FEE_RAISED", actor=actor,
          detail={"stage": stage, "pyr": pyr.ref, "amount": str(amount)})
    return pyr, None


def extend_visa(case, data, actor, invoice=None):
    """Extend a business visa before it lapses: push the expiry forward and raise
    an extension-fee PYR (invoice attachable). Keeps the worker legal on site
    until the job is done."""
    from datetime import date
    if actor.role not in PROCESS_ROLES:
        return None, "Only HR extends a visa."
    doc = case.document
    if doc.status != "IN_PROGRESS":
        return None, "The case is not in processing."
    if case.route != "BV" or not case.bv_expiry:
        return None, "Only an arrived business-visa case can be extended."
    raw = data.get("new_expiry")
    try:
        new_expiry = date.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None, "Enter the new visa expiry date."
    if new_expiry <= case.bv_expiry:
        return None, "The new expiry must be later than the current one."
    amount = _dec(data.get("amount"))
    if amount is None or amount <= Decimal("0"):
        return None, "Enter the extension fee amount."
    payee = (data.get("payee") or "").strip()
    if not payee:
        return None, "Enter the payee."
    n = case.bv_renewals + 1
    stage = f"BV_EXT_{n}"
    pyr, err = _build_fee_pyr(
        case, stage, f"Business-visa extension #{n}", amount, payee, actor,
        invoice=invoice, invoice_label="Visa extension invoice")
    if err:
        return None, err
    case.bv_expiry = new_expiry
    case.bv_renewals = n
    case.bv_alert = ""                           # new window — let clocks re-alert
    case.save(update_fields=["bv_expiry", "bv_renewals", "bv_alert",
                             "updated_at"])
    audit("document", doc.id, "OBR_VISA_EXTENDED", actor=actor,
          detail={"new_expiry": str(new_expiry), "pyr": pyr.ref})
    _stage_notify_text(case, f"business visa extended to {new_expiry:%d %b %Y}")
    return pyr, None


def close_departed(case, data, actor):
    """Close a subcontract worker's case when they leave the country — the case
    is done, the subcontract worker deactivated and their site allocation
    closed."""
    from datetime import date
    if actor.role not in PROCESS_ROLES:
        return "Only HR closes an onboarding case."
    doc = case.document
    if doc.status != "IN_PROGRESS":
        return "The case is not in processing."
    if not _is_subcontract(case):
        return "Only a subcontract case is closed on departure."
    raw = data.get("departed_date")
    departed = timezone.localdate()
    if raw:
        try:
            departed = date.fromisoformat(str(raw))
        except (ValueError, TypeError):
            return "Invalid departure date."
    _set_status(doc, "COMPLETED", "COMPLETE", actor,
                comment=f"Departed {departed:%d %b %Y}")
    emp = case.employee
    if emp:
        emp.is_active = False
        emp.save(update_fields=["is_active", "updated_at"])
        alloc = emp.site_allocations.filter(to_date__isnull=True).first()
        if alloc:
            alloc.to_date = departed
            alloc.save(update_fields=["to_date"])
    audit("document", doc.id, "OBR_DEPARTED", actor=actor,
          detail={"departed": str(departed),
                  "emp_no": emp.emp_no if emp else ""})
    _stage_notify_text(case, f"worker departed {departed:%d %b %Y}; case closed")
    return None


def _stage_notify_text(case, msg):
    from . import notify
    doc = case.document
    recips = set(notify._role_users("HO_HR"))
    recips.update(doc.site.current_pms())
    for u in recips:
        notify.notify_user(u, f"Onboarding {doc.ref} — {msg}",
                           body=f"{case.full_name} · {doc.site.code}",
                           doc=doc, category="alert")


def on_fee_settled(pyr_doc, actor):
    """The money for this stage is committed — authorised or paid."""
    return on_fee_paid(pyr_doc, actor)


def on_fee_paid(pyr_doc, actor):
    """A fee PYR has been paid — clear the gate it was holding.

    It used to only notify HR, so a paid case sat at "insurance pending" or
    "visa fee pending" until somebody read the message and pressed Advance.
    Cases were getting stuck at payment for weeks with the money long gone
    (owner 2026-08-16).

    Leaving a payment stage requires nothing but the payment, so the case is
    moved on here. If the NEXT stage needs something from HR — an arrival
    date, for instance — the advance declines and the case waits, exactly as
    before; it is never forced past a gate.
    """
    fee = getattr(pyr_doc, "onboarding_fee", None)
    if fee is None:
        return
    from . import notify
    case = fee.case
    doc = case.document
    label = FEE_META.get(fee.stage, (fee.stage,))[0]

    moved = False
    if doc.status == "IN_PROGRESS" and case.stage == fee.stage:
        err = advance_stage(case, {}, actor, system=True)
        if err is None:
            moved = True
            case.refresh_from_db()
            audit("document", doc.id, "OBR_ADVANCED_ON_PAYMENT", actor=actor,
                  detail={"ref": doc.ref, "paid": pyr_doc.ref,
                          "stage": fee.stage, "now": case.stage})
        else:
            audit("document", doc.id, "OBR_PAYMENT_GATE_CLEAR", actor=actor,
                  detail={"ref": doc.ref, "paid": pyr_doc.ref,
                          "stage": fee.stage, "waiting_on": err})

    body = (f"{case.full_name} · {doc.site.code} — "
            + (f"now at {STAGE_LABEL.get(case.stage, case.stage)}" if moved
               else "the case can now advance"))
    for u in notify._role_users("HO_HR"):
        notify.notify_user(u, f"Onboarding {doc.ref} — {label} paid",
                           body=body, category="alert")


# ---- official letters (Phase 4) ------------------------------------------

# kind -> {stage, human title, sign}. LOA is issued at the appointment stage
# (WP track, and the BV→WP conversion); SPL at the BV sponsor stage. AC (the
# official Appointment Confirmation) has no stage gate — it is a lean, early
# appointment offer for any recruitment case, signed by a signatory (`sign`).
LETTER_META = {
    "LOA": {"stage": "WP_APPOINTMENT", "title": "Letter of Appointment",
            "sign": True},
    "SPL": {"stage": "BV_SPONSOR", "title": "Sponsor Letter", "sign": True},
    "AC": {"stage": None, "title": "Appointment Confirmation", "sign": True},
    # The Maldives Immigration IM30 visa form — a filled PDF overlay, not an
    # HTML letter — submitted with the LOA for Sri-Lankan work-permit cases.
    "IM30": {"stage": None, "title": "Visa Form (IM30)", "im30": True},
    # The employment contract the Sri Lankan Embassy attests (their format on
    # our letterhead) — generated for every Sri Lankan once the work permit is
    # approved, ahead of the embassy-endorsement stage (owner 2026-08-09).
    "EA": {"stage": "WP_APPROVED",
           "title": "Employment Agreement (Embassy Attestation)", "sign": True},
}
_QUOTA_LABEL = {"SKILLED": "Skilled", "UNSKILLED": "Unskilled", "STAFF": "Staff"}
# Letters that print the salary in the body — see `_salary_str` below.
PAY_BEARING_LETTERS = ("LOA", "AC", "EA")


def letter_available(case, kind):
    """A letter can be generated once the case is in processing and has reached
    the stage the letter belongs to (so it stays available for regeneration)."""
    meta = LETTER_META.get(kind)
    if not meta or case.document.status != "IN_PROGRESS":
        return False
    # HARD GATE (owner 2026-08-11): nothing is generated before the signatory
    # signs the case off. Previously an unsigned letter rendered as a DRAFT
    # copy — staff issued those to the government portal anyway, so the draft
    # path is gone: every generated document now carries the signature + seal
    # by construction.
    if case.signatory_approved_at is None:
        return False
    # The Appointment Confirmation is an early, pre-travel offer for recruitment
    # cases — available throughout processing (any route), but NOT for a
    # subcontract worker (no appointment letter, no salary — owner 2026-08-04).
    if kind == "AC":
        return not _is_subcontract(case)
    # The IM30 visa form accompanies the LOA on the work-permit application, for
    # Sri-Lankan candidates only (owner 2026-08-05). Available throughout a case
    # that has a WP application in its path (a straight WP, or a recruitment BV
    # that converts) — never a subcontract worker.
    if kind == "IM30":
        return (not _is_subcontract(case) and _is_sri_lankan(case)
                and "WP_APPLICATION" in sequence(case))
    # The embassy-attestation agreement is a Sri Lankan requirement only —
    # beyond that it follows the normal stage gate (WP approved onward).
    if kind == "EA" and not (_is_sri_lankan(case)
                             and not _is_subcontract(case)):
        return False
    seq = sequence(case)
    if meta["stage"] not in seq or case.stage not in seq:
        return False
    return seq.index(case.stage) >= seq.index(meta["stage"])


def _is_sri_lankan(case):
    return "sri" in (case.nationality or "").lower()


def _fmt_date(d):
    return d.strftime("%d %b %Y") if d else ""


def _fmt_slash(d):
    """DD/MM/YYYY — the IM30 form's date-box layout."""
    return d.strftime("%d/%m/%Y") if d else ""


def _salutation(case):
    """A courteous 'Mr. Rodrigo' / 'Ms. X' from gender + the last name; falls
    back to the full name when gender or name is missing."""
    honor = {"Male": "Mr.", "Female": "Ms."}.get(case.gender or "", "")
    parts = (case.full_name or "").split()
    last = parts[-1] if parts else ""
    return f"{honor} {last}".strip() or (case.full_name or "")


def _salary_str(case):
    if case.proposed_salary is None:
        return ""
    cur = case.currency or "MVR"
    return f"{cur} {case.proposed_salary:,.2f}"


def _allowances_for_letter(case):
    """The case's allowances formatted for the appointment letter — empty when
    none, so the letter shows the rows only if applicable."""
    out = []
    for a in case.allowances or []:
        amt = _dec(a.get("amount"))
        cur = a.get("currency") or case.currency or "MVR"   # legacy rows: case
        if amt is not None:
            out.append({"label": a.get("type", ""),
                        "amount": f"{cur} {amt:,.2f}"})
    return out


def _default_signatory():
    """The company signatory who signs correspondence — a SIGNATORY if set,
    else the Director. Only a draft placeholder: the signed letter carries
    whoever actually signs the case off (their own designation)."""
    from . import notify
    for role, title in (("SIGNATORY", "Authorised Signatory"),
                        ("DIRECTOR", "Director")):
        u = next(iter(notify._role_users(role)), None)
        if u:
            return u.full_name, (u.designation or title)
    return "", "Director"


def letter_defaults(case, kind):
    """Prefilled merge fields for a letter, from the case + company. Fields the
    owner marked HR-editable (work site, accommodation, addressee, …) default
    blank for HR to complete at generation."""
    sig_name, sig_title = _default_signatory()
    common = {
        "passport_no": case.passport_no or "",
        "nationality": case.nationality or "",
        "dob": _fmt_date(case.date_of_birth),
        "signatory_name": sig_name,
        "signatory_designation": sig_title,
    }
    if kind == "AC":
        return {
            **common,
            "candidate_name": case.full_name or "",
            "salutation": _salutation(case),
            "position": case.trade_designation or "",
            "employment_status": "Full-time",
            "work_site": "Malé, Republic of Maldives",
            "basic_salary": _salary_str(case),
            "allowances": _allowances_for_letter(case),
            "salary_payment": "On or before the 10th day of the following month",
            "working_hours": "8 hours per day, 6 days per week",
            "contract_duration": "2 years",
            "commencement": "On the date of arrival in the Maldives",
            # The confirmation is signed by a company signatory, not the Director.
            "signatory_designation": "Managing Director",
        }
    if kind == "IM30":
        from .pdf import company_info
        co = company_info()
        work_site = co["legal_name"]
        if co.get("tin"):
            work_site += f" ({co['tin']})"
        return {
            "port_of_entry": "Velana International Airport",
            "name": case.full_name or "",
            "dob": _fmt_slash(case.date_of_birth),
            "gender": case.gender or "",
            "nationality": case.nationality or "",
            "marital_status": case.marital_status or "",
            "passport_no": case.passport_no or "",
            "expiry": _fmt_slash(case.passport_expiry),
            "old_passport_no": case.old_passport_no or "",
            "purpose_of_stay": "Employment",
            "work_site": work_site,
            "home_address": case.permanent_address or "",
            "email": "",
            "mobile": case.mobile or "",
            "company": co["legal_name"],
            "reg_no": co.get("reg_no", ""),
            "signee": co.get("signee_name", ""),
            "sponsor_mobile": co.get("signee_mobile", ""),
            "designation": co.get("signee_designation", ""),
            "sponsor_date": _fmt_slash(timezone.localdate()),
        }
    if kind == "EA":
        from .pdf import company_info
        co = company_info()
        return {
            **common,
            "employee_name": case.full_name or "",
            "employee_address": case.permanent_address or "",
            "passport_issue_date": "",           # not on the case — HR enters
            "passport_issue_place": "Sri Lanka",
            "passport_profession": "None",
            "employment_site": f"{co['legal_name']}, {co.get('address', '')}",
            "classification": _QUOTA_LABEL.get(case.category, ""),
            "position": case.trade_designation or "",
            "basic_pay": _salary_str(case),
            "hours_per_day": "8 hours",
            "hours_per_week": "48 hours",
            "ot_regular": "",                    # e.g. "USD 1.50 per hour"
            "ot_holiday": "",
            "vacation_days": "30 days",
            "sick_days": "30 days",
            "contract_duration": ("2 years from the date of arrival in the "
                                  "country of employment; renewable at the "
                                  "option of both parties"),
            "other_benefits": "Performance-based incentives",
        }
    if kind == "LOA":
        return {
            **common,
            "employee_name": case.full_name or "",
            "gender": case.gender or "",
            "permanent_address": case.permanent_address or "",
            "emergency_contact": case.emergency_contact or "",
            "employment_status": "Full-time",
            "job_title": case.trade_designation or "",
            "quota_work_type": _QUOTA_LABEL.get(case.category, ""),
            "basic_salary": _salary_str(case),
            "allowances": _allowances_for_letter(case),
            "work_site": "",
            "job_description": case.trade_designation or "",
            "contract_duration": "2 years",
            "working_hours": "8 hours per day, 6 days per week",
        }
    return {
        **common,
        "candidate_name": case.full_name or "",
        "mobile": case.mobile or "",
        "role": case.trade_designation or "",
        "duration": "90 days",
        "accommodation": "",
        "local_contact": "",
        "project_site": "",
        "addressee_line_1": "",
        "addressee_line_2": "",
    }


def generate_letter(case, kind, overrides, actor):
    """HR generates an official letter for the case: prefill from the case,
    overlay HR's edits, allocate a global LOA-/SPL- ref, render the PDF and store
    it as a case attachment. Regenerating keeps prior copies and bumps version."""
    from .models import OnboardingLetter
    if actor.role not in PROCESS_ROLES:
        return None, "Only HR generates onboarding letters."
    if kind not in LETTER_META:
        return None, "Unknown letter type."
    if not letter_available(case, kind):
        return None, (f"The {LETTER_META[kind]['title']} isn't available at "
                      "this stage.")
    defaults = letter_defaults(case, kind)
    # `allowances` is a structured list derived from the case, never an editable
    # text field — keep HR's text overrides from clobbering it.
    clean = {k: str(v) for k, v in (overrides or {}).items()
             if k in defaults and v is not None
             # allowances is structured; the signatory identity comes from the
             # case sign-off, never from HR's form
             and k not in ("allowances", "signatory_name",
                           "signatory_designation")}
    fields = {**defaults, **clean}
    issue_date = timezone.localdate().strftime("%d %b %Y")
    # Every letter is stamped with the signatory's signature + company seal ONCE
    # the case has been signed off by a signatory (owner 2026-08-08). Before that
    # it renders as an unstamped DRAFT; the sign-off re-renders it as official.
    signed = case.signatory_approved_at is not None
    with transaction.atomic():
        ref = next_ref(kind, None)
        if LETTER_META[kind].get("im30"):
            att = _render_im30(case, ref, fields)
        else:
            att = _render_letter(case, kind, ref, fields, issue_date, signed)
        if att is None:
            transaction.set_rollback(True)
            return None, "The PDF engine is unavailable in this environment."
        version = case.letters.filter(kind=kind).count() + 1
        letter = OnboardingLetter.objects.create(
            case=case, kind=kind, ref=ref, attachment=att, fields=fields,
            version=version, created_by=actor,
            status="SIGNED" if signed else "PENDING",
            # a letter produced after the sign-off carries that signatory on
            # its face — record who it was (owner 2026-08-11)
            approved_by=(case.signatory_approved_by if signed else None),
            approved_at=(case.signatory_approved_at if signed else None))
    audit("document", case.document_id, "OBR_LETTER", actor=actor,
          detail={"kind": kind, "ref": ref, "version": version})
    if not signed:
        _notify_signatories(case)
    return letter, None


def _render_letter(case, kind, ref, fields, issue_date, signed):
    """Render one letter — stamped with the signatory signature + company seal
    when the case is signed off, else an unsigned DRAFT."""
    from . import pdf
    stamp_src = _signatory_stamp_data_uri() if signed else ""
    seal_src = pdf.company_stamp_data_uri() if signed else ""
    fld = dict(fields)
    if signed and case.signatory_approved_by_id:
        # The letter carries whoever actually signed the case off — name AND
        # title come from that approval, not from the generation form. Title =
        # the user's own designation ("Managing Director" / "Director"), with
        # a role fallback when it isn't set.
        signer = case.signatory_approved_by
        fld["signatory_name"] = signer.full_name
        fld["signatory_designation"] = (
            signer.designation
            or ("Director" if signer.role == "DIRECTOR"
                else "Authorised Signatory"))
    return pdf.render_onboarding_letter(
        case.document, kind, ref, fld, issue_date,
        stamp_src=stamp_src, seal_src=seal_src, draft=not signed)


def sign_off_case(case, actor):
    """A signatory signs the whole case off ONCE — after this every letter it
    has (and any generated later) carries the signatory signature + company
    seal. Re-renders existing letters as the official stamped copies."""
    if actor.role not in ("SIGNATORY", "ADMIN"):
        return None, "Only a signatory can sign off an onboarding case."
    if case.document.status != "IN_PROGRESS":
        return None, "The case must be approved and in processing first."
    if case.signatory_approved_at is not None:
        return None, "This case is already signed off."
    if not getattr(actor, "stamp", None):
        return None, "Upload your approval stamp before signing off."
    issue_date = timezone.localdate().strftime("%d %b %Y")
    with transaction.atomic():
        case.signatory_approved_by = actor
        case.signatory_approved_at = timezone.now()
        case.save(update_fields=["signatory_approved_by",
                                 "signatory_approved_at", "updated_at"])
        # re-render each existing (non-IM30) letter as the stamped official copy
        for letter in case.letters.exclude(kind="IM30"):
            old = letter.attachment
            att = _render_letter(case, letter.kind, letter.ref,
                                 letter.fields or {}, issue_date, signed=True)
            if att is None:
                transaction.set_rollback(True)
                return None, "The PDF engine is unavailable in this environment."
            fld = dict(letter.fields or {})
            fld["signatory_name"] = actor.full_name
            letter.attachment = att
            letter.fields = fld
            letter.status = "SIGNED"
            letter.approved_by = actor
            letter.approved_at = case.signatory_approved_at
            letter.save(update_fields=["attachment", "fields", "status",
                                       "approved_by", "approved_at"])
            if old:
                old.delete()
    audit("document", case.document_id, "OBR_CASE_SIGNED_OFF", actor=actor,
          detail={"letters": case.letters.exclude(kind="IM30").count()})
    _notify_case_signed_off(case)
    return case, None


def _signatory_stamp_bytes():
    """The approval stamp of the first signatory who has uploaded one — reused
    on the IM30 form and the LOA without asking them to re-sign (owner
    2026-08-05). None when no signatory has a stamp yet."""
    from . import notify
    for u in notify._role_users("SIGNATORY"):
        f = getattr(u, "stamp", None)
        if f:
            try:
                with f.open("rb") as fh:
                    return fh.read()
            except Exception:
                continue
    return None


def _signatory_stamp_data_uri():
    from .pdf import _img_data_uri
    return _img_data_uri(_signatory_stamp_bytes())


def _render_im30(case, ref, fields):
    """Overlay the IM30 visa form and archive it as a case attachment, stamped
    with the signatory's mark + the company seal."""
    from . import im30, pdf
    pdf_bytes = im30.render_bytes(
        fields, signature=_signatory_stamp_bytes(),
        seal=pdf.company_stamp_bytes())
    return pdf.store_generated_pdf(case.document, f"{ref}.pdf", pdf_bytes)


def _notify_signatories(case):
    """Ping every signatory that an onboarding case is waiting for their
    sign-off (which stamps all its letters)."""
    from . import notify
    for u in notify._role_users("SIGNATORY"):
        notify.notify_user(
            u, f"Onboarding case to sign off — {case.full_name}",
            f"{case.document.ref}'s letters are ready for your signature "
            "and company stamp.",
            doc=case.document, category="approval")


def _notify_case_signed_off(case):
    from . import notify
    recipients = set(notify._role_users("HO_HR"))
    if case.document.created_by_id:
        recipients.add(case.document.created_by)
    who = case.signatory_approved_by.full_name \
        if case.signatory_approved_by_id else "a signatory"
    for u in recipients:
        notify.notify_user(
            u, f"Onboarding case signed off — {case.full_name}",
            f"{case.document.ref}'s letters have been signed + stamped by "
            f"{who}.", doc=case.document, category="info")


def _file_data_uri(filefield):
    """A data: URI for a stored image (stamp) — S3- and local-safe, so WeasyPrint
    embeds it without a filesystem path."""
    import base64
    import mimetypes
    try:
        with filefield.open("rb") as fh:
            raw = fh.read()
    except Exception:
        return ""
    mime = mimetypes.guess_type(filefield.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def _letter_dict(letter):
    return {
        "id": letter.id, "kind": letter.kind, "ref": letter.ref,
        "version": letter.version, "created_at": letter.created_at,
        "title": LETTER_META.get(letter.kind, {}).get("title", letter.kind),
        "created_by": (letter.created_by.full_name
                       if letter.created_by_id else ""),
        "download": (f"/onboarding/{letter.case_id}/letters/{letter.id}.pdf"
                     if letter.attachment_id else None),
        "status": letter.status,
        "needs_sign": bool(LETTER_META.get(letter.kind, {}).get("sign")),
        "approved_by": (letter.approved_by.full_name
                        if letter.approved_by_id else ""),
        "approved_at": letter.approved_at,
    }


def cases_to_sign_off(user):
    """Onboarding cases awaiting a signatory's sign-off — the signatory's
    limited queue (candidate + the appointment terms they are approving, NOT
    the full case with its sensitive documents).

    Every in-processing, unsigned case appears (owner 2026-08-11). It used to
    list only cases that already had DRAFT letters, which no longer works now
    that generation is gated behind the sign-off — and that ordering was the
    wrong way round anyway: the signatory approves the appointment, then the
    letters are produced from it, already stamped."""
    from .models import OnboardingCase
    if user.role not in ("SIGNATORY", "ADMIN"):
        return []
    qs = (OnboardingCase.objects.filter(
            document__status="IN_PROGRESS", signatory_approved_at__isnull=True)
          .distinct().select_related("document")
          .order_by("document__doc_date"))
    out = []
    for c in qs:
        # any letter already drafted under the old rule stays reviewable
        letters = [
            {"id": lt.id, "kind": lt.kind, "ref": lt.ref,
             "title": LETTER_META.get(lt.kind, {}).get("title", lt.kind),
             "draft": f"/onboarding/letters/{lt.id}/draft.pdf"}
            for lt in c.letters.exclude(kind="IM30").order_by("kind")]
        out.append({
            "case_id": c.document_id, "case_ref": c.document.ref,
            "candidate_name": c.full_name, "position": c.trade_designation,
            "nationality": c.nationality, "letters": letters,
            # the substance being approved — the LOA is generated from exactly
            # these fields, so reviewing them IS reviewing the letter
            "terms": {
                "route": c.get_route_display(),
                "site": c.document.site.code,
                "salary": (f"{c.currency or 'MVR'} {c.proposed_salary}"
                           if c.proposed_salary is not None else ""),
                "allowances": [f"{a.get('type')} {a.get('amount')}"
                               for a in (c.allowances or [])],
                "passport_no": c.passport_no,
            },
        })
    return out


def set_stamp(user, upload):
    """A signatory uploads (or replaces) their digital approval stamp."""
    if user.role not in ("SIGNATORY", "ADMIN"):
        return "Only a signatory keeps an approval stamp."
    if upload is None:
        return "Attach a stamp image."
    ctype = (getattr(upload, "content_type", "") or "").lower()
    if not ctype.startswith("image/"):
        return "The stamp must be an image (PNG or JPG)."
    try:                                     # reject a corrupt/unreadable image
        from PIL import Image
        Image.open(upload).verify()
        upload.seek(0)
    except Exception:
        return "The stamp image couldn't be read — try a PNG or JPG."
    if user.stamp:
        user.stamp.delete(save=False)
    user.stamp = upload
    user.save(update_fields=["stamp"])
    return None


# ---- countdown clocks + alerts (Phase 5) ---------------------------------

# Most-urgent → least, so a re-run only fires when the level has worsened.
_MED_ORDER = {"": 0, "T7": 1, "T3": 2, "OVERDUE": 3}
_BV_ORDER = {"": 0, "T14": 1, "T7": 2, "T3": 3, "OVERDUE": 4}
STALE_DAYS = 14


def _medical_level(days):
    if days < 0:
        return "OVERDUE"
    if days <= 3:
        return "T3"
    if days <= 7:
        return "T7"
    return None


def _bv_level(days):
    if days < 0:
        return "OVERDUE"
    if days <= 3:
        return "T3"
    if days <= 7:
        return "T7"
    if days <= 14:
        return "T14"
    return None


def _clock_recipients(case, escalate):
    from . import notify
    recips = set(notify._role_users("HO_HR"))
    recips.update(case.document.site.current_pms())
    if escalate:                                     # T-3 / overdue → the PD
        recips |= set(notify._role_users("DIRECTOR"))
    return recips


def _clock_notify(case, kind, level, days):
    from . import notify
    doc = case.document
    if kind == "medical":
        title = (f"Onboarding {doc.ref} — medical OVERDUE by {abs(days)} day(s)"
                 if level == "OVERDUE"
                 else f"Onboarding {doc.ref} — medical due in {days} day(s)")
        escalate = level == "OVERDUE"
    else:                                            # bv expiry
        title = (f"Onboarding {doc.ref} — BUSINESS VISA EXPIRED "
                 f"{abs(days)} day(s) ago" if level == "OVERDUE"
                 else f"Onboarding {doc.ref} — business visa expires in "
                      f"{days} day(s)")
        escalate = level in ("T3", "OVERDUE")
    body = f"{case.full_name} · {doc.site.code}"
    cat = "approval" if escalate else "alert"
    for u in _clock_recipients(case, escalate):
        notify.notify_user(u, title, body=body, doc=doc, category=cat)


def _stale_digest(cases, today):
    """One nudge per HR user listing pre-arrival cases with no movement for
    STALE_DAYS; deduped so a daily run sends at most one digest per day."""
    if not cases:
        return False
    from . import notify
    from .models import Notification
    title = "Onboarding — stale cases need attention"
    body = "; ".join(
        f"{c.document.ref} · {c.full_name} · {c.document.site.code} "
        f"(idle {(today - c.updated_at.date()).days}d)" for c in cases)
    sent = False
    for u in notify._role_users("HO_HR"):
        if Notification.objects.filter(recipient=u, title=title,
                                       created_at__date=today).exists():
            continue
        notify.notify_user(u, title, body=body, category="alert")
        sent = True
    return sent


def run_clocks(today=None):
    """Daily countdown alerts across all live cases: the medical deadline, the
    business-visa expiry (the module's headline risk), and a stale-case digest.
    Idempotent — each threshold fires once, tracked on the case."""
    from .models import OnboardingCase
    today = today or timezone.localdate()
    med = bv = 0
    stale = []
    for case in (OnboardingCase.objects
                 .filter(document__status="IN_PROGRESS")
                 .select_related("document__site")):
        # medical countdown — only after arrival, before the result is in
        if case.medical_due and not case.medical_result:
            days = (case.medical_due - today).days
            level = _medical_level(days)
            if level and _MED_ORDER[level] > _MED_ORDER.get(
                    case.medical_alert, 0):
                _clock_notify(case, "medical", level, days)
                case.medical_alert = level
                case.save(update_fields=["medical_alert", "updated_at"])
                med += 1
        # BV expiry countdown — while on a business visa, before WP is issued
        if case.route == "BV" and case.bv_expiry and case.stage != "WP_ISSUED":
            days = (case.bv_expiry - today).days
            level = _bv_level(days)
            if level and _BV_ORDER[level] > _BV_ORDER.get(case.bv_alert, 0):
                _clock_notify(case, "bv", level, days)
                case.bv_alert = level
                case.save(update_fields=["bv_alert", "updated_at"])
                bv += 1
        # stale pre-arrival case
        if (not case.arrived_date and case.updated_at
                and (today - case.updated_at.date()).days >= STALE_DAYS):
            stale.append(case)
    digest = _stale_digest(stale, today)
    return {"medical": med, "bv": bv, "stale": len(stale),
            "digest_sent": digest}


# ---- business-visa register (owner 2026-08-09) ---------------------------

def bv_register():
    """Every business-visa person on one schedule, so HR watches the visa
    clocks without digging through onboarding cases. Three buckets:
    - in_country: arrived, on the BV clock — soonest expiry first
    - pipeline:   case open but not arrived yet (no clock running)
    - closed:     converted to a work permit, or the case ended
    """
    from .models import OnboardingCase
    today = timezone.localdate()
    rows = {"in_country": [], "pipeline": [], "closed": []}
    qs = (OnboardingCase.objects.filter(route="BV")
          .select_related("document__site", "subcontractor"))
    for c in qs:
        doc = c.document
        days = (c.bv_expiry - today).days if c.bv_expiry else None
        level = (None if days is None
                 else "EXPIRED" if days < 0
                 else "T3" if days <= 3
                 else "T7" if days <= 7
                 else "T14" if days <= 14 else "OK")
        row = {
            "case_id": doc.pk, "ref": doc.ref, "name": c.full_name,
            "passport_no": c.passport_no, "nationality": c.nationality,
            "site": doc.site.code if doc.site_id else "",
            "position": c.trade_designation,
            "purpose": c.bv_purpose or "",
            "subcontractor": (c.subcontractor.name
                              if c.subcontractor_id else ""),
            "arrived": c.arrived_date, "expiry": c.bv_expiry,
            "days_left": days, "level": level,
            "renewals": c.bv_renewals, "stage": c.stage,
            "doc_status": doc.status,
            "converted": c.stage == "WP_ISSUED",
        }
        if doc.status in TERMINAL or c.stage == "WP_ISSUED":
            rows["closed"].append(row)
        elif c.bv_expiry and c.arrived_date:
            rows["in_country"].append(row)
        else:
            rows["pipeline"].append(row)
    rows["in_country"].sort(key=lambda r: (r["expiry"], r["ref"]))
    rows["pipeline"].sort(key=lambda r: r["ref"])
    rows["closed"].sort(key=lambda r: r["ref"], reverse=True)
    rows["closed"] = rows["closed"][:50]
    rows["counts"] = {
        "in_country": len(rows["in_country"]),
        "expiring": sum(1 for r in rows["in_country"]
                        if r["level"] in ("T14", "T7", "T3")),
        "expired": sum(1 for r in rows["in_country"]
                       if r["level"] == "EXPIRED"),
        "pipeline": len(rows["pipeline"]),
    }
    return rows


# ---- employee handover (Phase 6) -----------------------------------------

def _handover_employee(case, actor):
    """Mobilise the candidate into the Employee DB on arrival (owner). A
    recruitment/WP case becomes a DIRECT (payroll) hire; a subcontract BV worker
    becomes a SUBCONTRACT worker — on the site's manpower list but never on
    payroll, linked to the chosen subcontractor. Idempotent."""
    from .models import Employee, EmployeeSiteAllocation
    if case.employee_id:
        return case.employee
    # Already on file: the man is coming back, or the case duplicates an
    # existing record. Either way, hand the case the record that already
    # holds his history rather than minting a second one (owner 2026-08-16).
    from .models import passport_holder
    held = passport_holder(case.passport_no)
    if held is not None:
        case.employee = held
        case.save(update_fields=["employee"])
        audit("employee", held.id, "ONBOARDING_LINKED_EXISTING", actor=actor,
              detail={"case": case.document.ref, "emp_no": held.emp_no,
                      "passport": (case.passport_no or "").strip(),
                      "why": "passport already on file — linked instead of "
                             "creating a second record"})
        return held
    join = case.arrived_date or timezone.localdate()
    sub = _is_subcontract(case)
    with transaction.atomic():
        n = int(next_ref("EMP", None).split("-")[1])
        emp = Employee.objects.create(
            emp_no=f"EMP-{n:04d}", full_name=case.full_name,
            passport_no=case.passport_no or "",
            nationality=case.nationality or "",
            date_of_birth=case.date_of_birth,
            job_category_id=case.job_category_id or None,
            basic_pay=None if sub else case.proposed_salary,
            currency=case.currency or "MVR",
            employment_type=Employee.EmploymentType.CONTRACT if sub
            else Employee.EmploymentType.PERMANENT,
            emergency_contact=case.emergency_contact or "",
            join_date=join, is_active=True,
            engagement_type=Employee.Engagement.SUBCONTRACT if sub
            else Employee.Engagement.DIRECT,
            subcontractor_id=case.subcontractor_id if sub else None)
        EmployeeSiteAllocation.objects.create(
            employee=emp, site=case.document.site, from_date=join)
        photo = _photo_att(case)                 # carry the passport photo over
        if photo and photo.file:
            from django.core.files.base import ContentFile
            try:
                emp.photo.save(photo.file_name or f"{emp.emp_no}.jpg",
                               ContentFile(photo.file.read()), save=True)
            except Exception:                    # pragma: no cover - storage
                pass
        case.employee = emp
        case.save(update_fields=["employee", "updated_at"])
    audit("employee", emp.id, "OBR_HANDOVER", actor=actor,
          detail={"obr": case.document.ref, "emp_no": emp.emp_no})
    return emp


def _realign_join_date(case, join):
    """A corrected arrival date moves when salary starts — carry it onto the
    employee's join date and the open site-allocation's from-date."""
    emp = case.employee
    if emp.join_date != join:
        emp.join_date = join
        emp.save(update_fields=["join_date", "updated_at"])
    alloc = (emp.site_allocations.filter(to_date__isnull=True)
             .order_by("from_date").first())
    if alloc and alloc.from_date != join:
        alloc.from_date = join
        alloc.save(update_fields=["from_date"])


def _notify_handover(case, emp):
    if not emp:
        return
    from . import notify
    doc = case.document
    join = emp.join_date
    recips = set(notify._role_users("HO_HR"))
    recips.update(doc.site.current_pms())
    sub = emp.engagement_type == "SUBCONTRACT"
    kind = "subcontract worker (no payroll)" if sub else "DIRECT hire"
    for u in recips:
        notify.notify_user(
            u, f"Onboarding {doc.ref} — {emp.emp_no} on site",
            body=f"{emp.full_name} · {doc.site.code} — added to the site "
                 f"manpower list as a {kind} from {join:%d %b %Y}",
            doc=doc, category="alert")


# ---- serialisation -------------------------------------------------------

def checklist(case):
    kinds = [k for k, _, _ in CHECKLIST_DOCS]
    atts = {}
    for a in case.document.attachments.filter(kind__in=kinds).order_by("id"):
        atts[a.kind] = a                 # last upload of each kind wins
    return [{"kind": k, "label": label, "required": req,
             "present": k in atts,
             "att_id": atts[k].id if k in atts else None}
            for k, label, req in CHECKLIST_DOCS]


def _photo_att(case):
    return (case.document.attachments.filter(kind="PASSPORT_PHOTO")
            .order_by("id").last())


def stage_view(case):
    """The ordered stage stepper for the case + what the next advance needs."""
    seq = sequence(case)
    idx = seq.index(case.stage) if case.stage in seq else -1
    waived = set(case.waived_stages or [])
    stages = [{"key": s, "label": STAGE_LABEL.get(s, s),
               "state": "done" if i < idx else "current" if i == idx
               else "future", "payment": s in PAYMENT_STAGES,
               "waived": s in waived}
              for i, s in enumerate(seq)]
    nxt = seq[idx + 1] if 0 <= idx < len(seq) - 1 else None
    needs = None
    if nxt == "WP_ARRIVED":
        needs = "arrival"
    elif nxt == "BV_ARRIVED":
        needs = "arrival_bv"
    elif nxt in APPLICATION_STAGES:
        needs = "portal_ref"
    fee = None
    if case.stage in PAYMENT_STAGES:
        f = active_fee_for(case, case.stage)
        label, refundable = FEE_META.get(case.stage, ("", False))
        fee = {"label": label, "refundable": refundable, "raised": bool(f),
               "invoice_label": INVOICE_LABEL.get(case.stage, "Invoice"),
               "pyr_ref": f.document.ref if f else None,
               "pyr_status": f.document.status if f else None,
               "paid": bool(f) and f.document.status == "PAID"}
    return {"stages": stages, "next_stage": nxt,
            "next_label": STAGE_LABEL.get(nxt) if nxt else None,
            "next_needs": needs,
            "at_application": case.stage in APPLICATION_STAGES,
            "application": application_state(case),
            "at_medical": case.stage in MEDICAL_STAGES,
            "at_payment": case.stage in PAYMENT_STAGES, "fee": fee,
            "at_last": idx == len(seq) - 1}


def outstanding_fees(case):
    """Every fee on the case whose money has not actually gone yet.

    The stage's own fee block only exists while the case is sitting AT that
    stage. Once a settled-but-unpaid fee let the case move on, the unpaid
    obligation vanished off the screen entirely — DILKUSHSINGH HEER SINGH's
    insurance was authorised, never paid, and by then the case had advanced
    past it (owner 2026-08-16). Authorised is enough to keep the case moving;
    it is not enough to stop showing the money.
    """
    out = []
    for f in case.fees.select_related("document").order_by("created_at"):
        d = f.document
        if d.status in ("PAID", "CANCELLED") or d.is_void:
            continue
        pr = getattr(d, "payment_request", None)
        out.append({
            "stage": f.stage,
            "label": FEE_META.get(f.stage, (f.stage, False))[0],
            "pyr_ref": d.ref,
            "pyr_status": d.status,
            "amount": pr.amount_requested if pr else None,
            "currency": pr.currency if pr else "MVR",
            # authorised = committed and gone, just not stamped; anything
            # earlier is still working its way to Finance.
            "authorised": d.status == "AUTHORISED",
        })
    return out


def redact_pay(row, viewer, case):
    """Strip the salary off a MANAGEMENT case for a viewer who may not see pay.

    A PM was reading the proposed salary of another PM's site engineer straight
    off the onboarding list (owner 2026-08-16). Applied at the API boundary, not
    inside `case_dict`, so the letters and the payroll hand-off — which need the
    real figure — are unaffected. Every onboarding endpoint goes through it.
    """
    if sees_staff_pay(viewer) or not is_staff_grade(
            category=case.category,
            grp=(case.job_category.grp if case.job_category_id else "")):
        return row
    return {**row, "proposed_salary": None, "allowances": [],
            "pay_hidden": True}


def case_dict(case):
    doc = case.document
    sv = stage_view(case)
    return {
        "id": doc.id, "ref": doc.ref, "status": doc.status,
        "site_code": doc.site.code, "site_id": doc.site_id,
        "doc_date": doc.doc_date,
        # The list showed no date at all, so there was no telling a case
        # raised this morning from one that had been sitting for six weeks
        # (owner 2026-08-16). `updated_at` carries the second half of that:
        # how long it has been since anything happened to it.
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "outstanding_fees": outstanding_fees(case),
        "stage": case.stage, "stage_label": STAGE_LABEL.get(case.stage, ""),
        "pending_label": pending_summary(case)[0],
        "pending_note": pending_summary(case)[1],
        "waived_stages": list(case.waived_stages or []),
        # The CURRENT stage's application …
        "portal_status": portal_for(case, case.stage)["status"],
        "portal_ref": portal_for(case, case.stage)["ref"],
        # … and every application this case has lodged, so a candidate now on
        # the work-permit track still shows the business visa he flew in on
        # (owner 2026-08-18).
        "portal_history": [
            {"stage": st, "stage_label": STAGE_LABEL.get(st, st),
             "ref": (row or {}).get("ref") or "",
             "status": (row or {}).get("status") or ""}
            for st, row in sorted((case.portal_by_stage or {}).items())
            if (row or {}).get("ref") or (row or {}).get("status")],
        "hold_reason": case.hold_reason,
        "hold_since": case.hold_since,
        "hold_by": case.hold_by.full_name if case.hold_by_id else None,
        "stage_since": case.stage_since,
        "days_at_stage": ((timezone.localdate() - case.stage_since).days
                          if case.stage_since else None),
        "medical_result": case.medical_result,
        "arrived_date": case.arrived_date, "medical_due": case.medical_due,
        "bv_expiry": case.bv_expiry,
        # A business visa is a clock that starts on arrival, and the work
        # permit has to be through before it runs out. The list showed neither
        # the arrival nor how much of the visa is left (owner 2026-08-18).
        "bv_days_left": ((case.bv_expiry - timezone.localdate()).days
                         if case.bv_expiry else None),
        **sv,
        "route": case.route, "category": case.category,
        "quota_pool": case.quota_pool,
        "quota_pool_label": case.get_quota_pool_display(),
        "bv_purpose": case.bv_purpose,
        "bv_purpose_label": (case.get_bv_purpose_display()
                             if case.bv_purpose else ""),
        "is_subcontract": _is_subcontract(case),
        "subcontractor_id": case.subcontractor_id,
        "subcontractor_name": (case.subcontractor.name
                               if case.subcontractor_id else None),
        "bv_renewals": case.bv_renewals,
        "on_site": _is_subcontract(case) and case.stage == "BV_ARRIVED"
        and doc.status == "IN_PROGRESS",
        "can_extend": (case.route == "BV" and bool(case.bv_expiry)
                       and doc.status == "IN_PROGRESS"),
        "extensions": [
            {"pyr_ref": f.document.ref, "pyr_status": f.document.status,
             "paid": f.document.status == "PAID"}
            for f in case.fees.filter(stage__startswith="BV_EXT_")
            .select_related("document").order_by("created_at")],
        "full_name": case.full_name, "nationality": case.nationality,
        "date_of_birth": case.date_of_birth, "gender": case.gender,
        "marital_status": case.marital_status,
        "passport_no": case.passport_no, "passport_expiry": case.passport_expiry,
        "old_passport_no": case.old_passport_no,
        "trade_designation": case.trade_designation,
        "job_category_id": case.job_category_id,
        "proposed_salary": case.proposed_salary, "currency": case.currency,
        "allowances": list(case.allowances or []),
        "permanent_address": case.permanent_address, "mobile": case.mobile,
        "emergency_contact": case.emergency_contact,
        "mobilisation_date": case.mobilisation_date,
        "bv_justification": case.bv_justification,
        "created_by": doc.created_by.full_name if doc.created_by_id else "",
        "employee_id": case.employee_id,
        "employee_no": case.employee.emp_no if case.employee_id else None,
        "can_send_back": can_send_back(case),
        "photo_att_id": (lambda p: p.id if p else None)(_photo_att(case)),
        "documents": documents_list(case),
        "checklist": checklist(case),
        "missing_docs": missing_documents(case),
        # Signatory sign-off: once done, every letter carries the signature +
        # company seal. Letters generated before it are unstamped drafts.
        "signatory_signed_at": case.signatory_approved_at,
        "signatory_signed_by": (case.signatory_approved_by.full_name
                                if case.signatory_approved_by_id else None),
        "letters": [_letter_dict(ltr) for ltr
                    in case.letters.select_related("created_by", "approved_by")],
        "letter_options": [
            {"kind": k, "title": m["title"],
             "needs_sign": bool(m.get("sign")),
             "available": letter_available(case, k),
             # The signatory's name/title never come from HR — they're set by
             # whoever signs the case off (owner 2026-08-09), so they don't
             # appear on the generation form.
             "fields": {f: v for f, v in letter_defaults(case, k).items()
                        if f not in ("signatory_name",
                                     "signatory_designation")}
             if letter_available(case, k) else None}
            for k, m in LETTER_META.items()],
        "approvals": [{"action": a.action, "by": a.actor.full_name,
                       "role": a.actor_role, "at": a.acted_at,
                       "comment": a.comment}
                      for a in doc.approvals.select_related("actor")
                      .order_by("acted_at")],
    }
