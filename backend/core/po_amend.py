"""Amending a purchase order that has already gone to the supplier.

Orders change after they are issued — the supplier is short, an item turns out
to be unavailable, a quantity was wrong (owner 2026-08-13). Before this, a PO
could only go DRAFT → ISSUED → CLOSED, so the only ways to fix one were to
close it and raise another, or to correct it off the system.

Two rules shape the design:

* **The supplier's copy must not change under them.** A proposed amendment is
  a new revision that is NOT current, so the PO's PDF keeps showing the order
  the supplier actually holds until the Director approves. Only then does the
  new revision become the live one.
* **The supplier is never amended.** Buying from someone else is a different
  award and belongs on its own PO against the PR — otherwise an approved
  award silently becomes an order to a company nobody chose.
"""

import logging

from django.db import transaction

from .audit import audit
from .models import DocumentLine, DocumentRevision
from .notify import _role_users, notify_user

log = logging.getLogger(__name__)

PROPOSE_ROLES = ("HO_PURCHASING", "ADMIN")
DECIDE_ROLES = ("DIRECTOR", "ADMIN")
# Everything the amendment may set on a line. `item` and the supplier are
# deliberately absent — swapping what is being bought, or who from, is a new
# order rather than a correction of this one.
LINE_FIELDS = ("description", "unit", "qty_required", "rate", "amount",
               "remarks", "spec")


def pending_revision(po):
    """The proposed-but-unapproved revision, or None.

    It is simply the newest revision when one is awaiting a decision — the
    current revision is still the older, issued one.
    """
    if po.status != "AMENDMENT_PENDING":
        return None
    return po.revisions.exclude(pk=po.current_revision_id).order_by(
        "-id").first()


def _next_label(po):
    try:
        return f"R{int((po.current_revision.rev_label or 'R0')[1:]) + 1}"
    except (TypeError, ValueError):
        return f"R{po.revisions.count()}"


def _line_total(line):
    if line.amount is not None:
        return line.amount
    return (line.qty_required or 0) * (line.rate or 0)


def revision_total(revision):
    return sum((_line_total(ln) for ln in revision.lines.all()), 0)


@transaction.atomic
def propose_amendment(po, rows, reason, actor):
    """Draft a replacement revision for an issued PO. Returns (revision, err)."""
    if po.doc_type != "PO":
        return None, "Only a purchase order can be amended."
    if po.status != "ISSUED":
        return None, ("Only an issued order can be amended — this one is "
                      f"{po.status.replace('_', ' ').lower()}.")
    if not (reason or "").strip():
        return None, "Say why the order is being amended."
    rows = [r for r in (rows or []) if r]
    if not rows:
        return None, "An amended order needs at least one line."

    old = po.current_revision
    payload = dict(old.payload or {})
    payload["amendment_reason"] = reason.strip()
    payload["amended_from"] = old.rev_label
    revision = DocumentRevision.objects.create(
        document=po, rev_label=_next_label(po), payload=payload,
        created_by=actor, is_current=False)

    by_id = {ln.id: ln for ln in old.lines.all()}
    for i, row in enumerate(rows, start=1):
        src = by_id.get(row.get("id"))
        DocumentLine.objects.create(
            revision=revision, line_no=i,
            item=src.item if src else None,
            free_text_desc=(row.get("description")
                            or (src.free_text_desc if src else "")),
            unit=row.get("unit") or (src.unit if src else ""),
            spec=row.get("spec") or (src.spec if src else ""),
            qty_required=row.get("qty_required"),
            rate=row.get("rate"),
            amount=row.get("amount"),
            remarks=row.get("remarks") or (src.remarks if src else ""))

    po.status = "AMENDMENT_PENDING"
    po.save(update_fields=["status", "updated_at"])
    audit("document", po.id, "PO_AMENDMENT_PROPOSED", actor=actor,
          detail={"ref": po.ref, "rev": revision.rev_label, "reason": reason,
                  "was": str(revision_total(old)),
                  "now": str(revision_total(revision))})
    _notify(po, revision, actor)
    return revision, None


def _notify(po, revision, actor):
    was, now = revision_total(po.current_revision), revision_total(revision)
    direction = ("no change in value" if was == now
                 else f"{'up' if now > was else 'down'} {abs(now - was):,.2f}")
    for u in _role_users(*DECIDE_ROLES):
        notify_user(u, f"{po.ref} — amendment needs your approval",
                    body=f"{(revision.payload or {}).get('amendment_reason','')}"
                         f" ({direction})",
                    doc=po, category="approval")


def _money_block(po):
    """Why an approved amendment cannot move the money — or None if it can."""
    from .models import Payable, PaymentVoucherLine
    from .procurement import po_commitment
    pr, row, err = po_commitment(po)
    if err:                       # not a PR-backed order (an import PO)
        return None, None, None
    payable = Payable.objects.filter(document=pr, document_line=row).first()
    if payable is None:
        return pr, row, None
    if payable.status != "OUTSTANDING":
        return pr, row, (f"This order has already been settled "
                         f"({payable.status.lower()}) — a change now needs a "
                         f"credit note, not an amendment.")
    if PaymentVoucherLine.objects.filter(
            source_payable=payable,
            voucher__status__in=("DRAFT", "SUBMITTED")).exists():
        return pr, row, ("Finance has this payable on a voucher — take it off "
                         "the voucher before amending the order.")
    return pr, row, None


