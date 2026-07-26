"""Procurement Schedule — Phase 2: the schedule WATCHES execution documents.

A schedule line can be linked to the operational documents that fulfil it — a
MAR (material approval / TDS), an IPR (import order), a GRN (site receipt) — and
from those links, plus the manual production flag, we DERIVE a read-only
pipeline: TDS → Order → Production → Shipment → Delivery, with an estimated ETA
to site. The shipment and ETA come off the linked IPR's shipment automatically,
so nobody re-keys them. Nothing here mutates an execution document; it only
reads their status and records which document fulfils the line.

Retroactive linking: when a schedule is drawn up after execution has already
started, `link_candidates` surfaces the MAR/IPR/GRN documents that match the
line's project (and item, where the document carries typed lines) so the link
is one click rather than a ref hunt.
"""
import logging
from datetime import timedelta

from .audit import audit
from .models import (Document, ImportOrder, ImportOrderLine, ShipmentTracking,
                     ScheduleLine)
from .procurement_schedule import CONFIRM_ROLES, PROPOSE_ROLES, schedule_dict

log = logging.getLogger(__name__)

# Days added to a shipment's ETA to estimate arrival at the resort/site (sea
# leg from Male + island transfer). A rough default until Phase 3 tunes it.
SITE_BUFFER_DAYS = 5

# The project/commercial team and Purchasing maintain the links; the pipeline
# itself is read-only for everyone.
LINK_ROLES = tuple(dict.fromkeys((*PROPOSE_ROLES, *CONFIRM_ROLES)))

# slot -> (doc_type, ScheduleLine FK attr)
LINK_SLOTS = {"mar": ("MAR", "mar"), "ipr": ("IPR", "ipr"),
              "grn": ("GRN", "grn")}

PRODUCTION_LABEL = {"PENDING": "Pending", "IN_PRODUCTION": "In production",
                    "COMPLETED": "Completed"}


def _stage(key, label, state, detail, ref="", doc_id=None):
    """A pipeline stage. state ∈ none|na|pending|done|warn."""
    return {"key": key, "label": label, "state": state, "detail": detail,
            "ref": ref, "doc_id": doc_id}


def _title(s):
    return (s or "").replace("_", " ").title()


# ---- shipment / ETA derivation (off the linked IPR) ----------------------

def _shipment_for(line):
    """A line's shipment: an explicitly linked one, else the linked IPR's
    latest shipment (the schedule watches, so it follows the order)."""
    if line.shipment_id:
        return line.shipment
    if line.ipr_id:
        order = ImportOrder.objects.filter(document_id=line.ipr_id).first()
        if order:
            return order.shipments.order_by("-id").first()
    return None


def _site_eta(shipment):
    """Estimated arrival at site = shipment ETA (tracker-refined if live) +
    the site buffer. Returns a date or None."""
    if shipment is None:
        return None
    eta = None
    tr = ShipmentTracking.objects.filter(shipment=shipment).first()
    if tr and tr.current_eta:
        eta = tr.current_eta.date()
    elif shipment.eta:
        eta = shipment.eta
    return eta + timedelta(days=SITE_BUFFER_DAYS) if eta else None


# ---- per-stage derivation ------------------------------------------------

def _tds_stage(line):
    doc = line.mar
    if not doc:
        return _stage("tds", "TDS / MAR",
                      "none" if line.tds_required else "na",
                      "Required — not linked" if line.tds_required
                      else "Not required")
    s = doc.status
    if s in ("APPROVED", "APPROVED_WITH_COMMENTS"):
        state = "done"
    elif s in ("REJECTED", "REVISE_RESUBMIT"):
        state = "warn"
    else:
        state = "pending"
    return _stage("tds", "TDS / MAR", state, _title(s), doc.ref, doc.id)


def _order_stage(line):
    doc = line.ipr
    if not doc:
        return _stage("order", "Order (IPR)", "none", "Not ordered")
    s = doc.status
    state = "done" if s in ("AUTHORISED", "CLOSED") else (
        "warn" if s == "CANCELLED" else "pending")
    return _stage("order", "Order (IPR)", state, _title(s), doc.ref, doc.id)


def _production_stage(line):
    ps = line.production_status or "PENDING"
    state = {"PENDING": "none", "IN_PRODUCTION": "pending",
             "COMPLETED": "done"}.get(ps, "none")
    return _stage("production", "Production", state,
                  PRODUCTION_LABEL.get(ps, ps))


def _shipment_stage(line):
    sh = _shipment_for(line)
    if sh is None:
        return _stage("shipment", "Shipment", "none", "Not shipped")
    state = "done" if sh.status in ("ARRIVED", "CLEARED") else "pending"
    ref = ""
    order = getattr(sh, "order", None)
    if order and order.document_id:
        ref = order.document.ref
    return _stage("shipment", "Shipment", state, _title(sh.status), ref)


