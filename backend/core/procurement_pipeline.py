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

from django.db.models import F, Sum
from django.utils import timezone

from .audit import audit
from .models import (Document, ImportOrder, ImportOrderLine, ScheduleLine,
                     ScheduleLineQuote, ShipmentTracking)
from .procurement_schedule import (CONFIRM_ROLES, PROPOSE_ROLES, SIGNOFF_ROLES,
                                   schedule_dict)

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
    # UNDER_CLEARING sits BETWEEN arrived and cleared — leaving it out sent
    # the stage back to "pending" (client word: "In transit") the moment
    # clearing started on a landed shipment (IPR-024, 2026-08-26).
    state = ("done" if sh.status in ("ARRIVED", "UNDER_CLEARING", "CLEARED")
             else "pending")
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
    if line.grn_id and line.grn.status in ("COMPLETE", "SHORTAGE_REPORTED"):
        return _stage("eta", "ETA to site", "done", "Delivered")
    eta = _projected_onsite(line)
    if eta is None:
        return _stage("eta", "ETA to site", "none", "No ETA entered")
    late = line.required_date and eta > line.required_date
    # The team's own date reads as a date; the forwarder's ETA (+ buffer)
    # keeps its "~" so nobody mistakes an estimate for a commitment.
    shown = eta.isoformat() if line.eta_date else "~" + eta.isoformat()
    return _stage("eta", "ETA to site", "warn" if late else "pending",
                  ("Late — %s" if late else "%s") % shown)


def _client_pipeline(line):
    """CLIENT-supplied lines have no MAR/IPR/GRN — the client procures and
    delivers, so the stages Sand Planet doesn't own read 'client' and delivery
    is the manual mark."""
    na = "Client-supplied"
    delivered = bool(line.client_delivered_on)
    delivery = _stage("delivery", "Delivery", "done" if delivered else "pending",
                      f"Delivered {line.client_delivered_on.isoformat()}"
                      if delivered else "Awaiting client")
    if delivered:
        eta = _stage("eta", "ETA to site", "done", "Delivered")
    elif line.required_date and line.required_date < _today():
        eta = _stage("eta", "ETA to site", "warn", "Overdue")
    elif line.required_date:
        eta = _stage("eta", "ETA to site", "pending",
                     f"Due {line.required_date.isoformat()}")
    else:
        eta = _stage("eta", "ETA to site", "none", "—")
    return [_stage("tds", "TDS / MAR", "na", na),
            _stage("order", "Order (IPR)", "na", na),
            _production_stage(line), _stage("shipment", "Shipment", "na", na),
            delivery, eta]


def line_ipr_actuals(line):
    """The actuals the schedule surfaces once a line links to an IPR — the
    order's supplier, that supplier's country, and the committed value
    (item-matched when the line carries an item that's on the order, otherwise
    the order's total, since an order is usually raised for the one line). None
    when there's no IPR order. The schedule only displays this; it posts
    nothing."""
    if not line.ipr_id:
        return None
    order = (ImportOrder.objects.filter(document_id=line.ipr_id)
             .select_related("supplier").first())
    if order is None:
        return None
    val = None
    if line.item_id:
        val = order.lines.filter(item_id=line.item_id).aggregate(
            v=Sum(F("order_qty") * F("unit_price")))["v"]
    if val is None:
        total = order.lines.aggregate(
            v=Sum(F("order_qty") * F("unit_price")))["v"]
        if total is not None:
            # One IPR can cover several schedule lines (a bundle ordered
            # together). Without a per-item match, split the order total across
            # the lines that share this IPR so a bundle doesn't multiply-count
            # the same order (owner 2026-08-03).
            from .models import ScheduleLine
            n = (ScheduleLine.objects.filter(ipr_id=line.ipr_id)
                 .exclude(state="CANCELLED").count()) or 1
            val = total / n
        else:
            val = total
    return {
        "supplier": order.supplier.name if order.supplier_id else "",
        "country": order.supplier.country if order.supplier_id else "",
        "committed": ({"value": val, "currency": order.order_currency}
                      if val is not None else None),
    }


def line_committed(line):
    act = line_ipr_actuals(line)
    return act["committed"] if act else None


