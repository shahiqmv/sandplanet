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
from .numbering import next_trading_ref

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
    if user.has_any(("SALES_MANAGER", "ADMIN")):
        return True
    return user.has_role("SALES") and order.owner_id == user.id


def can_authorise(user):
    return user.has_any(("SALES_MANAGER", "ADMIN"))


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
                 "lead_time", "incoterm", "extra_terms",
                 "freight_cost", "freight_sell", "inquiry_date")

# The company's standard quotation lines. Company parameters, so they are
# the owner's to change without a release; a new inquiry copies them and
# the order's own copy is what prints.
STANDARD_TERMS = {
    "payment_terms": ("trading_terms_payment",
                      "50% with the order, balance before delivery"),
    "delivery_terms": ("trading_terms_delivery",
                       "Delivered to your vessel at Malé harbour"),
    "lead_time": ("trading_terms_lead_time",
                  "6–8 weeks from receipt of order and advance"),
    "incoterm": ("trading_terms_incoterm", "Delivered Malé (local supply)"),
    "extra_terms": ("trading_terms_extra",
                    "Prices are valid for the quantities quoted.\n"
                    "Goods remain the property of Sand Planet until paid in full."),
    "quote_valid_days": ("trading_terms_valid_days", 14),
}


def standard_terms():
    return {k: _param(key, default) for k, (key, default) in STANDARD_TERMS.items()}


def set_standard_terms(data, actor):
    from .models import CompanyParameter
    if not can_authorise(actor):
        return "Only the Sales Manager sets the standard terms."
    changed = []
    for k, (key, default) in STANDARD_TERMS.items():
        if k not in data:
            continue
        v = data[k]
        if k == "quote_valid_days":
            try:
                v = max(1, int(v or 14))
            except (TypeError, ValueError):
                return "Validity is a number of days."
        else:
            v = (v or "").strip()
        CompanyParameter.objects.update_or_create(
            key=key, defaults={"value": v,
                               "description": f"Trading quotation standard line — {k}"})
        changed.append(k)
    audit(ENTITY, 0, "TERMS_STANDARD_SET", actor=actor, detail={"fields": changed})
    return None


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
                         currency=customer.default_currency or "MVR",
                         **standard_terms())
    _apply_header(order, {"title": data.get("title"), **{
        k: data[k] for k in HEADER_FIELDS if k in data and k != "title"}}, errors)
    if errors:
        return None, errors
    with transaction.atomic():
        order.ref = next_trading_ref("IN")
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


COST_FIELDS = ("supplier_id", "cost", "cost_currency", "fx")


def update_costs(order, rows, actor):
    """A won order's customer prices are frozen with the quotation, but the
    supplier side keeps moving — the real supplier and landed cost are often
    known only later (owner 2026-09-25). Only supplier / cost / currency /
    rate change; each line's selling price is pinned first so a new cost
    cannot move it."""
    lines = {ln.id: ln for ln in order.lines.all()}
    cur = (order.currency or "MVR").upper()
    changed = 0
    with transaction.atomic():
        for r in rows or []:
            ln = lines.get(r.get("id"))
            if ln is None:
                continue
            if ln.sell is None:
                ln.sell = calc_line(ln, cur)["unit_sell"]      # pin the customer's price
                ln.margin_percent = None
            cost = _dec(r.get("cost"))
            fxv = _dec(r.get("fx"))
            new = {"supplier_id": r.get("supplier") or None,
                   "cost": cost if cost is None or cost >= 0 else ln.cost,
                   "cost_currency": (r.get("cost_currency") or ln.cost_currency or "USD").upper()[:3],
                   "fx": fxv if fxv and fxv > 0 else None}
            if new["supplier_id"] and not Supplier.objects.filter(id=new["supplier_id"]).exists():
                return "A line names a supplier that is not on file."
            if any(getattr(ln, k) != v for k, v in new.items()):
                changed += 1
            for k, v in new.items():
                setattr(ln, k, v)
            ln.save()
    audit(ENTITY, order.id, "TIN_COSTS", actor=actor,
          detail={"ref": order.ref, "lines_changed": changed})
    return None


def write_lines(order, rows, actor):
    """Replace the pricing sheet, keeping the ids of rows that survive (a
    later delivery note will reference them). One transaction — the
    blueprint's duplicated-list bug can't happen here."""
    if order.stage == "WON":
        return update_costs(order, rows, actor)
    if order.is_closed:
        return "This order is closed — the pricing sheet is locked."
    clean, errors = [], []
    for i, r in enumerate(rows or [], 1):
        # One multi-line field on the sheet: the first line is the product,
        # the rest its specs (owner 2026-09-24).
        raw = (r.get("description") or "").replace("\r", "").strip()
        desc, _, spec = raw.partition("\n")
        desc = desc.strip()
        spec = (r.get("spec") if r.get("spec") is not None and not spec else spec).strip()
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
            "description": desc, "spec": spec, "item_id": r.get("item") or None,
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
                     "description": ln.description, "spec": ln.spec,
                     "qty": str(ln.qty),
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
                  "delivery": order.delivery_terms,
                  "lead_time": order.lead_time, "incoterm": order.incoterm,
                  "extra": [t.strip() for t in (order.extra_terms or "").splitlines()
                            if t.strip()]},
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
            order.quote_ref = next_trading_ref("SQ")
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
    name = q.ref + ".pdf"
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
        order.so_ref = next_trading_ref("SO")
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
        "description": ln.description, "spec": ln.spec, "item": ln.item_id,
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
        "lead_time": order.lead_time, "incoterm": order.incoterm,
        "extra_terms": order.extra_terms,
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
        "money": money(order) if order.stage == "WON" else None,
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
    mine = (open_q.filter(owner=user) if user.has_role("SALES") and not user.has_role("SALES_MANAGER")
            else open_q)
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
                    "unit": ln.uom, "spec": ln.spec, "order_qty": str(ln.qty),
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


# ---- phase 4: delivery, invoicing and money in --------------------------------------

from django.db.models import Sum  # noqa: E402

from .commercial import _next_invoice_no  # noqa: E402
from .models import (CompanyBankAccount, StockLot, TradingCreditNote,  # noqa: E402
                     TradingDelivery, TradingDeliveryLine, TradingInvoice,
                     TradingReceipt, TradingReceiptLine)

