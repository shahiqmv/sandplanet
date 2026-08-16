"""Site-to-site transfer endpoints (MTN). The rules live in `transfers`."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import transfers
from .models import Project, Site, SiteTransfer
from .permissions import scoped_site_ids


def _visible(user):
    """A transfer is visible to either end of it."""
    ids = scoped_site_ids(user)
    qs = SiteTransfer.objects.select_related(
        "document", "document__site", "to_site", "approved_by",
        "despatched_by", "received_by").prefetch_related(
        "lines__item", "lines__tool")
    if ids is None:
        return qs
    from django.db.models import Q
    return qs.filter(Q(document__site_id__in=ids) | Q(to_site_id__in=ids))


def _line(ln):
    return {"id": ln.id,
            "item_id": ln.item_id,
            "item_code": ln.item.code if ln.item_id else None,
            "description": (ln.tool.name if ln.tool_id
                            else ln.item.description if ln.item_id else ""),
            "unit": ln.item.unit if ln.item_id else "",
            "tool_id": ln.tool_id,
            "serial_no": ln.tool.serial_no if ln.tool_id else "",
            "qty": ln.qty, "received_qty": ln.received_qty,
            "shortage": ln.shortage, "note": ln.note}


def _info(tr):
    return {
        "id": tr.id, "ref": tr.document.ref, "status": tr.status,
        "status_label": tr.get_status_display(),
        "from_site": tr.from_site.code, "from_site_id": tr.document.site_id,
        "to_site": tr.to_site.code, "to_site_id": tr.to_site_id,
        "to_project": tr.to_project.code if tr.to_project_id else None,
        "reason": tr.reason, "receipt_note": tr.receipt_note,
        "doc_date": tr.document.doc_date,
        "approved_by": tr.approved_by.full_name if tr.approved_by_id else None,
        "despatched_at": tr.despatched_at,
        "received_by": tr.received_by.full_name if tr.received_by_id else None,
        "received_at": tr.received_at,
        "lines": [_line(l) for l in tr.lines.all()],
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def transfer_list(request):
    if request.method == "POST":
        if request.user.role not in transfers.RAISE_ROLES:
            return Response({"detail": "Site team or Admin raise a transfer."},
                            status=403)
        try:
            from_site = Site.objects.get(pk=request.data.get("from_site_id"))
            to_site = Site.objects.get(pk=request.data.get("to_site_id"))
        except Site.DoesNotExist:
            return Response({"detail": "Both sites are required."}, status=400)
        ids = scoped_site_ids(request.user)
        if ids is not None and from_site.id not in ids:
            return Response({"detail": "Not your site to send from."},
                            status=403)
        project = Project.objects.filter(
            pk=request.data.get("to_project_id")).first()
        tr, err = transfers.create_transfer(
            from_site, to_site, request.data.get("lines") or [], request.user,
            reason=request.data.get("reason", ""), to_project=project)
        if err:
            return Response({"detail": err}, status=400)
        return Response(_info(tr), status=201)

    qs = _visible(request.user)
    site_id = request.GET.get("site")
    if site_id:
        from django.db.models import Q
        qs = qs.filter(Q(document__site_id=site_id) | Q(to_site_id=site_id))
    if request.GET.get("open") == "1":
        qs = qs.exclude(status__in=("RECEIVED", "CANCELLED"))
    return Response({"transfers": [_info(t) for t in
                                   qs.order_by("-id")[:200]]})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def transfer_action(request, pk):
    tr = _visible(request.user).filter(pk=pk).first()
    if tr is None:
        return Response({"detail": "Not found."}, status=404)
    action = request.data.get("action")
    if action == "approve":
        _, err = transfers.approve(tr, request.user)
    elif action == "despatch":
        _, err = transfers.despatch(tr, request.user)
    elif action == "receive":
        # only the receiving end counts it in
        ids = scoped_site_ids(request.user)
        if ids is not None and tr.to_site_id not in ids:
            return Response({"detail": f"Only {tr.to_site.code} can receive "
                                       "this."}, status=403)
        _, err = transfers.receive(tr, request.data.get("counts") or {},
                                   request.user,
                                   note=request.data.get("note", ""))
    elif action == "cancel":
        _, err = transfers.cancel(tr, request.user,
                                  request.data.get("reason", ""))
    else:
        return Response({"detail": "Unknown action."}, status=400)
    if err:
        return Response({"detail": err}, status=400)
    tr.refresh_from_db()
    return Response(_info(tr))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def transferable(request, site_id):
    """What this site could send: stock on hand, and tools not retired."""
    from . import stock
    from .models import ToolAsset
    site = Site.objects.filter(pk=site_id).first()
    if site is None:
        return Response({"detail": "Not found."}, status=404)
    ids = scoped_site_ids(request.user)
    if ids is not None and site.id not in ids:
        return Response({"detail": "Not your site."}, status=403)
    items = [r for r in stock.balances(site) if (r.get("on_hand") or 0) > 0]
    tools = ToolAsset.objects.filter(site=site).exclude(
        state=ToolAsset.State.RETIRED).order_by("name")
    return Response({
        "items": items,
        "tools": [{"id": t.id, "name": t.name, "serial_no": t.serial_no,
                   "state": t.state} for t in tools],
    })
