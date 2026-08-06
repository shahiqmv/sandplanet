"""Procurement Schedule service (per-project planning layer).

The schedule is a Document subtype (doc_type PSC) that WATCHES the execution
documents rather than duplicating them. This module owns the spine: create the
schedule, propose/confirm/edit lines, and run the sign-off cycle — PM drafts,
Purchasing confirms the commercial fields, the Director (PD) signs off the
baseline. Document linking, the derived pipeline, the late-risk engine, client
lines, values and the client export build on top of this in later phases.
"""
import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .audit import audit
from .models import (Approval, Document, DocumentRevision, Item,
                     ProcurementSchedule, ScheduleLine, ScheduleSection)
from .numbering import next_ref

log = logging.getLogger(__name__)

# The schedule starts from the commercial side (the QS is its natural
# custodian), but proposing lines isn't locked down — the whole project/
# commercial team can add lines; Purchasing and the PD are the real gates.
PROPOSE_ROLES = ("QS", "PM", "SITE_ENGINEER", "SITE_ADMIN", "DIRECTOR",
                 "ADMIN")                        # who proposes / edits planning
# Two-step control (owner 2026-08-01, "option A"): Purchasing confirms the
# commercial fields, THEN the Director signs off. The whose-turn indicator and
# task-queue routing below make it clear who acts next, so it never looks stuck.
CONFIRM_ROLES = ("HO_PURCHASING", "ADMIN")     # who confirms commercial fields
SIGNOFF_ROLES = ("DIRECTOR", "ADMIN")          # the PD sign-off gate
VIEW_ROLES = ("HO_PURCHASING", "DIRECTOR", "SIGNATORY", "FINANCE", "QS",
              "ADMIN", "PA")                    # HO roles that see all schedules

# Planning fields the PM owns; commercial fields Purchasing owns.
_PLAN_FIELDS = ("bundle", "category", "description", "make_brand",
                "specification", "uom", "trade", "remarks")
_COMM_FIELDS = ("planned_supplier", "source_country")


