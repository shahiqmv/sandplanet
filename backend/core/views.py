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
from .permissions import IsAdmin, IsAdminOrReadOnly, scoped_site_ids
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
    }


# ===== Sites =====


class SiteViewSet(viewsets.ModelViewSet):
    serializer_class = SiteSerializer
    permission_classes = [IsAdminOrReadOnly]
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
    http_method_names = ["get", "post", "patch", "head", "options"]

    def perform_create(self, serializer):
        user = serializer.save()
        audit("user", user.id, "USER_CREATED", actor=self.request.user,
              detail={"username": user.username, "role": user.role})

    def perform_update(self, serializer):
        user = serializer.save()
        audit("user", user.id, "USER_UPDATED", actor=self.request.user,
              detail={"fields": sorted(self.request.data.keys())})

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
    http_method_names = ["get", "post", "patch", "head", "options"]


class HolidayViewSet(viewsets.ModelViewSet):
    serializer_class = HolidaySerializer
    permission_classes = [IsAdminOrReadOnly]
    queryset = Holiday.objects.all().order_by("day")
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]


@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def parameter_detail(request, key):
    if request.method == "PUT":
        if request.user.role != User.Role.ADMIN:
            return Response({"detail": "Admin only."}, status=403)
        param, _ = CompanyParameter.objects.get_or_create(key=key, defaults={"value": None})
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


class ItemViewSet(viewsets.ModelViewSet):
    serializer_class = ItemSerializer
    permission_classes = [IsPurchasingOrReadOnly]
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

        with transaction.atomic():  # row-locked counter needs a transaction
            item = serializer.save(code=next_item_code())
        audit("item", item.id, "ITEM_CREATED", actor=self.request.user,
              detail={"code": item.code})

    def perform_update(self, serializer):
        item = serializer.save()
        audit("item", item.id, "ITEM_UPDATED", actor=self.request.user,
              detail={"fields": sorted(self.request.data.keys())})

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
