"""Rent the company pays — API (`/api/v1/rent/*`). Rules live in core/rent.py."""
import json

from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from . import rent
from .models import RentContract, RentDue


def _read(request):
    if request.user.role not in rent.VIEW_ROLES:
        return Response({"detail": "Rentals are open to Finance, the "
                                   "Director and the signatory."}, status=403)
    return None


def _write(request):
    if request.user.role not in rent.EDIT_ROLES:
        return Response({"detail": "Finance keeps the rentals."}, status=403)
    return None


def _data(request):
    """JSON, or — with the agreement attached — multipart with the fields
    as one JSON string beside the file."""
    if "payload" in request.data:
        try:
            return json.loads(request.data["payload"])
        except (TypeError, ValueError):
            return {}
    return request.data


def _find(ident):
    qs = RentContract.objects.select_related("site", "cost_head")
    if str(ident).upper().startswith("RENT-"):
        return qs.filter(ref__iexact=ident).first()
    return qs.filter(pk=ident).first() if str(ident).isdigit() else None


@api_view(["GET", "POST"])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def contracts(request):
    if (bad := _read(request)):
        return bad
    if request.method == "POST":
        if (bad := _write(request)):
            return bad
        c, msg = rent.save_contract(_data(request), request.user,
                                    agreement=request.FILES.get("agreement"))
        if msg:
            return Response({"detail": msg}, status=400)
        # a rental already under way has its current period up at once
        rent.raise_dues(actor=request.user, contract=c)
        return Response(rent.contract_dict(c, detail=True), status=201)
    qs = RentContract.objects.select_related("site", "cost_head") \
        .prefetch_related("dues")
    if request.GET.get("status") != "all":
        qs = qs.filter(status="ACTIVE")
    rows = [rent.contract_dict(c) for c in qs]
    return Response({
        "contracts": rows, "meta": rent.meta(),
        "can_edit": request.user.role in rent.EDIT_ROLES,
        "open_count": sum(r["open_count"] for r in rows),
        "overdue_count": sum(r["overdue_count"] for r in rows)})


@api_view(["GET", "PATCH"])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def contract_detail(request, ident):
    if (bad := _read(request)):
        return bad
    c = _find(ident)
    if c is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "PATCH":
        if (bad := _write(request)):
            return bad
        c, msg = rent.save_contract(_data(request), request.user, contract=c,
                                    agreement=request.FILES.get("agreement"))
        if msg:
            return Response({"detail": msg}, status=400)
    out = rent.contract_dict(c, detail=True)
    out.update(meta=rent.meta(),
               can_edit=request.user.role in rent.EDIT_ROLES)
    return Response(out)


@api_view(["POST"])
def contract_raise(request, ident):
    """Raise what has come up on this contract — and, with ahead=1, the
    next period too, before its time."""
    if (bad := _write(request)):
        return bad
    c = _find(ident)
    if c is None:
        return Response({"detail": "Not found."}, status=404)
    made = rent.raise_dues(actor=request.user, contract=c,
                           ahead=bool(request.data.get("ahead")))
    if not made:
        return Response({"detail": "Nothing has come up on this rental."
                         if c.status == "ACTIVE" else
                         "This rental has ended."}, status=400)
    out = rent.contract_dict(c, detail=True)
    out.update(raised=len(made), meta=rent.meta(), can_edit=True)
    return Response(out)


@api_view(["POST"])
def raise_all(request):
    """What the daily job does, on demand."""
    if (bad := _write(request)):
        return bad
    made = rent.raise_dues(actor=request.user)
    return Response({"raised": len(made)})


@api_view(["POST"])
def due_action(request, pk, action):
    if (bad := _write(request)):
        return bad
    due = RentDue.objects.select_related("contract", "contract__site",
                                         "contract__cost_head").filter(
        pk=pk).first()
    if due is None:
        return Response({"detail": "Not found."}, status=404)
    if action == "cancel":
        msg = rent.cancel_due(due, request.user, request.data.get("reason"))
    elif action == "raise-again":
        _, msg = rent.raise_again(due, request.user)
    else:
        return Response({"detail": "Unknown action."}, status=404)
    if msg:
        return Response({"detail": msg}, status=400)
    out = rent.contract_dict(due.contract, detail=True)
    out.update(meta=rent.meta(), can_edit=True)
    return Response(out)