def effective_supplier(line):
    """The supplier a line is grouped under for the bundle rollup: the awarded
    quote's supplier once decided, else the linked IPR's actual supplier, else
    the planned supplier. This is what makes a bundle split by supplier the
    moment purchasing awards / raises different IPRs (owner 2026-07-30). Uses the
    prefetched quotes, so it costs no extra query on a listed schedule."""
    q = next((x for x in line.quotes.all() if x.is_awarded), None)
    if q and (q.supplier_name or "").strip():
        return q.supplier_name.strip()
    if line.ipr_id:
        act = line_ipr_actuals(line)
        if act and (act.get("supplier") or "").strip():
            return act["supplier"].strip()
    return (line.planned_supplier or "").strip()


def line_pipeline(line):
    """The six derived stages for a line, in flow order."""
    if line.supply_by == "CLIENT":
        return _client_pipeline(line)
    return [_tds_stage(line), _order_stage(line), _production_stage(line),
            _shipment_stage(line), _delivery_stage(line), _eta_stage(line)]


# ---- late-risk engine ----------------------------------------------------

# A line is "at risk" when its projected arrival leaves this little slack.
AT_RISK_WINDOW_DAYS = 14
# A client-supplied line with no update in this many days (and not delivered)
# earns a chase to the PM.
CLIENT_STALE_DAYS = 14
# Rough door-to-Male sea-freight allowance by source country until a config
# screen exists (uppercased country string -> days).
SHIPPING_ALLOWANCE_DAYS = {
    "CHINA": 30, "INDIA": 21, "SRI LANKA": 14, "UAE": 18,
    "UNITED ARAB EMIRATES": 18, "MALAYSIA": 21, "THAILAND": 21,
    "SINGAPORE": 18, "TURKEY": 35, "ITALY": 35, "GERMANY": 35, "SPAIN": 35,
}
DEFAULT_ALLOWANCE_DAYS = 25
RISK_ORDER = {"LATE": 0, "AT_RISK": 1, "ON_TRACK": 2, "DELIVERED": 3,
              "NONE": 4}


def _today():
    return timezone.localdate()


def _delivered(line):
    if line.grn_id and line.grn.status in ("COMPLETE", "SHORTAGE_REPORTED"):
        return True
    if line.delivered_on:
        return True            # received without a GRN, marked by hand
    return bool(line.client_delivered_on)   # CLIENT lines are marked by hand


# What a clearing agent takes on a normal consignment. Only a default: a
# line that states its own is believed.
DEFAULT_CLEARANCE_DAYS = 10


def _shipping_allowance(line):
    """The sailing/flying leg. A line that states it wins; otherwise the
    per-country table, which is a guess made in code and should be treated
    as one."""
    if line.shipping_days:
        return line.shipping_days
    return SHIPPING_ALLOWANCE_DAYS.get(
        (line.source_country or "").strip().upper(), DEFAULT_ALLOWANCE_DAYS)


def _clearance_allowance(line):
    return (line.clearance_days if line.clearance_days is not None
            else DEFAULT_CLEARANCE_DAYS)


def lead_legs(line):
    """The three legs a PM actually plans with: the factory, the forwarder,
    the clearing agent. Kept apart because each has a different owner, and
    when a date slips the useful question is WHICH leg slipped."""
    manufacture = line.lead_time_days or 0
    shipping = _shipping_allowance(line)
    clearance = _clearance_allowance(line)
    return {
        "manufacture_days": manufacture,
        "shipping_days": shipping,
        "clearance_days": clearance,
        "site_buffer_days": SITE_BUFFER_DAYS,
        "total_days": manufacture + shipping + clearance + SITE_BUFFER_DAYS,
        "shipping_assumed": not line.shipping_days,
        "clearance_assumed": line.clearance_days is None,
    }


def suggested_order_by(line):
    """Arithmetic offered to a PM who has entered all three legs — never a
    substitute for their judgement.

    Deliberately returns nothing unless the PM has stated manufacturing,
    shipping AND clearance themselves. The country table is a guess made in
    code; letting it produce an order-by date would dress a guess as a
    deadline, and the durations genuinely are not knowable from here —
    product type, season, a war on the lane, the state of the port
    (owner 2026-08-29)."""
    if not line.required_date or line.supply_by == "CLIENT":
        return None
    if (line.lead_time_days is None or line.shipping_days is None
            or line.clearance_days is None):
        return None
    total = (line.lead_time_days + line.shipping_days + line.clearance_days
             + SITE_BUFFER_DAYS)
    return line.required_date - timedelta(days=total)


