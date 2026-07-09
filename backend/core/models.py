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
        SIGNATORY = "SIGNATORY", "Signatory (Executive Director)"  # R4/M6
        FINANCE = "FINANCE", "Finance"  # verifies & disburses (R4)
        HO_HR = "HO_HR", "HO HR / Payroll"
        ADMIN = "ADMIN", "Admin"

    # Roles with all-site read scope (spec §3 + R3; SIGNATORY at M6)
    HO_ROLES = {"HO_PURCHASING", "DIRECTOR", "SIGNATORY", "FINANCE",
                "HO_HR", "ADMIN"}
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
    client_address = models.TextField(blank=True)
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
        PO = "PO"  # purchase order (R2)
        DMA = "DMA"  # daily manpower allocation (R5, internal)
        PYR = "PYR"  # payment request (§5.9, M6)
        PV = "PV"    # payment voucher — batch authorisation (M6d)

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
            # Director approves (award) -> Signatory authorises (commitment,
            # §6C.2) -> POs issue + payables + payment. Return to DRAFT
            # before authorisation (§7.5a); Finance withdrawal after (§7.5b).
            "DRAFT": {"SUBMITTED", "CANCELLED"},
            "SUBMITTED": {"APPROVED", "DRAFT", "REJECTED", "CANCELLED"},
            "APPROVED": {"AUTHORISED", "DRAFT", "REJECTED"},
            "AUTHORISED": {"PAYMENT_PROCESSING", "PAID_PO_ISSUED", "DRAFT"},
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
        "PO": {  # generated per awarded supplier on PR approval (R2)
            "DRAFT": {"ISSUED"},
            "ISSUED": {"CLOSED"},
        },
        # Morning allocation off the previous day's TWSs; internal only (R5)
        "DMA": {"DRAFT": {"ISSUED"}},
        # Payment Request (§5.9, §7.1). Commitment posts at AUTHORISED;
        # any approver may Return to DRAFT (§7.5a); Finance may Withdraw
        # authorisation back to DRAFT (§7.5b). CANCELLED/REJECTED terminal.
        "PYR": {
            "DRAFT": {"SUBMITTED", "CANCELLED"},
            "SUBMITTED": {"PM_APPROVED", "DRAFT", "REJECTED"},
            "PM_APPROVED": {"DIRECTOR_APPROVED", "DRAFT", "REJECTED"},
            "DIRECTOR_APPROVED": {"AUTHORISED", "DRAFT", "REJECTED"},
            "AUTHORISED": {"PAID", "DRAFT"},  # DRAFT = withdrawal (§7.5b)
            "PAID": {"CLOSED"},
        },
        # Payment Voucher (M6d): Finance batches Director-approved PR/PYR;
        # a signatory approves the voucher (or queries lines). Approval is
        # the commitment point — replaces the per-document authorise step.
        "PV": {
            "DRAFT": {"SUBMITTED", "CANCELLED"},
            "SUBMITTED": {"APPROVED", "DRAFT"},  # DRAFT = returned to Finance
        },
    }

    doc_type = models.CharField(max_length=3, choices=Type.choices)
    ref = models.CharField(max_length=20, unique=True)  # DPR-SJR-001 / PR-014
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="documents")
    project = models.ForeignKey(  # DPR/TWS/IR/MAR are project-wise (R4)
        "Project", on_delete=models.PROTECT, null=True, blank=True,
        related_name="documents",
    )
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
    supplier = models.ForeignKey(  # POs only (R2)
        "Supplier", on_delete=models.PROTECT, null=True, blank=True,
        related_name="purchase_orders",
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
        ("PAYMENT_SLIP", "Payment slip / voucher"),
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
    action_taken = models.TextField(blank=True)  # payment slip / voucher no.
    po_ref = models.TextField(blank=True)  # auto-filled at PO generation (R3)
    cost_head = models.ForeignKey(  # PR vendor lines carry a cost head (§6C.1)
        "CostHead", on_delete=models.PROTECT, null=True, blank=True,
        related_name="+")
    purchase_type = models.CharField(max_length=6, blank=True)  # CASH|CREDIT
    rate = models.DecimalField(max_digits=14, decimal_places=2,  # PO lines (R2)
                               null=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2,
                                 null=True, blank=True)
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
                  ("LM_GRN", "LM→GRN"), ("IR_NCR", "IR→NCR"),
                  ("PR_PO", "PR→PO"), ("PO_LM", "PO→LM")]

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


