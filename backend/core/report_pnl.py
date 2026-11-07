"""Profit and loss, the management view, on the matching basis the owner
chose (2026-11-07): the value of the work done against the cost of that same
work. What is bought but not yet used is stock; what is ordered but not yet
delivered is a commitment; an advance is the client's money held against
future certificates. All three are shown below the margin, not inside it.

Revenue earned = work certified + work done not yet certified, the latter an
estimate from programme progress against the revised contract, blank where a
project has no progress measure. Cost of the work done = core/report_cost
WORK_DONE. The to-date columns are the ones to judge a project by: a month's
figures swing with when certificates land.

Not the accounting P&L in the Finance app, which comes from the books.
"""
from decimal import Decimal

from . import fx
from .commercial import claim_valuation, contract_summary
from .models import CostPosting, Project
from .report_cost import (SOURCE_LABEL, site_postings, stock_on_hand,
                          undelivered, usd_sum, work_done_by_source,
                          work_done_cost)
from .report_progress import _progress
from .reports import col, kpi, section, sum_rows

ZERO = Decimal("0")
CERTIFIED = ("CERTIFIED", "PAID")
LIVE = ("AWARDED", "ACTIVE", "ON_HOLD", "CLOSED")
COST_LINES = ("STAFF", "SUBCONTRACT", "STORE_ISSUE", "PR", "PYR",
              "PETTY_CASH", "RENT", "UTILITY", "STOCK_ADJ")


def _q2(v):
    return Decimal(v).quantize(Decimal("0.01"))


def _ccy(p):
    return getattr(getattr(p, "boq", None), "currency", "USD")


def certified_revenue(site_ids, start, end):
    """{site_id: (in period, to date)} of certified revenue, USD, with the
    advance held: {site_id: advance received not yet recovered}, and the
    certified value project by project: {project_id: to date}."""
    rate = fx.usd_rate()
    out, advances, per_project = {}, {}, {}
    projects = (Project.objects.filter(site_id__in=site_ids, status__in=LIVE)
                .select_related("site"))
    for p in projects:
        cache = {}
        ccy = _ccy(p)
        prev = ZERO
        in_p = to_d = ZERO
        last = None
        for c in p.claims.filter(status__in=CERTIFIED).order_by("seq"):
            w = claim_valuation(c, _cache=cache)["waterfall"]
            this, prev = w["k_gross"] - prev, w["k_gross"]
            on = c.certified_at.date() if c.certified_at else None
            if on and on <= end:
                to_d += this
                last = w
                if on >= start:
                    in_p += this
        if last is not None:
            held = last["advance_received"] - last["advance_recovered"]
            if held > 0:
                advances[p.site_id] = advances.get(p.site_id, ZERO) \
                    + fx.to_usd(held, ccy, rate)
        if in_p or to_d:
            a, b = out.get(p.site_id, (ZERO, ZERO))
            out[p.site_id] = (a + fx.to_usd(in_p, ccy, rate),
                              b + fx.to_usd(to_d, ccy, rate))
            per_project[p.id] = fx.to_usd(to_d, ccy, rate)
    certified_revenue.advances = advances
    certified_revenue.per_project = per_project
    return out


def uncertified_work(projects, certified_by_project=None):
    """Work done but not yet certified, USD, project by project: progress ×
    revised contract less what that project has certified, never below
    nothing. A project with no progress measure adds nothing."""
    rate = fx.usd_rate()
    certified_by_project = certified_by_project or {}
    earned = ZERO
    for p in projects:
        prog = _progress(p)
        if prog is None:
            continue
        revised = contract_summary(p)["revised"]
        done = fx.to_usd(revised * Decimal(str(prog)) / 100, _ccy(p), rate)
        earned += max(done - certified_by_project.get(p.id, ZERO), ZERO)
    return earned