MONEY_ROLES = ("FINANCE", "ADMIN")


def can_receipt(user):
    """Finance is the money desk; Admin covers for it."""
    return user.has_any(MONEY_ROLES)


def _ho():
    from .vouchers import ho_site
    return ho_site()


def _post_trading(head_code, state, source, amount, currency, actor):
    from . import costing
    head = costing.by_code(head_code)
    if head is None:
        raise ValueError(f"Cost head {head_code} is missing — ask Finance.")
    p = costing.post(site=_ho(), cost_head=head, state=state, source=source,
                     amount=amount, currency=currency, actor=actor,
                     book="TRADING")
    return p.id


def _reverse_postings(ids, actor):
    from . import costing
    from .models import CostPosting
    out = []
    for p in CostPosting.objects.filter(id__in=ids or []):
        r = costing.post(site=p.site, cost_head=p.cost_head, state=p.state,
                         source=p.source, amount=-p.amount, currency=p.currency,
                         reversal_of=p, actor=actor, is_stock_pool=p.is_stock_pool)
        out.append(r.id)
    return out


# --- deliveries ------------------------------------------------------------------

def _line_lots(line):
    return (StockLot.objects.filter(trading_order=line.order,
                                    source_ipr_line__trading_line=line,
                                    qty_on_hand__gt=0)
            .order_by("received_date", "id"))


def _needs_stock(line):
    return _live_ipr_line(line) is not None


def deliverable(order):
    """Per line: ordered, already on a delivery note (draft or live), left
    to deliver, and what is in the store for it."""
    rows = []
    for ln in order.lines.all():
        on_dn = (TradingDeliveryLine.objects
                 .filter(line=ln, delivery__status__in=("DRAFT", "DESPATCHED", "RECEIVED"))
                 .aggregate(s=Sum("qty"))["s"] or ZERO)
        stock = _needs_stock(ln)
        on_hand = (sum((l.qty_on_hand for l in _line_lots(ln)), ZERO) if stock else None)
        rows.append({"id": ln.id, "sr_no": ln.sr_no, "section": ln.section,
                     "description": ln.description, "uom": ln.uom,
                     "qty": _s(ln.qty), "delivered": _s(on_dn),
                     "remaining": _s(ln.qty - on_dn), "needs_stock": stock,
                     "on_hand": _s(on_hand) if on_hand is not None else None,
                     "can_deliver": _s(min(ln.qty - on_dn, on_hand) if stock
                                       else ln.qty - on_dn)})
    return rows


def _parse_dn_lines(order, rows, exclude_dn=None):
    """Validate {line_id, qty} rows against what is left to deliver and what
    is in the store. Returns (clean, error)."""
    clean = []
    for r in rows or []:
        qty = _dec(r.get("qty"))
        if qty is None or qty <= 0:
            continue
        ln = order.lines.filter(id=r.get("line_id") or r.get("line")).first()
        if ln is None:
            return None, "A delivery line is not on this order."
        on_dn_qs = TradingDeliveryLine.objects.filter(
            line=ln, delivery__status__in=("DRAFT", "DESPATCHED", "RECEIVED"))
        if exclude_dn is not None:
            on_dn_qs = on_dn_qs.exclude(delivery=exclude_dn)
        on_dn = on_dn_qs.aggregate(s=Sum("qty"))["s"] or ZERO
        left = ln.qty - on_dn
        if qty > left:
            return None, (f"{ln.description}: only {left} left to deliver "
                          f"(ordered {ln.qty}, on delivery notes {on_dn}).")
        if _needs_stock(ln):
            on_hand = sum((l.qty_on_hand for l in _line_lots(ln)), ZERO)
            if qty > on_hand:
                return None, (f"{ln.description}: only {on_hand} in the store "
                              "for this order.")
        clean.append((ln, qty))
    if not clean:
        return None, "Add at least one line with a quantity."
    return clean, None


def _apply_dn_header(dn, data, errors):
    if "delivery_date" in data:
        try:
            dn.delivery_date = date.fromisoformat(str(data["delivery_date"]))
        except (TypeError, ValueError):
            errors["delivery_date"] = "Enter the delivery date."
    for k in ("vessel", "jetty", "receiver", "notes"):
        if k in data:
            setattr(dn, k, (data.get(k) or "").strip())


def create_delivery(order, data, actor):
    if order.stage != "WON":
        return None, {"detail": "Deliveries are made against a won order."}
    clean, err = _parse_dn_lines(order, data.get("lines"))
    if err:
        return None, {"detail": err}
    dn = TradingDelivery(order=order, delivery_date=timezone.localdate(),
                         created_by=actor)
    errors = {}
    _apply_dn_header(dn, data, errors)
    if errors:
        return None, errors
    with transaction.atomic():
        dn.ref = next_trading_ref("DN")
        dn.save()
        for ln, qty in clean:
            TradingDeliveryLine.objects.create(delivery=dn, line=ln, qty=qty)
    audit(ENTITY, order.id, "TDN_CREATED", actor=actor,
          detail={"ref": order.ref, "dn": dn.ref, "lines": len(clean)})
    return dn, None


def update_delivery(dn, data, actor):
    if dn.status != "DRAFT":
        return {"detail": "Only a draft delivery note can change."}
    errors = {}
    _apply_dn_header(dn, data, errors)
    if errors:
        return errors
    with transaction.atomic():
        if "lines" in data:
            clean, err = _parse_dn_lines(dn.order, data["lines"], exclude_dn=dn)
            if err:
                return {"detail": err}
            dn.lines.all().delete()
            for ln, qty in clean:
                TradingDeliveryLine.objects.create(delivery=dn, line=ln, qty=qty)
        dn.save()
    audit(ENTITY, dn.order_id, "TDN_UPDATED", actor=actor,
          detail={"ref": dn.order.ref, "dn": dn.ref})
    return None


