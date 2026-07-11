"""Site inventory service — the sole writer of StockMovement rows.

A deliberately simple quantity ledger: on-hand for a (site, item) is the sum
of that pair's movement qtys, and the movement list *is* the stock history.
No costing, no lots, no reservations (deferred to Phase 1B). Receipts are
raised automatically from verified GRNs; issues and reconciliations are entered
by site admin staff.
"""
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from .models import Item, StockMovement

ZERO = Decimal("0")


def _dec(v):
    return v if isinstance(v, Decimal) else Decimal(str(v))


def balance(site, item):
    """On-hand quantity of one item at one site."""
    return StockMovement.objects.filter(site=site, item=item).aggregate(
        t=Sum("qty"))["t"] or ZERO


def balances(site):
    """All items that have ever moved at this site, with current on-hand.

    Returns a list of dicts sorted by item code, including zero/negative
    balances so staff can see items that have been fully issued out."""
    rows = (StockMovement.objects.filter(site=site)
            .values("item").annotate(on_hand=Sum("qty")))
    by_item = {r["item"]: (r["on_hand"] or ZERO) for r in rows}
    items = Item.objects.filter(id__in=by_item).order_by("code")
    out = []
    for it in items:
        out.append({
            "item_id": it.id,
            "code": it.code,
            "description": it.description,
            "unit": it.unit,
            "category": it.category,
            "on_hand": by_item[it.id],
        })
    return out


def received_on(site, item, on_date):
    """Total received (RECEIPT qty) for one item at one site on a given date —
    lets the DPR show today's GRN intake without re-entering it."""
    return StockMovement.objects.filter(
        site=site, item=item, kind=StockMovement.Kind.RECEIPT,
        movement_date=on_date).aggregate(t=Sum("qty"))["t"] or ZERO


def major_materials(site, on_date=None):
    """Every catalog item flagged as a major material, with this site's current
    on-hand (0 when it has never moved here). Feeds the DPR key-materials
    loader — a key material still belongs on the report at zero stock. When
    `on_date` is given, also reports that day's received (GRN) quantity."""
    on_hand = {r["item"]: (r["on_hand"] or ZERO) for r in
               StockMovement.objects.filter(site=site)
               .values("item").annotate(on_hand=Sum("qty"))}
    out = []
    for it in Item.objects.filter(is_major=True, is_active=True,
                                  merged_into__isnull=True).order_by("code"):
        row = {
            "item_id": it.id, "code": it.code, "description": it.description,
            "unit": it.unit, "on_hand": on_hand.get(it.id, ZERO),
        }
        if on_date is not None:
            row["received_today"] = received_on(site, it, on_date)
        out.append(row)
    return out


def consume(site, item, qty, *, project=None, document=None, actor=None,
            movement_date=None, reason=""):
    """Record reported consumption as an ISSUE movement. Unlike issue(), this
    does NOT guard against overdrawing — a DPR reports what was actually used,
    and a resulting negative balance is the signal that the ledger needs a
    reconciliation rather than a reason to reject the report."""
    qty = _dec(qty)
    if qty <= ZERO:
        return None
    return StockMovement.objects.create(
        site=site, item=item, kind=StockMovement.Kind.ISSUE, qty=-qty,
        project=project, document=document, reason=reason,
        movement_date=movement_date or date.today(), created_by=actor)


def history(site, item):
    """Movement rows for one (site, item), newest first, with running balance
    computed oldest→newest so each row shows the on-hand *after* it applied."""
    rows = list(StockMovement.objects.filter(site=site, item=item)
                .select_related("project", "document", "created_by")
                .order_by("movement_date", "id"))
    running = ZERO
    out = []
    for m in rows:
        running += m.qty
        out.append({
            "id": m.id,
            "kind": m.kind,
            "qty": m.qty,
            "running": running,
            "project": m.project.title if m.project else None,
            "project_id": m.project_id,
            "document": m.document.ref if m.document else None,
            "reason": m.reason,
            "date": m.movement_date,
            "by": m.created_by.full_name if m.created_by else None,
        })
    out.reverse()  # newest first for display
    return out


def record_receipt(site, item, qty, *, document=None, actor=None,
                   movement_date=None):
    """Add stock from a GRN line. Non-positive qty is ignored (returns None)."""
    qty = _dec(qty)
    if qty <= ZERO:
        return None
    return StockMovement.objects.create(
        site=site, item=item, kind=StockMovement.Kind.RECEIPT, qty=qty,
        document=document, movement_date=movement_date or date.today(),
        created_by=actor)


@transaction.atomic
def issue(site, project, lines, *, actor=None, movement_date=None, reason=""):
    """Hand stock out to a project. `lines` is an iterable of
    {item, qty}. Fails atomically if any line would overdraw on-hand."""
    when = movement_date or date.today()
    created = []
    for ln in lines:
        item = ln["item"]
        qty = _dec(ln["qty"])
        if qty <= ZERO:
            continue
        on_hand = balance(site, item)
        if qty > on_hand:
            raise ValueError(
                f"{item.code} — only {on_hand} {item.unit} in stock, "
                f"cannot issue {qty}.")
        created.append(StockMovement.objects.create(
            site=site, item=item, kind=StockMovement.Kind.ISSUE, qty=-qty,
            project=project, reason=ln.get("reason", reason),
            movement_date=when, created_by=actor))
    if not created:
        raise ValueError("No lines to issue.")
    return created


def reconcile(site, item, counted_qty, *, reason="", actor=None,
              movement_date=None):
    """Book an ADJUST movement so on-hand equals the physically counted qty.
    A zero variance records nothing and returns None."""
    counted = _dec(counted_qty)
    current = balance(site, item)
    delta = counted - current
    if delta == ZERO:
        return None
    return StockMovement.objects.create(
        site=site, item=item, kind=StockMovement.Kind.ADJUST, qty=delta,
        reason=reason, movement_date=movement_date or date.today(),
        created_by=actor)
