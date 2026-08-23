"""Planet Mobile API (R6) — /api/mobile/v1/.

A thin, token-authenticated client surface over the existing business logic.
No new rules live here: queues reuse the desktop 'waiting on you' computation,
actions call the same transition service, and scoping is server-enforced.
"""
from decimal import Decimal

from django.contrib.auth import authenticate as dj_authenticate
from rest_framework.decorators import (api_view, authentication_classes,
                                       permission_classes)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .audit import audit
from .mobile import MobileTokenAuthentication, new_token
from .models import MobileDevice
from .permissions import scoped_site_ids

MOBILE_AUTH = [MobileTokenAuthentication]


def me_payload(user):
    sids = scoped_site_ids(user)
    return {
        "id": user.id, "username": user.username,
        "full_name": user.full_name, "role": user.role,
        "role_label": user.get_role_display(),
        "is_signatory": user.role == "SIGNATORY",
        "all_sites": sids is None,
        "sites": [] if sids is None else sorted(sids),
    }


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def m_login(request):
    """Sign in with the existing Planet username + password; returns a device
    token to carry as a Bearer header."""
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""
    from .views import record_login_event
    user = dj_authenticate(username=username, password=password)
    if not user or not user.is_active:
        record_login_event(request, "FAILED", username=username,
                           source="MOBILE")
        return Response({"detail": "Wrong username or password."}, status=401)
    device = MobileDevice.objects.create(
        user=user, token=new_token(),
        label=(request.META.get("HTTP_USER_AGENT") or "")[:120])
    audit("user", user.id, "MOBILE_SIGN_IN", actor=user,
          detail={"device": device.id})
    record_login_event(request, "LOGIN", user=user, source="MOBILE")
    return Response({"token": device.token, "user": me_payload(user)},
                    status=201)


