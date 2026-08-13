"""Client Portal endpoints — the external read-only realm (owner 2026-08-02).

Every view here authenticates ONLY with a client token and permits ONLY a
ClientUser. Content is served through explicit allowlist dicts — adding a field
is a deliberate code change, never inherited — and scoped to the client's own
sites (a site outside their set is a 404, never a 403).
"""
from datetime import date

from django.utils import timezone
from rest_framework.decorators import (api_view, authentication_classes,
                                        permission_classes)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .client_portal import (ClientTokenAuthentication, IsClient,
                            client_site_ids, new_token)
from .models import Camera, ClientSession, ClientUser, Document, Site


VIS_FLAGS = ("show_reports", "show_programme", "show_procurement",
             "show_gallery", "show_cameras", "show_submittals")


def _client_dict(c):
    return {
        "full_name": c.full_name, "org_name": c.org_name, "email": c.email,
        "must_change_password": c.must_change_password,
        "sites": [{"id": s.id, "code": s.code, "name": s.name}
                  for s in c.sites.all().order_by("code")],
        "visibility": {f: getattr(c, f) for f in VIS_FLAGS},
    }


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def client_login(request):
    """Email + password → a client session token. Deliberately vague on
    failure (no user enumeration)."""
    email = (request.data.get("email") or "").strip().lower()
    password = request.data.get("password") or ""
    client = ClientUser.objects.filter(email__iexact=email,
                                       is_active=True).first()
    if not client or not client.check_password(password):
        return Response({"detail": "Wrong email or password."}, status=401)
    session = ClientSession.objects.create(client=client, token=new_token())
    client.last_login = timezone.now()
    client.save(update_fields=["last_login"])
    return Response({"token": session.token, **_client_dict(client)})


