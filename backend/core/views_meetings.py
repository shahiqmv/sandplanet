"""Meetings API — the calendar/log, minutes and action-item follow-up.
Custodians (PD/Admin) see everything; others see meetings they're part of."""
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from . import meetings as svc


def _get_visible(request, pk):
    m = svc.visible_meetings(request.user).filter(pk=pk).first()
    if m is None:
        return None, Response({"detail": "Not found."}, status=404)
    return m, None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def meeting_conflicts(request):
    """Which internal attendees are already booked over the proposed slot — the
    form calls this before saving to warn about a double-booking."""
    val = parse_datetime(request.data.get("scheduled_at") or "")
    if val is None:
        return Response({"conflicts": []})
    if timezone.is_naive(val):
        val = timezone.make_aware(val, svc.MALE_TZ)
    conflicts = svc.attendee_conflicts(
        val, request.data.get("duration_minutes") or 60,
        request.data.get("attendee_ids") or [],
        exclude_id=request.data.get("exclude_id"))
    return Response({"conflicts": conflicts})


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
                                       "can remove this."}, status=403)
        # ?hard=1 permanently deletes the record; otherwise cancel (keep on
        # record). Delete for a mistaken entry; cancel for one that won't happen.
        if request.query_params.get("hard") == "1":
            msg = svc.delete_meeting(m, request.user)
            if msg:
                return Response({"detail": msg}, status=403)
            return Response(status=204)
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


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def meeting_draft_minutes(request, pk):
    """Claude drafts minutes + action items from the organiser's rough notes.
    Returns the draft for review; the organiser edits and saves it themselves."""
    m, err = _get_visible(request, pk)
    if err:
        return err
    if not svc.can_manage(request.user, m):
        return Response({"detail": "Only the organiser or a custodian can "
                                   "draft the minutes."}, status=403)
    from . import meeting_minutes
    notes = request.data.get("notes") or ""
    minutes, actions, msg = meeting_minutes.draft_minutes(m, notes)
    if msg:
        return Response({"detail": msg}, status=400)
    # keep the raw notes on the meeting so the draft can be re-run/tweaked
    m.notes = notes
    m.save(update_fields=["notes", "updated_at"])
    return Response({"minutes": minutes, "action_items": actions})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def meeting_minutes_pdf(request, pk):
    m, err = _get_visible(request, pk)
    if err:
        return err
    from .views_commercial import _render_pdf
    return _render_pdf("pdf/meeting_minutes.html",
                       svc.minutes_pdf_context(m),
                       f"Minutes-{m.scheduled_at:%Y%m%d}")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def meeting_reschedule(request, pk):
    m, err = _get_visible(request, pk)
    if err:
        return err
    updated, msg = svc.reschedule_meeting(m, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(svc.meeting_dict(updated, detail=True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def meeting_audio(request, pk):
    m, err = _get_visible(request, pk)
    if err:
        return err
    _, msg = svc.add_audio(m, request.FILES.get("file"),
                           request.data.get("note"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(svc.meeting_dict(m, detail=True), status=201)


@api_view(["GET", "DELETE"])
@permission_classes([IsAuthenticated])
def meeting_audio_item(request, pk, audio_id):
    m, err = _get_visible(request, pk)
    if err:
        return err
    if request.method == "DELETE":
        msg = svc.delete_audio(m, audio_id, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(status=204)
    # GET → stream the recording to anyone who can see the meeting.
    from django.http import FileResponse

    from .models import MeetingAudio
    a = MeetingAudio.objects.filter(pk=audio_id, meeting=m).first()
    if a is None or not a.file:
        return Response({"detail": "Not found."}, status=404)
    resp = FileResponse(
        a.file.open("rb"),
        content_type=a.content_type or "application/octet-stream")
    resp["Content-Disposition"] = \
        f'inline; filename="{a.file_name or "recording"}"'
    return resp


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def meeting_send_invite(request, pk):
    m, err = _get_visible(request, pk)
    if err:
        return err
    if not svc.can_manage(request.user, m):
        return Response({"detail": "Only the organiser or a custodian can "
                                   "send invitations."}, status=403)
    from . import meeting_emails as em
    sent, skipped, msg = em.send_invite(m, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    d = svc.meeting_dict(m, detail=True)
    d.update({"sent": sent, "skipped": skipped,
              "email_configured": em.email_configured()})
    return Response(d)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def meeting_send_minutes(request, pk):
    m, err = _get_visible(request, pk)
    if err:
        return err
    if not svc.can_manage(request.user, m):
        return Response({"detail": "Only the organiser or a custodian can "
                                   "send minutes."}, status=403)
    from . import meeting_emails as em
    sent, msg = em.send_minutes(m, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    d = svc.meeting_dict(m, detail=True)
    d.update({"sent": sent, "email_configured": em.email_configured()})
    return Response(d)


@api_view(["GET"])
@permission_classes([AllowAny])
def meeting_rsvp(request, token):
    """One-click RSVP from an invite email — public, tokened, no login."""
    from django.http import HttpResponse

    from . import meeting_emails as em
    attendee, msg = em.record_rsvp(token, request.GET.get("r"))
    if msg:
        inner = f"<h2>{msg}</h2>"
    else:
        verb = {"ACCEPTED": "accepted", "DECLINED": "declined",
                "TENTATIVE": "tentatively accepted"}.get(attendee.rsvp, "")
        inner = ("<h2>Thank you — your response was recorded.</h2>"
                 f"<p>You have <b>{verb}</b> the invitation to "
                 f"“{attendee.meeting.title}”.</p>")
    return HttpResponse(
        "<html><body style='font-family:system-ui,sans-serif;max-width:480px;"
        "margin:64px auto;text-align:center;color:#1c2b36'>"
        f"{inner}</body></html>")


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def meeting_contacts(request):
    """The reusable external-guest contact book."""
    if request.method == "POST":
        c, msg = svc.upsert_contact(request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(svc.contact_dict(c), status=201)
    return Response({"contacts": [svc.contact_dict(c) for c in
                                  svc.list_contacts(request.query_params.get("q"))]})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def meeting_files(request, pk):
    m, err = _get_visible(request, pk)
    if err:
        return err
    _, msg = svc.add_attachment(m, request.FILES.get("file"), request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(svc.meeting_dict(m, detail=True), status=201)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def meeting_file_item(request, pk, file_id):
    m, err = _get_visible(request, pk)
    if err:
        return err
    msg = svc.delete_attachment(m, file_id, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(status=204)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_action_items(request):
    return Response({"items": svc.my_action_items(request.user)})
