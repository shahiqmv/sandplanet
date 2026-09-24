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
    return Response({
        "role": request.user.role,
        "can_write": can_write(request.user),
        "customers": Customer.objects.filter(is_active=True).count(),
        "suppliers": Supplier.objects.filter(is_trading=True,
                                             is_active=True).count(),
    })
