"""Handover API — the dossier, its candidates, and the snag list."""
from rest_framework import serializers
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import (FormParser, JSONParser,
                                    MultiPartParser)
from rest_framework.response import Response

from . import handover
from .models import (HandoverDossier, HandoverItem, HandoverTransmittal,
                     HandoverTransmittalLine, Project, SnagItem)
from .permissions import scoped_site_ids


class HandoverItemSerializer(serializers.ModelSerializer):
    section_display = serializers.CharField(source="get_section_display",
                                            read_only=True)
    document_ref = serializers.CharField(source="document.ref",
                                         read_only=True, default=None)
    document_type = serializers.CharField(source="document.doc_type",
                                          read_only=True, default=None)
    file_url = serializers.SerializerMethodField()
    provided_by_name = serializers.CharField(source="provided_by.full_name",
                                             read_only=True, default=None)
    has_evidence = serializers.BooleanField(read_only=True)

    class Meta:
        model = HandoverItem
        fields = ["id", "section", "section_display", "discipline", "title",
                  "reference", "description", "status", "document",
                  "document_ref", "document_type", "file_url", "provided_on",
                  "provided_by_name", "accepted_on", "notes", "revision",
                  "has_evidence"]

    def get_file_url(self, obj):
        try:
            return obj.file.url if obj.file else None
        except ValueError:                  # pragma: no cover - storage edge
            return None


class TransmittalLineSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source="item.title", read_only=True)
    section = serializers.CharField(source="item.section", read_only=True)
    reference = serializers.CharField(source="item.reference", read_only=True)
    item_status = serializers.CharField(source="item.status", read_only=True)
    recorded_by_name = serializers.CharField(source="recorded_by.full_name",
                                             read_only=True, default=None)

    class Meta:
        model = HandoverTransmittalLine
        fields = ["id", "item", "title", "section", "reference",
                  "item_status", "revision", "result", "result_on",
                  "reviewed_by", "position", "reply_ref", "comments",
                  "recorded_by_name", "recorded_at"]


class TransmittalSerializer(serializers.ModelSerializer):
    lines = TransmittalLineSerializer(many=True, read_only=True)
    issued_by_name = serializers.CharField(source="issued_by.full_name",
                                           read_only=True, default=None)
    is_overdue = serializers.BooleanField(read_only=True)
    answered = serializers.SerializerMethodField()

    class Meta:
        model = HandoverTransmittal
        fields = ["id", "ref", "seq", "status", "subject", "covering_note",
                  "addressed_to", "organisation", "issued_on",
                  "issued_by_name", "response_days", "response_due_on",
                  "is_overdue", "lines", "answered"]

    def get_answered(self, obj):
        return sum(1 for ln in obj.lines.all() if ln.result)


class SnagSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.full_name",
                                       read_only=True, default=None)
    raised_by_name = serializers.CharField(source="raised_by.full_name",
                                           read_only=True)
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = SnagItem
        fields = ["id", "ref_no", "location", "discipline", "description",
                  "raised_on", "raised_by_name", "owner", "owner_name",
                  "owner_note", "due_date", "status", "fixed_on", "closed_on",
                  "in_dlp", "photo_url"]

    def get_photo_url(self, obj):
        try:
            return obj.photo.url if obj.photo else None
        except ValueError:                  # pragma: no cover - storage edge
            return None


class DossierSerializer(serializers.ModelSerializer):
    project_code = serializers.CharField(source="project.code",
                                         read_only=True)
    project_title = serializers.CharField(source="project.title",
                                          read_only=True)
    items = HandoverItemSerializer(many=True, read_only=True)
    transmittals = serializers.SerializerMethodField()
    completeness = serializers.SerializerMethodField()
    snags = serializers.SerializerMethodField()
    dlp_ends = serializers.SerializerMethodField()

    class Meta:
        model = HandoverDossier
        fields = ["id", "project", "project_code", "project_title",
                  "target_date", "notes", "taking_over_on",
                  "taking_over_ref", "making_good_on", "making_good_ref",
                  "items", "completeness", "snags", "dlp_ends",
                  "transmittals"]

    def get_transmittals(self, obj):
        return handover.transmittal_summary(obj)

    def get_completeness(self, obj):
        return handover.completeness(obj)

    def get_snags(self, obj):
        return handover.snag_summary(obj)

    def get_dlp_ends(self, obj):
        return obj.defects_liability_ends()


