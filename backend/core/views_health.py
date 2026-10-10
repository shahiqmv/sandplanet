"""Worker health log API (SOP-HR-04). Site-scoped like every other site
surface: a site sees its own men, head office sees every site."""
from datetime import date, datetime

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from . import health
from .audit import audit
from .models import (Employee, HealthCase, HealthEvent, HealthFile, Site,
                     SiteMedicalPlan, User)
from .permissions import scoped_site_ids

MAX_FILE_BYTES = 15 * 1024 * 1024
PROFILE_FIELDS = ("blood_group", "medical_conditions", "allergies",
                  "medication")


def _site_ok(request, site_id):
    ids = scoped_site_ids(request.user)
    return ids is None or site_id in ids


def _scoped_cases(request):
    qs = HealthCase.objects.select_related("employee", "site", "reported_by",
                                           "closed_by")
    ids = scoped_site_ids(request.user)
    return qs if ids is None else qs.filter(site_id__in=ids)


def _get_case(request, pk):
    c = _scoped_cases(request).filter(pk=pk).first()
    if c is None:
        return None, Response({"detail": "Not found."}, status=404)
    return c, None


def _recorder(request, site_id):
    if not health.can_record(request.user):
        return Response({"detail": "The site team, PM, HR, the Director or "
                                   "Admin record health."}, status=403)
    if not _site_ok(request, site_id):
        return Response({"detail": "Not your site."}, status=403)
    return None


def _row(c, kinds=None):
    level, text = health.due(c, kinds)
    kinds = kinds if kinds is not None else set(
        c.events.values_list("kind", flat=True))
    return {
        "id": c.id, "ref": c.ref, "employee_id": c.employee_id,
        "emp_no": c.employee.emp_no, "full_name": c.employee.full_name,
        "nationality": c.employee.nationality,
        "photo_url": c.employee.photo.url if getattr(c.employee, "photo",
                                                      None) else None,
        "site_id": c.site_id, "site_code": c.site.code,
        "reported_on": c.reported_on, "started_on": c.started_on,
        "reported_by": c.reported_by.full_name if c.reported_by_id else "",
        "complaint": c.complaint, "complaint_label": c.get_complaint_display(),
        "symptoms": c.symptoms, "temperature": c.temperature,
        "red_flag": c.red_flag, "source": c.source,
        "incident_ref": c.incident.document.ref if c.incident_id else None,
        "status": c.status, "fit_on": c.fit_on,
        "light_duties": c.light_duties,
        "closed_at": c.closed_at,
        "attended": bool(kinds & HealthEvent.ATTENDED),
        "referred": bool(kinds & {"DOCTOR", "MALE", "EVACUATED",
                                  "ADMITTED"}),
        "days_sick": health.days_sick(c),
        "earlier_same": health.earlier_same(c),
        "repeat_cases": health.cases_in_window(c.employee_id, c.reported_on),
        "is_repeat": health.is_repeat(c.employee_id, c.reported_on),
        "due_level": level, "due": text,
    }


def _event(e):
    return {"id": e.id, "kind": e.kind, "label": e.get_kind_display(),
            "at": e.at, "detail": e.detail, "facility": e.facility,
            "escort": e.escort, "by": e.by.full_name if e.by_id else ""}


def _file(f):
    return {"id": f.id, "url": f.file.url if f.file else None,
            "file_name": f.file_name, "label": f.label,
            "by": f.uploaded_by.full_name if f.uploaded_by_id else "",
            "at": f.created_at}


def _detail(request, c):
    events = list(c.events.select_related("by"))
    d = _row(c, {e.kind for e in events})
    d["events"] = [_event(e) for e in events]
    d["files"] = [_file(f) for f in c.files.select_related("uploaded_by")]
    d["needs_clearance"] = health.needs_clearance(c)
    d["can_record"] = health.can_record(request.user) and _site_ok(
        request, c.site_id)
    d["history"] = [
        {"id": x.id, "ref": x.ref, "reported_on": x.reported_on,
         "complaint_label": x.get_complaint_display(), "status": x.status,
         "site_code": x.site.code}
        for x in HealthCase.objects.filter(employee_id=c.employee_id)
        .exclude(pk=c.pk).select_related("site")[:12]]
    if health.sees_profile(request.user, c.employee):
        d["profile"] = {k: getattr(c.employee, k) for k in PROFILE_FIELDS}
        d["profile"]["emergency_contact"] = c.employee.emergency_contact
    return d


