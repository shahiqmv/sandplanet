"""Project bonds & insurance (owner 2026-08-03).

Covers: Advance Payment Bond, Performance Bond, CAR, Third-Party Liability,
Other. Which a client requires varies, so each carries a `required` flag.
Lifecycle: the QS records the insurer's quote → raises a PYR for the premium →
once the PYR is paid the cover flips to PAID → the QS uploads the issued policy
+ expiry (tracked for renewal). Claims WARN (never block) while a required
cover isn't ISSUED.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.files.base import ContentFile
from django.db import transaction

from .audit import audit
from .models import (Attachment, CostHead, Document, DocumentRevision,
                     ProjectBond)

EDIT_ROLES = ("ADMIN", "DIRECTOR", "PM", "QS")

# The covers that block a client's payment when required but not in place.
CLAIM_BLOCKING = (ProjectBond.Kind.ADVANCE_PAYMENT_BOND,
                  ProjectBond.Kind.PERFORMANCE_BOND)


# ---- helpers --------------------------------------------------------------

def _dec(v):
    try:
        return Decimal(str(v)) if v not in (None, "") else None
    except (InvalidOperation, TypeError):
        return None


def _apply(bond, data):
    if "kind" in data and data["kind"] in ProjectBond.Kind.values:
        bond.kind = data["kind"]
    if "required" in data:
        bond.required = str(data["required"]).lower() not in ("false", "0", "")
    for f in ("insurer", "quote_ref", "policy_ref", "notes"):
        if f in data:
            setattr(bond, f, (data.get(f) or "").strip())
    if "currency" in data and data["currency"] in ("MVR", "USD"):
        bond.currency = data["currency"]
    if "insured_value" in data:
        bond.insured_value = _dec(data.get("insured_value"))
    if "premium" in data:
        bond.premium = _dec(data.get("premium"))
    for f in ("quote_date", "issue_date", "expiry_date"):
        if f in data:
            setattr(bond, f, data.get(f) or None)


def _pre_payment(bond):
    return bond.status in (ProjectBond.Status.REQUIRED,
                           ProjectBond.Status.QUOTED)


# ---- capture --------------------------------------------------------------

def add_bond(project, data, files, actor):
    if actor.role not in EDIT_ROLES:
        return None, "Only the QS / PM / Director / Admin manage bonds."
    if data.get("kind") not in ProjectBond.Kind.values:
        return None, "Pick a cover type."
    bond = ProjectBond(project=project, created_by=actor, currency="MVR")
    _apply(bond, data)
    bond.status = (ProjectBond.Status.QUOTED if bond.premium
                   else ProjectBond.Status.REQUIRED)
    bond.save()
    if files and files.get("quote_file"):
        bond.quote_file = files["quote_file"]
        bond.save(update_fields=["quote_file"])
    audit("project_bond", bond.id, "BOND_ADDED", actor=actor,
          detail={"project": project.code, "kind": bond.kind})
    return bond, None


def update_bond(bond, data, files, actor):
    if actor.role not in EDIT_ROLES:
        return "Not permitted."
    _apply(bond, data)
    if files and files.get("quote_file"):
        bond.quote_file = files["quote_file"]
    # keep REQUIRED/QUOTED coherent with whether a premium is captured; leave
    # payment/issue states alone.
    if _pre_payment(bond):
        bond.status = (ProjectBond.Status.QUOTED if bond.premium
                       else ProjectBond.Status.REQUIRED)
    bond.save()
    audit("project_bond", bond.id, "BOND_UPDATED", actor=actor)
    return None


def cancel_bond(bond, actor):
    if actor.role not in EDIT_ROLES:
        return "Not permitted."
    bond.status = ProjectBond.Status.CANCELLED
    bond.save(update_fields=["status", "updated_at"])
    audit("project_bond", bond.id, "BOND_CANCELLED", actor=actor)
    return None


def delete_bond(bond, actor):
    if actor.role not in EDIT_ROLES:
        return "Not permitted."
    if bond.status in (ProjectBond.Status.PAYMENT_RAISED,
                       ProjectBond.Status.PAID, ProjectBond.Status.ISSUED):
        return "A cover with a payment raised can't be deleted — cancel it."
    audit("project_bond", bond.id, "BOND_DELETED", actor=actor)
    bond.delete()
    return None


# ---- raise the premium PYR ------------------------------------------------

def raise_bond_pyr(bond, actor):
    """Raise a PYR for the premium, with the insurer quote attached, and link
    it to the cover. The QS then submits it through the normal payment rail."""
    from .numbering import next_ref
    from .payments import create_payment_request
    if actor.role not in EDIT_ROLES:
        return "Not permitted."
    if not bond.premium:
        return "Record the insurer's quote (premium) first."
    if bond.pyr_id and not bond.pyr.is_void:
        return "A payment request has already been raised for this cover."
    project = bond.project
    site = project.site
    ch, _ = CostHead.objects.get_or_create(
        name="Insurance & Bonds",
        defaults={"is_active": True, "commercial": True})
    label = bond.get_kind_display()
    purpose = f"{label} premium — {project.code}"
    data = {
        "amount_requested": str(bond.premium), "cost_head_id": ch.id,
        "payee": bond.insurer or label, "currency": bond.currency or "MVR",
        "purpose": purpose, "payment_method": "BANK",
        "payment_type": "DIRECT",
    }
    with transaction.atomic():
        ref = next_ref("PYR", site)
        doc = Document.objects.create(
            doc_type="PYR", ref=ref, site=site, doc_date=date.today(),
            status="DRAFT", created_by=actor)
        rev = DocumentRevision.objects.create(
            document=doc, rev_label="R0", created_by=actor,
            payload={"purpose": purpose, "payee": data["payee"],
                     "kind": "bond_premium"})
        doc.current_revision = rev
        doc.save(update_fields=["current_revision"])
        pr, err = create_payment_request(doc, data, actor)
        if err:
            transaction.set_rollback(True)
            return err
        if bond.quote_file:
            try:
                content = bond.quote_file.read()
                name = bond.quote_file.name.split("/")[-1]
                att = Attachment(document=doc, revision=rev, kind="QUOTATION",
                                 file_name=name,
                                 content_type="application/octet-stream",
                                 size_bytes=len(content))
                att.file.save(name, ContentFile(content), save=True)
            except Exception:
                pass
        # No approval layer — not the site PM and not the Director. A commercial
        # premium clears straight to Finance's payment voucher (owner 2026-08-05),
        # so it never sits as a draft in the site register waiting to be chased.
        from .payments import _set_status
        _set_status(doc, "SUBMITTED", "SUBMIT", actor, purpose)
        _set_status(doc, "DIRECTOR_APPROVED", "CLEAR_TO_VOUCHER", actor,
                    "Commercial premium — no approval step; cleared to Finance")
        bond.pyr = doc
        bond.status = ProjectBond.Status.PAYMENT_RAISED
        bond.save(update_fields=["pyr", "status", "updated_at"])
    audit("project_bond", bond.id, "BOND_PYR_RAISED", actor=actor,
          detail={"pyr": doc.ref})
    return None


def on_pyr_paid(doc, user=None):
    """Called when a PYR is paid — advance any cover it settles to PAID."""
    bond = ProjectBond.objects.filter(
        pyr=doc, status=ProjectBond.Status.PAYMENT_RAISED).first()
    if bond:
        bond.status = ProjectBond.Status.PAID
        bond.save(update_fields=["status", "updated_at"])
        audit("project_bond", bond.id, "BOND_PREMIUM_PAID", actor=user)


# ---- issue the policy -----------------------------------------------------

def issue_bond(bond, data, files, actor):
    if actor.role not in EDIT_ROLES:
        return "Not permitted."
    _apply(bond, data)     # policy_ref / issue_date / expiry_date
    if files and files.get("policy_file"):
        bond.policy_file = files["policy_file"]
    if not (bond.policy_file or bond.policy_ref):
        return "Upload the issued policy or record its reference."
    bond.status = ProjectBond.Status.ISSUED
    bond.expiry_alert = ""          # reset the renewal watermark
    bond.save()
    audit("project_bond", bond.id, "BOND_ISSUED", actor=actor,
          detail={"expiry": str(bond.expiry_date or "")})
    return None


# ---- serialize ------------------------------------------------------------

def bond_dict(bond, request=None):
    def url(f):
        if not f:
            return None
        try:
            u = f.url
            return request.build_absolute_uri(u) if request else u
        except Exception:
            return None

    pyr = bond.pyr
    return {
        "id": bond.id, "kind": bond.kind, "kind_label": bond.get_kind_display(),
        "required": bond.required, "insurer": bond.insurer,
        "insured_value": bond.insured_value, "currency": bond.currency,
        "quote_ref": bond.quote_ref, "quote_date": bond.quote_date,
        "premium": bond.premium, "quote_file_url": url(bond.quote_file),
        "status": bond.status, "status_label": bond.get_status_display(),
        "pyr_ref": pyr.ref if pyr else None,
        "pyr_status": pyr.status if pyr else None,
        "policy_ref": bond.policy_ref, "policy_file_url": url(bond.policy_file),
        "issue_date": bond.issue_date, "expiry_date": bond.expiry_date,
        "notes": bond.notes,
    }


def project_bonds(project, request=None):
    return [bond_dict(b, request) for b in project.bonds.all()]


def required_gaps(project):
    """Required covers that aren't ISSUED yet — the claim-submission warning.
    Returns a list of human labels (empty when all required covers are in
    place)."""
    gaps = []
    for b in project.bonds.exclude(status=ProjectBond.Status.CANCELLED):
        if b.required and b.status != ProjectBond.Status.ISSUED:
            gaps.append(b.get_kind_display())
    return gaps


# ---- expiry sweep (cron, daily) — 30 / 7 / expired ------------------------

_LEVELS = {"OVERDUE": 3, "T7": 2, "T30": 1}


def _level_for(days):
    if days < 0:
        return "OVERDUE"
    if days <= 7:
        return "T7"
    if days <= 30:
        return "T30"
    return None


def sweep_bond_expiry(today=None):
    """Fire renewal reminders for issued covers as expiry nears — once per
    escalation (watermarked), re-firing if the cover is renewed then lapses.
    Escalates to the Director at 7 days / overdue."""
    from . import notify
    today = today or date.today()
    fired = 0
    qs = ProjectBond.objects.filter(
        status=ProjectBond.Status.ISSUED, expiry_date__isnull=False
    ).select_related("project__site", "project__pm", "project__qs")
    for bond in qs:
        days = (bond.expiry_date - today).days
        level = _level_for(days)
        if not level:
            continue
        if _LEVELS[level] <= _LEVELS.get(bond.expiry_alert, 0):
            continue
        project = bond.project
        label = bond.get_kind_display()
        when = ("has EXPIRED" if days < 0
                else f"expires in {days} day{'s' if days != 1 else ''}")
        title = f"{label} {when} — {project.code}"
        body = (f"{label} for {project.code} ({project.title[:60]}) "
                f"{when} ({bond.expiry_date:%d %b %Y}). Arrange renewal.")
        recipients = set()
        if project.qs_id:
            recipients.add(project.qs)
        if project.pm_id:
            recipients.add(project.pm)
        if level in ("T7", "OVERDUE"):
            recipients.update(notify._role_users("DIRECTOR"))
        for u in recipients:
            notify.notify_user(u, title, body, category="alert")
        bond.expiry_alert = level
        bond.save(update_fields=["expiry_alert", "updated_at"])
        fired += 1
    return fired
