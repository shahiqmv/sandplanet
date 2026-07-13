"""International purchase (IPR) API — Phase 1B (P1B-b).

The order is a Head Office instrument, so these endpoints are HO/Director/
Signatory/Finance only (site staff never see import prices, §6C.5). Submit /
award / return / cancel reuse the generic document-action endpoint; authorise
happens on a Payment Voucher.
"""
from decimal import Decimal

from rest_framework import serializers
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from . import imports as ipr_svc
from .models import (CostHead, Document, ImportAllocation, ImportOrder,
                     ImportOrderLine, ImportPaymentMilestone, ImportReceipt,
                     ImportReceiptLine, ImportShipment, Project,
                     ShipmentDocument, Site, StockLot, Supplier)
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
    proforma_invoice_url = serializers.SerializerMethodField()
    lines = OrderLineSerializer(many=True, read_only=True)

    class Meta:
        model = ImportOrder
        fields = ["supplier", "supplier_name", "supplier_country",
                  "order_currency", "exchange_rate", "incoterm",
                  "loading_port", "discharge_port", "pi_ref",
                  "proforma_invoice_url", "notes", "lines"]

    def get_proforma_invoice_url(self, obj):
        return obj.proforma_invoice.url if obj.proforma_invoice else None


class MilestoneSerializer(serializers.ModelSerializer):
    due_amount = serializers.SerializerMethodField()
    tt_advice_url = serializers.SerializerMethodField()
    voucher_ref = serializers.CharField(source="voucher.ref", read_only=True,
                                        default=None)

    class Meta:
        model = ImportPaymentMilestone
        fields = ["id", "seq", "label", "trigger", "percent", "fixed_amount",
                  "due_date", "status", "due_amount", "tt_ref", "mvr_paid",
                  "actual_rate", "paid_at", "tt_advice_url", "voucher_ref"]

    def get_tt_advice_url(self, obj):
        return obj.tt_advice.url if obj.tt_advice else None

    def get_due_amount(self, obj):
        # order total is stashed on context to avoid a query per milestone
        total = (self.context or {}).get("order_total")
        if total is None:
            total = ipr_svc.ipr_order_total(obj.order)
        return obj.due_amount(total)


class ShipmentDocumentSerializer(serializers.ModelSerializer):
    doc_type_display = serializers.CharField(source="get_doc_type_display",
                                             read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = ShipmentDocument
        fields = ["id", "doc_type", "doc_type_display", "file_url",
                  "file_name", "notes", "uploaded_at"]

    def get_file_url(self, obj):
        return obj.file.url if obj.file else None


class ShipmentSerializer(serializers.ModelSerializer):
    forwarder_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display",
                                           read_only=True)
    documents = ShipmentDocumentSerializer(many=True, read_only=True)
    clearing_total = serializers.DecimalField(max_digits=16, decimal_places=2,
                                              read_only=True)
    missing_clearing = serializers.SerializerMethodField()
    next_statuses = serializers.SerializerMethodField()

    class Meta:
        model = ImportShipment
        fields = ["id", "seq", "mode", "forwarder", "forwarder_display",
                  "vessel_flight", "container_awb", "etd", "eta",
                  "tracking_ref", "carrier_link", "status", "status_display",
                  "shared_with_agent_at", "freight", "insurance",
                  "customs_duty", "import_gst", "port_handling",
                  "agent_charges", "local_transport",
                  "clearing_total", "documents", "missing_clearing",
                  "next_statuses", "notes"]

    def get_forwarder_display(self, obj):
        return obj.forwarder.name if obj.forwarder_id else obj.forwarder_name

    def get_missing_clearing(self, obj):
        return ipr_svc.missing_clearing_docs(obj)

    def get_next_statuses(self, obj):
        return sorted(ImportShipment.NEXT.get(obj.status, set()))


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
    data["shipments"] = ShipmentSerializer(
        order.shipments.prefetch_related("documents", "receipts").all(),
        many=True).data
    data["landed"] = ipr_svc.landed_cost(order)
    data["receipts"] = [
        {"ref": r.document.ref, "status": r.document.status,
         "shipment_seq": r.shipment.seq}
        for r in ImportReceipt.objects.filter(shipment__order=order)
        .select_related("document", "shipment")]
    data["can_pay"] = request.user.role in PAY_ROLES
    data["can_manage"] = request.user.role in CREATE_ROLES
    return data


