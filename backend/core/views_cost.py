"""Project cost control API (§6C, M7). Cost figures are commercially
sensitive (§6C.5): Admin, HO roles, Senior Management, and the assigned PM
for their own sites. Site-level users see no cost data."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import Sum
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import fx, staff_cost
from .audit import audit
from .costing import DEFAULT_HEADS
from .models import CompanyParameter, CostPosting, Project, Site

# QS is the project-financial role and sees all project costing (in USD).
COST_ROLES = ("ADMIN", "DIRECTOR", "FINANCE", "HO_HR", "QS")
SENIOR_COST_ROLES = ("ADMIN", "DIRECTOR", "FINANCE", "QS")
STATES = ("COMMITTED", "INCURRED", "PAID")


def _usd(v):
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def _can_see_cost(user):
    return user.role in COST_ROLES


@api_view(["GET", "PUT"])
def usd_rate(request):
    """The MVR-per-USD rate used to convert site/project costs to USD.
    Everyone who can see cost may read it; Admin / Finance / QS may set it."""
    if request.method == "PUT":
        if request.user.role not in ("ADMIN", "FINANCE", "QS"):
            return Response({"detail": "Admin / Finance / QS set the rate."},
                            status=403)
        try:
            rate = Decimal(str(request.data.get("rate")))
        except (TypeError, ValueError, InvalidOperation):
            return Response({"detail": "Enter a valid number."}, status=400)
        if rate <= 0:
            return Response({"detail": "Rate must be greater than zero."},
                            status=400)
        CompanyParameter.objects.update_or_create(
            key=fx.PARAM_KEY, defaults={"value": str(rate)})
        audit("parameter", 0, "USD_RATE_UPDATED", actor=request.user,
              detail={"rate": str(rate)})
    if not _can_see_cost(request.user):
        return Response({"detail": "Cost data is restricted."}, status=403)
    return Response({"rate": fx.usd_rate(), "default": fx.DEFAULT_RATE})


def _can_see_site_cost(user, site):
    """Full cost view: Admin/Director/Finance/QS, or the site's current PM."""
    if user.role in SENIOR_COST_ROLES:
        return True
    if user.role == "PM":
        pm = site.current_pm()
        return pm is not None and pm.id == user.id
    return False


def _pct_elapsed(start, finish):
    if not (start and finish and finish > start):
        return None
    pct = round(100 * (date.today() - start).days / (finish - start).days, 1)
    return max(min(pct, 100), 0)


def _contract_value(site):
    """Site contract value, or the sum of its projects' values if the site
    itself carries none."""
    if site.contract_value:
        return site.contract_value
    total = Project.objects.filter(site=site).aggregate(
        t=Sum("contract_value"))["t"]
    return total or Decimal("0")


def _site_cost(site):
    """Net committed / incurred / paid for a site, in USD (MVR postings are
    converted at the company rate; contract values are already USD)."""
    rate = fx.usd_rate()
    agg = CostPosting.objects.filter(site=site).values(
        "cost_head__name", "state", "currency").annotate(t=Sum("amount"))
    heads = {name: {s: Decimal("0") for s in STATES} for name in DEFAULT_HEADS}
    totals = {s: Decimal("0") for s in STATES}
    for r in agg:
        name, st = r["cost_head__name"], r["state"]
        val = fx.to_usd(r["t"] or 0, r["currency"], rate)
        heads.setdefault(name, {s: Decimal("0") for s in STATES})
        heads[name][st] += val
        if st in totals:
            totals[st] += val
    contract = _contract_value(site)
    incurred = totals["INCURRED"]
    return {
        "site_id": site.id, "site_code": site.code, "site_name": site.name,
        "currency": "USD", "usd_rate": rate,
        "contract_value": _usd(contract),
        "committed": _usd(totals["COMMITTED"]), "incurred": _usd(incurred),
        "paid": _usd(totals["PAID"]),
        "remaining": _usd(contract - incurred) if contract else None,
        "pct_consumed": (round(float(incurred / contract * 100), 1)
                         if contract else None),
        "pct_elapsed": _pct_elapsed(site.start_date, site.planned_completion),
        "by_cost_head": [{"cost_head": name,
                          **{s.lower(): _usd(heads[name][s]) for s in STATES}}
                         for name in heads if any(heads[name].values())],
    }