def despatch_delivery(dn, actor):
    """The goods leave for the harbour: draw the reserved lots (FIFO), post
    cost of sales at their landed cost, file the delivery note PDF."""
    if dn.status != "DRAFT":
        return "This delivery note is not a draft."
    if not dn.vessel.strip():
        return "Enter the customer's vessel before despatching."
    if not dn.receiver.strip():
        return "Enter who receives the goods on board."
    clean, err = _parse_dn_lines(dn.order, [{"line_id": l.line_id, "qty": l.qty}
                                            for l in dn.lines.all()], exclude_dn=dn)
    if err:
        return err
    with transaction.atomic():
        dn = TradingDelivery.objects.select_for_update().get(id=dn.id)
        cogs = ZERO
        for dl in dn.lines.select_related("line"):
            if not _needs_stock(dl.line):
                dl.unit_cost_mvr = None
                dl.lots = []
                dl.save(update_fields=["unit_cost_mvr", "lots"])
                continue
            need, drawn, cost = dl.qty, [], ZERO
            for lot in _line_lots(dl.line).select_for_update():
                if need <= 0:
                    break
                take = min(lot.qty_on_hand, need)
                lot.qty_on_hand -= take
                lot.save(update_fields=["qty_on_hand"])
                drawn.append({"lot": lot.id, "qty": str(take),
                              "unit_landed": str(lot.unit_landed_cost)})
                cost += take * lot.unit_landed_cost
                need -= take
            if need > 0:
                transaction.set_rollback(True)
                return f"{dl.line.description}: the store ran short by {need}."
            dl.unit_cost_mvr = (cost / dl.qty).quantize(_4DP) if dl.qty else None
            dl.lots = drawn
            dl.save(update_fields=["unit_cost_mvr", "lots"])
            cogs += cost
        dn.cogs_mvr = _q2(cogs)
        dn.posting_ids = ([_post_trading("TRD_COGS", "INCURRED", "STORE_ISSUE",
                                         dn.cogs_mvr, "MVR", actor)]
                          if dn.cogs_mvr else [])
        dn.status = "DESPATCHED"
        dn.despatched_by = actor
        dn.despatched_at = timezone.now()
        dn.save()
        _store_pdf(dn, "pdf/trading_delivery_note.html", delivery_context(dn),
                   dn.ref + ".pdf")
    audit(ENTITY, dn.order_id, "TDN_DESPATCHED", actor=actor,
          detail={"ref": dn.order.ref, "dn": dn.ref, "vessel": dn.vessel,
                  "cogs_mvr": str(dn.cogs_mvr)})
    return None


def receive_delivery(dn, signed_copy, actor):
    if dn.status != "DESPATCHED":
        return "Only a despatched delivery note can be marked received."
    if signed_copy is not None:
        dn.signed_copy = signed_copy
    dn.status = "RECEIVED"
    dn.received_at = timezone.now()
    dn.save()
    audit(ENTITY, dn.order_id, "TDN_RECEIVED", actor=actor,
          detail={"ref": dn.order.ref, "dn": dn.ref, "signed": bool(signed_copy)})
    return None


def cancel_delivery(dn, actor):
    if dn.status != "DRAFT":
        return "Only a draft delivery note can be cancelled."
    dn.status = "CANCELLED"
    dn.save(update_fields=["status"])
    audit(ENTITY, dn.order_id, "TDN_CANCELLED", actor=actor,
          detail={"ref": dn.order.ref, "dn": dn.ref})
    return None


def delivery_context(dn):
    from .pdf import company_info, logo_src
    rows, last, no = [], None, 0
    for dl in dn.lines.select_related("line"):
        ln = dl.line
        if ln.section and ln.section != last:
            rows.append({"heading": ln.section})
            last = ln.section
        no += 1
        rows.append({"no": no, "description": ln.description, "spec": ln.spec,
                     "qty_f": _fmt_qty(dl.qty), "uom": ln.uom})
    return {"logo_src": logo_src(), "co": company_info(), "dn": dn,
            "order": dn.order, "customer": _customer_block(dn.order.customer),
            "rows": rows,
            "despatched_by": dn.despatched_by.full_name if dn.despatched_by_id else ""}


def _store_pdf(obj, template, ctx, name):
    from django.conf import settings
    from django.core.files.base import ContentFile

    from .views_commercial import pdf_bytes
    try:
        pdf = pdf_bytes(template, ctx)
    except Exception:                             # pragma: no cover - env dep
        if settings.PDF_REQUIRED:
            raise
        return
    obj.pdf.save(name.replace("/", "-"), ContentFile(pdf), save=True)


def delivery_dict(dn):
    return {
        "id": dn.id, "ref": dn.ref, "status": dn.status,
        "delivery_date": dn.delivery_date, "vessel": dn.vessel, "jetty": dn.jetty,
        "receiver": dn.receiver, "notes": dn.notes,
        "signed_copy": dn.signed_copy.url if dn.signed_copy else None,
        "has_pdf": bool(dn.pdf), "invoice": dn.invoice.ref if dn.invoice_id else None,
        "invoice_id": dn.invoice_id, "cogs_mvr": _s(dn.cogs_mvr),
        "despatched_at": dn.despatched_at,
        "despatched_by": dn.despatched_by.full_name if dn.despatched_by_id else None,
        "received_at": dn.received_at,
        "lines": [{"id": dl.id, "line": dl.line_id, "description": dl.line.description,
                   "section": dl.line.section, "uom": dl.line.uom, "qty": _s(dl.qty),
                   "unit_cost_mvr": _s(dl.unit_cost_mvr)}
                  for dl in dn.lines.select_related("line")],
    }


# --- invoices ---------------------------------------------------------------------

def _unit_sell_for(order, line):
    """The price the customer agreed: the authorised quotation's, else the
    sheet's."""
    q = current_quotation(order)
    if q is not None:
        for row in q.snapshot.get("lines", []):
            if row.get("id") == line.id:
                return _dec(row.get("unit_sell"), ZERO)
    return calc_line(line, (order.currency or "MVR").upper())["unit_sell"] or ZERO


def invoiceable_deliveries(order):
    return order.deliveries.filter(status__in=("DESPATCHED", "RECEIVED"),
                                   invoice__isnull=True)


def freight_billed(order):
    return order.invoices.filter(includes_freight=True,
                                 status__in=("DRAFT", "ISSUED", "PAID")).exists()


