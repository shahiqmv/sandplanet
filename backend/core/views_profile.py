"""Company Profile API — office-only (Admin/Director/Signatory/Marketing).

Ongoing-project entries + reorder now; image upload, generate and mark-complete
land in later phases.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import profile as pf
from .models import ProfileEntry


def _guard(request):
    if not pf.can_edit(request.user):
        return Response({"detail": "Company Profile is management-only."},
                        status=403)
    return None


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def profile_entries(request):
    err = _guard(request)
    if err:
        return err
    if request.method == "POST":
        entry, msg = pf.create_entry(request.data, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
        return Response(pf.entry_dict(entry), status=201)
    entries = ProfileEntry.objects.prefetch_related("gallery").all()
    return Response({
        "ongoing": [pf.entry_dict(e) for e in entries
                    if e.status == "ONGOING"],
        "completed": [pf.entry_dict(e) for e in entries
                      if e.status == "COMPLETED"],
        "can_edit": True,
    })


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def profile_entry(request, pk):
    err = _guard(request)
    if err:
        return err
    entry = (ProfileEntry.objects.prefetch_related("gallery")
             .filter(pk=pk).first())
    if entry is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "DELETE":
        msg = pf.delete_entry(entry, request.user)
    else:
        msg = pf.update_entry(entry, request.data, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    if request.method == "DELETE":
        return Response(status=204)
    entry.refresh_from_db()
    return Response(pf.entry_dict(entry))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def profile_reorder(request):
    err = _guard(request)
    if err:
        return err
    pf.reorder(request.data.get("order") or [], request.user)
    return Response({"ok": True})
