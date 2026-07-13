"""International purchase (IPR) API — Phase 1B (P1B-b).

The order is a Head Office instrument, so these endpoints are HO/Director/
Signatory/Finance only (site staff never see import prices, §6C.5). Submit /
award / return / cancel reuse the generic document-action endpoint; authorise
happens on a Payment Voucher.
"""
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import imports as ipr_svc
from .models import (CostHead, Document, ImportAllocation, ImportOrder,
                     ImportOrderLine, Project, Supplier)
from .serializers_documents import DocumentSerializer

VIEW_ROLES = ("HO_PURCHASING", "DIRECTOR", "SIGNATORY", "FINANCE", "ADMIN")
CREATE_ROLES = ("HO_PURCHASING", "ADMIN")


class AllocationSerializer(serializers.ModelSerializer):
    project_code = serializers.CharField(source="project.code",
                                         read_only=True, default=None)
    project_title = serializers.CharField(source="project.title",
                                          read_only=True, default=None)

    class Meta:
        model = ImportAllocation
        fields = ["id", "project", "project_code", "project_title", "qty",
                  "is_general_stock"]


class OrderLineSerializer(serializers.ModelSerializer):
    description = serializers.CharField(read_only=True)
    cost_head_name = serializers.CharField(source="cost_head.name",
                                           read_only=True)
    line_value = serializers.DecimalField(max_digits=18, decimal_places=2,
                                          read_only=True)
    allocations = AllocationSerializer(many=True, read_only=True)

    class Meta:
        model = ImportOrderLine
        fields = ["id", "line_no", "item", "description", "unit", "spec",
                  "order_qty", "unit_price", "cost_head", "cost_head_name",
                  "line_value", "remarks", "allocations"]


class OrderSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name",
                                          read_only=True)
    supplier_country = serializers.CharField(source="supplier.country",
                                             read_only=True)
    lines = OrderLineSerializer(many=True, read_only=True)

    class Meta:
        model = ImportOrder
        fields = ["supplier", "supplier_name", "supplier_country",
                  "order_currency", "exchange_rate", "incoterm",
                  "loading_port", "discharge_port", "pi_ref", "notes", "lines"]


def _get_ipr(request, ref):
    try:
        doc = Document.objects.select_related("current_revision").get(
            ref=ref, doc_type="IPR")
    except Document.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    if request.user.role not in VIEW_ROLES:
        return None, Response({"detail": "Not found."}, status=404)
    return doc, None


def _serialize(doc, request):
    order = doc.import_order
    data = DocumentSerializer(doc, context={"request": request}).data
    data["order"] = OrderSerializer(order).data
    data["order_total"] = ipr_svc.ipr_order_total(order)
    data["mvr_total"] = ipr_svc.ipr_mvr_total(order)
    data["pmr_refs"] = list(
        ipr_svc.linked_pmrs(doc).values_list("ref", flat=True))
    return data


@api_view(["GET", "POST"])
def ipr_list_create(request):
    if request.method == "POST":
        if request.user.role not in CREATE_ROLES:
            return Response({"detail": "Head Office raises import orders."},
                            status=403)
        doc, err = ipr_svc.create_ipr(request.data, request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(_serialize(doc, request), status=201)

    if request.user.role not in VIEW_ROLES:
        return Response({"detail": "Head Office view."}, status=403)
    qs = Document.objects.filter(doc_type="IPR").select_related(
        "import_order__supplier", "created_by").order_by("-id")
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    rows = [{
        "ref": d.ref, "status": d.status, "doc_date": d.doc_date,
        "supplier": d.import_order.supplier.name,
        "currency": d.import_order.order_currency,
        "order_total": ipr_svc.ipr_order_total(d.import_order),
        "mvr_total": ipr_svc.ipr_mvr_total(d.import_order),
    } for d in qs[:200]]
    return Response(rows)


@api_view(["GET"])
def ipr_detail(request, ref):
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    return Response(_serialize(doc, request))


@api_view(["GET"])
def ipr_context(request):
    """Everything the New-order form needs: overseas suppliers, cost heads,
    active projects (for allocation), and the sized-and-released PMRs that are
    ready to be ordered (with their lines as demand)."""
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office raises import orders."},
                        status=403)
    suppliers = [{"id": s.id, "name": s.name, "country": s.country,
                  "default_currency": s.default_currency,
                  "default_incoterm": s.default_incoterm}
                 for s in Supplier.objects.filter(
                     category="INTERNATIONAL", is_active=True).order_by("name")]
    heads = [{"id": h.id, "name": h.name}
             for h in CostHead.objects.filter(is_active=True, is_pool=False)
             .order_by("sort_order", "name")]
    projects = [{"id": p.id, "code": p.code, "title": p.title,
                 "site_code": p.site.code}
                for p in Project.objects.filter(
                    status__in=("ACTIVE", "AWARDED")).select_related("site")
                .order_by("code")]
    pmrs = []
    for d in Document.objects.filter(
            doc_type="PMR", status__in=("SIZED_RELEASED", "SOURCING"),
            is_void=False).select_related("project", "current_revision",
                                          "site").order_by("-id")[:100]:
        rev = d.current_revision
        pmrs.append({
            "ref": d.ref, "status": d.status,
            "project": d.project.code if d.project else None,
            "project_id": d.project_id, "site_code": d.site.code,
            "lines": [{"description": ln.description, "qty": ln.qty_required,
                       "unit": ln.unit, "spec": ln.spec, "item_id": ln.item_id}
                      for ln in rev.lines.all()] if rev else [],
        })
    return Response({"suppliers": suppliers, "cost_heads": heads,
                     "projects": projects, "pmrs": pmrs})
