import { useEffect, useState } from "react";
import { api } from "./api.js";
import { card, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Admin security view (owner 2026-08-06): sign-in activity + the append-only
// audit trail, filterable and paged. Admin only.

const PAGE = 50;
const KIND_LABEL = { LOGIN: "Signed in", FAILED: "Failed", LOGOUT: "Signed out" };
const KIND_TONE = { LOGIN: "#1a7f37", FAILED: "#c0392b", LOGOUT: "#6b7681" };
const fmt = (s) => (s ? new Date(s).toLocaleString() : "");
const shortUA = (ua) => {
  if (!ua) return "—";
  const m = ua.match(/(Chrome|Firefox|Safari|Edg|Mobile|Android|iPhone|iPad)/g);
  return m ? [...new Set(m)].join(" / ") : ua.slice(0, 40);
};

export default function ActivityPage() {
  const [tab, setTab] = useState("login");
  return (
    <section style={card}>
      <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
        Login &amp; Audit</h2>
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "4px 0 12px" }}>
        Who signed in and every recorded action across Planet. Admin only.</p>
      <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
        {[["login", "Login activity"], ["audit", "Audit trail"]].map(
          ([k, label]) => (
          <button key={k} onClick={() => setTab(k)} style={{
            ...ghostButton, padding: "5px 14px",
            background: tab === k ? "var(--sp-navy)" : undefined,
            color: tab === k ? "#fff" : "var(--sp-navy)" }}>{label}</button>
        ))}
      </div>
      {tab === "login" ? <LoginActivity /> : <AuditTrail />}
    </section>
  );
}

function Pager({ offset, total, count, onPage }) {
  const from = total === 0 ? 0 : offset + 1;
  const to = offset + count;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10,
      marginTop: 10, fontSize: 12.5, color: "var(--muted)" }}>
      <span>{from}–{to} of {total}</span>
      <button style={{ ...ghostButton, padding: "2px 10px" }}
        disabled={offset === 0} onClick={() => onPage(offset - PAGE)}>
        ← Newer</button>
      <button style={{ ...ghostButton, padding: "2px 10px" }}
        disabled={to >= total} onClick={() => onPage(offset + PAGE)}>
        Older →</button>
    </div>
  );
}

const label = { display: "block", fontSize: 11.5, color: "var(--muted)" };

function LoginActivity() {
  const [data, setData] = useState(null);
  const [f, setF] = useState({ kind: "", q: "", since: "", until: "" });
  const [offset, setOffset] = useState(0);
  const [err, setErr] = useState(null);
  function load(off = offset) {
    const qs = new URLSearchParams({ limit: PAGE, offset: off });
    Object.entries(f).forEach(([k, v]) => v && qs.set(k, v));
    api(`/admin/login-activity?${qs}`).then((d) => { setData(d); setOffset(off); })
      .catch((e) => setErr(e.message));
  }
  useEffect(() => { load(0); }, [f]); // eslint-disable-line
  return (
    <div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
        marginBottom: 10, alignItems: "flex-end" }}>
        <label style={label}>Type
          <select value={f.kind} style={{ ...inputStyle, display: "block" }}
            onChange={(e) => setF({ ...f, kind: e.target.value })}>
            <option value="">All</option>
            <option value="LOGIN">Signed in</option>
            <option value="FAILED">Failed</option>
            <option value="LOGOUT">Signed out</option></select></label>
        <label style={label}>User
          <input value={f.q} placeholder="username…"
            style={{ ...inputStyle, display: "block" }}
            onChange={(e) => setF({ ...f, q: e.target.value })} /></label>
        <label style={label}>From
          <input type="date" value={f.since}
            style={{ ...inputStyle, display: "block" }}
            onChange={(e) => setF({ ...f, since: e.target.value })} /></label>
        <label style={label}>To
          <input type="date" value={f.until}
            style={{ ...inputStyle, display: "block" }}
            onChange={(e) => setF({ ...f, until: e.target.value })} /></label>
      </div>
      {err && <p style={{ color: "#c0392b", fontSize: 13 }}>{err}</p>}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
          fontSize: 12.5 }}>
          <thead><tr>
            <th style={th}>When</th><th style={th}>User</th>
            <th style={th}>Event</th><th style={th}>Source</th>
            <th style={th}>IP</th><th style={th}>Device</th>
          </tr></thead>
          <tbody>
            {(data?.items || []).map((e) => (
              <tr key={e.id}>
                <td style={{ ...td, whiteSpace: "nowrap" }}>{fmt(e.at)}</td>
                <td style={td}>{e.full_name || e.username || "—"}
                  {e.role && <span style={{ color: "var(--muted)" }}>
                    {" "}· {e.role}</span>}</td>
                <td style={{ ...td, color: KIND_TONE[e.kind], fontWeight: 600 }}>
                  {KIND_LABEL[e.kind] || e.kind}</td>
                <td style={td}>{e.source}</td>
                <td style={{ ...td, fontFamily: "monospace", fontSize: 11.5 }}>
                  {e.ip_address || "—"}</td>
                <td style={{ ...td, color: "var(--muted)" }} title={e.user_agent}>
                  {shortUA(e.user_agent)}</td>
              </tr>
            ))}
            {data && data.items.length === 0 && (
              <tr><td colSpan={6} style={{ ...td, color: "var(--muted)" }}>
                No sign-in activity for these filters.</td></tr>)}
          </tbody>
        </table>
      </div>
      {data && <Pager offset={offset} total={data.total}
        count={data.items.length} onPage={load} />}
    </div>
  );
}

