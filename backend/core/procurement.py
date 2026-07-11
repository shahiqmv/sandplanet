"""Procurement chain logic: MR → PR → LM → GRN (spec §4.3, §5.5–§5.8, §6)."""

from datetime import date
from decimal import Decimal

from .audit import audit
from .models import Document, DocumentLine, DocumentLink, Item, PendingItem


def line_key(data):
    if data.get("item_id"):
        return f"item:{data['item_id']}"
    return f"txt:{(data.get('free_text_desc') or '').strip().lower()}"


COMPARE_FIELDS = ["qty_required", "qty_stock", "qty_to_order", "priority",
                  "remarks", "qty_loaded", "qty_pending", "vendor",
                  "amount_cash", "amount_credit"]


def save_lines(revision, lines_data, previous_revision=None):
    """Replace the draft revision's lines. On MR amendments, new or changed
    lines are auto-flagged (spec §5.5 rule 3)."""
    revision.lines.all().delete()
    previous = {}
    if previous_revision is not None:
        for pl in previous_revision.lines.select_related("item"):
            key = f"item:{pl.item_id}" if pl.item_id else \
                  f"txt:{(pl.free_text_desc or '').strip().lower()}"
            previous[key] = pl
    created = []
    for i, data in enumerate(lines_data, start=1):
        item = None
        if data.get("item_id"):
            item = Item.objects.get(pk=data["item_id"], is_active=True)
            if item.merged_into_id:
                item = item.merged_into
        unit = item.unit if item else (data.get("unit") or "")
        is_changed = False
        if previous_revision is not None:
            old = previous.get(line_key(data))
            if old is None:
                is_changed = True  # new line
            else:
                for f in COMPARE_FIELDS:
                    new_val = data.get(f)
                    old_val = getattr(old, f)
                    if old_val is not None and isinstance(old_val, Decimal):
                        old_val = float(old_val)
                    if new_val not in (None, "") or old_val not in (None, ""):
                        if (new_val is None and old_val is not None) or \
                           (new_val is not None and old_val is None) or \
                           (new_val is not None and old_val is not None and
                                str(new_val) != str(old_val) and
                                _num(new_val) != _num(old_val)):
                            is_changed = True
                            break
        created.append(DocumentLine.objects.create(
            revision=revision,
            line_no=i,
            item=item,
            free_text_desc="" if item else (data.get("free_text_desc") or ""),
            unit=unit,
            qty_required=_dec(data.get("qty_required")),
            qty_stock=_dec(data.get("qty_stock")),
            qty_to_order=_dec(data.get("qty_to_order")),
            qty_loaded=_dec(data.get("qty_loaded")),
            qty_pending=_dec(data.get("qty_pending")),
            qty_manifest=_dec(data.get("qty_manifest")),
            qty_received=_dec(data.get("qty_received")),
            priority=data.get("priority") or "",
            urgent_reason=data.get("urgent_reason") or "",
            amount_cash=_dec(data.get("amount_cash")),
            amount_credit=_dec(data.get("amount_credit")),
            rate=_dec(data.get("rate")),
            amount=_dec(data.get("amount")),
            vendor=data.get("vendor") or "",
            quotation_ref=data.get("quotation_ref") or "",
            payment_terms=data.get("payment_terms") or "",
            action_taken=data.get("action_taken") or "",
            is_changed=is_changed,
            remarks=data.get("remarks") or "",
        ))
    return created


def _dec(value):
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def validate_mr_lines(lines_data):
    """MR rules (spec §5.5): urgent lines need a reason; every line needs an
    item or flagged free text."""
    for i, data in enumerate(lines_data, start=1):
        if not data.get("item_id") and not (data.get("free_text_desc") or "").strip():
            return f"Line {i}: pick a catalog item or enter a flagged new-item description."
        if (data.get("priority") or "").upper() == "URGENT" and \
                not (data.get("urgent_reason") or "").strip():
            return f"Line {i}: urgent priority requires a reason (MR rule 4)."
    return None


def link_documents(from_doc, to_doc, link_type):
    DocumentLink.objects.get_or_create(
        from_document=from_doc, to_document=to_doc, link_type=link_type
    )


def linked_docs(doc, link_type, direction="from"):
    if direction == "from":
        rows = doc.links_from.filter(link_type=link_type).select_related("to_document")
        return [r.to_document for r in rows]
    rows = doc.links_to.filter(link_type=link_type).select_related("from_document")
    return [r.from_document for r in rows]


