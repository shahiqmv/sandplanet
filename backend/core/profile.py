"""Company Profile module — ongoing-project entries + (later) PDF generation.

Marketing content, deliberately independent of the operational Project/Site
module (decades of pre-Planet work; content must not shift when operational
records change). Access is office-only: Admin, Director, Signatory, Marketing.
"""
from .audit import audit
from .models import ProfileEntry

PROFILE_ROLES = ("ADMIN", "DIRECTOR", "SIGNATORY", "MARKETING")
MAX_GALLERY = 6
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