def _book(book, start, end):
    """Revenue and cost of the trading or rental book in a period, USD."""
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
    advances = certified_revenue.advances
    rows, lines_by_site = [], {}
    ho = [s for s in ctx.sites if s.is_head_office]
    for s in ctx.sites:
        if s.is_head_office:
            continue        # head office is not a site: its payments go below
        projects = list(Project.objects.filter(site=s, status__in=LIVE)
                        .prefetch_related("activities"))
        cert_p, cert_d = rev.get(s.id, (ZERO, ZERO))
        unc = uncertified_work(projects, certified_revenue.per_project)
        earned = cert_d + unc
        cost_p = work_done_cost([s.id], ctx.start, ctx.end)
        cost_d = work_done_cost([s.id], end=ctx.end)
        if not any((cert_p, cert_d, unc, cost_p, cost_d)):
            continue
        stock = stock_on_hand([s.id], ctx.end)
        coming = undelivered([s.id], ctx.end)
        adv = advances.get(s.id, ZERO)
        lines_by_site[s.id] = work_done_by_source([s.id], end=ctx.end)
        rows.append({
            "site": f"{s.code} — {s.name}",
            "certified": _q2(cert_p), "cost": _q2(cost_p),
            "margin": _q2(cert_p - cost_p),
            "certified_to_date": _q2(cert_d), "uncertified": _q2(unc),
            "earned": _q2(earned), "cost_to_date": _q2(cost_d),
            "margin_to_date": _q2(earned - cost_d),
            "margin_pct": ((earned - cost_d) / earned * 100
                           if earned else None),
            "stock": _q2(stock), "undelivered": _q2(coming),
            "advance": _q2(adv),
        })
    rows.sort(key=lambda r: -r["earned"])
    keys = ("certified", "cost", "margin", "certified_to_date", "uncertified",
            "earned", "cost_to_date", "margin_to_date", "stock",
            "undelivered", "advance")
    total = sum_rows(rows, keys)
    total.update(site="Total",
                 margin_pct=(total["margin_to_date"] / total["earned"] * 100
                             if total["earned"] else None))

    # the cost of the work done, line by line, to date
    by_src = {}
    for d in lines_by_site.values():
        for k, v in d.items():
            by_src[k] = by_src.get(k, ZERO) + v
    cost_lines = [{"line": SOURCE_LABEL.get(k, k), "amount": _q2(by_src[k])}
                  for k in COST_LINES if by_src.get(k)]
    cost_lines.sort(key=lambda r: -r["amount"])

    sections = [
        section("Sites, to date", [
            col("site", "Site"),
            col("certified_to_date", "Work certified", "money"),
            col("uncertified", "Done, not yet certified", "money"),
            col("earned", "Revenue earned", "money"),
            col("cost_to_date", "Cost of the work done", "money"),
            col("margin_to_date", "Gross margin", "money"),
            col("margin_pct", "Margin %", "pct"),
            col("stock", "Stock on hand", "money"),
            col("undelivered", "Ordered, not delivered", "money"),
            col("advance", "Advance held", "money")],
            rows, total if rows else None,
            note="Done, not yet certified is an estimate: programme progress "
                 "times the revised contract, less what is certified; blank "
                 "where a project has no progress measure. Stock, orders not "
                 "delivered and the advance are not in the margin: stock is "
                 "an asset, orders a commitment, the advance the client's "
                 "money held against future certificates."),
        section("Sites, movement in the period", [
            col("site", "Site"), col("certified", "Certified", "money"),
            col("cost", "Cost of work booked", "money"),
            col("margin", "Difference", "money")],
            rows, {"site": "Total", **sum_rows(rows, ("certified", "cost",
                                                      "margin"))}
            if rows else None,
            note="A month swings with when certificates land; judge a site "
                 "by the to-date figures above."),
        section("Cost of the work done, to date", [
            col("line", "", wide=True), col("amount", "USD", "money")],
            cost_lines, {"line": "Total", "amount": total["cost_to_date"]}
            if cost_lines else None),
    ]
    kpis = [kpi("Revenue earned to date", total["earned"],
                sub=f"certified {total['certified_to_date']:,.0f}"),
            kpi("Cost of the work done", total["cost_to_date"]),
            kpi("Gross margin to date", total["margin_to_date"],
                sub=(f"{total['margin_pct']:.1f}%"
                     if total["margin_pct"] is not None else "")),
            kpi("Certified in the period", total["certified"]),
            kpi("Stock and orders in hand", total["stock"] + total["undelivered"],
                sub="not yet in the cost"),
            kpi("Advances held", total["advance"],
                sub="to be recovered from certificates")]
    notes = [
        "Revenue is recognised as work is done; an advance is not revenue. "
        "Cost is the cost of the work done: payroll once locked, "
        "subcontractors' certified work, imports once issued from the store, "
        "local purchases on order, expenses as booked.",
        "To-date figures count only what Planet holds: work certified and "
        "cost booked before Planet started are not in them.",
        f"MVR converted at the company rate of {rate} per USD.",
    ]
    if ctx.company:
        lines = [{"line": "Gross margin on projects, in the period",
                  "amount": _q2(total["margin"])}]
        for book, label in (("TRADING", "Trading"), ("RENTAL", "Rental")):
            r, c = _book(book, ctx.start, ctx.end)
            if r or c:
                lines.append({"line": f"{label}: sales", "amount": r})
                lines.append({"line": f"{label}: cost", "amount": -c})
        oh = _q2(sum(usd_sum(site_postings(None, ctx.start, ctx.end,
                                           overheads=True)
                             .filter(state="INCURRED")).values(), ZERO))
        lines.append({"line": "Head-office overheads", "amount": -oh})
        if ho:
            # payments raised at head office under ordinary cost heads:
            # some are company cost, some are money moving (a dollar
            # purchase), none belong to a site
            ho_cost = _q2(work_done_cost([x.id for x in ho], ctx.start,
                                         ctx.end))
            lines.append({"line": "Head-office payments not charged to a "
                                  "site (includes currency purchases)",
                          "amount": -ho_cost})
        net = sum((ln["amount"] for ln in lines), ZERO)
        sections.append(section("Company result for the period", [
            col("line", "", wide=True), col("amount", "USD", "money")],
            lines, {"line": "Net result for the period", "amount": net},
            note="The period's project margin, which swings with "
                 "certification, plus trading and rental as posted, less the "
                 "company's own costs. Head-office payments include dollar "
                 "purchases, which are not a cost: a separate head for those "
                 "would take them out."))
        kpis.append(kpi("Net result for the period", net))
    return {"kpis": kpis, "sections": sections, "notes": notes}
