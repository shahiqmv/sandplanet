"""Payroll computation helpers.

Kept separate from the HR views so the monthly run and the payslip share one
source of truth for pay maths. Money is quantised to 2dp at the edges.
"""
import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from .audit import audit
from .models import Attendance, CompanyParameter, Employee, SalaryAdvance

TWO = Decimal("0.01")
ABSENT_MARKS = ("ABSENT", "SICK", "LEAVE")
FRIDAY_OT_HOURS_DEFAULT = Decimal("12")
# A rest day is part of the monthly entitlement and is normally paid even
# though nobody marks it — that is why the register shows a blank there. But a
# worker who was absent most of the week has not earned it: EMP-0078 was paid
# 8 days for 5 days of work in July because three unworked Fridays came free
# (owner 2026-08-13). Above this many ABSENT days in a week, the week's rest
# days are not paid.
REST_DAY_ABSENCE_LIMIT_DEFAULT = 3


def friday_ot_hours():
    """Hours of OT a worked Friday earns (company policy, owner 2026-08-12:
    a Friday pays 12 × the worker's OT rate — NOT an extra day of basic).
    Editable via the `friday_ot_hours` company parameter."""
    try:
        v = (CompanyParameter.objects.get(key="friday_ot_hours").value
             or "").strip()
        return Decimal(v) if v else FRIDAY_OT_HOURS_DEFAULT
    except (CompanyParameter.DoesNotExist, ArithmeticError, ValueError):
        return FRIDAY_OT_HOURS_DEFAULT


def rest_day_absence_limit():
    """Absences in a week above which that week's unworked rest days are not
    paid (owner 2026-08-13). Editable via the `rest_day_absence_limit`
    company parameter, like `friday_ot_hours`."""
    try:
        v = (CompanyParameter.objects.get(
            key="rest_day_absence_limit").value or "").strip()
        return int(v) if v else REST_DAY_ABSENCE_LIMIT_DEFAULT
    except (CompanyParameter.DoesNotExist, TypeError, ValueError):
        return REST_DAY_ABSENCE_LIMIT_DEFAULT


def q(v):
    return Decimal(v).quantize(TWO, rounding=ROUND_HALF_UP)


def compute_line(line, fri_hours=None):
    """Derive the money for one PayrollLine from its stored inputs.

    A worked Friday pays `friday_ot_hours` × the worker's OT rate (company
    policy, owner 2026-08-12) — it no longer adds a day of basic. A worker
    with no OT rate therefore earns nothing extra for a Friday, which is the
    owner's explicit choice. OT hours recorded ON a Friday are excluded from
    `ot_hours` at prefill so the day can't be paid twice."""
    wd = line.run.working_days or 1
    fri_h = friday_ot_hours() if fri_hours is None else Decimal(fri_hours)
    daily = Decimal(line.basic_pay) / Decimal(wd)
    earned_basic = q(daily * Decimal(line.days_worked))
    friday_pay = q(fri_h * Decimal(line.fridays_worked) * Decimal(line.ot_rate))
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


def paid_window(employee, site, year, month):
    """The days of `month` this worker is owed pay for AT THIS SITE.

    Bounded by three things, because any of them can start or end mid-month:
      * the month itself,
      * the day they joined the company (`join_date`),
      * the stretch they were allocated to this site.

    Returns (start, end); end < start means they are owed nothing for the
    month — a worker allocated in August has no July window at all.

    Why the allocation matters as much as the join date: a worker who
    transfers on the 12th should be paid by their old site to the 11th and the
    new one from the 12th, and neither should pay a whole month (owner
    2026-08-13, after sites found full salaries paid to mid-month joiners).
    """
    from .models import EmployeeSiteAllocation

    start = date(year, month, 1)
    end = date(year, month, month_days(year, month))

    jd = employee.join_date
    if jd and jd > start:
        start = jd

    if site is not None:
        # the allocation to THIS site overlapping the month; if there are
        # several (transferred away and back), take the widest cover
        allocs = [a for a in EmployeeSiteAllocation.objects.filter(
            employee=employee, site=site, from_date__lte=end)
            if a.to_date is None or a.to_date >= date(year, month, 1)]
        if not allocs:
            return end + timedelta(days=1), end        # empty window
        a_start = min(a.from_date for a in allocs)
        a_ends = [a.to_date for a in allocs]
        a_end = end if any(e is None for e in a_ends) else max(a_ends)
        start = max(start, a_start)
        end = min(end, a_end)
    return start, end


