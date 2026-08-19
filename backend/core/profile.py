"""Company Profile module — ongoing-project entries + (later) PDF generation.

Marketing content, deliberately independent of the operational Project/Site
module (decades of pre-Planet work; content must not shift when operational
records change). Access is office-only: Admin, Director, Signatory, Marketing.
"""
from io import BytesIO

from django.core.files.base import ContentFile

from .audit import audit
from .models import ProfileEntry, ProfileGalleryImage

PROFILE_ROLES = ("ADMIN", "DIRECTOR", "SIGNATORY", "MARKETING", "PA")
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


# ---- management, corporate info and settings -----------------------------
# All three were literals in profile_render.py: adding a director or correcting
# the headcount meant a code change and a deploy. Management and manpower move
# far more often than the code does (owner 2026-08-19).

def mgmt_dict(m):
    return {"id": m.id, "name": m.name, "role": m.role, "intro": m.intro,
            "photo_url": m.photo.url if m.photo else "",
            "sort_order": m.sort_order, "is_active": m.is_active}


def row_dict(r):
    return {"id": r.id, "label": r.label, "value": r.value,
            "sort_order": r.sort_order, "is_active": r.is_active}


def settings_dict(st):
    return {"cover_url": st.cover_image.url if st.cover_image else "",
            "vision": st.vision, "mission": st.mission}


def save_management(data, actor, person=None):
    from .models import ProfileManagement

    name = (data.get("name") or "").strip()
    if not name:
        return None, "A name is required."
    if person is None:
        order = (ProfileManagement.objects.count() + 1) * 10
        person = ProfileManagement(sort_order=order)
    person.name = name
    person.role = (data.get("role") or "").strip()
    person.intro = (data.get("intro") or "").strip()
    if "is_active" in data:
        person.is_active = bool(data["is_active"])
    person.save()
    audit("profile_mgmt", person.id, "PROFILE_MGMT_SAVED", actor=actor,
          detail={"name": person.name})
    return person, None


def set_mgmt_photo(person, uploaded, actor):
    """Square, like the placeholder circle it replaces — a portrait cropped to
    anything else would sit oddly in the round frame."""
    person.photo.save("m.jpg", _process(uploaded, 1, 1, 600), save=True)
    audit("profile_mgmt", person.id, "PROFILE_MGMT_PHOTO", actor=actor)
    return None


def save_corporate_row(data, actor, row=None):
    from .models import ProfileCorporateRow

    label = (data.get("label") or "").strip()
    if not label:
        return None, "A label is required."
    if row is None:
        order = (ProfileCorporateRow.objects.count() + 1) * 10
        row = ProfileCorporateRow(sort_order=order)
    row.label = label
    row.value = (data.get("value") or "").strip()
    if "is_active" in data:
        row.is_active = bool(data["is_active"])
    row.save()
    audit("profile_corporate", row.id, "PROFILE_CORPORATE_SAVED", actor=actor,
          detail={"label": row.label})
    return row, None


def save_settings(data, actor):
    from .models import ProfileSettings

    st = ProfileSettings.get()
    for f in ("vision", "mission"):
        if f in data:
            setattr(st, f, (data.get(f) or "").strip())
    st.save()
    audit("profile_settings", 1, "PROFILE_SETTINGS_SAVED", actor=actor)
    return st, None


# The cover photo fills the band above the title: the FULL 210mm page width by
# 176mm tall, i.e. slightly wider than it is tall. Getting this wrong crops the
# picture twice — once on upload and again by object-fit — and throws away the
# sides of a landscape shot (owner 2026-08-19, on the pool project photo).
COVER = (210, 176, 2000)


def set_cover(uploaded, actor):
    """The profile's cover photo, cropped to the exact shape of the cover
    band so nothing is lost to a second crop at render time."""
    from .models import ProfileSettings

    st = ProfileSettings.get()
    st.cover_image.save("cover.jpg", _process(uploaded, *COVER), save=True)
    audit("profile_settings", 1, "PROFILE_COVER_SET", actor=actor)
    return None


def clear_cover(actor):
    """Back to the old behaviour — the first ongoing project's photo."""
    from .models import ProfileSettings

    st = ProfileSettings.get()
    st.cover_image.delete(save=True)
    audit("profile_settings", 1, "PROFILE_COVER_CLEARED", actor=actor)
    return None


def reorder_generic(model, order_ids, actor, event):
    for i, oid in enumerate([int(i) for i in order_ids], start=1):
        model.objects.filter(pk=oid).update(sort_order=i * 10)
    audit("profile", 0, event, actor=actor)
    return None
