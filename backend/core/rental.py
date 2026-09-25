"""Rental agreements and the daily register (MARINE_BUILD_BRIEF.md §4,
phase 4). An agreement puts vehicles on hire with a customer at agreed
daily rates; the register records each vehicle's day under it and the
customer's representative approves the days; phase 5 bills the approved
days."""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .audit import audit
from .models import (Customer, Employee, HireLog, RentalAgreement,
                     RentalAgreementVehicle, Vehicle)
from .numbering import next_trading_ref

ENTITY = "rental_agreement"
ZERO = Decimal("0")

STANDARD_TERMS = {
    "payment_terms": ("rental_terms_payment",
                      "Invoiced monthly in arrears on the approved daily register; "
                      "payment within 30 days of invoice"),
    "extra_terms": ("rental_terms_extra",
                    "Rates are per calendar day on hire, including standby days at the customer's site.\n"
                    "Breakdown days are not charged; the company replaces or repairs at its own cost.\n"
                    "The customer provides safe access, a level standing area and site security.\n"
                    "Fuel is the customer's unless the rate card says otherwise.\n"
                    "The daily register is approved by the customer's representative at the site."),
    "deposit_note": ("rental_terms_deposit", ""),
}


def _param(key, default):
    from .models import CompanyParameter
    try:
        return CompanyParameter.objects.get(key=key).value
    except CompanyParameter.DoesNotExist:
        return default


def standard_terms():
    return {k: _param(key, default) for k, (key, default) in STANDARD_TERMS.items()}


def set_standard_terms(data, actor):
    from . import fleet
    from .models import CompanyParameter
    if not fleet.can_set_rates(actor):
        return "Only the Rental Manager sets the standard terms."
    for k, (key, _) in STANDARD_TERMS.items():
        if k in data:
            CompanyParameter.objects.update_or_create(
                key=key, defaults={"value": (data[k] or "").strip(),
                                   "description": f"Rental agreement standard line — {k}"})
    audit(ENTITY, 0, "RENTAL_TERMS_SET", actor=actor, detail={"fields": [k for k in data if k in STANDARD_TERMS]})
    return None


def _dec(v, default=None):
    if v in (None, ""):
        return default
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return "bad"


def _date(v):
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        return "bad"


# ---- agreements -------------------------------------------------------------------

HEADER = ("title", "site_location", "customer_rep", "customer_rep_phone", "customer_po",
          "payment_terms", "extra_terms", "notes", "billing_cycle", "currency")


def _apply(a, data, errors):
    for k in HEADER:
        if k not in data:
            continue
        v = (data.get(k) or "").strip() if isinstance(data.get(k), str) else (data.get(k) or "")
        if k == "billing_cycle" and v not in RentalAgreement.Cycle.values:
            errors[k] = "Unknown billing cycle."
            continue
        if k == "currency":
            v = (v or "MVR").upper()
            if v not in ("MVR", "USD"):
                errors[k] = "MVR or USD."
                continue
        setattr(a, k, v)
    for k in ("start_date", "end_date"):
        if k in data:
            d = _date(data[k])
            if d == "bad":
                errors[k] = "Enter a valid date."
            else:
                setattr(a, k, d)
    if a.start_date and a.end_date and a.end_date < a.start_date:
        errors["end_date"] = "The end is before the start."
    for k in ("deposit", "mobilisation_charge", "demobilisation_charge"):
        if k in data:
            d = _dec(data[k], ZERO)
            if d == "bad" or d < 0:
                errors[k] = "Enter a valid amount."
            else:
                setattr(a, k, d)


def create_agreement(data, actor):
    customer = Customer.objects.filter(id=data.get("customer"), is_active=True).first()
    if customer is None:
        return None, {"customer": "Pick the customer."}
    st = standard_terms()
    a = RentalAgreement(customer=customer, created_by=actor,
                        currency=customer.default_currency or "MVR",
                        payment_terms=st["payment_terms"], extra_terms=st["extra_terms"])
    errors = {}
    _apply(a, data, errors)
    if errors:
        return None, errors
    with transaction.atomic():
        a.ref = next_trading_ref("RA")
        a.save()
    audit(ENTITY, a.id, "RA_CREATED", actor=actor, detail={"ref": a.ref, "customer": customer.name})
    return a, None


