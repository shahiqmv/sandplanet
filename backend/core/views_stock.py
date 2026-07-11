"""Site inventory API (Phase 1A). A simple quantity ledger per site:

    GET  /stock/<site_id>                      current on-hand per item
    GET  /stock/<site_id>/<item_id>/history    movement history + running bal
    POST /stock/<site_id>/issue                hand stock to a project
    POST /stock/<site_id>/reconcile            book a physical-count adjustment

Receipts are raised automatically when a GRN is verified (see procurement.py),
so there is no manual receipt endpoint. Visibility follows the caller's site
scope; issues and reconciliations are limited to site admin staff and HO."""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import stock
from .models import Item, Project, Site
from .permissions import scoped_site_ids

ISSUE_ROLES = ("ADMIN", "SITE_ADMIN", "SITE_ENGINEER", "PM")


def _get_site(request, site_id):
    try:
        site = Site.objects.get(pk=site_id)
    except Site.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    ids = scoped_site_ids(request.user)
    if ids is not None and site.id not in ids:
        return None, Response({"detail": "Not found."}, status=404)
    return site, None


@api_view(["GET"])
def stock_balances(request, site_id):
    site, err = _get_site(request, site_id)
    if err:
        return err
    return Response({
        "site_id": site.id, "site_code": site.code,
        "can_issue": request.user.role in ISSUE_ROLES,
        "balances": stock.balances(site),
    })


@api_view(["GET"])
def stock_history(request, site_id, item_id):
    site, err = _get_site(request, site_id)
    if err:
        return err
    try:
        item = Item.objects.get(pk=item_id)
    except Item.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    return Response({
        "item": {"id": item.id, "code": item.code,
                 "description": item.description, "unit": item.unit},
        "on_hand": stock.balance(site, item),
        "history": stock.history(site, item),
    })


@api_view(["GET"])
def stock_major_materials(request, site_id):
    """Major-material catalog items with this site's on-hand — the DPR's
    'load key materials from stock' source. Pass ?date=YYYY-MM-DD to also get
    that day's received (GRN) quantity per item."""
    site, err = _get_site(request, site_id)
    if err:
        return err
    on_date = None
    raw = request.GET.get("date")
    if raw:
        from datetime import date as _date
        try:
            on_date = _date.fromisoformat(raw)
        except ValueError:
            on_date = None
    return Response({"materials": stock.major_materials(site, on_date=on_date)})


@api_view(["POST"])
def stock_issue(request, site_id):
    site, err = _get_site(request, site_id)
    if err:
        return err
    if request.user.role not in ISSUE_ROLES:
        return Response({"detail": "Only site admin staff issue stock."},
                        status=403)
    project = None
    pid = request.data.get("project_id")
    if pid:
        try:
            project = Project.objects.get(pk=pid, site=site)
        except Project.DoesNotExist:
            return Response({"detail": "Unknown project for this site."},
                            status=400)
    raw = request.data.get("lines") or []
    lines = []
    for ln in raw:
        try:
            item = Item.objects.get(pk=ln.get("item_id"))
        except Item.DoesNotExist:
            return Response({"detail": "Unknown item in issue lines."},
                            status=400)
        lines.append({"item": item, "qty": ln.get("qty") or 0,
                      "reason": ln.get("reason", "")})
    try:
        stock.issue(site, project, lines, actor=request.user,
                    reason=request.data.get("reason", ""))
    except (ValueError, KeyError) as exc:
        return Response({"detail": str(exc)}, status=400)
    return Response({"issued": True, "balances": stock.balances(site)},
                    status=201)


@api_view(["POST"])
def stock_reconcile(request, site_id):
    site, err = _get_site(request, site_id)
    if err:
        return err
    if request.user.role not in ISSUE_ROLES:
        return Response({"detail": "Only site admin staff reconcile stock."},
                        status=403)
    try:
        item = Item.objects.get(pk=request.data.get("item_id"))
    except Item.DoesNotExist:
        return Response({"detail": "Unknown item."}, status=400)
    reason = (request.data.get("reason") or "").strip()
    if not reason:
        return Response({"detail": "A reason for the adjustment is required."},
                        status=400)
    try:
        counted = request.data.get("counted_qty")
        mv = stock.reconcile(site, item, counted, reason=reason,
                             actor=request.user)
    except (ValueError, TypeError):
        return Response({"detail": "Counted quantity is invalid."}, status=400)
    return Response({
        "reconciled": True, "adjusted": mv is not None,
        "on_hand": stock.balance(site, item),
        "balances": stock.balances(site),
    })
