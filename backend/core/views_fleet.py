"""The rental fleet API — /api/v1/fleet/… (MARINE_BUILD_BRIEF.md §4).
Behind the `rental` feature switch: on an instance without it every route
answers 404, so nothing of the fleet shows on a company that has none."""
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from . import fleet
from .models import Vehicle, VehicleDocument


class IsFleetReader(BasePermission):
    def has_permission(self, request, view):
        return fleet.can_read(request.user)


def _off():
    return Response({"detail": "Not found."}, status=404)


def _vehicle(pk):
    return Vehicle.objects.filter(id=pk).prefetch_related("documents").first()


@api_view(["GET"])
@permission_classes([IsFleetReader])
def summary(request):
    if not fleet.enabled():
        return _off()
    return Response({**fleet.summary(), "can_write": fleet.can_write(request.user),
                     "can_set_rates": fleet.can_set_rates(request.user)})


@api_view(["GET", "POST"])
@permission_classes([IsFleetReader])
def vehicles(request):
    if not fleet.enabled():
        return _off()
    if request.method == "POST":
        if not fleet.can_write(request.user):
            return Response({"detail": "The Rental team keeps the fleet register."}, status=403)
        v, errors = fleet.create_vehicle(request.data, request.user)
        if errors:
            return Response(errors, status=400)
        return Response(fleet.vehicle_dict(v, request.user, full=True), status=201)
    qs = Vehicle.objects.prefetch_related("documents").select_related("default_operator")
    if request.GET.get("active") != "all":
        qs = qs.filter(is_active=True).exclude(status="DISPOSED")
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    qs = fleet.search(qs, request.GET.get("search"))
    return Response([fleet.vehicle_dict(v) for v in qs])


@api_view(["GET", "PATCH"])
@permission_classes([IsFleetReader])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def vehicle_detail(request, pk):
    if not fleet.enabled():
        return _off()
    v = _vehicle(pk)
    if v is None:
        return _off()
    if request.method == "PATCH":
        if not fleet.can_write(request.user):
            return Response({"detail": "The Rental team keeps the fleet register."}, status=403)
        if "photo" in request.FILES:
            v.photo = request.FILES["photo"]
        errors = fleet.update_vehicle(v, request.data, request.user)
        if errors:
            return Response(errors, status=400)
        v = _vehicle(pk)
    return Response(fleet.vehicle_dict(v, request.user, full=True))