def update_agreement(a, data, actor):
    if a.status in ("COMPLETED", "TERMINATED"):
        return {"detail": "This agreement is closed."}
    if a.status == "ACTIVE":
        allowed = {"customer_rep", "customer_rep_phone", "customer_po", "notes", "end_date", "site_location"}
        if set(data) - allowed:
            return {"detail": "An active agreement only changes its representative, PO, "
                              "location, end date and notes — terminate it to re-let."}
    errors = {}
    _apply(a, data, errors)
    if errors:
        return errors
    a.save()
    audit(ENTITY, a.id, "RA_UPDATED", actor=actor, detail={"ref": a.ref, "fields": sorted(data)})
    return None


def set_vehicles(a, rows, actor):
    """Replace the vehicle lines of a draft; an active agreement adds lines
    but never loses one that has register days."""
    if a.status in ("COMPLETED", "TERMINATED"):
        return "This agreement is closed."
    clean, seen = [], set()
    for r in rows or []:
        v = Vehicle.objects.filter(id=r.get("vehicle"), is_active=True).exclude(status="DISPOSED").first()
        if v is None:
            return "A line names a vehicle that is not on the fleet."
        if v.id in seen:
            return f"{v.reg_no} is listed twice."
        seen.add(v.id)
        rate = _dec(r.get("rate_daily"), v.rate_daily)
        if rate in ("bad", None) or rate <= 0:
            return f"{v.reg_no}: enter the agreed daily rate."
        op_inc = bool(r.get("operator_included", v.operator_included))
        op_rate = _dec(r.get("operator_rate_daily"), v.operator_rate_daily)
        if op_rate == "bad":
            return f"{v.reg_no}: enter a valid operator rate."
        fd, td = _date(r.get("from_date")), _date(r.get("to_date"))
        if "bad" in (fd, td):
            return f"{v.reg_no}: enter valid dates."
        clean.append((v, {"rate_daily": rate, "operator_included": op_inc,
                          "operator_rate_daily": None if op_inc else op_rate,
                          "from_date": fd, "to_date": td, "notes": r.get("notes") or ""}))
    if not clean:
        return "Put at least one vehicle on the agreement."
    with transaction.atomic():
        existing = {ln.vehicle_id: ln for ln in a.vehicles.select_for_update()}
        keep = set()
        for v, fields in clean:
            ln = existing.get(v.id) or RentalAgreementVehicle(agreement=a, vehicle=v)
            for k, val in fields.items():
                setattr(ln, k, val)
            ln.save()
            keep.add(v.id)
        for vid, ln in existing.items():
            if vid not in keep:
                if ln.register.exists():
                    return f"{ln.vehicle.reg_no} has register days — it stays on the agreement."
                ln.delete()
                if a.status == "ACTIVE":
                    _release_vehicle(ln.vehicle)
        if a.status == "ACTIVE":
            for v, _ in clean:
                _put_on_hire(v)
    audit(ENTITY, a.id, "RA_VEHICLES", actor=actor,
          detail={"ref": a.ref, "vehicles": [v.reg_no for v, _ in clean]})
    return None


def _put_on_hire(v):
    if v.status == "AVAILABLE":
        v.status = "ON_HIRE"
        v.save(update_fields=["status", "updated_at"])


def _release_vehicle(v):
    still = RentalAgreementVehicle.objects.filter(vehicle=v, agreement__status="ACTIVE").exists()
    if not still and v.status == "ON_HIRE":
        v.status = "AVAILABLE"
        v.save(update_fields=["status", "updated_at"])


