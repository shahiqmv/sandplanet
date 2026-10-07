"""The discussion on a document — API (`/api/v1/discussion/*`). Rules live
in core/discussion.py."""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import discussion as svc
from .models import CommentRecipient


def _target(request, key):
    obj = svc.target(key)
    if obj is None or not svc.can_see(request.user, key, obj):
        return None, Response({"detail": "Not found."}, status=404)
    return obj, None


@api_view(["GET", "POST"])
def thread(request, key):
    obj, err = _target(request, key)
    if err:
        return err
    if request.method == "POST":
        _, msg = svc.post(key, obj, request.user, request.data.get("body"),
                          to_ids=request.data.get("to") or [],
                          reply_to=request.data.get("reply_to"))
        if msg:
            return Response({"detail": msg}, status=400)
    return Response(svc.thread(key, obj, request.user))


@api_view(["GET"])
def people(request, key):
    obj, err = _target(request, key)
    if err:
        return err
    return Response({"people": svc.people(key, obj, request.GET.get("q", ""),
                                          exclude=request.user.id)})


@api_view(["POST"])
def answered(request, pk):
    rec = (CommentRecipient.objects.select_related("comment__author")
           .filter(pk=pk).first())
    if rec is None:
        return Response({"detail": "Not found."}, status=404)
    key = rec.comment.thread
    obj, err = _target(request, key)
    if err:
        return err
    msg = svc.mark_answered(rec, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(svc.thread(key, obj, request.user))


@api_view(["GET"])
def mine(request):
    """Follow-ups waiting on me — the My Tasks group, on its own."""
    items = svc.open_followups(request.user)
    return Response({"count": len(items), "items": items})