class ReceiptLineSerializer(serializers.ModelSerializer):
    description = serializers.CharField(source="ipr_line.description",
                                        read_only=True)
    unit = serializers.CharField(source="ipr_line.unit", read_only=True)

    class Meta:
        model = ImportReceiptLine
        fields = ["id", "description", "unit", "expected_qty", "received_qty",
                  "damaged_qty", "condition_note", "variance"]


def _irn_payload(doc, request):
    receipt = doc.import_receipt
    order = receipt.order
    lc = ipr_svc.landed_cost(order)
    data = DocumentSerializer(doc, context={"request": request}).data
    data["ipr_ref"] = order.document.ref
    data["supplier"] = order.supplier.name
    data["shipment_seq"] = receipt.shipment.seq
    data["location"] = receipt.location
    data["can_post"] = (request.user.role in CREATE_ROLES
                        and doc.status == "DRAFT")
    lines = []
    for rl in receipt.lines.select_related("ipr_line").all():
        row = ReceiptLineSerializer(rl).data
        row["unit_landed_cost"] = lc["lines"].get(
            rl.ipr_line_id, {}).get("unit_landed")
        lines.append(row)
    data["lines"] = lines
    data["landed"] = lc
    return data


def _get_irn(request, ref):
    try:
        doc = Document.objects.select_related("current_revision").get(
            ref=ref, doc_type="IRN")
    except Document.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    if request.user.role not in VIEW_ROLES:
        return None, Response({"detail": "Not found."}, status=404)
    return doc, None


def _get_shipment(doc, pk):
    return doc.import_order.shipments.filter(pk=pk).first()


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def ipr_proforma_upload(request, ref):
    """HO uploads the supplier's proforma invoice so the Director / Signatory
    can view it before authorising the order (owner 2026-07-13)."""
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office uploads the proforma invoice."},
                        status=403)
    upload = request.FILES.get("file")
    if upload is None:
        return Response({"detail": "A file is required."}, status=400)
    order = doc.import_order
    order.proforma_invoice = upload
    if request.data.get("pi_ref"):
        order.pi_ref = request.data["pi_ref"]
    order.save(update_fields=["proforma_invoice", "pi_ref"])
    return Response(_serialize(doc, request))


@api_view(["POST"])
def ipr_shipment_create(request, ref):
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office manages shipments."},
                        status=403)
    ipr_svc.create_shipment(doc.import_order, request.data, request.user)
    return Response(_serialize(doc, request), status=201)


@api_view(["POST"])
def ipr_shipment_status(request, ref, pk):
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office manages shipments."},
                        status=403)
    s = _get_shipment(doc, pk)
    if not s:
        return Response({"detail": "Not found."}, status=404)
    msg = ipr_svc.advance_shipment(s, request.data.get("status"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_serialize(doc, request))


@api_view(["POST"])
def ipr_shipment_charges(request, ref, pk):
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES + ("FINANCE",):
        return Response({"detail": "Head Office / Finance record charges."},
                        status=403)
    s = _get_shipment(doc, pk)
    if not s:
        return Response({"detail": "Not found."}, status=404)
    ipr_svc.set_clearing_charges(s, request.data, request.user)
    return Response(_serialize(doc, request))


@api_view(["POST"])
def ipr_shipment_share(request, ref, pk):
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office shares with the agent."},
                        status=403)
    s = _get_shipment(doc, pk)
    if not s:
        return Response({"detail": "Not found."}, status=404)
    ipr_svc.share_with_agent(s, request.user)
    return Response(_serialize(doc, request))


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def ipr_shipment_document(request, ref, pk):
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office uploads shipping documents."},
                        status=403)
    s = _get_shipment(doc, pk)
    if not s:
        return Response({"detail": "Not found."}, status=404)
    upload = request.FILES.get("file")
    doc_type = request.data.get("doc_type")
    if upload is None or not doc_type:
        return Response({"detail": "A file and document type are required."},
                        status=400)
    ipr_svc.add_shipment_document(s, doc_type, upload, request.user,
                                  notes=request.data.get("notes", ""))
    return Response(_serialize(doc, request), status=201)


@api_view(["POST"])
def ipr_shipment_receive(request, ref, pk):
    """Open an IRN to count this shipment into the HO store."""
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office receives shipments."},
                        status=403)
    s = _get_shipment(doc, pk)
    if not s:
        return Response({"detail": "Not found."}, status=404)
    irn = ipr_svc.create_receipt(s, request.data, request.user)
    return Response(_irn_payload(irn, request), status=201)


