from decimal import Decimal

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
        QS = "QS", "Quantity Surveyor"  # tenders, contracts, project financials
        ADMIN = "ADMIN", "Admin"

    # Roles with all-site read scope (spec §3 + R3; SIGNATORY at M6; QS sees
    # the whole project portfolio)
    HO_ROLES = {"HO_PURCHASING", "DIRECTOR", "SIGNATORY", "FINANCE",
                "HO_HR", "QS", "ADMIN"}
    SINGLE_SITE_ROLES = {"SITE_ENGINEER", "SITE_ADMIN"}

    role = models.CharField(max_length=20, choices=Role.choices)
    full_name = models.TextField()
    # Set when an admin issues a temporary password by invite email; the user
    # must choose their own password before using the app.
    must_change_password = models.BooleanField(default=False)
    # Mobile (E.164, e.g. +9607xxxxxx) for SMS/WhatsApp approval alerts, and an
    # opt-out if the in-app bell is enough for this user.
    phone = models.CharField(max_length=20, blank=True)
    notify_external = models.BooleanField(default=True)
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


class Notification(models.Model):
    """An alert that a user needs to approve or attend to something. Created on
    the workflow transitions that block a specific person/role; surfaced in-app
    (the bell) and, when the user has a phone + external delivery is
    configured, pushed by SMS/WhatsApp."""

    recipient = models.ForeignKey(User, on_delete=models.CASCADE,
                                  related_name="notifications")
    title = models.CharField(max_length=140)
    body = models.CharField(max_length=300, blank=True)
    doc_ref = models.CharField(max_length=20, blank=True)
    doc_type = models.CharField(max_length=3, blank=True)
    # the document status this alert was raised for — dedupes re-fires
    doc_status = models.CharField(max_length=30, blank=True)
    category = models.CharField(max_length=20, default="approval")
    read_at = models.DateTimeField(null=True, blank=True)
    external_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "read_at"])]


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
        PMR = "PMR"  # project material requisition — imports (§5.10, P1B)
        IPR = "IPR"  # international purchase requisition — the order (§5.10)
        IRN = "IRN"  # import receipt note — count at the HO store (§5.10.8)
        SIN = "SIN"  # store issue note — issue stock to a site (§6D.3, P1B-f)

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
            # PARTIALLY_ORDERED: a PR covered some items, the rest still need
            # one — the MR stays open for further PRs (owner 2026-07-15).
            "SENT_TO_HO": {"PR_RAISED", "PARTIALLY_ORDERED", "LOADING_PLANNED"},
            "PARTIALLY_ORDERED": {"PARTIALLY_ORDERED", "PR_RAISED",
                                  "LOADING_PLANNED"},
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
            # SUBMITTED→DIRECTOR_APPROVED is the central path (no site PM):
            # HO Purchasing/HR Director-approve directly; a Finance-initiated
            # PYR is cleared to voucher at this status without a Director step.
            "SUBMITTED": {"PM_APPROVED", "DIRECTOR_APPROVED", "DRAFT",
                          "REJECTED"},
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
        # Project Material Requisition — the import demand raised at project
        # level, tracked end to end (§5.10.3). Early steps (Site→PM→HO→Director)
        # are manual; the later ladder (Sourcing→Ordered→Received→Closed) is
        # driven by the IPR/IRN/SIN lifecycle in later slices. DRAFT = returned.
        "PMR": {
            "DRAFT": {"SUBMITTED", "CANCELLED"},
            "SUBMITTED": {"PM_APPROVED", "DRAFT", "CANCELLED"},
            "PM_APPROVED": {"HO_REVIEWED", "DRAFT"},
            "HO_REVIEWED": {"SIZED_RELEASED", "DRAFT"},
            "SIZED_RELEASED": {"SOURCING", "DRAFT"},
            "SOURCING": {"ORDERED"},
            "ORDERED": {"RECEIVED"},
            "RECEIVED": {"CLOSED"},
        },
        # International Purchase Requisition — the overseas order (§5.10.4).
        # HO raises it, the Director awards (APPROVED), a signatory authorises
        # it on a Payment Voucher (AUTHORISED = commitment, §6C.2 / D1). The
        # shipment→clearance→receipt lifecycle lands in later slices (-d/-e).
        "IPR": {
            "DRAFT": {"SUBMITTED", "CANCELLED"},
            "SUBMITTED": {"APPROVED", "DRAFT", "CANCELLED"},
            "APPROVED": {"AUTHORISED", "DRAFT"},
            "AUTHORISED": {"CLOSED"},
        },
        # Import Receipt Note — count at the HO store, creates stock lots at
        # landed cost (§5.10.8). Draft while counting; Received posts the lots.
        "IRN": {
            "DRAFT": {"RECEIVED", "CANCELLED"},
        },
        # Store Issue Note — issue store stock to a site (§6D.3, P1B-f). Draft
        # while picking lots; Issued moves stock on-hand → in transit; Received
        # when the site's GRN counts it in (posts INCURRED at landed cost).
        "SIN": {
            "DRAFT": {"ISSUED", "CANCELLED"},
            "ISSUED": {"RECEIVED"},
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
    line = models.ForeignKey(  # a photo tied to one line (free-text MR items)
        "DocumentLine", on_delete=models.CASCADE, null=True, blank=True,
        related_name="attachments",
    )
    kind = models.CharField(max_length=20, choices=KINDS)
    file = models.FileField(upload_to=attachment_path)
    file_name = models.TextField(blank=True)
    content_type = models.TextField(blank=True)
    size_bytes = models.BigIntegerField(default=0)
    caption = models.TextField(blank=True)  # DPR photo captions
    project_code = models.CharField(  # tags a DPR photo to a project for the
        max_length=20, blank=True)    # scoped client report (owner 2026-07-14)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)


class MobileDevice(models.Model):
    """A signed-in mobile (PWA) device holding a long-lived, sliding-expiry
    token so approvers stay logged in ~30 days and can be revoked per device
    from the desktop admin (owner 2026-07-14, R6 mobile companion)."""

    IDLE_DAYS = 30

    user = models.ForeignKey(User, on_delete=models.CASCADE,
                             related_name="mobile_devices")
    token = models.CharField(max_length=64, unique=True, db_index=True)
    label = models.CharField(max_length=120, blank=True)   # user-agent hint
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now_add=True)
    revoked = models.BooleanField(default=False)

    @property
    def is_active(self):
        from datetime import timedelta

        from django.utils import timezone
        return (not self.revoked and self.last_seen >=
                timezone.now() - timedelta(days=self.IDLE_DAYS))


