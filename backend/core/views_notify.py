"""In-app notification centre (the bell)."""
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "title", "body", "doc_ref", "doc_type", "category",
                  "read_at", "created_at"]


@api_view(["GET"])
def notifications_list(request):
    qs = Notification.objects.filter(recipient=request.user)[:30]
    unread = Notification.objects.filter(
        recipient=request.user, read_at__isnull=True).count()
    return Response({"unread": unread,
                     "items": NotificationSerializer(qs, many=True).data})


@api_view(["POST"])
def notifications_read(request):
    """Mark notifications read — a list of ids, or all when none given."""
    qs = Notification.objects.filter(recipient=request.user,
                                     read_at__isnull=True)
    ids = request.data.get("ids")
    if ids:
        qs = qs.filter(id__in=ids)
    qs.update(read_at=timezone.now())
    return Response({"ok": True})


# ---- Desktop web push ----------------------------------------------------
# The same PushSubscription store Planet Mobile uses, reached with the desktop
# app's session auth and tagged DESKTOP so clicks open the desktop views.

@api_view(["GET"])
def push_key(request):
    from .push import vapid_public_key
    key = vapid_public_key()
    return Response({"public_key": key, "enabled": bool(key)})


@api_view(["POST"])
def push_subscribe(request):
    """Register this browser's push endpoint. Body: {endpoint, keys:{p256dh,
    auth}}."""
    from .models import PushSubscription
    endpoint = (request.data.get("endpoint") or "").strip()
    keys = request.data.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        return Response({"detail": "endpoint + keys are required."}, status=400)
    sub, _ = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={"user": request.user, "platform": "DESKTOP",
                  "p256dh": keys["p256dh"][:200],
                  "auth": keys["auth"][:100],
                  "label": (request.META.get("HTTP_USER_AGENT") or "")[:120]})
    return Response({"id": sub.id}, status=201)


@api_view(["POST"])
def push_unsubscribe(request):
    from .models import PushSubscription
    endpoint = (request.data.get("endpoint") or "").strip()
    PushSubscription.objects.filter(user=request.user,
                                    endpoint=endpoint).delete()
    return Response({"ok": True})
