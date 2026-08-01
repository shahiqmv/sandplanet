import { useEffect, useState } from "react";
import { api } from "./api.js";
import { card, th, td, Btn, Chip, ghostButton } from "./ui.jsx";

const TYPE_LABEL = { PROJECT: "Project review", PROSPECT: "Prospective client",
  SITE: "Site meeting", OTHER: "Other" };
const TYPE_TONE = { PROJECT: "info", PROSPECT: "ok", SITE: "warn",
  OTHER: "info" };
const STATUS_TONE = { SCHEDULED: "info", HELD: "ok", CANCELLED: "alert",
  POSTPONED: "warn" };
const LOC = { OFFICE: "Head office", SITE: "At site", CLIENT: "Client's office",
  ONLINE: "Online", OTHER: "Other" };
const AI_STATUS = { OPEN: "Open", IN_PROGRESS: "In progress", DONE: "Done",
  CANCELLED: "Cancelled" };

const dt = (s) => s ? new Date(s).toLocaleString("en-GB", { day: "2-digit",
  month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
const dOnly = (s) => s ? new Date(s).toLocaleDateString("en-GB",
  { day: "2-digit", month: "short", year: "numeric" }) : "—";

const sel = { padding: "6px 8px", border: "1px solid var(--line)",
  borderRadius: 6, fontSize: 13, background: "#fff" };

// Module-scope so it's a stable component type — defining it inside a form
// component remounts inputs on every render and steals focus each keystroke.
function F({ label, children }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 3,
      fontSize: 12, color: "var(--muted)" }}>{label}{children}</label>);
}

