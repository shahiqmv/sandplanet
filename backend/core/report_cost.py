"""Cost analysis: what each site's work has cost, from the cost ledger
(owner 2026-11-07).

What counts as cost is the owner's rule: a purchase when the Signatory
approves the payment voucher, a credit purchase when the Signatory signs the
order, an import when the Signatory authorises the IPR, a subcontractor's
work when the Signatory authorises the valuation. The ledger books every one
of those as COMMITTED on that day. Where nothing is ever committed — payroll
(booked when the run locks), petty cash (when the PM approves the expense),
store issues (when the site receives the goods) — the booking is INCURRED, and
that is the event used. Paid is shown beside it, never in place of it.

Head-office overheads are not a site's cost (owner 2026-09-07): the company
report totals them on their own. Pools (input GST, general stock, FX) and the
trading and rental books stay out; the P&L takes those up.
"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Q, Sum

from . import fx
from .models import CostPosting
from .reports import col, kpi, month_label, section, sum_rows

ZERO = Decimal("0")
# the state that is the owner's "cost", by what posted it
RECOGNISED = {
    "PR": "COMMITTED", "IPR": "COMMITTED", "PYR": "COMMITTED",
    "SUBCONTRACT": "COMMITTED", "RENT": "COMMITTED", "UTILITY": "COMMITTED",
    "STAFF": "INCURRED", "PETTY_CASH": "INCURRED", "STORE_ISSUE": "INCURRED",
    "STOCK_ADJ": "INCURRED",
}
SOURCE_LABEL = {
    "PR": "Local purchases", "IPR": "Imports", "PYR": "Payment requests",
    "SUBCONTRACT": "Subcontractors", "STAFF": "Payroll",
    "PETTY_CASH": "Petty cash", "STORE_ISSUE": "Issued from HO store",
    "RENT": "Rent", "UTILITY": "Phone & utility bills",
    "STOCK_ADJ": "Stock adjustments", "FX": "Exchange differences",
}


def recognised_q():
    """The ledger rows that are cost by the owner's rule."""
    q = Q()
    for source, state in RECOGNISED.items():
        q |= Q(source=source, state=state)
    # A petty-cash replenishment is the float coming back: the expenses it
    # repays are already in as PETTY_CASH. A salary advance is a prepayment
    # recovered from pay, which payroll books when the run locks.
    return (q & ~Q(source="PYR",
                   document__payment_request__payment_type=
                   "PETTY_CASH_REPLENISH")
            & ~Q(source="PYR", document__salary_advances__isnull=False))


def site_postings(site_ids, start=None, end=None, overheads=False):
    qs = CostPosting.objects.filter(book="PROJECT", is_stock_pool=False,
                                    cost_head__overhead=overheads)
    if site_ids is not None:
        qs = qs.filter(site_id__in=site_ids)
    if start:
        qs = qs.filter(posted_on__gte=start)
    if end:
        qs = qs.filter(posted_on__lte=end)
    return qs


def usd_sum(qs, *group):
    """{group key: USD} over postings, converted currency by currency."""
    rate = fx.usd_rate()
    out = defaultdict(lambda: ZERO)
    for r in qs.values(*group, "currency").annotate(t=Sum("amount")):
        key = tuple(r[g] for g in group) if len(group) != 1 else r[group[0]]
        out[key] += fx.to_usd(r["t"] or ZERO, r["currency"], rate)
    return out


def recognised_cost(site_ids, start=None, end=None):
    """USD cost by the owner's rule for these sites, in a period."""
    return sum(usd_sum(site_postings(site_ids, start, end)
                       .filter(recognised_q())).values(), ZERO)


