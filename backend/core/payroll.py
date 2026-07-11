"""Payroll computation helpers.

Kept separate from the HR views so the monthly run and the payslip share one
source of truth for pay maths. Money is quantised to 2dp at the edges.
"""
import calendar
from decimal import ROUND_HALF_UP, Decimal

from .models import Attendance, Employee, SalaryAdvance

TWO = Decimal("0.01")
ABSENT_MARKS = ("ABSENT", "SICK", "LEAVE")


def q(v):
    return Decimal(v).quantize(TWO, rounding=ROUND_HALF_UP)


def compute_line(line):
    """Derive the money for one PayrollLine from its stored inputs. Friday work
    is one extra day at the daily rate; OT is hours × the snapshot rate."""
    wd = line.run.working_days or 1
    daily = Decimal(line.basic_pay) / Decimal(wd)
    earned_basic = q(daily * Decimal(line.days_worked))
    friday_pay = q(daily * Decimal(line.fridays_worked))
    ot_pay = q(Decimal(line.ot_hours) * Decimal(line.ot_rate))
    allowance = q(line.allowance)
    gross = q(earned_basic + friday_pay + ot_pay + allowance)
    deductions = q(Decimal(line.penalty) + Decimal(line.advance)
                   + Decimal(line.loan))
    net = q(gross - deductions)
    return {
        "daily_rate": q(daily), "earned_basic": earned_basic,
        "friday_pay": friday_pay, "ot_pay": ot_pay, "allowance": allowance,
        "gross": gross, "deductions": deductions, "net": net,
    }


def month_days(year, month):
    return calendar.monthrange(year, month)[1]


def _attendance_prefill(employee, site, year, month, working_days):
    """Days worked (working_days − absences) and approved OT hours for a worker
    in a month, from attendance. Falls back to full attendance when none."""
    qs = Attendance.objects.filter(employee=employee, day__year=year,
                                   day__month=month)
    if site is not None:
        qs = qs.filter(site=site)
    absents = sum(1 for a in qs if a.remark in ABSENT_MARKS)
    ot = sum((a.ot_approved or 0 for a in qs), Decimal("0"))
    days = max(working_days - absents, 0)
    return Decimal(days), ot


def generate_run(*, site, currency, year, month, working_days, actor):
    """Create a draft run and a prefilled line per eligible worker. MVR runs
    are scoped to one site; the USD run spans all sites (site=None)."""
    from django.db import transaction

    from .models import EmployeeSiteAllocation, PayrollLine, PayrollRun

    with transaction.atomic():
        run = PayrollRun.objects.create(
            site=site, currency=currency, year=year, month=month,
            working_days=working_days, created_by=actor)
        if site is not None:
            emp_ids = EmployeeSiteAllocation.objects.filter(
                site=site, to_date__isnull=True).values_list(
                "employee_id", flat=True)
            workers = Employee.objects.filter(
                id__in=emp_ids, is_active=True, currency=currency)
        else:  # USD combined across all sites
            workers = Employee.objects.filter(is_active=True,
                                              currency=currency)
        for emp in workers.select_related("job_category").order_by("emp_no"):
            days, ot = _attendance_prefill(emp, site, year, month, working_days)
            ded = deductions_for(emp, year, month)
            PayrollLine.objects.create(
                run=run, employee=emp, site_id=emp.current_site_id(),
                basic_pay=emp.basic_pay or 0, ot_rate=emp.ot_rate(),
                days_worked=days, ot_hours=ot,
                advance=ded["advance"], loan=ded["loan"])
    return run


def lock_run(run, actor):
    """Freeze the run and post its labour cost — the authoritative actual,
    replacing the M7 estimate: per affected site, reverse that site's existing
    STAFF estimate for the period, then post the payroll gross."""
    from collections import defaultdict

    from django.db import transaction
    from django.utils import timezone

    from . import costing, staff_cost
    from .models import CostHead, Site

    if run.status == "LOCKED":
        return
    head = CostHead.objects.filter(name="Labour & Staff").first()
    by_site = defaultdict(Decimal)
    for line in run.lines.all():
        by_site[line.site_id] += compute_line(line)["gross"]
    with transaction.atomic():
        for site_id, gross in by_site.items():
            if not site_id or gross <= 0 or head is None:
                continue
            site = Site.objects.get(pk=site_id)
            staff_cost.reverse_staff_cost(site, run.year, run.month, actor)
            costing.post(site=site, cost_head=head, state="INCURRED",
                         source="STAFF", amount=gross, currency=run.currency,
                         staff_year=run.year, staff_month=run.month,
                         actor=actor)
        run.status = "LOCKED"
        run.locked_by = actor
        run.locked_at = timezone.now()
        run.save(update_fields=["status", "locked_by", "locked_at"])


def deductions_for(employee, year, month):
    """Advance + loan installments due for this worker in this payroll period,
    from salary-advance PYRs that Finance has PAID. An advance falls in one
    period; a loan spreads equally over its `months`."""
    period = year * 12 + (month - 1)
    advance = Decimal("0")
    loan = Decimal("0")
    rows = SalaryAdvance.objects.filter(
        employee=employee, document__status="PAID").select_related("document")
    for a in rows:
        start = a.period_year * 12 + (a.period_month - 1)
        n = max(a.months, 1)
        if start <= period < start + n:
            installment = q(a.amount / n)
            if a.kind == SalaryAdvance.Kind.LOAN:
                loan += installment
            else:
                advance += installment
    return {"advance": advance, "loan": loan}
