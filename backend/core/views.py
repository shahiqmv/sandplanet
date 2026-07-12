from datetime import date

from django.contrib.auth import authenticate, login, logout
from django.db import connection
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .audit import audit
from .models import (
    CompanyParameter,
    Holiday,
    ManpowerCategory,
    Site,
    SitePmHistory,
    User,
    UserSiteAllocation,
)
from .permissions import (
    IsAdmin,
    IsAdminOrReadOnly,
    IsSiteManagerOrReadOnly,
    scoped_site_ids,
)
from .serializers import (
    AllocationSerializer,
    HolidaySerializer,
    ManpowerCategorySerializer,
    ParameterSerializer,
    SiteSerializer,
    UserSerializer,
)


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        db_ok = cursor.fetchone()[0] == 1
    return Response(
        {"status": "ok", "db": "ok" if db_ok else "error", "engine": connection.vendor}
    )


# ===== Auth =====


@api_view(["POST"])
@permission_classes([AllowAny])
def auth_login(request):
    user = authenticate(
        request,
        username=request.data.get("username", ""),
        password=request.data.get("password", ""),
    )
    if user is None or not user.is_active:
        return Response({"detail": "Invalid credentials."}, status=400)
    login(request, user)
    return Response(_me_payload(user))


@api_view(["POST"])
def auth_logout(request):
    logout(request)
    return Response({"detail": "Logged out."})


@ensure_csrf_cookie
@api_view(["GET"])
@permission_classes([AllowAny])
def auth_me(request):
    """Also sets the CSRF cookie — the SPA calls this first."""
    if not request.user.is_authenticated:
        return Response({"authenticated": False})
    return Response(_me_payload(request.user))


def _me_payload(user):
    allocations = AllocationSerializer(
        user.site_allocations.filter(to_date__isnull=True).select_related("site"),
        many=True,
    ).data
    # Single-site roles land directly on their site (brief: no site picker)
    landing_site = allocations[0]["site"] if len(allocations) == 1 else None
    return {
        "authenticated": True,
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "is_ho": user.is_ho,
        "allocations": allocations,
        "landing_site_id": landing_site,
        "must_change_password": user.must_change_password,
    }


@api_view(["POST"])
def auth_change_password(request):
    """Any signed-in user sets a new password (also clears the
    must-change flag from an invite)."""
    current = request.data.get("current_password", "")
    new = request.data.get("new_password", "")
    user = request.user
    if not user.check_password(current):
        return Response({"detail": "Current password is incorrect."},
                        status=400)
    if len(new) < 8:
        return Response({"detail": "New password must be at least 8 "
                                   "characters."}, status=400)
    user.set_password(new)
    user.must_change_password = False
    user.save(update_fields=["password", "must_change_password"])
    from django.contrib.auth import update_session_auth_hash
    update_session_auth_hash(request, user)  # keep the session alive
    audit("user", user.id, "PASSWORD_CHANGED", actor=user)
    return Response({"detail": "Password updated."})


# ===== Sites =====


class SiteViewSet(viewsets.ModelViewSet):
    serializer_class = SiteSerializer
    permission_classes = [IsSiteManagerOrReadOnly]  # Admin + Director (R4)
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = Site.objects.all().order_by("code")
        site_ids = scoped_site_ids(self.request.user)
        if site_ids is not None:
            qs = qs.filter(id__in=site_ids)
        return qs

    def perform_create(self, serializer):
        site = serializer.save()
        audit("site", site.id, "SITE_CREATED", actor=self.request.user,
              to_state=site.status, detail={"code": site.code})

    def perform_update(self, serializer):
        site = serializer.save()
        audit("site", site.id, "SITE_UPDATED", actor=self.request.user,
              detail={"fields": sorted(self.request.data.keys())})

    @action(detail=True, methods=["post"])
    def status(self, request, pk=None):
        """Lifecycle transition; reason required; every change audited (§2.2)."""
        site = self.get_object()
        new_status = request.data.get("status")
        reason = (request.data.get("reason") or "").strip()
        if new_status not in Site.Status.values:
            return Response({"detail": f"Unknown status '{new_status}'."}, status=400)
        if not reason:
            return Response({"detail": "A reason is required."}, status=400)
        allowed = Site.TRANSITIONS.get(site.status, set())
        if new_status not in allowed:
            return Response(
                {"detail": f"Cannot move {site.status} → {new_status}."}, status=400
            )
        if site.status == Site.Status.CLOSED and request.user.role != User.Role.ADMIN:
            return Response(
                {"detail": "Only Admin can reopen a closed site."}, status=403
            )
        old = site.status
        site.status = new_status
        if new_status == Site.Status.CLOSED and not site.actual_completion:
            site.actual_completion = request.data.get("actual_completion") or date.today()
        site.save()
        audit("site", site.id, "SITE_STATUS_CHANGED", actor=request.user,
              from_state=old, to_state=new_status, detail={"reason": reason})
        return Response(self.get_serializer(site).data)

    @action(detail=True, methods=["post"], url_path="assign-pm")
    def assign_pm(self, request, pk=None):
        """Reassign the project PM; history kept (spec §2.1)."""
        site = self.get_object()
        try:
            pm = User.objects.get(pk=request.data.get("pm_user_id"), role=User.Role.PM,
                                  is_active=True)
        except User.DoesNotExist:
            return Response({"detail": "pm_user_id must be an active PM."}, status=400)
        today = date.today()
        previous = site.current_pm()
        site.pm_history.filter(to_date__isnull=True).update(to_date=today)
        SitePmHistory.objects.create(site=site, pm_user=pm, from_date=today)
        # PM approval routing needs a read allocation on the site
        if not UserSiteAllocation.objects.filter(
            user=pm, site=site, to_date__isnull=True
        ).exists():
            UserSiteAllocation.objects.create(user=pm, site=site, from_date=today)
        audit("site", site.id, "SITE_PM_ASSIGNED", actor=request.user,
              from_state=previous.username if previous else "",
              to_state=pm.username)
        return Response(self.get_serializer(site).data)