@api_view(["POST"])
@permission_classes([IsFleetReader])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def vehicle_documents(request, pk):
    if not fleet.enabled():
        return _off()
    v = _vehicle(pk)
    if v is None:
        return _off()
    if not fleet.can_write(request.user):
        return Response({"detail": "The Rental team keeps the fleet register."}, status=403)
    d, msg = fleet.add_document(v, request.data, request.FILES.get("file"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(fleet.vehicle_dict(_vehicle(pk), request.user, full=True), status=201)


@api_view(["DELETE"])
@permission_classes([IsFleetReader])
def vehicle_document(request, pk, did):
    if not fleet.enabled():
        return _off()
    d = VehicleDocument.objects.filter(vehicle_id=pk, id=did).select_related("vehicle").first()
    if d is None:
        return _off()
    if not fleet.can_write(request.user):
        return Response({"detail": "The Rental team keeps the fleet register."}, status=403)
    fleet.remove_document(d, request.user)
    return Response(fleet.vehicle_dict(_vehicle(pk), request.user, full=True))


@api_view(["GET"])
@permission_classes([IsFleetReader])
def operators(request):
    """Employees who can be a vehicle's default operator."""
    if not fleet.enabled():
        return _off()
    from .models import Employee
    q = (request.GET.get("search") or "").strip()
    qs = Employee.objects.filter(is_active=True)
    if q:
        qs = qs.filter(full_name__icontains=q)
    return Response([{"id": e.id, "emp_no": e.emp_no, "full_name": e.full_name,
                      "job_title": e.job_title}
                     for e in qs.order_by("full_name")[:50]])


# ---- phase 4: customers, agreements and the daily register -----------------------

from datetime import date as _date  # noqa: E402

from django.http import HttpResponse  # noqa: E402

from . import rental  # noqa: E402
from .models import Customer, RentalAgreement  # noqa: E402
from .views_trading import CustomerSerializer  # noqa: E402


def _pdf(pdf, name):
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{name}"'
    return resp


def _parse(v):
    try:
        return _date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


@api_view(["GET", "POST"])
@permission_classes([IsFleetReader])
def customers(request):
    """The fleet's customer directory — the same Customer rows the trading
    app uses, reachable by the Rental roles."""
    if not fleet.enabled():
        return _off()
    if request.method == "POST":
        if not fleet.can_write(request.user):
            return Response({"detail": "The Rental team keeps the customers."}, status=403)
        ser = CustomerSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        c = ser.save(created_by=request.user)
        return Response(CustomerSerializer(c).data, status=201)
    qs = Customer.objects.order_by("name")
    if request.GET.get("active") != "all":
        qs = qs.filter(is_active=True)
    q = (request.GET.get("search") or "").strip()
    if q:
        qs = qs.filter(name__icontains=q)
    return Response(CustomerSerializer(qs, many=True).data)


@api_view(["PATCH"])
@permission_classes([IsFleetReader])
def customer_detail(request, pk):
    if not fleet.enabled():
        return _off()
    c = Customer.objects.filter(id=pk).first()
    if c is None:
        return _off()
    if not fleet.can_write(request.user):
        return Response({"detail": "The Rental team keeps the customers."}, status=403)
    ser = CustomerSerializer(c, data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    ser.save()
    return Response(ser.data)


def _agreement(pk):
    return RentalAgreement.objects.select_related("customer", "activated_by").filter(id=pk).first()


@api_view(["GET", "POST"])
@permission_classes([IsFleetReader])
def agreements(request):
    if not fleet.enabled():
        return _off()
    if request.method == "POST":
        if not fleet.can_write(request.user):
            return Response({"detail": "The Rental team raises agreements."}, status=403)
        a, errors = rental.create_agreement(request.data, request.user)
        if errors:
            return Response(errors, status=400)
        return Response(rental.agreement_dict(a, request.user, full=True), status=201)
    qs = RentalAgreement.objects.select_related("customer")
    st = request.GET.get("status")
    if st == "open":
        qs = qs.filter(status__in=("DRAFT", "ACTIVE"))
    elif st:
        qs = qs.filter(status=st)
    q = (request.GET.get("search") or "").strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(ref__icontains=q) | Q(customer__name__icontains=q)
                       | Q(title__icontains=q) | Q(site_location__icontains=q))
    return Response([rental.agreement_dict(a) for a in qs[:300]])


@api_view(["GET", "PATCH"])
@permission_classes([IsFleetReader])
def agreement_detail(request, pk):
    if not fleet.enabled():
        return _off()
    a = _agreement(pk)
    if a is None:
        return _off()
    if request.method == "PATCH":
        if not fleet.can_write(request.user):
            return Response({"detail": "The Rental team keeps agreements."}, status=403)
        errors = rental.update_agreement(a, request.data, request.user)
        if errors:
            return Response(errors, status=400)
    return Response(rental.agreement_dict(_agreement(pk), request.user, full=True))


@api_view(["PUT"])
@permission_classes([IsFleetReader])
def agreement_vehicles(request, pk):
    if not fleet.enabled():
        return _off()
    a = _agreement(pk)
    if a is None:
        return _off()
    if not fleet.can_write(request.user):
        return Response({"detail": "The Rental team keeps agreements."}, status=403)
    msg = rental.set_vehicles(a, request.data.get("vehicles"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(rental.agreement_dict(_agreement(pk), request.user, full=True))


@api_view(["POST"])
@permission_classes([IsFleetReader])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def agreement_action(request, pk):
    if not fleet.enabled():
        return _off()
    a = _agreement(pk)
    if a is None:
        return _off()
    if not fleet.can_write(request.user):
        return Response({"detail": "The Rental team keeps agreements."}, status=403)
    action = request.data.get("action")
    if action == "activate":
        msg = rental.activate(a, request.user)
    elif action in ("complete", "terminate"):
        msg = rental.close(a, "COMPLETED" if action == "complete" else "TERMINATED",
                           request.data.get("reason"), request.user)
    elif action == "signed":
        msg = rental.attach_signed(a, request.FILES.get("file"), request.user)
    else:
        msg = "Unknown action."
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(rental.agreement_dict(_agreement(pk), request.user, full=True))


@api_view(["GET"])
@permission_classes([IsFleetReader])
def agreement_pdf(request, pk):
    if not fleet.enabled():
        return _off()
    a = _agreement(pk)
    if a is None:
        return _off()
    if a.pdf and a.status != "DRAFT":
        return _pdf(a.pdf.read(), f"{a.ref}.pdf")
    try:
        pdf = rental.agreement_pdf_bytes(a, draft=a.status == "DRAFT")
    except Exception as e:                            # pragma: no cover - env dep
        return Response({"detail": f"PDF engine unavailable: {e}"}, status=500)
    return _pdf(pdf, f"{a.ref}.pdf")


@api_view(["GET", "PUT"])
@permission_classes([IsFleetReader])
def agreement_register(request, pk):
    if not fleet.enabled():
        return _off()
    a = _agreement(pk)
    if a is None:
        return _off()
    if request.method == "PUT":
        if not fleet.can_write(request.user):
            return Response({"detail": "The Rental team keeps the register."}, status=403)
        msg = rental.save_register(a, request.data.get("rows"), request.user)
        if msg:
            return Response({"detail": msg}, status=400)
    d_from = _parse(request.GET.get("from") or request.data.get("from") if request.method == "PUT" else request.GET.get("from"))
    d_to = _parse(request.GET.get("to") or request.data.get("to") if request.method == "PUT" else request.GET.get("to"))
    if not d_from or not d_to:
        today = _date.today()
        d_from, d_to = today.replace(day=1), today
    if d_to < d_from or (d_to - d_from).days > 62:
        return Response({"detail": "Pick a window of up to two months."}, status=400)
    return Response(rental.register(a, d_from, d_to))


@api_view(["POST"])
@permission_classes([IsFleetReader])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def agreement_register_approve(request, pk):
    if not fleet.enabled():
        return _off()
    a = _agreement(pk)
    if a is None:
        return _off()
    if not fleet.can_write(request.user):
        return Response({"detail": "The Rental team keeps the register."}, status=403)
    d_from, d_to = _parse(request.data.get("from")), _parse(request.data.get("to"))
    if not d_from or not d_to or d_to < d_from:
        return Response({"detail": "Pick the days to approve."}, status=400)
    if request.data.get("action") == "reopen":
        n, msg = rental.unapprove_register(a, d_from, d_to, request.user)
    else:
        n, msg = rental.approve_register(a, d_from, d_to, request.data.get("approved_by"),
                                         request.data.get("via"), request.FILES.get("file"),
                                         request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response({**rental.register(a, d_from, d_to), "count": n})


@api_view(["GET", "PUT"])
@permission_classes([IsFleetReader])
def rental_terms(request):
    if not fleet.enabled():
        return _off()
    if request.method == "PUT":
        msg = rental.set_standard_terms(request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=403)
    return Response({**rental.standard_terms(), "can_edit": fleet.can_set_rates(request.user)})
