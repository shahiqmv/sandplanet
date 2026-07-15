"""Projects under sites + programme milestones (DECISIONS.md R4)."""

import re
from datetime import date, datetime

from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .audit import audit
from .models import ProgrammeActivity, Project, Site, User
from .permissions import scoped_site_ids

# Creating projects (incl. new tenders), the programme and activities is a
# Director / Sr PM / Admin job. The QS does NOT create — the Director assigns
# a QS, who then edits the project's financials & contract terms.
PROJECT_CREATE_ROLES = ("ADMIN", "DIRECTOR", "PM")
PROJECT_EDIT_ROLES = ("ADMIN", "DIRECTOR", "PM", "QS")

# Contract terms + value are commercial data — shown only to those who may see
# the contract value (HO roles incl. QS, and the assigned PM).
CONTRACT_FIELDS = (
    "contract_value", "contract_type", "payment_terms", "advance_payment_pct",
    "retention_pct", "retention_release_terms", "output_gst_pct",
    "defects_liability_months",
    "liquidated_damages", "price_escalation", "performance_bond_pct",
    "advance_guarantee", "insurance_details",
)


def _can_view_value(user, project):
    if user.is_ho:
        return True
    if user.role == User.Role.PM:
        pm = project.site.current_pm()
        return pm is not None and pm.id == user.id
    return False


class ProjectSerializer(serializers.ModelSerializer):
    site_code = serializers.CharField(source="site.code", read_only=True)
    pm_name = serializers.CharField(source="pm.full_name", read_only=True,
                                    default=None)
    qs_name = serializers.CharField(source="qs.full_name", read_only=True,
                                    default=None)
    activity_count = serializers.SerializerMethodField()
    overall_progress = serializers.SerializerMethodField()
    latest_manpower = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ["id", "site", "site_code", "code", "title", "scope",
                  "boq_ref", "contract_value", "loa_date", "pm", "pm_name",
                  "qs", "qs_name",
                  "manpower_summary", "manpower_plan", "start_date",
                  "planned_completion", "actual_completion", "status",
                  "activity_count", "overall_progress", "latest_manpower",
                  # contract terms (QS)
                  "contract_type", "payment_terms", "advance_payment_pct",
                  "retention_pct", "retention_release_terms", "output_gst_pct",
                  "defects_liability_months", "liquidated_damages",
                  "price_escalation", "performance_bond_pct",
                  "advance_guarantee", "insurance_details"]
        read_only_fields = ["site", "status"]

    def get_latest_manpower(self, obj):
        """Total manpower from the project's most recent issued DPR."""
        dpr = obj.documents.filter(doc_type="DPR", is_void=False,
                                   status__in=["ISSUED", "VERIFIED"]) \
            .order_by("-doc_date").first()
        if not dpr or not dpr.current_revision:
            return None
        counts = (dpr.current_revision.payload or {}).get("manpower", {}) or {}
        try:
            return sum(int(v or 0) for v in counts.values())
        except (TypeError, ValueError):
            return None

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
            for f in CONTRACT_FIELDS:
                data.pop(f, None)
        return data


class ActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProgrammeActivity
        fields = ["id", "sort_order", "indent", "name", "duration_days",
                  "start", "finish", "is_milestone", "predecessors",
                  "progress"]


@api_view(["GET"])
def assignable_qs(request):
    """Active Quantity Surveyors — for the project QS-assignment dropdown
    (the Director assigns a QS to work on a project's financials/tender)."""
    if request.user.role not in PROJECT_EDIT_ROLES:
        return Response({"detail": "Not allowed."}, status=403)
    people = User.objects.filter(role=User.Role.QS, is_active=True) \
        .order_by("full_name").values("id", "full_name")
    return Response(list(people))


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
        if request.user.role not in PROJECT_CREATE_ROLES:
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


