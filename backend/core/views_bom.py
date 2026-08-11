"""Bill of Materials endpoints (owner 2026-08-11) — the per-project quantity
budget + variance. Visible to anyone who can open the project workspace
(quantities, not money); edited by the QS/PM chain."""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import bom as bom_svc
from .models import Item, Project
from .permissions import scoped_site_ids

EDIT_ROLES = ("QS", "PM", "DIRECTOR", "ADMIN")


def _get_project(request, pid):
    try:
        p = Project.objects.select_related("site").get(pk=pid)
    except Project.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    site_ids = scoped_site_ids(request.user)
    if site_ids is not None and p.site_id not in site_ids:
        return None, Response({"detail": "Not found."}, status=404)
    return p, None


@api_view(["GET"])
def bom_detail(request, pid):
    """The BOM + its variance report in one payload."""
    p, err = _get_project(request, pid)
    if err:
        return err
    data = bom_svc.variance(p)
    data["can_edit"] = request.user.role in EDIT_ROLES
    boq = getattr(p, "boq", None)
    data["can_seed"] = bool(boq and boq.mode == "UNIT"
                            and boq.categories.exists())
    return Response(data)


@api_view(["POST"])
def bom_save(request, pid):
    """Replace the BOM with reviewed rows [{item_id, qty, source, remarks}]."""
    p, err = _get_project(request, pid)
    if err:
        return err
    if request.user.role not in EDIT_ROLES:
        return Response({"detail": "The QS / PM maintains the BOM."},
                        status=403)
    n, msg = bom_svc.save_bom(p, request.data.get("rows") or [], request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    data = bom_svc.variance(p)
    data["can_edit"] = True
    data["saved"] = n
    return Response(data)


@api_view(["GET"])
def bom_seed(request, pid):
    """Draft rows from the unit BOQ's build-ups for the QS to map + commit."""
    p, err = _get_project(request, pid)
    if err:
        return err
    if request.user.role not in EDIT_ROLES:
        return Response({"detail": "The QS / PM maintains the BOM."},
                        status=403)
    rows = bom_svc.seed_from_boq(p)
    if not rows:
        return Response({"detail": "This project's BOQ has no per-unit "
                                   "build-ups to seed from — enter the BOM "
                                   "manually."}, status=400)
    return Response({"rows": rows})


@api_view(["GET"])
def bom_balance(request, pid):
    """Remaining orderable balance for one item — the MR form's over-BOM
    warning. ?item_id=N → {on_bom, balance}."""
    p, err = _get_project(request, pid)
    if err:
        return err
    try:
        item = Item.objects.get(pk=request.GET.get("item_id"))
    except (Item.DoesNotExist, ValueError, TypeError):
        return Response({"detail": "Unknown item."}, status=400)
    bal = bom_svc.bom_balance(p, item)
    return Response({"item_id": item.id, "on_bom": bal is not None,
                     "balance": bal})
