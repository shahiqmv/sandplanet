"""Petty cash API (§6B, M6e). Custodian records expenses; the PM approves
(posting Incurred cost); replenishment raises a PYR that restores the float
when Finance pays it. Site users see only their own float and entries."""
from decimal import Decimal

from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from . import petty_cash
from .models import CostHead, PettyCashFloat, Site, User
from .permissions import scoped_site_ids

LIVE = ("RECORDED", "APPROVED")


def _get_site(request, site_id):
    try:
        site = Site.objects.get(pk=site_id)
    except Site.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    ids = scoped_site_ids(request.user)
    if ids is not None and site.id not in ids:
        return None, Response({"detail": "Not found."}, status=404)
    return site, None


def _is_custodian(user, fl):
    return user.role == "ADMIN" or (fl and user.id == fl.custodian_id)


def _is_site_pm(user, site):
    if user.role == "ADMIN":
        return True
    pm = site.current_pm()
    return pm is not None and pm.id == user.id


def _float_summary(fl):
    cyc = petty_cash.current_cycle(fl)
    cih = petty_cash.cash_in_hand(fl)
    trigger_amount = (fl.imprest_amount * fl.trigger_pct / 100)
    no_receipt = sum((e.amount for e in cyc.entries.filter(
        status__in=LIVE, has_receipt=False)), Decimal("0"))
    return {
        "site_id": fl.site_id, "site_code": fl.site.code,
        "imprest": fl.imprest_amount, "custodian": fl.custodian.full_name,
        "custodian_id": fl.custodian_id, "trigger_pct": fl.trigger_pct,
        "per_txn_cap": fl.per_txn_cap, "cash_in_hand": cih,
        "trigger_amount": trigger_amount, "needs_replenish": cih <= trigger_amount,
        "cycle_no": cyc.cycle_no, "cycle_status": cyc.status,
        "approved_unreimbursed": petty_cash.approved_unreimbursed_total(fl),
        "no_receipt_total": no_receipt,
    }


def _entry_info(e):
    return {
        "id": e.id, "date": e.entry_date, "amount": e.amount,
        "cost_head": e.cost_head.name, "cost_head_id": e.cost_head_id,
        "payee": e.payee, "purpose": e.purpose, "has_receipt": e.has_receipt,
        "no_receipt_reason": e.no_receipt_reason, "status": e.status,
        "entered_by": e.entered_by.full_name,
        "receipt_url": e.receipt.url if e.receipt else None,
    }


@api_view(["GET", "PUT"])
def petty_cash_float(request, site_id):
    site, err = _get_site(request, site_id)
    if err:
        return err
    fl = PettyCashFloat.objects.filter(site=site).first()
    if request.method == "PUT":
        if request.user.role not in ("FINANCE", "ADMIN"):
            return Response({"detail": "Finance or Admin sets up the "
                                       "float."}, status=403)
        try:
            custodian = User.objects.get(pk=request.data.get("custodian_id"))
        except User.DoesNotExist:
            return Response({"detail": "A valid custodian is required."},
                            status=400)
        try:
            imprest = Decimal(str(request.data.get("imprest_amount") or 0))
        except (TypeError, ValueError):
            return Response({"detail": "Imprest amount is invalid."},
                            status=400)
        if imprest <= 0:
            return Response({"detail": "Imprest amount must be positive."},
                            status=400)
        fl = petty_cash.setup_float(
            site, imprest, custodian,
            trigger_pct=request.data.get("trigger_pct", 30),
            per_txn_cap=request.data.get("per_txn_cap", 1500))
        return Response(_float_summary(fl))
    if fl is None:
        return Response({"detail": "No petty cash float set up for this "
                                   "site yet.", "configured": False},
                        status=404)
    return Response(_float_summary(fl))


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, FormParser])
def petty_cash_entries(request, site_id):
    site, err = _get_site(request, site_id)
    if err:
        return err
    fl = PettyCashFloat.objects.filter(site=site).first()
    if fl is None:
        return Response({"detail": "No float set up."}, status=404)
    if request.method == "POST":
        if not _is_custodian(request.user, fl):
            return Response({"detail": "Only the named custodian records "
                                       "petty cash."}, status=403)
        data = request.data.dict() if hasattr(request.data, "dict") \
            else dict(request.data)
        data["receipt"] = request.FILES.get("receipt")
        entry, err = petty_cash.add_entry(fl, data, request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(_entry_info(entry), status=201)
    cyc = petty_cash.current_cycle(fl)
    return Response({
        "summary": _float_summary(fl),
        "entries": [_entry_info(e) for e in cyc.entries.all()],
    })


@api_view(["POST"])
def petty_cash_approve(request, site_id):
    site, err = _get_site(request, site_id)
    if err:
        return err
    fl = PettyCashFloat.objects.filter(site=site).first()
    if fl is None:
        return Response({"detail": "No float set up."}, status=404)
    if not _is_site_pm(request.user, site):
        return Response({"detail": "The site PM approves petty cash "
                                   "entries."}, status=403)
    ids = request.data.get("entry_ids") or []
    n = petty_cash.approve_entries(fl, ids, request.user)
    return Response({"approved": n, "summary": _float_summary(fl)})


@api_view(["POST"])
def petty_cash_replenish(request, site_id):
    site, err = _get_site(request, site_id)
    if err:
        return err
    fl = PettyCashFloat.objects.filter(site=site).first()
    if fl is None:
        return Response({"detail": "No float set up."}, status=404)
    if not (_is_custodian(request.user, fl) or _is_site_pm(request.user, site)):
        return Response({"detail": "The custodian or PM requests "
                                   "replenishment."}, status=403)
    doc, err = petty_cash.request_replenishment(fl, request.user)
    if err:
        return Response({"detail": err}, status=400)
    return Response({"pyr_ref": doc.ref, "summary": _float_summary(fl)},
                    status=201)


@api_view(["POST"])
def petty_cash_reconcile(request, site_id):
    site, err = _get_site(request, site_id)
    if err:
        return err
    fl = PettyCashFloat.objects.filter(site=site).first()
    if fl is None:
        return Response({"detail": "No float set up."}, status=404)
    if not (_is_custodian(request.user, fl) or _is_site_pm(request.user, site)):
        return Response({"detail": "The custodian or PM reconciles the "
                                   "float."}, status=403)
    try:
        counted = request.data.get("counted_cash")
    except (TypeError, ValueError):
        return Response({"detail": "Counted cash is invalid."}, status=400)
    recon, err = petty_cash.reconcile(
        fl, counted, request.data.get("explanation", ""), request.user)
    if err:
        return Response({"detail": err}, status=400)
    return Response({"variance": recon.variance,
                     "system_balance": recon.system_balance,
                     "counted_cash": recon.counted_cash}, status=201)


@api_view(["GET"])
def petty_cash_cycles(request, site_id):
    site, err = _get_site(request, site_id)
    if err:
        return err
    fl = PettyCashFloat.objects.filter(site=site).first()
    if fl is None:
        return Response({"detail": "No float set up."}, status=404)
    out = []
    for cyc in fl.cycles.all():
        pyr = cyc.replenishments.first()
        out.append({
            "cycle_no": cyc.cycle_no, "status": cyc.status,
            "opening_float": cyc.opening_float,
            "closing_float": cyc.closing_float,
            "entries": cyc.entries.count(),
            "spent": sum((e.amount for e in cyc.entries.exclude(
                status="VOID")), Decimal("0")),
            "replenish_pyr": pyr.document.ref if pyr else None,
            "opened_at": cyc.opened_at, "closed_at": cyc.closed_at,
        })
    return Response(out)
