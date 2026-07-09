"""Project cost control API (§6C, M7). Cost figures are commercially
sensitive (§6C.5): Admin, HO roles, Senior Management, and the assigned PM
for their own sites. Site-level users see no cost data."""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import staff_cost
from .models import Site

COST_ROLES = ("ADMIN", "DIRECTOR", "FINANCE", "HO_HR")


def _can_see_cost(user):
    return user.role in COST_ROLES


@api_view(["GET"])
def staff_cost_current(request):
    """Projected monthly staff cost from the current headcount (run-rate),
    per site and by job category. Basic pay only; never per-employee."""
    if not _can_see_cost(request.user):
        return Response({"detail": "Cost data is restricted."}, status=403)
    return Response(staff_cost.current_run_rate())


@api_view(["GET"])
def staff_cost_history(request):
    """Past-months salary summary from the locked Labour & Staff postings."""
    if not _can_see_cost(request.user):
        return Response({"detail": "Cost data is restricted."}, status=403)
    site = None
    if request.GET.get("site"):
        site = Site.objects.filter(pk=request.GET["site"]).first()
    return Response(staff_cost.history(site))
