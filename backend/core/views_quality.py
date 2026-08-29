"""QA / QC API — inspection & test plans, non-conformance, supplier ratings."""
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import quality
from .models import (InspectionTestPlan, ItpItem, ItpRecord, NonConformance,
                     Site, Supplier, SupplierEvaluation)
from .permissions import scoped_site_ids
from .views_hse import ActionSerializer


class ItpRecordSerializer(serializers.ModelSerializer):
    inspected_by_name = serializers.CharField(source="inspected_by.full_name",
                                              read_only=True)

    class Meta:
        model = ItpRecord
        fields = ["id", "location", "inspected_on", "inspected_by_name",
                  "inspector_name", "result", "note"]


class ItpItemSerializer(serializers.ModelSerializer):
    point_type_display = serializers.CharField(source="get_point_type_display",
                                               read_only=True)
    records = ItpRecordSerializer(many=True, read_only=True)

    class Meta:
        model = ItpItem
        fields = ["id", "sort_order", "activity", "reference",
                  "acceptance_criteria", "point_type", "point_type_display",
                  "responsible", "frequency", "record_required", "records"]


class ItpSerializer(serializers.ModelSerializer):
    ref = serializers.CharField(source="document.ref", read_only=True)
    status = serializers.CharField(source="document.status", read_only=True)
    site_code = serializers.CharField(source="document.site.code",
                                      read_only=True)
    prepared_by_name = serializers.CharField(source="prepared_by.full_name",
                                             read_only=True)
    supersedes_ref = serializers.CharField(source="supersedes.document.ref",
                                           read_only=True, default=None)
    items = ItpItemSerializer(many=True, read_only=True)
    progress = serializers.SerializerMethodField()

    class Meta:
        model = InspectionTestPlan
        fields = ["id", "ref", "status", "site_code", "title", "discipline",
                  "prepared_by_name", "prepared_on", "notes", "items",
                  "supersedes_ref", "progress"]

    def get_progress(self, obj):
        return quality.itp_progress(obj)


class NcrSerializer(serializers.ModelSerializer):
    ref = serializers.CharField(source="document.ref", read_only=True)
    status = serializers.CharField(source="document.status", read_only=True)
    site_code = serializers.CharField(source="document.site.code",
                                      read_only=True)
    category_display = serializers.CharField(source="get_category_display",
                                             read_only=True)
    disposition_display = serializers.CharField(
        source="get_disposition_display", read_only=True, default=None)
    raised_by_name = serializers.CharField(source="raised_by.full_name",
                                           read_only=True)
    disposition_by_name = serializers.CharField(
        source="disposition_by.full_name", read_only=True, default=None)
    supplier_name = serializers.CharField(source="supplier.name",
                                          read_only=True, default=None)
    actions = serializers.SerializerMethodField()
    open_actions = serializers.SerializerMethodField()

    class Meta:
        model = NonConformance
        fields = ["id", "ref", "status", "site_code", "category",
                  "category_display", "severity", "raised_by_name",
                  "raised_on", "location", "description", "requirement",
                  "supplier", "supplier_name", "disposition",
                  "disposition_display", "disposition_note",
                  "disposition_by_name", "disposition_at", "root_cause",
                  "cost_impact", "closed_at", "verification_note",
                  "actions", "open_actions"]

    def get_actions(self, obj):
        return ActionSerializer(obj.document.corrective_actions.all(),
                                many=True).data

    def get_open_actions(self, obj):
        from .hse import open_actions_for
        return open_actions_for(obj.document).count()


class EvaluationSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name",
                                          read_only=True)
    evaluated_by_name = serializers.CharField(source="evaluated_by.full_name",
                                              read_only=True)

    class Meta:
        model = SupplierEvaluation
        fields = ["id", "supplier", "supplier_name", "period_start",
                  "period_end", "quality", "delivery", "price",
                  "responsiveness", "documentation", "score", "band",
                  "ncr_count", "notes", "evaluated_by_name"]


def _site_or_error(request, site_id):
    try:
        site = Site.objects.get(pk=site_id)
    except (Site.DoesNotExist, ValueError, TypeError):
        return None, Response({"detail": "Choose the site."}, status=400)
    allowed = scoped_site_ids(request.user)
    if allowed is not None and site.id not in allowed:
        return None, Response({"detail": "Not your site."}, status=403)
    return site, None


def _scope(qs, request, path="document__site_id"):
    allowed = scoped_site_ids(request.user)
    if allowed is not None:
        qs = qs.filter(**{f"{path}__in": allowed})
    return qs


# ---- ITP ----------------------------------------------------------------

@api_view(["GET", "POST"])
def itps(request):
    if request.method == "POST":
        if request.user.role not in quality.RAISER_ROLES:
            return Response({"detail": "Not allowed."}, status=403)
        site, err = _site_or_error(request, request.data.get("site_id"))
        if err:
            return err
        plan, problem = quality.create_itp(site=site, data=request.data,
                                           user=request.user)
        if problem:
            return Response({"detail": problem}, status=400)
        return Response(ItpSerializer(plan).data, status=201)

    qs = _scope(InspectionTestPlan.objects.select_related(
        "document", "document__site", "prepared_by",
        "supersedes__document").prefetch_related("items", "items__records"),
        request)
    if request.GET.get("site"):
        qs = qs.filter(document__site_id=request.GET["site"])
    if request.GET.get("status") == "current":
        qs = qs.filter(document__status="RECORDED")
    return Response(ItpSerializer(qs[:200], many=True).data)


