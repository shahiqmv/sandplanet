import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Chip, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

// Unit progress board for unit-based BOQ projects (owner 2026-08-23).
// Everyone — client, site team, management — needs to know at a glance where
// each villa/pool has got to. Each BOQ category defines its stages once with
// weights; a unit's percentage is the weighted roll-up, and every figure says
// which DPR reported it, so the daily report stays the record rather than
// being replaced by a second place to type progress.
const TONE = { COMPLETE: "ok", IN_PROGRESS: "info", ON_HOLD: "warn",
               NOT_STARTED: "info" };
const REPORT_ROLES = ["PM", "QS", "DIRECTOR", "ADMIN", "SITE_ENGINEER",
                      "SITE_ADMIN"];
const pct = (v) => `${Number(v || 0).toFixed(0)}%`;

function Bar({ value, tone }) {
  const v = Math.max(0, Math.min(100, Number(value || 0)));
  return (
    <div style={{ background: "#e8eef3", borderRadius: 99, height: 8,
                  width: 120, overflow: "hidden" }}>
      <div style={{ width: `${v}%`, height: "100%", borderRadius: 99,
                    background: tone === "ON_HOLD" ? "#e0a44a"
                              : v >= 100 ? "#1a7f37"
                              : "var(--sp-sky, #29ABE2)" }} />
    </div>
  );
}

export default function UnitsPanel({ projectId, me }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);        // expanded unit id
  const [editing, setEditing] = useState(null);  // category id for the ladder
  const [filter, setFilter] = useState("");

  const load = () => api(`/projects/${projectId}/units`).then(setData)
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, [projectId]); // eslint-disable-line

  if (error && !data) return <section style={card}>{error}</section>;
  if (!data) return <section style={card}>Loading…</section>;
  if (!data.is_unit_project) {
    return (
      <section style={card}>
        <p style={{ color: "var(--muted)", fontSize: 13, margin: 0 }}>
          Unit tracking is for unit-based BOQs — this project prices flat
          items. Switch the BOQ to unit mode to track per-unit progress.
        </p>
      </section>);
  }
  const can = data.can_manage;

  async function call(path, body, method = "POST") {
    setError(null);
    try { setData(await api(path, { method, body })); }
    catch (e) { setError(e.message); }
  }
  const patchUnit = (u, body) => call(`/units/${u.id}`, body, "PATCH");

  const shown = data.units.filter((u) => {
    const q = filter.trim().toLowerCase();
    return !q || `${u.ref} ${u.name} ${u.category} ${u.current_stage}`
      .toLowerCase().includes(q);
  });

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 14,
                    flexWrap: "wrap", marginBottom: 10 }}>
        <h3 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 16 }}>
          Unit progress</h3>
        <span style={{ fontSize: 13, color: "var(--muted)" }}>
          {data.complete} of {data.unit_count} complete ·{" "}
          <strong style={{ color: "var(--sp-navy)" }}>
            {pct(data.overall_percent)}</strong> overall
        </span>
        <input placeholder="Find a unit…" value={filter}
               onChange={(e) => setFilter(e.target.value)}
               style={{ ...inputStyle, width: 180, marginLeft: "auto" }} />
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {/* Per-category roll-up — the management view */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                    marginBottom: 12 }}>
        {data.categories.map((c) => (
          <div key={c.id} style={{ border: "1px solid var(--sp-border, #d8e1e8)",
                                   borderRadius: 8, padding: "8px 12px",
                                   minWidth: 190 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>{c.name}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 8,
                          margin: "5px 0" }}>
              <Bar value={c.percent} />
              <span style={{ fontSize: 12.5, fontWeight: 600 }}>
                {pct(c.percent)}</span>
            </div>
            <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
              {c.complete} done · {c.in_progress} running ·{" "}
              {c.not_started} to start{c.on_hold ? ` · ${c.on_hold} held` : ""}
            </div>
          </div>))}
      </div>

      {/* Setup: generate units, edit the stage ladder */}
      {can && (
        <div style={{ marginBottom: 12 }}>
          {data.ladders.filter((l) => !l.is_lump).map((l) => (
            <div key={l.category_id} style={{ fontSize: 12.5, margin: "4px 0" }}>
              <strong>{l.name}</strong>{" "}
              <span style={{ color: "var(--muted)" }}>
                {l.units} of {Number(l.qty)} units · {l.stages.length} stages
              </span>{" "}
              {l.units < Number(l.qty) && (
                <button style={{ ...ghostButton, padding: "2px 9px",
                                 fontSize: 12 }}
                        onClick={() => call(
                          `/boq-categories/${l.category_id}/generate-units`,
                          {})}>
                  generate {Number(l.qty) - l.units} unit(s)</button>)}{" "}
              <button style={{ ...ghostButton, padding: "2px 9px",
                               fontSize: 12 }}
                      onClick={() => setEditing(
                        editing === l.category_id ? null : l.category_id)}>
                {editing === l.category_id ? "close" : "stages"}</button>
              {editing === l.category_id && (
                <StageLadder ladder={l} onDone={(d) => {
                  if (d) setData(d); setEditing(null); }} />)}
            </div>))}
        </div>)}

      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead><tr>
          <th style={th}>Ref</th><th style={th}>Unit</th>
          <th style={th}>Stage now</th>
          <th style={th}>Progress</th><th style={th}>Status</th>
          <th style={th}>Last reported</th>
        </tr></thead>
        <tbody>
          {shown.map((u) => (
            <UnitRow key={u.id} u={u} open={open === u.id}
              onToggle={() => setOpen(open === u.id ? null : u.id)}
              can={can} me={me} patchUnit={patchUnit} call={call} />))}
          {shown.length === 0 && (
            <tr><td style={td} colSpan={6}>
              {data.unit_count === 0
                ? "No units yet — generate them from the BOQ categories above."
                : "No unit matches."}</td></tr>)}
        </tbody>
      </table>
    </section>
  );
}

