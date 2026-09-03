"""Procurement chain logic: MR → PR → LM → GRN (spec §4.3, §5.5–§5.8, §6)."""

from datetime import date
from decimal import Decimal

from .audit import audit
from .models import Document, DocumentLine, DocumentLink, Item, PendingItem


def line_key(data):
    if data.get("item_id"):
        return f"item:{data['item_id']}"
    return f"txt:{(data.get('free_text_desc') or '').strip().lower()}"


def mr_live_pr_refs(mr):
    """Refs of the live PRs being raised against this MR's current lines — an
    MR is locked from amendment while any exist, so a PR isn't orphaned
    mid-flight (owner 2026-07-31)."""
    rev = mr.current_revision
    if rev is None:
        return []
    from .models import Document
    ids = set(rev.lines.filter(
        ordered_pr__isnull=False, ordered_pr__is_void=False)
        .exclude(ordered_pr__status__in=["CANCELLED", "REJECTED"])
        .values_list("ordered_pr_id", flat=True))
    return list(Document.objects.filter(id__in=ids)
                .order_by("ref").values_list("ref", flat=True))


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
        new_line = DocumentLine.objects.create(
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
            credit_days=(int(data["credit_days"])
                         if str(data.get("credit_days") or "").strip().isdigit()
                         else None),
            action_taken=data.get("action_taken") or "",
            is_changed=is_changed,
            spec=data.get("spec") or "",
            mar_ref=data.get("mar_ref") or "",
            fulfil_source=data.get("fulfil_source") or "",
            store_issue_line_id=data.get("store_issue_line") or None,
            remarks=data.get("remarks") or "",
        )
        created.append(new_line)
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


def orderable_mr_lines(mr):
    """Current-revision MR lines that go through the local-purchase (PR) route
    and still need ordering — i.e. not store-issued and with something to
    order. These are the lines a PR can take."""
    rev = mr.current_revision
    if rev is None:
        return []
    return [ln for ln in rev.lines.all()
            if ln.fulfil_source != "STORE"
            and (ln.qty_to_order is None or ln.qty_to_order > 0)]


def active_pr_claimed_line_ids():
    """MR-line ids already taken by a live PR (not void/cancelled/rejected)."""
    from .models import DocumentLine
    return set(
        DocumentLine.objects.filter(
            ordered_pr__isnull=False, ordered_pr__is_void=False)
        .exclude(ordered_pr__status__in=["CANCELLED", "REJECTED"])
        .values_list("id", flat=True))


def remaining_mr_lines(mr, claimed=None):
    """Orderable MR lines not yet taken by a live PR."""
    if claimed is None:
        claimed = active_pr_claimed_line_ids()
    return [ln for ln in orderable_mr_lines(mr) if ln.id not in claimed]


def scope_pr_to_mr_lines(pr, mr_docs, line_ids):
    """Take the chosen MR lines for this PR. `line_ids` empty/None means the
    whole MR (every orderable line). Returns an error string on conflict."""
    from .models import DocumentLine
    claimed = active_pr_claimed_line_ids()
    orderable = {}
    for mr in mr_docs:
        for ln in orderable_mr_lines(mr):
            orderable[ln.id] = ln
    if line_ids:
        targets = []
        for lid in line_ids:
            ln = orderable.get(lid)
            if ln is None:
                return (f"Item {lid} isn't an orderable line on the selected "
                        f"MR(s).")
            if ln.id in claimed:
                return f"“{ln.description}” is already on another PR."
            targets.append(ln)
    else:
        targets = [ln for ln in orderable.values() if ln.id not in claimed]
    for ln in targets:
        ln.ordered_pr = pr
    DocumentLine.objects.bulk_update(targets, ["ordered_pr"])
    return None