def resolve_refs(refs, doc_type):
    docs = list(Document.objects.filter(ref__in=refs or [], doc_type=doc_type,
                                        is_void=False))
    missing = set(refs or []) - {d.ref for d in docs}
    return docs, missing


def set_status(doc, new_status, actor, event):
    """System transition with audit; ignores if already there or invalid."""
    if doc.status == new_status:
        return
    allowed = Document.TRANSITIONS.get(doc.doc_type, {}).get(doc.status, set())
    if new_status not in allowed:
        return
    old = doc.status
    doc.status = new_status
    doc.save(update_fields=["status", "updated_at"])
    audit("document", doc.id, event, actor=actor, from_state=old,
          to_state=new_status, detail={"ref": doc.ref})


def on_pr_approved(pr, actor):
    """Spec §4.3: issuing a PR against an MR sets the MR to PR Raised."""
    for mr in linked_docs(pr, "MR_PR", "from"):  # link rows: PR → MR
        set_status(mr, "PR_RAISED", actor, "MR_PR_RAISED")


def on_lm_departed(lm, actor):
    """LM issue side effects (spec §4.3/§6): MR statuses, pending items
    creation, and clearing of older pending items now shipped."""
    revision = lm.current_revision
    lines = list(revision.lines.select_related("item"))
    has_pending = any((line.qty_pending or 0) > 0 for line in lines)

    prs = linked_docs(lm, "PR_LM", "from")  # link rows: LM → PR
    pr_by_any = prs[0] if prs else None

    for mr in linked_docs(lm, "MR_LM", "from"):  # link rows: LM → MR
        if mr.status in ("SENT_TO_HO", "PR_RAISED"):
            set_status(mr, "LOADING_PLANNED", actor, "MR_LOADING_PLANNED")
        set_status(mr, "PARTIALLY_LOADED" if has_pending else "LOADED",
                   actor, "MR_LOADING_UPDATED")

    # Auto-create pending log entries (every qty_pending > 0 line)
    for line in lines:
        if (line.qty_pending or 0) > 0:
            PendingItem.objects.create(
                lm_line=line, site=lm.site, pr_document=pr_by_any,
                item=line.item,
                free_text_desc=line.free_text_desc,
                unit=line.unit, qty_pending=line.qty_pending,
            )
    # Auto-clear older pending entries for items this LM now ships in full
    shipped_items = {line.item_id for line in lines
                     if line.item_id and (line.qty_loaded or 0) > 0
                     and (line.qty_pending or 0) == 0}
    if shipped_items:
        stale = PendingItem.objects.filter(
            site=lm.site, status="PENDING", item_id__in=shipped_items
        ).exclude(lm_line__revision__document=lm)
        for row in stale:
            row.status = "CLEARED"
            row.cleared_date = date.today()
            row.cleared_lm = lm
            row.save(update_fields=["status", "cleared_date", "cleared_lm"])
            audit("pending_item", row.id, "PENDING_CLEARED", actor=actor,
                  detail={"lm": lm.ref})


def on_grn_verified(grn, actor):
    """GRN verify: complete/shortage result + LM status (spec §5.6), and route
    received quantities — tool-category items become individual assets on the
    site Tools & Equipment register; everything else adds to site stock."""
    from . import stock, tools  # local import to avoid a cycle at module load

    lines = list(grn.current_revision.lines.all())
    shortage = any(
        (line.qty_received or 0) < (line.qty_manifest or 0) for line in lines
    )
    for lm in linked_docs(grn, "LM_GRN", "from"):  # link rows: GRN → LM
        set_status(lm, "RECEIVED_WITH_SHORTAGE" if shortage else "RECEIVED",
                   actor, "LM_RECEIVED")

    for line in lines:
        if not (line.item_id and (line.qty_received or 0) > 0):
            continue
        if tools.is_tool_item(line.item):
            tools.create_from_grn(grn, line, line.qty_received, actor)
        else:
            stock.record_receipt(grn.site, line.item, line.qty_received,
                                 document=grn, actor=actor,
                                 movement_date=grn.doc_date)
    return shortage