class ItemCategory(models.Model):
    """Controlled list of item categories/trades (owner, 2026-07-08) —
    the Item Master's category field selects from these; managed on its
    own page by HO Purchasing."""

    name = models.CharField(max_length=60, unique=True)
    sort_order = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "item categories"

    def __str__(self):
        return self.name


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


# ===== Suppliers, quotations, purchase orders (DECISIONS.md R2) =====


class Supplier(models.Model):
    """Supplier contact database, owned by HO Purchasing (R2)."""

    name = models.TextField()
    contact_person = models.TextField(blank=True)
    phone = models.TextField(blank=True)
    email = models.TextField(blank=True)
    address = models.TextField(blank=True)
    # payment terms live per quotation, not per supplier — terms vary by
    # goods/volume (owner, 2026-07-07)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


def quotation_path(instance, filename):
    return f"quotations/{instance.document.ref}/{instance.supplier_id}-{filename}"


class Quotation(models.Model):
    """A supplier's quotation captured against a PR, in the supplier's own
    wording; lines are matched manually to MR lines (R2)."""

    document = models.ForeignKey(  # the PR
        Document, on_delete=models.PROTECT, related_name="quotations"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="quotations"
    )
    quote_ref = models.TextField(blank=True)
    quote_date = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    payment_terms = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    file = models.FileField(upload_to=quotation_path, null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class QuotationLine(models.Model):
    quotation = models.ForeignKey(
        Quotation, on_delete=models.CASCADE, related_name="lines"
    )
    line_no = models.IntegerField()
    supplier_desc = models.TextField()  # the supplier's wording, verbatim
    unit = models.CharField(max_length=20, blank=True)
    qty = models.DecimalField(max_digits=12, decimal_places=2,
                              null=True, blank=True)
    rate = models.DecimalField(max_digits=14, decimal_places=2,
                               null=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2,
                                 null=True, blank=True)
    mr_line = models.ForeignKey(  # the manual match (R2)
        DocumentLine, on_delete=models.PROTECT, null=True, blank=True,
        related_name="quote_matches",
    )
    awarded = models.BooleanField(default=False)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["line_no"]


# ===== Employees & timesheets (spec §6A, design §2) =====


class Employee(models.Model):
    """Employee database, maintained by HO HR/Payroll (+Admin). Employees
    are NOT app users (spec §6A.1). passport_no and basic_pay are sensitive:
    HR/Admin only — API-gated, never in site-level exports or logs."""

    emp_no = models.CharField(max_length=10, unique=True)  # EMP-0231, server-issued
    full_name = models.TextField()
    passport_no = models.TextField(blank=True)          # sensitive
    nationality = models.TextField(blank=True)
    job_category = models.ForeignKey(  # company-wide DPR list (spec §6A.1)
        ManpowerCategory, on_delete=models.PROTECT, null=True, blank=True,
        related_name="employees",
    )
    basic_pay = models.DecimalField(max_digits=12, decimal_places=2,  # sensitive
                                    null=True, blank=True)
    work_permit_no = models.TextField(blank=True)
    work_permit_expiry = models.DateField(null=True, blank=True)
    emergency_contact = models.TextField(blank=True)
    join_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)  # deactivate, never delete
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.emp_no} — {self.full_name}"

    def current_site_id(self):
        row = self.site_allocations.filter(to_date__isnull=True).first()
        return row.site_id if row else None


class EmployeeSiteAllocation(models.Model):
    """Transfer history — payroll must know where each person worked and
    when (spec §6A.1)."""

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT,
                                 related_name="site_allocations")
    site = models.ForeignKey(Site, on_delete=models.PROTECT,
                             related_name="employee_allocations")
    from_date = models.DateField()
    to_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-from_date"]