def _invoice_figures(order, dns, charges, include_freight):
    rows = []
    for dn in dns:
        for dl in dn.lines.select_related("line"):
            unit = _unit_sell_for(order, dl.line)
            rows.append({"line": dl.line_id, "dn_ref": dn.ref,
                         "description": dl.line.description, "spec": dl.line.spec,
                         "uom": dl.line.uom,
                         "qty": str(dl.qty), "unit_sell": str(_q4(unit)),
                         "amount": str(_q2(unit * dl.qty))})
    goods = sum((Decimal(r["amount"]) for r in rows), ZERO)
    freight = _q2(order.freight_sell) if include_freight and order.freight_sell else ZERO
    clean_charges = []
    for c in charges or []:
        amt = _dec(c.get("amount"))
        label = (c.get("label") or "").strip()
        if amt is None or amt == 0 or not label:
            continue
        clean_charges.append({"label": label, "amount": str(_q2(amt))})
    extra = sum((Decimal(c["amount"]) for c in clean_charges), ZERO)
    subtotal = _q2(goods + freight + extra)
    gst_pct = ZERO if order.customer.gst_exempt else gst_rate()
    gst = _q2(subtotal * gst_pct / 100)
    return {"rows": rows, "goods": goods, "freight": freight, "charges": clean_charges,
            "subtotal": subtotal, "gst_percent": gst_pct, "gst": gst,
            "total": _q2(subtotal + gst)}


def create_invoice(order, data, actor):
    if order.stage != "WON":
        return None, "Invoices are raised against a won order."
    ids = data.get("delivery_ids") or []
    dns = list(invoiceable_deliveries(order).filter(id__in=ids))
    if not dns or len(dns) != len(set(ids)):
        return None, "Pick despatched delivery notes that are not yet invoiced."
    include_freight = bool(data.get("include_freight")) and not freight_billed(order) \
        and order.freight_sell is not None
    f = _invoice_figures(order, dns, data.get("charges"), include_freight)
    try:
        inv_date = date.fromisoformat(str(data.get("invoice_date") or timezone.localdate()))
    except ValueError:
        return None, "Enter the invoice date."
    due = inv_date + timedelta(days=order.customer.credit_days or 0)
    # The advance the customer paid on the pro-forma comes off this invoice
    # (all of what is still unapplied, up to the invoice total) unless told
    # to hold it back for a later delivery.
    apply_adv = data.get("apply_advance", True)
    advance = min(advance_available(order), f["total"]) if apply_adv else ZERO
    with transaction.atomic():
        inv = TradingInvoice.objects.create(
            order=order, customer=order.customer, ref=_next_invoice_no(), invoice_date=inv_date,
            due_date=due, currency=(order.currency or "MVR").upper(),
            includes_freight=include_freight, charges=f["charges"],
            snapshot={"customer": _customer_block(order.customer),
                      "lines": f["rows"], "dn_refs": [d.ref for d in dns]},
            subtotal=f["subtotal"], gst_percent=f["gst_percent"], gst=f["gst"],
            total=f["total"], advance_applied=_q2(advance), created_by=actor)
        for dn in dns:
            dn.invoice = inv
            dn.save(update_fields=["invoice"])
    audit(ENTITY, order.id, "TSI_CREATED", actor=actor,
          detail={"ref": order.ref, "invoice": inv.ref, "total": str(inv.total),
                  "deliveries": [d.ref for d in dns]})
    return inv, None


def issue_invoice(inv, actor):
    if not can_authorise(actor):
        return "Only the Sales Manager issues a tax invoice."
    if inv.status != "DRAFT":
        return "This invoice is not a draft."
    if not inv.customer.tin and not inv.customer.gst_exempt:
        return ("The customer has no GST TIN on file — a tax invoice needs "
                "it. Add it on the customer, or mark them GST exempt.")
    with transaction.atomic():
        inv.status = "ISSUED"
        inv.issued_by = actor
        inv.issued_at = timezone.now()
        ids = [_post_trading("TRD_REVENUE", "INCURRED", "SALE", inv.subtotal,
                             inv.currency, actor)]
        if inv.gst:
            ids.append(_post_trading("TRD_OUTPUT_GST", "INCURRED", "SALE", inv.gst,
                                     inv.currency, actor))
        inv.posting_ids = ids
        inv.save()
        _store_pdf(inv, "pdf/trading_tax_invoice.html", invoice_context(inv),
                   inv.ref + ".pdf")
    audit(ENTITY, inv.order_id, "TSI_ISSUED", actor=actor,
          detail={"ref": inv.order.ref, "invoice": inv.ref, "total": str(inv.total)})
    return None


def void_invoice(inv, reason, actor):
    if inv.status == "VOID":
        return "Already void."
    if inv.receipts.exists():
        return "Money has been received against this invoice — it cannot be voided."
    if inv.credit_notes.exists():
        return "A credit note has been issued against this invoice."
    reason = (reason or "").strip()
    if not reason:
        return "Say why the invoice is void."
    with transaction.atomic():
        if inv.status in ("ISSUED", "PAID"):
            inv.posting_ids = _reverse_postings(inv.posting_ids, actor)
        inv.status = "VOID"
        inv.void_reason = reason
        inv.save()
        inv.deliveries.update(invoice=None)       # free the deliveries to re-invoice
    audit(ENTITY, inv.order_id or 0, "TSI_VOID", actor=actor,
          detail={"ref": inv.order.ref if inv.order_id else "historic", "invoice": inv.ref,
                  "reason": reason})
    return None


def invoice_received(inv):
    return _q2(inv.receipts.aggregate(s=Sum("amount"))["s"] or ZERO)


def invoice_credited(inv):
    return _q2(inv.credit_notes.aggregate(s=Sum("amount"))["s"] or ZERO)


def invoice_outstanding(inv):
    if inv.status not in ("ISSUED", "PAID"):
        return ZERO
    return _q2(inv.total - inv.advance_applied - invoice_credited(inv)
               - invoice_received(inv))


# --- advances (money in before delivery, on the pro-forma) -------------------------

def advance_received(order):
    return _q2(TradingReceiptLine.objects.filter(order=order)
               .aggregate(s=Sum("amount"))["s"] or ZERO)


