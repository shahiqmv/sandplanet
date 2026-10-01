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


DEFAULT_TOOL_CATEGORY = "Tools & Equipment"
MAX_UNITS = 50            # added in one go


def tool_category_names():
    """Lower-cased names of the item categories flagged as tools."""
    return {c.name.lower() for c in
            ItemCategory.objects.filter(is_tool=True)}


def _flagged_categories():
    return list(ItemCategory.objects.filter(is_tool=True)
                .order_by("name").values_list("name", flat=True))


def tool_items():
    """Catalog items whose units are tracked on the register — the controlled
    source of tool names (the same names a GRN uses, so the DPR summary groups
    manual and received tools together). An item's own answer wins; without
    one it follows its category."""
    from django.db.models import Q

    from .models import Item
    return (Item.objects.filter(is_active=True, merged_into__isnull=True)
            .filter(Q(tracked_tool=True)
                    | Q(tracked_tool__isnull=True,
                        category__in=_flagged_categories()))
            .order_by("category", "description"))


def tool_categories():
    """The categories the pick-list is grouped under — every category that
    holds a tracked tool, not only the flagged ones."""
    return sorted({c for c in tool_items().values_list("category", flat=True)},
                  key=lambda c: (c or "").lower())


def is_tool_item(item):
    if item is None:
        return False
    if item.tracked_tool is not None:
        return item.tracked_tool
    return bool(item.category
                and item.category.lower() in tool_category_names())


def default_category():
    flagged = _flagged_categories()
    if DEFAULT_TOOL_CATEGORY in flagged or not flagged:
        return DEFAULT_TOOL_CATEGORY
    return flagged[0]


def tool_type_for(name, actor):
    """The catalog tool with this name — the existing one whatever its
    capitals, or a new one. A site that has a tool the catalog does not list
    types its name and carries on; the new entry is provisional until
    Purchasing checks the spelling, like any item a site creates."""
    from django.db import transaction

    from .models import Item
    from .procurement import next_item_code
    name = " ".join((name or "").split())
    if len(name) < 3:
        return None, "Type the tool's name."
    hit = tool_items().filter(description__iexact=name).first()
    if hit:
        return hit, None
    other = Item.objects.filter(description__iexact=name, is_active=True,
                                merged_into__isnull=True).first()
    if other is not None:
        return None, (f"'{other.description}' is in the catalog as a stock "
                      f"item ({other.category or 'no category'}), not a "
                      "tracked tool. Ask Purchasing to mark it as a tracked "
                      "tool, or use a more specific name.")
    with transaction.atomic():
        item = Item.objects.create(
            code=next_item_code(), description=name[:200], unit="nos",
            category=default_category(), tracked_tool=True,
            is_provisional=actor.role not in ("HO_PURCHASING", "ADMIN"))
    audit("item", item.id, "ITEM_CREATED", actor=actor,
          detail={"code": item.code, "provisional": item.is_provisional,
                  "via": "tools register"})
    return item, None


def add_units(site, item, qty, actor, *, source=None, details=None,
              document=None):
    """`qty` individual assets of one catalog tool at a site."""
    details = details or {}
    made = [ToolAsset.objects.create(
        site=site, item=item, name=item.description.strip(),
        category=item.category,
        serial_no=details.get("serial_no", "") if qty == 1 else "",
        model=details.get("model", ""),
        brand=details.get("brand") or item.brand or "",
        notes=details.get("notes", ""),
        source=source or ToolAsset.Source.MOBILISATION,
        document=document, added_by=actor) for _ in range(qty)]
    return made


def remove(assets, actor, reason, to_stock):
    """Take units off the register: entered by mistake, or not a tool that
    should be tracked one by one. `to_stock` puts each back into the site's
    counted stock — the pliers are still on the shelf. A unit that has moved
    between sites keeps its history and is retired instead."""
    from django.db import transaction
    from django.db.models import ProtectedError

    from .models import StockMovement
    removed, kept = [], []
    for asset in assets:
        snap = {"site": asset.site.code, "name": asset.name,
                "serial_no": asset.serial_no, "reason": reason[:200],
                "to_stock": bool(to_stock and asset.item_id)}
        try:
            with transaction.atomic():
                aid, site, item = asset.id, asset.site, asset.item
                asset.delete()
                if to_stock and item is not None:
                    StockMovement.objects.create(
                        site=site, item=item, kind=StockMovement.Kind.ADJUST,
                        qty=Decimal("1"),
                        reason=f"Returned from the tools register — {reason}"[:300],
                        movement_date=timezone.localdate(), created_by=actor)
            audit("tool_asset", aid, "TOOL_REMOVED", actor=actor, detail=snap)
            removed.append(aid)
        except ProtectedError:
            kept.append(asset.name)
    return removed, kept


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


def stock_to_convert():
    """Tracked tools sitting in counted stock: (site, item, whole units, the
    GRN the latest of them came on). They were received while the category
    tick was off, so the GRN booked them as consumables."""
    from django.db.models import Sum

    from .models import Site, StockMovement
    ids = list(tool_items().values_list("id", flat=True))
    rows = (StockMovement.objects.filter(item_id__in=ids)
            .values("site_id", "item_id").annotate(t=Sum("qty")))
    sites = {s.id: s for s in Site.objects.all()}
    items = {i.id: i for i in tool_items()}
    out = []
    for r in rows:
        n = int(r["t"] or 0)
        if n < 1:
            continue
        last = (StockMovement.objects.filter(
            site_id=r["site_id"], item_id=r["item_id"],
            kind=StockMovement.Kind.RECEIPT, document__isnull=False)
            .order_by("-movement_date", "-id").first())
        out.append((sites[r["site_id"]], items[r["item_id"]], n,
                    last.document if last else None))
    out.sort(key=lambda x: (x[0].code, x[1].description.lower()))
    return out


def convert_stock(actor=None):
    """Move every tracked tool out of counted stock onto its site's register,
    one row per unit, and take the same number out of stock. Returns the
    (site, item, units) moved. Atomic: all of it or none."""
    from django.db import transaction

    from .models import StockMovement
    from . import stock
    moved = []
    with transaction.atomic():
        for site, item, n, grn in stock_to_convert():
            before = stock.balance(site, item)
            add_units(site, item, n, actor, source=ToolAsset.Source.STOCK,
                      document=grn)
            StockMovement.objects.create(
                site=site, item=item, kind=StockMovement.Kind.ADJUST,
                qty=-Decimal(n),
                reason="Moved to the tools register — tracked tools are not "
                       "counted stock (owner 2026-10-01)",
                movement_date=timezone.localdate(), created_by=actor)
            assert stock.balance(site, item) == before - n
            moved.append((site, item, n))
        if moved:
            audit("tool_asset", 0, "TOOLS_MOVED_FROM_STOCK", actor=actor,
                  detail={"units": sum(m[2] for m in moved),
                          "lines": len(moved),
                          "sites": sorted({m[0].code for m in moved})})
    return moved


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
