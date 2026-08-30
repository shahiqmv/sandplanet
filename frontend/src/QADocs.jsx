import { useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { SectionTitle, StatusChip, buttonStyle, card, ghostButton, inputStyle,
         td, th } from "./ui.jsx";

export const QA_LABELS = {
  IR: "Inspection Request",
  MAR: "Material Approval Request",
  SD: "Shop Drawing Submittal",
  MS: "Method Statement",
  MXD: "Concrete Mix Design",
  BBS: "Bar Bending Schedule",
  TWD: "Temporary Works Design",
  MOC: "Sample / Mock-up Approval",
  TWS: "Tomorrow Work Schedule",
};

const IR_FIELDS = [
  ["discipline", "Discipline", "select",
   ["Civil", "Structural", "Architectural", "MEP", "Finishes", "Marine",
    "Other"]],
  ["location", "Location / Villa", "text"],
  ["requested_date", "Inspection requested — date", "date"],
  ["requested_time", "Inspection requested — time", "time"],
  ["ncr_ref", "NCR Ref (if closure)", "text"],
  ["ref_drawings", "Reference drawings / documents", "text"],
  ["enclosed", "Drawings enclosed", "checkbox"],
  ["work_description", "Description of work ready for inspection", "textarea"],
  ["work_after", "Work proposed after inspection", "textarea"],
];

const MAR_FIELDS = [
  ["attention_to", "Attention To", "text"],
  ["material_description", "Material / Sample description", "textarea"],
  ["location_use", "Location / Use", "text"],
  ["spec_ref", "Specification Ref", "text"],
  ["drawing_ref", "Drawing Ref", "text"],
  ["boq_ref", "BOQ Ref", "text"],
  ["manufacturer", "Manufacturer", "text"],
  ["supplier", "Supplier", "text"],
  ["origin", "Country of Origin", "text"],
  ["warranty", "Warranty (if any)", "text"],
  ["confirms_spec", "Confirms to Specification", "checkbox"],
  ["proposed_equivalent", "Proposed as Equivalent", "checkbox"],
  ["reasons", "Reasons for Alteration / Equivalent", "textarea"],
  ["remarks", "Remarks", "textarea"],
];

// Shop Drawing — drawing-focused transmittal (owner 2026-08-05).
const SD_FIELDS = [
  ["attention_to", "Attention To", "text"],
  ["drawing_title", "Drawing Title", "text"],
  ["drawing_no", "Drawing No.", "text"],
  ["drawing_rev", "Drawing Revision", "text"],
  ["discipline", "Discipline / Trade", "select",
   ["Civil", "Structural", "Architectural", "MEP", "Finishes", "Marine",
    "Other"]],
  ["spec_ref", "Specification Ref", "text"],
  ["boq_ref", "BOQ Ref", "text"],
  ["confirms_design", "Confirms to Design / Spec", "checkbox"],
  ["remarks", "Remarks", "textarea"],
];

// Method Statement — minimal fields; the prepared PDF rides as the enclosure.
const MS_FIELDS = [
  ["attention_to", "Attention To", "text"],
  ["statement_title", "Statement Title", "text"],
  ["activity_scope", "Activity / Scope", "textarea"],
  ["reference", "Reference", "text"],
  ["remarks", "Remarks", "textarea"],
];

// Concrete mix design — a MAR describes a product, this describes a RECIPE,
// and it is what a cube result is judged against (owner 2026-08-30).
const MXD_FIELDS = [
  ["attention_to", "Attention To", "text"],
  ["mix_ref", "Mix reference", "text"],
  ["grade", "Grade", "text"],
  ["application", "Where it is used", "text"],
  ["design_strength", "Design strength at 28 days (N/mm²)", "text"],
  ["batching_plant", "Batching plant / supplier", "text"],
  ["cement_type", "Cement type", "text"],
  ["cement_content", "Cement content (kg/m³)", "text"],
  ["wc_ratio", "Water / cement ratio", "text"],
  ["target_slump", "Target slump (mm)", "text"],
  ["coarse_aggregate", "Coarse aggregate", "text"],
  ["fine_aggregate", "Fine aggregate", "text"],
  ["admixture", "Admixture", "text"],
  ["trial_ref", "Trial mix reference", "text"],
  ["trial_result", "Trial mix result", "text"],
  ["spec_ref", "Specification Ref", "text"],
  ["boq_ref", "BOQ Ref", "text"],
  ["remarks", "Remarks", "textarea"],
];

// Bar bending schedule — approved before the steel is cut, because once it
// is cut it is cut.
const BBS_FIELDS = [
  ["attention_to", "Attention To", "text"],
  ["element", "Element", "text"],
  ["location", "Location", "text"],
  ["drawing_ref", "Structural drawing", "text"],
  ["drawing_rev", "Drawing revision", "text"],
  ["steel_grade", "Steel grade", "text"],
  ["bar_marks", "Number of bar marks", "text"],
  ["total_weight", "Total weight (kg)", "text"],
  ["spec_ref", "Specification Ref", "text"],
  ["confirms_design", "Scheduled from the approved drawing", "checkbox"],
  ["remarks", "Remarks", "textarea"],
];

// Temporary works — the independent design CHECK is the field that matters.
// Temporary works fail while people are standing on them.
const TWD_FIELDS = [
  ["attention_to", "Attention To", "text"],
  ["tw_type", "Type", "select",
   ["Formwork", "Falsework", "Shoring / propping", "Scaffolding",
    "Excavation support", "Lifting / craneage", "Other"]],
  ["location", "Location", "text"],
  ["supports", "Permanent works supported", "text"],
  ["in_use", "In use from / to", "text"],
  ["designed_by", "Designed by", "text"],
  ["design_loading", "Design loading", "text"],
  ["checked_by", "Independently checked by", "text"],
  ["check_date", "Check date", "date"],
  ["striking", "Striking / dismantling criteria", "textarea"],
  ["spec_ref", "Specification / standard", "text"],
  ["remarks", "Remarks", "textarea"],
];

// A mock-up approves the BUILT result, not the product on paper — so what
// matters is where it stands, what it represents, and whether it is kept as
// the benchmark the rest of the work is judged against (owner 2026-08-30).
const MOC_FIELDS = [
  ["attention_to", "Attention To", "text"],
  ["mockup_title", "Mock-up", "text"],
  ["represents", "Represents (scope it sets the standard for)", "textarea"],
  ["location", "Location on site", "text"],
  ["built_on", "Built on", "date"],
  ["spec_ref", "Specification Ref", "text"],
  ["drawing_ref", "Drawing Ref", "text"],
  ["materials", "Materials used / approved MAR refs", "textarea"],
  ["workmanship", "Workmanship notes", "textarea"],
  ["retained", "Retained on site as the benchmark", "checkbox"],
  ["retain_until", "Retained until", "date"],
  ["remarks", "Remarks", "textarea"],
];

const FIELDS_BY_TYPE = { MAR: MAR_FIELDS, SD: SD_FIELDS, MS: MS_FIELDS,
                         MXD: MXD_FIELDS, BBS: BBS_FIELDS,
                         TWD: TWD_FIELDS, MOC: MOC_FIELDS };

// Per-type attachment slots (files uploaded here are compiled into the PDF).
const ENCLOSURES_BY_TYPE = {
  MAR: [["sample", "Sample"], ["catalogue", "Catalogue"],
        ["technical_data", "Technical Data"], ["test_report", "Test Report"],
        ["compliance_sheet", "Compliance Sheet"],
        ["company_profile", "Company Profile"]],
  SD: [["shop_drawing", "Shop Drawing"], ["detail_section", "Detail / Section"],
       ["reference", "Reference"]],
  MS: [["method_statement", "Method Statement"],
       ["risk_assessment", "Risk Assessment"], ["itp", "ITP"]],
  MXD: [["mix_design", "Mix design certificate"],
        ["trial_results", "Trial mix results"],
        ["aggregate_tests", "Aggregate test reports"],
        ["cement_cert", "Cement certificate"],
        ["admixture_data", "Admixture data sheet"]],
  BBS: [["schedule", "Bar bending schedule"],
        ["reinforcement_drawing", "Reinforcement drawing"],
        ["shape_codes", "Bar shape codes"]],
  MOC: [["photographs", "Photographs"], ["drawings", "Drawings"],
        ["material_list", "Material list"]],
  TWD: [["design_drawings", "Design drawings"],
        ["calculations", "Calculations"],
        ["check_certificate", "Design check certificate"],
        ["risk_assessment", "Risk assessment"],
        ["method_statement", "Method statement"]],
};

// Exported: App routes an opened document to the QA viewer off this list.
// Hand-copying it there is what left MXD/BBS/TWD/MOC opening as line
// documents (owner 2026-08-30).
export const SUBMITTAL_TYPES = ["MAR", "SD", "MS", "MXD", "BBS", "TWD",
                                "MOC"];

const RESULT_OPTIONS = {
  IR: [["APPROVED", "Approved"],
       ["APPROVED_WITH_COMMENTS", "Approved with comments"],
       ["REJECTED", "Rejected"]],
  MAR: [["APPROVED", "Approved"],
        ["APPROVED_WITH_COMMENTS", "Approved with comments"],
        ["REVISE_RESUBMIT", "Revise & resubmit"],
        ["REJECTED", "Rejected"]],
};
RESULT_OPTIONS.SD = RESULT_OPTIONS.MAR;
RESULT_OPTIONS.MS = RESULT_OPTIONS.MAR;
// The civil submittals take the same four results as a material approval:
// approved, approved with comments, revise & resubmit, rejected.
RESULT_OPTIONS.MXD = RESULT_OPTIONS.MAR;
RESULT_OPTIONS.BBS = RESULT_OPTIONS.MAR;
RESULT_OPTIONS.TWD = RESULT_OPTIONS.MAR;
RESULT_OPTIONS.MOC = RESULT_OPTIONS.MAR;

const SITE_TEAM = ["SITE_ENGINEER", "SITE_ADMIN", "PM", "DIRECTOR", "ADMIN"];

function Field({ def, value, onChange }) {
  const [key, label, kind, options] = def;
  if (kind === "checkbox") {
    return (
      <label style={{ fontSize: 13, display: "flex", gap: 6,
                      alignItems: "center" }}>
        <input type="checkbox" checked={!!value}
               onChange={(e) => onChange(e.target.checked)} /> {label}
      </label>
    );
  }
  if (kind === "textarea") {
    return (
      <label style={{ fontSize: 13, gridColumn: "1 / -1" }}>{label}
        <textarea value={value || ""} rows={3}
                  onChange={(e) => onChange(e.target.value)}
                  style={{ ...inputStyle, resize: "vertical" }} />
      </label>
    );
  }
  if (kind === "select") {
    return (
      <label style={{ fontSize: 13 }}>{label}
        <select value={value || ""} onChange={(e) => onChange(e.target.value)}
                style={inputStyle}>
          <option value="" />
          {options.map((o) => <option key={o}>{o}</option>)}
        </select>
      </label>
    );
  }
  return (
    <label style={{ fontSize: 13 }}>{label}
      <input type={kind} value={value || ""}
             onChange={(e) => onChange(e.target.value)} style={inputStyle} />
    </label>
  );
}

// Local YYYY-MM-DD (avoids the UTC shift toISOString would cause east of GMT).
function localISO(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-`
    + `${String(d.getDate()).padStart(2, "0")}`;
}

// TWS is next-working-day's schedule. The "day" rolls over at 3am, so a
// schedule keyed in just after midnight is for the coming day, not the day
// after (owner 2026-07-14).
export function twsDefaultDate() {
  const base = new Date();
  if (base.getHours() < 3) base.setDate(base.getDate() - 1);
  base.setDate(base.getDate() + 1);
  return localISO(base);
}

export function QAForm({ docType, site, project, projects = [], existing,
                         prefill, onSaved, onCancel }) {
  // TWS is SITE-WIDE (R8): planned rows are tagged per project; IR/MAR
  // remain project documents.
  const activeProjects = projects.filter((pr) => pr.status === "ACTIVE");
  // Every submittal belongs to a project; a TWS is site-wide. The backend
  // only demands one when the site actually has an active project, so the
  // form asks on exactly the same condition.
  const needsProject = docType !== "TWS" && activeProjects.length > 0;
  const [payload, setPayload] = useState(existing?.payload ||
                                         prefill?.payload || {});
  // The document's project is a field ON the form. It used to be inherited
  // invisibly from the chip selected on the site page, which worked only
  // while submittals were raised from there — off the submittals page you
  // filled the whole form and lost it to a 400 on save (owner 2026-08-30).
  const [projectId, setProjectId] = useState(
    String(existing?.project_id || project?.id || ""));
  const [docDate, setDocDate] = useState(
    existing?.doc_date ||
    (docType === "TWS" ? twsDefaultDate()
      : new Date().toISOString().slice(0, 10))
  );
  const [activities, setActivities] = useState(payload.activities?.length
    ? payload.activities : [{ activity: "", location: "", trade: "",
                              remarks: "" }]);
  const [categories, setCategories] = useState([]);
  // Manpower as dynamic rows (like the DPR form) — only the categories in
  // use are shown, no wasted grid space (owner)
  const [mpRows, setMpRows] = useState(
    Object.entries(payload.manpower || {})
      .filter(([, n]) => +n > 0)
      .map(([category_id, count]) => ({ category_id: String(category_id),
                                        count: String(count) })));
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [encAtts, setEncAtts] = useState(
    (existing?.attachments || []).filter((a) => a.kind === "ENCLOSURE"));

  async function refreshEnc() {
    if (!existing) return;
    const d = await api(`/documents/${existing.ref}`);
    setEncAtts((d.attachments || []).filter((a) => a.kind === "ENCLOSURE"));
  }
  async function uploadEnclosure(label, key, fileList) {
    const files = [...(fileList || [])];
    if (!files.length) return;
    setBusy(true); setError(null);
    try {
      for (const file of files) {
        const fd = new FormData();
        fd.append("file", file);
        fd.append("kind", "ENCLOSURE");
        fd.append("caption", label);
        await apiUpload(`/documents/${existing.ref}/attachments`, fd);
      }
      setP("enclosures", { ...(payload.enclosures || {}), [key]: true });
      await refreshEnc();
    } catch (e) { setError(e.message); }
    setBusy(false);
  }
  async function deleteEnclosure(id) {
    setBusy(true); setError(null);
    try {
      await api(`/documents/${existing.ref}/attachments/${id}`,
                { method: "DELETE" });
      await refreshEnc();
    } catch (e) { setError(e.message); }
    setBusy(false);
  }

  useEffect(() => {
    if (docType === "TWS") {
      // One company-wide worker list for both DPR and TWS (owner)
      api("/manpower-categories").then((all) =>
        setCategories(all.filter((c) => c.list_type === "DPR" && c.is_active)));
    }
  }, [docType]);

  const fields = docType === "IR" ? IR_FIELDS
               : (FIELDS_BY_TYPE[docType] || []);
  const setP = (k, v) => setPayload((p) => ({ ...p, [k]: v }));

  async function save() {
    setBusy(true);
    setError(null);
    const body = { ...payload };
    if (docType === "TWS") {
      body.activities = activities.filter((a) => a.activity);
      body.manpower = Object.fromEntries(
        mpRows.filter((r) => r.category_id && +r.count > 0)
          .map((r) => [r.category_id, +r.count]));
    }
    if (needsProject && !existing && !projectId) {
      setError("Select the project this submittal belongs to.");
      setBusy(false);
      return;
    }
    try {
      let doc;
      if (existing) {
        doc = await api(`/documents/${existing.ref}`, {
          method: "PATCH", body: { payload: body, doc_date: docDate },
        });
      } else {
        const req = { doc_type: docType, site_id: site.id, doc_date: docDate,
                      project_id: docType === "TWS" ? null
                                  : projectId || null,
                      payload: body };
        if (prefill?.previous_ir_ref) {
          req.previous_ir_ref = prefill.previous_ir_ref;
        }
        doc = await api("/documents", { method: "POST", body: req });
      }
      onSaved(doc);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
          {existing ? `${existing.ref} (draft)` : `New ${QA_LABELS[docType]}`}
          {prefill?.previous_ir_ref &&
            ` — resubmission of ${prefill.previous_ir_ref}`}
        </h2>
        <button onClick={onCancel} style={ghostButton}>Close</button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
                    gap: 12, marginTop: 16 }}>
        <label style={{ fontSize: 13 }}>
          {docType === "TWS" ? "Schedule for (date)" : "Date"}
          {/* TWS date stays editable on a draft so a late-night entry can be
              corrected to the right day (owner 2026-07-14) */}
          <input type="date" value={docDate}
                 disabled={!!existing && docType !== "TWS"}
                 onChange={(e) => setDocDate(e.target.value)}
                 style={inputStyle} />
        </label>
        {needsProject && (
          <label style={{ fontSize: 13 }}>
            Project
            {/* Locked once the document exists: moving a raised submittal to
                another project is a different act from filling this in. */}
            <select value={projectId} disabled={!!existing}
                    onChange={(e) => setProjectId(e.target.value)}
                    style={{ ...inputStyle,
                             borderColor: projectId ? undefined : "#b35900" }}>
              <option value="">— select the project —</option>
              {activeProjects.map((pr) => (
                <option key={pr.id} value={pr.id}>
                  {pr.code} — {pr.title}
                </option>
              ))}
            </select>
          </label>
        )}
        {fields.map((def) => (
          <Field key={def[0]} def={def} value={payload[def[0]]}
                 onChange={(v) => setP(def[0], v)} />
        ))}
      </div>

      {SUBMITTAL_TYPES.includes(docType) && (
        <>
          <SectionTitle>{docType === "SD" ? "Drawings"
            : docType === "MS" ? "Attachments" : "Enclosures"}</SectionTitle>
          {!existing && (
            <p style={{ fontSize: 12, color: "#5a6b78", margin: "0 0 8px" }}>
              Tick what you're attaching. Save the draft, then attach the actual
              files (PDF or image) here — they're compiled into the submittal
              PDF.</p>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {(ENCLOSURES_BY_TYPE[docType] || []).map(([key, label]) => {
              const files = encAtts.filter((a) => a.caption === label);
              return (
                <div key={key} style={{ display: "flex", alignItems: "center",
                  gap: 10, flexWrap: "wrap" }}>
                  <label style={{ fontSize: 13, minWidth: 155 }}>
                    <input type="checkbox"
                           checked={!!(payload.enclosures || {})[key]
                                    || files.length > 0}
                           onChange={(e) => setP("enclosures", {
                             ...(payload.enclosures || {}),
                             [key]: e.target.checked })} /> {label}
                  </label>
                  {existing && (
                    <label style={{ ...ghostButton, padding: "2px 10px",
                      fontSize: 12, cursor: busy ? "wait" : "pointer" }}>
                      + Attach
                      <input type="file" hidden multiple
                        accept="application/pdf,image/*" disabled={busy}
                        onChange={(e) => {
                          uploadEnclosure(label, key, e.target.files);
                          e.target.value = "";
                        }} />
                    </label>
                  )}
                  {files.map((a) => (
                    <span key={a.id} style={{ fontSize: 12,
                      background: "#eef4f8", borderRadius: 6,
                      padding: "2px 8px" }}>
                      📎 {a.file_name}
                      <button onClick={() => deleteEnclosure(a.id)}
                        disabled={busy}
                        style={{ border: "none", background: "none",
                          cursor: "pointer", color: "#c0392b",
                          marginLeft: 4 }}>×</button>
                    </span>
                  ))}
                </div>
              );
            })}
          </div>
        </>
      )}

      {docType === "TWS" && (
        <>
          <SectionTitle>1. Planned Activities</SectionTitle>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>Project</th>
              <th style={th}>Planned Activity</th>
              <th style={th}>Location/Area/Villa</th>
              <th style={th}>Trade</th><th style={th}>Remarks</th><th />
            </tr></thead>
            <tbody>
              {activities.map((row, i) => (
                <tr key={i}>
                  <td style={{ padding: 3 }}>
                    <select value={row.project || ""}
                            onChange={(e) => setActivities(activities.map(
                              (r, j) => j === i
                                ? { ...r, project: e.target.value } : r))}
                            style={{ ...inputStyle, width: 105 }}>
                      <option value="">General</option>
                      {activeProjects.map((pr) => (
                        <option key={pr.id} value={pr.code}>{pr.code}</option>
                      ))}
                    </select>
                  </td>
                  {["activity", "location", "trade", "remarks"].map((f) => (
                    <td key={f} style={{ padding: 3 }}>
                      <input value={row[f] || ""}
                             onChange={(e) => setActivities(activities.map(
                               (r, j) => j === i ? { ...r, [f]: e.target.value }
                                                 : r))}
                             style={inputStyle} />
                    </td>
                  ))}
                  <td style={{ width: 30 }}>
                    <button onClick={() => setActivities(
                              activities.filter((_, j) => j !== i))}
                            style={{ ...ghostButton, padding: "2px 8px",
                                     color: "#c0392b" }}>×</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button onClick={() => setActivities([...activities, {}])}
                  style={{ ...ghostButton, padding: "4px 12px", marginTop: 6 }}>
            + Add row
          </button>

          <SectionTitle>2. Planned Manpower — total{" "}
            {mpRows.reduce((a, r) => a + (+r.count || 0), 0)}
          </SectionTitle>
          {mpRows.map((row, i) => {
            const used = mpRows.map((r) => r.category_id);
            return (
              <div key={i} style={{ display: "flex", gap: 8,
                   alignItems: "center", marginBottom: 6 }}>
                <select value={row.category_id}
                        onChange={(e) => setMpRows(mpRows.map((r, j) =>
                          j === i ? { ...r, category_id: e.target.value } : r))}
                        style={{ ...inputStyle, width: 280 }}>
                  <option value="">— category —</option>
                  {[["Staff", "STAFF"], ["Trades / Labour", "LABOUR"]].map(
                    ([label, grp]) => (
                    <optgroup key={grp} label={label}>
                      {categories.filter((c) => c.grp === grp).map((c) => (
                        <option key={c.id} value={String(c.id)}
                                disabled={used.includes(String(c.id)) &&
                                          String(c.id) !== row.category_id}>
                          {c.name}</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
                <input type="number" min="0" value={row.count}
                       placeholder="count"
                       onChange={(e) => setMpRows(mpRows.map((r, j) =>
                         j === i ? { ...r, count: e.target.value } : r))}
                       style={{ ...inputStyle, width: 90 }} />
                <button type="button"
                        onClick={() => setMpRows(mpRows.filter((_, j) =>
                          j !== i))}
                        style={{ ...ghostButton, padding: "2px 8px",
                                 color: "#c0392b" }}>×</button>
              </div>
            );
          })}
          <button type="button"
                  onClick={() => setMpRows([...mpRows,
                                            { category_id: "", count: "" }])}
                  style={{ ...ghostButton, padding: "4px 12px" }}>
            + Add category
          </button>

          <SectionTitle>3. Access / Support Required from Client</SectionTitle>
          <textarea value={payload.access_support || ""} rows={3}
                    onChange={(e) => setP("access_support", e.target.value)}
                    style={{ ...inputStyle, resize: "vertical" }} />
        </>
      )}

      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {existing ? "Save changes" : "Save draft"}
        </button>
      </div>
    </section>
  );
}

function ResultPanel({ doc, onAct }) {
  const [result, setResult] = useState("");
  const [comment, setComment] = useState("");
  const [reviewedBy, setReviewedBy] = useState("");
  const [position, setPosition] = useState("");

  return (
    <div style={{ background: "#f4f7fa", border: "1px solid var(--sp-border)",
                  borderRadius: 8, padding: 16, margin: "12px 0" }}>
      <strong style={{ color: "var(--sp-navy)", fontSize: 14 }}>
        Record client / consultant result
      </strong>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10,
                    marginTop: 10 }}>
        <select value={result} onChange={(e) => setResult(e.target.value)}
                style={inputStyle}>
          <option value="">Result…</option>
          {RESULT_OPTIONS[doc.doc_type].map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
        <input placeholder="Reviewed / inspected by (name)" value={reviewedBy}
               onChange={(e) => setReviewedBy(e.target.value)}
               style={inputStyle} />
        <input placeholder="Position" value={position}
               onChange={(e) => setPosition(e.target.value)} style={inputStyle} />
        <input placeholder="Observations / comments" value={comment}
               onChange={(e) => setComment(e.target.value)} style={inputStyle} />
      </div>
      <button disabled={!result} style={{ ...buttonStyle, marginTop: 10 }}
              onClick={() => onAct("record-result",
                                   { result, comment, reviewed_by: reviewedBy,
                                     position })}>
        Record result
      </button>
    </div>
  );
}

export function QADocView({ doc: initial, me, onClose, onChanged, onEdit,
                            onResubmit }) {
  const [doc, setDoc] = useState(initial);
  const [error, setError] = useState(null);
  const p = doc.payload || {};

  async function act(action, body) {
    setError(null);
    try {
      const fresh = await api(`/documents/${doc.ref}/actions/${action}`,
                              { method: "POST", body });
      setDoc(fresh);
      onChanged?.();
    } catch (e) {
      setError(e.message);
    }
  }

  const role = me.role;
  const isSiteTeam = SITE_TEAM.includes(role);
  const canPmGate = role === "PM" || role === "ADMIN";
  const pdfs = (doc.attachments || []).filter((a) => a.kind === "GENERATED_PDF");
  const isQA = doc.doc_type === "IR" || SUBMITTAL_TYPES.includes(doc.doc_type);

  const buttons = [];
  if (!doc.is_void) {
    if (doc.status === "DRAFT") {
      buttons.push(["Continue editing", () => onEdit(doc)]);
      if (isQA) buttons.push(["Submit", () => act("submit")]);
      if (doc.doc_type === "TWS") buttons.push(["Issue", () => act("issue")]);
    }
    if (isQA && doc.status === "SUBMITTED" && canPmGate) {
      buttons.push(["Approve (PM)", () => act("approve")]);
      buttons.push(["Return with comment", () => {
        const comment = window.prompt("Return comment (required):");
        if (comment) act("return", { comment });
      }]);
    }
    if (isQA && doc.status === "PM_APPROVED") {
      buttons.push(["Issue to client", () => act("issue")]);
    }
    if (doc.doc_type === "TWS" && doc.status === "ISSUED" && isSiteTeam) {
      buttons.push(["Record acknowledgement", () => {
        const name = window.prompt("Acknowledged by (client representative):");
        if (name) act("acknowledge", { acknowledged_by: name });
      }]);
    }
    if (doc.doc_type === "IR" && doc.status === "APPROVED_WITH_COMMENTS" &&
        canPmGate) {
      buttons.push(["Close Part C (corrective action)", () => {
        const text = window.prompt("Corrective action taken (required):");
        if (text) act("close", { comment: text });
      }]);
    }
    if (doc.doc_type === "IR" && doc.status === "CLOSED_BY_PM" && isSiteTeam) {
      buttons.push(["Record client verification", () => {
        const name = window.prompt("Verified by (client, name):");
        if (name) act("client-verify", { verified_by: name });
      }]);
    }
    if (doc.doc_type === "IR" && doc.status === "REJECTED" && isSiteTeam) {
      buttons.push(["Resubmit as new IR", () => onResubmit(doc)]);
    }
    if (SUBMITTAL_TYPES.includes(doc.doc_type)
        && doc.status === "REVISE_RESUBMIT" && isSiteTeam) {
      buttons.push(["Revise & resubmit (new revision)", async () => {
        try {
          const fresh = await api(`/documents/${doc.ref}/revisions`,
                                  { method: "POST" });
          onEdit(fresh);
        } catch (e) {
          setError(e.message);
        }
      }]);
    }
  }

  const result = p.client_result;

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
          {doc.ref} <span style={{ color: "#5a6b78", fontSize: 14 }}>
            {doc.rev_label}</span>{" "}
          <StatusChip status={doc.is_void ? "VOID" : doc.status} />
        </h2>
        <button onClick={onClose} style={ghostButton}>Close</button>
      </div>
      <p style={{ color: "#5a6b78", fontSize: 13, margin: "6px 0 0" }}>
        {QA_LABELS[doc.doc_type]} · {doc.site_name} · {doc.doc_date} ·
        prepared by {doc.created_by_name}
        {doc.previous_ir_ref && ` · resubmission of ${doc.previous_ir_ref}`}
        {doc.resubmitted_as && ` · resubmitted as ${doc.resubmitted_as}`}
        {doc.is_void && ` · VOID: ${doc.void_reason}`}
      </p>

      <div style={{ display: "flex", gap: 10, margin: "14px 0",
                    flexWrap: "wrap" }}>
        {buttons.map(([label, fn]) => (
          <button key={label} onClick={fn} style={buttonStyle}>{label}</button>
        ))}
        {pdfs.map((f) => (
          <a key={f.id} href={f.url} target="_blank" rel="noreferrer"
             style={{ ...ghostButton, textDecoration: "none",
                      display: "inline-block" }}>
            PDF — {f.file_name}
          </a>
        ))}
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {isQA && doc.status === "ISSUED" && isSiteTeam && (
        <ResultPanel doc={doc} onAct={act} />
      )}

      {result && (
        <div style={{ border: "1px solid var(--sp-border)", borderRadius: 8,
                      padding: 12, margin: "8px 0", background:
                      result.result === "APPROVED" ? "#effaf1" : "#fff8e6" }}>
          <strong>{result.result.replace(/_/g, " ")}</strong>
          {result.comments && <> — {result.comments}</>}
          <div style={{ fontSize: 12, color: "#5a6b78" }}>
            {[result.reviewed_by, result.position,
              result.approval_date || result.inspection_date]
              .filter(Boolean).join(" · ")}
          </div>
        </div>
      )}
      {p.closure && (
        <div style={{ border: "1px solid var(--sp-border)", borderRadius: 8,
                      padding: 12, margin: "8px 0" }}>
          <strong>Part C closure</strong> — {p.closure.corrective_action}
          <div style={{ fontSize: 12, color: "#5a6b78" }}>
            {[p.closure.closed_by_pm && `Closed by ${p.closure.closed_by_pm}`,
              p.closure.verified_by && `Verified by ${p.closure.verified_by}`,
              p.closure.verified_date].filter(Boolean).join(" · ")}
          </div>
        </div>
      )}

      <SectionTitle>Details</SectionTitle>
      <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
        <tbody>
          {Object.entries(p)
            .filter(([k, v]) => v !== "" && v != null &&
                    typeof v !== "object" && k !== "access_support")
            .map(([k, v]) => (
              <tr key={k}>
                <td style={{ ...td, color: "#5a6b78", borderTop: "none",
                             paddingRight: 18 }}>{k.replace(/_/g, " ")}</td>
                <td style={{ ...td, borderTop: "none" }}>
                  {v === true ? "Yes" : v === false ? "No" : String(v)}</td>
              </tr>
            ))}
        </tbody>
      </table>

      {p.enclosures && (
        <p style={{ fontSize: 13 }}>
          Enclosures: {(ENCLOSURES_BY_TYPE[doc.doc_type] || [])
            .filter(([k]) => p.enclosures[k])
            .map(([, l]) => l).join(", ") || "none"}
        </p>
      )}

      {p.activities?.length > 0 && (
        <>
          <SectionTitle>Planned Activities</SectionTitle>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>Project</th>
              <th style={th}>Activity</th><th style={th}>Location</th>
              <th style={th}>Trade</th><th style={th}>Remarks</th>
            </tr></thead>
            <tbody>
              {p.activities.map((a, i) => (
                <tr key={i}>
                  <td style={td}>{a.project || "General"}</td>
                  <td style={td}>{a.activity}</td><td style={td}>{a.location}</td>
                  <td style={td}>{a.trade}</td><td style={td}>{a.remarks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {p.access_support && (
        <>
          <SectionTitle>Access / Support Required</SectionTitle>
          <p style={{ fontSize: 13 }}>{p.access_support}</p>
        </>
      )}

      {doc.revisions?.length > 1 && (
        <p style={{ fontSize: 12, color: "#5a6b78" }}>
          Revisions: {doc.revisions.map((r) =>
            r.is_current ? `${r.rev_label} (current)` : r.rev_label)
            .join(" · ")}
        </p>
      )}

      {doc.approvals?.length > 0 && (
        <>
          <SectionTitle>Workflow trail</SectionTitle>
          {doc.approvals.map((a) => (
            <p key={a.id} style={{ fontSize: 12, color: "#1a7f37",
                                   margin: "4px 0" }}>
              {a.action}{a.result && ` (${a.result})`} — {a.actor_name}{" "}
              ({a.actor_role.replace(/_/g, " ")}) —{" "}
              {new Date(a.acted_at).toLocaleString()}
              {a.comment && ` — "${a.comment}"`}
            </p>
          ))}
        </>
      )}
    </section>
  );
}