def advance_applied(order):
    return _q2(order.invoices.filter(status__in=("DRAFT", "ISSUED", "PAID"))
               .aggregate(s=Sum("advance_applied"))["s"] or ZERO)


def advance_available(order):
    return _q2(advance_received(order) - advance_applied(order))


def proforma_context(order, advance_pct=None):
    """A pro-forma invoice off the authorised quotation, carrying the sales
    order reference rather than a number of its own (the owner's practice):
    what the customer pays against before anything ships."""
    from .commercial import amount_in_words
    from .pdf import _money as money
    q = current_quotation(order)
    if q is None:
        return None
    ctx = quotation_context(q, draft=False)
    t = q.snapshot["totals"]
    total = Decimal(t["total"])
    pct = _dec(advance_pct)
    adv = _q2(total * pct / 100) if pct and pct > 0 else None
    received = advance_received(order)
    ctx.update({
        "proforma": True, "order": order,
        "advance_pct": pct if adv is not None else None,
        "advance_f": money(adv) if adv is not None else None,
        "advance_words": amount_in_words(adv, "USD" if ctx["currency"] == "USD" else "Rufiyaa")
        if adv is not None else None,
        "received_f": money(received) if received else None,
        "balance_f": money(_q2(total - received)) if received else None,
        "date": order.won_at or q.authorised_at or timezone.now(),
        "signer": None,
    })
    return ctx


def proforma_pdf_bytes(order, advance_pct=None):
    from .views_commercial import pdf_bytes
    ctx = proforma_context(order, advance_pct)
    if ctx is None:
        raise ValueError("no authorised quotation")
    return pdf_bytes("pdf/trading_proforma.html", ctx)


def _settle(inv):
    if inv.status == "ISSUED" and invoice_outstanding(inv) <= ZERO:
        inv.status = "PAID"
        inv.save(update_fields=["status"])
    elif inv.status == "PAID" and invoice_outstanding(inv) > ZERO:
        inv.status = "ISSUED"
        inv.save(update_fields=["status"])


def invoice_context(inv, draft=False):
    from .commercial import amount_in_words
    from .pdf import company_info, logo_src
    from .pdf import _money as money
    s = inv.snapshot
    signer = inv.issued_by
    return {
        "logo_src": logo_src(), "co": company_info(), "inv": inv, "order": inv.order,
        "customer": s.get("customer", {}), "currency": inv.currency,
        "draft": draft and inv.status == "DRAFT", "void": inv.status == "VOID",
        "dn_refs": ", ".join(s.get("dn_refs", [])),
        "rows": [{**r, "qty_f": _fmt_qty(r["qty"]), "unit_f": money(r["unit_sell"]),
                  "amount_f": money(r["amount"])} for r in s.get("lines", [])],
        "freight_f": money(inv.order.freight_sell) if inv.includes_freight else None,
        "charges": [{**c, "amount_f": money(c["amount"])} for c in inv.charges],
        "subtotal_f": money(inv.subtotal), "gst_pct": inv.gst_percent,
        "gst_f": money(inv.gst), "total_f": money(inv.total),
        "advance_f": money(inv.advance_applied) if inv.advance_applied else None,
        "balance_f": money(_q2(inv.total - inv.advance_applied)),
        "advance_receipts": ", ".join(sorted({l.receipt.receipt_no for l in
                                              TradingReceiptLine.objects.filter(order=inv.order)
                                              .select_related("receipt")})),
        "in_words": amount_in_words(_q2(inv.total - inv.advance_applied),
                                    "USD" if inv.currency == "USD" else "Rufiyaa"),
        "signer": ({"name": signer.full_name,
                    "designation": "Sales Manager" if signer.role == "SALES_MANAGER"
                    else _param("company_signee_designation", "Managing Director")}
                   if signer else None),
    }


def invoice_pdf_bytes(inv):
    from .views_commercial import pdf_bytes
    return pdf_bytes("pdf/trading_tax_invoice.html", invoice_context(inv, draft=True))


def invoice_dict(inv):
    return {
        "id": inv.id, "ref": inv.ref, "status": inv.status, "historic": inv.historic,
        "description": inv.description, "customer": inv.customer_id,
        "customer_name": inv.customer.name if inv.customer_id else None,
        "invoice_date": inv.invoice_date, "due_date": inv.due_date,
        "currency": inv.currency, "subtotal": _s(inv.subtotal),
        "gst_percent": _s(inv.gst_percent), "gst": _s(inv.gst), "total": _s(inv.total),
        "includes_freight": inv.includes_freight, "charges": inv.charges,
        "advance_applied": _s(inv.advance_applied),
        "deliveries": inv.snapshot.get("dn_refs", []),
        "lines": inv.snapshot.get("lines", []),
        "received": _s(invoice_received(inv)), "credited": _s(invoice_credited(inv)),
        "outstanding": _s(invoice_outstanding(inv)),
        "has_pdf": bool(inv.pdf), "void_reason": inv.void_reason,
        "issued_at": inv.issued_at,
        "issued_by": inv.issued_by.full_name if inv.issued_by_id else None,
        "credit_notes": [{"id": c.id, "ref": c.ref, "amount": _s(c.amount),
                          "gst": _s(c.gst), "reason": c.reason, "at": c.issued_at,
                          "by": c.issued_by.full_name}
                         for c in inv.credit_notes.select_related("issued_by")],
        "receipts": [{"receipt_no": l.receipt.receipt_no, "date": l.receipt.receipt_date,
                      "amount": _s(l.amount), "method": l.receipt.method,
                      "reference": l.receipt.reference}
                     for l in inv.receipts.select_related("receipt")],
    }


