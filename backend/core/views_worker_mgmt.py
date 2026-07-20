"""Site worker-management API (site-worker-management tool): SA/SE raise
add / remove / transfer requests for a site's DIRECT workforce; the PM (and,
for a new hire, the Director) approve. See worker_mgmt.py for the rules."""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import worker_mgmt as wm
from .models import Employee, Site
from .models import WorkerChangeRequest as WCR
from .permissions import scoped_site_ids

VIEW_ALL = ("PM", "DIRECTOR", "ADMIN")          # see requests across all sites


def _can_see_all(user):
    return user.role in VIEW_ALL


def _scoped(user, qs, site_field="site_id"):
    if _can_see_all(user):
        return qs
    ids = scoped_site_ids(user)
    return qs.filter(**{f"{site_field}__in": ids or []})


def _site_for(request, site_id):
    try:
        site = Site.objects.get(pk=site_id)
    except (Site.DoesNotExist, TypeError, ValueError):
        return None, Response({"detail": "Unknown site."}, status=400)
    ids = scoped_site_ids(request.user)
    if ids is not None and site.id not in ids:
        return None, Response({"detail": "Not one of your sites."}, status=403)
    return site, None


def _req_json(req):
    emp = req.employee
    return {
        "id": req.id, "kind": req.kind, "status": req.status,
        "status_label": req.get_status_display(),
        "site_code": req.site.code,
        "to_site_code": req.to_site.code if req.to_site_id else None,
        "reason": req.reason, "decision_note": req.decision_note,
        "requested_by": req.requested_by.full_name if req.requested_by_id
        else "",
        "created_at": req.created_at,
        "employee": {
            "id": emp.id, "emp_no": emp.emp_no, "full_name": emp.full_name,
            "nationality": emp.nationality, "passport_no": emp.passport_no,
            "job_title": emp.job_category.name if emp.job_category_id else "",
            "job_category_id": emp.job_category_id,
            "basic_pay": emp.basic_pay, "currency": emp.currency,
            "employment_type": emp.employment_type,
            "work_permit_no": emp.work_permit_no,
            "work_permit_expiry": emp.work_permit_expiry,
            "join_date": emp.join_date,
        },
    }


@api_view(["GET"])
def worker_requests(request):
    if request.user.role not in ("SITE_ADMIN", "SITE_ENGINEER", *VIEW_ALL):
        return Response({"detail": "Not permitted."}, status=403)
    qs = WCR.objects.select_related(
        "site", "to_site", "employee__job_category", "requested_by")
    qs = _scoped(request.user, qs)
    if request.GET.get("site_id"):
        qs = qs.filter(site_id=request.GET["site_id"])
    if request.GET.get("open") == "1":
        qs = qs.filter(status__in=(WCR.Status.SUBMITTED, WCR.Status.PM_APPROVED,
                                   WCR.Status.RETURNED))
    return Response([_req_json(r) for r in qs[:200]])


@api_view(["GET"])
def site_direct_workers(request, site_id):
    """Active DIRECT workers at a site — the pick-list for remove / transfer."""
    site, err = _site_for(request, site_id)
    if err:
        return err
    qs = Employee.objects.filter(
        engagement_type=Employee.Engagement.DIRECT, is_active=True,
        site_allocations__site=site,
        site_allocations__to_date__isnull=True,
    ).select_related("job_category").order_by("emp_no").distinct()
    return Response([
        {"id": e.id, "emp_no": e.emp_no, "full_name": e.full_name,
         "nationality": e.nationality,
         "job_title": e.job_category.name if e.job_category_id else ""}
        for e in qs])


@api_view(["POST"])
def worker_add(request, site_id):
    if request.user.role not in wm.SITE_MANAGE_ROLES:
        return Response({"detail": "Site Admin / Engineer only."}, status=403)
    site, err = _site_for(request, site_id)
    if err:
        return err
    req, msg = wm.request_add_worker(site, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_req_json(req), status=201)


def _get_worker(request, emp_id):
    try:
        emp = Employee.objects.get(pk=emp_id)
    except Employee.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    ids = scoped_site_ids(request.user)
    if ids is not None and (emp.current_site_id() or 0) not in ids:
        return None, Response({"detail": "Not one of your sites."}, status=403)
    return emp, None


@api_view(["POST"])
def worker_remove(request, emp_id):
    if request.user.role not in wm.SITE_MANAGE_ROLES:
        return Response({"detail": "Site Admin / Engineer only."}, status=403)
    emp, err = _get_worker(request, emp_id)
    if err:
        return err
    req, msg = wm.request_remove_worker(emp, request.user,
                                        request.data.get("reason", ""))
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_req_json(req), status=201)


@api_view(["POST"])
def worker_transfer(request, emp_id):
    if request.user.role not in wm.SITE_MANAGE_ROLES:
        return Response({"detail": "Site Admin / Engineer only."}, status=403)
    emp, err = _get_worker(request, emp_id)
    if err:
        return err
    try:
        to_site = Site.objects.get(pk=request.data.get("to_site_id"))
    except (Site.DoesNotExist, TypeError, ValueError):
        return Response({"detail": "Choose a destination site."}, status=400)
    req, msg = wm.request_transfer_worker(emp, to_site, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_req_json(req), status=201)


def _get_request(request, pk):
    try:
        req = WCR.objects.select_related(
            "site", "to_site", "employee").get(pk=pk)
    except WCR.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    if not _can_see_all(request.user):
        ids = scoped_site_ids(request.user)
        if ids is not None and req.site_id not in ids:
            return None, Response({"detail": "Not found."}, status=404)
    return req, None


@api_view(["PATCH"])
def worker_request_edit(request, pk):
    req, err = _get_request(request, pk)
    if err:
        return err
    if request.user.role not in wm.SITE_MANAGE_ROLES:
        return Response({"detail": "Site Admin / Engineer only."}, status=403)
    req, msg = wm.update_add_request(req, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_req_json(req))


@api_view(["POST"])
def worker_request_action(request, pk):
    req, err = _get_request(request, pk)
    if err:
        return err
    action = request.data.get("action")
    note = request.data.get("note", "")
    if action == "approve":
        msg = wm.approve_request(req, request.user)
    elif action == "return":
        if not note.strip():
            return Response({"detail": "A note is required to return."},
                            status=400)
        msg = wm.return_request(req, request.user, note)
    elif action == "cancel":
        msg = wm.cancel_request(req, request.user)
    else:
        return Response({"detail": "Unknown action."}, status=400)
    if msg:
        return Response({"detail": msg}, status=400)
    req.refresh_from_db()
    return Response(_req_json(req))