def activate(a, actor):
    from . import fleet
    if not fleet.can_set_rates(actor):
        return "Only the Rental Manager activates an agreement."
    if a.status != "DRAFT":
        return "Only a draft agreement is activated."
    if not a.start_date:
        return "Enter the start date."
    if not a.customer_rep.strip():
        return "Name the customer's representative who approves the daily register."
    if not a.vehicles.exists():
        return "Put at least one vehicle on the agreement."
    with transaction.atomic():
        a.status = "ACTIVE"
        a.activated_by = actor
        a.activated_at = timezone.now()
        a.save()
        for ln in a.vehicles.select_related("vehicle"):
            _put_on_hire(ln.vehicle)
        _store_pdf(a)
    audit(ENTITY, a.id, "RA_ACTIVATED", actor=actor,
          detail={"ref": a.ref, "vehicles": a.vehicles.count(), "start": str(a.start_date)})
    return None


def close(a, how, reason, actor):
    from . import fleet
    if not fleet.can_set_rates(actor):
        return "Only the Rental Manager closes an agreement."
    if a.status != "ACTIVE":
        return "Only an active agreement is closed."
    if how not in ("COMPLETED", "TERMINATED"):
        return "Unknown close."
    if how == "TERMINATED" and not (reason or "").strip():
        return "Say why the agreement is terminated."
    unapproved = a.register.filter(approved=False, state__in=HireLog.BILLABLE).count()
    with transaction.atomic():
        a.status = how
        a.closed_at = timezone.now()
        a.close_reason = (reason or "").strip()
        if not a.end_date or a.end_date > timezone.localdate():
            a.end_date = timezone.localdate()
        a.save()
        for ln in a.vehicles.select_related("vehicle"):
            _release_vehicle(ln.vehicle)
    audit(ENTITY, a.id, f"RA_{how}", actor=actor,
          detail={"ref": a.ref, "reason": a.close_reason, "unapproved_days": unapproved})
    return None


def attach_signed(a, upload, actor):
    if upload is None:
        return "Attach the signed copy."
    a.signed_copy = upload
    a.save(update_fields=["signed_copy"])
    audit(ENTITY, a.id, "RA_SIGNED", actor=actor, detail={"ref": a.ref})
    return None


# ---- PDF ---------------------------------------------------------------------------------

def _money(v):
    from .pdf import _money as m
    return m(v)


def agreement_context(a, draft=False):
    from .pdf import company_info, logo_src
    c = a.customer
    rows = []
    for ln in a.vehicles.select_related("vehicle"):
        v = ln.vehicle
        rows.append({"vehicle": f"{v.fleet_no + ' · ' if v.fleet_no else ''}{v.reg_no}",
                     "desc": f"{v.vehicle_class}{' · ' + v.make if v.make else ''}"
                             f"{' ' + v.model if v.model else ''}{' · ' + v.capacity if v.capacity else ''}",
                     "rate_f": _money(ln.rate_daily),
                     "operator": ("included" if ln.operator_included
                                  else f"{_money(ln.operator_rate_daily or 0)} / day"),
                     "period": (f"{ln.from_date:%d %b %Y}" if ln.from_date else "") +
                               (f" – {ln.to_date:%d %b %Y}" if ln.to_date else "")})
    return {
        "logo_src": logo_src(), "co": company_info(), "a": a, "draft": draft,
        "customer": {"name": c.name, "address": c.billing_address, "tin": c.tin,
                     "contact": c.contact_person, "phone": c.phone},
        "rows": rows, "currency": a.currency,
        "deposit_f": _money(a.deposit) if a.deposit else None,
        "mob_f": _money(a.mobilisation_charge) if a.mobilisation_charge else None,
        "demob_f": _money(a.demobilisation_charge) if a.demobilisation_charge else None,
        "extra": [t.strip() for t in (a.extra_terms or "").splitlines() if t.strip()],
        "signer": ({"name": a.activated_by.full_name} if a.activated_by_id else None),
        "date": a.activated_at or a.created_at,
    }


def agreement_pdf_bytes(a, draft=False):
    from .views_commercial import pdf_bytes
    return pdf_bytes("pdf/rental_agreement.html", agreement_context(a, draft))


def _store_pdf(a):
    from django.conf import settings
    from django.core.files.base import ContentFile
    try:
        pdf = agreement_pdf_bytes(a)
    except Exception:                                 # pragma: no cover - env dep
        if settings.PDF_REQUIRED:
            raise
        return
    a.pdf.save(f"{a.ref}.pdf", ContentFile(pdf), save=True)


