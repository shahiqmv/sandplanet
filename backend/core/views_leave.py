"""Worker leave API — HR grants, HR marks the return (owner 2026-08-20)."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import leave as lv_svc
from .models import WorkerLeave
from .permissions import scoped_site_ids


def _guard(request):
    if not lv_svc.can_grant(request.user):
        return Response({"detail": "Only HR grants leave."}, status=403)
    return None


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def leaves(request):
    """GET: the leave register. POST: grant leave (HR)."""
    if request.method == "POST":
        err = _guard(request)
        if err:
            return err
        lv, msg = lv_svc.grant(request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(lv_svc.leave_dict(lv), status=201)

    qs = (WorkerLeave.objects.select_related("employee", "from_site",
                                             "granted_by")
          .order_by("-from_date", "-id"))
    # Site roles see only their own people; HO sees everyone.
    ids = scoped_site_ids(request.user)
    if ids is not None:
        qs = qs.filter(employee__site_allocations__site_id__in=ids).distinct()
    if request.GET.get("open") == "1":
        qs = qs.filter(returned_on__isnull=True, cancelled_at__isnull=True)
    if request.GET.get("employee_id"):
        qs = qs.filter(employee_id=request.GET["employee_id"])
    return Response([lv_svc.leave_dict(x) for x in qs[:300]])


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def leaves_overdue(request):
    """Open leave whose end date has passed — HR marks returns by hand, so a
    man back at work can sit on the Head Office register unnoticed."""
    return Response([lv_svc.leave_dict(x) for x in lv_svc.overdue()])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def leave_return(request, pk):
    err = _guard(request)
    if err:
        return err
    lv = WorkerLeave.objects.filter(pk=pk).select_related("employee").first()
    if lv is None:
        return Response({"detail": "Not found."}, status=404)
    on = request.data.get("on")
    if on:
        from datetime import date
        try:
            on = date.fromisoformat(str(on))
        except ValueError:
            return Response({"detail": "Invalid return date."}, status=400)
    msg = lv_svc.mark_returned(lv, request.user, on or None)
    if msg:
        return Response({"detail": msg}, status=400)
    lv.refresh_from_db()
    return Response(lv_svc.leave_dict(lv))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def leave_cancel(request, pk):
    err = _guard(request)
    if err:
        return err
    lv = WorkerLeave.objects.filter(pk=pk).select_related("employee").first()
    if lv is None:
        return Response({"detail": "Not found."}, status=404)
    msg = lv_svc.cancel(lv, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    lv.refresh_from_db()
    return Response(lv_svc.leave_dict(lv))