def _dossier(request, project_id, create_with=None):
    project = Project.objects.select_related("site").filter(
        pk=project_id).first()
    if project is None:
        return None, Response({"detail": "Not found."}, status=404)
    allowed = scoped_site_ids(request.user)
    if allowed is not None and project.site_id not in allowed:
        return None, Response({"detail": "Not found."}, status=404)
    dossier = getattr(project, "handover", None)
    if dossier is None:
        if create_with is None:
            return None, Response({"detail": "no-dossier"}, status=404)
        dossier, _ = handover.open_dossier(project, create_with)
    return dossier, None


@api_view(["GET", "POST"])
def dossier(request, pk):
    """GET the pack; POST opens one with the standard checklist."""
    if request.method == "POST":
        if request.user.role not in handover.RECORDER_ROLES:
            return Response({"detail": "Not allowed."}, status=403)
        d, err = _dossier(request, pk, create_with=request.user)
        if err:
            return err
        return Response(DossierSerializer(d).data, status=201)

    d, err = _dossier(request, pk)
    if err:
        return err
    return Response(DossierSerializer(d).data)


@api_view(["GET"])
def dossier_candidates(request, pk):
    """Records already produced on this project that belong in the pack."""
    d, err = _dossier(request, pk)
    if err:
        return err
    return Response(handover.candidates(d))


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def dossier_upload(request, pk):
    """Add an item with a file — cube test reports, as-builts, O&M manuals,
    warranties: the parts of the pack that arrive as paper."""
    d, err = _dossier(request, pk)
    if err:
        return err
    if request.user.role not in handover.RECORDER_ROLES:
        return Response({"detail": "Not allowed."}, status=403)
    item, problem = handover.add_item(d, request.data, request.user,
                                      file=request.FILES.get("file"))
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(HandoverItemSerializer(item).data, status=201)


@api_view(["POST"])
def dossier_items(request, pk):
    d, err = _dossier(request, pk)
    if err:
        return err
    if request.user.role not in handover.RECORDER_ROLES:
        return Response({"detail": "Not allowed."}, status=403)
    item, problem = handover.add_item(d, request.data, request.user)
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(HandoverItemSerializer(item).data, status=201)