def order_by(line):
    """The PM's own date. Nothing computes this."""
    return line.order_by_date


def _projected_onsite(line):
    """When a not-yet-delivered contractor line is expected on site: the
    date the project team ENTERED, else the forwarder's ETA on the shipment
    block (tracker-refined) plus the site buffer, else nothing.

    Until 2026-09-03 this fell through to today + lead time + a per-country
    shipping guess — a date nobody had typed, that crept forward daily and
    that the client read as a commitment. Nothing computes an ETA now."""
    if line.eta_date:
        return line.eta_date
    return _site_eta(_shipment_for(line))


def line_risk(line):
    """On-track / at-risk / late assessment for a line — derived, read-only.
    Late-while-unordered is the worst case: the date can't be met even if the
    order goes out today."""
    if _delivered(line):
        return {"level": "DELIVERED", "reason": "Received at site",
                "projected": None, "slack_days": None, "unordered": False}
    req = line.required_date
    if line.supply_by == "CLIENT":
        if req and req < _today():
            return {"level": "LATE", "reason": "Client supply overdue",
                    "projected": None, "slack_days": (req - _today()).days,
                    "unordered": False}
        return {"level": "NONE", "reason": "Client-supplied", "projected": None,
                "slack_days": None, "unordered": False}
    if not req:
        return {"level": "NONE", "reason": "No required date",
                "projected": None, "slack_days": None, "unordered": False}
    proj = _projected_onsite(line)
    unordered = not line.ipr_id
    if proj is None:
        out = {"level": "NONE", "reason": "No ETA entered", "projected": None,
               "slack_days": None, "unordered": unordered}
        if req < _today():
            out.update(level="LATE", reason="Required date passed, no ETA",
                       slack_days=(req - _today()).days)
        by = line.order_by_date
        out["order_by"] = by
        out["order_overdue_days"] = (
            (_today() - by).days if (by and unordered and by < _today())
            else 0)
        return out
    slack = (req - proj).days
    if proj > req:
        level = "LATE"
        reason = ("Can't make the date even if ordered today" if unordered
                  else "Projected to land after the required date")
    elif slack <= AT_RISK_WINDOW_DAYS:
        level, reason = "AT_RISK", f"Only {slack}d of slack"
    else:
        level, reason = "ON_TRACK", f"{slack}d slack"
    out = {"level": level, "reason": reason, "projected": proj,
           "slack_days": slack, "unordered": unordered}
    # "You needed to place this order N days ago" is a different sentence from
    # "this will land late", and it is the one somebody can still act on. It
    # counts off the PM's OWN date — a flag raised by the app's arithmetic
    # would be a flag nobody trusts.
    by = line.order_by_date
    out["order_by"] = by
    out["order_overdue_days"] = (
        (_today() - by).days if (by and unordered and by < _today()) else 0)
    return out


def line_stage(line):
    """A live execution-stage label for the row — the furthest point the line
    has actually reached — so the status moves as it progresses (distinct from
    the propose/confirm/sign-off approval state). None until execution starts."""
    if _delivered(line):
        return {"label": "Delivered", "tone": "ok"}
    sh = _shipment_for(line)
    if sh is not None:
        # A consignment being cleared has plainly landed. Reading only
        # ARRIVED and CLEARED as arrived left BAO-LI's bridge showing
        # "Shipped" while its agent was at customs with it (owner
        # 2026-08-31).
        if sh.status == "CLEARED":
            return {"label": "Cleared", "tone": "ok"}
        if sh.status == "UNDER_CLEARING":
            return {"label": "Clearing", "tone": "info"}
        if sh.status == "ARRIVED":
            return {"label": "Arrived", "tone": "ok"}
        return {"label": "Shipped", "tone": "info"}
    if line.production_status == "COMPLETED":
        return {"label": "Produced", "tone": "info"}
    if line.production_status == "IN_PRODUCTION":
        return {"label": "In production", "tone": "warn"}
    if line.ipr_id:
        return {"label": "Ordered", "tone": "info"}
    if line.mar_id and line.mar.status in ("APPROVED", "APPROVED_WITH_COMMENTS"):
        return {"label": "TDS approved", "tone": "info"}
    return None


def schedule_risk_counts(sched):
    """Roll up line risk levels for a schedule header ("3 late, 5 at risk")."""
    counts = {}
    lines = sched.lines.select_related("grn", "ipr", "shipment").exclude(
        state="CANCELLED")
    for line in lines:
        lvl = line_risk(line)["level"]
        counts[lvl] = counts.get(lvl, 0) + 1
    return counts


