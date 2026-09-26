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


# The long-form hire agreement's standard clauses. Company parameter
# `rental_clauses` overrides them; every agreement takes a copy the user
# edits — strike what does not apply, add what the job needs.
STANDARD_CLAUSES = [
    {"heading": "Definitions",
     "text": "\"Owner\" is the company named above; \"Hirer\" is the customer named above; \"Equipment\" is each vehicle or machine listed in the schedule with its attachments and, where stated, its operator; \"Hire Period\" runs from the start date to the end date, or until off-hire is given under these clauses; \"Register\" is the daily hire register kept at the site; \"Rates\" are the daily rates in the schedule."},
    {"heading": "Hire period",
     "text": "The Hire Period begins on the start date whether or not the Hirer puts the Equipment to work. An open-ended hire continues until either party gives seven days' written notice of off-hire. Equipment is on hire, and chargeable, on every calendar day of the Hire Period other than a breakdown day or an off-hire day recorded in the Register."},
    {"heading": "Rates and what they cover",
     "text": "The Rates are per calendar day on hire, for a working day of up to ten hours. Standby days at the Hirer's site are charged at the full daily rate. Where the schedule says the operator is included, the operator's wages, accommodation and meals are the Owner's; otherwise the operator is charged at the operator rate per day. Fuel, lubricants and consumables are the Hirer's unless the schedule says the rate is with fuel. Rates exclude GST, which is charged at the prevailing rate."},
    {"heading": "The daily register",
     "text": "The Owner's operator records each day's status and hours in the Register. The Hirer's representative named in this agreement approves the Register at the site, in the Owner's application or by signing the paper register, at least weekly. Approved days are final and are invoiced at the Rates. A day not disputed in writing within seven days of the entry is taken as approved."},
    {"heading": "Mobilisation and demobilisation",
     "text": "The mobilisation and demobilisation charges in the schedule cover transport of the Equipment to and from the Hirer's site by the agreed means. The Hirer provides a safe landing, a level standing area, access and any permits the site requires. Delay at the site caused by the Hirer's failure to provide these is a standby day."},
    {"heading": "Hirer's obligations",
     "text": "The Hirer shall use the Equipment only for the purpose stated, within its rated capacity and on ground fit for it; provide site security and secure storage overnight; not move the Equipment from the site, sub-hire it or let any person other than the Owner's operator drive or operate it; keep the Equipment accessible for inspection and servicing; and comply with all laws and site safety rules."},
    {"heading": "Maintenance and breakdown",
     "text": "The Owner maintains the Equipment in working order and carries out scheduled servicing, arranging it around the Hirer's programme where practicable. A breakdown not caused by the Hirer is not charged from the time it is reported until the Equipment is working again; the Owner will repair or replace with equivalent Equipment as soon as practicable. A breakdown or damage caused by the Hirer's misuse, overloading, unsafe ground or want of care is the Hirer's cost, and standby is charged while it is repaired."},
    {"heading": "Damage, loss and return",
     "text": "Risk in the Equipment passes to the Hirer on delivery to the site and returns to the Owner on off-hire. The Hirer is liable for loss of, or damage to, the Equipment at the site beyond fair wear and tear, up to its replacement value, and for the Rates while it is out of service for repair. The Equipment is returned clean and in the condition delivered."},
    {"heading": "Insurance",
     "text": "The Owner insures the Equipment for third-party liability as required by law. The Hirer insures its own works, materials and personnel, and indemnifies the Owner against claims arising from the Hirer's use of the Equipment or the condition of the site, except to the extent caused by the Owner's negligence."},
    {"heading": "Safety and compliance",
     "text": "The Owner's operator works under the Hirer's site supervision but may refuse any instruction that is unsafe or outside the Equipment's capacity. The Hirer provides the site induction, personal protective equipment for the operator where the site requires it, and a competent banksman for lifting and reversing operations. Either party may stop work where there is a danger to persons or property."},
    {"heading": "Invoicing and payment",
     "text": "Invoices are raised from the approved Register under the billing cycle in this agreement, plus mobilisation, demobilisation and any agreed charges. Payment is due within the credit period stated, without set-off. The security deposit, if any, is held against damage and unpaid charges and returned within fourteen days of off-hire less any amounts due. The Owner may suspend the hire or take the Equipment off hire where an invoice is more than fourteen days overdue, with standby charged until it is settled."},
    {"heading": "Termination",
     "text": "Either party may terminate on seven days' written notice. The Owner may terminate immediately if the Hirer breaches these clauses and does not remedy the breach within three days of notice, becomes insolvent, or uses the Equipment unlawfully or unsafely. On termination the Hirer pays for the days on hire, the demobilisation charge and any damage."},
    {"heading": "Force majeure",
     "text": "Neither party is liable for delay or failure caused by events beyond its reasonable control, including severe weather, sea conditions preventing transport, government action or epidemic. Equipment stranded at the site by such an event is on standby at half the daily rate until it can be moved."},
    {"heading": "Governing law and disputes",
     "text": "This agreement is governed by the laws of the Republic of Maldives. The parties first try to settle any dispute by discussion between their managers within fourteen days; failing that, either party may refer it to the courts of the Maldives."},
    {"heading": "Entire agreement",
     "text": "This agreement, its schedule and the approved Register are the whole agreement between the parties for this hire and replace any earlier quotation or correspondence. A change is binding only if made in writing and signed by both parties."},
]