@api_view(["GET"])
def summary(request):
    ids = scoped_site_ids(request.user)
    if request.GET.get("site"):
        try:
            sid = int(request.GET["site"])
        except ValueError:
            return Response({"detail": "Bad site."}, status=400)
        if not _site_ok(request, sid):
            return Response({"detail": "Not your site."}, status=403)
        ids = [sid]
    return Response(health.summary(ids))


@api_view(["GET", "POST"])
def cases(request):
    if request.method == "POST":
        try:
            site = Site.objects.get(pk=request.data.get("site_id"))
            employee = Employee.objects.get(pk=request.data.get("employee_id"))
        except (Site.DoesNotExist, Employee.DoesNotExist, ValueError,
                TypeError):
            return Response({"detail": "Choose the site and the worker."},
                            status=400)
        err = _recorder(request, site.id)
        if err:
            return err
        complaint = request.data.get("complaint") or "UNKNOWN"
        if complaint not in HealthCase.Complaint.values:
            return Response({"detail": "Unknown complaint."}, status=400)
        temp = request.data.get("temperature")
        try:
            temp = float(temp) if temp not in (None, "") else None
        except (TypeError, ValueError):
            return Response({"detail": "Temperature must be a number."},
                            status=400)
        reported_on = parse_date(str(request.data.get("reported_on") or "")) \
            or timezone.localdate()
        if reported_on > timezone.localdate():
            return Response({"detail": "A report cannot be dated in the "
                                       "future."}, status=400)
        case, created = health.open_case(
            employee=employee, site=site, user=request.user,
            reported_on=reported_on, complaint=complaint,
            symptoms=request.data.get("symptoms") or "",
            started_on=parse_date(str(request.data.get("started_on") or "")),
            temperature=temp, red_flag=bool(request.data.get("red_flag")),
            source="REPORT")
        d = _detail(request, case)
        d["created"] = created
        return Response(d, status=201 if created else 200)

    qs = _scoped_cases(request)
    g = request.GET
    if g.get("site"):
        qs = qs.filter(site_id=g["site"])
    if g.get("status") == "open":
        qs = qs.filter(status="OPEN")
    elif g.get("status") == "closed":
        qs = qs.filter(status="CLOSED")
    if g.get("employee"):
        qs = qs.filter(employee_id=g["employee"])
    if g.get("complaint"):
        qs = qs.filter(complaint=g["complaint"])
    if g.get("from"):
        qs = qs.filter(reported_on__gte=g["from"])
    if g.get("to"):
        qs = qs.filter(reported_on__lte=g["to"])
    if g.get("q"):
        from django.db.models import Q
        qs = qs.filter(Q(employee__full_name__icontains=g["q"])
                       | Q(employee__emp_no__icontains=g["q"])
                       | Q(ref__icontains=g["q"]))
    rows = list(qs.prefetch_related("events")[:400])
    out = [_row(c, {e.kind for e in c.events.all()}) for c in rows]
    if g.get("attend"):
        out = [r for r in out if not r["attended"]]
    return Response(out)


