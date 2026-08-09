"""Public, token-gated client view of a procurement schedule (no login).

The client opens an unguessable link and sees the live plan — the same allowlist
the xlsx export uses (no money, no supplier). It's read-only and always current;
regenerating the token revokes the old link. The same link also serves the full
spreadsheet download.
"""
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_exempt

from . import procurement_client as pc
from .models import ProcurementSchedule


def _resolve(token):
    token = (token or "").strip()
    if not token:
        raise Http404
    sched = (ProcurementSchedule.objects
             .select_related("document__site", "project")
             .filter(share_token=token).first())
    if sched is None:
        raise Http404
    return sched


@xframe_options_exempt
def client_plan_page(request, token):
    sched = _resolve(token)
    return render(request, "procurement/client_plan.html",
                  {"plan": pc.client_plan(sched),
                   "download_url": f"/share/procurement/{token}/plan.xlsx"})


def client_plan_xlsx(request, token):
    """The full spreadsheet, same allowlist, from the client's link (no login).
    ?expand=1 lists every bundled variant under its group."""
    from . import procurement_export
    sched = _resolve(token)
    wb = procurement_export.build_client_xlsx(
        sched, expand=request.GET.get("expand") == "1")
    resp = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument."
        "spreadsheetml.sheet")
    resp["Content-Disposition"] = (
        f'attachment; filename="{sched.project.code}-Procurement-Plan.xlsx"')
    wb.save(resp)
    return resp