export default function MeetingsPage({ me }) {
  const [tab, setTab] = useState("meetings");
  return (
    <div style={{ maxWidth: 1100 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <h1 style={{ margin: 0 }}>Meetings</h1>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>
          Client &amp; site meetings, minutes and follow-ups</span>
      </div>
      <div style={{ display: "flex", gap: 6, margin: "10px 0 14px" }}>
        {[["meetings", "Calendar & log"], ["actions", "My follow-ups"]].map(
          ([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            style={{ padding: "6px 14px", border: "1px solid var(--line)",
              borderRadius: 6, cursor: "pointer", fontSize: 13,
              background: tab === k ? "var(--navy)" : "#fff",
              color: tab === k ? "#fff" : "var(--navy)" }}>{label}</button>
        ))}
      </div>
      {tab === "meetings" ? <MeetingList me={me} /> : <MyActions />}
    </div>
  );
}

function MeetingList({ me }) {
  const [data, setData] = useState(null);
  const [type, setType] = useState("");
  const [selected, setSelected] = useState(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);

  const load = () => api(`/meetings${type ? `?type=${type}` : ""}`)
    .then(setData).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [type]);

  if (selected) return <MeetingDetail id={selected} me={me}
    onBack={() => { setSelected(null); load(); }} />;
  if (creating) return <NewMeeting me={me}
    onDone={(m) => { setCreating(false); load(); if (m) setSelected(m.id); }}
    onCancel={() => setCreating(false)} />;

  return (
    <div>
      <div style={{ display: "flex", gap: 8, alignItems: "center",
        marginBottom: 10, flexWrap: "wrap" }}>
        <select value={type} onChange={(e) => setType(e.target.value)}
          style={sel}>
          <option value="">All types</option>
          {Object.entries(TYPE_LABEL).map(([k, v]) =>
            <option key={k} value={k}>{v}</option>)}
        </select>
        {data?.can_create && <Btn variant="primary"
          onClick={() => setCreating(true)}
          style={{ marginLeft: "auto" }}>+ New meeting</Btn>}
      </div>
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      <div style={{ ...card, padding: 0, overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
          fontSize: 13 }}>
          <thead><tr>
            <th style={{ ...th, textAlign: "left" }}>When</th>
            <th style={{ ...th, textAlign: "left" }}>Meeting</th>
            <th style={{ ...th, textAlign: "left" }}>Type</th>
            <th style={{ ...th, textAlign: "left" }}>With</th>
            <th style={{ ...th, textAlign: "left" }}>Status</th>
            <th style={{ ...th, textAlign: "right" }}>Open follow-ups</th>
          </tr></thead>
          <tbody>
            {data && !data.meetings.length && <tr><td style={td} colSpan={6}>
              No meetings yet.</td></tr>}
            {data?.meetings.map((m) => (
              <tr key={m.id} style={{ cursor: "pointer" }}
                onClick={() => setSelected(m.id)}>
                <td style={td}>{dt(m.scheduled_at)}</td>
                <td style={td}><b style={{ color: "var(--navy)" }}>{m.title}</b>
                  {m.cadence !== "ONE_OFF" && <span style={{ fontSize: 11,
                    color: "var(--muted)" }}> · {m.cadence.toLowerCase()}</span>}
                </td>
                <td style={td}><Chip tone={TYPE_TONE[m.meeting_type]}>
                  {TYPE_LABEL[m.meeting_type]}</Chip></td>
                <td style={td}>{m.project_code || m.org_name
                  || m.site_code || "—"}</td>
                <td style={td}><Chip tone={STATUS_TONE[m.status]}>
                  {m.status.toLowerCase()}</Chip></td>
                <td style={{ ...td, textAlign: "right" }}>
                  {m.open_actions || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MyActions() {
  const [items, setItems] = useState(null);
  useEffect(() => {
    api("/meetings/my-actions").then((r) => setItems(r.items)).catch(() => {});
  }, []);
  if (!items) return <div style={card}>Loading…</div>;
  return (
    <div style={{ ...card, padding: 0, overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse",
        fontSize: 13 }}>
        <thead><tr>
          <th style={{ ...th, textAlign: "left" }}>Action</th>
          <th style={{ ...th, textAlign: "left" }}>From meeting</th>
          <th style={{ ...th, textAlign: "left" }}>Due</th>
          <th style={{ ...th, textAlign: "left" }}>Status</th>
        </tr></thead>
        <tbody>
          {!items.length && <tr><td style={td} colSpan={4}>
            Nothing outstanding — you're all clear.</td></tr>}
          {items.map((a) => (
            <tr key={a.id}>
              <td style={td}>{a.description}</td>
              <td style={td}>{a.meeting_title}</td>
              <td style={{ ...td, color: a.overdue ? "var(--red-fg)" : "" }}>
                {dOnly(a.due_date)}{a.overdue ? " · overdue" : ""}</td>
              <td style={td}>{AI_STATUS[a.status]}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MeetingDetail({ id, me, onBack }) {
  const [m, setM] = useState(null);
  const [minutes, setMinutes] = useState("");
  const [notes, setNotes] = useState("");
  const [actions, setActions] = useState([]);
  const [users, setUsers] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);

  const load = () => api(`/meetings/${id}`).then((d) => {
    setM(d); setMinutes(d.minutes || ""); setNotes(d.notes || "");
    setActions(d.action_items.map((a) => ({ ...a })));
  }).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [id]);
  useEffect(() => { api("/users").then((r) =>
    setUsers(Array.isArray(r) ? r : (r.results || []))).catch(() => {}); }, []);

  async function run(fn, ok) {
    setError(null); setMsg(null); setBusy(true);
    try { await fn(); if (ok) setMsg(ok); } catch (e) { setError(e.message); }
    setBusy(false);
  }
  const saveMinutes = (status) => run(async () => {
    const d = await api(`/meetings/${id}`, { method: "PATCH",
      body: { minutes, ...(status ? { minutes_status: status } : {}) } });
    setM(d);
  }, status === "FINAL" ? "Minutes finalised" : "Minutes saved");
  const saveActions = () => run(async () => {
    const d = await api(`/meetings/${id}/actions`, { method: "POST",
      body: { rows: actions } });
    setM(d); setActions(d.action_items.map((a) => ({ ...a })));
  }, "Follow-ups saved");
  const close = () => run(async () => {
    const r = await api(`/meetings/${id}/close`, { method: "POST", body: {} });
    setM(r.meeting);
    setMsg(r.next ? `Marked held · next occurrence scheduled for `
      + `${dt(r.next.scheduled_at)}` : "Marked held");
  });
  const draft = () => run(async () => {
    const r = await api(`/meetings/${id}/draft-minutes`,
      { method: "POST", body: { notes } });
    if (r.minutes) setMinutes(r.minutes);
    if (r.action_items?.length)
      setActions((as) => [...as, ...r.action_items]);
  }, "Claude drafted the minutes — review, edit and save.");

  if (!m) return <div style={card}>{error || "Loading…"}</div>;
  const canManage = m.can_manage;
  const setA = (i, k, v) => setActions((as) =>
    as.map((a, j) => j === i ? { ...a, [k]: v } : a));

  return (
    <div>
      <button style={{ ...ghostButton, marginBottom: 10 }}
        onClick={onBack}>← All meetings</button>
      <div style={{ ...card }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center",
          flexWrap: "wrap" }}>
          <h2 style={{ margin: 0, color: "var(--navy)" }}>{m.title}</h2>
          <Chip tone={TYPE_TONE[m.meeting_type]}>
            {TYPE_LABEL[m.meeting_type]}</Chip>
          <Chip tone={STATUS_TONE[m.status]}>{m.status.toLowerCase()}</Chip>
          {m.cadence !== "ONE_OFF" && <Chip tone="info">
            {m.cadence.toLowerCase()}</Chip>}
        </div>
        <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 6,
          display: "flex", gap: 16, flexWrap: "wrap" }}>
          <span>🕑 {dt(m.scheduled_at)} · {m.duration_minutes} min</span>
          <span>📍 {LOC[m.location_kind]}{m.location_note
            ? ` — ${m.location_note}` : ""}</span>
          <span>With: {m.project_code || m.org_name || m.site_code || "—"}
            {m.org_contact ? ` (${m.org_contact})` : ""}</span>
          <span>Organiser: {m.organiser}</span>
        </div>
        {msg && <p style={{ color: "var(--green-fg)", fontSize: 13 }}>{msg}</p>}
        {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
        {canManage && m.status === "SCHEDULED" && (
          <Btn variant="secondary" disabled={busy} onClick={close}
            style={{ marginTop: 8 }}>
            Mark held{m.cadence !== "ONE_OFF" ? " & schedule next" : ""}</Btn>)}
      </div>

      {m.attendees?.length > 0 && (
        <div style={{ ...card, marginTop: 10 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 14 }}>Attendees</h3>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {m.attendees.map((a) => (
              <span key={a.id} style={{ fontSize: 12.5, padding: "3px 10px",
                borderRadius: 999, background: a.is_external
                  ? "var(--amber-bg)" : "var(--sky-soft)" }}>
                {a.name}{a.org ? ` · ${a.org}` : ""}</span>
            ))}
          </div>
        </div>)}

      {m.agenda && (
        <div style={{ ...card, marginTop: 10 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 14 }}>Agenda</h3>
          <div style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{m.agenda}</div>
        </div>)}

      <div style={{ ...card, marginTop: 10 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 14 }}>Minutes</h3>
          <Chip tone={m.minutes_status === "FINAL" ? "ok" : "info"}>
            {m.minutes_status === "FINAL" ? "final"
              : m.minutes_status === "DRAFT" ? "draft" : "none"}</Chip>
        </div>
        {canManage && (
          <div style={{ background: "var(--sky-soft)", borderRadius: 8,
            padding: 10, marginBottom: 10 }}>
            <div style={{ fontSize: 12, color: "var(--muted)",
              marginBottom: 4 }}>Rough notes — jot down what happened, then let
              Claude write it up and pull out the follow-ups.</div>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)}
              rows={4} placeholder="e.g. slab on block B done, client wants pool
                coping in black granite, Ahmed to send revised programme by Fri…"
              style={{ width: "100%", ...sel, fontFamily: "inherit",
                resize: "vertical" }} />
            <Btn variant="primary" disabled={busy || !notes.trim()}
              onClick={draft} style={{ marginTop: 6 }}>
              {busy ? "Drafting…" : "✦ Draft with Claude"}</Btn>
          </div>)}
        <textarea value={minutes} onChange={(e) => setMinutes(e.target.value)}
          disabled={!canManage} rows={10} placeholder="Record the minutes…"
          style={{ width: "100%", ...sel, fontFamily: "inherit",
            resize: "vertical" }} />
        {canManage && (
          <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
            <Btn variant="secondary" disabled={busy}
              onClick={() => saveMinutes()}>Save draft</Btn>
            <Btn variant="primary" disabled={busy}
              onClick={() => saveMinutes("FINAL")}>Finalise</Btn>
          </div>)}
      </div>

      <div style={{ ...card, marginTop: 10 }}>
        <h3 style={{ margin: "0 0 6px", fontSize: 14 }}>Follow-ups</h3>
        <table style={{ width: "100%", borderCollapse: "collapse",
          fontSize: 13 }}>
          <thead><tr>
            <th style={{ ...th, textAlign: "left" }}>Action</th>
            <th style={{ ...th, textAlign: "left", width: 160 }}>Owner</th>
            <th style={{ ...th, textAlign: "left", width: 130 }}>Due</th>
            <th style={{ ...th, textAlign: "left", width: 130 }}>Status</th>
            <th style={{ ...th, width: 28 }}></th>
          </tr></thead>
          <tbody>
            {actions.map((a, i) => (
              <tr key={i}>
                <td style={{ padding: 2 }}>
                  <input value={a.description || ""} disabled={!canManage}
                    onChange={(e) => setA(i, "description", e.target.value)}
                    style={{ ...sel, width: "100%" }} />
                  {a.carried && <span style={{ fontSize: 10,
                    color: "var(--muted)" }}>carried forward</span>}</td>
                <td style={{ padding: 2 }}>
                  <select value={a.owner_id || ""} disabled={!canManage}
                    onChange={(e) => setA(i, "owner_id",
                      e.target.value ? Number(e.target.value) : null)}
                    style={{ ...sel, width: "100%" }}>
                    <option value="">{a.owner_name || "— external —"}</option>
                    {users.map((u) => <option key={u.id} value={u.id}>
                      {u.full_name}</option>)}
                  </select></td>
                <td style={{ padding: 2 }}>
                  <input type="date" value={a.due_date || ""}
                    disabled={!canManage}
                    onChange={(e) => setA(i, "due_date", e.target.value)}
                    style={{ ...sel, width: "100%" }} /></td>
                <td style={{ padding: 2 }}>
                  <select value={a.status || "OPEN"} disabled={!canManage}
                    onChange={(e) => setA(i, "status", e.target.value)}
                    style={{ ...sel, width: "100%" }}>
                    {Object.entries(AI_STATUS).map(([k, v]) =>
                      <option key={k} value={k}>{v}</option>)}
                  </select></td>
                <td style={{ padding: 2, textAlign: "center" }}>
                  {canManage && <button onClick={() => setActions((as) =>
                    as.filter((_, j) => j !== i))} style={{ border: "none",
                    background: "none", cursor: "pointer",
                    color: "var(--muted)" }}>×</button>}</td>
              </tr>
            ))}
            {!actions.length && <tr><td style={td} colSpan={5}>
              No follow-ups.</td></tr>}
          </tbody>
        </table>
        {canManage && (
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button style={{ ...ghostButton, padding: "4px 12px" }}
              onClick={() => setActions((as) => [...as,
                { description: "", status: "OPEN" }])}>+ Add follow-up</button>
            <Btn variant="primary" disabled={busy}
              onClick={saveActions}>Save follow-ups</Btn>
          </div>)}
      </div>
    </div>
  );
}

function NewMeeting({ me, onDone, onCancel }) {
  const [sites, setSites] = useState([]);
  const [projects, setProjects] = useState([]);
  const [siteId, setSiteId] = useState("");
  const [f, setF] = useState({
    meeting_type: "PROJECT", title: "", project_id: "",
    scheduled_at: "", duration_minutes: 60, location_kind: "OFFICE",
    location_note: "", cadence: "ONE_OFF", org_name: "", org_contact: "",
    agenda: "" });
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  useEffect(() => { api("/sites").then((r) =>
    setSites(Array.isArray(r) ? r : (r.results || []))).catch(() => {}); }, []);
  useEffect(() => {
    if (!siteId) { setProjects([]); return; }
    api(`/sites/${siteId}/projects`).then((r) =>
      setProjects(Array.isArray(r) ? r : (r.results || []))).catch(() => {});
  }, [siteId]);

  const isProject = f.meeting_type === "PROJECT";
  const isSite = f.meeting_type === "SITE";
  const isProspect = f.meeting_type === "PROSPECT";

  async function save() {
    setError(null);
    if (!f.title.trim()) { setError("Give the meeting a title."); return; }
    if (!f.scheduled_at) { setError("Set the date and time."); return; }
    setSaving(true);
    try {
      const body = { ...f };
      if (!isProject) body.project_id = null;
      if (isProject || isSite) body.site_id = siteId || null;
      const m = await api("/meetings", { method: "POST", body });
      onDone(m);
    } catch (e) { setError(e.message); }
    setSaving(false);
  }

  return (
    <div style={{ ...card, maxWidth: 760 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>New meeting</h2>
        <button onClick={onCancel} style={{ border: "none", background: "none",
          cursor: "pointer", color: "var(--muted)" }}>Cancel</button>
      </div>
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
        marginBottom: 8 }}>
        <F label="Type">
          <select value={f.meeting_type} onChange={set("meeting_type")}
            style={sel}>
            {Object.entries(TYPE_LABEL).map(([k, v]) =>
              <option key={k} value={k}>{v}</option>)}
          </select></F>
        <F label="Title"><input value={f.title} onChange={set("title")}
          placeholder="e.g. Weekly progress review"
          style={{ ...sel, width: 260 }} /></F>
        <F label="Cadence">
          <select value={f.cadence} onChange={set("cadence")} style={sel}>
            <option value="ONE_OFF">One-off</option>
            <option value="WEEKLY">Weekly</option>
            <option value="FORTNIGHTLY">Fortnightly</option>
            <option value="MONTHLY">Monthly</option>
          </select></F>
      </div>

      {(isProject || isSite) && (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
          marginBottom: 8 }}>
          <F label="Client / site">
            <select value={siteId} onChange={(e) => setSiteId(e.target.value)}
              style={sel}>
              <option value="">Select…</option>
              {sites.map((s) => <option key={s.id} value={s.id}>
                {s.client_name || s.name} ({s.code})</option>)}
            </select></F>
          {isProject && (
            <F label="Project">
              <select value={f.project_id} onChange={set("project_id")}
                style={sel} disabled={!siteId}>
                <option value="">Select project…</option>
                {projects.map((p) => <option key={p.id} value={p.id}>
                  {p.code} — {p.title}</option>)}
              </select></F>)}
        </div>)}

      {isProspect && (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
          marginBottom: 8 }}>
          <F label="Organisation"><input value={f.org_name}
            onChange={set("org_name")} placeholder="e.g. Blue Lagoon Resort"
            style={{ ...sel, width: 240 }} /></F>
          <F label="Contact"><input value={f.org_contact}
            onChange={set("org_contact")} placeholder="name / role"
            style={{ ...sel, width: 200 }} /></F>
        </div>)}

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
        marginBottom: 8 }}>
        <F label="Date & time"><input type="datetime-local"
          value={f.scheduled_at} onChange={set("scheduled_at")}
          style={sel} /></F>
        <F label="Duration (min)"><input type="number" value={f.duration_minutes}
          onChange={set("duration_minutes")} style={{ ...sel, width: 90 }} /></F>
        <F label="Location">
          <select value={f.location_kind} onChange={set("location_kind")}
            style={sel}>
            {Object.entries(LOC).map(([k, v]) =>
              <option key={k} value={k}>{v}</option>)}
          </select></F>
        <F label="Location note"><input value={f.location_note}
          onChange={set("location_note")} style={{ ...sel, width: 180 }} /></F>
      </div>

      <div style={{ marginBottom: 12 }}>
        <F label="Agenda (optional)"><textarea value={f.agenda}
          onChange={set("agenda")} rows={3}
          style={{ ...sel, width: "100%", fontFamily: "inherit",
            resize: "vertical" }} /></F>
      </div>

      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <Btn variant="primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Schedule meeting"}</Btn>
      </div>
    </div>
  );
}