def pr_scope_line_ids(pr):
    """The MR-line ids a PR is responsible for: the lines explicitly scoped to
    it (ordered_pr), PLUS any it has quotation-matched. An empty set means the
    PR hasn't been scoped and hasn't matched anything — callers then fall back
    to the whole linked MR. This keeps a legacy PR (scoped to nothing by the
    one-time backfill because an older PR on the same MR grabbed the lines
    first) anchored to what it actually quoted, not the entire MR."""
    from .models import DocumentLine, QuotationLine
    scoped = set(DocumentLine.objects.filter(ordered_pr=pr)
                 .values_list("id", flat=True))
    matched = set(QuotationLine.objects.filter(
        quotation__document=pr, mr_line__isnull=False)
        .values_list("mr_line_id", flat=True))
    return scoped | matched


def release_pr_lines(pr, line_ids, actor):
    """Return MR lines from an in-progress PR to the open pool, so a purchaser
    who can't source them on this PR can raise another PR for them (owner
    2026-07-15). Only before the PR is committed; awarded lines stay put (they
    are being ordered). `line_ids` empty = release everything not yet awarded.
    Returns (released_count, error)."""
    from .models import DocumentLine, QuotationLine
    if pr.status not in ("DRAFT", "SUBMITTED"):
        return 0, "You can only change a PR's items before it is approved."
    # Operate on the PR's whole item set (scoped + quotation-matched), so a
    # matched-but-unscoped line can still be removed.
    scope = pr_scope_line_ids(pr)
    if line_ids:
        scope &= set(line_ids)
    awarded = set(QuotationLine.objects.filter(
        quotation__document=pr, awarded=True, mr_line__isnull=False)
        .values_list("mr_line_id", flat=True))
    ids = [lid for lid in scope if lid not in awarded]
    if ids:
        # clear any scope claim, and drop the non-awarded quote matches
        DocumentLine.objects.filter(id__in=ids).update(ordered_pr=None)
        QuotationLine.objects.filter(
            quotation__document=pr, mr_line_id__in=ids).update(mr_line=None)
    audit("document", pr.id, "PR_LINES_RELEASED", actor=actor,
          detail={"ref": pr.ref, "count": len(ids)})
    return len(ids), None


def on_pr_approved(pr, actor):
    """Issuing a PR against an MR marks the MR PR-raised (spec §4.3). When the
    PR only covered some of a long MR, the MR goes to Partially Ordered and
    stays open for further PRs (owner 2026-07-15).

    The Director's approval is the award, so this is where the credit orders
    are drafted. They used to be generated only once a Finance payment voucher
    was signed, which held every order behind a payment run (owner
    2026-08-22); Purchasing now sends each drafted order for the Signatory's
    approval itself.
    """
    claimed = active_pr_claimed_line_ids()
    for mr in linked_docs(pr, "MR_PR", "from"):  # link rows: PR → MR
        target = "PR_RAISED" if not remaining_mr_lines(mr, claimed) \
            else "PARTIALLY_ORDERED"
        set_status(mr, target, actor, "MR_PR_RAISED")
    generate_pos_for_pr(pr, actor)


def on_lm_departed(lm, actor):
    """LM issue side effects (spec §4.3/§6): MR statuses, pending items
    creation, and clearing of older pending items now shipped."""
    revision = lm.current_revision
    lines = list(revision.lines.select_related("item"))
    has_pending = any((line.qty_pending or 0) > 0 for line in lines)

    prs = linked_docs(lm, "PR_LM", "from")  # link rows: LM → PR
    pr_by_any = prs[0] if prs else None

    for mr in linked_docs(lm, "MR_LM", "from"):  # link rows: LM → MR
        if mr.status in ("SENT_TO_HO", "PR_RAISED", "PARTIALLY_ORDERED"):
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
    from .imports import receive_store_issue_line

    lines = list(grn.current_revision.lines.select_related(
        "item", "store_issue_line").all())
    shortage = any(
        (line.qty_received or 0) < (line.qty_manifest or 0) for line in lines
    )
    for lm in linked_docs(grn, "LM_GRN", "from"):  # link rows: GRN → LM
        set_status(lm, "RECEIVED_WITH_SHORTAGE" if shortage else "RECEIVED",
                   actor, "LM_RECEIVED")

    for line in lines:
        qty = line.qty_received or 0
        # A store-issued line becomes project cost here — INCURRED at landed
        # cost, and its SIN advances to Received (P1B-f3).
        if line.store_issue_line_id and qty > 0:
            receive_store_issue_line(line.store_issue_line, qty, grn.site, grn,
                                     actor)
        if not (line.item_id and qty > 0):
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
            # carry a store-issued line through so the GRN can receive it and
            # post its landed cost (P1B-f3)
            "fulfil_source": line.fulfil_source or "",
            "store_issue_line": line.store_issue_line_id,
            "remarks": "",
        })
    return rows


