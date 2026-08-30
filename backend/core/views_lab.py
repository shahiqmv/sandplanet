"""Materials & site testing API — test requests and their results."""
from rest_framework import serializers
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import (FormParser, JSONParser, MultiPartParser)
from rest_framework.response import Response

from . import lab
from .models import MaterialTest, Project, Site, TestResult
from .permissions import scoped_site_ids


class TestResultSerializer(serializers.ModelSerializer):
    recorded_by_name = serializers.CharField(source="recorded_by.full_name",
                                             read_only=True)
    certificate_url = serializers.SerializerMethodField()

    class Meta:
        model = TestResult
        fields = ["id", "report_ref", "specimen_ref", "age_days",
                  "tested_on", "value", "unit", "outcome", "remarks",
                  "recorded_by_name", "certificate_url"]

    def get_certificate_url(self, obj):
        try:
            return obj.certificate.url if obj.certificate else None
        except ValueError:                  # pragma: no cover - storage edge
            return None


class MaterialTestSerializer(serializers.ModelSerializer):
    ref = serializers.CharField(source="document.ref", read_only=True)
    status = serializers.CharField(source="document.status", read_only=True)
    site_code = serializers.CharField(source="document.site.code",
                                      read_only=True)
    project_code = serializers.CharField(source="document.project.code",
                                         read_only=True, default=None)
    kind_display = serializers.CharField(source="get_kind_display",
                                         read_only=True)
    requested_by_name = serializers.CharField(source="requested_by.full_name",
                                              read_only=True)
    ncr_ref = serializers.CharField(source="ncr.ref", read_only=True,
                                    default=None)
    mix_design_ref = serializers.CharField(source="mix_design.ref",
                                           read_only=True, default=None)
    results = TestResultSerializer(many=True, read_only=True)
    result_due_on = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()

    pdf_url = serializers.SerializerMethodField()

    class Meta:
        model = MaterialTest
        fields = ["id", "ref", "status", "site_code", "project_code", "kind",
                  "kind_display", "element", "location", "pour_ref", "grade",
                  "quantity", "spec_reference", "acceptance_criteria",
                  "required_value", "unit", "requested_on", "required_by",
                  "sampled_on", "sampled_note", "lab_name",
                  "witnessed_by", "notes", "requested_by_name", "ncr_ref",
                  "mix_design", "mix_design_ref",
                  "results", "result_due_on", "is_overdue", "pdf_url"]

    def get_pdf_url(self, obj):
        """The request sheet itself — what gets sent to the lab, and what
        ends up in the handover pack."""
        latest = obj.document.attachments.filter(
            kind="GENERATED_PDF").order_by("-id").first()
        try:
            return latest.file.url if latest and latest.file else None
        except ValueError:                  # pragma: no cover - storage edge
            return None

    def get_result_due_on(self, obj):
        return obj.result_due_on()

    def get_is_overdue(self, obj):
        return obj.is_overdue()


def _scope(qs, request):
    allowed = scoped_site_ids(request.user)
    if allowed is not None:
        qs = qs.filter(document__site_id__in=allowed)
    return qs


def _get_test(request, ref):
    test = _scope(MaterialTest.objects.select_related(
        "document", "document__site", "document__project", "requested_by",
        "ncr").prefetch_related("results"), request).filter(
        document__ref=ref).first()
    if test is None:
        return None, Response({"detail": "Not found."}, status=404)
    return test, None


@api_view(["GET", "POST"])
def tests(request):
    if request.method == "POST":
        if request.user.role not in lab.REQUESTER_ROLES:
            return Response({"detail": "Not allowed."}, status=403)
        site = Site.objects.filter(pk=request.data.get("site_id")).first()
        if site is None:
            return Response({"detail": "Choose the site."}, status=400)
        allowed = scoped_site_ids(request.user)
        if allowed is not None and site.id not in allowed:
            return Response({"detail": "Not your site."}, status=403)
        project = None
        if request.data.get("project_id"):
            project = Project.objects.filter(
                pk=request.data["project_id"], site=site).first()
        test, problem = lab.request_test(site=site, data=request.data,
                                         user=request.user, project=project)
        if problem:
            return Response({"detail": problem}, status=400)
        return Response(MaterialTestSerializer(test).data, status=201)

    qs = _scope(MaterialTest.objects.select_related(
        "document", "document__site", "document__project", "requested_by",
        "ncr").prefetch_related("results"), request)
    if request.GET.get("site"):
        qs = qs.filter(document__site_id=request.GET["site"])
    if request.GET.get("project"):
        qs = qs.filter(document__project_id=request.GET["project"])
    if request.GET.get("kind"):
        qs = qs.filter(kind=request.GET["kind"])
    if request.GET.get("status") == "awaiting":
        qs = qs.filter(document__status__in=["SAMPLED", "PARTIAL"])
    elif request.GET.get("status"):
        qs = qs.filter(document__status=request.GET["status"])
    rows = list(qs[:400])
    if request.GET.get("overdue"):
        rows = [t for t in rows if t.is_overdue()]
    return Response(MaterialTestSerializer(rows, many=True).data)


@api_view(["GET"])
def test_detail(request, ref):
    test, err = _get_test(request, ref)
    if err:
        return err
    return Response(MaterialTestSerializer(test).data)


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def test_results(request, ref):
    """Record a result. Several per request is normal — a concrete cube is
    broken at 7 days and again at 28."""
    test, err = _get_test(request, ref)
    if err:
        return err
    if request.user.role not in lab.REQUESTER_ROLES:
        return Response({"detail": "Not allowed."}, status=403)
    result, problem = lab.record_result(
        test=test, data=request.data, user=request.user,
        certificate=request.FILES.get("certificate"))
    if problem:
        return Response({"detail": problem}, status=400)
    test.refresh_from_db()
    return Response(MaterialTestSerializer(test).data, status=201)


@api_view(["POST"])
def test_sampled(request, ref):
    """Confirm the sample was taken. Until this the request is something the
    lab is being asked for; after it the result clock is running."""
    test, err = _get_test(request, ref)
    if err:
        return err
    if request.user.role not in lab.REQUESTER_ROLES:
        return Response({"detail": "Not allowed."}, status=403)
    problem = lab.confirm_sampling(test=test, data=request.data,
                                   user=request.user)
    if problem:
        return Response({"detail": problem}, status=400)
    test.refresh_from_db()
    return Response(MaterialTestSerializer(test).data)


@api_view(["POST"])
def test_ncr(request, ref):
    test, err = _get_test(request, ref)
    if err:
        return err
    if request.user.role not in lab.REQUESTER_ROLES:
        return Response({"detail": "Not allowed."}, status=403)
    ncr, problem = lab.raise_ncr_for(test, request.data, request.user)
    if problem:
        return Response({"detail": problem}, status=400)
    test.refresh_from_db()
    return Response(MaterialTestSerializer(test).data, status=201)


@api_view(["GET"])
def test_stats(request):
    return Response(lab.statistics(scoped_site_ids(request.user)))