def eligible_workers(site, currency, year, month):
    """Who belongs on a run for this site/currency/month.

    Membership is decided by the month, not by today. The old rule — everyone
    *currently* allocated to the site — put an August joiner on the July run
    and, worse, dropped anyone who left mid-month, who would then have been
    paid nothing for days they had actually worked (owner 2026-08-13).

    generate_run and refresh_run must agree on this, so it lives here rather
    than in both: they had already drifted once.
    """
    from django.db.models import Q

    from .models import EmployeeSiteAllocation

    m_start = date(year, month, 1)
    m_end = date(year, month, month_days(year, month))
    if site is not None:
        allocs = EmployeeSiteAllocation.objects.filter(
            site=site, from_date__lte=m_end).filter(
            Q(to_date__isnull=True) | Q(to_date__gte=m_start))
        emp_ids = allocs.values_list("employee_id", flat=True)
        # A leaver gets deactivated, so is_active alone would lose them. Keep
        # them when their allocation closed during/after the month; still
        # exclude the long-gone whose allocation was never tidied up.
        left_ids = allocs.filter(to_date__gte=m_start).values_list(
            "employee_id", flat=True)
        qs = Employee.objects.payroll_eligible().filter(
            id__in=emp_ids, currency=currency).filter(
            Q(is_active=True) | Q(id__in=left_ids))
    elif currency == "USD":                 # combined USD run
        # full-USD workers + split-pay workers (their USD basic only)
        qs = Employee.objects.payroll_eligible().filter(
            is_active=True).filter(
            Q(currency="USD")
            | Q(usd_basic_pay__gt=0, employment_type="PERMANENT"))
    else:
        qs = Employee.objects.payroll_eligible().filter(
            is_active=True, currency=currency)
    # Nobody is paid for a month they had not joined yet.
    return qs.filter(Q(join_date__isnull=True) | Q(join_date__lte=m_end))


def _attendance_prefill(employee, site, year, month, working_days):
    """Days worked (expected − absences), approved OT hours, and Fridays
    (rest days) worked for a worker in a month, from attendance. A rest day is
    any weekday not in the site's working week; being PRESENT on one is the
    7th-day work paid as an extra day.

    A worker is only expected — and paid — inside `paid_window`: days outside
    it are neither worked nor counted absent. The daily rate divisor stays the
    full month (run.working_days), so a part-month worker is paid pro-rata,
    not penalised."""
    from .models import Site

    qs = Attendance.objects.filter(employee=employee, day__year=year,
                                   day__month=month)
    if site is not None:
        qs = qs.filter(site=site)
    site_obj = site
    if site_obj is None:  # combined run — use the worker's current site
        sid = employee.current_site_id()
        site_obj = Site.objects.filter(pk=sid).first() if sid else None
    work_week = set(site_obj.working_days) if site_obj else {6, 7, 1, 2, 3, 4}

    start, last = paid_window(employee, site, year, month)
    expected = 0 if start > last else (last - start).days + 1

    absents = fridays = 0
    ot = Decimal("0")
    marked = {}                      # day -> remark, for the rest-day test
    absent_by_week = {}              # ISO (year, week) -> genuine absences
    for a in qs:
        if a.day < start or a.day > last:
            continue      # outside the paid window — a stray row from before
                          # they joined, or after they left this site
        marked[a.day] = a.remark
        if a.remark in ABSENT_MARKS:
            absents += 1
        if a.remark == "ABSENT":
            # Only a genuine absence counts towards forfeiting the rest day —
            # someone on sanctioned leave or off sick should not lose their
            # Friday on top of the day itself (owner 2026-08-13).
            wk = a.day.isocalendar()[:2]
            absent_by_week[wk] = absent_by_week.get(wk, 0) + 1
        is_friday = a.day.isoweekday() not in work_week
        if a.remark == "PRESENT" and is_friday:
            fridays += 1
            continue        # the flat Friday OT covers the whole day (owner
                            # 2026-08-12) — never add its hours again
        ot += a.ot_approved or 0

    # A rest day is unmarked and normally paid as part of the month. Drop the
    # ones in a week the worker was largely absent: EMP-0078 drew 8 days' pay
    # for 5 days of work in July because three unworked Fridays came free.
    limit = rest_day_absence_limit()
    forfeited = 0
    day = start
    while day <= last:
        if (day not in marked and day.isoweekday() not in work_week
                and absent_by_week.get(day.isocalendar()[:2], 0) > limit):
            forfeited += 1
        day += timedelta(days=1)

    days = max(expected - absents - forfeited, 0)
    return Decimal(days), ot, fridays