@api_view(["GET", "PATCH"])
def case_detail(request, pk):
    c, err = _get_case(request, pk)
    if err:
        return err
    if request.method == "GET":
        return Response(_detail(request, c))
    err = _recorder(request, c.site_id)
    if err:
        return err
    if c.status == "CLOSED":
        return Response({"detail": "This case is closed."}, status=400)
    changed = []
    if "complaint" in request.data:
        if request.data["complaint"] not in HealthCase.Complaint.values:
            return Response({"detail": "Unknown complaint."}, status=400)
        c.complaint = request.data["complaint"]
        changed.append("complaint")
    for f in ("symptoms",):
        if f in request.data:
            setattr(c, f, (request.data[f] or "").strip())
            changed.append(f)
    if "started_on" in request.data:
        c.started_on = parse_date(str(request.data["started_on"] or ""))
        changed.append("started_on")
    if "temperature" in request.data:
        t = request.data["temperature"]
        try:
            c.temperature = float(t) if t not in (None, "") else None
        except (TypeError, ValueError):
            return Response({"detail": "Temperature must be a number."},
                            status=400)
        changed.append("temperature")
    if "red_flag" in request.data:
        c.red_flag = bool(request.data["red_flag"])
        changed.append("red_flag")
    if changed:
        c.save(update_fields=changed)
        audit("health", c.id, "HEALTH_CASE_UPDATED", actor=request.user,
              detail={"ref": c.ref, "fields": sorted(changed)})
        if "complaint" in changed or "red_flag" in changed:
            health._check_cluster(c)
            if c.red_flag and "red_flag" in changed:
                health._notify_red_flag(c, request.user)
    return Response(_detail(request, c))


@api_view(["POST"])
def case_events(request, pk):
    c, err = _get_case(request, pk)
    if err:
        return err
    err = _recorder(request, c.site_id)
    if err:
        return err
    at = None
    if request.data.get("at"):
        at = parse_datetime(str(request.data["at"]))
        if at is None:
            d = parse_date(str(request.data["at"]))
            at = datetime.combine(d, datetime.min.time()) if d else None
        if at is not None and timezone.is_naive(at):
            at = timezone.make_aware(at)
    fit_on = parse_date(str(request.data.get("fit_on") or "")) or None
    ev, problem = health.add_event(
        c, kind=request.data.get("kind") or "", user=request.user, at=at,
        detail=request.data.get("detail") or "",
        facility=request.data.get("facility") or "",
        escort=request.data.get("escort") or "", fit_on=fit_on,
        light_duties=bool(request.data.get("light_duties")))
    if problem:
        return Response({"detail": problem}, status=400)
    c.refresh_from_db()
    return Response(_detail(request, c), status=201)


@api_view(["POST"])
def case_close(request, pk):
    c, err = _get_case(request, pk)
    if err:
        return err
    err = _recorder(request, c.site_id)
    if err:
        return err
    problem = health.close_case(c, request.user,
                                note=request.data.get("note") or "")
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(_detail(request, c))


@api_view(["POST"])
def case_reopen(request, pk):
    c, err = _get_case(request, pk)
    if err:
        return err
    err = _recorder(request, c.site_id)
    if err:
        return err
    problem = health.reopen_case(c, request.user,
                                 reason=request.data.get("reason") or "")
    if problem:
        return Response({"detail": problem}, status=400)
    return Response(_detail(request, c))


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def case_files(request, pk):
    c, err = _get_case(request, pk)
    if err:
        return err
    err = _recorder(request, c.site_id)
    if err:
        return err
    uploads = request.FILES.getlist("files") or (
        [request.FILES["file"]] if "file" in request.FILES else [])
    if not uploads:
        return Response({"detail": "Choose a file."}, status=400)
    for up in uploads:
        if up.size > MAX_FILE_BYTES:
            return Response({"detail": f"{up.name} is over 15 MB."},
                            status=400)
        HealthFile.objects.create(
            case=c, file=up, file_name=up.name[:200],
            label=(request.data.get("label") or "")[:120],
            uploaded_by=request.user)
    audit("health", c.id, "HEALTH_FILE_ADDED", actor=request.user,
          detail={"ref": c.ref, "files": len(uploads)})
    # a doctor's paper on file is a step on the ladder too
    if not c.events.filter(kind="REPORT").exists():
        HealthEvent.objects.create(
            case=c, kind="REPORT", at=timezone.now(),
            detail=(request.data.get("label") or "Doctor's paper filed"),
            by=request.user)
    return Response(_detail(request, c), status=201)


