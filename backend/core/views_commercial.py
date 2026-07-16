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
from .models import (BoqItem, ClientReceipt, ProgressClaim, Project,
                     Variation, VariationItem)
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
    amount_supply = serializers.DecimalField(max_digits=18, decimal_places=2,
                                             read_only=True)
    amount_install = serializers.DecimalField(max_digits=18, decimal_places=2,
                                              read_only=True)
    rate_total = serializers.DecimalField(max_digits=16, decimal_places=2,
                                          read_only=True)

    class Meta:
        model = BoqItem
        fields = ["id", "sort_order", "section", "item_code", "description",
                  "unit", "qty", "rate_supply", "rate_install", "rate_total",
                  "is_heading", "amount", "amount_supply", "amount_install"]


def _boq_payload(project):
    boq = getattr(project, "boq", None)
    if boq is None:
        return {"exists": False, "currency": "USD", "is_locked": False,
                "split_rates": False, "total": 0, "total_supply": 0,
                "total_install": 0, "items": []}
    return {"exists": True, "currency": boq.currency,
            "is_locked": boq.is_locked, "split_rates": boq.split_rates,
            "total": boq.total, "total_supply": boq.total_supply,
            "total_install": boq.total_install,
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
    # Supply (Material) + Install (Labour) columns; leave Install blank for a
    # combined-rate contract.
    headers = ["Section", "Code", "Description", "Unit", "Qty",
               "Material", "Labour"]
    ws.append(headers)
    for i, w in enumerate([22, 10, 46, 8, 12, 12, 12], start=1):
        ws.cell(row=1, column=i).font = Font(bold=True)
        ws.column_dimensions[chr(64 + i)].width = w
    ws.append(["Bill 1 — Substructure", "", "", "", "", "", ""])
    ws.append(["", "1.1", "Excavate for foundations", "m3", "120", "5.00",
               "3.50"])
    ws.append(["", "1.2", "Mass concrete blinding", "m3", "35", "80.00",
               "15.00"])
    ws.freeze_panes = "A2"
    resp = HttpResponse(content_type="application/vnd.openxmlformats-"
                        "officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = 'attachment; filename="boq-template.xlsx"'
    wb.save(resp)
    return resp


# ---- Variations (VOs) ---------------------------------------------------

class VariationItemSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2,
                                      read_only=True)
    amount_supply = serializers.DecimalField(max_digits=18, decimal_places=2,
                                             read_only=True)
    amount_install = serializers.DecimalField(max_digits=18, decimal_places=2,
                                              read_only=True)
    rate_total = serializers.DecimalField(max_digits=16, decimal_places=2,
                                          read_only=True)

    class Meta:
        model = VariationItem
        fields = ["id", "sort_order", "section", "item_code", "description",
                  "unit", "qty", "rate_supply", "rate_install", "rate_total",
                  "is_heading", "amount", "amount_supply", "amount_install"]


class VariationSerializer(serializers.ModelSerializer):
    gross = serializers.DecimalField(max_digits=18, decimal_places=2,
                                     read_only=True)
    signed_total = serializers.DecimalField(max_digits=18, decimal_places=2,
                                            read_only=True)
    items = VariationItemSerializer(many=True, read_only=True)

    class Meta:
        model = Variation
        fields = ["id", "seq", "ref", "title", "kind", "status", "ref_date",
                  "gross", "signed_total", "items"]


def _variations_payload(project):
    vs = project.variations.prefetch_related("items").all()
    return {
        "currency": (getattr(project, "boq", None).currency
                     if getattr(project, "boq", None) else "USD"),
        "contract": {k: v for k, v in commercial.contract_summary(
            project).items()},
        "variations": VariationSerializer(vs, many=True).data,
    }


def _get_variation(request, pk):
    try:
        v = Variation.objects.select_related("project__site").get(pk=pk)
    except Variation.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    if not _can_view_value(request.user, v.project):
        return None, Response({"detail": "Not permitted."}, status=403)
    return v, None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def variation_list(request, pid):
    p, err = _get_project(request, pid)
    if err:
        return err
    return Response(_variations_payload(p))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def variation_create(request, pid):
    p, err = _get_project(request, pid)
    if err:
        return err
    if (bad := _require_editor(request)):
        return bad
    commercial.create_variation(p, request.data, request.user)
    return Response(_variations_payload(p), status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def variation_items(request, pk):
    v, err = _get_variation(request, pk)
    if err:
        return err
    if (bad := _require_editor(request)):
        return bad
    _, msg = commercial.set_variation_items(v, request.data.get("rows") or [],
                                            request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_variations_payload(v.project))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def variation_meta(request, pk):
    v, err = _get_variation(request, pk)
    if err:
        return err
    if (bad := _require_editor(request)):
        return bad
    _, msg = commercial.set_variation_meta(v, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_variations_payload(v.project))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def variation_status(request, pk):
    v, err = _get_variation(request, pk)
    if err:
        return err
    if (bad := _require_editor(request)):
        return bad
    _, msg = commercial.set_variation_status(
        v, request.data.get("status"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_variations_payload(v.project))


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def variation_delete(request, pk):
    v, err = _get_variation(request, pk)
    if err:
        return err
    if (bad := _require_editor(request)):
        return bad
    if v.status != "DRAFT":
        return Response({"detail": "Only a draft variation can be deleted."},
                        status=400)
    project = v.project
    v.delete()
    return Response(_variations_payload(project))


# ---- Progress claims (interim payment applications) ---------------------

def _claim_meta(claim):
    return {
        "id": claim.id, "seq": claim.seq, "ref": claim.ref,
        "claim_type": claim.claim_type, "basis": claim.basis,
        "status": claim.status, "work_done_upto": claim.work_done_upto,
        "advance_pct": claim.advance_pct, "recovery_pct": claim.recovery_pct,
        "retention_pct": claim.retention_pct, "gst_pct": claim.gst_pct,
        "material_on_site": claim.material_on_site,
        "material_off_site": claim.material_off_site,
        "retention_released": claim.retention_released,
        "note": claim.note,
        "previous_ref": claim.previous.ref if claim.previous_id else None,
        "certified_at": claim.certified_at,
    }


def _receipt_json(r):
    return {
        "id": r.id, "amount": r.amount, "currency": r.currency,
        "received_on": r.received_on, "reference": r.reference,
        "note": r.note, "claim_ref": r.claim.ref if r.claim_id else None,
        "claim_id": r.claim_id,
        "recorded_by": (r.recorded_by.full_name if r.recorded_by_id else None),
    }


def _claims_payload(project):
    """The claims register: each claim's header plus its net-due / total from
    the waterfall, the contract summary, the money-in position and receipts."""
    claims = list(project.claims.all())
    rows = []
    for c in claims:
        w = commercial.claim_valuation(c)["waterfall"]
        rows.append({**_claim_meta(c),
                     "k_gross": w["k_gross"], "net_due": w["net_due"],
                     "gst": w["gst"], "total": w["total"]})
    receipts = project.receipts.all()
    return {
        "currency": (getattr(project, "boq", None).currency
                     if getattr(project, "boq", None) else "USD"),
        "contract": {k: v for k, v in commercial.contract_summary(
            project).items()},
        "can_raise": bool(getattr(project, "boq", None)
                          and project.boq.items.exists()),
        "claims": rows,
        "revenue": commercial.project_revenue_summary(project),
        "receipts": [_receipt_json(r) for r in receipts],
    }


def _claim_detail(claim):
    val = commercial.claim_valuation(claim)
    return {"claim": _claim_meta(claim), **val}


def _get_claim(request, pk):
    try:
        c = ProgressClaim.objects.select_related(
            "project__site", "previous").get(pk=pk)
    except ProgressClaim.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    if not _can_view_value(request.user, c.project):
        return None, Response({"detail": "Not permitted."}, status=403)
    return c, None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def claim_list(request, pid):
    p, err = _get_project(request, pid)
    if err:
        return err
    return Response(_claims_payload(p))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def claim_create(request, pid):
    p, err = _get_project(request, pid)
    if err:
        return err
    if (bad := _require_editor(request)):
        return bad
    _, msg = commercial.create_claim(p, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_claims_payload(p), status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def claim_detail(request, pk):
    c, err = _get_claim(request, pk)
    if err:
        return err
    return Response(_claim_detail(c))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def claim_items(request, pk):
    c, err = _get_claim(request, pk)
    if err:
        return err
    if (bad := _require_editor(request)):
        return bad
    _, msg = commercial.set_claim_items(c, request.data.get("rows") or [],
                                        request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_claim_detail(c))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def claim_meta(request, pk):
    c, err = _get_claim(request, pk)
    if err:
        return err
    if (bad := _require_editor(request)):
        return bad
    _, msg = commercial.set_claim_meta(c, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_claim_detail(c))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def claim_status(request, pk):
    c, err = _get_claim(request, pk)
    if err:
        return err
    if (bad := _require_editor(request)):
        return bad
    _, msg = commercial.set_claim_status(c, request.data.get("status"),
                                         request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_claim_detail(c))


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def claim_delete(request, pk):
    c, err = _get_claim(request, pk)
    if err:
        return err
    if (bad := _require_editor(request)):
        return bad
    if c.status != "DRAFT":
        return Response({"detail": "Only a draft claim can be deleted."},
                        status=400)
    # Only the newest claim can be removed — earlier ones anchor the chain.
    if c.project.claims.filter(seq__gt=c.seq).exists():
        return Response({"detail": "Delete the later claim(s) first."},
                        status=400)
    project = c.project
    c.delete()
    return Response(_claims_payload(project))


# ---- Client receipts (money-in, P4) -------------------------------------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def receipt_create(request, pid):
    p, err = _get_project(request, pid)
    if err:
        return err
    if (bad := _require_editor(request)):
        return bad
    _, msg = commercial.record_client_receipt(p, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_claims_payload(p), status=201)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def receipt_delete(request, pk):
    try:
        r = ClientReceipt.objects.select_related("project__site").get(pk=pk)
    except ClientReceipt.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if not _can_view_value(request.user, r.project):
        return Response({"detail": "Not permitted."}, status=403)
    if (bad := _require_editor(request)):
        return bad
    project = r.project
    commercial.delete_client_receipt(r, request.user)
    return Response(_claims_payload(project))