def manifest_keys(lm):
    """The items on a manifest — item ids + free-text descriptions (lowered) —
    so a GRN can be checked to receive ONLY what was manifested."""
    ids, texts = set(), set()
    for ln in lm.current_revision.lines.all():
        if ln.item_id:
            ids.add(ln.item_id)
        elif ln.free_text_desc:
            texts.add(ln.free_text_desc.strip().lower())
    return ids, texts


def grn_offmanifest_line(lines_data, lm):
    """The description of the first GRN line whose item isn't on the manifest, or
    None. A GRN raised against a manifest can only receive manifested items —
    extras must be added to the manifest by Purchasing first (owner 2026-08-05)."""
    ids, texts = manifest_keys(lm)
    for ln in lines_data:
        iid = ln.get("item_id")
        txt = (ln.get("free_text_desc") or "").strip()
        if iid:
            if iid in ids:
                continue
            item = Item.objects.filter(pk=iid).first()
            return (item.description if item else None) or txt or "an item"
        if txt:
            if txt.lower() in texts:
                continue
            return txt
    return None


def reopen_grn(grn, actor):
    """Admin re-opens a wrongly-verified GRN back to Draft so the received
    quantities can be corrected and re-verified. Reverses the stock this GRN
    added and resets the manifest to in-transit. Refuses when the goods can't be
    cleanly unwound — already issued from stock, received as a tool/asset, or a
    store transfer — since those must be voided and re-raised (owner 2026-08-05)."""
    from django.db import transaction

    from . import stock, tools
    from .models import StockMovement
    if grn.doc_type != "GRN":
        return "Only a GRN can be re-opened."
    if grn.status not in ("SHORTAGE_REPORTED", "COMPLETE"):
        return "Only a verified GRN can be re-opened."
    lines = list(grn.current_revision.lines.select_related("item").all())
    for line in lines:
        qty = line.qty_received or Decimal("0")
        if qty <= 0:
            continue
        name = (line.item.description if line.item_id
                else line.free_text_desc) or "an item"
        if line.store_issue_line_id:
            return (f"'{name}' was received as a store transfer (SIN) — re-open "
                    "isn't supported. Void this GRN and raise a corrected one.")
        if line.item_id and tools.is_tool_item(line.item):
            return (f"'{name}' was received as a tool/asset — re-open isn't "
                    "supported. Void this GRN and raise a corrected one.")
        if line.item_id and stock.balance(grn.site, line.item) < qty:
            return (f"Some of '{name}' has already been issued from stock — "
                    "re-open isn't safe. Adjust the stock instead, or void and "
                    "re-raise this GRN.")
    with transaction.atomic():
        StockMovement.objects.filter(
            document=grn, kind=StockMovement.Kind.RECEIPT).delete()
        for lm in linked_docs(grn, "LM_GRN", "from"):
            lm.status = "DEPARTED"                # back to in-transit
            lm.save(update_fields=["status", "updated_at"])
        rev = grn.current_revision
        if rev.issued_at is not None:            # unlock the locked revision
            rev.issued_at = None
            rev.save(update_fields=["issued_at"])
        grn.status = "DRAFT"                      # editable again for correction
        grn.save(update_fields=["status", "updated_at"])
    audit("document", grn.id, "GRN_REOPENED", actor=actor,
          detail={"ref": grn.ref})
    return None


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

    # Orders are drafted at award now, so this can be reached twice — a PR
    # returned to draft and approved again. One order per awarded vendor:
    # anything already cut for that vendor stands.
    rev = pr.current_revision
    rows = list(rev.lines.all()) if rev else []
    already = {ln.vendor for ln in rows if ln.po_ref.strip()}
    by_supplier = {sup: qls for sup, qls in by_supplier.items()
                   if sup.name not in already}
    # A credit row entered straight on the PR, with no quotation behind it,
    # still commits money to a vendor. It gets an order of its own so that
    # every credit commitment is one a signatory has signed — under the old
    # voucher route these rows were committed with no order at all.
    quoted = {sup.name for sup in by_supplier}
    bare = [ln for ln in rows
            if (ln.amount_credit or 0) > 0 and not ln.po_ref.strip()
            and (ln.vendor or "").strip()
            and ln.vendor not in quoted and ln.vendor not in already]

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
    for ln in bare:
        created.append(_po_from_pr_row(pr, ln, actor))
    advance_pr_settlement(pr, actor)
    return created


