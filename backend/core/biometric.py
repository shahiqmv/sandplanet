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
