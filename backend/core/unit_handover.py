"""Handing a project over unit by unit (owner 2026-10-05).

Where the work is villas or pools, the client takes each one as it is
finished rather than waiting for the whole project. A unit is offered for
inspection, walked jointly with the client, and handed over on a signed
certificate — with minor snags still open if need be; a major one holds it.

Decisions that are the owner's, not conveniences:
  * the unit's defects-liability period runs from ITS handover date;
  * retention is NOT released unit by unit — claims are untouched;
  * the project's own dossier (documents, transmittals, taking-over) stays
    as it is; the snags found in a unit are that dossier's snags, tagged
    with the unit.
"""
from datetime import date

from django.db import transaction
from django.utils import timezone

from . import handover
from .audit import audit
from .models import UnitHandover

RECORD_ROLES = handover.RECORDER_ROLES     # the site team and above
UNDO_ROLES = handover.CLOSER_ROLES         # taking a step back


def _date(v):
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def _text(data, key, limit=None):
    v = " ".join(str(data.get(key) or "").split()) if limit else \
        str(data.get(key) or "").strip()
    return v[:limit] if limit else v


def _of(unit):
    return getattr(unit, "handover", None)


def open_snags(unit):
    return [s for s in unit.snags.all() if s.is_open]


def _next_certificate_no(project):
    n = UnitHandover.objects.filter(unit__project=project).exclude(
        certificate_no="").count() + 1
    return f"UHC-{project.code}-{n:03d}"


@transaction.atomic
def offer(unit, data, user):
    """The unit is ready: offer it to the client for inspection."""
    if _of(unit) is not None:
        return None, "This unit has already been offered for handover."
    on = _date(data.get("offered_on")) or timezone.localdate()
    h = UnitHandover.objects.create(
        unit=unit, offered_on=on, offered_by=user,
        percent_at_offer=unit.percent or 0,
        proposed_inspection=_date(data.get("proposed_inspection")),
        notes=_text(data, "notes"))
    audit("project", unit.project_id, "UNIT_OFFERED_FOR_HANDOVER", actor=user,
          detail={"unit": unit.ref, "percent": str(unit.percent),
                  "inspection": str(h.proposed_inspection or "")})
    return h, None


@transaction.atomic
def record_inspection(unit, data, user):
    """The joint walk-round with the client. Snags are raised against the
    unit separately; this records that the inspection happened and who was
    there, and issues the certificate number the handover will carry."""
    h = _of(unit)
    if h is None:
        return None, "Offer the unit for inspection first."
    if h.status == "HANDED_OVER":
        return None, "This unit is already handed over."
    on = _date(data.get("inspected_on"))
    if on is None:
        return None, "Give the date of the inspection."
    if on > timezone.localdate():
        return None, "The inspection date is in the future."
    who = _text(data, "client_attendees")
    if not who:
        return None, "Say who attended for the client."
    h.inspected_on, h.client_attendees = on, who
    h.our_attendees = _text(data, "our_attendees")
    h.inspection_notes = _text(data, "inspection_notes")
    h.status = "INSPECTED"
    if not h.certificate_no:
        h.certificate_no = _next_certificate_no(unit.project)
    h.save()
    audit("project", unit.project_id, "UNIT_INSPECTED", actor=user,
          detail={"unit": unit.ref, "on": str(on),
                  "open_snags": len(open_snags(unit))})
    return h, None


def handover_block(unit):
    """Why this unit cannot be handed over now, or None."""
    h = _of(unit)
    if h is None or h.status == "OFFERED":
        return "Record the joint inspection first."
    if h.status == "HANDED_OVER":
        return "This unit is already handed over."
    major = [s.ref_no for s in open_snags(unit) if s.severity == "MAJOR"]
    if major:
        return ("Major snags are still open: " + ", ".join(major) + ". Close "
                "them, or mark them minor if the client accepts the unit "
                "with them.")
    return None


