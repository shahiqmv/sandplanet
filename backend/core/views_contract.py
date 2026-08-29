"""Contract & time API — correspondence, delay events, extensions of time."""
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import contract
from .models import (Correspondence, DelayEvent, ExtensionOfTime, Project,
                     Site)
from .permissions import scoped_site_ids


class CorrespondenceSerializer(serializers.ModelSerializer):
    ref = serializers.CharField(source="document.ref", read_only=True)
    status = serializers.CharField(source="document.status", read_only=True)
    site_code = serializers.CharField(source="document.site.code",
                                      read_only=True)
    project_code = serializers.CharField(source="document.project.code",
                                         read_only=True, default=None)
    kind_display = serializers.CharField(source="get_kind_display",
                                         read_only=True)
    raised_by_name = serializers.CharField(source="raised_by.full_name",
                                           read_only=True)
    days_outstanding = serializers.SerializerMethodField()
    served_late = serializers.SerializerMethodField()

    class Meta:
        model = Correspondence
        fields = ["id", "ref", "status", "site_code", "project_code", "kind",
                  "kind_display", "direction", "party", "party_name",
                  "their_ref", "subject", "body", "dated_on",
                  "response_required", "response_due", "responded_on",
                  "response_summary", "clause", "aware_on", "time_bar_on",
                  "raised_by_name", "days_outstanding", "served_late"]

    def get_days_outstanding(self, obj):
        return obj.days_outstanding()

    def get_served_late(self, obj):
        return obj.served_late()


class DelayEventSerializer(serializers.ModelSerializer):
    ref = serializers.CharField(source="document.ref", read_only=True)
    status = serializers.CharField(source="document.status", read_only=True)
    project_code = serializers.CharField(source="project.code",
                                         read_only=True)
    cause_display = serializers.CharField(source="get_cause_display",
                                          read_only=True)
    responsibility_display = serializers.CharField(
        source="get_responsibility_display", read_only=True)
    notice_ref = serializers.CharField(source="notice.document.ref",
                                       read_only=True, default=None)
    duration = serializers.SerializerMethodField()
    activity_names = serializers.SerializerMethodField()
    evidence_refs = serializers.SerializerMethodField()

    class Meta:
        model = DelayEvent
        fields = ["id", "ref", "status", "project", "project_code", "title",
                  "description", "cause", "cause_display", "responsibility",
                  "responsibility_display", "started_on", "ended_on",
                  "days_lost", "mitigation", "notice_ref", "duration",
                  "activity_names", "evidence_refs"]

    def get_duration(self, obj):
        return obj.duration_days()

    def get_activity_names(self, obj):
        return [a.name for a in obj.activities.all()[:20]]

    def get_evidence_refs(self, obj):
        return [d.ref for d in obj.evidence.all()[:20]]


class EotSerializer(serializers.ModelSerializer):
    ref = serializers.CharField(source="document.ref", read_only=True)
    status = serializers.CharField(source="document.status", read_only=True)
    project_code = serializers.CharField(source="project.code",
                                         read_only=True)
    raised_by_name = serializers.CharField(source="raised_by.full_name",
                                           read_only=True)
    event_refs = serializers.SerializerMethodField()
    baseline_label = serializers.CharField(source="baseline.label",
                                           read_only=True, default=None)

    class Meta:
        model = ExtensionOfTime
        fields = ["id", "ref", "status", "project", "project_code",
                  "days_claimed", "days_awarded", "submitted_on",
                  "decided_on", "revised_completion", "grounds",
                  "decision_note", "raised_by_name", "event_refs",
                  "baseline_label"]

    def get_event_refs(self, obj):
        return [e.document.ref for e in obj.delay_events.all()]


def _scope(qs, request, path="document__site_id"):
    allowed = scoped_site_ids(request.user)
    if allowed is not None:
        qs = qs.filter(**{f"{path}__in": allowed})
    return qs


def _project_or_error(request, project_id):
    project = Project.objects.select_related("site").filter(
        pk=project_id).first()
    if project is None:
        return None, Response({"detail": "Choose the project."}, status=400)
    allowed = scoped_site_ids(request.user)
    if allowed is not None and project.site_id not in allowed:
        return None, Response({"detail": "Not your site."}, status=403)
    return project, None


# ---- correspondence -----------------------------------------------------

@api_view(["GET", "POST"])
def correspondence(request):
    if request.method == "POST":
        if request.user.role not in contract.RAISER_ROLES:
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
        record, problem = contract.log_correspondence(
            site=site, data=request.data, user=request.user, project=project)
        if problem:
            return Response({"detail": problem}, status=400)
        return Response(CorrespondenceSerializer(record).data, status=201)

    qs = _scope(Correspondence.objects.select_related(
        "document", "document__site", "document__project", "raised_by"),
        request)
    if request.GET.get("site"):
        qs = qs.filter(document__site_id=request.GET["site"])
    if request.GET.get("kind"):
        qs = qs.filter(kind=request.GET["kind"])
    if request.GET.get("status") == "outstanding":
        qs = qs.filter(response_required=True,
                       responded_on__isnull=True).exclude(
            document__status="CLOSED")
    return Response(CorrespondenceSerializer(qs[:400], many=True).data)


