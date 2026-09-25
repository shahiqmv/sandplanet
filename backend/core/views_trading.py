"""The trading app's API (TRADING_BUILD_BRIEF.md) — /api/trading/…

Phase 1 (foundations): who may enter, the customer directory, and the
trading supplier directory. Every endpoint here is gated on the trading
roles plus Finance / Signatory / Admin; a site role gets 403, and nothing
under /api/trading ever takes a site.
"""
from django.db.models import Q
from rest_framework import serializers, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .audit import audit
from .models import Customer, Supplier, User

# Who may change trading masters and documents. Finance and the Signatory
# read the trading world (they pay its suppliers and receipt its customers)
# but never edit a customer or an order.
TRADING_WRITERS = ("SALES", "SALES_MANAGER", "ADMIN")


class IsTradingReader(BasePermission):
    """Read: the trading roles + Finance/Signatory/Admin. Write: Sales,
    Sales Manager, Admin."""

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated or u.role not in User.TRADING_READERS:
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return u.role in TRADING_WRITERS


def can_write(user):
    return user.is_authenticated and user.role in TRADING_WRITERS


class IsTradingReaderAnyMethod(BasePermission):
    """Entry for everyone who may read trading; the service decides who may
    act (Finance records receipts, which Sales never do)."""

    def has_permission(self, request, view):
        u = request.user
        return u.is_authenticated and u.role in User.TRADING_READERS


# ---- customers -----------------------------------------------------------

