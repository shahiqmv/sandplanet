import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import BoqPanel from "./BoqPanel.jsx";
import ProgrammePage from "./ProgrammePage.jsx";
import VariationsPanel from "./VariationsPanel.jsx";
import ClaimsPanel from "./ClaimsPanel.jsx";
import { Chip, Eyebrow, RefStamp, Stat, StatusChip, buttonStyle, card,
         ghostButton, inputStyle, td, th } from "./ui.jsx";

// Dedicated project workspace (owner, Phase A): a project has many
// components — programme, documents, and later manpower plan, BOM
// (built by the QS from the BOQ), budget and tender. Overview +
// Programme + Documents now; the other tabs are reserved slots.

const TABS = [
  ["overview", "Overview", true],
  ["programme", "Programme", true],
  ["manpower", "Manpower plan", true],
  ["documents", "Documents", true],
  ["commercial", "Commercial", true],  // QS: BOQ (claims follow)
  ["budget", "Budget · later", false],
  ["tender", "Tender · later", false],
];

const money = (v) => v == null ? null
  : Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });

export default function ProjectPage({ projectId, me, onClose, onOpenDoc }) {
  const [project, setProject] = useState(null);
  const [tab, setTab] = useState("overview");
  const [docs, setDocs] = useState(null);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(false);

  const load = useCallback(() => {
    api(`/projects/${projectId}`).then(setProject)
      .catch((e) => setError(e.message));
  }, [projectId]);
  useEffect(load, [load]);

  const canEdit = ["PM", "ADMIN", "DIRECTOR", "QS"].includes(me.role);
  const canDelete = ["ADMIN", "DIRECTOR"].includes(me.role);

  async function deleteProject() {
    if (!window.confirm(
          `Delete project ${project.code} — ${project.title}? This removes `
          + "the programme and all its activities. It can only be done while "
          + "the project has no documents. This can't be undone.")) return;
    setError(null);
    try {
      await api(`/projects/${projectId}`, { method: "DELETE" });
      onClose();
    } catch (e) { setError(e.message); }
  }

  useEffect(() => {
    if (tab === "documents") {
      api(`/projects/${projectId}/documents`).then(setDocs)
        .catch((e) => setError(e.message));
    }
  }, [tab, projectId]);

  if (error) return <section style={card}>{error}</section>;
  if (!project) return <section style={card}>Loading…</section>;

  const elapsed = (() => {
    if (!project.start_date || !project.planned_completion) return null;
    const s = new Date(project.start_date).getTime();
    const f = new Date(project.planned_completion).getTime();
    if (f <= s) return null;
    return Math.min(Math.max(Math.round(100 * (Date.now() - s) / (f - s)),
                             0), 100);
  })();
  const behind = elapsed != null &&
    Number(project.overall_progress) < elapsed - 10;

  return (
    <>
      <section style={{ ...card, paddingBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                      flexWrap: "wrap" }}>
          <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 18 }}>
            <RefStamp>{project.code}</RefStamp>{" "}
            {project.title}
          </h2>
          <StatusChip status={project.status} />
          <span style={{ fontSize: 13, color: "var(--muted)" }}>
            {project.site_code}</span>
          <a href={`/api/v1/projects/${project.id}/programme.pdf`}
             target="_blank" rel="noreferrer"
             title="The award package: programme Gantt + activity table +
