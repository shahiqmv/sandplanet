"""Management reports API (owner 2026-11-07). See core/reports.py for who
reads them and the one shape every report returns."""
from datetime import date

from django.http import HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import reports as rp
from .audit import audit


def _site_row(s):
    return {"id": s.id, "code": s.code, "name": s.name}


@api_view(["GET"])
def report_list(request):
    """The reports this person may run, and for which sites."""
    user = request.user
    if not rp.is_reader(user):
        return Response({"detail": "Reports are for the executive committee "
                                   "and site PMs."}, status=403)
    start, end = rp.default_period()
    return Response({
        "reports": [{"key": r.key, "title": r.title,
                     "description": r.description,
                     "company_only": r.company_only}
                    for r in rp.reports().values()
                    if user.excom or not r.company_only],
        "sites": [_site_row(s) for s in rp.allowed_sites(user)],
        "company": bool(user.excom),
        "default_from": start, "default_to": end,
    })


def _context(user, key, params):
    """(Context, None) for a report request, or (None, error Response)."""
    if not rp.is_reader(user):
        return None, Response({"detail": "Reports are for the executive "
                                         "committee and site PMs."},
                              status=403)
    if key not in rp.reports():
        return None, Response({"detail": "No such report."}, status=404)
    sites = rp.allowed_sites(user)
    want = str(params.get("site") or "")
    if rp.reports()[key].company_only and want != "all":
        return None, Response({"detail": "This report is company-wide only."},
                              status=400)
    if want == "all":
        if not user.excom:
            return None, Response({"detail": "Company-wide reports are for "
                                             "the executive committee."},
                                  status=403)
        scope, company = sites, True
    else:
        scope = [s for s in sites if str(s.id) == want]
        if not scope:
            return None, Response({"detail": "Pick one of your sites."},
                                  status=400)
        company = False
    try:
        start = date.fromisoformat(str(params.get("from") or ""))
        end = date.fromisoformat(str(params.get("to") or ""))
    except ValueError:
        return None, Response({"detail": "Give the period: from and to."},
                              status=400)
    if end < start:
        return None, Response({"detail": "The period ends before it starts."},
                              status=400)
    if (end - start).days > 366 * 3:
        return None, Response({"detail": "Keep the period to three years or "
                                         "less."}, status=400)
    return rp.Context(user=user, sites=scope, company=company,
                      start=start, end=end), None


@api_view(["GET"])
def report_run(request, key):
    user = request.user
    ctx, err = _context(user, key, request.GET)
    if err:
        return err
    scope, company, start, end = ctx.sites, ctx.company, ctx.start, ctx.end
    rep = rp.run(key, ctx)
    fmt = request.GET.get("export") or ""
    audit("report", user.id, "REPORT_RUN", actor=user,
          detail={"report": key, "scope": "all" if company else scope[0].code,
                  "from": str(start), "to": str(end), "format": fmt or "screen"})
    base = (f"{key}-{'company' if company else scope[0].code}-"
            f"{start}-to-{end}")
    if fmt == "xlsx":
        resp = HttpResponse(
            rp.workbook(rep),
            content_type="application/vnd.openxmlformats-officedocument."
                         "spreadsheetml.sheet")
        resp["Content-Disposition"] = f'attachment; filename="{base}.xlsx"'
        return resp
    if fmt == "pdf":
        from .views_payroll import _pdf_response
        return _pdf_response(rp.pdf_html(rep, user), f"{base}.pdf")
    return Response(rep)


# ---- ask Claude about a report (owner 2026-11-09) --------------------------

@api_view(["POST"])
def report_ask(request):
    """Put a question to Claude about the report on screen. The report is
    run again here, under the asker's own rights, and handed to the model
    with the question; the answer arrives in the background."""
    from . import report_ask as ask
    user = request.user
    body = request.data or {}
    key = str(body.get("report") or "")
    ctx, err = _context(user, key, body)
    if err:
        return err
    follow = body.get("follow_up_of")
    rep = None if follow else rp.run(key, ctx)
    a, problem = ask.start(
        user, key, "all" if ctx.company else ctx.sites[0].code,
        ctx.start, ctx.end, body.get("question"), rep,
        follow_up_of=follow)
    if problem:
        return Response({"detail": problem}, status=400)
    return Response({"analysis": ask.payload(a)}, status=202)


@api_view(["GET"])
def report_ask_detail(request, pk):
    from . import report_ask as ask
    from .models import ReportAnalysis
    a = ReportAnalysis.objects.filter(pk=pk, user=request.user).first()
    if a is None:
        return Response({"detail": "Not your question."}, status=404)
    if request.GET.get("export") == "pdf":
        if a.status != "DONE":
            return Response({"detail": "No answer to print yet."}, status=400)
        from .views_payroll import _pdf_response
        return _pdf_response(ask.pdf_html(a, request.user),
                             f"analysis-{a.report_key}-{a.scope}-{a.id}.pdf")
    return Response({"analysis": ask.payload(a)})


@api_view(["GET"])
def report_asks(request):
    """This reader's questions on one report view, oldest first, so the page
    can show the threads under the report."""
    from . import report_ask as ask
    from .models import ReportAnalysis
    user = request.user
    if not rp.is_reader(user):
        return Response({"detail": "Reports are for the executive committee "
                                   "and site PMs."}, status=403)
    qs = ReportAnalysis.objects.filter(user=user)
    key = request.GET.get("report")
    if key:
        qs = qs.filter(report_key=key)
    scope = request.GET.get("scope")
    if scope:
        qs = qs.filter(scope=scope)
    items = list(qs.order_by("-started_at")[:40])
    items.reverse()
    return Response({"analyses": [ask.payload(a) for a in items]})