def create_credit_note(inv, data, actor):
    if not can_authorise(actor):
        return None, "Only the Sales Manager issues a credit note."
    if inv.status not in ("ISSUED", "PAID"):
        return None, "A credit note is issued against an issued invoice."
    amt = _dec(data.get("amount"))
    reason = (data.get("reason") or "").strip()
    if amt is None or amt <= 0:
        return None, "Enter the credit amount (including GST)."
    if not reason:
        return None, "Say why the credit is given."
    if amt > invoice_outstanding(inv) + invoice_received(inv):
        return None, "The credit exceeds the invoice."
    gst_share = _q2(amt * inv.gst / inv.total) if inv.total else ZERO
    with transaction.atomic():
        cn = TradingCreditNote(invoice=inv, ref=next_trading_ref("CN"), amount=_q2(amt),
                               gst=gst_share, reason=reason, issued_by=actor)
        ids = [_post_trading("TRD_REVENUE", "INCURRED", "SALE", -(cn.amount - gst_share),
                             inv.currency, actor)]
        if gst_share:
            ids.append(_post_trading("TRD_OUTPUT_GST", "INCURRED", "SALE", -gst_share,
                                     inv.currency, actor))
        cn.posting_ids = ids
        cn.save()
        _settle(inv)
    audit(ENTITY, inv.order_id or 0, "TCN_ISSUED", actor=actor,
          detail={"ref": inv.order.ref if inv.order_id else "historic", "invoice": inv.ref,
                  "credit_note": cn.ref,
                  "amount": str(cn.amount), "reason": reason})
    return cn, None


def money(order):
    live = order.invoices.filter(status__in=("ISSUED", "PAID"))
    invoiced = _q2(sum((i.total for i in live), ZERO))
    credited = _q2(sum((invoice_credited(i) for i in live), ZERO))
    received = _q2(sum((invoice_received(i) for i in live), ZERO))
    adv_in, adv_applied = advance_received(order), advance_applied(order)
    applied_live = _q2(live.aggregate(s=Sum("advance_applied"))["s"] or ZERO)
    return {"invoiced": _s(invoiced), "credited": _s(credited),
            "received": _s(received), "advance_received": _s(adv_in),
            "advance_applied": _s(adv_applied), "advance_available": _s(adv_in - adv_applied),
            "outstanding": _s(invoiced - credited - received - applied_live),
            "delivered_cogs_mvr": _s(sum((d.cogs_mvr for d in order.deliveries.filter(
                status__in=("DESPATCHED", "RECEIVED"))), ZERO))}


# --- receipts (money in) -----------------------------------------------------------

def open_invoices(customer):
    return [i for i in TradingInvoice.objects.filter(
        customer=customer, status__in=("ISSUED", "PAID"))
        .select_related("order").order_by("invoice_date", "id")
        if invoice_outstanding(i) > ZERO]


def invoice_label(inv):
    """What a receipt or statement line calls the invoice's job."""
    if inv.order_id:
        return inv.order.so_ref or inv.order.ref
    return inv.description or "Historic invoice"


HISTORIC_ROLES = ("FINANCE", "ADMIN", "SALES_MANAGER")


def create_historic_invoice(data, actor):
    """An invoice issued before Planet, still unpaid: entered only to be
    collected. ISSUED at once, no order, no postings (its revenue lives in
    the old books), no PDF (the original exists); the aging, the statement
    and receipts treat it like any other (owner 2026-09-26)."""
    from .models import Customer
    if not actor.has_any(HISTORIC_ROLES):
        return None, "Finance or the Sales Manager enters historic invoices."
    customer = Customer.objects.filter(id=data.get("customer"), is_active=True).first()
    if customer is None:
        return None, "Pick the customer."
    ref = (data.get("ref") or "").strip()[:20]
    if not ref:
        return None, "Enter the invoice number as it was issued."
    if TradingInvoice.objects.filter(ref__iexact=ref).exists():
        return None, f"{ref} is already on file."
    try:
        inv_date = date.fromisoformat(str(data.get("invoice_date")))
    except (TypeError, ValueError):
        return None, "Enter the invoice date."
    due = None
    if data.get("due_date"):
        try:
            due = date.fromisoformat(str(data["due_date"]))
        except (TypeError, ValueError):
            return None, "Enter a valid due date."
    else:
        due = inv_date + timedelta(days=customer.credit_days or 0)
    currency = (data.get("currency") or customer.default_currency or "MVR").upper()
    if currency not in ("MVR", "USD"):
        return None, "MVR or USD."
    subtotal = _dec(data.get("subtotal"))
    gst = _dec(data.get("gst"), ZERO)
    if subtotal is None or subtotal <= 0 or gst is None or gst < 0:
        return None, "Enter the invoice amount (before GST) and the GST, if any."
    subtotal, gst = _q2(subtotal), _q2(gst)
    total = _q2(subtotal + gst)
    received = _dec(data.get("received"), ZERO)          # part-paid before Planet
    if received is None or received < 0 or received > total:
        return None, "Amount already received must be between 0 and the total."
    inv = TradingInvoice.objects.create(
        order=None, customer=customer, historic=True,
        description=(data.get("description") or "").strip()[:200],
        ref=ref, status="ISSUED", invoice_date=inv_date, due_date=due, currency=currency,
        snapshot={"customer": _customer_block(customer), "lines": [], "dn_refs": []},
        subtotal=subtotal, gst_percent=(gst / subtotal * 100).quantize(Decimal("0.01"))
        if gst else ZERO, gst=gst, total=total,
        advance_applied=_q2(received),                    # the part already paid comes off
        created_by=actor, issued_by=actor, issued_at=timezone.now())
    audit(ENTITY, 0, "HISTORIC_INVOICE", actor=actor,
          detail={"invoice": inv.ref, "customer": customer.name, "total": str(total),
                  "received_before": str(_q2(received))})
    return inv, None


def auto_allocate(customer, amount):
    """Oldest-first across the customer's open invoices (blueprint §7.6)."""
    left, out = _q2(amount), []
    for inv in open_invoices(customer):
        if left <= ZERO:
            break
        take = min(invoice_outstanding(inv), left)
        out.append({"invoice_id": inv.id, "invoice": inv.ref, "amount": str(take),
                    "outstanding": str(invoice_outstanding(inv))})
        left -= take
    return out, _s(left)