class PushSubscription(models.Model):
    """A Web Push (VAPID) endpoint for a user's browser/PWA. One per browser;
    purged on a 404/410 from the push service (R6 mobile, owner 2026-07-14)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE,
                             related_name="push_subs")
    endpoint = models.TextField(unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    label = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_success = models.DateTimeField(null=True, blank=True)


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
    is_major = models.BooleanField(  # a key project material (shows on DPR)
        default=False)
    # Created by a site team when an item was missing from the catalogue —
    # awaiting HO Purchasing review (owner, temporary access).
    is_provisional = models.BooleanField(default=False)
    photo = models.FileField(upload_to="items/", null=True, blank=True)
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
    # GST on a PR vendor row (recoverable input tax, owner 2026-07-13):
    # amount_cash/amount_credit stay NET; this is the tax added for payment.
    gst_amount = models.DecimalField(max_digits=14, decimal_places=2,
                                     null=True, blank=True)
    vendor = models.TextField(blank=True)
    quotation_ref = models.TextField(blank=True)
    payment_terms = models.TextField(blank=True)  # descriptive note
    # Credit period in days for a credit vendor — drives the payable due date at
    # authorisation. Prefilled from the supplier default, overridable per PR.
    credit_days = models.PositiveIntegerField(null=True, blank=True)
    action_taken = models.TextField(blank=True)  # payment slip / voucher no.
    po_ref = models.TextField(blank=True)  # auto-filled at PO generation (R3)
    cost_head = models.ForeignKey(  # PR vendor lines carry a cost head (§6C.1)
        "CostHead", on_delete=models.PROTECT, null=True, blank=True,
        related_name="+")
    purchase_type = models.CharField(max_length=6, blank=True)  # CASH|CREDIT
    # How an MR line is fulfilled (P1B-f): blank = local purchase (PR);
    # "STORE" = issued from HO store stock via a SIN (owner 2026-07-13).
    fulfil_source = models.CharField(max_length=8, blank=True)
    # The PR that has taken this MR line for ordering (owner 2026-07-15): a
    # PR can cover only some of a long MR's items, so each ordered line points
    # to its PR and the rest stay requisitionable for a later PR. Null = still
    # open. Only set on MR lines. A line counts as taken only while its PR is
    # live (not void / cancelled / rejected).
    ordered_pr = models.ForeignKey(
        "Document", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ordered_mr_lines")
    # An LM/GRN line that carries a store-issued item points back to its SIN
    # line, so the site GRN can receive it and post INCURRED at landed cost in
    # the same combined receipt (owner 2026-07-14, P1B-f3).
    store_issue_line = models.ForeignKey("StoreIssueLine",
                                         on_delete=models.PROTECT, null=True,
                                         blank=True, related_name="+")
    rate = models.DecimalField(max_digits=14, decimal_places=2,  # PO lines (R2)
                               null=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2,
                                 null=True, blank=True)
    is_changed = models.BooleanField(default=False)  # MR amendment flag (§5.5 r3)
    # PMR (imports, §5.10.3): free-text spec / model / brand, and the approved
    # MAR reference the line relies on (a blank one raises a soft warning).
    spec = models.TextField(blank=True)
    mar_ref = models.CharField(max_length=20, blank=True)
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
                  ("PR_PO", "PR→PO"), ("PO_LM", "PO→LM"),
                  ("PMR_IPR", "PMR→IPR")]

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
    # Items in a tool category go to the site Tools & Equipment register on GRN
    # (as individual assets), not the consumable stock ledger.
    is_tool = models.BooleanField(default=False)

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
    """Supplier contact database, owned by HO Purchasing (R2). Phase 1B adds
    the category/country/currency/incoterm/bank fields the international
    procurement flow needs (§5.10.2); the category filters the supplier
    picker (local purchase vs an overseas order vs a forwarder/clearing agent).
    """

    class Category(models.TextChoices):
        LOCAL = "LOCAL", "Local supplier"
        INTERNATIONAL = "INTERNATIONAL", "International supplier"
        FORWARDER = "FORWARDER", "Freight forwarder"
        CLEARING_AGENT = "CLEARING_AGENT", "Clearing agent"

    name = models.TextField()
    category = models.CharField(max_length=15, choices=Category.choices,
                                default=Category.LOCAL)
    country = models.CharField(max_length=60, blank=True)
    default_currency = models.CharField(max_length=3, blank=True)   # e.g. USD
    default_incoterm = models.CharField(max_length=12, blank=True)  # e.g. FOB
    credit_days = models.PositiveIntegerField(null=True, blank=True)  # default
    #  credit period; prefills a PR vendor line, drives the payable due date
    contact_person = models.TextField(blank=True)
    phone = models.TextField(blank=True)
    email = models.TextField(blank=True)
    address = models.TextField(blank=True)
    # Bank / remittance details for TT payments — sensitive, shown only to
    # HO Purchasing / Finance / Admin (§5.10.2).
    bank_details = models.TextField(blank=True)
    # payment terms live per quotation, not per supplier — terms vary by
    # goods/volume (owner, 2026-07-07)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class ImportOrder(models.Model):
    """IPR typed header (§5.10.4) — one row per IPR document. The order is
    placed in the supplier's currency; a manually agreed exchange rate (D4)
    converts it to MVR when the commitment posts at authorisation."""

    document = models.OneToOneField(Document, on_delete=models.CASCADE,
                                    related_name="import_order")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT,
                                 related_name="import_orders")
    order_currency = models.CharField(max_length=3, default="USD")
    # order currency → MVR (the "agreed exchange-rate basis"); manual per D4
    exchange_rate = models.DecimalField(max_digits=12, decimal_places=4)
    incoterm = models.CharField(max_length=12, blank=True)
    loading_port = models.CharField(max_length=60, blank=True)
    discharge_port = models.CharField(max_length=60, blank=True)
    pi_ref = models.CharField(max_length=40, blank=True)  # proforma invoice no.
    # The supplier's proforma invoice file, uploaded by HO for the Director /
    # Signatory to view before authorising the order (owner 2026-07-13).
    proforma_invoice = models.FileField(upload_to="import-docs/pi/", null=True,
                                        blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"IPR {self.document.ref}"


class ImportOrderLine(models.Model):
    """A line on the order: an item, the ordered quantity and unit price (in
    the order currency), and a cost head. Its allocations split the ordered
    quantity between reserving projects and general company stock (§5.10.4)."""

    order = models.ForeignKey(ImportOrder, on_delete=models.CASCADE,
                              related_name="lines")
    line_no = models.IntegerField()
    item = models.ForeignKey(Item, on_delete=models.PROTECT, null=True,
                             blank=True, related_name="+")
    free_text_desc = models.TextField(blank=True)
    unit = models.CharField(max_length=10, blank=True)
    spec = models.TextField(blank=True)
    order_qty = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = models.DecimalField(max_digits=14, decimal_places=4)  # order ccy
    cost_head = models.ForeignKey("CostHead", on_delete=models.PROTECT,
                                  related_name="+")
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["line_no"]

    @property
    def description(self):
        return self.item.description if self.item else self.free_text_desc

    @property
    def line_value(self):  # in order currency
        return (self.order_qty or 0) * (self.unit_price or 0)


class ImportAllocation(models.Model):
    """How one order line's quantity is shared. A project allocation reserves
    stock to that project (commitment lands on the project's site); a null
    project is the general-stock balance (commitment to the General Stock
    pool). Per line, the allocations must sum to the ordered quantity."""

    line = models.ForeignKey(ImportOrderLine, on_delete=models.CASCADE,
                             related_name="allocations")
    project = models.ForeignKey("Project", on_delete=models.PROTECT, null=True,
                                blank=True, related_name="import_allocations")
    qty = models.DecimalField(max_digits=12, decimal_places=2)

    @property
    def is_general_stock(self):
        return self.project_id is None


class ImportPaymentMilestone(models.Model):
    """A scheduled part-payment on an import order (§5.10.5). Milestones are
    set in the order currency (a percent or a fixed amount) and must sum to the
    order total. Purchasing marks one DUE when its trigger is met; Finance pays
    it, recording the actual MVR paid and the TT reference. The committed-value
    share posts PAID to the projects/stock; the difference between what was
    actually paid and that committed value is realised FX (never a project)."""

    class Trigger(models.TextChoices):
        ADVANCE = "ADVANCE", "Advance / on order (PI)"
        BL = "BL", "On shipping documents (B/L)"
        ARRIVAL = "ARRIVAL", "On arrival"
        DATE = "DATE", "By date"
        BALANCE = "BALANCE", "Balance / other"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        DUE = "DUE", "Due"                    # trigger met — needs a voucher
        AUTHORISED = "AUTHORISED", "Authorised"  # signatory-approved on a PV
        PAID = "PAID", "Paid"                 # TT executed by Finance

    order = models.ForeignKey(ImportOrder, on_delete=models.CASCADE,
                              related_name="milestones")
    seq = models.IntegerField()
    label = models.CharField(max_length=60)
    trigger = models.CharField(max_length=8, choices=Trigger.choices,
                               default=Trigger.BALANCE)
    percent = models.DecimalField(max_digits=6, decimal_places=3, null=True,
                                  blank=True)
    fixed_amount = models.DecimalField(max_digits=14, decimal_places=2,
                                       null=True, blank=True)  # order currency
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.PENDING)
    # the Payment Voucher a signatory approved to authorise this TT — every
    # overseas payment carries its voucher reference for book-keeping (§6C.2)
    voucher = models.ForeignKey("Document", on_delete=models.PROTECT,
                                null=True, blank=True, related_name="+")
    # payment record (Finance)
    tt_ref = models.CharField(max_length=60, blank=True)
    mvr_paid = models.DecimalField(max_digits=14, decimal_places=2, null=True,
                                   blank=True)
    actual_rate = models.DecimalField(max_digits=12, decimal_places=4,
                                      null=True, blank=True)
    paid_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                blank=True, related_name="+")
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["seq"]

    def due_amount(self, order_total):
        """This milestone's value in the order currency."""
        from decimal import Decimal
        if self.fixed_amount is not None:
            return self.fixed_amount
        if self.percent is not None:
            return (order_total * self.percent / Decimal("100")).quantize(
                Decimal("0.01"))
        return Decimal("0")

    # payment proof (Finance uploads the TT advice, §5.10.5 / §5.10.7)
    tt_advice = models.FileField(upload_to="import-docs/tt/", null=True,
                                 blank=True)


class ImportShipment(models.Model):
    """A physical shipment moving an import order to Malé (§5.10.6). An order
    may ship in several parts. Clearing charges recorded here feed the landed
    cost (§5.10.9, apportioned in P1B-e)."""

    class Mode(models.TextChoices):
        SEA = "SEA", "Sea"
        AIR = "AIR", "Air"

    class Status(models.TextChoices):
        BOOKED = "BOOKED", "Booked"
        SHIPPED = "SHIPPED", "Shipped"
        IN_TRANSIT = "IN_TRANSIT", "In transit"
        ARRIVED = "ARRIVED", "Arrived Malé"
        UNDER_CLEARING = "UNDER_CLEARING", "Under clearing"
        CLEARED = "CLEARED", "Cleared"

    order = models.ForeignKey(ImportOrder, on_delete=models.CASCADE,
                              related_name="shipments")
    seq = models.IntegerField()
    mode = models.CharField(max_length=3, choices=Mode.choices,
                            default=Mode.SEA)
    forwarder = models.ForeignKey(Supplier, on_delete=models.PROTECT,
                                  null=True, blank=True, related_name="+")
    forwarder_name = models.CharField(max_length=120, blank=True)
    vessel_flight = models.CharField(max_length=80, blank=True)
    container_awb = models.CharField(max_length=80, blank=True)
    etd = models.DateField(null=True, blank=True)
    eta = models.DateField(null=True, blank=True)
    tracking_ref = models.CharField(max_length=80, blank=True)
    carrier_link = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=14, choices=Status.choices,
                              default=Status.BOOKED)
    shared_with_agent_at = models.DateTimeField(null=True, blank=True)
    # freight + insurance to Malé, then local clearing charges (all MVR) —
    # the landed-cost inputs (§5.10.8/9)
    freight = models.DecimalField(max_digits=14, decimal_places=2,
                                  null=True, blank=True)
    insurance = models.DecimalField(max_digits=14, decimal_places=2,
                                    null=True, blank=True)
    customs_duty = models.DecimalField(max_digits=14, decimal_places=2,
                                       null=True, blank=True)
    import_gst = models.DecimalField(max_digits=14, decimal_places=2,
                                     null=True, blank=True)
    port_handling = models.DecimalField(max_digits=14, decimal_places=2,
                                        null=True, blank=True)
    agent_charges = models.DecimalField(max_digits=14, decimal_places=2,
                                        null=True, blank=True)
    local_transport = models.DecimalField(max_digits=14, decimal_places=2,
                                          null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                   blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    # Transitions the UI offers; the service is the authority.
    NEXT = {
        "BOOKED": {"SHIPPED"},
        "SHIPPED": {"IN_TRANSIT", "ARRIVED"},
        "IN_TRANSIT": {"ARRIVED"},
        "ARRIVED": {"UNDER_CLEARING"},
        "UNDER_CLEARING": {"CLEARED"},
    }

    class Meta:
        ordering = ["seq"]

    CHARGE_FIELDS = ("freight", "insurance", "customs_duty", "import_gst",
                     "port_handling", "agent_charges", "local_transport")

    @property
    def clearing_total(self):
        from decimal import Decimal
        return sum((getattr(self, f) or Decimal("0"))
                   for f in self.CHARGE_FIELDS)


class ImportShipmentLine(models.Model):
    """Which order-line quantities travel on this shipment (§5.10.6). An order
    may ship in parts; each part draws a quantity from a line's still-to-ship
    balance. When a shipment has no lines (legacy / whole-order shipments) it is
    treated as carrying the full order."""

    shipment = models.ForeignKey(ImportShipment, on_delete=models.CASCADE,
                                 related_name="lines")
    ipr_line = models.ForeignKey(ImportOrderLine, on_delete=models.PROTECT,
                                 related_name="shipment_lines")
    qty = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["shipment", "ipr_line"],
                                    name="uniq_shipment_line"),
        ]


