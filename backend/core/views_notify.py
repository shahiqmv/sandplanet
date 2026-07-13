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