# ===== Users (admin-managed accounts, no self-registration) =====


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsAdmin]
    queryset = User.objects.all().order_by("username")
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def destroy(self, request, *args, **kwargs):
        from django.db.models import ProtectedError
        user = self.get_object()
        if user.id == request.user.id:
            return Response({"detail": "You can't delete your own account."},
                            status=400)
        username = user.username
        try:
            user.delete()
        except ProtectedError:
            return Response(
                {"detail": "This user has records (documents, approvals, "
                           "payments) and can't be deleted — deactivate them "
                           "instead."}, status=400)
        audit("user", 0, "USER_DELETED", actor=request.user,
              detail={"username": username})
        return Response(status=204)

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        # Report whether the welcome email went out (set on the instance in
        # perform_create) so the admin sees it immediately.
        response.data["invite_sent"] = getattr(self, "_invite_sent", False)
        if getattr(self, "_invite_error", None):
            response.data["invite_error"] = self._invite_error
        return response

    def perform_create(self, serializer):
        user = serializer.save()
        audit("user", user.id, "USER_CREATED", actor=self.request.user,
              detail={"username": user.username, "role": user.role})
        self._invite_sent, self._invite_error = self._maybe_invite(
            user, getattr(user, "_temp_password", None))

    def _maybe_invite(self, user, temp_password):
        """Email login details if a temp password was issued and an address is
        on file. Returns (sent, error)."""
        if not temp_password or not user.email:
            return False, None
        from .invites import send_user_invite
        try:
            send_user_invite(user, temp_password)
            audit("user", user.id, "USER_INVITE_SENT", actor=self.request.user,
                  detail={"email": user.email})
            return True, None
        except Exception as exc:  # noqa: BLE001 — surface send failures to admin
            return False, str(exc)

    def perform_update(self, serializer):
        user = serializer.save()
        audit("user", user.id, "USER_UPDATED", actor=self.request.user,
              detail={"fields": sorted(self.request.data.keys())})

    @action(detail=True, methods=["post"])
    def resend_invite(self, request, pk=None):
        """Re-issue a temporary password and email it (e.g. lost invite)."""
        from .invites import make_temp_password, send_user_invite
        user = self.get_object()
        if not user.email:
            return Response({"detail": "This user has no email address."},
                            status=400)
        temp = make_temp_password()
        user.set_password(temp)
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])
        try:
            send_user_invite(user, temp)
        except Exception as exc:  # noqa: BLE001
            return Response({"detail": f"Email failed: {exc}"}, status=502)
        audit("user", user.id, "USER_INVITE_RESENT", actor=request.user,
              detail={"email": user.email})
        return Response({"invite_sent": True})

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        """Deactivation, never deletion (NFR §9)."""
        user = self.get_object()
        user.is_active = False
        user.save()
        UserSiteAllocation.objects.filter(user=user, to_date__isnull=True).update(
            to_date=date.today()
        )
        audit("user", user.id, "USER_DEACTIVATED", actor=request.user)
        return Response(self.get_serializer(user).data)

    @action(detail=True, methods=["post"])
    def allocate(self, request, pk=None):
        """Allocate a user to a site (closes previous open allocation for
        single-site roles)."""
        user = self.get_object()
        try:
            site = Site.objects.get(pk=request.data.get("site_id"))
        except Site.DoesNotExist:
            return Response({"detail": "Unknown site_id."}, status=400)
        today = date.today()
        if user.role in User.SINGLE_SITE_ROLES:
            user.site_allocations.filter(to_date__isnull=True).update(to_date=today)
        UserSiteAllocation.objects.create(user=user, site=site, from_date=today)
        audit("user", user.id, "USER_ALLOCATED", actor=request.user,
              to_state=site.code)
        return Response(self.get_serializer(user).data)