@api_view(["POST"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_logout(request):
    """Revoke this device's token (and, later, its push subscription)."""
    device = getattr(request, "mobile_device", None)
    if device:
        MobileDevice.objects.filter(pk=device.pk).update(revoked=True)
    return Response({"detail": "Signed out."})


@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_me(request):
    return Response(me_payload(request.user))


# ---- Approver: queue / actioned / detail / actions ----------------------

# The document/status pairs an approver may action FROM MOBILE. Everything else
# in the desktop 'waiting on you' queue (DPR verify, DMA issue, PO issue,
# Finance payment tasks, Phase-1B PMR/IPR) stays desktop-only (R6 §2/§4).
APPROVABLE = {
    ("MR", "SUBMITTED"), ("IR", "SUBMITTED"), ("MAR", "SUBMITTED"),
    ("SD", "SUBMITTED"), ("MS", "SUBMITTED"),
    ("PR", "SUBMITTED"), ("PYR", "SUBMITTED"), ("PYR", "PM_APPROVED"),
    ("PV", "SUBMITTED"),
    ("IPR", "SUBMITTED"),   # Director/QS award the overseas order on mobile
    ("IPR", "APPROVED"),    # signatory authorises the order (raises the PO)
    # A local credit purchase order is signed by the signatory on the order
    # itself — not inside a payment voucher — so it must be on the phone the
    # way an import order is (owner 2026-08-22).
    ("PO", "SUBMITTED"),
    # The Director's internal approval of a variation order. Not a Document:
    # its queue key is "<project code> VO-NN" (owner 2026-08-22).
    ("VO", "PD_PENDING"),
    # A charge correction on an already-authorised order: the row carries the
    # CORRECTION's status, so it no longer looks like a finished IPR and is
    # actionable from the phone (owner 2026-08-15).
    ("IPR", "PENDING_DIRECTOR"), ("IPR", "PENDING_SIGNATORY"),
    ("OBR", "SUBMITTED"),   # Director approves expat mobilisation on mobile
    ("OBR", "IN_PROGRESS"),  # signatory signs the appointment off on mobile
    ("PSC", "CONFIRMED"),   # Director signs off a procurement schedule on mobile
    # Subcontract valuation: PM verifies, Director approves, Signatory authorises
    ("SVC", "SUBMITTED"), ("SVC", "PM_VERIFIED"), ("SVC", "DIRECTOR_APPROVED"),
}


from .views_documents import queue_amount as _card_amount


@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_queue(request):
    """Pending approvals for this user — the desktop 'waiting on you' queue
    filtered to the items actionable on mobile, flattened to cards."""
    from .views_documents import pending_groups

    groups = pending_groups(request.user)
    cards = []
    for g in groups:
        for it in g["items"]:
            if (it["doc_type"], it["status"]) not in APPROVABLE:
                continue
            cards.append({**it, "amount": _card_amount(it["ref"],
                                                        it["doc_type"])})
    return Response({"count": len(cards), "items": cards})


@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_actioned(request):
    """Documents this user actioned (any client) in the last N days."""
    from datetime import timedelta

    from django.utils import timezone

    from .models import Approval
    try:
        days = min(int(request.GET.get("days", 30)), 90)
    except (TypeError, ValueError):
        days = 30
    since = timezone.now() - timedelta(days=days)
    seen, items = set(), []
    for a in Approval.objects.filter(
            actor=request.user, acted_at__gte=since,
            action__in=("APPROVE", "AUTHORISE", "RETURN", "REJECT")) \
            .select_related("document", "document__site").order_by("-acted_at"):
        d = a.document
        if not d or d.ref in seen:
            continue
        seen.add(d.ref)
        items.append({
            "ref": d.ref, "doc_type": d.doc_type,
            "site_code": d.site.code if d.site_id else "—",
            "result": a.result or a.action, "acted_at": a.acted_at})
    return Response({"items": items[:80]})


def _pv_line_ref(ln):
    """Label for a voucher line: the source document's ref, or — for an
    overseas TT — the import order + milestone name."""
    if ln.source_document_id:
        return ln.source_document.ref
    m = ln.source_milestone
    if not m:
        return "—"
    try:
        return f"{m.order.document.ref} · {m.label}"
    except Exception:               # pragma: no cover - defensive
        return m.label or "—"


def _pr_vendor_summary(pr):
    """Short 'who we're paying' line for a PR: the awarded vendors."""
    names = []
    rev = pr.current_revision
    if rev is not None:
        for ln in rev.lines.all():
            net = (ln.amount_cash or 0) + (ln.amount_credit or 0)
            name = (ln.vendor or ln.free_text_desc or "").strip()
            if net > 0 and name and name not in names:
                names.append(name)
    if not names:
        return ""
    if len(names) <= 2:
        return ", ".join(names)
    return f"{names[0]}, {names[1]} +{len(names) - 2} more"


def _pv_line_detail(ln):
    """A readable summary of one voucher line so the signatory knows what the
    payment is for — payee, purpose, vendors — not just a document ref."""
    d = {"ref": _pv_line_ref(ln), "amount": float(ln.amount or 0),
         "currency": ln.currency, "kind": "", "title": "", "subtitle": "",
         "site_code": ""}
    src = ln.source_document
    if src is not None:
        d["site_code"] = src.site.code if src.site_id else ""
        if src.doc_type == "PYR" and hasattr(src, "payment_request"):
            pr = src.payment_request
            d["kind"] = "Payment request"
            d["title"] = pr.payee or "Payment"
            d["subtitle"] = " · ".join(
                x for x in (pr.purpose, getattr(pr.cost_head, "name", None))
                if x)
        elif src.doc_type == "PR":
            d["kind"] = "Procurement"
            d["title"] = _pr_vendor_summary(src) or "Materials procurement"
            d["subtitle"] = "Local purchase"
        else:
            d["kind"] = src.doc_type
            d["title"] = src.ref
    elif ln.source_milestone_id:
        m = ln.source_milestone
        d["kind"] = "Import payment"
        d["site_code"] = "HO"
        try:
            d["title"] = m.order.supplier.name
            d["subtitle"] = f"{m.order.document.ref} · {m.label}"
        except Exception:           # pragma: no cover - defensive
            d["title"] = m.label or "Milestone"
    elif ln.source_payable_id:
        p = ln.source_payable
        d["kind"] = "Credit payable"
        d["site_code"] = p.site.code if p.site_id else ""
        d["title"] = p.vendor or "Payable"
        d["subtitle"] = f"terms {p.terms or '—'} · due {p.due_date or '—'}"
    return d


def _money(v, ccy="MVR"):
    return f"{ccy} {float(v or 0):,.2f}"


def _pr_mobile_payload(doc, request):
    """A concise 'what am I awarding' summary of a PR for the Director: the
    quoted vendors with amounts, the cash/credit/GST split, and which MRs it
    covers — not the full quotation comparison (that stays on desktop)."""
    from .procurement import pr_cash_total, pr_gst_total, pr_grand_total
    base = _base_header(doc, request)
    lines, credit = [], Decimal("0")
    rev = doc.current_revision
    if rev is not None:
        for ln in rev.lines.all():
            cash = ln.amount_cash or 0
            cr = ln.amount_credit or 0
            gst = ln.gst_amount or 0
            net = cash + cr
            if net <= 0:
                continue
            is_credit = cr > 0
            credit += cr
            terms = ("Credit" if is_credit else "Cash")
            if ln.quotation_ref:
                terms += f" · quote {ln.quotation_ref}"
            lines.append({
                "ref": "", "kind": terms, "title": ln.vendor
                or ln.free_text_desc or "Vendor",
                "subtitle": "", "amount": float(net + gst), "currency": "MVR",
                "site_code": ""})
    mr_refs = [l.to_document.ref for l in doc.links_from.filter(
        link_type="MR_PR").select_related("to_document")]
    summary = [
        {"k": "Cash", "v": _money(pr_cash_total(doc))},
        {"k": "Credit", "v": _money(credit)},
        {"k": "GST (input)", "v": _money(pr_gst_total(doc))},
        {"k": "Total", "v": _money(pr_grand_total(doc))},
    ]
    if mr_refs:
        summary.append({"k": "For", "v": ", ".join(mr_refs)})
    base.update({"amount": float(pr_grand_total(doc)), "currency": "MVR",
                 "line_label": "Quoted vendors", "summary": summary,
                 "lines": lines})
    return base


def _ipr_mobile_payload(doc, request):
    """A concise overseas-order summary for the Director/Signatory: supplier,
    order value in the order currency and MVR, incoterm, the line items, and
    the payment-milestone schedule."""
    from .imports import ipr_mvr_total, ipr_order_total
    base = _base_header(doc, request)
    order = getattr(doc, "import_order", None)
    if order is None:
        base.update({"lines": [], "summary": []})
        return base
    ccy = order.order_currency
    total = ipr_order_total(order)
    lines = []
    for ln in order.lines.all():
        qty = float(ln.order_qty or 0)
        lines.append({
            "ref": "", "kind": "", "title": ln.description or "Item",
            "subtitle": f"{qty:g} {ln.unit or ''} × {ccy} "
                        f"{float(ln.unit_price or 0):,.2f}".strip(),
            "amount": float(ln.line_value), "currency": ccy, "site_code": ""})
    milestones = []
    for m in order.milestones.order_by("seq"):
        if m.fixed_amount is not None:
            amt = m.fixed_amount
        elif m.percent is not None:
            amt = (total * m.percent / Decimal("100"))
        else:
            amt = Decimal("0")
        milestones.append({
            "label": m.label, "when": m.get_trigger_display(),
            "amount": _money(amt, ccy), "status": m.status})
    summary = [
        {"k": "Order value", "v": _money(total, ccy)},
        {"k": "In MVR", "v": f"{_money(ipr_mvr_total(order))} "
                             f"@ {order.exchange_rate}"},
    ]
    if order.incoterm:
        summary.append({"k": "Incoterm", "v": order.incoterm})
    base.update({"amount": float(total), "currency": ccy,
                 "supplier_name": order.supplier.name,
                 "line_label": "Order items", "summary": summary,
                 "lines": lines, "milestones": milestones})
    return base


def _base_header(doc, request):
    return {"ref": doc.ref, "doc_type": doc.doc_type, "status": doc.status,
            "rev_label": doc.current_revision.rev_label
            if doc.current_revision_id else "",
            "doc_date": doc.doc_date,
            "site_code": doc.site.code if doc.site_id else "",
            "project_code": getattr(doc.project, "code", None)
            if doc.project_id else None,
            "created_by_name": (doc.created_by.full_name
                                if doc.created_by_id else None),
            "attachments": _attachment_list(doc, request),
            "approvals": _approval_list(doc)}


def _attachment_list(doc, request):
    out = []
    for a in doc.attachments.all():
        url = a.file.url if a.file else None
        if url and request is not None:
            url = request.build_absolute_uri(url)
        out.append({"id": a.id, "kind": a.kind, "file_name": a.file_name,
                    "caption": a.caption, "url": url})
    return out


def _approval_list(doc):
    return [{"action": a.action, "result": a.result or a.action,
             "actor_name": a.actor.full_name if a.actor_id else "",
             "actor_role": a.actor_role, "acted_at": a.acted_at,
             "comment": a.comment}
            for a in doc.approvals.select_related("actor").order_by("acted_at")]


def _obr_mobile_payload(doc, request):
    """Read-only render of an onboarding request for the Director's approval
    screen — the candidate + terms as a summary, plus the checklist docs."""
    case = doc.onboarding
    base = _base_header(doc, request)
    summary = [
        {"k": "Candidate", "v": f"{case.full_name} · {case.nationality}"},
        {"k": "Passport", "v": case.passport_no or "—"},
        {"k": "Route", "v": case.get_route_display()},
    ]
    if case.route == "BV":
        summary.append({"k": "BV purpose", "v": case.get_bv_purpose_display()
                        if case.bv_purpose else "—"})
        if case.bv_purpose == "SUBCONTRACT" and case.subcontractor_id:
            summary.append({"k": "Subcontractor", "v": case.subcontractor.name})
    else:
        summary.append({"k": "Quota pool", "v": case.get_quota_pool_display()})
    summary += [
        {"k": "Trade / category",
         "v": f"{case.trade_designation} · {case.category}"},
        {"k": "Destination site", "v": doc.site.code},
    ]
    if case.proposed_salary is not None:
        summary.append({"k": "Proposed salary",
                        "v": f"{case.currency} {case.proposed_salary:,.2f}"})
    if case.route == "BV" and case.bv_justification:
        summary.append({"k": "BV reason", "v": case.bv_justification})
    base.update({"summary": summary})
    return base


def _psc_mobile_payload(doc, request):
    """Read-only render of a procurement schedule for the Director's sign-off
    screen — the project + a per-section line count as a summary."""
    sched = doc.procurement_schedule
    base = _base_header(doc, request)
    lines = list(sched.lines.exclude(state="CANCELLED")
                 .select_related("section"))
    per_section = {}
    for ln in lines:
        key = f"{ln.section.code} — {ln.section.title}" if ln.section_id \
            else "Ungrouped"
        per_section[key] = per_section.get(key, 0) + 1
    summary = [
        {"k": "Project", "v": f"{sched.project.code} · {sched.project.title}"},
        {"k": "Site", "v": doc.site.code},
        {"k": "Lines to sign off",
         "v": str(sum(1 for ln in lines if ln.state == "CONFIRMED"))},
        {"k": "Total lines", "v": str(len(lines))},
    ]
    summary += [{"k": sec, "v": str(n)} for sec, n in per_section.items()]
    base.update({"summary": summary})
    return base


def _po_mobile_payload(doc, request):
    """What the signatory is being asked to place: the supplier, the lines,
    what it commits, and the terms the payable will fall due on."""
    from .procurement import (credit_period_for, po_commitment,
                              po_credit_total)
    base = _base_header(doc, request)
    rev = doc.current_revision
    payload = (rev.payload or {}) if rev else {}
    lines = []
    for ln in (rev.lines.select_related("item") if rev else []):
        qty = float(ln.qty_required or 0)
        rate = float(ln.rate or 0)
        amount = float(ln.amount if ln.amount is not None else qty * rate)
        lines.append({
            "ref": "", "kind": "",
            "title": (ln.item.description if ln.item_id
                      else ln.free_text_desc) or "Item",
            "subtitle": f"{qty:g} {ln.unit or ''} × {rate:,.2f}".strip(),
            "amount": amount, "currency": "MVR", "site_code": ""})
    pr, row, _err = po_commitment(doc)
    summary = [{"k": "Supplier", "v": (doc.supplier.name if doc.supplier_id
                                       else payload.get("supplier_name", ""))},
               {"k": "Payment terms", "v": payload.get("payment_terms") or "—"}]
    if pr is not None and row is not None:
        days, terms = credit_period_for(row)
        summary += [{"k": "Credit period", "v": f"{days} days"},
                    {"k": "Commits (incl. GST)",
                     "v": _money(po_credit_total(doc))},
                    {"k": "From", "v": pr.ref}]
    base.update({"supplier_name": summary[0]["v"],
                 "line_label": "Order lines",
                 "amount": float(po_credit_total(doc)) if pr else None,
                 "lines": lines, "summary": summary})
    return base


def _document_payload(doc, request):
    """Read-only render for the approver detail screen."""
    from .models import PaymentVoucherLine
    from .serializers_documents import DocumentSerializer
    if doc.doc_type == "PR":
        return _pr_mobile_payload(doc, request)
    if doc.doc_type == "PO":
        return _po_mobile_payload(doc, request)
    if doc.doc_type == "IPR":
        return _ipr_mobile_payload(doc, request)
    if doc.doc_type == "OBR":
        return _obr_mobile_payload(doc, request)
    if doc.doc_type == "PSC":
        return _psc_mobile_payload(doc, request)
    if doc.doc_type == "PV":
        qs = (PaymentVoucherLine.objects.filter(voucher=doc)
              .select_related("source_document__site",
                              "source_document__payment_request__cost_head",
                              "source_milestone__order__document",
                              "source_milestone__order__supplier",
                              "source_payable__site")
              .order_by("id"))
        lines = [_pv_line_detail(ln) for ln in qs]
        return {"ref": doc.ref, "doc_type": "PV", "status": doc.status,
                "doc_date": doc.doc_date,
                "prepared_by": (doc.created_by.full_name
                                if doc.created_by_id else None),
                "amount": float(sum(x["amount"] for x in lines)),
                "line_count": len(lines), "lines": lines}
    return DocumentSerializer(doc, context={"request": request}).data


def _vo_mobile_payload(v, request):
    """The priced variation the Director is asked to approve internally."""
    from .commercial import variation_pdf_context
    ctx = variation_pdf_context(v)
    ccy = ctx["currency"]
    lines = []
    for sec in ctx["sections"]:
        for ln in sec["lines"]:
            if ln["is_heading"]:
                continue
            it = ln["item"]
            lines.append({"ref": "", "kind": "",
                          "title": it.description or "Item",
                          "subtitle": f"{ln['qty']} {it.unit or ''} × "
                                      f"{ln['rate_total']}".strip(),
                          "amount": float(it.amount), "currency": ccy,
                          "site_code": ""})
    return {"ref": f"{v.project.code} {v.ref}", "doc_type": "VO",
            "status": v.status, "rev_label": "",
            "doc_date": v.ref_date or v.created_at.date(),
            "site_code": v.project.site.code if v.project.site_id else "",
            "project_code": v.project.code,
            "created_by_name": (v.created_by.full_name
                                if v.created_by_id else None),
            "attachments": [], "approvals": [],
            "title": v.title, "line_label": "Variation items",
            "amount": float(abs(v.signed_total)), "currency": ccy,
            "lines": lines,
            "summary": [
                {"k": "Type", "v": ctx["kind_label"]},
                {"k": "Project", "v": v.project.title},
                {"k": "Contract sum now", "v": f"{ccy} {ctx['sum_before_f']}"},
                {"k": "This variation", "v": f"{ccy} {ctx['signed_total_f']}"},
                {"k": "If the Employer approves",
                 "v": f"{ccy} {ctx['sum_after_f']}"},
            ]}


@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_document(request, ref):
    from .models import Document
    from .permissions import scoped_site_ids
    if " " in ref:                      # a variation: "<project code> VO-NN"
        from .commercial import variation_by_queue_ref
        v = variation_by_queue_ref(ref)
        if v is None:
            return Response({"detail": "Not found."}, status=404)
        return Response(_vo_mobile_payload(v, request))
    try:
        doc = Document.objects.select_related("site", "current_revision").get(
            ref=ref, is_void=False)
    except Document.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    sids = scoped_site_ids(request.user)
    if sids is not None and doc.site_id not in sids and doc.doc_type != "PV":
        return Response({"detail": "Not found."}, status=404)
    return Response(_document_payload(doc, request))


def _act(request, ref, kind):
    """Approve/return a document from mobile, reusing the exact desktop service
    functions. Returns a DRF Response."""
    from .models import Document
    if " " in ref:                      # a variation: "<project code> VO-NN"
        from .commercial import set_variation_status, variation_by_queue_ref
        comment = (request.data.get("comment") or "").strip()
        v = variation_by_queue_ref(ref)
        if v is None:
            return Response({"detail": "Not found."}, status=404)
        if v.status != "PD_PENDING":
            return Response({"detail": f"Already actioned — {v.ref} is now "
                                       f"{v.get_status_display()}."},
                            status=409)
        if kind == "return" and not comment:
            return Response({"detail": "A reason is required to return."},
                            status=400)
        _, msg = set_variation_status(
            v, "PD_APPROVED" if kind == "approve" else "DRAFT",
            request.user, {"comment": comment})
        if msg:
            return Response({"detail": msg}, status=400)
        return Response({"ref": ref, "doc_type": "VO", "status": v.status})

    try:
        doc = Document.objects.select_related("current_revision").get(
            ref=ref, is_void=False)
    except Document.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    comment = (request.data.get("comment") or "").strip()
    if kind == "return" and not comment:
        return Response({"detail": "A reason is required to return."},
                        status=400)
    # A charge correction rides on an order that is itself AUTHORISED — the
    # queue row carries the correction's status, the document carries the
    # order's, so the pair is allowed here while a correction is pending.
    if doc.doc_type == "IPR" and doc.status == "AUTHORISED":
        from .imports import pending_charge_correction
        if pending_charge_correction(doc.import_order) is None:
            return Response({"detail": f"Already actioned — {doc.ref} is now "
                             f"{doc.status}."}, status=409)
    # 409 if it's no longer in a mobile-actionable state (someone beat us to it)
    elif (doc.doc_type, doc.status) not in APPROVABLE:
        return Response({"detail": f"Already actioned — {doc.ref} is now "
                        f"{doc.status}."}, status=409)

    if doc.doc_type == "PV":
        from . import vouchers
        if request.user.role not in ("SIGNATORY", "ADMIN"):
            return Response({"detail": "Only a signatory approves a voucher."},
                            status=403)
        if kind == "return":
            # Returning a voucher on the desktop means querying its lines:
            # each one goes back to whoever raised it with the reason. A
            # signatory on the road wants the whole batch back, so Return
            # queries every line rather than refusing (owner 2026-08-15).
            line_ids = list(doc.voucher_lines.filter(
                status="INCLUDED").values_list("id", flat=True))
            if not line_ids:
                return Response({"detail": "This voucher has no lines to "
                                           "return."}, status=400)
            err = vouchers.approve_voucher(doc, request.user,
                                           queried_ids=line_ids,
                                           note=comment)
            if err:
                return Response({"detail": err}, status=400)
        else:
            err = vouchers.approve_voucher(doc, request.user)
            if err:
                return Response({"detail": err}, status=400)
    elif doc.doc_type == "PYR":
        from .payments import pyr_action
        result = pyr_action(request, doc, "approve" if kind == "approve"
                            else "return")
        if isinstance(result, Response) and result.status_code >= 400:
            return result
    elif doc.doc_type == "IPR" and doc.status == "AUTHORISED":
        # the pending charge correction on this order, not the order itself
        from . import imports
        msg = imports.decide_charge_correction(
            doc, "approve" if kind == "approve" else "reject",
            request.user, comment)
        if msg:
            return Response({"detail": msg}, status=400)
    elif doc.doc_type == "IPR" and doc.status == "APPROVED":
        # signatory authorises the overseas order — commits it and raises the PO
        from .views_documents import _do_authorise, _do_return
        result = (_do_return if kind == "return" else _do_authorise)(
            request, doc, comment)
        if isinstance(result, Response) and result.status_code >= 400:
            return result
    elif doc.doc_type == "PO":
        # signatory signs a local credit order — places it, commits the cost,
        # raises the payable; Return sends it back to Purchasing
        from .views_documents import _do_authorise, _do_return
        result = (_do_return if kind == "return" else _do_authorise)(
            request, doc, comment)
        if isinstance(result, Response) and result.status_code >= 400:
            return result
    elif doc.doc_type == "OBR" and doc.status == "IN_PROGRESS":
        # The signatory's appointment sign-off — one action, not a decision
        # with two sides: signing stamps every letter the case will carry.
        from . import onboarding
        if kind == "return":
            return Response({"detail": "A sign-off is not returned — either "
                                       "sign it, or leave it and take it up "
                                       "with HR."}, status=400)
        _, msg = onboarding.sign_off_case(doc.onboarding, request.user)
        if msg:
            return Response({"detail": msg}, status=400)
    elif doc.doc_type == "OBR":
        # Director approves / returns an expat mobilisation request
        from . import onboarding
        msg = onboarding.decide_case(
            doc.onboarding, "approve" if kind == "approve" else "return",
            request.user, comment)
        if msg:
            return Response({"detail": msg}, status=400)
    elif doc.doc_type == "PSC":
        # Director signs off / returns a procurement schedule
        from . import procurement_schedule as ps
        msg = ps.decide(
            doc.procurement_schedule,
            "sign_off" if kind == "approve" else "return",
            request.user, comment)
        if msg:
            return Response({"detail": msg}, status=400)
    elif doc.doc_type == "SVC":
        # One "approve" tap advances the valuation by its stage: PM verify →
        # Director approve → Signatory authorise.
        from . import subcontract
        svc_act = "return" if kind == "return" else {
            "SUBMITTED": "verify", "PM_VERIFIED": "approve",
            "DIRECTOR_APPROVED": "authorise"}[doc.status]
        msg = subcontract.svc_action(doc.subcontract_valuation, svc_act,
                                     request.user, comment)
        if msg:
            return Response({"detail": msg}, status=400)
    else:
        from .views_documents import _do_approve, _do_return
        fn = _do_approve if kind == "approve" else _do_return
        result = fn(request, doc, comment)
        if isinstance(result, Response) and result.status_code >= 400:
            return result

    audit("document", doc.id, f"MOBILE_{kind.upper()}", actor=request.user,
          detail={"ref": doc.ref, "channel": "mobile"})
    doc.refresh_from_db()
    return Response(_document_payload(doc, request))


@api_view(["POST"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_approve(request, ref):
    return _act(request, ref, "approve")


@api_view(["POST"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_return(request, ref):
    return _act(request, ref, "return")


# ---- Originator: my requests / timeline / alerts ------------------------

TRACKABLE = ("MR", "IR", "MAR", "SD", "MS", "PMR", "PR", "PYR")

# A live status is a "current" step; these read as finished/terminal.
_TERMINAL = {"CLOSED", "COMPLETE", "PAID", "RECEIVED", "REJECTED", "CANCELLED",
             "PAID_PO_ISSUED", "VERIFIED", "ACKNOWLEDGED"}


def _request_line(doc):
    bits = [doc.site.code] if doc.site_id else []
    if doc.project_id:
        bits.append(doc.project.code)
    bits.append(doc.status.replace("_", " ").title())
    return " · ".join(bits)


@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_requests(request):
    """Documents this user raised, newest activity first, with an unread-change
    dot when an alert about them is still unread."""
    from .models import Document, Notification
    docs = Document.objects.filter(
        created_by=request.user, is_void=False, doc_type__in=TRACKABLE) \
        .select_related("site", "project").order_by("-updated_at")[:60]
    unread_refs = set(Notification.objects.filter(
        recipient=request.user, read_at__isnull=True)
        .values_list("doc_ref", flat=True))
    items = [{
        "ref": d.ref, "doc_type": d.doc_type,
        "site_code": d.site.code if d.site_id else "—",
        "status": d.status, "status_label": d.status.replace("_", " ").title(),
        "line": _request_line(d), "updated_at": d.updated_at,
        "unread": d.ref in unread_refs,
    } for d in docs]
    return Response({"items": items})


def _timeline(doc):
    """A tracking stepper derived from the document's own status audit plus its
    linked downstream documents — no new chain model (R6 §5.5)."""
    steps = [{"label": "Raised", "ref": doc.ref,
              "when": doc.created_at.date().isoformat(), "state": "done"}]
    for a in doc.approvals.select_related("actor").order_by("acted_at"):
        steps.append({
            "label": (a.result or a.action or "").replace("_", " ").title(),
            "ref": a.actor.full_name if a.actor_id else (a.actor_role or ""),
            "when": a.acted_at.date().isoformat(), "state": "done"})

    def add_linked(d, hop=0):
        seen = set()
        links = (list(d.links_from.select_related("to_document")) +
                 list(d.links_to.select_related("from_document")))
        for lk in links:
            other = (lk.to_document if lk.from_document_id == d.id
                     else lk.from_document)
            if (not other or other.id == doc.id or other.id in seen
                    or other.doc_type in ("PO",)):
                continue
            seen.add(other.id)
            steps.append({
                "label": f"{other.doc_type} · "
                         f"{other.status.replace('_', ' ').title()}",
                "ref": other.ref,
                "when": other.doc_date.isoformat() if other.doc_date else "",
                "state": "done" if other.status in _TERMINAL else "current"})
            if hop < 1 and other.doc_type in ("MR", "PR", "LM"):
                add_linked(other, hop + 1)   # e.g. MR→LM→GRN

    add_linked(doc)
    return steps


@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_timeline(request, ref):
    from .models import Document
    try:
        doc = Document.objects.select_related("site", "project").get(ref=ref)
    except Document.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    sids = scoped_site_ids(request.user)
    if (doc.created_by_id != request.user.id and sids is not None
            and doc.site_id not in sids):
        return Response({"detail": "Not found."}, status=404)
    return Response({"ref": doc.ref, "doc_type": doc.doc_type,
                     "title_line": _request_line(doc),
                     "status": doc.status, "steps": _timeline(doc)})


@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_alerts(request):
    """The originator alerts feed — the existing Notification records."""
    from .models import Notification
    from .views_notify import NotificationSerializer
    qs = Notification.objects.filter(recipient=request.user)[:40]
    unread = Notification.objects.filter(
        recipient=request.user, read_at__isnull=True).count()
    return Response({"unread": unread,
                     "items": NotificationSerializer(qs, many=True).data})


# ---- Web push subscriptions ---------------------------------------------

@api_view(["GET"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_vapid_key(request):
    from .push import vapid_public_key
    key = vapid_public_key()
    return Response({"public_key": key, "enabled": bool(key)})


@api_view(["POST"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_push_subscribe(request):
    """Register this browser's push endpoint. Body: {endpoint, keys:{p256dh,
    auth}}."""
    from .models import PushSubscription
    endpoint = (request.data.get("endpoint") or "").strip()
    keys = request.data.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        return Response({"detail": "endpoint + keys are required."}, status=400)
    sub, _ = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={"user": request.user, "p256dh": keys["p256dh"][:200],
                  "auth": keys["auth"][:100],
                  "label": (request.META.get("HTTP_USER_AGENT") or "")[:120]})
    return Response({"id": sub.id}, status=201)


@api_view(["POST"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_push_unsubscribe(request):
    from .models import PushSubscription
    endpoint = (request.data.get("endpoint") or "").strip()
    PushSubscription.objects.filter(user=request.user,
                                    endpoint=endpoint).delete()
    return Response({"ok": True})


@api_view(["POST"])
@authentication_classes(MOBILE_AUTH)
@permission_classes([IsAuthenticated])
def m_alerts_read(request):
    from django.utils import timezone

    from .models import Notification
    qs = Notification.objects.filter(recipient=request.user,
                                     read_at__isnull=True)
    ids = request.data.get("ids")
    if ids:
        qs = qs.filter(id__in=ids)
    qs.update(read_at=timezone.now())
    return Response({"ok": True})
