"""PDF contexts for the QA/section forms: IR / MAR / TWS (spec §5.2–§5.4).
Rendered through pdf_templates/pdf/qa_form.html on the shared letterhead."""

from datetime import date

from .models import ManpowerCategory
from .pdf import company_info, logo_src as _logo_src

RESULT_LABELS = {
    "APPROVED": ("Approved", "ok"),
    "APPROVED_WITH_COMMENTS": ("Approved with Comments", "warn"),
    "REVISE_RESUBMIT": ("Revise & Resubmit", "warn"),
    "REJECTED": ("Rejected", "bad"),
}


def _yesno(value):
    return "Yes" if value else "No"


def _stamp_for(approvals, action):
    for a in approvals:
        if a.action == action:
            return (f"{a.actor.full_name} — {a.actor_role} — "
                    f"{a.acted_at.strftime('%d/%m/%y %H:%M')} — "
                    f"approved electronically via Sand Planet Project Management App")
    return ""


def _client_by(payload):
    block = payload.get("client_result") or {}
    return " — ".join(
        x for x in [block.get("reviewed_by", ""), block.get("position", "")] if x
    )


def _result_section(payload, title):
    block = payload.get("client_result")
    if not block:
        return []
    label, tone = RESULT_LABELS.get(block.get("result"),
                                    (block.get("result"), ""))
    by = " — ".join(x for x in [block.get("reviewed_by"), block.get("position"),
                                block.get("inspection_date") or
                                block.get("approval_date")] if x)
    return [{
        "kind": "result", "title": title, "result_label": label, "tone": tone,
        "comments": block.get("comments", ""), "by": by,
    }]


def ir_context(document, revision):
    payload = revision.payload or {}
    approvals = list(document.approvals.select_related("actor"))
    sections = [
        {"kind": "text", "title": "Part A — Work ready for inspection",
         "text": payload.get("work_description", "")},
        {"kind": "text", "title": "Work proposed after inspection",
         "text": payload.get("work_after", "")},
        {"kind": "kv", "title": "References", "rows": [
            ["Reference drawings/documents", payload.get("ref_drawings", ""),
             "Enclosed", _yesno(payload.get("enclosed"))],
        ]},
        {"kind": "text", "title": "QA/QC confirmation",
         "text": "We confirm the works above are complete and ready for "
                 "inspection in accordance with the contract documents."},
    ]
    sections += _result_section(payload, "Part B — Client / Consultant result")
    block = payload.get("client_result") or {}
    if block.get("result") == "APPROVED_WITH_COMMENTS" or payload.get("closure"):
        closure = payload.get("closure", {})
        sections.append({
            "kind": "kv", "title": "Part C — Comment / Rejection Closure",
            "rows": [
                ["Corrective action taken", closure.get("corrective_action", ""),
                 "Closed by (PM)", closure.get("closed_by_pm", "")],
                ["Verified by (Client)", closure.get("verified_by", ""),
                 "Date", closure.get("verified_date", "")],
            ],
        })
    prev = document.previous_ir.ref if document.previous_ir else "—"
    return {
        "doc": document, "rev": revision, "site": document.site,
        "logo_src": _logo_src(), "co": company_info(),
        "form_title": "INSPECTION REQUEST",
        "form_subline": f"Form No: FRM-PRJ-02  |  Rev: {revision.rev_label}",
        "header_rows": [
            ["Discipline", payload.get("discipline", ""), "Previous IR", prev],
            ["Inspection requested",
             f"{payload.get('requested_date', '')} "
             f"{payload.get('requested_time', '')}",
             "Location / Villa", payload.get("location", "")],
            ["NCR Ref", payload.get("ncr_ref", ""), "", ""],
        ],
        "sections": sections,
        "sig_blocks": [
            {"title": "Submitted By — Site Engineer / QA-QC",
             "stamp": _stamp_for(approvals, "SUBMIT")},
            {"title": "Approved By — Project Manager",
             "stamp": _stamp_for(approvals, "APPROVE")},
            {"title": "Inspected By — Client / Consultant",
             "text": _client_by(payload)},
        ],
    }


def mar_context(document, revision):
    payload = revision.payload or {}
    approvals = list(document.approvals.select_related("actor"))
    enclosures = payload.get("enclosures") or {}
    sections = [
        {"kind": "kv", "title": "1. Material Details", "rows": [
            ["Material / Sample", payload.get("material_description", ""),
             "Location / Use", payload.get("location_use", "")],
            ["Specification Ref", payload.get("spec_ref", ""),
             "Drawing Ref", payload.get("drawing_ref", "")],
            ["BOQ Ref", payload.get("boq_ref", ""),
             "Manufacturer", payload.get("manufacturer", "")],
            ["Supplier", payload.get("supplier", ""),
             "Country of Origin", payload.get("origin", "")],
            ["Warranty", payload.get("warranty", ""), "", ""],
        ]},
        {"kind": "enclosures", "title": "2. Attachments / Enclosures",
         "items": [(name, bool(enclosures.get(key))) for name, key in [
             ("Sample", "sample"), ("Catalogue", "catalogue"),
             ("Technical Data", "technical_data"),
             ("Test Report", "test_report"),
             ("Compliance Sheet", "compliance_sheet"),
             ("Company Profile", "company_profile")]]},
        {"kind": "kv", "title": "3. Contractor Confirmation", "rows": [
            ["Confirms to Specification", _yesno(payload.get("confirms_spec")),
             "Proposed as Equivalent",
             _yesno(payload.get("proposed_equivalent"))],
            ["Reasons for Alteration/Equivalent", payload.get("reasons", ""),
             "Remarks", payload.get("remarks", "")],
        ]},
    ]
    sections += _result_section(payload, "4. Client / Consultant Review")
    return {
        "doc": document, "rev": revision, "site": document.site,
        "logo_src": _logo_src(), "co": company_info(),
        "form_title": "MATERIAL APPROVAL REQUEST",
        "form_subline": f"Form No: FRM-PRJ-03  |  Rev: {revision.rev_label}",
        "header_rows": [
            ["Attention To", payload.get("attention_to", ""),
             "Revision", revision.rev_label],
        ],
        "sections": sections,
        "sig_blocks": [
            {"title": "Submitted By — Site Engineer / QS",
             "stamp": _stamp_for(approvals, "SUBMIT")},
            {"title": "Approved By — Project Manager",
             "stamp": _stamp_for(approvals, "APPROVE")},
            {"title": "Reviewed By — Client / Consultant",
             "text": _client_by(payload)},
        ],
    }