# ===== Master data =====


class ManpowerCategoryViewSet(viewsets.ModelViewSet):
    serializer_class = ManpowerCategorySerializer
    permission_classes = [IsAdminOrReadOnly]
    queryset = ManpowerCategory.objects.all()
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def perform_destroy(self, instance):
        # Deactivate rather than delete if the category is referenced by an
        # employee — history must survive (spec §6A.1)
        if instance.employees.exists():
            instance.is_active = False
            instance.save(update_fields=["is_active"])
        else:
            instance.delete()


class HolidayViewSet(viewsets.ModelViewSet):
    serializer_class = HolidaySerializer
    permission_classes = [IsAdminOrReadOnly]
    queryset = Holiday.objects.all().order_by("day")
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cost_heads(request):
    """Cost heads for PYR / petty cash pickers (§6C.1). Project heads only
    by default; ?pools=1 includes the three HO pools."""
    from .models import CostHead

    qs = CostHead.objects.filter(is_active=True)
    if request.GET.get("pools") != "1":
        qs = qs.filter(is_pool=False)
    return Response([{"id": c.id, "name": c.name, "is_pool": c.is_pool}
                     for c in qs])


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pm_list(request):
    """Active PM users, for site/project PM assignment pick-lists."""
    pms = User.objects.filter(role=User.Role.PM, is_active=True) \
        .order_by("full_name")
    return Response([{"id": u.id, "full_name": u.full_name} for u in pms])


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pm_overview(request):
    """PM assignments board (R5): every active PM with the sites they run
    (current site PM), the projects they run (project PM), and the site-PM
    history. Site PM is a special duty — managed on its own page."""
    if request.user.role not in ("ADMIN", "DIRECTOR"):
        return Response({"detail": "Admin/Director only."}, status=403)
    from .models import Project

    pms = list(User.objects.filter(role=User.Role.PM).order_by("full_name"))
    current = SitePmHistory.objects.filter(to_date__isnull=True) \
        .select_related("site")
    sites_by_pm = {}
    for h in current:
        sites_by_pm.setdefault(h.pm_user_id, []).append(
            {"site_id": h.site_id, "code": h.site.code, "name": h.site.name,
             "since": h.from_date}
        )
    projects_by_pm = {}
    for p in Project.objects.filter(pm__isnull=False).select_related("site"):
        projects_by_pm.setdefault(p.pm_id, []).append(
            {"project_id": p.id, "code": p.code, "title": p.title,
             "site_code": p.site.code, "status": p.status}
        )
    history = [
        {"pm_id": h.pm_user_id, "pm_name": h.pm_user.full_name,
         "site_code": h.site.code, "site_name": h.site.name,
         "from_date": h.from_date, "to_date": h.to_date}
        for h in SitePmHistory.objects.select_related("site", "pm_user")
        .order_by("-from_date")[:100]
    ]
    return Response({
        "pms": [{
            "id": u.id, "username": u.username, "full_name": u.full_name,
            "email": u.email, "is_active": u.is_active,
            "sites": sites_by_pm.get(u.id, []),
            "projects": projects_by_pm.get(u.id, []),
        } for u in pms],
        "history": history,
    })


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def company_logo(request):
    """Company logo image used on every PDF letterhead. Stored via the
    configured storage — Spaces in production, local disk in dev — at
    company/logo.png|jpg; PDFs fall back to the bundled stationery logo when
    nothing is uploaded."""
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    names = ("company/logo.png", "company/logo.jpg")
    if request.method == "POST":
        if request.user.role != User.Role.ADMIN:
            return Response({"detail": "Admin only."}, status=403)
        file = request.FILES.get("file")
        if not file:
            return Response({"detail": "Attach the logo as 'file'."}, status=400)
        ext = {"image/png": "png", "image/jpeg": "jpg"}.get(file.content_type)
        if not ext:
            return Response({"detail": "PNG or JPEG only."}, status=400)
        for old in names:  # one logo at a time
            if default_storage.exists(old):
                default_storage.delete(old)
        default_storage.save(f"company/logo.{ext}", ContentFile(file.read()))
        audit("parameter", 0, "COMPANY_LOGO_UPDATED", actor=request.user,
              detail={"file_name": file.name, "size": file.size})
    for name in names:
        if default_storage.exists(name):
            return Response({"url": default_storage.url(name), "uploaded": True})
    return Response({"url": None, "uploaded": False})