def build(ctx):
    rate = fx.usd_rate()
    ids = ctx.site_ids
    period = site_postings(ids, ctx.start, ctx.end)
    to_date = site_postings(ids, end=ctx.end)
    rec_p = period.filter(recognised_q())
    rec_d = to_date.filter(recognised_q())
    q2 = lambda v: v.quantize(Decimal("0.01"))  # noqa: E731

    def states(qs, key):
        """rows keyed by `key` with cost/committed/incurred/paid."""
        rec = usd_sum(qs.filter(recognised_q()), key)
        st = usd_sum(qs, key, "state")
        keys = set(rec) | {k for k, _ in st}
        rows = {}
        for k in keys:
            rows[k] = {"cost": q2(rec.get(k, ZERO)),
                       "committed": q2(st.get((k, "COMMITTED"), ZERO)),
                       "incurred": q2(st.get((k, "INCURRED"), ZERO)),
                       "paid": q2(st.get((k, "PAID"), ZERO))}
        return rows

    money = ("cost", "committed", "incurred", "paid")
    cols = [col("cost", "Cost", "money"),
            col("committed", "Committed", "money"),
            col("incurred", "Incurred", "money"),
            col("paid", "Paid", "money")]

    sections = []
    # by site: the period and to date side by side
    if ctx.company:
        p_rows, d_rows = states(period, "site__code"), states(to_date, "site__code")
        names = dict(CostPosting.objects.filter(site_id__in=ids)
                     .values_list("site__code", "site__name").distinct())
        rows = []
        for code in sorted(set(p_rows) | set(d_rows)):
            p, d = p_rows.get(code, {}), d_rows.get(code, {})
            rows.append({"site": f"{code} — {names.get(code, '')}",
                         "cost": p.get("cost", ZERO),
                         "paid": p.get("paid", ZERO),
                         "cost_to_date": d.get("cost", ZERO),
                         "committed_to_date": d.get("committed", ZERO),
                         "paid_to_date": d.get("paid", ZERO)})
        rows.sort(key=lambda r: -r["cost_to_date"])
        keys = ("cost", "paid", "cost_to_date", "committed_to_date",
                "paid_to_date")
        sections.append(section("By site", [
            col("site", "Site"), col("cost", "Cost in period", "money"),
            col("paid", "Paid in period", "money"),
            col("cost_to_date", "Cost to date", "money"),
            col("committed_to_date", "Committed to date", "money"),
            col("paid_to_date", "Paid to date", "money")],
            rows, {"site": "Total", **sum_rows(rows, keys)} if rows else None,
            note="To date is everything booked up to the end of the period."))

    for label, key, fmt in (("By cost head", "cost_head__name", str),
                            ("By source", "source",
                             lambda s: SOURCE_LABEL.get(s, s))):
        got = states(period, key)
        rows = [{"name": fmt(k), **v} for k, v in got.items()
                if any(v.values())]
        rows.sort(key=lambda r: -r["cost"])
        sections.append(section(label, [col("name", label[3:].capitalize(),
                                             wide=True)] + cols, rows,
                                {"name": "Total", **sum_rows(rows, money)}
                                if rows else None))

    by_month = usd_sum(rec_p, "posted_on__year", "posted_on__month")
    paid_month = usd_sum(period.filter(state="PAID"), "posted_on__year",
                         "posted_on__month")
    rows = [{"month": month_label(y, m), "cost": q2(v),
             "paid": q2(paid_month.get((y, m), ZERO))}
            for (y, m), v in sorted(by_month.items())]
    sections.append(section("By month", [
        col("month", "Month"), col("cost", "Cost", "money"),
        col("paid", "Paid", "money")], rows,
        {"month": "Total", **sum_rows(rows, ("cost", "paid"))}
        if rows else None))

    notes = [
        "Cost is counted when the Signatory approves it: the payment voucher "
        "for a purchase, the order for a credit purchase, the IPR for an "
        "import, the valuation for a subcontractor. Payroll counts when the "
        "run locks, petty cash when the PM approves the expense, goods from "
        "the HO store when the site receives them.",
        "Head-office overheads, recoverable GST and the trading and rental "
        "books are not site cost.",
        f"MVR converted at the company rate of {rate} per USD.",
    ]
    kpis = [
        kpi("Cost in period", q2(sum(usd_sum(rec_p).values(), ZERO))),
        kpi("Paid in period", q2(sum(usd_sum(
            period.filter(state="PAID")).values(), ZERO))),
        kpi("Cost to date", q2(sum(usd_sum(rec_d).values(), ZERO))),
        kpi("Committed to date", q2(sum(usd_sum(
            to_date.filter(state="COMMITTED")).values(), ZERO))),
        kpi("Paid to date", q2(sum(usd_sum(
            to_date.filter(state="PAID")).values(), ZERO))),
    ]
    if ctx.company:
        oh = site_postings(None, ctx.start, ctx.end, overheads=True)
        got = states(oh, "cost_head__name")
        rows = [{"name": k, **v} for k, v in got.items() if any(v.values())]
        rows.sort(key=lambda r: -r["cost"])
        sections.append(section("Head-office overheads", [
            col("name", "Cost head", wide=True)] + cols, rows,
            {"name": "Total", **sum_rows(rows, money)} if rows else None,
            note="The company's own costs, charged to no site."))
        kpis.append(kpi("Overheads in period",
                        q2(sum((r["cost"] for r in rows), ZERO))))
    return {"kpis": kpis, "sections": sections, "notes": notes}
