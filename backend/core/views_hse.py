"""HSE API — the incident register and the corrective-action list.

Site-scoped like every other document surface: a site user sees their own
site's records, Head Office sees all of them.
"""
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import hse
from .audit import audit
from .models import (CorrectiveAction, IncidentPerson, Project,
                     SafetyIncident, Site)
from .permissions import scoped_site_ids


class IncidentPersonSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    emp_no = serializers.CharField(source="employee.emp_no", read_only=True,
                                   default=None)

    class Meta:
        model = IncidentPerson
        fields = ["id", "employee", "emp_no", "name", "display_name",
                  "employer", "involvement", "injury", "body_part",
                  "treatment", "days_lost", "returned_to_work_on"]

    def get_display_name(self, obj):
        return obj.display_name()


class ActionSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.full_name",
                                       read_only=True)
    raised_by_name = serializers.CharField(source="raised_by.full_name",
                                           read_only=True)
    verified_by_name = serializers.CharField(source="verified_by.full_name",
                                             read_only=True, default=None)
    source_ref = serializers.CharField(source="source_document.ref",
                                       read_only=True)
    site_code = serializers.CharField(source="site.code", read_only=True)
    days_overdue = serializers.SerializerMethodField()

    class Meta:
        model = CorrectiveAction
        fields = ["id", "source_ref", "site_code", "description",
                  "is_preventive", "owner", "owner_name", "due_date",
                  "priority", "status", "raised_by_name", "raised_at",
                  "completed_at", "completion_note", "verified_at",
                  "verified_by_name", "days_overdue"]

    def get_days_overdue(self, obj):
        return obj.days_overdue()


class IncidentSerializer(serializers.ModelSerializer):
    ref = serializers.CharField(source="document.ref", read_only=True)
    status = serializers.CharField(source="document.status", read_only=True)
    site_code = serializers.CharField(source="document.site.code",
                                      read_only=True)
    site_id = serializers.IntegerField(source="document.site_id",
                                       read_only=True)
    project_code = serializers.CharField(source="document.project.code",
                                         read_only=True, default=None)
    kind_display = serializers.CharField(source="get_kind_display",
                                         read_only=True)
    reported_by_name = serializers.CharField(source="reported_by.full_name",
                                             read_only=True)
    investigated_by_name = serializers.CharField(
        source="investigated_by.full_name", read_only=True, default=None)
    people = IncidentPersonSerializer(many=True, read_only=True)
    actions = serializers.SerializerMethodField()
    open_actions = serializers.SerializerMethodField()

    class Meta:
        model = SafetyIncident
        fields = ["id", "ref", "status", "site_code", "site_id",
                  "project_code", "kind", "kind_display", "severity",
                  "occurred_at", "location", "description",
                  "immediate_action", "work_stopped", "is_reportable",
                  "reported_to_authority_on", "authority_reference",
                  "reported_by_name", "reported_at", "investigated_by_name",
                  "investigation_started_at", "root_cause",
                  "contributing_factors", "lessons", "closed_at",
                  "people", "actions", "open_actions"]

    def get_actions(self, obj):
        return ActionSerializer(obj.document.corrective_actions.all(),
                                many=True).data

    def get_open_actions(self, obj):
        return hse.open_actions(obj).count()


def _scoped_incidents(request):
    qs = SafetyIncident.objects.select_related(
        "document", "document__site", "document__project", "reported_by",
        "investigated_by").prefetch_related("people", "people__employee")
    site_ids = scoped_site_ids(request.user)
    if site_ids is not None:
        qs = qs.filter(document__site_id__in=site_ids)
    return qs


def _get_incident(request, ref):
    inc = _scoped_incidents(request).filter(document__ref=ref).first()
    if inc is None:
        return None, Response({"detail": "Not found."}, status=404)
    return inc, None


@api_view(["GET", "POST"])
def incidents(request):
    if request.method == "POST":
        if request.user.role not in hse.REPORTER_ROLES:
            return Response({"detail": "Not allowed to report incidents."},
                            status=403)
        try:
            site = Site.objects.get(pk=request.data.get("site_id"))
        except (Site.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "Choose the site."}, status=400)
        site_ids = scoped_site_ids(request.user)
        if site_ids is not None and site.id not in site_ids:
            return Response({"detail": "Not your site."}, status=403)
        project = None
        if request.data.get("project_id"):
            project = Project.objects.filter(
                pk=request.data["project_id"], site=site).first()
        incident, err = hse.create_incident(
            site=site, data=request.data, user=request.user, project=project)
        if err:
            return Response({"detail": err}, status=400)
        return Response(IncidentSerializer(incident).data, status=201)

    qs = _scoped_incidents(request)
    if request.GET.get("site"):
        qs = qs.filter(document__site_id=request.GET["site"])
    if request.GET.get("status") == "open":
        qs = qs.exclude(document__status="CLOSED")
    elif request.GET.get("status"):
        qs = qs.filter(document__status=request.GET["status"])
    if request.GET.get("kind"):
        qs = qs.filter(kind=request.GET["kind"])
    if request.GET.get("from"):
        qs = qs.filter(occurred_at__date__gte=request.GET["from"])
    if request.GET.get("to"):
        qs = qs.filter(occurred_at__date__lte=request.GET["to"])
    return Response(IncidentSerializer(qs[:300], many=True).data)