@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def parameter_detail(request, key):
    if request.method == "PUT":
        if request.user.role != User.Role.ADMIN:
            return Response({"detail": "Admin only."}, status=403)
        param, _ = CompanyParameter.objects.get_or_create(
            key=key, defaults={"value": ""})
        serializer = ParameterSerializer(param, data={**request.data, "key": key})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        audit("parameter", 0, "PARAMETER_UPDATED", actor=request.user,
              detail={"key": key})
        return Response(serializer.data)
    try:
        param = CompanyParameter.objects.get(key=key)
    except CompanyParameter.DoesNotExist:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(ParameterSerializer(param).data)


# ===== Item Master (spec §5.0) — owned by HO Purchasing =====


from rest_framework.permissions import BasePermission  # noqa: E402

from .models import Item  # noqa: E402
from .procurement import next_item_code  # noqa: E402
from .serializers_documents import ItemSerializer  # noqa: E402


class IsPurchasingOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True  # sites need the catalog for MR autocomplete
        return request.user.role in ("HO_PURCHASING", "ADMIN")


class CanEditCatalogItem(BasePermission):
    """HO Purchasing/Admin manage the catalogue; site teams may CREATE a
    missing item (flagged provisional) while receiving goods / adding tools."""
    OWNER = ("HO_PURCHASING", "ADMIN")
    CREATOR = OWNER + ("SITE_ADMIN", "SITE_ENGINEER", "PM")

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        if request.method == "POST":
            return request.user.role in self.CREATOR
        return request.user.role in self.OWNER   # PATCH: owners only


class ItemCategoryViewSet(viewsets.ModelViewSet):
    """Controlled item categories, managed by HO Purchasing on their own
    page (owner, 2026-07-08)."""
    from .models import ItemCategory
    from .serializers import ItemCategorySerializer

    serializer_class = ItemCategorySerializer
    permission_classes = [IsPurchasingOrReadOnly]
    queryset = ItemCategory.objects.all()
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def perform_destroy(self, instance):
        # Keep categories still in use by items — deactivate instead
        if Item.objects.filter(category=instance.name).exists():
            instance.is_active = False
            instance.save(update_fields=["is_active"])
        else:
            instance.delete()


class ItemViewSet(viewsets.ModelViewSet):
    serializer_class = ItemSerializer
    permission_classes = [CanEditCatalogItem]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = Item.objects.filter(merged_into__isnull=True).order_by("code")
        search = self.request.GET.get("search")
        if search:
            from django.db.models import Q

            qs = qs.filter(Q(description__icontains=search) |
                           Q(code__icontains=search) |
                           Q(category__icontains=search))
        if self.request.GET.get("active") != "all":
            qs = qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        from django.db import transaction

        # A site team creating a missing item marks it provisional for HO review
        provisional = self.request.user.role not in ("HO_PURCHASING", "ADMIN")
        with transaction.atomic():  # row-locked counter needs a transaction
            item = serializer.save(code=next_item_code(),
                                   is_provisional=provisional)
        audit("item", item.id, "ITEM_CREATED", actor=self.request.user,
              detail={"code": item.code, "provisional": provisional})

    def perform_update(self, serializer):
        item = serializer.save()
        audit("item", item.id, "ITEM_UPDATED", actor=self.request.user,
              detail={"fields": sorted(self.request.data.keys())})

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """HO Purchasing / Admin confirm a site-created provisional item."""
        if request.user.role not in ("HO_PURCHASING", "ADMIN"):
            return Response({"detail": "HO Purchasing/Admin approve items."},
                            status=403)
        item = self.get_object()
        item.is_provisional = False
        item.save(update_fields=["is_provisional", "updated_at"])
        audit("item", item.id, "ITEM_APPROVED", actor=request.user)
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None):
        """Duplicate resolution (spec §5.0): this item merges into target;
        existing document lines keep their history."""
        item = self.get_object()
        try:
            target = Item.objects.get(pk=request.data.get("target_id"),
                                      merged_into__isnull=True)
        except Item.DoesNotExist:
            return Response({"detail": "target_id must be an unmerged item."},
                            status=400)
        if target.pk == item.pk:
            return Response({"detail": "Cannot merge an item into itself."},
                            status=400)
        item.merged_into = target
        item.is_active = False
        item.save(update_fields=["merged_into", "is_active"])
        audit("item", item.id, "ITEM_MERGED", actor=request.user,
              to_state=target.code)
        return Response(self.get_serializer(target).data)
