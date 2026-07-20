"""Site-Admin-driven management of a site's DIRECT (salaried) workforce with
an approval gate (site-worker-management tool). Sites do the fast data entry;
salary is only committed live once approved. HO HR keeps the payroll master.

Chains (owner 2026-07-20): ADD = PM → Director (salary is a recurring cost);
REMOVE / TRANSFER = site PM only."""
import logging
from datetime import date

from django.db import transaction
from django.utils import timezone

from .audit import audit
from .models import (Employee, EmployeeSiteAllocation, Site,
                     WorkerChangeRequest as WCR)
from .numbering import next_ref

log = logging.getLogger(__name__)

SITE_MANAGE_ROLES = ("SITE_ADMIN", "SITE_ENGINEER", "ADMIN")
# Fields the site enters for a new hire (salary + identity).
_ADD_FIELDS = ("full_name", "passport_no", "nationality", "basic_pay",
               "currency", "employment_type", "work_permit_no",
               "work_permit_expiry", "join_date", "date_of_birth",
               "emergency_contact", "ot_applies")


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
        return "The worker's full name is required."
    if not (data.get("passport_no") or "").strip():
        return "Passport number is required."
    if not (data.get("nationality") or "").strip():
        return "Nationality is required."
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
    if "employment_type" in data and data.get("employment_type"):
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


# ---- requests ----------------------------------------------------------------

def request_add_worker(site, data, actor):
    err = _validate_add(data)
    if err:
        return None, err
    with transaction.atomic():
        emp = Employee(emp_no=f"EMP-{int(next_ref('EMP', None).split('-')[1]):04d}",
                       engagement_type=Employee.Engagement.DIRECT,
                       is_active=False, hire_pending=True)
        _apply_add_fields(emp, data)
        emp.save()
        req = WCR.objects.create(kind=WCR.Kind.ADD, employee=emp, site=site,
                                 requested_by=actor)
    audit("employee", emp.id, "WORKER_ADD_REQUESTED", actor=actor,
          detail={"site": site.code, "req": req.id})
    _notify_next(req)
    return req, None


def update_add_request(req, data, actor):
    """Edit the pending hire while the request is still with the site."""
    if req.kind != WCR.Kind.ADD or req.status not in (
            WCR.Status.SUBMITTED, WCR.Status.RETURNED):
        return None, "Only a submitted or returned new-hire request is editable."
    err = _validate_add({**{"full_name": req.employee.full_name,
                            "passport_no": req.employee.passport_no,
                            "nationality": req.employee.nationality,
                            "basic_pay": req.employee.basic_pay}, **data})
    if err:
        return None, err
    _apply_add_fields(req.employee, data)
    req.employee.save()
    if req.status == WCR.Status.RETURNED:
        req.status = WCR.Status.SUBMITTED
        req.save(update_fields=["status", "updated_at"])
        _notify_next(req)
    audit("employee", req.employee_id, "WORKER_ADD_EDITED", actor=actor,
          detail={"req": req.id})
    return req, None


def request_remove_worker(employee, actor, reason=""):
    site = _home_site(employee)
    if site is None:
        return None, "This worker has no active site allocation."
    if employee.is_subcontract:
        return None, "Use the subcontractor team tool for subcontract workers."
    if _open_request(employee):
        return None, "This worker already has a change request in progress."
    req = WCR.objects.create(kind=WCR.Kind.REMOVE, employee=employee, site=site,
                             reason=reason, requested_by=actor)
    audit("employee", employee.id, "WORKER_REMOVE_REQUESTED", actor=actor,
          detail={"site": site.code, "req": req.id})
    _notify_next(req)
    return req, None


def request_transfer_worker(employee, to_site, actor):
    site = _home_site(employee)
    if site is None:
        return None, "This worker has no active site allocation."
    if employee.is_subcontract:
        return None, "Subcontract workers are managed per subcontractor."
    if to_site.id == site.id:
        return None, "Choose a different destination site."
    if _open_request(employee):
        return None, "This worker already has a change request in progress."
    req = WCR.objects.create(kind=WCR.Kind.TRANSFER, employee=employee,
                             site=site, to_site=to_site, requested_by=actor)
    audit("employee", employee.id, "WORKER_TRANSFER_REQUESTED", actor=actor,
          detail={"from": site.code, "to": to_site.code, "req": req.id})
    _notify_next(req)
    return req, None


# ---- decisions ---------------------------------------------------------------

