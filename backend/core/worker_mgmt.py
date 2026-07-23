"""Site-Admin-driven management of a site's DIRECT (salaried) workforce, in
approval BATCHES (site-worker-management tool). Sites do the fast data entry;
salary is only committed live once approved. Approvers act on a whole batch at
once so individual changes don't swamp them (owner 2026-07-20).

Chains: ADD = PM → Director (salary is a recurring cost); REMOVE / TRANSFER =
site PM only."""
import logging
from datetime import date

from django.db import transaction
from django.utils import timezone

from .audit import audit
from .models import (Employee, EmployeeSiteAllocation, WorkerChangeItem,
                     WorkerChangeRequest as WCR)
from .numbering import next_ref

log = logging.getLogger(__name__)

SITE_MANAGE_ROLES = ("SITE_ADMIN", "SITE_ENGINEER", "PM", "ADMIN")
OPEN = (WCR.Status.SUBMITTED, WCR.Status.PM_APPROVED, WCR.Status.RETURNED)


def _dec(v):
    from decimal import Decimal, InvalidOperation
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _is_site_pm(actor, site):
    if actor.role == "ADMIN":
        return True
    pm = site.current_pm()
    return actor.role == "PM" and pm is not None and pm.id == actor.id


def _validate_add(data):
    if not (data.get("full_name") or "").strip():
        return "Full name is required."
    if not (data.get("passport_no") or "").strip():
        return "Passport number is required."
    if not (data.get("nationality") or "").strip():
        return "Nationality is required."
    if not data.get("job_category_id"):
        return "Trade / category is required."
    if _dec(data.get("basic_pay")) is None:
        return "Basic pay (salary) is required."
    return None


def _apply_add_fields(emp, data):
    if "full_name" in data:
        emp.full_name = (data.get("full_name") or "").strip()
    if "passport_no" in data:
        emp.passport_no = (data.get("passport_no") or "").strip()
    if "nationality" in data:
        emp.nationality = (data.get("nationality") or "").strip()
    if "basic_pay" in data:
        emp.basic_pay = _dec(data.get("basic_pay"))
    if "currency" in data:
        emp.currency = (data.get("currency") or "MVR")[:3].upper()
    if data.get("employment_type"):
        emp.employment_type = data["employment_type"]
    if "work_permit_no" in data:
        emp.work_permit_no = data.get("work_permit_no") or ""
    if "work_permit_expiry" in data:
        emp.work_permit_expiry = data.get("work_permit_expiry") or None
    if "join_date" in data:
        emp.join_date = data.get("join_date") or None
    if "date_of_birth" in data:
        emp.date_of_birth = data.get("date_of_birth") or None
    if "emergency_contact" in data:
        emp.emergency_contact = data.get("emergency_contact") or ""
    if "ot_applies" in data:
        emp.ot_applies = data.get("ot_applies")
    if "job_category_id" in data:
        emp.job_category_id = data.get("job_category_id") or None


def _has_open_change(employee):
    return employee.change_items.filter(request__status__in=OPEN).exists()


def _home_site(employee):
    row = employee.site_allocations.filter(to_date__isnull=True) \
        .select_related("site").first()
    return row.site if row else None


# ---- batch creation ----------------------------------------------------------

def create_add_batch(site, workers, actor):
    workers = [w for w in (workers or []) if any(
        (w.get(k) or "").strip() for k in ("full_name", "passport_no"))]
    if not workers:
        return None, "Add at least one worker."
    for i, w in enumerate(workers, 1):
        err = _validate_add(w)
        if err:
            return None, f"Worker {i}: {err}"
    with transaction.atomic():
        batch = WCR.objects.create(kind=WCR.Kind.ADD, site=site,
                                   requested_by=actor)
        for w in workers:
            emp = Employee(
                emp_no=f"EMP-{int(next_ref('EMP', None).split('-')[1]):04d}",
                engagement_type=Employee.Engagement.DIRECT,
                is_active=False, hire_pending=True)
            _apply_add_fields(emp, w)
            emp.save()
            WorkerChangeItem.objects.create(request=batch, employee=emp)
    audit("worker_batch", batch.id, "WORKER_ADD_REQUESTED", actor=actor,
          detail={"site": site.code, "workers": len(workers)})
    _notify(batch)
    return batch, None


