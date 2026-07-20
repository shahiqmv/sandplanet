"""Subcontractor register + site-level team management API (subcontractor
module, Phase 2). The SA/SE manage their own site's subcontractors and workers;
PM / Director / Signatory / Finance / QS see the whole register (§7)."""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import subcontract
from .models import Employee, Site, Subcontractor
from .permissions import scoped_site_ids

VIEW_ALL = ("PM", "DIRECTOR", "SIGNATORY", "FINANCE", "QS", "ADMIN")


def _can_see_all(user):
    return user.role in VIEW_ALL


def _visible_subs(user):
    qs = Subcontractor.objects.select_related("site", "created_by")
    if _can_see_all(user):
        return qs
    return qs.filter(site_id__in=(scoped_site_ids(user) or []))


def _get_visible(request, pk):
    return _visible_subs(request.user).filter(pk=pk).first()


def _worker_json(emp):
    state = ("PENDING" if emp.sub_pending
             else "ACTIVE" if emp.is_active else "REMOVED")
    return {
        "id": emp.id, "emp_no": emp.emp_no, "full_name": emp.full_name,
        "nationality": emp.nationality,
        "job_title": emp.job_category.name if emp.job_category_id else "",
        "job_category_id": emp.job_category_id, "state": state,
    }


def _sub_json(sub, workers=False):
    data = {
        "id": sub.id, "name": sub.name, "site_id": sub.site_id,
        "site_code": sub.site.code, "registration_no": sub.registration_no,
        "contact_person": sub.contact_person, "phone": sub.phone,
        "bank_details": sub.bank_details, "notes": sub.notes,
        "status": sub.status, "status_label": sub.get_status_display(),
        "can_raise_sca": sub.can_raise_sca,
        "created_by": sub.created_by.full_name if sub.created_by_id else "",
        "created_at": sub.created_at,
        "worker_count": sub.workers.filter(is_active=True).count(),
        "pending_count": sub.workers.filter(sub_pending=True).count(),
    }
    if workers:
        data["workers"] = [_worker_json(w) for w in sub.workers
                           .select_related("job_category").order_by("full_name")]
    return data


@api_view(["GET", "POST"])
def subcontractors(request):
    if request.method == "POST":
        if request.user.role not in subcontract.SITE_MANAGE_ROLES:
            return Response({"detail": "Site Admin / Engineer only."},
                            status=403)
        try:
            site = Site.objects.get(pk=request.data.get("site_id"))
        except (Site.DoesNotExist, TypeError, ValueError):
            return Response({"detail": "A site is required."}, status=400)
        scoped = scoped_site_ids(request.user)
        if scoped is not None and site.id not in scoped:
            return Response({"detail": "Not one of your sites."}, status=403)
        sub, err = subcontract.create_subcontractor(site, request.data,
                                                    request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(_sub_json(sub), status=201)

    qs = _visible_subs(request.user)
    if request.GET.get("site_id"):
        qs = qs.filter(site_id=request.GET["site_id"])
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    return Response([_sub_json(s) for s in qs])


@api_view(["GET", "PATCH"])
def subcontractor_detail(request, pk):
    sub = _get_visible(request, pk)
    if sub is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "PATCH":
        if request.user.role not in subcontract.SITE_MANAGE_ROLES:
            return Response({"detail": "Site Admin / Engineer only."},
                            status=403)
        err = subcontract.update_subcontractor(sub, request.data, request.user)
        if err:
            return Response({"detail": err}, status=400)
    return Response(_sub_json(sub, workers=True))


@api_view(["POST"])
def subcontractor_action(request, pk):
    sub = _get_visible(request, pk)
    if sub is None:
        return Response({"detail": "Not found."}, status=404)
    action = request.data.get("action")
    if action == "approve":
        err = subcontract.approve_subcontractor(sub, request.user)
    elif action == "return":
        err = subcontract.return_subcontractor(
            sub, request.user, request.data.get("reason", ""))
    elif action in ("suspend", "close", "reactivate"):
        target = {"suspend": Subcontractor.Status.SUSPENDED,
                  "close": Subcontractor.Status.CLOSED,
                  "reactivate": Subcontractor.Status.APPROVED}[action]
        err = subcontract.set_subcontractor_status(sub, target, request.user)
    else:
        return Response({"detail": "Unknown action."}, status=400)
    if err:
        return Response({"detail": err}, status=400)
    return Response(_sub_json(sub, workers=True))


@api_view(["POST"])
def subcontractor_workers(request, pk):
    sub = _get_visible(request, pk)
    if sub is None:
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in subcontract.SITE_MANAGE_ROLES:
        return Response({"detail": "Site Admin / Engineer only."}, status=403)
    emp, err = subcontract.add_worker(sub, request.data, request.user)
    if err:
        return Response({"detail": err}, status=400)
    return Response(_worker_json(emp), status=201)


@api_view(["POST"])
def subcontract_worker_action(request, emp_id):
    try:
        emp = Employee.objects.select_related("subcontractor__site").get(
            pk=emp_id, engagement_type=Employee.Engagement.SUBCONTRACT)
    except Employee.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    sub = emp.subcontractor
    scoped = scoped_site_ids(request.user)
    if (sub and not _can_see_all(request.user)
            and scoped is not None and sub.site_id not in scoped):
        return Response({"detail": "Not one of your sites."}, status=403)
    action = request.data.get("action")
    if action == "approve":
        if request.user.role not in ("PM", "ADMIN"):
            return Response({"detail": "PM approval required."}, status=403)
        err = subcontract.approve_worker(emp, request.user)
    elif action == "remove":
        if request.user.role not in subcontract.SITE_MANAGE_ROLES + ("PM",):
            return Response({"detail": "Site team only."}, status=403)
        err = subcontract.remove_worker(emp, request.user)
    else:
        return Response({"detail": "Unknown action."}, status=400)
    if err:
        return Response({"detail": err}, status=400)
    return Response(_worker_json(emp))
