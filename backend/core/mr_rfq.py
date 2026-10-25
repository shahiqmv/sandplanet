"""Requests for quotation on a material request (owner 2026-10-13).

Local purchasing asks suppliers for prices before it raises the PR.
Purchasing picks the MR's items, names the supplier (mandatory: the RFQ is a
record on the MR's history), adds a remark for the supplier, and prints the
same plain RFQ the procurement schedule prints — no freight or shipping
terms, this is local buying. The supplier's quote is uploaded against the
RFQ; when the PR is prepared, Purchasing picks it from there and the PR's
quotation is filled in from it: supplier, quote file, and the asked items
already matched to their MR lines.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .audit import audit
from .models import (AuditLog, MrRfq, MrRfqLine, Quotation,
                     QuotationLine, Supplier)

RFQ_ROLES = ("HO_PURCHASING", "ADMIN")
# an MR is at Head Office for buying from SENT_TO_HO until it is loaded
OPEN_STATUSES = ("SENT_TO_HO", "PARTIALLY_ORDERED", "PR_RAISED")


def next_rfq_ref(site):
    """RFQ-<site>-NNN, one sequence for the site's RFQs from the MR and from
    the procurement schedule."""
    n = (MrRfq.objects.filter(mr__site=site).count()
         + AuditLog.objects.filter(event="PSC_RFQ",
                                   detail__site=site.code).count() + 1)
    while True:
        ref = f"RFQ-{site.code}-{n:03d}"
        if not MrRfq.objects.filter(ref=ref).exists() and \
                not AuditLog.objects.filter(event="PSC_RFQ",
                                            detail__ref=ref).exists():
            return ref
        n += 1


def _qty(line):
    return line.qty_to_order if line.qty_to_order is not None \
        else line.qty_required


def orderable_lines(mr):
    """The MR's items Purchasing may ask a price for: the current revision's
    lines that are not being served from the store."""
    rev = mr.current_revision
    if rev is None:
        return []
    return [ln for ln in rev.lines.select_related("item").order_by("line_no")
            if ln.fulfil_source != "STORE"]


def _supplier(data, actor):
    """The named supplier: an existing one by id, or a new local supplier
    by name (matched case-insensitively first). Returns (supplier, error)."""
    sid = data.get("supplier_id")
    if sid:
        s = Supplier.objects.filter(pk=sid, is_active=True).first()
        return (s, None) if s else (None, "That supplier is not active.")
    name = (data.get("supplier_name") or "").strip()
    if not name:
        return None, "Name the supplier — the RFQ is kept on the MR's record."
    s = Supplier.objects.filter(name__iexact=name).first()
    if s:
        if not s.is_active:
            return None, f"{s.name} is marked inactive."
        return s, None
    s = Supplier.objects.create(name=name[:200], category="LOCAL")
    audit("supplier", s.id, "SUPPLIER_CREATED", actor=actor,
          detail={"name": s.name, "via": "MR RFQ"})
    return s, None


@transaction.atomic
def create(mr, data, actor):
    """Returns (rfq, error)."""
    if actor.role not in RFQ_ROLES:
        return None, "Purchasing sends requests for quotation."
    if mr.doc_type != "MR" or mr.is_void:
        return None, "Not a material request."
    if mr.status not in OPEN_STATUSES:
        return None, ("An RFQ is sent while the MR is with Purchasing — this "
                      f"one is {mr.status.replace('_', ' ').lower()}.")
    try:
        ids = {int(x) for x in (data.get("line_ids") or [])}
    except (TypeError, ValueError):
        return None, "Choose the items to ask for."
    lines = [ln for ln in orderable_lines(mr) if ln.id in ids]
    if not lines:
        return None, "Choose at least one item to ask a price for."
    if len(lines) != len(ids):
        return None, "Some of those items are not open on this MR."
    supplier, err = _supplier(data, actor)
    if err:
        return None, err
    rfq = MrRfq.objects.create(
        mr=mr, ref=next_rfq_ref(mr.site), supplier=supplier,
        remark=(data.get("remark") or "").strip(), created_by=actor)
    for ln in lines:
        MrRfqLine.objects.create(rfq=rfq, mr_line=ln, qty=_qty(ln))
    audit("document", mr.id, "MR_RFQ_SENT", actor=actor,
          detail={"ref": rfq.ref, "mr": mr.ref, "supplier": supplier.name,
                  "lines": len(lines)})
    return rfq, None


def _image(line):
    f = line.item.photo if line.item_id and line.item.photo else None
    if not f:
        return None
    try:
        return f"file:///{f.path}"
    except NotImplementedError:
        return f.url


def pdf_context(rfq):
    rows = []
    for i, rl in enumerate(rfq.lines.select_related("mr_line__item"),
                           start=1):
        ln = rl.mr_line
        rows.append({"no": i,
                     "description": (ln.item.description if ln.item_id
                                     else ln.free_text_desc),
                     "make": ln.item.brand if ln.item_id else "",
                     "spec": "", "qty": rl.qty, "uom": ln.unit,
                     "image": _image(ln)})
    return {"ref": rfq.ref, "supplier": rfq.supplier.name, "rows": rows,
            "remark": rfq.remark,
            "has_images": any(r["image"] for r in rows)}


def attach_quote(rfq, upload, data, actor):
    if actor.role not in RFQ_ROLES:
        return "Purchasing records the supplier's quote."
    if upload is None:
        return "Attach the quote the supplier sent."
    rfq.quote_file = upload
    rfq.quote_ref = (data.get("quote_ref") or "").strip()[:120]
    qd = data.get("quote_date") or None
    if qd:
        from datetime import date
        try:
            qd = date.fromisoformat(str(qd)[:10])
        except ValueError:
            return "The quote date is not a date."
    rfq.quote_date = qd
    rfq.received_by = actor
    rfq.received_at = timezone.now()
    rfq.save()
    audit("document", rfq.mr_id, "MR_RFQ_QUOTE_RECEIVED", actor=actor,
          detail={"ref": rfq.ref, "supplier": rfq.supplier.name})
    return None


def rfq_dict(rfq, request=None):
    def url(f):
        if not f:
            return None
        return request.build_absolute_uri(f.url) if request else f.url
    return {
        "id": rfq.id, "ref": rfq.ref, "mr_ref": rfq.mr.ref,
        "supplier_id": rfq.supplier_id, "supplier": rfq.supplier.name,
        "remark": rfq.remark, "created_at": rfq.created_at,
        "created_by": rfq.created_by.full_name,
        "lines": [{"mr_line": rl.mr_line_id,
                   "description": (rl.mr_line.item.description
                                   if rl.mr_line.item_id
                                   else rl.mr_line.free_text_desc),
                   "unit": rl.mr_line.unit, "qty": rl.qty}
                  for rl in rfq.lines.select_related("mr_line__item")],
        "quote_url": url(rfq.quote_file),
        "quote_name": (rfq.quote_file.name.rsplit("/", 1)[-1]
                       if rfq.quote_file else ""),
        "quote_ref": rfq.quote_ref, "quote_date": rfq.quote_date,
        "received_at": rfq.received_at,
        "received_by": rfq.received_by.full_name if rfq.received_by_id else "",
        "used_on": sorted({q.document.ref for q in
                           rfq.quotations.select_related("document")
                           if not q.document.is_void}),
    }


# ---- the PR picks a quote from its MRs' RFQs ---------------------------------

def pr_mrs(pr):
    return [link.to_document for link in
            pr.links_from.filter(link_type="MR_PR")
            .select_related("to_document")]


def quotes_for_pr(pr):
    """RFQs of the PR's MRs whose quote has come in and that this PR has not
    taken yet."""
    used = set(pr.quotations.filter(rfq__isnull=False)
               .values_list("rfq_id", flat=True))
    return [r for r in MrRfq.objects.filter(
        mr__in=pr_mrs(pr), quote_file__isnull=False)
        .exclude(quote_file="").exclude(id__in=used)
        .select_related("mr", "supplier", "created_by", "received_by")]


def _current_line(rl, mr):
    """The MR line as it stands now: an amendment makes a new revision with
    new lines, so an RFQ asked against the old one follows by item."""
    ln = rl.mr_line
    if mr.current_revision_id is None or \
            ln.revision_id == mr.current_revision_id:
        return ln
    cur = mr.current_revision.lines
    return (cur.filter(item_id=ln.item_id).first() if ln.item_id
            else cur.filter(line_no=ln.line_no).first()) or ln


@transaction.atomic
def take_into_pr(pr, rfq, actor):
    """Make the PR's quotation from the RFQ. Returns (quotation, error)."""
    if rfq.mr_id not in {m.id for m in pr_mrs(pr)}:
        return None, "That RFQ is not for one of this PR's MRs."
    if not rfq.quote_file:
        return None, "The supplier's quote has not been uploaded yet."
    if pr.quotations.filter(rfq=rfq).exists():
        return None, "This PR already has that quote."
    from .procurement import supplier_currency
    q = Quotation.objects.create(
        document=pr, supplier=rfq.supplier, rfq=rfq,
        quote_ref=rfq.quote_ref or rfq.ref, quote_date=rfq.quote_date,
        payment_terms="Cash", notes=f"From {rfq.ref}", created_by=actor,
        currency=supplier_currency(rfq.supplier))
    # the same file, under the quotation
    from django.core.files.base import ContentFile
    rfq.quote_file.open("rb")
    try:
        name = rfq.quote_file.name.rsplit("/", 1)[-1]
        q.file.save(name, ContentFile(rfq.quote_file.read()), save=True)
    finally:
        rfq.quote_file.close()
    # the items asked, already matched to their MR lines; rates from the
    # supplier's PDF when it reads cleanly and lists the same number of items
    rows = []
    if q.file.name.lower().endswith(".pdf"):
        try:
            from .quote_extract import extract_quote_lines
            rows = extract_quote_lines(q.file)
        except Exception:                       # pragma: no cover
            rows = []
    asked = list(rfq.lines.select_related("mr_line__item"))
    use_rates = len(rows) == len(asked)
    for i, rl in enumerate(asked, start=1):
        ln = _current_line(rl, rfq.mr)
        rate = rows[i - 1]["rate"] if use_rates else None
        qty = rl.qty
        amount = (Decimal(str(qty)) * Decimal(str(rate))
                  if rate is not None and qty is not None else None)
        QuotationLine.objects.create(
            quotation=q, line_no=i,
            supplier_desc=(rows[i - 1]["supplier_desc"] if use_rates else
                           (ln.item.description if ln.item_id
                            else ln.free_text_desc)),
            unit=ln.unit, qty=qty, rate=rate, amount=amount, mr_line=ln)
    from .procurement import sync_pr_vendor_rows
    if pr.status in ("DRAFT", "SUBMITTED"):
        sync_pr_vendor_rows(pr)
    audit("quotation", q.id, "QUOTATION_FROM_RFQ", actor=actor,
          detail={"pr": pr.ref, "rfq": rfq.ref, "supplier": rfq.supplier.name,
                  "rates_read": use_rates})
    return q, None