def shipment_doc_path(instance, filename):
    return (f"import-docs/{instance.shipment.order.document.ref}/"
            f"{instance.doc_type}-{filename}")


class ShipmentDocument(models.Model):
    """A typed shipping document on a shipment (§5.10.7). The completeness
    checklist for clearing looks for the required types."""

    class Type(models.TextChoices):
        BL_AWB = "BL_AWB", "Bill of Lading / AWB"
        PACKING_LIST = "PACKING_LIST", "Packing list"
        COMMERCIAL_INVOICE = "COMMERCIAL_INVOICE", "Commercial invoice"
        COO = "COO", "Certificate of origin"
        INSURANCE = "INSURANCE", "Insurance"
        TEST_CERT = "TEST_CERT", "Test certificate"
        PI = "PI", "Proforma invoice"
        OTHER = "OTHER", "Other"

    shipment = models.ForeignKey(ImportShipment, on_delete=models.CASCADE,
                                 related_name="documents")
    doc_type = models.CharField(max_length=20, choices=Type.choices)
    file = models.FileField(upload_to=shipment_doc_path)
    file_name = models.CharField(max_length=200, blank=True)
    notes = models.CharField(max_length=200, blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                    blank=True, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)


class ImportReceipt(models.Model):
    """IRN header (§5.10.8) — one per IRN document. Counts a shipment against
    its order at the HO store; posting creates stock lots at landed cost."""

    document = models.OneToOneField(Document, on_delete=models.CASCADE,
                                    related_name="import_receipt")
    shipment = models.ForeignKey(ImportShipment, on_delete=models.PROTECT,
                                 related_name="receipts")
    location = models.CharField(max_length=60, blank=True)  # store location
    notes = models.TextField(blank=True)

    @property
    def order(self):
        return self.shipment.order


