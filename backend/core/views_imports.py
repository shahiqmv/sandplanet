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
from .audit import audit
from .models import (CostHead, Document, ImportAllocation, ImportOrder,
                     ImportOrderLine, ImportPaymentMilestone, ImportReceipt,
                     ImportReceiptLine, ImportShipment, ImportShipmentLine,
                     Project, ShipmentDocument, ShipmentPayment, Site, Supplier)
from .serializers_documents import DocumentSerializer

VIEW_ROLES = ("HO_PURCHASING", "DIRECTOR", "SIGNATORY", "FINANCE", "ADMIN",
              "QS", "PA")  # QS: overseas-procurement authority; PA: read-only
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
    shipped_qty = serializers.SerializerMethodField()
    remaining_qty = serializers.SerializerMethodField()

    class Meta:
        model = ImportOrderLine
        fields = ["id", "line_no", "item", "description", "unit", "spec",
                  "order_qty", "unit_price", "cost_head", "cost_head_name",
                  "line_value", "remarks", "allocations",
                  "shipped_qty", "remaining_qty"]

    def get_shipped_qty(self, obj):
        return ipr_svc.line_shipped(obj)

    def get_remaining_qty(self, obj):
        return ipr_svc.line_remaining(obj)


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
                  "discount", "freight_handling", "misc_fee",
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
                  "actual_rate", "paid_at", "tt_advice_url", "voucher_ref", "credit_days", "fell_due_on", "pay_by"]

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


class ShipmentLineSerializer(serializers.ModelSerializer):
    description = serializers.CharField(source="ipr_line.description",
                                        read_only=True)
    unit = serializers.CharField(source="ipr_line.unit", read_only=True)
    line_no = serializers.IntegerField(source="ipr_line.line_no",
                                       read_only=True)

    class Meta:
        model = ImportShipmentLine
        fields = ["id", "ipr_line", "line_no", "description", "unit", "qty"]


class ShipmentPaymentSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display",
                                         read_only=True)
    payee_display = serializers.SerializerMethodField()
    invoice_url = serializers.SerializerMethodField()
    pyr_ref = serializers.CharField(source="pyr.ref", read_only=True,
                                    default=None)
    pyr_status = serializers.CharField(source="pyr.status", read_only=True,
                                       default=None)

    class Meta:
        model = ShipmentPayment
        fields = ["id", "kind", "kind_display", "payee", "payee_name",
                  "payee_display", "amount", "currency", "invoice_url",
                  "invoice_ref", "pyr_ref", "pyr_status", "notes"]

    def get_payee_display(self, obj):
        return obj.resolved_payee()

    def get_invoice_url(self, obj):
        return obj.invoice.url if obj.invoice else None