# ---- alerts + PD digest (driven by the procurement_risk command) ---------

def _operational_lines():
    """Signed-off (operational) lines of baselined schedules — the ones the
    late-risk sweep watches."""
    return (ScheduleLine.objects
            .filter(schedule__baseline_signed_at__isnull=False,
                    state="SIGNED_OFF")
            .select_related("schedule__project__site", "schedule__document",
                            "grn", "ipr", "shipment"))


def _line_recipients(notify, sched, escalate):
    recips = set(notify._role_users("HO_PURCHASING"))
    proj = sched.project
    pm = proj.pm or (proj.site.current_pm() if proj.site_id else None)
    if pm:
        recips.add(pm)
    if escalate:
        recips |= set(notify._role_users("DIRECTOR"))
    return recips


def _alert_line(notify, line, risk):
    sched = line.schedule
    tag = "LATE" if risk["level"] == "LATE" else "at risk"
    unord = " — not yet ordered" if risk.get("unordered") else ""
    what = (line.description or "item")[:60]
    title = f"Procurement {tag}: {what}"
    body = (f"{sched.project.code} · {sched.document.ref} · {what}{unord}. "
            f"{risk['reason']}. Required {line.required_date}.")[:300]
    for u in _line_recipients(notify, sched, risk["level"] == "LATE"):
        notify.notify_user(u, title, body=body, doc=sched.document,
                           category="alert")


def sweep_risk_alerts(today=None):
    """Fire a PM+Purchasing alert (Director too when LATE) the first time a
    line escalates into at-risk / late. Watermarked so daily runs don't spam;
    the watermark clears when a line recovers so a later slip re-fires."""
    from . import notify
    sent = 0
    for line in _operational_lines():
        risk = line_risk(line)
        lvl = risk["level"]
        prev = line.risk_alerted or ""
        if lvl in ("AT_RISK", "LATE"):
            if RISK_ORDER[lvl] < RISK_ORDER.get(prev or "NONE", 99):
                _alert_line(notify, line, risk)
                line.risk_alerted = lvl
                line.save(update_fields=["risk_alerted"])
                sent += 1
        elif prev:
            line.risk_alerted = ""
            line.save(update_fields=["risk_alerted"])
    return sent


def send_pd_digest(today=None):
    """One digest per Director of every late / at-risk line across all
    projects, worst first (late-while-unordered at the top). Deduped so a
    given day sends at most one digest per Director."""
    from . import notify
    from .models import Notification
    today = today or _today()
    at_risk = []
    for line in _operational_lines():
        risk = line_risk(line)
        if risk["level"] in ("AT_RISK", "LATE"):
            at_risk.append((line, risk))
    if not at_risk:
        return 0
    at_risk.sort(key=lambda lr: (RISK_ORDER[lr[1]["level"]],
                                 not lr[1].get("unordered"),
                                 lr[1].get("slack_days")
                                 if lr[1].get("slack_days") is not None
                                 else 0))
    late = sum(1 for _, r in at_risk if r["level"] == "LATE")
    risky = len(at_risk) - late
    title = f"Procurement digest: {late} late, {risky} at risk"
    parts = [f"{ln.schedule.project.code}: {(ln.description or 'item')[:24]}"
             f" ({r['level'].replace('_', ' ').lower()})"
             for ln, r in at_risk[:8]]
    body = "; ".join(parts)
    if len(at_risk) > 8:
        body += f"; +{len(at_risk) - 8} more"
    body = body[:300]
    sent = 0
    for u in notify._role_users("DIRECTOR"):
        if Notification.objects.filter(
                recipient=u, title__startswith="Procurement digest:",
                created_at__date=today).exists():
            continue
        notify.notify_user(u, title, body=body, category="alert")
        sent += 1
    return sent


def _chase_client(notify, line):
    sched = line.schedule
    proj = sched.project
    what = (line.description or "item")[:60]
    title = f"Chase client update — {what}"
    body = (f"{proj.code} · {sched.document.ref} · client-supplied {what}: "
            f"no update in {CLIENT_STALE_DAYS}+ days. "
            f"Required {line.required_date or '—'}.")[:300]
    pm = proj.pm or (proj.site.current_pm() if proj.site_id else None)
    recips = {pm} if pm else set(notify._role_users("HO_PURCHASING"))
    for u in recips:
        notify.notify_user(u, title, body=body, doc=sched.document,
                           category="alert")