class ImportReceiptLine(models.Model):
    receipt = models.ForeignKey(ImportReceipt, on_delete=models.CASCADE,
                                related_name="lines")
    ipr_line = models.ForeignKey(ImportOrderLine, on_delete=models.PROTECT,
                                 related_name="receipt_lines")
    expected_qty = models.DecimalField(max_digits=12, decimal_places=2)
    received_qty = models.DecimalField(max_digits=12, decimal_places=2,
                                       null=True, blank=True)
    damaged_qty = models.DecimalField(max_digits=12, decimal_places=2,
                                      null=True, blank=True)
    condition_note = models.TextField(blank=True)

    @property
    def variance(self):
        from decimal import Decimal
        return (self.received_qty or Decimal("0")) - (self.expected_qty
                                                      or Decimal("0"))


class StockLot(models.Model):
    """A valued lot of imported stock in the HO store (§6D.1). Created by an
    IRN at unit landed cost; reserved to a project (from the IPR allocation) or
    general company stock. Stock is a company asset, not project cost — it
    becomes project cost only when issued to site and received (GRN, P1B-f)."""

    item = models.ForeignKey(Item, on_delete=models.PROTECT, null=True,
                             blank=True, related_name="stock_lots")
    free_text_desc = models.TextField(blank=True)
    unit = models.CharField(max_length=10, blank=True)
    # Import-received lots carry their source; opening/manual stock has none.
    source_receipt = models.ForeignKey(ImportReceipt, on_delete=models.PROTECT,
                                        null=True, blank=True,
                                        related_name="lots")
    source_ipr_line = models.ForeignKey(ImportOrderLine,
                                        on_delete=models.PROTECT, null=True,
                                        blank=True, related_name="+")
    # provenance for non-import lots, e.g. "Opening stock" + a note/ref
    origin_note = models.CharField(max_length=120, blank=True)
    # reserved to a project (committed exposure) or null = general stock
    project = models.ForeignKey("Project", on_delete=models.PROTECT, null=True,
                                blank=True, related_name="stock_lots")
    qty_received = models.DecimalField(max_digits=12, decimal_places=2)
    qty_on_hand = models.DecimalField(max_digits=12, decimal_places=2)
    # Issued to a site but not yet received there (§6D.3) — left the store,
    # still a company asset until the site GRN turns it into project cost.
    qty_in_transit = models.DecimalField(max_digits=12, decimal_places=2,
                                         default=0)
    unit_landed_cost = models.DecimalField(max_digits=16, decimal_places=4)
    location = models.CharField(max_length=60, blank=True)
    received_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_date", "id"]

    @property
    def description(self):
        return self.item.description if self.item_id else self.free_text_desc

    @property
    def source_ref(self):
        """The IRN that brought it in, or a label for opening/manual stock."""
        if self.source_receipt_id:
            return self.source_receipt.document.ref
        return self.origin_note or "Opening stock"

    @property
    def value_on_hand(self):
        return (self.qty_on_hand or 0) * (self.unit_landed_cost or 0)


class StoreIssue(models.Model):
    """SIN typed header (§6D.3) — one row per SIN document. Issues store stock
    to a site (optionally reserved to a project); the value moves from the
    store to *in transit to site*, becoming project cost only at the site
    GRN (§5.10.11, INCURRED at landed cost)."""

    document = models.OneToOneField(Document, on_delete=models.CASCADE,
                                    related_name="store_issue")
    to_site = models.ForeignKey(Site, on_delete=models.PROTECT,
                                related_name="store_issues")
    to_project = models.ForeignKey("Project", on_delete=models.PROTECT,
                                   null=True, blank=True,
                                   related_name="store_issues")
    notes = models.TextField(blank=True)
    issued_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                  blank=True, related_name="+")
    issued_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"SIN {self.document.ref}"