def grn_lines_from_lm(lm):
    """Prefill GRN lines from the manifest (spec §5.6)."""
    rows = []
    for line in lm.current_revision.lines.select_related("item"):
        rows.append({
            "item_id": line.item_id,
            "free_text_desc": line.free_text_desc,
            "unit": line.unit,
            "qty_manifest": float(line.qty_loaded) if line.qty_loaded else 0,
            "qty_received": None,
            "remarks": "",
        })
    return rows


def next_item_code():
    from .numbering import next_ref  # avoid circular import at module load

    # Reuse the doc counter machinery: gap-free, row-locked
    ref = next_ref("ITM", None)
    return f"ITM-{int(ref.split('-')[1]):05d}"


def generate_pos_for_pr(pr, actor):
    """On Director approval of the PR (award), generate one draft PO per
    awarded CREDIT supplier from the awarded quotation lines (R2/R3).
    Cash purchases settle by payment slip — no PO (owner, 2026-07-08)."""
    from .models import DocumentRevision, QuotationLine
    from .numbering import next_ref
    from django.db import transaction

    awarded = (
        QuotationLine.objects.filter(quotation__document=pr, awarded=True)
        .select_related("quotation__supplier", "mr_line__item")
        .order_by("quotation__supplier_id", "line_no")
    )
    by_supplier = {}
    for ql in awarded:
        if "credit" not in (ql.quotation.payment_terms or "").lower():
            continue  # cash purchase — settled by slip, no PO
        by_supplier.setdefault(ql.quotation.supplier, []).append(ql)

    created = []
    for supplier, quote_lines in by_supplier.items():
        with transaction.atomic():
            ref = next_ref("PO", pr.site)
            po = Document.objects.create(
                doc_type="PO", ref=ref, site=pr.site, doc_date=date.today(),
                status="DRAFT", created_by=actor, supplier=supplier,
                previous_ir=None,
            )
            quotation = quote_lines[0].quotation
            revision = DocumentRevision.objects.create(
                document=po, rev_label="R0", created_by=actor,
                payload={
                    "pr_ref": pr.ref,  # internal only — never on the PO PDF
                    "supplier_name": supplier.name,
                    "supplier_contact": supplier.contact_person,
                    "quote_ref": quotation.quote_ref,
                    "payment_terms": quotation.payment_terms,
                    "expected_delivery": (pr.current_revision.payload or {})
                    .get("requested_delivery", ""),
                },
            )
            po.current_revision = revision
            po.save(update_fields=["current_revision"])
            for i, ql in enumerate(quote_lines, start=1):
                mr_line = ql.mr_line
                DocumentLine.objects.create(
                    revision=revision, line_no=i,
                    item=mr_line.item if mr_line else None,
                    free_text_desc=(ql.supplier_desc
                                    if not (mr_line and mr_line.item)
                                    else ""),
                    unit=ql.unit or (mr_line.unit if mr_line else ""),
                    qty_required=ql.qty,
                    rate=ql.rate, amount=ql.amount,
                    remarks=ql.remarks,
                )
            link_documents(po, pr, "PR_PO")
            # PO ref lands in the matching vendor summary row (R3 addendum)
            pr.current_revision.lines.filter(vendor=supplier.name).update(
                po_ref=po.ref
            )
        audit("document", po.id, "PO_GENERATED", actor=actor,
              detail={"ref": po.ref, "pr": pr.ref, "supplier": supplier.name})
        created.append(po)
    advance_pr_settlement(pr, actor)
    return created


def advance_pr_settlement(pr, actor):
    """PR status follows the vendor rows: a row is settled by a payment
    slip (cash) or a generated PO (credit). All settled -> PAID_PO_ISSUED;
    some -> PAYMENT_PROCESSING (R3 addendum)."""
    lines = list(pr.current_revision.lines.all())
    if not lines:
        return
    settled = [ln for ln in lines
               if ln.action_taken.strip() or ln.po_ref.strip()]
    if len(settled) == len(lines):
        set_status(pr, "PAID_PO_ISSUED", actor, "PR_SETTLED")
    elif settled:
        set_status(pr, "PAYMENT_PROCESSING", actor, "PR_PARTIALLY_SETTLED")


def po_lm_prefill_lines(po):
    """LM lines from a PO: what was ordered from this supplier (R2)."""
    rows = []
    for line in po.current_revision.lines.select_related("item"):
        rows.append({
            "item_id": line.item_id,
            "free_text_desc": line.free_text_desc,
            "unit": line.unit,
            "qty_loaded": float(line.qty_required or 0),
            "qty_pending": 0,
            "remarks": line.remarks,
        })
    return rows