class ShipmentSerializer(serializers.ModelSerializer):
    forwarder_display = serializers.SerializerMethodField()
    payments = ShipmentPaymentSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display",
                                           read_only=True)
    documents = ShipmentDocumentSerializer(many=True, read_only=True)
    lines = ShipmentLineSerializer(many=True, read_only=True)
    clearing_total = serializers.DecimalField(max_digits=16, decimal_places=2,
                                              read_only=True)
    missing_clearing = serializers.SerializerMethodField()
    next_statuses = serializers.SerializerMethodField()
    tracking = serializers.SerializerMethodField()

    class Meta:
        model = ImportShipment
        fields = ["id", "seq", "mode", "forwarder", "forwarder_display",
                  "vessel_flight", "carrier_scac", "bl_no", "container_awb",
                  "etd", "eta", "tracking_ref", "carrier_link", "status",
                  "status_display", "shared_with_agent_at", "freight",
                  "insurance", "customs_duty", "import_gst", "port_handling",
                  "agent_charges", "local_transport",
                  "clearing_total", "documents", "lines", "missing_clearing",
                  "next_statuses", "notes", "tracking",
                  "shipping_agent", "clearing_agent", "payments"]

    def get_forwarder_display(self, obj):
        return obj.forwarder.name if obj.forwarder_id else obj.forwarder_name

    def get_tracking(self, obj):
        t = getattr(obj, "tracking", None)
        if t is None:
            return None
        # stakeholder timeline shows only the normalised milestones, newest last
        events = [e for e in t.events.all() if e.code != "OTHER"]
        from . import tracking as trk
        health = trk.health_for(t)
        movements = trk.movements_for(t)
        return {
            "state": t.state, "state_display": t.get_state_display(),
            "health": health, "reason": trk.reason_for(t, health),
            "mode": t.mode, "carrier_scac": t.carrier_scac,
            "tracking_key": t.tracking_key,
            "raw_status": t.raw_status, "map_url": t.map_url,
            "current_eta": t.current_eta, "last_event_at": t.last_event_at,
            "last_polled_at": t.last_polled_at, "registered_at": t.created_at,
            "register_attempts": t.register_attempts,
            "provider_tracking_id": t.provider_tracking_id,
            "last_error": t.last_error,
            "movements": movements,
            "events": [{
                "code": e.code, "code_display": e.get_code_display(),
                "description": e.description, "location": e.location,
                "vessel_flight": e.vessel_flight, "event_time": e.event_time,
                "is_actual": e.is_actual, "source": e.source,
            } for e in events],
        }

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
    # A voided order stays readable (number kept, §7.2) but nothing on it may
    # move — the generic document actions already refuse, this covers the
    # IPR-specific endpoints (shipments, milestones, charges, share…).
    if doc.is_void and request.method not in ("GET", "HEAD", "OPTIONS"):
        return None, Response({"detail": "This order is void."}, status=400)
    return doc, None


def _serialize(doc, request):
    order = doc.import_order
    total = ipr_svc.ipr_order_total(order)
    data = DocumentSerializer(doc, context={"request": request}).data
    data["order"] = OrderSerializer(order).data
    data["line_subtotal"] = ipr_svc.ipr_line_subtotal(order)
    data["order_total"] = total
    data["mvr_total"] = ipr_svc.ipr_mvr_total(order)
    # When the supplier already charges freight on the PI, the forwarder-freight
    # charge on the shipment doesn't apply (owner 2026-07-23).
    data["supplier_charges_freight"] = bool(
        order.freight_handling and order.freight_handling > 0)
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
    # A voided order is read-only for everyone — no client shows its
    # manage/pay controls (the endpoints refuse anyway, see _get_ipr).
    data["can_pay"] = request.user.role in PAY_ROLES and not doc.is_void
    data["can_manage"] = (request.user.role in CREATE_ROLES
                          and not doc.is_void)
    corr = ipr_svc.pending_charge_correction(order)
    data["charge_correction"] = ({
        "id": corr.id, "status": corr.status, "reason": corr.reason,
        "discount": corr.discount, "freight_handling": corr.freight_handling,
        "misc_fee": corr.misc_fee,
        "fold_lines": [{"id": ln.id, "description": ln.description}
                       for ln in order.lines.filter(
                           id__in=corr.fold_line_ids or [])],
        "created_by": corr.created_by.get_full_name() or corr.created_by.username,
    } if corr else None)
    data["can_correct"] = (request.user.role in CREATE_ROLES
                           and doc.status == "AUTHORISED")
    data["can_decide_correction"] = request.user.role in (
        "DIRECTOR", "QS", "SIGNATORY", "ADMIN")
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
    _, msg = ipr_svc.create_shipment(doc.import_order, request.data,
                                     request.user)
    if msg:
        return Response({"detail": msg}, status=400)
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
def ipr_shipment_update(request, ref, pk):
    """Edit a booked shipment's carrier / routing details (incl. the tracking
    keys). Real imports enter the B/L after departure, so this also re-registers
    live tracking when keys change."""
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office manages shipments."},
                        status=403)
    s = _get_shipment(doc, pk)
    if not s:
        return Response({"detail": "Not found."}, status=404)
    msg = ipr_svc.update_shipment_details(s, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_serialize(doc, request))