@transaction.atomic
def hand_over(unit, data, user, signed_copy=None):
    """The client has taken the unit. Its defects period starts here."""
    block = handover_block(unit)
    if block:
        return None, block
    h = unit.handover
    on = _date(data.get("handed_over_on"))
    if on is None:
        return None, "Give the date of handover."
    if on > timezone.localdate():
        return None, "The handover date is in the future."
    if on < h.inspected_on:
        return None, "The handover is dated before the inspection."
    signer = _text(data, "client_signatory", 120)
    if not signer:
        return None, "Say who signed for the client."
    h.handed_over_on, h.client_signatory = on, signer
    h.client_position = _text(data, "client_position", 120)
    h.status, h.recorded_by = "HANDED_OVER", user
    if signed_copy is not None:
        h.signed_copy = signed_copy
    h.save()
    audit("project", unit.project_id, "UNIT_HANDED_OVER", actor=user,
          detail={"unit": unit.ref, "on": str(on),
                  "certificate": h.certificate_no,
                  "open_snags": len(open_snags(unit)),
                  "dlp_ends": str(h.defects_liability_ends() or "")})
    return h, None


@transaction.atomic
def attach_signed_copy(unit, upload, user):
    h = _of(unit)
    if h is None or h.status == "OFFERED":
        return None, "There is no certificate yet — record the inspection."
    if upload is None:
        return None, "Choose the signed certificate."
    h.signed_copy = upload
    h.save(update_fields=["signed_copy", "updated_at"])
    audit("project", unit.project_id, "UNIT_HANDOVER_SIGNED_COPY", actor=user,
          detail={"unit": unit.ref, "certificate": h.certificate_no})
    return h, None


@transaction.atomic
def step_back(unit, reason, user):
    """Undo the last step — a handover recorded on the wrong unit, an offer
    made too early. The snags stay: they were found, whatever happens to the
    paperwork."""
    h = _of(unit)
    if h is None:
        return None, "This unit has not been offered."
    reason = (reason or "").strip()
    if not reason:
        return None, "Say why."
    was = h.status
    if was == "HANDED_OVER":
        h.status, h.handed_over_on = "INSPECTED", None
        h.client_signatory = h.client_position = ""
        h.save()
    elif was == "INSPECTED":
        h.status, h.inspected_on = "OFFERED", None
        h.save()
    else:
        h.delete()
        h = None
    audit("project", unit.project_id, "UNIT_HANDOVER_STEP_BACK", actor=user,
          detail={"unit": unit.ref, "from": was, "reason": reason[:200]})
    return h, None


# ---- for the screens ---------------------------------------------------------

def summary(unit):
    """The few facts the unit board shows. Safe for the client portal."""
    h = _of(unit)
    snags = list(unit.snags.all())
    open_ = [s for s in snags if s.is_open]
    out = {"status": h.status if h else "NONE",
           "status_label": h.get_status_display() if h else "Not offered",
           "offered_on": h.offered_on if h else None,
           "proposed_inspection": h.proposed_inspection if h else None,
           "inspected_on": h.inspected_on if h else None,
           "handed_over_on": h.handed_over_on if h else None,
           "dlp_ends": h.defects_liability_ends() if h else None,
           "certificate_no": h.certificate_no if h else "",
           "snags_total": len(snags), "snags_open": len(open_),
           "snags_major_open": sum(1 for s in open_ if s.severity == "MAJOR")}
    return out


def detail(unit, user):
    from .views_handover import SnagSerializer
    h = _of(unit)
    out = summary(unit)
    role = getattr(user, "role", "")
    out.update({
        "unit": {"id": unit.id, "ref": unit.ref, "name": unit.name,
                 "percent": unit.percent, "project_id": unit.project_id,
                 "project_code": unit.project.code},
        "client_attendees": h.client_attendees if h else "",
        "our_attendees": h.our_attendees if h else "",
        "inspection_notes": h.inspection_notes if h else "",
        "client_signatory": h.client_signatory if h else "",
        "client_position": h.client_position if h else "",
        "notes": h.notes if h else "",
        "offered_by": h.offered_by.full_name if h else "",
        "signed_copy_url": (h.signed_copy.url if h and h.signed_copy
                            else None),
        "dlp_months": unit.project.defects_liability_months,
        "handover_block": handover_block(unit) if h else None,
        "snags": SnagSerializer(
            unit.snags.select_related("owner", "raised_by", "unit")
            .order_by("status", "id"), many=True).data,
        "can_record": role in RECORD_ROLES,
        "can_undo": role in UNDO_ROLES,
        "can_close_snag": role in handover.CLOSER_ROLES,
    })
    return out


def project_summary(project):
    units = list(project.units.select_related("handover"))
    done = [u for u in units if getattr(_of(u), "status", "") == "HANDED_OVER"]
    return {"units": len(units), "handed_over": len(done),
            "offered": sum(1 for u in units if _of(u) is not None
                           and _of(u).status != "HANDED_OVER")}
