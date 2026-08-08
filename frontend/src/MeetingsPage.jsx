import { useEffect, useRef, useState } from "react";
import { api, apiUpload } from "./api.js";
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

// The company runs on Maldives time (fixed UTC+5, no DST). Instants come from
// the server in UTC; pin every render + every input to Maldives so a traveller's
// device or the server's clock can't shift what attendees see (owner 2026-08-08).
const MV = { timeZone: "Indian/Maldives" };
// datetime-local (Maldives wall-clock "YYYY-MM-DDTHH:mm") → UTC ISO to send.
const localToUtc = (s) => s
  ? new Date(`${s.length === 16 ? `${s}:00` : s}+05:00`).toISOString() : s;
// UTC ISO → datetime-local Maldives wall-clock, to prefill an edit field.
const utcToLocal = (iso) => iso
  ? new Date(new Date(iso).getTime() + 5 * 3600e3).toISOString().slice(0, 16)
  : "";
// The Maldives calendar-day parts of a UTC instant (for bucketing/highlighting).
const mvParts = (iso) => {
  const d = new Date(new Date(iso).getTime() + 5 * 3600e3);
  return { y: d.getUTCFullYear(), m: d.getUTCMonth(), d: d.getUTCDate() };
};

const dt = (s) => s ? new Date(s).toLocaleString("en-GB", { day: "2-digit",
  month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  ...MV }) : "—";
const dOnly = (s) => s ? new Date(s).toLocaleDateString("en-GB",
  { day: "2-digit", month: "short", year: "numeric", ...MV }) : "—";

// Warn if any internal attendee already has an overlapping meeting. Returns
// true to proceed (no conflict, or the user chose to book anyway); false to
// abort. A check failure never blocks scheduling.
async function confirmNoConflicts({ scheduled_at, duration_minutes,
  attendee_ids, exclude_id }) {
  if (!attendee_ids?.length) return true;
  try {
    const r = await api("/meetings/conflicts", { method: "POST",
      body: { scheduled_at, duration_minutes, attendee_ids, exclude_id } });
    if (!r.conflicts?.length) return true;
    const lines = r.conflicts.map((c) => `• ${c.name}: ${c.meetings
      .map((mm) => `${mm.title} (${dt(mm.scheduled_at)})`).join("; ")}`)
      .join("\n");
    return window.confirm(`Some attendees are already booked at that time:\n\n`
      + `${lines}\n\nSchedule anyway?`);
  } catch { return true; }
}

const sel = { padding: "6px 8px", border: "1px solid var(--line)",
  borderRadius: 6, fontSize: 13, background: "#fff" };
// Full-width field + section styles for the New-meeting form grid.
const field = { padding: "9px 11px", border: "1px solid var(--line)",
  borderRadius: 8, fontSize: 13.5, background: "#fff", width: "100%",
  boxSizing: "border-box", fontFamily: "inherit" };
const secTitle = { fontSize: 11, fontWeight: 700, letterSpacing: 0.6,
  textTransform: "uppercase", color: "var(--navy)", margin: "20px 0 12px",
  paddingBottom: 5, borderBottom: "1px solid var(--line)" };
const grid2 = { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 };
const spanAll = { gridColumn: "1 / -1" };
// Consistent card heading for the meeting-detail sections.
const cardH = { margin: "0 0 10px", fontSize: 14.5, fontWeight: 700,
  color: "var(--navy)" };
const fmtSize = (b) => !b ? "" : b < 1048576
  ? `${Math.round(b / 1024)} KB` : `${(b / 1048576).toFixed(1)} MB`;

// Module-scope so it's a stable component type — defining it inside a form
// component remounts inputs on every render and steals focus each keystroke.
function F({ label, children }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 3,
      fontSize: 12, color: "var(--muted)" }}>{label}{children}</label>);
}

// A month grid of meetings; click a meeting to open it.
// A soft [background, text] pair per meeting type, so the calendar reads at a
// glance instead of every chip being the same colour.
const TYPE_CHIP = {
  PROJECT: ["#e7f0fb", "#1c4e80"],
  PROSPECT: ["#e6f4ea", "#137333"],
  SITE: ["#fdf3e0", "#8a5a00"],
  OTHER: ["#eceff2", "#41505e"],
};
const navBtn = { width: 30, height: 30, borderRadius: 8, cursor: "pointer",
  border: "1px solid var(--line)", background: "#fff", color: "var(--navy)",
  fontSize: 16, lineHeight: 1, display: "flex", alignItems: "center",
  justifyContent: "center" };

