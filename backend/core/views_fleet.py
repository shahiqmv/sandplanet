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
