"""Biometric attendance terminals — ingest and matching (owner 2026-08-23).

Phase 1 is deliberately LISTEN ONLY: punches are received, stored and matched
to workers, and nothing touches attendance or payroll. That lets the device run
alongside manual marking for a month so its record can be compared with the
clerk's before it is trusted with anyone's pay.

ZKTeco's ADMS ("push") protocol: the terminal HTTP-POSTs records to a URL we
configure, identifying itself only by its serial number. The record format is
tab-separated and its exact column order varies by model and firmware, so the
parser here is deliberately tolerant — it takes what it recognises, stores the
raw line either way, and never drops a punch it failed to read.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone as djtz

from .audit import audit
from .models import (AttendanceDevice, BiometricEnrolment, DevicePunch,
                     Employee)

log = logging.getLogger(__name__)

MANAGE_ROLES = ("HO_HR", "ADMIN", "PA")
VIEW_ROLES = MANAGE_ROLES + ("DIRECTOR", "PM", "SITE_ADMIN", "SITE_ENGINEER",
                             "FINANCE")

# Terminals are set to local time; the app stores UTC (settings §1).
SITE_OFFSET = timedelta(hours=5)          # Maldives, UTC+5, no DST

# ZKTeco status column -> direction. 0/4 in, 1/5 out; break punches are not a
# direction we act on. Unknown values fall through to UNKNOWN rather than
# guessing, because guessing a direction silently moves someone's hours.
_DIRECTION = {"0": "IN", "4": "IN", "1": "OUT", "5": "OUT"}

# ZKTeco verify-mode column -> how the worker identified themselves. Useful for
# the enrolment argument: if face carries most punches, fingerprints are not
# working on these hands.
_VERIFY = {"0": "password", "1": "finger", "2": "finger", "3": "card",
           "4": "card", "15": "face", "20": "face", "25": "palm"}


def can_manage(user):
    return user.role in MANAGE_ROLES


def can_view(user):
    return user.role in VIEW_ROLES


def device_id_for(employee):
    """The numeric part of the employee number — EMP-0603 -> 603."""
    digits = re.sub(r"\D", "", employee.emp_no or "")
    return str(int(digits)) if digits else ""


def _aware(naive):
    """A terminal's local timestamp as a stored UTC instant."""
    return naive.replace(tzinfo=timezone(SITE_OFFSET))


def parse_timestamp(raw):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return _aware(datetime.strptime(raw.strip(), fmt))
        except (ValueError, AttributeError):
            continue
    return None


def parse_attlog(body):
    """Split an ATTLOG upload into rows.

    Each line is tab-separated, conventionally:
        user_id, timestamp, status, verify_mode, workcode, reserved…
    Anything past the first four columns is ignored; anything short of a user id
    and a readable timestamp is returned unparsed, with its line kept.
    """
    rows = []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        if not line.strip():
            continue
        parts = re.split(r"\t+|\s{2,}", line.strip())
        if len(parts) < 2:
            parts = line.split()
        uid = (parts[0] if parts else "").strip()
        # The timestamp is one field when the line is tab-separated
        # ("…\t2026-08-23 07:12:04\t…") and two when it is space-separated.
        # Which it is decides where the status and verify columns sit, so work
        # it out rather than assuming — assuming put every punch's direction
        # and verify mode one column out.
        when, used = None, 0
        if len(parts) >= 2:
            when = parse_timestamp(parts[1])
            used = 1
        if when is None and len(parts) >= 3:
            when = parse_timestamp(f"{parts[1]} {parts[2]}")
            used = 2 if when is not None else 0
        nxt = 1 + used
        status = parts[nxt].strip() if len(parts) > nxt else ""
        verify = parts[nxt + 1].strip() if len(parts) > nxt + 1 else ""
        rows.append({
            "raw": line.strip(),
            "device_user_id": uid if uid.isdigit() else uid[:20],
            "punched_at": when,
            "direction": _DIRECTION.get(status, "UNKNOWN"),
            "verify_mode": _VERIFY.get(verify, verify[:16] if verify else ""),
        })
    return rows


