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


def sd_context(document, revision):
    """Shop Drawing submittal — same transmittal form as the MAR, with drawing
    fields and the drawing files as enclosures."""
    payload = revision.payload or {}
    approvals = list(document.approvals.select_related("actor"))
    enclosures = payload.get("enclosures") or {}
    sections = [
        {"kind": "kv", "title": "1. Drawing Details", "rows": [
            ["Drawing Title", payload.get("drawing_title", ""),
             "Drawing No.", payload.get("drawing_no", "")],
            ["Drawing Revision", payload.get("drawing_rev", ""),
             "Discipline / Trade", payload.get("discipline", "")],
            ["Specification Ref", payload.get("spec_ref", ""),
             "BOQ Ref", payload.get("boq_ref", "")],
        ]},
        {"kind": "enclosures", "title": "2. Attachments / Drawings",
         "items": [(name, bool(enclosures.get(key))) for name, key in [
             ("Shop Drawing", "shop_drawing"),
             ("Detail / Section", "detail_section"),
             ("Reference", "reference")]]},
        {"kind": "kv", "title": "3. Contractor Confirmation", "rows": [
            ["Confirms to Design / Spec", _yesno(payload.get("confirms_design")),
             "Remarks", payload.get("remarks", "")],
        ]},
    ]
    sections += _result_section(payload, "4. Client / Consultant Review")
    return {
        "doc": document, "rev": revision, "site": document.site,
        "logo_src": _logo_src(), "co": company_info(),
        "form_title": "SHOP DRAWING SUBMITTAL",
        "form_subline": f"Form No: FRM-PRJ-04  |  Rev: {revision.rev_label}",
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


def ms_context(document, revision):
    """Method Statement submittal — same transmittal form as the MAR; the
    prepared method-statement PDF rides along as the enclosure."""
    payload = revision.payload or {}
    approvals = list(document.approvals.select_related("actor"))
    enclosures = payload.get("enclosures") or {}
    sections = [
        {"kind": "kv", "title": "1. Statement Details", "rows": [
            ["Statement Title", payload.get("statement_title", ""),
             "Reference", payload.get("reference", "")],
            ["Activity / Scope", payload.get("activity_scope", ""),
             "Remarks", payload.get("remarks", "")],
        ]},
        {"kind": "enclosures", "title": "2. Attachments",
         "items": [(name, bool(enclosures.get(key))) for name, key in [
             ("Method Statement", "method_statement"),
             ("Risk Assessment", "risk_assessment"),
             ("ITP", "itp")]]},
    ]
    sections += _result_section(payload, "3. Client / Consultant Review")
    return {
        "doc": document, "rev": revision, "site": document.site,
        "logo_src": _logo_src(), "co": company_info(),
        "form_title": "METHOD STATEMENT SUBMITTAL",
        "form_subline": f"Form No: FRM-PRJ-05  |  Rev: {revision.rev_label}",
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
    # Worker-assignments per category across tasks. A crew reused on several
    # tasks is counted once per task, so this is an ALLOCATION count — NOT the
    # headcount on site. The real manpower on site comes from that day's
    # attendance (owner 2026-08-04).
    alloc = {}
    for t in tasks:
        try:
            count = int(t.get("workers") or 0)
        except (TypeError, ValueError):
            count = 0
        if count:
            key = (t.get("category") or "Unassigned").strip() or "Unassigned"
            alloc[key] = alloc.get(key, 0) + count
    from .views_hr import site_manpower_data
    mp = site_manpower_data(document.site, document.doc_date)
    present = {c["name"]: c["present"] for c in mp["categories"] if c["present"]}
    att_in = bool(mp["attendance_entered"] and mp["present"])
    names = sorted(set(alloc) | set(present))
    if att_in:
        alloc_title = (f"2. Allocation by Category  ·  {mp['present']} on site "
                       "(from attendance)")
        alloc_headers = ["Category", "Assigned", "On site"]
        alloc_rows = [[n, alloc.get(n, "—"), present.get(n, "—")] for n in names]
    else:
        alloc_title = "2. Allocation by Category (worker-assignments)"
        alloc_headers = ["Category", "Assigned"]
        alloc_rows = [[n, alloc.get(n, "—")] for n in names]
    sections = [
        {"kind": "table", "title": "1. Task Allocation",
         "headers": ["No.", "Task", "Project", "Location/Area", "Category",
                     "Workers", "Remarks"],
         "rows": [[i + 1, t.get("task", ""), t.get("project", "") or "General",
                   t.get("location", ""), t.get("category", ""),
                   t.get("workers", ""), t.get("remarks", "")]
                  for i, t in enumerate(tasks)]},
        {"kind": "table", "title": alloc_title,
         "headers": alloc_headers, "rows": alloc_rows},
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


def tr_context(document, revision):
    """Test request / report. One document carries both halves: the request
    the consultant is asked to witness, and every result that came back
    against it — so the sheet handed over at the end is the same sheet the
    lab was asked for (owner 2026-08-29)."""
    test = document.material_test
    results = list(test.results.select_related("recorded_by"))
    approvals = list(document.approvals.select_related("actor"))
    unit = test.unit or ""

    sections = [
        {"kind": "kv", "title": "Sample", "rows": [
            ["Element", test.element, "Location", test.location or "—"],
            ["Pour / batch ref", test.pour_ref or "—",
             "Grade / mix", test.grade or "—"],
            ["Quantity represented", test.quantity or "—",
             "Sampled on", test.sampled_on],
        ]},
        {"kind": "kv", "title": "Requirement", "rows": [
            ["Specification", test.spec_reference or "—",
             "Required",
             f"{test.required_value} {unit}" if test.required_value
             else "—"],
            ["Acceptance criteria", test.acceptance_criteria or "—",
             "Laboratory", test.lab_name or "—"],
        ]},
    ]
    if results:
        sections.append({
            "kind": "table", "title": "Results",
            "headers": ["Age (days)", "Tested", "Specimen", "Result",
                        "Outcome", "Lab report"],
            "rows": [[
                r.age_days if r.age_days is not None else "—",
                r.tested_on or "—",
                r.specimen_ref or "—",
                f"{r.value} {r.unit or unit}" if r.value is not None else "—",
                r.get_outcome_display(),
                r.report_ref or "—",
            ] for r in results],
        })
    else:
        sections.append({
            "kind": "text", "title": "Results",
            "text": "No results received yet."
                    + (f" The {test.final_age_days()}-day result is due "
                       f"{test.result_due_on()}."
                       if test.result_due_on() else ""),
        })
    if test.notes:
        sections.append({"kind": "text", "title": "Notes",
                         "text": test.notes})
    if test.ncr_id:
        sections.append({
            "kind": "text", "title": "Non-conformance",
            "text": f"This failure is covered by {test.ncr.ref}.",
        })

    return {
        "doc": document, "rev": revision, "site": document.site,
        "logo_src": _logo_src(), "co": company_info(),
        "form_title": "TEST REQUEST / REPORT",
        "form_subline": f"Form No: FRM-QAQ-01  |  Rev: {revision.rev_label}",
        "header_rows": [
            ["Test", test.get_kind_display(), "Status",
             document.get_status_display() if hasattr(document,
                                                      "get_status_display")
             else document.status],
            ["Project",
             document.project.code if document.project_id else "Site-wide",
             "Witnessed by", test.witnessed_by or "—"],
        ],
        "sections": sections,
        "sig_blocks": [
            {"title": "Requested By — Site Engineer / QA-QC",
             "stamp": _stamp_for(approvals, "SUBMIT"),
             "text": test.requested_by.full_name},
            {"title": "Witnessed By — Client / Consultant",
             "text": test.witnessed_by or ""},
            {"title": "Reviewed By — Project Manager",
             "stamp": _stamp_for(approvals, "APPROVE")},
        ],
    }


def mxd_context(document, revision):
    """Concrete mix design. A MAR describes a product; this describes a
    RECIPE, and the consultant approves it before anything is poured. It is
    also what a cube result is judged against — a strength figure means
    nothing without the mix it came from (owner 2026-08-30)."""
    payload = revision.payload or {}
    approvals = list(document.approvals.select_related("actor"))
    sections = [
        {"kind": "kv", "title": "1. Mix", "rows": [
            ["Mix reference", payload.get("mix_ref", ""),
             "Grade", payload.get("grade", "")],
            ["Where it is used", payload.get("application", ""),
             "Design strength (28 day)",
             payload.get("design_strength", "")],
            ["Batching plant / supplier", payload.get("batching_plant", ""),
             "Target slump", payload.get("target_slump", "")],
        ]},
        {"kind": "kv", "title": "2. Proportions", "rows": [
            ["Cement type", payload.get("cement_type", ""),
             "Cement content (kg/m³)", payload.get("cement_content", "")],
            ["Water / cement ratio", payload.get("wc_ratio", ""),
             "Admixture", payload.get("admixture", "")],
            ["Coarse aggregate", payload.get("coarse_aggregate", ""),
             "Fine aggregate", payload.get("fine_aggregate", "")],
        ]},
        {"kind": "kv", "title": "3. Trial mix", "rows": [
            ["Trial mix reference", payload.get("trial_ref", ""),
             "Trial result", payload.get("trial_result", "")],
            ["Specification Ref", payload.get("spec_ref", ""),
             "BOQ Ref", payload.get("boq_ref", "")],
        ]},
        {"kind": "enclosures", "title": "4. Attachments",
         "items": _enclosure_rows(payload, [
             ("mix_design", "Mix design certificate"),
             ("trial_results", "Trial mix results"),
             ("aggregate_tests", "Aggregate test reports"),
             ("cement_cert", "Cement certificate"),
             ("admixture_data", "Admixture data sheet")])},
        {"kind": "text", "title": "5. Contractor confirmation",
         "text": payload.get("remarks", "")
         or "We confirm the mix above meets the specified requirements."},
    ]
    sections += _result_section(payload, "Client / Consultant result")
    return {
        "doc": document, "rev": revision, "site": document.site,
        "logo_src": _logo_src(), "co": company_info(),
        "form_title": "CONCRETE MIX DESIGN SUBMITTAL",
        "form_subline": f"Form No: FRM-CIV-01  |  Rev: {revision.rev_label}",
        "header_rows": [
            ["Attention", payload.get("attention_to", ""),
             "Project", document.project.code if document.project_id else "—"],
            ["Grade", payload.get("grade", ""),
             "Where it is used", payload.get("application", "")],
        ],
        "sections": sections,
        "sig_blocks": _submittal_signatures(approvals, payload),
    }


def bbs_context(document, revision):
    """Bar bending schedule. Approved before steel is cut and bent, because
    once it is cut it is cut."""
    payload = revision.payload or {}
    approvals = list(document.approvals.select_related("actor"))
    sections = [
        {"kind": "kv", "title": "1. Schedule details", "rows": [
            ["Element", payload.get("element", ""),
             "Location", payload.get("location", "")],
            ["Structural drawing", payload.get("drawing_ref", ""),
             "Drawing revision", payload.get("drawing_rev", "")],
            ["Steel grade", payload.get("steel_grade", ""),
             "Bar marks", payload.get("bar_marks", "")],
            ["Total weight (kg)", payload.get("total_weight", ""),
             "Specification Ref", payload.get("spec_ref", "")],
        ]},
        {"kind": "enclosures", "title": "2. Attachments",
         "items": _enclosure_rows(payload, [
             ("schedule", "Bar bending schedule"),
             ("reinforcement_drawing", "Reinforcement drawing"),
             ("shape_codes", "Bar shape codes")])},
        {"kind": "kv", "title": "3. Contractor confirmation", "rows": [
            ["Scheduled from the approved drawing",
             _yesno(payload.get("confirms_design")),
             "Remarks", payload.get("remarks", "")],
        ]},
    ]
    sections += _result_section(payload, "Client / Consultant result")
    return {
        "doc": document, "rev": revision, "site": document.site,
        "logo_src": _logo_src(), "co": company_info(),
        "form_title": "BAR BENDING SCHEDULE SUBMITTAL",
        "form_subline": f"Form No: FRM-CIV-02  |  Rev: {revision.rev_label}",
        "header_rows": [
            ["Attention", payload.get("attention_to", ""),
             "Project", document.project.code if document.project_id else "—"],
            ["Element", payload.get("element", ""),
             "Drawing", payload.get("drawing_ref", "")],
        ],
        "sections": sections,
        "sig_blocks": _submittal_signatures(approvals, payload),
    }


def twd_context(document, revision):
    """Temporary works — formwork, falsework, shoring, scaffolding.

    The independent design CHECK is the field that matters: temporary works
    fail while people are standing on them, and the check is what a consultant
    asks for first."""
    payload = revision.payload or {}
    approvals = list(document.approvals.select_related("actor"))
    sections = [
        {"kind": "kv", "title": "1. The works", "rows": [
            ["Type", payload.get("tw_type", ""),
             "Location", payload.get("location", "")],
            ["Permanent works supported", payload.get("supports", ""),
             "In use from / to", payload.get("in_use", "")],
        ]},
        {"kind": "kv", "title": "2. Design", "rows": [
            ["Designed by", payload.get("designed_by", ""),
             "Design loading", payload.get("design_loading", "")],
            ["Independently checked by", payload.get("checked_by", ""),
             "Check date", payload.get("check_date", "")],
            ["Specification / standard", payload.get("spec_ref", ""),
             "Striking / dismantling criteria",
             payload.get("striking", "")],
        ]},
        {"kind": "enclosures", "title": "3. Attachments",
         "items": _enclosure_rows(payload, [
             ("design_drawings", "Design drawings"),
             ("calculations", "Calculations"),
             ("check_certificate", "Design check certificate"),
             ("risk_assessment", "Risk assessment"),
             ("method_statement", "Method statement")])},
        {"kind": "text", "title": "4. Contractor confirmation",
         "text": payload.get("remarks", "")
         or "We confirm the temporary works above have been designed and "
            "independently checked for the loads stated."},
    ]
    sections += _result_section(payload, "Client / Consultant result")
    return {
        "doc": document, "rev": revision, "site": document.site,
        "logo_src": _logo_src(), "co": company_info(),
        "form_title": "TEMPORARY WORKS SUBMITTAL",
        "form_subline": f"Form No: FRM-CIV-03  |  Rev: {revision.rev_label}",
        "header_rows": [
            ["Attention", payload.get("attention_to", ""),
             "Project", document.project.code if document.project_id else "—"],
            ["Type", payload.get("tw_type", ""),
             "Location", payload.get("location", "")],
        ],
        "sections": sections,
        "sig_blocks": _submittal_signatures(approvals, payload),
    }


def _enclosure_rows(payload, pairs):
    """(label, present?) for the attachment checklist, from the payload's
    enclosures map — the same shape MAR and SD build inline."""
    enclosures = payload.get("enclosures") or {}
    return [(label, bool(enclosures.get(key))) for key, label in pairs]


def _submittal_signatures(approvals, payload):
    return [
        {"title": "Submitted By — Site Engineer / QA-QC",
         "stamp": _stamp_for(approvals, "SUBMIT")},
        {"title": "Approved By — Project Manager",
         "stamp": _stamp_for(approvals, "APPROVE")},
        {"title": "Reviewed By — Client / Consultant",
         "text": _client_by(payload)},
    ]


def moc_context(document, revision):
    """Sample / mock-up approval.

    Distinct from a material approval: a MAR approves a product on paper, a
    mock-up approves the BUILT result — the tiling, the joint, the finish —
    and once signed it becomes the benchmark the rest of the work is measured
    against. Whether it is retained on site matters, because an argument
    about workmanship six months later is settled by walking to it
    (owner 2026-08-30)."""
    payload = revision.payload or {}
    approvals = list(document.approvals.select_related("actor"))
    sections = [
        {"kind": "kv", "title": "1. What was built", "rows": [
            ["Mock-up", payload.get("mockup_title", ""),
             "Represents", payload.get("represents", "")],
            ["Location on site", payload.get("location", ""),
             "Built on", payload.get("built_on", "")],
            ["Specification Ref", payload.get("spec_ref", ""),
             "Drawing Ref", payload.get("drawing_ref", "")],
        ]},
        {"kind": "kv", "title": "2. Materials used", "rows": [
            ["Materials / approved MARs", payload.get("materials", ""),
             "Workmanship notes", payload.get("workmanship", "")],
        ]},
        {"kind": "enclosures", "title": "3. Attachments",
         "items": _enclosure_rows(payload, [
             ("photographs", "Photographs"),
             ("drawings", "Drawings"),
             ("material_list", "Material list")])},
        {"kind": "kv", "title": "4. After approval", "rows": [
            ["Retained on site as the benchmark",
             _yesno(payload.get("retained")),
             "Retained until", payload.get("retain_until", "")],
            ["Remarks", payload.get("remarks", ""), "", ""],
        ]},
    ]
    sections += _result_section(payload, "Client / Consultant result")
    return {
        "doc": document, "rev": revision, "site": document.site,
        "logo_src": _logo_src(), "co": company_info(),
        "form_title": "SAMPLE / MOCK-UP APPROVAL",
        "form_subline": f"Form No: FRM-CIV-04  |  Rev: {revision.rev_label}",
        "header_rows": [
            ["Attention", payload.get("attention_to", ""),
             "Project", document.project.code if document.project_id else "—"],
            ["Mock-up", payload.get("mockup_title", ""),
             "Location", payload.get("location", "")],
        ],
        "sections": sections,
        "sig_blocks": _submittal_signatures(approvals, payload),
    }
