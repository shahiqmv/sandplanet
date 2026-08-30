"""Payroll computation helpers.

Kept separate from the HR views so the monthly run and the payslip share one
source of truth for pay maths. Money is quantised to 2dp at the edges.
"""
import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Max, Min

from .audit import audit
from .models import Attendance, CompanyParameter, Employee, SalaryAdvance

TWO = Decimal("0.01")
# LEAVE means leave WITHOUT pay and always has; PAID_LEAVE is the other kind
# and is paid like a worked day (owner 2026-08-20).
ABSENT_MARKS = ("ABSENT", "SICK", "LEAVE")
PAID_MARKS = ("PRESENT", "PAID_LEAVE")
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
    if line.excluded:
        # Paid off in cash when he left; the line stays for the record but
        # pays nothing (owner 2026-08-14).
        z = Decimal("0.00")
        return {"daily_rate": z, "earned_basic": z, "friday_pay": z,
                "ot_pay": z, "allowance": z, "gross": z, "deductions": z,
                "net": z}
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

    But the paperwork does not outrank the register. Those two dates are
    administrative: BVR's whole workforce carries `from_date` 2026-07-12, the
    day the site was loaded into the app, and Sahajalal carries a join date of
    1 August with 28 days of July attendance against his name. Clamping to
    them alone silently cut a third off an entire site's July pay. So a day
    the site actually marked this worker on is inside the window, whatever the
    dates say — and a genuine transfer still splits cleanly, because the
    register itself stops at the old site and starts at the new one
    (owner 2026-08-14).
    """
    from .models import EmployeeSiteAllocation

    start = date(year, month, 1)
    end = date(year, month, month_days(year, month))

    jd = employee.join_date
    if jd and jd > start:
        start = jd

    empty = False
    if site is not None:
        # the allocation to THIS site overlapping the month; if there are
        # several (transferred away and back), take the widest cover
        allocs = [a for a in EmployeeSiteAllocation.objects.filter(
            employee=employee, site=site, from_date__lte=end)
            if a.to_date is None or a.to_date >= date(year, month, 1)]
        if not allocs:
            # An empty window — but fall through, never return here: the
            # register below is exactly what rescues a worker whose
            # allocation was filed a month late.
            start, end = end + timedelta(days=1), end
            empty = True
        else:
            a_start = min(a.from_date for a in allocs)
            a_ends = [a.to_date for a in allocs]
            a_end = end if any(e is None for e in a_ends) else max(a_ends)
            start = max(start, a_start)
            end = min(end, a_end)

    work_week = set(site.working_days) if site is not None else {6, 7, 1, 2, 3, 4}
    marks = Attendance.objects.filter(employee=employee, day__year=year,
                                      day__month=month)
    if site is not None:
        marks = marks.filter(site=site)
    span = marks.aggregate(first=Min("day"), last=Max("day"))
    if span["first"]:
        if empty:
            # No allocation covers the month at all, so the register is the
            # ONLY evidence and it bounds the window. Stretching to the month
            # end instead would invent the rest of the month: Rakib Hosen's
            # duplicate record drew 7 days off the 2 marks a clerk left on it,
            # five of them unworked Fridays (owner 2026-08-15).
            #
            # But it cannot bound at a REST day, because nobody ever marks
            # one. MD TAQIR AHAMMED worked every day of July and was paid 30,
            # purely because the 31st was a Friday and so the last mark was
            # the 30th. Walk past the trailing rest days.
            start, end = span["first"], span["last"]
            month_end = date(year, month, month_days(year, month))
            while (end < month_end
                   and (end + timedelta(days=1)).isoweekday() not in work_week):
                end += timedelta(days=1)
        else:
            # min/max, not "or": a late-filed allocation must not cut off days
            # the site plainly marked.
            start = min(start, span["first"])
            end = max(end, span["last"])

    # ...but never back past the join date. Allocation dates are bulk-entered
    # and unreliable, so the register outranks them; the join date is HR's own
    # record and the owner is explicit that nothing before it counts. Marks
    # that fall before it — Hossain sharif picked up 1 and 2 July while a
    # clerk was fixing another man's row, two months before he joined — pay
    # nothing, and the run flags the contradiction so somebody settles which
    # of the two is wrong (owner 2026-08-15).
    if jd and start < jd:
        start = jd
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
    # Anyone the site marked during the month worked there, whatever the
    # allocation and join dates claim (owner 2026-08-14) — see paid_window.
    marks = Attendance.objects.filter(day__year=year, day__month=month)
    if site is not None:
        marks = marks.filter(site=site)
    marked_ids = set(marks.values_list("employee_id", flat=True))
    if site is not None:
        allocs = EmployeeSiteAllocation.objects.filter(
            site=site, from_date__lte=m_end).filter(
            Q(to_date__isnull=True) | Q(to_date__gte=m_start))
        emp_ids = set(allocs.values_list("employee_id", flat=True)) | marked_ids
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
    # Nobody is paid for a month they had not joined yet — unless the site
    # marked them in it, which outranks a join date that says otherwise.
    qs = qs.filter(Q(join_date__isnull=True) | Q(join_date__lte=m_end)
                   | Q(id__in=marked_ids))
    # ...and nobody is paid twice. A worker settled in full on the way out is
    # off every monthly run for the periods that settlement covered. This used
    # to be a flag somebody had to remember to tick, and the once it was
    # forgotten BVR's July run paid three men a second time (owner
    # 2026-08-14). A locked settlement's last working day cannot be forgotten.
    from .models import PayrollRun
    settled = PayrollRun.objects.filter(
        kind=PayrollRun.Kind.SETTLEMENT, status="LOCKED",
        last_working_day__gte=m_start).values_list("lines__employee_id",
                                                   flat=True)
    return qs.exclude(id__in=[i for i in settled if i])


def _attendance_prefill(employee, site, year, month, working_days,
                        cap=None):
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
    # A final settlement caps the window at the man's last working day. It is
    # the one place a stated date outranks the register, because a register
    # that keeps marking men after they have gone is exactly what a late
    # demobilisation produces (owner 2026-08-30). Passed in rather than
    # forked: these rules carry a year of corrections about rest days, half
    # days and absent weeks, and a second copy would drift from them.
    if cap is not None and cap < last:
        last = cap

    fridays = 0
    ot = Decimal("0")
    marked = {}                      # day -> remark; the day loop below reads
                                     # this, so a blank day stays blank
    absent_by_week = {}              # ISO (year, week) -> genuine absences
    for a in qs:
        if a.day < start or a.day > last:
            continue      # outside the paid window — a stray row from before
                          # they joined, or after they left this site
        marked[a.day] = a.remark
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

    # Day by day, because "the whole window minus the days marked absent"
    # pays for days nobody ever recorded. Three BVR workers with two marks
    # each were being paid 31 days, and two more with thirteen marks were paid
    # thirty (owner 2026-08-14).
    #
    #   working day — paid only if the register says they worked it; a half
    #                 day is half a day, as it already is in the cost ledger
    #                 (staff_cost._day_weight), though payroll had been
    #                 paying it in full;
    #   rest day    — paid as part of the monthly entitlement whether worked
    #                 or not, unless it was itself an absence or the week was
    #                 mostly absence (owner 2026-08-13: EMP-0078 drew 8 days'
    #                 pay for 5 days of work on three free Fridays).
    #
    # Where a site keeps a complete register this lands on exactly the old
    # figure — SSL's 28 lines did not move by a single day.
    # Nothing recorded at all is missing data, not a month of work: two BVR
    # men drew MVR 16,500 between them on an empty register. Not even the rest
    # days are owed, since nothing says they were here (owner 2026-08-14).
    if not marked:
        return Decimal(0), Decimal("0"), 0, 0

    limit = rest_day_absence_limit()
    days = Decimal(0)
    rest_paid = 0            # unworked rest days the PM may still strike
    day = start
    while day <= last:
        mark = marked.get(day)
        if day.isoweekday() not in work_week:
            if mark == "PRESENT":
                days += 1        # he turned up on his rest day; it is his
                                 # however the rest of the week went
            elif (mark not in ABSENT_MARKS
                    and absent_by_week.get(day.isocalendar()[:2], 0) <= limit):
                days += 1
                if mark is None:
                    rest_paid += 1
        elif mark in PAID_MARKS:
            days += 1            # worked, or away on PAID leave
        elif mark == "HALF_DAY":
            days += Decimal("0.5")
        day += timedelta(days=1)

    return days, ot, fridays, rest_paid


def marked_but_unpayable(site, currency, year, month):
    """Workers the register names for this month who have no payable day.

    A man who joined in August has no business on a July run even at zero
    (owner 2026-08-15) — but he is only ever there because something is wrong,
    so he is reported instead of dropped in silence. That is the whole lesson
    of this month: Sahajalal's 28 days of July went unnoticed precisely
    because a worker could disappear off a run without a word.

    Returns [{"emp_no", "full_name", "marked", "join_date"}].
    """
    out = []
    for e in eligible_workers(site, currency, year, month).select_related(
            "job_category"):
        w_start, w_end = paid_window(e, site, year, month)
        if w_start <= w_end:
            continue
        qs = Attendance.objects.filter(employee=e, day__year=year,
                                       day__month=month)
        if site is not None:
            qs = qs.filter(site=site)
        n = qs.count()
        if n:
            out.append({"emp_no": e.emp_no, "full_name": e.full_name,
                        "marked": n,
                        "join_date": e.join_date.isoformat()
                        if e.join_date else None})
    return out


def register_summary(run):
    """Per worker on `run`, what the attendance register actually holds for
    the month: {employee_id: {"marked": n, "present": n, "absent": n}}.

    The BVR run paid two men a full month each with no attendance row at all,
    and cut eleven days off everyone else, and nothing on the screen showed
    either. Days paid is a computed number; this is the evidence behind it, so
    a PM can see the two disagree (owner 2026-08-14). One query for the run.
    """
    from django.db.models import Count, Q

    qs = Attendance.objects.filter(
        employee_id__in=run.lines.values_list("employee_id", flat=True),
        day__year=run.year, day__month=run.month)
    if run.site_id:
        qs = qs.filter(site_id=run.site_id)
    rows = qs.values("employee_id").annotate(
        marked=Count("id"),
        present=Count("id", filter=Q(remark="PRESENT")),
        absent=Count("id", filter=Q(remark__in=ABSENT_MARKS)),
        first=Min("day"))
    joined = dict(Employee.objects.filter(
        id__in=run.lines.values_list("employee_id", flat=True)).values_list(
        "id", "join_date"))
    out = {}
    for r in rows:
        jd = joined.get(r["employee_id"])
        # The register and the join date can flatly contradict each other, and
        # neither is reliably right: Sahajalal is down as joining 1 August
        # with 28 days of July behind him, while Hossain sharif joined on the
        # 5th of August and has two July days marked against him. One is a bad
        # join date, the other a bad mark. The engine pays what the register
        # says and says so here, rather than quietly picking a winner — HR
        # fixes the date or the site fixes the mark (owner 2026-08-14).
        out[r["employee_id"]] = {
            "marked": r["marked"], "present": r["present"],
            "absent": r["absent"],
            "joined_after": (jd.isoformat()
                             if jd and r["first"] and jd > r["first"] else None),
        }
    return out


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
                continue        # no payable day in this month at this site.
                                # If the register names him anyway the run
                                # says so — see marked_but_unpayable.
            days, ot, fridays, _rest = _attendance_prefill(
                emp, site, year, month, working_days)
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
    if action == "reopen":
        return st == "LOCKED" and role in ("HO_HR", "FINANCE", "ADMIN")
    return False


def set_run_status(run, action, actor, reason=""):
    """Move a run through the verification chain (owner 2026-08-12).
    Returns (run, error).

    Approving also raises the payroll PYR and locks the run, in one
    transaction: a run left approved with no payment behind it is the gap this
    was built to close, so a failure anywhere takes the approval with it.
    """
    from django.db import transaction
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
    with transaction.atomic():
        run.save()
    audit("payroll_run", run.id, f"PAYROLL_RUN_{action.upper()}", actor=actor,
          to_state=target, detail={"period": f"{run.year}-{run.month:02d}",
                                   "site": run.site.code if run.site_id
                                   else "ALL", "reason": reason})
    _notify_run(run, action, actor)

    if action == "approve":
        # The Director's approval is the end of the decision-making, so the
        # run stops being editable there and the money starts moving. Locking
        # used to be a button somebody had to remember to press, which left
        # approved runs sitting unposted and unpaid (owner 2026-08-15).
        #
        # A run with nothing payable on it still locks — it has a cost to post
        # of zero and simply needs no payment raising.
        net = sum((compute_line(l)["net"] for l in run.lines.all()),
                  Decimal("0"))
        try:
            with transaction.atomic():
                if net > 0:
                    _, err = raise_payroll_pyr(run, actor)
                    if err:
                        raise ValueError(err)
                lock_run(run, actor)
        except ValueError as exc:
            run.status, run.approved_by, run.approved_at = (
                "PD_REVIEW", None, None)
            run.save(update_fields=["status", "approved_by", "approved_at"])
            return None, str(exc)
        run.refresh_from_db()
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

    changed, added, stale, removed = [], [], [], []
    with transaction.atomic():
        for line in run.lines.select_related("employee").all():
            emp = line.employee
            if emp.id not in eligible:
                stale.append(emp.emp_no)
                # An empty line for a worker with no payable day is pure
                # noise — an August joiner on a July run (owner 2026-08-15).
                # It goes, and the run still names him in
                # marked_but_unpayable. A line HR has put money on stays put
                # and is reported instead: that is their entry to withdraw,
                # not ours.
                w_start, w_end = paid_window(emp, site, run.year, run.month)
                # Only what a person typed counts as a reason to keep the
                # line. `advance` and `loan` are derived from paid advance
                # PYRs and recomputed on every refresh, so counting them kept
                # KABIR and MD RUBEL on SSL's run at minus 2,000 apiece for a
                # site they never worked at (owner 2026-08-15). Their advance
                # is recovered on the run for the site where they did work.
                empty_line = not any([line.allowance, line.penalty,
                                      line.amount_to_site,
                                      line.amount_to_office])
                # Only when there is genuinely no payable day in the month.
                # "Not eligible" alone is too broad: a leaver whose allocation
                # was never closed is ineligible yet worked the month, and
                # deleting his line would be the very fault this run exposed.
                if w_start > w_end and empty_line:
                    line.delete()
                    removed.append(emp.emp_no)
                continue
            days, ot, fridays, rest_paid = _attendance_prefill(
                emp, site, run.year, run.month, run.working_days)
            if line.rest_day_revoked:
                days = max(days - rest_paid, 0)
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
            # A worker only just added to the run has no PM decision yet.
            days, ot, fridays, _rest = _attendance_prefill(
                emp, site, run.year, run.month, run.working_days)
            ded = deductions_for(emp, run.year, run.month)
            PayrollLine.objects.create(
                run=run, employee=emp, site_id=emp.current_site_id(),
                basic_pay=emp.basic_pay or 0, ot_rate=emp.ot_rate(),
                days_worked=days, ot_hours=ot, fridays_worked=fridays,
                advance=ded["advance"], loan=ded["loan"])
            added.append(emp.emp_no)
    if changed or added:
        reset_to_draft(run, actor, "figures refreshed from attendance")
    summary = {"changed": changed, "added": added, "no_longer_eligible": stale,
               "removed": removed}
    audit("payroll_run", run.id, "PAYROLL_RUN_REFRESHED", actor=actor,
          detail={"period": f"{run.year}-{run.month:02d}",
                  "site": site.code if site else "ALL",
                  "changed": len(changed), "added": len(added),
                  "no_longer_eligible": stale, "removed": removed})
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
        if run.kind == "SETTLEMENT":
            # Locking a settlement is the moment the exit becomes a fact: the
            # men are deactivated and their allocations closed on the real
            # last working day, not on whatever day the paperwork landed.
            from .payroll_settlement import apply_settlement
            apply_settlement(run, actor)


# Authorisation on a payment voucher is the commitment point — the cash goes
# out then. Finance's "paid" stamp is bookkeeping that follows, and often
# late: eleven July advance PYRs worth MVR 75,650 were still sitting
# AUTHORISED in mid-August, so payroll was paying those men in full while
# holding an advance it could not see (owner 2026-08-15).
RECOVERABLE_ADVANCE_STATUSES = ("PAID", "AUTHORISED")


def deductions_for(employee, year, month):
    """Advance + loan installments due for this worker in this payroll period.

    Counted from the moment the PYR is authorised, not when Finance gets round
    to marking it paid (owner 2026-08-15). An advance falls in one period; a
    loan spreads equally over its `months`."""
    period = year * 12 + (month - 1)
    advance = Decimal("0")
    loan = Decimal("0")
    rows = SalaryAdvance.objects.filter(
        employee=employee,
        document__status__in=RECOVERABLE_ADVANCE_STATUSES).select_related(
        "document")
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


def set_rest_day_revoked(line, revoked, actor):
    """Strike (or restore) a worker's unworked rest days on one payroll line.

    The site PM is the person who knows a worker was absent through the week
    and did not earn the rest day (owner 2026-08-13). Recorded as a decision
    on the line, not a hand-edited day count, so a later "Refresh from
    attendance" recomputes the days and reapplies it rather than silently
    undoing it.

    Deliberately does NOT bounce the run back to HR the way an HR edit does —
    the PM makes this call *during* their own verification, and resetting to
    draft would make it impossible to act on.
    """
    run = line.run
    if run.status == "LOCKED":
        return None, "The run is locked."
    revoked = bool(revoked)
    days, ot, fridays, rest_paid = _attendance_prefill(
        line.employee, run.site, run.year, run.month, run.working_days)
    if revoked:
        days = max(days - rest_paid, 0)
    line.rest_day_revoked = revoked
    line.days_worked = days
    line.save(update_fields=["rest_day_revoked", "days_worked"])
    audit("payroll_line", line.id,
          "REST_DAY_REVOKED" if revoked else "REST_DAY_RESTORED", actor=actor,
          detail={"run": run.id, "emp_no": line.employee.emp_no,
                  "rest_days": rest_paid, "days_now": str(days)})
    return line, None


def set_excluded(line, excluded, reason, actor):
    """Take a worker off a run's payout, or put them back.

    For the man who was paid off in cash when he left and would otherwise be
    paid a second time by the monthly run (owner 2026-08-14). The line is not
    deleted: it keeps its days and its attendance, and simply pays nothing, so
    the record still shows he worked the month and why he was not paid for it.

    Like the rest-day decision, this survives "Refresh from attendance" — it
    is a judgement about the man, not a number derived from the register.
    """
    run = line.run
    if run.status == "LOCKED":
        return None, "The run is locked."
    excluded = bool(excluded)
    if excluded and not (reason or "").strip():
        return None, "Say why this worker is being left off the payout."
    line.excluded = excluded
    line.excluded_reason = (reason or "").strip()[:200] if excluded else ""
    line.save(update_fields=["excluded", "excluded_reason"])
    audit("payroll_line", line.id,
          "PAYROLL_LINE_EXCLUDED" if excluded else "PAYROLL_LINE_RESTORED",
          actor=actor, detail={"run": run.id, "emp_no": line.employee.emp_no,
                               "reason": line.excluded_reason})
    return line, None


def raise_payroll_pyr(run, actor):
    """Raise the payment request that pays a run's workers.

    The Director approving the run IS the approval — a second one on the PYR
    would be the same person signing off the same money twice — so it clears
    straight to a Payment Voucher for the Signatory, the route rent and other
    Finance-initiated payments already take.

    Capitalized on purpose: locking the run posts the labour cost itself, so
    this PYR must post nothing or July would be counted twice (owner
    2026-08-15). It moves the money; the run books the cost.
    """
    from django.db import transaction

    from .models import CostHead, Document, DocumentRevision, Site
    from .numbering import next_ref
    from .payments import _set_status, create_payment_request

    if run.payment_request_id:
        return run.payment_request, None
    net = sum((compute_line(l)["net"] for l in run.lines.all()), Decimal("0"))
    if net <= 0:
        return None, "There is nothing to pay on this run."
    head = CostHead.objects.filter(name="Labour & Staff",
                                   is_active=True).first()
    if head is None:
        return None, "No 'Labour & Staff' cost head to charge the payroll to."
    # The combined USD run spans every site, so it has none of its own; Head
    # Office pays it.
    site = run.site or Site.objects.filter(is_head_office=True).first()
    if site is None:
        return None, "No site to raise the payment request against."

    to_site = sum((Decimal(l.amount_to_site or 0) for l in run.lines.all()),
                  Decimal("0"))
    to_office = sum((Decimal(l.amount_to_office or 0) for l in run.lines.all()),
                    Decimal("0"))
    period = f"{run.year}-{run.month:02d}"
    label = f"{run.site.code if run.site_id else 'All sites'} {period}"
    purpose = (f"Salaries for {label} — {run.lines.count()} worker(s), "
               f"net {run.currency} {net:,.2f}.")
    if to_site or to_office:
        purpose += (f" Paid at site {run.currency} {to_site:,.2f}; "
                    f"from office {run.currency} {to_office:,.2f}.")

    with transaction.atomic():
        ref = next_ref("PYR", site)
        doc = Document.objects.create(
            doc_type="PYR", ref=ref, site=site, doc_date=date.today(),
            status="DRAFT", created_by=actor)
        rev = DocumentRevision.objects.create(
            document=doc, rev_label="R0", created_by=actor,
            payload={"kind": "payroll", "purpose": purpose,
                     "payroll_run": run.id, "period": period})
        doc.current_revision = rev
        doc.save(update_fields=["current_revision"])
        pr, err = create_payment_request(doc, {
            "cost_head_id": head.id,
            "payee": f"Payroll — {label}",
            "currency": run.currency,
            "amount_requested": net,
            "purpose": purpose,
            "payment_method": "BANK",
            "payment_type": "DIRECT",
            "has_supporting_doc": True,   # the run and its report ARE the doc
        }, actor)
        if err:
            transaction.set_rollback(True)
            return None, err
        pr.is_capitalized = True          # the run posts the cost, not the PYR
        pr.origin = "FINANCE"             # salaries — straight to the voucher
        pr.save(update_fields=["is_capitalized", "origin"])
        _set_status(doc, "SUBMITTED", "SUBMIT", actor, purpose)
        _set_status(doc, "DIRECTOR_APPROVED", "CLEAR_TO_VOUCHER", actor,
                    "Payroll approved by the Director — to Finance for payment")
        run.payment_request = doc
        run.save(update_fields=["payment_request"])
    audit("payroll_run", run.id, "PAYROLL_PYR_RAISED", actor=actor,
          detail={"ref": doc.ref, "amount": str(net),
                  "currency": run.currency, "period": period})
    return doc, None


def reopen_run(run, actor):
    """Unlock a run so its figures can be corrected.

    Locking is automatic now, which makes a way back essential: before, a
    wrong run could sit locked for ever because nothing in the app could
    reopen it. Allowed only while nobody has committed to the money — once
    the Signatory has authorised the PYR or Finance has paid it, the way back
    is to withdraw that payment, not to quietly rewrite the payroll behind it
    (owner 2026-08-15).

    Reverses the labour cost the lock posted and cancels the PYR.
    """
    from django.db import transaction

    from . import staff_cost
    from .models import Site

    if run.status != "LOCKED":
        return None, "This run is not locked."
    doc = run.payment_request
    if doc is not None:
        pr = getattr(doc, "payment_request", None)
        if pr and pr.paid_date:
            return None, (f"{doc.ref} has already been paid. Withdraw the "
                          "payment first.")
        if pr and pr.authorised_at:
            return None, (f"{doc.ref} is authorised on a payment voucher. "
                          "Withdraw the authorisation first.")
        if doc.status in ("PAID", "CANCELLED"):
            return None, f"{doc.ref} is {doc.status.lower()}."

    with transaction.atomic():
        for site_id in {l.site_id for l in run.lines.all() if l.site_id}:
            staff_cost.reverse_staff_cost(Site.objects.get(pk=site_id),
                                          run.year, run.month, actor)
        if doc is not None:
            doc.status = "CANCELLED"
            doc.save(update_fields=["status"])
            run.payment_request = None
        run.status = "DRAFT"
        run.locked_by = None
        run.locked_at = None
        run.save(update_fields=["status", "locked_by", "locked_at",
                                "payment_request"])
    audit("payroll_run", run.id, "PAYROLL_RUN_REOPENED", actor=actor,
          detail={"period": f"{run.year}-{run.month:02d}",
                  "cancelled_pyr": doc.ref if doc else None})
    return run, None
