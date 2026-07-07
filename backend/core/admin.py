from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    AuditLog,
    CompanyParameter,
    Holiday,
    ManpowerCategory,
    Site,
    SitePmHistory,
    User,
    UserSiteAllocation,
)


@admin.register(User)
class SPUserAdmin(UserAdmin):
    list_display = ["username", "full_name", "role", "is_active", "last_login"]
    fieldsets = UserAdmin.fieldsets + (("Sand Planet", {"fields": ("full_name", "role")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Sand Planet", {"fields": ("full_name", "role")}),
    )


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "status", "is_head_office", "start_date"]
    list_filter = ["status"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only: the audit log is append-only (spec §7.2)."""

    list_display = ["at", "entity", "entity_id", "event", "actor"]
    list_filter = ["entity", "event"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(SitePmHistory)
admin.site.register(UserSiteAllocation)
admin.site.register(Holiday)
admin.site.register(ManpowerCategory)
admin.site.register(CompanyParameter)
