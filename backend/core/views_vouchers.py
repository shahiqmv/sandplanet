"""Payment Voucher API (M6d). Finance builds and submits vouchers; a
signatory approves or queries them."""
from datetime import date
from decimal import Decimal

from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import vouchers
from .models import Document


def _line_info(line):
    if line.source_milestone_id:
        m = line.source_milestone
        order = m.order
        return {"line_id": line.id, "ref": order.document.ref,
                "doc_type": "MILESTONE", "site_code": "HO",
                "amount": line.amount, "currency": line.currency,
                "status": line.status, "query_note": line.query_note,
                "source_status": m.status,
                "payee": order.supplier.name, "cost_head": "Imports",
                "purpose": m.label, "milestone_label": m.label,
                "payment_ref": m.tt_ref, "mvr_paid": m.mvr_paid,
                # the TT itself is executed on the Import Payments page
                "paid": m.status == "PAID"}
    src = line.source_document
    info = {"line_id": line.id, "ref": src.ref, "doc_type": src.doc_type,
            "site_code": src.site.code, "amount": line.amount,
            "currency": line.currency,
            "status": line.status, "query_note": line.query_note,
            "source_status": src.status, "paid": False}
    if src.doc_type == "PYR" and hasattr(src, "payment_request"):
        pr = src.payment_request
        info.update({"payee": pr.payee, "cost_head": pr.cost_head.name,
                     "purpose": pr.purpose, "payment_type": pr.payment_type,
                     "has_supporting_doc": pr.has_supporting_doc,
                     "currency": pr.currency,
                     "payment_method": pr.payment_method,
                     "amount_paid": pr.amount_paid,
                     "payment_ref": pr.payment_ref,
                     "paid": src.status == "PAID"})
    if src.doc_type == "PR":
        rows = []
        for ln in src.current_revision.lines.all():
            cash = ln.amount_cash or 0
            credit = ln.amount_credit or 0
            if cash <= 0 and credit <= 0:
                continue
            # action_taken holds the slip/voucher ref once actually paid;
            # po_ref alone means ordered-not-yet-paid (credit vendors)
            rows.append({"line_id": ln.id,
                         "vendor": ln.vendor or ln.free_text_desc,
                         "amount_cash": cash, "amount_credit": credit,
                         "is_credit": credit > 0, "po_ref": ln.po_ref,
                         "payment_ref": ln.action_taken,
                         "paid": bool((ln.action_taken or "").strip())})
        info.update({
            "payee": ", ".join(r["vendor"] for r in rows if r["vendor"])
                     or "(procurement)",
            "cost_head": "Materials", "purpose": "Procurement",
            "vendor_rows": rows,
            "paid": bool(rows) and all(r["paid"] for r in rows)})
    return info


def _voucher_info(pv):
    lines = [_line_info(ln) for ln in pv.voucher_lines.select_related(
        "source_document__site",
        "source_milestone__order__document",
        "source_milestone__order__supplier").order_by("id")]
    approved = [ln for ln in lines if ln["status"] == "APPROVED"]
    currency = lines[0]["currency"] if lines else "MVR"
    return {
        "ref": pv.ref, "status": pv.status, "doc_date": pv.doc_date,
        "prepared_by": pv.created_by.full_name if pv.created_by else None,
        "currency": currency,
        "total": sum(ln["amount"] for ln in lines),
        "paid_count": sum(1 for ln in approved if ln["paid"]),
        "approved_count": len(approved),
        "settled": bool(approved) and all(ln["paid"] for ln in approved),
        "lines": lines,
        "approvals": [{"action": a.action, "by": a.actor.full_name,
                       "role": a.actor_role, "at": a.acted_at,
                       "comment": a.comment}
                      for a in pv.approvals.select_related("actor")
                      .order_by("acted_at")],
    }


