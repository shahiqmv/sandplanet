"""Manual client invoices — tax invoices recorded directly in Planet, outside
the progress-claim flow, so a project that came onto the system mid-flight has
complete receivables without rebuilding its BOQ and past claims.

Two origins (see models.ManualInvoice):
  * HISTORICAL — an invoice raised the old way before Planet: back-dated to its
    real date, the client's own invoice number, record-only (optionally with
    the actual invoice PDF attached). Nothing is printed.
  * ISSUED — an invoice raised on Planet for an off-system claim: a Planet
    invoice number and a generated tax-invoice PDF.

Either way it feeds the same receivables aging / statement / receipts as a
claim invoice (see receivables.py). Contracts are USD. Void, never delete, so
the number is never silently reused.
"""
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q as models_Q
from django.db.models import Sum

from .audit import audit
from .commercial import (_employer, _fmt_money, _next_invoice_no, _q2,
                         amount_in_words)
from .models import ManualInvoice, Project

ZERO = Decimal("0")

CREATE_ROLES = ("QS", "FINANCE", "DIRECTOR", "ADMIN")


def _dec(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


APPROVE_ROLES = ("DIRECTOR", "ADMIN")

# What QS teams take off an invoice; offered as presets, any text is allowed.
DEDUCTION_PRESETS = ("Advance recovery", "Retention", "Back charge",
                     "Contra charge")


def _truthy(v, default=True):
    if v in (None, ""):
        return default
    return str(v).strip().lower() not in ("0", "false", "no", "off")


def _parse_lines(raw):
    """Coerce incoming line dicts → clean line records. A line's amount is
    qty × unit_price when both are given, else the amount typed directly.

    A deduction (advance recovery, retention, a back charge) is stored
    negative whatever sign was typed. A charge typed negative is what QS did
    before deductions existed — it is taken as a deduction before GST, rather
    than dropped (owner 2026-10-31, INV-2026-0064 went out without its
    advance recovery)."""
    out = []
    for r in (raw or []):
        desc = str(r.get("description") or "").strip()[:300]
        qty = _dec(r.get("quantity"))
        unit = _dec(r.get("unit_price"))
        amt = _dec(r.get("amount"))
        if amt is None and qty is not None and unit is not None:
            amt = qty * unit
        if not desc or amt is None or amt == 0:
            continue
        kind = "DEDUCTION" if (r.get("kind") == "DEDUCTION" or amt < 0) \
            else "CHARGE"
        before = _truthy(r.get("before_gst")) if kind == "DEDUCTION" else True
        amt = -abs(amt) if kind == "DEDUCTION" else amt
        if kind == "DEDUCTION" and unit is not None:
            unit = -abs(unit)
        out.append({"description": desc, "quantity": qty,
                    "unit_price": unit, "amount": _q2(amt), "kind": kind,
                    "before_gst": before})
    return out


def totals(lines, gst_pct):
    """The money of an invoice from its lines: charges, less the deductions
    taken before GST = the taxable net; GST on that; less the deductions
    taken after GST = the total the client owes. Same order as a claim's
    waterfall (advance recovery and retention before GST)."""
    def get(ln, k):
        return ln[k] if isinstance(ln, dict) else getattr(ln, k)
    charges = sum((get(ln, "amount") for ln in lines
                   if get(ln, "kind") != "DEDUCTION"), ZERO)
    pre = -sum((get(ln, "amount") for ln in lines
                if get(ln, "kind") == "DEDUCTION" and get(ln, "before_gst")),
               ZERO)
    post = -sum((get(ln, "amount") for ln in lines
                 if get(ln, "kind") == "DEDUCTION"
                 and not get(ln, "before_gst")), ZERO)
    net = _q2(charges - pre)
    gst = _q2(net * (gst_pct or ZERO) / Decimal("100"))
    return {"charges": _q2(charges), "deducted_before_gst": _q2(pre),
            "net": net, "gst": gst, "deducted_after_gst": _q2(post),
            "amount": _q2(net + gst - post)}


def _clean(data, actor, mi=None):
    """Validate the editable fields. Returns (fields, lines, error)."""
    project = Project.objects.filter(
        pk=data.get("project_id") or (mi.project_id if mi else None)).first()
    if project is None:
        return None, None, "Choose the project this invoice belongs to."
    origin = data.get("origin") or (mi.origin if mi else None)
    if origin not in ("HISTORICAL", "ISSUED"):
        return None, None, ("Choose whether this is a historical or an issued "
                            "invoice.")
    if not data.get("invoice_date"):
        return None, None, "Enter the invoice date."
    lines = _parse_lines(data.get("lines"))
    if not any(ln["kind"] == "CHARGE" for ln in lines):
        return None, None, ("Add at least one line item — a description and "
                            "an amount.")
    gst_pct = _dec(data.get("gst_pct"))
    if gst_pct is None:
        gst_pct = Decimal("8")           # local GST default
    t = totals(lines, gst_pct)
    if t["net"] <= ZERO:
        return None, None, ("The deductions take the invoice to nothing — the "
                            "net must be more than zero.")
    if t["amount"] <= ZERO:
        return None, None, "The invoice total must be more than zero."
    fields = {"project": project, "origin": origin,
              "invoice_date": data["invoice_date"],
              "due_date": data.get("due_date") or None,
              "currency": (data.get("currency") or "USD")[:3].upper(),
              "gst_pct": gst_pct, "net_amount": t["net"],
              "gst_amount": t["gst"], "amount": t["amount"],
              "note": (data.get("note") or "").strip()}
    if origin == "HISTORICAL":
        no = (data.get("invoice_no") or "").strip()
        if not no:
            return None, None, "Enter the client's invoice number."
        fields["invoice_no"] = no[:40]
    elif mi is None or mi.origin != "ISSUED":
        fields["invoice_no"] = ""        # Planet numbers it on approval
    # A single-charge invoice titles itself from that line unless a summary
    # is set.
    description = (data.get("description") or "").strip()[:300]
    charges = [ln for ln in lines if ln["kind"] == "CHARGE"]
    if not description and len(charges) == 1:
        description = charges[0]["description"]
    fields["description"] = description
    return fields, lines, None


def _write_lines(mi, lines):
    from .models import ManualInvoiceLine
    mi.lines.all().delete()
    ManualInvoiceLine.objects.bulk_create([
        ManualInvoiceLine(
            invoice=mi, sort_order=i * 10, description=ln["description"],
            quantity=ln["quantity"], unit_price=ln["unit_price"],
            amount=ln["amount"], kind=ln["kind"],
            before_gst=ln["before_gst"])
        for i, ln in enumerate(lines, 1)])


def label(mi):
    """How people know an invoice before it has a number."""
    return mi.invoice_no or f"Draft invoice #{mi.id} ({mi.project.code})"


def create_manual_invoice(data, actor):
    """Draft a manual invoice from its line items (charges and deductions).
    Nothing is owed until a Director approves it; `submit` sends it straight
    on. HISTORICAL carries the client's own number; ISSUED is numbered at
    approval. Returns (invoice, error)."""
    if actor.role not in CREATE_ROLES:
        return None, "You can't record client invoices."
    fields, lines, err = _clean(data, actor)
    if err:
        return None, err
    with transaction.atomic():
        mi = ManualInvoice(status="DRAFT", created_by=actor, **fields)
        att = data.get("attachment")
        if att is not None:
            mi.attachment = att
        mi.save()
        _write_lines(mi, lines)
    audit("project", mi.project_id, "MANUAL_INVOICE_CREATED", actor=actor,
          detail={"invoice": label(mi), "origin": mi.origin,
                  "lines": len(lines), "amount": str(mi.amount)})
    if _truthy(data.get("submit"), default=False):
        err = submit(mi, actor)
        if err:
            return mi, err
    return mi, None


def update_manual_invoice(mi, data, actor):
    """Change a draft — its own, a returned one, or one reopened for a
    revision. Returns an error or None."""
    if actor.role not in CREATE_ROLES:
        return "You can't change client invoices."
    if mi.is_void:
        return "This invoice is void."
    if mi.approved_at and data.get("origin") not in (None, "", mi.origin):
        return "A revision keeps its type — it can't change origin."
    if mi.status != "DRAFT":
        return ("Only a draft can be changed — "
                + ("reopen it as a revision first." if mi.status == "APPROVED"
                   else "it is waiting for approval; it can be returned."))
    fields, lines, err = _clean(data, actor, mi)
    if err:
        return err
    with transaction.atomic():
        for k, v in fields.items():
            setattr(mi, k, v)
        att = data.get("attachment")
        if att is not None:
            mi.attachment = att
        mi.save()
        _write_lines(mi, lines)
    audit("project", mi.project_id, "MANUAL_INVOICE_EDITED", actor=actor,
          detail={"invoice": label(mi), "revision": mi.revision,
                  "amount": str(mi.amount)})
    if _truthy(data.get("submit"), default=False):
        return submit(mi, actor)
    return None


def _approvers(mi):
    from .models import User
    return User.objects.filter(role="DIRECTOR", is_active=True)


def submit(mi, actor):
    """Send a draft to the Directors for approval."""
    from django.utils import timezone

    from .notify import notify_user
    if actor.role not in CREATE_ROLES:
        return "You can't submit client invoices."
    if mi.is_void:
        return "This invoice is void."
    if mi.status != "DRAFT":
        return "Only a draft can be submitted."
    mi.status = "SUBMITTED"
    mi.submitted_by = actor
    mi.submitted_at = timezone.now()
    mi.save(update_fields=["status", "submitted_by", "submitted_at",
                           "updated_at"])
    audit("project", mi.project_id, "MANUAL_INVOICE_SUBMITTED", actor=actor,
          detail={"invoice": label(mi), "revision": mi.revision,
                  "amount": str(mi.amount)})
    what = label(mi) + (f" (revision {mi.revision})" if mi.revision else "")
    for u in _approvers(mi).exclude(pk=actor.pk):
        notify_user(u, f"Client invoice to approve: {what}",
                    f"{mi.project.code} · {mi.currency} "
                    f"{_fmt_money(mi.amount, 2)} — from {actor.full_name}. "
                    "Receivables → Manual invoices.", category="approval")
    return None


def approve(mi, actor):
    """A Director approves: the invoice is owed from now — receivables,
    receipts and the books take it — and an issued one gets its number."""
    from django.utils import timezone

    from .notify import notify_user
    if actor.role not in APPROVE_ROLES:
        return "A Director approves client invoices."
    if mi.status != "SUBMITTED" or mi.is_void:
        return "Only a submitted invoice can be approved."
    if actor.role != "ADMIN" and actor.id in (mi.submitted_by_id,):
        return ("You submitted this invoice — another Director approves "
                "it.")
    with transaction.atomic():
        if mi.origin == "ISSUED" and not mi.invoice_no:
            mi.invoice_no = _next_invoice_no()
        mi.status = "APPROVED"
        mi.approved_by = actor
        mi.approved_at = timezone.now()
        mi.return_note = ""
        mi.save(update_fields=["status", "invoice_no", "approved_by",
                               "approved_at", "return_note", "updated_at"])
    audit("project", mi.project_id, "MANUAL_INVOICE_APPROVED", actor=actor,
          detail={"invoice_no": mi.invoice_no, "revision": mi.revision,
                  "amount": str(mi.amount)})
    if mi.submitted_by_id and mi.submitted_by_id != actor.id:
        notify_user(mi.submitted_by, f"Invoice approved: {mi.invoice_no}",
                    f"{mi.project.code} · {mi.currency} "
                    f"{_fmt_money(mi.amount, 2)} — approved by "
                    f"{actor.full_name}.")
    return None


def return_invoice(mi, actor, note):
    """A Director sends a submitted invoice back to draft, with the reason."""
    from .notify import notify_user
    if actor.role not in APPROVE_ROLES:
        return "A Director returns client invoices."
    if mi.status != "SUBMITTED" or mi.is_void:
        return "Only a submitted invoice can be returned."
    note = (note or "").strip()
    if not note:
        return "Say what needs changing."
    mi.status = "DRAFT"
    mi.return_note = note[:1000]
    mi.save(update_fields=["status", "return_note", "updated_at"])
    audit("project", mi.project_id, "MANUAL_INVOICE_RETURNED", actor=actor,
          detail={"invoice": label(mi), "note": note[:300]})
    if mi.submitted_by_id:
        notify_user(mi.submitted_by, f"Invoice returned: {label(mi)}",
                    f"{actor.full_name}: {note}")
    return None


def reopen(mi, actor, reason):
    """Reopen an approved invoice as a revision, to correct and resubmit it.
    It keeps its number; until it is approved again it is not owed. Refused
    once money is recorded against it, or a claim has taken it over."""
    if actor.role not in CREATE_ROLES:
        return "You can't change client invoices."
    if mi.is_void or mi.status != "APPROVED":
        return "Only an approved invoice can be reopened."
    if mi.receipts.exists():
        return ("A receipt is recorded against this invoice — it can't be "
                "revised. Raise a correcting invoice instead.")
    if mi.bills_claim_id or mi.superseded_at:
        return ("This invoice is tied to a certified claim — unlink it "
                "first.")
    reason = (reason or "").strip()
    if not reason:
        return "Give the reason for the revision."
    mi.status = "DRAFT"
    mi.revision += 1
    mi.return_note = f"Revision {mi.revision}: {reason}"[:1000]
    mi.save(update_fields=["status", "revision", "return_note", "updated_at"])
    audit("project", mi.project_id, "MANUAL_INVOICE_REOPENED", actor=actor,
          detail={"invoice_no": mi.invoice_no, "revision": mi.revision,
                  "reason": reason[:300]})
    return None


def delete_draft(mi, actor):
    """Discard a draft that was never approved — it has no number to keep."""
    if actor.role not in CREATE_ROLES:
        return "You can't change client invoices."
    if mi.status != "DRAFT" or mi.approved_at is not None:
        return "Only a draft that was never approved can be deleted — void it."
    audit("project", mi.project_id, "MANUAL_INVOICE_DELETED", actor=actor,
          detail={"invoice": label(mi), "amount": str(mi.amount)})
    mi.delete()
    return None


def void_manual_invoice(mi, actor):
    """Void an invoice recorded in error. Blocked while receipts are settled
    against it — those must be removed first (never orphan client cash)."""
    if actor.role not in CREATE_ROLES:
        return "You can't void client invoices."
    if mi.is_void:
        return "This invoice is already void."
    if mi.receipts.exists():
        return ("Receipts are recorded against this invoice — remove them "
                "before voiding it.")
    mi.is_void = True
    mi.save(update_fields=["is_void", "updated_at"])
    audit("project", mi.project_id, "MANUAL_INVOICE_VOIDED", actor=actor,
          detail={"invoice": label(mi)})
    return None


def received_for(mi):
    return _q2(mi.receipts.aggregate(s=Sum("amount"))["s"] or ZERO)


def manual_invoice_dict(mi, user=None):
    got = received_for(mi)
    amt = _q2(mi.amount)
    lines = list(mi.lines.all())
    t = totals(lines, mi.gst_pct)
    role = getattr(user, "role", None)
    live = not mi.is_void
    return {
        "id": mi.id, "origin": mi.origin, "invoice_no": mi.invoice_no,
        "label": label(mi), "status": mi.status, "revision": mi.revision,
        "return_note": mi.return_note,
        "submitted_by": (mi.submitted_by.full_name if mi.submitted_by_id
                         else ""),
        "submitted_at": mi.submitted_at,
        "approved_by": mi.approved_by.full_name if mi.approved_by_id else "",
        "approved_at": mi.approved_at,
        "charges": t["charges"], "deducted_before_gst": t["deducted_before_gst"],
        "deducted_after_gst": t["deducted_after_gst"],
        # what the person looking can do with it now
        "can_edit": live and mi.status == "DRAFT" and role in CREATE_ROLES,
        "can_submit": live and mi.status == "DRAFT" and role in CREATE_ROLES,
        "can_approve": (live and mi.status == "SUBMITTED"
                        and role in APPROVE_ROLES
                        and (role == "ADMIN"
                             or getattr(user, "id", None)
                             != mi.submitted_by_id)),
        "can_reopen": (live and mi.status == "APPROVED"
                       and role in CREATE_ROLES and got == ZERO
                       and not mi.bills_claim_id and not mi.superseded_at),
        "can_delete": (mi.status == "DRAFT" and mi.approved_at is None
                       and role in CREATE_ROLES),
        # The claim taking this invoice over, and whether it has closed it.
        "superseded_by": (mi.superseded_by.ref if mi.superseded_by_id
                          else None),
        "superseded_by_id": mi.superseded_by_id,
        "superseded_at": mi.superseded_at,
        "project_id": mi.project_id, "project_code": mi.project.code,
        "project_title": mi.project.title, "site_id": mi.project.site_id,
        "invoice_date": mi.invoice_date, "due_date": mi.effective_due_date,
        "currency": mi.currency, "net_amount": mi.net_amount,
        "gst_pct": mi.gst_pct, "gst_amount": mi.gst_amount, "amount": amt,
        "received": got, "outstanding": amt - got,
        "description": mi.description, "note": mi.note,
        "lines": [{"id": ln.id, "description": ln.description,
                   "quantity": ln.quantity, "unit_price": ln.unit_price,
                   "amount": ln.amount, "kind": ln.kind,
                   "before_gst": ln.before_gst} for ln in lines],
        "has_attachment": bool(mi.attachment),
        "can_pdf": mi.origin == "ISSUED",
        "is_void": mi.is_void,
        "created_by": mi.created_by.full_name if mi.created_by_id else "",
        "created_at": mi.created_at,
    }


def list_invoices(site_id=None, include_void=False, user=None):
    qs = (ManualInvoice.objects.select_related(
        "project", "project__site", "created_by", "submitted_by",
        "approved_by").prefetch_related("lines")
        .order_by("-invoice_date", "-id"))
    if site_id is not None:
        qs = qs.filter(project__site_id=site_id)
    if not include_void:
        qs = qs.filter(is_void=False)
    return [manual_invoice_dict(mi, user) for mi in qs]


def _plain(d):
    """1.000 → 1, 8.00 → 8, 2.50 → 2.5 — how a person writes a quantity."""
    return f"{Decimal(d).normalize():f}"


def manual_invoice_pdf_context(mi):
    """Context for the ISSUED tax-invoice PDF (branded like the claim invoice)."""
    from .pdf import company_info, logo_src
    net = _q2(mi.net_amount or ZERO)
    gst = _q2(mi.gst_amount or ZERO)
    amount = _q2(mi.amount)
    all_lines = list(mi.lines.all())

    def row(ln):
        # a deduction reads as a bracketed figure, as on an IPC
        neg = ln.amount < 0
        return {
            "description": ln.description,
            "quantity": (_plain(ln.quantity) if ln.quantity is not None
                         else ""),
            "unit_price": (_fmt_money(abs(ln.unit_price), 2)
                           if ln.unit_price is not None else ""),
            "amount_f": (f"({_fmt_money(abs(ln.amount), 2)})" if neg
                         else _fmt_money(ln.amount, 2)),
        }
    t = totals(all_lines, mi.gst_pct)
    return {
        "logo_src": logo_src(), "co": company_info(),
        "employer": _employer(mi.project), "mi": mi, "project": mi.project,
        "currency": mi.currency,
        "lines": [row(ln) for ln in all_lines if ln.kind != "DEDUCTION"],
        "less_before": [row(ln) for ln in all_lines
                        if ln.kind == "DEDUCTION" and ln.before_gst],
        "less_after": [row(ln) for ln in all_lines
                       if ln.kind == "DEDUCTION" and not ln.before_gst],
        "charges_f": _fmt_money(t["charges"], 2),
        "draft": mi.status != "APPROVED",
        "gst_pct": _plain(mi.gst_pct),
        "net_f": _fmt_money(net, 2), "gst_f": _fmt_money(gst, 2),
        "amount_f": _fmt_money(amount, 2),
        "amount_words": amount_in_words(amount, mi.currency),
    }


def link_to_claim(mi, claim, actor):
    """Tie an invoice to the claim that will take it over.

    Work is often billed before the claim covering it can be raised — an
    advance against a signed LOA, where the bonds and the advance claim take
    weeks, so the QS invoices it directly. When that claim is eventually
    certified it bills the same money, and receivables reads certified claims
    AND manual invoices: the client would owe it twice. The link closes this
    invoice at the moment the claim is certified, which is exactly when the
    second bill appears (owner 2026-09-01, SFR CASUAL).
    """
    from django.utils import timezone

    if actor.role not in CREATE_ROLES:
        return "You can't change client invoices."
    if mi.is_void:
        return "This invoice is void."
    if mi.status != "APPROVED":
        return "Only an approved invoice can be linked to a claim."
    if claim.project_id != mi.project_id:
        return (f"{claim.ref} is a claim on {claim.project.code}, and this "
                f"invoice is on {mi.project.code}.")
    if mi.receipts.exists():
        # The cash is allocated to this invoice. Closing it would leave the
        # receipt pointing at something no longer owed, and the claim showing
        # unpaid — so the receipt is moved first, deliberately, by a person.
        return ("Receipts are recorded against this invoice — move them to "
                f"{claim.ref} before linking it.")
    other = mi.superseded_by
    if other is not None and other.id != claim.id:
        return f"This invoice is already linked to {other.ref}."

    mi.superseded_by = claim
    # If the claim is already certified there is no later moment to wait for:
    # the second bill exists now.
    mi.superseded_at = (timezone.now() if claim.status in ("CERTIFIED", "PAID")
                        else None)
    mi.save(update_fields=["superseded_by", "superseded_at", "updated_at"])
    audit("project", mi.project_id, "MANUAL_INVOICE_LINKED", actor=actor,
          detail={"invoice_no": mi.invoice_no, "claim": claim.ref,
                  "closed": mi.superseded_at is not None})
    return None


def unlink_from_claim(mi, actor):
    """Undo the link — the invoice stands on its own again."""
    if actor.role not in CREATE_ROLES:
        return "You can't change client invoices."
    if mi.superseded_by_id is None:
        return "This invoice isn't linked to a claim."
    was = mi.superseded_by.ref
    mi.superseded_by = None
    mi.superseded_at = None
    mi.save(update_fields=["superseded_by", "superseded_at", "updated_at"])
    audit("project", mi.project_id, "MANUAL_INVOICE_UNLINKED", actor=actor,
          detail={"invoice_no": mi.invoice_no, "was": was})
    return None


@transaction.atomic
def bill_claim_by(claim, invoices, actor, drop_claim_invoice=False):
    """Record that these manual invoices are how a certified claim was billed
    (owner 2026-10-24, SFR CASUAL IPA-01 = INV-2026-0029 + INV-2026-0055).

    The claim keeps its certificate — the next IPC reads its advance from
    it — while receivables reads the invoices. Their total must match what
    the claim bills, to the cent or two a split rounds. With
    drop_claim_invoice the claim's own invoice number is withdrawn (kept in
    the audit), since the client never got it. Returns an error or None."""
    from .commercial import claim_valuation
    from .receipts import _settle
    if claim.status not in ("CERTIFIED", "PAID"):
        return "Only a certified claim is billed."
    if not invoices:
        return unbill_claim(claim, actor)
    for m in invoices:
        if m.project_id != claim.project_id:
            return f"{m.invoice_no} is on another project."
        if m.is_void:
            return f"{m.invoice_no} is void."
        if m.status != "APPROVED":
            return f"{label(m)} is not approved yet."
        if m.superseded_at:
            return (f"{m.invoice_no} was closed when a claim took it over — "
                    "it cannot also bill one.")
        if m.bills_claim_id and m.bills_claim_id != claim.id:
            return f"{m.invoice_no} already bills {m.bills_claim.ref}."
    due = _q2(claim_valuation(claim)["waterfall"]["net_to_pay"])
    total = sum((_q2(m.amount) for m in invoices), Decimal("0"))
    if abs(total - due) > Decimal("0.05"):
        return (f"The invoices total {total}, but {claim.ref} bills {due} — "
                "they must match.")
    # the set given is the whole billing: anything linked before and left
    # out stands on its own again
    keep = {m.id for m in invoices}
    for old in claim.billing_invoices.exclude(pk__in=keep):
        old.bills_claim = None
        old.save(update_fields=["bills_claim", "updated_at"])
    for m in invoices:
        m.bills_claim = claim
        m.save(update_fields=["bills_claim", "updated_at"])
    dropped = ""
    if drop_claim_invoice and claim.invoice_no:
        dropped = claim.invoice_no
        claim.invoice_no = ""
        claim.save(update_fields=["invoice_no"])
    _settle(claim, actor)
    audit("project", claim.project_id, "CLAIM_BILLED_BY_INVOICES",
          actor=actor,
          detail={"claim": claim.ref, "invoices": [m.invoice_no
                                                   for m in invoices],
                  "total": str(total), "claim_due": str(due),
                  "dropped_invoice_no": dropped})
    return None


@transaction.atomic
def unbill_claim(claim, actor):
    """Undo billing through manual invoices: they stand on their own again
    and the claim bills itself — with a fresh invoice number if its own was
    withdrawn (a withdrawn number is never reissued)."""
    from .receipts import _settle
    nos = list(claim.billing_invoices.values_list("invoice_no", flat=True))
    if not nos:
        return "This claim is not billed through manual invoices."
    claim.billing_invoices.update(bills_claim=None)
    issued = ""
    if not claim.invoice_no and claim.status in ("CERTIFIED", "PAID"):
        claim.invoice_no = issued = _next_invoice_no()
        claim.save(update_fields=["invoice_no"])
    _settle(claim, actor)
    audit("project", claim.project_id, "CLAIM_UNBILLED", actor=actor,
          detail={"claim": claim.ref, "invoices": nos,
                  "new_invoice_no": issued})
    return None


def billing_options(claim):
    """For the claim page: what bills it now, what could, and its total."""
    from django.db.models import Sum as _Sum

    from .commercial import claim_valuation

    def row(m):
        got = m.receipts.aggregate(s=_Sum("amount"))["s"] or ZERO
        return {"id": m.id, "invoice_no": m.invoice_no,
                "invoice_date": m.invoice_date, "amount": m.amount,
                "currency": m.currency, "description": m.description,
                "received": got, "linked": m.bills_claim_id == claim.id}
    qs = (ManualInvoice.objects.filter(project=claim.project, is_void=False,
                                       status="APPROVED",
                                       superseded_at__isnull=True)
          .filter(models_Q(bills_claim__isnull=True) | models_Q(
              bills_claim=claim))
          .order_by("invoice_date", "id"))
    return {"claim_ref": claim.ref, "claim_invoice_no": claim.invoice_no,
            "claim_total": _q2(claim_valuation(claim)["waterfall"]
                               ["net_to_pay"]),
            "invoices": [row(m) for m in qs]}