# ---- the daily register ----------------------------------------------------------

def _line_days(ln, d_from, d_to):
    a = ln.agreement
    lo = max(filter(None, [d_from, ln.from_date, a.start_date]))
    hi_c = [d for d in (d_to, ln.to_date, a.end_date) if d]
    hi = min(hi_c) if hi_c else d_to
    return lo, hi


def register(a, d_from, d_to):
    """The grid: each vehicle on the agreement × each day in the window,
    with the line already recorded, if any."""
    lines = list(a.vehicles.select_related("vehicle"))
    logs = {(h.line_id, h.date): h for h in
            a.register.filter(date__gte=d_from, date__lte=d_to).select_related("operator")}
    days = [d_from + timedelta(days=i) for i in range((d_to - d_from).days + 1)]
    out = []
    for ln in lines:
        lo, hi = _line_days(ln, d_from, d_to)
        cells = []
        for d in days:
            h = logs.get((ln.id, d))
            cells.append({"date": d, "in_period": lo <= d <= hi,
                          **({"state": h.state, "hours": str(h.hours) if h.hours is not None else "",
                              "operator": h.operator_id, "remarks": h.remarks,
                              "approved": h.approved, "approved_by": h.approved_by,
                              "invoiced": h.invoice.ref if h.invoice_id else None} if h else
                             {"state": "", "hours": "", "operator": None, "remarks": "",
                              "approved": False, "approved_by": "", "invoiced": None})})
        billable = sum(1 for c in cells if c["state"] in HireLog.BILLABLE)
        approved = sum(1 for c in cells if c["state"] in HireLog.BILLABLE and c["approved"])
        out.append({"line": ln.id, "vehicle": ln.vehicle_id, "reg_no": ln.vehicle.reg_no,
                    "fleet_no": ln.vehicle.fleet_no, "vehicle_class": ln.vehicle.vehicle_class,
                    "rate_daily": str(ln.rate_daily),
                    "default_operator": ln.vehicle.default_operator_id,
                    "cells": cells, "billable_days": billable, "approved_days": approved})
    return {"agreement": a.id, "ref": a.ref, "from": d_from, "to": d_to,
            "days": days, "lines": out,
            "operators": [{"id": e.id, "full_name": e.full_name}
                          for e in Employee.objects.filter(is_active=True).order_by("full_name")[:300]]}


def save_register(a, rows, actor):
    """Bulk upsert of register lines: {line, date, state, hours, operator,
    remarks}. An approved day never changes here; an empty state clears an
    unapproved day."""
    if a.status != "ACTIVE":
        return "The register runs under an active agreement."
    lines = {ln.id: ln for ln in a.vehicles.all()}
    n = 0
    with transaction.atomic():
        for r in rows or []:
            ln = lines.get(r.get("line"))
            d = _date(r.get("date"))
            if ln is None or d in (None, "bad"):
                return "A register line is not on this agreement."
            lo, hi = _line_days(ln, d, d)
            state = (r.get("state") or "").strip()
            existing = HireLog.objects.filter(line=ln, date=d).first()
            if existing and (existing.approved or existing.invoice_id):
                continue                                     # locked by approval / invoice
            if not state:
                if existing:
                    existing.delete()
                    n += 1
                continue
            if state not in HireLog.State.values:
                return f"Unknown state for {ln.vehicle.reg_no} on {d}."
            if not (lo <= d <= hi):
                return f"{ln.vehicle.reg_no}: {d:%d %b} is outside its hire period."
            hours = _dec(r.get("hours"))
            if hours == "bad" or (hours is not None and (hours < 0 or hours > 24)):
                return f"{ln.vehicle.reg_no}: enter the hours as a number up to 24."
            op = None
            if r.get("operator"):
                op = Employee.objects.filter(id=r["operator"], is_active=True).first()
            h = existing or HireLog(line=ln, agreement=a, date=d, entered_by=actor)
            h.state, h.hours, h.operator = state, hours, op or (ln.vehicle.default_operator if not existing else h.operator)
            h.remarks = (r.get("remarks") or "").strip()
            h.entered_by = actor
            h.save()
            n += 1
    audit(ENTITY, a.id, "REGISTER_SAVED", actor=actor, detail={"ref": a.ref, "days": n})
    return None