def resolve_employee(device_user_id):
    """The worker a device ID belongs to: an active enrolment first, else the
    employee number it was derived from."""
    if not device_user_id:
        return None
    hit = (BiometricEnrolment.objects
           .filter(device_user_id=device_user_id, is_active=True)
           .select_related("employee").first())
    if hit:
        return hit.employee
    if device_user_id.isdigit():
        return Employee.objects.filter(
            emp_no=f"EMP-{int(device_user_id):04d}").first()
    return None


def record_punches(device, body):
    """Store an upload. Returns a tally; a repeat of a punch we already hold is
    counted as a duplicate and changes nothing, so a device may safely re-send
    everything after an outage."""
    rows = parse_attlog(body)
    tally = {"received": len(rows), "stored": 0, "duplicate": 0,
             "unknown_id": 0, "unparsed": 0}
    latest = None
    for r in rows:
        if r["punched_at"] is None or not r["device_user_id"]:
            status, emp = DevicePunch.Status.UNPARSED, None
            tally["unparsed"] += 1
        else:
            emp = resolve_employee(r["device_user_id"])
            if emp is None:
                status = DevicePunch.Status.UNKNOWN_ID
                tally["unknown_id"] += 1
            else:
                status = DevicePunch.Status.MATCHED
        try:
            with transaction.atomic():
                DevicePunch.objects.create(
                    device=device, device_user_id=r["device_user_id"],
                    punched_at=r["punched_at"], direction=r["direction"],
                    verify_mode=r["verify_mode"], employee=emp,
                    status=status, raw=r["raw"][:2000])
            tally["stored"] += 1
            if r["punched_at"] and (latest is None or r["punched_at"] > latest):
                latest = r["punched_at"]
        except IntegrityError:
            tally["duplicate"] += 1          # already held — the point of D-02
    fields = ["last_seen_at"]
    device.last_seen_at = djtz.now()
    if tally["stored"]:
        device.punches_received += tally["stored"]
        fields.append("punches_received")
        if latest and (device.last_punch_at is None
                       or latest > device.last_punch_at):
            device.last_punch_at = latest
            fields.append("last_punch_at")
    device.save(update_fields=fields)
    return tally


def touch(device):
    """The terminal checked in without sending records."""
    device.last_seen_at = djtz.now()
    device.save(update_fields=["last_seen_at"])


def device_by_serial(serial):
    if not serial:
        return None
    return (AttendanceDevice.objects
            .filter(serial=serial.strip(), is_active=True)
            .select_related("site").first())


# ---- enrolment ------------------------------------------------------------

def enrol(employee, data, actor):
    """Record that a worker has been enrolled on the terminals."""
    from datetime import date as _date
    device_user_id = (data.get("device_user_id") or "").strip() \
        or device_id_for(employee)
    if not device_user_id:
        return None, "This worker has no employee number to enrol against."
    clash = (BiometricEnrolment.objects
             .filter(device_user_id=device_user_id, is_active=True)
             .exclude(employee=employee).select_related("employee").first())
    if clash:
        return None, (f"Device ID {device_user_id} is already enrolled to "
                      f"{clash.employee.emp_no} {clash.employee.full_name}.")
    fingers = data.get("finger_count")
    row, _ = BiometricEnrolment.objects.update_or_create(
        employee=employee, is_active=True,
        defaults={
            "device_user_id": device_user_id,
            "site_id": employee.current_site_id(),
            "finger_count": int(fingers) if str(fingers or "").isdigit() else 0,
            "face_enrolled": bool(data.get("face_enrolled")),
            "card_enrolled": bool(data.get("card_enrolled")),
            "enrolled_on": _date.today(),
            "enrolled_by": actor,
            "notes": (data.get("notes") or "")[:200],
        })
    audit("employee", employee.id, "BIOMETRIC_ENROLLED", actor=actor,
          detail={"emp_no": employee.emp_no, "device_user_id": device_user_id,
                  "fingers": row.finger_count, "face": row.face_enrolled})
    return row, None