def _delivery_stage(line):
    doc = line.grn
    if not doc:
        return _stage("delivery", "Delivery", "none", "Not received")
    if doc.status == "COMPLETE":
        return _stage("delivery", "Delivery", "done", "Received at site",
                      doc.ref, doc.id)
    if doc.status == "SHORTAGE_REPORTED":
        return _stage("delivery", "Delivery", "warn", "Shortage reported",
                      doc.ref, doc.id)
    return _stage("delivery", "Delivery", "pending", _title(doc.status),
                  doc.ref, doc.id)


def _eta_stage(line):
    sh = _shipment_for(line)
    site_eta = _site_eta(sh)
    if line.grn_id and line.grn.status in ("COMPLETE", "SHORTAGE_REPORTED"):
        return _stage("eta", "ETA to site", "done", "Delivered")
    if site_eta is None:
        return _stage("eta", "ETA to site",
                      "pending" if sh is not None else "none",
                      "No ETA yet" if sh is not None else "—")
    late = line.required_date and site_eta > line.required_date
    return _stage("eta", "ETA to site", "warn" if late else "pending",
                  ("Late — ~%s" if late else "~%s") % site_eta.isoformat())


def line_pipeline(line):
    """The six derived stages for a line, in flow order."""
    return [_tds_stage(line), _order_stage(line), _production_stage(line),
            _shipment_stage(line), _delivery_stage(line), _eta_stage(line)]


# ---- linking -------------------------------------------------------------

def _resolve(ref, doc_type):
    return Document.objects.filter(ref=(ref or "").strip(), doc_type=doc_type,
                                   is_void=False).first()


def link_doc(line, slot, ref, actor):
    """Link an execution document to a line by its ref (idempotent set)."""
    if actor.role not in LINK_ROLES:
        return "Not permitted to link documents."
    if slot not in LINK_SLOTS:
        return "Unknown link slot."
    doc_type, field = LINK_SLOTS[slot]
    doc = _resolve(ref, doc_type)
    if doc is None:
        return f"No {doc_type} found with ref {ref!r}."
    setattr(line, field, doc)
    line.save(update_fields=[field, "updated_at"])
    audit("document", line.schedule.document_id, "PSC_LINE_LINKED", actor=actor,
          detail={"line": line.id, "slot": slot, "ref": doc.ref})
    return None


def unlink_doc(line, slot, actor):
    if actor.role not in LINK_ROLES:
        return "Not permitted to unlink documents."
    if slot not in LINK_SLOTS:
        return "Unknown link slot."
    _, field = LINK_SLOTS[slot]
    setattr(line, field, None)
    line.save(update_fields=[field, "updated_at"])
    audit("document", line.schedule.document_id, "PSC_LINE_UNLINKED",
          actor=actor, detail={"line": line.id, "slot": slot})
    return None


def set_production(line, status, actor):
    """Manual production flag for made-to-order items (no watched doc)."""
    if actor.role not in LINK_ROLES:
        return "Not permitted to update production status."
    if status not in PRODUCTION_LABEL:
        return "Unknown production status."
    line.production_status = status
    line.save(update_fields=["production_status", "updated_at"])
    audit("document", line.schedule.document_id, "PSC_LINE_PRODUCTION",
          actor=actor, detail={"line": line.id, "status": status})
    return None


def _cand(doc, note=""):
    return {"ref": doc.ref, "doc_id": doc.id, "status": doc.status,
            "date": doc.doc_date, "note": note}


def link_candidates(line, slot):
    """Execution docs that plausibly fulfil this line — matched on project, and
    on item where the doc type carries typed line items."""
    proj_id = line.schedule.project_id
    site_id = line.schedule.document.site_id
    item_id = line.item_id
    if slot == "mar":
        # MAR is project-wise; item lives only in its payload, so match project.
        qs = Document.objects.filter(doc_type="MAR", project_id=proj_id,
                                     is_void=False).order_by("-doc_date")
        return [_cand(d) for d in qs[:25]]
    if slot == "ipr":
        # IPR carries no project FK — the project lives on the order-line
        # allocation, so reach it through ImportOrderLine.
        q = ImportOrderLine.objects.filter(allocations__project_id=proj_id)
        if item_id:
            q = q.filter(item_id=item_id)
        doc_ids = list(q.values_list("order__document_id", flat=True)
                       .distinct())
        qs = Document.objects.filter(id__in=doc_ids, is_void=False).order_by(
            "-doc_date")
        return [_cand(d, "matches item" if item_id else "") for d in qs[:25]]
    if slot == "grn":
        qs = Document.objects.filter(doc_type="GRN", site_id=site_id,
                                     is_void=False)
        if item_id:
            qs = qs.filter(revisions__lines__item_id=item_id).distinct()
        return [_cand(d) for d in qs.order_by("-doc_date")[:25]]
    return []


def line_detail(line, user):
    """Fresh schedule payload after a link/production change."""
    return schedule_dict(line.schedule, user)