def standard_clauses():
    v = _param("rental_clauses", None)
    return [dict(c) for c in v] if isinstance(v, list) and v else [dict(c) for c in STANDARD_CLAUSES]


def clean_clauses(rows):
    """[{heading, text}] with blanks dropped; None if the shape is wrong."""
    if not isinstance(rows, list):
        return None
    out = []
    for r in rows:
        if not isinstance(r, dict):
            return None
        h, t = (r.get("heading") or "").strip(), (r.get("text") or "").strip()
        if not h and not t:
            continue
        if not h or not t:
            return None
        out.append({"heading": h[:80], "text": t})
    return out


def _param(key, default):
    from .models import CompanyParameter
    try:
        return CompanyParameter.objects.get(key=key).value
    except CompanyParameter.DoesNotExist:
        return default


def standard_terms():
    return {**{k: _param(key, default) for k, (key, default) in STANDARD_TERMS.items()},
            "clauses": standard_clauses()}


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
    if "clauses" in data:
        rows = clean_clauses(data["clauses"])
        if rows is None:
            return "Each clause needs a heading and its text."
        CompanyParameter.objects.update_or_create(
            key="rental_clauses", defaults={"value": rows,
                                            "description": "Rental agreement — standard clauses"})
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
    if "clauses" in data:
        rows = clean_clauses(data["clauses"])
        if rows is None:
            errors["clauses"] = "Each clause needs a heading and its text."
        else:
            a.clauses = rows


def create_agreement(data, actor):
    customer = Customer.objects.filter(id=data.get("customer"), is_active=True).first()
    if customer is None:
        return None, {"customer": "Pick the customer."}
    st = standard_terms()
    a = RentalAgreement(customer=customer, created_by=actor,
                        currency=customer.default_currency or "MVR",
                        payment_terms=st["payment_terms"], extra_terms=st["extra_terms"],
                        clauses=st["clauses"])
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
        "customer": customer_info(c),
        "rows": rows, "currency": a.currency,
        "deposit_f": _money(a.deposit) if a.deposit else None,
        "mob_f": _money(a.mobilisation_charge) if a.mobilisation_charge else None,
        "demob_f": _money(a.demobilisation_charge) if a.demobilisation_charge else None,
        "extra": [t.strip() for t in (a.extra_terms or "").splitlines() if t.strip()],
        "clauses": a.clauses or [],
        "signer": ({"name": a.activated_by.full_name} if a.activated_by_id else None),
        "date": a.activated_at or a.created_at,
    }


CLIENT_FIELDS = (("name", "client_name"), ("billing_address", "client_address"),
                 ("tin", "client_tin"), ("contact_person", "client_contact"),
                 ("phone", "client_phone"), ("email", "client_email"))


