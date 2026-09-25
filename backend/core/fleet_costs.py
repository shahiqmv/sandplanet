"""Vehicle cost centres, job cards and the vehicle P&L
(MARINE_BUILD_BRIEF.md §4, phase 6).

Money reaches a vehicle three ways, all through the ordinary ledger: a PYR
raised on a fleet cost head carries the vehicle (payments.cost_centre), the
operator's payroll share follows the vehicles they ran that month
(operator_allocation, called from payroll.lock_run), and the rental invoice
posts revenue per vehicle (rental.issue_invoice). This module reads those
postings back per vehicle and keeps the job cards."""
import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from .audit import audit
from .models import CostPosting, HireLog, MaintenanceJob, Vehicle
from .numbering import next_trading_ref

ZERO = Decimal("0")
_CENT = Decimal("0.01")
ENTITY = "vehicle"
COST_HEADS = ("RNT_MAINTENANCE", "RNT_FUEL", "RNT_OPERATOR", "RNT_INSURANCE")


def _q2(v):
    return Decimal(str(v or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)


def _s(v):
    return None if v is None else str(_q2(v))


# ---- payroll allocation ----------------------------------------------------------------

def operator_allocation(line, gross):
    """[(vehicle, share)] of one payroll line's gross: the days the employee
    ran each vehicle in the run's month (the register's operator, any state
    but off-hire) at the line's own per-day rate, never more than the gross
    in total. A man who ran no vehicle allocates nothing."""
    if gross <= 0 or not line.days_worked or line.days_worked <= 0:
        return []
    run = line.run
    first = date(run.year, run.month, 1)
    last = date(run.year, run.month, calendar.monthrange(run.year, run.month)[1])
    rows = (HireLog.objects.filter(operator_id=line.employee_id, date__range=(first, last))
            .exclude(state="OFF_HIRE")
            .values("line__vehicle_id").annotate(n=Count("id")).order_by("line__vehicle_id"))
    if not rows:
        return []
    per_day = Decimal(gross) / Decimal(line.days_worked)
    out, left = [], _q2(gross)
    vehicles = {v.id: v for v in Vehicle.objects.filter(id__in=[r["line__vehicle_id"] for r in rows])}
    for r in rows:
        share = min(_q2(per_day * r["n"]), left)
        if share <= 0:
            continue
        out.append((vehicles[r["line__vehicle_id"]], share))
        left -= share
    return out


# ---- job cards -----------------------------------------------------------------------------

def _date(v):
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        return "bad"


def _dec(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (ArithmeticError, ValueError):
        return "bad"


def open_job(vehicle, data, actor):
    desc = (data.get("description") or "").strip()
    if not desc:
        return None, "Say what the job is."
    kind = data.get("kind") or "REPAIR"
    if kind not in MaintenanceJob.Kind.values:
        return None, "Unknown job kind."
    opened = _date(data.get("opened_on")) or timezone.localdate()
    hm = _dec(data.get("hour_meter_at"))
    if "bad" in (opened, hm):
        return None, "Enter a valid date and hour meter."
    with transaction.atomic():
        job = MaintenanceJob.objects.create(
            vehicle=vehicle, ref=next_trading_ref("MJ"), kind=kind, opened_on=opened,
            hour_meter_at=hm, description=desc, vendor=(data.get("vendor") or "").strip(),
            created_by=actor)
        if hm is not None and (vehicle.hour_meter is None or hm > vehicle.hour_meter):
            vehicle.hour_meter = hm
        if vehicle.status == "AVAILABLE":
            vehicle.status = "MAINTENANCE"
        vehicle.save(update_fields=["hour_meter", "status", "updated_at"])
    audit(ENTITY, vehicle.id, "JOB_OPENED", actor=actor,
          detail={"reg_no": vehicle.reg_no, "job": job.ref, "kind": kind})
    return job, None


def update_job(job, data, actor):
    if job.status == "CLOSED":
        return "This job card is closed."
    for k in ("description", "work_done", "vendor"):
        if k in data:
            setattr(job, k, (data.get(k) or "").strip())
    if "kind" in data and data["kind"] in MaintenanceJob.Kind.values:
        job.kind = data["kind"]
    for k in ("hour_meter_at", "next_service_hours"):
        if k in data:
            d = _dec(data[k])
            if d == "bad":
                return "Enter a valid number."
            setattr(job, k, d)
    for k in ("opened_on", "next_service_date"):
        if k in data:
            d = _date(data[k])
            if d == "bad":
                return "Enter a valid date."
            setattr(job, k, d)
    if not job.description:
        return "Say what the job is."
    job.save()
    audit(ENTITY, job.vehicle_id, "JOB_UPDATED", actor=actor, detail={"job": job.ref})
    return None


def close_job(job, data, actor):
    if job.status == "CLOSED":
        return "Already closed."
    work = (data.get("work_done") or job.work_done or "").strip()
    if not work:
        return "Record the work done before closing the card."
    closed = _date(data.get("closed_on")) or timezone.localdate()
    hm = _dec(data.get("hour_meter_at"))
    nsh, nsd = _dec(data.get("next_service_hours")), _date(data.get("next_service_date"))
    if "bad" in (closed, hm, nsh, nsd):
        return "Enter valid dates and numbers."
    if closed < job.opened_on:
        return "The close date is before the job was opened."
    v = job.vehicle
    with transaction.atomic():
        job.work_done = work
        job.status = "CLOSED"
        job.closed_on = closed
        job.closed_by = actor
        job.downtime_days = (closed - job.opened_on).days + 1
        if hm is not None:
            job.hour_meter_at = hm
        if nsh is not None:
            job.next_service_hours = nsh
        if nsd is not None:
            job.next_service_date = nsd
        if "vendor" in data:
            job.vendor = (data.get("vendor") or "").strip()
        job.save()
        if hm is not None and (v.hour_meter is None or hm > v.hour_meter):
            v.hour_meter = hm
        if v.status == "MAINTENANCE" and not v.jobs.filter(status="OPEN").exclude(id=job.id).exists():
            v.status = "AVAILABLE"
        v.save(update_fields=["hour_meter", "status", "updated_at"])
    audit(ENTITY, v.id, "JOB_CLOSED", actor=actor,
          detail={"reg_no": v.reg_no, "job": job.ref, "downtime_days": job.downtime_days})
    return None


def _pyr_row(pr):
    d = pr.document
    return {"ref": d.ref, "status": d.status, "payee": pr.payee, "purpose": pr.purpose,
            "cost_head": pr.cost_head.name, "currency": pr.currency,
            "amount": _s(pr.amount_paid if pr.amount_paid is not None else pr.amount_requested),
            "paid_date": pr.paid_date, "job": pr.maintenance_job.ref if pr.maintenance_job_id else None,
            "doc_date": d.doc_date}


def job_dict(job):
    prs = list(job.payment_requests.select_related("document", "cost_head", "maintenance_job")
               .exclude(document__status__in=("CANCELLED", "REJECTED")))
    return {"id": job.id, "ref": job.ref, "vehicle": job.vehicle_id, "reg_no": job.vehicle.reg_no,
            "fleet_no": job.vehicle.fleet_no, "kind": job.kind, "kind_label": job.get_kind_display(),
            "status": job.status, "opened_on": job.opened_on, "closed_on": job.closed_on,
            "hour_meter_at": _s(job.hour_meter_at) if job.hour_meter_at is not None else None,
            "description": job.description, "work_done": job.work_done, "vendor": job.vendor,
            "downtime_days": job.downtime_days,
            "next_service_hours": (str(job.next_service_hours)
                                   if job.next_service_hours is not None else None),
            "next_service_date": job.next_service_date,
            "cost": _s(sum((_mvr(pr) for pr in prs), ZERO)),
            "pyrs": [_pyr_row(pr) for pr in prs],
            "created_by": job.created_by.full_name,
            "closed_by": job.closed_by.full_name if job.closed_by_id else None}


def _mvr(pr):
    amt = pr.amount_paid if pr.amount_paid is not None else pr.amount_requested
    if pr.currency == "USD":
        from . import fx
        return _q2(Decimal(amt) * (pr.fx_rate or fx.usd_rate()))
    return _q2(amt)


def vehicle_costs(vehicle):
    """The PYRs charged to this vehicle, live or in flight."""
    from .models import PaymentRequest
    prs = (PaymentRequest.objects.filter(vehicle=vehicle)
           .exclude(document__status__in=("CANCELLED", "REJECTED"))
           .select_related("document", "cost_head", "maintenance_job")
           .order_by("-document__doc_date", "-document_id"))
    return [_pyr_row(pr) for pr in prs]


# ---- the P&L --------------------------------------------------------------------------------

def _posting_mvr(p, rate):
    return Decimal(p.amount) * rate if p.currency == "USD" else Decimal(p.amount)


def pnl(d_from, d_to, vehicle=None):
    """Per vehicle over a period: revenue (the invoices' per-vehicle postings),
    costs by head, margin; and from the register the days on hire, the
    breakdown days and the hours. INCURRED postings only — COMMITTED and
    PAID are the same money at other stages. USD postings convert at the
    company rate. A row without a vehicle (mobilisation and other charges
    billed, costs no one tagged) is the fleet's own."""
    from . import fx
    rate = fx.usd_rate()
    posts = CostPosting.objects.filter(book="RENTAL", state="INCURRED",
                                       posted_on__range=(d_from, d_to)).select_related("cost_head")
    logs = HireLog.objects.filter(date__range=(d_from, d_to))
    if vehicle is not None:
        posts = posts.filter(vehicle=vehicle)
        logs = logs.filter(line__vehicle=vehicle)
    rows = {}

    def row(v):
        key = v.id if v else None
        if key not in rows:
            rows[key] = {"vehicle": key, "reg_no": v.reg_no if v else None,
                         "fleet_no": v.fleet_no if v else None,
                         "vehicle_class": v.vehicle_class if v else None,
                         "revenue": ZERO, "costs": {c: ZERO for c in COST_HEADS}, "other_cost": ZERO,
                         "total_cost": ZERO, "margin": ZERO,
                         "hire_days": 0, "breakdown_days": 0, "hours": ZERO}
        return rows[key]

    vs = {v.id: v for v in Vehicle.objects.filter(id__in={p.vehicle_id for p in posts if p.vehicle_id}
                                                      | {l["line__vehicle_id"] for l in
                                                         logs.values("line__vehicle_id")})}
    if vehicle is not None:
        vs[vehicle.id] = vehicle
        row(vehicle)
    for p in posts:
        r = row(vs.get(p.vehicle_id))
        amt = _posting_mvr(p, rate)
        code = p.cost_head.code
        if code == "RNT_REVENUE":
            r["revenue"] += amt
        elif code == "RNT_OUTPUT_GST":
            continue
        elif code in r["costs"]:
            r["costs"][code] += amt
        else:
            r["other_cost"] += amt
    for l in (logs.values("line__vehicle_id", "state").annotate(n=Count("id"), h=Sum("hours"))):
        r = row(vs.get(l["line__vehicle_id"]))
        if l["state"] in HireLog.BILLABLE:
            r["hire_days"] += l["n"]
        elif l["state"] == "BREAKDOWN":
            r["breakdown_days"] += l["n"]
        r["hours"] += l["h"] or ZERO
    days = (d_to - d_from).days + 1
    out = []
    fleet = {"revenue": ZERO, "costs": {c: ZERO for c in COST_HEADS}, "other_cost": ZERO,
             "total_cost": ZERO, "margin": ZERO, "hire_days": 0, "breakdown_days": 0}
    for r in rows.values():
        r["total_cost"] = sum(r["costs"].values(), ZERO) + r["other_cost"]
        r["margin"] = r["revenue"] - r["total_cost"]
        for k in ("revenue", "other_cost", "total_cost", "margin"):
            fleet[k] += r[k]
        for c in COST_HEADS:
            fleet["costs"][c] += r["costs"][c]
        fleet["hire_days"] += r["hire_days"]
        fleet["breakdown_days"] += r["breakdown_days"]
        r["utilisation"] = round(100 * r["hire_days"] / days, 1) if r["vehicle"] and days else None
        r["margin_pct"] = (round(100 * float(r["margin"] / r["revenue"]), 1)
                           if r["revenue"] else None)
        out.append({**r, "revenue": _s(r["revenue"]), "other_cost": _s(r["other_cost"]),
                    "total_cost": _s(r["total_cost"]), "margin": _s(r["margin"]),
                    "costs": {c: _s(x) for c, x in r["costs"].items()}, "hours": str(r["hours"])})
    out.sort(key=lambda r: (r["vehicle"] is None, r["fleet_no"] or "", r["reg_no"] or ""))
    n_vehicles = sum(1 for r in out if r["vehicle"])
    fleet["utilisation"] = (round(100 * fleet["hire_days"] / (days * n_vehicles), 1)
                            if n_vehicles and days else None)
    fleet["margin_pct"] = (round(100 * float(fleet["margin"] / fleet["revenue"]), 1)
                           if fleet["revenue"] else None)
    return {"from": d_from, "to": d_to, "days": days, "usd_rate": str(rate),
            "rows": out,
            "fleet": {**fleet, "revenue": _s(fleet["revenue"]), "other_cost": _s(fleet["other_cost"]),
                      "total_cost": _s(fleet["total_cost"]), "margin": _s(fleet["margin"]),
                      "costs": {c: _s(x) for c, x in fleet["costs"].items()}}}
