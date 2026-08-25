import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

/* Biometric terminals (owner 2026-08-23). Phase 1 is listen only: this page
 * shows what the gate is sending and who is enrolled. Nothing here writes
 * attendance — the day grid is still the clerk's.
 */
const MANAGE = ["HO_HR", "ADMIN", "PA"];
const STATUS_TONE = { MATCHED: "ok", UNKNOWN_ID: "warn", UNPARSED: "alert" };
// Timestamps arrive as UTC ISO strings; the gate clerk thinks in Maldives
// time, so render +5 — slicing the raw string showed punches 5h early.
const fmt = (s) => s
  ? new Date(s).toLocaleString("sv-SE",
      { timeZone: "Indian/Maldives" }).slice(0, 16)
  : "—";

export default function AttendanceDevicesPage({ me, sites }) {
  const [devices, setDevices] = useState(null);
  const [log, setLog] = useState(null);
  const [enrol, setEnrol] = useState(null);
  const [site, setSite] = useState("");
  const [tab, setTab] = useState("punches");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);
  const can = MANAGE.includes(me.role);

  const loadDevices = () => api("/attendance-devices").then(setDevices)
    .catch((e) => setError(e.message));
  const loadLog = () => api(`/attendance-devices/punches${
    site ? `?site=${site}` : ""}`).then(setLog).catch((e) => setError(e.message));
  const loadEnrol = () => site
    ? api(`/attendance-devices/enrolment?site=${site}`).then(setEnrol)
        .catch((e) => setError(e.message))
    : setEnrol(null);

  useEffect(() => { loadDevices(); }, []);
  useEffect(() => { loadLog(); if (tab === "enrolment") loadEnrol(); },
    [site, tab]); // eslint-disable-line

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap", marginBottom: 4 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Attendance terminals</h2>
        <select value={site} onChange={(e) => setSite(e.target.value)}
                style={{ ...inputStyle, width: 170, marginLeft: "auto" }}>
          <option value="">All sites</option>
          {(sites || []).map((s) => (
            <option key={s.id} value={s.id}>{s.code}</option>))}
        </select>
        {can && !adding && (
          <button style={buttonStyle} onClick={() => setAdding(true)}>
            ➕ Register a terminal</button>)}
      </div>
      <p style={{ color: "var(--muted)", fontSize: 12.5, margin: "0 0 12px" }}>
        Punches are evidence that a worker was at the gate. They are recorded
        here and matched to a worker — they do not write attendance. The day
        grid stays the clerk's, and the PM still locks the month.
      </p>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {adding && can && (
        <RegisterForm sites={sites} onDone={(ok) => {
          setAdding(false); if (ok) loadDevices(); }} />)}

      {/* --- terminals + health --- */}
      <table style={{ width: "100%", borderCollapse: "collapse",
                      fontSize: 13, marginBottom: 18 }}>
        <thead><tr>
          <th style={th}>Terminal</th><th style={th}>Site</th>
          <th style={th}>Serial</th><th style={th}>Last heard</th>
          <th style={{ ...th, textAlign: "right" }}>Today</th>
          <th style={{ ...th, textAlign: "right" }}>Total</th>
          <th style={th}>State</th>
        </tr></thead>
        <tbody>
          {(devices || []).filter((d) => !site || String(d.site_id) === site)
            .map((d) => (
            <tr key={d.id}>
              <td style={td}><strong>{d.name}</strong>
                {d.location_note && <div style={{ fontSize: 11,
                  color: "var(--muted)" }}>{d.location_note}</div>}</td>
              <td style={td}>{d.site_code}</td>
              <td style={{ ...td, fontFamily: "var(--font-mono)",
                           fontSize: 12 }}>{d.serial}
                {d.model && <div style={{ fontSize: 11,
                  color: "var(--muted)" }}>{d.model}</div>}</td>
              <td style={td}>{fmt(d.last_seen_at)}
                {d.minutes_since_seen != null && (
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>
                    {d.minutes_since_seen} min ago</div>)}</td>
              <td style={{ ...td, textAlign: "right" }}>{d.punches_today}</td>
              <td style={{ ...td, textAlign: "right" }}>
                {d.punches_received}</td>
              <td style={td}>
                {!d.is_active ? <Chip tone="info">Off</Chip>
                  : d.last_seen_at
                    ? <Chip tone={d.healthy ? "ok" : "alert"}>
                        {d.healthy ? "Live" : "Silent"}</Chip>
                    : <Chip tone="warn">Never heard from</Chip>}
              </td>
            </tr>))}
          {devices && devices.length === 0 && (
            <tr><td style={td} colSpan={7}>
              No terminal registered yet.{can ? " Register one above, then point"
                + " the device's ADMS server setting at the app." : ""}</td></tr>)}
        </tbody>
      </table>

      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        <button style={tab === "punches" ? buttonStyle : ghostButton}
                onClick={() => setTab("punches")}>Punch log</button>
        <button style={tab === "enrolment" ? buttonStyle : ghostButton}
                onClick={() => setTab("enrolment")}>Enrolment</button>
      </div>

      {tab === "punches" && (
        <>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
            <thead><tr>
              <th style={th}>Punched</th><th style={th}>Worker</th>
              <th style={th}>Device ID</th><th style={th}>In / out</th>
              <th style={th}>How</th><th style={th}>Terminal</th>
              <th style={th}>Status</th>
            </tr></thead>
            <tbody>
              {(log?.punches || []).map((p) => (
                <tr key={p.id}>
                  <td style={td}>{fmt(p.punched_at)}</td>
                  <td style={td}>{p.full_name
                    ? <>{p.full_name}<div style={{ fontSize: 11,
                        color: "var(--muted)" }}>{p.emp_no}</div></>
                    : <span style={{ color: "var(--muted)" }}>—</span>}</td>
                  <td style={{ ...td, fontFamily: "var(--font-mono)" }}>
                    {p.device_user_id}</td>
                  <td style={td}>{p.direction === "UNKNOWN" ? "—"
                    : p.direction}</td>
                  <td style={td}>{p.verify_mode || "—"}</td>
                  <td style={td}>{p.device}
                    <div style={{ fontSize: 11, color: "var(--muted)" }}>
                      {p.site_code}</div></td>
                  <td style={td}>
                    <Chip tone={STATUS_TONE[p.status] || "info"}>
                      {p.status_label}</Chip></td>
                </tr>))}
              {log && log.punches.length === 0 && (
                <tr><td style={td} colSpan={7}>
                  No punches yet. They appear within a minute of a worker using
                  the terminal.</td></tr>)}
            </tbody>
          </table>
          {log && log.count >= 400 && (
            <p style={{ fontSize: 12, color: "var(--muted)" }}>
              Showing the most recent 400.</p>)}
        </>
      )}

      {tab === "enrolment" && (
        !site ? <p style={{ color: "var(--muted)", fontSize: 13 }}>
          Choose a site to see who is enrolled.</p>
        : !enrol ? <p style={{ color: "var(--muted)", fontSize: 13 }}>
          Loading…</p>
        : <Enrolment data={enrol} can={can} reload={() => {
            loadEnrol(); loadLog(); }} />)}
    </section>
  );
}

