"""HSE API — the incident register and the corrective-action list.

Site-scoped like every other document surface: a site user sees their own
site's records, Head Office sees all of them.
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import hse
from .audit import audit
from .models import (CorrectiveAction, Employee, IncidentPerson, PpeIssue,
                     Project, RiskAssessment, RiskHazard, SafetyIncident,
                     SafetyInduction, SafetyInspection, Site, ToolboxAttendee,
                     ToolboxTalk, TrainingRecord, WorkPermit)
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
        return Response({"detail": "The site team, PM, Director or HR "
                                   "record the investigation."}, status=403)
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
        return Response({"detail": "Not allowed to investigate incidents."},
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
        return Response({"detail": "Not allowed to close incidents."},
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
        return Response({"detail": "Only the owner, or the site team, can "
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
        return Response({"detail": "Not allowed to verify actions."},
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
    # An issued permit past its end time was never handed back — the single
    # thing the permit register exists to surface.
    data["permits_expired"] = hse.expired_permits(site_ids).count()
    data["permits_open"] = WorkPermit.objects.filter(
        document__status="ISSUED",
        **({} if site_ids is None
           else {"document__site_id__in": site_ids})).count()
    data["actions_open"] = CorrectiveAction.objects.filter(
        status__in=["OPEN", "IN_PROGRESS", "DONE"],
        **({} if site_ids is None else {"site_id__in": site_ids})).count()
    return Response(data)


# ---- people records ------------------------------------------------------

class ToolboxAttendeeSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    emp_no = serializers.CharField(source="employee.emp_no", read_only=True,
                                   default=None)

    class Meta:
        model = ToolboxAttendee
        fields = ["id", "employee", "emp_no", "name", "display_name",
                  "employer"]

    def get_display_name(self, obj):
        return obj.display_name()


class ToolboxTalkSerializer(serializers.ModelSerializer):
    ref = serializers.CharField(source="document.ref", read_only=True)
    site_code = serializers.CharField(source="document.site.code",
                                      read_only=True)
    delivered_by_name = serializers.CharField(source="delivered_by.full_name",
                                              read_only=True)
    attendees = ToolboxAttendeeSerializer(many=True, read_only=True)
    attendee_count = serializers.SerializerMethodField()

    class Meta:
        model = ToolboxTalk
        fields = ["id", "ref", "site_code", "topic", "delivered_at",
                  "delivered_by_name", "presenter_name", "duration_min",
                  "location", "key_points", "attendees", "attendee_count"]

    def get_attendee_count(self, obj):
        return obj.attendees.count()


class InductionSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name",
                                          read_only=True)
    emp_no = serializers.CharField(source="employee.emp_no", read_only=True)
    site_code = serializers.CharField(source="site.code", read_only=True)
    inducted_by_name = serializers.CharField(source="inducted_by.full_name",
                                             read_only=True)

    class Meta:
        model = SafetyInduction
        fields = ["id", "employee", "employee_name", "emp_no", "site_code",
                  "inducted_on", "inducted_by_name", "topics", "valid_until",
                  "notes"]


class TrainingSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name",
                                          read_only=True)
    emp_no = serializers.CharField(source="employee.emp_no", read_only=True)
    category_display = serializers.CharField(source="get_category_display",
                                             read_only=True)
    days_to_expiry = serializers.SerializerMethodField()

    class Meta:
        model = TrainingRecord
        fields = ["id", "employee", "employee_name", "emp_no", "category",
                  "category_display", "title", "issuer", "reference",
                  "issued_on", "expires_on", "notes", "days_to_expiry"]

    def get_days_to_expiry(self, obj):
        return obj.days_to_expiry()


class PpeSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name",
                                          read_only=True)
    emp_no = serializers.CharField(source="employee.emp_no", read_only=True)
    site_code = serializers.CharField(source="site.code", read_only=True)
    issued_by_name = serializers.CharField(source="issued_by.full_name",
                                           read_only=True)

    class Meta:
        model = PpeIssue
        fields = ["id", "employee", "employee_name", "emp_no", "site_code",
                  "item", "qty", "issued_on", "issued_by_name", "replacement",
                  "notes"]


def _site_or_error(request, site_id):
    try:
        site = Site.objects.get(pk=site_id)
    except (Site.DoesNotExist, ValueError, TypeError):
        return None, Response({"detail": "Choose the site."}, status=400)
    allowed = scoped_site_ids(request.user)
    if allowed is not None and site.id not in allowed:
        return None, Response({"detail": "Not your site."}, status=403)
    return site, None


@api_view(["GET", "POST"])
def toolbox_talks(request):
    if request.method == "POST":
        if request.user.role not in hse.RECORDER_ROLES:
            return Response({"detail": "Not allowed."}, status=403)
        site, err = _site_or_error(request, request.data.get("site_id"))
        if err:
            return err
        talk, problem = hse.create_toolbox_talk(
            site=site, data=request.data, user=request.user)
        if problem:
            return Response({"detail": problem}, status=400)
        return Response(ToolboxTalkSerializer(talk).data, status=201)

    qs = ToolboxTalk.objects.select_related(
        "document", "document__site", "delivered_by").prefetch_related(
        "attendees", "attendees__employee")
    allowed = scoped_site_ids(request.user)
    if allowed is not None:
        qs = qs.filter(document__site_id__in=allowed)
    if request.GET.get("site"):
        qs = qs.filter(document__site_id=request.GET["site"])
    if request.GET.get("from"):
        qs = qs.filter(delivered_at__date__gte=request.GET["from"])
    return Response(ToolboxTalkSerializer(qs[:200], many=True).data)


@api_view(["GET"])
def present_today(request):
    """Who was marked present at a site on a day — the attendance register is
    already the list of men who were there for the talk."""
    site, err = _site_or_error(request, request.GET.get("site"))
    if err:
        return err
    day = request.GET.get("day") or str(timezone.localdate())
    people = hse.workers_present(site, day)
    return Response([{"employee_id": e.id, "emp_no": e.emp_no,
                      "full_name": e.full_name,
                      "trade": getattr(e.job_category, "name", "")}
                     for e in people])


@api_view(["GET", "POST"])
def inductions(request):
    if request.method == "POST":
        if request.user.role not in hse.RECORDER_ROLES:
            return Response({"detail": "Not allowed."}, status=403)
        site, err = _site_or_error(request, request.data.get("site_id"))
        if err:
            return err
        employee = Employee.objects.filter(
            pk=request.data.get("employee_id")).first()
        if employee is None:
            return Response({"detail": "Unknown worker."}, status=400)
        induction, problem = hse.record_induction(
            employee=employee, site=site, data=request.data,
            user=request.user)
        if problem:
            return Response({"detail": problem}, status=400)
        return Response(InductionSerializer(induction).data, status=201)

    qs = SafetyInduction.objects.select_related("employee", "site",
                                                "inducted_by")
    allowed = scoped_site_ids(request.user)
    if allowed is not None:
        qs = qs.filter(site_id__in=allowed)
    if request.GET.get("site"):
        qs = qs.filter(site_id=request.GET["site"])
    if request.GET.get("employee"):
        qs = qs.filter(employee_id=request.GET["employee"])
    return Response(InductionSerializer(qs[:400], many=True).data)


@api_view(["GET", "POST"])
def training(request):
    if request.method == "POST":
        if request.user.role not in hse.RECORDER_ROLES:
            return Response({"detail": "Not allowed."}, status=403)
        employee = Employee.objects.filter(
            pk=request.data.get("employee_id")).first()
        if employee is None:
            return Response({"detail": "Unknown worker."}, status=400)
        record, problem = hse.record_training(
            employee=employee, data=request.data, user=request.user)
        if problem:
            return Response({"detail": problem}, status=400)
        return Response(TrainingSerializer(record).data, status=201)

    qs = TrainingRecord.objects.select_related("employee")
    allowed = scoped_site_ids(request.user)
    if allowed is not None:
        qs = qs.filter(employee__site_allocations__site_id__in=allowed,
                       employee__site_allocations__to_date__isnull=True)
    if request.GET.get("employee"):
        qs = qs.filter(employee_id=request.GET["employee"])
    if request.GET.get("expiring"):
        horizon = timezone.localdate() + timedelta(
            days=int(request.GET["expiring"]))
        qs = qs.filter(expires_on__isnull=False, expires_on__lte=horizon)
    return Response(TrainingSerializer(qs.distinct()[:400], many=True).data)


@api_view(["GET", "POST"])
def ppe(request):
    if request.method == "POST":
        if request.user.role not in hse.RECORDER_ROLES:
            return Response({"detail": "Not allowed."}, status=403)
        site, err = _site_or_error(request, request.data.get("site_id"))
        if err:
            return err
        employee = Employee.objects.filter(
            pk=request.data.get("employee_id")).first()
        if employee is None:
            return Response({"detail": "Unknown worker."}, status=400)
        issue, problem = hse.issue_ppe(employee=employee, site=site,
                                       data=request.data, user=request.user)
        if problem:
            return Response({"detail": problem}, status=400)
        return Response(PpeSerializer(issue).data, status=201)

    qs = PpeIssue.objects.select_related("employee", "site", "issued_by")
    allowed = scoped_site_ids(request.user)
    if allowed is not None:
        qs = qs.filter(site_id__in=allowed)
    if request.GET.get("site"):
        qs = qs.filter(site_id=request.GET["site"])
    if request.GET.get("employee"):
        qs = qs.filter(employee_id=request.GET["employee"])
    return Response(PpeSerializer(qs[:400], many=True).data)


# ---- work records: permits, risk assessments, inspections ---------------

class PermitSerializer(serializers.ModelSerializer):
    ref = serializers.CharField(source="document.ref", read_only=True)
    status = serializers.CharField(source="document.status", read_only=True)
    site_code = serializers.CharField(source="document.site.code",
                                      read_only=True)
    kind_display = serializers.CharField(source="get_kind_display",
                                         read_only=True)
    issued_by_name = serializers.CharField(source="issued_by.full_name",
                                           read_only=True)
    is_expired = serializers.SerializerMethodField()

    class Meta:
        model = WorkPermit
        fields = ["id", "ref", "status", "site_code", "kind", "kind_display",
                  "location", "description", "valid_from", "valid_to",
                  "precautions", "issued_by_name", "accepted_by_name",
                  "closed_at", "closing_note", "is_expired"]

    def get_is_expired(self, obj):
        return obj.is_expired()


class HazardSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskHazard
        fields = ["id", "hazard", "who_at_risk", "existing_controls",
                  "likelihood", "severity", "rating", "band",
                  "further_controls", "residual_likelihood",
                  "residual_severity", "residual_rating", "residual_band"]


class RiskAssessmentSerializer(serializers.ModelSerializer):
    ref = serializers.CharField(source="document.ref", read_only=True)
    status = serializers.CharField(source="document.status", read_only=True)
    site_code = serializers.CharField(source="document.site.code",
                                      read_only=True)
    assessed_by_name = serializers.CharField(source="assessed_by.full_name",
                                             read_only=True)
    hazards = HazardSerializer(many=True, read_only=True)
    supersedes_ref = serializers.CharField(source="supersedes.document.ref",
                                           read_only=True, default=None)
    highest_band = serializers.SerializerMethodField()

    class Meta:
        model = RiskAssessment
        fields = ["id", "ref", "status", "site_code", "activity",
                  "assessed_on", "assessed_by_name", "assessor_name",
                  "review_on", "notes", "hazards", "supersedes_ref",
                  "highest_band"]

    def get_highest_band(self, obj):
        best = 0
        for h in obj.hazards.all():
            best = max(best, h.residual_rating or h.rating)
        return RiskHazard.band_for(best) if best else None


class InspectionSerializer(serializers.ModelSerializer):
    ref = serializers.CharField(source="document.ref", read_only=True)
    site_code = serializers.CharField(source="document.site.code",
                                      read_only=True)
    inspected_by_name = serializers.CharField(source="inspected_by.full_name",
                                              read_only=True)
    counts = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()

    class Meta:
        model = SafetyInspection
        fields = ["id", "ref", "site_code", "area", "inspected_on",
                  "inspected_by_name", "inspector_name", "checklist",
                  "summary", "counts", "actions"]

    def get_counts(self, obj):
        return obj.counts()

    def get_actions(self, obj):
        return ActionSerializer(obj.document.corrective_actions.all(),
                                many=True).data


@api_view(["GET", "POST"])
def permits(request):
    if request.method == "POST":
        if request.user.role not in hse.RECORDER_ROLES:
            return Response({"detail": "Not allowed."}, status=403)
        site, err = _site_or_error(request, request.data.get("site_id"))
        if err:
            return err
        permit, problem = hse.issue_permit(site=site, data=request.data,
                                           user=request.user)
        if problem:
            return Response({"detail": problem}, status=400)
        return Response(PermitSerializer(permit).data, status=201)

    qs = WorkPermit.objects.select_related("document", "document__site",
                                           "issued_by")
    allowed = scoped_site_ids(request.user)
    if allowed is not None:
        qs = qs.filter(document__site_id__in=allowed)
    if request.GET.get("site"):
        qs = qs.filter(document__site_id=request.GET["site"])
    if request.GET.get("status") == "open":
        qs = qs.filter(document__status="ISSUED")
    if request.GET.get("expired"):
        qs = qs.filter(document__status="ISSUED",
                       valid_to__lt=timezone.now())
    return Response(PermitSerializer(qs[:300], many=True).data)


@api_view(["POST"])
def permit_close(request, ref):
    qs = WorkPermit.objects.select_related("document")
    allowed = scoped_site_ids(request.user)
    if allowed is not None:
        qs = qs.filter(document__site_id__in=allowed)
    permit = qs.filter(document__ref=ref).first()
    if permit is None:
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in hse.RECORDER_ROLES:
        return Response({"detail": "Not allowed."}, status=403)
    problem = hse.close_permit(permit, request.user,
                               request.data.get("note", ""))
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(PermitSerializer(permit).data)


@api_view(["GET", "POST"])
def risk_assessments(request):
    if request.method == "POST":
        if request.user.role not in hse.RECORDER_ROLES:
            return Response({"detail": "Not allowed."}, status=403)
        site, err = _site_or_error(request, request.data.get("site_id"))
        if err:
            return err
        assessment, problem = hse.create_risk_assessment(
            site=site, data=request.data, user=request.user)
        if problem:
            return Response({"detail": problem}, status=400)
        return Response(RiskAssessmentSerializer(assessment).data, status=201)

    qs = RiskAssessment.objects.select_related(
        "document", "document__site", "assessed_by",
        "supersedes__document").prefetch_related("hazards")
    allowed = scoped_site_ids(request.user)
    if allowed is not None:
        qs = qs.filter(document__site_id__in=allowed)
    if request.GET.get("site"):
        qs = qs.filter(document__site_id=request.GET["site"])
    if request.GET.get("status") == "current":
        qs = qs.filter(document__status="RECORDED")
    return Response(RiskAssessmentSerializer(qs[:200], many=True).data)


@api_view(["GET", "POST"])
def inspections(request):
    if request.method == "POST":
        if request.user.role not in hse.RECORDER_ROLES:
            return Response({"detail": "Not allowed."}, status=403)
        site, err = _site_or_error(request, request.data.get("site_id"))
        if err:
            return err
        inspection, problem = hse.create_inspection(
            site=site, data=request.data, user=request.user)
        if problem:
            return Response({"detail": problem}, status=400)
        return Response(InspectionSerializer(inspection).data, status=201)

    qs = SafetyInspection.objects.select_related("document",
                                                 "document__site",
                                                 "inspected_by")
    allowed = scoped_site_ids(request.user)
    if allowed is not None:
        qs = qs.filter(document__site_id__in=allowed)
    if request.GET.get("site"):
        qs = qs.filter(document__site_id=request.GET["site"])
    return Response(InspectionSerializer(qs[:200], many=True).data)


@api_view(["POST"])
def inspection_actions(request, ref):
    """A finding becomes a corrective action on the same register everything
    else uses — one open-actions list, whatever raised the item."""
    qs = SafetyInspection.objects.select_related("document")
    allowed = scoped_site_ids(request.user)
    if allowed is not None:
        qs = qs.filter(document__site_id__in=allowed)
    inspection = qs.filter(document__ref=ref).first()
    if inspection is None:
        return Response({"detail": "Not found."}, status=404)
    action, problem = hse.raise_action(
        source_document=inspection.document, data=request.data,
        user=request.user)
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(ActionSerializer(action).data, status=201)
