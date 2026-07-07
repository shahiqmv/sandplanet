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
