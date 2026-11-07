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


@api_view(["GET"])
def report_run(request, key):
    user = request.user
    if not rp.is_reader(user):
        return Response({"detail": "Reports are for the executive committee "
                                   "and site PMs."}, status=403)
    if key not in rp.reports():
        return Response({"detail": "No such report."}, status=404)
    sites = rp.allowed_sites(user)
    want = request.GET.get("site") or ""
    if rp.reports()[key].company_only and want != "all":
        return Response({"detail": "This report is company-wide only."},
                        status=400)
    if want == "all":
        if not user.excom:
            return Response({"detail": "Company-wide reports are for the "
                                       "executive committee."}, status=403)
        scope, company = sites, True
    else:
        scope = [s for s in sites if str(s.id) == want]
        if not scope:
            return Response({"detail": "Pick one of your sites."}, status=400)
        company = False
    try:
        start = date.fromisoformat(request.GET.get("from") or "")
        end = date.fromisoformat(request.GET.get("to") or "")
    except ValueError:
        return Response({"detail": "Give the period: from and to."},
                        status=400)
    if end < start:
        return Response({"detail": "The period ends before it starts."},
                        status=400)
    if (end - start).days > 366 * 3:
        return Response({"detail": "Keep the period to three years or less."},
                        status=400)
    ctx = rp.Context(user=user, sites=scope, company=company,
                     start=start, end=end)
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