def _po_from_pr_row(pr, ln, actor):
    """An order cut straight from a PR vendor row (no quotation behind it)."""
    from django.db import transaction

    from .models import DocumentRevision
    from .numbering import next_ref

    with transaction.atomic():
        po = Document.objects.create(
            doc_type="PO", ref=next_ref("PO", pr.site), site=pr.site,
            doc_date=date.today(), status="DRAFT", created_by=actor)
        revision = DocumentRevision.objects.create(
            document=po, rev_label="R0", created_by=actor,
            payload={"pr_ref": pr.ref,        # internal only — not on the PDF
                     "supplier_name": ln.vendor,
                     "payment_terms": ln.payment_terms or "Credit"})
        po.current_revision = revision
        po.save(update_fields=["current_revision"])
        DocumentLine.objects.create(
            revision=revision, line_no=1, item=ln.item,
            free_text_desc=ln.free_text_desc or ln.vendor,
            unit=ln.unit, qty_required=ln.qty_required,
            rate=ln.rate, amount=ln.amount_credit, remarks=ln.remarks)
        link_documents(po, pr, "PR_PO")
        ln.po_ref = po.ref
        ln.save(update_fields=["po_ref"])
    audit("document", po.id, "PO_GENERATED", actor=actor,
          detail={"ref": po.ref, "pr": pr.ref, "supplier": ln.vendor,
                  "from_row": True})
    return po


def advance_pr_settlement(pr, actor):
    """PR status follows the vendor rows: a row is settled by a payment
    slip (cash) or a generated PO (credit). All settled -> PAID_PO_ISSUED;
    some -> PAYMENT_PROCESSING (R3 addendum).

    A zero-value row (a captured quotation with nothing awarded — a losing
    bid) has nothing to pay or order, so it counts as already settled; it must
    not hold the PR open forever (owner 2026-07-16)."""
    lines = list(pr.current_revision.lines.all())
    if not lines:
        return

    def _net(ln):
        return (ln.amount_cash or 0) + (ln.amount_credit or 0)

    issued_pos = set(Document.objects.filter(
        doc_type="PO", ref__in=[ln.po_ref.strip() for ln in lines
                                if ln.po_ref.strip()],
        status__in=("ISSUED", "AMENDMENT_PENDING", "CLOSED")
    ).values_list("ref", flat=True))

    def _acted(ln):
        # A drafted PO is not an order yet — it settles the row once the
        # Signatory has approved it and it has issued. Counting the draft
        # marked the PR settled the moment the Director approved it (owner
        # 2026-08-22).
        return bool(ln.action_taken.strip()
                    or (ln.po_ref.strip() in issued_pos))

    settled = [ln for ln in lines if _acted(ln) or _net(ln) <= 0]
    if len(settled) == len(lines):
        set_status(pr, "PAID_PO_ISSUED", actor, "PR_SETTLED")
    elif any(_acted(ln) for ln in lines):
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


def _ho_site():
    from .vouchers import ho_site
    return ho_site()


def company_gst_rate():
    """The company GST rate (%), default 8. Applied to a registered vendor's
    awarded net at PR-matching time (owner 2026-07-13)."""
    from .models import CompanyParameter
    try:
        v = CompanyParameter.objects.get(key="gst_rate").value
        return Decimal(str(v))
    except (CompanyParameter.DoesNotExist, Exception):
        return Decimal("8")