class CustomerSerializer(serializers.ModelSerializer):
    # Declared so a form-encoded POST that omits them keeps the model's
    # defaults (DRF reads an absent form boolean as False).
    is_active = serializers.BooleanField(default=True)
    gst_exempt = serializers.BooleanField(default=False)

    class Meta:
        model = Customer
        fields = ["id", "name", "tin", "business_reg_no", "billing_address",
                  "island", "vessels", "contact_person", "phone", "email",
                  "default_currency", "credit_days", "gst_exempt", "notes",
                  "is_active", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_name(self, v):
        v = (v or "").strip()
        if not v:
            raise serializers.ValidationError("Enter the customer's name.")
        qs = Customer.objects.filter(name__iexact=v)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A customer with this name is already on file.")
        return v

    def validate_default_currency(self, v):
        v = (v or "MVR").upper()
        if v not in ("MVR", "USD"):
            raise serializers.ValidationError("Currency must be MVR or USD.")
        return v


class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [IsTradingReader]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = Customer.objects.order_by("name")
        search = (self.request.GET.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(name__icontains=search)
                           | Q(island__icontains=search)
                           | Q(vessels__icontains=search)
                           | Q(contact_person__icontains=search))
        if self.request.GET.get("active") != "all":
            qs = qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        c = serializer.save(created_by=self.request.user)
        audit("customer", c.id, "CUSTOMER_CREATED", actor=self.request.user,
              detail={"name": c.name})

    def perform_update(self, serializer):
        c = serializer.save()
        audit("customer", c.id, "CUSTOMER_UPDATED", actor=self.request.user,
              detail={"fields": sorted(self.request.data.keys())})


# ---- trading suppliers ---------------------------------------------------

class TradingSupplierSerializer(serializers.ModelSerializer):
    """The supplier as Sales see it. Bank details stay with Finance on the
    purchasing side; the trading app never shows or edits them."""
    is_active = serializers.BooleanField(default=True)

    class Meta:
        model = Supplier
        fields = ["id", "name", "category", "country", "default_currency",
                  "default_incoterm", "contact_person", "phone", "email",
                  "address", "notes", "is_active"]

    def validate_name(self, v):
        v = (v or "").strip()
        if not v:
            raise serializers.ValidationError("Enter the supplier's name.")
        return v

    def validate_category(self, v):
        if v not in (Supplier.Category.LOCAL, Supplier.Category.INTERNATIONAL):
            raise serializers.ValidationError(
                "A trading supplier is a local or an international supplier.")
        return v


class TradingSupplierViewSet(viewsets.ModelViewSet):
    """Suppliers flagged for trading. Creating one here flags it; a supplier
    already on the purchasing directory can be brought in with the `adopt`
    action rather than duplicated."""
    serializer_class = TradingSupplierSerializer
    permission_classes = [IsTradingReader]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = Supplier.objects.filter(is_trading=True).order_by("name")
        search = (self.request.GET.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(name__icontains=search)
                           | Q(country__icontains=search))
        if self.request.GET.get("active") != "all":
            qs = qs.filter(is_active=True)
        return qs

    def create(self, request, *args, **kwargs):
        name = (request.data.get("name") or "").strip()
        existing = Supplier.objects.filter(name__iexact=name).first()
        if existing is not None:
            if existing.is_trading:
                return Response({"detail": "This supplier is already on the "
                                           "trading directory."}, status=400)
            # Same company, already known to Purchasing — one record.
            existing.is_trading = True
            existing.save(update_fields=["is_trading", "updated_at"])
            audit("supplier", existing.id, "SUPPLIER_TRADING_ADOPTED",
                  actor=request.user, detail={"name": existing.name})
            return Response(self.get_serializer(existing).data, status=201)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        s = serializer.save(is_trading=True)
        audit("supplier", s.id, "SUPPLIER_CREATED", actor=self.request.user,
              detail={"name": s.name, "trading": True})

    def perform_update(self, serializer):
        s = serializer.save()
        audit("supplier", s.id, "SUPPLIER_UPDATED", actor=self.request.user,
              detail={"fields": sorted(self.request.data.keys()),
                      "trading": True})


# ---- home ------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsTradingReader])
def home(request):
    """What the trading dashboard opens on. Phase 1 carries the directory
    counts and the caller's rights; the chase list arrives with phase 2."""
    from . import trading as svc
    return Response({
        "role": request.user.role,
        "can_write": can_write(request.user),
        "customers": Customer.objects.filter(is_active=True).count(),
        "suppliers": Supplier.objects.filter(is_trading=True,
                                             is_active=True).count(),
        **svc.home(request.user),
    })


# ---- orders (phase 2: the sales front) --------------------------------------

from django.http import HttpResponse  # noqa: E402
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser  # noqa: E402
from rest_framework.decorators import parser_classes  # noqa: E402

from . import trading  # noqa: E402
from .models import TradingOrder, TradingQuotation  # noqa: E402


def _order(pk):
    return (TradingOrder.objects.select_related("customer", "owner", "won_by")
            .filter(id=pk).first())


def _manage_or_403(request, order):
    if not can_write(request.user) or not trading.can_manage(request.user, order):
        return Response({"detail": "Only the inquiry's owner or the Sales "
                                   "Manager can change it."}, status=403)
    return None


@api_view(["GET", "POST"])
@permission_classes([IsTradingReader])
def orders(request):
    """The inquiry register. Everyone in trading sees every inquiry
    (blueprint §6); `mine=1` narrows to the caller's own."""
    if request.method == "POST":
        if not can_write(request.user):
            return Response({"detail": "Finance reads the register; Sales raise "
                                       "inquiries."}, status=403)
        order, errors = trading.create_order(request.data, request.user)
        if errors:
            return Response(errors, status=400)
        return Response(trading.order_dict(order, request.user), status=201)
    qs = TradingOrder.objects.select_related("customer", "owner")
    stage = request.GET.get("stage")
    if stage == "open":
        qs = qs.exclude(stage__in=("WON", "LOST"))
    elif stage:
        qs = qs.filter(stage=stage)
    if request.GET.get("mine") == "1":
        qs = qs.filter(owner=request.user)
    search = (request.GET.get("search") or "").strip()
    if search:
        qs = qs.filter(Q(ref__icontains=search) | Q(title__icontains=search)
                       | Q(customer__name__icontains=search)
                       | Q(quote_ref__icontains=search)
                       | Q(so_ref__icontains=search)
                       | Q(po_number__icontains=search))
    return Response([trading.order_summary(o) for o in qs[:300]])


@api_view(["GET", "PATCH"])
@permission_classes([IsTradingReader])
def order_detail(request, pk):
    order = _order(pk)
    if order is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "PATCH":
        err = _manage_or_403(request, order)
        if err:
            return err
        errors = trading.update_order(order, request.data, request.user)
        if errors:
            return Response(errors, status=400)
    return Response(trading.order_dict(order, request.user))


@api_view(["PUT"])
@permission_classes([IsTradingReader])
def order_lines(request, pk):
    order = _order(pk)
    if order is None:
        return Response({"detail": "Not found."}, status=404)
    err = _manage_or_403(request, order)
    if err:
        return err
    rows = request.data.get("lines") if isinstance(request.data, dict) else request.data
    if not isinstance(rows, list):
        return Response({"detail": "Send the lines as a list."}, status=400)
    msg = trading.write_lines(order, rows, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(trading.order_dict(_order(pk), request.user))


@api_view(["POST"])
@permission_classes([IsTradingReader])
def order_stage(request, pk):
    order = _order(pk)
    if order is None:
        return Response({"detail": "Not found."}, status=404)
    err = _manage_or_403(request, order)
    if err:
        return err
    msg = trading.set_stage(order, request.data.get("stage"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(trading.order_dict(order, request.user))


@api_view(["POST"])
@permission_classes([IsTradingReader])
def order_quotations(request, pk):
    """Issue the next quotation revision (the manager's own is authorised
    in the same step)."""
    order = _order(pk)
    if order is None:
        return Response({"detail": "Not found."}, status=404)
    err = _manage_or_403(request, order)
    if err:
        return err
    q, msg = trading.issue_quotation(order, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(trading.order_dict(_order(pk), request.user), status=201)


def _quotation(pk, qid):
    return (TradingQuotation.objects.select_related("order__customer", "order__owner",
                                                    "created_by", "authorised_by")
            .filter(order_id=pk, id=qid).first())


@api_view(["POST"])
@permission_classes([IsTradingReader])
def quotation_authorise(request, pk, qid):
    q = _quotation(pk, qid)
    if q is None:
        return Response({"detail": "Not found."}, status=404)
    msg = trading.authorise_quotation(q, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(trading.order_dict(_order(pk), request.user))


@api_view(["POST"])
@permission_classes([IsTradingReader])
def quotation_withdraw(request, pk, qid):
    q = _quotation(pk, qid)
    if q is None:
        return Response({"detail": "Not found."}, status=404)
    err = _manage_or_403(request, q.order)
    if err:
        return err
    msg = trading.withdraw_quotation(q, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(trading.order_dict(_order(pk), request.user))


@api_view(["GET"])
@permission_classes([IsTradingReader])
def quotation_pdf(request, pk, qid):
    """The authorised PDF as filed; before authorisation, a DRAFT render of
    the frozen revision so Sales can read what they are sending up."""
    q = _quotation(pk, qid)
    if q is None:
        return Response({"detail": "Not found."}, status=404)
    if q.status == "AUTHORISED" and q.pdf:
        pdf = q.pdf.read()
    else:
        try:
            pdf = trading.quotation_pdf_bytes(q, draft=q.status != "AUTHORISED")
        except Exception as e:                       # pragma: no cover - env dep
            return Response({"detail": f"PDF engine unavailable: {e}"},
                            status=500)
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = (
        f'inline; filename="{q.ref}.pdf"')
    return resp


@api_view(["POST"])
@permission_classes([IsTradingReader])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def order_won(request, pk):
    order = _order(pk)
    if order is None:
        return Response({"detail": "Not found."}, status=404)
    err = _manage_or_403(request, order)
    if err:
        return err
    msg = trading.win_order(order, request.data, request.user,
                            po_file=request.FILES.get("po_file"))
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(trading.order_dict(_order(pk), request.user))


@api_view(["POST"])
@permission_classes([IsTradingReader])
def order_lost(request, pk):
    order = _order(pk)
    if order is None:
        return Response({"detail": "Not found."}, status=404)
    err = _manage_or_403(request, order)
    if err:
        return err
    msg = trading.lose_order(order, request.data.get("reason"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(trading.order_dict(order, request.user))


@api_view(["GET"])
@permission_classes([IsTradingReader])
def order_activity(request, pk):
    order = _order(pk)
    if order is None:
        return Response({"detail": "Not found."}, status=404)
    return Response(trading.activity(order))


@api_view(["GET"])
@permission_classes([IsTradingReader])
def sales_users(request):
    """Who an inquiry can be owned by."""
    return Response([{"id": u.id, "full_name": u.full_name, "role": u.role}
                     for u in User.objects.filter(role__in=User.TRADING_ROLES,
                                                  is_active=True)
                     .order_by("full_name")])


# ---- phase 3: the supply leg --------------------------------------------------

@api_view(["GET"])
@permission_classes([IsTradingReader])
def order_supply(request, pk):
    order = _order(pk)
    if order is None:
        return Response({"detail": "Not found."}, status=404)
    return Response(trading.supply(order))


@api_view(["POST"])
@permission_classes([IsTradingReader])
def order_import_orders(request, pk):
    """Raise draft import orders (one per supplier) for the chosen lines."""
    order = _order(pk)
    if order is None:
        return Response({"detail": "Not found."}, status=404)
    err = _manage_or_403(request, order)
    if err:
        return err
    docs, msg = trading.raise_import_orders(order, request.data.get("line_ids"),
                                            request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response({"raised": [d.ref for d in docs],
                     **trading.supply(_order(pk))}, status=201)


# ---- phase 4: deliveries, invoices, receipts, receivables ---------------------

from datetime import date as _date  # noqa: E402

from .models import (CompanyBankAccount, Customer as _Customer,  # noqa: E402
                     TradingDelivery, TradingInvoice, TradingReceipt)


def _dn(pk, did):
    return TradingDelivery.objects.select_related("order__customer", "despatched_by") \
        .filter(order_id=pk, id=did).first()


def _inv(pk, iid):
    return TradingInvoice.objects.select_related("order__customer", "issued_by") \
        .filter(order_id=pk, id=iid).first()


def _pdf_response(pdf, name):
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{name}"'
    return resp


@api_view(["GET", "POST"])
@permission_classes([IsTradingReader])
def order_deliveries(request, pk):
    order = _order(pk)
    if order is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "POST":
        err = _manage_or_403(request, order)
        if err:
            return err
        dn, errors = trading.create_delivery(order, request.data, request.user)
        if errors:
            return Response(errors, status=400)
        return Response(trading.delivery_dict(dn), status=201)
    return Response({"deliverable": trading.deliverable(order),
                     "deliveries": [trading.delivery_dict(d) for d in
                                    order.deliveries.select_related("despatched_by", "invoice")],
                     "money": trading.money(order)})


@api_view(["PATCH", "POST"])
@permission_classes([IsTradingReader])
def delivery_detail(request, pk, did):
    dn = _dn(pk, did)
    if dn is None:
        return Response({"detail": "Not found."}, status=404)
    err = _manage_or_403(request, dn.order)
    if err:
        return err
    if request.method == "PATCH":
        errors = trading.update_delivery(dn, request.data, request.user)
        if errors:
            return Response(errors, status=400)
    else:
        action = request.data.get("action")
        if action == "despatch":
            msg = trading.despatch_delivery(dn, request.user)
        elif action == "cancel":
            msg = trading.cancel_delivery(dn, request.user)
        else:
            msg = "Unknown action."
        if msg:
            return Response({"detail": msg}, status=400)
    return Response(trading.delivery_dict(_dn(pk, did)))


@api_view(["POST"])
@permission_classes([IsTradingReader])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def delivery_receive(request, pk, did):
    dn = _dn(pk, did)
    if dn is None:
        return Response({"detail": "Not found."}, status=404)
    err = _manage_or_403(request, dn.order)
    if err:
        return err
    msg = trading.receive_delivery(dn, request.FILES.get("signed_copy"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(trading.delivery_dict(_dn(pk, did)))


@api_view(["GET"])
@permission_classes([IsTradingReader])
def delivery_pdf(request, pk, did):
    dn = _dn(pk, did)
    if dn is None:
        return Response({"detail": "Not found."}, status=404)
    if dn.pdf:
        return _pdf_response(dn.pdf.read(), f"{dn.ref}.pdf")
    from .views_commercial import pdf_bytes
    try:
        pdf = pdf_bytes("pdf/trading_delivery_note.html", trading.delivery_context(dn))
    except Exception as e:                       # pragma: no cover - env dep
        return Response({"detail": f"PDF engine unavailable: {e}"}, status=500)
    return _pdf_response(pdf, f"{dn.ref}.pdf")


@api_view(["GET", "POST"])
@permission_classes([IsTradingReader])
def order_invoices(request, pk):
    order = _order(pk)
    if order is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "POST":
        err = _manage_or_403(request, order)
        if err:
            return err
        inv, msg = trading.create_invoice(order, request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(trading.invoice_dict(inv), status=201)
    return Response({
        "invoices": [trading.invoice_dict(i) for i in
                     order.invoices.select_related("issued_by")],
        "invoiceable": [trading.delivery_dict(d) for d in
                        trading.invoiceable_deliveries(order)],
        "freight_sell": trading._s(order.freight_sell),
        "freight_billed": trading.freight_billed(order),
        "money": trading.money(order),
    })


@api_view(["POST"])
@permission_classes([IsTradingReader])
def invoice_action(request, pk, iid):
    inv = _inv(pk, iid)
    if inv is None:
        return Response({"detail": "Not found."}, status=404)
    err = _manage_or_403(request, inv.order)
    if err:
        return err
    action = request.data.get("action")
    if action == "issue":
        msg = trading.issue_invoice(inv, request.user)
    elif action == "void":
        msg = trading.void_invoice(inv, request.data.get("reason"), request.user)
    elif action == "credit":
        cn, msg = trading.create_credit_note(inv, request.data, request.user)
    else:
        msg = "Unknown action."
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(trading.invoice_dict(_inv(pk, iid)))


@api_view(["GET"])
@permission_classes([IsTradingReader])
def invoice_pdf(request, pk, iid):
    inv = _inv(pk, iid)
    if inv is None:
        return Response({"detail": "Not found."}, status=404)
    if inv.pdf and inv.status != "VOID":
        return _pdf_response(inv.pdf.read(), f"{inv.ref}.pdf")
    try:
        pdf = trading.invoice_pdf_bytes(inv)
    except Exception as e:                       # pragma: no cover - env dep
        return Response({"detail": f"PDF engine unavailable: {e}"}, status=500)
    return _pdf_response(pdf, f"{inv.ref}.pdf")


@api_view(["GET", "POST"])
@permission_classes([IsTradingReaderAnyMethod])
def receipts(request):
    if request.method == "POST":
        rc, msg = trading.record_receipt(request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(trading.receipt_dict(rc), status=201)
    qs = TradingReceipt.objects.select_related("customer", "bank_account", "recorded_by")
    if request.GET.get("customer"):
        qs = qs.filter(customer_id=request.GET["customer"])
    return Response([trading.receipt_dict(r) for r in qs[:300]])


@api_view(["DELETE", "GET"])
@permission_classes([IsTradingReaderAnyMethod])
def receipt_detail(request, rid):
    rc = TradingReceipt.objects.filter(id=rid).first()
    if rc is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "DELETE":
        msg = trading.delete_receipt(rc, request.user)
        if msg:
            return Response({"detail": msg}, status=403)
        return Response({"detail": "Receipt deleted."})
    from .views_commercial import pdf_bytes
    try:
        pdf = pdf_bytes("pdf/official_receipt.html", trading.receipt_context(rc))
    except Exception as e:                       # pragma: no cover - env dep
        return Response({"detail": f"PDF engine unavailable: {e}"}, status=500)
    return _pdf_response(pdf, f"{rc.receipt_no}.pdf")


@api_view(["GET"])
@permission_classes([IsTradingReader])
def receipt_allocate(request):
    """Oldest-first suggestion for a customer and an amount."""
    customer = _Customer.objects.filter(id=request.GET.get("customer")).first()
    if customer is None:
        return Response({"detail": "Pick the customer."}, status=400)
    amount = trading._dec(request.GET.get("amount"), trading.ZERO)
    rows, left = trading.auto_allocate(customer, amount)
    return Response({"allocations": rows, "unallocated": left,
                     "open_invoices": [{"id": i.id, "ref": i.ref, "order": i.order.ref,
                                        "so_ref": i.order.so_ref, "currency": i.currency,
                                        "total": trading._s(i.total),
                                        "outstanding": trading._s(trading.invoice_outstanding(i)),
                                        "due_date": i.due_date}
                                       for i in trading.open_invoices(customer)],
                     "bank_accounts": [{"id": b.id, "label": b.label, "currency": b.currency}
                                       for b in CompanyBankAccount.objects.filter(is_active=True)
                                       .order_by("label")],
                     "can_receipt": trading.can_receipt(request.user)})


@api_view(["GET"])
@permission_classes([IsTradingReader])
def receivables(request):
    return Response({**trading.aging(), "can_receipt": trading.can_receipt(request.user)})


def _parse_date(v):
    try:
        return _date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


@api_view(["GET"])
@permission_classes([IsTradingReader])
def customer_statement(request, cid):
    customer = _Customer.objects.filter(id=cid).first()
    if customer is None:
        return Response({"detail": "Not found."}, status=404)
    dfrom, dto = _parse_date(request.GET.get("from")), _parse_date(request.GET.get("to"))
    if request.GET.get("pdf") == "1":
        from .views_commercial import pdf_bytes
        try:
            pdf = pdf_bytes("pdf/trading_statement.html",
                            trading.statement_context(customer, dfrom, dto))
        except Exception as e:                   # pragma: no cover - env dep
            return Response({"detail": f"PDF engine unavailable: {e}"}, status=500)
        return _pdf_response(pdf, f"SOA-{customer.name[:20]}.pdf")
    return Response(trading.statement(customer, dfrom, dto))



# ---- standard quotation terms ---------------------------------------------------

@api_view(["GET", "PUT"])
@permission_classes([IsTradingReaderAnyMethod])
def standard_terms(request):
    if request.method == "PUT":
        msg = trading.set_standard_terms(request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=403)
    return Response({**trading.standard_terms(),
                     "can_edit": trading.can_authorise(request.user)})
