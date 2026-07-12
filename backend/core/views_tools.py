"""Tools & Equipment register API (per site).

    GET  /tools/<site_id>              register (filter ?state=)
    POST /tools/<site_id>              add a tool manually (mobilisation)
    GET  /tools/<site_id>/summary      in-use summary by name (DPR loader)
    PATCH /tools/<asset_id>            edit serial / model / details
    POST  /tools/<asset_id>/state      faulty / repair / return / retire
"""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import tools as tools_svc
from .audit import audit
from .models import Item, Site, ToolAsset
from .permissions import scoped_site_ids

MANAGE_ROLES = ("ADMIN", "SITE_ADMIN", "SITE_ENGINEER", "PM")
# Per-unit details are free text; name/category are controlled (from the
# catalog item), so the DPR summary never fragments on spelling variants.
DETAIL_FIELDS = ("serial_no", "model", "brand", "notes")


def _get_site(request, site_id):
    try:
        site = Site.objects.get(pk=site_id)
    except Site.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    ids = scoped_site_ids(request.user)
    if ids is not None and site.id not in ids:
        return None, Response({"detail": "Not found."}, status=404)
    return site, None


def _asset_info(t):
    return {
        "id": t.id, "name": t.name, "category": t.category,
        "serial_no": t.serial_no, "model": t.model, "brand": t.brand,
        "notes": t.notes, "state": t.state, "state_note": t.state_note,
        "source": t.source, "grn": t.document.ref if t.document_id else None,
        "created_at": t.created_at,
    }


@api_view(["GET", "POST"])
def tools_register(request, site_id):
    site, err = _get_site(request, site_id)
    if err:
        return err
    if request.method == "POST":
        if request.user.role not in MANAGE_ROLES:
            return Response({"detail": "Only site staff manage tools."},
                            status=403)
        # Tool name/category are controlled — pick a catalog item in a tool
        # category so every unit of the same tool shares one exact name.
        item = None
        if request.data.get("item_id"):
            item = Item.objects.filter(pk=request.data["item_id"]).first()
        if not item or not tools_svc.is_tool_item(item):
            return Response(
                {"detail": "Choose a tool from the catalog. Tool types are "
                           "controlled — add a new one in the Item Register "
                           "under a tool category first."}, status=400)
        asset = ToolAsset.objects.create(
            site=site, item=item,
            name=item.description.strip(),
            category=item.category,
            serial_no=request.data.get("serial_no", ""),
            model=request.data.get("model", ""),
            brand=(request.data.get("brand") or item.brand or ""),
            notes=request.data.get("notes", ""),
            source=ToolAsset.Source.MOBILISATION, added_by=request.user)
        audit("tool_asset", asset.id, "TOOL_ADDED", actor=request.user,
              detail={"site": site.code, "name": asset.name})
        return Response(_asset_info(asset), status=201)

    qs = ToolAsset.objects.filter(site=site).select_related("document")
    if request.GET.get("state"):
        qs = qs.filter(state=request.GET["state"])
    counts = {}
    for t in ToolAsset.objects.filter(site=site):
        counts[t.state] = counts.get(t.state, 0) + 1
    return Response({
        "site_id": site.id, "site_code": site.code,
        "can_manage": request.user.role in MANAGE_ROLES,
        "counts": counts,
        "tools": [_asset_info(t) for t in qs],
    })


@api_view(["GET"])
def tool_catalog(request):
    """Controlled tool name/category source: catalog items in tool categories.
    The Add-tool form and edit reselection pick from these so names stay
    consistent for the DPR machinery summary."""
    items = [{"id": i.id, "description": i.description, "category": i.category,
              "brand": i.brand, "unit": i.unit}
             for i in tools_svc.tool_items()]
    return Response({"categories": tools_svc.tool_categories(),
                     "items": items})


@api_view(["GET"])
def tools_summary(request, site_id):
    """In-use summary by name — the DPR machinery loader source."""
    site, err = _get_site(request, site_id)
    if err:
        return err
    return Response({"machinery": tools_svc.summary(site)})


@api_view(["PATCH"])
def tool_detail(request, pk):
    try:
        asset = ToolAsset.objects.select_related("site").get(pk=pk)
    except ToolAsset.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    _, err = _get_site(request, asset.site_id)
    if err:
        return err
    if request.user.role not in MANAGE_ROLES:
        return Response({"detail": "Only site staff manage tools."}, status=403)
    changed = []
    for f in DETAIL_FIELDS:
        if f in request.data:
            setattr(asset, f, request.data[f] or "")
            changed.append(f)
    if changed:
        asset.save(update_fields=changed + ["updated_at"])
        audit("tool_asset", asset.id, "TOOL_UPDATED", actor=request.user,
              detail={"fields": sorted(changed)})
    return Response(_asset_info(asset))


@api_view(["POST"])
def tool_state(request, pk):
    try:
        asset = ToolAsset.objects.select_related("site").get(pk=pk)
    except ToolAsset.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    _, err = _get_site(request, asset.site_id)
    if err:
        return err
    if request.user.role not in MANAGE_ROLES:
        return Response({"detail": "Only site staff manage tools."}, status=403)
    state = request.data.get("state")
    if state not in ToolAsset.State.values:
        return Response({"detail": "Unknown state."}, status=400)
    note = (request.data.get("note") or "").strip()
    if state in (ToolAsset.State.FAULTY, ToolAsset.State.RETIRED) and not note:
        return Response({"detail": "A note/reason is required."}, status=400)
    tools_svc.set_state(asset, state, note, request.user)
    return Response(_asset_info(asset))