@api_view(["GET", "PATCH"])
def incident_detail(request, ref):
    incident, err = _get_incident(request, ref)
    if err:
        return err
    if request.method == "GET":
        return Response(IncidentSerializer(incident).data)

    if request.user.role not in hse.INVESTIGATOR_ROLES:
        return Response({"detail": "PM / Director / HR record the "
                                   "investigation."}, status=403)
    if incident.document.status == "CLOSED":
        return Response({"detail": "This incident is closed."}, status=400)
    editable = ["severity", "location", "immediate_action", "root_cause",
                "contributing_factors", "lessons", "is_reportable",
                "reported_to_authority_on", "authority_reference",
                "work_stopped"]
    changed = []
    for field in editable:
        if field in request.data:
            setattr(incident, field, request.data[field])
            changed.append(field)
    if changed:
        incident.save(update_fields=changed)
        audit("document", incident.document_id, "INCIDENT_UPDATED",
              actor=request.user, detail={"fields": sorted(changed)})
    return Response(IncidentSerializer(incident).data)


@api_view(["POST"])
def incident_investigate(request, ref):
    incident, err = _get_incident(request, ref)
    if err:
        return err
    if request.user.role not in hse.INVESTIGATOR_ROLES:
        return Response({"detail": "PM / Director / HR investigate."},
                        status=403)
    problem = hse.start_investigation(incident, request.user)
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(IncidentSerializer(incident).data)


@api_view(["POST"])
def incident_close(request, ref):
    incident, err = _get_incident(request, ref)
    if err:
        return err
    if request.user.role not in hse.INVESTIGATOR_ROLES:
        return Response({"detail": "PM / Director / HR close incidents."},
                        status=403)
    problem = hse.close_incident(incident, request.user)
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(IncidentSerializer(incident).data)


@api_view(["POST"])
def incident_people(request, ref):
    incident, err = _get_incident(request, ref)
    if err:
        return err
    if incident.document.status == "CLOSED":
        return Response({"detail": "This incident is closed."}, status=400)
    person = hse.add_person(incident, request.data)
    audit("document", incident.document_id, "INCIDENT_PERSON_ADDED",
          actor=request.user, detail={"who": person.display_name()})
    return Response(IncidentSerializer(incident).data, status=201)


@api_view(["POST"])
def incident_actions(request, ref):
    incident, err = _get_incident(request, ref)
    if err:
        return err
    action, problem = hse.raise_action(
        source_document=incident.document, data=request.data,
        user=request.user)
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(ActionSerializer(action).data, status=201)


@api_view(["GET"])
def actions(request):
    """The company's open-actions list — one list, whatever raised them."""
    qs = CorrectiveAction.objects.select_related(
        "owner", "site", "source_document", "raised_by", "verified_by")
    site_ids = scoped_site_ids(request.user)
    if site_ids is not None:
        qs = qs.filter(site_id__in=site_ids)
    if request.GET.get("mine"):
        qs = qs.filter(owner=request.user)
    if request.GET.get("status") == "open":
        qs = qs.filter(status__in=["OPEN", "IN_PROGRESS", "DONE"])
    elif request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("overdue"):
        qs = qs.filter(status__in=["OPEN", "IN_PROGRESS", "DONE"],
                       due_date__lt=timezone.localdate())
    return Response(ActionSerializer(qs[:400], many=True).data)


@api_view(["POST"])
def action_complete(request, pk):
    action = _scoped_action(request, pk)
    if action is None:
        return Response({"detail": "Not found."}, status=404)
    if action.owner_id != request.user.id \
            and request.user.role not in hse.INVESTIGATOR_ROLES:
        return Response({"detail": "Only the owner (or a PM/Director) can "
                                   "complete this action."}, status=403)
    problem = hse.complete_action(action, request.user,
                                  request.data.get("note", ""))
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(ActionSerializer(action).data)


@api_view(["POST"])
def action_verify(request, pk):
    action = _scoped_action(request, pk)
    if action is None:
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in hse.INVESTIGATOR_ROLES:
        return Response({"detail": "PM / Director / HR verify actions."},
                        status=403)
    problem = hse.verify_action(action, request.user)
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(ActionSerializer(action).data)


def _scoped_action(request, pk):
    qs = CorrectiveAction.objects.select_related("source_document", "site")
    site_ids = scoped_site_ids(request.user)
    if site_ids is not None:
        qs = qs.filter(site_id__in=site_ids)
    return qs.filter(pk=pk).first()


@api_view(["GET"])
def stats(request):
    site_ids = scoped_site_ids(request.user)
    if request.GET.get("site"):
        want = int(request.GET["site"])
        site_ids = [want] if site_ids is None else [s for s in site_ids
                                                    if s == want]
    data = hse.statistics(site_ids, request.GET.get("from"),
                          request.GET.get("to"))
    overdue = hse.overdue_actions(site_ids)
    data["actions_overdue"] = overdue.count()
    data["actions_open"] = CorrectiveAction.objects.filter(
        status__in=["OPEN", "IN_PROGRESS", "DONE"],
        **({} if site_ids is None else {"site_id__in": site_ids})).count()
    return Response(data)
