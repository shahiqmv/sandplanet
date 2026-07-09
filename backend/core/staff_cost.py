"""Staff cost (§6A.3, §6C.3.5) — posted at timesheet month lock.

For each employee with attendance at a site in the month:
`(basic pay × attended-day proportion at the site) + (approved OT hours ×
hourly rate × OT multiplier)`. Summed into ONE monthly `Labour & Staff`
INCURRED posting per site — immutable once the month is locked, reversed and
reposted if HR reopens (§6C.2). Per-employee pay is never exposed at site
level; the ledger carries only the site total.
"""
from decimal import Decimal

from django.db.models import Sum

from . import costing
from .audit import audit
from .models import Attendance, CostPosting, EmployeeSiteAllocation


def _param(key, default):
    from .models import CompanyParameter

    try:
        return Decimal(str(CompanyParameter.objects.get(key=key).value))
    except CompanyParameter.DoesNotExist:
        return Decimal(str(default))


def _day_weight(remark):
    if remark == "HALF_DAY":
        return Decimal("0.5")
    if remark in ("ABSENT", "SICK", "LEAVE"):
        return Decimal("0")
    return Decimal("1")


def month_staff_cost(site, year, month):
    """Per-employee staff cost at a site for a month + the site total. The
    basic pay is apportioned by attended days at this site over the
    employee's total attended days that month (so a shared employee splits
    across sites); approved OT at this site is added at the hourly rate."""
    mult = _param("ot_multiplier", "1.25")
    div = _param("hourly_rate_divisor", "240")

    site_att = Attendance.objects.filter(
        site=site, day__year=year, day__month=month).select_related(
        "employee")
    emp_ids = {a.employee_id for a in site_att}
    # total attended days across ALL sites that month (apportionment base)
    total_days = {}
    for a in Attendance.objects.filter(
            employee_id__in=emp_ids, day__year=year, day__month=month):
        total_days[a.employee_id] = total_days.get(
            a.employee_id, Decimal("0")) + _day_weight(a.remark)
    here = {}
    for a in site_att:
        e = here.setdefault(a.employee_id, {
            "emp": a.employee, "days": Decimal("0"), "ot": Decimal("0")})
        e["days"] += _day_weight(a.remark)
        e["ot"] += a.ot_approved or Decimal("0")

    rows, total = [], Decimal("0")
    for eid, e in here.items():
        basic = e["emp"].basic_pay or Decimal("0")
        td = total_days.get(eid, Decimal("0"))
        prop = (e["days"] / td) if td else Decimal("0")
        basic_portion = (basic * prop).quantize(Decimal("0.01"))
        hourly = (basic / div).quantize(Decimal("0.01")) if div else \
            Decimal("0")
        ot_amount = (e["ot"] * hourly * mult).quantize(Decimal("0.01"))
        cost = basic_portion + ot_amount
        total += cost
        rows.append({"emp_no": e["emp"].emp_no,
                     "full_name": e["emp"].full_name,
                     "days": e["days"], "ot_hours": e["ot"],
                     "basic_portion": basic_portion, "ot_amount": ot_amount,
                     "cost": cost})
    return rows, total


def _staff_head():
    return costing.head("Labour & Staff")


def _active_originals(site, year, month):
    """Non-reversed STAFF postings for this site+month that are not already
    reversed."""
    reversed_ids = set(CostPosting.objects.filter(
        reversal_of__site=site, reversal_of__source="STAFF",
        reversal_of__staff_year=year, reversal_of__staff_month=month)
        .values_list("reversal_of_id", flat=True))
    return CostPosting.objects.filter(
        site=site, source="STAFF", staff_year=year, staff_month=month,
        reversal_of__isnull=True).exclude(id__in=reversed_ids)


def post_staff_cost(site, year, month, actor):
    """Post the month's Labour & Staff INCURRED cost for a site (at lock).
    Idempotent — skips if an active posting already exists for the period."""
    if _active_originals(site, year, month).exists():
        return None
    _, total = month_staff_cost(site, year, month)
    if total <= 0:
        return None
    posting = costing.post(
        site=site, cost_head=_staff_head(), state="INCURRED", source="STAFF",
        amount=total, staff_year=year, staff_month=month, actor=actor)
    audit("cost_posting", posting.id, "STAFF_COST_POSTED", actor=actor,
          detail={"site": site.code, "period": f"{year}-{month:02d}",
                  "amount": str(total)})
    return posting


def reverse_staff_cost(site, year, month, actor):
    """Reverse the month's staff cost (at HR reopen) — negative mirror."""
    reversals = []
    for orig in _active_originals(site, year, month):
        reversals.append(costing.post(
            site=orig.site, cost_head=orig.cost_head, state=orig.state,
            source="STAFF", amount=-orig.amount, staff_year=year,
            staff_month=month, reversal_of=orig, actor=actor))
    if reversals:
        audit("cost_posting", reversals[0].id, "STAFF_COST_REVERSED",
              actor=actor, detail={"site": site.code,
                                   "period": f"{year}-{month:02d}"})
    return reversals


def current_run_rate():
    """Projected monthly staff cost from the CURRENT headcount — active
    employees on an open site allocation, summed by site. A run-rate, not a
    posting; basic pay only (OT is variable). Per-site totals + head counts;
    never per-employee pay."""
    from .models import Site

    rows = []
    grand_head = 0
    grand_basic = Decimal("0")
    for site in Site.objects.filter(status=Site.Status.ACTIVE) \
            .order_by("code"):
        allocs = EmployeeSiteAllocation.objects.filter(
            site=site, to_date__isnull=True,
            employee__is_active=True).select_related("employee")
        headcount = 0
        basic = Decimal("0")
        by_cat = {}
        for a in allocs:
            emp = a.employee
            headcount += 1
            basic += emp.basic_pay or Decimal("0")
            cat = emp.job_category.name if emp.job_category_id else \
                "Uncategorised"
            c = by_cat.setdefault(cat, {"count": 0, "basic": Decimal("0")})
            c["count"] += 1
            c["basic"] += emp.basic_pay or Decimal("0")
        if headcount == 0:
            continue
        grand_head += headcount
        grand_basic += basic
        rows.append({
            "site": site.code, "site_name": site.name,
            "headcount": headcount, "monthly_basic": basic,
            "by_category": [{"category": k, "count": v["count"],
                             "monthly_basic": v["basic"]}
                            for k, v in sorted(by_cat.items())],
        })
    return {"sites": rows, "total_headcount": grand_head,
            "total_monthly_basic": grand_basic}


def history(site=None):
    """Past-months salary summary from the locked Labour & Staff postings —
    net (originals + reversals) per site per month."""
    qs = CostPosting.objects.filter(source="STAFF")
    if site is not None:
        qs = qs.filter(site=site)
    grouped = qs.values("site__code", "staff_year", "staff_month") \
        .annotate(total=Sum("amount")).order_by("-staff_year", "-staff_month",
                                                 "site__code")
    return [{"site": g["site__code"], "year": g["staff_year"],
             "month": g["staff_month"], "amount": g["total"]}
            for g in grouped if g["total"]]