def _dec(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


# ---- transitions (mirrors onboarding/payments) ---------------------------

def _transition(doc, new_status):
    return new_status in Document.TRANSITIONS["PSC"].get(doc.status, set())


def _record(doc, action, user, comment=""):
    Approval.objects.create(
        document=doc, revision=doc.current_revision, action=action,
        actor=user, actor_role=user.role, comment=comment)


def _set_status(doc, new_status, action, user, comment="", notify=True):
    doc.status = new_status
    doc.save(update_fields=["status", "updated_at"])
    _record(doc, action, user, comment=comment)
    if notify:
        _notify(doc, user)


def _notify(doc, actor):
    from .notify import notify_document
    try:
        notify_document(doc, actor)
    except Exception:                       # pragma: no cover - defensive
        log.exception("notify_document(PSC) failed")


# ---- create / fetch ------------------------------------------------------

def get_or_create_schedule(project, actor):
    """One schedule per project. Created lazily by the PM (or HO) on first use."""
    sched = ProcurementSchedule.objects.filter(project=project).first()
    if sched:
        return sched, None
    if actor.role not in (*PROPOSE_ROLES, *VIEW_ROLES):
        return None, "Not permitted to open a schedule."
    site = project.site
    with transaction.atomic():
        doc = Document.objects.create(
            doc_type="PSC", ref=next_ref("PSC", site), site=site,
            project=project, doc_date=timezone.localdate(), status="DRAFT",
            created_by=actor)
        rev = DocumentRevision.objects.create(
            document=doc, rev_label="R0", payload={}, created_by=actor)
        doc.current_revision = rev
        doc.save(update_fields=["current_revision"])
        sched = ProcurementSchedule.objects.create(document=doc, project=project)
    audit("document", doc.id, "PSC_CREATED", actor=actor,
          detail={"ref": doc.ref, "project": project.code})
    return sched, None


def _get_section(sched, data):
    """Resolve or create the line's section from {section_id} or {section_code,
    section_title}. A supplied section_title always renames the resolved section
    — so editing the title on a line's Edit form updates its section header
    (the edit form sends section_id, which used to skip the rename)."""
    title = (data.get("section_title") or "").strip()

    def _rename(sec):
        if sec and title and sec.title != title:
            sec.title = title
            sec.save(update_fields=["title"])
        return sec

    sid = data.get("section_id")
    if sid:
        return _rename(sched.sections.filter(pk=sid).first())
    code = (data.get("section_code") or "").strip()
    if not code:
        return None
    sec = sched.sections.filter(code__iexact=code).first()
    if sec:
        return _rename(sec)
    order = (sched.sections.count() + 1) * 10
    return ScheduleSection.objects.create(schedule=sched, code=code.upper(),
                                          title=title or code.upper(),
                                          sort_order=order)


# ---- lines ---------------------------------------------------------------

def add_line(sched, data, actor):
    """PM proposes a new line. Adding to a signed-off schedule reopens a change
    batch (already-signed lines stay operational)."""
    if actor.role not in PROPOSE_ROLES:
        return None, "Only the PM proposes schedule lines."
    doc = sched.document
    if doc.status not in ("DRAFT", "SIGNED_OFF"):
        return None, "The schedule is mid sign-off; wait for the current batch."
    if not (data.get("description") or "").strip():
        return None, "A line needs a description."
    section = _get_section(sched, data)
    with transaction.atomic():
        if doc.status == "SIGNED_OFF":       # reopen for a change batch
            _set_status(doc, "DRAFT", "REOPEN", actor,
                        comment="Change batch opened", notify=False)
        line = ScheduleLine(schedule=sched, section=section,
                            supply_by=(data.get("supply_by") or "CONTRACTOR"),
                            created_by=actor)
        _apply_plan(line, data)
        _apply_required(line, data)
        line.save()
        _renumber(section)
    audit("document", doc.id, "PSC_LINE_ADDED", actor=actor,
          detail={"line": line.id})
    return line, None


def update_line(line, data, actor):
    """PM edits planning fields (while draft); Purchasing edits commercial
    fields (while submitted)."""
    doc = line.schedule.document
    role = actor.role
    if role in PROPOSE_ROLES and doc.status == "DRAFT":
        _apply_plan(line, data)
        _apply_required(line, data)
        if "supply_by" in data and data["supply_by"] in ("CONTRACTOR", "CLIENT"):
            line.supply_by = data["supply_by"]
        if "section_id" in data or "section_code" in data:
            sec = _get_section(line.schedule, data)
            if sec and sec.id != line.section_id:
                old = line.section
                line.section = sec
                line.save()
                _renumber(old)
                _renumber(sec)
    elif role in CONFIRM_ROLES and doc.status == "SUBMITTED":
        _apply_commercial(line, data)
    else:
        return "This line can't be edited at its current stage by your role."
    line.save()
    audit("document", doc.id, "PSC_LINE_EDITED", actor=actor,
          detail={"line": line.id})
    return None


def delete_line(line, actor):
    """PM removes a not-yet-confirmed line while the schedule is a draft."""
    doc = line.schedule.document
    if actor.role not in PROPOSE_ROLES or doc.status != "DRAFT":
        return ("Lines can only be removed by the PM while the schedule is a "
                "draft.")
    if line.state != "PROPOSED":
        return "A confirmed or signed line can't be deleted — cancel it instead."
    section = line.section
    line.delete()
    _renumber(section)
    audit("document", doc.id, "PSC_LINE_DELETED", actor=actor)
    return None


def cancel_line(line, note, actor):
    """Cancelling a signed line needs the Director, with a reason."""
    if actor.role not in SIGNOFF_ROLES:
        return "Only the Director cancels a schedule line."
    if not (note or "").strip():
        return "A reason is required to cancel a line."
    line.state = "CANCELLED"
    line.save(update_fields=["state", "updated_at"])
    audit("document", line.schedule.document_id, "PSC_LINE_CANCELLED",
          actor=actor, detail={"line": line.id, "reason": note})
    return None


SPLIT_ROLES = (*PROPOSE_ROLES, *CONFIRM_ROLES)   # operational, like doc-linking

# Fields a split sibling inherits from its parent line — the material identity +
# planning + commercial values, and the shared MAR/TDS. It does NOT inherit the
# order links (ipr/shipment/grn), production stage, quotes or award — each split
# gets its own IPR and tracks independently.
_SPLIT_COPY = ("category", "item_id", "description", "make_brand",
               "specification", "uom", "trade", "supply_by", "required_date",
               "tds_required", "remarks", "planned_supplier", "source_country",
               "currency", "lead_time_days", "mar_id")


def _split_label(line):
    """A bundle label so the split siblings collapse into one expandable row.
    Reuse the line's existing bundle, else derive one from its identity."""
    if (line.bundle or "").strip():
        return line.bundle.strip()
    base = (line.description or line.make_brand
            or (line.item.name if line.item_id else "") or "Split order")
    return " ".join(base.split())[:120]      # single-line, within max_length


def split_line(line, quantities, actor):
    """Split one line's order across several IPRs by dividing it into sibling
    sub-lines that share a bundle (so they roll up into one expandable row).
    Each sub-line links its own IPR / shipment / GRN. Operational — it does NOT
    re-open the sign-off; siblings inherit the parent's state (owner 2026-08-04).
    `quantities` is the full set of resulting quantities; the first stays on this
    line, the rest become new siblings. Returns (created_lines, error)."""
    if actor.role not in SPLIT_ROLES:
        return None, "Not permitted to split a schedule line."
    if line.state == "CANCELLED":
        return None, "A cancelled line can't be split."
    if line.supply_by != "CONTRACTOR":
        return None, ("Only a contractor-supplied line (which is ordered via "
                      "an IPR) can be split.")
    total = line.quantity
    if total is None or total <= 0:
        return None, "Set a quantity on the line before splitting it."
    parts = [_dec(q) for q in (quantities or [])]
    if len(parts) < 2 or any(p is None or p <= 0 for p in parts):
        return None, "Give at least two positive quantities to split into."
    if sum(parts, Decimal("0")) != total:
        return None, (f"The split quantities must add up to {total:g} "
                      f"{line.uom or ''}".strip() + ".")
    label = _split_label(line)
    est = line.estimated_value
    with transaction.atomic():
        # New siblings first, so the parent keeps the rounding remainder of value.
        siblings, given = [], Decimal("0")
        for q in parts[1:]:
            sib = ScheduleLine(schedule=line.schedule, section=line.section,
                               state=line.state, created_by=actor, quantity=q)
            for f in _SPLIT_COPY:
                setattr(sib, f, getattr(line, f))
            sib.bundle = label
            if est is not None:
                sib.estimated_value = (est * q / total).quantize(Decimal("0.01"))
                given += sib.estimated_value
            sib.save()
            siblings.append(sib)
        line.bundle = label
        line.quantity = parts[0]
        if est is not None:
            line.estimated_value = est - given          # remainder to the parent
        line.save()
        _renumber(line.section)
    audit("document", line.schedule.document_id, "PSC_LINE_SPLIT", actor=actor,
          detail={"line": line.id, "into": [s.id for s in siblings],
                  "quantities": [str(p) for p in parts]})
    return [line, *siblings], None


def set_reference_image(line, upload, actor):
    """Attach (or clear) a reference image on a schedule line — a product photo /
    sample shot so the planner and client plan show what's being procured."""
    if actor.role not in (*PROPOSE_ROLES, *CONFIRM_ROLES):
        return "Not permitted to edit this line."
    if upload is None:                           # clear it
        if line.reference_image:
            line.reference_image.delete(save=False)
        line.reference_image = None
        line.save(update_fields=["reference_image"])
        return None
    ctype = (getattr(upload, "content_type", "") or "").lower()
    if not ctype.startswith("image/"):
        return "The reference must be an image (PNG or JPG)."
    if line.reference_image:
        line.reference_image.delete(save=False)
    line.reference_image = upload
    line.save(update_fields=["reference_image"])
    return None


def _apply_plan(line, data):
    for f in _PLAN_FIELDS:
        if f in data:
            setattr(line, f, (data.get(f) or "").strip())


def _apply_required(line, data):
    if "item_id" in data:
        iid = data.get("item_id") or None
        # A stale/deleted catalog link would raise a FK IntegrityError (500) on
        # save. Drop it and keep the line as free-text rather than crash the
        # whole save (owner 2026-08-03 — "difficulty saving at times").
        if iid and not Item.objects.filter(pk=iid).exists():
            iid = None
        line.item_id = iid
    if "quantity" in data:
        line.quantity = _dec(data.get("quantity"))
    if "required_date" in data:
        line.required_date = data.get("required_date") or None
    if "tds_required" in data:
        line.tds_required = bool(data.get("tds_required"))


def _apply_commercial(line, data):
    for f in _COMM_FIELDS:
        if f in data:
            setattr(line, f, (data.get(f) or "").strip())
    if "estimated_value" in data:
        line.estimated_value = _dec(data.get("estimated_value"))
    if "currency" in data:
        line.currency = (data.get("currency") or "USD")[:3].upper()
    if "lead_time_days" in data:
        v = data.get("lead_time_days")
        line.lead_time_days = int(v) if str(v).isdigit() else None


def _renumber(section):
    if not section:
        return
    for i, ln in enumerate(section.lines.exclude(state="CANCELLED")
                           .order_by("s_no", "id"), start=1):
        if ln.s_no != i:
            ln.s_no = i
            ln.save(update_fields=["s_no"])


# ---- sign-off cycle ------------------------------------------------------

def submit(sched, actor):
    """PM sends the draft batch to Purchasing to confirm."""
    doc = sched.document
    if actor.role not in PROPOSE_ROLES:
        return "Only the PM submits the schedule."
    if doc.status != "DRAFT":
        return "Only a draft schedule can be submitted."
    if not sched.lines.filter(state="PROPOSED").exists():
        return "Add at least one proposed line before submitting."
    _set_status(doc, "SUBMITTED", "SUBMIT", actor)
    return None


def reopen(sched, actor):
    """A proposer reopens a signed-off schedule to change lines — the same
    change-batch add_line opens implicitly, but as an explicit action so the
    team can edit an existing signed-off schedule. Goes back to DRAFT; the
    signed lines stay operational until it's re-submitted and re-signed."""
    doc = sched.document
    if actor.role not in PROPOSE_ROLES:
        return "Only the project team can reopen the schedule for changes."
    if doc.status != "SIGNED_OFF":
        return "Only a signed-off schedule can be reopened for changes."
    _set_status(doc, "DRAFT", "REOPEN", actor,
                comment="Reopened for changes", notify=False)
    audit("document", doc.id, "PSC_REOPENED", actor=actor)
    return None


def decide(sched, action, actor, note=""):
    """Workflow action dispatch — shared by desktop and mobile."""
    doc = sched.document
    if action == "confirm":
        if actor.role not in CONFIRM_ROLES:
            return "Only Purchasing confirms the schedule."
        if not _transition(doc, "CONFIRMED"):
            return f"Cannot confirm a {doc.status} schedule."
        sched.lines.filter(state="PROPOSED").update(state="CONFIRMED")
        _set_status(doc, "CONFIRMED", "CONFIRM", actor)
        return None
    if action == "sign_off":
        if actor.role not in SIGNOFF_ROLES:
            return "Only the Director signs off the schedule."
        if not _transition(doc, "SIGNED_OFF"):
            return f"Cannot sign off a {doc.status} schedule."
        sched.lines.filter(state="CONFIRMED").update(state="SIGNED_OFF")
        if sched.baseline_signed_at is None:
            sched.baseline_signed_at = timezone.now()
            sched.baseline_signed_by = actor
            sched.save(update_fields=["baseline_signed_at",
                                      "baseline_signed_by"])
        _set_status(doc, "SIGNED_OFF", "SIGN_OFF", actor)
        return None
    if action == "return":
        if not (note or "").strip():
            return "A reason is required to return the schedule."
        if actor.role in CONFIRM_ROLES and doc.status == "SUBMITTED":
            _set_status(doc, "DRAFT", "RETURN", actor, comment=note)
            return None
        if actor.role in SIGNOFF_ROLES and doc.status == "CONFIRMED":
            _set_status(doc, "DRAFT", "RETURN", actor, comment=note)
            return None
        return "You can't return the schedule at its current stage."
    if action == "cancel":
        if actor.role not in SIGNOFF_ROLES:
            return "Only the Director cancels a schedule."
        if not _transition(doc, "CANCELLED"):
            return f"Cannot cancel a {doc.status} schedule."
        _set_status(doc, "CANCELLED", "CANCEL", actor, comment=note)
        return None
    return "Unknown action."


# ---- serialisation -------------------------------------------------------

def can_see_values(user, sched):
    """Values are internal: HO roles + the project's PM see them; SE/Site-Admin
    don't (mirrors the contract-value rate-visibility norm)."""
    if user.is_ho:
        return True
    if user.role == "PM":
        proj = sched.project
        return proj.pm_id == user.id or proj.site.is_current_pm(user)
    return False


def _line_tracking(line):
    """Compact live-shipment tracking for a planner line — the linked shipment's
    health, live status, ETA, latest actual movement and the provider's
    live-position link, so planners see the shipment without leaving the
    schedule (owner 2026-08-06). None when the line has no tracked shipment."""
    from . import tracking as trk
    from .models import ShipmentTracking
    from .procurement_pipeline import _shipment_for
    from .tracking_shipsgo import move_label
    sh = _shipment_for(line)
    if sh is None:
        return None
    t = ShipmentTracking.objects.filter(shipment=sh).first()
    if t is None:
        return None
    ev = (t.events.filter(is_actual=True).exclude(code="OTHER")
          .order_by("-event_time", "-id").first()
          or t.events.filter(is_actual=True).order_by("-event_time", "-id")
          .first())
    last = None
    if ev:
        last = {
            "label": (move_label(ev.provider_event_code, t.mode,
                                 ev.code == "TRANSSHIPMENT")
                      if ev.provider_event_code else ev.get_code_display()),
            "location": ev.location, "event_time": ev.event_time}
    return {
        "shipment_id": sh.id, "ipr_ref": line.ipr.ref if line.ipr_id else "",
        "mode": t.mode, "health": trk.health_for(t),
        "live_status": t.raw_status, "current_eta": t.current_eta,
        "map_url": t.map_url, "last_move": last}


def line_dict(line, values=True):
    d = {
        "id": line.id, "s_no": line.s_no,
        "section_id": line.section_id,
        "section_code": line.section.code if line.section_id else "",
        "section_title": line.section.title if line.section_id else "",
        "bundle": line.bundle,
        "category": line.category, "description": line.description,
        "item_id": line.item_id,
        "item_code": line.item.code if line.item_id else "",
        "make_brand": line.make_brand, "specification": line.specification,
        "quantity": line.quantity, "uom": line.uom,
        "trade": line.trade, "supply_by": line.supply_by,
        "required_date": line.required_date, "tds_required": line.tds_required,
        "remarks": line.remarks, "state": line.state,
        "reference_image": (line.reference_image.url
                            if line.reference_image else ""),
        "production_status": line.production_status,
        "planned_supplier": line.planned_supplier,
        "source_country": line.source_country,
        "lead_time_days": line.lead_time_days,
        "client_last_update": line.client_last_update,
        "client_update_note": line.client_update_note,
        "mar_id": line.mar_id, "ipr_id": line.ipr_id,
        "shipment_id": line.shipment_id, "grn_id": line.grn_id,
        "mar_ref": line.mar.ref if line.mar_id else "",
        "ipr_ref": line.ipr.ref if line.ipr_id else "",
        "grn_ref": line.grn.ref if line.grn_id else "",
    }
    from .procurement_pipeline import (client_is_stale, effective_supplier,
                                       line_pipeline, line_risk, line_stage)
    d["pipeline"] = line_pipeline(line)
    d["risk"] = line_risk(line)
    d["stage"] = line_stage(line)
    d["tracking"] = _line_tracking(line)
    # The supplier a line groups under (awarded → IPR → planned). Not a money
    # value — it's the bundle key, so it's exposed to every role.
    d["bundle_supplier"] = effective_supplier(line)
    d["client_delivered_on"] = line.client_delivered_on
    d["client_stale"] = client_is_stale(line)
    if values:
        d["estimated_value"] = line.estimated_value
        d["currency"] = line.currency
        from .procurement_pipeline import line_ipr_actuals, quote_dict
        d["quotes"] = [quote_dict(q) for q in line.quotes.all()]
        d["award_is_new_supplier"] = line.award_is_new_supplier
        d["award_note"] = line.award_note
        d["awarded_by"] = (line.awarded_by.full_name
                           if line.awarded_by_id else "")
        # Once linked to an IPR, show the order's real supplier / country /
        # value; fall back to the planned/estimated fields otherwise.
        act = line_ipr_actuals(line)
        comm = act["committed"] if act else None
        d["committed"] = comm
        d["ipr_supplier"] = act["supplier"] if act else ""
        d["ipr_country"] = act["country"] if act else ""
        d["variance"] = None
        if (comm and line.estimated_value is not None
                and comm["currency"] == (line.currency or "USD")):
            d["variance"] = comm["value"] - line.estimated_value
    return d


def _share_block(sched, user):
    """The client live-link state for the header control."""
    from .procurement_client import SHARE_ROLES, share_path
    return {"path": share_path(sched), "can_share": user.role in SHARE_ROLES}


def schedule_dict(sched, user):
    doc = sched.document
    values = can_see_values(user, sched)
    lines = list(sched.lines.select_related("section", "item", "mar", "ipr",
                                            "grn", "shipment", "awarded_by")
                 .prefetch_related("quotes")
                 .exclude(state="CANCELLED"))
    sections = [{"id": s.id, "code": s.code, "title": s.title,
                 "sort_order": s.sort_order}
                for s in sched.sections.all()]
    line_dicts = [line_dict(ln, values=values) for ln in lines]
    counts, risk_counts = {}, {}
    est_total = Decimal("0")
    comm_total = Decimal("0")
    section_est = {}
    for ln, ld in zip(lines, line_dicts):
        counts[ln.state] = counts.get(ln.state, 0) + 1
        lvl = ld["risk"]["level"]
        risk_counts[lvl] = risk_counts.get(lvl, 0) + 1
        if values:
            ev = ln.estimated_value or Decimal("0")
            est_total += ev
            key = ln.section_id or 0
            section_est[key] = section_est.get(key, Decimal("0")) + ev
            comm = ld.get("committed")
            if comm and comm["currency"] == "USD":
                comm_total += comm["value"]
    totals = ({"currency": "USD", "estimated": est_total,
               "committed": comm_total, "sections": section_est}
              if values else None)
    # Collapse same-bundle + same-supplier lines into expandable summary rows,
    # per section, so the planner (and client plan) stay readable. Standalone
    # lines pass through unchanged.
    from .procurement_grouping import group_rows
    by_sec = {}
    for ld in line_dicts:
        by_sec.setdefault(ld["section_id"] or 0, []).append(ld)
    groups = {str(sid): group_rows(lds, values)
              for sid, lds in by_sec.items()}
    return {
        "id": doc.id, "ref": doc.ref, "status": doc.status,
        "project_id": sched.project_id, "project_code": sched.project.code,
        "project_title": sched.project.title,
        "site_code": doc.site.code, "site_id": doc.site_id,
        "baseline_signed_at": sched.baseline_signed_at,
        "baseline_signed_by": (sched.baseline_signed_by.full_name
                               if sched.baseline_signed_by_id else ""),
        "can_edit_plan": user.role in PROPOSE_ROLES and doc.status == "DRAFT",
        "can_reopen": (user.role in PROPOSE_ROLES
                       and doc.status == "SIGNED_OFF"),
        "can_submit": (user.role in PROPOSE_ROLES and doc.status == "DRAFT"
                       and any(ln.state == "PROPOSED" for ln in lines)),
        "can_confirm": user.role in CONFIRM_ROLES and doc.status == "SUBMITTED",
        "can_sign_off": user.role in SIGNOFF_ROLES and doc.status == "CONFIRMED",
        "can_link": user.role in (*PROPOSE_ROLES, *CONFIRM_ROLES),
        "can_split": user.role in SPLIT_ROLES,
        "can_quote": user.role in (*PROPOSE_ROLES, *CONFIRM_ROLES) and values,
        "can_award": user.role in (*CONFIRM_ROLES, *SIGNOFF_ROLES) and values,
        "share": _share_block(sched, user),
        "show_values": values,
        "line_counts": counts,
        "risk_counts": risk_counts,
        "totals": totals,
        "sections": sections,
        "lines": line_dicts,
        "groups": groups,
        "approvals": [{"action": a.action, "by": a.actor.full_name,
                       "role": a.actor_role, "at": a.acted_at,
                       "comment": a.comment}
                      for a in doc.approvals.select_related("actor")
                      .order_by("acted_at")],
    }
