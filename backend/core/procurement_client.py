"""Procurement Schedule — the client-facing view (shared by the xlsx export and
the live HTML share link).

Single source of the client ALLOWLIST: what the employer is allowed to see —
planning identity, the required-on-site date, the derived pipeline as plain
words, source country, and an overall status. No internal money (estimated /
committed / variance / lead time) and no supplier name ever leave through here.
Both the spreadsheet export and the public web page render from `client_plan`,
so the two can never drift apart.
"""
import secrets

from .procurement_pipeline import line_pipeline, line_risk

# ---- client-facing stage vocabulary (from the derived pipeline state) ----
# Each derived stage carries state ∈ none|na|pending|done|warn; map it to a word
# the client understands, per stage.
STAGE_WORDS = {
    "tds": {"done": "Approved", "pending": "Under review", "warn": "Revise",
            "none": "Pending", "na": "—"},
    "order": {"done": "Ordered", "pending": "Processing", "warn": "Cancelled",
              "none": "Pending", "na": "—"},
    "production": {"done": "Completed", "pending": "In production",
                   "warn": "—", "none": "Pending", "na": "—"},
    "shipment": {"done": "Arrived", "pending": "In transit", "warn": "—",
                 "none": "Pending", "na": "—"},
    "delivery": {"done": "Delivered", "pending": "Awaiting",
                 "warn": "Shortage", "none": "Pending", "na": "—"},
}
RISK_WORD = {"LATE": "Late", "AT_RISK": "At risk", "ON_TRACK": "On track",
             "DELIVERED": "Delivered", "NONE": ""}
# hex (xlsx) — the HTML template maps the level to its own CSS class.
RISK_COLOR = {"LATE": "B02418", "AT_RISK": "B35900", "ON_TRACK": "1A7F37",
              "DELIVERED": "8A94A0", "NONE": None}


def initials(user):
    name = (getattr(user, "full_name", "") or getattr(user, "username", "")
            or "").strip()
    parts = [p for p in name.replace(".", " ").split() if p]
    return "".join(p[0] for p in parts[:3]).upper() if parts else "—"


def _stage_word(pipeline, key):
    st = next((s for s in pipeline if s["key"] == key), None)
    return STAGE_WORDS.get(key, {}).get(st["state"], "") if st else ""


def _shipment_word(pipeline):
    """The shipment column shows the IPR shipment's REAL status (Booked /
    Shipped / In Transit / Arrived / Under Clearing / Cleared) so the client
    sees what is actually going on, not a two-word rollup (owner
    2026-08-26). Falls back to the mapped word when there is no shipment or
    the rollup carries no status text."""
    st = next((s for s in pipeline if s["key"] == "shipment"), None)
    if not st:
        return ""
    if st["state"] in ("none", "na"):
        return STAGE_WORDS["shipment"].get(st["state"], "")
    return st.get("detail") or STAGE_WORDS["shipment"].get(st["state"], "")


def _eta_value(line, risk):
    if risk["level"] == "DELIVERED":
        return "Delivered"
    proj = risk.get("projected")
    return proj if proj else ""


def _last_update(sched):
    dates = [sched.document.updated_at]
    dates += [ln.updated_at for ln in sched.lines.all() if ln.updated_at]
    return max(d for d in dates if d)


CLIENT_STATUS_WORDS = {
    "NEW": "Booked", "INPROGRESS": "Booked", "BOOKED": "Booked",
    "LOADED": "Loaded", "SAILING": "Sailing", "ARRIVED": "Arrived",
    "DISCHARGED": "Discharged", "EN_ROUTE": "En route", "LANDED": "Landed",
    "DELIVERED": "Delivered",
}


def client_tracking(line):
    """Sanitised live tracking for the client (owner 2026-08-26, reversing
    the 2026-08-06 hold-back): friendly status, ETA and the movement
    timeline — never the provider map link, internal health states, errors,
    or anything money-side. None when there is nothing live to show."""
    from . import tracking as trk
    from .models import ShipmentTracking
    from .procurement_pipeline import _shipment_for
    sh = _shipment_for(line)
    if sh is None:
        return None
    t = ShipmentTracking.objects.filter(shipment=sh).first()
    if t is None or t.state not in ("ACTIVE", "ARRIVED"):
        return None
    moves = trk.movements_for(t)
    if not moves and not t.raw_status:
        return None
    # No provider map link for clients (owner 2026-08-26) — the movement
    # summary below is the tracker; the ShipsGo map stays internal.
    return {
        "mode": t.mode,
        "status": CLIENT_STATUS_WORDS.get(
            t.raw_status, (t.raw_status or "").title()),
        "eta": t.current_eta.date() if t.current_eta else None,
        "movements": [{
            "label": m["label"], "location": m["location"],
            "vessel": m["vessel_flight"], "date": m["event_time"],
            "actual": m["is_actual"],
        } for m in moves],
    }


