"""Company Profile API — office-only (Admin/Director/Signatory/Marketing).

Ongoing-project entries + reorder now; image upload, generate and mark-complete
land in later phases.
"""
from rest_framework.decorators import (api_view, parser_classes,
                                       permission_classes)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import profile as pf
from .models import ProfileEntry, ProfileGalleryImage, ProfileReferee


def _referee_dict(r):
    return {"id": r.id, "name": r.name, "role": r.role, "org": r.org,
            "email": r.email, "sort_order": r.sort_order}


def _guard(request):
    if not pf.can_edit(request.user):
        return Response({"detail": "Company Profile is management-only."},
                        status=403)
    return None


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def profile_referees(request):
    """The 'Trusted by the industry' referees — list / add."""
    err = _guard(request)
    if err:
        return err
    if request.method == "POST":
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"detail": "A referee needs a name."}, status=400)
        order = (ProfileReferee.objects.count() + 1) * 10
        r = ProfileReferee.objects.create(
            name=name[:120], role=(request.data.get("role") or "").strip()[:160],
            org=(request.data.get("org") or "").strip()[:160],
            email=(request.data.get("email") or "").strip()[:160],
            sort_order=order)
        return Response(_referee_dict(r), status=201)
    return Response([_referee_dict(r) for r in ProfileReferee.objects.all()])


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def profile_referee(request, pk):
    err = _guard(request)
    if err:
        return err
    try:
        r = ProfileReferee.objects.get(pk=pk)
    except ProfileReferee.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "DELETE":
        r.delete()
        return Response(status=204)
    for f in ("name", "role", "org", "email"):
        if f in request.data:
            setattr(r, f, (request.data.get(f) or "").strip()[:160])
    r.save()
    return Response(_referee_dict(r))


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


def _entry(pk):
    return ProfileEntry.objects.prefetch_related("gallery").filter(pk=pk).first()


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def profile_featured(request, pk):
    """Upload/replace the square featured image (cropped client-side; the server
    re-crops to 1:1 and downscales as a guarantee)."""
    err = _guard(request)
    if err:
        return err
    entry = _entry(pk)
    if entry is None:
        return Response({"detail": "Not found."}, status=404)
    up = request.FILES.get("file")
    if up is None:
        return Response({"detail": "An image file is required."}, status=400)
    msg = pf.set_featured(entry, up, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    entry.refresh_from_db()
    return Response(pf.entry_dict(entry))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def profile_gallery(request, pk):
    """Add one 3:2 gallery image (up to six per project)."""
    err = _guard(request)
    if err:
        return err
    entry = _entry(pk)
    if entry is None:
        return Response({"detail": "Not found."}, status=404)
    up = request.FILES.get("file")
    if up is None:
        return Response({"detail": "An image file is required."}, status=400)
    _, msg = pf.add_gallery(entry, up, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    entry.refresh_from_db()
    return Response(pf.entry_dict(entry))


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def profile_generate(request):
    """Render the profile PDF. ?preview=1 → watermarked, uncompressed, inline;
    otherwise the compressed final (also archived, dated, to storage)."""
    from django.http import HttpResponse

    from . import profile_render as pr
    err = _guard(request)
    if err:
        return err
    mode = "preview" if request.GET.get("preview") else "final"
    pdf = pr.generate(mode)
    if mode == "final":
        try:
            from django.core.files.base import ContentFile
            from django.core.files.storage import default_storage
            from django.utils import timezone
            stamp = timezone.now().strftime("%Y%m%d-%H%M")
            default_storage.save(f"profile/generated/profile-{stamp}.pdf",
                                 ContentFile(pdf))
        except Exception:                        # pragma: no cover - defensive
            pass
    resp = HttpResponse(pdf, content_type="application/pdf")
    disp = "inline" if mode == "preview" else "attachment"
    resp["Content-Disposition"] = (
        f'{disp}; filename="Sand_Planet_Company_Profile.pdf"')
    return resp


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def profile_gallery_delete(request, gid):
    err = _guard(request)
    if err:
        return err
    img = ProfileGalleryImage.objects.select_related("entry").filter(
        pk=gid).first()
    if img is None:
        return Response({"detail": "Not found."}, status=404)
    msg = pf.remove_gallery(img, request.user)
    if msg:
        return Response({"detail": msg}, status=400)
    return Response(status=204)