@api_view(["GET"])
def staff_cost_current(request):
    """Projected monthly staff cost from the current headcount (run-rate),
    per site and by job category. Basic pay only; never per-employee."""
    if not _can_see_cost(request.user):
        return Response({"detail": "Cost data is restricted."}, status=403)
    return Response(staff_cost.current_run_rate())


@api_view(["GET"])
def staff_cost_history(request):
    """Past-months salary summary from the locked Labour & Staff postings."""
    if not _can_see_cost(request.user):
        return Response({"detail": "Cost data is restricted."}, status=403)
    site = None
    if request.GET.get("site"):
        site = Site.objects.filter(pk=request.GET["site"]).first()
    return Response(staff_cost.history(site))


@api_view(["GET"])
def site_cost(request, site_id):
    """The project cost view for a site (§6C.4): contract vs committed /
    incurred / paid, by cost head, % consumed vs % elapsed."""
    try:
        site = Site.objects.get(pk=site_id)
    except Site.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if not _can_see_site_cost(request.user, site):
        return Response({"detail": "Cost data is restricted."}, status=403)
    return Response(_site_cost(site))


@api_view(["GET"])
def site_cost_postings(request, site_id):
    """Drill-down: the source postings behind a cost-head / state figure."""
    try:
        site = Site.objects.get(pk=site_id)
    except Site.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if not _can_see_site_cost(request.user, site):
        return Response({"detail": "Cost data is restricted."}, status=403)
    qs = CostPosting.objects.filter(site=site).select_related(
        "cost_head", "document")
    if request.GET.get("head"):
        qs = qs.filter(cost_head__name=request.GET["head"])
    if request.GET.get("state"):
        qs = qs.filter(state=request.GET["state"])
    rate = fx.usd_rate()
    out = []
    for p in qs.order_by("-posted_on", "-id")[:200]:
        out.append({
            "id": p.id, "state": p.state, "source": p.source,
            "cost_head": p.cost_head.name,
            "amount": _usd(fx.to_usd(p.amount, p.currency, rate)),
            "amount_original": p.amount, "currency_original": p.currency,
            "posted_on": p.posted_on,
            "ref": p.document.ref if p.document_id else (
                f"{p.source} {p.staff_year}-{p.staff_month:02d}"
                if p.staff_year else p.source),
            "is_reversal": p.reversal_of_id is not None,
        })
    return Response(out)


@api_view(["GET"])
def cost_portfolio(request):
    """Cost roll-up across all sites (§6C.4): contract vs consumed, with a
    flag where cost consumption outpaces time elapsed."""
    if request.user.role not in SENIOR_COST_ROLES:
        return Response({"detail": "Senior management / Finance / QS only."},
                        status=403)
    rows = []
    tot = {"contract": Decimal("0"), "committed": Decimal("0"),
           "incurred": Decimal("0"), "paid": Decimal("0"),
           "currency": "USD"}
    for site in Site.objects.filter(is_head_office=False).order_by("code"):
        c = _site_cost(site)
        # a site with no contract and no cost is noise — skip
        if not c["contract_value"] and not c["incurred"] \
                and not c["committed"]:
            continue
        outpacing = (c["pct_consumed"] is not None
                     and c["pct_elapsed"] is not None
                     and c["pct_consumed"] > c["pct_elapsed"] + 5)
        rows.append({**{k: c[k] for k in (
            "site_id", "site_code", "site_name", "contract_value",
            "committed", "incurred", "paid", "pct_consumed",
            "pct_elapsed")}, "outpacing": outpacing})
        tot["contract"] += c["contract_value"] or 0
        tot["committed"] += c["committed"]
        tot["incurred"] += c["incurred"]
        tot["paid"] += c["paid"]
    return Response({"sites": rows, "totals": tot})
