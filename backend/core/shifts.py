"""Shift assignments (owner 2026-08-25): some sites run Morning / Afternoon /
Night crews. Shifts are defined per site; each worker optionally points at
one through a date-scoped assignment. Everything that reads a schedule — the
day grid's defaults, the gate terminal's late flag and OT proposal, stored
normal hours — resolves the worker's shift first and falls back to the
site's single schedule."""

from datetime import datetime, timedelta

from django.db.models import Q

from .models import EmployeeShiftAssignment


def site_shifts(site):
    return list(site.shifts.filter(is_active=True))


def shifts_map(site, day, employee_ids):
    """{employee_id: SiteShift} for whoever holds an assignment on this
    site's shifts covering the day. Latest from_date wins if history ever
    overlaps."""
    rows = (EmployeeShiftAssignment.objects
            .filter(employee_id__in=employee_ids, shift__site=site,
                    shift__is_active=True, from_date__lte=day)
            .filter(Q(to_date__isnull=True) | Q(to_date__gte=day))
            .select_related("shift")
            .order_by("from_date", "id"))
    return {r.employee_id: r.shift for r in rows}


def assign(employee, shift, day):
    """Put the worker on a shift from this day (or clear with shift=None).
    Any open assignment — on any site, so a transferred man never drags an
    old shift along — is closed the day before."""
    open_rows = employee.shift_assignments.filter(to_date__isnull=True)
    for row in open_rows:
        if shift and row.shift_id == shift.id and row.from_date <= day:
            return row                      # already on it — nothing to do
        if row.from_date >= day:
            row.delete()                    # assignment not yet started
        else:
            row.to_date = day - timedelta(days=1)
            row.save(update_fields=["to_date"])
    if shift is None:
        return None
    return EmployeeShiftAssignment.objects.create(
        employee=employee, shift=shift, from_date=day)


def schedule_for(site, shift):
    """(start, end, ot_from, overnight) — the shift's window, or the site's
    single schedule when the worker has no shift."""
    if shift:
        return (shift.start, shift.end,
                shift.ot_counts_from or shift.end, shift.overnight)
    return (site.working_hours_from, site.working_hours_to,
            site.ot_counts_from or site.working_hours_to, False)


def window_datetimes(day, start, end):
    """The concrete window on one day; an overnight window ends tomorrow."""
    s = datetime.combine(day, start)
    e = datetime.combine(day, end)
    if e <= s:
        e += timedelta(days=1)
    return s, e


def can_manage_shifts(user, site):
    """Admin/Director, or the site's own PM (owner 2026-08-25)."""
    if user.role in ("ADMIN", "DIRECTOR"):
        return True
    return user.role == "PM" and site.is_current_pm(user)
