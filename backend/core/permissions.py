from rest_framework.permissions import BasePermission

from .models import User


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.ADMIN


class IsAdminOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return request.user.role == User.Role.ADMIN


def scoped_site_ids(user):
    """Site ids the user may read. None = all sites (HO roles, spec §3)."""
    if user.is_ho:
        return None
    return user.allocated_site_ids()