def customer_from_client(site, actor):
    """The customer record for a project client — the one already linked to
    the site, or a new one taken from the site's client block. Nothing is
    typed twice: the block on the site stays the source and the customer
    follows it (sync_client_customers)."""
    c = Customer.objects.filter(project_client=site, is_active=True).first()
    if c is not None:
        return c, False
    if not (site.client_name or "").strip():
        return None, "That site has no client on record yet — enter the client on the site first."
    c = Customer(project_client=site, created_by=actor, default_currency="MVR")
    for cf, sf in CLIENT_FIELDS:
        setattr(c, cf, getattr(site, sf) or "")
    c.save()
    audit(ENTITY, 0, "CUSTOMER_FROM_CLIENT", actor=actor,
          detail={"site": site.code, "customer": c.id, "name": c.name})
    return c, True


def sync_client_customers(site):
    """Called when a site is saved: customers that are this site's client
    take its client block (name, address, TIN, contact, phone, email)."""
    for c in Customer.objects.filter(project_client=site):
        changed = []
        for cf, sf in CLIENT_FIELDS:
            v = getattr(site, sf) or ""
            if getattr(c, cf) != v:
                setattr(c, cf, v)
                changed.append(cf)
        if changed:
            c.save(update_fields=changed + ["updated_at"])


def customer_info(c):
    """Everything the agreement and its invoices need to know about the
    hirer — the customer record in full, plus which project site they are
    the client of, if any."""
    return {"id": c.id, "name": c.name, "address": c.billing_address, "tin": c.tin,
            "reg_no": c.business_reg_no, "contact": c.contact_person, "phone": c.phone,
            "email": c.email, "island": c.island, "credit_days": c.credit_days,
            "gst_exempt": c.gst_exempt, "currency": c.default_currency,
            "project_client": ({"site": c.project_client_id, "code": c.project_client.code,
                                "name": c.project_client.name}
                               if c.project_client_id else None)}


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
            "customer_info": customer_info(a.customer),
            "customer_rep_phone": a.customer_rep_phone, "customer_po": a.customer_po,
            "deposit": _s(a.deposit), "mobilisation_charge": _s(a.mobilisation_charge),
            "demobilisation_charge": _s(a.demobilisation_charge),
            "payment_terms": a.payment_terms, "extra_terms": a.extra_terms, "notes": a.notes,
            "clauses": a.clauses or [],
            "signed_copy": a.signed_copy.url if a.signed_copy else None,
            "activated_at": a.activated_at,
            "activated_by": a.activated_by.full_name if a.activated_by_id else None,
            "closed_at": a.closed_at, "close_reason": a.close_reason,
            "vehicles": [line_dict(ln) for ln in a.vehicles.select_related("vehicle")],
            "can_write": fleet.can_write(user) if user else False,
            "can_manage": fleet.can_set_rates(user) if user else False,
        })
    return out


# ================================================================================
# Phase 5: invoicing the approved days, and the money that comes in
# ================================================================================

from decimal import ROUND_HALF_UP  # noqa: E402

from django.db.models import Sum  # noqa: E402

from .models import (CompanyBankAccount, RentalInvoice, RentalReceipt,  # noqa: E402
                     RentalReceiptLine)

_CENT = Decimal("0.01")
MONEY_ROLES = ("FINANCE", "ADMIN", "DIRECTOR")