@api_view(["POST"])
def ipr_shipment_delete(request, ref, pk):
    """Delete a shipment — admin only (destructive; frees its allocation and
    removes its tracking). Blocked once an IRN exists for it."""
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.user.role != "ADMIN":
        return Response({"detail": "Only an administrator can delete a "
                                   "shipment."}, status=403)
    s = _get_shipment(doc, pk)
    if not s:
        return Response({"detail": "Not found."}, status=404)
    msg = ipr_svc.delete_shipment(s, request.user)
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
@parser_classes([MultiPartParser, FormParser])
def ipr_shipment_payment(request, ref, pk, kind):
    """Enter/edit a shipment charge (payee / amount / invoice-ref) and, if a
    file is attached, its invoice."""
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES + ("FINANCE",):
        return Response({"detail": "Head Office / Finance record charges."},
                        status=403)
    s = _get_shipment(doc, pk)
    if not s:
        return Response({"detail": "Not found."}, status=404)
    payment, msg = ipr_svc.set_shipment_payment(s, kind.upper(), request.data,
                                                request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    upload = request.FILES.get("invoice")
    if upload is not None:
        payment.invoice = upload
        payment.save(update_fields=["invoice", "updated_at"])
    return Response(_serialize(doc, request))


@api_view(["POST"])
def ipr_shipment_payment_raise(request, ref, pk, kind):
    """Raise the capitalized PYR that pays this charge to its agent."""
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office raises the payment."},
                        status=403)
    s = _get_shipment(doc, pk)
    if not s:
        return Response({"detail": "Not found."}, status=404)
    payment = ShipmentPayment.objects.filter(
        shipment=s, kind=kind.upper()).first()
    if not payment:
        return Response({"detail": "Enter the charge first."}, status=400)
    _, msg = ipr_svc.raise_charge_pyr(payment, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
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
    err = ipr_svc.share_with_agent(s, request.user)
    if err:
        return Response({"detail": err}, status=400)
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
            "source_irn": lot.source_ref,
            "location": lot.location, "received_date": lot.received_date,
        })
    total = sum((r["value_on_hand"] for r in rows), Decimal("0"))
    return Response({"lots": rows, "total_value": total})


@api_view(["POST"])
def store_opening_stock(request):
    """Seed the HO store with existing / opening stock (owner 2026-07-14) — one
    valued lot per line, no import needed. Purchasing/Admin only."""
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office receives store stock."},
                        status=403)
    result, msg = ipr_svc.receive_opening_stock(
        request.data.get("lines") or [], request.user,
        received_date=request.data.get("received_date") or None)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(result, status=201)


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
            "source_irn": ln.lot.source_ref,
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


SIN_RECEIVE_ROLES = ("SITE_ADMIN", "SITE_ENGINEER", "HO_PURCHASING", "DIRECTOR",
                     "ADMIN")