def record_receipt(data, actor):
    from .models import Customer
    from .receipts import next_receipt_no
    if not can_receipt(actor):
        return None, "Finance records customer receipts."
    customer = Customer.objects.filter(id=data.get("customer")).first()
    if customer is None:
        return None, "Pick the customer the money is from."
    try:
        rdate = date.fromisoformat(str(data.get("receipt_date")))
    except (TypeError, ValueError):
        return None, "Enter the receipt date."
    method = data.get("method") or "TT"
    if method not in TradingReceipt._meta.get_field("method").choices and \
            method not in [c[0] for c in TradingReceipt._meta.get_field("method").choices]:
        return None, "Choose how the payment was received."
    bank = None
    if data.get("bank_account"):
        bank = CompanyBankAccount.objects.filter(id=data["bank_account"]).first()
        if bank is None:
            return None, "That bank account no longer exists."
    parsed, currency = [], None
    for row in data.get("allocations") or []:
        amt = _dec(row.get("amount"))
        if amt is None or amt <= ZERO:
            continue
        if row.get("order_id"):
            # An advance against the pro-forma: on account of the won order.
            o = TradingOrder.objects.filter(id=row["order_id"], customer=customer,
                                            stage="WON").first()
            if o is None:
                return None, "An advance on this receipt is not against this customer's won order."
            q = current_quotation(o)
            cap = Decimal(q.snapshot["totals"]["total"]) if q else ZERO
            if advance_received(o) + amt > cap + Decimal("0.01"):
                return None, (f"{amt:,.2f} would take the advance on {o.so_ref} past "
                              f"the order value {cap:,.2f}.")
            ccy = (o.currency or "MVR").upper()
            if currency and ccy != currency:
                return None, "One receipt is in one currency."
            currency = ccy
            parsed.append((o, _q2(amt)))
            continue
        inv = TradingInvoice.objects.filter(id=row.get("invoice_id"),
                                            customer=customer,
                                            status__in=("ISSUED", "PAID")).first()
        if inv is None:
            return None, "An invoice on this receipt is not this customer's."
        due = invoice_outstanding(inv)
        if amt > due + Decimal("0.01"):
            return None, f"{amt:,.2f} exceeds the {due:,.2f} outstanding on {inv.ref}."
        if currency and inv.currency != currency:
            return None, "One receipt settles invoices in one currency."
        currency = inv.currency
        parsed.append((inv, _q2(amt)))
    if not parsed:
        return None, "Allocate the money to at least one invoice or order."
    with transaction.atomic():
        rc = TradingReceipt.objects.create(
            customer=customer, receipt_no=next_receipt_no(), receipt_date=rdate,
            method=method, reference=(data.get("reference") or "").strip(),
            bank_account=bank, currency=currency, note=data.get("note") or "",
            recorded_by=actor)
        for target, amt in parsed:
            if isinstance(target, TradingOrder):
                TradingReceiptLine.objects.create(receipt=rc, order=target, amount=amt)
            else:
                TradingReceiptLine.objects.create(receipt=rc, invoice=target, amount=amt)
        for target, _ in parsed:
            if isinstance(target, TradingInvoice):
                _settle(target)
    for target, amt in parsed:
        if isinstance(target, TradingOrder):
            audit(ENTITY, target.id, "ADVANCE_RECEIPT", actor=actor,
                  detail={"ref": target.ref, "so": target.so_ref,
                          "receipt_no": rc.receipt_no, "amount": str(amt)})
        else:
            audit(ENTITY, target.order_id or 0, "RECEIPT", actor=actor,
                  detail={"ref": target.order.ref if target.order_id else "historic",
                          "invoice": target.ref,
                          "receipt_no": rc.receipt_no, "amount": str(amt)})
    return rc, None


def delete_receipt(rc, actor):
    if not can_receipt(actor):
        return "Finance records customer receipts."
    lines = list(rc.lines.select_related("invoice", "order"))
    for l in lines:
        if l.order_id and advance_applied(l.order) > advance_received(l.order) - l.amount:
            return (f"The advance on {l.order.so_ref} has already been applied to an "
                    "invoice — void that invoice first.")
    invs = [l.invoice for l in lines if l.invoice_id]
    no = rc.receipt_no
    with transaction.atomic():
        rc.lines.all().delete()
        rc.delete()
        for inv in invs:
            _settle(inv)
    for l in lines:
        oid = (l.invoice.order_id or 0) if l.invoice_id else l.order_id
        audit(ENTITY, oid, "RECEIPT_DELETED", actor=actor,
              detail={"receipt_no": no, "invoice": l.invoice.ref if l.invoice_id else None,
                      "so": l.order.so_ref if l.order_id else None})
    return None


def receipt_dict(rc):
    ba = rc.bank_account
    lines = []
    for l in rc.lines.select_related("invoice__order", "order"):
        if l.invoice_id:
            lines.append({"id": l.id, "invoice_id": l.invoice_id, "invoice_no": l.invoice.ref,
                          "claim_ref": invoice_label(l.invoice),
                          "project_code": (l.invoice.order.so_ref or "") if l.invoice.order_id else "",
                          "amount": l.amount, "invoice_amount": l.invoice.total})
        else:
            q = current_quotation(l.order)
            lines.append({"id": l.id, "invoice_id": None, "order_id": l.order_id,
                          "invoice_no": f"Advance — {l.order.so_ref}",
                          "claim_ref": l.order.so_ref, "project_code": l.order.so_ref,
                          "amount": l.amount,
                          "invoice_amount": Decimal(q.snapshot["totals"]["total"]) if q else None})
    return {"id": rc.id, "receipt_no": rc.receipt_no, "receipt_date": rc.receipt_date,
            "method": rc.method, "method_label": rc.get_method_display(),
            "reference": rc.reference, "note": rc.note,
            "customer": rc.customer_id, "client": rc.customer.name,
            "bank_account": ba.label if ba else "", "currency": rc.currency,
            "total": rc.total, "lines": lines,
            "recorded_by": rc.recorded_by.full_name if rc.recorded_by_id else ""}


def receipt_context(rc):
    from .commercial import amount_in_words
    from .pdf import company_info, logo_src
    d = receipt_dict(rc)
    ba = rc.bank_account
    c = rc.customer
    return {"logo_src": logo_src(), "co": company_info(), "receipt": rc, "r": d,
            "currency": rc.currency,
            "payer": {"name": c.name, "address": c.billing_address,
                      "contact": c.contact_person, "designation": ""},
            "bank_account": ({"label": ba.label, "bank_name": ba.bank_name,
                              "account_name": ba.account_name, "account_no": ba.account_no,
                              "currency": ba.currency} if ba else None),
            "invoice_list": ", ".join(l["invoice_no"] for l in d["lines"]),
            "amount_words": amount_in_words(rc.total, "USD" if rc.currency == "USD" else "Rufiyaa")}


