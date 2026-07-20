"""Subcontractor lifecycle + site-level team management (subcontractor module,
Phase 2). Site-managed: the SA/SE create and staff subcontractors; PM→Director
activate; HR/HO have no management role. A subcontract worker is an Employee
(engagement_type SUBCONTRACT), kept out of payroll structurally (Phase 1)."""
import logging
from datetime import date

from django.db import transaction

from .audit import audit
from .models import Employee, EmployeeSiteAllocation, Subcontractor
from .numbering import next_ref

log = logging.getLogger(__name__)

SITE_MANAGE_ROLES = ("SITE_ADMIN", "SITE_ENGINEER", "ADMIN")
_FIELDS = ("name", "registration_no", "contact_person", "phone",
           "bank_details", "notes")


def create_subcontractor(site, data, actor):
    if not (data.get("name") or "").strip():
        return None, "A subcontractor name is required."
    sub = Subcontractor.objects.create(
        site=site, created_by=actor,
        **{f: (data.get(f) or "") for f in _FIELDS})
    audit("subcontractor", sub.id, "SUB_CREATED", actor=actor,
          detail={"name": sub.name, "site": site.code})
    return sub, None


def update_subcontractor(sub, data, actor):
    if sub.status != Subcontractor.Status.DRAFT:
        return "Only a draft subcontractor can be edited."
    for f in _FIELDS:
        if f in data:
            setattr(sub, f, data.get(f) or "")
    sub.save()
    return None


def approve_subcontractor(sub, actor):
    """PM approves a Draft → PM_APPROVED; Director activates that → Approved."""
    S = Subcontractor.Status
    role = actor.role
    if sub.status == S.DRAFT:
        if role not in ("PM", "ADMIN"):
            return "A draft subcontractor is approved by the site PM."
        sub.status = S.PM_APPROVED
    elif sub.status == S.PM_APPROVED:
        if role not in ("DIRECTOR", "ADMIN"):
            return "A PM-approved subcontractor is activated by a Director."
        sub.status = S.APPROVED
    else:
        return f"Cannot approve a {sub.get_status_display()} subcontractor."
    sub.save(update_fields=["status", "updated_at"])
    audit("subcontractor", sub.id, "SUB_APPROVED", actor=actor,
          to_state=sub.status, detail={"name": sub.name})
    from . import notify
    notify.notify_subcontractor(sub, actor)
    return None


def return_subcontractor(sub, actor, reason=""):
    if sub.status not in (Subcontractor.Status.PM_APPROVED,
                          Subcontractor.Status.DRAFT):
        return "Only a pending subcontractor can be returned."
    sub.status = Subcontractor.Status.DRAFT
    sub.save(update_fields=["status", "updated_at"])
    audit("subcontractor", sub.id, "SUB_RETURNED", actor=actor,
          detail={"reason": reason})
    return None


def set_subcontractor_status(sub, status, actor):
    """Suspend / close / reactivate — a PM+ control (per §3.1)."""
    S = Subcontractor.Status
    if status not in (S.SUSPENDED, S.CLOSED, S.ACTIVE, S.APPROVED):
        return "Invalid status."
    if actor.role not in ("PM", "DIRECTOR", "ADMIN"):
        return "Suspend / close requires PM approval."
    sub.status = status
    sub.save(update_fields=["status", "updated_at"])
    audit("subcontractor", sub.id, "SUB_STATUS", actor=actor, to_state=status)
    return None


# ---- team management ---------------------------------------------------------

def add_worker(sub, data, actor):
    """SA/SE adds a worker under an Approved subcontractor. The worker starts
    inactive + pending, so it stays out of every attendance roster + manpower
    count until the PM approves it."""
    if not sub.can_raise_sca:
        return None, "Workers can only be added under an approved subcontractor."
    if not (data.get("full_name") or "").strip():
        return None, "The worker's name is required."
    with transaction.atomic():
        n = int(next_ref("EMP", None).split("-")[1])
        emp = Employee.objects.create(
            emp_no=f"EMP-{n:04d}", full_name=data["full_name"].strip(),
            passport_no=data.get("passport_no", ""),
            nationality=data.get("nationality", ""),
            job_category_id=data.get("job_category_id") or None,
            emergency_contact=data.get("emergency_contact", ""),
            engagement_type=Employee.Engagement.SUBCONTRACT, subcontractor=sub,
            is_active=False, sub_pending=True)
        EmployeeSiteAllocation.objects.create(
            employee=emp, site=sub.site, from_date=date.today())
    audit("employee", emp.id, "SUB_WORKER_ADDED", actor=actor,
          detail={"sub": sub.name, "name": emp.full_name})
    return emp, None