def _q2(v):
    return Decimal(str(v or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)


def can_receipt(user):
    """Finance is the money desk; Admin covers for it."""
    return user.is_authenticated and user.has_any(MONEY_ROLES)


def gst_rate():
    from .trading import gst_rate as g
    return g()


def _ho():
    from .vouchers import ho_site
    return ho_site()


def _post(head_code, amount, currency, actor, vehicle=None):
    from . import costing
    head = costing.by_code(head_code)
    if head is None:
        raise ValueError(f"Cost head {head_code} is missing — ask Finance.")
    p = costing.post(site=_ho(), cost_head=head, state="INCURRED", source="SALE",
                     amount=amount, currency=currency, actor=actor, book="RENTAL",
                     vehicle=vehicle)
    return p.id


def _reverse_postings(ids, actor):
    from .trading import _reverse_postings as rev
    return rev(ids, actor)


def _customer_block(c):
    return {"name": c.name, "address": c.billing_address, "tin": c.tin,
            "contact": c.contact_person, "island": c.island}


# ---- what is billable -----------------------------------------------------------

def unbilled_days(a, d_from, d_to):
    return (a.register.filter(date__gte=d_from, date__lte=d_to, approved=True,
                              state__in=HireLog.BILLABLE, invoice__isnull=True)
            .select_related("line__vehicle").order_by("line_id", "date"))


def charge_billed(a, kind):
    return any(c.get("kind") == kind
               for inv in a.invoices.filter(status__in=("DRAFT", "ISSUED", "PAID"))
               for c in inv.charges)


def _rows(a, days):
    """One row per vehicle: billable days × the agreed rate, and the operator
    days at the operator rate when the operator is priced separately."""
    by_line = {}
    for h in days:
        by_line.setdefault(h.line_id, []).append(h)
    rows = []
    for ln in a.vehicles.select_related("vehicle"):
        hs = by_line.get(ln.id)
        if not hs:
            continue
        v = ln.vehicle
        n = len(hs)
        amount = _q2(ln.rate_daily * n)
        rows.append({"line": ln.id, "vehicle": v.id, "reg_no": v.reg_no, "fleet_no": v.fleet_no,
                     "description": f"{v.vehicle_class}{' · ' + v.make if v.make else ''}"
                                    f"{' ' + v.model if v.model else ''}",
                     "from": str(hs[0].date), "to": str(hs[-1].date),
                     "worked": sum(1 for h in hs if h.state == "WORKED"),
                     "standby": sum(1 for h in hs if h.state == "STANDBY"),
                     "days": n, "rate": str(ln.rate_daily), "amount": str(amount),
                     "operator_days": n if (not ln.operator_included and ln.operator_rate_daily) else 0,
                     "operator_rate": str(ln.operator_rate_daily or 0),
                     "operator_amount": str(_q2((ln.operator_rate_daily or 0) * n))
                     if not ln.operator_included and ln.operator_rate_daily else "0"})
    return rows


def invoice_preview(a, d_from, d_to):
    days = list(unbilled_days(a, d_from, d_to))
    rows = _rows(a, days)
    sub = sum((Decimal(r["amount"]) + Decimal(r["operator_amount"]) for r in rows), ZERO)
    pending = a.register.filter(date__gte=d_from, date__lte=d_to, approved=False,
                                state__in=HireLog.BILLABLE).count()
    return {"from": d_from, "to": d_to, "rows": rows, "days": len(days),
            "subtotal": str(_q2(sub)), "unapproved_days": pending,
            "mobilisation": (str(a.mobilisation_charge)
                             if a.mobilisation_charge and not charge_billed(a, "MOB") else None),
            "demobilisation": (str(a.demobilisation_charge)
                               if a.demobilisation_charge and not charge_billed(a, "DEMOB") else None),
            "currency": a.currency}


def create_invoice(a, data, actor):
    from .commercial import _next_invoice_no
    if a.status == "DRAFT":
        return None, "Activate the agreement before invoicing."
    d_from, d_to = _date(data.get("from")), _date(data.get("to"))
    if d_from in (None, "bad") or d_to in (None, "bad") or d_to < d_from:
        return None, "Pick the period to invoice."
    try:
        inv_date = date.fromisoformat(str(data.get("invoice_date") or timezone.localdate()))
    except ValueError:
        return None, "Enter the invoice date."
    days = list(unbilled_days(a, d_from, d_to))
    charges = []
    if data.get("include_mobilisation") and a.mobilisation_charge and not charge_billed(a, "MOB"):
        charges.append({"kind": "MOB", "label": "Mobilisation to site",
                        "amount": str(_q2(a.mobilisation_charge))})
    if data.get("include_demobilisation") and a.demobilisation_charge and not charge_billed(a, "DEMOB"):
        charges.append({"kind": "DEMOB", "label": "Demobilisation from site",
                        "amount": str(_q2(a.demobilisation_charge))})
    for c in data.get("charges") or []:
        amt = _dec(c.get("amount"))
        label = (c.get("label") or "").strip()
        if amt in (None, "bad") or amt == 0 or not label:
            continue
        charges.append({"kind": "OTHER", "label": label, "amount": str(_q2(amt))})
    if not days and not charges:
        return None, ("No approved, unbilled days in that period — the customer's "
                      "representative approves the register first.")
    rows = _rows(a, days)
    sub = _q2(sum((Decimal(r["amount"]) + Decimal(r["operator_amount"]) for r in rows), ZERO)
              + sum((Decimal(c["amount"]) for c in charges), ZERO))
    gst_pct = ZERO if a.customer.gst_exempt else gst_rate()
    gst = _q2(sub * gst_pct / 100)
    due = inv_date + timedelta(days=a.customer.credit_days or 0)
    with transaction.atomic():
        inv = RentalInvoice.objects.create(
            agreement=a, customer=a.customer, ref=_next_invoice_no(), invoice_date=inv_date,
            due_date=due, period_from=d_from, period_to=d_to, currency=a.currency,
            charges=charges,
            snapshot={"customer": _customer_block(a.customer), "lines": rows,
                      "agreement": a.ref, "title": a.title, "site": a.site_location,
                      "po": a.customer_po},
            subtotal=sub, gst_percent=gst_pct, gst=gst, total=_q2(sub + gst),
            created_by=actor)
        HireLog.objects.filter(id__in=[h.id for h in days]).update(invoice=inv)
    audit(ENTITY, a.id, "RINV_CREATED", actor=actor,
          detail={"ref": a.ref, "invoice": inv.ref, "days": len(days), "total": str(inv.total)})
    return inv, None


def issue_invoice(inv, actor):
    from . import fleet
    if not fleet.can_set_rates(actor):
        return "Only the Rental Manager issues a tax invoice."
    if inv.status != "DRAFT":
        return "This invoice is not a draft."
    c = inv.customer
    if not c.tin and not c.gst_exempt:
        return ("The customer has no GST TIN on file — a tax invoice needs it. "
                "Add it on the customer, or mark them GST exempt.")
    with transaction.atomic():
        inv.status = "ISSUED"
        inv.issued_by = actor
        inv.issued_at = timezone.now()
        ids = []
        for r in inv.snapshot.get("lines", []):
            v = Vehicle.objects.filter(id=r["vehicle"]).first()
            amt = Decimal(r["amount"]) + Decimal(r["operator_amount"])
            if amt:
                ids.append(_post("RNT_REVENUE", amt, inv.currency, actor, vehicle=v))
        other = sum((Decimal(c["amount"]) for c in inv.charges), ZERO)
        if other:
            ids.append(_post("RNT_REVENUE", other, inv.currency, actor))
        if inv.gst:
            ids.append(_post("RNT_OUTPUT_GST", inv.gst, inv.currency, actor))
        inv.posting_ids = ids
        inv.save()
        _store_invoice_pdf(inv)
    audit(ENTITY, inv.agreement_id, "RINV_ISSUED", actor=actor,
          detail={"ref": inv.agreement.ref, "invoice": inv.ref, "total": str(inv.total)})
    return None


def void_invoice(inv, reason, actor):
    from . import fleet
    if not fleet.can_set_rates(actor):
        return "Only the Rental Manager voids an invoice."
    if inv.status == "VOID":
        return "Already void."
    if inv.receipts.exists():
        return "Money has been received against this invoice — it cannot be voided."
    reason = (reason or "").strip()
    if not reason:
        return "Say why the invoice is void."
    with transaction.atomic():
        if inv.status in ("ISSUED", "PAID"):
            inv.posting_ids = _reverse_postings(inv.posting_ids, actor)
        inv.status = "VOID"
        inv.void_reason = reason
        inv.save()
        inv.days.update(invoice=None)                # the days bill again
    audit(ENTITY, inv.agreement_id, "RINV_VOID", actor=actor,
          detail={"ref": inv.agreement.ref, "invoice": inv.ref, "reason": reason})
    return None


def invoice_received(inv):
    return _q2(inv.receipts.aggregate(s=Sum("amount"))["s"] or ZERO)


def invoice_outstanding(inv):
    if inv.status not in ("ISSUED", "PAID"):
        return ZERO
    return _q2(inv.total - invoice_received(inv))


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
    s = inv.snapshot
    signer = inv.issued_by
    rows = []
    for r in s.get("lines", []):
        rows.append({**r, "rate_f": _money(r["rate"]), "amount_f": _money(r["amount"]),
                     "period": f"{date.fromisoformat(r['from']):%d %b} – {date.fromisoformat(r['to']):%d %b %Y}",
                     "op_rate_f": _money(r["operator_rate"]),
                     "op_amount_f": _money(r["operator_amount"])})
    return {
        "logo_src": logo_src(), "co": company_info(), "inv": inv, "a": inv.agreement,
        "customer": s.get("customer", {}), "currency": inv.currency,
        "draft": draft and inv.status == "DRAFT", "void": inv.status == "VOID",
        "title": s.get("title", ""), "site": s.get("site", ""), "po": s.get("po", ""),
        "rows": rows,
        "charges": [{**c, "amount_f": _money(c["amount"])} for c in inv.charges],
        "subtotal_f": _money(inv.subtotal), "gst_pct": inv.gst_percent,
        "gst_f": _money(inv.gst), "total_f": _money(inv.total),
        "in_words": amount_in_words(inv.total, "USD" if inv.currency == "USD" else "Rufiyaa"),
        "signer": ({"name": signer.full_name,
                    "designation": "Rental Manager" if signer.role == "RENTAL_MANAGER"
                    else _param("company_signee_designation", "Managing Director")}
                   if signer else None),
    }


def invoice_pdf_bytes(inv):
    from .views_commercial import pdf_bytes
    return pdf_bytes("pdf/rental_tax_invoice.html", invoice_context(inv, draft=True))


def _store_invoice_pdf(inv):
    from django.conf import settings
    from django.core.files.base import ContentFile
    try:
        pdf = invoice_pdf_bytes(inv)
    except Exception:                                 # pragma: no cover - env dep
        if settings.PDF_REQUIRED:
            raise
        return
    inv.pdf.save(f"{inv.ref}.pdf", ContentFile(pdf), save=True)


def invoice_dict(inv):
    return {"id": inv.id, "ref": inv.ref, "status": inv.status,
            "agreement": inv.agreement_id, "agreement_ref": inv.agreement.ref,
            "customer": inv.customer_id, "customer_name": inv.customer.name,
            "invoice_date": inv.invoice_date, "due_date": inv.due_date,
            "period_from": inv.period_from, "period_to": inv.period_to,
            "currency": inv.currency, "subtotal": _s(inv.subtotal),
            "gst_percent": _s(inv.gst_percent), "gst": _s(inv.gst), "total": _s(inv.total),
            "charges": inv.charges, "lines": inv.snapshot.get("lines", []),
            "days": sum(r["days"] for r in inv.snapshot.get("lines", [])),
            "received": _s(invoice_received(inv)), "outstanding": _s(invoice_outstanding(inv)),
            "has_pdf": bool(inv.pdf), "void_reason": inv.void_reason,
            "issued_at": inv.issued_at,
            "issued_by": inv.issued_by.full_name if inv.issued_by_id else None}


# ---- receipts -----------------------------------------------------------------------

def open_invoices(customer):
    return [i for i in RentalInvoice.objects.filter(customer=customer, status__in=("ISSUED", "PAID"))
            .select_related("agreement").order_by("invoice_date", "id")
            if invoice_outstanding(i) > ZERO]


def auto_allocate(customer, amount):
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
    if method not in [c[0] for c in RentalReceipt._meta.get_field("method").choices]:
        return None, "Choose how the payment was received."
    bank = None
    if data.get("bank_account"):
        bank = CompanyBankAccount.objects.filter(id=data["bank_account"]).first()
        if bank is None:
            return None, "That bank account no longer exists."
    parsed, currency = [], None
    for row in data.get("allocations") or []:
        amt = _dec(row.get("amount"))
        if amt in (None, "bad") or amt <= ZERO:
            continue
        inv = RentalInvoice.objects.filter(id=row.get("invoice_id"), customer=customer,
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
        return None, "Allocate the money to at least one invoice."
    with transaction.atomic():
        rc = RentalReceipt.objects.create(
            customer=customer, receipt_no=next_receipt_no(), receipt_date=rdate,
            method=method, reference=(data.get("reference") or "").strip(),
            bank_account=bank, currency=currency, note=data.get("note") or "",
            recorded_by=actor)
        for inv, amt in parsed:
            RentalReceiptLine.objects.create(receipt=rc, invoice=inv, amount=amt)
        for inv, _ in parsed:
            _settle(inv)
    for inv, amt in parsed:
        audit(ENTITY, inv.agreement_id, "RECEIPT", actor=actor,
              detail={"ref": inv.agreement.ref, "invoice": inv.ref,
                      "receipt_no": rc.receipt_no, "amount": str(amt)})
    return rc, None


def delete_receipt(rc, actor):
    if not can_receipt(actor):
        return "Finance records customer receipts."
    lines = list(rc.lines.select_related("invoice"))
    no = rc.receipt_no
    with transaction.atomic():
        rc.lines.all().delete()
        rc.delete()
        for l in lines:
            _settle(l.invoice)
    for l in lines:
        audit(ENTITY, l.invoice.agreement_id, "RECEIPT_DELETED", actor=actor,
              detail={"receipt_no": no, "invoice": l.invoice.ref})
    return None


def receipt_dict(rc):
    ba = rc.bank_account
    lines = [{"id": l.id, "invoice_id": l.invoice_id, "invoice_no": l.invoice.ref,
              "claim_ref": l.invoice.agreement.ref, "project_code": l.invoice.agreement.ref,
              "amount": l.amount, "invoice_amount": l.invoice.total}
             for l in rc.lines.select_related("invoice__agreement")]
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


# ---- receivables ---------------------------------------------------------------------

def aging(as_of=None):
    from .trading import _bucket
    today = as_of or timezone.localdate()
    by_cust = {}
    for inv in RentalInvoice.objects.filter(status__in=("ISSUED", "PAID")) \
            .select_related("customer", "agreement"):
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
        row["invoices"].append({"id": inv.id, "ref": inv.ref, "agreement": inv.agreement.ref,
                                "agreement_id": inv.agreement_id,
                                "invoice_date": inv.invoice_date, "due_date": inv.due_date,
                                "total": _s(inv.total), "outstanding": _s(out),
                                "overdue_days": max(0, overdue), "currency": inv.currency})
    rows = sorted(by_cust.values(), key=lambda r: -r["total"])
    for r in rows:
        for k in ("current", "d30", "d60", "d90", "d90plus", "total"):
            r[k] = _s(_q2(r[k]))
    return {"as_of": today, "customers": rows,
            "total": _s(_q2(sum((Decimal(r["total"]) for r in rows), ZERO)))}


def statement(customer, date_from=None, date_to=None):
    to = date_to or timezone.localdate()
    entries = []
    for inv in RentalInvoice.objects.filter(customer=customer, status__in=("ISSUED", "PAID")) \
            .select_related("agreement"):
        entries.append({"date": inv.invoice_date, "kind": "INVOICE", "ref": inv.ref,
                        "detail": f"{inv.agreement.ref} · {inv.period_from:%d %b} – {inv.period_to:%d %b %Y}",
                        "debit": inv.total, "credit": ZERO, "currency": inv.currency})
    for rc in RentalReceipt.objects.filter(customer=customer).prefetch_related("lines__invoice"):
        settled = ", ".join(x.invoice.ref for x in rc.lines.all())
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
    return {"logo_src": logo_src(), "co": company_info(),
            "st": statement(customer, date_from, date_to),
            "customer": _customer_block(customer)}