function Enrolment({ data, can, reload }) {
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);

  async function add(emp) {
    setBusy(emp.id); setErr(null);
    try {
      await api(`/employees/${emp.id}/biometric`, { method: "POST",
        body: { finger_count: 2, face_enrolled: true } });
      reload();
    } catch (e) { setErr(e.message); }
    finally { setBusy(null); }
  }
  async function remove(row) {
    if (!window.confirm(`Remove ${row.full_name} from the terminals?`)) return;
    setBusy(row.employee_id); setErr(null);
    try {
      await api(`/employees/${row.employee_id}/biometric`,
                { method: "DELETE", body: { reason: "removed by HR" } });
      reload();
    } catch (e) { setErr(e.message); }
    finally { setBusy(null); }
  }

  return (<>
    {err && <p style={{ color: "#c0392b", fontSize: 13 }}>{err}</p>}
    {data.missing.length > 0 && (
      <div style={{ border: "1px solid #F0C36D", background: "#FFF6E5",
                    borderRadius: 6, padding: "10px 13px", marginBottom: 14 }}>
        <strong style={{ fontSize: 13 }}>
          {data.missing.length} worker{data.missing.length > 1 ? "s" : ""} on
          site not enrolled</strong>
        <p style={{ fontSize: 12.5, margin: "4px 0 8px",
                    color: "var(--muted)" }}>
          Enrol them on the terminal using the ID shown, then record it here.
          Two fingers on different hands plus a face — a man with a bandaged
          hand should still be able to clock in.</p>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 12.5 }}>
          <tbody>
            {data.missing.map((m) => (
              <tr key={m.id}>
                <td style={td}>{m.emp_no}</td>
                <td style={td}>{m.full_name}</td>
                <td style={td}>{m.trade}</td>
                <td style={{ ...td, fontFamily: "var(--font-mono)",
                             fontWeight: 600 }}>ID {m.suggested_id}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {can && <Btn variant="secondary" disabled={busy === m.id}
                    onClick={() => add(m)}>enrolled</Btn>}</td>
              </tr>))}
          </tbody>
        </table>
      </div>)}

    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
      <thead><tr>
        <th style={th}>Worker</th><th style={th}>Device ID</th>
        <th style={th}>Fingers</th><th style={th}>Face</th>
        <th style={th}>Enrolled</th>{can && <th style={th}></th>}
      </tr></thead>
      <tbody>
        {data.enrolled.map((r) => (
          <tr key={r.employee_id}>
            <td style={td}>{r.full_name}
              <div style={{ fontSize: 11, color: "var(--muted)" }}>
                {r.emp_no}</div></td>
            <td style={{ ...td, fontFamily: "var(--font-mono)" }}>
              {r.device_user_id}</td>
            <td style={td}>{r.finger_count || "—"}</td>
            <td style={td}>{r.face_enrolled
              ? <Chip tone="ok">yes</Chip>
              : <span style={{ color: "var(--muted)" }}>no</span>}</td>
            <td style={td}>{r.enrolled_on || "—"}
              {r.enrolled_by && <div style={{ fontSize: 11,
                color: "var(--muted)" }}>{r.enrolled_by}</div>}</td>
            {can && <td style={{ ...td, textAlign: "right" }}>
              <Btn variant="secondary" disabled={busy === r.employee_id}
                   onClick={() => remove(r)}>remove</Btn></td>}
          </tr>))}
        {data.enrolled.length === 0 && (
          <tr><td style={td} colSpan={can ? 6 : 5}>
            Nobody enrolled on this site yet.</td></tr>)}
      </tbody>
    </table>
  </>);
}