class StoreIssueLine(models.Model):
    """One lot drawn on a SIN: the source lot, the quantity issued, and the
    unit landed cost snapshot (the value that will INCURRED at the site GRN)."""

    issue = models.ForeignKey(StoreIssue, on_delete=models.CASCADE,
                              related_name="lines")
    lot = models.ForeignKey(StockLot, on_delete=models.PROTECT,
                            related_name="issue_lines")
    qty = models.DecimalField(max_digits=12, decimal_places=2)
    unit_landed_cost = models.DecimalField(max_digits=16, decimal_places=4)
    # How much has been received at site (via a GRN or a direct SIN receipt) —
    # the single guard against posting the cost twice (P1B-f3).
    received_qty = models.DecimalField(max_digits=12, decimal_places=2,
                                       default=0)

    @property
    def value(self):
        return (self.qty or 0) * (self.unit_landed_cost or 0)


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
    # This supplier charges GST — off for unregistered vendors (owner
    # 2026-07-13). Applied at the company rate on the awarded net.
    gst_applicable = models.BooleanField(default=True)
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
    photo = models.FileField(upload_to="employees/", null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    passport_no = models.TextField(blank=True)          # sensitive
    nationality = models.TextField(blank=True)
    job_category = models.ForeignKey(  # company-wide DPR list (spec §6A.1)
        ManpowerCategory, on_delete=models.PROTECT, null=True, blank=True,
        related_name="employees",
    )
    basic_pay = models.DecimalField(max_digits=12, decimal_places=2,  # sensitive
                                    null=True, blank=True)
    currency = models.CharField(max_length=3, default="MVR")  # MVR / USD
    # NULL = inherit the category's OT default; True/False overrides per worker
    ot_applies = models.BooleanField(null=True, blank=True)

    class EmploymentType(models.TextChoices):
        PERMANENT = "PERMANENT", "Permanent"    # on the company work permit
        CONTRACT = "CONTRACT", "Contract"       # temporary hire, no permit

    # Permanent workers (local or foreign) are on the company work permit and
    # get expiry tracking; contract workers are temporary and are not.
    employment_type = models.CharField(
        max_length=10, choices=EmploymentType.choices,
        default=EmploymentType.PERMANENT)
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

    def ot_rate(self):
        """The OT rate that applies to this worker (0 if none / not eligible):
        the category+currency rate from the OT master, gated by the per-worker
        override which falls back to the category default."""
        if not self.job_category_id:
            return Decimal("0")
        rate = OvertimeRate.objects.filter(
            category_id=self.job_category_id, currency=self.currency).first()
        if rate is None:
            return Decimal("0")
        applies = self.ot_applies
        if applies is None:
            applies = rate.applies_by_default
        return rate.rate_per_hour if applies else Decimal("0")


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


class WorkPermitRenewal(models.Model):
    """One record per work-permit renewal — HR picks a number of months and
    the employee's expiry is pushed forward by that much. Keeps an audit
    trail of who renewed, for how long, and the resulting expiry."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE,
                                 related_name="permit_renewals")
    months = models.PositiveIntegerField()
    previous_expiry = models.DateField(null=True, blank=True)
    # Set only once the renewal is applied (i.e. the PYR is paid); null while
    # the renewal is pending payment.
    new_expiry = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True)        # e.g. the PYR ref that paid it
    fee = models.DecimalField(max_digits=12, decimal_places=2, null=True,
                              blank=True)       # renewal fee, for the PYR
    # The PYR raised to pay this renewal's fee. The expiry only moves forward
    # once Finance pays that PYR (applied=True).
    document = models.ForeignKey(Document, on_delete=models.SET_NULL,
                                 null=True, blank=True,
                                 related_name="permit_renewals")
    applied = models.BooleanField(default=False)  # expiry actually extended
    applied_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class OvertimeRate(models.Model):
    """Managed OT rates (owner: no hardcoding). One flat rate per hour per job
    category and currency; `applies_by_default` sets whether workers in that
    category get OT unless individually overridden (Employee.ot_applies)."""

    category = models.ForeignKey(ManpowerCategory, on_delete=models.CASCADE,
                                 related_name="ot_rates")
    currency = models.CharField(max_length=3, default="MVR")  # MVR / USD
    rate_per_hour = models.DecimalField(max_digits=10, decimal_places=2)
    applies_by_default = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["category", "currency"],
                                    name="uniq_ot_rate")
        ]


class SalaryAdvance(models.Model):
    """A salary advance or loan for one worker, raised at site inside a PYR
    (payment_type=ADVANCE). Once Finance pays that PYR it becomes a payroll
    deduction — an advance in one hit, a loan spread over `months` installments
    from (period_year, period_month)."""

    class Kind(models.TextChoices):
        ADVANCE = "ADVANCE", "Advance"
        LOAN = "LOAN", "Loan"

    document = models.ForeignKey(Document, on_delete=models.CASCADE,
                                 related_name="salary_advances")  # the PYR
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT,
                                 related_name="salary_advances")
    kind = models.CharField(max_length=8, choices=Kind.choices,
                            default=Kind.ADVANCE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)  # total
    months = models.IntegerField(default=1)  # installments (1 = advance)
    period_year = models.IntegerField()   # first deduction period
    period_month = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)


class PayrollRun(models.Model):
    """A monthly salary run. MVR runs are per site; the USD run is a single
    combined run across all sites (site=NULL) — middle management and above."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        LOCKED = "LOCKED", "Locked"

    site = models.ForeignKey(Site, on_delete=models.PROTECT, null=True,
                             blank=True, related_name="payroll_runs")
    currency = models.CharField(max_length=3, default="MVR")
    year = models.IntegerField()
    month = models.IntegerField()
    working_days = models.IntegerField()  # divisor for pro-rating
    status = models.CharField(max_length=8, choices=Status.choices,
                              default=Status.DRAFT)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT,
                                   related_name="+")
    locked_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                  blank=True, related_name="+")
    locked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["site", "currency", "year",
                                            "month"], name="uniq_payroll_run")
        ]
        ordering = ["-year", "-month"]


class PayrollLine(models.Model):
    """One worker on a run. Inputs are stored; money is derived (see
    core.payroll) so the run screen and payslip agree. basic_pay and ot_rate
    are snapshotted so a later profile change doesn't rewrite history."""

    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE,
                            related_name="lines")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT,
                                 related_name="payroll_lines")
    site = models.ForeignKey(Site, on_delete=models.PROTECT, null=True,
                             blank=True, related_name="+")  # worker's site
    basic_pay = models.DecimalField(max_digits=12, decimal_places=2,
                                    default=0)
    ot_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    days_worked = models.DecimalField(max_digits=5, decimal_places=1,
                                      default=0)
    fridays_worked = models.IntegerField(default=0)
    ot_hours = models.DecimalField(max_digits=7, decimal_places=1, default=0)
    allowance = models.DecimalField(max_digits=12, decimal_places=2,
                                    default=0)  # adhoc allowance / air ticket
    penalty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    advance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    loan = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_to_site = models.DecimalField(max_digits=12, decimal_places=2,
                                         null=True, blank=True)
    amount_to_office = models.DecimalField(max_digits=12, decimal_places=2,
                                           null=True, blank=True)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["employee__emp_no"]
        constraints = [
            models.UniqueConstraint(fields=["run", "employee"],
                                    name="uniq_payroll_line")
        ]


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
        POTENTIAL = "POTENTIAL", "Potential"   # QS pre-award / tender stage
        AWARDED = "AWARDED", "Awarded"
        ACTIVE = "ACTIVE", "Active"
        ON_HOLD = "ON_HOLD", "On hold"
        CLOSED = "CLOSED", "Closed"

    site = models.ForeignKey(Site, on_delete=models.PROTECT,
                             related_name="projects")
    code = models.CharField(max_length=12)  # short label, e.g. OWV-POOLS
    title = models.TextField()
    scope = models.TextField(blank=True)  # general summary
    boq_ref = models.TextField(blank=True)
    # Contract value is in USD (resort contracts are USD); site MVR costs are
    # converted to USD for the project P&L. Sensitivity rule as for sites.
    contract_value = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True)
    loa_date = models.DateField(null=True, blank=True)  # letter of award

    # --- Contract terms (owner: QS records these) -----------------------
    class ContractType(models.TextChoices):
        LUMP_SUM = "LUMP_SUM", "Lump sum"
        REMEASUREMENT = "REMEASUREMENT", "Re-measurement"
        COST_PLUS = "COST_PLUS", "Cost plus"

    contract_type = models.CharField(max_length=16,
                                     choices=ContractType.choices, blank=True)
    # payment & money terms
    payment_terms = models.TextField(blank=True)
    advance_payment_pct = models.DecimalField(max_digits=5, decimal_places=2,
                                              null=True, blank=True)
    retention_pct = models.DecimalField(max_digits=5, decimal_places=2,
                                        null=True, blank=True)
    retention_release_terms = models.TextField(blank=True)
    # Output GST charged on interim claims (Maldives GST, statutory 8%). Held
    # per project so a zero-rated/exempt contract can override it.
    output_gst_pct = models.DecimalField(max_digits=5, decimal_places=2,
                                         null=True, blank=True)
    # time & penalties
    defects_liability_months = models.PositiveIntegerField(null=True,
                                                           blank=True)
    liquidated_damages = models.TextField(blank=True)  # e.g. 0.5%/week, cap 10%
    # contract type & basis
    price_escalation = models.TextField(blank=True)
    # bonds & insurance
    performance_bond_pct = models.DecimalField(max_digits=5, decimal_places=2,
                                               null=True, blank=True)
    advance_guarantee = models.TextField(blank=True)
    insurance_details = models.TextField(blank=True)
    # --------------------------------------------------------------------

    pm = models.ForeignKey(  # Project PM — approval routing prefers this
        User, on_delete=models.PROTECT, null=True, blank=True,
        related_name="pm_projects")
    qs = models.ForeignKey(  # assigned Quantity Surveyor — owns the financials
        User, on_delete=models.PROTECT, null=True, blank=True,
        related_name="qs_projects")
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