def _apply_amendment_money(po, pr, row, delta_net, actor):
    """Move the commitment and what we owe by the amendment's difference.

    Approving used to swap the revision and nothing else, so an order whose
    value changed left the payable and the cost ledger on the old figure —
    PO-036 would have understated what we owe Sonee by 4,860 (owner
    2026-08-23).
    """
    from decimal import Decimal

    from .models import Payable
    from .procurement import _post_pr_line

    if delta_net == 0:
        return
    old_credit = row.amount_credit or Decimal("0")
    old_gst = row.gst_amount or Decimal("0")
    # Keep the row's own effective tax rate rather than assuming the company
    # rate — the quotation set it.
    rate = (old_gst / old_credit) if old_credit else Decimal("0")
    delta_gst = (delta_net * rate).quantize(Decimal("0.01"))
    row.amount_credit = old_credit + delta_net
    row.gst_amount = old_gst + delta_gst
    row.save(update_fields=["amount_credit", "gst_amount"])
    # The ledger is append-only: post the difference, never rewrite history.
    _post_pr_line(pr, row, delta_net, delta_gst, actor)
    payable = Payable.objects.filter(document=pr, document_line=row,
                                     status="OUTSTANDING").first()
    if payable:
        payable.amount = payable.amount + delta_net + delta_gst
        payable.save(update_fields=["amount"])
    audit("document", po.id, "PO_AMENDMENT_MONEY_ADJUSTED", actor=actor,
          detail={"ref": po.ref, "net_delta": str(delta_net),
                  "gst_delta": str(delta_gst),
                  "payable_now": str(payable.amount) if payable else None})


@transaction.atomic
def decide_amendment(po, approve, actor, note=""):
    """Approve (the new revision goes live) or reject it (the supplier's copy
    stands). Either way the order returns to ISSUED. Approving also moves the
    commitment and the payable by the difference in value."""
    revision = pending_revision(po)
    if revision is None:
        return None, "This order has no amendment waiting."
    old = po.current_revision
    pr = row = None
    if approve:
        was, now = revision_total(old), revision_total(revision)
        pr, row, blocked = _money_block(po)
        if blocked and was != now:
            return None, blocked
        old.is_current = False
        old.save(update_fields=["is_current"])
        revision.is_current = True
        revision.save(update_fields=["is_current"])
        po.current_revision = revision
    else:
        revision.lines.all().delete()
        revision.delete()
    po.status = "ISSUED"
    po.save(update_fields=["status", "current_revision", "updated_at"])
    if approve:
        if pr is not None and row is not None:
            _apply_amendment_money(po, pr, row, now - was, actor)
        # The supplier holds a document, and the amended order is a new one.
        # Approving used to change the lines and leave the only PDF on the
        # file showing the superseded revision (owner 2026-08-23).
        try:
            from .pdf import generate_pdf
            generate_pdf(po, revision, "amendment")
        except Exception:                  # never block the decision on a PDF
            log.exception("amendment PDF failed for %s %s", po.ref,
                          revision.rev_label)
    audit("document", po.id,
          "PO_AMENDMENT_APPROVED" if approve else "PO_AMENDMENT_REJECTED",
          actor=actor, detail={"ref": po.ref, "note": note,
                               "rev": old.rev_label if not approve
                               else revision.rev_label})
    if po.created_by_id:
        notify_user(po.created_by,
                    f"{po.ref} — amendment {'approved' if approve else 'rejected'}",
                    body=note, doc=po, category="approval")
    return po, None


def _line_view(line):
    return {
        "id": line.id, "line_no": line.line_no,
        # Item's field is `description`, not `name` — reading `.name` here
        # raised on every order carrying a catalog item, so the Director's
        # amendment screen 500'd and left the PO stuck with no button on it
        # (owner 2026-08-23, PO-036).
        "description": line.free_text_desc or (
            line.item.description if line.item_id else ""),
        "unit": line.unit or "",
        "qty": line.qty_required, "rate": line.rate,
        "amount": _line_total(line), "remarks": line.remarks or "",
    }


def amendment_diff(po):
    """What the Director is being asked to approve: the issued order, the
    proposed one, and which lines actually moved.

    Matching is by description+unit rather than line id, because a proposal
    may drop a line, add one, or renumber — the Director cares about the item,
    not the row it happened to sit on.
    """
    revision = pending_revision(po)
    if revision is None:
        return None
    old, new = po.current_revision, revision
    before = [_line_view(ln) for ln in old.lines.all().order_by("line_no")]
    after = [_line_view(ln) for ln in new.lines.all().order_by("line_no")]
    def key(r):
        return (r["description"].strip().lower(), (r["unit"] or "").lower())

    b_by, a_by = {key(r): r for r in before}, {key(r): r for r in after}
    for r in after:
        prev = b_by.get(key(r))
        if prev is None:
            r["change"] = "added"
        elif prev["qty"] != r["qty"] or prev["rate"] != r["rate"]:
            r["change"] = "changed"
            r["was_qty"], r["was_rate"] = prev["qty"], prev["rate"]
        else:
            r["change"] = "same"
    dropped = [r for r in before if key(r) not in a_by]
    for r in dropped:
        r["change"] = "dropped"
    was, now = revision_total(old), revision_total(new)
    return {
        "reason": (new.payload or {}).get("amendment_reason", ""),
        "revision": new.rev_label, "from_revision": old.rev_label,
        "before": before, "after": after, "dropped": dropped,
        "was_total": was, "now_total": now, "delta": now - was,
        "proposed_by": (new.created_by.full_name if new.created_by_id else ""),
    }