@api_view(["POST"])
def correspondence_respond(request, ref):
    record = _scope(Correspondence.objects.select_related("document"),
                    request).filter(document__ref=ref).first()
    if record is None:
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in contract.RAISER_ROLES:
        return Response({"detail": "Not allowed."}, status=403)
    problem = contract.record_response(record, request.data, request.user)
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(CorrespondenceSerializer(record).data)


# ---- delay events -------------------------------------------------------

@api_view(["GET", "POST"])
def delays(request):
    if request.method == "POST":
        if request.user.role not in contract.RAISER_ROLES:
            return Response({"detail": "Not allowed."}, status=403)
        project, err = _project_or_error(request,
                                         request.data.get("project_id"))
        if err:
            return err
        event, problem = contract.log_delay(project=project,
                                            data=request.data,
                                            user=request.user)
        if problem:
            return Response({"detail": problem}, status=400)
        return Response(DelayEventSerializer(event).data, status=201)

    qs = _scope(DelayEvent.objects.select_related(
        "document", "project", "notice__document").prefetch_related(
        "activities", "evidence"), request)
    if request.GET.get("project"):
        qs = qs.filter(project_id=request.GET["project"])
    if request.GET.get("open"):
        qs = qs.filter(ended_on__isnull=True)
    return Response(DelayEventSerializer(qs[:300], many=True).data)


@api_view(["PATCH"])
def delay_detail(request, ref):
    event = _scope(DelayEvent.objects.select_related("document", "project"),
                   request).filter(document__ref=ref).first()
    if event is None:
        return Response({"detail": "Not found."}, status=404)
    if "responsibility" in request.data \
            and request.user.role not in contract.COMMERCIAL_ROLES:
        return Response({"detail": "A PM, QS or Director decides whose risk "
                                   "a delay is."}, status=403)
    changed = []
    for field in ("responsibility", "ended_on", "days_lost", "mitigation",
                  "description"):
        if field in request.data:
            setattr(event, field, request.data[field] or None)
            changed.append(field)
    if changed:
        event.save()
        from .audit import audit
        audit("document", event.document_id, "DELAY_UPDATED",
              actor=request.user, detail={"fields": sorted(changed)})
    contract._link_delay(event, request.data, event.project)
    return Response(DelayEventSerializer(event).data)


# ---- extension of time --------------------------------------------------

@api_view(["GET", "POST"])
def eots(request):
    if request.method == "POST":
        if request.user.role not in contract.COMMERCIAL_ROLES:
            return Response({"detail": "A PM, QS or Director prepares an "
                                       "application."}, status=403)
        project, err = _project_or_error(request,
                                         request.data.get("project_id"))
        if err:
            return err
        eot, problem = contract.create_eot(project=project,
                                           data=request.data,
                                           user=request.user)
        if problem:
            return Response({"detail": problem}, status=400)
        return Response(EotSerializer(eot).data, status=201)

    qs = _scope(ExtensionOfTime.objects.select_related(
        "document", "project", "raised_by", "baseline").prefetch_related(
        "delay_events__document"), request)
    if request.GET.get("project"):
        qs = qs.filter(project_id=request.GET["project"])
    return Response(EotSerializer(qs[:200], many=True).data)


def _get_eot(request, ref):
    eot = _scope(ExtensionOfTime.objects.select_related("document",
                                                        "project"),
                 request).filter(document__ref=ref).first()
    if eot is None:
        return None, Response({"detail": "Not found."}, status=404)
    if request.user.role not in contract.COMMERCIAL_ROLES:
        return None, Response({"detail": "A PM, QS or Director handles "
                                         "applications."}, status=403)
    return eot, None


@api_view(["POST"])
def eot_submit(request, ref):
    eot, err = _get_eot(request, ref)
    if err:
        return err
    problem = contract.submit_eot(eot, request.user,
                                  request.data.get("submitted_on"))
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(EotSerializer(eot).data)


@api_view(["POST"])
def eot_decide(request, ref):
    eot, err = _get_eot(request, ref)
    if err:
        return err
    eot, problem = contract.decide_eot(eot, request.data, request.user)
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(EotSerializer(eot).data)


@api_view(["GET"])
def entitlement(request, pk):
    project, err = _project_or_error(request, pk)
    if err:
        return err
    return Response(contract.entitlement_view(project))


@api_view(["GET"])
def outstanding_replies(request):
    site_ids = scoped_site_ids(request.user)
    rows = contract.outstanding(site_ids)
    return Response(CorrespondenceSerializer(rows[:200], many=True).data)