def is_split_pay(emp):
    """A worker paid their attendance-based basic in USD, everything else MVR
    with their site team. Permanent staff only (owner 2026-08-06)."""
    return bool(emp.usd_basic_pay and emp.usd_basic_pay > 0
                and emp.employment_type == "PERMANENT")


def generate_run(*, site, currency, year, month, working_days, actor):
    """Create a draft run and a prefilled line per eligible worker. MVR runs are
    scoped to one site; the USD run spans all sites (site=None). Split-pay
    workers (basic in USD) appear in BOTH: a basic-only line on the combined USD
    run and a no-basic line (OT/allowances/deductions) on their site MVR run."""
    from django.db import transaction

    from .models import PayrollLine, PayrollRun

    with transaction.atomic():
        run = PayrollRun.objects.create(
            site=site, currency=currency, year=year, month=month,
            working_days=working_days, created_by=actor)
        workers = eligible_workers(site, currency, year, month)
        for emp in workers.select_related("job_category").order_by("emp_no"):
            w_start, w_end = paid_window(emp, site, year, month)
            if w_start > w_end:
                continue        # no days in this month at this site
            days, ot, fridays = _attendance_prefill(emp, site, year, month,
                                                    working_days)
            split = is_split_pay(emp)
            if currency == "USD" and split:
                # basic-only, attendance-based, in USD — nothing else here
                PayrollLine.objects.create(
                    run=run, employee=emp, site_id=emp.current_site_id(),
                    basic_pay=emp.usd_basic_pay, ot_rate=Decimal("0"),
                    days_worked=days, ot_hours=Decimal("0"), fridays_worked=0)
            elif currency != "USD" and split:
                # site MVR line: no basic (paid in USD); OT (incl. rest-day
                # hours) + allowances + deductions stay MVR
                ded = deductions_for(emp, year, month)
                PayrollLine.objects.create(
                    run=run, employee=emp, site_id=emp.current_site_id(),
                    basic_pay=Decimal("0"), ot_rate=emp.ot_rate(),
                    days_worked=days, ot_hours=ot, fridays_worked=0,
                    advance=ded["advance"], loan=ded["loan"])
            else:
                ded = deductions_for(emp, year, month)
                PayrollLine.objects.create(
                    run=run, employee=emp, site_id=emp.current_site_id(),
                    basic_pay=emp.basic_pay or 0, ot_rate=emp.ot_rate(),
                    days_worked=days, ot_hours=ot, fridays_worked=fridays,
                    advance=ded["advance"], loan=ded["loan"])
    return run


def attendance_locked(site, year, month):
    """True if the site's attendance is locked for the month — the gate for
    running that site's payroll on its own (owner 2026-08-05)."""
    from .models import TimesheetMonth
    return TimesheetMonth.objects.filter(
        site=site, year=year, month=month, status="LOCKED").exists()


def unlocked_sites(year, month, currency=None):
    """Active, staffed sites whose attendance is NOT locked for the month.
    A site-wise MVR run is gated only on its own site; the combined USD run is
    gated on every USD-staffed site (pass currency="USD")."""
    from django.db.models import Q

    from .models import EmployeeSiteAllocation, Site, TimesheetMonth

    # Only direct workers gate payroll — a site staffed solely by subcontract
    # workers has no payroll and must not block the run.
    staffed_q = EmployeeSiteAllocation.objects.filter(
        to_date__isnull=True, employee__is_active=True,
        employee__engagement_type="DIRECT")
    if currency == "USD":
        # the USD run also carries split-pay workers' basic, so their sites
        # must be locked too (split pay is permanent-only).
        staffed_q = staffed_q.filter(
            Q(employee__currency="USD")
            | Q(employee__usd_basic_pay__gt=0,
                employee__employment_type="PERMANENT"))
    elif currency:
        staffed_q = staffed_q.filter(employee__currency=currency)
    staffed = set(staffed_q.values_list("site_id", flat=True))
    out = []
    for site in Site.objects.filter(status=Site.Status.ACTIVE,
                                    id__in=staffed).order_by("code"):
        if not TimesheetMonth.objects.filter(site=site, year=year, month=month,
                                             status="LOCKED").exists():
            out.append(site.code)
    return out