def sweep_client_staleness(today=None):
    """Chase the PM on client-supplied lines that have gone quiet. Re-chases at
    most once per staleness window; a client update clears the watermark."""
    from . import notify
    today = today or _today()
    sent = 0
    lines = (ScheduleLine.objects
             .filter(schedule__baseline_signed_at__isnull=False,
                     state="SIGNED_OFF", supply_by="CLIENT",
                     client_delivered_on__isnull=True)
             .select_related("schedule__project__site", "schedule__document"))
    for line in lines:
        if not client_is_stale(line, today):
            continue
        chased = line.client_chased_on
        if chased and (today - chased).days < CLIENT_STALE_DAYS:
            continue
        _chase_client(notify, line)
        line.client_chased_on = today
        line.save(update_fields=["client_chased_on"])
        sent += 1
    return sent


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


def set_eta(line, on, actor):
    """The team's expected-on-site date (blank clears it)."""
    from datetime import date as _date
    if actor.role not in LINK_ROLES:
        return "Not permitted to set the ETA."
    if line.supply_by == "CLIENT":
        return "Client-supplied lines are due on their required date."
    if on in (None, ""):
        line.eta_date = None
    else:
        try:
            line.eta_date = _date.fromisoformat(str(on))
        except ValueError:
            return "ETA must be a date (YYYY-MM-DD)."
    line.save(update_fields=["eta_date", "updated_at"])
    audit("document", line.schedule.document_id, "PSC_LINE_ETA",
          actor=actor, detail={"line": line.id,
                               "eta": line.eta_date.isoformat()
                               if line.eta_date else None})
    return None


def set_delivered(line, on, note, actor):
    """Close a line that arrived without a GRN.

    The pipeline normally learns of delivery from a GRN, which is right when
    the goods passed through a store. Two cases never will: material bought
    and installed before the import module existed, and a local purchase that
    never had a receipt raised. Without this the line stays "Produced" and
    flags Late forever, and the planner slowly fills with rows nobody can
    close (owner 2026-08-31, BAO-LI's HDPE liner).

    A note is required. A delivery asserted by hand should say who asserted
    it and on what basis, because it is the one stage with no document
    behind it. Passing on=None reopens the line."""
    from datetime import date as _date

    if actor.role not in LINK_ROLES:
        return "Not permitted to mark a line delivered."
    if line.grn_id:
        return ("This line has a GRN — its delivery comes from the receipt, "
                "not by hand.")
    if on in (None, ""):
        line.delivered_on = None
        line.delivered_note = ""
        line.delivered_by = None
        line.save(update_fields=["delivered_on", "delivered_note",
                                 "delivered_by", "updated_at"])
        audit("document", line.schedule.document_id, "PSC_LINE_UNDELIVERED",
              actor=actor, detail={"line": line.id})
        return None
    try:
        when = on if isinstance(on, _date) else _date.fromisoformat(str(on))
    except (TypeError, ValueError):
        return "Give the date it was received."
    if when > timezone.localdate():
        return "A delivery date can't be in the future."
    if not (note or "").strip():
        return ("Say how this was received — it is being closed without a "
                "goods receipt.")
    line.delivered_on = when
    line.delivered_note = (note or "").strip()[:200]
    line.delivered_by = actor
    line.save(update_fields=["delivered_on", "delivered_note", "delivered_by",
                             "updated_at"])
    audit("document", line.schedule.document_id, "PSC_LINE_DELIVERED",
          actor=actor, detail={"line": line.id, "on": when.isoformat(),
                               "note": line.delivered_note})
    return None


# ---- BOQ supplier quotes + award decision --------------------------------

# QS/PM capture quotes (LINK_ROLES); Purchasing + PD record the award.
AWARD_ROLES = tuple(dict.fromkeys((*CONFIRM_ROLES, *SIGNOFF_ROLES)))
_QUOTE_TEXT = ("supplier_name", "country", "contact", "remarks")
_TRUE = ("1", "true", "yes", "on")


def _qdec(v):
    from decimal import Decimal, InvalidOperation
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _qbool(v):
    return str(v).strip().lower() in _TRUE