def sync_pr_vendor_rows(pr):
    """Vendor-summary rows derived from captured quotations (R2): one row
    per supplier, cash vs credit split by the quotation's payment terms.
    Totals count AWARDED lines only — what we actually intend to buy;
    quotes with nothing awarded still appear (total 0) for the record.
    GST is added per vendor (registered = quotation.gst_applicable) at the
    company rate on the awarded net; amount_cash/amount_credit stay NET.

    Rows are updated IN PLACE, never deleted and recreated. A PR that was
    authorised and then withdrawn keeps its cost postings — the originals
    and the reversing mirrors — and every one of them points at a vendor
    row. Rebuilding by delete raised ProtectedError, and PR-159 could not
    take, edit or remove a single quotation after Finance sent it back
    (owner 2026-09-03). A row a quotation no longer backs is deleted only
    when nothing in the ledger refers to it; otherwise it stays at zero,
    saying why."""
    from .models import CostPosting
    revision = pr.current_revision
    existing = {}
    for ln in revision.lines.all():
        # Two quotations from one supplier used to make two rows; keep the
        # first for the name and let the second fall through to create.
        existing.setdefault((ln.vendor or "").strip(), ln)
    rate = company_gst_rate()
    keep, line_no = set(), 0
    for quotation in pr.quotations.select_related("supplier") \
            .prefetch_related("lines"):
        all_lines = list(quotation.lines.all())
        awarded = [line for line in all_lines if line.awarded]
        total = sum((line.amount or Decimal("0")) for line in awarded)
        gst = ((total * rate / Decimal("100")).quantize(Decimal("0.01"))
               if quotation.gst_applicable else Decimal("0"))
        is_credit = "credit" in (quotation.payment_terms or "").lower()
        line_no += 1
        name = quotation.supplier.name
        fields = dict(
            line_no=line_no, free_text_desc=name, vendor=name,
            quotation_ref=quotation.quote_ref,
            payment_terms=quotation.payment_terms,
            # The supplier's agreed credit period, so the payable's due date
            # follows it (owner 2026-08-22). Purchasing can still override
            # it on the row.
            credit_days=(quotation.supplier.credit_days
                         if is_credit else None),
            purchase_type="CREDIT" if is_credit else "CASH",
            amount_cash=None if is_credit else total,
            amount_credit=total if is_credit else None,
            gst_amount=gst,
            remarks=f"{len(awarded)}/{len(all_lines)} lines awarded",
        )
        ln = existing.pop(name.strip(), None) if name.strip() not in keep \
            else None
        if ln is None:
            ln = DocumentLine.objects.create(revision=revision, **fields)
        else:
            for k, v in fields.items():
                setattr(ln, k, v)
            ln.save(update_fields=list(fields))
        keep.add(ln.id)
    for ln in existing.values():
        if CostPosting.objects.filter(document_line=ln).exists():
            line_no += 1
            ln.line_no = line_no
            ln.amount_cash = ln.amount_credit = None
            ln.gst_amount = Decimal("0")
            ln.remarks = "quotation removed — row kept for the cost ledger"
            ln.save(update_fields=["line_no", "amount_cash", "amount_credit",
                                   "gst_amount", "remarks"])
        else:
            ln.delete()


# ===== PR signatory authorisation + cost postings (M6c) =====

def pr_net_total(pr):
    total = Decimal("0")
    for ln in pr.current_revision.lines.all():
        total += (ln.amount_cash or 0) + (ln.amount_credit or 0)
    return total


def pr_gst_total(pr):
    return sum((ln.gst_amount or Decimal("0"))
               for ln in pr.current_revision.lines.all())


def pr_grand_total(pr):
    """The whole committed value of a PR — net + GST (gross), cash and credit."""
    return pr_net_total(pr) + pr_gst_total(pr)


def _gst_share(ln, portion):
    """The GST belonging to one side of a part-cash / part-credit vendor row.

    A row's GST is stated once for the whole line, so splitting the row across
    two authorisation routes has to split the tax with it — otherwise the cash
    voucher and the credit order each claim the full input tax.
    """
    net = (ln.amount_cash or 0) + (ln.amount_credit or 0)
    gst = ln.gst_amount or 0
    if gst <= 0 or net <= 0:
        return Decimal("0")
    return (Decimal(str(gst)) * Decimal(str(portion))
            / Decimal(str(net))).quantize(Decimal("0.01"))