class TimesheetMonth(models.Model):
    """Month close: PM sign-off locks the site's timesheet; corrections
    need an audited HR reopen (spec §6A.3)."""

    site = models.ForeignKey(Site, on_delete=models.PROTECT,
                             related_name="timesheet_months")
    year = models.IntegerField()
    month = models.IntegerField()
    status = models.CharField(max_length=10, default="OPEN")  # OPEN/LOCKED
    signed_off_by = models.ForeignKey(User, on_delete=models.PROTECT,
                                      null=True, blank=True, related_name="+")
    signed_off_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(User, on_delete=models.PROTECT,
                                    null=True, blank=True, related_name="+")
    reopen_reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["site", "year", "month"],
                                    name="uniq_timesheet_month")
        ]


class Attendance(models.Model):
    """One row per employee per day at their allocated site (spec §6A.2)."""

    REMARKS = [("PRESENT", "Present"), ("ABSENT", "Absent"), ("SICK", "Sick"),
               ("LEAVE", "Leave"), ("HALF_DAY", "Half day")]

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT,
                                 related_name="attendance")
    site = models.ForeignKey(Site, on_delete=models.PROTECT,
                             related_name="attendance")
    day = models.DateField()
    check_in = models.TimeField(null=True, blank=True)
    check_out = models.TimeField(null=True, blank=True)
    normal_hours = models.DecimalField(max_digits=4, decimal_places=2,
                                       null=True, blank=True)  # computed
    ot_requested = models.DecimalField(max_digits=4, decimal_places=2,
                                       default=0)
    ot_approved = models.DecimalField(max_digits=4, decimal_places=2,  # PM only
                                      null=True, blank=True)
    ot_approved_by = models.ForeignKey(User, on_delete=models.PROTECT,
                                       null=True, blank=True, related_name="+")
    ot_approved_at = models.DateTimeField(null=True, blank=True)
    remark = models.CharField(max_length=12, choices=REMARKS, default="PRESENT")
    entered_by = models.ForeignKey(User, on_delete=models.PROTECT,
                                   null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["employee", "day"],
                                    name="uniq_attendance_day")
        ]
        ordering = ["day"]


# ===== Projects & programmes (DECISIONS.md R4) =====