manpower histogram, on the letterhead — send to the client"
             style={{ marginLeft: "auto", fontSize: 13,
                      color: "var(--navy)", fontWeight: 600 }}>
            ⬇ Programme PDF
          </a>
          {canEdit && (
            <button onClick={() => setEditing(true)} style={ghostButton}>
              ✎ Edit</button>
          )}
          {canDelete && (
            <button onClick={deleteProject}
                    style={{ ...ghostButton, color: "#c0392b" }}>
              Delete</button>
          )}
          <button onClick={onClose} style={ghostButton}>← Back</button>
        </div>
        <div style={{ display: "flex", gap: 6, marginTop: 14,
                      flexWrap: "wrap" }}>
          {TABS.filter(([key]) => key !== "commercial" || canEdit)
            .map(([key, label, enabled]) => (
            <button key={key} disabled={!enabled}
                    onClick={() => enabled && setTab(key)}
                    title={enabled ? "" : "Reserved — coming in a later phase"}
                    style={{
                      ...ghostButton, padding: "4px 14px", fontSize: 13,
                      opacity: enabled ? 1 : 0.45,
                      cursor: enabled ? "pointer" : "default",
                      background: tab === key ? "var(--navy)" : "#fff",
                      color: tab === key ? "#fff" : "var(--navy)",
                    }}>
              {label}
            </button>
          ))}
        </div>
      </section>

      {editing && (
        <EditProjectModal project={project} onClose={() => setEditing(false)}
                          onSaved={() => { setEditing(false); load(); }} />
      )}

      {tab === "overview" && (
        <>
          <section style={{ ...card, display: "flex", gap: 18,
                            flexWrap: "wrap" }}>
            <Stat label="Programme progress"
                  value={`${project.overall_progress}%`}
                  tone={behind ? "alert" : "ok"}
                  context={elapsed == null ? "no dates set"
                    : behind
                      ? `behind — ${elapsed}% of time elapsed`
                      : `${elapsed}% of time elapsed`} />
            <Stat label="Activities" value={project.activity_count}
                  tone="info" context="in the programme" />
            <Stat label="Manpower (last DPR)"
                  value={project.latest_manpower ?? "—"} tone="info"
                  context="reported at site" />
            {money(project.contract_value) && (
              <Stat label="Contract value"
                    value={`$${money(project.contract_value)}`} tone="info"
                    context="USD" />
            )}
          </section>
          <section style={card}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <tbody>
                {[["Project PM", project.pm_name || "—"],
                  ..."qs_name" in project
                    ? [["Assigned QS", project.qs_name || "—"]] : [],
                  ["LOA date", project.loa_date || "—"],
                  ["Start date", project.start_date || "—"],
                  ["Planned finish", project.planned_completion || "—"],
                  ["Actual completion", project.actual_completion || "—"],
                  ["BOQ ref", project.boq_ref || "—"],
                  ["Scope", project.scope || "—"],
                  ["Planned manpower",
                   project.manpower_plan?.length
                     ? `${project.manpower_plan.reduce((a, r) =>
                         a + (parseInt(r.workers, 10) || 0), 0)} across `
                       + `${project.manpower_plan.length} categories`
                     : "—"],
                ].map(([k, v]) => (
                  <tr key={k}>
                    <td style={{ ...td, width: 170, color: "var(--muted)",
                                 fontWeight: 600 }}>{k}</td>
                    <td style={td}>{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {canEdit && (
              <p style={{ fontSize: 12, color: "var(--faint)",
                          margin: "10px 0 0" }}>
                Use ✎ Edit above to update the value, dates and contract terms.
              </p>
            )}
          </section>
          {"contract_type" in project && <ContractTermsCard project={project} />}
        </>
      )}

      {tab === "programme" && (
        <section style={card}>
          <ProgrammePage project={project} me={me} embedded />
        </section>
      )}

      {tab === "manpower" && (
        <ManpowerPlanTab project={project} me={me} onSaved={load} />
      )}

      {tab === "commercial" && (
        <>
          <BoqPanel projectId={projectId} project={project} me={me} />
          <VariationsPanel projectId={projectId} me={me} />
          <ClaimsPanel projectId={projectId} me={me} />
        </>
      )}

      {tab === "documents" && (
        <section style={card}>
          {!docs ? "Loading…" : (
            <>
              <Eyebrow meta={String(docs.project_docs.length)}>
                Project documents
              </Eyebrow>
              <DocTable rows={docs.project_docs} onOpenDoc={onOpenDoc}
                        empty="No inspection requests or material approvals
                               yet for this project." />
              <Eyebrow meta={String(docs.daily_docs.length)}>
                Daily reports carrying this project's rows
              </Eyebrow>
              <DocTable rows={docs.daily_docs} onOpenDoc={onOpenDoc}
                        empty="No DPR/TWS rows tagged to this project yet." />
            </>
          )}
        </section>
      )}
    </>
  );
}

// Manpower REQUIREMENT per category, PM down to unskilled (owner) —
// the histogram sent to the client with the programme is drawn from
// these numbers. Categories come strictly from the company manpower list.
function ManpowerPlanTab({ project, me, onSaved }) {
  const [rows, setRows] = useState(
    project.manpower_plan?.length ? project.manpower_plan
      : [{ category: "", workers: "" }]);
  const [categories, setCategories] = useState([]);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);
  const canManage = ["PM", "DIRECTOR", "ADMIN"].includes(me.role);
  const clean = rows.filter((r) => r.category &&
                            parseInt(r.workers, 10) > 0);
  const peak = Math.max(...clean.map((r) => parseInt(r.workers, 10)), 1);
  const total = clean.reduce((a, r) => a + parseInt(r.workers, 10), 0);

  useEffect(() => {
    api("/manpower-categories").then((all) => setCategories(
      all.filter((c) => c.list_type === "DPR" && c.is_active)));
  }, []);

  async function save() {
    setError(null);
    try {
      await api(`/projects/${project.id}`, {
        method: "PATCH",
        body: { manpower_plan: clean.map((r) => ({
          category: r.category, workers: parseInt(r.workers, 10) })) },
      });
      setNotice("Manpower requirement saved — it prints with the "
                + "Programme PDF.");
      onSaved();
    } catch (e) {
      setError(e.message);
    }
  }

  const staff = categories.filter((c) => c.grp === "STAFF");
  const labour = categories.filter((c) => c.grp === "LABOUR");
  const used = rows.map((r) => r.category);

  return (
    <section style={card}>
      <Eyebrow meta={clean.length ? `total ${total}` : null}>
        Manpower requirement — by category
      </Eyebrow>
      {clean.length > 0 && (
        <div style={{ display: "flex", alignItems: "flex-end", gap: 6,
                      height: 120, borderBottom: "1px solid var(--line)",
                      borderLeft: "1px solid var(--line)",
                      padding: "0 6px", maxWidth: 640, marginBottom: 4 }}>
          {clean.map((r, i) => (
            <div key={i} style={{ flex: 1, display: "flex",
                                  flexDirection: "column",
                                  justifyContent: "flex-end",
                                  textAlign: "center", height: "100%" }}>
              <div style={{ fontSize: 11, fontWeight: 700,
                            color: "var(--navy)" }}>{r.workers}</div>
              <div style={{ background: "var(--sky)",
                            borderRadius: "3px 3px 0 0",
                            height: `${(100 * r.workers) / peak}%` }} />
            </div>
          ))}
        </div>
      )}
      {clean.length > 0 && (
        <div style={{ display: "flex", gap: 6, maxWidth: 640,
                      padding: "0 6px", marginBottom: 14 }}>
          {clean.map((r, i) => (
            <span key={i} style={{ flex: 1, textAlign: "center",
                                   fontSize: 10,
                                   color: "var(--faint)" }}>{r.category}</span>
          ))}
        </div>
      )}
      {canManage ? (
        <>
          {rows.map((r, i) => (
            <div key={i} style={{ display: "flex", gap: 8,
                                  alignItems: "center", marginBottom: 6 }}>
              <select value={r.category}
                      onChange={(e) => setRows(rows.map((x, j) =>
                        j === i ? { ...x, category: e.target.value } : x))}
                      style={{ width: 260, padding: "6px 8px",
                               borderRadius: 8,
                               border: "1px solid #BFD6E6" }}>
                <option value="">— category —</option>
                {[["Staff", staff], ["Trades / Labour", labour]].map(
                  ([label, list]) => (
                  <optgroup key={label} label={label}>
                    {list.map((c) => (
                      <option key={c.id} value={c.name}
                              disabled={used.includes(c.name) &&
                                        c.name !== r.category}>
                        {c.name}</option>
                    ))}
                  </optgroup>
                ))}
              </select>
              <input type="number" min="0" value={r.workers}
                     placeholder="workers"
                     onChange={(e) => setRows(rows.map((x, j) =>
                       j === i ? { ...x, workers: e.target.value } : x))}
                     style={{ width: 100, padding: "6px 8px",
                              borderRadius: 8,
                              border: "1px solid #BFD6E6" }} />
              <button onClick={() => setRows(rows.filter((_, j) => j !== i))}
                      style={{ ...ghostButton, padding: "2px 8px",
                               color: "var(--red-fg)" }}>×</button>
            </div>
          ))}
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button onClick={() => setRows([...rows,
                                            { category: "", workers: "" }])}
                    style={{ ...ghostButton, padding: "4px 12px" }}>
              + Add category
            </button>
            <button onClick={save} disabled={!clean.length}
                    style={{ background: "var(--navy)", color: "#fff",
                             border: "none", borderRadius: 8,
                             padding: "6px 16px", fontWeight: 600,
                             cursor: "pointer" }}>
              Save plan
            </button>
          </div>
        </>
      ) : (
        !clean.length && (
          <p style={{ fontSize: 13, color: "var(--muted)" }}>
            No manpower requirement yet — the PM enters the planned
            numbers per category (PM down to unskilled) here.</p>
        )
      )}
      {notice && <p style={{ color: "var(--green-fg)", fontSize: 13 }}>
        {notice}</p>}
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>
        {error}</p>}
    </section>
  );
}