@api_view(["POST"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_logout(request):
    s = getattr(request, "client_session", None)
    if s:
        ClientSession.objects.filter(pk=s.pk).update(revoked=True)
    return Response(status=204)


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_me(request):
    return Response(_client_dict(request.user))


@api_view(["POST"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_change_password(request):
    client = request.user
    if not client.check_password(request.data.get("current_password") or ""):
        return Response({"detail": "Current password is wrong."}, status=400)
    new = request.data.get("new_password") or ""
    if len(new) < 8:
        return Response({"detail": "Use at least 8 characters."}, status=400)
    client.set_password(new)
    client.must_change_password = False
    client.save(update_fields=["password", "must_change_password"])
    return Response({"detail": "Password changed."})


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_sites(request):
    """The client's assigned sites — minimal, allowlisted."""
    sites = list(request.user.sites.all().order_by("code"))
    with_cams = set()
    if getattr(request.user, "show_cameras", True):
        with_cams = set(Camera.objects.filter(
            site_id__in=[s.id for s in sites], is_active=True,
            client_visible=True).values_list("site_id", flat=True))
    return Response([
        {"id": s.id, "code": s.code, "name": s.name,
         "status": s.status,
         "has_cameras": s.id in with_cams}
        for s in sites])


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_site(request, pk):
    """A client's own site dashboard — allowlisted, read-only. Site-wide
    sections (manpower, DMA, DPR, deliveries) plus the site's projects for the
    per-project switcher (brief + procurement). Unassigned site → 404."""
    from datetime import timedelta
    if pk not in client_site_ids(request.user):
        return Response({"detail": "Not found."}, status=404)
    site = Site.objects.get(pk=pk)
    today = date.today()
    tomorrow = today + timedelta(days=1)
    reports = request.user.show_reports

    def dma_on(day):
        d = Document.objects.filter(doc_type="DMA", site=site, doc_date=day,
                                    is_void=False,
                                    status="ISSUED").order_by("-id").first()
        return {"ref": d.ref, "date": d.doc_date} if d else None

    dprs = Document.objects.filter(
        site=site, doc_type="DPR", is_void=False,
        status__in=("ISSUED", "VERIFIED"),
        doc_date__gte=today - timedelta(days=6)).order_by("-doc_date")[:7]
    lms = Document.objects.filter(
        site=site, doc_type="LM", is_void=False,
        status="DEPARTED").order_by("-doc_date")[:20]
    projects = site.projects.exclude(
        status__in=("POTENTIAL", "CLOSED")).order_by("code")
    from . import client_report as cr
    return Response({
        "site": {"id": site.id, "code": site.code, "name": site.name,
                 "status": site.status,
                 "progress": cr.project_progress(site)},
        "projects": [{"id": p.id, "code": p.code, "title": p.title,
                      "scope": p.scope,
                      "progress": cr.client_project_progress(p),
                      "start_date": p.start_date,
                      "target_date": p.planned_completion,
                      "has_programme": p.activities.exists()}
                     for p in projects],
        # Current strength on site — by trade + grand total, from the latest
        # daily report (includes subcontract labour).
        "manpower": cr.site_workforce(site),
        # Daily reports / allocations / deliveries are gated by show_reports.
        "dma": ({"today": dma_on(today), "tomorrow": dma_on(tomorrow)}
                if reports else {"today": None, "tomorrow": None}),
        "recent_dprs": [
            {"ref": d.ref, "date": d.doc_date, "verified": d.status == "VERIFIED"}
            for d in dprs] if reports else [],
        "materials_on_the_way": [
            {"ref": d.ref, "date": d.doc_date} for d in lms] if reports else [],
        # Issued submittals (MAR / Shop Drawing / Method Statement), view-only.
        "submittals": (cr.site_submittals(site)
                       if request.user.show_submittals else []),
        "visibility": {f: getattr(request.user, f) for f in VIS_FLAGS},
    })


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_site_gallery(request, pk):
    """Progress photos from the site's recent daily reports, date-grouped."""
    if (b := _blocked(request, "show_gallery")):
        return b
    if pk not in client_site_ids(request.user):
        return Response({"detail": "Not found."}, status=404)
    site = Site.objects.get(pk=pk)
    from . import client_report as cr
    return Response(cr.site_gallery(site))


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_submittal_pdf(request, pk):
    """View an issued submittal's PDF — MAR / Shop Drawing / Method Statement.
    Scoped to the client's own sites and to the issued states only."""
    from django.http import HttpResponse
    if (b := _blocked(request, "show_submittals")):
        return b
    from . import client_report as cr
    doc = (Document.objects.filter(
        pk=pk, doc_type__in=cr.SUBMITTAL_TYPES, is_void=False,
        status__in=cr.SUBMITTAL_STATES)
        .select_related("current_revision").first())
    if not doc or doc.site_id not in client_site_ids(request.user):
        return Response({"detail": "Not found."}, status=404)
    from . import pdf
    pdf_bytes = pdf.document_pdf_bytes(doc, doc.current_revision)
    if not pdf_bytes:
        return Response({"detail": "PDF is unavailable right now."}, status=503)
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{doc.ref}.pdf"'
    return resp


def _project_schedule(project):
    from .models import ProcurementSchedule
    return (ProcurementSchedule.objects
            .filter(project=project, document__is_void=False)
            .select_related("document", "project")
            .order_by("-document__doc_date").first())


def _client_project(request, pk):
    """The Project `pk` if it sits on one of the client's own sites, else
    None — the per-project authorisation gate (a project on another site is a
    404, never a 403)."""
    from .models import Project
    project = Project.objects.filter(pk=pk).select_related("site").first()
    if not project or project.site_id not in client_site_ids(request.user):
        return None
    return project


def _blocked(request, flag):
    """A 404 Response when the client's account has this portal section hidden
    (HO admin gate), else None so the caller proceeds."""
    if not getattr(request.user, flag, True):
        return Response({"detail": "Not found."}, status=404)
    return None


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_site_procurement(request, pk):
    """The whole site's procurement plan for the portal — every project's plan
    merged into one, so the client sees it site-wide without toggling projects
    (owner 2026-08-03). Per-project scheduling stays intact in the staff app."""
    if (b := _blocked(request, "show_procurement")):
        return b
    if pk not in client_site_ids(request.user):
        return Response({"detail": "Not found."}, status=404)
    site = Site.objects.get(pk=pk)
    from . import procurement_client as pc
    return Response(pc.client_site_plan(site))


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_site_procurement_xlsx(request, pk):
    """The site-wide procurement plan as a spreadsheet."""
    from django.http import HttpResponse
    if (b := _blocked(request, "show_procurement")):
        return b
    if pk not in client_site_ids(request.user):
        return Response({"detail": "Not found."}, status=404)
    site = Site.objects.get(pk=pk)
    from . import procurement_client as pc, procurement_export
    plan = pc.client_site_plan(site)
    if not plan.get("available"):
        return Response({"detail": "No plan."}, status=404)
    wb = procurement_export.build_client_xlsx_from_plan(
        plan, expand=request.query_params.get("expand") == "1")
    resp = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument."
        "spreadsheetml.sheet")
    resp["Content-Disposition"] = (
        f'attachment; filename="{site.code}-Procurement-Plan.xlsx"')
    wb.save(resp)
    return resp


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_project_programme(request, pk):
    """The client-safe construction programme (Gantt data) for one of the
    client's own projects."""
    if (b := _blocked(request, "show_programme")):
        return b
    project = _client_project(request, pk)
    if not project:
        return Response({"detail": "Not found."}, status=404)
    from . import client_report as cr
    return Response(cr.project_programme(project))


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_project_programme_pdf(request, pk):
    """The construction programme as a PDF (Gantt + activity table + planned
    manpower) — the same award-package document, downloadable in the portal."""
    from django.http import HttpResponse
    if (b := _blocked(request, "show_programme")):
        return b
    project = _client_project(request, pk)
    if not project:
        return Response({"detail": "Not found."}, status=404)
    from .views_projects import programme_pdf_bytes
    pdf_bytes = programme_pdf_bytes(project)
    if pdf_bytes is None:
        return Response({"detail": "PDF is unavailable right now."}, status=503)
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = (
        f'attachment; filename="Programme-{project.code}.pdf"')
    return resp


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_project_procurement(request, pk):
    """The client procurement plan for one of the client's own projects — the
    same vetted allowlist the public share link uses, served in the portal."""
    if (b := _blocked(request, "show_procurement")):
        return b
    project = _client_project(request, pk)
    if not project:
        return Response({"detail": "Not found."}, status=404)
    sched = _project_schedule(project)
    if not sched:
        return Response({"available": False})
    from . import procurement_client as pc
    return Response({"available": True, **pc.client_plan(sched)})


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_project_procurement_xlsx(request, pk):
    """The project procurement plan as a spreadsheet — same client allowlist."""
    from django.http import HttpResponse
    if (b := _blocked(request, "show_procurement")):
        return b
    project = _client_project(request, pk)
    if not project:
        return Response({"detail": "Not found."}, status=404)
    sched = _project_schedule(project)
    if not sched:
        return Response({"detail": "No plan."}, status=404)
    from . import procurement_export
    wb = procurement_export.build_client_xlsx(sched)
    resp = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument."
        "spreadsheetml.sheet")
    resp["Content-Disposition"] = (
        f'attachment; filename="{project.code}-Procurement-Plan.xlsx"')
    wb.save(resp)
    return resp


# ---- report viewer: DPR / DMA / LM rendered inside the portal --------------
# Site-level reports the client is allowed to open. These carry no commercial
# or engagement data; everything else (PO/PR/MR/GRN/IR/MAR) stays internal.
CLIENT_VIEWABLE = {"DPR", "DMA", "TWS", "LM"}


def _client_document(request, ref):
    """The Document `ref` if it is a client-viewable report on one of the
    client's own sites and issued (not a draft), else None."""
    doc = (Document.objects.filter(ref=ref, is_void=False)
           .select_related("site", "current_revision").first())
    if (not doc or doc.doc_type not in CLIENT_VIEWABLE
            or doc.site_id not in client_site_ids(request.user)
            or doc.status == "DRAFT" or not doc.current_revision):
        return None
    return doc


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_document(request, ref):
    """A client-viewable report as structured, allowlisted JSON — the portal
    renders it web-native (responsive), not the print PDF in a frame. The
    print PDF stays available at the .pdf sibling endpoint."""
    if (b := _blocked(request, "show_reports")):
        return b
    doc = _client_document(request, ref)
    if not doc:
        return Response({"detail": "Not found."}, status=404)
    from . import client_report as cr
    data = cr.report_json(doc, doc.current_revision)
    if data is None:
        return Response({"detail": "This report has no viewer yet."},
                        status=404)
    return Response(data)


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_document_pdf(request, ref):
    """The same report rendered to PDF for the portal 'Download PDF' button."""
    from django.http import HttpResponse
    if (b := _blocked(request, "show_reports")):
        return b
    doc = _client_document(request, ref)
    if not doc:
        return Response({"detail": "Not found."}, status=404)
    from . import pdf
    pdf_bytes = pdf.document_pdf_bytes(doc, doc.current_revision)
    if pdf_bytes is None:
        return Response({"detail": "PDF is unavailable right now."}, status=503)
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{doc.ref}.pdf"'
    return resp


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_site_cameras(request, pk):
    """Cameras this client may watch on this site.

    Two independent gates, both of which must be open: the account-level
    `show_cameras` flag (HO admin can hide the whole section) and each
    camera's own `client_visible` (off by default, so a newly registered
    camera is internal until someone deliberately publishes it)."""
    if (b := _blocked(request, "show_cameras")):
        return b
    if pk not in client_site_ids(request.user):
        return Response({"detail": "Not found."}, status=404)
    from . import cameras as cam_svc
    status = cam_svc.relay_status()
    cams = Camera.objects.filter(site_id=pk, is_active=True,
                                 client_visible=True).select_related("site")
    return Response({
        # `on_demand` (not the URL, not the mode) so the portal does not tell
        # a client "Offline" about a camera that is merely idle waiting for a
        # viewer. No infrastructure detail leaves here.
        "cameras": [{"id": c.id, "name": c.name,
                     "location_note": c.location_note,
                     "on_demand": bool(c.source_url),
                     "online": bool((status.get(c.path) or {}).get("ready"))}
                    for c in cams],
        "relay_configured": bool(cam_svc.relay_public_base()),
    })


@api_view(["POST"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_camera_ticket(request, pk):
    """A ~90s ticket for one client-visible camera on one of their sites."""
    if (b := _blocked(request, "show_cameras")):
        return b
    from . import cameras as cam_svc
    cam = Camera.objects.filter(pk=pk, is_active=True,
                                client_visible=True).first()
    if not cam or cam.site_id not in client_site_ids(request.user):
        return Response({"detail": "Not found."}, status=404)
    if not cam_svc.relay_public_base():
        return Response({"detail": "Not found."}, status=404)
    return Response({
        "whep": cam_svc.whep_url(cam),
        "ticket": cam_svc.issue_ticket(cam, "client", request.user.id),
        "expires_in": cam_svc.TICKET_MAX_AGE,
    })