class Project(models.Model):
    """A client award within a site. Sites host multiple projects, each
    with its own scope, BOQ, programme and timeline (R4). DPR/TWS/IR/MAR
    belong to a project; MR/GRN and the HO chain stay site-wise."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        ON_HOLD = "ON_HOLD"
        CLOSED = "CLOSED"

    site = models.ForeignKey(Site, on_delete=models.PROTECT,
                             related_name="projects")
    code = models.CharField(max_length=12)  # short label, e.g. OWV-POOLS
    title = models.TextField()
    scope = models.TextField(blank=True)  # general summary
    boq_ref = models.TextField(blank=True)
    contract_value = models.DecimalField(  # same sensitivity rule as sites
        max_digits=14, decimal_places=2, null=True, blank=True)
    loa_date = models.DateField(null=True, blank=True)  # letter of award
    pm = models.ForeignKey(  # Project PM — approval routing prefers this
        User, on_delete=models.PROTECT, null=True, blank=True,
        related_name="pm_projects")
    manpower_summary = models.TextField(blank=True)  # e.g. "1 SE, 2 masons…"
    # Planned manpower per month [{"month": "2026-05", "workers": 45}] —
    # the histogram sent to the client with the programme upon award
    manpower_plan = models.JSONField(default=list, blank=True)
    start_date = models.DateField(null=True, blank=True)
    planned_completion = models.DateField(null=True, blank=True)
    actual_completion = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["site", "code"],
                                    name="uniq_project_code_per_site")
        ]
        ordering = ["site", "code"]

    def __str__(self):
        return f"{self.site.code}/{self.code} — {self.title[:40]}"


class ProgrammeActivity(models.Model):
    """A row of the project programme (task or milestone). Progress is
    cumulative %-complete to date, updated from issued DPRs (R4)."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name="activities")
    sort_order = models.IntegerField()
    indent = models.IntegerField(default=0)  # outline level (0 = top)
    name = models.TextField()
    duration_days = models.IntegerField(null=True, blank=True)
    start = models.DateField(null=True, blank=True)
    finish = models.DateField(null=True, blank=True)
    is_milestone = models.BooleanField(default=False)  # 0-day items
    # Comma-separated predecessor activity ids — drives the Gantt's
    # dependency arrows (Phase A of the project workspace)
    predecessors = models.CharField(max_length=200, blank=True)
    progress = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    progress_updated_from = models.ForeignKey(  # last DPR that updated it
        Document, on_delete=models.PROTECT, null=True, blank=True,
        related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order"]
        verbose_name_plural = "programme activities"


# ===== Project cost control (§6C) — the Committed/Incurred/Paid ledger =====


class CostHead(models.Model):
    """Company-wide cost head master (§6C.1). is_pool marks the three HO
    pools (General Stock, Foreign Exchange, Stock Adjustment) that are
    never charged to a project — a small, enforceable deviation from the
    Technical Design schema, recorded in DECISIONS.md (M6)."""

    name = models.CharField(max_length=60, unique=True)
    sort_order = models.IntegerField(default=100)
    is_pool = models.BooleanField(default=False)  # HO pool, never a project
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class CostPosting(models.Model):
    """One row per cost event, per state (§6C.2, Technical Design §4A).
    Append-only: never edited; a correction is a new reversal row with a
    negative amount and reversal_of set. The posting service in
    core/costing.py is the ONLY writer."""

    class State(models.TextChoices):
        COMMITTED = "COMMITTED"
        INCURRED = "INCURRED"
        PAID = "PAID"

    class Source(models.TextChoices):
        PR = "PR"
        PYR = "PYR"
        PETTY_CASH = "PETTY_CASH"
        STAFF = "STAFF"
        IPR = "IPR"            # Phase 1B
        STORE_ISSUE = "STORE_ISSUE"  # Phase 1B
        FX = "FX"             # Phase 1B
        STOCK_ADJ = "STOCK_ADJ"      # Phase 1B

    site = models.ForeignKey(Site, on_delete=models.PROTECT,
                             related_name="cost_postings")
    cost_head = models.ForeignKey(CostHead, on_delete=models.PROTECT,
                                  related_name="postings")
    state = models.CharField(max_length=10, choices=State.choices)
    source = models.CharField(max_length=12, choices=Source.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)  # -ve = rev
    currency = models.CharField(max_length=3, default="MVR")
    posted_on = models.DateField()
    # Provenance — exactly one of these identifies the source event
    document = models.ForeignKey(Document, on_delete=models.PROTECT,
                                 null=True, blank=True, related_name="+")
    document_line = models.ForeignKey(DocumentLine, on_delete=models.PROTECT,
                                      null=True, blank=True, related_name="+")
    # petty_cash_entry / ipr_line / sin_line FKs added with their modules
    is_stock_pool = models.BooleanField(default=False)  # HO pool posting
    staff_year = models.IntegerField(null=True, blank=True)
    staff_month = models.IntegerField(null=True, blank=True)
    work_package = models.TextField(blank=True)  # Phase 2 BOQ dimension
    reversal_of = models.ForeignKey("self", on_delete=models.PROTECT,
                                    null=True, blank=True,
                                    related_name="reversals")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT,
                                   null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["site", "state", "cost_head", "posted_on"]),
            models.Index(fields=["document"]),
        ]