def client_row(line):
    """One line as the client sees it — allowlist fields only."""
    pipe = line_pipeline(line)
    risk = line_risk(line)
    return {
        "tracking": client_tracking(line),
        "s_no": line.s_no, "category": line.category,
        "description": line.description, "make_brand": line.make_brand,
        "specification": line.specification,
        "quantity": line.quantity, "uom": line.uom,
        "supply_by": ("Sand Planet" if line.supply_by == "CONTRACTOR"
                      else "Client"),
        "source_country": line.source_country,
        "required_date": line.required_date,
        "tds_req": "Yes" if line.tds_required else "No",
        "tds": _stage_word(pipe, "tds"), "order": _stage_word(pipe, "order"),
        "production": _stage_word(pipe, "production"),
        "shipment": _shipment_word(pipe),
        "delivery": _stage_word(pipe, "delivery"),
        "eta": _eta_value(line, risk),
        "status": RISK_WORD.get(risk["level"], ""),
        "status_level": risk["level"],
        "remarks": line.remarks,
        "image": line.reference_image.url if line.reference_image else "",
    }


def _grouping_dict(line):
    """The minimal line shape the shared bundle grouper needs (client context —
    no money). `_line` carries the model back for a standalone row."""
    from .procurement_pipeline import (effective_supplier, line_pipeline,
                                       line_risk)
    return {
        "_line": line, "section_id": line.section_id, "bundle": line.bundle,
        "bundle_supplier": effective_supplier(line),
        "pipeline": line_pipeline(line), "risk": line_risk(line),
        "required_date": line.required_date, "quantity": line.quantity,
        "uom": line.uom, "make_brand": line.make_brand,
        "source_country": line.source_country, "category": line.category,
        "trade": line.trade, "supply_by": line.supply_by,
    }


def _bundle_client_row(summary, members=None):
    """A collapsed bundle as the client sees it — one summary line reusing the
    same rollup the planner shows, mapped to the client's stage vocabulary. The
    member variants ride along under `variants` so the client can expand them
    (and the export can list them)."""
    lvl = summary["risk"]["level"]
    country = summary.get("source_country") or ""
    return {
        "s_no": "", "category": summary.get("category", ""),
        "description": summary["bundle"],
        "make_brand": ("" if summary.get("make_brand") == "Multiple"
                       else summary.get("make_brand", "")),
        "specification": f"{summary['count']} items",
        "quantity": summary.get("quantity"), "uom": summary.get("uom", ""),
        "supply_by": ("Sand Planet" if summary.get("supply_by") == "CONTRACTOR"
                      else "Client"),
        "source_country": ("" if country == "Multiple" else country),
        "required_date": summary.get("required_date"),
        "tds_req": "",
        "tds": _stage_word(summary["pipeline"], "tds"),
        "order": _stage_word(summary["pipeline"], "order"),
        "production": _stage_word(summary["pipeline"], "production"),
        "shipment": _shipment_word(summary["pipeline"]),
        "delivery": _stage_word(summary["pipeline"], "delivery"),
        "eta": ("Delivered" if lvl == "DELIVERED"
                else (summary["risk"].get("projected") or "")),
        "status": RISK_WORD.get(lvl, ""), "status_level": lvl,
        "remarks": f"{summary['count']} variants", "is_bundle": True,
        "variants": [client_row(m["_line"]) for m in (members or [])],
    }


