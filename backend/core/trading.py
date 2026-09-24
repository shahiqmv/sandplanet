"""The trading arm's business rules (TRADING_BUILD_BRIEF.md) — phase 2, the
sales front: inquiry → pricing → quotation → won / lost.

Money truth lives here and nowhere else (blueprint §7.2): `calc()` prices
an order, and every screen and PDF reads its result. Stages derive forward
from the work done; an explicit pick wins; nothing moves backward.
"""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from . import fx
from .audit import audit
from .models import (ImportReceipt, Item, Supplier, TradingLine,
                     TradingOrder, TradingQuotation, User)
from .numbering import next_ref

ZERO = Decimal("0")
_CENT = Decimal("0.01")
_4DP = Decimal("0.0001")
STAGES = TradingOrder.STAGE_ORDER
ENTITY = "trading_order"


def _q2(v):
    return Decimal(str(v or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)


def _q4(v):
    return Decimal(str(v or 0)).quantize(_4DP, rounding=ROUND_HALF_UP)


def _dec(v, default=None):
    if v is None or v == "":
        return default
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return default


def _param(key, default):
    from .models import CompanyParameter
    try:
        return CompanyParameter.objects.get(key=key).value
    except CompanyParameter.DoesNotExist:
        return default


def gst_rate():
    """Output GST on local sales — the same company parameter the project
    tax invoice prints (8 % unless Finance changes it)."""
    return _dec(_param("gst_rate", 8), Decimal("8"))


# ---- access ------------------------------------------------------------------

def can_manage(user, order):
    """Sales manage their own inquiries; the Sales Manager and Admin manage
    all (blueprint §6). Finance / Signatory read only."""
    if user.role in ("SALES_MANAGER", "ADMIN"):
        return True
    return user.role == "SALES" and order.owner_id == user.id


def can_authorise(user):
    return user.role in ("SALES_MANAGER", "ADMIN")


# ---- pricing ---------------------------------------------------------------

def line_fx(line, sell_currency, rate=None):
    """Cost-currency → sell-currency rate for a line: the one typed on the
    line, else the company USD/MVR rate, else 1 for a same-currency line."""
    if line.fx:
        return Decimal(str(line.fx))
    cc = (line.cost_currency or sell_currency).upper()
    if cc == sell_currency:
        return Decimal("1")
    rate = rate or fx.usd_rate()
    if cc == "USD" and sell_currency == "MVR":
        return rate
    if cc == "MVR" and sell_currency == "USD":
        return (Decimal("1") / rate).quantize(Decimal("0.000001"))
    return None                                  # a pair we have no rate for


def calc_line(line, sell_currency, rate=None):
    r = line_fx(line, sell_currency, rate)
    qty = _dec(line.qty, ZERO) or ZERO
    cost = _dec(line.cost)
    unit_cost = None
    if cost is not None and r is not None:
        unit_cost = _q4(cost * r)
    if line.sell is not None:
        unit_sell = _q4(line.sell)
    elif unit_cost is not None and line.margin_percent is not None:
        unit_sell = _q4(unit_cost * (Decimal("1") + Decimal(str(line.margin_percent)) / 100))
    elif unit_cost is not None:
        unit_sell = unit_cost
    else:
        unit_sell = None
    line_cost = _q2(unit_cost * qty) if unit_cost is not None else None
    line_sell = _q2(unit_sell * qty) if unit_sell is not None else None
    margin_pct = None
    if unit_cost and unit_sell is not None:
        margin_pct = _q2((unit_sell / unit_cost - 1) * 100)
    elif line.margin_percent is not None:
        margin_pct = _q2(line.margin_percent)
    return {
        "fx": r, "fx_missing": cost is not None and r is None,
        "unit_cost": unit_cost, "line_cost": line_cost,
        "unit_sell": unit_sell, "line_sell": line_sell,
        "margin_percent": margin_pct,
        "margin_amount": (_q2(line_sell - line_cost)
                          if line_sell is not None and line_cost is not None
                          else None),
    }


def calc(order, lines=None):
    """Price the whole order. Returns per-line figures keyed by line id and
    the totals: cost, sell, freight, GST, grand total, margin."""
    lines = list(order.lines.all()) if lines is None else list(lines)
    rate = fx.usd_rate()
    cur = (order.currency or "MVR").upper()
    per = {ln.id: calc_line(ln, cur, rate) for ln in lines}
    cost_lines = sum((p["line_cost"] for p in per.values()
                      if p["line_cost"] is not None), ZERO)
    sell_lines = sum((p["line_sell"] for p in per.values()
                      if p["line_sell"] is not None), ZERO)
    freight_cost = _q2(order.freight_cost)
    freight_sell = _q2(order.freight_sell) if order.freight_sell is not None else None
    cost_total = _q2(cost_lines + freight_cost)
    subtotal = _q2(sell_lines + (freight_sell or ZERO))
    gst_pct = ZERO if order.customer.gst_exempt else gst_rate()
    gst = _q2(subtotal * gst_pct / 100)
    total = _q2(subtotal + gst)
    margin_amount = _q2(subtotal - cost_total)
    margin_pct = (_q2(margin_amount / cost_total * 100) if cost_total else None)
    return {
        "lines": per,
        "currency": cur, "usd_rate": rate,
        "cost_lines": cost_lines, "sell_lines": sell_lines,
        "freight_cost": freight_cost, "freight_sell": freight_sell,
        "cost_total": cost_total, "subtotal": subtotal,
        "gst_percent": gst_pct, "gst": gst, "total": total,
        "margin_amount": margin_amount, "margin_percent": margin_pct,
        "n_lines": len(lines),
        "n_costed": sum(1 for p in per.values() if p["unit_cost"] is not None),
        "n_priced": sum(1 for p in per.values() if p["unit_sell"]),
        "fx_missing": any(p["fx_missing"] for p in per.values()),
    }


# ---- stages ------------------------------------------------------------------

def derived_stage(order, lines=None):
    """What the work says the stage is (blueprint §6): a supplier assigned
    → Sourcing, a cost entered → Pricing, an authorised quotation → Quoted."""
    lines = list(order.lines.all()) if lines is None else list(lines)
    st = "INQUIRY"
    if any(ln.supplier_id for ln in lines):
        st = "SOURCING"
    if any(ln.cost is not None for ln in lines):
        st = "PRICING"
    if order.quotations.filter(status="AUTHORISED").exists():
        st = "QUOTED"
    return st


def effective_stage(order, lines=None):
    if order.is_closed:
        return order.stage
    d = derived_stage(order, lines)
    return d if STAGES.index(d) > STAGES.index(order.stage) else order.stage


def sync_stage(order, actor=None, lines=None):
    """Persist a forward auto-advance. Never moves backward, never past
    QUOTED on its own."""
    eff = effective_stage(order, lines)
    if eff != order.stage:
        old = order.stage
        order.stage = eff
        order.stage_since = timezone.localdate()
        order.save(update_fields=["stage", "stage_since", "updated_at"])
        audit(ENTITY, order.id, "TIN_STAGE", actor=actor, from_state=old,
              to_state=eff, detail={"ref": order.ref, "auto": True})
    return order.stage


def set_stage(order, stage, actor):
    """An explicit pick: forward only, among the pre-Won stages."""
    if order.is_closed:
        return "This order is closed."
    if stage not in STAGES[:-1]:
        return "Won is recorded with the customer's PO; Lost with a reason."
    if STAGES.index(stage) < STAGES.index(order.stage):
        return "A stage never moves backward."
    if stage == order.stage:
        return None
    old = order.stage
    order.stage = stage
    order.stage_since = timezone.localdate()
    order.save(update_fields=["stage", "stage_since", "updated_at"])
    audit(ENTITY, order.id, "TIN_STAGE", actor=actor, from_state=old,
          to_state=stage, detail={"ref": order.ref})
    return None


# ---- create / edit -----------------------------------------------------------

HEADER_FIELDS = ("title", "received_via", "customer_ref", "currency",
                 "next_action", "next_action_date", "notes",
                 "quote_valid_days", "payment_terms", "delivery_terms",
                 "freight_cost", "freight_sell", "inquiry_date")


def _apply_header(order, data, errors):
    for k in HEADER_FIELDS:
        if k not in data:
            continue
        v = data[k]
        if k in ("next_action_date", "inquiry_date"):
            if v in (None, ""):
                v = None
            else:
                try:
                    v = date.fromisoformat(str(v))
                except ValueError:
                    errors[k] = "Enter a valid date."
                    continue
        elif k in ("freight_cost", "freight_sell"):
            d = _dec(v, None)
            if k == "freight_cost":
                d = d if d is not None else ZERO
            if d is not None and d < 0:
                errors[k] = "Cannot be negative."
                continue
            v = d
        elif k == "quote_valid_days":
            try:
                v = max(1, int(v or 14))
            except (TypeError, ValueError):
                errors[k] = "Enter a number of days."
                continue
        elif k == "currency":
            v = (v or "MVR").upper()
            if v not in ("MVR", "USD"):
                errors[k] = "Quotes are in MVR or USD."
                continue
        elif k == "received_via":
            if v not in TradingOrder.Via.values:
                errors[k] = "Unknown channel."
                continue
        elif k == "title":
            v = (v or "").strip()
            if not v:
                errors[k] = "Say what the customer asked for."
                continue
        else:
            v = v or ""
        setattr(order, k, v)


def create_order(data, actor):
    from .models import Customer
    errors = {}
    try:
        customer = Customer.objects.get(id=data.get("customer"), is_active=True)
    except (Customer.DoesNotExist, ValueError, TypeError):
        return None, {"customer": "Pick the customer."}
    owner = actor
    if data.get("owner") and can_authorise(actor):
        owner = User.objects.filter(id=data["owner"],
                                    role__in=User.TRADING_ROLES).first() or actor
    order = TradingOrder(customer=customer, owner=owner, created_by=actor,
                         inquiry_date=timezone.localdate(),
                         stage_since=timezone.localdate(),
                         currency=customer.default_currency or "MVR")
    _apply_header(order, {"title": data.get("title"), **{
        k: data[k] for k in HEADER_FIELDS if k in data and k != "title"}}, errors)
    if errors:
        return None, errors
    with transaction.atomic():
        order.ref = next_ref("TIN", None)
        order.save()
    audit(ENTITY, order.id, "TIN_CREATED", actor=actor,
          detail={"ref": order.ref, "customer": customer.name,
                  "owner": owner.username})
    return order, None


def update_order(order, data, actor):
    errors = {}
    if order.is_closed:
        allowed = {"next_action", "next_action_date", "notes"}
        if set(data) - allowed:
            return {"detail": "This order is closed — only the notes and "
                              "next action can change."}
    _apply_header(order, data, errors)
    if "owner" in data and can_authorise(actor):
        u = User.objects.filter(id=data["owner"],
                                role__in=User.TRADING_ROLES).first()
        if u is None:
            errors["owner"] = "Pick a Sales user."
        else:
            order.owner = u
    if errors:
        return errors
    order.save()
    audit(ENTITY, order.id, "TIN_UPDATED", actor=actor,
          detail={"ref": order.ref, "fields": sorted(k for k in data
                                                      if k in HEADER_FIELDS
                                                      or k == "owner")})
    return None


def write_lines(order, rows, actor):
    """Replace the pricing sheet, keeping the ids of rows that survive (a
    later delivery note will reference them). One transaction — the
    blueprint's duplicated-list bug can't happen here."""
    if order.is_closed:
        return "This order is closed — the pricing sheet is locked."
    clean, errors = [], []
    for i, r in enumerate(rows or [], 1):
        desc = (r.get("description") or "").strip()
        if not desc:
            errors.append(f"Line {i}: enter a description.")
            continue
        qty = _dec(r.get("qty"), Decimal("1"))
        if qty is None or qty <= 0:
            errors.append(f"Line {i}: quantity must be more than zero.")
            continue
        cost = _dec(r.get("cost"))
        if cost is not None and cost < 0:
            errors.append(f"Line {i}: cost cannot be negative.")
            continue
        sell = _dec(r.get("sell"))
        margin = _dec(r.get("margin_percent"))
        fxv = _dec(r.get("fx"))
        clean.append({
            "id": r.get("id"), "sr_no": i,
            "section": (r.get("section") or "").strip(),
            "description": desc, "item_id": r.get("item") or None,
            "qty": qty, "uom": (r.get("uom") or "").strip()[:20],
            "supplier_id": r.get("supplier") or None,
            "cost": cost, "cost_currency": (r.get("cost_currency") or "USD").upper()[:3],
            "fx": fxv if fxv and fxv > 0 else None,
            "margin_percent": margin, "sell": sell if sell is not None and sell >= 0 else None,
            "notes": r.get("notes") or "",
        })
    if errors:
        return " ".join(errors)
    sup_ids = {c["supplier_id"] for c in clean if c["supplier_id"]}
    if sup_ids and Supplier.objects.filter(id__in=sup_ids).count() != len(sup_ids):
        return "A line names a supplier that is not on file."
    item_ids = {c["item_id"] for c in clean if c["item_id"]}
    if item_ids and Item.objects.filter(id__in=item_ids).count() != len(item_ids):
        return "A line names a catalogue item that is not on file."
    with transaction.atomic():
        existing = {ln.id: ln for ln in order.lines.select_for_update()}
        keep = set()
        for c in clean:
            ln = existing.get(c["id"]) if c["id"] else None
            if ln is None:
                ln = TradingLine(order=order)
            for k, v in c.items():
                if k != "id":
                    setattr(ln, k, v)
            ln.save()
            keep.add(ln.id)
        for lid, ln in existing.items():
            if lid not in keep:
                ln.delete()
    audit(ENTITY, order.id, "TIN_LINES", actor=actor,
          detail={"ref": order.ref, "lines": len(clean)})
    sync_stage(order, actor)
    return None


# ---- quotation ---------------------------------------------------------------

def _customer_block(c):
    return {"name": c.name, "address": c.billing_address, "tin": c.tin,
            "contact": c.contact_person, "island": c.island}


def snapshot(order):
    """The priced sheet as the customer will see it: no cost, no margin."""
    lines = list(order.lines.all())
    k = calc(order, lines)
    rows = []
    for ln in lines:
        p = k["lines"][ln.id]
        rows.append({"id": ln.id, "sr_no": ln.sr_no, "section": ln.section,
                     "description": ln.description, "qty": str(ln.qty),
                     "uom": ln.uom, "unit_sell": str(p["unit_sell"] or 0),
                     "line_sell": str(p["line_sell"] or 0)})
    return {
        "title": order.title, "customer": _customer_block(order.customer),
        "customer_ref": order.customer_ref, "currency": k["currency"],
        "lines": rows,
        "totals": {"subtotal": str(k["subtotal"]),
                   "freight": (str(k["freight_sell"])
                               if k["freight_sell"] is not None else None),
                   "gst_percent": str(k["gst_percent"]), "gst": str(k["gst"]),
                   "total": str(k["total"])},
        "terms": {"valid_days": order.quote_valid_days,
                  "payment": order.payment_terms,
                  "delivery": order.delivery_terms},
    }


def quotation_blockers(order):
    if order.is_closed:
        return "This order is closed."
    lines = list(order.lines.all())
    if not lines:
        return "Price at least one line before quoting."
    k = calc(order, lines)
    if k["fx_missing"]:
        return "A line has a cost currency with no exchange rate — enter the rate on the line."
    if k["n_priced"] < k["n_lines"]:
        return ("Every line needs a selling price before the quotation goes "
                f"out ({k['n_lines'] - k['n_priced']} still unpriced).")
    return None


def issue_quotation(order, actor):
    """Freeze the sheet as the next revision and hand it to the Sales
    Manager. Any earlier revision still awaiting authorisation is withdrawn
    by this one; an authorised one is superseded only when this one is
    authorised."""
    err = quotation_blockers(order)
    if err:
        return None, err
    with transaction.atomic():
        order = TradingOrder.objects.select_for_update().get(id=order.id)
        if not order.quote_ref:
            order.quote_ref = next_ref("TQ", None)
            order.save(update_fields=["quote_ref", "updated_at"])
        order.quotations.filter(status="AWAITING_AUTH").update(status="WITHDRAWN")
        rev = (order.quotations.order_by("-revision").first() or
               TradingQuotation(revision=0)).revision + 1
        q = TradingQuotation.objects.create(
            order=order, revision=rev, snapshot=snapshot(order),
            valid_until=timezone.localdate() + timedelta(days=order.quote_valid_days),
            created_by=actor)
    audit(ENTITY, order.id, "TQ_ISSUED", actor=actor,
          detail={"ref": order.ref, "quotation": q.ref, "revision": rev,
                  "total": q.snapshot["totals"]["total"]})
    if can_authorise(actor):
        # The manager preparing their own quotation authorises it in one step.
        authorise_quotation(q, actor)
    return q, None


def authorise_quotation(q, actor):
    if not can_authorise(actor):
        return "Only the Sales Manager authorises a quotation."
    if q.status != "AWAITING_AUTH":
        return "This revision is not awaiting authorisation."
    with transaction.atomic():
        q.order.quotations.filter(status="AUTHORISED").update(status="SUPERSEDED")
        q.status = "AUTHORISED"
        q.authorised_by = actor
        q.authorised_at = timezone.now()
        q.valid_until = timezone.localdate() + timedelta(days=q.order.quote_valid_days)
        q.save(update_fields=["status", "authorised_by", "authorised_at",
                              "valid_until"])
        _store_quotation_pdf(q)
    audit(ENTITY, q.order_id, "TQ_AUTHORISED", actor=actor,
          detail={"ref": q.order.ref, "quotation": q.ref})
    sync_stage(q.order, actor)
    return None


def withdraw_quotation(q, actor):
    if q.status not in ("AWAITING_AUTH", "AUTHORISED"):
        return "This revision is already closed."
    if q.order.is_closed:
        return "This order is closed."
    q.status = "WITHDRAWN"
    q.save(update_fields=["status"])
    audit(ENTITY, q.order_id, "TQ_WITHDRAWN", actor=actor,
          detail={"ref": q.order.ref, "quotation": q.ref})
    return None


def current_quotation(order):
    return order.quotations.filter(status="AUTHORISED").order_by("-revision").first()


def quotation_context(q, draft=False):
    from .commercial import amount_in_words
    from .pdf import company_info, logo_src
    from .pdf import _money as money
    s = q.snapshot
    cur = s.get("currency", "MVR")
    cur_words = "Rufiyaa" if cur == "MVR" else "US Dollars"
    rows, last_section = [], None
    for ln in s["lines"]:
        if ln.get("section") and ln["section"] != last_section:
            rows.append({"heading": ln["section"]})
            last_section = ln["section"]
        rows.append({**ln, "qty_f": _fmt_qty(ln["qty"]),
                     "unit_f": money(ln["unit_sell"]),
                     "amount_f": money(ln["line_sell"])})
    t = s["totals"]
    signer = q.authorised_by
    return {
        "logo_src": logo_src(), "co": company_info(), "q": q, "order": q.order,
        "ref": q.ref, "draft": draft, "s": s, "rows": rows, "currency": cur,
        "date": (q.authorised_at or q.created_at),
        "valid_until": q.valid_until,
        "subtotal_f": money(t["subtotal"]),
        "freight_f": money(t["freight"]) if t.get("freight") is not None else None,
        "gst_pct": Decimal(t["gst_percent"]), "gst_f": money(t["gst"]),
        "total_f": money(t["total"]),
        "in_words": amount_in_words(t["total"], cur_words),
        "signer": ({"name": signer.full_name,
                    "designation": "Sales Manager" if signer.role == "SALES_MANAGER"
                    else _param("company_signee_designation", "Managing Director")}
                   if signer else None),
        "customer": s["customer"], "terms": s["terms"],
    }


def _fmt_qty(v):
    d = Decimal(str(v))
    return f"{d.normalize():f}" if d == d.to_integral() else f"{d:,.2f}"


def quotation_pdf_bytes(q, draft=False):
    from .views_commercial import pdf_bytes
    return pdf_bytes("pdf/trading_quotation.html", quotation_context(q, draft))


def _store_quotation_pdf(q):
    from django.conf import settings
    from django.core.files.base import ContentFile
    try:
        pdf = quotation_pdf_bytes(q)
    except Exception:                             # pragma: no cover - env dep
        if settings.PDF_REQUIRED:
            raise
        return
    name = q.ref.replace("/", "-") + ".pdf"
    q.pdf.save(name, ContentFile(pdf), save=True)


# ---- won / lost ----------------------------------------------------------------

def win_order(order, data, actor, po_file=None):
    """The customer's PO turns the quotation into a Sales Order (TSO-001).
    Needs an authorised quotation — nobody ships without one (blueprint
    §7.1)."""
    if order.is_closed:
        return "This order is closed."
    q = current_quotation(order)
    if q is None:
        return "Issue and authorise a quotation before recording the order."
    po = (data.get("po_number") or "").strip()
    if not po:
        return "Enter the customer's PO number."
    try:
        po_date = date.fromisoformat(str(data.get("po_date")))
    except (TypeError, ValueError):
        return "Enter the PO date."
    with transaction.atomic():
        order = TradingOrder.objects.select_for_update().get(id=order.id)
        order.po_number = po
        order.po_date = po_date
        if po_file is not None:
            order.po_file = po_file
        order.so_ref = next_ref("TSO", None)
        order.stage = "WON"
        order.stage_since = timezone.localdate()
        order.won_at = timezone.now()
        order.won_by = actor
        order.save()
    audit(ENTITY, order.id, "TIN_WON", actor=actor, from_state="QUOTED",
          to_state="WON", detail={"ref": order.ref, "so": order.so_ref,
                                  "po": po, "quotation": q.ref,
                                  "total": q.snapshot["totals"]["total"]})
    return None


def lose_order(order, reason, actor):
    if order.is_closed:
        return "This order is closed."
    reason = (reason or "").strip()
    if not reason:
        return "Say why it was lost — it is the one thing worth learning from."
    old = order.stage
    order.stage = "LOST"
    order.stage_since = timezone.localdate()
    order.lost_reason = reason
    order.lost_at = timezone.now()
    order.save()
    audit(ENTITY, order.id, "TIN_LOST", actor=actor, from_state=old,
          to_state="LOST", detail={"ref": order.ref, "reason": reason})
    return None


# ---- serialisation -----------------------------------------------------------------

def _s(v):
    return None if v is None else str(v)


def line_dict(ln, p):
    return {
        "id": ln.id, "sr_no": ln.sr_no, "section": ln.section,
        "description": ln.description, "item": ln.item_id,
        "qty": _s(ln.qty), "uom": ln.uom,
        "supplier": ln.supplier_id,
        "supplier_name": ln.supplier.name if ln.supplier_id else "",
        "cost": _s(ln.cost), "cost_currency": ln.cost_currency, "fx": _s(ln.fx),
        "margin_percent": _s(ln.margin_percent), "sell": _s(ln.sell),
        "notes": ln.notes,
        "calc": {k: _s(v) if isinstance(v, Decimal) else v for k, v in p.items()},
    }


def quotation_dict(q):
    return {
        "id": q.id, "ref": q.ref, "revision": q.revision, "status": q.status,
        "created_at": q.created_at, "created_by": q.created_by.full_name,
        "authorised_at": q.authorised_at,
        "authorised_by": q.authorised_by.full_name if q.authorised_by_id else None,
        "valid_until": q.valid_until, "total": q.snapshot["totals"]["total"],
        "currency": q.snapshot.get("currency"), "has_pdf": bool(q.pdf),
        "n_lines": len(q.snapshot.get("lines", [])),
    }


def order_summary(order, k=None):
    k = k or calc(order)
    return {
        "id": order.id, "ref": order.ref, "title": order.title,
        "customer": order.customer_id, "customer_name": order.customer.name,
        "owner": order.owner_id, "owner_name": order.owner.full_name,
        "stage": order.stage, "stage_since": order.stage_since,
        "inquiry_date": order.inquiry_date, "currency": order.currency,
        "next_action": order.next_action, "next_action_date": order.next_action_date,
        "quote_ref": order.quote_ref, "so_ref": order.so_ref,
        "subtotal": _s(k["subtotal"]), "total": _s(k["total"]),
        "margin_percent": _s(k["margin_percent"]),
        "n_lines": k["n_lines"], "updated_at": order.updated_at,
    }


def order_dict(order, user):
    lines = list(order.lines.select_related("supplier"))
    k = calc(order, lines)
    d = order_summary(order, k)
    d.update({
        "received_via": order.received_via, "customer_ref": order.customer_ref,
        "notes": order.notes, "quote_valid_days": order.quote_valid_days,
        "payment_terms": order.payment_terms,
        "delivery_terms": order.delivery_terms,
        "freight_cost": _s(order.freight_cost), "freight_sell": _s(order.freight_sell),
        "po_number": order.po_number, "po_date": order.po_date,
        "po_file": order.po_file.url if order.po_file else None,
        "won_at": order.won_at, "won_by": order.won_by.full_name if order.won_by_id else None,
        "lost_reason": order.lost_reason, "lost_at": order.lost_at,
        "customer_detail": _customer_block(order.customer) | {
            "gst_exempt": order.customer.gst_exempt,
            "default_currency": order.customer.default_currency},
        "lines": [line_dict(ln, k["lines"][ln.id]) for ln in lines],
        "calc": {kk: (_s(v) if isinstance(v, Decimal) else v)
                 for kk, v in k.items() if kk != "lines"},
        "quotations": [quotation_dict(q) for q in
                       order.quotations.select_related("created_by", "authorised_by")],
        "quotation_blocker": quotation_blockers(order),
        "can_manage": can_manage(user, order),
        "can_authorise": can_authorise(user),
        "is_closed": order.is_closed,
        "stages": STAGES,
    })
    return d


def activity(order):
    from .models import AuditLog
    out = []
    for a in AuditLog.objects.filter(entity=ENTITY, entity_id=order.id) \
            .select_related("actor").order_by("-id")[:200]:
        out.append({"at": a.at, "event": a.event,
                    "actor": a.actor.full_name if a.actor_id else "Planet",
                    "from": a.from_state, "to": a.to_state,
                    "detail": a.detail or {}})
    return out


# ---- the chase list ------------------------------------------------------------------

def home(user):
    today = timezone.localdate()
    open_q = TradingOrder.objects.exclude(stage__in=("WON", "LOST")) \
        .select_related("customer", "owner")
    mine = open_q.filter(owner=user) if user.role == "SALES" else open_q
    by_stage = {s: 0 for s in STAGES[:-1]}
    for o in mine:
        by_stage[o.stage] = by_stage.get(o.stage, 0) + 1
    due = mine.filter(next_action_date__isnull=False,
                      next_action_date__lte=today + timedelta(days=7)) \
        .order_by("next_action_date")
    chase = [{**order_summary(o), "overdue": o.next_action_date < today}
             for o in due[:30]]
    awaiting = []
    if can_authorise(user):
        awaiting = [{"order": q.order.ref, "order_id": q.order_id,
                     "quotation": q.ref, "customer": q.order.customer.name,
                     "total": q.snapshot["totals"]["total"],
                     "currency": q.snapshot.get("currency"),
                     "by": q.created_by.full_name, "at": q.created_at}
                    for q in TradingQuotation.objects.filter(status="AWAITING_AUTH")
                    .select_related("order__customer", "created_by")]
    recent_won = [order_summary(o) for o in
                  TradingOrder.objects.filter(stage="WON")
                  .select_related("customer", "owner").order_by("-won_at")[:5]]
    return {"by_stage": by_stage, "open": mine.count(), "chase": chase,
            "awaiting_authorisation": awaiting, "recent_won": recent_won}


# ---- phase 3: the supply leg ------------------------------------------------------

LIVE_IPR = ("DRAFT", "SUBMITTED", "APPROVED", "AUTHORISED", "CLOSED")


def _live_ipr_line(tline):
    """The order line already buying for this pricing-sheet line, if any."""
    for il in tline.ipr_lines.select_related("order__document"):
        d = il.order.document
        if d.status in LIVE_IPR and not d.is_void:
            return il
    return None


def _mvr_rate_for(order, cost_currency, lines):
    """Order currency → MVR for the import order: the company USD rate, 1
    for rufiyaa, or the sheet's own rate through the sell currency."""
    cc = cost_currency.upper()
    if cc == "MVR":
        return Decimal("1")
    if cc == "USD":
        return fx.usd_rate()
    sell = (order.currency or "MVR").upper()
    typed = [Decimal(str(ln.fx)) for ln in lines if ln.fx]
    if typed:
        to_sell = typed[0]
        return (to_sell * (fx.usd_rate() if sell == "USD" else Decimal("1"))
                ).quantize(Decimal("0.0001"))
    return None


def raise_import_orders(order, line_ids, actor):
    """Turn the won order's supplier lines into draft import orders — one
    per supplier — on the normal IPR chain, reserved to this trading order
    and posting in the trading book. Purchasing completes the draft (ports,
    proforma, payment schedule) and it is awarded and authorised as any
    other import (TRADING_BUILD_BRIEF.md §5.5)."""
    from . import costing, imports
    if order.stage != "WON":
        return None, "Import orders are raised against a won order (a sales order)."
    head = costing.by_code(costing.TRD_COGS)
    if head is None:
        return None, "The trading cost-of-sales head is missing — ask Finance."
    lines = list(order.lines.filter(id__in=line_ids or []).select_related("supplier"))
    if not lines:
        return None, "Pick the lines to order."
    groups = {}
    for ln in lines:
        if not ln.supplier_id:
            return None, f"Line {ln.sr_no} has no supplier."
        if ln.cost is None:
            return None, f"Line {ln.sr_no} has no cost."
        if _live_ipr_line(ln) is not None:
            return None, f"Line {ln.sr_no} is already on an import order."
        groups.setdefault(ln.supplier_id, []).append(ln)
    created = []
    with transaction.atomic():
        for sid, group in groups.items():
            sup = group[0].supplier
            ccys = {(ln.cost_currency or "USD").upper() for ln in group}
            if len(ccys) > 1:
                return None, (f"{sup.name}: the lines are costed in more than "
                              "one currency — one import order takes one.")
            ccy = ccys.pop()
            rate = _mvr_rate_for(order, ccy, group)
            if rate is None:
                return None, (f"{sup.name}: no {ccy} → MVR rate. Enter the "
                              "exchange rate on the pricing-sheet lines first.")
            data = {
                "supplier_id": sup.id, "order_currency": ccy,
                "exchange_rate": str(rate),
                "incoterm": sup.default_incoterm or "",
                "notes": f"Trading — {order.so_ref} for {order.customer.name} "
                         f"({order.ref}: {order.title})",
                "trading_order_id": order.id,
                "lines": [{
                    "item_id": ln.item_id, "free_text_desc": ln.description,
                    "unit": ln.uom, "spec": "", "order_qty": str(ln.qty),
                    "unit_price": str(ln.cost), "cost_head_id": head.id,
                    "remarks": ln.section, "trading_line_id": ln.id,
                    "allocations": [{"trading_order_id": order.id,
                                     "qty": str(ln.qty)}],
                } for ln in group],
            }
            doc, err = imports.create_ipr(data, actor)
            if err:
                transaction.set_rollback(True)
                return None, f"{sup.name}: {err}"
            created.append(doc)
    audit(ENTITY, order.id, "TIN_IPR_RAISED", actor=actor,
          detail={"ref": order.ref, "so": order.so_ref,
                  "iprs": [d.ref for d in created],
                  "lines": [ln.id for ln in lines]})
    return created, None


def supply(order):
    """The sales order's supply picture: each line's import status, and each
    import order with its shipments, receipts and landed cost."""
    from . import imports
    lines_out, iprs = [], {}
    for ln in order.lines.select_related("supplier"):
        il = _live_ipr_line(ln)
        row = {"id": ln.id, "sr_no": ln.sr_no, "section": ln.section,
               "description": ln.description, "qty": _s(ln.qty), "uom": ln.uom,
               "supplier": ln.supplier_id,
               "supplier_name": ln.supplier.name if ln.supplier_id else "",
               "cost": _s(ln.cost), "cost_currency": ln.cost_currency,
               "orderable": bool(ln.supplier_id and ln.cost is not None and il is None),
               "ipr": None, "ordered_qty": None, "shipped_qty": None,
               "received_qty": None, "unit_landed_mvr": None,
               "on_hand": _s(sum((lot.qty_on_hand for lot in
                                  ln.order.lots.filter(source_ipr_line__trading_line=ln)),
                                 ZERO))}
        if il is not None:
            d = il.order.document
            row.update({"ipr": d.ref, "ipr_status": d.status,
                        "ordered_qty": _s(il.order_qty),
                        "shipped_qty": _s(imports.line_shipped(il)),
                        "received_qty": _s(imports.line_received_qty(il))})
            iprs.setdefault(d.ref, il.order)
        lines_out.append(row)
    for ref, io in iprs.items():
        lc = imports.landed_cost(io)
        for il in io.lines.all():
            for row in lines_out:
                if row["ipr"] == ref and il.trading_line_id == row["id"]:
                    row["unit_landed_mvr"] = _s(lc["lines"].get(il.id, {}).get("unit_landed"))
    ipr_rows = []
    for ref, io in iprs.items():
        d = io.document
        lc = imports.landed_cost(io)
        ships = []
        for sh in imports.order_shipments(io):
            t = sh.tracking.first() if hasattr(sh, "tracking") else None
            ships.append({"ref": sh.ref, "seq": sh.seq, "mode": sh.mode,
                          "status": sh.status, "eta": getattr(sh, "eta", None),
                          "live": (t.raw_status if t and getattr(t, "raw_status", None) else None)})
        ipr_rows.append({
            "ref": d.ref, "status": d.status, "is_void": d.is_void,
            "supplier": io.supplier.name, "currency": io.order_currency,
            "exchange_rate": _s(io.exchange_rate),
            "order_total": _s(imports.ipr_order_total(io)),
            "mvr_total": _s(imports.ipr_mvr_total(io)),
            "landed_total_mvr": _s(lc["total_landed"]),
            "charges_mvr": _s(lc["total_charges"]),
            "uplift_pct": _s(lc["uplift_pct"]),
            "shipments": ships,
            "received": [r.document.ref for r in
                         ImportReceipt.objects.filter(shipment__order=io,
                                                      document__status="RECEIVED")
                         .select_related("document")],
        })
    return {"lines": lines_out, "import_orders": ipr_rows,
            "orderable": [r["id"] for r in lines_out if r["orderable"]],
            "lots_on_hand": _s(sum((lot.qty_on_hand for lot in order.lots.all()), ZERO))}