class Boq(models.Model):
    """A project's Bill of Quantities — the priced contract schedule the QS
    progresses interim claims against. One per project; locked once claiming
    starts so the contract baseline can't shift under a live claim.

    `split_rates` records whether the client wants supply (material) and
    installation (labour) priced separately, or as one combined rate."""

    project = models.OneToOneField(Project, on_delete=models.CASCADE,
                                   related_name="boq")
    currency = models.CharField(max_length=3, default="USD")  # contracts are USD
    split_rates = models.BooleanField(default=False)  # material + labour columns
    is_locked = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                   blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total(self):
        from decimal import Decimal
        return sum((i.amount for i in self.items.all()), Decimal("0"))

    @property
    def total_supply(self):
        from decimal import Decimal
        return sum((i.amount_supply for i in self.items.all()), Decimal("0"))

    @property
    def total_install(self):
        from decimal import Decimal
        return sum((i.amount_install for i in self.items.all()), Decimal("0"))


class BoqItem(models.Model):
    """One BOQ line. A priced item carries qty × rate; the rate splits into a
    supply (material) leg and an installation (labour) leg — a combined-rate
    contract simply leaves the labour leg empty and puts the whole rate on
    supply. A heading/preamble row (is_heading) is a section title or note with
    no money. `section` groups items under a bill/trade for subtotals."""

    boq = models.ForeignKey(Boq, on_delete=models.CASCADE, related_name="items")
    sort_order = models.IntegerField(default=0)
    section = models.CharField(max_length=120, blank=True)  # bill / trade
    item_code = models.CharField(max_length=30, blank=True)  # e.g. A.1.2
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=20, blank=True)
    qty = models.DecimalField(max_digits=14, decimal_places=3, null=True,
                              blank=True)
    rate_supply = models.DecimalField(max_digits=14, decimal_places=2,
                                      null=True, blank=True)   # material
    rate_install = models.DecimalField(max_digits=14, decimal_places=2,
                                       null=True, blank=True)  # labour
    is_heading = models.BooleanField(default=False)

    class Meta:
        ordering = ["sort_order", "id"]

    @property
    def rate_total(self):
        from decimal import Decimal
        return (self.rate_supply or Decimal("0")) + (self.rate_install
                                                     or Decimal("0"))

    def _amount(self, rate):
        from decimal import Decimal
        if self.is_heading:
            return Decimal("0")
        return (self.qty or Decimal("0")) * (rate or Decimal("0"))

    @property
    def amount_supply(self):
        return self._amount(self.rate_supply)

    @property
    def amount_install(self):
        return self._amount(self.rate_install)

    @property
    def amount(self):
        return self._amount(self.rate_total)