def client_plan(sched, updated_by=""):
    """The whole client plan for a project: header identity + sectioned rows.
    Bundled variants collapse to one summary row (same rule as the planner).
    Rendered identically by the xlsx export and the public HTML page."""
    from .pdf import company_info
    from .procurement_grouping import group_rows
    doc = sched.document
    site = sched.site or doc.site
    co = company_info()
    client_name = getattr(site, "client_name", "") or site.name

    lines = list(sched.lines.select_related("section", "item", "project")
                 .prefetch_related("quotes").exclude(state="CANCELLED"))
    # One schedule per site, read project-wise (owner 2026-10-11): the
    # projects in code order, each with its own sections; a section title is
    # tagged with the project code when the plan spans more than one.
    by_section = {}
    for ln in lines:
        by_section.setdefault(ln.section_id, []).append(ln)
    projects = {}
    for ln in lines:
        if ln.project_id:
            projects[ln.project_id] = ln.project
    order = [p for p in sorted(projects.values(), key=lambda p: p.code)]
    multi = len(order) > 1
    secs = list(sched.sections.select_related("project")
                .order_by("sort_order", "id"))
    sections = []

    def emit(code, title, sid, proj):
        rows = sorted(by_section.get(sid, []),
                      key=lambda x: (x.s_no or 0, x.id))
        if not rows:
            return
        grouped = group_rows([_grouping_dict(ln) for ln in rows], values=False)
        crows = [client_row(r["line"]["_line"]) if r["kind"] == "line"
                 else _bundle_client_row(r["summary"], r["members"])
                 for r in grouped]
        label = title or "Items"
        sections.append({
            "code": code, "project": proj.code if proj else "",
            "project_title": proj.title if proj else "",
            "title": f"{proj.code} · {label}" if (multi and proj) else label,
            "rows": crows})

    for proj in order + [None]:
        for s in secs:
            if (s.project_id or None) == (proj.id if proj else None):
                emit(s.code, s.title, s.id, proj)
        # lines of this project with no section
        loose = [ln for ln in by_section.get(None, [])
                 if (ln.project_id or None) == (proj.id if proj else None)]
        if loose:
            by_section[("loose", proj.id if proj else None)] = loose
            emit("", "Unsectioned", ("loose", proj.id if proj else None),
                 proj)

    first = order[0] if order else sched.project
    return {
        "project_title": (site.name if multi or not first else first.title),
        "project_code": (site.code if multi or not first else first.code),
        "projects": [{"code": p.code, "title": p.title} for p in order],
        "site_code": site.code, "site_name": site.name,
        "contractor": co["legal_name"], "client": client_name,
        "last_update": _last_update(sched).date(),
        "updated_by": updated_by,
        "sections": sections,
    }


def client_site_plan(site, updated_by=""):
    """Every non-closed project's plan on a site, merged into ONE client plan
    (same shape as client_plan) — so the portal can show procurement site-wide
    without the client toggling between projects. Section titles are tagged
    with the project code when the site has more than one project, so it's
    still clear which award each item belongs to."""
    from .models import ProcurementSchedule
    from .pdf import company_info
    co = company_info()
    client_name = getattr(site, "client_name", "") or site.name
    base = {"project_title": site.name, "project_code": site.code,
            "contractor": co["legal_name"], "client": client_name,
            "updated_by": updated_by, "last_update": None, "sections": []}

    # One schedule per site now (owner 2026-10-11): the site's live plan,
    # already grouped project-wise by client_plan.
    sched = (ProcurementSchedule.objects
             .filter(site=site, merged_into__isnull=True,
                     document__is_void=False)
             .select_related("document", "site")
             .order_by("document__doc_date", "document_id").first())
    if sched is None:
        return {**base, "available": False}
    plan = client_plan(sched, updated_by=updated_by)
    return {**base, **plan, "project_title": site.name,
            "project_code": site.code, "available": True}


# ---- share token (the live client link) ----------------------------------

# Roles allowed to mint / revoke the client link — the schedule's custodians.
SHARE_ROLES = ("QS", "PM", "HO_PURCHASING", "DIRECTOR", "ADMIN")


def generate_share_token(sched, actor):
    """Mint (or rotate) the client link token. Rotating revokes the old URL."""
    from .audit import audit
    if actor.role not in SHARE_ROLES:
        return None, "Not permitted to share this schedule."
    sched.share_token = secrets.token_urlsafe(24)
    sched.save(update_fields=["share_token", "updated_at"])
    audit("document", sched.document_id, "PSC_SHARE_LINK", actor=actor,
          detail={"action": "generated"})
    return sched.share_token, None


def revoke_share_token(sched, actor):
    from .audit import audit
    if actor.role not in SHARE_ROLES:
        return "Not permitted to revoke this schedule's link."
    sched.share_token = ""
    sched.save(update_fields=["share_token", "updated_at"])
    audit("document", sched.document_id, "PSC_SHARE_LINK", actor=actor,
          detail={"action": "revoked"})
    return None


def share_path(sched):
    """The public path for the client link, or '' when unshared."""
    return f"/share/procurement/{sched.share_token}" if sched.share_token else ""