@api_view(["DELETE"])
def case_file(request, pk, fid):
    c, err = _get_case(request, pk)
    if err:
        return err
    err = _recorder(request, c.site_id)
    if err:
        return err
    f = c.files.filter(pk=fid).first()
    if f is None:
        return Response({"detail": "Not found."}, status=404)
    name = f.file_name
    f.file.delete(save=False)
    f.delete()
    audit("health", c.id, "HEALTH_FILE_REMOVED", actor=request.user,
          detail={"ref": c.ref, "file": name[:120]})
    return Response(_detail(request, c))


@api_view(["GET"])
def repeat(request):
    ids = scoped_site_ids(request.user)
    if request.GET.get("site"):
        sid = int(request.GET["site"])
        if not _site_ok(request, sid):
            return Response({"detail": "Not your site."}, status=403)
        ids = [sid]
    return Response(health.repeat_list(ids))


@api_view(["GET"])
def follow_ups(request):
    ids = scoped_site_ids(request.user)
    if request.GET.get("site"):
        sid = int(request.GET["site"])
        if not _site_ok(request, sid):
            return Response({"detail": "Not your site."}, status=403)
        ids = [sid]
    return Response([{**_row(c), "due": text, "due_level": 1}
                     for c, text in health.follow_ups_due(ids)])


@api_view(["GET"])
def workers(request):
    """Men to open a case for: everyone currently allocated to the site,
    with the repeat-sickness count beside the name."""
    try:
        site = Site.objects.get(pk=request.GET.get("site"))
    except (Site.DoesNotExist, ValueError, TypeError):
        return Response({"detail": "site required."}, status=400)
    if not _site_ok(request, site.id):
        return Response({"detail": "Not your site."}, status=403)
    emps = list(Employee.objects.filter(
        is_active=True, site_allocations__site=site,
        site_allocations__to_date__isnull=True).distinct()
        .order_by("emp_no"))
    flags = health.repeat_flags([e.id for e in emps])
    open_ids = set(HealthCase.objects.filter(
        employee_id__in=[e.id for e in emps], status="OPEN")
        .values_list("employee_id", flat=True))
    return Response([{"id": e.id, "emp_no": e.emp_no,
                      "full_name": e.full_name, "nationality": e.nationality,
                      "repeat_cases": flags.get(e.id, 0),
                      "has_open_case": e.id in open_ids} for e in emps])


@api_view(["GET", "PATCH"])
def employee_health(request, pk):
    """A man's health history, and — for HR, the Director, Admin and his
    site's PM — his medical profile."""
    try:
        emp = Employee.objects.get(pk=pk)
    except Employee.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    site_id = emp.current_site_id()
    if request.user.role not in health.HO_READ_ROLES and not (
            site_id and _site_ok(request, site_id)):
        return Response({"detail": "Not found."}, status=404)
    sees = health.sees_profile(request.user, emp)
    if request.method == "PATCH":
        if not sees:
            return Response({"detail": "HR, the Director, Admin or the "
                                       "site's PM keep the medical profile."},
                            status=403)
        changed = []
        for f in PROFILE_FIELDS:
            if f in request.data:
                setattr(emp, f, (request.data[f] or "").strip()
                        [:5 if f == "blood_group" else 2000])
                changed.append(f)
        if changed:
            emp.save(update_fields=changed)
            audit("employee", emp.id, "HEALTH_PROFILE_UPDATED",
                  actor=request.user, detail={"emp": emp.emp_no,
                                              "fields": sorted(changed)})
    cases_qs = HealthCase.objects.filter(employee=emp).select_related(
        "site").prefetch_related("events")
    out = {
        "employee_id": emp.id, "emp_no": emp.emp_no,
        "full_name": emp.full_name,
        "repeat_cases": health.cases_in_window(emp.id),
        "repeat_days": health.param("health_repeat_days"),
        "is_repeat": health.is_repeat(emp.id),
        "cases": [_row(c, {e.kind for e in c.events.all()})
                  for c in cases_qs[:50]],
        "sees_profile": sees,
    }
    if sees:
        out["profile"] = {k: getattr(emp, k) for k in PROFILE_FIELDS}
        out["profile"]["emergency_contact"] = emp.emergency_contact
        out["profile"]["medical_expiry"] = emp.medical_expiry
    return Response(out)