def remove_enrolment(employee, actor, reason=""):
    from datetime import date as _date
    rows = BiometricEnrolment.objects.filter(employee=employee, is_active=True)
    if not rows.exists():
        return "This worker is not enrolled."
    rows.update(is_active=False, removed_on=_date.today())
    audit("employee", employee.id, "BIOMETRIC_REMOVED", actor=actor,
          detail={"emp_no": employee.emp_no, "reason": reason[:200]})
    return None


def enrolment_gaps(site):
    """Active direct/subcontract workers on this site with no live enrolment —
    the list a supervisor works through."""
    enrolled = set(BiometricEnrolment.objects.filter(is_active=True)
                   .values_list("employee_id", flat=True))
    out = []
    for e in (Employee.objects.filter(
            is_active=True, site_allocations__site=site,
            site_allocations__to_date__isnull=True)
            .select_related("job_category").distinct().order_by("emp_no")):
        if e.id not in enrolled:
            out.append({"id": e.id, "emp_no": e.emp_no,
                        "full_name": e.full_name,
                        "trade": (e.job_category.name
                                  if e.job_category_id else ""),
                        "suggested_id": device_id_for(e)})
    return out


# ---- Phase 2: propose the day from the punches (owner 2026-08-24) ---------
#
# The rules, as decided by the owner:
#   * no punch-out  -> propose a NORMAL day to the site's finish time, flagged
#   * span < 5h     -> propose HALF_DAY
#   * beyond hours  -> PROPOSE the overtime; the clerk adjusts, the PM still
#                      approves — the approval chain is untouched
#   * rest day      -> flag the punch, propose NOTHING (rest-day pay is
#                      deliberate, never a by-product of crossing the gate)
#   * >15 min late  -> flagged only; pay is untouched (check-in is stored)
#   * no punch, no clerk mark -> stays unmarked and unpaid, as today
#
# Proposals are computed from the punch log at read time and are never stored:
# the only write path into attendance remains the clerk's own save, which
# carries every existing guard (join date, unpaid leave, month lock).

HALF_DAY_BELOW_HOURS = Decimal("5")
LATE_GRACE_MIN = 15


def _local(dt):
    return dt.astimezone(timezone(SITE_OFFSET))


def day_punch_window(day):
    """The UTC instants bounding a Maldives calendar day."""
    start = datetime(day.year, day.month, day.day, tzinfo=timezone(SITE_OFFSET))
    return start, start + timedelta(days=1)