class PaymentRequest(models.Model):
    """PYR cost-bearing fields, typed for querying (§5.9, Technical Design
    §2). The form's descriptive content lives in the document revision
    payload; the money and workflow fields live here. One row per PYR
    document."""

    class Type(models.TextChoices):
        DIRECT = "DIRECT", "Direct payment"
        ADVANCE = "ADVANCE", "Advance"
        REIMBURSEMENT = "REIMBURSEMENT", "Reimbursement"
        PETTY_CASH_REPLENISH = "PETTY_CASH_REPLENISH", "Petty cash replenishment"

    class Method(models.TextChoices):
        BANK = "BANK", "Bank transfer"
        CASH = "CASH", "Cash"
        CHEQUE = "CHEQUE", "Cheque"

    document = models.OneToOneField(Document, on_delete=models.CASCADE,
                                    primary_key=True,
                                    related_name="payment_request")
    payment_type = models.CharField(max_length=24, choices=Type.choices,
                                    default=Type.DIRECT)
    cost_head = models.ForeignKey(CostHead, on_delete=models.PROTECT,
                                  related_name="payment_requests")
    payee = models.TextField()
    payment_method = models.CharField(max_length=16, choices=Method.choices,
                                      default=Method.BANK)
    payee_account = models.TextField(blank=True)
    currency = models.CharField(max_length=3, default="MVR")
    amount_requested = models.DecimalField(max_digits=14, decimal_places=2)
    required_by = models.DateField(null=True, blank=True)
    purpose = models.TextField()
    is_urgent = models.BooleanField(default=False)
    urgent_reason = models.TextField(blank=True)
    has_supporting_doc = models.BooleanField(default=False)
    no_doc_reason = models.TextField(blank=True)  # mandatory when no doc
    override_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                    blank=True, related_name="+")
    # Signatory gate (§7.5) — the commitment point
    authorised_by = models.ForeignKey(User, on_delete=models.PROTECT,
                                      null=True, blank=True, related_name="+")
    authorised_at = models.DateTimeField(null=True, blank=True)
    authorise_note = models.TextField(blank=True)
    authorised_under_threshold = models.BooleanField(default=False)
    # Return for review (§7.5a) — before commitment, posts nothing
    returned_reason = models.CharField(max_length=24, blank=True)
    returned_note = models.TextField(blank=True)
    returned_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                    blank=True, related_name="+")
    returned_at = models.DateTimeField(null=True, blank=True)
    # Withdrawal of authorisation (§7.5b) — Finance only, posts reversals
    withdrawn_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                     blank=True, related_name="+")
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_reason = models.TextField(blank=True)
    # Finance execution
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2,
                                      null=True, blank=True)
    paid_date = models.DateField(null=True, blank=True)
    payment_ref = models.TextField(blank=True)
    variance_reason = models.TextField(blank=True)
    paid_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                blank=True, related_name="+")
    # Advances settlement
    is_settled = models.BooleanField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    settlement_note = models.TextField(blank=True)
    # petty_cash_cycle FK added with the petty cash module (M6d)

    def __str__(self):
        return f"{self.document.ref} — {self.payee}"


class Payable(models.Model):
    """A credit-purchase obligation created at signatory authorisation of a
    PR, cleared when Finance settles it on terms (§4A). One per credit
    vendor row."""

    document = models.ForeignKey(Document, on_delete=models.PROTECT,
                                 related_name="payables")
    document_line = models.ForeignKey(DocumentLine, on_delete=models.PROTECT,
                                      null=True, blank=True, related_name="+")
    site = models.ForeignKey(Site, on_delete=models.PROTECT,
                             related_name="payables")
    vendor = models.TextField()
    terms = models.TextField(blank=True)  # e.g. '30 days'
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, default="OUTSTANDING")  # /SETTLED
    settled_on = models.DateField(null=True, blank=True)
    settled_ref = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["status", "due_date"])]


class PaymentVoucherLine(models.Model):
    """One requisition on a Payment Voucher (M6d). The signatory approves
    the voucher line by line: approved lines commit their source
    requisition; queried lines return it to its raiser."""

    class Status(models.TextChoices):
        INCLUDED = "INCLUDED"   # on the voucher, awaiting the signatory
        APPROVED = "APPROVED"   # signatory approved → source authorised
        QUERIED = "QUERIED"     # signatory queried → source returned

    voucher = models.ForeignKey(Document, on_delete=models.CASCADE,
                                related_name="voucher_lines")  # the PV
    source_document = models.ForeignKey(
        Document, on_delete=models.PROTECT,
        related_name="voucher_lines_as_source")  # the PR / PYR
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.INCLUDED)
    query_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["voucher", "source_document"],
                                    name="uniq_voucher_source")
        ]
