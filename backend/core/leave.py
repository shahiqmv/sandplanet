"""Worker leave: hold a man at Head Office while he is away, then put him back.

A worker on leave is not at his site. Leaving him on the site register forced a
bad choice — mark him present and pay for days not worked, or mark him absent,
which reads as a discipline problem and costs him his rest days. So granting
leave MOVES him to MLE for its duration (owner 2026-08-20).

Paid or unpaid is the whole difference:
  * PAID   — the MLE days are pre-marked PAID_LEAVE, so payroll pays them and
             nobody has to remember to mark him every morning.
  * UNPAID — nothing is marked, and `blocked_days` stops the site marking him
             either. The days cannot be paid by accident.

HR grants and HR marks the return. No approval step, no entitlement balance.
"""
import logging
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from .audit import audit
from .models import (Attendance, Employee, EmployeeSiteAllocation, Site,
                     WorkerLeave)

log = logging.getLogger(__name__)

GRANT_ROLES = ("HO_HR", "ADMIN", "PA")   # PA = full HR (owner 2026-08-03)


def can_grant(user):
    return user.role in GRANT_ROLES


def head_office_site():
    return Site.objects.filter(is_head_office=True).order_by("id").first()


def _current_site(employee):
    row = (employee.site_allocations.filter(to_date__isnull=True)
           .select_related("site").first())
    return row.site if row else None


def open_leave_for(employee, day=None):
    """The open leave covering `day` (today by default), if any."""
    day = day or timezone.localdate()
    return (WorkerLeave.objects.filter(
        employee=employee, returned_on__isnull=True, cancelled_at__isnull=True,
        from_date__lte=day, to_date__gte=day).first())


def blocked_days(employee, year, month):
    """Days in this month the site must NOT be able to mark.

    Unpaid leave only: the pay is being withheld deliberately, so a stray
    PRESENT would quietly undo the decision. Paid leave is pre-marked and stays
    editable — HR may need to correct a date.
    """
    first = date(year, month, 1)
    last = (date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1))
    out = set()
    for lv in WorkerLeave.objects.filter(
            employee=employee, kind=WorkerLeave.Kind.UNPAID,
            cancelled_at__isnull=True,
            from_date__lte=last, to_date__gte=first):
        day = max(lv.from_date, first)
        while day <= min(lv.to_date, last):
            out.add(day)
            day += timedelta(days=1)
    return out


def _working_days(site, start, end):
    """Days in the range that are working days for the site."""
    week = set(site.working_days or [6, 7, 1, 2, 3, 4])
    day, out = start, []
    while day <= end:
        if day.isoweekday() in week:
            out.append(day)
        day += timedelta(days=1)
    return out


def grant(data, actor):
    """Move a worker to Head Office and record the leave."""
    if not can_grant(actor):
        return None, "Only HR grants leave."
    emp = Employee.objects.filter(pk=data.get("employee_id"),
                                  is_active=True).first()
    if emp is None:
        return None, "Choose an active worker."
    try:
        start = date.fromisoformat(str(data.get("from_date")))
        end = date.fromisoformat(str(data.get("to_date")))
    except (TypeError, ValueError):
        return None, "Give the leave dates."
    if end < start:
        return None, "The end date is before the start date."
    kind = data.get("kind")
    if kind not in (WorkerLeave.Kind.PAID, WorkerLeave.Kind.UNPAID):
        return None, "Say whether the leave is paid or without pay."
    clash = WorkerLeave.objects.filter(
        employee=emp, cancelled_at__isnull=True,
        from_date__lte=end, to_date__gte=start).first()
    if clash:
        return None, (f"{emp.full_name} already has leave "
                      f"{clash.from_date} to {clash.to_date}.")
    ho = head_office_site()
    if ho is None:
        return None, ("No Head Office site is set up — mark one site as head "
                      "office first.")
    origin = _current_site(emp)
    if origin and origin.id == ho.id:
        origin = None                      # already at HO; nothing to go back to

    with transaction.atomic():
        lv = WorkerLeave.objects.create(
            employee=emp, kind=kind, from_date=start, to_date=end,
            reason=(data.get("reason") or "").strip(),
            from_site=origin, granted_by=actor)
        # Move him to Head Office for the duration.
        emp.site_allocations.filter(to_date__isnull=True).update(
            to_date=start - timedelta(days=1))
        EmployeeSiteAllocation.objects.create(employee=emp, site=ho,
                                              from_date=start)
        if kind == WorkerLeave.Kind.PAID:
            _prefill_paid(lv, ho, actor)
        else:
            # Nothing to mark — but clear anything already marked in the
            # window, or a PRESENT entered before the leave was granted would
            # still pay him.
            Attendance.objects.filter(employee=emp, day__gte=start,
                                      day__lte=end).delete()
    audit("worker_leave", lv.id, "LEAVE_GRANTED", actor=actor,
          detail={"employee": emp.emp_no, "kind": kind,
                  "from": str(start), "to": str(end),
                  "from_site": origin.code if origin else None})
    return lv, None


def _prefill_paid(lv, ho, actor):
    """Mark the working days of paid leave, so payroll pays them by itself."""
    made = 0
    for day in _working_days(ho, lv.from_date, lv.to_date):
        _, created = Attendance.objects.update_or_create(
            employee=lv.employee, day=day,
            defaults={"site": ho, "remark": "PAID_LEAVE",
                      "entered_by": actor})
        made += int(created)
    log.info("paid leave %s: marked %s day(s)", lv.pk, made)
    return made