def generate_month(year, month, actor):
    """Generate the month's payroll: one all-sites MVR run and one all-sites USD
    run, each grouped site-wise on its report. Hard-gated — every active,
    staffed site must have locked attendance first; otherwise nothing is
    generated and the unlocked sites are returned."""
    from .models import Employee, PayrollRun

    pending = unlocked_sites(year, month)
    if pending:
        return {"blocked": True, "unlocked": pending,
                "created": [], "skipped": []}

    working_days = month_days(year, month)
    created, skipped = [], []
    for currency in ("MVR", "USD"):
        if not Employee.objects.payroll_eligible().filter(
                is_active=True, currency=currency).exists():
            continue
        label = f"{currency} — all sites"
        if PayrollRun.objects.filter(site__isnull=True, currency=currency,
                                     year=year, month=month).exists():
            skipped.append({"site": label, "reason": "already generated"})
            continue
        run = generate_run(site=None, currency=currency, year=year,
                           month=month, working_days=working_days, actor=actor)
        created.append({"site": label, "currency": currency, "run_id": run.id})
    return {"blocked": False, "unlocked": [], "created": created,
            "skipped": skipped, "working_days": working_days}


def _run_pm_ids(run):
    """Current PMs of the run's site (co-PMs share the duty). Empty for the
    site-less combined USD run — it goes straight to the PD."""
    if run.site_id is None:
        return set()
    return {u.id for u in run.site.current_pms()}


def can_act(run, user, action):
    """Whether `user` may perform `action` on `run` right now."""
    role = user.role
    st = run.status
    if action == "submit":
        return role in ("HO_HR", "FINANCE", "ADMIN", "PA") and st in (
            "DRAFT", "RETURNED")
    if action == "verify":                      # the site PM
        return st == "PM_REVIEW" and (
            role == "ADMIN" or user.id in _run_pm_ids(run))
    if action == "approve":                     # the PD
        return st == "PD_REVIEW" and role in ("DIRECTOR", "ADMIN")
    if action == "return":
        return st in ("PM_REVIEW", "PD_REVIEW") and (
            role in ("DIRECTOR", "ADMIN") or user.id in _run_pm_ids(run))
    if action == "lock":
        return st == "APPROVED" and role in ("HO_HR", "FINANCE", "ADMIN", "PA")
    return False


def set_run_status(run, action, actor, reason=""):
    """Move a run through the verification chain (owner 2026-08-12).
    Returns (run, error)."""
    from django.utils import timezone

    from .models import PayrollRun
    if run.status == "LOCKED":
        return None, "This run is locked."
    if not can_act(run, actor, action):
        return None, {
            "submit": "Only HR / Finance submits a run for verification.",
            "verify": "Only this site's PM verifies the run.",
            "approve": "Only the Director approves the run.",
            "return": "Only the site PM or the Director returns a run.",
            "lock": "The run must be approved before it can be locked.",
        }.get(action, "Not permitted.")
    if action == "return" and not (reason or "").strip():
        return None, "Give the reason you're returning it."

    if action == "submit":
        target = "PD_REVIEW" if run.site_id is None else "PM_REVIEW"
        run.submitted_by, run.submitted_at = actor, timezone.now()
        run.return_reason = ""
    elif action == "verify":
        target = "PD_REVIEW"
        run.verified_by, run.verified_at = actor, timezone.now()
    elif action == "approve":
        target = "APPROVED"
        run.approved_by, run.approved_at = actor, timezone.now()
    else:                                        # return
        target = "RETURNED"
        run.return_reason = reason.strip()
        run.verified_by = run.verified_at = None
        run.approved_by = run.approved_at = None
    if target not in PayrollRun.FLOW.get(run.status, set()):
        return None, f"Cannot move a {run.status} run to {target}."
    run.status = target
    run.save()
    audit("payroll_run", run.id, f"PAYROLL_RUN_{action.upper()}", actor=actor,
          to_state=target, detail={"period": f"{run.year}-{run.month:02d}",
                                   "site": run.site.code if run.site_id
                                   else "ALL", "reason": reason})
    _notify_run(run, action, actor)
    return run, None


def reset_to_draft(run, actor, why):
    """Any change to the figures voids the sign-offs (owner 2026-08-12) — an
    approval must never outlive the numbers it was given."""
    if run.status in ("DRAFT", "LOCKED"):
        return run
    run.status = "DRAFT"
    run.verified_by = run.verified_at = None
    run.approved_by = run.approved_at = None
    run.save()
    audit("payroll_run", run.id, "PAYROLL_RUN_REOPENED", actor=actor,
          to_state="DRAFT", detail={"why": why})
    return run


