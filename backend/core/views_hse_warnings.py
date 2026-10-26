"""Warning notices API (owner 2026-10-26). Rules live in core/hse_warnings.py.
"""
from datetime import date

from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from . import hse_warnings as svc
from .models import Employee, SafetyIncident, Site


def _who(u):
    return (u.get_full_name() or u.username) if u else ""


def _row(w, user, full=False):
    emp = w.employee
    out = {
        "id": w.id, "ref": w.ref, "status": w.status,
        "status_label": w.get_status_display(),
        "employee": emp.id, "emp_no": emp.emp_no, "full_name": emp.full_name,
        "trade": emp.job_category.name if emp.job_category_id else "",
        "subcontractor": (emp.subcontractor.name
                          if emp.is_subcontract and emp.subcontractor_id
                          else ""),
        "site": w.site_id, "site_code": w.site.code,
        "event_date": w.event_date, "level": w.level,
        "level_label": w.get_level_display(),
        "suggested_level": w.suggested_level, "level_reason": w.level_reason,
        "offences": w.offences, "other_offence": w.other_offence,
        "what_happened": w.what_happened,
        "corrective_action": w.corrective_action,
        "supervisor": w.supervisor,
        "incident_ref": (w.incident.document.ref if w.incident_id else None),
        "raised_by": _who(w.raised_by), "created_at": w.created_at,
        "decided_by": _who(w.decided_by), "decided_at": w.decided_at,
        "decision_note": w.decision_note,
        "printed_at": w.printed_at, "served_on": w.served_on,
        "refused_to_sign": w.refused_to_sign, "witness_name": w.witness_name,
        "signed_copy_url": w.signed_copy.url if w.signed_copy else None,
        "active_until": w.active_until, "form_rev": w.form_rev,
        "removal_batch": w.removal_batch_id,
        "cancel_reason": w.cancel_reason,
        "can_decide": w.status == "PENDING" and svc.can_approve(user, w),
        "can_edit": (w.status in ("PENDING", "RETURNED")
                     and (user.id == w.raised_by_id
                          or user.role in ("HO_HR", "ADMIN"))),
        "can_serve": (w.status == "APPROVED"
                      and svc.can_record(user, w.site)),
    }
    if full or w.status in ("PENDING", "RETURNED"):
        out["history"] = [{"ref": h.ref, "date": h.event_date,
                           "level": h.get_level_display(),
                           "status": h.get_status_display(),
                           "site": h.site.code,
                           "active": (h.status == "ACTIVE" and h.active_until
                                      and h.active_until >= timezone.localdate())}
                          for h in svc.history(emp, exclude_id=w.id)[:10]]
    return out


@api_view(["GET"])
def warning_meta(request):
    """The form's offence list, levels and the languages a worker's forms
    can print in."""
    return Response({
        "offences": [{"code": c, "group": g, "label": en, "label_bn": bn}
                     for c, g, en, bn in svc.OFFENCES],
        "levels": [{"code": c, "label": lbl} for c, lbl in
                   svc.WarningNotice.Level.choices],
        "languages": [{"code": c, "label": lbl} for c, lbl in svc.LANGUAGES],
        "active_months": svc.active_months(),
        "can_record": request.user.role in svc.RECORD_ROLES,
    })


@api_view(["GET", "POST"])
def warnings(request):
    user = request.user
    if request.method == "GET":
        qs = svc.scoped(user)
        g = request.GET
        if g.get("site"):
            qs = qs.filter(site_id=g["site"])
        if g.get("status"):
            qs = qs.filter(status=g["status"])
        if g.get("employee"):
            qs = qs.filter(employee_id=g["employee"])
        if g.get("q"):
            t = g["q"].strip()
            qs = qs.filter(Q(employee__emp_no__icontains=t)
                           | Q(employee__full_name__icontains=t)
                           | Q(ref__icontains=t))
        return Response({"results": [_row(w, user) for w in qs[:500]],
                         "can_record": user.role in svc.RECORD_ROLES})
    d = request.data
    try:
        site = Site.objects.get(pk=d.get("site"))
        emp = Employee.objects.get(pk=d.get("employee"))
        day = date.fromisoformat(d.get("event_date") or "")
    except (Site.DoesNotExist, Employee.DoesNotExist, ValueError, TypeError):
        return Response({"detail": "Pick the site, the worker and the date."},
                        status=400)
    incident = None
    if d.get("incident"):
        incident = SafetyIncident.objects.filter(
            pk=d["incident"], document__site=site).first()
    w, err = svc.raise_warning(user=user, employee=emp, site=site,
                               event_date=day, data=d, incident=incident)
    if err:
        return Response({"detail": err}, status=400)
    return Response(_row(w, user, full=True), status=201)