def approve_worker(emp, actor):
    """PM approval activates a pending subcontract worker — it now appears in
    the site attendance register + manpower count."""
    if not emp.sub_pending:
        return "This worker is not pending approval."
    emp.sub_pending = False
    emp.is_active = True
    emp.save(update_fields=["sub_pending", "is_active", "updated_at"])
    audit("employee", emp.id, "SUB_WORKER_APPROVED", actor=actor)
    return None


def remove_worker(emp, actor):
    """Immediate deactivation with an audit entry (no approval needed)."""
    emp.is_active = False
    emp.sub_pending = False
    emp.save(update_fields=["is_active", "sub_pending", "updated_at"])
    audit("employee", emp.id, "SUB_WORKER_REMOVED", actor=actor)
    return None


# ---- Subcontract Agreements (SCA) --------------------------------------------
# An SCA is a Document subtype (doc_type SCA) headed by SubcontractAgreement,
# exactly the way an IPR is headed by ImportOrder. Lifecycle DRAFT→SUBMITTED→
# PM_APPROVED→APPROVED runs on the generic Document approval engine
# (views_documents._do_submit/_do_approve/_do_return); this module owns only
# creation + draft editing of the header and its priced scope.

def _dec(v):
    from decimal import Decimal, InvalidOperation
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _scope_items(agreement, rows):
    """(unsaved) SubcontractScopeItem instances from cleaned dict rows. A row
    with no qty, rate or unit is a heading."""
    from .models import SubcontractScopeItem
    out = []
    for i, r in enumerate(rows):
        desc = str(r.get("description") or "").strip()
        section = str(r.get("section") or "").strip()
        code = str(r.get("item_code") or "").strip()
        unit = str(r.get("unit") or "").strip()
        if not (desc or section or code):
            continue
        qty, rate = _dec(r.get("qty")), _dec(r.get("rate"))
        is_heading = bool(r.get("is_heading")) or (
            qty is None and rate is None and not unit)
        out.append(SubcontractScopeItem(
            agreement=agreement, sort_order=i, section=section, item_code=code,
            description=desc, unit=unit, qty=qty, rate=rate,
            is_heading=is_heading))
    return out


def _set_scope(agreement, rows):
    from .models import SubcontractScopeItem
    items = _scope_items(agreement, rows)
    agreement.items.all().delete()
    SubcontractScopeItem.objects.bulk_create(items)
    return len(items)


def create_sca(sub, data, actor):
    """Draft a Subcontract Agreement under an approved subcontractor."""
    from datetime import date

    from .models import (Document, DocumentRevision, Project,
                         SubcontractAgreement)
    from .numbering import next_ref
    if not sub.can_raise_sca:
        return None, "Only an approved subcontractor can hold an agreement."
    if not (data.get("title") or "").strip():
        return None, "Give the agreement a title."
    project = None
    if data.get("project_id"):
        project = Project.objects.filter(pk=data["project_id"],
                                         site=sub.site).first()
    with transaction.atomic():
        doc = Document.objects.create(
            doc_type="SCA", ref=next_ref("SCA", sub.site), site=sub.site,
            project=project, doc_date=data.get("doc_date") or date.today(),
            status="DRAFT", created_by=actor)
        DocumentRevision.objects.create(document=doc, rev_label="R0",
                                        payload={}, created_by=actor)
        doc.current_revision = doc.revisions.first()
        doc.save(update_fields=["current_revision"])
        agreement = SubcontractAgreement.objects.create(
            document=doc, subcontractor=sub, project=project,
            title=data["title"].strip(),
            currency=(data.get("currency") or "MVR")[:3].upper(),
            start_date=data.get("start_date") or None,
            end_date=data.get("end_date") or None,
            notes=data.get("notes", ""))
        _set_scope(agreement, data.get("rows") or [])
    audit("document", doc.id, "DOC_CREATED", actor=actor, to_state="DRAFT",
          detail={"ref": doc.ref, "sub": sub.name})
    return doc, None


def update_sca(doc, data, actor):
    """Edit a draft SCA in place — header + scope."""
    if doc.status != "DRAFT":
        return None, "Only a draft agreement can be edited."
    agreement = doc.subcontract_agreement
    if "title" in data and (data.get("title") or "").strip():
        agreement.title = data["title"].strip()
    if "currency" in data:
        agreement.currency = (data.get("currency")
                              or agreement.currency)[:3].upper()
    for f in ("start_date", "end_date"):
        if f in data:
            setattr(agreement, f, data.get(f) or None)
    if "notes" in data:
        agreement.notes = data.get("notes") or ""
    agreement.save()
    if "rows" in data:
        _set_scope(agreement, data.get("rows") or [])
    audit("document", doc.id, "SCA_EDITED", actor=actor,
          detail={"ref": doc.ref})
    return doc, None
