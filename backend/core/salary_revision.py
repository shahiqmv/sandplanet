"""Salary revisions — a site PM re-grades a direct worker's category + salary
on performance, a Director approves, and the new pay applies to the WHOLE month
it was initiated (owner 2026-07-25).

Payroll snapshots basic_pay + ot_rate per worker when the month's run is
generated, so applying whole-month means: update the live Employee, and if a
DRAFT run already exists for the effective month, re-snapshot that worker's line
to the new figures. A locked (paid) run is left untouched — the change then
only carries forward.
"""
import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .audit import audit
from .models import Employee, ManpowerCategory, SalaryRevision
from .worker_mgmt import SITE_MANAGE_ROLES, _is_site_pm

log = logging.getLogger(__name__)
S = SalaryRevision.Status
OPEN = (S.SUBMITTED, S.PM_APPROVED, S.RETURNED)


def _dec(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _first_of_this_month():
    t = timezone.localdate()
    return date(t.year, t.month, 1)


def create_revision(site, data, actor):
    """A site team member proposes a category/salary change for a worker. If the
    site PM raises it, it skips their own approval and waits on the Director; a
    Site Admin/Engineer's revision waits on the PM first (owner 2026-07-25)."""
    if actor.role not in SITE_MANAGE_ROLES:
        return None, "Only the site team can revise a worker's salary."
    emp = Employee.objects.filter(
        pk=data.get("employee_id"),
        engagement_type=Employee.Engagement.DIRECT, is_active=True).first()
    if emp is None or emp.current_site_id() != site.id:
        return None, "Choose an active direct worker at this site."
    if emp.salary_revisions.filter(status__in=OPEN).exists():
        return None, f"{emp.full_name} already has a revision in progress."
    to_pay = _dec(data.get("to_basic_pay"))
    if to_pay is None or to_pay <= 0:
        return None, "Enter the revised salary."
    to_cat_id = data.get("to_category_id") or emp.job_category_id
    if to_cat_id and not ManpowerCategory.objects.filter(
            pk=to_cat_id, is_active=True).exists():
        return None, "That category no longer exists."
    if not (data.get("reason") or "").strip():
        return None, "Give a reason (the performance note)."
    if to_pay == (emp.basic_pay or Decimal("0")) \
            and to_cat_id == emp.job_category_id:
        return None, "Nothing changed — set a new category or salary."
    # PM (or Admin) initiates → their approval is implied, straight to Director;
    # Site Admin/Engineer initiates → the PM approves first.
    status = S.PM_APPROVED if _is_site_pm(actor, site) else S.SUBMITTED
    rev = SalaryRevision.objects.create(
        employee=emp, site=site, status=status,
        from_category_id=emp.job_category_id, to_category_id=to_cat_id,
        from_basic_pay=emp.basic_pay, to_basic_pay=to_pay,
        currency=emp.currency, effective_month=_first_of_this_month(),
        reason=(data.get("reason") or "").strip(), requested_by=actor)
    audit("salary_revision", rev.id, "SALARY_REVISION_REQUESTED", actor=actor,
          detail={"employee": emp.emp_no, "to_pay": str(to_pay)})
    _notify(rev)
    return rev, None


def decide_revision(rev, action, actor, note=""):
    """Move a revision forward: PM approval → Director approval → applied; or
    reject / return / cancel."""
    if not rev.is_open:
        return f"This revision is already {rev.get_status_display().lower()}."
    if action == "approve":
        return _approve(rev, actor, note)
    if action == "return":
        if not (_is_site_pm(actor, rev.site)
                or actor.role in ("DIRECTOR", "ADMIN")):
            return "Only the PM or Director can return this."
        rev.status = S.RETURNED
    elif action == "reject":
        if actor.role not in ("DIRECTOR", "ADMIN"):
            return "Only a Director can reject a salary revision."
        rev.status = S.REJECTED
    elif action == "cancel":
        if actor.role not in SITE_MANAGE_ROLES:
            return "Only the site team can cancel a revision."
        rev.status = S.REJECTED
        note = note or "Cancelled by the site."
    else:
        return "Unknown action."
    rev.decision_note = note or ""
    _stamp(rev, actor)
    _notify(rev)
    return None


def _approve(rev, actor, note=""):
    if rev.status in (S.SUBMITTED, S.RETURNED):
        # PM approval step
        if not _is_site_pm(actor, rev.site):
            return "The site PM approves the revision first."
        rev.status = S.PM_APPROVED
        _stamp(rev, actor)
        _notify(rev)
        return None
    # PM_APPROVED → Director clears it and it applies
    if actor.role not in ("DIRECTOR", "ADMIN"):
        return "A Director approves the salary revision."
    return _apply(rev, actor, note)


def _apply(rev, actor, note=""):
    from .models import PayrollLine
    with transaction.atomic():
        emp = rev.employee
        emp.job_category_id = rev.to_category_id
        emp.basic_pay = rev.to_basic_pay
        emp.save(update_fields=["job_category", "basic_pay", "updated_at"])
        # Whole-month: re-snapshot any DRAFT payroll line for the effective
        # month so the new pay covers the entire month (locked runs untouched).
        y, m = rev.effective_month.year, rev.effective_month.month
        synced = 0
        for line in PayrollLine.objects.filter(
                employee=emp, run__year=y, run__month=m, run__status="DRAFT"):
            line.basic_pay = rev.to_basic_pay
            line.ot_rate = emp.ot_rate()
            line.save(update_fields=["basic_pay", "ot_rate"])
            synced += 1
        rev.status = SalaryRevision.Status.APPROVED
        rev.decision_note = note or ""
        _stamp(rev, actor)
    audit("salary_revision", rev.id, "SALARY_REVISION_APPROVED", actor=actor,
          detail={"employee": emp.emp_no, "to_pay": str(rev.to_basic_pay),
                  "lines_resynced": synced})
    _notify(rev)
    return None


def _stamp(rev, actor):
    rev.decided_by = actor
    rev.decided_at = timezone.now()
    rev.save()


def revision_dict(rev):
    return {
        "id": rev.id, "status": rev.status,
        "status_label": rev.get_status_display(),
        "employee_id": rev.employee_id, "employee": rev.employee.full_name,
        "emp_no": rev.employee.emp_no,
        "site_id": rev.site_id, "site_code": rev.site.code,
        "from_category": rev.from_category.name if rev.from_category else "",
        "to_category": rev.to_category.name if rev.to_category else "",
        "from_basic_pay": rev.from_basic_pay, "to_basic_pay": rev.to_basic_pay,
        "currency": rev.currency,
        "effective_month": rev.effective_month,
        "reason": rev.reason, "decision_note": rev.decision_note,
        "requested_by": (rev.requested_by.full_name
                         if rev.requested_by else ""),
        "requested_at": rev.requested_at,
        "decided_by": rev.decided_by.full_name if rev.decided_by else "",
        "is_open": rev.is_open,
    }


def _notify(rev):
    from . import notify
    try:
        notify.notify_salary_revision(rev)
    except Exception:                       # pragma: no cover - defensive
        log.exception("notify_salary_revision failed")
