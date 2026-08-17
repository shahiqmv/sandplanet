from rest_framework.permissions import BasePermission

from .models import User


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.ADMIN


class IsSiteManagerOrReadOnly(BasePermission):
    """Site records: Admin + Director write (site management is an
    admin/HO function, spec §2); everyone in scope reads."""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return request.user.role in (User.Role.ADMIN, User.Role.DIRECTOR)


class IsAdminOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return request.user.role == User.Role.ADMIN


class IsHrAdminOrReadOnly(BasePermission):
    """Company masters the Director's office (PA) maintains as part of full HR
    access, alongside Admin (owner 2026-08-03). Read for any authed user."""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return request.user.role in (User.Role.ADMIN, User.Role.PA)


def scoped_site_ids(user):
    """Site ids the user may read. None = all sites (HO roles, spec §3)."""
    if user.is_ho:
        return None
    return user.allocated_site_ids()


# Who may see what an individual is paid: HR/Payroll, Finance, the Director's
# office (PA), Admin, and the signatory who signs the payment.
PAY_ROLES = ("HO_HR", "FINANCE", "ADMIN", "PA", "SIGNATORY")


def sees_pay(user):
    return user.role in PAY_ROLES


def sees_staff_pay(user):
    """A MANAGEMENT salary is head-office business, never site business.

    A PM was reading the pay of the site engineer beside them, and of another
    PM's staff on an onboarding case — "causing some trouble" (owner
    2026-08-16). Site roles still see their WORKERS' pay: they hire them,
    revise them and verify the payroll days. It is the STAFF grade that is
    closed, to everyone outside `PAY_ROLES` — the Director included, at the
    owner's word.
    """
    return sees_pay(user)


def is_staff_grade(category=None, grp=None):
    """Management, not trades. `category` is the onboarding quota class
    (SKILLED / UNSKILLED / STAFF); `grp` is ManpowerCategory.grp
    (STAFF / LABOUR). Either saying STAFF is enough."""
    return "STAFF" in (category or "", grp or "")