def _apply_quote(quote, data):
    for f in _QUOTE_TEXT:
        if f in data:
            setattr(quote, f, (data.get(f) or "").strip()[:200])
    if "currency" in data:
        quote.currency = ((data.get("currency") or "USD")[:3].upper() or "USD")
    if "quoted_value" in data:
        quote.quoted_value = _qdec(data.get("quoted_value"))
    if "lead_time_days" in data:
        v = data.get("lead_time_days")
        quote.lead_time_days = int(v) if str(v).strip().isdigit() else None
    if "valid_until" in data:
        quote.valid_until = data.get("valid_until") or None
    if "supplier_id" in data:
        quote.supplier_id = data.get("supplier_id") or None


def _set_recommended(quote):
    """Make this the sole recommended quote on its line."""
    quote.line.quotes.exclude(pk=quote.pk).update(is_recommended=False)
    ScheduleLineQuote.objects.filter(pk=quote.pk).update(is_recommended=True)


def add_quote(line, data, file, actor):
    if actor.role not in LINK_ROLES:
        return None, "Not permitted to add quotes."
    if not (data.get("supplier_name") or "").strip():
        return None, "A quote needs a supplier name."
    quote = ScheduleLineQuote(line=line, created_by=actor)
    _apply_quote(quote, data)
    if file is not None:
        quote.quote_file = file
    quote.save()
    if _qbool(data.get("is_recommended")):
        _set_recommended(quote)
    audit("document", line.schedule.document_id, "PSC_QUOTE_ADDED", actor=actor,
          detail={"line": line.id, "supplier": quote.supplier_name})
    return quote, None


def update_quote(quote, data, file, actor):
    if actor.role not in LINK_ROLES:
        return "Not permitted to edit quotes."
    _apply_quote(quote, data)
    if file is not None:
        quote.quote_file = file
    quote.save()
    if "is_recommended" in data:
        if _qbool(data.get("is_recommended")):
            _set_recommended(quote)
        else:
            ScheduleLineQuote.objects.filter(pk=quote.pk).update(
                is_recommended=False)
    audit("document", quote.line.schedule.document_id, "PSC_QUOTE_EDITED",
          actor=actor, detail={"quote": quote.id})
    return None


def delete_quote(quote, actor):
    if actor.role not in LINK_ROLES:
        return "Not permitted to delete quotes."
    if quote.is_awarded:
        return "This quote is the awarded supplier — un-award it first."
    audit("document", quote.line.schedule.document_id, "PSC_QUOTE_DELETED",
          actor=actor, detail={"quote": quote.id})
    quote.delete()
    return None


def award_supplier(line, data, actor):
    """Record the IPR award decision: award a quote, note a new supplier, or
    clear the decision. Purchasing + PD only."""
    if actor.role not in AWARD_ROLES:
        return "Only Purchasing / the Director records the supplier award."
    action = data.get("action")
    line.quotes.update(is_awarded=False)
    fields = ["award_is_new_supplier", "award_note", "awarded_by", "awarded_at"]
    if action == "clear":
        line.award_is_new_supplier = False
        line.award_note = ""
        line.awarded_by = None
        line.awarded_at = None
        line.save(update_fields=fields)
        return None
    if action == "new":
        note = (data.get("note") or "").strip()
        if not note:
            return "A reason is required when going with a new supplier."
        line.award_is_new_supplier = True
        line.award_note = note[:200]
    elif action == "quote":
        q = line.quotes.filter(pk=data.get("quote_id")).first()
        if q is None:
            return "Unknown quote."
        ScheduleLineQuote.objects.filter(pk=q.pk).update(is_awarded=True)
        line.award_is_new_supplier = False
        line.award_note = (data.get("note") or "").strip()[:200]
    else:
        return "Unknown award action."
    line.awarded_by = actor
    line.awarded_at = timezone.now()
    line.save(update_fields=fields)
    audit("document", line.schedule.document_id, "PSC_AWARDED", actor=actor,
          detail={"line": line.id, "action": action})
    return None


def quote_dict(quote):
    return {
        "id": quote.id, "supplier_name": quote.supplier_name,
        "supplier_id": quote.supplier_id, "country": quote.country,
        "contact": quote.contact, "quoted_value": quote.quoted_value,
        "currency": quote.currency, "lead_time_days": quote.lead_time_days,
        "valid_until": quote.valid_until,
        "file_url": quote.quote_file.url if quote.quote_file else "",
        "is_recommended": quote.is_recommended, "is_awarded": quote.is_awarded,
        "remarks": quote.remarks,
    }


