"""Profit and loss, the management view: revenue the client has certified
less the cost booked by the owner's rule (core/report_cost.py), site by site,
with trading, rental and head-office overheads on the company's own
(owner 2026-11-07).

This is not the accounting P&L in the Finance app, which comes from the
books; it is the project view, and the two are reconciled separately.
"""
from decimal import Decimal

from . import fx
from .commercial import claim_valuation
from .models import CostPosting, Project
from .report_cost import recognised_cost, site_postings, usd_sum
from .reports import col, kpi, section, sum_rows

ZERO = Decimal("0")
CERTIFIED = ("CERTIFIED", "PAID")
LIVE = ("AWARDED", "ACTIVE", "ON_HOLD", "CLOSED")


def _q2(v):
    return Decimal(v).quantize(Decimal("0.01"))


def certified_revenue(site_ids, start, end):
    """{site_id: (in period, to date)} of certified revenue, USD."""
    rate = fx.usd_rate()
    out = {}
    projects = (Project.objects.filter(site_id__in=site_ids, status__in=LIVE)
                .select_related("site"))
    for p in projects:
        cache = {}
        ccy = getattr(getattr(p, "boq", None), "currency", "USD")
        prev = ZERO
        in_p = to_d = ZERO
        for c in p.claims.filter(status__in=CERTIFIED).order_by("seq"):
            w = claim_valuation(c, _cache=cache)["waterfall"]
            this, prev = w["k_gross"] - prev, w["k_gross"]
            on = c.certified_at.date() if c.certified_at else None
            if on and on <= end:
                to_d += this
                if on >= start:
                    in_p += this
        if in_p or to_d:
            a, b = out.get(p.site_id, (ZERO, ZERO))
            out[p.site_id] = (a + fx.to_usd(in_p, ccy, rate),
                              b + fx.to_usd(to_d, ccy, rate))
    return out


def _book(book, start, end):
    """Revenue and cost of the trading or rental book in a period, USD:
    revenue heads carry the sales, every other non-GST head is cost."""
    qs = CostPosting.objects.filter(book=book, state="INCURRED",
                                    posted_on__gte=start, posted_on__lte=end)
    rev = cost = ZERO
    for code, v in usd_sum(qs, "cost_head__code").items():
        if "OUTPUT_GST" in (code or ""):
            continue
        if "REVENUE" in (code or ""):
            rev += v
        else:
            cost += v
    return _q2(rev), _q2(cost)


def build(ctx):
    rate = fx.usd_rate()
    rev = certified_revenue(ctx.site_ids, ctx.start, ctx.end)
    rows = []
    for s in ctx.sites:
        in_p, to_d = rev.get(s.id, (ZERO, ZERO))
        cost_p = recognised_cost([s.id], ctx.start, ctx.end)
        cost_d = recognised_cost([s.id], end=ctx.end)
        if not any((in_p, to_d, cost_p, cost_d)):
            continue
        rows.append({
            "site": f"{s.code} — {s.name}",
            "revenue": _q2(in_p), "cost": _q2(cost_p),
            "margin": _q2(in_p - cost_p),
            "margin_pct": (in_p - cost_p) / in_p * 100 if in_p else None,
            "revenue_to_date": _q2(to_d), "cost_to_date": _q2(cost_d),
            "margin_to_date": _q2(to_d - cost_d),
            "margin_pct_to_date": ((to_d - cost_d) / to_d * 100
                                   if to_d else None),
        })
    rows.sort(key=lambda r: -r["revenue_to_date"])
    keys = ("revenue", "cost", "margin", "revenue_to_date", "cost_to_date",
            "margin_to_date")
    total = sum_rows(rows, keys)
    total.update(site="Total",
                 margin_pct=(total["margin"] / total["revenue"] * 100
                             if total["revenue"] else None),
                 margin_pct_to_date=(total["margin_to_date"]
                                     / total["revenue_to_date"] * 100
                                     if total["revenue_to_date"] else None))
    sections = [section("Sites", [
        col("site", "Site"), col("revenue", "Certified revenue", "money"),
        col("cost", "Cost", "money"), col("margin", "Gross margin", "money"),
        col("margin_pct", "Margin %", "pct"),
        col("revenue_to_date", "Revenue to date", "money"),
        col("cost_to_date", "Cost to date", "money"),
        col("margin_to_date", "Margin to date", "money"),
        col("margin_pct_to_date", "Margin % to date", "pct")],
        rows, total if rows else None,
        note="Revenue is the value of work the client certified in the "
             "period, ex-GST. Cost is by the owner's rule: counted when the "
             "Signatory approves it, payroll when the run locks.")]

    kpis = [kpi("Certified revenue", total["revenue"]),
            kpi("Cost", total["cost"]),
            kpi("Gross margin", total["margin"],
                sub=(f"{total['margin_pct']:.1f}%"
                     if total["margin_pct"] is not None else ""))]
    notes = [
        "The management P&L, from certified work and the cost ledger; the "
        "Finance app's accounting P&L comes from the books and is reconciled "
        "separately.",
        "To-date figures count only what Planet holds: work certified and "
        "cost booked before Planet started are not in them.",
        f"MVR converted at the company rate of {rate} per USD.",
    ]
    if ctx.company:
        lines = [{"line": "Gross margin on projects", "amount": total["margin"]}]
        for book, label in (("TRADING", "Trading"), ("RENTAL", "Rental")):
            r, c = _book(book, ctx.start, ctx.end)
            if r or c:
                lines.append({"line": f"{label}: sales", "amount": r})
                lines.append({"line": f"{label}: cost", "amount": -c})
        oh = _q2(sum(usd_sum(site_postings(None, ctx.start, ctx.end,
                                           overheads=True)
                             .filter(state="INCURRED")).values(), ZERO))
        lines.append({"line": "Head-office overheads", "amount": -oh})
        net = sum((ln["amount"] for ln in lines), ZERO)
        sections.append(section("Company result", [
            col("line", "", wide=True), col("amount", "USD", "money")],
            lines, {"line": "Net result for the period", "amount": net},
            note="Trading and rental are their own books, as posted; "
                 "overheads are the company's own costs."))
        kpis.append(kpi("Net result", net, sub="after trading, rental and "
                                                "overheads"))
    return {"kpis": kpis, "sections": sections, "notes": notes}