def pr_cash_total(pr):
    """The CASH portion of a PR (gross) — what is actually paid on a payment
    voucher. Credit lines are committed as payables and settled separately, so
    they never appear on the voucher (owner 2026-07-16)."""
    total = Decimal("0")
    for ln in pr.current_revision.lines.all():
        cash = ln.amount_cash or 0
        if cash > 0:
            # On a row that is part cash and part credit the stated GST covers
            # both, so only the cash share is paid here — the rest rides with
            # the credit order (owner 2026-08-22).
            total += cash + _gst_share(ln, cash)
    return total


def _post_pr_line(pr, ln, amount, gst, actor):
    """Post COMMITTED + INCURRED for one side of a vendor row.

    Owner decision (M7): materials are Incurred at authorisation, not at GRN
    receipt. The spec (§6C.3.1) puts the Incurred trigger at the GRN, but that
    needs a landed-cost/inventory valuation the business does not yet run;
    until then, ordering a material is treated as consuming it. The GRN stays
    a delivery/QA record with no cost event. Paid posts at vendor payment.
    """
    from . import costing
    from .models import CostHead

    if amount <= 0:
        return
    head = ln.cost_head or CostHead.objects.get(name="Materials")
    gst_head = CostHead.objects.filter(name=costing.INPUT_GST_HEAD).first()
    # Net is the project cost; GST is recoverable input tax (not a project
    # cost) — posted to the Input GST account at HO (owner 2026-07-13).
    for state in ("COMMITTED", "INCURRED"):
        costing.post(site=pr.site, cost_head=head, state=state,
                     source="PR", amount=amount, document=pr,
                     document_line=ln, actor=actor)
        if gst > 0 and gst_head is not None:
            costing.post(site=_ho_site(), cost_head=gst_head, state=state,
                         source="PR", amount=gst, document=pr,
                         document_line=ln, is_stock_pool=True, actor=actor)


def authorise_pr(pr, actor):
    """Signatory approval of the PR's CASH side on a Payment Voucher.

    Only cash reaches a voucher now. A credit purchase is a commitment, not a
    payment: its order is signed on the PO itself and its cost posts there
    (owner 2026-08-22). A PR with no cash never goes to Finance at all until
    the payable falls due.
    """
    for ln in pr.current_revision.lines.all():
        cash = ln.amount_cash or 0
        if cash > 0:
            _post_pr_line(pr, ln, cash, _gst_share(ln, cash), actor)


def po_source_pr(po):
    """The PR a generated PO came from."""
    # link_documents(po, pr, "PR_PO") stores from=PO, to=PR, so the PR is
    # reached in the "from" direction.
    found = linked_docs(po, "PR_PO", "from")
    return found[0] if found else None


def po_pr_line(po, pr=None):
    """The PR's vendor row this PO was cut from (matched by the stamped ref)."""
    pr = pr or po_source_pr(po)
    if pr is None or pr.current_revision is None:
        return None
    return pr.current_revision.lines.filter(po_ref=po.ref).first()


def po_credit_total(po):
    """What this order commits — the credit amount of its PR row, gross of
    GST, which is what we will owe the supplier."""
    ln = po_pr_line(po)
    if ln is None:
        return Decimal("0")
    credit = ln.amount_credit or Decimal("0")
    return Decimal(str(credit)) + _gst_share(ln, credit)


def credit_period_for(ln):
    """(days, terms text) for a credit row's payable.

    The row's own period wins; failing that, the period agreed with the
    supplier on its record; failing both, 30 — and the terms say so. The 30
    used to be silent, which is how two months of a 60-day supplier's orders
    were booked a month early without anyone seeing it (owner 2026-08-22).
    """
    from .models import Supplier
    if ln.credit_days is not None:
        return ln.credit_days, (ln.payment_terms or f"{ln.credit_days} days")
    sup = Supplier.objects.filter(name=(ln.vendor or "").strip()).first()
    if sup is not None and sup.credit_days is not None:
        base = ln.payment_terms or "Credit"
        return sup.credit_days, f"{base} · {sup.credit_days} days (supplier terms)"
    base = ln.payment_terms or "Credit"
    return 30, f"{base} · 30 days (no agreed period on file)"


