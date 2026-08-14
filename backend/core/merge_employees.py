"""Merge a duplicate employee record into the one that keeps the history.

Rakib Hosen moved from BVR to Malé on 12 August and HR opened a second record
rather than transferring him, so his July attendance sat on EMP-0020 while his
August days went to EMP-0603 and he appeared on one payroll run twice. He is
not alone: 38 passport numbers are on more than one record (owner 2026-08-15).

Merging is deliberately not automatic. It moves work history between records
and there is no undo, so it runs as a plan first — `plan()` says exactly what
would move and what collides — and only `merge()` writes.

Everything that points at an employee is moved: attendance, allocations,
payroll lines, advances, salary revisions, permit renewals and worker-change
items. The duplicate is then deactivated, never deleted: it keeps its emp_no
so the audit trail and any paper referring to it still resolve.
"""
from django.db import transaction

from .audit import audit
from .models import (Attendance, Employee, EmployeeSiteAllocation, PayrollLine,
                     SalaryAdvance, SalaryRevision, WorkerChangeItem,
                     WorkPermitRenewal)

# Everything with a FK to Employee. Attendance and PayrollLine are handled
# separately because each has a uniqueness rule that can collide.
SIMPLE = [EmployeeSiteAllocation, SalaryAdvance, SalaryRevision,
          WorkPermitRenewal, WorkerChangeItem]


def _collisions(keeper, dup):
    """Days and runs where BOTH records already have a row."""
    k_days = set(Attendance.objects.filter(employee=keeper)
                 .values_list("day", flat=True))
    d_days = set(Attendance.objects.filter(employee=dup)
                 .values_list("day", flat=True))
    k_runs = set(PayrollLine.objects.filter(employee=keeper)
                 .values_list("run_id", flat=True))
    d_runs = set(PayrollLine.objects.filter(employee=dup)
                 .values_list("run_id", flat=True))
    return sorted(k_days & d_days), sorted(k_runs & d_runs)


def plan(keeper, dup):
    """What a merge would do. Read-only."""
    days, runs = _collisions(keeper, dup)
    counts = {m.__name__: m.objects.filter(employee=dup).count()
              for m in SIMPLE}
    counts["Attendance"] = Attendance.objects.filter(employee=dup).count()
    counts["PayrollLine"] = PayrollLine.objects.filter(employee=dup).count()
    blocked = []
    for rid in runs:
        line = PayrollLine.objects.get(employee=dup, run_id=rid)
        if line.run.status == "LOCKED":
            blocked.append(f"run {rid} is locked and holds both records")
    return {
        "keeper": keeper.emp_no, "duplicate": dup.emp_no,
        "moves": {k: v for k, v in counts.items() if v},
        "same_day_attendance": [d.isoformat() for d in days],
        "same_run_payroll": runs,
        "blocked": blocked,
    }


def merge(keeper, dup, actor):
    """Move everything onto `keeper` and retire `dup`.

    Where both records cover the same day or the same run, the keeper's row
    stands and the duplicate's is dropped: the keeper is the record with the
    history, and two rows for one man on one day were never both true.
    """
    if keeper.pk == dup.pk:
        return None, "That is the same record."
    p = plan(keeper, dup)
    if p["blocked"]:
        return None, "; ".join(p["blocked"])

    with transaction.atomic():
        days, runs = _collisions(keeper, dup)
        dropped_days = Attendance.objects.filter(
            employee=dup, day__in=days).count()
        Attendance.objects.filter(employee=dup, day__in=days).delete()
        Attendance.objects.filter(employee=dup).update(employee=keeper)

        dropped_lines = PayrollLine.objects.filter(
            employee=dup, run_id__in=runs).count()
        PayrollLine.objects.filter(employee=dup, run_id__in=runs).delete()
        PayrollLine.objects.filter(employee=dup).update(employee=keeper)

        for model in SIMPLE:
            model.objects.filter(employee=dup).update(employee=keeper)

        # He is working somewhere, or he would not have been duplicated.
        keeper.is_active = True
        if dup.join_date and (not keeper.join_date
                              or dup.join_date < keeper.join_date):
            keeper.join_date = dup.join_date
        for field in ("passport_no", "date_of_birth", "nationality",
                      "basic_pay", "job_category_id"):
            if not getattr(keeper, field) and getattr(dup, field):
                setattr(keeper, field, getattr(dup, field))
        keeper.save()

        dup.is_active = False
        # Blank the passport so the duplicate stops colliding with the record
        # that now holds the man's history.
        dup.passport_no = ""
        dup.full_name = f"{dup.full_name} (merged into {keeper.emp_no})"
        dup.save(update_fields=["is_active", "passport_no", "full_name"])

    audit("employee", keeper.id, "EMPLOYEE_MERGED", actor=actor,
          detail={"kept": keeper.emp_no, "merged": dup.emp_no,
                  "moved": p["moves"],
                  "dropped_duplicate_attendance": dropped_days,
                  "dropped_duplicate_payroll_lines": dropped_lines})
    return {**p, "dropped_attendance": dropped_days,
            "dropped_payroll_lines": dropped_lines}, None


def transfer_from(employee, to_site, from_date, actor):
    """Move a worker to another site from a date, attendance and all.

    A merge alone leaves the days where they were entered. Rakib Hosen moved
    to Malé on 12 August but his August attendance is still tagged BVR, so
    BVR is carrying Malé's man (owner 2026-08-15). This closes the old
    allocation the day before, opens the new one, and re-tags every attendance
    row from that date onward — which is what makes the cost land on the right
    site and keeps `paid_window` splitting the month correctly between them.
    """
    from datetime import timedelta

    with transaction.atomic():
        moved = Attendance.objects.filter(
            employee=employee, day__gte=from_date).exclude(
            site=to_site)
        sites_before = sorted({a.site.code for a in moved})
        n = moved.update(site=to_site)

        # close anything still open elsewhere, the day before he moved
        closed = []
        for a in EmployeeSiteAllocation.objects.filter(
                employee=employee, to_date__isnull=True).exclude(site=to_site):
            a.to_date = from_date - timedelta(days=1)
            a.save(update_fields=["to_date"])
            closed.append(a.site.code)

        alloc = EmployeeSiteAllocation.objects.filter(
            employee=employee, site=to_site).order_by("-from_date").first()
        if alloc is None or (alloc.to_date and alloc.to_date < from_date):
            EmployeeSiteAllocation.objects.create(
                employee=employee, site=to_site, from_date=from_date)
        elif alloc.from_date > from_date:
            alloc.from_date = from_date
            alloc.to_date = None
            alloc.save(update_fields=["from_date", "to_date"])

    audit("employee", employee.id, "EMPLOYEE_ATTENDANCE_RESITED", actor=actor,
          detail={"emp_no": employee.emp_no, "to_site": to_site.code,
                  "from_date": from_date.isoformat(), "rows_moved": n,
                  "was_at": sites_before, "closed_allocations": closed})
    return {"rows_moved": n, "was_at": sites_before,
            "closed_allocations": closed}
