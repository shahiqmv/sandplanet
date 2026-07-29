"""Company Profile module — ongoing-project entries + (later) PDF generation.

Marketing content, deliberately independent of the operational Project/Site
module (decades of pre-Planet work; content must not shift when operational
records change). Access is office-only: Admin, Director, Signatory, Marketing.
"""
from io import BytesIO

from django.core.files.base import ContentFile

from .audit import audit
from .models import ProfileEntry, ProfileGalleryImage

PROFILE_ROLES = ("ADMIN", "DIRECTOR", "SIGNATORY", "MARKETING")
MAX_GALLERY = 6
# (aspect_w, aspect_h, max_long_edge_px) — the layout depends on these exactly.
FEATURED = (1, 1, 1300)
GALLERY = (3, 2, 1000)
_EDITABLE = ("project_name", "client_display", "summary", "start_label",
             "start_value")


def can_edit(user):
    return user.role in PROFILE_ROLES


def _apply(entry, data):
    for f in _EDITABLE:
        if f in data:
            setattr(entry, f, (data.get(f) or "").strip())


def entry_dict(entry):
    return {
        "id": entry.id, "status": entry.status, "sort_order": entry.sort_order,
        "project_name": entry.project_name,
        "client_display": entry.client_display, "summary": entry.summary,
        "start_label": entry.start_label, "start_value": entry.start_value,
        "featured_url": entry.featured_image.url if entry.featured_image else "",
        "completed_at": entry.completed_at, "locked": entry.snapshot_locked,
        "gallery": [{"id": g.id, "url": g.image.url, "sort_order": g.sort_order}
                    for g in entry.gallery.all()],
    }


def create_entry(data, actor):
    order = (ProfileEntry.objects.filter(status="ONGOING").count() + 1) * 10
    entry = ProfileEntry(status="ONGOING", sort_order=order,
                         start_label="Commenced", created_by=actor)
    _apply(entry, data)
    if not entry.project_name.strip():
        return None, "A project needs a name."
    entry.save()
    audit("profile_entry", entry.id, "PROFILE_ENTRY_ADDED", actor=actor,
          detail={"name": entry.project_name})
    return entry, None


def update_entry(entry, data, actor):
    if entry.snapshot_locked:
        return "This entry is completed and locked — reopen it first to edit."
    _apply(entry, data)
    if not entry.project_name.strip():
        return "A project needs a name."
    entry.save()
    audit("profile_entry", entry.id, "PROFILE_ENTRY_EDITED", actor=actor)
    return None


def delete_entry(entry, actor):
    if entry.snapshot_locked:
        return "A completed entry can't be deleted."
    audit("profile_entry", entry.id, "PROFILE_ENTRY_DELETED", actor=actor,
          detail={"name": entry.project_name})
    entry.delete()
    return None


def reorder(order_ids, actor):
    """Set sort_order to match the given list of ongoing-entry ids."""
    ids = [int(i) for i in order_ids]
    for i, eid in enumerate(ids, start=1):
        ProfileEntry.objects.filter(pk=eid, status="ONGOING").update(
            sort_order=i * 10)
    audit("profile_entry", 0, "PROFILE_REORDERED", actor=actor)
    return None


# ---- images (server-side guarantee so a bad upload can't break the grid) --

def _process(uploaded, aspect_w, aspect_h, max_edge):
    """Open, orient by EXIF then strip it, centre-crop to the EXACT aspect,
    downscale to the max long edge, re-encode JPEG Q85. The client crops too,
    but this guarantees the stored image regardless of what arrives."""
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(Image.open(uploaded)).convert("RGB")
    w, h = img.size
    target, cur = aspect_w / aspect_h, w / h
    if cur > target:                         # too wide → trim the sides
        nw = round(h * target)
        x = (w - nw) // 2
        img = img.crop((x, 0, x + nw, h))
    elif cur < target:                       # too tall → trim top/bottom
        nh = round(w / target)
        y = (h - nh) // 2
        img = img.crop((0, y, w, y + nh))
    if img.width > max_edge:
        img = img.resize((max_edge, round(img.height * max_edge / img.width)),
                         Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return ContentFile(buf.getvalue())


def set_featured(entry, uploaded, actor):
    if entry.snapshot_locked:
        return "This entry is locked — reopen it first."
    entry.featured_image.save("f.jpg", _process(uploaded, *FEATURED), save=True)
    audit("profile_entry", entry.id, "PROFILE_FEATURED_SET", actor=actor)
    return None


def add_gallery(entry, uploaded, actor):
    if entry.snapshot_locked:
        return None, "This entry is locked — reopen it first."
    if entry.gallery.count() >= MAX_GALLERY:
        return None, f"Up to {MAX_GALLERY} photos per project."
    order = (entry.gallery.count() + 1) * 10
    g = ProfileGalleryImage.objects.create(entry=entry, sort_order=order)
    g.image.save("g.jpg", _process(uploaded, *GALLERY), save=True)
    audit("profile_entry", entry.id, "PROFILE_GALLERY_ADDED", actor=actor)
    return g, None


def remove_gallery(img, actor):
    if img.entry.snapshot_locked:
        return "This entry is locked — reopen it first."
    eid = img.entry_id
    img.delete()
    audit("profile_entry", eid, "PROFILE_GALLERY_REMOVED", actor=actor)
    return None
