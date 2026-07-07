from rest_framework import serializers

from .models import Approval, Attachment, Document, DocumentLine, Item, PendingItem


class ItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Item
        fields = ["id", "code", "description", "unit", "category", "brand",
                  "spec_ref", "notes", "is_active", "merged_into"]
        read_only_fields = ["code", "merged_into"]


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


class DocumentLineSerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source="item.code", read_only=True,
                                      default=None)
    description = serializers.CharField(read_only=True)
    is_free_text = serializers.SerializerMethodField()

    class Meta:
        model = DocumentLine
        fields = ["id", "line_no", "item", "item_code", "description",
                  "free_text_desc", "is_free_text", "unit",
                  "qty_required", "qty_stock", "qty_to_order",
                  "qty_loaded", "qty_pending", "qty_manifest", "qty_received",
                  "priority", "urgent_reason", "rate", "amount",
                  "amount_cash", "amount_credit", "vendor", "quotation_ref",
                  "payment_terms", "action_taken", "is_changed", "remarks"]

    def get_is_free_text(self, obj):
        return obj.item_id is None  # flagged "new item — not in catalog"


class DocumentSerializer(serializers.ModelSerializer):
    site_code = serializers.CharField(source="site.code", read_only=True)
    site_name = serializers.CharField(source="site.name", read_only=True)
    payload = serializers.SerializerMethodField()
    rev_label = serializers.CharField(
        source="current_revision.rev_label", read_only=True
    )
    lines = serializers.SerializerMethodField()
    links = serializers.SerializerMethodField()
    revisions = serializers.SerializerMethodField()
    attachments = AttachmentSerializer(many=True, read_only=True)
    approvals = ApprovalSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(
        source="created_by.full_name", read_only=True
    )
    previous_ir_ref = serializers.CharField(source="previous_ir.ref",
                                            read_only=True, default=None)
    supplier_name = serializers.CharField(source="supplier.name",
                                          read_only=True, default=None)
    resubmitted_as = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = ["id", "doc_type", "ref", "site", "site_code", "site_name",
                  "doc_date", "status", "rev_label", "payload", "lines",
                  "links", "revisions", "is_void", "void_reason",
                  "previous_ir_ref", "resubmitted_as", "supplier_name",
                  "attachments", "approvals", "created_by_name", "created_at"]

    def get_resubmitted_as(self, obj):
        if obj.doc_type != "IR":
            return None
        child = Document.objects.filter(previous_ir=obj, is_void=False).first()
        return child.ref if child else None

    def get_payload(self, obj):
        return obj.current_revision.payload if obj.current_revision else {}

    def get_lines(self, obj):
        if not obj.current_revision:
            return []
        qs = obj.current_revision.lines.select_related("item")
        return DocumentLineSerializer(qs, many=True).data

    def get_links(self, obj):
        out = []
        for link in obj.links_from.select_related("to_document"):
            out.append({"type": link.link_type, "ref": link.to_document.ref,
                        "direction": "to"})
        for link in obj.links_to.select_related("from_document"):
            out.append({"type": link.link_type, "ref": link.from_document.ref,
                        "direction": "from"})
        return out

    def get_revisions(self, obj):
        return [
            {"rev_label": r.rev_label, "is_current": r.is_current,
             "issued_at": r.issued_at}
            for r in obj.revisions.order_by("id")
        ]


class PendingItemSerializer(serializers.ModelSerializer):
    site_code = serializers.CharField(source="site.code", read_only=True)
    item_code = serializers.CharField(source="item.code", read_only=True,
                                      default=None)
    description = serializers.SerializerMethodField()
    lm_ref = serializers.CharField(source="lm_line.revision.document.ref",
                                   read_only=True)
    pr_ref = serializers.CharField(source="pr_document.ref", read_only=True,
                                   default=None)
    cleared_lm_ref = serializers.CharField(source="cleared_lm.ref",
                                           read_only=True, default=None)

    class Meta:
        model = PendingItem
        fields = ["id", "site_code", "lm_ref", "pr_ref", "item_code",
                  "description", "unit", "qty_pending", "reason",
                  "action_next", "status", "cleared_date", "cleared_lm_ref",
                  "cleared_reason", "created_at"]
        read_only_fields = ["site_code", "lm_ref", "pr_ref", "item_code",
                            "description", "unit", "qty_pending", "status",
                            "cleared_date", "cleared_lm_ref", "created_at"]

    def get_description(self, obj):
        return obj.item.description if obj.item else obj.free_text_desc