@api_view(["GET", "PATCH", "DELETE"])
def project_detail(request, pk):
    try:
        project = Project.objects.select_related("site").get(pk=pk)
    except Project.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    site_ids = scoped_site_ids(request.user)
    if site_ids is not None and project.site_id not in site_ids:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "DELETE":
        if request.user.role not in ("ADMIN", "DIRECTOR"):
            return Response({"detail": "Admin/Director delete projects."},
                            status=403)
        if project.documents.exists():
            return Response(
                {"detail": "This project has documents recorded against it — "
                           "it can't be deleted. Close it (set status Closed) "
                           "instead."}, status=400)
        code = project.code
        project.delete()  # cascades the programme activities
        audit("project", pk, "PROJECT_DELETED", actor=request.user,
              detail={"code": code, "site": project.site.code})
        return Response(status=204)
    if request.method == "PATCH":
        if request.user.role not in PROJECT_EDIT_ROLES:
            return Response({"detail": "Admin/Director/PM/QS edit projects."},
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


@api_view(["GET"])
def project_documents(request, pk):
    """The project workspace's Documents tab (Phase A): the project's own
    IR/MAR (+ legacy per-project DPR/TWS), and the site-wide daily
    DPR/TWS that carry rows tagged with this project."""
    try:
        project = Project.objects.select_related("site").get(pk=pk)
    except Project.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    site_ids = scoped_site_ids(request.user)
    if site_ids is not None and project.site_id not in site_ids:
        return Response({"detail": "Not found."}, status=404)
    from .models import Document

    def row(d, extra=None):
        return {"ref": d.ref, "doc_type": d.doc_type, "doc_date": d.doc_date,
                "status": "VOID" if d.is_void else d.status,
                "detail": extra or ""}

    own = [row(d) for d in Document.objects.filter(project=project)
           .order_by("-doc_date", "-id")[:100]]
    daily = []
    key = {"DPR": "work_done", "TWS": "activities"}
    for d in Document.objects.filter(
            site_id=project.site_id, doc_type__in=("DPR", "TWS"),
            project__isnull=True, is_void=False,
    ).select_related("current_revision").order_by("-doc_date", "-id")[:200]:
        rows = [r for r in (d.current_revision.payload or {})
                .get(key[d.doc_type], [])
                if (r.get("project") or "").strip() == project.code]
        if rows:
            daily.append(row(d, f"{len(rows)} row(s) for {project.code}"))
    return Response({"project_docs": own, "daily_docs": daily[:60]})


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
        if request.user.role not in PROJECT_CREATE_ROLES:
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
                is_milestone=bool(row.get("is_milestone")) or
                row.get("duration_days") == 0,
            ))
        audit("project", project.id, "PROGRAMME_IMPORTED", actor=request.user,
              detail={"count": len(created)})
        return Response({"imported": len(created)}, status=201)

    acts = list(project.activities.all())
    data = ActivitySerializer(acts, many=True).data
    # Trade/discipline = the top-level WORK SECTION each row sits under — the
    # "MEP / Civil / Finishes" grouping the owner wants on the DPR. Derived
    # from the outline (no schema change) and adaptive to how the programme is
    # structured: a single indent-0 row is treated as the overall project
    # title, so the trade level is indent 1; when several sections sit at
    # indent 0, those are the trades. Editable on the DPR either way.
    root_count = sum(1 for a in acts if a.indent == 0)
    trade_level = 1 if root_count == 1 else 0
    current_trade = ""
    for act, row in zip(acts, data):
        if act.indent == trade_level:
            current_trade = act.name
        elif act.indent < trade_level:
            current_trade = ""  # back above the trade level (the title row)
        row["trade"] = current_trade
    return Response(data)


