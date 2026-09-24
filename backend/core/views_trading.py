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
        f'inline; filename="{q.ref.replace("/", "-")}.pdf"')
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
