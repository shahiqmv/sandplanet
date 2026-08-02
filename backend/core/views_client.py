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
from .models import ClientSession, ClientUser, Document, Site


def _client_dict(c):
    return {
        "full_name": c.full_name, "org_name": c.org_name, "email": c.email,
        "must_change_password": c.must_change_password,
        "sites": [{"id": s.id, "code": s.code, "name": s.name}
                  for s in c.sites.all().order_by("code")],
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
    return Response([
        {"id": s.id, "code": s.code, "name": s.name,
         "status": s.status,
         "has_cameras": False}          # cameras: Phase-later, always false now
        for s in request.user.sites.all().order_by("code")])


def _site_schedule(site):
    from .models import ProcurementSchedule
    return (ProcurementSchedule.objects
            .filter(document__site=site, document__is_void=False)
            .select_related("document", "project")
            .order_by("-document__doc_date").first())


def _inbound_and_summary(site):
    """Upcoming deliveries + a procurement summary, from the project's schedule
    — reusing the vetted client-facing `client_plan` allowlist. Rows with an
    ETA that aren't delivered yet are 'coming to site'."""
    sched = _site_schedule(site)
    if not sched:
        return [], {"available": False}
    from . import procurement_client as pc
    rows = [r for sec in pc.client_plan(sched)["sections"] for r in sec["rows"]]
    inbound = sorted(
        [{"description": r.get("description"), "quantity": r.get("quantity"),
          "uom": r.get("uom"), "eta": r.get("eta"),
          "stage": r.get("shipment"), "status": r.get("status")}
         for r in rows if r.get("eta")
         and (r.get("delivery") or "").lower() not in
         ("delivered", "received", "done", "complete", "—", "")],
        key=lambda x: str(x["eta"]))
    return inbound[:12], {"available": True, "items": len(rows),
                          "upcoming": len(inbound)}


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_site(request, pk):
    """A client's own site dashboard — allowlisted, read-only, no commercial or
    internal data. A site outside their set is a 404, never a 403."""
    if pk not in client_site_ids(request.user):
        return Response({"detail": "Not found."}, status=404)
    site = Site.objects.get(pk=pk)
    from .views_hr import site_manpower_data
    mp = site_manpower_data(site)
    dprs = Document.objects.filter(
        site=site, doc_type="DPR", is_void=False,
        status__in=("ISSUED", "VERIFIED")).order_by("-doc_date")[:14]
    tws = Document.objects.filter(
        site=site, doc_type="TWS", is_void=False,
        status__in=("ISSUED", "ACKNOWLEDGED")).order_by("-doc_date")[:14]
    inbound, proc = _inbound_and_summary(site)
    head = mp["present"] if mp["attendance_entered"] else mp["roster_total"]
    return Response({
        "site": {"id": site.id, "code": site.code, "name": site.name,
                 "status": site.status},
        "summary": {
            "date": date.today(),
            "workforce": head,
            "workforce_label": ("on site today" if mp["attendance_entered"]
                                else "assigned to site"),
            "latest_report": dprs[0].doc_date if dprs else None,
            "next_delivery": inbound[0]["eta"] if inbound else None,
        },
        # Trade breakdown for today (counts only — no names, no engagement type).
        "manpower": {
            "total": head, "attendance_entered": mp["attendance_entered"],
            "by_trade": [{"trade": c["name"],
                          "count": c["present"] if mp["attendance_entered"]
                          else c["roster"]}
                         for c in mp["categories"]
                         if (c["present"] if mp["attendance_entered"]
                             else c["roster"]) > 0],
        },
        "inbound": inbound,
        "procurement": proc,
        "recent_progress": [
            {"date": d.doc_date, "ref": d.ref, "verified": d.status == "VERIFIED"}
            for d in dprs],
        "recent_works": [
            {"date": d.doc_date, "ref": d.ref, "status": d.status}
            for d in tws],
        "cameras": {"available": False, "coming_soon": True},
    })


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_site_procurement(request, pk):
    """The full client procurement plan for the client's own site — the same
    allowlist the public share link uses, served inside the portal."""
    if pk not in client_site_ids(request.user):
        return Response({"detail": "Not found."}, status=404)
    site = Site.objects.get(pk=pk)
    sched = _site_schedule(site)
    if not sched:
        return Response({"available": False})
    from . import procurement_client as pc
    return Response({"available": True, **pc.client_plan(sched)})


@api_view(["GET"])
@authentication_classes([ClientTokenAuthentication])
@permission_classes([IsClient])
def client_site_procurement_xlsx(request, pk):
    """The procurement plan as a spreadsheet — same client allowlist as the
    public share link, but served through the authenticated portal."""
    from django.http import HttpResponse
    if pk not in client_site_ids(request.user):
        return Response({"detail": "Not found."}, status=404)
    site = Site.objects.get(pk=pk)
    sched = _site_schedule(site)
    if not sched:
        return Response({"detail": "No plan."}, status=404)
    from . import procurement_export
    wb = procurement_export.build_client_xlsx(sched)
    resp = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument."
        "spreadsheetml.sheet")
    resp["Content-Disposition"] = (
        f'attachment; filename="{sched.project.code}-Procurement-Plan.xlsx"')
    wb.save(resp)
    return resp
