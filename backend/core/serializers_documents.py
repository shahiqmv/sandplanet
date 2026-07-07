from rest_framework import serializers

from .models import Approval, Attachment, Document


class AttachmentSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = ["id", "kind", "file_name", "content_type", "size_bytes",
                  "caption", "url", "created_at"]

    def get_url(self, obj):
        request = self.context.get("request")
        url = obj.file.url
        return request.build_absolute_uri(url) if request else url


class ApprovalSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.full_name", read_only=True)

    class Meta:
        model = Approval
        fields = ["id", "action", "result", "actor_name", "actor_role",
                  "comment", "acted_at"]


class DocumentSerializer(serializers.ModelSerializer):
    site_code = serializers.CharField(source="site.code", read_only=True)
    site_name = serializers.CharField(source="site.name", read_only=True)
    payload = serializers.SerializerMethodField()
    rev_label = serializers.CharField(
        source="current_revision.rev_label", read_only=True
    )
    attachments = AttachmentSerializer(many=True, read_only=True)
    approvals = ApprovalSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(
        source="created_by.full_name", read_only=True
    )

    class Meta:
        model = Document
        fields = ["id", "doc_type", "ref", "site", "site_code", "site_name",
                  "doc_date", "status", "rev_label", "payload", "is_void",
                  "void_reason", "attachments", "approvals",
                  "created_by_name", "created_at"]

    def get_payload(self, obj):
        return obj.current_revision.payload if obj.current_revision else {}