@api_view(["GET"])
def awaiting_voucher(request):
    """Director-approved PR/PYR/IPR and due overseas TT milestones awaiting
    authorisation on a voucher."""
    if request.user.role not in ("FINANCE", "ADMIN"):
        return Response({"detail": "Finance builds vouchers."}, status=403)
    out = []
    for doc in vouchers.awaiting_voucher():
        row = {"kind": "DOC", "ref": doc.ref, "doc_type": doc.doc_type,
               "site_code": doc.site.code, "doc_date": doc.doc_date,
               "amount": vouchers._source_amount(doc),
               "currency": vouchers.source_currency(doc)}
        if doc.doc_type == "PYR" and hasattr(doc, "payment_request"):
            pr = doc.payment_request
            row.update({"payee": pr.payee, "cost_head": pr.cost_head.name,
                        "purpose": pr.purpose, "origin": pr.origin,
                        "has_supporting_doc": pr.has_supporting_doc})
        else:
            row.update({"payee": "(procurement)", "cost_head": "Materials"})
        out.append(row)
    for m in vouchers.awaiting_milestones():
        out.append({
            "kind": "MILESTONE", "milestone_id": m.id,
            "ref": m.order.document.ref, "doc_type": "MILESTONE",
            "site_code": "HO", "doc_date": m.due_date,
            "amount": vouchers.milestone_amount(m),
            "currency": vouchers.milestone_currency(m),
            "payee": m.order.supplier.name,
            "cost_head": f"Overseas TT · {m.label}",
            "purpose": m.label})
    return Response(out)


@api_view(["GET", "POST"])
def payment_vouchers(request):
    if request.method == "POST":
        if request.user.role not in ("FINANCE", "ADMIN"):
            return Response({"detail": "Finance builds vouchers."},
                            status=403)
        pv, err = vouchers.create_voucher(
            request.data.get("source_refs") or [], request.user,
            milestone_ids=request.data.get("milestone_ids") or [])
        if err:
            return Response({"detail": err}, status=400)
        return Response(_voucher_info(pv), status=201)
    if request.user.role not in ("FINANCE", "SIGNATORY", "ADMIN"):
        return Response({"detail": "Finance / signatory only."}, status=403)
    qs = Document.objects.filter(doc_type="PV").order_by("-id")
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    return Response([_voucher_info(pv) for pv in qs[:100]])


@api_view(["GET"])
def payment_voucher_detail(request, ref):
    try:
        pv = Document.objects.get(ref=ref, doc_type="PV")
    except Document.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in ("FINANCE", "SIGNATORY", "ADMIN"):
        return Response({"detail": "Finance / signatory only."}, status=403)
    return Response(_voucher_info(pv))


def _pay_str(li):
    """The payment reference(s) recorded on a line, for the filing PDF."""
    if li["doc_type"] == "PYR":
        return li.get("payment_ref") or ("paid" if li["paid"] else "")
    if li["doc_type"] == "PR":
        refs = [r["payment_ref"] for r in li.get("vendor_rows", [])
                if r.get("paid") and r.get("payment_ref")]
        return ", ".join(refs)
    if li["doc_type"] == "MILESTONE":
        return li.get("payment_ref") or ("paid" if li["paid"] else "")
    return ""


def _pv_pdf_context(pv):
    from .pdf import _money, _stamp_for, company_info, logo_src

    approvals = list(pv.approvals.select_related("actor"))
    rows, total = [], Decimal("0")
    info = _voucher_info(pv)
    for i, li in enumerate(info["lines"], 1):
        queried = li["status"] == "QUERIED"
        if not queried:
            total += Decimal(str(li["amount"] or 0))
        rows.append({
            "no": i, "ref": li["ref"], "site": li["site_code"],
            "payee": li.get("payee", ""), "purpose": li.get("purpose", ""),
            "cost_head": li.get("cost_head", ""),
            "amount": _money(li["amount"] or 0),
            "payment": _pay_str(li), "queried": queried})
    return {
        "doc": pv, "logo_src": logo_src(), "co": company_info(),
        "lines": rows, "total": _money(total), "settled": info["settled"],
        "currency": info["currency"],
        "prepared_by": pv.created_by.full_name if pv.created_by else "",
        "submit_stamp": _stamp_for(approvals, "SUBMIT"),
        "approve_stamp": _stamp_for(approvals, "APPROVE"),
        "generated": date.today().strftime("%d.%m.%Y"),
    }