def day_proposals(site, day):
    """What the gate saw, per worker, for one site and one local day.

    Returns {"rows": {employee_id: {...}}, "unmatched": [...]} — the second
    list is punches at this site's terminals that belong to nobody on this
    site's register (an unknown ID, or a worker allocated elsewhere).
    """
    from decimal import ROUND_FLOOR

    start, end = day_punch_window(day)
    # Night crews punch out after midnight, so the fetch runs into the next
    # morning; each worker's own window (below) decides what counts as HIS day.
    punches = (DevicePunch.objects
               .filter(device__site=site, punched_at__gte=start,
                       punched_at__lt=end + timedelta(hours=13))
               .select_related("employee")
               .order_by("punched_at"))
    if not punches:
        return {"rows": {}, "unmatched": []}
    here = set(Employee.objects.filter(
        is_active=True, site_allocations__site=site,
        site_allocations__to_date__isnull=True).values_list("id", flat=True))
    is_rest = day.isoweekday() not in (site.working_days or [])
    by_emp, unmatched = {}, []
    for p in punches:
        if p.employee_id and p.employee_id in here:
            by_emp.setdefault(p.employee_id, []).append(p)
        elif p.punched_at < end:   # strangers list stays this calendar day's
            unmatched.append({
                "device_user_id": p.device_user_id,
                "punched_at": _local(p.punched_at).strftime("%H:%M")
                if p.punched_at else None,
                "emp_no": p.employee.emp_no if p.employee_id else None,
                "full_name": p.employee.full_name if p.employee_id else None,
                "why": ("not on this site's register" if p.employee_id
                        else "no worker for this ID"),
            })
    # Shift sites: every threshold below — window, late, finish, OT — is the
    # WORKER's schedule; a worker with no shift follows the site's hours. A
    # night shift belongs to the date it starts (owner 2026-08-25).
    from .shifts import schedule_for, shifts_map, window_datetimes
    smap = shifts_map(site, day, list(by_emp)) if site.shifts.exists() else {}
    rows = {}
    for emp_id, plist in by_emp.items():
        shift = smap.get(emp_id)
        sched_start, sched_end, ot_from, overnight = schedule_for(site, shift)
        win_s, win_e = window_datetimes(day, sched_start, sched_end)
        if overnight:
            # His day: from well before the shift to a while after it ends
            # tomorrow. Anything outside is another day's business (an early
            # out-punch this morning belongs to yesterday's row).
            lo, hi = win_s - timedelta(hours=4), win_e + timedelta(hours=6)
        else:
            lo = datetime.combine(day, datetime.min.time())
            hi = lo + timedelta(days=1)
        plist = [p for p in plist
                 if lo <= _local(p.punched_at).replace(tzinfo=None) < hi]
        if not plist:
            continue
        first, last = _local(plist[0].punched_at), _local(plist[-1].punched_at)
        first_dt = first.replace(tzinfo=None)
        last_dt = last.replace(tzinfo=None)
        distinct = last > first
        flags = []
        row = {
            "punch_count": len(plist),
            "first": first.strftime("%H:%M"),
            "last": last.strftime("%H:%M") if distinct else None,
            "shift": shift.name if shift else None,
            "modes": sorted({p.verify_mode for p in plist if p.verify_mode}),
            "flags": flags, "proposal": None,
        }
        if is_rest:
            # Owner: rest-day pay is deliberate — show, never propose.
            flags.append("REST_DAY")
            rows[emp_id] = row
            continue
        grace = (site.late_after_min if site.late_after_min is not None
                 else LATE_GRACE_MIN)
        late_by = (first_dt - win_s).total_seconds() / 60
        if late_by > grace:
            flags.append("LATE")
        if not distinct:
            # The most common exception: he was almost certainly there all
            # day. Propose the normal finish, loudly flagged.
            flags.append("NO_OUT")
            rows[emp_id] = {**row, "proposal": {
                "check_in": first.strftime("%H:%M"),
                "check_out": sched_end.strftime("%H:%M"),
                "remark": "PRESENT", "ot_requested": "0"}}
            continue
        span = Decimal(str((last - first).total_seconds())) / 3600
        remark = "PRESENT"
        if span < HALF_DAY_BELOW_HOURS:
            remark = "HALF_DAY"
            flags.append("SHORT")
        # OT proposed from time past the schedule's OT threshold (the finish
        # unless a later ot_counts_from is set), floored to the half hour so
        # a proposal never overstates; the clerk bumps it if real.
        if ot_from == sched_end:
            ot_from_dt = win_e
        else:
            ot_from_dt = datetime.combine(day, ot_from)
            if overnight and ot_from <= sched_start:
                ot_from_dt += timedelta(days=1)   # threshold past midnight
        ot = Decimal("0")
        if remark == "PRESENT" and last_dt > ot_from_dt:
            past = (last_dt - ot_from_dt).total_seconds() / 3600
            ot = (Decimal(str(past)) * 2).quantize(
                Decimal("1"), rounding=ROUND_FLOOR) / 2
        if ot > 0:
            flags.append("OT")
        rows[emp_id] = {**row, "proposal": {
            "check_in": first.strftime("%H:%M"),
            "check_out": last.strftime("%H:%M"),
            "remark": remark, "ot_requested": str(ot)}}
    return {"rows": rows, "unmatched": unmatched}
