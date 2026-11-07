"""Performance analysis: each site on one line — programme against time,
cost against revenue, the people on it and what is open against it — with
the portfolio's rating (owner 2026-11-07). The figures come from the other
reports' own builders, so a number here is the number there.
"""
from decimal import Decimal


from .models import Attendance, Document, Project
from .report_cost import recognised_cost
from .report_pnl import certified_revenue
from .report_progress import LIVE, _progress, _rating, RATING
from .reports import col, kpi, section, sum_rows
from .submittals import TO_CLIENT, WITH_CLIENT

ZERO = Decimal("0")


def build(ctx):
    on = ctx.end
    rev = certified_revenue(ctx.site_ids, ctx.start, ctx.end)
    rows = []
    counts = {"on_track": 0, "watch": 0, "attention": 0, "info": 0}
    for s in ctx.sites:
        if s.is_head_office:
            continue
        projects = list(Project.objects.filter(site=s, status__in=LIVE)
                        .prefetch_related("activities"))
        if not projects:
            continue
        # progress and time, weighted by contract value where there is one
        wp = we = wsum = ZERO
        worst = "info"
        order = ["info", "on_track", "watch", "attention"]
        for p in projects:
            prog = _progress(p)
            elapsed = None
            if p.start_date and p.planned_completion \
                    and p.planned_completion > p.start_date:
                elapsed = max(min(100 * (on - p.start_date).days / (
                    p.planned_completion - p.start_date).days, 100), 0)
            r = _rating(p, prog, elapsed)
            if order.index(r) > order.index(worst):
                worst = r
            if prog is not None and elapsed is not None:
                w = Decimal(p.contract_value or 1)
                wp += w * Decimal(str(prog))
                we += w * Decimal(str(elapsed))
                wsum += w
        counts[worst] += 1
        in_p, to_d = rev.get(s.id, (ZERO, ZERO))
        cost_d = recognised_cost([s.id], end=on)
        cost_p = recognised_cost([s.id], ctx.start, on)
        docs = Document.objects.filter(site=s, is_void=False)
        man_days = Attendance.objects.filter(
            site=s, day__gte=ctx.start, day__lte=on,
            remark__in=("PRESENT", "HALF_DAY")).count()
        rows.append({
            "site": f"{s.code} — {s.name}", "projects": len(projects),
            "progress": float(wp / wsum) if wsum else None,
            "elapsed": float(we / wsum) if wsum else None,
            "rating": RATING[worst],
            "revenue": in_p.quantize(Decimal("0.01")),
            "cost": cost_p.quantize(Decimal("0.01")),
            "revenue_to_date": to_d.quantize(Decimal("0.01")),
            "cost_to_date": cost_d.quantize(Decimal("0.01")),
            "cost_pct": (cost_d / to_d * 100) if to_d else None,
            "man_days": man_days,
            "cost_per_man_day": ((cost_p / man_days).quantize(Decimal("0.01"))
                                 if man_days else None),
            "submittals": docs.filter(doc_type__in=TO_CLIENT,
                                      status__in=WITH_CLIENT).count(),
            "ncrs": docs.filter(doc_type="NCR").exclude(
                status__in=("CLOSED", "CANCELLED")).count(),
            "notices": docs.filter(doc_type__in=("NTC", "RFI", "LTR", "INS"),
                                   correspondence__responded_on__isnull=True,
                                   correspondence__response_due__lt=on).count(),
            "incidents": docs.filter(
                doc_type="INC",
                safety_incident__occurred_at__date__gte=ctx.start,
                safety_incident__occurred_at__date__lte=on).count(),
        })
    rows.sort(key=lambda r: (["Attention", "Watch", "On track", "—"]
                             .index(r["rating"]), -r["revenue_to_date"]))
    money = ("revenue", "cost", "revenue_to_date", "cost_to_date")
    total = {"site": "Total", **sum_rows(rows, money + ("man_days", "submittals",
                                                        "ncrs", "notices",
                                                        "incidents"))}
    total["cost_pct"] = (total["cost_to_date"] / total["revenue_to_date"] * 100
                         if total["revenue_to_date"] else None)
    return {
        "kpis": [
            kpi("Sites", len(rows), "int"),
            kpi("On track", counts["on_track"], "int"),
            kpi("Watch", counts["watch"], "int"),
            kpi("Attention", counts["attention"], "int",
                sub="a site takes its worst project's rating"),
            kpi("Cost as % of revenue", total["cost_pct"], "pct",
                sub="to date, where the client has certified"),
            kpi("Man-days in period", total["man_days"], "int"),
        ],
        "sections": [section("Sites", [
            col("site", "Site", wide=True), col("projects", "Projects", "int"),
            col("progress", "Progress", "pct"),
            col("elapsed", "Time elapsed", "pct"), col("rating", "Rating"),
            col("revenue", "Certified in period", "money"),
            col("cost", "Cost in period", "money"),
            col("revenue_to_date", "Certified to date", "money"),
            col("cost_to_date", "Cost to date", "money"),
            col("cost_pct", "Cost % of revenue", "pct"),
            col("man_days", "Man-days", "int"),
            col("cost_per_man_day", "Cost / man-day", "money"),
            col("submittals", "Submittals with client", "int"),
            col("ncrs", "Open NCRs", "int"),
            col("notices", "Replies overdue", "int"),
            col("incidents", "Incidents", "int")],
            rows, total if rows else None,
            note="Progress and time elapsed are weighted by contract value "
                 "across the site's live projects. Replies overdue counts "
                 "letters, RFIs, instructions and notices past their "
                 "response date.")],
        "notes": [
            "Rating: on track within 10 points of time elapsed, watch within "
            "25, attention beyond; a site shows its worst project.",
            "Cost by the owner's rule, revenue as certified; see the cost and "
            "revenue reports for the detail.",
        ],
    }