const PROJECT_STATUSES = ["POTENTIAL", "AWARDED", "ACTIVE", "ON_HOLD",
                          "CLOSED"];
const CONTRACT_TYPES = [["", "—"], ["LUMP_SUM", "Lump sum"],
                        ["REMEASUREMENT", "Re-measurement"],
                        ["COST_PLUS", "Cost plus"]];
const CONTRACT_TYPE_LABEL = Object.fromEntries(CONTRACT_TYPES);

// Read-only contract-terms summary on the overview (shown to those who may see
// the contract value — HO roles incl. QS, and the assigned PM).
function ContractTermsCard({ project }) {
  const pct = (v) => (v == null || v === "" ? null : `${v}%`);
  const rows = [
    ["Contract type", CONTRACT_TYPE_LABEL[project.contract_type] || "—"],
    ["Payment terms", project.payment_terms],
    ["Client credit period", project.client_credit_days != null
      ? `${project.client_credit_days} days` : null],
    ["Advance payment", pct(project.advance_payment_pct)],
    ["Advance guarantee", project.advance_guarantee],
    ["Retention", pct(project.retention_pct)],
    ["Retention release", project.retention_release_terms],
    ["Defects liability", project.defects_liability_months
      ? `${project.defects_liability_months} months` : null],
    ["Liquidated damages", project.liquidated_damages],
    ["Price escalation", project.price_escalation],
    ["Performance bond", pct(project.performance_bond_pct)],
    ["Insurance / CAR", project.insurance_details],
  ].filter(([, v]) => v && v !== "—");
  return (
    <section style={card}>
      <Eyebrow>Contract terms</Eyebrow>
      {rows.length ? (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}>
                <td style={{ ...td, width: 170, color: "var(--muted)",
                             fontWeight: 600, verticalAlign: "top" }}>{k}</td>
                <td style={{ ...td, whiteSpace: "pre-wrap" }}>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p style={{ fontSize: 13, color: "var(--muted)" }}>
          No contract terms recorded yet — the QS enters these via ✎ Edit.</p>
      )}
    </section>
  );
}