def _resolve_award_supplier(quote):
    """The awarded quote's supplier as a registered INTERNATIONAL supplier, so
    the IPR can be raised against it. Reuse the linked/same-named one, else
    register a new one from the quote."""
    from .models import Supplier
    if quote.supplier_id and quote.supplier.category == "INTERNATIONAL":
        return quote.supplier
    name = (quote.supplier_name or "").strip()
    s = Supplier.objects.filter(name__iexact=name,
                                category="INTERNATIONAL").first()
    if s is None:
        s = Supplier.objects.create(
            name=name, category="INTERNATIONAL", country=quote.country or "",
            default_currency=(quote.currency or "USD")[:3].upper())
    if quote.supplier_id != s.id:
        quote.supplier = s
        quote.save(update_fields=["supplier"])
    return s


def create_ipr_from_line(line, actor):
    """Raise a DRAFT IPR from the line's awarded quote: register the supplier if
    needed, pre-fill one order line from the quote, and link it back to the
    line. Purchasing completes the rest (rate, cost head, extra lines) in the
    IPR editor and runs it through the normal award/authorise flow."""
    from decimal import Decimal
    from . import fx, imports
    from .models import CostHead
    if actor.role not in AWARD_ROLES:
        return None, "Only Purchasing / the Director raises the IPR."
    if line.ipr_id:
        return None, "This line already links to an IPR."
    quote = line.quotes.filter(is_awarded=True).first()
    if quote is None:
        return None, ("Award a quote first — for a brand-new supplier, raise "
                      "the IPR from International Orders.")
    cost_head = (CostHead.objects.filter(is_active=True, is_pool=False)
                 .order_by("sort_order", "name").first())
    if cost_head is None:
        return None, "No cost head is configured to book the order against."
    supplier = _resolve_award_supplier(quote)
    qty = line.quantity or Decimal("1")
    total = quote.quoted_value or Decimal("0")
    unit_price = (total / qty) if qty else total
    data = {
        "supplier_id": supplier.id,
        "order_currency": (quote.currency or "USD"),
        "exchange_rate": str(fx.usd_rate()),
        "lines": [{
            "item_id": line.item_id,
            "free_text_desc": "" if line.item_id else (line.description or ""),
            "unit": line.uom or "", "spec": line.specification or "",
            "order_qty": str(qty), "unit_price": str(unit_price),
            "cost_head_id": cost_head.id,
            "allocations": [{"project_id": line.schedule.project_id,
                             "qty": str(qty)}],
        }],
        "pmr_refs": [],
    }
    doc, err = imports.create_ipr(data, actor)
    if err:
        return None, err
    line.ipr = doc
    line.save(update_fields=["ipr", "updated_at"])
    audit("document", line.schedule.document_id, "PSC_IPR_RAISED", actor=actor,
          detail={"line": line.id, "ipr": doc.ref, "supplier": supplier.name})
    return doc, None


def record_client_update(line, note, delivered, actor):
    """Log where a CLIENT-supplied line stands (client procures + delivers).
    Stamps the update date, optionally marks/unmarks delivery, and clears the
    chase watermark so freshness resets."""
    if actor.role not in LINK_ROLES:
        return "Not permitted to update client-supplied lines."
    if line.supply_by != "CLIENT":
        return "Client updates apply to client-supplied lines only."
    line.client_last_update = _today()
    if note is not None:
        line.client_update_note = (note or "")[:200]
    if delivered is True:
        line.client_delivered_on = line.client_delivered_on or _today()
    elif delivered is False:
        line.client_delivered_on = None
    line.client_chased_on = None
    line.save(update_fields=["client_last_update", "client_update_note",
                             "client_delivered_on", "client_chased_on",
                             "updated_at"])
    audit("document", line.schedule.document_id, "PSC_CLIENT_UPDATE",
          actor=actor, detail={"line": line.id,
                               "delivered": bool(line.client_delivered_on)})
    return None


def client_is_stale(line, today=None):
    """A client line overdue for an update: not delivered and no update within
    the staleness window."""
    if line.supply_by != "CLIENT" or line.client_delivered_on:
        return False
    today = today or _today()
    last = line.client_last_update
    return last is None or (today - last).days >= CLIENT_STALE_DAYS


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