function RegisterForm({ sites, onDone }) {
  const [f, setF] = useState({ site_id: "", name: "", serial: "", model: "",
                               location_note: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  async function save() {
    setBusy(true); setErr(null);
    try {
      await api("/attendance-devices", { method: "POST", body: f });
      onDone(true);
    } catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <div style={{ border: "1px solid var(--sp-border, #d8e1e8)",
                  borderRadius: 8, padding: 12, marginBottom: 14,
                  display: "flex", gap: 8, flexWrap: "wrap",
                  alignItems: "flex-end" }}>
      <select value={f.site_id} onChange={set("site_id")}
              style={{ ...inputStyle, width: 150 }}>
        <option value="">Site…</option>
        {(sites || []).map((s) => (
          <option key={s.id} value={s.id}>{s.code} — {s.name}</option>))}
      </select>
      <input placeholder="Name, e.g. Camp gate" value={f.name}
             onChange={set("name")} style={{ ...inputStyle, width: 170 }} />
      <input placeholder="Serial number" value={f.serial}
             onChange={set("serial")} style={{ ...inputStyle, width: 170 }} />
      <input placeholder="Model" value={f.model} onChange={set("model")}
             style={{ ...inputStyle, width: 170 }} />
      <input placeholder="Where it is mounted" value={f.location_note}
             onChange={set("location_note")}
             style={{ ...inputStyle, flex: "1 1 180px" }} />
      <Btn onClick={save}
           disabled={busy || !f.site_id || !f.name.trim() || !f.serial.trim()}>
        {busy ? "Saving…" : "Register"}</Btn>
      <Btn variant="secondary" onClick={() => onDone(false)}>Cancel</Btn>
      {err && <div style={{ color: "#c0392b", fontSize: 12.5, width: "100%" }}>
        {err}</div>}
    </div>
  );
}
