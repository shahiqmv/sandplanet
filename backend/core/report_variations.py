"""Variations and claims: what has been asked of the client and how long it
has waited (owner 2026-11-07).
"""
from decimal import Decimal

from . import fx
from .commercial import claim_valuation, contract_summary
from .models import AuditLog, ClientReceipt, Project
from .reports import col, kpi, section, sum_rows

ZERO = Decimal("0")
LIVE = ("AWARDED", "ACTIVE", "ON_HOLD")
STAGE = {"DRAFT": "Draft", "PD_PENDING": "With the Director",
         "PD_APPROVED": "Approved internally, not yet sent",
         "SUBMITTED": "With the client", "APPROVED": "Approved by the client",
         "REJECTED": "Rejected by the client"}


def _usd(v, ccy, rate):
    return fx.to_usd(v or ZERO, ccy, rate).quantize(Decimal("0.01"))


def _submitted_on(project, ref):
    a = (AuditLog.objects.filter(entity="project", entity_id=project.id,
                                 event="CLAIM_SUBMITTED", detail__ref=ref)
         .order_by("-id").first())
    return a.at.date() if a else None


def build(ctx):
    rate = fx.usd_rate()
    on = ctx.end
    projects = (Project.objects.filter(site_id__in=ctx.site_ids,
                                       status__in=LIVE)
                .select_related("site").order_by("site__code", "code"))
    contract, open_vos, decided, claims = [], [], [], []
    for p in projects:
        ccy = getattr(getattr(p, "boq", None), "currency", "USD")
        cs = contract_summary(p)
        if not (cs["original"] or p.variations.exists()):
            continue
        contract.append({
            "site": p.site.code, "project": f"{p.code} — {p.title}",
            "original": _usd(cs["original"], ccy, rate),
            "approved": _usd(cs["approved_net"], ccy, rate),
            "revised": _usd(cs["revised"], ccy, rate),
            "with_client": _usd(cs["pending_net"], ccy, rate),
            "internal": _usd(cs["internal_net"], ccy, rate),
            "forecast": _usd(cs["forecast"], ccy, rate),
        })
        for v in p.variations.exclude(status="DRAFT").order_by("seq"):
            row = {"site": p.site.code, "project": p.code, "vo": v.ref,
                   "title": v.title, "kind": v.get_kind_display(),
                   "value": _usd(v.signed_total, ccy, rate),
                   "stage": STAGE.get(v.status, v.status)}
            if v.status == "SUBMITTED":
                row.update(since=v.sent_at,
                           waiting=(on - v.sent_at).days if v.sent_at else None)
                open_vos.append(row)
            elif v.status in ("PD_PENDING", "PD_APPROVED"):
                since = (v.pd_approved_at.date() if v.pd_approved_at
                         else v.created_at.date())
                row.update(since=since, waiting=(on - since).days)
                open_vos.append(row)
            elif v.status == "APPROVED" and v.employer_approved_on \
                    and ctx.start <= v.employer_approved_on <= on:
                row.update(decided_on=v.employer_approved_on,
                           ref=v.employer_ref)
                decided.append(row)
        cache = {}
        prev = ZERO
        for c in p.claims.exclude(status="DRAFT").order_by("seq"):
            w = claim_valuation(c, _cache=cache)["waterfall"]
            this = w["k_gross"] - prev
            if c.status in ("CERTIFIED", "PAID"):
                prev = w["k_gross"]
            cert = c.certified_at.date() if c.certified_at else None
            sub = _submitted_on(p, c.ref)
            received = (ClientReceipt.objects.filter(claim=c)
                        .order_by("-received_on").first())
            show = (c.status == "SUBMITTED"
                    or (cert and ctx.start <= cert <= on)
                    or (received and ctx.start <= received.received_on <= on))
            if not show:
                continue
            claims.append({
                "site": p.site.code, "project": p.code, "claim": c.ref,
                "type": c.get_claim_type_display(),
                "status": c.get_status_display(),
                "submitted_on": sub, "certified_on": cert,
                "waiting": ((on - sub).days if c.status == "SUBMITTED" and sub
                            else None),
                "value": _usd(this if c.status != "SUBMITTED"
                              else w["k_gross"] - prev, ccy, rate),
                "net_due": _usd(w["net_to_pay"], ccy, rate),
                "received_on": received.received_on if received else None,
            })

    open_vos.sort(key=lambda r: -(r.get("waiting") or 0))
    waiting_client = [r for r in open_vos if r["stage"] == "With the client"]
    money = ("original", "approved", "revised", "with_client", "internal",
             "forecast")
    total = {"site": "", "project": "Total", **sum_rows(contract, money)}
    return {
        "kpis": [
            kpi("Revised contract value", total["revised"]),
            kpi("Variations with the client", total["with_client"],
                sub=f"{len(waiting_client)} waiting"),
            kpi("Longest wait", max((r["waiting"] or 0
                                     for r in waiting_client), default=0),
                "int", sub="days with the client"),
            kpi("Approved in the period",
                sum((r["value"] for r in decided), ZERO),
                sub=f"{len(decided)} variation{'s' if len(decided) != 1 else ''}"),
            kpi("Claims awaiting certification",
                sum(1 for c in claims if c["status"] == "Submitted"), "int"),
        ],
        "sections": [
            section("Contract value by project", [
                col("site", "Site"), col("project", "Project", wide=True),
                col("original", "Original", "money"),
                col("approved", "Approved variations", "money"),
                col("revised", "Revised", "money"),
                col("with_client", "With the client", "money"),
                col("internal", "Not yet sent", "money"),
                col("forecast", "Forecast if approved", "money")],
                contract, total if contract else None),
            section("Variations waiting", [
                col("site", "Site"), col("project", "Project"),
                col("vo", "Variation"), col("title", "Description", wide=True),
                col("kind", "Kind"), col("value", "Value", "money"),
                col("stage", "Where it is", wide=True),
                col("since", "Since", "date"),
                col("waiting", "Days", "int")], open_vos,
                note="Longest wait first. Not yet sent means approved by the "
                     "Director but still to go to the client."),
            section("Variations the client decided in the period", [
                col("site", "Site"), col("project", "Project"),
                col("vo", "Variation"), col("title", "Description", wide=True),
                col("value", "Value", "money"),
                col("decided_on", "Approved on", "date"),
                col("ref", "Client reference")], decided),
            section("Claims", [
                col("site", "Site"), col("project", "Project"),
                col("claim", "Claim"), col("type", "Type"),
                col("status", "Status"),
                col("submitted_on", "Submitted", "date"),
                col("waiting", "Days waiting", "int"),
                col("certified_on", "Certified", "date"),
                col("value", "Value certified", "money"),
                col("net_due", "Net due", "money"),
                col("received_on", "Last receipt", "date")], claims,
                note="Claims awaiting certification, and those certified or "
                     "paid in the period."),
        ],
        "notes": [f"MVR converted at the company rate of {rate} per USD."],
    }
