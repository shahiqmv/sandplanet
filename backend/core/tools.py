"""Tools & Equipment register service.

Tools are tracked as individual assets (one row per physical unit), unlike
consumable stock. Items in a tool-flagged category arrive on the register from
a verified GRN; site admin fills serial/model and manages the faulty → repair →
in-use cycle. The register also feeds the DPR machinery summary.
"""
from decimal import Decimal

from django.utils import timezone

from .audit import audit
from .models import ItemCategory, ToolAsset


def tool_category_names():
    """Lower-cased names of the item categories flagged as tools."""
    return {c.name.lower() for c in
            ItemCategory.objects.filter(is_tool=True)}


def is_tool_item(item):
    return bool(item and item.category
               and item.category.lower() in tool_category_names())


def create_from_grn(grn, line, qty, actor):
    """Add `qty` individual tool assets from a received GRN line."""
    n = int(Decimal(str(qty)))
    made = []
    for _ in range(max(n, 0)):
        asset = ToolAsset.objects.create(
            site=grn.site, item=line.item,
            name=line.item.description if line.item_id else line.free_text_desc,
            category=line.item.category if line.item_id else "",
            brand=line.item.brand if line.item_id else "",
            source=ToolAsset.Source.GRN, document=grn, added_by=actor)
        made.append(asset)
    if made:
        audit("tool_asset", made[0].id, "TOOLS_RECEIVED", actor=actor,
              detail={"grn": grn.ref, "name": made[0].name, "qty": len(made)})
    return made


def set_state(asset, state, note, actor):
    """Move a tool through its condition cycle (in use / faulty / under repair
    / retired) with an audited note."""
    old = asset.state
    asset.state = state
    asset.state_note = note or ""
    asset.state_changed_at = timezone.now()
    asset.save(update_fields=["state", "state_note", "state_changed_at",
                              "updated_at"])
    audit("tool_asset", asset.id, "TOOL_STATE_CHANGED", actor=actor,
          from_state=old, to_state=state,
          detail={"name": asset.name, "note": note or ""})
    return asset


def summary(site):
    """Machinery summary for the DPR: in-use tools grouped by name with counts
    (e.g. Battery drill × 3), plus a faulty/under-repair count per name."""
    rows = {}
    for t in ToolAsset.objects.filter(site=site).exclude(
            state=ToolAsset.State.RETIRED):
        r = rows.setdefault(t.name, {"item": t.name, "nos": 0, "down": 0})
        if t.state == ToolAsset.State.IN_USE:
            r["nos"] += 1
        else:
            r["down"] += 1
    out = []
    for r in sorted(rows.values(), key=lambda x: x["item"].lower()):
        remarks = f"{r['down']} faulty/under repair" if r["down"] else ""
        out.append({"item": r["item"], "nos": r["nos"], "remarks": remarks})
    return out
