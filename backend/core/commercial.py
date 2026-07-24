"""Project commercial — the QS side: BOQ → variations → progress claims.

This is the client-revenue counterpart to the cost-control ledger: the QS
prices the contract (BOQ), values work done progressively, and claims it from
the client. Slice 1 is the BOQ itself.
"""
from decimal import Decimal, InvalidOperation

from django.db.models import Max, Sum

from .audit import audit

ZERO = Decimal("0")


def _dec(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def normalise_header(h):
    """Map a spreadsheet header cell to a canonical BOQ field key. Supply
    (material) and installation (labour) rates map to distinct keys; a lone
    'rate'/'total' column maps to the combined rate."""
    key = str(h or "").strip().lower()
    return {
        "section": "section", "bill": "section", "trade": "section",
        "code": "item_code", "item": "item_code", "item code": "item_code",
        "ref": "item_code", "no": "item_code", "item no": "item_code",
        "description": "description", "desc": "description",
        "unit": "unit", "uom": "unit",
        "qty": "qty", "quantity": "qty",
        "material": "rate_supply", "supply": "rate_supply",
        "supply rate": "rate_supply", "material rate": "rate_supply",
        "labor": "rate_install", "labour": "rate_install",
        "install": "rate_install", "installation": "rate_install",
        "install rate": "rate_install", "labour rate": "rate_install",
        "rate": "rate_combined", "price": "rate_combined",
        "unit rate": "rate_combined", "total": "rate_combined",
        "total rate": "rate_combined",
    }.get(key, "")


def _row_items(boq, rows):
    """Turn cleaned dict rows into (unsaved) BoqItem instances. A supply/labour
    split is used when either is present; a lone combined rate goes on the
    supply leg. A row with no qty, rate or unit is treated as a heading."""
    from .models import BoqItem
    out = []
    for i, r in enumerate(rows):
        desc = str(r.get("description") or "").strip()
        section = str(r.get("section") or "").strip()
        code = str(r.get("item_code") or "").strip()
        unit = str(r.get("unit") or "").strip()
        if not (desc or section or code):
            continue
        qty = _dec(r.get("qty"))
        supply = _dec(r.get("rate_supply"))
        install = _dec(r.get("rate_install"))
        if supply is None and install is None:
            supply = _dec(r.get("rate_combined"))   # combined rate → supply leg
        has_rate = supply is not None or install is not None
        is_heading = bool(r.get("is_heading")) or (
            qty is None and not has_rate and not unit)
        out.append(BoqItem(
            boq=boq, sort_order=i, section=section, item_code=code,
            description=desc, unit=unit, qty=qty, rate_supply=supply,
            rate_install=install, is_heading=is_heading))
    return out


def set_boq_items(project, rows, actor):
    """Replace the project's BOQ lines. Creates the BOQ on first save; blocked
    once it's locked (a claim has started). Records whether the schedule prices
    supply and installation separately. Returns (boq, error)."""
    from .models import Boq, BoqItem
    boq, _ = Boq.objects.get_or_create(
        project=project, defaults={"created_by": actor})
    if boq.is_locked:
        return None, "The BOQ is locked — a claim has already started."
    items = _row_items(boq, rows)
    split = any(i.rate_install is not None for i in items)
    boq.items.all().delete()
    BoqItem.objects.bulk_create(items)
    if boq.split_rates != split:
        boq.split_rates = split
        boq.save(update_fields=["split_rates"])
    audit("project", project.id, "BOQ_SAVED", actor=actor,
          detail={"items": len(items), "total": str(boq.total),
                  "split": split})
    return boq, None


def import_boq_rows(project, rows, actor):
    """Import BOQ rows (already parsed from the uploaded sheet)."""
    return set_boq_items(project, rows, actor)


def set_boq_lock(project, locked, actor):
    from .models import Boq
    boq = getattr(project, "boq", None)
    if boq is None:
        return None, "There's no BOQ to lock yet."
    boq.is_locked = bool(locked)
    boq.save(update_fields=["is_locked"])
    audit("project", project.id,
          "BOQ_LOCKED" if locked else "BOQ_UNLOCKED", actor=actor)
    return boq, None


# ---- Variations (VOs) ----------------------------------------------------

def _variation_items(variation, rows):
    from .models import VariationItem
    out = []
    for i, r in enumerate(rows):
        desc = str(r.get("description") or "").strip()
        section = str(r.get("section") or "").strip()
        code = str(r.get("item_code") or "").strip()
        unit = str(r.get("unit") or "").strip()
        if not (desc or section or code):
            continue
        qty = _dec(r.get("qty"))
        supply = _dec(r.get("rate_supply"))
        install = _dec(r.get("rate_install"))
        if supply is None and install is None:
            supply = _dec(r.get("rate_combined"))
        has_rate = supply is not None or install is not None
        is_heading = bool(r.get("is_heading")) or (
            qty is None and not has_rate and not unit)
        out.append(VariationItem(
            variation=variation, sort_order=i, section=section, item_code=code,
            description=desc, unit=unit, qty=qty, rate_supply=supply,
            rate_install=install, is_heading=is_heading))
    return out


def create_variation(project, data, actor):
    from .models import Variation
    seq = (project.variations.aggregate(m=Max("seq"))["m"] or 0) + 1
    v = Variation.objects.create(
        project=project, seq=seq, ref=(data.get("ref") or f"VO-{seq:02d}"),
        title=data.get("title") or "",
        kind=data.get("kind") or "ADDITION",
        ref_date=data.get("ref_date") or None, created_by=actor)
    if data.get("rows"):
        set_variation_items(v, data["rows"], actor)
    audit("project", project.id, "VARIATION_CREATED", actor=actor,
          detail={"ref": v.ref})
    return v, None


def set_variation_items(variation, rows, actor):
    from .models import VariationItem
    if variation.status not in ("DRAFT",):
        return None, "Only a draft variation can be edited."
    items = _variation_items(variation, rows)
    variation.items.all().delete()
    VariationItem.objects.bulk_create(items)
    audit("project", variation.project_id, "VARIATION_SAVED", actor=actor,
          detail={"ref": variation.ref, "gross": str(variation.gross)})
    return variation, None


def set_variation_meta(variation, data, actor):
    """Edit a draft variation's header (title/kind/ref/date)."""
    if variation.status != "DRAFT":
        return None, "Only a draft variation can be edited."
    for f in ("ref", "title", "kind"):
        if f in data:
            setattr(variation, f, data.get(f) or getattr(variation, f))
    if "ref_date" in data:
        variation.ref_date = data.get("ref_date") or None
    variation.save(update_fields=["ref", "title", "kind", "ref_date"])
    return variation, None


VARIATION_FLOW = {
    "DRAFT": {"SUBMITTED"},
    "SUBMITTED": {"APPROVED", "REJECTED", "DRAFT"},
    "APPROVED": set(),          # locked once approved (feeds claims)
    "REJECTED": {"DRAFT"},
}


def set_variation_status(variation, to_status, actor):
    from .models import Variation
    allowed = VARIATION_FLOW.get(variation.status, set())
    if to_status not in allowed:
        return None, f"Cannot move a {variation.status} variation to {to_status}."
    if to_status == "SUBMITTED" and not variation.items.exists():
        return None, "Add at least one variation item before submitting."
    variation.status = to_status
    variation.save(update_fields=["status"])
    audit("project", variation.project_id, f"VARIATION_{to_status}",
          actor=actor, detail={"ref": variation.ref})
    return variation, None


def contract_summary(project):
    """The IPA contract block: original sum + approved VOs = revised sum;
    submitted-not-approved VOs are provisions in the forecast (IPA §C–E)."""
    from decimal import Decimal
    original = Decimal(str(project.contract_value or 0))
    approved = project.variations.filter(status="APPROVED")
    submitted = project.variations.filter(status="SUBMITTED")

    def signed(qs):
        return sum((v.signed_total for v in qs), Decimal("0"))

    approved_net = signed(approved)
    pending_net = signed(submitted)
    revised = original + approved_net
    return {
        "original": original,
        "approved_net": approved_net,
        "revised": revised,
        "pending_net": pending_net,
        "forecast": revised + pending_net,
    }


# ---- Progress claims (interim payment applications / IPCs) ---------------

def create_claim(project, data, actor):
    """Open a new interim claim. Locks the BOQ (the contract baseline is now
    frozen), snapshots the money terms, and pre-populates one line per priced
    BOQ item and approved-variation item — each seeded from the previous
    claim's cumulative valuation so the QS only bumps the figures that moved."""
    from .models import ProgressClaim, ProgressClaimItem
    claim_type = data.get("claim_type") or "INTERIM"
    boq = getattr(project, "boq", None)
    is_advance = claim_type == "ADVANCE"
    if is_advance:
        # The advance is a flat % of the contract value — it needs the terms,
        # not a BOQ, and it carries no work lines.
        if not project.contract_value:
            return None, "Set the project's contract value first."
        if not _dec(project.advance_payment_pct):
            return None, ("Set the advance payment % in the project's contract "
                          "terms first.")
    else:
        if boq is None or not boq.items.exists():
            return None, "Add a BOQ before raising a claim."
        if not boq.is_locked:
            boq.is_locked = True
            boq.save(update_fields=["is_locked"])

    seq = (project.claims.aggregate(m=Max("seq"))["m"] or 0) + 1
    previous = project.claims.order_by("-seq").first()
    gst = _dec(project.output_gst_pct)
    default_basis = ("MEASURED" if project.contract_type == "REMEASUREMENT"
                     else "PERCENT")
    claim = ProgressClaim.objects.create(
        project=project, seq=seq, ref=(data.get("ref") or f"IPA-{seq:02d}"),
        claim_type=data.get("claim_type") or "INTERIM",
        basis=data.get("basis") or default_basis,
        work_done_upto=data.get("work_done_upto") or None, previous=previous,
        advance_pct=_dec(project.advance_payment_pct) or ZERO,
        # The recovery rate carries forward from the previous claim (so an
        # agreed rate set once sticks); defaults to the advance % (pro-rata).
        recovery_pct=(previous.recovery_pct if previous
                      else _dec(project.advance_payment_pct) or ZERO),
        retention_pct=_dec(project.retention_pct) or ZERO,
        gst_pct=gst if gst is not None else Decimal("8"),
        material_on_site=(previous.material_on_site if previous else ZERO),
        material_off_site=(previous.material_off_site if previous else ZERO),
        retention_released=(previous.retention_released if previous else ZERO),
        created_by=actor)

    prev_map = {}
    if previous:
        for pci in previous.items.all():
            prev_map[(pci.source, pci.boq_item_id,
                      pci.variation_item_id)] = pci
    new_items = []
    # An advance claim carries no work lines — its value is the flat advance %.
    if not is_advance and boq:
        for it in boq.items.all():
            if it.is_heading:
                continue
            pci = prev_map.get(("BOQ", it.id, None))
            new_items.append(ProgressClaimItem(
                claim=claim, source="BOQ", boq_item=it,
                cumulative_pct=(pci.cumulative_pct if pci else None),
                cumulative_qty=(pci.cumulative_qty if pci else None)))
        for v in project.variations.filter(
                status="APPROVED").prefetch_related("items"):
            for it in v.items.all():
                if it.is_heading:
                    continue
                pci = prev_map.get(("VO", None, it.id))
                new_items.append(ProgressClaimItem(
                    claim=claim, source="VO", variation_item=it,
                    cumulative_pct=(pci.cumulative_pct if pci else None),
                    cumulative_qty=(pci.cumulative_qty if pci else None)))
        ProgressClaimItem.objects.bulk_create(new_items)
    audit("project", project.id, "CLAIM_CREATED", actor=actor,
          detail={"ref": claim.ref, "lines": len(new_items)})
    return claim, None


def set_claim_items(claim, rows, actor):
    """Update the cumulative %-complete / measured qty on a draft claim's
    lines. Rows are [{id, cumulative_pct?, cumulative_qty?}]."""
    from .models import ProgressClaimItem
    if claim.status != "DRAFT":
        return None, "Only a draft claim can be valued."
    by_id = {ci.id: ci for ci in claim.items.all()}
    changed = []
    for r in rows:
        ci = by_id.get(r.get("id"))
        if ci is None:
            continue
        if "cumulative_pct" in r:
            ci.cumulative_pct = _dec(r.get("cumulative_pct"))
        if "cumulative_qty" in r:
            ci.cumulative_qty = _dec(r.get("cumulative_qty"))
        changed.append(ci)
    if changed:
        ProgressClaimItem.objects.bulk_update(
            changed, ["cumulative_pct", "cumulative_qty"])
    audit("project", claim.project_id, "CLAIM_VALUED", actor=actor,
          detail={"ref": claim.ref, "lines": len(changed)})
    return claim, None


def set_claim_meta(claim, data, actor):
    """Edit a draft claim's header — type, basis, date, and the cumulative
    material-on/off-site and retention-release figures the QS enters direct."""
    if claim.status != "DRAFT":
        return None, "Only a draft claim can be edited."
    for f in ("ref", "claim_type", "basis", "note"):
        if f in data:
            setattr(claim, f, data.get(f) or getattr(claim, f))
    if "work_done_upto" in data:
        claim.work_done_upto = data.get("work_done_upto") or None
    for f in ("material_on_site", "material_off_site", "retention_released"):
        if f in data:
            setattr(claim, f, _dec(data.get(f)) or ZERO)
    if "recovery_pct" in data:
        claim.recovery_pct = _dec(data.get("recovery_pct")) or ZERO
    if "advance_recovered_override" in data:
        # blank/None clears the override → back to the rate formula
        v = data.get("advance_recovered_override")
        claim.advance_recovered_override = (_dec(v) if v not in (None, "")
                                            else None)
    claim.save()
    return claim, None


CLAIM_FLOW = {
    "DRAFT": {"SUBMITTED"},
    "SUBMITTED": {"CERTIFIED", "REJECTED", "DRAFT"},
    "CERTIFIED": {"PAID"},
    "PAID": set(),
    "REJECTED": {"DRAFT"},
}


def set_claim_status(claim, to_status, actor):
    from django.utils import timezone
    allowed = CLAIM_FLOW.get(claim.status, set())
    if to_status not in allowed:
        return None, f"Cannot move a {claim.status} claim to {to_status}."
    if (to_status == "SUBMITTED" and claim.claim_type != "ADVANCE"
            and not claim.items.exists()):
        return None, "Value at least one line before submitting the claim."
    claim.status = to_status
    fields = ["status"]
    if to_status == "CERTIFIED":
        claim.certified_by = actor
        claim.certified_at = timezone.now()
        fields += ["certified_by", "certified_at"]
        if not claim.invoice_no:
            claim.invoice_no = _next_invoice_no()
            fields.append("invoice_no")
    claim.save(update_fields=fields)
    audit("project", claim.project_id, f"CLAIM_{to_status}", actor=actor,
          detail={"ref": claim.ref})
    return claim, None


def _cum_value(basis, cum_pct, cum_qty, contract_amount, rate, sign):
    """Cumulative value of a line: qty×rate for re-measurement, else a % of the
    (signed) contract amount for lump-sum."""
    if basis == "MEASURED":
        return (cum_qty or ZERO) * (rate or ZERO) * sign
    return (cum_pct or ZERO) / Decimal("100") * contract_amount


def _claim_net(claim):
    """Net cumulative certified (waterfall line N) — used as the 'previously
    certified' figure of the following claim."""
    if claim is None:
        return ZERO
    return claim_valuation(claim)["waterfall"]["net_cumulative"]


def claim_valuation(claim):
    """The full IPA waterfall for one claim: per-line previous/current/
    cumulative values, per-section summary, and the header money cascade
    (gross K → advance recovery L → retention M → net N → less previous P →
    net due Q → output GST R → total). Mirrors the owner's Soneva IPA."""
    from collections import OrderedDict
    project = claim.project
    original = Decimal(str(project.contract_value or 0))
    revised = contract_summary(project)["revised"]
    basis = claim.basis

    prev = claim.previous
    prev_map = {}
    if prev:
        for pci in prev.items.all():
            prev_map[(pci.source, pci.boq_item_id,
                      pci.variation_item_id)] = pci

    k1 = k4 = ZERO
    lines = []
    for ci in claim.items.select_related(
            "boq_item", "variation_item", "variation_item__variation"):
        line = ci.line
        if line is None:
            continue
        is_vo = ci.source == "VO"
        omission = is_vo and line.variation.kind == "OMISSION"
        sign = Decimal("-1") if omission else Decimal("1")
        rate = line.rate_total
        contract_amt = (line.amount or ZERO) * sign
        cum_val = _cum_value(basis, ci.cumulative_pct, ci.cumulative_qty,
                             contract_amt, rate, sign)
        pci = prev_map.get((ci.source, ci.boq_item_id, ci.variation_item_id))
        prev_val = (_cum_value(basis, pci.cumulative_pct, pci.cumulative_qty,
                               contract_amt, rate, sign) if pci else ZERO)
        cur_val = cum_val - prev_val
        if is_vo:
            k4 += cum_val
        else:
            k1 += cum_val
        lines.append({
            "id": ci.id, "source": ci.source, "section": line.section,
            "item_code": line.item_code, "description": line.description,
            "unit": line.unit, "contract_qty": line.qty, "rate": rate,
            "contract_amount": contract_amt,
            "cumulative_pct": ci.cumulative_pct,
            "cumulative_qty": ci.cumulative_qty,
            "previous_value": prev_val, "current_value": cur_val,
            "cumulative_value": cum_val,
        })

    k2 = Decimal(str(claim.material_on_site or 0))     # material on site
    k3 = Decimal(str(claim.material_off_site or 0))    # material off site
    k_gross = k1 + k2 + k3 + k4                        # K gross cumulative

    from .models import ProgressClaim
    advance_total = claim.advance_pct / Decimal("100") * original    # L1
    # The advance is paid on the Advance claim, then recovered pro-rata as work
    # is valued. It rides the cumulative waterfall as +received / −recovered, so
    # each claim's "now due" comes out right (advance received once, recovery
    # nets it back over the interims).
    has_advance = ProgressClaim.objects.filter(
        project=project, claim_type=ProgressClaim.Type.ADVANCE,
        seq__lte=claim.seq).exists()
    advance_received = advance_total if has_advance else ZERO        # L0
    if claim.advance_recovered_override is not None:                 # L2
        advance_recovered = min(Decimal(str(claim.advance_recovered_override)),
                                advance_total)
    else:
        advance_recovered = min(
            claim.recovery_pct / Decimal("100") * k_gross, advance_total)
    retention_held = (claim.retention_pct / Decimal("100")
                      * (k1 + k2 + k4))                 # M1 (not on off-site)
    retention_released = Decimal(str(claim.retention_released or 0))  # M2
    net_retention = retention_released - retention_held              # M
    net_cumulative = (k_gross + advance_received - advance_recovered
                      + net_retention)                  # N
    previously = _claim_net(prev)                                    # P
    net_due = net_cumulative - previously                           # Q
    gst = claim.gst_pct / Decimal("100") * net_due                  # R
    total = net_due + gst

    secs = OrderedDict()
    for ln in lines:
        s = ln["section"] or "—"
        d = secs.setdefault(s, {"section": s, "previous": ZERO,
                                "current": ZERO, "cumulative": ZERO})
        d["previous"] += ln["previous_value"]
        d["current"] += ln["current_value"]
        d["cumulative"] += ln["cumulative_value"]

    return {
        "lines": lines,
        "section_summary": list(secs.values()),
        "waterfall": {
            "original": original, "revised": revised,
            "k1_work_done": k1, "k2_material_on_site": k2,
            "k3_material_off_site": k3, "k4_variations": k4,
            "k_gross": k_gross,
            "advance_total": advance_total,
            "advance_received": advance_received,
            "advance_recovered": advance_recovered,
            "retention_held": retention_held,
            "retention_released": retention_released,
            "net_retention": net_retention,
            "net_cumulative": net_cumulative,
            "previously_certified": previously,
            "net_due": net_due, "gst": gst, "total": total,
        },
    }


# ---- Client receipts + project revenue (money-in, P4) --------------------

def record_client_receipt(project, data, actor):
    """Record money received from the client (USD) against a certified claim.
    Fully settling a certified claim marks it Paid. Returns (receipt, error)."""
    from .models import ClientReceipt, ProgressClaim
    amt = _dec(data.get("amount"))
    if amt is None or amt <= ZERO:
        return None, "Enter the amount received."
    if not data.get("received_on"):
        return None, "Enter the date the money was received."
    claim = None
    if data.get("claim_id"):
        claim = ProgressClaim.objects.filter(
            pk=data["claim_id"], project=project).first()
        if claim is None:
            return None, "That claim isn't on this project."
    receipt = ClientReceipt.objects.create(
        project=project, claim=claim, amount=amt,
        received_on=data["received_on"], reference=data.get("reference") or "",
        note=data.get("note") or "", recorded_by=actor)
    if claim and claim.status == "CERTIFIED":
        due = claim_valuation(claim)["waterfall"]["total"]
        got = (ClientReceipt.objects.filter(claim=claim)
               .aggregate(s=Sum("amount"))["s"] or ZERO)
        if got >= due:
            set_claim_status(claim, "PAID", actor)
    audit("project", project.id, "CLIENT_RECEIPT", actor=actor,
          detail={"amount": str(amt), "claim": claim.ref if claim else None})
    return receipt, None


def delete_client_receipt(receipt, actor):
    pid, amt = receipt.project_id, str(receipt.amount)
    receipt.delete()
    audit("project", pid, "CLIENT_RECEIPT_DELETED", actor=actor,
          detail={"amount": amt})
    return None


def project_revenue_summary(project):
    """The project's money-in position (USD): certified revenue to date (gross
    value of work certified, ex-GST), amount billed incl GST, retention still
    held, client money received and what's still outstanding."""
    from .models import ClientReceipt
    csum = contract_summary(project)
    certified = list(project.claims.filter(
        status__in=["CERTIFIED", "PAID"]).order_by("seq"))
    revenue = billed = gst_billed = retention_held = ZERO
    last = None
    for c in certified:
        w = claim_valuation(c)["waterfall"]
        gst_billed += w["gst"]
        billed += w["total"]
        last = w
    if last is not None:
        revenue = last["k_gross"]                       # ex-GST earned revenue
        retention_held = last["retention_held"] - last["retention_released"]
    received = (ClientReceipt.objects.filter(project=project)
                .aggregate(s=Sum("amount"))["s"] or ZERO)
    revised = csum["revised"]
    boq = getattr(project, "boq", None)
    return {
        "currency": boq.currency if boq else "USD",
        "contract_original": csum["original"],
        "contract_revised": revised,
        "certified_revenue": revenue,
        "gst_billed": gst_billed,
        "retention_held": retention_held,
        "billed": billed,
        "received": received,
        "outstanding": billed - received,
        "pct_complete": (revenue / revised * Decimal("100")
                         if revised else ZERO),
        "claims_certified": len(certified),
    }


# ---- Claim / invoice PDFs (P5) -------------------------------------------

def _next_invoice_no():
    from .models import ProgressClaim
    n = ProgressClaim.objects.exclude(invoice_no="").count() + 1
    return f"INV-{n:04d}"


_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight",
         "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
         "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]


def _under_1000(n):
    if n < 20:
        return _ONES[n]
    if n < 100:
        return (_TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")).strip()
    return (_ONES[n // 100] + " hundred"
            + (" " + _under_1000(n % 100) if n % 100 else "")).strip()


def amount_in_words(amount, currency="USD"):
    """A money amount as words for the invoice/IPA (e.g. 'US Dollars One
    Thousand Five Hundred and 40/100 only')."""
    amount = Decimal(str(amount or 0))
    whole = int(amount)
    cents = int((amount - whole) * 100)
    groups = [("", 0), (" thousand", 1), (" million", 2), (" billion", 3)]
    parts, rest = [], whole
    chunks = []
    while rest > 0:
        chunks.append(rest % 1000)
        rest //= 1000
    if not chunks:
        chunks = [0]
    for i in range(len(chunks) - 1, -1, -1):
        if chunks[i]:
            parts.append(_under_1000(chunks[i]) + groups[i][0])
    words = " ".join(parts).strip() or "zero"
    words = words[:1].upper() + words[1:]
    name = "US Dollars" if currency == "USD" else currency
    return f"{name} {words} and {cents:02d}/100 only"


def _employer(project):
    """The client (Employer) block for a project's IPA / invoice — held on the
    site (the resort relationship)."""
    s = project.site
    return {
        "name": s.client_name or s.name,
        "address": s.client_address, "contact": s.client_contact,
        "designation": s.client_designation,
        "phone": s.client_phone, "email": s.client_email,
    }


def claim_pdf_context(claim):
    """Context for the interim payment application / certificate PDF."""
    from .pdf import company_info, logo_src
    project = claim.project
    val = claim_valuation(claim)
    w = val["waterfall"]
    boq = getattr(project, "boq", None)
    ccy = boq.currency if boq else "USD"
    return {
        "logo_src": logo_src(), "co": company_info(),
        "claim": claim, "project": project,
        "employer": _employer(project), "currency": ccy,
        "waterfall": w, "approved_vos": w["revised"] - w["original"],
        "lines": val["lines"], "sections": val["section_summary"],
        "amount_words": amount_in_words(w["total"], ccy),
        "type_label": dict(
            claim.Type.choices).get(claim.claim_type, claim.claim_type),
        "subline": f"Application {claim.ref}  ·  {project.code}",
    }


def invoice_pdf_context(claim):
    """Context for the client tax invoice PDF (the GST bill for this claim)."""
    from .pdf import company_info, logo_src
    project = claim.project
    w = claim_valuation(claim)["waterfall"]
    boq = getattr(project, "boq", None)
    ccy = boq.currency if boq else "USD"
    return {
        "logo_src": logo_src(), "co": company_info(),
        "claim": claim, "project": project,
        "employer": _employer(project), "currency": ccy,
        "type_label": dict(
            claim.Type.choices).get(claim.claim_type, claim.claim_type),
        "net_due": w["net_due"], "gst": w["gst"], "gst_pct": claim.gst_pct,
        "total": w["total"], "amount_words": amount_in_words(w["total"], ccy),
        "subline": f"Invoice {claim.invoice_no or '—'}",
    }
