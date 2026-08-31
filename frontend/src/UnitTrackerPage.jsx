import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

/* Unit progress tracker — a page of its own, opened from the site dashboard
 * (owner 2026-08-23). The site team's read of where every villa/pool stands:
 * a bar per unit, the milestones behind it, and which daily report last moved
 * it. Editing lives on the project's Units tab; this is for reading.
 */
const TONE = { COMPLETE: "ok", IN_PROGRESS: "info", ON_HOLD: "warn",
               NOT_STARTED: "info" };
const round = (v) => Math.round(Number(v || 0));

function Bar({ value, h = 9, w = "100%" }) {
  const v = Math.max(0, Math.min(100, Number(value || 0)));
  return (
    <div style={{ background: "#e8eef3", borderRadius: 99, height: h,
                  width: w, overflow: "hidden" }}>
      <div style={{ width: `${v}%`, height: "100%", borderRadius: 99,
                    background: v >= 100 ? "#1a7f37"
                                         : "var(--sp-sky, #29ABE2)" }} />
    </div>);
}

export default function UnitTrackerPage({ site, me, onClose, onOpenProject }) {
  const [projects, setProjects] = useState(null);
  const [boards, setBoards] = useState({});
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    api(`/sites/${site.id}/projects`).then((rows) => {
      setProjects(rows);
      rows.forEach((p) => api(`/projects/${p.id}/units`)
        .then((d) => setBoards((b) => ({ ...b, [p.id]: d })))
        .catch(() => {}));
    }).catch((e) => setError(e.message));
  }, [site.id]);

  const tracked = (projects || []).filter(
    (p) => boards[p.id] && boards[p.id].unit_count > 0);

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap", marginBottom: 12 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 18 }}>
          Unit Progress — {site.code}</h2>
        <input placeholder="Find a unit…" value={filter}
               onChange={(e) => setFilter(e.target.value)}
               style={{ ...inputStyle, width: 190, marginLeft: "auto" }} />
        <Btn variant="ghost" onClick={onClose}>Close</Btn>
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      {projects && tracked.length === 0 && (
        <p style={{ color: "var(--muted)", fontSize: 13 }}>
          No project on this site is tracking units yet. Set them up on a
          project’s <strong>Commercial → Units</strong> tab.
        </p>)}

      {tracked.map((p) => {
        const d = boards[p.id];
        const units = d.units.filter((u) => {
          const q = filter.trim().toLowerCase();
          return !q || `${u.ref} ${u.name} ${u.current_stage}`
            .toLowerCase().includes(q);
        });
        return (
          <div key={p.id} style={{ marginBottom: 26 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                          flexWrap: "wrap" }}>
              <h3 style={{ margin: 0, fontSize: 15,
                           color: "var(--sp-navy)" }}>{p.title}</h3>
              <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
                {p.code} · {d.complete} of {d.unit_count} complete</span>
              {/* The week's movement as a client PDF — charts and all. */}
              <a href={`/api/v1/projects/${p.id}/units/weekly.pdf`}
                 target="_blank" rel="noreferrer"
                 style={{ ...ghostButton, padding: "2px 10px", fontSize: 12,
                          marginLeft: "auto", textDecoration: "none" }}>
                ⬇ Weekly report</a>
              {onOpenProject && (
                <button style={{ ...ghostButton, padding: "2px 10px",
                                 fontSize: 12 }}
                        onClick={() => onOpenProject(p.id)}>
                  open project →</button>)}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 12,
                          margin: "8px 0 14px" }}>
              <Bar value={d.overall_percent} h={12} />
              <strong style={{ fontSize: 17, minWidth: 52,
                               color: "var(--sp-navy)" }}>
                {round(d.overall_percent)}%</strong>
            </div>

            <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 13 }}>
              <thead><tr>
                <th style={th}>Unit</th><th style={th}>Milestone now</th>
                <th style={{ ...th, width: 190 }}>Progress</th>
                <th style={th}>Started</th>
                <th style={th}>Status</th><th style={th}>Last reported</th>
              </tr></thead>
              <tbody>
                {units.map((u) => (
                  <UnitRows key={u.id} u={u} open={open === u.id}
                    onToggle={() => setOpen(open === u.id ? null : u.id)} />))}
                {units.length === 0 && (
                  <tr><td style={td} colSpan={6}>No unit matches.</td></tr>)}
              </tbody>
            </table>
          </div>);
      })}
    </section>);
}

function UnitRows({ u, open, onToggle }) {
  return (<>
    <tr style={{ cursor: "pointer" }} onClick={onToggle}>
      <td style={{ ...td, fontWeight: 600 }}>
        {open ? "▾ " : "▸ "}{u.ref}
        {u.size && <span style={{ color: "var(--muted)", fontWeight: 400 }}>
          {" "}· {u.size}</span>}</td>
      <td style={td}>{u.current_stage || "—"}</td>
      <td style={td}>
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Bar value={u.percent} w={120} />
          <strong style={{ minWidth: 38 }}>{round(u.percent)}%</strong></span>
      </td>
      {/* When work began on this unit, and how long it has run — or took
          (owner 2026-08-23). */}
      <td style={td}>
        {u.started_on ? (<>
          {u.started_on}
          <div style={{ fontSize: 11, color: "var(--muted)" }}>
            {u.days_running} day{u.days_running === 1 ? "" : "s"}
            {u.status === "COMPLETE" ? " · finished" : ""}</div>
        </>) : <span style={{ color: "var(--muted)" }}>—</span>}
      </td>
      <td style={td}><Chip tone={TONE[u.status] || "info"}>
        {u.status_label}</Chip>
        {u.status === "ON_HOLD" && u.hold_reason && (
          <div style={{ fontSize: 11, color: "var(--muted)" }}>
            {u.hold_reason}</div>)}</td>
      <td style={td}>{u.last_reported_on || "—"}
        {u.last_dpr && <div style={{ fontSize: 11, color: "var(--muted)" }}>
          {u.last_dpr}</div>}</td>
    </tr>
    {open && (
      <tr><td colSpan={6} style={{ background: "var(--sky-soft, #f3f8fb)",
                                   padding: "8px 16px 14px" }}>
        {/* The milestones behind the bar — how far each stage has got and
            which daily report reported it. */}
        {u.stages.map((s) => {
          const pc = Number(s.percent);
          return (
            <div key={s.id} style={{ display: "flex", alignItems: "center",
                                     gap: 10, margin: "6px 0" }}>
              <span style={{ width: 16, textAlign: "center",
                             color: pc >= 100 ? "#1a7f37"
                                  : pc > 0 ? "var(--sp-sky, #29ABE2)"
                                  : "#b6c2cc" }}>
                {pc >= 100 ? "●" : pc > 0 ? "◐" : "○"}</span>
              <span style={{ flex: "1 1 auto", fontSize: 12.5 }}>{s.name}</span>
              <Bar value={pc} h={6} w={130} />
              <span style={{ width: 40, textAlign: "right", fontSize: 12 }}>
                {round(pc)}%</span>
              <span style={{ width: 150, fontSize: 11,
                             color: "var(--muted)" }}>
                {s.dpr ? `${s.dpr} · ${s.on}` : (s.on || "")}</span>
            </div>);
        })}
        {u.scope && <p style={{ fontSize: 12, color: "var(--muted)",
                                marginTop: 8 }}>{u.scope}</p>}
      </td></tr>)}
  </>);
}