def create_remove_batch(site, employee_ids, actor, reason=""):
    emps, err = _resolve_workers(site, employee_ids)
    if err:
        return None, err
    with transaction.atomic():
        batch = WCR.objects.create(kind=WCR.Kind.REMOVE, site=site,
                                   reason=reason, requested_by=actor)
        for e in emps:
            WorkerChangeItem.objects.create(request=batch, employee=e)
    audit("worker_batch", batch.id, "WORKER_REMOVE_REQUESTED", actor=actor,
          detail={"site": site.code, "workers": len(emps)})
    _notify(batch)
    return batch, None


def create_transfer_batch(site, employee_ids, to_site, actor):
    if to_site is None or to_site.id == site.id:
        return None, "Choose a different destination site."
    emps, err = _resolve_workers(site, employee_ids)
    if err:
        return None, err
    with transaction.atomic():
        batch = WCR.objects.create(kind=WCR.Kind.TRANSFER, site=site,
                                   to_site=to_site, requested_by=actor)
        for e in emps:
            WorkerChangeItem.objects.create(request=batch, employee=e)
    audit("worker_batch", batch.id, "WORKER_TRANSFER_REQUESTED", actor=actor,
          detail={"from": site.code, "to": to_site.code, "workers": len(emps)})
    _notify(batch)
    return batch, None


def _resolve_workers(site, employee_ids):
    ids = [i for i in (employee_ids or []) if i]
    if not ids:
        return None, "Select at least one worker."
    emps = list(Employee.objects.filter(pk__in=ids))
    if len(emps) != len(set(ids)):
        return None, "One or more workers were not found."
    for e in emps:
        if e.is_subcontract:
            return None, f"{e.full_name} is a subcontract worker."
        if not e.is_active or (_home_site(e) or None) != site:
            return None, f"{e.full_name} is not an active worker at this site."
        if _has_open_change(e):
            return None, f"{e.full_name} already has a change in progress."
    return emps, None


# ---- decisions (whole batch) -------------------------------------------------

def approve_batch(batch, actor):
    if not batch.is_open:
        return f"This batch is already {batch.get_status_display().lower()}."
    if batch.kind == WCR.Kind.ADD:
        if batch.status in (WCR.Status.SUBMITTED, WCR.Status.RETURNED):
            if not _is_site_pm(actor, batch.site):
                return "The site PM approves new hires first."
            batch.status = WCR.Status.PM_APPROVED
            _stamp(batch, actor)
            _notify(batch)
            return None
        if actor.role not in ("DIRECTOR", "ADMIN"):
            return "A Director activates new hires (salary approval)."
        return _activate_add(batch, actor)
    if not _is_site_pm(actor, batch.site):
        return "The site PM approves this batch."
    return _apply_remove(batch, actor) if batch.kind == WCR.Kind.REMOVE \
        else _apply_transfer(batch, actor)


def return_batch(batch, actor, note=""):
    if not batch.is_open:
        return "This batch is not open."
    if batch.kind == WCR.Kind.ADD:
        if not (_is_site_pm(actor, batch.site) or actor.role in ("DIRECTOR",
                                                                 "ADMIN")):
            return "Only the PM or Director can return this."
    elif not _is_site_pm(actor, batch.site):
        return "Only the site PM can return this."
    batch.status = WCR.Status.RETURNED
    batch.decision_note = note
    _stamp(batch, actor)
    audit("worker_batch", batch.id, "WORKER_BATCH_RETURNED", actor=actor,
          detail={"note": note})
    return None


def resubmit_batch(batch, actor):
    if batch.status != WCR.Status.RETURNED:
        return "Only a returned batch can be resubmitted."
    if actor.role not in SITE_MANAGE_ROLES:
        return "Only the site team can resubmit."
    batch.status = WCR.Status.SUBMITTED
    batch.save(update_fields=["status", "updated_at"])
    audit("worker_batch", batch.id, "WORKER_BATCH_RESUBMITTED", actor=actor)
    _notify(batch)
    return None


