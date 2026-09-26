"""The heavy-vehicle rental fleet (MARINE_BUILD_BRIEF.md §4) — phase 3, the
foundations: the vehicle register with its rate card and cost centre, the
documents whose expiry the fleet is alerted on, and the fleet summary.
Behind the `rental` feature switch; the Rental roles run it."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.utils import timezone

from . import brand
from .audit import audit
from .models import Employee, User, Vehicle, VehicleDocument

ENTITY = "vehicle"
RATE_FIELDS = ("rate_hourly", "rate_daily", "rate_weekly", "rate_monthly",
               "operator_rate_daily", "purchase_cost", "hour_meter")
TEXT_FIELDS = ("reg_no", "fleet_no", "vehicle_class", "make", "model", "capacity",
               "engine_no", "chassis_no", "notes", "rate_currency", "fuel_basis",
               "status")


def enabled():
    return bool(brand.brand()["features"].get("rental"))


def can_read(user):
    return user.is_authenticated and user.has_any(User.FLEET_READERS)


# The Director (PD) has everything Admin has on the fleet (owner 2026-09-25).
FULL_ACCESS = ("ADMIN", "DIRECTOR")


def can_write(user):
    return user.is_authenticated and user.has_any(("RENTAL", "RENTAL_MANAGER", *FULL_ACCESS))


def can_set_rates(user):
    return user.is_authenticated and user.has_any(("RENTAL_MANAGER", *FULL_ACCESS))


def _dec(v):
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return "bad"
    return d


def _date(v):
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        return "bad"


def apply(vehicle, data, actor, rates_ok):
    """Write the register fields; rate-card money only for the manager."""
    errors = {}
    for k in TEXT_FIELDS:
        if k not in data:
            continue
        v = (data.get(k) or "").strip() if isinstance(data.get(k), str) else data.get(k)
        if k == "reg_no":
            if not v:
                errors[k] = "Enter the registration number."
                continue
            v = v.upper()
            if Vehicle.objects.filter(reg_no__iexact=v).exclude(pk=vehicle.pk).exists():
                errors[k] = "A vehicle with this registration is already on the fleet."
                continue
        if k == "vehicle_class" and not v:
            errors[k] = "Say what kind of vehicle it is."
            continue
        if k == "status" and v not in Vehicle.Status.values:
            errors[k] = "Unknown status."
            continue
        if k == "fuel_basis" and v not in Vehicle.FuelBasis.values:
            errors[k] = "Unknown fuel basis."
            continue
        if k == "rate_currency":
            v = (v or "MVR").upper()
            if v not in ("MVR", "USD"):
                errors[k] = "MVR or USD."
                continue
            if not rates_ok and vehicle.pk and v != vehicle.rate_currency:
                errors[k] = "Only the Rental Manager changes the rate card."
                continue
        setattr(vehicle, k, v or "")
    if "year" in data:
        try:
            vehicle.year = int(data["year"]) if data["year"] not in (None, "") else None
        except (TypeError, ValueError):
            errors["year"] = "Enter the year as a number."
    for k in ("purchase_date",):
        if k in data:
            d = _date(data[k])
            if d == "bad":
                errors[k] = "Enter a valid date."
            else:
                setattr(vehicle, k, d)
    for k in RATE_FIELDS:
        if k not in data:
            continue
        d = _dec(data[k])
        if d == "bad" or (d is not None and d < 0):
            errors[k] = "Enter a valid amount."
            continue
        if k.startswith("rate_") or k == "operator_rate_daily":
            # A first rate can be typed by whoever adds the vehicle; changing
            # one on the register is the manager's.
            if not rates_ok and vehicle.pk and getattr(vehicle, k) != d:
                errors[k] = "Only the Rental Manager changes the rate card."
                continue
        setattr(vehicle, k, d)
    for k in ("operator_included", "is_active"):
        if k in data:
            setattr(vehicle, k, bool(data[k]))
    if "minimum_charge_days" in data:
        try:
            vehicle.minimum_charge_days = max(1, int(data["minimum_charge_days"] or 1))
        except (TypeError, ValueError):
            errors["minimum_charge_days"] = "Enter the minimum charge in days."
    if "default_operator" in data:
        if data["default_operator"]:
            emp = Employee.objects.filter(id=data["default_operator"], is_active=True).first()
            if emp is None:
                errors["default_operator"] = "Pick an employee."
            else:
                vehicle.default_operator = emp
        else:
            vehicle.default_operator = None
    return errors


def create_vehicle(data, actor):
    v = Vehicle(created_by=actor)
    errors = apply(v, data, actor, rates_ok=can_set_rates(actor))
    if errors:
        return None, errors
    v.save()
    audit(ENTITY, v.id, "VEHICLE_ADDED", actor=actor,
          detail={"reg_no": v.reg_no, "class": v.vehicle_class})
    return v, None


def update_vehicle(v, data, actor):
    before = v.status
    errors = apply(v, data, actor, rates_ok=can_set_rates(actor))
    if errors:
        return errors
    v.save()
    audit(ENTITY, v.id, "VEHICLE_UPDATED", actor=actor,
          detail={"reg_no": v.reg_no, "fields": sorted(k for k in data),
                  **({"status": [before, v.status]} if before != v.status else {})})
    return None


# ---- documents ----------------------------------------------------------------

def add_document(v, data, upload, actor):
    kind = data.get("kind")
    if kind not in VehicleDocument.Kind.values:
        return None, "Pick the document type."
    issued, expires = _date(data.get("issued_on")), _date(data.get("expires_on"))
    if "bad" in (issued, expires):
        return None, "Enter valid dates."
    d = VehicleDocument.objects.create(
        vehicle=v, kind=kind, reference=(data.get("reference") or "").strip()[:80],
        issued_on=issued, expires_on=expires, file=upload,
        notes=data.get("notes") or "", created_by=actor)
    audit(ENTITY, v.id, "VEHICLE_DOCUMENT", actor=actor,
          detail={"reg_no": v.reg_no, "kind": kind, "expires": str(expires or "")})
    return d, None


def remove_document(d, actor):
    audit(ENTITY, d.vehicle_id, "VEHICLE_DOCUMENT_REMOVED", actor=actor,
          detail={"reg_no": d.vehicle.reg_no, "kind": d.kind})
    d.delete()


def doc_state(d, today=None):
    today = today or timezone.localdate()
    if not d.expires_on:
        return "none", None
    days = (d.expires_on - today).days
    if days < 0:
        return "overdue", days
    if days <= 7:
        return "d7", days
    if days <= 30:
        return "d30", days
    return "ok", days


def sweep_expiry(today=None):
    """Daily: alert the fleet at 30 days, 7 days and overdue — once per
    level per document."""
    from .notify import _role_users, notify_user
    today = today or timezone.localdate()
    fired = 0
    recips = _role_users("RENTAL_MANAGER", "RENTAL", "ADMIN")
    for d in VehicleDocument.objects.filter(expires_on__isnull=False,
                                            vehicle__is_active=True) \
            .exclude(vehicle__status="DISPOSED").select_related("vehicle"):
        state, days = doc_state(d, today)
        level = {"overdue": "OVERDUE", "d7": "7", "d30": "30"}.get(state)
        if level is None or d.alert_level == level:
            continue
        d.alert_level = level
        d.save(update_fields=["alert_level"])
        when = ("is overdue" if days < 0 else f"expires in {days} day{'s' if days != 1 else ''}")
        for u in recips:
            notify_user(u, f"{d.vehicle.reg_no}: {d.get_kind_display()} {when}",
                        body=f"{d.vehicle} — {d.get_kind_display()} {d.reference} "
                             f"{'expired' if days < 0 else 'expires'} {d.expires_on:%d %b %Y}",
                        category="alert")
            fired += 1
    return fired


# ---- serialisation -------------------------------------------------------------

def _s(v, places="0.01"):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return str(v.quantize(Decimal(places)))
    return str(v)


def doc_dict(d):
    state, days = doc_state(d)
    return {"id": d.id, "kind": d.kind, "kind_label": d.get_kind_display(),
            "reference": d.reference, "issued_on": d.issued_on, "expires_on": d.expires_on,
            "file": d.file.url if d.file else None, "notes": d.notes,
            "state": state, "days": days}


def vehicle_dict(v, user=None, full=False):
    docs = list(v.documents.all())
    worst = "ok"
    for d in docs:
        st, _ = doc_state(d)
        if st == "overdue" or (st == "d7" and worst != "overdue") or (st == "d30" and worst == "ok"):
            worst = st
    out = {
        "id": v.id, "reg_no": v.reg_no, "fleet_no": v.fleet_no,
        "vehicle_class": v.vehicle_class, "make": v.make, "model": v.model,
        "year": v.year, "capacity": v.capacity, "status": v.status,
        "photo": v.photo.url if v.photo else None,
        "rate_currency": v.rate_currency, "rate_daily": _s(v.rate_daily),
        "operator_included": v.operator_included, "fuel_basis": v.fuel_basis,
        "is_active": v.is_active, "docs_state": worst, "n_docs": len(docs),
        "default_operator": v.default_operator_id,
        "default_operator_name": v.default_operator.full_name if v.default_operator_id else "",
    }
    if full:
        out.update({
            "engine_no": v.engine_no, "chassis_no": v.chassis_no,
            "rate_hourly": _s(v.rate_hourly), "rate_weekly": _s(v.rate_weekly),
            "rate_monthly": _s(v.rate_monthly), "operator_rate_daily": _s(v.operator_rate_daily),
            "minimum_charge_days": v.minimum_charge_days,
            "purchase_date": v.purchase_date, "purchase_cost": _s(v.purchase_cost),
            "hour_meter": _s(v.hour_meter, "0.1"), "notes": v.notes,
            "documents": [doc_dict(d) for d in docs],
            "can_write": can_write(user) if user else False,
            "can_set_rates": can_set_rates(user) if user else False,
        })
    return out


def summary():
    today = timezone.localdate()
    vs = list(Vehicle.objects.filter(is_active=True).exclude(status="DISPOSED")
              .prefetch_related("documents"))
    by_status = {s: 0 for s in Vehicle.Status.values}
    expiring = []
    for v in vs:
        by_status[v.status] = by_status.get(v.status, 0) + 1
        for d in v.documents.all():
            st, days = doc_state(d, today)
            if st in ("overdue", "d7", "d30"):
                expiring.append({"vehicle": v.id, "reg_no": v.reg_no, "fleet_no": v.fleet_no,
                                 "kind": d.get_kind_display(), "expires_on": d.expires_on,
                                 "state": st, "days": days})
    expiring.sort(key=lambda x: x["expires_on"])
    return {"fleet": len(vs), "by_status": by_status, "expiring": expiring}


def search(qs, q):
    q = (q or "").strip()
    if not q:
        return qs
    return qs.filter(Q(reg_no__icontains=q) | Q(fleet_no__icontains=q)
                     | Q(vehicle_class__icontains=q) | Q(make__icontains=q)
                     | Q(model__icontains=q))
