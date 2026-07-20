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