@api_view(["GET"])
def finance_dashboard(request):
    """Money in motion for Finance (M6f, operational): what needs a voucher,
    vouchers in flight, what is waiting to be paid, outstanding payables, and
    petty-cash floats below their replenishment trigger."""
    if request.user.role not in ("FINANCE", "ADMIN"):
        return Response({"detail": "Finance only."}, status=403)
    from .models import Payable, PettyCashFloat
    from .petty_cash import cash_in_hand

    from . import fx
    from . import imports as ipr_svc
    rate = fx.usd_rate()

    def _mvr(amount, currency):
        amount = Decimal(str(amount or 0))
        return amount * rate if currency == "USD" else amount

    aw = vouchers.awaiting_voucher()
    aw_ms = list(vouchers.awaiting_milestones())
    aw_count = len(aw) + len(aw_ms)
    # A mixed-currency KPI: show the MVR-equivalent of everything awaiting a
    # voucher (USD converted at the company rate).
    aw_total = (
        sum((_mvr(vouchers._source_amount(d), vouchers.source_currency(d))
             for d in aw), Decimal("0"))
        + sum(((m.due_amount(ipr_svc.ipr_order_total(m.order))
                * m.order.exchange_rate) for m in aw_ms), Decimal("0")))
    pvs = Document.objects.filter(doc_type="PV")
    to_pay = []          # approved vouchers still carrying unpaid lines
    for pv in pvs.filter(status="APPROVED"):
        info = _voucher_info(pv)
        if not info["settled"]:
            to_pay.append({"ref": pv.ref, "total": info["total"],
                           "paid": info["paid_count"],
                           "lines": info["approved_count"]})
    pyr_pay = Document.objects.filter(doc_type="PYR", status="AUTHORISED")
    pyr_total = sum((_mvr(d.payment_request.amount_requested,
                          d.payment_request.currency) for d in pyr_pay
                     if hasattr(d, "payment_request")), Decimal("0"))
    payables = Payable.objects.filter(status="OUTSTANDING")
    pay_total = sum((p.amount for p in payables), Decimal("0"))
    floats = []
    for fl in PettyCashFloat.objects.filter(
            is_active=True).select_related("site", "custodian"):
        cih = cash_in_hand(fl)
        trigger = fl.imprest_amount * fl.trigger_pct / 100
        floats.append({"site": fl.site.code, "cash_in_hand": cih,
                       "imprest": fl.imprest_amount,
                       "below_trigger": cih <= trigger,
                       "custodian": fl.custodian.full_name})
    return Response({
        "awaiting_voucher": {"count": aw_count, "total": aw_total},
        "vouchers": {"draft": pvs.filter(status="DRAFT").count(),
                     "submitted": pvs.filter(status="SUBMITTED").count(),
                     "to_pay": to_pay},
        "pyr_to_pay": {"count": pyr_pay.count(), "total": pyr_total},
        "payables": {"count": payables.count(), "total": pay_total},
        "petty_cash": floats,
    })


@api_view(["GET"])
def payment_voucher_pdf(request, ref):
    """Letterhead PDF of the voucher for accounting filing (opens inline)."""
    try:
        pv = Document.objects.get(ref=ref, doc_type="PV")
    except Document.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    if request.user.role not in ("FINANCE", "SIGNATORY", "ADMIN"):
        return Response({"detail": "Finance / signatory only."}, status=403)
    from django.conf import settings
    from django.http import HttpResponse
    from django.template.loader import render_to_string

    html = render_to_string("pdf/payment_voucher.html", _pv_pdf_context(pv))
    try:
        from weasyprint import HTML

        pdf_bytes = HTML(string=html,
                         base_url=str(settings.MEDIA_ROOT)).write_pdf()
    except Exception:
        return Response({"detail": "PDF engine unavailable on this "
                                   "server."}, status=503)
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{pv.ref}.pdf"'
    return resp


@api_view(["POST"])
def payment_voucher_action(request, ref, action):
    try:
        pv = Document.objects.get(ref=ref, doc_type="PV")
    except Document.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    user = request.user
    if action == "submit":
        if user.role not in ("FINANCE", "ADMIN"):
            return Response({"detail": "Finance submits vouchers."},
                            status=403)
        err = vouchers.submit_voucher(pv, user)
    elif action == "approve":
        if user.role not in ("SIGNATORY", "ADMIN"):
            return Response({"detail": "Only a signatory approves a "
                                       "voucher — Finance prepares it."},
                            status=403)
        err = vouchers.approve_voucher(
            pv, user, queried_ids=request.data.get("queried_ids") or [],
            note=request.data.get("note", ""))
    elif action == "cancel":
        if user.role not in ("FINANCE", "ADMIN") or pv.status != "DRAFT":
            return Response({"detail": "Only Finance can cancel a draft "
                                       "voucher."}, status=400)
        pv.status = "CANCELLED"
        pv.save(update_fields=["status", "updated_at"])
        err = None
    else:
        return Response({"detail": f"Unknown action '{action}'."}, status=400)
    if err:
        return Response({"detail": err}, status=400)
    pv.refresh_from_db()
    return Response(_voucher_info(pv))