def approve_register(a, d_from, d_to, approved_by, via, upload, actor):
    """The customer's representative approves the register for a window:
    in the app (their client user, or the Rental user recording the rep's
    sign-off) or on paper with the signed sheet attached."""
    approved_by = (approved_by or a.customer_rep or "").strip()
    if not approved_by:
        return None, "Name who approved the register."
    via = "PAPER" if upload is not None or via == "PAPER" else "APP"
    qs = a.register.filter(date__gte=d_from, date__lte=d_to, approved=False)
    n = 0
    now = timezone.now()
    with transaction.atomic():
        for h in qs.select_for_update():
            h.approved, h.approved_by, h.approved_at, h.approved_via = True, approved_by, now, via
            if upload is not None and n == 0:
                h.signed_register = upload
            h.save(update_fields=["approved", "approved_by", "approved_at", "approved_via",
                                  "signed_register"])
            n += 1
    audit(ENTITY, a.id, "REGISTER_APPROVED", actor=actor,
          detail={"ref": a.ref, "from": str(d_from), "to": str(d_to), "days": n,
                  "by": approved_by, "via": via})
    return n, None


def unapprove_register(a, d_from, d_to, actor):
    from . import fleet
    if not fleet.can_set_rates(actor):
        return None, "Only the Rental Manager reopens approved days."
    qs = a.register.filter(date__gte=d_from, date__lte=d_to, approved=True, invoice__isnull=True)
    n = qs.update(approved=False, approved_by="", approved_at=None, approved_via="")
    audit(ENTITY, a.id, "REGISTER_REOPENED", actor=actor,
          detail={"ref": a.ref, "from": str(d_from), "to": str(d_to), "days": n})
    return n, None


# ---- serialisation ---------------------------------------------------------------

def _s(v):
    return None if v is None else str(v)


def line_dict(ln):
    v = ln.vehicle
    return {"id": ln.id, "vehicle": v.id, "reg_no": v.reg_no, "fleet_no": v.fleet_no,
            "vehicle_class": v.vehicle_class, "make": v.make, "model": v.model,
            "card_rate": _s(v.rate_daily), "rate_daily": _s(ln.rate_daily),
            "operator_included": ln.operator_included,
            "operator_rate_daily": _s(ln.operator_rate_daily),
            "from_date": ln.from_date, "to_date": ln.to_date, "notes": ln.notes,
            "register_days": ln.register.count()}


def agreement_dict(a, user=None, full=False):
    from . import fleet
    out = {"id": a.id, "ref": a.ref, "status": a.status, "customer": a.customer_id,
           "customer_name": a.customer.name, "title": a.title,
           "start_date": a.start_date, "end_date": a.end_date,
           "billing_cycle": a.billing_cycle, "currency": a.currency,
           "site_location": a.site_location, "customer_rep": a.customer_rep,
           "n_vehicles": a.vehicles.count(),
           "unapproved_days": a.register.filter(approved=False, state__in=HireLog.BILLABLE).count(),
           "has_pdf": bool(a.pdf), "signed": bool(a.signed_copy)}
    if full:
        out.update({
            "customer_rep_phone": a.customer_rep_phone, "customer_po": a.customer_po,
            "deposit": _s(a.deposit), "mobilisation_charge": _s(a.mobilisation_charge),
            "demobilisation_charge": _s(a.demobilisation_charge),
            "payment_terms": a.payment_terms, "extra_terms": a.extra_terms, "notes": a.notes,
            "signed_copy": a.signed_copy.url if a.signed_copy else None,
            "activated_at": a.activated_at,
            "activated_by": a.activated_by.full_name if a.activated_by_id else None,
            "closed_at": a.closed_at, "close_reason": a.close_reason,
            "vehicles": [line_dict(ln) for ln in a.vehicles.select_related("vehicle")],
            "can_write": fleet.can_write(user) if user else False,
            "can_manage": fleet.can_set_rates(user) if user else False,
        })
    return out