function UnitRow({ u, open, onToggle, can, me, patchUnit, call }) {
  const canReport = REPORT_ROLES.includes(me.role);
  return (<>
    <tr style={{ cursor: "pointer" }} onClick={onToggle}>
      <td style={{ ...td, fontFamily: "var(--font-mono)", fontWeight: 600 }}>
        {open ? "▾ " : "▸ "}{u.ref}</td>
      <td style={td}>{u.name}
        {u.size && <span style={{ color: "var(--muted)" }}> · {u.size}</span>}
      </td>
      <td style={td}>{u.current_stage || "—"}</td>
      <td style={td}>
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Bar value={u.percent} tone={u.status} />
          <strong>{pct(u.percent)}</strong></span></td>
      <td style={td}>
        <Chip tone={TONE[u.status] || "info"}>{u.status_label}</Chip>
        {u.status === "ON_HOLD" && u.hold_reason && (
          <div style={{ fontSize: 11, color: "var(--muted)" }}>
            {u.hold_reason}</div>)}</td>
      <td style={td}>{u.last_reported_on || "—"}
        {u.last_dpr && <div style={{ fontSize: 11, color: "var(--muted)" }}>
          {u.last_dpr}</div>}</td>
    </tr>
    {open && (
      <tr><td colSpan={6} style={{ padding: "6px 14px 12px",
                                   background: "var(--sky-soft, #f3f8fb)" }}>
        <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 320px" }}>
            <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 12.5 }}>
              <tbody>
                {u.stages.map((s) => (
                  <tr key={s.id}>
                    <td style={{ ...td, width: "45%" }}>{s.name}
                      <span style={{ color: "var(--muted)" }}>
                        {" "}· wt {Number(s.weight)}</span></td>
                    <td style={td}><Bar value={s.percent} /></td>
                    <td style={{ ...td, width: 52 }}>{pct(s.percent)}</td>
                    <td style={{ ...td, color: "var(--muted)", fontSize: 11 }}>
                      {s.dpr ? `${s.dpr} · ${s.on}` : (s.on || "")}</td>
                    {canReport && (
                      <td style={{ ...td, width: 74 }}>
                        <button style={{ ...ghostButton, padding: "2px 8px",
                                         fontSize: 11.5 }}
                                onClick={() => {
                                  const v = window.prompt(
                                    `${u.ref} — ${s.name}: % complete`,
                                    String(Number(s.percent)));
                                  if (v !== null) call(
                                    `/units/${u.id}/progress`,
                                    { stage_id: s.id, percent: v });
                                }}>set</button></td>)}
                  </tr>))}
              </tbody>
            </table>
            <p style={{ fontSize: 11.5, color: "var(--muted)",
                        margin: "6px 0 0" }}>
              Normally reported on the daily report — pick the unit and stage
              on a DPR work row and it lands here when the DPR is issued.
            </p>
          </div>
          {can && (
            <div style={{ flex: "0 0 250px", fontSize: 12.5 }}>
              <UnitEdit u={u} patchUnit={patchUnit} />
            </div>)}
        </div>
      </td></tr>)}
  </>);
}