PLAN_FIELDS = ("focal_point_backup", "hotline", "hse_lead", "first_aiders",
               "nearest_health_centre", "travel_time", "resort_clinic",
               "male_hospitals", "boat_arrangement", "sick_bay",
               "emergency_contacts")


def _plan(p):
    return {**{f: getattr(p, f) for f in PLAN_FIELDS},
            "focal_point_id": p.focal_point_id,
            "focal_point": p.focal_point.full_name if p.focal_point_id else "",
            "updated_by": p.updated_by.full_name if p.updated_by_id else "",
            "updated_at": p.updated_at}


@api_view(["GET", "PUT"])
def plan(request, site_id):
    """The site medical plan (SOP §A): who, where, how long, which boat."""
    try:
        site = Site.objects.get(pk=site_id)
    except Site.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if not _site_ok(request, site.id):
        return Response({"detail": "Not found."}, status=404)
    p, _ = SiteMedicalPlan.objects.get_or_create(site=site)
    if request.method == "PUT":
        if request.user.role not in ("PM", "DIRECTOR", "ADMIN", "HO_HR") \
                or (request.user.role == "PM"
                    and not site.is_current_pm(request.user)):
            return Response({"detail": "The site PM, HR, the Director or "
                                       "Admin keep the medical plan."},
                            status=403)
        for f in PLAN_FIELDS:
            if f in request.data:
                setattr(p, f, (request.data[f] or "").strip())
        if "focal_point_id" in request.data:
            fp = request.data["focal_point_id"]
            p.focal_point = User.objects.filter(pk=fp, is_active=True).first() \
                if fp else None
        p.updated_by = request.user
        p.save()
        audit("site", site.id, "HEALTH_PLAN_UPDATED", actor=request.user,
              detail={"site": site.code})
    return Response(_plan(p))


@api_view(["GET"])
def log_pdf(request):
    """The month's health log for a site, for the weekly review and the
    file (SOP §H)."""
    from django.template.loader import render_to_string

    from .pdf import company_info, logo_src
    from .views_payroll import _pdf_response

    try:
        site = Site.objects.get(pk=request.GET.get("site"))
        year, month = int(request.GET["year"]), int(request.GET["month"])
    except (Site.DoesNotExist, KeyError, ValueError, TypeError):
        return Response({"detail": "site, year and month required."},
                        status=400)
    if not _site_ok(request, site.id):
        return Response({"detail": "Not found."}, status=404)
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    qs = (HealthCase.objects.filter(site=site, reported_on__gte=start,
                                    reported_on__lt=end)
          .select_related("employee").prefetch_related("events__by")
          .order_by("reported_on", "id"))
    rows = []
    for c in qs:
        events = list(c.events.all())
        kinds = {e.kind for e in events}
        rows.append({
            "c": c, "events": events,
            "steps": " → ".join(e.get_kind_display().split(" /")[0]
                                for e in events
                                if e.kind not in ("NOTE",)),
            "days_sick": health.days_sick(c),
            "repeat": health.cases_in_window(c.employee_id, c.reported_on),
            "referred": bool(kinds & {"DOCTOR", "MALE", "EVACUATED",
                                      "ADMITTED"}),
        })
    import calendar
    plan_obj = SiteMedicalPlan.objects.filter(site=site).select_related(
        "focal_point").first()
    html = render_to_string("pdf/health_log.html", {
        "site": site, "rows": rows, "plan": plan_obj,
        "period": f"{calendar.month_name[month]} {year}",
        "summary": health.summary([site.id]),
        "alerts": [a for a in health.active_alerts([site.id])],
        "repeat": health.repeat_list([site.id]),
        "logo_src": logo_src(), "co": company_info(),
        "printed_at": timezone.localtime(),
    })
    return _pdf_response(html, f"health-log-{site.code}-{year}-{month:02d}.pdf")