def _already_committed(pr, ln):
    """Net COMMITTED already on the ledger for one vendor row (excluding the
    recoverable-GST pool, which is not a project cost)."""
    from .models import CostPosting

    total = Decimal("0")
    for cp in CostPosting.objects.filter(document=pr, document_line=ln,
                                         state="COMMITTED",
                                         is_stock_pool=False):
        total += cp.amount
    return total


def is_local_credit_po(po):
    """Is this a local credit order raised off a PR?

    An import order's PO comes from an IPR instead, and its commitment was
    already authorised by a signatory on the IPR itself — it must not be sent
    round the local signature loop a second time (owner 2026-08-22).
    """
    return po.doc_type == "PO" and po_source_pr(po) is not None


def po_commitment(po):
    """(pr, vendor row, error) for an order about to be signed. Resolved
    before the status moves, so a broken link cannot leave an order issued
    with nothing committed behind it."""
    pr = po_source_pr(po)
    if pr is None:
        return None, None, "This order is not linked to a purchase request."
    ln = po_pr_line(po, pr)
    if ln is None:
        return None, None, f"{pr.ref} has no vendor row for {po.ref}."
    return pr, ln, None


def issue_po(po, actor):
    """A Signatory has signed the order: commit its cost, record what we will
    owe the supplier, and let the PR move on.

    This is the step that used to happen inside a Finance payment voucher. A
    purchase order is a commitment, not a payment — putting it through a
    payment instrument meant Purchasing could not place an order until Finance
    ran a voucher, and made Finance the gatekeeper of a purchasing document
    (owner 2026-08-22).
    """
    from datetime import timedelta

    from .models import Payable

    pr, ln, err = po_commitment(po)
    if err:
        return err
    credit = ln.amount_credit or Decimal("0")
    gst = _gst_share(ln, credit)
    # Orders drafted before this change belong to PRs that were already
    # authorised the old way, so their cost is already on the ledger. Posting
    # again on signature would double-count it — and `costing.post` is an
    # append-only writer, so nothing else would stop it (owner 2026-08-22).
    if _already_committed(pr, ln) < ((ln.amount_cash or 0) + credit):
        _post_pr_line(pr, ln, credit, gst, actor)
    if credit > 0 and not Payable.objects.filter(
            document=pr, document_line=ln).exists():
        # We owe the vendor the gross (net + GST).
        days, terms = credit_period_for(ln)
        Payable.objects.create(
            document=pr, document_line=ln, site=pr.site,
            vendor=ln.vendor or ln.free_text_desc,
            terms=terms, amount=credit + gst,
            due_date=date.today() + timedelta(days=days))
    audit("document", po.id, "PO_AUTHORISED", actor=actor,
          detail={"ref": po.ref, "pr": pr.ref, "amount": str(credit + gst)})
    advance_pr_settlement(pr, actor)
    return None


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

    net = (line.amount_cash or 0) + (line.amount_credit or 0)
    gst = line.gst_amount or 0
    if net > 0:
        materials = CostHead.objects.get(name="Materials")
        costing.post(site=pr.site, cost_head=line.cost_head or materials,
                     state="PAID", source="PR", amount=net, document=pr,
                     document_line=line, actor=actor)
        gst_head = CostHead.objects.filter(name=costing.INPUT_GST_HEAD).first()
        if gst > 0 and gst_head is not None:
            costing.post(site=_ho_site(), cost_head=gst_head, state="PAID",
                         source="PR", amount=gst, document=pr,
                         document_line=line, is_stock_pool=True, actor=actor)
    Payable.objects.filter(document=pr, document_line=line,
                           status="OUTSTANDING").update(
        status="SETTLED", settled_on=date.today(), settled_ref=ref)
