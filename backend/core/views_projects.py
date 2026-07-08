"""Projects under sites + programme milestones (DECISIONS.md R4)."""

import re
from datetime import datetime

from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .audit import audit
from .models import ProgrammeActivity, Project, Site, User
from .permissions import scoped_site_ids

PROJECT_ADMIN_ROLES = ("ADMIN", "DIRECTOR", "PM")


def _can_view_value(user, project):
    if user.is_ho:
        return True
    if user.role == User.Role.PM:
        pm = project.site.current_pm()
        return pm is not None and pm.id == user.id
    return False


class ProjectSerializer(serializers.ModelSerializer):
    site_code = serializers.CharField(source="site.code", read_only=True)
    activity_count = serializers.SerializerMethodField()
    overall_progress = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ["id", "site", "site_code", "code", "title", "scope",
                  "boq_ref", "contract_value", "start_date",
                  "planned_completion", "actual_completion", "status",
                  "activity_count", "overall_progress"]
        read_only_fields = ["site", "status"]

    def get_activity_count(self, obj):
        return obj.activities.count()

    def get_overall_progress(self, obj):
        """Duration-weighted mean over LEAF tasks only — summary rows and
        milestones carry no weight of their own."""
        activities = list(obj.activities.all())
        rows = []
        for i, activity in enumerate(activities):
            is_leaf = (i + 1 >= len(activities) or
                       activities[i + 1].indent <= activity.indent)
            if is_leaf and not activity.is_milestone:
                rows.append((activity.duration_days or 1, activity.progress))
        total = sum(w for w, _ in rows)
        if not total:
            return 0
        return round(sum(w * float(p) for w, p in rows) / total, 1)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request and not _can_view_value(request.user, instance):
            data.pop("contract_value", None)
        return data


class ActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProgrammeActivity
        fields = ["id", "sort_order", "indent", "name", "duration_days",
                  "start", "finish", "is_milestone", "progress"]


@api_view(["GET", "POST"])
def site_projects(request, site_id):
    try:
        site = Site.objects.get(pk=site_id)
    except Site.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    site_ids = scoped_site_ids(request.user)
    if site_ids is not None and site.id not in site_ids:
        return Response({"detail": "Not found."}, status=404)

    if request.method == "POST":
        if request.user.role not in PROJECT_ADMIN_ROLES:
            return Response({"detail": "Admin/Director/PM create projects."},
                            status=403)
        serializer = ProjectSerializer(data=request.data,
                                       context={"request": request})
        serializer.is_valid(raise_exception=True)
        project = serializer.save(site=site)
        audit("project", project.id, "PROJECT_CREATED", actor=request.user,
              detail={"site": site.code, "code": project.code})
        return Response(ProjectSerializer(project,
                                          context={"request": request}).data,
                        status=201)

    qs = site.projects.all()
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    return Response(ProjectSerializer(qs, many=True,
                                      context={"request": request}).data)


@api_view(["GET", "PATCH"])
def project_detail(request, pk):
    try:
        project = Project.objects.select_related("site").get(pk=pk)
    except Project.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    site_ids = scoped_site_ids(request.user)
    if site_ids is not None and project.site_id not in site_ids:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "PATCH":
        if request.user.role not in PROJECT_ADMIN_ROLES:
            return Response({"detail": "Admin/Director/PM edit projects."},
                            status=403)
        if "status" in request.data and \
                request.data["status"] in Project.Status.values:
            project.status = request.data["status"]
        serializer = ProjectSerializer(project, data=request.data,
                                       partial=True,
                                       context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        audit("project", project.id, "PROJECT_UPDATED", actor=request.user,
              detail={"fields": sorted(request.data.keys())})
    return Response(ProjectSerializer(project,
                                      context={"request": request}).data)


# ===== Programme =====

_DURATION = re.compile(r"(\d+)\s*day", re.I)
_DATE_FORMATS = ("%m/%d/%y", "%m/%d/%Y", "%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d")


def _parse_date(text):
    if not text:
        return None
    cleaned = re.sub(r"^[A-Za-z]{3,4}\s+", "", str(text).strip())  # "Fri 4/17/26"
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def parse_programme_paste(text):
    """Parse rows pasted from MS Project (tab-separated): optional ID,
    Task Name (leading spaces = outline level), Duration, Start, Finish."""
    rows = []
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        if parts and re.fullmatch(r"\d+", parts[0].strip()):
            parts = parts[1:]  # drop the MS Project ID column
        if not parts:
            continue
        raw_name = parts[0]
        name = raw_name.strip()
        if not name:
            continue
        indent = min((len(raw_name) - len(raw_name.lstrip())) // 2, 8)
        duration = None
        start = finish = None
        for cell in parts[1:]:
            cell = cell.strip()
            if duration is None:
                match = _DURATION.search(cell)
                if match:
                    duration = int(match.group(1))
                    continue
            parsed = _parse_date(cell)
            if parsed and start is None:
                start = parsed
            elif parsed:
                finish = parsed
        rows.append({
            "name": name, "indent": indent, "duration_days": duration,
            "start": start, "finish": finish,
            "is_milestone": duration == 0,
        })
    return rows


@api_view(["GET", "POST"])
def project_programme(request, pk):
    try:
        project = Project.objects.select_related("site").get(pk=pk)
    except Project.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    site_ids = scoped_site_ids(request.user)
    if site_ids is not None and project.site_id not in site_ids:
        return Response({"detail": "Not found."}, status=404)

    if request.method == "POST":
        if request.user.role not in PROJECT_ADMIN_ROLES:
            return Response({"detail": "Admin/Director/PM manage the "
                                       "programme."}, status=403)
        if request.data.get("paste"):
            rows = parse_programme_paste(request.data["paste"])
        else:
            rows = request.data.get("activities") or []
        if not rows:
            return Response({"detail": "Nothing to import — paste the "
                                       "programme rows or send activities."},
                            status=400)
        if request.data.get("replace", True):
            project.activities.all().delete()
        base = project.activities.count()
        created = []
        for i, row in enumerate(rows, start=1):
            created.append(ProgrammeActivity.objects.create(
                project=project, sort_order=base + i,
                indent=row.get("indent", 0), name=row["name"],
                duration_days=row.get("duration_days"),
                start=row.get("start") or None,
                finish=row.get("finish") or None,
                is_milestone=bool(row.get("is_milestone")),
            ))
        audit("project", project.id, "PROGRAMME_IMPORTED", actor=request.user,
              detail={"count": len(created)})
        return Response({"imported": len(created)}, status=201)

    return Response(ActivitySerializer(project.activities.all(),
                                       many=True).data)


@api_view(["PATCH"])
def activity_detail(request, pk):
    try:
        activity = ProgrammeActivity.objects.select_related(
            "project__site").get(pk=pk)
    except ProgrammeActivity.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in PROJECT_ADMIN_ROLES:
        return Response({"detail": "Admin/Director/PM edit activities."},
                        status=403)
    serializer = ActivitySerializer(activity, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    audit("programme_activity", activity.id, "ACTIVITY_UPDATED",
          actor=request.user, detail={"fields": sorted(request.data.keys())})
    return Response(serializer.data)