@api_view(["POST"])
def itp_item_record(request, pk):
    item = ItpItem.objects.select_related("plan__document").filter(
        pk=pk).first()
    if item is None:
        return Response({"detail": "Not found."}, status=404)
    allowed = scoped_site_ids(request.user)
    if allowed is not None and item.plan.document.site_id not in allowed:
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in quality.RAISER_ROLES:
        return Response({"detail": "Not allowed."}, status=403)
    record, problem = quality.record_itp_result(
        item=item, data=request.data, user=request.user)
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(ItpRecordSerializer(record).data, status=201)


# ---- NCR ----------------------------------------------------------------

def _get_ncr(request, ref):
    qs = _scope(NonConformance.objects.select_related(
        "document", "document__site", "raised_by", "supplier",
        "disposition_by"), request)
    ncr = qs.filter(document__ref=ref).first()
    if ncr is None:
        return None, Response({"detail": "Not found."}, status=404)
    return ncr, None


@api_view(["GET", "POST"])
def ncrs(request):
    if request.method == "POST":
        if request.user.role not in quality.RAISER_ROLES:
            return Response({"detail": "Not allowed."}, status=403)
        site, err = _site_or_error(request, request.data.get("site_id"))
        if err:
            return err
        ncr, problem = quality.raise_ncr(site=site, data=request.data,
                                          user=request.user)
        if problem:
            return Response({"detail": problem}, status=400)
        return Response(NcrSerializer(ncr).data, status=201)

    qs = _scope(NonConformance.objects.select_related(
        "document", "document__site", "raised_by", "supplier",
        "disposition_by"), request)
    if request.GET.get("site"):
        qs = qs.filter(document__site_id=request.GET["site"])
    if request.GET.get("status") == "open":
        qs = qs.exclude(document__status="CLOSED")
    if request.GET.get("supplier"):
        qs = qs.filter(supplier_id=request.GET["supplier"])
    return Response(NcrSerializer(qs[:300], many=True).data)


@api_view(["GET", "PATCH"])
def ncr_detail(request, ref):
    ncr, err = _get_ncr(request, ref)
    if err:
        return err
    if request.method == "GET":
        return Response(NcrSerializer(ncr).data)
    if request.user.role not in quality.RAISER_ROLES:
        return Response({"detail": "Not allowed."}, status=403)
    if ncr.document.status == "CLOSED":
        return Response({"detail": "This NCR is closed."}, status=400)
    changed = []
    for field in ("severity", "location", "requirement", "root_cause",
                  "cost_impact", "supplier"):
        if field in request.data:
            setattr(ncr, field if field != "supplier" else "supplier_id",
                    request.data[field])
            changed.append(field)
    if changed:
        ncr.save()
        audit_fields = sorted(changed)
        from .audit import audit
        audit("document", ncr.document_id, "NCR_UPDATED", actor=request.user,
              detail={"fields": audit_fields})
    return Response(NcrSerializer(ncr).data)


@api_view(["POST"])
def ncr_disposition(request, ref):
    ncr, err = _get_ncr(request, ref)
    if err:
        return err
    if request.user.role not in quality.DISPOSITION_ROLES:
        return Response({"detail": "A PM, QS or Director decides what "
                                   "happens to non-conforming work."},
                        status=403)
    problem = quality.set_disposition(ncr, request.data, request.user)
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(NcrSerializer(ncr).data)


@api_view(["POST"])
def ncr_close(request, ref):
    ncr, err = _get_ncr(request, ref)
    if err:
        return err
    if request.user.role not in quality.DISPOSITION_ROLES:
        return Response({"detail": "A PM, QS or Director closes an NCR."},
                        status=403)
    problem = quality.close_ncr(ncr, request.user,
                                request.data.get("note", ""))
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(NcrSerializer(ncr).data)


@api_view(["POST"])
def ncr_actions(request, ref):
    ncr, err = _get_ncr(request, ref)
    if err:
        return err
    action, problem = quality.raise_ncr_action(ncr, request.data,
                                                request.user)
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(ActionSerializer(action).data, status=201)


# ---- supplier evaluation ------------------------------------------------

@api_view(["GET", "POST"])
def supplier_evaluations(request):
    if request.method == "POST":
        if request.user.role not in quality.DISPOSITION_ROLES | {
                "HO_PURCHASING"}:
            return Response({"detail": "Not allowed."}, status=403)
        supplier = Supplier.objects.filter(
            pk=request.data.get("supplier_id")).first()
        if supplier is None:
            return Response({"detail": "Unknown supplier."}, status=400)
        evaluation, problem = quality.evaluate_supplier(
            supplier=supplier, data=request.data, user=request.user)
        if problem:
            return Response({"detail": problem}, status=400)
        return Response(EvaluationSerializer(evaluation).data, status=201)

    qs = SupplierEvaluation.objects.select_related("supplier", "evaluated_by")
    if request.GET.get("supplier"):
        qs = qs.filter(supplier_id=request.GET["supplier"])
    return Response(EvaluationSerializer(qs[:200], many=True).data)


@api_view(["GET"])
def supplier_scorecards(request):
    """The supplier register with performance beside the name."""
    rows = [quality.supplier_scorecard(s)
            for s in Supplier.objects.all().order_by("name")[:400]]
    if request.GET.get("rated"):
        rows = [r for r in rows if r["latest_score"] is not None]
    return Response(rows)
