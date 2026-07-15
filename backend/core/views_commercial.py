"""Project commercial API (QS): BOQ. Progress claims + P&L follow in later
slices. Commercial data is contract-sensitive, so access is gated to those who
may see the contract value (HO roles incl. QS, and the assigned PM)."""
from rest_framework import serializers
from rest_framework.decorators import (api_view, parser_classes,
                                       permission_classes)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import commercial
from .models import BoqItem, Project
from .views_projects import PROJECT_EDIT_ROLES, _can_view_value


def _get_project(request, pid):
    try:
        p = Project.objects.select_related("site").get(pk=pid)
    except Project.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    if not _can_view_value(request.user, p):
        return None, Response({"detail": "Not permitted."}, status=403)
    return p, None


def _require_editor(request):
    if request.user.role not in PROJECT_EDIT_ROLES:
        return Response({"detail": "Only the QS / PM edits the BOQ."},
                        status=403)
    return None


class BoqItemSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2,
                                      read_only=True)

    class Meta:
        model = BoqItem
        fields = ["id", "sort_order", "section", "item_code", "description",
                  "unit", "qty", "rate", "is_heading", "amount"]


def _boq_payload(project):
    boq = getattr(project, "boq", None)
    if boq is None:
        return {"exists": False, "currency": "USD", "is_locked": False,
                "total": 0, "items": []}
    return {"exists": True, "currency": boq.currency,
            "is_locked": boq.is_locked, "total": boq.total,
            "items": BoqItemSerializer(boq.items.all(), many=True).data}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def boq_detail(request, pid):
    p, err = _get_project(request, pid)
    if err:
        return err
    return Response(_boq_payload(p))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def boq_save(request, pid):
    p, err = _get_project(request, pid)
    if err:
        return err
    if (bad := _require_editor(request)):
        return bad
    boq, msg = commercial.set_boq_items(p, request.data.get("rows") or [],
                                        request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_boq_payload(p))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def boq_lock(request, pid):
    p, err = _get_project(request, pid)
    if err:
        return err
    if (bad := _require_editor(request)):
        return bad
    _, msg = commercial.set_boq_lock(p, request.data.get("locked", True),
                                     request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_boq_payload(p))


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def boq_import(request, pid):
    p, err = _get_project(request, pid)
    if err:
        return err
    if (bad := _require_editor(request)):
        return bad
    upload = request.FILES.get("file")
    if not upload:
        return Response({"detail": "Attach the filled BOQ Excel (.xlsx)."},
                        status=400)
    from openpyxl import load_workbook
    try:
        wb = load_workbook(upload, read_only=True, data_only=True)
    except Exception:
        return Response({"detail": "Could not read that file — save it as "
                         ".xlsx and try again."}, status=400)
    ws = wb["BOQ"] if "BOQ" in wb.sheetnames else wb.active
    rows_iter = ws.iter_rows(values_only=True)
    header = next(rows_iter, None)
    if not header:
        return Response({"detail": "The sheet is empty."}, status=400)
    keys = [commercial.normalise_header(h) for h in header]
    if "description" not in keys:
        return Response({"detail": "Need at least a Description column."},
                        status=400)
    rows = []
    for raw in rows_iter:
        if raw is None or all(c in (None, "") for c in raw):
            continue
        rows.append({k: v for k, v in zip(keys, raw) if k})
    if not rows:
        return Response({"detail": "No rows found below the header."},
                        status=400)
    boq, msg = commercial.import_boq_rows(p, rows, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_boq_payload(p))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def boq_template(request, pid):
    from django.http import HttpResponse
    from openpyxl import Workbook
    from openpyxl.styles import Font
    p, err = _get_project(request, pid)
    if err:
        return err
    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    headers = ["Section", "Code", "Description", "Unit", "Qty", "Rate"]
    ws.append(headers)
    for i, w in enumerate([22, 10, 46, 8, 12, 12], start=1):
        ws.cell(row=1, column=i).font = Font(bold=True)
        ws.column_dimensions[chr(64 + i)].width = w
    ws.append(["Bill 1 — Substructure", "", "", "", "", ""])
    ws.append(["", "1.1", "Excavate for foundations", "m3", "120", "8.50"])
    ws.append(["", "1.2", "Mass concrete blinding", "m3", "35", "95.00"])
    ws.freeze_panes = "A2"
    resp = HttpResponse(content_type="application/vnd.openxmlformats-"
                        "officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = 'attachment; filename="boq-template.xlsx"'
    wb.save(resp)
    return resp