def cancel_batch(batch, actor):
    if not batch.is_open:
        return "This batch is not open."
    if actor.role not in SITE_MANAGE_ROLES:
        return "Only the site team can cancel a batch."
    with transaction.atomic():
        batch.status = WCR.Status.CANCELLED
        _stamp(batch, actor)
        if batch.kind == WCR.Kind.ADD:
            # the pending hires never went live — retire the placeholders
            for item in batch.items.select_related("employee"):
                emp = item.employee
                emp.hire_pending = False
                emp.save(update_fields=["hire_pending", "updated_at"])
    audit("worker_batch", batch.id, "WORKER_BATCH_CANCELLED", actor=actor)
    return None


def update_hire(employee, data, actor):
    """Edit a pending hire while its ADD batch is still with the site."""
    if not employee.hire_pending:
        return "This worker is not a pending hire."
    if not employee.change_items.filter(
            request__status__in=(WCR.Status.SUBMITTED,
                                 WCR.Status.RETURNED)).exists():
        return "This hire's batch is no longer editable."
    merged = {
        "full_name": data.get("full_name", employee.full_name),
        "passport_no": data.get("passport_no", employee.passport_no),
        "nationality": data.get("nationality", employee.nationality),
        "job_category_id": data.get("job_category_id",
                                    employee.job_category_id),
        "basic_pay": data.get("basic_pay", employee.basic_pay),
    }
    err = _validate_add(merged)
    if err:
        return err
    _apply_add_fields(employee, data)
    employee.save()
    audit("employee", employee.id, "WORKER_HIRE_EDITED", actor=actor)
    return None


# ---- application -------------------------------------------------------------

def _activate_add(batch, actor):
    with transaction.atomic():
        for item in batch.items.select_related("employee"):
            emp = item.employee
            emp.is_active = True
            emp.hire_pending = False
            emp.save(update_fields=["is_active", "hire_pending", "updated_at"])
            if not emp.site_allocations.filter(to_date__isnull=True).exists():
                EmployeeSiteAllocation.objects.create(
                    employee=emp, site=batch.site, from_date=date.today())
        batch.status = WCR.Status.APPROVED
        _stamp(batch, actor)
    audit("worker_batch", batch.id, "WORKER_ADD_APPROVED", actor=actor,
          detail={"site": batch.site.code, "workers": batch.items.count()})
    return None


def _apply_remove(batch, actor):
    with transaction.atomic():
        for item in batch.items.select_related("employee"):
            emp = item.employee
            emp.is_active = False
            emp.save(update_fields=["is_active", "updated_at"])
            emp.site_allocations.filter(to_date__isnull=True).update(
                to_date=date.today())
        batch.status = WCR.Status.APPROVED
        _stamp(batch, actor)
    audit("worker_batch", batch.id, "WORKER_REMOVE_APPROVED", actor=actor,
          detail={"workers": batch.items.count()})
    return None


def _apply_transfer(batch, actor):
    with transaction.atomic():
        for item in batch.items.select_related("employee"):
            emp = item.employee
            emp.site_allocations.filter(to_date__isnull=True).update(
                to_date=date.today())
            EmployeeSiteAllocation.objects.create(
                employee=emp, site=batch.to_site, from_date=date.today())
        batch.status = WCR.Status.APPROVED
        _stamp(batch, actor)
    audit("worker_batch", batch.id, "WORKER_TRANSFER_APPROVED", actor=actor,
          detail={"from": batch.site.code, "to": batch.to_site.code,
                  "workers": batch.items.count()})
    return None


# ---- helpers -----------------------------------------------------------------

def _stamp(batch, actor):
    batch.decided_by = actor
    batch.decided_at = timezone.now()
    batch.save()


def _notify(batch):
    from . import notify
    try:
        notify.notify_worker_request(batch)
    except Exception:                       # pragma: no cover - defensive
        log.exception("notify_worker_request failed")
