"""Final settlement — paying a demobilised worker on the way out.

A man whose contract ends when he leaves the site cannot wait for a monthly
run: that run is generated after month end, then goes HR → PM → Director →
lock, and by then he has flown home. Twenty men left VKR in August owed the
whole month (owner 2026-08-30).

The arithmetic is deliberately the monthly run's, not a second formula — a
leaver must be paid the same daily rate as the man standing next to him for
the same days. What a settlement adds is three things the monthly run has no
reason to do:

  * it spans EVERY month still unpaid, not one. A man leaving on 8 September
    with August not yet locked is owed both.
  * the stated last working day CAPS the window. Everywhere else in payroll
    the register outranks the paperwork, because allocation dates were
    bulk-entered and unreliable. Here it is the other way round, and for the
    same reason: when demobilisation is filed late the register keeps marking
    men who have gone. VKR's 20 were recorded on the 29th with a real last
    day of the 24th, and were marked PRESENT for four days in between.
  * it deducts the FULL outstanding advance and loan balance, not this
    month's installment. After he flies there is nobody to deduct from.

Nothing here trusts the last working day silently: `register_conflicts`
reports every day the site marked a man present after it, so the PM settles
the contradiction before the money moves rather than after.
"""
import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .audit import audit
from .models import (Attendance, EmployeeSiteAllocation, PayrollLine,
                     PayrollRun, SalaryAdvance)
from .payroll import (RECOVERABLE_ADVANCE_STATUSES, _attendance_prefill,
                      compute_line, month_days, paid_window, q)

log = logging.getLogger(__name__)


def _period(year, month):
    return year * 12 + (month - 1)


def unpaid_months(employee, site, upto):
    """Every (year, month) up to `upto` that this worker has not been PAID for.

    Paid means a line on a LOCKED run — monthly or an earlier settlement.
    Walks back from the leaving month to the earliest month the worker has any
    evidence in (join date or a mark), so a man owed two months gets two."""
    locked = {(l.run.year, l.run.month) for l in PayrollLine.objects.filter(
        employee=employee, run__status="LOCKED",
        excluded=False).select_related("run")}

    first = employee.join_date
    marks = Attendance.objects.filter(employee=employee)
    if site is not None:
        marks = marks.filter(site=site)
    earliest_mark = marks.order_by("day").values_list("day", flat=True).first()
    if earliest_mark and (first is None or earliest_mark < first):
        first = earliest_mark
    if first is None:
        first = upto.replace(day=1)

    out = []
    p, end_p = _period(first.year, first.month), _period(upto.year, upto.month)
    while p <= end_p:
        y, m = divmod(p, 12)
        m += 1
        if (y, m) not in locked:
            out.append((y, m))
        p += 1
    return out


def settlement_window(employee, site, year, month, last_working_day):
    """The month's paid window, capped at the last working day.

    Returns (start, end); end < start means nothing is owed for the month."""
    start, end = paid_window(employee, site, year, month)
    if last_working_day < end:
        end = last_working_day
    return start, end


def outstanding_balance(employee):
    """Everything still owed on this worker's advances and loans.

    The monthly run takes one installment at a time. A settlement takes the
    lot: an unrecovered balance after the man has left the country is a debt
    with nobody to collect it from."""
    advance = Decimal("0")
    loan = Decimal("0")
    for a in SalaryAdvance.objects.filter(
            employee=employee,
            document__status__in=RECOVERABLE_ADVANCE_STATUSES):
        n = max(a.months, 1)
        installment = q(a.amount / n)
        recovered = Decimal("0")
        for line in PayrollLine.objects.filter(
                employee=employee, run__status="LOCKED", excluded=False):
            p = _period(line.run.year, line.run.month)
            start = _period(a.period_year, a.period_month)
            if start <= p < start + n:
                recovered += installment
        balance = a.amount - recovered
        if balance <= 0:
            continue
        if a.kind == SalaryAdvance.Kind.LOAN:
            loan += balance
        else:
            advance += balance
    return {"advance": q(advance), "loan": q(loan)}


def register_conflicts(employee, site, last_working_day):
    """Days the site marked this worker present AFTER his stated last day.

    Not an error to fix silently — a contradiction between two records, and
    the money turns on which is right. VKR marked twenty men present on four
    days after the date the owner gave; at stake was MVR 24,903."""
    rows = Attendance.objects.filter(
        employee=employee, day__gt=last_working_day,
        remark__in=("PRESENT", "PAID_LEAVE", "HALF_DAY"))
    if site is not None:
        rows = rows.filter(site=site)
    return sorted(r.day for r in rows.only("day"))