function UnitEdit({ u, patchUnit }) {
  const [f, setF] = useState({ ref: u.ref, name: u.name, size: u.size,
                               location: u.location, scope: u.scope,
                               target_date: u.target_date || "" });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const row = { display: "flex", gap: 6, alignItems: "center",
                marginBottom: 5 };
  return (
    <div>
      <div style={row}><span style={{ width: 62 }}>Ref</span>
        <input value={f.ref} onChange={set("ref")} style={inputStyle} /></div>
      <div style={row}><span style={{ width: 62 }}>Name</span>
        <input value={f.name} onChange={set("name")} style={inputStyle} /></div>
      <div style={row}><span style={{ width: 62 }}>Size</span>
        <input value={f.size} onChange={set("size")} placeholder="145 m²"
               style={inputStyle} /></div>
      <div style={row}><span style={{ width: 62 }}>Location</span>
        <input value={f.location} onChange={set("location")}
               style={inputStyle} /></div>
      <div style={row}><span style={{ width: 62 }}>Target</span>
        <input type="date" value={f.target_date} onChange={set("target_date")}
               style={inputStyle} /></div>
      <div style={row}><span style={{ width: 62 }}>Scope</span>
        <input value={f.scope} onChange={set("scope")}
               style={inputStyle} /></div>
      <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
        <button style={{ ...buttonStyle, padding: "3px 12px", fontSize: 12 }}
                onClick={() => patchUnit(u, f)}>Save</button>
        {u.status !== "ON_HOLD" ? (
          <button style={{ ...ghostButton, padding: "3px 10px", fontSize: 12 }}
                  onClick={() => {
                    const why = window.prompt("Why is this unit on hold?");
                    if (why) patchUnit(u, { status: "ON_HOLD",
                                            hold_reason: why });
                  }}>Put on hold</button>
        ) : (
          <button style={{ ...ghostButton, padding: "3px 10px", fontSize: 12 }}
                  onClick={() => patchUnit(u, { status: "IN_PROGRESS",
                                                hold_reason: "" })}>
            Release hold</button>)}
      </div>
    </div>);
}

function StageLadder({ ladder, onDone }) {
  const [rows, setRows] = useState(ladder.stages.map(
    (s) => ({ name: s.name, weight: String(Number(s.weight)) })));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const total = rows.reduce((a, r) => a + (Number(r.weight) || 0), 0);

  async function save() {
    setBusy(true); setErr(null);
    try {
      onDone(await api(`/boq-categories/${ladder.category_id}/stages`,
        { method: "POST", body: { stages: rows } }));
    } catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <div style={{ border: "1px solid var(--sp-border, #d8e1e8)",
                  borderRadius: 8, padding: 10, margin: "6px 0" }}>
      <p style={{ fontSize: 11.5, color: "var(--muted)", margin: "0 0 6px" }}>
        The stages every {ladder.name} goes through, and what share of the unit
        each is worth. Weights need not add to 100 — they are relative.
      </p>
      {rows.map((r, i) => (
        <div key={i} style={{ display: "flex", gap: 6, marginBottom: 4 }}>
          <input value={r.name} placeholder="Stage"
                 style={{ ...inputStyle, flex: 1 }}
                 onChange={(e) => setRows(rows.map((x, j) => j === i
                   ? { ...x, name: e.target.value } : x))} />
          <input type="number" min="0" value={r.weight} placeholder="weight"
                 style={{ ...inputStyle, width: 84 }}
                 onChange={(e) => setRows(rows.map((x, j) => j === i
                   ? { ...x, weight: e.target.value } : x))} />
          <button style={{ ...ghostButton, color: "#c0392b",
                           padding: "2px 8px" }}
                  onClick={() => setRows(rows.filter((_, j) => j !== i))}>
            ×</button>
        </div>))}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button style={{ ...ghostButton, padding: "2px 9px", fontSize: 12 }}
                onClick={() => setRows([...rows, { name: "", weight: "10" }])}>
          + stage</button>
        <span style={{ fontSize: 12, color: "var(--muted)" }}>
          total weight {total}</span>
        <button style={{ ...buttonStyle, padding: "3px 12px", fontSize: 12,
                         marginLeft: "auto" }}
                disabled={busy} onClick={save}>Save stages</button>
        <button style={ghostButton} onClick={() => onDone(null)}>Cancel</button>
      </div>
      {err && <div style={{ color: "#c0392b", fontSize: 12 }}>{err}</div>}
    </div>);
}