function AuditTrail() {
  const [data, setData] = useState(null);
  const [f, setF] = useState({ entity: "", event: "", entity_id: "",
    since: "", until: "" });
  const [offset, setOffset] = useState(0);
  const [err, setErr] = useState(null);
  const [open, setOpen] = useState({});
  function load(off = offset) {
    const qs = new URLSearchParams({ limit: PAGE, offset: off });
    Object.entries(f).forEach(([k, v]) => v && qs.set(k, v));
    api(`/admin/audit-trail?${qs}`).then((d) => { setData(d); setOffset(off); })
      .catch((e) => setErr(e.message));
  }
  useEffect(() => { load(0); }, [f]); // eslint-disable-line
  return (
    <div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
        marginBottom: 10, alignItems: "flex-end" }}>
        <label style={label}>Area
          <select value={f.entity} style={{ ...inputStyle, display: "block" }}
            onChange={(e) => setF({ ...f, entity: e.target.value })}>
            <option value="">All</option>
            {(data?.entities || []).map((x) =>
              <option key={x} value={x}>{x}</option>)}</select></label>
        <label style={label}>Event
          <input value={f.event} placeholder="e.g. APPROVE"
            style={{ ...inputStyle, display: "block" }}
            onChange={(e) => setF({ ...f, event: e.target.value })} /></label>
        <label style={label}>Record ID
          <input value={f.entity_id} placeholder="entity id"
            style={{ ...inputStyle, display: "block", width: 90 }}
            onChange={(e) => setF({ ...f, entity_id: e.target.value })} /></label>
        <label style={label}>From
          <input type="date" value={f.since}
            style={{ ...inputStyle, display: "block" }}
            onChange={(e) => setF({ ...f, since: e.target.value })} /></label>
        <label style={label}>To
          <input type="date" value={f.until}
            style={{ ...inputStyle, display: "block" }}
            onChange={(e) => setF({ ...f, until: e.target.value })} /></label>
      </div>
      {err && <p style={{ color: "#c0392b", fontSize: 13 }}>{err}</p>}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
          fontSize: 12.5 }}>
          <thead><tr>
            <th style={th}>When</th><th style={th}>Actor</th>
            <th style={th}>Area</th><th style={th}>Event</th>
            <th style={th}>Change</th><th style={th} />
          </tr></thead>
          <tbody>
            {(data?.items || []).map((a) => {
              const hasDetail = a.detail && Object.keys(a.detail).length > 0;
              return (
                <tr key={a.id}>
                  <td style={{ ...td, whiteSpace: "nowrap" }}>{fmt(a.at)}</td>
                  <td style={td}>{a.actor || "—"}
                    {a.actor_role && <span style={{ color: "var(--muted)" }}>
                      {" "}· {a.actor_role}</span>}</td>
                  <td style={td}>{a.entity}
                    <span style={{ color: "var(--muted)" }}> #{a.entity_id}</span>
                  </td>
                  <td style={{ ...td, fontWeight: 600 }}>{a.event}</td>
                  <td style={{ ...td, color: "var(--muted)" }}>
                    {a.from_state || a.to_state
                      ? `${a.from_state || "—"} → ${a.to_state || "—"}` : ""}</td>
                  <td style={td}>{hasDetail && (
                    <button style={{ ...ghostButton, padding: "1px 8px",
                      fontSize: 11 }}
                      onClick={() => setOpen((o) => ({ ...o, [a.id]: !o[a.id] }))}>
                      {open[a.id] ? "Hide" : "Detail"}</button>)}
                    {open[a.id] && (
                      <pre style={{ margin: "4px 0 0", fontSize: 11,
                        whiteSpace: "pre-wrap", color: "#41505c" }}>
                        {JSON.stringify(a.detail, null, 1)}</pre>)}</td>
                </tr>
              );
            })}
            {data && data.items.length === 0 && (
              <tr><td colSpan={6} style={{ ...td, color: "var(--muted)" }}>
                No audit entries for these filters.</td></tr>)}
          </tbody>
        </table>
      </div>
      {data && <Pager offset={offset} total={data.total}
        count={data.items.length} onPage={load} />}
    </div>
  );
}
