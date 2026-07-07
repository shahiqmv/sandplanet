from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user per design §2 `users`: one role per user, admin-managed."""

    class Role(models.TextChoices):
        SITE_ENGINEER = "SITE_ENGINEER", "Site Engineer"
        SITE_ADMIN = "SITE_ADMIN", "Site Admin / Storekeeper"
        PM = "PM", "Project Manager"
        HO_PURCHASING = "HO_PURCHASING", "HO Purchasing"
        DIRECTOR = "DIRECTOR", "Sr PM / Director, Projects"
        HO_HR = "HO_HR", "HO HR / Payroll"
        ADMIN = "ADMIN", "Admin"

    # Roles with all-site read scope (spec §3)
    HO_ROLES = {"HO_PURCHASING", "DIRECTOR", "HO_HR", "ADMIN"}
    SINGLE_SITE_ROLES = {"SITE_ENGINEER", "SITE_ADMIN"}

    role = models.CharField(max_length=20, choices=Role.choices)
    full_name = models.TextField()
    # employee FK added in M5 (employees module)

    REQUIRED_FIELDS = ["full_name", "role"]

    @property
    def is_ho(self) -> bool:
        return self.role in self.HO_ROLES

    def allocated_site_ids(self):
        """Open allocations only (to_date null)."""
        return list(
            self.site_allocations.filter(to_date__isnull=True).values_list(
                "site_id", flat=True
            )
        )


def default_working_days():
    return [6, 7, 1, 2, 3, 4]


class Site(models.Model):
    """A site IS a project (spec §2). Created at award, closed at completion."""

    class Status(models.TextChoices):
        AWARDED = "AWARDED"
        ACTIVE = "ACTIVE"
        ON_HOLD = "ON_HOLD"
        CLOSED = "CLOSED"

    # Valid lifecycle transitions (spec §2.2). CLOSED→ACTIVE = reopen, Admin only.
    TRANSITIONS = {
        Status.AWARDED: {Status.ACTIVE, Status.ON_HOLD},
        Status.ACTIVE: {Status.ON_HOLD, Status.CLOSED},
        Status.ON_HOLD: {Status.ACTIVE, Status.CLOSED},
        Status.CLOSED: {Status.ACTIVE},
    }

    code = models.CharField(max_length=6, unique=True)  # immutable after first doc
    name = models.TextField()
    is_head_office = models.BooleanField(default=False)  # MLE special record
    scope = models.TextField(blank=True)
    contract_value = models.DecimalField(  # sensitive: HO/Admin/assigned PM only
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    currency = models.CharField(max_length=3, default="MVR")
    award_date = models.DateField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    duration_days = models.IntegerField(null=True, blank=True)
    planned_completion = models.DateField(null=True, blank=True)
    actual_completion = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.AWARDED
    )
    client_name = models.TextField(blank=True)
    client_contact = models.TextField(blank=True)
    client_designation = models.TextField(blank=True)
    client_phone = models.TextField(blank=True)
    client_email = models.TextField(blank=True)
    consultant_name = models.TextField(blank=True)
    consultant_contact = models.TextField(blank=True)
    working_hours_from = models.TimeField(default="07:00")
    working_hours_to = models.TimeField(default="18:00")
    # ISO dow list; default Sat–Thu, Fri off (decision 5). JSON for SQLite compat.
    working_days = models.JSONField(default=default_working_days)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.code} — {self.name}"

    def current_pm(self):
        row = (
            self.pm_history.filter(to_date__isnull=True)
            .order_by("-from_date")
            .select_related("pm_user")
            .first()
        )
        return row.pm_user if row else None


class SitePmHistory(models.Model):
    """Who is/was project PM; latest open row = current (design §2)."""

    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="pm_history")
    pm_user = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="pm_site_history"
    )
    from_date = models.DateField()
    to_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "site PM history"


class UserSiteAllocation(models.Model):
    """SITE_* users: exactly one open row; PM: one or more (design §2)."""

    user = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="site_allocations"
    )
    site = models.ForeignKey(
        Site, on_delete=models.PROTECT, related_name="user_allocations"
    )
    from_date = models.DateField()
    to_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "site", "from_date"], name="uniq_allocation"
            )
        ]


class Holiday(models.Model):
    site = models.ForeignKey(  # NULL = company-wide
        Site, on_delete=models.PROTECT, null=True, blank=True, related_name="holidays"
    )
    day = models.DateField()
    name = models.TextField(blank=True)


class ManpowerCategory(models.Model):
    """Two company-wide lists (decision 4): DPR (fine) and TWS (coarse)."""

    LIST_TYPES = [("DPR", "DPR"), ("TWS", "TWS")]
    GROUPS = [("STAFF", "Staff"), ("LABOUR", "Trades/Labour")]

    list_type = models.CharField(max_length=3, choices=LIST_TYPES)
    grp = models.CharField(max_length=10, choices=GROUPS)
    name = models.TextField()
    sort_order = models.IntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "manpower categories"
        constraints = [
            models.UniqueConstraint(
                fields=["list_type", "name"], name="uniq_category_per_list"
            )
        ]
        ordering = ["list_type", "grp", "sort_order"]


class CompanyParameter(models.Model):
    """OT multiplier, hourly-rate divisor, etc. (spec §6A.3)."""

    key = models.CharField(max_length=60, primary_key=True)
    value = models.JSONField()
    description = models.TextField(blank=True)


class AuditLog(models.Model):
    """Append-only (spec §7.2 / NFR). Never updated or deleted in app code;
    on Postgres the app DB role additionally gets no UPDATE/DELETE grant."""

    entity = models.CharField(max_length=30)
    entity_id = models.BigIntegerField()
    event = models.CharField(max_length=40)
    from_state = models.TextField(blank=True)
    to_state = models.TextField(blank=True)
    actor = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True)
    detail = models.JSONField(null=True, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at"]


# ===== Documents (design §2, spec §4/§5/§7) =====


class DocCounter(models.Model):
    """Gap-free numbering: row-locked (SELECT FOR UPDATE) at ref issue."""

    doc_type = models.CharField(max_length=3)
    site = models.ForeignKey(  # NULL for global PR/LM
        Site, on_delete=models.PROTECT, null=True, blank=True
    )
    last_no = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["doc_type", "site"], name="uniq_counter")
        ]


class Document(models.Model):
    class Type(models.TextChoices):
        DPR = "DPR"
        TWS = "TWS"
        IR = "IR"
        MAR = "MAR"
        MR = "MR"
        GRN = "GRN"
        PR = "PR"
        LM = "LM"

    # Per-type state machines (spec §7.1). Void is a flag, not a state.
    TRANSITIONS = {
        "DPR": {"DRAFT": {"ISSUED"}, "ISSUED": {"VERIFIED"}},
        "TWS": {"DRAFT": {"ISSUED"}, "ISSUED": {"ACKNOWLEDGED"}},
        "IR": {
            "DRAFT": {"SUBMITTED"},
            "SUBMITTED": {"PM_APPROVED", "DRAFT"},  # DRAFT = returned
            "PM_APPROVED": {"ISSUED"},
            # Client result (recorded in-app by the site team, decision 1)
            "ISSUED": {"APPROVED", "APPROVED_WITH_COMMENTS", "REJECTED"},
            # Part C closure for Approved-with-Comments (spec §5.3)
            "APPROVED_WITH_COMMENTS": {"CLOSED_BY_PM"},
            "CLOSED_BY_PM": {"CLOSED"},
            # REJECTED is terminal: resubmit = NEW IR quoting previous (§4.2)
        },
        "MAR": {
            "DRAFT": {"SUBMITTED"},
            "SUBMITTED": {"PM_APPROVED", "DRAFT"},
            "PM_APPROVED": {"ISSUED"},
            "ISSUED": {"APPROVED", "APPROVED_WITH_COMMENTS",
                       "REVISE_RESUBMIT", "REJECTED"},
            # REVISE_RESUBMIT → new revision, same number, restart at DRAFT
        },
        "MR": {
            "DRAFT": {"SUBMITTED"},
            "SUBMITTED": {"PM_APPROVED", "DRAFT"},  # DRAFT = returned
            "PM_APPROVED": {"SENT_TO_HO"},
            "SENT_TO_HO": {"PR_RAISED", "LOADING_PLANNED"},
            "PR_RAISED": {"LOADING_PLANNED"},
            "LOADING_PLANNED": {"PARTIALLY_LOADED", "LOADED"},
            "PARTIALLY_LOADED": {"PARTIALLY_LOADED", "LOADED", "CLOSED"},
            "LOADED": {"CLOSED"},
        },
        "PR": {
            "DRAFT": {"SUBMITTED", "CANCELLED"},
            "SUBMITTED": {"APPROVED", "DRAFT", "REJECTED", "CANCELLED"},
            "APPROVED": {"PAYMENT_PROCESSING", "PAID_PO_ISSUED"},
            "PAYMENT_PROCESSING": {"PAID_PO_ISSUED"},
            "PAID_PO_ISSUED": {"CLOSED"},
        },
        "LM": {
            "DRAFT": {"LOADING", "DEPARTED"},
            "LOADING": {"DEPARTED"},
            # DEPARTED shown as In Transit; final states set by the site's GRN
            "DEPARTED": {"RECEIVED", "RECEIVED_WITH_SHORTAGE"},
        },
        "GRN": {
            "DRAFT": {"COUNTED"},
            "COUNTED": {"COMPLETE", "SHORTAGE_REPORTED"},
        },
    }

    doc_type = models.CharField(max_length=3, choices=Type.choices)
    ref = models.CharField(max_length=20, unique=True)  # DPR-SJR-001 / PR-014
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="documents")
    doc_date = models.DateField()  # the form's principal date
    status = models.CharField(max_length=30, default="DRAFT")
    current_revision = models.ForeignKey(
        "DocumentRevision", on_delete=models.PROTECT, null=True, blank=True,
        related_name="+",
    )
    previous_ir = models.ForeignKey(  # IR resubmission chain (spec §4.2)
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    is_void = models.BooleanField(default=False)
    void_reason = models.TextField(blank=True)
    voided_by = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="documents_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["doc_type", "site", "doc_date"])]

    def __str__(self):
        return self.ref


class DocumentRevision(models.Model):
    """Immutable snapshot once issued_at is set (spec §7.2)."""

    document = models.ForeignKey(
        Document, on_delete=models.PROTECT, related_name="revisions"
    )
    rev_label = models.CharField(max_length=4, default="R0")
    payload = models.JSONField()  # full form contents (design payload-vs-columns rule)
    is_current = models.BooleanField(default=True)
    issued_at = models.DateTimeField(null=True, blank=True)  # set at issue → locks it
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document", "rev_label"], name="uniq_revision_label"
            )
        ]


class Approval(models.Model):
    """Every workflow action, immutable (spec §7.2)."""

    document = models.ForeignKey(
        Document, on_delete=models.PROTECT, related_name="approvals"
    )
    revision = models.ForeignKey(
        DocumentRevision, on_delete=models.PROTECT, null=True, blank=True,
        related_name="approvals",
    )
    action = models.CharField(max_length=30)  # SUBMIT/APPROVE/RETURN/ISSUE/VERIFY/...
    result = models.CharField(max_length=40, blank=True)  # client results
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    actor_role = models.CharField(max_length=20)
    comment = models.TextField(blank=True)
    acted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["acted_at"]


def attachment_path(instance, filename):
    ref = instance.document.ref if instance.document else "misc"
    if instance.kind == "GENERATED_PDF":  # design §4: pdf/{ref}/{rev}-{milestone}.pdf
        return f"pdf/{ref}/{filename}"
    return f"attachments/{ref}/{filename}"


class Attachment(models.Model):
    KINDS = [
        ("PHOTO", "Photo"), ("ENCLOSURE", "Enclosure"), ("QUOTATION", "Quotation"),
        ("EVIDENCE", "Evidence"), ("GENERATED_PDF", "Generated PDF"),
    ]

    document = models.ForeignKey(
        Document, on_delete=models.PROTECT, null=True, blank=True,
        related_name="attachments",
    )
    revision = models.ForeignKey(
        DocumentRevision, on_delete=models.PROTECT, null=True, blank=True,
        related_name="attachments",
    )
    kind = models.CharField(max_length=20, choices=KINDS)
    file = models.FileField(upload_to=attachment_path)
    file_name = models.TextField(blank=True)
    content_type = models.TextField(blank=True)
    size_bytes = models.BigIntegerField(default=0)
    caption = models.TextField(blank=True)  # DPR photo captions
    uploaded_by = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)


# ===== Item master (spec §5.0) & procurement chain (§5.5–§5.8, §6) =====


class Item(models.Model):
    """Company-wide catalog, owned by HO Purchasing. Units fixed per item;
    a product handled in two units = two catalog entries (spec §5.0)."""

    code = models.CharField(max_length=12, unique=True)  # ITM-00412, server-issued
    description = models.TextField()
    unit = models.CharField(max_length=10)
    category = models.TextField(blank=True)  # trade/discipline
    brand = models.TextField(blank=True)
    spec_ref = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    merged_into = models.ForeignKey(  # duplicate resolution
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.code} — {self.description[:40]}"


class DocumentLine(models.Model):
    """Typed item lines for MR/PR/LM/GRN (design payload-vs-columns rule)."""

    revision = models.ForeignKey(
        DocumentRevision, on_delete=models.CASCADE, related_name="lines"
    )
    line_no = models.IntegerField()
    item = models.ForeignKey(  # NULL only for flagged free-text new items
        Item, on_delete=models.PROTECT, null=True, blank=True, related_name="lines"
    )
    free_text_desc = models.TextField(blank=True)
    unit = models.CharField(max_length=10, blank=True)
    qty_required = models.DecimalField(max_digits=12, decimal_places=2,
                                       null=True, blank=True)
    qty_stock = models.DecimalField(max_digits=12, decimal_places=2,
                                    null=True, blank=True)
    qty_to_order = models.DecimalField(max_digits=12, decimal_places=2,
                                       null=True, blank=True)
    qty_loaded = models.DecimalField(max_digits=12, decimal_places=2,
                                     null=True, blank=True)
    qty_pending = models.DecimalField(max_digits=12, decimal_places=2,
                                      null=True, blank=True)
    qty_manifest = models.DecimalField(max_digits=12, decimal_places=2,
                                       null=True, blank=True)
    qty_received = models.DecimalField(max_digits=12, decimal_places=2,
                                       null=True, blank=True)
    priority = models.CharField(max_length=8, blank=True)  # MR: NORMAL/URGENT
    urgent_reason = models.TextField(blank=True)
    amount_cash = models.DecimalField(max_digits=14, decimal_places=2,
                                      null=True, blank=True)  # PR vendor rows
    amount_credit = models.DecimalField(max_digits=14, decimal_places=2,
                                        null=True, blank=True)
    vendor = models.TextField(blank=True)
    quotation_ref = models.TextField(blank=True)
    payment_terms = models.TextField(blank=True)
    action_taken = models.TextField(blank=True)  # slip no. / PO no.
    is_changed = models.BooleanField(default=False)  # MR amendment flag (§5.5 r3)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["line_no"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(item__isnull=False) | ~models.Q(free_text_desc="")
                ),
                name="line_item_or_free_text",
            )
        ]

    @property
    def description(self):
        return self.item.description if self.item else self.free_text_desc


class DocumentLink(models.Model):
    LINK_TYPES = [("MR_PR", "MR→PR"), ("MR_LM", "MR→LM"), ("PR_LM", "PR→LM"),
                  ("LM_GRN", "LM→GRN"), ("IR_NCR", "IR→NCR")]

    from_document = models.ForeignKey(
        Document, on_delete=models.PROTECT, related_name="links_from"
    )
    to_document = models.ForeignKey(
        Document, on_delete=models.PROTECT, related_name="links_to"
    )
    link_type = models.CharField(max_length=8, choices=LINK_TYPES)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["from_document", "to_document", "link_type"],
                name="uniq_document_link",
            )
        ]


class PendingItem(models.Model):
    """Pending Items Log (spec §6): auto-created from LM lines with
    qty_pending > 0; cleared automatically when a later LM ships the item."""

    lm_line = models.ForeignKey(
        DocumentLine, on_delete=models.PROTECT, related_name="pending_items"
    )
    site = models.ForeignKey(Site, on_delete=models.PROTECT,
                             related_name="pending_items")
    pr_document = models.ForeignKey(Document, on_delete=models.PROTECT,
                                    null=True, blank=True, related_name="+")
    item = models.ForeignKey(Item, on_delete=models.PROTECT,
                             null=True, blank=True, related_name="+")
    free_text_desc = models.TextField(blank=True)
    unit = models.CharField(max_length=10, blank=True)
    qty_pending = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField(blank=True)  # e.g. Vendor Stock-Out
    action_next = models.TextField(blank=True)
    status = models.CharField(max_length=10, default="PENDING")  # PENDING/CLEARED
    cleared_date = models.DateField(null=True, blank=True)
    cleared_lm = models.ForeignKey(Document, on_delete=models.PROTECT,
                                   null=True, blank=True, related_name="+")
    cleared_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
