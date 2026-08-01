"""Meetings API — the calendar/log, minutes and action-item follow-up.
Custodians (PD/Admin) see everything; others see meetings they're part of."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import meetings as svc
from .models import Meeting


def _get_visible(request, pk):
    m = svc.visible_meetings(request.user).filter(pk=pk).first()
    if m is None:
        return None, Response({"detail": "Not found."}, status=404)
    return m, None


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def meetings(request):
    if request.method == "POST":
        if request.user.role not in svc.CREATE_ROLES:
            return Response({"detail": "You can't schedule meetings."},
                            status=403)
        m, msg = svc.create_meeting(request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(svc.meeting_dict(m, detail=True), status=201)
    qs = svc.visible_meetings(request.user)
    p = request.query_params
    if p.get("type"):
        qs = qs.filter(meeting_type=p["type"])
    if p.get("status"):
        qs = qs.filter(status=p["status"])
    if p.get("project"):
        qs = qs.filter(project_id=p["project"])
    if p.get("site"):
        qs = qs.filter(site_id=p["site"])
    if p.get("upcoming") == "1":
        from django.utils import timezone
        qs = qs.filter(scheduled_at__gte=timezone.now(),
                       status="SCHEDULED").order_by("scheduled_at")
    return Response({"meetings": [svc.meeting_dict(m) for m in qs[:300]],
                     "can_create": request.user.role in svc.CREATE_ROLES,
                     "is_custodian": svc.is_custodian(request.user)})


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def meeting_detail(request, pk):
    m, err = _get_visible(request, pk)
    if err:
        return err
    if request.method == "GET":
        d = svc.meeting_dict(m, detail=True)
        d["can_manage"] = svc.can_manage(request.user, m)
        return Response(d)
    if request.method == "DELETE":
        if not svc.can_manage(request.user, m):
            return Response({"detail": "Only the organiser or a custodian "
                                       "can cancel this."}, status=403)
        m.status = "CANCELLED"
        m.save(update_fields=["status", "updated_at"])
        return Response(svc.meeting_dict(m, detail=True))
    updated, msg = svc.update_meeting(m, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(svc.meeting_dict(updated, detail=True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def meeting_actions(request, pk):
    m, err = _get_visible(request, pk)
    if err:
        return err
    msg = svc.set_action_items(m, request.data.get("rows") or [], request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(svc.meeting_dict(m, detail=True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def meeting_close(request, pk):
    m, err = _get_visible(request, pk)
    if err:
        return err
    _, nxt, msg = svc.close_meeting(m, request.user,
                                    spawn_next=request.data.get(
                                        "spawn_next", True))
    if msg:
        return Response({"detail": msg}, status=400)
    return Response({"meeting": svc.meeting_dict(m, detail=True),
                     "next": svc.meeting_dict(nxt) if nxt else None})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_action_items(request):
    return Response({"items": svc.my_action_items(request.user)})