@api_view(["POST"])
def sin_receive(request, ref):
    """The destination site receives the store issue → INCURRED at landed
    cost (P1B-f2)."""
    try:
        doc = Document.objects.get(ref=ref, doc_type="SIN")
    except Document.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in SIN_RECEIVE_ROLES:
        return Response({"detail": "The receiving site confirms a store "
                                   "issue."}, status=403)
    msg = ipr_svc.receive_store_issue(doc, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    doc.refresh_from_db()
    return Response(_sin_payload(doc, request))


def _get_mr(request, ref):
    try:
        doc = Document.objects.select_related("current_revision", "site",
                                              "project").get(
            ref=ref, doc_type="MR")
    except Document.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    return doc, None


@api_view(["GET"])
def mr_store_availability(request, ref):
    doc, err = _get_mr(request, ref)
    if err:
        return err
    if request.user.role not in VIEW_ROLES:
        return Response({"detail": "Head Office view."}, status=403)
    avail = ipr_svc.mr_store_availability(doc)
    return Response({"availability": {str(k): v for k, v in avail.items()}})


@api_view(["POST"])
def mr_store_fulfil(request, ref):
    doc, err = _get_mr(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office fulfils from the store."},
                        status=403)
    sin, msg = ipr_svc.fulfil_mr_from_store(
        doc, request.data.get("line_ids") or [], request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_sin_payload(sin, request), status=201)


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
def ipr_correct_charges(request, ref):
    """Purchasing proposes corrected commercial charges (discount / supplier
    freight / misc fee) on an AUTHORISED order — routed to the Director, then
    a Signatory, who applies the new committed total."""
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.user.role not in CREATE_ROLES:
        return Response({"detail": "Head Office proposes the correction."},
                        status=403)
    _, msg = ipr_svc.propose_charge_correction(doc, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_serialize(doc, request))


@api_view(["POST"])
def ipr_correct_charges_decide(request, ref):
    """Director approves / Signatory authorises (applies) / either rejects the
    pending charge correction. Body: {action: approve|reject, reason}."""
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    action = request.data.get("action")
    if action not in ("approve", "reject"):
        return Response({"detail": "Unknown action."}, status=400)
    msg = ipr_svc.decide_charge_correction(
        doc, action, request.user, reason=request.data.get("reason") or "")
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
    if request.user.role not in PAY_ROLES + ("SIGNATORY",):
        return Response({"detail": "Finance view."}, status=403)
    from datetime import date as _date
    from .vouchers import _on_live_milestone
    on_live = set(_on_live_milestone())
    today = _date.today()
    rows = []
    for m in ipr_svc.payments_due():
        total = ipr_svc.ipr_order_total(m.order)
        band = {"PENDING": "COMING", "DUE": "PAYABLE",
                "AUTHORISED": "TT_READY"}[m.status]
        rows.append({
            "ipr_ref": m.order.document.ref, "milestone_id": m.id,
            "label": m.label, "trigger": m.trigger,
            "trigger_label": m.get_trigger_display(),
            "supplier": m.order.supplier.name,
            "supplier_id": m.order.supplier_id,
            "currency": m.order.order_currency,
            "due_amount": m.due_amount(total),
            "expected_mvr": (m.due_amount(total) * m.order.exchange_rate)
            .quantize(Decimal("0.01")),
            "due_date": m.due_date, "credit_days": m.credit_days,
            "fell_due_on": m.fell_due_on, "pay_by": m.pay_by,
            "overdue": bool(m.status == "DUE" and m.pay_by
                            and m.pay_by < today),
            "status": m.status, "band": band,
            "on_voucher": m.id in on_live,
            "stage": ("READY" if m.status == "AUTHORISED"
                      else "AWAITING_VOUCHER" if m.status == "DUE"
                      else "PENDING"),
            "voucher_ref": m.voucher.ref if m.voucher_id else None,
        })
    return Response(rows)


@api_view(["POST"])
def ipr_milestone_pay_by(request, pk):
    """Finance moves a due milestone's pay-by date (reason required)."""
    if request.user.role not in ("FINANCE", "ADMIN"):
        return Response({"detail": "Finance moves a pay-by date."}, status=403)
    from .models import ImportPaymentMilestone
    m = ImportPaymentMilestone.objects.filter(pk=pk).select_related(
        "order__document").first()
    if m is None:
        return Response({"detail": "Not found."}, status=404)
    msg = ipr_svc.move_pay_by(m, request.data.get("pay_by"),
                              request.data.get("reason") or "", request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response({"milestone_id": m.id, "pay_by": m.pay_by})


PMR_REGISTER_ROLES = ("HO_PURCHASING", "DIRECTOR", "SIGNATORY", "FINANCE",
                      "QS", "ADMIN", "PA")
# Ordered PMR pipeline for age/next-step display
PMR_STAGE_ORDER = ["DRAFT", "SUBMITTED", "PM_APPROVED", "HO_REVIEWED",
                   "SIZED_RELEASED", "SOURCING", "ORDERED", "RECEIVED",
                   "CLOSED"]
PMR_NEXT_ACTION = {
    "SUBMITTED": "Site PM to approve",
    "PM_APPROVED": "HO Purchasing to review",
    "HO_REVIEWED": "Director to size & release",
    "SIZED_RELEASED": "HO Purchasing to raise the overseas order",
    "SOURCING": "HO Purchasing — order in progress",
    "ORDERED": "On an overseas order — in the import pipeline",
    "RECEIVED": "Received at store",
}


@api_view(["GET"])
def pmr_register(request):
    """Register of Project Material Requisitions for HO / Purchasing / Director
    to track — especially those sized-and-released but not yet ordered
    (owner 2026-07-14). ?filter=pending_order | open | <status>."""
    if request.user.role not in PMR_REGISTER_ROLES:
        return Response({"detail": "Head Office view."}, status=403)
    from datetime import date

    qs = Document.objects.filter(doc_type="PMR", is_void=False).select_related(
        "project", "site", "current_revision").order_by("-id")
    flt = request.GET.get("filter")
    if flt == "pending_order":
        qs = qs.filter(status__in=("SIZED_RELEASED", "SOURCING"))
    elif flt == "open":
        qs = qs.exclude(status__in=("CLOSED", "CANCELLED", "REJECTED"))
    elif flt:
        qs = qs.filter(status=flt)
    today = date.today()
    rows = []
    for d in qs[:300]:
        rev = d.current_revision
        payload = (rev.payload or {}) if rev else {}
        lines = list(rev.lines.all()) if rev else []
        ipr = d.links_to.filter(link_type="PMR_IPR").select_related(
            "from_document").first()
        rows.append({
            "ref": d.ref, "status": d.status,
            "project": d.project.code if d.project_id else None,
            "site": d.site.code, "discipline": payload.get("discipline", ""),
            "justification": payload.get("justification", ""),
            "lines_count": len(lines),
            "items": [{"description": ln.description, "qty": ln.qty_required,
                       "unit": ln.unit, "spec": ln.spec} for ln in lines[:8]],
            "doc_date": d.doc_date,
            "days_open": (today - d.doc_date).days if d.doc_date else None,
            "pending_order": d.status in ("SIZED_RELEASED", "SOURCING"),
            "next_action": PMR_NEXT_ACTION.get(d.status, ""),
            "ipr_ref": ipr.from_document.ref if ipr else None,
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
        "import_order__supplier", "created_by").prefetch_related(
        "import_order__milestones",
        "import_order__shipments__tracking",
        "import_order__lines__allocations__project").order_by("-id")
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])

    # The list is the desk view of the whole import process (owner
    # 2026-08-27): each order carries where it is going, how much of it is
    # paid and what payment comes next, and where its cargo physically is.
    def payment_summary(order, total):
        ms = list(order.milestones.all())
        if not ms:
            return {"label": "No schedule", "tone": "none",
                    "paid": None, "total": total}
        paid = sum((m.due_amount(total) for m in ms if m.status == "PAID"),
                   Decimal("0"))
        if all(m.status == "PAID" for m in ms):
            return {"label": "Paid in full", "tone": "ok",
                    "paid": paid, "total": total}
        nxt = next((m for m in ms if m.status == "DUE"), None)
        if nxt:
            return {"label": f"{nxt.label} due", "tone": "due",
                    "paid": paid, "total": total}
        nxt = next((m for m in ms if m.status == "AUTHORISED"), None)
        if nxt:
            return {"label": "TT ready", "tone": "due",
                    "paid": paid, "total": total}
        return {"label": ("Advance paid" if paid > 0 else "Nothing due yet"),
                "tone": "part" if paid > 0 else "none",
                "paid": paid, "total": total}

    def shipping_summary(order):
        ships = list(order.shipments.all())
        if not ships:
            return None
        sh = max(ships, key=lambda x: x.seq)
        t = getattr(sh, "tracking", None)
        return {"status": sh.status, "mode": sh.mode,
                "count": len(ships),
                "live": (t.raw_status if t and t.raw_status else None),
                "eta": sh.eta}

    def destinations(order):
        codes = []
        for ln in order.lines.all():
            for a in ln.allocations.all():
                code = a.project.code if a.project_id else "Stock"
                if code not in codes:
                    codes.append(code)
        return codes

    rows = []
    for d in qs[:200]:
        order = d.import_order
        total = ipr_svc.ipr_order_total(order)
        rows.append({
            "ref": d.ref, "status": d.status, "is_void": d.is_void,
            "doc_date": d.doc_date,
            "supplier": order.supplier.name,
            "currency": order.order_currency,
            "order_total": total,
            "mvr_total": ipr_svc.ipr_mvr_total(order),
            "projects": destinations(order),
            "payment": payment_summary(order, total),
            "shipping": shipping_summary(order),
        })

    live = [r for r in rows if not r["is_void"]]
    tiles = {
        "draft": sum(1 for r in live if r["status"] == "DRAFT"),
        "awaiting_award": sum(1 for r in live if r["status"] == "SUBMITTED"),
        "awaiting_authorisation": sum(1 for r in live
                                      if r["status"] == "APPROVED"),
        "active": sum(1 for r in live if r["status"] == "AUTHORISED"),
        "payments_open": sum(1 for r in live
                             if r["payment"]["tone"] == "due"),
        "cargo_moving": sum(1 for r in live if r["shipping"] and
                            r["shipping"]["status"] in
                            ("SHIPPED", "IN_TRANSIT")),
        "cargo_at_port": sum(1 for r in live if r["shipping"] and
                             r["shipping"]["status"] in
                             ("ARRIVED", "UNDER_CLEARING")),
    }
    return Response({"rows": rows, "tiles": tiles})


@api_view(["GET", "PATCH"])
def ipr_detail(request, ref):
    doc, err = _get_ipr(request, ref)
    if err:
        return err
    if request.method == "PATCH":
        if request.user.role not in CREATE_ROLES:
            return Response({"detail": "Head Office edits draft orders."},
                            status=403)
        doc, msg = ipr_svc.update_ipr(doc, request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
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


@api_view(["GET", "POST"])
def clearance_setup(request):
    """The cargo-clearance board (owner 2026-08-26): everything the
    clearance officer needs in one page — what is at the port now, what is
    arriving, what is cleared but not yet in the store, each with its next
    action; plus the agent + share-email setup. Import chain reads,
    Purchasing/Admin edit."""
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError
    from django.utils import timezone as _tz
    from datetime import date as _date, timedelta as _td
    from .models import (AuditLog, CompanyParameter, ImportShipment,
                         Supplier)

    if request.user.role not in VIEW_ROLES:
        return Response({"detail": "Head Office view."}, status=403)
    if request.method == "POST":
        if request.user.role not in CREATE_ROLES:
            return Response({"detail": "Purchasing manages clearance "
                                       "setup."}, status=403)
        raw = str(request.data.get("share_cc") or "").replace(";", ",")
        addrs = [a.strip() for a in raw.split(",") if a.strip()]
        for a in addrs:
            try:
                validate_email(a)
            except ValidationError:
                return Response({"detail": f"'{a}' is not a valid email "
                                           "address."}, status=400)
        CompanyParameter.objects.update_or_create(
            key=ipr_svc.SHARE_CC_PARAM,
            defaults={"value": ", ".join(addrs),
                      "description": "CC on clearing-agent document shares"})
        audit("company", 0, "CLEARANCE_CC_SET", actor=request.user,
              detail={"cc": addrs})

    agent = Supplier.objects.filter(is_clearing_agent=True,
                                    is_active=True).first()
    candidates = Supplier.objects.filter(
        category="CLEARING_AGENT", is_active=True).order_by("name")

    live = list(
        ImportShipment.objects
        .filter(order__document__status="AUTHORISED",
                order__document__is_void=False)
        .exclude(status="CLEARED")
        .select_related("order__document", "order__supplier")
        .prefetch_related("documents", "payments__pyr"))
    cleared = list(
        ImportShipment.objects
        .filter(status="CLEARED", order__document__status="AUTHORISED",
                order__document__is_void=False)
        .select_related("order__document", "order__supplier")
        .prefetch_related("receipts__document"))
    # When each shipment reached ARRIVED, from the append-only audit trail.
    doc_ids = {s.order.document_id for s in live}
    arrived_on = {}
    for row in AuditLog.objects.filter(
            entity="document", entity_id__in=doc_ids,
            event="SHIPMENT_STATUS", to_state="ARRIVED").order_by("at"):
        seq = (row.detail or {}).get("shipment")
        arrived_on[(row.entity_id, seq)] = row.at.date()

    today = _date.today()

    def charges_tally(s):
        return {
            "paid": sum(1 for p in s.payments.all()
                        if p.pyr_id and p.pyr.status == "PAID"),
            "raised": sum(1 for p in s.payments.all()
                          if p.pyr_id and p.pyr.status != "PAID"),
            "entered": sum(1 for p in s.payments.all()
                           if p.amount and not p.pyr_id),
        }

    def next_action(s, missing, ch, at_port):
        if not agent:
            return "Set the clearing agent first"
        if missing:
            return ("Upload " + ", ".join(missing).lower()
                    + (" to start clearing" if at_port
                       else " before arrival"))
        if not s.shared_with_agent_at:
            return ("Share the documents with the agent"
                    + ("" if at_port else " ahead of arrival"))
        if s.status == "ARRIVED":
            return "Move to Under clearing"
        if s.status == "UNDER_CLEARING":
            if ch["entered"]:
                return f"Raise the PYR for {ch['entered']} charge(s)"
            if ch["raised"]:
                return (f"{ch['raised']} charge PYR(s) with Finance — "
                        "chase payment")
            if not ch["paid"]:
                return "Enter the clearing charges when invoiced"
            return "With the agent — mark Cleared when the cargo is out"
        return "Documents ready — waiting on the vessel"

    def row(s, at_port):
        missing = [dict(ShipmentDocument.Type.choices)[d]
                   for d in ipr_svc.missing_clearing_docs(s)]
        ch = charges_tally(s)
        arr = arrived_on.get((s.order.document_id, s.seq))
        return {
            "ipr_ref": s.order.document.ref, "shipment_seq": s.seq,
            "supplier": s.order.supplier.name, "mode": s.mode,
            "status": s.status, "status_display": s.get_status_display(),
            "eta": s.eta, "arrived_on": arr,
            "days_at_port": (today - arr).days if at_port and arr else None,
            "shared_at": s.shared_with_agent_at,
            "documents": s.documents.count(), "missing_docs": missing,
            "charges": ch,
            "next_action": next_action(s, missing, ch, at_port),
        }

    stage = {"UNDER_CLEARING": 0, "ARRIVED": 1, "IN_TRANSIT": 2,
             "SHIPPED": 3, "BOOKED": 4}
    far = _date(9999, 12, 31)
    live.sort(key=lambda s: (stage.get(s.status, 9), s.eta or far))
    at_port_rows = [row(s, True) for s in live
                    if s.status in ("ARRIVED", "UNDER_CLEARING")]
    incoming_rows = [row(s, False) for s in live
                     if s.status in ("BOOKED", "SHIPPED", "IN_TRANSIT")]
    to_receive = []
    for s in cleared:
        irns = [r.document for r in s.receipts.all()]
        if any(d.status == "VERIFIED" for d in irns):
            continue                    # in the store — off the board
        open_irn = irns[-1] if irns else None
        to_receive.append({
            "ipr_ref": s.order.document.ref, "shipment_seq": s.seq,
            "supplier": s.order.supplier.name, "mode": s.mode,
            "irn_ref": open_irn.ref if open_irn else None,
            "irn_status": open_irn.status if open_irn else None,
            "next_action": (f"Finish the count on {open_irn.ref}"
                            if open_irn
                            else "Count into the HO store (IRN)"),
        })
    week = today + _td(days=7)
    return Response({
        "agent": ({
            "id": agent.id, "name": agent.name,
            "contact_person": agent.contact_person, "phone": agent.phone,
            "email": agent.email, "address": agent.address,
            "notes": agent.notes,
        } if agent else None),
        "candidates": [{"id": s.id, "name": s.name,
                        "is_agent": bool(agent and s.id == agent.id)}
                       for s in candidates],
        "share_cc": ", ".join(ipr_svc.share_cc_list()),
        "can_edit": request.user.role in CREATE_ROLES,
        "tiles": {
            "at_sea": len(incoming_rows),
            "arriving_week": sum(1 for r in incoming_rows
                                 if r["eta"] and r["eta"] <= week),
            "at_port": len(at_port_rows),
            "to_receive": len(to_receive),
        },
        "at_port": at_port_rows,
        "incoming": incoming_rows,
        "to_receive": to_receive,
    })