function MonthCalendar({ meetings, onOpen }) {
  const now = new Date();
  const [cur, setCur] = useState({ y: now.getFullYear(), m: now.getMonth() });
  const first = new Date(cur.y, cur.m, 1);
  const startDow = (first.getDay() + 6) % 7;            // Monday-first
  const days = new Date(cur.y, cur.m + 1, 0).getDate();
  const byDay = {};
  meetings.forEach((mm) => {
    const p = mvParts(mm.scheduled_at);           // bucket by Maldives day
    if (p.y === cur.y && p.m === cur.m)
      (byDay[p.d] = byDay[p.d] || []).push(mm);
  });
  Object.values(byDay).forEach((list) =>
    list.sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at)));
  const cells = [];
  for (let i = 0; i < startDow; i++) cells.push(null);
  for (let d = 1; d <= days; d++) cells.push(d);
  const shift = (n) => setCur((c) => {
    const d = new Date(c.y, c.m + n, 1);
    return { y: d.getFullYear(), m: d.getMonth() };
  });
  const tp = mvParts(now.toISOString());
  const isToday = (d) => tp.y === cur.y && tp.m === cur.m && tp.d === d;

  return (
    <div style={{ ...card, padding: "18px 20px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
        marginBottom: 14 }}>
        <button style={navBtn} title="Previous month"
          onClick={() => shift(-1)}>‹</button>
        <button style={navBtn} title="Next month"
          onClick={() => shift(1)}>›</button>
        <b style={{ fontSize: 18, color: "var(--navy)", marginLeft: 6 }}>
          {first.toLocaleDateString("en-GB", { month: "long",
            year: "numeric" })}</b>
        <button style={{ ...ghostBtn, marginLeft: "auto", padding: "6px 14px" }}
          onClick={() => setCur({ y: now.getFullYear(),
            m: now.getMonth() })}>Today</button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)",
        gap: 6 }}>
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d, i) => (
          <div key={d} style={{ fontSize: 11, fontWeight: 700,
            letterSpacing: 0.5, color: i > 4 ? "var(--muted)" : "var(--navy)",
            textAlign: "center", padding: "2px 0 6px",
            textTransform: "uppercase" }}>{d}</div>))}
        {cells.map((d, i) => {
          const weekend = i % 7 > 4;
          const today = d && isToday(d);
          const list = (d && byDay[d]) || [];
          return (
            <div key={i} style={{ minHeight: 104, borderRadius: 10,
              padding: 5, border: today ? "1.5px solid var(--sky)"
                : "1px solid var(--line)",
              background: !d ? "transparent"
                : today ? "var(--sky-soft, #eef6fd)"
                : weekend ? "#fafbfc" : "#fff",
              display: "flex", flexDirection: "column", gap: 2 }}>
              {d && (
                <div style={{ display: "flex", justifyContent: "flex-end",
                  marginBottom: 1 }}>
                  <span style={{ fontSize: 11.5, fontWeight: today ? 700 : 500,
                    minWidth: 20, height: 20, borderRadius: 10,
                    display: "inline-flex", alignItems: "center",
                    justifyContent: "center", padding: "0 5px",
                    color: today ? "#fff" : "var(--muted)",
                    background: today ? "var(--sky)" : "transparent" }}>
                    {d}</span>
                </div>)}
              {list.slice(0, 3).map((mm) => {
                const cancelled = mm.status === "CANCELLED";
                const [bg, fg] = TYPE_CHIP[mm.meeting_type] || TYPE_CHIP.OTHER;
                return (
                  <div key={mm.id} onClick={() => onOpen(mm.id)}
                    title={`${mm.title} · ${TYPE_LABEL[mm.meeting_type]}`}
                    style={{ cursor: "pointer", fontSize: 10.5,
                      padding: "2px 6px", borderRadius: 5,
                      whiteSpace: "nowrap", overflow: "hidden",
                      textOverflow: "ellipsis",
                      borderLeft: `3px solid ${cancelled ? "#b6bcc2" : fg}`,
                      textDecoration: cancelled ? "line-through" : "none",
                      background: cancelled ? "#f0f1f3" : bg,
                      color: cancelled ? "var(--muted)" : fg }}>
                    <b>{new Date(mm.scheduled_at).toLocaleTimeString("en-GB",
                      { hour: "2-digit", minute: "2-digit", ...MV })}</b>{" "}
                    {mm.title}</div>
                );
              })}
              {list.length > 3 && (
                <div onClick={() => onOpen(list[3].id)}
                  style={{ fontSize: 10, color: "var(--navy)", cursor: "pointer",
                    padding: "0 6px", fontWeight: 600 }}>
                  +{list.length - 3} more</div>)}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const RSVP_PILL = { ACCEPTED: ["✓ Accepted", "#137333", "#e6f4ea"],
  DECLINED: ["✕ Declined", "#a50e0e", "#fce8e6"],
  TENTATIVE: ["? Tentative", "#8a6d00", "#fef7e0"] };

// Add/remove attendees — internal Planet users + external guests (with email
// so they can be sent the invite + minutes). Guests can be pulled from / saved
// to a reusable contact book.
function AttendeeEditor({ attendees, setAttendees, users, editable }) {
  const [pick, setPick] = useState("");
  const [g, setG] = useState({ name: "", email: "", org: "", role: "" });
  const [saveContact, setSaveContact] = useState(false);
  const [cq, setCq] = useState("");
  const [contacts, setContacts] = useState([]);
  const timer = useRef(null);

  const searchContacts = (q) => {
    setCq(q);
    clearTimeout(timer.current);
    if (q.trim().length < 2) { setContacts([]); return; }
    timer.current = setTimeout(() => {
      api(`/meeting-contacts?q=${encodeURIComponent(q.trim())}`)
        .then((r) => setContacts(r.contacts || [])).catch(() => {});
    }, 250);
  };
  const addUser = () => {
    const u = users.find((x) => String(x.id) === pick);
    if (u && !attendees.some((a) => a.user_id === u.id))
      setAttendees([...attendees,
        { user_id: u.id, name: u.full_name, email: u.email,
          is_external: false }]);
    setPick("");
  };
  const addGuest = () => {
    if (!g.name.trim()) return;
    setAttendees([...attendees, { ...g, is_external: true }]);
    if (saveContact && g.email.trim())
      api("/meeting-contacts", { method: "POST", body: g }).catch(() => {});
    setG({ name: "", email: "", org: "", role: "" });
    setSaveContact(false);
  };
  const addContact = (c) => {
    const dup = attendees.some((a) => (a.email || "").toLowerCase()
      === (c.email || "").toLowerCase() && c.email);
    if (!dup) setAttendees([...attendees, { name: c.name, email: c.email,
      org: c.org, role: c.role, is_external: true }]);
    setCq(""); setContacts([]);
  };
  return (
    <div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap",
        marginBottom: editable ? 8 : 0 }}>
        {attendees.length === 0 && <span style={{ fontSize: 12,
          color: "var(--muted)" }}>No attendees yet.</span>}
        {attendees.map((a, i) => {
          const pill = RSVP_PILL[a.rsvp];
          const noEmail = a.is_external && !((a.email || "").trim());
          return (
            <span key={i} style={{ fontSize: 12.5, padding: "3px 8px",
              borderRadius: 999, display: "inline-flex", gap: 6,
              alignItems: "center", background: a.is_external
                ? "var(--amber-bg)" : "var(--sky-soft)" }}>
              {a.name}{a.org ? ` · ${a.org}` : ""}
              {a.email ? <span style={{ color: "var(--muted)" }}>
                &lt;{a.email}&gt;</span>
                : noEmail ? <span title="No email — can't be invited"
                  style={{ color: "#a50e0e" }}>⚠ no email</span> : null}
              {pill && <span style={{ fontSize: 10.5, padding: "0 6px",
                borderRadius: 999, color: pill[1], background: pill[2] }}>
                {pill[0]}</span>}
              {editable && <button onClick={() =>
                setAttendees(attendees.filter((_, j) => j !== i))}
                style={{ border: "none", background: "none", cursor: "pointer",
                  color: "var(--muted)", padding: 0 }}>×</button>}
            </span>
          );
        })}
      </div>
      {editable && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
            alignItems: "center" }}>
            <select value={pick} onChange={(e) => setPick(e.target.value)}
              style={{ ...sel, maxWidth: 180 }}>
              <option value="">Add our team…</option>
              {users.filter((u) => !attendees.some((a) => a.user_id === u.id))
                .map((u) => <option key={u.id} value={u.id}>
                  {u.full_name}</option>)}
            </select>
            <button style={ghostBtn} disabled={!pick}
              onClick={addUser}>Add</button>
            <span style={{ color: "var(--muted)", fontSize: 12 }}>·</span>
            <div style={{ position: "relative" }}>
              <input value={cq} onChange={(e) => searchContacts(e.target.value)}
                placeholder="Search saved contacts…"
                style={{ ...sel, width: 170 }} />
              {contacts.length > 0 && (
                <div style={{ position: "absolute", top: "100%", left: 0,
                  zIndex: 30, background: "#fff", border: "1px solid var(--line)",
                  borderRadius: 6, minWidth: 200, maxHeight: 200,
                  overflowY: "auto", boxShadow: "0 8px 24px rgba(0,0,0,.12)" }}>
                  {contacts.map((c) => (
                    <div key={c.id} onMouseDown={() => addContact(c)}
                      style={{ padding: "6px 10px", cursor: "pointer",
                        fontSize: 12.5, borderBottom: "1px solid #eef2f5" }}>
                      <b>{c.name}</b>{c.org ? ` · ${c.org}` : ""}
                      {c.email ? <span style={{ color: "var(--muted)" }}>
                        {" "}&lt;{c.email}&gt;</span> : ""}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
            alignItems: "center" }}>
            <input value={g.name} onChange={(e) => setG({ ...g,
              name: e.target.value })} placeholder="Guest name"
              style={{ ...sel, width: 130 }} />
            <input value={g.email} type="email" onChange={(e) => setG({ ...g,
              email: e.target.value })} placeholder="guest@email"
              style={{ ...sel, width: 160 }} />
            <input value={g.org} onChange={(e) => setG({ ...g,
              org: e.target.value })} placeholder="Organisation"
              style={{ ...sel, width: 120 }} />
            <button style={ghostBtn} disabled={!g.name.trim()}
              onClick={addGuest}>Add guest</button>
            <label style={{ fontSize: 12, color: "var(--muted)",
              display: "flex", alignItems: "center", gap: 4 }}>
              <input type="checkbox" checked={saveContact}
                onChange={(e) => setSaveContact(e.target.checked)} />
              save to contacts</label>
          </div>
        </div>)}
    </div>
  );
}

const ghostBtn = { padding: "4px 10px", border: "1px solid var(--line)",
  borderRadius: 6, background: "#fff", cursor: "pointer", fontSize: 12.5,
  color: "var(--navy)" };

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
  const [view, setView] = useState("calendar");
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
        <div style={{ display: "flex", gap: 4 }}>
          {[["list", "List"], ["calendar", "Calendar"]].map(([k, l]) => (
            <button key={k} onClick={() => setView(k)}
              style={{ ...ghostBtn, background: view === k
                ? "var(--navy)" : "#fff",
                color: view === k ? "#fff" : "var(--navy)" }}>{l}</button>))}
        </div>
        {data?.can_create && <Btn variant="primary"
          onClick={() => setCreating(true)}
          style={{ marginLeft: "auto" }}>+ New meeting</Btn>}
      </div>
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      {view === "calendar" && data && (
        <MonthCalendar meetings={data.meetings} onOpen={setSelected} />)}
      {view === "list" && (
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
      </div>)}
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
  const [att, setAtt] = useState([]);
  const [users, setUsers] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [resched, setResched] = useState(false);
  const [newDt, setNewDt] = useState("");
  const [linkVal, setLinkVal] = useState("");

  const load = () => api(`/meetings/${id}`).then((d) => {
    setM(d); setMinutes(d.minutes || ""); setNotes(d.notes || "");
    setLinkVal(d.meeting_link || "");
    setActions(d.action_items.map((a) => ({ ...a })));
    setAtt(d.attendees.map((a) => ({ user_id: a.user_id, name: a.name,
      email: a.email, org: a.org, role: a.role, is_external: a.is_external,
      rsvp: a.rsvp })));
  }).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [id]);
  useEffect(() => { api("/directory").then((r) =>
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
  const saveAtt = () => run(async () => {
    const d = await api(`/meetings/${id}`, { method: "PATCH",
      body: { attendees: att } });
    setM(d);
  }, "Attendees updated — new invitees notified");
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
  const cancelMeeting = () => {
    if (!window.confirm("Cancel this meeting? It stays on record as "
      + "cancelled.")) return;
    run(async () => { const d = await api(`/meetings/${id}`,
      { method: "DELETE" }); setM(d); }, "Meeting cancelled");
  };
  const deleteMeeting = () => {
    if (!window.confirm("Delete this meeting permanently? This removes it and "
      + "its minutes and follow-ups — it can't be undone.")) return;
    run(async () => { await api(`/meetings/${id}?hard=1`,
      { method: "DELETE" }); onBack(); });
  };
  const doReschedule = () => {
    if (!newDt) return;
    const scheduled_at = localToUtc(newDt);
    const attendee_ids = (m.attendees || []).filter((a) => a.user_id)
      .map((a) => a.user_id);
    run(async () => {
      if (!(await confirmNoConflicts({ scheduled_at,
        duration_minutes: m.duration_minutes, attendee_ids, exclude_id: id })))
        return;
      const d = await api(`/meetings/${id}/reschedule`, { method: "POST",
        body: { scheduled_at } });
      setM(d); setResched(false); setNewDt("");
    }, "Rescheduled — participants notified");
  };
  const saveLink = () => run(async () => {
    const d = await api(`/meetings/${id}`, { method: "PATCH",
      body: { meeting_link: linkVal.trim() } });
    setM(d);
  }, "Meeting link saved");
  const uploadAudio = (file) => {
    if (!file) return;
    run(async () => {
      const fd = new FormData(); fd.append("file", file);
      const d = await apiUpload(`/meetings/${id}/audio`, fd);
      setM(d);
    }, "Recording uploaded");
  };
  const removeAudio = (aid) => {
    if (!window.confirm("Remove this recording?")) return;
    run(async () => { await api(`/meetings/${id}/audio/${aid}`,
      { method: "DELETE" }); load(); });
  };
  const sendInvite = () => run(async () => {
    const d = await api(`/meetings/${id}/send-invite`, { method: "POST" });
    setM(d);
    const skip = (d.skipped || []).length;
    setMsg(`Invitation emailed to ${d.sent} recipient(s).`
      + (skip ? ` ${skip} attendee(s) have no email.` : "")
      + (d.email_configured ? "" : " (Dev: email isn't configured — logged only.)"));
  });
  const sendMinutes = () => run(async () => {
    const d = await api(`/meetings/${id}/send-minutes`, { method: "POST" });
    setM(d); setMsg(`Minutes emailed to ${d.sent} recipient(s).`);
  });
  const uploadFile = (file) => {
    if (!file) return;
    run(async () => {
      const fd = new FormData(); fd.append("file", file);
      const d = await apiUpload(`/meetings/${id}/files`, fd);
      setM(d);
    }, "Pre-read attached");
  };
  const removeFile = (fid) => run(async () => {
    await api(`/meetings/${id}/files/${fid}`, { method: "DELETE" }); load();
  });

  if (!m) return <div style={card}>{error || "Loading…"}</div>;
  const canManage = m.can_manage;
  const setA = (i, k, v) => setActions((as) =>
    as.map((a, j) => j === i ? { ...a, [k]: v } : a));

  return (
    <div style={{ maxWidth: 900 }}>
      <button style={{ ...ghostButton, marginBottom: 10 }}
        onClick={onBack}>← All meetings</button>
      <div style={{ ...card }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center",
          flexWrap: "wrap" }}>
          <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 20 }}>
            {m.title}</h2>
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
        {m.meeting_link && (
          <div style={{ marginTop: 6 }}>
            <a href={m.meeting_link} target="_blank" rel="noreferrer"
              style={{ fontSize: 13, color: "var(--sky)", fontWeight: 600,
                textDecoration: "none" }}>🔗 Join online meeting</a>
          </div>)}
        {canManage && (
          <div style={{ display: "flex", gap: 8, marginTop: 6,
            alignItems: "center", flexWrap: "wrap" }}>
            <input type="url" value={linkVal} placeholder="Online meeting link (https://…)"
              onChange={(e) => setLinkVal(e.target.value)}
              style={{ ...sel, width: 300 }} />
            <Btn variant="ghost" disabled={busy || linkVal === (m.meeting_link || "")}
              onClick={saveLink}>Save link</Btn>
          </div>)}
        {msg && <p style={{ color: "var(--green-fg)", fontSize: 13 }}>{msg}</p>}
        {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
        {canManage && (
          <div style={{ display: "flex", gap: 8, marginTop: 8,
            flexWrap: "wrap" }}>
            {m.status === "SCHEDULED" && (
              <Btn variant="secondary" disabled={busy} onClick={close}>
                Mark held{m.cadence !== "ONE_OFF"
                  ? " & schedule next" : ""}</Btn>)}
            {["SCHEDULED", "POSTPONED"].includes(m.status) && (
              <Btn variant="secondary" disabled={busy}
                onClick={() => setResched((v) => !v)}>Reschedule</Btn>)}
            {m.status === "SCHEDULED" && (
              <Btn variant="ghost" disabled={busy} onClick={cancelMeeting}>
                Cancel meeting</Btn>)}
            <Btn variant="danger" disabled={busy} onClick={deleteMeeting}
              style={{ marginLeft: "auto" }}>Delete</Btn>
          </div>)}
        {canManage && resched && (
          <div style={{ display: "flex", gap: 8, marginTop: 8,
            alignItems: "center", flexWrap: "wrap" }}>
            <input type="datetime-local" value={newDt}
              onChange={(e) => setNewDt(e.target.value)} style={sel} />
            <Btn variant="primary" disabled={busy || !newDt}
              onClick={doReschedule}>Confirm new time</Btn>
            <span style={{ fontSize: 12, color: "var(--muted)" }}>
              Participants are notified of the change.</span>
          </div>)}
      </div>

      <div style={{ ...card, marginTop: 14 }}>
        <h3 style={cardH}>Attendees</h3>
        <AttendeeEditor attendees={att} setAttendees={setAtt} users={users}
          editable={canManage} />
        {canManage && (
          <div style={{ display: "flex", gap: 8, marginTop: 8,
            alignItems: "center", flexWrap: "wrap" }}>
            <Btn variant="secondary" disabled={busy}
              onClick={saveAtt}>Save attendees</Btn>
            <Btn variant="primary" disabled={busy || !m.email_recipients}
              onClick={sendInvite}
              title={m.email_recipients
                ? `Email the invite + calendar file to ${m.email_recipients} `
                  + "attendee(s) with an email"
                : "No attendee has an email yet"}>
              {m.invite_sent_at ? "✉ Resend invite" : "✉ Send invite"}</Btn>
            <span style={{ fontSize: 12, color: "var(--muted)" }}>
              {m.email_recipients
                ? `${m.email_recipients} with email`
                : "add emails to invite by email"}
              {m.invite_sent_at ? ` · last sent ${dt(m.invite_sent_at)}` : ""}
            </span>
            {m.email_configured === false && (
              <span style={{ fontSize: 11.5, color: "#8a6d00" }}>
                Email isn't configured on the server yet — sends are logged
                only.</span>)}
          </div>)}
        {!canManage && att.some((a) => a.rsvp && a.rsvp !== "NONE") && (
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
            RSVP shown on each attendee above.</div>)}
      </div>

      <div style={{ ...card, marginTop: 14 }}>
        <h3 style={cardH}>Pre-read files</h3>
        <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>
          Attached to the invitation email so attendees get the agenda pack up
          front.</div>
        {!(m.files || []).length && (
          <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
            No files attached.</div>)}
        {(m.files || []).map((f) => (
          <div key={f.id} style={{ display: "flex", alignItems: "center",
            gap: 10, padding: "5px 0", borderBottom: "1px solid var(--line)",
            fontSize: 12.5 }}>
            <a href={f.url} target="_blank" rel="noreferrer"
              style={{ color: "var(--sky)", textDecoration: "none" }}>
              📎 {f.file_name}</a>
            <span style={{ color: "var(--muted)", fontSize: 11 }}>
              {fmtSize(f.size_bytes)}</span>
            {canManage && (
              <button onClick={() => removeFile(f.id)} style={{ border: "none",
                background: "none", cursor: "pointer", color: "var(--red-fg)",
                fontSize: 12, marginLeft: "auto" }}>Remove</button>)}
          </div>
        ))}
        {canManage && (
          <label style={{ display: "inline-block", marginTop: 8,
            ...ghostButton, cursor: busy ? "default" : "pointer",
            fontSize: 12.5 }}>
            {busy ? "Uploading…" : "＋ Attach file"}
            <input type="file" style={{ display: "none" }} disabled={busy}
              onChange={(e) => { uploadFile(e.target.files[0]);
                e.target.value = ""; }} />
          </label>)}
      </div>

      {m.agenda && (
        <div style={{ ...card, marginTop: 14 }}>
          <h3 style={cardH}>Agenda</h3>
          <div style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{m.agenda}</div>
        </div>)}

      <div style={{ ...card, marginTop: 14 }}>
        <h3 style={cardH}>Audio recordings</h3>
        {!(m.recordings || []).length && (
          <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
            No recordings yet.</div>)}
        {(m.recordings || []).map((a) => (
          <div key={a.id} style={{ display: "flex", alignItems: "center",
            gap: 10, padding: "6px 0", borderBottom: "1px solid var(--line)",
            flexWrap: "wrap" }}>
            <audio controls preload="none"
              src={`/api/v1/meetings/${id}/audio/${a.id}`}
              style={{ height: 32, maxWidth: 260 }} />
            <div style={{ fontSize: 12.5 }}>
              <div>{a.file_name}{a.note ? ` — ${a.note}` : ""}</div>
              <div style={{ color: "var(--muted)", fontSize: 11 }}>
                {fmtSize(a.size_bytes)} · {a.uploaded_by} · {dt(a.uploaded_at)}
              </div>
            </div>
            <a href={`/api/v1/meetings/${id}/audio/${a.id}`} download
              style={{ fontSize: 12, color: "var(--sky)",
                textDecoration: "none" }}>⬇</a>
            {canManage && (
              <button onClick={() => removeAudio(a.id)} style={{ border: "none",
                background: "none", cursor: "pointer", color: "var(--red-fg)",
                fontSize: 12 }}>Remove</button>)}
          </div>
        ))}
        {canManage && (
          <label style={{ display: "inline-block", marginTop: 8,
            ...ghostButton, cursor: busy ? "default" : "pointer",
            fontSize: 12.5 }}>
            {busy ? "Uploading…" : "＋ Upload audio"}
            <input type="file" accept="audio/*" style={{ display: "none" }}
              disabled={busy}
              onChange={(e) => { uploadAudio(e.target.files[0]);
                e.target.value = ""; }} />
          </label>)}
      </div>

      <div style={{ ...card, marginTop: 14 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <h3 style={cardH}>Minutes</h3>
          <Chip tone={m.minutes_status === "FINAL" ? "ok" : "info"}>
            {m.minutes_status === "FINAL" ? "final"
              : m.minutes_status === "DRAFT" ? "draft" : "none"}</Chip>
          <a href={`/api/v1/meetings/${id}/minutes.pdf`} target="_blank"
            rel="noreferrer" style={{ marginLeft: "auto", fontSize: 12.5,
              color: "var(--sky)", textDecoration: "none" }}>
            ⬇ Minutes PDF</a>
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
          <div style={{ display: "flex", gap: 8, marginTop: 6,
            alignItems: "center", flexWrap: "wrap" }}>
            <Btn variant="secondary" disabled={busy}
              onClick={() => saveMinutes()}>Save draft</Btn>
            <Btn variant="primary" disabled={busy}
              onClick={() => saveMinutes("FINAL")}>Finalise</Btn>
            <Btn variant="secondary"
              disabled={busy || m.minutes_status !== "FINAL"
                || !m.email_recipients}
              onClick={sendMinutes}
              title={m.minutes_status !== "FINAL"
                ? "Finalise the minutes first"
                : !m.email_recipients ? "No attendee has an email"
                : "Email the minutes PDF to attendees"}>
              {m.minutes_sent_at ? "✉ Resend minutes" : "✉ Email minutes"}</Btn>
            {m.minutes_sent_at && (
              <span style={{ fontSize: 12, color: "var(--muted)" }}>
                last sent {dt(m.minutes_sent_at)}</span>)}
          </div>)}
      </div>

      <div style={{ ...card, marginTop: 14 }}>
        <h3 style={cardH}>Follow-ups</h3>
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
    location_note: "", meeting_link: "", cadence: "ONE_OFF", org_name: "",
    org_contact: "", agenda: "" });
  const [users, setUsers] = useState([]);
  const [attendees, setAttendees] = useState([]);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  useEffect(() => { api("/sites").then((r) =>
    setSites(Array.isArray(r) ? r : (r.results || []))).catch(() => {}); }, []);
  useEffect(() => { api("/directory").then((r) =>
    setUsers(Array.isArray(r) ? r : (r.results || []))).catch(() => {}); }, []);
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
    const scheduled_at = localToUtc(f.scheduled_at);
    const attendee_ids = attendees.filter((a) => a.user_id)
      .map((a) => a.user_id);
    if (!(await confirmNoConflicts({ scheduled_at,
      duration_minutes: f.duration_minutes, attendee_ids }))) return;
    setSaving(true);
    try {
      const body = { ...f, attendees, scheduled_at };
      if (!isProject) body.project_id = null;
      if (isProject || isSite) body.site_id = siteId || null;
      const m = await api("/meetings", { method: "POST", body });
      onDone(m);
    } catch (e) { setError(e.message); }
    setSaving(false);
  }

  return (
    <div style={{ ...card, maxWidth: 900, padding: "22px 26px" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "baseline", gap: 12 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 20, color: "var(--navy)" }}>
            New meeting</h2>
          <p style={{ margin: "2px 0 0", fontSize: 12.5,
            color: "var(--muted)" }}>
            Schedule it, add attendees, and issue the invite once it's saved.</p>
        </div>
        <button onClick={onCancel} style={{ border: "1px solid var(--line)",
          background: "#fff", borderRadius: 8, padding: "6px 14px",
          cursor: "pointer", color: "var(--navy)", fontSize: 13 }}>Cancel</button>
      </div>
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13,
        background: "var(--red-bg)", padding: "8px 12px", borderRadius: 8,
        margin: "12px 0 0" }}>{error}</p>}

      <div style={secTitle}>Details</div>
      <div style={grid2}>
        <F label="Type">
          <select value={f.meeting_type} onChange={set("meeting_type")}
            style={field}>
            {Object.entries(TYPE_LABEL).map(([k, v]) =>
              <option key={k} value={k}>{v}</option>)}
          </select></F>
        <F label="Cadence">
          <select value={f.cadence} onChange={set("cadence")} style={field}>
            <option value="ONE_OFF">One-off</option>
            <option value="WEEKLY">Weekly</option>
            <option value="FORTNIGHTLY">Fortnightly</option>
            <option value="MONTHLY">Monthly</option>
          </select></F>
        <div style={spanAll}>
          <F label="Title"><input value={f.title} onChange={set("title")}
            placeholder="e.g. Weekly progress review" style={field} /></F>
        </div>
        {(isProject || isSite) && (
          <F label="Client / site">
            <select value={siteId} onChange={(e) => setSiteId(e.target.value)}
              style={field}>
              <option value="">Select…</option>
              {sites.map((s) => <option key={s.id} value={s.id}>
                {s.client_name || s.name} ({s.code})</option>)}
            </select></F>)}
        {isProject && (
          <F label="Project">
            <select value={f.project_id} onChange={set("project_id")}
              style={field} disabled={!siteId}>
              <option value="">Select project…</option>
              {projects.map((p) => <option key={p.id} value={p.id}>
                {p.code} — {p.title}</option>)}
            </select></F>)}
        {isProspect && (<>
          <F label="Organisation"><input value={f.org_name}
            onChange={set("org_name")} placeholder="e.g. Blue Lagoon Resort"
            style={field} /></F>
          <F label="Contact"><input value={f.org_contact}
            onChange={set("org_contact")} placeholder="name / role"
            style={field} /></F>
        </>)}
      </div>

      <div style={secTitle}>When &amp; where</div>
      <div style={grid2}>
        <F label="Date &amp; time"><input type="datetime-local"
          value={f.scheduled_at} onChange={set("scheduled_at")}
          style={field} /></F>
        <F label="Duration (min)"><input type="number"
          value={f.duration_minutes} onChange={set("duration_minutes")}
          style={field} /></F>
        <F label="Location">
          <select value={f.location_kind} onChange={set("location_kind")}
            style={field}>
            {Object.entries(LOC).map(([k, v]) =>
              <option key={k} value={k}>{v}</option>)}
          </select></F>
        <F label="Location note"><input value={f.location_note}
          onChange={set("location_note")} placeholder="room / address"
          style={field} /></F>
        {f.location_kind === "ONLINE" && (
          <div style={spanAll}>
            <F label="Meeting link"><input value={f.meeting_link} type="url"
              placeholder="https://…" onChange={set("meeting_link")}
              style={field} /></F>
          </div>)}
      </div>

      <div style={secTitle}>Attendees</div>
      <div style={{ fontSize: 12, color: "var(--muted)", margin: "-4px 0 8px" }}>
        Our team are notified in-app; external guests with an email can be sent
        the invite after you save.</div>
      <div style={{ border: "1px solid var(--line)", borderRadius: 10,
        padding: 14, background: "var(--sky-soft, #f5f8fb)" }}>
        <AttendeeEditor attendees={attendees} setAttendees={setAttendees}
          users={users} editable />
      </div>

      <div style={secTitle}>Agenda</div>
      <textarea value={f.agenda} onChange={set("agenda")} rows={4}
        placeholder="Optional — one line per item; carries into the invite."
        style={{ ...field, resize: "vertical" }} />

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 10,
        marginTop: 20, paddingTop: 16, borderTop: "1px solid var(--line)" }}>
        <button onClick={onCancel} style={{ border: "1px solid var(--line)",
          background: "#fff", borderRadius: 8, padding: "9px 18px",
          cursor: "pointer", color: "var(--navy)", fontSize: 13.5 }}>Cancel</button>
        <Btn variant="primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Schedule meeting"}</Btn>
      </div>
    </div>
  );
}