class Variation(models.Model):
    """A variation order (VO) on a project's contract — an addition or omission
    the QS raises, sends for client approval, and (once approved) claims like
    BOQ items. Approved VOs adjust the contract sum; submitted-not-approved
    ones read as provisions pending approval in the forecast (IPA §D/E)."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted to client"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    class Kind(models.TextChoices):
        ADDITION = "ADDITION", "Addition"
        OMISSION = "OMISSION", "Omission"

    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name="variations")
    seq = models.IntegerField()
    ref = models.CharField(max_length=20)          # e.g. VO-01
    title = models.TextField(blank=True)
    kind = models.CharField(max_length=8, choices=Kind.choices,
                            default=Kind.ADDITION)
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.DRAFT)
    ref_date = models.DateField(null=True, blank=True)   # client instruction
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                   blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["seq"]

    @property
    def gross(self):
        from decimal import Decimal
        return sum((i.amount for i in self.items.all()), Decimal("0"))

    @property
    def signed_total(self):
        """Net effect on the contract sum: additions add, omissions subtract."""
        return -self.gross if self.kind == self.Kind.OMISSION else self.gross


class VariationItem(models.Model):
    """A priced line on a variation — same shape as a BOQ line (supply +
    installation, or a combined rate; headings carry no money)."""

    variation = models.ForeignKey(Variation, on_delete=models.CASCADE,
                                  related_name="items")
    sort_order = models.IntegerField(default=0)
    section = models.CharField(max_length=120, blank=True)
    item_code = models.CharField(max_length=30, blank=True)
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=20, blank=True)
    qty = models.DecimalField(max_digits=14, decimal_places=3, null=True,
                              blank=True)
    rate_supply = models.DecimalField(max_digits=14, decimal_places=2,
                                      null=True, blank=True)
    rate_install = models.DecimalField(max_digits=14, decimal_places=2,
                                       null=True, blank=True)
    is_heading = models.BooleanField(default=False)

    class Meta:
        ordering = ["sort_order", "id"]

    @property
    def rate_total(self):
        from decimal import Decimal
        return (self.rate_supply or Decimal("0")) + (self.rate_install
                                                     or Decimal("0"))

    def _amount(self, rate):
        from decimal import Decimal
        if self.is_heading:
            return Decimal("0")
        return (self.qty or Decimal("0")) * (rate or Decimal("0"))

    @property
    def amount_supply(self):
        return self._amount(self.rate_supply)

    @property
    def amount_install(self):
        return self._amount(self.rate_install)

    @property
    def amount(self):
        return self._amount(self.rate_total)


class ProgressClaim(models.Model):
    """An interim payment application (IPA / IPC) — the QS values work done to
    date against the BOQ + approved variations, applies the contract's advance
    recovery and retention, and claims the balance from the client. Claims
    chain by seq: each carries the cumulative valuation forward, and the amount
    "now due" is this claim's net cumulative less the previous claim's.

    The money terms (advance %, recovery %, retention %, GST %) are snapshotted
    at creation so a signed claim's arithmetic never shifts if the project
    terms are later edited."""

    class Type(models.TextChoices):
        ADVANCE = "ADVANCE", "Advance payment"
        INTERIM = "INTERIM", "Interim"
        RELEASE = "RELEASE", "Retention release"
        FINAL = "FINAL", "Final account"

    class Basis(models.TextChoices):
        PERCENT = "PERCENT", "% complete"       # lump-sum valuation
        MEASURED = "MEASURED", "Measured qty"    # re-measurement valuation

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        CERTIFIED = "CERTIFIED", "Certified"
        PAID = "PAID", "Paid"
        REJECTED = "REJECTED", "Rejected"

    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name="claims")
    seq = models.IntegerField()
    ref = models.CharField(max_length=20)          # e.g. IPA-01
    claim_type = models.CharField(max_length=8, choices=Type.choices,
                                  default=Type.INTERIM)
    basis = models.CharField(max_length=8, choices=Basis.choices,
                             default=Basis.PERCENT)
    work_done_upto = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.DRAFT)
    previous = models.ForeignKey("self", on_delete=models.SET_NULL, null=True,
                                 blank=True, related_name="+")
    # Money terms snapshotted from the project at creation.
    advance_pct = models.DecimalField(max_digits=5, decimal_places=2,
                                      default=0)   # advance as % of contract
    recovery_pct = models.DecimalField(max_digits=5, decimal_places=2,
                                       default=0)  # recovered per work done
    retention_pct = models.DecimalField(max_digits=5, decimal_places=2,
                                        default=0)
    gst_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    # Cumulative header figures the QS enters directly (IPA K2/K3, M2).
    material_on_site = models.DecimalField(max_digits=16, decimal_places=2,
                                           default=0)  # K2
    material_off_site = models.DecimalField(max_digits=16, decimal_places=2,
                                            default=0)  # K3
    retention_released = models.DecimalField(max_digits=16, decimal_places=2,
                                             default=0)  # M2 (cumulative)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                   blank=True, related_name="+")
    certified_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                     blank=True, related_name="+")
    certified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["seq"]
        constraints = [
            models.UniqueConstraint(fields=["project", "seq"],
                                    name="uniq_claim_seq_per_project")
        ]

    def __str__(self):
        return f"{self.project.code}/{self.ref}"


class ProgressClaimItem(models.Model):
    """One valued line within a claim — a cumulative %-complete (lump sum) or a
    cumulative measured quantity (re-measurement) against a BOQ item or an
    approved variation item. The contract price is read live from the linked
    item (both are locked once claiming starts). 'Current' value is derived by
    the service as this cumulative less the previous claim's."""

    class Source(models.TextChoices):
        BOQ = "BOQ", "BOQ"
        VO = "VO", "Variation"

    claim = models.ForeignKey(ProgressClaim, on_delete=models.CASCADE,
                              related_name="items")
    source = models.CharField(max_length=3, choices=Source.choices)
    boq_item = models.ForeignKey(BoqItem, on_delete=models.CASCADE, null=True,
                                 blank=True, related_name="+")
    variation_item = models.ForeignKey(VariationItem, on_delete=models.CASCADE,
                                       null=True, blank=True, related_name="+")
    cumulative_pct = models.DecimalField(max_digits=6, decimal_places=2,
                                         null=True, blank=True)   # 0..100
    cumulative_qty = models.DecimalField(max_digits=14, decimal_places=3,
                                         null=True, blank=True)

    class Meta:
        ordering = ["id"]

    @property
    def line(self):
        """The underlying priced item (BOQ or variation)."""
        return self.boq_item if self.source == self.Source.BOQ \
            else self.variation_item


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
    petty_cash_entry = models.ForeignKey("PettyCashEntry",
                                         on_delete=models.PROTECT, null=True,
                                         blank=True, related_name="+")
    ipr_line = models.ForeignKey("ImportOrderLine", on_delete=models.PROTECT,
                                 null=True, blank=True, related_name="+")
    ipr_milestone = models.ForeignKey("ImportPaymentMilestone",
                                      on_delete=models.PROTECT, null=True,
                                      blank=True, related_name="+")
    # sin_line FK added with its Phase 1B module
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
        PERMIT_RENEWAL = "PERMIT_RENEWAL", "Work-permit renewal"

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
    currency = models.CharField(max_length=3, default="MVR")   # MVR or USD
    # Who raised it drives the approval chain (§7.1 / owner 2026-07-13):
    #   SITE    → PM → Director → voucher   (site teams, MVR only)
    #   CENTRAL → Director → voucher        (HO Purchasing / HR, MVR or USD)
    #   FINANCE → voucher only              (Accounts-initiated rent/salary etc.)
    origin = models.CharField(max_length=8, default="SITE")
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
    # Finance execution. amount_paid is in `currency`; for a USD request
    # fx_rate is the MVR-per-USD rate applied when paying, so the cost ledger
    # (MVR) receives amount_paid * fx_rate (owner 2026-07-13).
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2,
                                      null=True, blank=True)
    fx_rate = models.DecimalField(max_digits=12, decimal_places=4, null=True,
                                  blank=True)
    paid_date = models.DateField(null=True, blank=True)
    payment_ref = models.TextField(blank=True)
    variance_reason = models.TextField(blank=True)
    paid_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                blank=True, related_name="+")
    # Advances settlement
    is_settled = models.BooleanField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    settlement_note = models.TextField(blank=True)
    # The cycle a petty-cash replenishment PYR restores (M6e); null for a
    # normal PYR
    petty_cash_cycle = models.ForeignKey("PettyCashCycle",
                                         on_delete=models.PROTECT, null=True,
                                         blank=True,
                                         related_name="replenishments")

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
        Document, on_delete=models.PROTECT, null=True, blank=True,
        related_name="voucher_lines_as_source")  # the PR / PYR / IPR
    # an overseas TT (import milestone) batched for signatory authorisation —
    # exactly one of source_document / source_milestone is set per line
    source_milestone = models.ForeignKey(
        "ImportPaymentMilestone", on_delete=models.PROTECT, null=True,
        blank=True, related_name="voucher_lines")
    # A credit-vendor payable pulled onto a voucher to be paid (when due, or
    # early if a vendor withdraws credit) — owner 2026-07-15. Exactly one of
    # source_document / source_milestone / source_payable is set per line.
    source_payable = models.ForeignKey(
        "Payable", on_delete=models.PROTECT, null=True, blank=True,
        related_name="voucher_lines")
    # A voucher is single-currency (owner 2026-07-13): every line on it shares
    # this currency — MVR for PR, the request currency for a PYR, the order
    # currency for an overseas TT.
    currency = models.CharField(max_length=3, default="MVR")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.INCLUDED)
    query_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["voucher", "source_document"],
                                    name="uniq_voucher_source"),
            models.UniqueConstraint(fields=["voucher", "source_milestone"],
                                    name="uniq_voucher_milestone"),
            models.UniqueConstraint(fields=["voucher", "source_payable"],
                                    name="uniq_voucher_payable"),
        ]


# ===== Petty cash — imprest system (§6B, M6e) =============================

class PettyCashFloat(models.Model):
    """One imprest float per site (§6B.1): a fixed amount held by a named
    custodian, replenished by an auto-generated PYR when it runs low."""

    site = models.OneToOneField(Site, on_delete=models.PROTECT,
                                related_name="petty_cash")
    imprest_amount = models.DecimalField(max_digits=12, decimal_places=2)
    custodian = models.ForeignKey(User, on_delete=models.PROTECT,
                                  related_name="petty_cash_floats")
    # replenish when cash in hand falls below this % of the imprest
    trigger_pct = models.IntegerField(default=30)
    per_txn_cap = models.DecimalField(max_digits=10, decimal_places=2,
                                      default=1500)  # larger spend → PYR
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Petty cash — {self.site.code}"


