"""Work-permit tracking for employees.

Permanent workers (local or foreign) sit on the company work permit and have
an expiry we watch; contract workers are temporary hires and are not tracked.
HR renews a permit by choosing a number of months — the expiry moves forward
by that much and a renewal record is kept. The HR view flags anything expiring
within 30 days (or already expired).
"""
import calendar
from datetime import date, timedelta

from django.utils import timezone

from .audit import audit
from .models import Employee, WorkPermitRenewal

ALERT_DAYS = 30


def add_months(d, months):
    """d plus `months` calendar months, clamping the day to the target
    month's length (e.g. 31 Jan + 1 month → 28/29 Feb)."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def permit_status(emp, today=None):
    """('NA' | 'OK' | 'EXPIRING' | 'EXPIRED', days_to_expiry|None).
    NA when the worker isn't permit-tracked (contract, or no expiry set)."""
    today = today or date.today()
    if (emp.employment_type != Employee.EmploymentType.PERMANENT
            or not emp.work_permit_expiry):
        return "NA", None
    days = (emp.work_permit_expiry - today).days
    if days < 0:
        return "EXPIRED", days
    if days <= ALERT_DAYS:
        return "EXPIRING", days
    return "OK", days


def schedule(emp, months, fee, note, actor, document=None):
    """Record a PENDING renewal for `months` linked to the PYR that pays its
    fee. The expiry is NOT touched yet — it only moves forward once Finance
    pays the PYR (see apply). Returns the renewal row."""
    months = int(months)
    if months <= 0:
        raise ValueError("Choose a number of months greater than zero.")
    # a renewal implies the worker is on the permit
    if emp.employment_type != Employee.EmploymentType.PERMANENT:
        emp.employment_type = Employee.EmploymentType.PERMANENT
        emp.save(update_fields=["employment_type", "updated_at"])
    row = WorkPermitRenewal.objects.create(
        employee=emp, months=months, previous_expiry=emp.work_permit_expiry,
        note=note or "", fee=fee, document=document, created_by=actor)
    audit("employee", emp.id, "PERMIT_RENEWAL_SCHEDULED", actor=actor,
          detail={"emp_no": emp.emp_no, "months": months,
                  "pyr": document.ref if document else None})
    return row


def apply(row, actor, today=None):
    """Extend the worker's permit for an already-scheduled renewal — called
    when its PYR is paid. Idempotent: does nothing if already applied."""
    if row.applied:
        return row
    today = today or date.today()
    emp = row.employee
    base = emp.work_permit_expiry if emp.work_permit_expiry else today
    new_expiry = add_months(base, row.months)
    emp.work_permit_expiry = new_expiry
    emp.save(update_fields=["work_permit_expiry", "updated_at"])
    row.previous_expiry = base
    row.new_expiry = new_expiry
    row.applied = True
    row.applied_at = timezone.now()
    row.save(update_fields=["previous_expiry", "new_expiry", "applied",
                            "applied_at"])
    audit("employee", emp.id, "PERMIT_RENEWED", actor=actor,
          detail={"emp_no": emp.emp_no, "months": row.months,
                  "previous_expiry": base.isoformat(),
                  "new_expiry": new_expiry.isoformat(),
                  "pyr": row.document.ref if row.document_id else None})
    return row


def apply_for_document(doc, actor):
    """Apply every pending renewal attached to a paid PYR."""
    for row in doc.permit_renewals.filter(applied=False).select_related(
            "employee"):
        apply(row, actor)


def has_pending(emp):
    """True if the worker has a renewal awaiting payment."""
    return emp.permit_renewals.filter(applied=False).exists()


def alerts(within_days=ALERT_DAYS, today=None, site_ids=None):
    """Permanent workers whose permit expires within `within_days` (or already
    has). Sorted soonest first. `site_ids=None` = all sites."""
    today = today or date.today()
    horizon = today + timedelta(days=within_days)
    qs = Employee.objects.filter(
        is_active=True,
        employment_type=Employee.EmploymentType.PERMANENT,
        work_permit_expiry__isnull=False,
        work_permit_expiry__lte=horizon,
    ).select_related("job_category")
    if site_ids is not None:
        qs = qs.filter(site_allocations__site_id__in=site_ids,
                       site_allocations__to_date__isnull=True).distinct()
    out = []
    for emp in qs.order_by("work_permit_expiry"):
        state, days = permit_status(emp, today)
        alloc = emp.site_allocations.filter(
            to_date__isnull=True).select_related("site").first()
        out.append({
            "id": emp.id, "emp_no": emp.emp_no, "full_name": emp.full_name,
            "nationality": emp.nationality,
            "site_code": alloc.site.code if alloc else None,
            "work_permit_no": emp.work_permit_no,
            "work_permit_expiry": emp.work_permit_expiry,
            "state": state, "days": days,
        })
    return out
