from rest_framework import serializers

from .models import Approval, Attachment, Document, DocumentLine, Item, PendingItem


class ItemSerializer(serializers.ModelSerializer):
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = ["id", "code", "description", "unit", "category", "brand",
                  "spec_ref", "notes", "is_active", "is_major",
                  "is_provisional", "photo", "photo_url", "merged_into"]
        read_only_fields = ["code", "merged_into", "photo_url",
                            "is_provisional"]
        extra_kwargs = {"photo": {"write_only": True, "required": False}}

    def get_photo_url(self, obj):
        return obj.photo.url if obj.photo else None

    def validate_category(self, value):
        # Category is a controlled list (owner, 2026-07-08): must be blank
        # or an active ItemCategory managed on its own page.
        from .models import ItemCategory

        if value and not ItemCategory.objects.filter(
                name=value, is_active=True).exists():
            raise serializers.ValidationError(
                f"'{value}' is not a known item category — add it on the "
                "Item Categories page first.")
        return value


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
    item_photo_url = serializers.SerializerMethodField()
    item_is_major = serializers.BooleanField(source="item.is_major",
                                             read_only=True, default=False)

    class Meta:
        model = DocumentLine
        fields = ["id", "line_no", "item", "item_code", "description",
                  "free_text_desc", "is_free_text", "unit",
                  "item_photo_url", "item_is_major",
                  "qty_required", "qty_stock", "qty_to_order",
                  "qty_loaded", "qty_pending", "qty_manifest", "qty_received",
                  "priority", "urgent_reason", "rate", "amount",
                  "amount_cash", "amount_credit", "vendor", "quotation_ref",
                  "payment_terms", "action_taken", "po_ref", "is_changed",
                  "spec", "mar_ref", "remarks"]

    def get_is_free_text(self, obj):
        return obj.item_id is None  # flagged "new item — not in catalog"

    def get_item_photo_url(self, obj):
        # A photo attached to THIS line (free-text items) wins; otherwise the
        # catalog item's own photo.
        line_photo = obj.attachments.filter(kind="PHOTO").order_by("-id").first()
        if line_photo:
            return line_photo.file.url
        return obj.item.photo.url if obj.item_id and obj.item.photo else None


class DocumentSerializer(serializers.ModelSerializer):
    site_code = serializers.CharField(source="site.code", read_only=True)
    site_name = serializers.CharField(source="site.name", read_only=True)
    project_code = serializers.CharField(source="project.code",
                                         read_only=True, default=None)
    project_title = serializers.CharField(source="project.title",
                                          read_only=True, default=None)
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
    payment_request = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = ["id", "doc_type", "ref", "site", "site_code", "site_name",
                  "project", "project_code", "project_title",
                  "doc_date", "status", "rev_label", "payload", "lines",
                  "links", "revisions", "is_void", "void_reason",
                  "previous_ir_ref", "resubmitted_as", "supplier_name",
                  "payment_request",
                  "attachments", "approvals", "created_by_name", "created_at"]

    def get_payment_request(self, obj):
        if obj.doc_type != "PYR" or not hasattr(obj, "payment_request"):
            return None
        pr = obj.payment_request
        return {
            "payment_type": pr.payment_type, "cost_head": pr.cost_head.name,
            "cost_head_id": pr.cost_head_id, "payee": pr.payee,
            "payment_method": pr.payment_method,
            "payee_account": pr.payee_account, "currency": pr.currency,
            "origin": pr.origin, "fx_rate": pr.fx_rate,
            "amount_requested": pr.amount_requested,
            "required_by": pr.required_by, "purpose": pr.purpose,
            "is_urgent": pr.is_urgent, "urgent_reason": pr.urgent_reason,
            "has_supporting_doc": pr.has_supporting_doc,
            "no_doc_reason": pr.no_doc_reason,
            "authorised_by": pr.authorised_by.full_name
            if pr.authorised_by else None,
            "authorised_at": pr.authorised_at,
            "authorised_under_threshold": pr.authorised_under_threshold,
            "returned_reason": pr.returned_reason,
            "returned_note": pr.returned_note,
            "amount_paid": pr.amount_paid, "paid_date": pr.paid_date,
            "payment_ref": pr.payment_ref,
            "variance_reason": pr.variance_reason,
            "withdrawn_reason": pr.withdrawn_reason,
            "salary_advances": [
                {"employee": a.employee.full_name,
                 "emp_no": a.employee.emp_no, "kind": a.kind,
                 "amount": a.amount, "months": a.months,
                 "period": f"{a.period_year}-{a.period_month:02d}"}
                for a in obj.salary_advances.select_related("employee").all()
            ],
        }

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