@api_view(["GET"])
def irn_detail(request, ref):
    doc, err = _get_irn(request, ref)
    if err:
        return err
    return Response(_irn_payload(doc, request))


@api_view(["POST"])
def irn_save_counts(request, ref):
    doc, err = _get_irn(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES or doc.status != "DRAFT":
        return Response({"detail": "Only a draft IRN can be edited by HO."},
                        status=403)
    ipr_svc.save_receipt_counts(doc.import_receipt, request.data.get("rows")
                                or [], request.user)
    return Response(_irn_payload(doc, request))


@api_view(["POST"])
def irn_post(request, ref):
    doc, err = _get_irn(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office posts the receipt."},
                        status=403)
    if doc.status != "DRAFT":
        return Response({"detail": "This IRN is already posted."}, status=400)
    if request.data.get("rows"):
        ipr_svc.save_receipt_counts(doc.import_receipt, request.data["rows"],
                                    request.user)
    ipr_svc.post_receipt(doc, request.user)
    doc.refresh_from_db()
    return Response(_irn_payload(doc, request))


@api_view(["GET"])
def store_lots(request):
    """The HO store: valued stock lots, reserved-to-project or general."""
    if request.user.role not in VIEW_ROLES:
        return Response({"detail": "Head Office store view."}, status=403)
    rows = []
    for lot in ipr_svc.store_lots(project_id=request.GET.get("project")):
        rows.append({
            "id": lot.id, "description": lot.description, "unit": lot.unit,
            "qty_on_hand": lot.qty_on_hand,
            "qty_in_transit": lot.qty_in_transit,
            "unit_landed_cost": lot.unit_landed_cost,
            "value_on_hand": (lot.qty_on_hand * lot.unit_landed_cost)
            .quantize(Decimal("0.01")),
            "reserved_for": (lot.project.code if lot.project_id
                             else "General stock"),
            "project_id": lot.project_id,
            "site": lot.project.site.code if lot.project_id else "—",
            "source_irn": lot.source_receipt.document.ref,
            "location": lot.location, "received_date": lot.received_date,
        })
    total = sum((r["value_on_hand"] for r in rows), Decimal("0"))
    return Response({"lots": rows, "total_value": total})


# ---- SIN — store issue to site (P1B-f) -----------------------------------

def _sin_payload(doc, request):
    issue = doc.store_issue
    data = DocumentSerializer(doc, context={"request": request}).data
    data["to_site"] = issue.to_site.code
    data["to_project"] = issue.to_project.code if issue.to_project_id else None
    data["notes"] = issue.notes
    data["issued_by"] = issue.issued_by.full_name if issue.issued_by_id else None
    data["can_issue"] = (request.user.role in CREATE_ROLES
                         and doc.status == "DRAFT")
    lines, total = [], Decimal("0")
    for ln in issue.lines.select_related("lot__item").all():
        val = (ln.qty * ln.unit_landed_cost).quantize(Decimal("0.01"))
        total += val
        lines.append({
            "id": ln.id, "description": ln.lot.description,
            "unit": ln.lot.unit, "qty": ln.qty,
            "unit_landed_cost": ln.unit_landed_cost, "value": val,
            "source_irn": ln.lot.source_receipt.document.ref,
            "reserved_for": (ln.lot.project.code if ln.lot.project_id
                             else "General stock")})
    data["lines"] = lines
    data["total_value"] = total
    return data


def _get_sin(request, ref):
    try:
        doc = Document.objects.select_related("current_revision").get(
            ref=ref, doc_type="SIN")
    except Document.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    if request.user.role not in VIEW_ROLES:
        return None, Response({"detail": "Not found."}, status=404)
    return doc, None


@api_view(["GET", "POST"])
def store_issues(request):
    if request.method == "POST":
        if request.user.role not in CREATE_ROLES:
            return Response({"detail": "Head Office issues store stock."},
                            status=403)
        try:
            to_site = Site.objects.get(pk=request.data.get("to_site_id"))
        except Site.DoesNotExist:
            return Response({"detail": "Choose the destination site."},
                            status=400)
        to_project = None
        if request.data.get("to_project_id"):
            to_project = Project.objects.filter(
                pk=request.data["to_project_id"]).first()
        doc, err = ipr_svc.create_store_issue(
            to_site, to_project, request.data.get("rows") or [], request.user,
            notes=request.data.get("notes", ""))
        if err:
            return Response({"detail": err}, status=400)
        return Response(_sin_payload(doc, request), status=201)

    if request.user.role not in VIEW_ROLES:
        return Response({"detail": "Head Office store view."}, status=403)
    qs = Document.objects.filter(doc_type="SIN").select_related(
        "store_issue__to_site", "store_issue__to_project").order_by("-id")
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    rows = [{
        "ref": d.ref, "status": d.status, "doc_date": d.doc_date,
        "to_site": d.store_issue.to_site.code,
        "to_project": (d.store_issue.to_project.code
                       if d.store_issue.to_project_id else None),
        "lines": d.store_issue.lines.count(),
    } for d in qs[:200]]
    return Response(rows)


@api_view(["GET"])
def sin_detail(request, ref):
    doc, err = _get_sin(request, ref)
    if err:
        return err
    return Response(_sin_payload(doc, request))


@api_view(["POST"])
def sin_issue(request, ref):
    doc, err = _get_sin(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office issues store stock."},
                        status=403)
    if doc.status != "DRAFT":
        return Response({"detail": "Only a draft SIN can be issued."},
                        status=400)
    msg = ipr_svc.issue_store_issue(doc, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    doc.refresh_from_db()
    return Response(_sin_payload(doc, request))


@api_view(["POST"])
def sin_cancel(request, ref):
    doc, err = _get_sin(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office manages the store."},
                        status=403)
    msg = ipr_svc.cancel_store_issue(doc, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    doc.refresh_from_db()
    return Response(_sin_payload(doc, request))


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def ipr_milestone_tt_advice(request, ref, pk):
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.user.role not in PAY_ROLES:
        return Response({"detail": "Finance uploads the TT advice."},
                        status=403)
    m = _get_milestone(doc, pk)
    if not m:
        return Response({"detail": "Not found."}, status=404)
    upload = request.FILES.get("file")
    if upload is None:
        return Response({"detail": "A file is required."}, status=400)
    m.tt_advice = upload
    m.save(update_fields=["tt_advice"])
    return Response(_serialize(doc, request))


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
            "due_date": m.due_date, "status": m.status,
            "stage": ("READY" if m.status == "AUTHORISED"
                      else "AWAITING_VOUCHER"),
            "voucher_ref": m.voucher.ref if m.voucher_id else None,
        })
    return Response(rows)


@api_view(["GET"])
def imports_tracker(request):
    """One row per overseas order with its live stage across the pipeline
    (PMR demand → order → shipments → receipt → payments), plus sized-and-
    released PMRs still awaiting an order (owner 2026-07-13)."""
    if request.user.role not in VIEW_ROLES:
        return Response({"detail": "Head Office view."}, status=403)
    orders = []
    for d in Document.objects.filter(doc_type="IPR").select_related(
            "import_order__supplier", "created_by").order_by("-id")[:200]:
        o = d.import_order
        ships = list(o.shipments.all())
        milestones = list(o.milestones.all())
        receipts = ImportReceipt.objects.filter(
            shipment__order=o).select_related("document")
        orders.append({
            "ref": d.ref, "status": d.status, "supplier": o.supplier.name,
            "currency": o.order_currency,
            "order_total": ipr_svc.ipr_order_total(o),
            "pmrs": list(ipr_svc.linked_pmrs(d).values_list("ref", flat=True)),
            "shipments": [{"seq": s.seq, "status": s.status,
                           "status_display": s.get_status_display(),
                           "eta": s.eta} for s in ships],
            "milestones_paid": sum(1 for m in milestones
                                   if m.status == "PAID"),
            "milestones_total": len(milestones),
            "receipts": [{"ref": r.document.ref, "status": r.document.status}
                         for r in receipts],
            "created_by": d.created_by.full_name if d.created_by else None,
            "doc_date": d.doc_date,
        })
    awaiting_order = [
        {"ref": p.ref, "status": p.status,
         "project": p.project.code if p.project else None,
         "site": p.site.code, "doc_date": p.doc_date}
        for p in Document.objects.filter(
            doc_type="PMR", status__in=("SIZED_RELEASED", "SOURCING"),
            is_void=False).select_related("project", "site").order_by("-id")]
    return Response({"orders": orders, "awaiting_order": awaiting_order})


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
    from .models import Item
    items = [{"id": it.id, "code": it.code, "description": it.description,
              "unit": it.unit}
             for it in Item.objects.filter(is_active=True, merged_into__isnull=True)
             .order_by("code")]
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
                     "items": items, "projects": projects, "pmrs": pmrs})
