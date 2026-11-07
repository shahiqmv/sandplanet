"""Manpower cost analysis: what the labour on each site cost, from locked
payroll runs (owner 2026-11-07).

Labour lands where the work was done, the way the cost ledger books it at
lock: payroll.labour_shares splits a man's month across the sites he worked
(days for basic and allowances, hours for overtime, Fridays for Friday pay).
His days and hours at a site come from the same split the run stored.

Only LOCKED runs count. A month still being reviewed is named in the notes
rather than estimated, so a figure here is never one that may still change.
A PM sees the site's totals, with management staff as one line, never one
person's pay; the by-person table is for those who see pay (Context.sees_pay).
"""
from collections import defaultdict
from decimal import Decimal

from . import fx
from .models import PayrollRun
from .payroll import compute_line, labour_shares
from .permissions import is_staff_grade
from .reports import col, kpi, month_label, months_in, section, sum_rows

ZERO = Decimal("0")
STAFF_LINE = "Staff — all grades"


def _part(line, site_id):
    """(days, ot_hours, fridays, ot_share, friday_share) of a line at a site."""
    split = line.site_split or []
    if not split:
        if site_id == line.site_id or not line.site_id:
            return (Decimal(line.days_worked), Decimal(line.ot_hours),
                    Decimal(line.fridays_worked), Decimal(1), Decimal(1))
        return ZERO, ZERO, ZERO, ZERO, ZERO
    mine = [p for p in split if p.get("site") == site_id]

    def tot(k):
        return sum((Decimal(str(p.get(k) or 0)) for p in split), ZERO)

    def got(k):
        return sum((Decimal(str(p.get(k) or 0)) for p in mine), ZERO)

    ot_t, fri_t = tot("ot_hours"), tot("fridays")
    return (got("days"), got("ot_hours"), got("fridays"),
            got("ot_hours") / ot_t if ot_t else ZERO,
            got("fridays") / fri_t if fri_t else ZERO)


