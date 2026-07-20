"""Site worker-management API (site-worker-management tool): SA/SE raise
add / remove / transfer BATCHES for a site's DIRECT workforce; the PM (and,
for new hires, the Director) approve or return a whole batch. See
worker_mgmt.py for the rules."""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import worker_mgmt as wm
from .models import Employee, Site
from .models import WorkerChangeRequest as WCR
from .permissions import scoped_site_ids

VIEW_ALL = ("PM", "DIRECTOR", "ADMIN")          # see batches across all sites


def _can_see_all(user):
    return user.role in VIEW_ALL


def _site_for(request, site_id):
    try:
        site = Site.objects.get(pk=site_id)
    except (Site.DoesNotExist, TypeError, ValueError):
        return None, Response({"detail": "Unknown site."}, status=400)
    ids = scoped_site_ids(request.user)
    if ids is not None and site.id not in ids:
        return None, Response({"detail": "Not one of your sites."}, status=403)
    return site, None


def _emp_json(emp):
    return {
        "id": emp.id, "emp_no": emp.emp_no, "full_name": emp.full_name,
        "nationality": emp.nationality, "passport_no": emp.passport_no,
        "job_title": emp.job_category.name if emp.job_category_id else "",
        "job_category_id": emp.job_category_id,
        "basic_pay": emp.basic_pay, "currency": emp.currency,
        "employment_type": emp.employment_type,
        "work_permit_no": emp.work_permit_no,
        "work_permit_expiry": emp.work_permit_expiry,
        "join_date": emp.join_date, "hire_pending": emp.hire_pending,
    }


def _batch_json(batch):
    return {
        "id": batch.id, "kind": batch.kind, "status": batch.status,
        "status_label": batch.get_status_display(),
        "site_code": batch.site.code,
        "to_site_code": batch.to_site.code if batch.to_site_id else None,
        "reason": batch.reason, "decision_note": batch.decision_note,
        "requested_by": batch.requested_by.full_name
        if batch.requested_by_id else "",
        "created_at": batch.created_at, "worker_count": batch.worker_count,
        "workers": [_emp_json(i.employee) for i in
                    batch.items.select_related("employee__job_category").all()],
    }


@api_view(["GET"])
def worker_batches(request):
    if request.user.role not in ("SITE_ADMIN", "SITE_ENGINEER", *VIEW_ALL):
        return Response({"detail": "Not permitted."}, status=403)
    qs = WCR.objects.select_related("site", "to_site", "requested_by") \
        .prefetch_related("items__employee__job_category")
    if not _can_see_all(request.user):
        qs = qs.filter(site_id__in=(scoped_site_ids(request.user) or []))
    if request.GET.get("site_id"):
        qs = qs.filter(site_id=request.GET["site_id"])
    if request.GET.get("open") == "1":
        qs = qs.filter(status__in=wm.OPEN)
    return Response([_batch_json(b) for b in qs[:200]])


@api_view(["GET"])
def site_direct_workers(request, site_id):
    """Active DIRECT workers at a site — the pick-list for remove / transfer."""
    site, err = _site_for(request, site_id)
    if err:
        return err
    open_ids = set(Employee.objects.filter(
        change_items__request__status__in=wm.OPEN).values_list("id", flat=True))
    qs = Employee.objects.filter(
        engagement_type=Employee.Engagement.DIRECT, is_active=True,
        site_allocations__site=site,
        site_allocations__to_date__isnull=True,
    ).select_related("job_category").order_by("emp_no").distinct()
    return Response([
        {"id": e.id, "emp_no": e.emp_no, "full_name": e.full_name,
         "nationality": e.nationality,
         "job_title": e.job_category.name if e.job_category_id else "",
         "busy": e.id in open_ids}
        for e in qs])


@api_view(["POST"])
def create_batch(request, site_id):
    if request.user.role not in wm.SITE_MANAGE_ROLES:
        return Response({"detail": "Site Admin / Engineer only."}, status=403)
    site, err = _site_for(request, site_id)
    if err:
        return err
    kind = request.data.get("kind")
    if kind == "ADD":
        batch, msg = wm.create_add_batch(site, request.data.get("workers"),
                                         request.user)
    elif kind == "REMOVE":
        batch, msg = wm.create_remove_batch(
            site, request.data.get("employee_ids"), request.user,
            request.data.get("reason", ""))
    elif kind == "TRANSFER":
        try:
            to_site = Site.objects.get(pk=request.data.get("to_site_id"))
        except (Site.DoesNotExist, TypeError, ValueError):
            return Response({"detail": "Choose a destination site."},
                            status=400)
        batch, msg = wm.create_transfer_batch(
            site, request.data.get("employee_ids"), to_site, request.user)
    else:
        return Response({"detail": "kind must be ADD / REMOVE / TRANSFER."},
                        status=400)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_batch_json(batch), status=201)


def _get_batch(request, pk):
    try:
        batch = WCR.objects.select_related("site", "to_site").get(pk=pk)
    except WCR.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    if not _can_see_all(request.user):
        ids = scoped_site_ids(request.user)
        if ids is not None and batch.site_id not in ids:
            return None, Response({"detail": "Not found."}, status=404)
    return batch, None


@api_view(["POST"])
def batch_action(request, pk):
    batch, err = _get_batch(request, pk)
    if err:
        return err
    action = request.data.get("action")
    note = request.data.get("note", "")
    if action == "approve":
        msg = wm.approve_batch(batch, request.user)
    elif action == "return":
        if not note.strip():
            return Response({"detail": "A note is required to return."},
                            status=400)
        msg = wm.return_batch(batch, request.user, note)
    elif action == "resubmit":
        msg = wm.resubmit_batch(batch, request.user)
    elif action == "cancel":
        msg = wm.cancel_batch(batch, request.user)
    else:
        return Response({"detail": "Unknown action."}, status=400)
    if msg:
        return Response({"detail": msg}, status=400)
    batch.refresh_from_db()
    return Response(_batch_json(batch))


@api_view(["PATCH"])
def hire_edit(request, emp_id):
    if request.user.role not in wm.SITE_MANAGE_ROLES:
        return Response({"detail": "Site Admin / Engineer only."}, status=403)
    try:
        emp = Employee.objects.get(pk=emp_id)
    except Employee.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    ids = scoped_site_ids(request.user)
    site = wm._home_site(emp)
    home_id = site.id if site else emp.change_items.first().request.site_id \
        if emp.change_items.exists() else None
    if ids is not None and (home_id or 0) not in ids:
        return Response({"detail": "Not one of your sites."}, status=403)
    msg = wm.update_hire(emp, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(_emp_json(emp))