// PM / QS / Admin edit project details, value (USD), dates and contract terms.
// Admin/Director may also delete an empty project (no documents).
function EditProjectModal({ project, onClose, onSaved }) {
  const [form, setForm] = useState({
    code: project.code || "", title: project.title || "",
    start_date: project.start_date || "",
    planned_completion: project.planned_completion || "",
    actual_completion: project.actual_completion || "",
    loa_date: project.loa_date || "",
    contract_value: project.contract_value ?? "",
    status: project.status || "ACTIVE",
    qs: project.qs ?? "",
    contract_type: project.contract_type || "",
    payment_terms: project.payment_terms || "",
    client_credit_days: project.client_credit_days ?? "",
    advance_payment_pct: project.advance_payment_pct ?? "",
    advance_guarantee: project.advance_guarantee || "",
    retention_pct: project.retention_pct ?? "",
    retention_release_terms: project.retention_release_terms || "",
    defects_liability_months: project.defects_liability_months ?? "",
    liquidated_damages: project.liquidated_damages || "",
    price_escalation: project.price_escalation || "",
    performance_bond_pct: project.performance_bond_pct ?? "",
    insurance_details: project.insurance_details || "",
  });
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [qsList, setQsList] = useState([]);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const num = (v) => (v === "" || v == null ? null : Number(v));

  useEffect(() => {
    api("/assignable/qs").then(setQsList).catch(() => setQsList([]));
  }, []);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const body = {
        code: form.code.trim(), title: form.title.trim(),
        start_date: form.start_date || null,
        planned_completion: form.planned_completion || null,
        actual_completion: form.actual_completion || null,
        loa_date: form.loa_date || null,
        contract_value: num(form.contract_value), status: form.status,
        qs: form.qs === "" ? null : Number(form.qs),
        contract_type: form.contract_type,
        payment_terms: form.payment_terms,
        client_credit_days: num(form.client_credit_days),
        advance_payment_pct: num(form.advance_payment_pct),
        advance_guarantee: form.advance_guarantee,
        retention_pct: num(form.retention_pct),
        retention_release_terms: form.retention_release_terms,
        defects_liability_months: num(form.defects_liability_months),
        liquidated_damages: form.liquidated_damages,
        price_escalation: form.price_escalation,
        performance_bond_pct: num(form.performance_bond_pct),
        insurance_details: form.insurance_details,
      };
      await api(`/projects/${project.id}`, { method: "PATCH", body });
      onSaved();
    } catch (e) {
      setError(e.message);
      setSaving(false);
    }
  }

  const field = { display: "flex", flexDirection: "column", gap: 4,
                  fontSize: 12, color: "var(--muted)" };
  const full = { ...field, gridColumn: "1 / -1" };
  const ta = { ...inputStyle, minHeight: 40, resize: "vertical" };
  const heading = { gridColumn: "1 / -1", margin: "8px 0 0", fontSize: 13,
                    fontWeight: 700, color: "var(--navy)" };
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.35)",
                  display: "flex", alignItems: "flex-start",
                  justifyContent: "center", padding: "5vh 16px", zIndex: 50 }}
         onClick={onClose}>
      <div style={{ ...card, maxWidth: 680, width: "100%", margin: 0,
                    maxHeight: "90vh", overflow: "auto" }}
           onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0, color: "var(--navy)", fontSize: 16 }}>
          Edit project</h3>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                      gap: 12 }}>
          <label style={field}>Project code
            <input value={form.code} onChange={set("code")}
                   style={inputStyle} /></label>
          <label style={field}>Status
            <select value={form.status} onChange={set("status")}
                    style={inputStyle}>
              {PROJECT_STATUSES.map((s) => (
                <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
              ))}
            </select></label>
          <label style={full}>Title
            <input value={form.title} onChange={set("title")}
                   style={inputStyle} /></label>
          <label style={full}>Assigned QS (owns the financials/tender)
            <select value={form.qs} onChange={set("qs")} style={inputStyle}>
              <option value="">— none —</option>
              {qsList.map((u) => (
                <option key={u.id} value={u.id}>{u.full_name}</option>
              ))}
            </select></label>
          <label style={field}>Start date
            <input type="date" value={form.start_date}
                   onChange={set("start_date")} style={inputStyle} /></label>
          <label style={field}>Planned completion
            <input type="date" value={form.planned_completion}
                   onChange={set("planned_completion")}
                   style={inputStyle} /></label>
          <label style={field}>Actual completion
            <input type="date" value={form.actual_completion}
                   onChange={set("actual_completion")}
                   style={inputStyle} /></label>
          <label style={field}>LOA date
            <input type="date" value={form.loa_date}
                   onChange={set("loa_date")} style={inputStyle} /></label>

          <div style={heading}>Contract</div>
          <label style={field}>Contract value (USD)
            <input type="number" min="0" value={form.contract_value}
                   onChange={set("contract_value")}
                   style={inputStyle} /></label>
          <label style={field}>Contract type
            <select value={form.contract_type} onChange={set("contract_type")}
                    style={inputStyle}>
              {CONTRACT_TYPES.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select></label>
          <label style={full}>Payment terms
            <textarea value={form.payment_terms} rows={2}
                      onChange={set("payment_terms")} style={ta} /></label>
          <label style={field}>Client credit period (days)
            <input type="number" min="0" value={form.client_credit_days}
                   onChange={set("client_credit_days")}
                   placeholder="e.g. 30" style={inputStyle} /></label>
          <label style={field}>Advance payment %
            <input type="number" min="0" value={form.advance_payment_pct}
                   onChange={set("advance_payment_pct")}
                   style={inputStyle} /></label>
          <label style={field}>Retention %
            <input type="number" min="0" value={form.retention_pct}
                   onChange={set("retention_pct")} style={inputStyle} /></label>
          <label style={full}>Retention release terms
            <textarea value={form.retention_release_terms} rows={2}
                      onChange={set("retention_release_terms")}
                      style={ta} /></label>
          <label style={field}>Defects liability (months)
            <input type="number" min="0" value={form.defects_liability_months}
                   onChange={set("defects_liability_months")}
                   style={inputStyle} /></label>
          <label style={field}>Performance bond %
            <input type="number" min="0" value={form.performance_bond_pct}
                   onChange={set("performance_bond_pct")}
                   style={inputStyle} /></label>
          <label style={full}>Liquidated damages (penalty)
            <textarea value={form.liquidated_damages} rows={2}
                      onChange={set("liquidated_damages")} style={ta} /></label>
          <label style={full}>Price escalation
            <textarea value={form.price_escalation} rows={2}
                      onChange={set("price_escalation")} style={ta} /></label>
          <label style={full}>Advance-payment guarantee
            <textarea value={form.advance_guarantee} rows={2}
                      onChange={set("advance_guarantee")} style={ta} /></label>
          <label style={full}>Insurance / CAR policy
            <textarea value={form.insurance_details} rows={2}
                      onChange={set("insurance_details")} style={ta} /></label>
        </div>
        {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end",
                      marginTop: 16 }}>
          <button onClick={onClose} style={ghostButton}>Cancel</button>
          <button onClick={save} disabled={saving || !form.code.trim()
                                           || !form.title.trim()}
                  style={buttonStyle}>
            {saving ? "Saving…" : "Save changes"}</button>
        </div>
      </div>
    </div>
  );
}

function DocTable({ rows, onOpenDoc, empty }) {
  if (!rows.length) {
    return <p style={{ fontSize: 13, color: "var(--muted)" }}>{empty}</p>;
  }
  return (
    <table style={{ width: "100%", borderCollapse: "collapse",
                    marginBottom: 14 }}>
      <thead><tr>
        <th style={th}>Ref</th><th style={th}>Type</th>
        <th style={th}>Date</th><th style={th}>Status</th>
        <th style={th}>Detail</th>
      </tr></thead>
      <tbody>
        {rows.map((d) => (
          <tr key={d.ref}>
            <td style={{ ...td, width: 130 }}>
              <a href="#" onClick={(e) => { e.preventDefault();
                                            onOpenDoc(d.ref); }}
                 style={{ textDecoration: "none" }}>
                <RefStamp small>{d.ref}</RefStamp>
              </a>
            </td>
            <td style={td}>{d.doc_type}</td>
            <td style={td}>{d.doc_date}</td>
            <td style={td}>
              {d.status === "VOID" ? <Chip tone="alert">VOID</Chip>
                                   : <StatusChip status={d.status} />}
            </td>
            <td style={{ ...td, color: "var(--muted)", fontSize: 12 }}>
              {d.detail}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