# --- receivables ------------------------------------------------------------------

def _bucket(days):
    if days <= 0:
        return "current"
    if days <= 30:
        return "d30"
    if days <= 60:
        return "d60"
    if days <= 90:
        return "d90"
    return "d90plus"


def aging(as_of=None):
    """Every open trading invoice by customer, bucketed by days past due."""
    today = as_of or timezone.localdate()
    by_cust = {}
    for inv in TradingInvoice.objects.filter(status__in=("ISSUED", "PAID")) \
            .select_related("order", "customer"):
        out = invoice_outstanding(inv)
        if out <= ZERO:
            continue
        c = inv.customer
        row = by_cust.setdefault(c.id, {
            "customer": c.id, "customer_name": c.name, "currency": inv.currency,
            "current": ZERO, "d30": ZERO, "d60": ZERO, "d90": ZERO, "d90plus": ZERO,
            "total": ZERO, "invoices": []})
        overdue = (today - (inv.due_date or inv.invoice_date)).days
        row[_bucket(overdue)] += out
        row["total"] += out
        row["invoices"].append({"id": inv.id, "ref": inv.ref,
                                "order": inv.order.ref if inv.order_id else None,
                                "order_id": inv.order_id, "historic": inv.historic,
                                "so_ref": invoice_label(inv), "invoice_date": inv.invoice_date,
                                "due_date": inv.due_date, "total": _s(inv.total),
                                "outstanding": _s(out), "overdue_days": max(0, overdue),
                                "currency": inv.currency})
    # Advances paid on pro-formas that no invoice has yet absorbed: money the
    # company holds for that customer, shown beside what they owe.
    for o in TradingOrder.objects.filter(stage="WON", advance_receipts__isnull=False) \
            .select_related("customer").distinct():
        avail = advance_available(o)
        if avail <= ZERO:
            continue
        c = o.customer
        row = by_cust.setdefault(c.id, {
            "customer": c.id, "customer_name": c.name, "currency": o.currency,
            "current": ZERO, "d30": ZERO, "d60": ZERO, "d90": ZERO, "d90plus": ZERO,
            "total": ZERO, "invoices": []})
        row["advance_on_account"] = _q2(row.get("advance_on_account", ZERO) + avail)
        row.setdefault("advances", []).append({"order_id": o.id, "order": o.ref, "so_ref": o.so_ref,
                                               "available": _s(avail)})
    rows = sorted(by_cust.values(), key=lambda r: -r["total"])
    for r in rows:
        for k in ("current", "d30", "d60", "d90", "d90plus", "total"):
            r[k] = _s(_q2(r[k]))
        r["advance_on_account"] = _s(_q2(r.get("advance_on_account", ZERO)))
    return {"as_of": today, "customers": rows,
            "total": _s(_q2(sum((Decimal(r["total"]) for r in rows), ZERO)))}


def statement(customer, date_from=None, date_to=None):
    """Chronological invoices, credit notes and receipts for a customer, with
    an opening balance for anything before the range (blueprint §7.6)."""
    to = date_to or timezone.localdate()
    entries = []
    for inv in TradingInvoice.objects.filter(customer=customer,
                                             status__in=("ISSUED", "PAID")) \
            .select_related("order"):
        entries.append({"date": inv.invoice_date, "kind": "INVOICE", "ref": inv.ref,
                        "detail": (f"{inv.order.so_ref} · {inv.order.title}" if inv.order_id
                                   else f"{inv.description or 'Invoice'} (before Planet)"),
                        "debit": inv.total, "credit": ZERO, "currency": inv.currency})
        if inv.historic and inv.advance_applied:
            # What the customer had paid on it before Planet: shown as a
            # credit on the invoice date so the balance carried is right.
            entries.append({"date": inv.invoice_date, "kind": "RECEIPT", "ref": "before Planet",
                            "detail": f"received on {inv.ref} before Planet",
                            "debit": ZERO, "credit": inv.advance_applied,
                            "currency": inv.currency})
        for cn in inv.credit_notes.all():
            entries.append({"date": cn.issued_at.date(), "kind": "CREDIT_NOTE", "ref": cn.ref,
                            "detail": f"against {inv.ref} — {cn.reason}",
                            "debit": ZERO, "credit": cn.amount, "currency": inv.currency})
    seen = set()
    for l in TradingReceiptLine.objects.filter(receipt__customer=customer) \
            .select_related("receipt", "invoice"):
        rc = l.receipt
        if rc.id in seen:
            continue
        seen.add(rc.id)
        settled = ", ".join((x.invoice.ref if x.invoice_id else f"advance on {x.order.so_ref}")
                            for x in rc.lines.select_related("invoice", "order"))
        entries.append({"date": rc.receipt_date, "kind": "RECEIPT", "ref": rc.receipt_no,
                        "detail": f"{rc.get_method_display()}"
                                  f"{' ' + rc.reference if rc.reference else ''} — {settled}",
                        "debit": ZERO, "credit": rc.total, "currency": rc.currency})
    entries.sort(key=lambda e: (e["date"], e["kind"] != "INVOICE", e["ref"]))
    opening = ZERO
    rows, bal = [], ZERO
    for e in entries:
        if e["date"] > to:
            continue
        if date_from and e["date"] < date_from:
            opening += e["debit"] - e["credit"]
            continue
        bal += e["debit"] - e["credit"]
        rows.append({**e, "debit": _s(_q2(e["debit"])) if e["debit"] else None,
                     "credit": _s(_q2(e["credit"])) if e["credit"] else None,
                     "balance": _s(_q2(opening + bal))})
    return {"customer": customer.id, "customer_name": customer.name,
            "date_from": date_from, "date_to": to, "opening": _s(_q2(opening)),
            "rows": rows, "closing": _s(_q2(opening + bal))}


def statement_context(customer, date_from, date_to):
    from .pdf import company_info, logo_src
    st = statement(customer, date_from, date_to)
    return {"logo_src": logo_src(), "co": company_info(), "st": st,
            "customer": _customer_block(customer)}
