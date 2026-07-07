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
