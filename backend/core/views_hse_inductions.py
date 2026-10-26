"""Safety induction sessions API (owner 2026-10-26). Rules live in
core/hse_inductions.py; the form's content in core/hse_induction_content.py.
"""
from datetime import date

from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from . import hse_induction_content as content
from . import hse_inductions as svc
from .hse_warnings import LANGUAGES
from .models import Site, SiteMedicalPlan


def _who(u):
    return (u.get_full_name() or u.username) if u else ""


def _emp(e):
    return {"id": e.id, "emp_no": e.emp_no, "full_name": e.full_name,
            "trade": e.job_category.name if e.job_category_id else "",
            "subcontractor": (e.subcontractor.name if e.is_subcontract
                              and e.subcontractor_id else ""),
            "language": e.preferred_language or ""}


def _row(s, user):
    att = list(s.attendees.select_related("employee__job_category",
                                          "employee__subcontractor"))
    return {
        "id": s.id, "ref": s.ref, "status": s.status,
        "status_label": s.get_status_display(),
        "site": s.site_id, "site_code": s.site.code,
        "held_on": s.held_on, "language": s.language,
        "language_label": dict(LANGUAGES).get(s.language, "English"),
        "trainer_name": s.trainer_name, "notes": s.notes,
        "topics_na": s.topics_na, "form_rev": s.form_rev,
        "created_by": _who(s.created_by), "created_at": s.created_at,
        "printed_at": s.printed_at,
        "uploaded_by": _who(s.uploaded_by), "uploaded_at": s.uploaded_at,
        "verified_by": _who(s.verified_by), "verified_at": s.verified_at,
        "signed_copy_url": s.signed_copy.url if s.signed_copy else None,
        "attendees": [{**_emp(a.employee), "attended": a.attended}
                      for a in att],
        "can_edit": (s.status in ("DRAFT", "PRINTED")
                     and svc.can_record(user, s.site)),
        "can_verify": s.status == "SIGNED" and svc.can_verify(user, s),
    }


@api_view(["GET"])
def induction_meta(request):
    return Response({
        "topics": [{"no": no, "title": en, "title_bn": bn}
                   for no, en, bn, _b in content.TOPICS],
        "languages": [{"code": c, "label": lbl} for c, lbl in LANGUAGES],
        "form_rev": content.FORM_REV,
        "can_record": request.user.role in svc.RECORD_ROLES,
    })


@api_view(["GET", "POST"])
def sessions(request):
    user = request.user
    if request.method == "GET":
        qs = svc.scoped(user)
        if request.GET.get("site"):
            qs = qs.filter(site_id=request.GET["site"])
        if request.GET.get("status"):
            qs = qs.filter(status=request.GET["status"])
        return Response({"results": [_row(s, user) for s in qs[:200]],
                         "can_record": user.role in svc.RECORD_ROLES})
    d = request.data
    try:
        site = Site.objects.get(pk=d.get("site"))
        held = date.fromisoformat(d.get("held_on") or "")
    except (Site.DoesNotExist, ValueError, TypeError):
        return Response({"detail": "Pick the site and the date."}, status=400)
    s, err = svc.create(user=user, site=site, held_on=held,
                        language=d.get("language"),
                        trainer_name=d.get("trainer_name"),
                        employee_ids=d.get("employees") or [],
                        notes=d.get("notes", ""))
    if err:
        return Response({"detail": err}, status=400)
    return Response(_row(s, user), status=201)


def _get(request, pk):
    return svc.scoped(request.user).filter(pk=pk).first()


@api_view(["GET", "PATCH"])
def session_detail(request, pk):
    s = _get(request, pk)
    if s is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "PATCH":
        err = svc.edit_attendees(s, request.user,
                                 add=request.data.get("add") or [],
                                 remove=request.data.get("remove") or [])
        if err:
            return Response({"detail": err}, status=400)
        s.refresh_from_db()
    return Response(_row(s, request.user))


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def session_action(request, pk, action):
    s = _get(request, pk)
    if s is None:
        return Response({"detail": "Not found."}, status=404)
    d = request.data
    if action == "upload":
        getl = d.getlist if hasattr(d, "getlist") else (lambda k: d.get(k) or [])
        err = svc.upload_signed(s, request.user, request.FILES.getlist("files"),
                                absent_ids=getl("absent"),
                                topics_na=getl("topics_na"))
    elif action == "verify":
        err = svc.verify(s, request.user)
    elif action == "cancel":
        err = svc.cancel(s, request.user, d.get("reason"))
    else:
        return Response({"detail": "Unknown action."}, status=400)
    if err:
        return Response({"detail": err}, status=400)
    s.refresh_from_db()
    return Response(_row(s, request.user))


@api_view(["GET"])
def induction_candidates(request):
    """Who a session can take: on the site that day, not yet inducted for
    this stint, not on another open session."""
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
    return Response([_emp(e) for e in svc.candidates(site, day)])


@api_view(["GET"])
def session_pdf(request, pk):
    """SP-HSE-F01 printed for this session: the six topics, the site box
    from the site's medical plan, and the men on it. English, plus Bengali
    when that is the language of the training."""
    from . import pdf as pdf_mod
    from .views_payroll import _pdf_response
    s = _get(request, pk)
    if s is None:
        return Response({"detail": "Not found."}, status=404)
    if s.status == "CANCELLED":
        return Response({"detail": "This session was cancelled."}, status=400)
    if s.status == "DRAFT" and svc.can_record(request.user, s.site):
        svc.mark_printed(s)
    plan = SiteMedicalPlan.objects.filter(site=s.site).first()
    att = [a.employee for a in s.attendees.select_related(
        "employee__job_category", "employee__subcontractor")
        if a.attended or s.status in ("DRAFT", "PRINTED")]
    rows = [{"n": i + 1, "name": e.full_name, "id": e.emp_no,
             "employer": (e.subcontractor.name if e.is_subcontract
                          and e.subcontractor_id else "Sand Planet"),
             "trade": e.job_category.name if e.job_category_id else "",
             "language": dict(LANGUAGES).get(e.preferred_language or "", "")}
            for i, e in enumerate(att)]
    rows += [{"n": len(rows) + i + 1} for i in range(max(0, 20 - len(rows)))]
    employers = sorted({r["employer"] for r in rows if r.get("employer")})
    trades = sorted({r["trade"] for r in rows if r.get("trade")})
    ctx = {
        "s": s, "site": s.site, "plan": plan, "rows": rows,
        "bn": s.language == "BN",
        "language_label": dict(LANGUAGES).get(s.language, "English"),
        "employers": ", ".join(employers) or "Sand Planet",
        "trades": ", ".join(trades[:4]) + (" and others" if len(trades) > 4
                                            else ""),
        "topics": [{"no": no, "en": en, "bn": bn, "bullets": b,
                    "na": no in (s.topics_na or [])}
                   for no, en, bn, b in content.TOPICS],
        "c": content,
        "footer_doc": "SP-HSE-" + s.form_rev.replace(" Rev", " · Rev"),
        "subline": ("Health, Safety & Environment · Form SP-HSE-"
                    + s.form_rev.replace(" Rev", " · Rev")),
        "logo_src": pdf_mod.logo_src(), "co": pdf_mod.company_info(),
        "printed_at": timezone.localtime(),
    }
    return _pdf_response(render_to_string("pdf/hse_induction.html", ctx),
                         f"{s.ref}-safety-induction.pdf")
