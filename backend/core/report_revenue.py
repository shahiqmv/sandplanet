"""Revenue analysis: what each project is worth and how much of it the client
has certified, billed and paid (owner 2026-11-07: revenue is recognised on
certification).

A claim's own value is the change it made to the value of work certified to
date: k_gross on that claim less k_gross on the claim before it.
"""
from decimal import Decimal

from . import fx
from .commercial import claim_valuation, contract_summary, project_revenue_summary
from .models import Project
from .reports import col, kpi, section, sum_rows

ZERO = Decimal("0")
CERTIFIED = ("CERTIFIED", "PAID")


def _usd(amount, currency, rate):
    return fx.to_usd(amount or ZERO, currency, rate).quantize(Decimal("0.01"))


def build(ctx):
    rate = fx.usd_rate()
    projects = (Project.objects.filter(site_id__in=ctx.site_ids)
                .exclude(status="TENDERING")
                .select_related("site").order_by("site__code", "code"))
    rows, period_claims, pending_vos = [], [], []
    for p in projects:
        cache = {}
        summ = project_revenue_summary(p, _cache=cache)
        if not (summ["contract_original"] or summ["claims_certified"]):
            continue
        ccy = summ["currency"]
        csum = contract_summary(p)
        in_period = ZERO
        prev = ZERO
        for c in p.claims.filter(status__in=CERTIFIED).order_by("seq"):
            w = claim_valuation(c, _cache=cache)["waterfall"]
            this = w["k_gross"] - prev
            prev = w["k_gross"]
            on = c.certified_at.date() if c.certified_at else None
            if on and ctx.start <= on <= ctx.end:
                in_period += this
                period_claims.append({
                    "site": p.site.code, "project": p.code, "claim": c.ref,
                    "certified_on": on,
                    "value": _usd(this, ccy, rate),
                    "net_due": _usd(w["net_due"], ccy, rate),
                })
        for v in p.variations.filter(status="SUBMITTED").order_by("seq"):
            pending_vos.append({
                "site": p.site.code, "project": p.code, "vo": v.ref,
                "title": v.title, "value": _usd(v.signed_total, ccy, rate),
                "sent_on": v.sent_at,
                "waiting": (ctx.end - v.sent_at).days if v.sent_at else None,
            })
        revised = summ["contract_revised"]
        rows.append({
            "site": p.site.code, "project": f"{p.code} — {p.title}",
            "original": _usd(summ["contract_original"], ccy, rate),
            "approved_vos": _usd(csum["approved_net"], ccy, rate),
            "revised": _usd(revised, ccy, rate),
            "pending_vos": _usd(csum["pending_net"], ccy, rate),
            "certified": _usd(summ["certified_revenue"], ccy, rate),
            "pct": (summ["certified_revenue"] / revised * 100
                    if revised else None),
            "in_period": _usd(in_period, ccy, rate),
            "billed": _usd(summ["billed"], ccy, rate),
            "received": _usd(summ["received"], ccy, rate),
            "outstanding": _usd(summ["outstanding"], ccy, rate),
            "retention": _usd(summ["retention_held"], ccy, rate),
        })

    money = ("original", "approved_vos", "revised", "pending_vos",
             "certified", "in_period", "billed", "received", "outstanding",
             "retention")
    total = sum_rows(rows, money)
    total.update(site="", project="Total",
                 pct=(total["certified"] / total["revised"] * 100
                      if total["revised"] else None))

    aging = _aging(ctx, rate)
    period_claims.sort(key=lambda r: r["certified_on"])
    pending_vos.sort(key=lambda r: -(r["waiting"] or 0))
    return {
        "kpis": [
            kpi("Revised contract value", total["revised"],
                sub=f"{len(rows)} project{'s' if len(rows) != 1 else ''}"),
            kpi("Certified to date", total["certified"],
                sub=(f"{total['pct']:.1f}% of revised value"
                     if total["pct"] is not None else "")),
            kpi("Certified in the period", total["in_period"],
                sub=f"{len(period_claims)} claim"
                    f"{'s' if len(period_claims) != 1 else ''}"),
            kpi("Received to date", total["received"]),
            kpi("Outstanding from clients", total["outstanding"],
                sub="billed, not yet received"),
            kpi("Variations with the client", total["pending_vos"],
                sub=f"{len(pending_vos)} awaiting approval"),
        ],
        "sections": [
            section("Projects", [
                col("site", "Site"), col("project", "Project", wide=True),
                col("original", "Original contract", "money"),
                col("approved_vos", "Approved variations", "money"),
                col("revised", "Revised contract", "money"),
                col("pending_vos", "Variations with client", "money"),
                col("certified", "Certified to date", "money"),
                col("pct", "% certified", "pct"),
                col("in_period", "Certified in period", "money"),
                col("billed", "Billed (incl. GST)", "money"),
                col("received", "Received", "money"),
                col("outstanding", "Outstanding", "money"),
                col("retention", "Retention held", "money"),
            ], rows, total if rows else None,
                note="Certified values are ex-GST, the value of work the "
                     "client has certified. Billed is what the invoices ask "
                     "for, including GST, after deductions."),
            section("Claims certified in the period", [
                col("site", "Site"), col("project", "Project", wide=True),
                col("claim", "Claim"), col("certified_on", "Certified", "date"),
                col("value", "Value of this claim", "money"),
                col("net_due", "Net due on it", "money"),
            ], period_claims,
                {"site": "", "project": "Total", "claim": "",
                 **sum_rows(period_claims, ("value", "net_due"))}
                if period_claims else None),
            section("Variations awaiting the client", [
                col("site", "Site"), col("project", "Project", wide=True),
                col("vo", "Variation"), col("title", "Description", wide=True),
                col("value", "Value", "money"),
                col("sent_on", "Sent", "date"),
                col("waiting", "Days waiting", "int"),
            ], pending_vos),
            aging,
        ],
        "notes": [
            "Revenue is recognised when the client certifies the work.",
            f"MVR converted at the company rate of {rate} per USD.",
        ],
    }


def _aging(ctx, rate):
    from .receivables import BUCKET_LABELS, BUCKETS, aging
    rows = []
    for sid in ctx.site_ids:
        a = aging(as_of=ctx.end, site_id=sid)
        for c in a["clients"]:
            ccy = c["currency"]
            rows.append({"site": c["site_code"], "client": c["client"],
                         **{b: _usd(c[b], ccy, rate) for b in BUCKETS},
                         "total": _usd(c["total"], ccy, rate)})
    rows.sort(key=lambda r: -r["total"])
    cols = [col("site", "Site"), col("client", "Client", wide=True)]
    cols += [col(b, BUCKET_LABELS.get(b, b), "money") for b in BUCKETS]
    cols.append(col("total", "Total outstanding", "money"))
    total = None
    if rows:
        total = {"site": "", "client": "Total",
                 **sum_rows(rows, list(BUCKETS) + ["total"])}
    return section(f"Outstanding invoices by age, at {ctx.end:%d %b %Y}",
                   cols, rows, total)
