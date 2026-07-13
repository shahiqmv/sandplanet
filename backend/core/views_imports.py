"""International purchase (IPR) API — Phase 1B (P1B-b).

The order is a Head Office instrument, so these endpoints are HO/Director/
Signatory/Finance only (site staff never see import prices, §6C.5). Submit /
award / return / cancel reuse the generic document-action endpoint; authorise
happens on a Payment Voucher.
"""
from decimal import Decimal

from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import imports as ipr_svc
from .models import (CostHead, Document, ImportAllocation, ImportOrder,
                     ImportOrderLine, ImportPaymentMilestone, Project, Supplier)
from .serializers_documents import DocumentSerializer

VIEW_ROLES = ("HO_PURCHASING", "DIRECTOR", "SIGNATORY", "FINANCE", "ADMIN")
CREATE_ROLES = ("HO_PURCHASING", "ADMIN")
PAY_ROLES = ("FINANCE", "ADMIN")


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


class MilestoneSerializer(serializers.ModelSerializer):
    due_amount = serializers.SerializerMethodField()

    class Meta:
        model = ImportPaymentMilestone
        fields = ["id", "seq", "label", "trigger", "percent", "fixed_amount",
                  "due_date", "status", "due_amount", "tt_ref", "mvr_paid",
                  "actual_rate", "paid_at"]

    def get_due_amount(self, obj):
        # order total is stashed on context to avoid a query per milestone
        total = (self.context or {}).get("order_total")
        if total is None:
            total = ipr_svc.ipr_order_total(obj.order)
        return obj.due_amount(total)


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
    total = ipr_svc.ipr_order_total(order)
    data = DocumentSerializer(doc, context={"request": request}).data
    data["order"] = OrderSerializer(order).data
    data["order_total"] = total
    data["mvr_total"] = ipr_svc.ipr_mvr_total(order)
    data["pmr_refs"] = list(
        ipr_svc.linked_pmrs(doc).values_list("ref", flat=True))
    data["milestones"] = MilestoneSerializer(
        order.milestones.all(), many=True,
        context={"order_total": total}).data
    data["can_pay"] = request.user.role in PAY_ROLES
    data["can_manage"] = request.user.role in CREATE_ROLES
    return data


def _get_milestone(doc, pk):
    return doc.import_order.milestones.filter(pk=pk).first()


@api_view(["POST"])
def ipr_set_milestones(request, ref):
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office sets the payment schedule."},
                        status=403)
    msg = ipr_svc.set_milestones(doc.import_order, request.data.get("rows") or [])
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_serialize(doc, request))


@api_view(["POST"])
def ipr_milestone_due(request, ref, pk):
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office marks a milestone due."},
                        status=403)
    m = _get_milestone(doc, pk)
    if not m:
        return Response({"detail": "Not found."}, status=404)
    msg = ipr_svc.mark_milestone_due(m, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_serialize(doc, request))


@api_view(["POST"])
def ipr_milestone_pay(request, ref, pk):
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.user.role not in PAY_ROLES:
        return Response({"detail": "Finance records import payments."},
                        status=403)
    m = _get_milestone(doc, pk)
    if not m:
        return Response({"detail": "Not found."}, status=404)
    msg = ipr_svc.pay_milestone(m, request.data.get("mvr_paid"),
                                request.data.get("tt_ref", ""), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_serialize(doc, request))


@api_view(["GET"])
def ipr_payments_due(request):
    if request.user.role not in PAY_ROLES:
        return Response({"detail": "Finance view."}, status=403)
    rows = []
    for m in ipr_svc.payments_due():
        total = ipr_svc.ipr_order_total(m.order)
        rows.append({
            "ipr_ref": m.order.document.ref, "milestone_id": m.id,
            "label": m.label, "supplier": m.order.supplier.name,
            "currency": m.order.order_currency,
            "due_amount": m.due_amount(total),
            "expected_mvr": (m.due_amount(total) * m.order.exchange_rate)
            .quantize(Decimal("0.01")),
            "due_date": m.due_date,
        })
    return Response(rows)


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