def _notify_run(run, action, actor):
    """Tell whoever the run is now waiting on."""
    from .notify import _role_users, notify_user
    where = run.site.code if run.site_id else "USD (all sites)"
    body = f"{where} · {run.year}-{run.month:02d} · {run.currency}"
    try:
        if run.status == "PM_REVIEW":
            for u in run.site.current_pms():          # every co-PM
                notify_user(u, "Salary draft — verify your site",
                            body=body, category="approval")
        elif run.status == "PD_REVIEW":
            for u in _role_users("DIRECTOR"):
                notify_user(u, "Salary draft — needs your approval",
                            body=body, category="approval")
        elif run.status == "RETURNED":
            for u in _role_users("HO_HR", "FINANCE"):
                notify_user(u, "Salary draft returned",
                            body=f"{body} — {run.return_reason}",
                            category="approval")
        elif run.status == "APPROVED":
            for u in _role_users("HO_HR", "FINANCE"):
                notify_user(u, "Salary draft approved — ready to lock",
                            body=body, category="approval")
    except Exception:                      # pragma: no cover - never block
        pass


def refresh_run(run, actor):
    """Re-prefill a DRAFT run from current attendance, rates and policy.

    Needed whenever something the run was built from changes underneath it —
    a site corrects attendance, an OT rate is fixed, or the Friday policy
    moves (owner 2026-08-12). Attendance-derived and rate fields are
    recomputed; HR's own entries (allowance, penalty) are left alone.
    Newly eligible workers are added; workers who are no longer eligible are
    reported, never silently dropped, so HR decides."""
    from django.db import transaction

    from .models import PayrollLine

    if run.status == "LOCKED":
        return None, ("This run is locked — reopen it before refreshing.")
    site, currency = run.site, run.currency
    eligible = {}
    for e in eligible_workers(site, currency, run.year,
                              run.month).select_related("job_category"):
        # An overlapping allocation is not enough: someone who joined after
        # the month ends has no payable days in it.
        w_start, w_end = paid_window(e, site, run.year, run.month)
        if w_start <= w_end:
            eligible[e.id] = e

    changed, added, stale = [], [], []
    with transaction.atomic():
        for line in run.lines.select_related("employee").all():
            emp = line.employee
            if emp.id not in eligible:
                stale.append(emp.emp_no)
                continue
            days, ot, fridays = _attendance_prefill(emp, site, run.year,
                                                    run.month,
                                                    run.working_days)
            split = is_split_pay(emp)
            before = (line.days_worked, line.ot_hours, line.fridays_worked,
                      line.ot_rate, line.basic_pay)
            if currency == "USD" and split:
                line.basic_pay = emp.usd_basic_pay or 0
                line.ot_rate = Decimal("0")
                line.days_worked, line.ot_hours, line.fridays_worked = (
                    days, Decimal("0"), 0)
            else:
                line.ot_rate = emp.ot_rate()
                line.days_worked, line.ot_hours = days, ot
                if currency != "USD" and split:
                    line.basic_pay, line.fridays_worked = Decimal("0"), 0
                else:
                    line.basic_pay = emp.basic_pay or 0
                    line.fridays_worked = fridays
                ded = deductions_for(emp, run.year, run.month)
                line.advance, line.loan = ded["advance"], ded["loan"]
            after = (line.days_worked, line.ot_hours, line.fridays_worked,
                     line.ot_rate, line.basic_pay)
            if before != after:
                changed.append(emp.emp_no)
            line.save()
        have = set(run.lines.values_list("employee_id", flat=True))
        for emp in eligible.values():
            if emp.id in have:
                continue
            days, ot, fridays = _attendance_prefill(emp, site, run.year,
                                                    run.month,
                                                    run.working_days)
            ded = deductions_for(emp, run.year, run.month)
            PayrollLine.objects.create(
                run=run, employee=emp, site_id=emp.current_site_id(),
                basic_pay=emp.basic_pay or 0, ot_rate=emp.ot_rate(),
                days_worked=days, ot_hours=ot, fridays_worked=fridays,
                advance=ded["advance"], loan=ded["loan"])
            added.append(emp.emp_no)
    if changed or added:
        reset_to_draft(run, actor, "figures refreshed from attendance")
    summary = {"changed": changed, "added": added, "no_longer_eligible": stale}
    audit("payroll_run", run.id, "PAYROLL_RUN_REFRESHED", actor=actor,
          detail={"period": f"{run.year}-{run.month:02d}",
                  "site": site.code if site else "ALL",
                  "changed": len(changed), "added": len(added),
                  "no_longer_eligible": stale})
    return summary, None


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
