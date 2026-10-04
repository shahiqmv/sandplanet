"""External audits (owner 2026-10-04: "manage audit ... & upload audit
report"). A register of each audit of the company by an outside auditor —
who, for which year, where it stands — and the papers that belong to it:
the engagement letter, the draft, the signed report. Deliberately small: the
auditor's fee is paid on an ordinary payment requisition, and only its
reference is noted here.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .audit import audit as log
from .models import ExternalAudit, ExternalAuditFile

VIEW_ROLES = ("FINANCE", "ADMIN", "SIGNATORY", "DIRECTOR", "PA")
EDIT_ROLES = ("FINANCE", "ADMIN")
MAX_FILE_BYTES = 40 * 1024 * 1024


def _date(v):
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def save(data, actor, rec=None):
    """Create an audit or change it. Returns (audit, error)."""
    from .numbering import next_ref
    a = rec or ExternalAudit(created_by=actor)
    new = a.pk is None
    try:
        for key, limit, required in (
                ("auditor", 160, "Give the auditor."),
                ("title", 200, None), ("partner", 160, None),
                ("auditor_contact", 200, None), ("payment_ref", 120, None)):
            if key in data or new:
                v = " ".join(str(data.get(key) or "").split())[:limit]
                if required and not v:
                    raise ValueError(required)
                setattr(a, key, v)
        if "notes" in data or new:
            a.notes = str(data.get("notes") or "").strip()
        if "kind" in data or new:
            a.kind = data.get("kind") or "FINANCIAL"
            if a.kind not in ExternalAudit.Kind.values:
                raise ValueError("Unknown kind of audit.")
        for key, what in (("period_start", "the first day of the period"),
                          ("period_end", "the last day of the period")):
            if key in data or new:
                d = _date(data.get(key))
                if d is None:
                    raise ValueError(f"Give {what} audited.")
                setattr(a, key, d)
        if a.period_end < a.period_start:
            raise ValueError("The period ends before it starts.")
        for key in ("started_on", "report_date"):
            if key in data:
                d = _date(data.get(key))
                if data.get(key) and d is None:
                    raise ValueError("A date is not a date.")
                setattr(a, key, d)
        if "status" in data:
            if data["status"] not in ExternalAudit.Status.values:
                raise ValueError("Unknown status.")
            a.status = data["status"]
        if "opinion" in data:
            a.opinion = data.get("opinion") or ""
            if a.opinion and a.opinion not in ExternalAudit.Opinion.values:
                raise ValueError("Unknown opinion.")
        if "fee_currency" in data:
            a.fee_currency = (data.get("fee_currency") or "MVR").upper()[:3]
        if "fee_amount" in data:
            v = data.get("fee_amount")
            try:
                a.fee_amount = (None if v in (None, "") else
                                Decimal(str(v).replace(",", ""))
                                .quantize(Decimal("0.01")))
            except (InvalidOperation, ValueError):
                raise ValueError("The fee is not a number.")
        if a.status == "COMPLETED" and a.report_date is None:
            raise ValueError("Give the date on the audit report.")
        if not a.title:
            a.title = default_title(a)
    except ValueError as exc:
        return None, str(exc)
    with transaction.atomic():
        if new:
            a.ref = next_ref("AUD", None)
        a.save()
    log("external_audit", a.id,
        "EXTERNAL_AUDIT_CREATED" if new else "EXTERNAL_AUDIT_CHANGED",
        actor=actor, detail={"ref": a.ref, "auditor": a.auditor,
                             "period_end": str(a.period_end),
                             "status": a.status})
    return a, None


def default_title(a):
    year = (f"{a.period_end.year}" if a.period_start.year == a.period_end.year
            else f"{a.period_start.year}/{a.period_end.year % 100:02d}")
    what = {"FINANCIAL": "Financial statements", "TAX": "Tax audit",
            "OTHER": "Audit"}[a.kind]
    return f"{what} {year}"


def add_file(a, upload, kind, label, actor):
    """Attach a paper. Returns (file, error). Uploading the final report to
    an audit still open does not close it — the status says that."""
    if upload is None:
        return None, "Choose the file."
    if upload.size > MAX_FILE_BYTES:
        return None, "That file is over 40 MB."
    kind = kind or "OTHER"
    if kind not in ExternalAuditFile.Kind.values:
        return None, "Unknown kind of document."
    f = ExternalAuditFile.objects.create(
        audit=a, kind=kind, label=" ".join((label or "").split())[:160],
        file=upload, original_name=(upload.name or "")[:200],
        uploaded_by=actor)
    log("external_audit", a.id, "EXTERNAL_AUDIT_FILE_ADDED", actor=actor,
        detail={"ref": a.ref, "kind": kind, "name": f.original_name})
    return f, None


def remove_file(f, actor):
    a = f.audit
    name, kind = f.original_name, f.kind
    f.file.delete(save=False)
    f.delete()
    log("external_audit", a.id, "EXTERNAL_AUDIT_FILE_REMOVED", actor=actor,
        detail={"ref": a.ref, "kind": kind, "name": name})


def file_dict(f):
    return {"id": f.id, "kind": f.kind, "kind_label": f.get_kind_display(),
            "label": f.label, "name": f.original_name, "url": f.file.url,
            "uploaded_at": f.uploaded_at,
            "uploaded_by": f.uploaded_by.full_name if f.uploaded_by_id
            else ""}


def audit_dict(a, detail=False):
    files = list(a.files.all())
    report = next((f for f in reversed(files) if f.kind == "REPORT"), None)
    out = {
        "id": a.id, "ref": a.ref, "kind": a.kind,
        "kind_label": a.get_kind_display(), "title": a.title,
        "period_start": a.period_start, "period_end": a.period_end,
        "auditor": a.auditor, "partner": a.partner,
        "auditor_contact": a.auditor_contact, "status": a.status,
        "status_label": a.get_status_display(), "started_on": a.started_on,
        "report_date": a.report_date, "opinion": a.opinion,
        "opinion_label": a.get_opinion_display() if a.opinion else "",
        "fee_currency": a.fee_currency, "fee_amount": a.fee_amount,
        "payment_ref": a.payment_ref, "notes": a.notes,
        "file_count": len(files),
        "report_url": report.file.url if report else None,
    }
    if detail:
        out["files"] = [file_dict(f) for f in files]
    return out


def meta():
    def opts(choices):
        return [{"value": v, "label": lab} for v, lab in choices]
    return {"kinds": opts(ExternalAudit.Kind.choices),
            "statuses": opts(ExternalAudit.Status.choices),
            "opinions": opts(ExternalAudit.Opinion.choices),
            "file_kinds": opts(ExternalAuditFile.Kind.choices)}