class PettyCashCycle(models.Model):
    """A closed, immutable imprest cycle (§6B.3): opening float, its
    expenses, the replenishment PYR that restored it, closing float."""

    class Status(models.TextChoices):
        OPEN = "OPEN"
        REQUESTED = "REQUESTED"      # replenishment PYR raised, awaiting pay
        REPLENISHED = "REPLENISHED"  # float restored, cycle closed & immutable

    float = models.ForeignKey(PettyCashFloat, on_delete=models.PROTECT,
                              related_name="cycles")
    cycle_no = models.IntegerField()
    opening_float = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=12, choices=Status.choices,
                              default=Status.OPEN)
    closing_float = models.DecimalField(max_digits=12, decimal_places=2,
                                        null=True, blank=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["float", "cycle_no"],
                                    name="uniq_float_cycle")
        ]
        ordering = ["-cycle_no"]

    def __str__(self):
        return f"{self.float.site.code} cycle {self.cycle_no}"


class PettyCashEntry(models.Model):
    """A single petty-cash expense (§6B.2), recorded by the custodian,
    PM-approved (posts Incurred), then reimbursed when the cycle's
    replenishment PYR is paid."""

    class Status(models.TextChoices):
        RECORDED = "RECORDED"          # entered, not yet PM-approved
        APPROVED = "APPROVED"          # PM approved → posted to Incurred cost
        REIMBURSED = "REIMBURSED"      # closed by a paid replenishment PYR
        VOID = "VOID"                  # reversed before reimbursement

    cycle = models.ForeignKey(PettyCashCycle, on_delete=models.PROTECT,
                              related_name="entries")
    entry_date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    cost_head = models.ForeignKey(CostHead, on_delete=models.PROTECT,
                                  related_name="petty_cash_entries")
    payee = models.TextField()
    purpose = models.TextField(blank=True)
    receipt = models.FileField(upload_to="petty_cash/", null=True, blank=True)
    has_receipt = models.BooleanField(default=False)
    no_receipt_reason = models.TextField(blank=True)  # mandatory when none
    status = models.CharField(max_length=12, choices=Status.choices,
                              default=Status.RECORDED)
    entered_by = models.ForeignKey(User, on_delete=models.PROTECT,
                                   related_name="+")
    approved_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                    blank=True, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-entry_date", "-id"]


class PettyCashReconciliation(models.Model):
    """A physical cash count against the system balance (§6B.4), with a
    mandatory variance explanation. A custodian handover records both
    outgoing and incoming custodians."""

    float = models.ForeignKey(PettyCashFloat, on_delete=models.PROTECT,
                              related_name="reconciliations")
    recon_date = models.DateField()
    counted_cash = models.DecimalField(max_digits=12, decimal_places=2)
    system_balance = models.DecimalField(max_digits=12, decimal_places=2)
    variance = models.DecimalField(max_digits=12, decimal_places=2)
    explanation = models.TextField(blank=True)
    is_handover = models.BooleanField(default=False)
    outgoing_custodian = models.ForeignKey(User, on_delete=models.PROTECT,
                                           null=True, blank=True,
                                           related_name="+")
    incoming_custodian = models.ForeignKey(User, on_delete=models.PROTECT,
                                           null=True, blank=True,
                                           related_name="+")
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT,
                                    related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recon_date", "-id"]


# ===== Site inventory (Phase 1A — simple quantity ledger) =====


class StockMovement(models.Model):
    """Append-only site-level inventory ledger. On-hand for a (site, item) is
    the sum of its movement qtys; the movement list is the history. No costing
    or lot tracking — quantities only (that is deferred to Phase 1B).

    RECEIPT (+, raised automatically when a GRN is verified),
    ISSUE   (−, stock handed out to a project),
    ADJUST  (±, a physical-count reconciliation)."""

    class Kind(models.TextChoices):
        RECEIPT = "RECEIPT", "GRN receipt"
        ISSUE = "ISSUE", "Issue to project"
        ADJUST = "ADJUST", "Reconciliation"

    site = models.ForeignKey(Site, on_delete=models.PROTECT,
                             related_name="stock_movements")
    item = models.ForeignKey(Item, on_delete=models.PROTECT,
                             related_name="stock_movements")
    kind = models.CharField(max_length=8, choices=Kind.choices)
    qty = models.DecimalField(max_digits=12, decimal_places=2)  # signed
    project = models.ForeignKey(  # set on ISSUE
        Project, on_delete=models.PROTECT, null=True, blank=True,
        related_name="stock_issues")
    document = models.ForeignKey(  # the GRN, on RECEIPT
        Document, on_delete=models.PROTECT, null=True, blank=True,
        related_name="+")
    reason = models.TextField(blank=True)  # issue purpose / adjust explanation
    movement_date = models.DateField()
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                   blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-movement_date", "-id"]
        indexes = [models.Index(fields=["site", "item"])]


class SiteMajorMaterial(models.Model):
    """Which catalogue items a SITE treats as major (key) materials for its
    DPR. Major varies with the work a site does — pipe fittings matter on an
    MEP job, not a civil one (owner) — so this is per-site, not a global flag."""

    site = models.ForeignKey(Site, on_delete=models.CASCADE,
                             related_name="major_materials")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="+")
    added_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                 blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["site", "item"],
                                    name="uniq_site_major_material")
        ]


class ToolAsset(models.Model):
    """One physical tool / machine / piece of equipment at a site. Created on
    site mobilisation (manual) or when a GRN receives an item in a tool
    category (one asset per unit). Site admin fills serial/model and manages
    its condition through the faulty → repair → in-use cycle."""

    class State(models.TextChoices):
        IN_USE = "IN_USE", "In use"
        FAULTY = "FAULTY", "Faulty"
        UNDER_REPAIR = "UNDER_REPAIR", "Under repair"
        RETIRED = "RETIRED", "Retired"

    class Source(models.TextChoices):
        MOBILISATION = "MOBILISATION", "Mobilisation"
        GRN = "GRN", "Received (GRN)"
        MANUAL = "MANUAL", "Added manually"

    site = models.ForeignKey(Site, on_delete=models.PROTECT,
                             related_name="tools")
    item = models.ForeignKey(  # the catalog item it came from (null = free)
        Item, on_delete=models.PROTECT, null=True, blank=True,
        related_name="tool_assets")
    name = models.TextField()               # snapshot / free-text name
    category = models.TextField(blank=True)  # snapshot of the item category
    serial_no = models.CharField(max_length=80, blank=True)
    model = models.CharField(max_length=80, blank=True)
    brand = models.CharField(max_length=80, blank=True)
    notes = models.TextField(blank=True)
    state = models.CharField(max_length=12, choices=State.choices,
                             default=State.IN_USE)
    state_note = models.TextField(blank=True)  # last fault/repair note
    state_changed_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=12, choices=Source.choices,
                              default=Source.MANUAL)
    document = models.ForeignKey(  # the GRN it arrived on
        Document, on_delete=models.PROTECT, null=True, blank=True,
        related_name="+")
    added_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                 blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        indexes = [models.Index(fields=["site", "state"])]

    def __str__(self):
        return f"{self.name} @ {self.site.code}"