def build(ctx):
    rate = fx.usd_rate()
    wanted = set(ctx.site_ids)
    months = months_in(ctx.start, ctx.end)
    runs = (PayrollRun.objects.filter(status="LOCKED")
            .filter(year__gte=months[0][0], year__lte=months[-1][0])
            .select_related("site").order_by("year", "month", "id"))
    runs = [r for r in runs if (r.year, r.month) in set(months)]

    # one row per (line, site): the man's cost and time at that site
    facts = []
    for run in runs:
        per = defaultdict(lambda: ZERO)
        lines, sites = {}, {}
        for site, _vehicle, gross, _net, line in labour_shares(run):
            if site is None or site.id not in wanted:
                continue
            per[(line.id, site.id)] += gross
            lines[line.id], sites[site.id] = line, site
        for (line_id, site_id), gross in per.items():
            line, site = lines[line_id], sites[site_id]
            money = compute_line(line)
            days, ot_h, fri, ot_sh, fri_sh = _part(line, site_id)
            ot_pay = money["ot_pay"] * ot_sh
            fri_pay = money["friday_pay"] * fri_sh
            emp = line.employee
            cat = emp.job_category
            usd = lambda v: fx.to_usd(v, run.currency, rate)  # noqa: E731
            facts.append({
                "month": (run.year, run.month), "site": site,
                "emp": emp, "staff": is_staff_grade(
                    grp=getattr(cat, "grp", "") if cat else ""),
                "trade": cat.name if cat else "Unassigned",
                "days": days, "ot_hours": ot_h, "fridays": fri,
                "cost": usd(gross), "ot_cost": usd(ot_pay),
                "friday_cost": usd(fri_pay),
            })

    def rollup(key_fn, label_fn):
        groups = defaultdict(list)
        for f in facts:
            groups[key_fn(f)].append(f)
        out = []
        for k, fs in groups.items():
            cost = sum((f["cost"] for f in fs), ZERO)
            ot_cost = sum((f["ot_cost"] for f in fs), ZERO)
            fri_cost = sum((f["friday_cost"] for f in fs), ZERO)
            basic = cost - ot_cost - fri_cost
            days = sum((f["days"] for f in fs), ZERO)
            heads = len({f["emp"].id for f in fs})
            n_months = len({f["month"] for f in fs}) or 1
            out.append({
                "_sort": k, **label_fn(k, fs),
                "headcount": Decimal(heads) / n_months if len(months) > 1
                else Decimal(heads),
                "days": days,
                "cost": cost.quantize(Decimal("0.01")),
                "basic": basic.quantize(Decimal("0.01")),
                "ot_hours": sum((f["ot_hours"] for f in fs), ZERO),
                "ot_cost": ot_cost.quantize(Decimal("0.01")),
                "friday_cost": fri_cost.quantize(Decimal("0.01")),
                "ot_pct": (ot_cost / basic * 100) if basic else None,
                "per_day": (cost / days).quantize(Decimal("0.01"))
                if days else None,
            })
        out.sort(key=lambda r: r.pop("_sort"))
        return out

    by_site = rollup(lambda f: f["site"].code,
                     lambda k, fs: {"site": f"{k} — {fs[0]['site'].name}"})
    by_month = rollup(lambda f: f["month"],
                      lambda k, fs: {"month": month_label(*k)})
    # a PM sees management staff as one line: a grade with one man in it
    # would otherwise show that man's pay
    by_trade = rollup(
        lambda f: ((0, STAFF_LINE) if f["staff"] and not ctx.sees_pay
                   else (0 if f["staff"] else 1, f["trade"])),
        lambda k, fs: {"group": "Staff" if fs[0]["staff"] else "Labour",
                       "trade": k[1]})

    money_keys = ("cost", "basic", "ot_cost", "friday_cost")
    num_keys = ("days", "ot_hours")
    total = sum_rows(by_site, money_keys + num_keys)
    heads_all = len({f["emp"].id for f in facts})
    avg_heads = (Decimal(len({(f["emp"].id, f["month"]) for f in facts}))
                 / (len({f["month"] for f in facts}) or 1))
    total.update(
        headcount=avg_heads,
        ot_pct=(total["ot_cost"] / total["basic"] * 100
                if total["basic"] else None),
        per_day=(total["cost"] / total["days"]).quantize(Decimal("0.01"))
        if total["days"] else None)

    common = [col("headcount", "Headcount" + (" (avg / month)"
                                               if len(months) > 1 else ""),
                  "num"),
              col("days", "Man-days", "num"),
              col("cost", "Labour cost", "money"),
              col("basic", "Basic & allowances", "money"),
              col("ot_hours", "OT hours", "num"),
              col("ot_cost", "OT cost", "money"),
              col("friday_cost", "Friday pay", "money"),
              col("ot_pct", "OT % of basic", "pct"),
              col("per_day", "Cost per man-day", "money")]

    def totalled(label_key, rows):
        if not rows:
            return None
        t = dict(total)
        t[label_key] = "Total"
        return t

    sections = []
    if ctx.company:
        sections.append(section("By site", [col("site", "Site")] + common,
                                by_site, totalled("site", by_site)))
    sections.append(section("By month", [col("month", "Month")] + common,
                            by_month, totalled("month", by_month)))
    sections.append(section(
        "By trade", [col("group", "Group"), col("trade", "Trade", wide=True)] + common,
        by_trade, totalled("trade", by_trade),
        note="" if ctx.sees_pay else
        "Management staff are shown as one line, so no one person's pay "
        "can be read off a grade."))
    if ctx.sees_pay:
        people = defaultdict(list)
        for f in facts:
            people[(f["emp"].emp_no, f["site"].code)].append(f)
        rows = []
        for (emp_no, code), fs in sorted(people.items()):
            e = fs[0]["emp"]
            rows.append({
                "emp_no": emp_no, "name": e.full_name, "trade": fs[0]["trade"],
                "site": code,
                "days": sum((f["days"] for f in fs), ZERO),
                "ot_hours": sum((f["ot_hours"] for f in fs), ZERO),
                "cost": sum((f["cost"] for f in fs), ZERO)
                .quantize(Decimal("0.01"))})
        rows.sort(key=lambda r: -r["cost"])
        sections.append(section("By person", [
            col("emp_no", "Emp no"), col("name", "Name", wide=True),
            col("trade", "Trade", wide=True), col("site", "Site"),
            col("days", "Days", "num"), col("ot_hours", "OT hours", "num"),
            col("cost", "Labour cost", "money")], rows,
            {"emp_no": "", "name": "Total", "trade": "", "site": "",
             **sum_rows(rows, ("days", "ot_hours", "cost"))} if rows else None,
            note="Highest cost first. Shown to ExCom members who see pay."))

    return {
        "kpis": [
            kpi("Labour cost", total["cost"],
                sub=f"{heads_all} people"),
            kpi("Man-days", total["days"], "num"),
            kpi("Cost per man-day", total["per_day"]),
            kpi("OT hours", total["ot_hours"], "num"),
            kpi("OT cost", total["ot_cost"],
                sub=(f"{total['ot_pct']:.1f}% of basic"
                     if total["ot_pct"] is not None else "")),
            kpi("Friday pay", total["friday_cost"]),
        ],
        "sections": sections,
        "notes": _open_months(ctx, months) + [
            "From locked payroll runs only. Each person's cost is placed "
            "where the work was done, as the cost ledger books it.",
            f"MVR converted at the company rate of {rate} per USD.",
            "Subcontractors' labour is not included: it is paid on their "
            "valuations and belongs to the cost reports.",
        ],
    }


def _open_months(ctx, months):
    """Months in the period with a run not yet locked for a site in scope."""
    pending = (PayrollRun.objects.filter(site_id__in=ctx.site_ids)
               .exclude(status="LOCKED").select_related("site")
               .order_by("year", "month", "site__code"))
    names = [f"{r.site.code} {month_label(r.year, r.month)} "
             f"({r.get_status_display().lower()})"
             for r in pending if (r.year, r.month) in set(months)]
    if not names:
        return []
    return ["Not yet counted, payroll not locked: " + ", ".join(names) + "."]
