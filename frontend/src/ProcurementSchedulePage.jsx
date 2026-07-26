import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, card, inputStyle } from "./ui.jsx";

const STATUS_TONE = {
  DRAFT: "info", SUBMITTED: "warn", CONFIRMED: "warn", SIGNED_OFF: "ok",
  CANCELLED: "alert",
};
const STATE_TONE = {
  PROPOSED: "info", CONFIRMED: "warn", SIGNED_OFF: "ok", CANCELLED: "alert",
};
const SUPPLY = [["CONTRACTOR", "Contractor"], ["CLIENT", "Client"]];
const money = (v, c) => v == null ? "—"
  : `${c || ""} ${Number(v).toLocaleString("en-US",
      { minimumFractionDigits: 2 })}`.trim();
const fmt = (s) => s ? new Date(s).toLocaleDateString("en-GB",
  { day: "2-digit", month: "short", year: "numeric" }) : "—";

// Per-project procurement schedule: PM proposes lines, Purchasing confirms the
// commercial fields, the Director signs off the baseline.
export default function ProcurementSchedulePage({ me, sites }) {
  const [list, setList] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [view, setView] = useState("list");   // list | new
  const [error, setError] = useState(null);

  const load = () => api("/procurement-schedules").then(setList)
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  if (openId)
    return <ScheduleDetail id={openId} me={me}
             onBack={() => { setOpenId(null); load(); }} />;
  if (view === "new")
    return <NewSchedule sites={sites} onCancel={() => setView("list")}
             onDone={(d) => { setView("list"); setOpenId(d.id); load(); }} />;

  const canOpen = me.role === "PM" || me.is_ho;
  return (
    <div style={{ maxWidth: 980 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12,
        marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Procurement Schedule</h2>
        {canOpen && <Btn variant="primary"
          onClick={() => setView("new")}>+ Open a project schedule</Btn>}
      </div>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      {list === null ? <div style={card}>Loading…</div>
       : !list.length ? <div style={card}>No schedules yet.</div> : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
            fontSize: 13 }}>
            <thead><tr style={{ textAlign: "left", color: "var(--muted)" }}>
              {["Ref", "Project", "Site", "Status", "Lines"].map((h) =>
                <th key={h} style={{ padding: "8px 12px" }}>{h}</th>)}
            </tr></thead>
            <tbody>
              {list.map((s) => (
                <tr key={s.id} style={{ borderTop: "1px solid var(--line)",
                  cursor: "pointer" }} onClick={() => setOpenId(s.id)}>
                  <td style={{ padding: "8px 12px", fontFamily:
                    "var(--font-mono)" }}>{s.ref}</td>
                  <td style={{ padding: "8px 12px" }}>{s.project_code} —{" "}
                    {s.project_title}</td>
                  <td style={{ padding: "8px 12px" }}>{s.site_code}</td>
                  <td style={{ padding: "8px 12px" }}>
                    <Chip tone={STATUS_TONE[s.status]}>
                      {s.status.replace(/_/g, " ")}</Chip></td>
                  <td style={{ padding: "8px 12px", color: "var(--muted)" }}>
                    {Object.entries(s.line_counts || {})
                      .map(([k, v]) => `${v} ${k.toLowerCase()}`).join(" · ")
                      || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function NewSchedule({ sites, onCancel, onDone }) {
  const [siteId, setSiteId] = useState(sites?.[0]?.id || "");
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!siteId) { setProjects([]); return; }
    api(`/sites/${siteId}/projects`).then((l) => { setProjects(l);
      setProjectId(l?.[0]?.id || ""); }).catch(() => setProjects([]));
  }, [siteId]);

  async function open() {
    if (!projectId) { setError("Pick a project."); return; }
    setBusy(true); setError(null);
    try {
      const d = await api(`/projects/${projectId}/procurement-schedule`,
        { method: "POST" });
      onDone(d);
    } catch (e) { setError(e.message); setBusy(false); }
  }
  return (
    <div style={{ ...card, maxWidth: 560 }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Open a project schedule</h2>
        <button onClick={onCancel} style={{ border: "none",
          background: "none", cursor: "pointer", color: "var(--navy)" }}>
          Cancel</button>
      </div>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      <label style={fld}>Site
        <select style={inputStyle} value={siteId}
          onChange={(e) => setSiteId(e.target.value)}>
          {(sites || []).map((s) => <option key={s.id} value={s.id}>
            {s.code} — {s.name}</option>)}
        </select></label>
      <label style={{ ...fld, marginTop: 8 }}>Project
        <select style={inputStyle} value={projectId}
          onChange={(e) => setProjectId(e.target.value)}>
          <option value="">Select…</option>
          {projects.map((p) => <option key={p.id} value={p.id}>
            {p.code} — {p.title}</option>)}
        </select></label>
      <div style={{ marginTop: 12 }}>
        <Btn variant="primary" disabled={busy} onClick={open}>
          Open schedule</Btn>
      </div>
    </div>
  );
}

function ScheduleDetail({ id, me, onBack }) {
  const [c, setC] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [editId, setEditId] = useState(null);

  const load = () => api(`/procurement-schedules/${id}`).then(setC)
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, [id]);

  async function run(fn) {
    setBusy(true); setError(null);
    try { await fn(); await load(); } catch (e) { setError(e.message); }
    setBusy(false);
  }
  const act = (action) => run(async () => {
    let note = "";
    if (action === "return") {
      note = window.prompt("Reason to return to the PM:") || "";
      if (!note.trim()) throw new Error("A reason is required.");
    }
    await api(`/procurement-schedules/${id}/action`,
      { method: "POST", body: { action, note } });
  });
  const submit = () => run(() =>
    api(`/procurement-schedules/${id}/submit`, { method: "POST" }));

  if (error && !c) return <div style={card}>{error}
    <div><button style={linkBtn} onClick={onBack}>← Back</button></div></div>;
  if (!c) return <div style={card}>Loading…</div>;

  const bySection = {};
  for (const ln of c.lines) {
    const k = ln.section_id || "none";
    (bySection[k] = bySection[k] || []).push(ln);
  }
  const secList = c.sections.length ? c.sections
    : [{ id: "none", code: "", title: "Ungrouped" }];

  return (
    <div style={{ maxWidth: 1100 }}>
      <button style={linkBtn} onClick={onBack}>← All schedules</button>
      <div style={{ ...card, marginTop: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10,
          flexWrap: "wrap" }}>
          <h2 style={{ margin: 0, fontFamily: "var(--font-mono)" }}>{c.ref}</h2>
          <Chip tone={STATUS_TONE[c.status]}>{c.status.replace(/_/g, " ")}</Chip>
          <span style={{ color: "var(--muted)" }}>{c.project_code} —{" "}
            {c.project_title} · {c.site_code}</span>
          {c.baseline_signed_at && <span style={{ fontSize: 12,
            color: "var(--muted)" }}>baseline {fmt(c.baseline_signed_at)} ·{" "}
            {c.baseline_signed_by}</span>}
        </div>
        {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
        {/* workflow bar */}
        <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
          {c.can_edit_plan && <Btn variant="secondary" disabled={busy}
            onClick={() => setAdding(true)}>+ Add line</Btn>}
          {c.status === "DRAFT" && me.role === "PM" &&
            <Btn variant="primary" disabled={busy}
              onClick={submit}>Submit to Purchasing</Btn>}
          {c.can_confirm && <>
            <Btn variant="primary" disabled={busy}
              onClick={() => act("confirm")}>Confirm → Director</Btn>
            <Btn variant="ghost" disabled={busy}
              onClick={() => act("return")}>Return to PM</Btn></>}
          {c.can_sign_off && <>
            <Btn variant="primary" disabled={busy}
              onClick={() => act("sign_off")}>Sign off baseline</Btn>
            <Btn variant="ghost" disabled={busy}
              onClick={() => act("return")}>Return to PM</Btn></>}
        </div>
      </div>

      {adding && <LineForm mode="plan" c={c}
        onCancel={() => setAdding(false)}
        onSaved={() => { setAdding(false); load(); }} />}

      {secList.map((sec) => {
        const rows = bySection[sec.id] || [];
        if (!rows.length && sec.id !== "none") return null;
        return (
          <div key={sec.id} style={{ ...card, marginTop: 10, padding: 0,
            overflowX: "auto" }}>
            {sec.code && <div style={{ padding: "8px 12px", fontWeight: 600,
              background: "var(--sky-soft)" }}>{sec.code} — {sec.title}</div>}
            <table style={{ width: "100%", borderCollapse: "collapse",
              fontSize: 12.5 }}>
              <thead><tr style={{ textAlign: "left", color: "var(--muted)" }}>
                {["#", "Description", "Make", "Trade", "Supply", "Required",
                  "Supplier", "Country", "Lead",
                  ...(c.show_values ? ["Est. value"] : []),
                  "State", ""].map((h, i) =>
                  <th key={i} style={{ padding: "6px 10px",
                    whiteSpace: "nowrap" }}>{h}</th>)}
              </tr></thead>
              <tbody>
                {rows.map((ln) => (
                  <tr key={ln.id} style={{ borderTop: "1px solid var(--line)" }}>
                    <td style={cell}>{ln.s_no}</td>
                    <td style={cell}>{ln.description}
                      {ln.specification && <div style={{ color: "var(--muted)",
                        fontSize: 11 }}>{ln.specification}</div>}</td>
                    <td style={cell}>{ln.make_brand || "—"}</td>
                    <td style={cell}>{ln.trade || "—"}</td>
                    <td style={cell}>{ln.supply_by === "CLIENT"
                      ? <Chip tone="warn">Client</Chip> : "Contractor"}</td>
                    <td style={cell}>{fmt(ln.required_date)}</td>
                    <td style={cell}>{ln.planned_supplier || "—"}</td>
                    <td style={cell}>{ln.source_country || "—"}</td>
                    <td style={cell}>{ln.lead_time_days != null
                      ? `${ln.lead_time_days}d` : "—"}</td>
                    {c.show_values && <td style={cell}>
                      {money(ln.estimated_value, ln.currency)}</td>}
                    <td style={cell}><Chip tone={STATE_TONE[ln.state]}>
                      {ln.state.replace(/_/g, " ")}</Chip></td>
                    <td style={cell}>
                      {(c.can_edit_plan || c.can_confirm) &&
                        <button style={linkBtn}
                          onClick={() => setEditId(ln.id)}>Edit</button>}
                    </td>
                  </tr>
                ))}
                {!rows.length && <tr><td style={{ ...cell,
                  color: "var(--muted)" }} colSpan={12}>No lines.</td></tr>}
              </tbody>
            </table>
          </div>
        );
      })}

      {editId && <LineForm mode={c.can_confirm ? "commercial" : "plan"} c={c}
        line={c.lines.find((l) => l.id === editId)}
        onCancel={() => setEditId(null)}
        onSaved={() => { setEditId(null); load(); }} />}
    </div>
  );
}

function LineForm({ mode, c, line, onCancel, onSaved }) {
  const isNew = !line;
  const [f, setF] = useState(() => line ? { ...line,
    section_code: line.section_code, section_title: line.section_title }
    : { supply_by: "CONTRACTOR", section_code: "", section_title: "",
        description: "", make_brand: "", specification: "", trade: "",
        required_date: "", tds_required: false });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setF({ ...f,
    [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function save() {
    setBusy(true); setErr(null);
    try {
      if (isNew) {
        await api(`/procurement-schedules/${c.id}/lines`,
          { method: "POST", body: f });
      } else {
        await api(`/procurement-schedule-lines/${line.id}`,
          { method: "PATCH", body: f });
      }
      onSaved();
    } catch (e) { setErr(e.message); setBusy(false); }
  }
  async function del() {
    if (!window.confirm("Remove this line?")) return;
    setBusy(true);
    try { await api(`/procurement-schedule-lines/${line.id}`,
      { method: "DELETE" }); onSaved(); }
    catch (e) { setErr(e.message); setBusy(false); }
  }

  const commercial = mode === "commercial";
  return (
    <div style={{ ...card, marginTop: 10, border: "1px solid var(--sky)" }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>
        {isNew ? "New line" : commercial ? "Confirm commercial fields"
          : "Edit line"}</div>
      {err && <p style={{ color: "var(--red-fg)" }}>{err}</p>}
      {!commercial ? (
        <div style={grid}>
          <L k="Section code"><input style={inputStyle} value={f.section_code}
            onChange={set("section_code")} placeholder="A" /></L>
          <L k="Section title"><input style={inputStyle}
            value={f.section_title} onChange={set("section_title")}
            placeholder="Villa Upgrades" /></L>
          <L k="Supply"><select style={inputStyle} value={f.supply_by}
            onChange={set("supply_by")}>{SUPPLY.map(([v, l]) =>
              <option key={v} value={v}>{l}</option>)}</select></L>
          <L k="Description *" wide><input style={inputStyle}
            value={f.description} onChange={set("description")} /></L>
          <L k="Make / brand"><input style={inputStyle} value={f.make_brand}
            onChange={set("make_brand")} /></L>
          <L k="Trade"><input style={inputStyle} value={f.trade}
            onChange={set("trade")} /></L>
          <L k="Required on site"><input type="date" style={inputStyle}
            value={f.required_date || ""} onChange={set("required_date")} /></L>
          <L k="Specification" wide><input style={inputStyle}
            value={f.specification} onChange={set("specification")} /></L>
          <L k="Remarks" wide><input style={inputStyle} value={f.remarks || ""}
            onChange={set("remarks")} /></L>
          <label style={{ ...fld, alignSelf: "end" }}>
            <span><input type="checkbox" checked={!!f.tds_required}
              onChange={set("tds_required")} /> TDS / MAR required</span></label>
        </div>
      ) : (
        <div style={grid}>
          <L k="Planned supplier" wide><input style={inputStyle}
            value={f.planned_supplier || ""}
            onChange={set("planned_supplier")} /></L>
          <L k="Source country"><input style={inputStyle}
            value={f.source_country || ""} onChange={set("source_country")} /></L>
          <L k="Lead time (days)"><input type="number" style={inputStyle}
            value={f.lead_time_days ?? ""} onChange={set("lead_time_days")} /></L>
          <L k="Estimated value"><input type="number" style={inputStyle}
            value={f.estimated_value ?? ""}
            onChange={set("estimated_value")} /></L>
          <L k="Currency"><input style={inputStyle} value={f.currency || "USD"}
            onChange={set("currency")} /></L>
        </div>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <Btn variant="primary" disabled={busy} onClick={save}>Save</Btn>
        <Btn variant="ghost" disabled={busy} onClick={onCancel}>Cancel</Btn>
        {!isNew && !commercial && line.state === "PROPOSED" &&
          <Btn variant="danger" disabled={busy} onClick={del}>Delete</Btn>}
      </div>
    </div>
  );
}

const fld = { display: "flex", flexDirection: "column", gap: 3, fontSize: 12,
  color: "var(--muted)" };
const grid = { display: "grid", gap: 8, gridTemplateColumns: "repeat(3, 1fr)" };
const cell = { padding: "6px 10px", verticalAlign: "top" };
const linkBtn = { border: "none", background: "none", cursor: "pointer",
  color: "var(--navy)", fontSize: 13, padding: 0 };
function L({ k, wide, children }) {
  return <label style={{ ...fld, gridColumn: wide ? "span 2" : "auto" }}>
    {k}{children}</label>;
}