def _get(request, pk):
    return svc.scoped(request.user).filter(pk=pk).first()


@api_view(["GET", "PATCH"])
def warning_detail(request, pk):
    w = _get(request, pk)
    if w is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "PATCH":
        err = svc.edit(w, request.user, request.data)
        if err:
            return Response({"detail": err}, status=400)
        w.refresh_from_db()
    return Response(_row(w, request.user, full=True))


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def warning_action(request, pk, action):
    w = _get(request, pk)
    if w is None:
        return Response({"detail": "Not found."}, status=404)
    d = request.data
    note = d.get("note") or d.get("reason") or ""
    if action in ("approve", "return"):
        err = svc.decide(w, request.user, action == "approve", note)
    elif action == "cancel":
        err = svc.cancel(w, request.user, note)
    elif action == "serve":
        try:
            served = date.fromisoformat(d.get("served_on") or "")
        except ValueError:
            served = None
        refused = str(d.get("refused_to_sign") or "").lower() in (
            "1", "true", "yes", "on")
        err = svc.serve(w, request.user, request.FILES.getlist("files"),
                        served, refused, d.get("witness_name"))
    else:
        return Response({"detail": "Unknown action."}, status=400)
    if err:
        return Response({"detail": err}, status=400)
    w.refresh_from_db()
    return Response(_row(w, request.user, full=True))


@api_view(["GET"])
def warning_workers(request):
    """Who can be warned at a site on a date — direct and subcontract."""
    try:
        site = Site.objects.get(pk=request.GET.get("site"))
    except (Site.DoesNotExist, ValueError, TypeError):
        return Response({"detail": "Pick a site."}, status=400)
    if not svc.can_record(request.user, site):
        return Response({"detail": "Not your site."}, status=403)
    try:
        day = date.fromisoformat(request.GET.get("date") or "")
    except ValueError:
        day = date.today()
    out = []
    for e in svc.eligible_workers(site, day):
        out.append({
            "id": e.id, "emp_no": e.emp_no, "full_name": e.full_name,
            "trade": e.job_category.name if e.job_category_id else "",
            "subcontractor": (e.subcontractor.name if e.is_subcontract
                              and e.subcontractor_id else ""),
            "suggested_level": svc.suggest_level(e, day),
            "active": svc.active_warnings(e, day).count(),
            "language": e.preferred_language or "",
        })
    return Response(out)


@api_view(["GET"])
def warning_pdf(request, pk):
    """SP-HSE-F02 printed from the record: everything filled in but the
    employee's statement and the signatures. English, plus Bengali when that
    is his language."""
    from . import pdf as pdf_mod
    from .views_payroll import _pdf_response
    w = _get(request, pk)
    if w is None:
        return Response({"detail": "Not found."}, status=404)
    if w.status not in ("APPROVED", "ACTIVE"):
        return Response({"detail": "A warning is printed once the PM has "
                                   "approved it."}, status=400)
    svc.mark_printed(w)
    emp = w.employee
    lang = (w.language or emp.preferred_language or "").upper()
    project = (w.site.projects.filter(status="ACTIVE").count() == 1
               and w.site.projects.filter(status="ACTIVE").first())
    ctx = {
        "w": w, "emp": emp, "site": w.site, "project": project or None,
        "bn": lang == "BN",
        "explained_verbally": bool(lang) and lang not in svc.TRANSLATED
        and lang != "EN",
        "language_label": dict(svc.LANGUAGES).get(lang, ""),
        "offences": [{"code": c, "group": g, "en": en, "bn": bn,
                      "ticked": c in (w.offences or [])}
                     for c, g, en, bn in svc.OFFENCES],
        "levels": [{"code": c, "en": lbl, "ticked": w.level == c}
                   for c, lbl in svc.WarningNotice.Level.choices],
        "is_sub": emp.is_subcontract,
        "subcontractor": (emp.subcontractor.name if emp.is_subcontract
                          and emp.subcontractor_id else ""),
        "logo_src": pdf_mod.logo_src(), "co": pdf_mod.company_info(),
        "printed_at": timezone.localtime(),
    }
    return _pdf_response(render_to_string("pdf/hse_warning.html", ctx),
                         f"{w.ref}-warning-notice.pdf")
