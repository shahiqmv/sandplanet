import { useEffect, useState } from "react";
import { api } from "./api.js";
import { SectionTitle, StatusChip, buttonStyle, card, ghostButton, inputStyle,
         td, th } from "./ui.jsx";

export const QA_LABELS = {
  IR: "Inspection Request",
  MAR: "Material Approval Request",
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

const ENCLOSURES = [
  ["sample", "Sample"], ["catalogue", "Catalogue"],
  ["technical_data", "Technical Data"], ["test_report", "Test Report"],
  ["compliance_sheet", "Compliance Sheet"], ["company_profile", "Company Profile"],
];

const RESULT_OPTIONS = {
  IR: [["APPROVED", "Approved"],
       ["APPROVED_WITH_COMMENTS", "Approved with comments"],
       ["REJECTED", "Rejected"]],
  MAR: [["APPROVED", "Approved"],
        ["APPROVED_WITH_COMMENTS", "Approved with comments"],
        ["REVISE_RESUBMIT", "Revise & resubmit"],
        ["REJECTED", "Rejected"]],
};

const SITE_TEAM = ["SITE_ENGINEER", "SITE_ADMIN", "PM", "ADMIN"];

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

export function QAForm({ docType, site, project, existing, prefill, onSaved,
                         onCancel }) {
  const [payload, setPayload] = useState(existing?.payload ||
                                         prefill?.payload || {});
  const [docDate, setDocDate] = useState(
    existing?.doc_date ||
    (docType === "TWS"
      ? new Date(Date.now() + 86400000).toISOString().slice(0, 10)
      : new Date().toISOString().slice(0, 10))
  );
  const [activities, setActivities] = useState(payload.activities?.length
    ? payload.activities : [{ activity: "", location: "", trade: "",
                              remarks: "" }]);
  const [categories, setCategories] = useState([]);
  const [manpower, setManpower] = useState(payload.manpower || {});
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (docType === "TWS") {
      api("/manpower-categories").then((all) =>
        setCategories(all.filter((c) => c.list_type === "TWS" && c.is_active)));
    }
  }, [docType]);

  const fields = docType === "IR" ? IR_FIELDS
               : docType === "MAR" ? MAR_FIELDS : [];
  const setP = (k, v) => setPayload((p) => ({ ...p, [k]: v }));

  async function save() {
    setBusy(true);
    setError(null);
    const body = { ...payload };
    if (docType === "TWS") {
      body.activities = activities.filter((a) => a.activity);
      body.manpower = manpower;
    }
    try {
      let doc;
      if (existing) {
        doc = await api(`/documents/${existing.ref}`, {
          method: "PATCH", body: { payload: body, doc_date: docDate },
        });
      } else {
        const req = { doc_type: docType, site_id: site.id, doc_date: docDate,
                      project_id: project?.id || null, payload: body };
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
          <input type="date" value={docDate} disabled={!!existing}
                 onChange={(e) => setDocDate(e.target.value)}
                 style={inputStyle} />
        </label>
        {fields.map((def) => (
          <Field key={def[0]} def={def} value={payload[def[0]]}
                 onChange={(v) => setP(def[0], v)} />
        ))}
      </div>

      {docType === "MAR" && (
        <>
          <SectionTitle>Enclosures</SectionTitle>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            {ENCLOSURES.map(([key, label]) => (
              <label key={key} style={{ fontSize: 13 }}>
                <input type="checkbox"
                       checked={!!(payload.enclosures || {})[key]}
                       onChange={(e) => setP("enclosures", {
                         ...(payload.enclosures || {}),
                         [key]: e.target.checked,
                       })} /> {label}
              </label>
            ))}
          </div>
        </>
      )}

      {docType === "TWS" && (
        <>
          <SectionTitle>1. Planned Activities</SectionTitle>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>Planned Activity</th>
              <th style={th}>Location/Area/Villa</th>
              <th style={th}>Trade</th><th style={th}>Remarks</th><th />
            </tr></thead>
            <tbody>
              {activities.map((row, i) => (
                <tr key={i}>
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
            {Object.values(manpower).reduce((a, b) => a + (+b || 0), 0)}
          </SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                        gap: 20 }}>
            {[["Staff", "STAFF"], ["Trades / Labour", "LABOUR"]].map(
              ([label, grp]) => (
              <div key={grp}>
                <strong style={{ fontSize: 13, color: "var(--sp-navy)" }}>
                  {label}</strong>
                {categories.filter((c) => c.grp === grp).map((c) => (
                  <div key={c.id} style={{ display: "flex",
                       justifyContent: "space-between", alignItems: "center",
                       padding: "2px 0" }}>
                    <span style={{ fontSize: 13 }}>{c.name}</span>
                    <input type="number" min="0" value={manpower[c.id] ?? ""}
                           onChange={(e) => setManpower({ ...manpower,
                                                          [c.id]: e.target.value })}
                           style={{ ...inputStyle, width: 70 }} />
                  </div>
                ))}
              </div>
            ))}
          </div>

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
  const isQA = doc.doc_type === "IR" || doc.doc_type === "MAR";

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
    if (doc.doc_type === "MAR" && doc.status === "REVISE_RESUBMIT" &&
        isSiteTeam) {
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
          Enclosures: {ENCLOSURES.filter(([k]) => p.enclosures[k])
            .map(([, l]) => l).join(", ") || "none"}
        </p>
      )}

      {p.activities?.length > 0 && (
        <>
          <SectionTitle>Planned Activities</SectionTitle>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>Activity</th><th style={th}>Location</th>
              <th style={th}>Trade</th><th style={th}>Remarks</th>
            </tr></thead>
            <tbody>
              {p.activities.map((a, i) => (
                <tr key={i}>
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