def dma_context(document, revision):
    """Daily Manpower Allocation (R5) — internal notice-board sheet: the
    PM's morning task assignments off the previous day's TWSs, with the
    manpower at work totalled by category."""
    payload = revision.payload or {}
    approvals = list(document.approvals.select_related("actor"))
    tasks = payload.get("tasks", [])
    totals, total = {}, 0
    for t in tasks:
        try:
            count = int(t.get("workers") or 0)
        except (TypeError, ValueError):
            count = 0
        if count:
            key = (t.get("category") or "Unassigned").strip() or "Unassigned"
            totals[key] = totals.get(key, 0) + count
            total += count
    sections = [
        {"kind": "table", "title": "1. Task Allocation",
         "headers": ["No.", "Task", "Project", "Location/Area", "Category",
                     "Workers", "Remarks"],
         "rows": [[i + 1, t.get("task", ""), t.get("project", "") or "General",
                   t.get("location", ""), t.get("category", ""),
                   t.get("workers", ""), t.get("remarks", "")]
                  for i, t in enumerate(tasks)]},
        {"kind": "table", "title": f"2. Manpower at Work — total {total}",
         "headers": ["Category", "Workers"],
         "rows": sorted(totals.items())},
    ]
    if payload.get("notes"):
        sections.append({"kind": "text", "title": "3. Notes / Instructions",
                         "text": payload["notes"]})
    tws_refs = payload.get("tws_refs") or []
    return {
        "doc": document, "rev": revision, "site": document.site,
        "logo_src": _logo_src(), "co": company_info(),
        "form_title": "DAILY MANPOWER ALLOCATION",
        "form_subline": "Form No: FRM-PRJ-06  |  Internal",
        "header_rows": [
            ["Allocation For", document.doc_date.strftime("%d/%m/%y"),
             "Based on TWS", ", ".join(tws_refs) or "—"],
            ["Working Hours", payload.get("working_hours", ""), "", ""],
        ],
        "sections": sections,
        "sig_blocks": [
            {"title": "Allocated By — Project Manager",
             "stamp": _stamp_for(approvals, "ISSUE")},
            {"title": ""},
            {"title": ""},
        ],
    }


def tws_context(document, revision):
    payload = revision.payload or {}
    approvals = list(document.approvals.select_related("actor"))
    # One company-wide worker list for both DPR and TWS (owner) — the same
    # list the DPR form/PDF use.
    categories = {
        c.id: c for c in ManpowerCategory.objects.filter(list_type="DPR")
    }
    counts = payload.get("manpower", {}) or {}
    manpower_rows, total = [], 0
    for cat in sorted(categories.values(), key=lambda c: (c.grp, c.sort_order)):
        count = int(counts.get(str(cat.id), 0) or 0)
        if count:
            manpower_rows.append([cat.grp, cat.name, count])
            total += count
    sections = [
        # TWS is site-wide; each planned row is tagged per project (R8)
        {"kind": "table", "title": "1. Planned Activities",
         "headers": ["No.", "Planned Activity", "Project",
                     "Location/Area/Villa", "Trade", "Remarks"],
         "rows": [[i + 1, a.get("activity", ""),
                   a.get("project") or "General", a.get("location", ""),
                   a.get("trade", ""), a.get("remarks", "")]
                  for i, a in enumerate(payload.get("activities", []))]},
        {"kind": "table", "title": f"2. Planned Manpower — total {total}",
         "headers": ["Group", "Category", "Count"], "rows": manpower_rows},
        {"kind": "text", "title": "3. Access / Support Required from Client",
         "text": payload.get("access_support", "") or "None."},
    ]
    ack = payload.get("acknowledgement") or {}
    return {
        "doc": document, "rev": revision, "site": document.site,
        "logo_src": _logo_src(), "co": company_info(),
        "form_title": "TOMORROW WORK SCHEDULE",
        "form_subline": "Form No: FRM-PRJ-04  |  Rev: R0",
        "header_rows": [
            ["Schedule For",
             f"{document.doc_date.strftime('%d/%m/%y')}",
             "Issued On", date.today().strftime("%d/%m/%y")],
            ["Working Hours", payload.get("working_hours", ""), "", ""],
        ],
        "sections": sections,
        "sig_blocks": [
            {"title": "Prepared By — Site Engineer",
             "stamp": _stamp_for(approvals, "ISSUE")},
            {"title": "Acknowledged By — Client Representative",
             "text": " — ".join(x for x in [ack.get("acknowledged_by", ""),
                                            ack.get("date", "")] if x)},
            {"title": ""},
        ],
    }