def approve_request(req, actor):
    if not req.is_open:
        return f"This request is already {req.get_status_display().lower()}."
    if req.kind == WCR.Kind.ADD:
        if req.status in (WCR.Status.SUBMITTED, WCR.Status.RETURNED):
            if not _is_site_pm(actor, req.site):
                return "The site PM approves a new hire first."
            req.status = WCR.Status.PM_APPROVED
            _stamp(req, actor)
            _notify_next(req)
            return None
        # PM_APPROVED → Director activates (commits the salary)
        if actor.role not in ("DIRECTOR", "ADMIN"):
            return "A Director activates the new hire (salary approval)."
        return _activate_hire(req, actor)
    # REMOVE / TRANSFER — site PM only, single step
    if not _is_site_pm(actor, req.site):
        return "The site PM approves this request."
    if req.kind == WCR.Kind.REMOVE:
        return _apply_remove(req, actor)
    return _apply_transfer(req, actor)


def return_request(req, actor, note=""):
    if not req.is_open:
        return "This request is not open."
    if req.kind == WCR.Kind.ADD:
        if not (_is_site_pm(actor, req.site) or actor.role in ("DIRECTOR",
                                                               "ADMIN")):
            return "Only the PM or Director can return this."
    elif not _is_site_pm(actor, req.site):
        return "Only the site PM can return this."
    req.status = WCR.Status.RETURNED
    req.decision_note = note
    _stamp(req, actor)
    audit("employee", req.employee_id, "WORKER_REQ_RETURNED", actor=actor,
          detail={"req": req.id, "note": note})
    return None


def cancel_request(req, actor):
    """The requesting site withdraws an open request."""
    if not req.is_open:
        return "This request is not open."
    if actor.role not in SITE_MANAGE_ROLES:
        return "Only the site team can cancel a request."
    req.status = WCR.Status.CANCELLED
    _stamp(req, actor)
    if req.kind == WCR.Kind.ADD:
        # the pending hire never went live — retire the placeholder record
        req.employee.hire_pending = False
        req.employee.save(update_fields=["hire_pending", "updated_at"])
    audit("employee", req.employee_id, "WORKER_REQ_CANCELLED", actor=actor,
          detail={"req": req.id})
    return None


# ---- application -------------------------------------------------------------

def _activate_hire(req, actor):
    emp = req.employee
    with transaction.atomic():
        emp.is_active = True
        emp.hire_pending = False
        emp.save(update_fields=["is_active", "hire_pending", "updated_at"])
        if not emp.site_allocations.filter(to_date__isnull=True).exists():
            EmployeeSiteAllocation.objects.create(
                employee=emp, site=req.site, from_date=date.today())
        req.status = WCR.Status.APPROVED
        _stamp(req, actor)
    audit("employee", emp.id, "WORKER_ADD_APPROVED", actor=actor,
          detail={"site": req.site.code, "req": req.id})
    return None


def _apply_remove(req, actor):
    emp = req.employee
    with transaction.atomic():
        emp.is_active = False
        emp.save(update_fields=["is_active", "updated_at"])
        emp.site_allocations.filter(to_date__isnull=True).update(
            to_date=date.today())
        req.status = WCR.Status.APPROVED
        _stamp(req, actor)
    audit("employee", emp.id, "WORKER_REMOVE_APPROVED", actor=actor,
          detail={"req": req.id})
    return None


def _apply_transfer(req, actor):
    emp = req.employee
    with transaction.atomic():
        emp.site_allocations.filter(to_date__isnull=True).update(
            to_date=date.today())
        EmployeeSiteAllocation.objects.create(
            employee=emp, site=req.to_site, from_date=date.today())
        req.status = WCR.Status.APPROVED
        _stamp(req, actor)
    audit("employee", emp.id, "WORKER_TRANSFER_APPROVED", actor=actor,
          detail={"from": req.site.code, "to": req.to_site.code,
                  "req": req.id})
    return None


# ---- helpers -----------------------------------------------------------------

def _home_site(employee):
    row = employee.site_allocations.filter(to_date__isnull=True) \
        .select_related("site").first()
    return row.site if row else None


def _open_request(employee):
    return employee.change_requests.filter(
        status__in=(WCR.Status.SUBMITTED, WCR.Status.PM_APPROVED,
                    WCR.Status.RETURNED)).exists()


def _stamp(req, actor):
    req.decided_by = actor
    req.decided_at = timezone.now()
    req.save()


def _notify_next(req):
    """Alert whoever the request now waits on."""
    from . import notify
    try:
        notify.notify_worker_request(req)
    except Exception:                       # pragma: no cover - defensive
        log.exception("notify_worker_request failed")