def sync_pr_vendor_rows(pr):
    """Vendor-summary rows derived from captured quotations (R2): one row
    per supplier, cash vs credit split by the quotation's payment terms.
    Totals count AWARDED lines only — what we actually intend to buy;
    quotes with nothing awarded still appear (total 0) for the record."""
    revision = pr.current_revision
    revision.lines.all().delete()
    line_no = 0
    for quotation in pr.quotations.select_related("supplier") \
            .prefetch_related("lines"):
        all_lines = list(quotation.lines.all())
        awarded = [line for line in all_lines if line.awarded]
        total = sum((line.amount or 0) for line in awarded)
        is_credit = "credit" in (quotation.payment_terms or "").lower()
        line_no += 1
        DocumentLine.objects.create(
            revision=revision, line_no=line_no,
            free_text_desc=quotation.supplier.name,
            vendor=quotation.supplier.name,
            quotation_ref=quotation.quote_ref,
            payment_terms=quotation.payment_terms,
            purchase_type="CREDIT" if is_credit else "CASH",
            amount_cash=None if is_credit else total,
            amount_credit=total if is_credit else None,
            remarks=f"{len(awarded)}/{len(all_lines)} lines awarded",
        )


# ===== PR signatory authorisation + cost postings (M6c) =====

def pr_grand_total(pr):
    total = Decimal("0")
    for ln in pr.current_revision.lines.all():
        total += (ln.amount_cash or 0) + (ln.amount_credit or 0)
    return total


def authorise_pr(pr, actor):
    """Signatory authorisation of a PR on a Payment Voucher (§6C.2 — the
    commitment point): post COMMITTED and INCURRED per vendor line (cost
    head from the line, default Materials), create payables for credit
    vendors, and generate the credit POs.

    Owner decision (M7): materials are Incurred at PV authorisation, not at
    GRN receipt. The spec (§6C.3.1) puts the Incurred trigger at the GRN,
    but that requires a landed-cost/inventory valuation the business does
    not yet run; until an inventory system exists, ordering a material on an
    authorised voucher is treated as consuming it. The GRN stays a delivery/
    QA record with no cost event. Paid still posts at vendor payment."""
    from datetime import timedelta

    from . import costing
    from .models import CostHead, Payable

    materials = CostHead.objects.get(name="Materials")
    for ln in pr.current_revision.lines.all():
        amount = (ln.amount_cash or 0) + (ln.amount_credit or 0)
        if amount <= 0:
            continue
        head = ln.cost_head or materials
        costing.post(site=pr.site, cost_head=head, state="COMMITTED",
                     source="PR", amount=amount, document=pr,
                     document_line=ln, actor=actor)
        costing.post(site=pr.site, cost_head=head, state="INCURRED",
                     source="PR", amount=amount, document=pr,
                     document_line=ln, actor=actor)
        if (ln.amount_credit or 0) > 0:
            Payable.objects.create(
                document=pr, document_line=ln, site=pr.site,
                vendor=ln.vendor or ln.free_text_desc,
                terms=ln.payment_terms or "", amount=ln.amount_credit,
                due_date=date.today() + timedelta(days=30))
    generate_pos_for_pr(pr, actor)


def reverse_pr_authorisation(pr, actor):
    """Finance withdrawal (§7.5b): reverse the PR's COMMITTED postings and
    cancel its outstanding payables. Issued POs are flagged to Purchasing
    for manual withdrawal."""
    from . import costing

    costing.reverse_document(pr, actor=actor)
    pr.payables.filter(status="OUTSTANDING").update(status="CANCELLED")


def post_pr_vendor_paid(pr, line, actor, ref):
    """PAID leg when Finance records a vendor payment / settlement (§4A).
    Settles the vendor's payable if credit."""
    from . import costing
    from .models import CostHead, Payable

    amount = (line.amount_cash or 0) + (line.amount_credit or 0)
    if amount > 0:
        materials = CostHead.objects.get(name="Materials")
        costing.post(site=pr.site, cost_head=line.cost_head or materials,
                     state="PAID", source="PR", amount=amount, document=pr,
                     document_line=line, actor=actor)
    Payable.objects.filter(document=pr, document_line=line,
                           status="OUTSTANDING").update(
        status="SETTLED", settled_on=date.today(), settled_ref=ref)