def mark_returned(lv, actor, on=None):
    """He is back. Put him on his old site again."""
    if not can_grant(actor):
        return "Only HR marks a return."
    if not lv.is_open:
        return "This leave is already closed."
    day = on or timezone.localdate()
    if day <= lv.from_date:
        return ("The return date must be after the leave started — if he never "
                "went, cancel the leave instead.")
    with transaction.atomic():
        lv.returned_on = day
        lv.returned_by = actor
        lv.save(update_fields=["returned_on", "returned_by"])
        emp = lv.employee
        # He is back AT the site on his return date, so that day belongs to the
        # site and Head Office ends the day before — the same way the transfer
        # was made when the leave was granted.
        emp.site_allocations.filter(to_date__isnull=True).update(
            to_date=day - timedelta(days=1))
        if lv.from_site_id:
            EmployeeSiteAllocation.objects.create(
                employee=emp, site_id=lv.from_site_id, from_date=day)
        # He came back early: the rest of the paid-leave days were marked in
        # advance and would pay him a second time on top of the days he now
        # works at site. Clear them.
        if lv.kind == WorkerLeave.Kind.PAID and day <= lv.to_date:
            Attendance.objects.filter(employee=emp, remark="PAID_LEAVE",
                                      day__gte=day,
                                      day__lte=lv.to_date).delete()
    audit("worker_leave", lv.id, "LEAVE_RETURNED", actor=actor,
          detail={"employee": lv.employee.emp_no, "on": str(day),
                  "to_site": lv.from_site.code if lv.from_site else None})
    return None


def _undo_move(lv, emp):
    """Erase the Head Office stint the grant created.

    A cancelled leave never happened, so his record should not keep a spell at
    Head Office — least of all one that overlaps the site he never left. Where
    the grant's own allocation is still the open one, delete it and reopen what
    it closed. If he has been moved again since, that history is not ours to
    rewrite: close today and post him back the ordinary way.
    """
    current = emp.site_allocations.filter(to_date__isnull=True).first()
    ho = head_office_site()
    untouched = (current and ho and current.site_id == ho.id
                 and current.from_date == lv.from_date)
    if untouched:
        current.delete()
        previous = emp.site_allocations.filter(
            to_date=lv.from_date - timedelta(days=1)).order_by(
            "-from_date").first()
        if previous:
            previous.to_date = None
            previous.save(update_fields=["to_date"])
        elif lv.from_site_id:
            EmployeeSiteAllocation.objects.create(
                employee=emp, site_id=lv.from_site_id,
                from_date=lv.from_date)
        return
    today = timezone.localdate()
    emp.site_allocations.filter(to_date__isnull=True).update(
        to_date=today - timedelta(days=1))
    if lv.from_site_id:
        EmployeeSiteAllocation.objects.create(
            employee=emp, site_id=lv.from_site_id, from_date=today)


def cancel(lv, actor):
    """Granted by mistake. Undo the move and any marks it made."""
    if not can_grant(actor):
        return "Only HR cancels leave."
    if lv.returned_on:
        return "He has already returned from this leave."
    if lv.cancelled_at:
        return "This leave is already cancelled."
    with transaction.atomic():
        if lv.kind == WorkerLeave.Kind.PAID:
            Attendance.objects.filter(employee=lv.employee,
                                      remark="PAID_LEAVE",
                                      day__gte=lv.from_date,
                                      day__lte=lv.to_date).delete()
        emp = lv.employee
        _undo_move(lv, emp)
        lv.cancelled_at = timezone.now()
        lv.save(update_fields=["cancelled_at"])
    audit("worker_leave", lv.id, "LEAVE_CANCELLED", actor=actor,
          detail={"employee": lv.employee.emp_no})
    return None


def overdue(today=None):
    """Open leaves whose end date has passed — nobody has marked them back.

    HR marks the return by hand (owner 2026-08-20), so the risk is a man who is
    back at work but still on the Head Office register. This is the list that
    stops that being invisible.
    """
    today = today or timezone.localdate()
    return (WorkerLeave.objects.filter(
        returned_on__isnull=True, cancelled_at__isnull=True,
        to_date__lt=today)
        .select_related("employee", "from_site").order_by("to_date"))


def leave_dict(lv, today=None):
    today = today or timezone.localdate()
    return {
        "id": lv.id,
        "employee_id": lv.employee_id,
        "emp_no": lv.employee.emp_no,
        "full_name": lv.employee.full_name,
        "kind": lv.kind, "kind_label": lv.get_kind_display(),
        "from_date": lv.from_date, "to_date": lv.to_date, "days": lv.days,
        "reason": lv.reason,
        "from_site": lv.from_site.code if lv.from_site_id else None,
        "granted_by": lv.granted_by.full_name if lv.granted_by_id else "",
        "returned_on": lv.returned_on,
        "cancelled": bool(lv.cancelled_at),
        "open": lv.is_open,
        "overdue": bool(lv.is_open and lv.to_date < today),
        "on_leave_today": bool(lv.is_open and lv.covers(today)),
    }