@api_view(["PATCH", "DELETE"])
def activity_detail(request, pk):
    try:
        activity = ProgrammeActivity.objects.select_related(
            "project__site").get(pk=pk)
    except ProgrammeActivity.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in PROJECT_CREATE_ROLES:
        return Response({"detail": "Admin/Director/PM edit activities."},
                        status=403)
    if request.method == "DELETE":
        if activity.progress_updated_from_id:
            return Response({"detail": "This activity has DPR progress "
                                       "recorded against it — it cannot be "
                                       "deleted."}, status=400)
        audit("programme_activity", pk, "ACTIVITY_DELETED",
              actor=request.user, detail={"name": activity.name[:80]})
        activity.delete()
        return Response(status=204)
    serializer = ActivitySerializer(activity, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    audit("programme_activity", activity.id, "ACTIVITY_UPDATED",
          actor=request.user, detail={"fields": sorted(request.data.keys())})
    return Response(serializer.data)


@api_view(["GET"])
def dashboard_portfolio(request):
    """Senior-management portfolio (spec §7.4): every project with value,
    % duration elapsed vs programme progress, open-items count, and an
    on-track / watch / attention classification."""
    if request.user.role not in ("DIRECTOR", "ADMIN", "QS", "SIGNATORY"):
        return Response({"detail": "Director / Admin / QS / Signatory only."},
                        status=403)
    from datetime import date

    today = date.today()
    rows = []
    counts = {"ACTIVE": 0, "ON_HOLD": 0, "CLOSED": 0}
    projects = Project.objects.select_related("site", "pm") \
        .prefetch_related("activities").order_by("site__code", "code")
    serializer = ProjectSerializer(context={"request": request})
    for p in projects:
        counts[p.status] = counts.get(p.status, 0) + 1
        elapsed = None
        if p.start_date and p.planned_completion \
                and p.planned_completion > p.start_date:
            elapsed = round(100 * (today - p.start_date).days
                            / (p.planned_completion - p.start_date).days, 1)
            elapsed = max(min(elapsed, 100), 0)
        progress = serializer.get_overall_progress(p)
        open_items = p.documents.filter(is_void=False).exclude(
            status__in=("VERIFIED", "CLOSED", "COMPLETE", "APPROVED",
                        "ACKNOWLEDGED", "PAID_PO_ISSUED", "RECEIVED",
                        "LOADED", "REJECTED", "CANCELLED")).count()
        if p.status != "ACTIVE" or elapsed is None:
            health = "info"
        elif progress >= elapsed - 10:
            health = "on_track"
        elif progress >= elapsed - 25:
            health = "watch"
        else:
            health = "attention"
        rows.append({
            "project_id": p.id, "site_code": p.site.code, "code": p.code,
            "title": p.title, "status": p.status,
            "contract_value": p.contract_value, "pm_name":
            p.pm.full_name if p.pm else None,
            "start_date": p.start_date,
            "planned_completion": p.planned_completion,
            "pct_time_elapsed": elapsed, "overall_progress": progress,
            "open_items": open_items, "health": health,
        })
    return Response({"counts": counts, "projects": rows})


def _month_span(start, finish):
    """[(label, days)] month columns across the programme span."""
    import calendar
    from datetime import date as ddate

    months = []
    y, m = start.year, start.month
    while (y, m) <= (finish.year, finish.month):
        first = ddate(y, m, 1)
        last = ddate(y, m, calendar.monthrange(y, m)[1])
        days = (min(last, finish) - max(first, start)).days + 1
        months.append((first.strftime("%b %y"), days))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return months


@api_view(["GET"])
def programme_pdf(request, pk):
    """The award package (owner): the construction programme as a
    letterhead PDF — Gantt + activity table + planned-manpower histogram
    — downloaded and sent to the client upon award."""
    try:
        project = Project.objects.select_related("site").get(pk=pk)
    except Project.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    site_ids = scoped_site_ids(request.user)
    if site_ids is not None and project.site_id not in site_ids:
        return Response({"detail": "Not found."}, status=404)

    from django.http import HttpResponse
    from django.template.loader import render_to_string

    from .pdf import company_info, logo_src

    activities = list(project.activities.all())
    dated = [a for a in activities if a.start and (a.finish or a.start)]
    rows, months = [], []
    if dated:
        span_start = min(a.start for a in dated)
        span_end = max((a.finish or a.start) for a in dated)
        span = max((span_end - span_start).days + 1, 1)
        total_days = span
        months = [{"label": lab, "width": round(100 * d / total_days, 3)}
                  for lab, d in _month_span(span_start, span_end)]
        for a in activities:
            row = {"name": a.name, "indent": a.indent,
                   "is_milestone": a.is_milestone,
                   "duration": a.duration_days,
                   "start": a.start, "finish": a.finish,
                   "progress": float(a.progress), "bar": None}
            if a.start:
                end = a.finish or a.start
                offset = 100 * (a.start - span_start).days / span
                width = 100 * ((end - a.start).days + 1) / span
                row["bar"] = {"offset": round(offset, 3),
                              "width": max(round(width, 3), 0.4)}
            rows.append(row)
    # Manpower REQUIREMENT per category, PM down to unskilled (owner) —
    # the histogram is drawn from these numbers
    plan = []
    counts = [int(p.get("workers") or 0) for p in project.manpower_plan or []]
    peak = max(counts, default=0)
    total = sum(counts)
    for p in project.manpower_plan or []:
        w = int(p.get("workers") or 0)
        label = p.get("category") or p.get("month", "")
        plan.append({"label": label, "workers": w,
                     "height": round(100 * w / peak, 1) if peak else 0})

    html = render_to_string("pdf/programme.html", {
        "project": project, "site": project.site,
        "logo_src": logo_src(), "co": company_info(),
        "rows": rows, "months": months, "plan": plan, "peak": peak,
        "plan_total": total,
        "generated": date.today().strftime("%d.%m.%Y"),
    })
    try:
        from weasyprint import HTML

        from django.conf import settings

        pdf_bytes = HTML(string=html,
                         base_url=str(settings.MEDIA_ROOT)).write_pdf()
    except Exception:
        return Response({"detail": "PDF engine unavailable on this "
                                   "server."}, status=503)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="Programme-{project.site.code}-'
        f'{project.code}.pdf"')
    return response
