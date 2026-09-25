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


# ---- phase 5: invoices, receipts and receivables ------------------------------------

from .models import RentalInvoice, RentalReceipt  # noqa: E402


class IsFleetReaderAnyMethod(IsFleetReader):
    """Readers may also POST/DELETE here — the service decides who may
    (Finance records receipts; the Rental Manager issues invoices)."""


def _inv(iid):
    return RentalInvoice.objects.select_related("agreement", "customer", "issued_by").filter(id=iid).first()


@api_view(["GET", "POST"])
@permission_classes([IsFleetReader])
def agreement_invoices(request, pk):
    if not fleet.enabled():
        return _off()
    a = _agreement(pk)
    if a is None:
        return _off()
    if request.method == "POST":
        if not fleet.can_write(request.user):
            return Response({"detail": "The Rental team raises invoices."}, status=403)
        inv, msg = rental.create_invoice(a, request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(rental.invoice_dict(inv), status=201)
    d_from, d_to = _parse(request.GET.get("from")), _parse(request.GET.get("to"))
    out = {"invoices": [rental.invoice_dict(i) for i in
                        a.invoices.select_related("agreement", "customer", "issued_by")]}
    if d_from and d_to and d_to >= d_from:
        out["preview"] = rental.invoice_preview(a, d_from, d_to)
    return Response(out)


@api_view(["GET"])
@permission_classes([IsFleetReader])
def invoices(request):
    if not fleet.enabled():
        return _off()
    qs = RentalInvoice.objects.select_related("agreement", "customer", "issued_by").order_by("-id")
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("customer"):
        qs = qs.filter(customer_id=request.GET["customer"])
    return Response([rental.invoice_dict(i) for i in qs[:300]])


@api_view(["GET", "POST"])
@permission_classes([IsFleetReader])
def invoice_detail(request, iid):
    if not fleet.enabled():
        return _off()
    inv = _inv(iid)
    if inv is None:
        return _off()
    if request.method == "POST":
        if not fleet.can_write(request.user):
            return Response({"detail": "The Rental team keeps invoices."}, status=403)
        action = request.data.get("action")
        if action == "issue":
            msg = rental.issue_invoice(inv, request.user)
        elif action == "void":
            msg = rental.void_invoice(inv, request.data.get("reason"), request.user)
        else:
            msg = "Unknown action."
        if msg:
            return Response({"detail": msg}, status=400)
    return Response(rental.invoice_dict(_inv(iid)))


@api_view(["GET"])
@permission_classes([IsFleetReader])
def invoice_pdf(request, iid):
    if not fleet.enabled():
        return _off()
    inv = _inv(iid)
    if inv is None:
        return _off()
    if inv.pdf and inv.status != "VOID":
        return _pdf(inv.pdf.read(), f"{inv.ref}.pdf")
    try:
        pdf = rental.invoice_pdf_bytes(inv)
    except Exception as e:                            # pragma: no cover - env dep
        return Response({"detail": f"PDF engine unavailable: {e}"}, status=500)
    return _pdf(pdf, f"{inv.ref}.pdf")


@api_view(["GET", "POST"])
@permission_classes([IsFleetReaderAnyMethod])
def receipts(request):
    if not fleet.enabled():
        return _off()
    if request.method == "POST":
        rc, msg = rental.record_receipt(request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(rental.receipt_dict(rc), status=201)
    qs = RentalReceipt.objects.select_related("customer", "bank_account", "recorded_by")
    if request.GET.get("customer"):
        qs = qs.filter(customer_id=request.GET["customer"])
    return Response([rental.receipt_dict(r) for r in qs[:300]])


@api_view(["GET", "DELETE"])
@permission_classes([IsFleetReaderAnyMethod])
def receipt_detail(request, rid):
    if not fleet.enabled():
        return _off()
    rc = RentalReceipt.objects.filter(id=rid).first()
    if rc is None:
        return _off()
    if request.method == "DELETE":
        msg = rental.delete_receipt(rc, request.user)
        if msg:
            return Response({"detail": msg}, status=403)
        return Response({"detail": "Receipt deleted."})
    from .views_commercial import pdf_bytes
    try:
        pdf = pdf_bytes("pdf/official_receipt.html", rental.receipt_context(rc))
    except Exception as e:                            # pragma: no cover - env dep
        return Response({"detail": f"PDF engine unavailable: {e}"}, status=500)
    return _pdf(pdf, f"{rc.receipt_no}.pdf")


@api_view(["GET"])
@permission_classes([IsFleetReader])
def receipt_allocate(request):
    from .models import CompanyBankAccount
    if not fleet.enabled():
        return _off()
    customer = Customer.objects.filter(id=request.GET.get("customer")).first()
    if customer is None:
        return Response({"detail": "Pick the customer."}, status=400)
    amount = rental._dec(request.GET.get("amount"), rental.ZERO)
    rows, left = rental.auto_allocate(customer, amount if amount != "bad" else rental.ZERO)
    return Response({"allocations": rows, "unallocated": left,
                     "open_invoices": [{"id": i.id, "ref": i.ref, "agreement": i.agreement.ref,
                                        "currency": i.currency, "total": rental._s(i.total),
                                        "outstanding": rental._s(rental.invoice_outstanding(i)),
                                        "due_date": i.due_date}
                                       for i in rental.open_invoices(customer)],
                     "bank_accounts": [{"id": b.id, "label": b.label, "currency": b.currency}
                                       for b in CompanyBankAccount.objects.filter(is_active=True)
                                       .order_by("label")],
                     "can_receipt": rental.can_receipt(request.user)})


@api_view(["GET"])
@permission_classes([IsFleetReader])
def receivables(request):
    if not fleet.enabled():
        return _off()
    return Response({**rental.aging(), "can_receipt": rental.can_receipt(request.user)})


@api_view(["GET"])
@permission_classes([IsFleetReader])
def customer_statement(request, cid):
    if not fleet.enabled():
        return _off()
    customer = Customer.objects.filter(id=cid).first()
    if customer is None:
        return _off()
    d_from, d_to = _parse(request.GET.get("from")), _parse(request.GET.get("to"))
    if request.GET.get("pdf") == "1":
        from .views_commercial import pdf_bytes
        try:
            pdf = pdf_bytes("pdf/trading_statement.html",
                            rental.statement_context(customer, d_from, d_to))
        except Exception as e:                        # pragma: no cover - env dep
            return Response({"detail": f"PDF engine unavailable: {e}"}, status=500)
        return _pdf(pdf, f"SOA-{customer.name[:20]}.pdf")
    return Response(rental.statement(customer, d_from, d_to))