def preview(site, employees, last_working_day, working_days=None):
    """What the batch would be paid, without writing anything."""
    out = []
    for emp in employees:
        months = unpaid_months(emp, site, last_working_day)
        rows = []
        gross = Decimal("0")
        for (y, m) in months:
            wd = working_days or month_days(y, m)
            start, end = settlement_window(emp, site, y, m, last_working_day)
            if start > end:
                continue
            days, ot, fridays, _rest = _attendance_prefill(
                emp, site, y, m, wd, cap=last_working_day)
            if not days and not ot and not fridays:
                continue
            line = PayrollLine(run=PayrollRun(working_days=wd), employee=emp,
                               basic_pay=emp.basic_pay or 0,
                               ot_rate=emp.ot_rate(), days_worked=days,
                               ot_hours=ot, fridays_worked=fridays)
            money = compute_line(line)
            gross += money["gross"]
            rows.append({"year": y, "month": m, "start": start, "end": end,
                         "days": days, "ot_hours": ot, "fridays": fridays,
                         "gross": money["gross"]})
        bal = outstanding_balance(emp)
        deductions = bal["advance"] + bal["loan"]
        out.append({
            "employee_id": emp.id, "emp_no": emp.emp_no,
            "full_name": emp.full_name, "months": rows,
            "gross": q(gross), "advance": bal["advance"], "loan": bal["loan"],
            "net": q(gross - deductions),
            "conflicts": register_conflicts(emp, site, last_working_day),
        })
    return out


def generate_settlement(*, site, employees, last_working_day, reason, actor,
                        working_days=None, currency="MVR"):
    """Create a DRAFT settlement run for a demobilised batch.

    One run per batch, not per man: twenty leaving together is one decision,
    one approval and one payment. Lines carry the same snapshotted basic and
    OT rate a monthly line does, so a later profile change cannot rewrite what
    was paid."""
    if last_working_day > timezone.localdate():
        return None, "A last working day can't be in the future."
    people = [e for e in employees]
    if not people:
        return None, "Select at least one worker to settle."
    bad = [e.emp_no for e in people
           if e.engagement_type == "SUBCONTRACT"]
    if bad:
        return None, ("Subcontract workers are paid through a valuation, not "
                      "payroll: " + ", ".join(bad[:10]))

    with transaction.atomic():
        run = PayrollRun.objects.create(
            site=site, kind=PayrollRun.Kind.SETTLEMENT, currency=currency,
            year=last_working_day.year, month=last_working_day.month,
            working_days=working_days or month_days(last_working_day.year,
                                                    last_working_day.month),
            last_working_day=last_working_day,
            settlement_reason=(reason or "").strip(), created_by=actor)
        made = 0
        for emp in sorted(people, key=lambda e: e.emp_no or ""):
            days = Decimal(0)
            ot = Decimal("0")
            fridays = 0
            for (y, m) in unpaid_months(emp, site, last_working_day):
                wd = run.working_days
                start, end = settlement_window(emp, site, y, m,
                                               last_working_day)
                if start > end:
                    continue
                d, o, f, _rest = _attendance_prefill(emp, site, y, m, wd,
                                                     cap=last_working_day)
                days += d
                ot += o
                fridays += f
            bal = outstanding_balance(emp)
            # A line is written even at zero: a man who is owed nothing is a
            # fact worth showing the PM, and a silently missing man is how
            # somebody gets left behind.
            PayrollLine.objects.create(
                run=run, employee=emp, site_id=site.id if site else None,
                basic_pay=emp.basic_pay or 0, ot_rate=emp.ot_rate(),
                days_worked=days, ot_hours=ot, fridays_worked=fridays,
                advance=bal["advance"], loan=bal["loan"])
            made += 1
    audit("payroll_run", run.id, "SETTLEMENT_GENERATED", actor=actor,
          detail={"site": site.code if site else None, "workers": made,
                  "last_working_day": last_working_day.isoformat()})
    return run, None


def apply_settlement(run, actor):
    """Record the exits. Called when a settlement run locks.

    This is what demobilisation never did: stamp the real last working day on
    the worker and on his allocation, instead of closing at whatever day the
    paperwork happened to be approved."""
    if run.kind != PayrollRun.Kind.SETTLEMENT or not run.last_working_day:
        return
    lwd = run.last_working_day
    with transaction.atomic():
        for line in run.lines.select_related("employee"):
            emp = line.employee
            emp.is_active = False
            emp.left_on = lwd
            emp.left_reason = run.settlement_reason
            emp.save(update_fields=["is_active", "left_on", "left_reason",
                                    "updated_at"])
            # Close the allocation ON the last working day, and correct one
            # already closed later by a late demobilisation.
            for alloc in EmployeeSiteAllocation.objects.filter(
                    employee=emp).filter(
                    Q(to_date__isnull=True) | Q(to_date__gt=lwd)):
                alloc.to_date = lwd
                alloc.save(update_fields=["to_date"])
    audit("payroll_run", run.id, "SETTLEMENT_APPLIED", actor=actor,
          detail={"workers": run.lines.count(),
                  "last_working_day": lwd.isoformat()})


def settled_through(employee):
    """The last working day of this worker's most recent LOCKED settlement,
    or None. Everything up to that date has been paid in full.

    The monthly run reads this to skip a man already settled. The old guard
    was the hand-ticked `excluded` flag, used exactly once across every run on
    record — which is how BVR's July run paid three men who had been settled
    in cash on the way out (owner 2026-08-14). A date cannot be forgotten."""
    row = PayrollRun.objects.filter(
        kind=PayrollRun.Kind.SETTLEMENT, status="LOCKED",
        lines__employee=employee,
        last_working_day__isnull=False).order_by("-last_working_day").first()
    return row.last_working_day if row else None
