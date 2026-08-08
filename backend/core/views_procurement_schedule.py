"""Procurement Schedule API — per-project planning layer (doc_type PSC).

Access: HO roles (Purchasing, PD/Directors, Signatory, Finance, QS, Admin) see
all schedules; the PM and the site's SE/Site-Admin see their site's schedules
(value columns are hidden below PM by schedule_dict). PM proposes lines,
Purchasing confirms, the Director signs off.
"""
from rest_framework.decorators import (api_view, parser_classes,
                                       permission_classes)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import procurement_pipeline as pp
from . import procurement_schedule as ps
from .models import (Project, ProcurementSchedule, ScheduleLine,
                     ScheduleLineQuote)
from .permissions import scoped_site_ids


def _can_see(user, sched):
    ids = scoped_site_ids(user)
    return ids is None or sched.document.site_id in ids


def _get_sched(request, pk):
    try:
        sched = ProcurementSchedule.objects.select_related(
            "document__site", "project__site").get(pk=pk)
    except ProcurementSchedule.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    if not _can_see(request.user, sched):
        return None, Response({"detail": "Not found."}, status=404)
    return sched, None


def _get_line(request, line_id):
    line = (ScheduleLine.objects
            .select_related("schedule__document__site", "schedule__project",
                            "section").filter(pk=line_id).first())
    if line is None or not _can_see(request.user, line.schedule):
        return None, Response({"detail": "Not found."}, status=404)
    return line, None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def schedule_list(request):
    """Schedules the user can see, newest first. Filter by ?site_id / ?project_id."""
    qs = ProcurementSchedule.objects.select_related(
        "document__site", "project").order_by("-document__doc_date")
    ids = scoped_site_ids(request.user)
    if ids is not None:
        qs = qs.filter(document__site_id__in=ids)
    if request.GET.get("site_id"):
        qs = qs.filter(document__site_id=request.GET["site_id"])
    if request.GET.get("project_id"):
        qs = qs.filter(project_id=request.GET["project_id"])
    out = []
    for s in qs[:200]:
        counts = {}
        for st in s.lines.exclude(state="CANCELLED").values_list(
                "state", flat=True):
            counts[st] = counts.get(st, 0) + 1
        out.append({"id": s.document_id, "ref": s.document.ref,
                    "status": s.document.status,
                    "project_id": s.project_id, "project_code": s.project.code,
                    "project_title": s.project.title,
                    "site_code": s.document.site.code,
                    "line_counts": counts,
                    "risk_counts": pp.schedule_risk_counts(s)})
    return Response(out)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def project_schedule(request, project_id):
    """Fetch (GET) or open (POST get-or-create) a project's schedule."""
    try:
        project = Project.objects.select_related("site").get(pk=project_id)
    except Project.DoesNotExist:
        return Response({"detail": "Unknown project."}, status=404)
    ids = scoped_site_ids(request.user)
    if ids is not None and project.site_id not in ids:
        return Response({"detail": "Not one of your sites."}, status=403)
    if request.method == "POST":
        sched, msg = ps.get_or_create_schedule(project, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(ps.schedule_dict(sched, request.user), status=201)
    sched = ProcurementSchedule.objects.filter(project=project).first()
    if sched is None:
        return Response({"detail": "No schedule yet.", "exists": False},
                        status=404)
    return Response(ps.schedule_dict(sched, request.user))


@api_view(["GET", "DELETE"])
@permission_classes([IsAuthenticated])
def schedule_detail(request, pk):
    sched, err = _get_sched(request, pk)
    if err:
        return err
    if request.method == "DELETE":
        msg = ps.delete_schedule(sched, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(status=204)
    return Response(ps.schedule_dict(sched, request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def schedule_lines(request, pk):
    sched, err = _get_sched(request, pk)
    if err:
        return err
    line, msg = ps.add_line(sched, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(ps.schedule_dict(sched, request.user), status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def schedule_line(request, line_id):
    line, err = _get_line(request, line_id)
    if err:
        return err
    if request.method == "DELETE":
        msg = ps.delete_line(line, request.user)
    else:
        msg = ps.update_line(line, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    line.schedule.refresh_from_db()
    return Response(ps.schedule_dict(line.schedule, request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def schedule_line_cancel(request, line_id):
    line, err = _get_line(request, line_id)
    if err:
        return err
    msg = ps.cancel_line(line, request.data.get("note", ""), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(ps.schedule_dict(line.schedule, request.user))


@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
def schedule_line_link(request, line_id):
    """Link (POST {slot, ref}) or unlink (DELETE {slot}) an execution document."""
    line, err = _get_line(request, line_id)
    if err:
        return err
    slot = request.data.get("slot")
    if request.method == "DELETE":
        msg = pp.unlink_doc(line, slot, request.user)
    else:
        msg = pp.link_doc(line, slot, request.data.get("ref", ""), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(ps.schedule_dict(line.schedule, request.user))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def schedule_line_candidates(request, line_id):
    """Execution docs that could fulfil the line, for retroactive linking."""
    line, err = _get_line(request, line_id)
    if err:
        return err
    return Response(pp.link_candidates(line, request.GET.get("slot", "")))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def schedule_line_production(request, line_id):
    """Set the manual production flag (made-to-order items)."""
    line, err = _get_line(request, line_id)
    if err:
        return err
    msg = pp.set_production(line, request.data.get("status"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(ps.schedule_dict(line.schedule, request.user))


@api_view(["POST", "DELETE"])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def schedule_line_image(request, line_id):
    """Attach (POST multipart 'image') or clear (DELETE) the line's reference
    image — a product photo shown on the planner + client plan."""
    line, err = _get_line(request, line_id)
    if err:
        return err
    upload = None if request.method == "DELETE" else request.FILES.get("image")
    msg = ps.set_reference_image(line, upload, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(ps.schedule_dict(line.schedule, request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def schedule_line_split(request, line_id):
    """Split a line's order across several IPRs: POST {quantities: [..]} — the
    first stays on this line, the rest become sibling sub-lines under one bundle.
    """
    line, err = _get_line(request, line_id)
    if err:
        return err
    _, msg = ps.split_line(line, request.data.get("quantities") or [],
                           request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(ps.schedule_dict(line.schedule, request.user), status=201)


def _quote_line(request, line_id):
    """Fetch a line for quote work — scoped, and gated on value visibility
    (quotes carry pricing)."""
    line, err = _get_line(request, line_id)
    if err:
        return None, err
    if not ps.can_see_values(request.user, line.schedule):
        return None, Response({"detail": "Not permitted to view quotes."},
                              status=403)
    return line, None


def _get_quote(request, quote_id):
    quote = (ScheduleLineQuote.objects
             .select_related("line__schedule__document__site",
                             "line__schedule__project__site").filter(
                 pk=quote_id).first())
    if quote is None or not _can_see(request.user, quote.line.schedule):
        return None, Response({"detail": "Not found."}, status=404)
    if not ps.can_see_values(request.user, quote.line.schedule):
        return None, Response({"detail": "Not permitted."}, status=403)
    return quote, None


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def schedule_line_quotes(request, line_id):
    """Attach a BOQ supplier quote to a line (multipart: fields + quote_file)."""
    line, err = _quote_line(request, line_id)
    if err:
        return err
    _, msg = pp.add_quote(line, request.data, request.FILES.get("quote_file"),
                          request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(ps.schedule_dict(line.schedule, request.user), status=201)


@api_view(["PATCH", "DELETE"])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def schedule_line_quote(request, quote_id):
    quote, err = _get_quote(request, quote_id)
    if err:
        return err
    if request.method == "DELETE":
        msg = pp.delete_quote(quote, request.user)
    else:
        msg = pp.update_quote(quote, request.data,
                              request.FILES.get("quote_file"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(ps.schedule_dict(quote.line.schedule, request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def schedule_line_award(request, line_id):
    """Record the supplier award decision (Purchasing + PD)."""
    line, err = _quote_line(request, line_id)
    if err:
        return err
    msg = pp.award_supplier(line, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(ps.schedule_dict(line.schedule, request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def schedule_line_raise_ipr(request, line_id):
    """Raise a draft IPR from the line's awarded quote and link it back."""
    line, err = _get_line(request, line_id)
    if err:
        return err
    doc, msg = pp.create_ipr_from_line(line, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    resp = ps.schedule_dict(line.schedule, request.user)
    resp["raised_ipr"] = doc.ref
    return Response(resp)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def schedule_line_client_update(request, line_id):
    """Log a client-supplied line's status: {note, delivered?}."""
    line, err = _get_line(request, line_id)
    if err:
        return err
    msg = pp.record_client_update(line, request.data.get("note"),
                                  request.data.get("delivered"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(ps.schedule_dict(line.schedule, request.user))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def schedule_export(request, pk):
    """Download the client procurement plan (xlsx). Allowlist columns only — no
    internal values or supplier names reach the client."""
    from django.http import HttpResponse

    from . import procurement_export
    sched, err = _get_sched(request, pk)
    if err:
        return err
    wb = procurement_export.build_client_xlsx(sched, request.user)
    resp = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument."
        "spreadsheetml.sheet")
    fname = f"{sched.project.code}-Procurement-Plan.xlsx"
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    wb.save(resp)
    return resp


@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
def schedule_share(request, pk):
    """Mint/rotate (POST) or revoke (DELETE) the client live-link token."""
    from . import procurement_client as pc
    sched, err = _get_sched(request, pk)
    if err:
        return err
    if request.method == "DELETE":
        msg = pc.revoke_share_token(sched, request.user)
    else:
        _, msg = pc.generate_share_token(sched, request.user)
    if msg:
        return Response({"detail": msg}, status=403)
    sched.refresh_from_db()
    return Response(ps.schedule_dict(sched, request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def schedule_submit(request, pk):
    sched, err = _get_sched(request, pk)
    if err:
        return err
    msg = ps.submit(sched, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    sched.refresh_from_db()
    return Response(ps.schedule_dict(sched, request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def schedule_reopen(request, pk):
    """Reopen a signed-off schedule so the team can edit lines (change batch)."""
    sched, err = _get_sched(request, pk)
    if err:
        return err
    msg = ps.reopen(sched, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    sched.refresh_from_db()
    return Response(ps.schedule_dict(sched, request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def schedule_action(request, pk):
    sched, err = _get_sched(request, pk)
    if err:
        return err
    msg = ps.decide(sched, request.data.get("action"), request.user,
                    request.data.get("note", ""))
    if msg:
        return Response({"detail": msg}, status=400)
    sched.refresh_from_db()
    return Response(ps.schedule_dict(sched, request.user))
