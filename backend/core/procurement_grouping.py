"""Bundle grouping for the procurement schedule (owner 2026-07-30).

Materials often need many variant lines — "Deck & Fence Timber" in six sizes,
pool plumbing across dozens of fittings — each its own ScheduleLine because IPR,
shipment tracking and GRN all attach per line. That makes the planner (and the
client plan) far too long. This collapses lines that share a **bundle label AND
a supplier** into ONE expandable summary row; the moment purchasing awards /
raises different IPRs the bundle splits by supplier, so each summary still maps
cleanly to one IPR.

Pure presentation: nothing here is stored, every summary figure is derived from
the member lines, and each line keeps its own record. Used by BOTH the app
(`schedule_dict`) and the client plan/export so the two never drift.
"""
from decimal import Decimal

# worst-first ordering for the rolled-up risk chip
RISK_ORDER = {"NONE": 0, "DELIVERED": 1, "ON_TRACK": 2, "AT_RISK": 3, "LATE": 4}
# least-advanced wins for the rolled-up state
STATE_ORDER = {"PROPOSED": 0, "CONFIRMED": 1, "SIGNED_OFF": 2, "CANCELLED": 3}


def group_key(ld):
    """A line's bundle identity: (section, bundle label, supplier), all
    case-folded. None when the line carries no bundle label (stands alone)."""
    label = (ld.get("bundle") or "").strip()
    if not label:
        return None
    return (ld.get("section_id") or 0, label.lower(),
            (ld.get("bundle_supplier") or "").strip().lower())


def _common(members, key):
    """The shared value across members, "Multiple" if they differ, "" if none."""
    vals = {(m.get(key) or "").strip() for m in members}
    vals.discard("")
    if len(vals) == 1:
        return next(iter(vals))
    return "Multiple" if len(vals) > 1 else ""


def _earliest_required(members):
    ds = [m.get("required_date") for m in members if m.get("required_date")]
    return min(ds) if ds else None


def _rollup_qty(members):
    """Sum the quantity only when every member shares one unit; otherwise the
    quantities aren't additive, so report none (the count carries the size)."""
    uoms = {(m.get("uom") or "").strip().lower() for m in members}
    qtys = [m.get("quantity") for m in members if m.get("quantity") is not None]
    if len(uoms) == 1 and qtys:
        total = sum((Decimal(str(q)) for q in qtys), Decimal("0"))
        return total, (members[0].get("uom") or "")
    return None, ""


def _agg_pipeline(members):
    """One rolled-up pipeline strip: a stage is 'done' only when every member
    reaches it, 'warn' if any member warns, 'pending' while any is mid-flight."""
    base = members[0].get("pipeline") or []
    out = []
    for i, stage in enumerate(base):
        states = [(m.get("pipeline") or [])[i].get("state")
                  for m in members if i < len(m.get("pipeline") or [])]
        real = [s for s in states if s not in ("na", "none", None)]
        if not real:
            state = next((s for s in states if s), "none")
        elif all(s == "done" for s in real):
            state = "done"
        elif any(s == "warn" for s in real):
            state = "warn"
        else:
            state = "pending"
        done = sum(1 for s in real if s == "done")
        out.append({
            "key": stage.get("key"), "label": stage.get("label"),
            "state": state, "ref": "",
            "detail": (f"{done} of {len(real)} lines done" if real
                       else stage.get("detail", "")),
        })
    return out


def _worst_risk(members):
    worst = max(members, key=lambda m: RISK_ORDER.get(
        (m.get("risk") or {}).get("level"), 0))
    r = dict(worst.get("risk") or {"level": "NONE"})
    n = len(members)
    lvl = r.get("level")
    same = sum(1 for m in members
               if (m.get("risk") or {}).get("level") == lvl)
    if lvl in ("LATE", "AT_RISK") and same:
        r["reason"] = f"{same} of {n} lines {('late' if lvl == 'LATE' else 'at risk')}"
    return r


def _least_state(members):
    return min((m.get("state") for m in members),
               key=lambda s: STATE_ORDER.get(s, 0))


def _summary(members, values):
    first = members[0]
    qty, uom = _rollup_qty(members)
    s = {
        "count": len(members),
        "bundle": (first.get("bundle") or "").strip(),
        "supplier": (first.get("bundle_supplier") or "").strip(),
        "category": first.get("category") or first.get("trade") or "",
        "make_brand": _common(members, "make_brand"),
        "supply_by": first.get("supply_by"),
        "source_country": (_common(members, "source_country")
                           or _common(members, "ipr_country")),
        "required_date": _earliest_required(members),
        "quantity": qty, "uom": uom,
        "pipeline": _agg_pipeline(members),
        "risk": _worst_risk(members),
        "state": _least_state(members),
    }
    if values:
        est = sum((Decimal(str(m["estimated_value"])) for m in members
                   if m.get("estimated_value") is not None), Decimal("0"))
        comm = sum((Decimal(str(m["committed"]["value"])) for m in members
                    if m.get("committed")
                    and m["committed"].get("currency") == "USD"), Decimal("0"))
        s["estimated_value"] = est
        s["currency"] = "USD"
        s["committed_value"] = comm if comm else None
    return s


def group_rows(line_dicts, values=True):
    """Order a section's lines into rows: a standalone {'kind':'line'} row, or a
    {'kind':'bundle'} row carrying the derived `summary` + its `members`. A
    bundle needs >=2 members; a lone bundled line renders as a normal line.
    Order is preserved from the first appearance of each bundle."""
    buckets, order = {}, []
    for ld in line_dicts:
        k = group_key(ld)
        if k is None:
            order.append(("line", ld, None))
            continue
        if k not in buckets:
            buckets[k] = []
            order.append(("bundle", None, k))
        buckets[k].append(ld)
    rows = []
    for kind, ld, k in order:
        if kind == "line":
            rows.append({"kind": "line", "line": ld})
            continue
        members = buckets[k]
        if len(members) < 2:
            rows.append({"kind": "line", "line": members[0]})
        else:
            rows.append({
                "kind": "bundle",
                "key": "|".join(str(x) for x in k),
                "summary": _summary(members, values),
                "members": members,
            })
    return rows