@api_view(["PATCH", "DELETE"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def dossier_item_detail(request, pk):
    item = HandoverItem.objects.select_related(
        "dossier__project").filter(pk=pk).first()
    if item is None:
        return Response({"detail": "Not found."}, status=404)
    allowed = scoped_site_ids(request.user)
    if allowed is not None \
            and item.dossier.project.site_id not in allowed:
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in handover.RECORDER_ROLES:
        return Response({"detail": "Not allowed."}, status=403)
    if request.method == "DELETE":
        item.delete()
        return Response(status=204)
    item, problem = handover.update_item(item, request.data, request.user,
                                         file=request.FILES.get("file"))
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(HandoverItemSerializer(item).data)


@api_view(["POST"])
def dossier_milestones(request, pk):
    d, err = _dossier(request, pk)
    if err:
        return err
    if request.user.role not in handover.CLOSER_ROLES:
        return Response({"detail": "A PM, QS or Director records taking-over."},
                        status=403)
    handover.record_milestone(d, request.data, request.user)
    return Response(DossierSerializer(d).data)


def _transmittal(request, pk):
    t = HandoverTransmittal.objects.select_related(
        "dossier__project").filter(pk=pk).first()
    if t is None:
        return None, Response({"detail": "Not found."}, status=404)
    allowed = scoped_site_ids(request.user)
    if allowed is not None and t.dossier.project.site_id not in allowed:
        return None, Response({"detail": "Not found."}, status=404)
    return t, None


@api_view(["GET", "POST"])
def transmittals(request, pk):
    """The submission log: what went to the client, when, and what came
    back."""
    d, err = _dossier(request, pk)
    if err:
        return err
    if request.method == "POST":
        if request.user.role not in handover.TRANSMITTAL_EDITOR_ROLES:
            return Response({"detail": "Not allowed."}, status=403)
        try:
            t = handover.create_transmittal(d, request.data, request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(TransmittalSerializer(t).data, status=201)
    qs = d.transmittals.prefetch_related("lines__item", "lines__recorded_by")
    return Response(TransmittalSerializer(qs, many=True).data)


@api_view(["GET"])
def transmittal_candidates(request, pk):
    """Documents that can go out: owed, evidenced, and not already with the
    client."""
    d, err = _dossier(request, pk)
    if err:
        return err
    return Response(HandoverItemSerializer(
        handover.submittable(d), many=True).data)


@api_view(["GET", "PATCH", "DELETE"])
def transmittal_detail(request, pk):
    t, err = _transmittal(request, pk)
    if err:
        return err
    if request.method == "GET":
        return Response(TransmittalSerializer(t).data)
    if request.user.role not in handover.TRANSMITTAL_EDITOR_ROLES:
        return Response({"detail": "Not allowed."}, status=403)
    if request.method == "DELETE":
        if t.status != "DRAFT":
            return Response({"detail": "An issued transmittal is part of the "
                                       "record and cannot be deleted."},
                            status=400)
        t.delete()
        return Response(status=204)
    if t.status != "DRAFT":
        return Response({"detail": "This transmittal has been issued — its "
                                   "contents are fixed."}, status=400)
    for field in ("subject", "covering_note", "addressed_to", "organisation"):
        if field in request.data:
            setattr(t, field, request.data[field])
    if "response_days" in request.data:
        t.response_days = int(request.data["response_days"] or 14)
    t.save()
    if "item_ids" in request.data:
        problem = handover.set_transmittal_items(
            t, request.data["item_ids"], request.user)
        if problem:
            return Response({"detail": problem}, status=400)
    return Response(TransmittalSerializer(t).data)


@api_view(["POST"])
def transmittal_issue(request, pk):
    t, err = _transmittal(request, pk)
    if err:
        return err
    if request.user.role not in handover.TRANSMITTAL_ISSUER_ROLES:
        return Response({"detail": "A PM, QS or Director issues a transmittal "
                                   "to the client."}, status=403)
    problem = handover.issue_transmittal(t, request.data, request.user)
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(TransmittalSerializer(t).data)


@api_view(["GET"])
def transmittal_pdf(request, pk):
    """The covering note that goes to the Engineer with the documents."""
    from django.http import HttpResponse

    from .views_commercial import pdf_bytes
    t, err = _transmittal(request, pk)
    if err:
        return err
    if not t.lines.exists():
        return Response({"detail": "This transmittal has no documents."},
                        status=400)
    try:
        pdf = pdf_bytes("pdf/handover_transmittal.html",
                        handover.transmittal_pdf_context(t))
    except Exception as exc:            # pragma: no cover - env dependent
        return Response({"detail": f"PDF engine unavailable: {exc}"},
                        status=500)
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = (
        f'inline; filename="{t.dossier.project.code}-{t.ref}.pdf"')
    return resp


@api_view(["POST"])
def transmittal_response(request, pk):
    """Record what the Engineer said about one document."""
    line = HandoverTransmittalLine.objects.select_related(
        "transmittal__dossier__project", "item").filter(pk=pk).first()
    if line is None:
        return Response({"detail": "Not found."}, status=404)
    allowed = scoped_site_ids(request.user)
    if allowed is not None \
            and line.transmittal.dossier.project.site_id not in allowed:
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in handover.TRANSMITTAL_ISSUER_ROLES:
        return Response({"detail": "A PM, QS or Director records the client's "
                                   "response."}, status=403)
    problem = handover.record_response(line, request.data, request.user)
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(TransmittalLineSerializer(line).data)


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def snags(request, pk):
    d, err = _dossier(request, pk)
    if err:
        return err
    if request.method == "POST":
        if request.user.role not in handover.RECORDER_ROLES:
            return Response({"detail": "Not allowed."}, status=403)
        snag, problem = handover.raise_snag(d, request.data, request.user,
                                            photo=request.FILES.get("photo"))
        if problem:
            return Response({"detail": problem}, status=400)
        return Response(SnagSerializer(snag).data, status=201)

    qs = d.snags.select_related("owner", "raised_by")
    if request.GET.get("status") == "open":
        qs = qs.filter(status__in=["OPEN", "IN_PROGRESS", "FIXED"])
    return Response(SnagSerializer(qs, many=True).data)


@api_view(["PATCH"])
def snag_detail(request, pk):
    snag = SnagItem.objects.select_related("dossier__project").filter(
        pk=pk).first()
    if snag is None:
        return Response({"detail": "Not found."}, status=404)
    allowed = scoped_site_ids(request.user)
    if allowed is not None \
            and snag.dossier.project.site_id not in allowed:
        return Response({"detail": "Not found."}, status=404)
    if request.data.get("status") == "CLOSED" \
            and request.user.role not in handover.CLOSER_ROLES:
        return Response({"detail": "A PM, QS or Director closes a snag."},
                        status=403)
    if request.user.role not in handover.RECORDER_ROLES:
        return Response({"detail": "Not allowed."}, status=403)
    return Response(SnagSerializer(
        handover.update_snag(snag, request.data, request.user)).data)
