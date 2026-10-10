import { useCallback, useEffect, useState } from "react";
import { api, apiDownload, apiUpload } from "./api.js";
import { BTN, buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";
import Discussion from "./Discussion.jsx";

// Worker health log (SOP-HR-04, owner 2026-10-10). Sites are on islands with
// limited or no medical facilities, so delay can cost a life. Every complaint
// is a case, every action on it a dated step, and the referral ladder is
// computed on the case so the Health Focal Point is TOLD what is due rather
// than left to remember the SOP. Repeat sickness and clusters of the same
// complaint are counted by the server, never noticed by luck.

export const COMPLAINTS = [
  ["UNKNOWN", "Not yet recorded"],
  ["FEVER", "Fever / flu-like"],
  ["DENGUE", "Suspected dengue"],
  ["RESPIRATORY", "Cough / respiratory"],
  ["STOMACH", "Diarrhoea / vomiting / stomach"],
  ["SKIN", "Skin / rash"],
  ["HEAT", "Heat illness"],
  ["INJURY", "Injury"],
  ["PAIN", "Pain (back, joint, tooth, head)"],
  ["OTHER", "Other"],
];
const STEPS = [
  ["FIRST_AID", "First aid / OTC medicine on site"],
  ["RESTED", "Rested in camp / sick bay"],
  ["RECHECK", "Checked again (evening / next morning)"],
  ["DOCTOR", "Seen resort doctor / nearest health centre"],
  ["MALE", "Referred to Malé"],
  ["EVACUATED", "Emergency evacuation"],
  ["ADMITTED", "Admitted"],
  ["CLEARED", "Cleared by doctor to return"],
  ["FOLLOW_UP", "Follow-up check after return"],
  ["NOTE", "Note"],
];
const RED_FLAGS = [
  "Chest pain, breathlessness, fainting or collapse",
  "Unconscious, confused, fits, sudden weakness, slurred speech",
  "Fever with bleeding gums or nose, rash, severe stomach pain, black stools",
  "Vomiting blood, heavy bleeding, a serious injury",
  "Hot dry skin, confusion or collapse after work in the sun",
  "Any worker who says he feels very ill and is getting worse",
];
const CAN_RECORD = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "HO_HR", "DIRECTOR",
                    "ADMIN", "PA"];
const DUE_TONE = {
  3: { bg: "#fbeae8", fg: "#a3271b", border: "#e4b4ae" },
  2: { bg: "#fff7e0", fg: "#8a6d00", border: "#e0c66b" },
  1: { bg: "#eef4fb", fg: "#16527E", border: "#bcd3e8" },
};

function fmtDate(d) {
  if (!d) return "";
  const x = new Date(d);
  return Number.isNaN(x.getTime()) ? String(d)
    : x.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}
function fmtWhen(d) {
  if (!d) return "";
  const x = new Date(d);
  return x.toLocaleString("en-GB", { day: "2-digit", month: "short",
                                     hour: "2-digit", minute: "2-digit" });
}

function Stat({ value, label, alarm, onClick }) {
  return (
    <div onClick={onClick}
         style={{ padding: "12px 16px", background: "var(--paper)",
                  border: "1px solid var(--line)", borderRadius: 10,
                  minWidth: 118, cursor: onClick ? "pointer" : undefined }}>
      <div style={{ fontSize: 24, fontWeight: 700,
                    fontFamily: "var(--font-mono, monospace)",
                    color: alarm && value > 0 ? "#a3271b" : "var(--navy)" }}>
        {value}</div>
      <div style={{ fontSize: 12, color: "#5a6b78", marginTop: 2 }}>{label}</div>
    </div>
  );
}

export function DueChip({ level, text, small }) {
  if (!level || !text) return null;
  const t = DUE_TONE[level] || DUE_TONE[1];
  return (
    <span style={{ display: "inline-block", padding: small ? "1px 7px" : "3px 10px",
                   borderRadius: 999, fontSize: small ? 11 : 12.5,
                   fontWeight: 700, background: t.bg, color: t.fg,
                   border: `1px solid ${t.border}`, whiteSpace: "nowrap",
                   maxWidth: small ? 260 : undefined, overflow: "hidden",
                   textOverflow: "ellipsis" }}
          title={text}>
      {text}
    </span>
  );
}

export function RepeatChip({ n }) {
  if (!n) return null;
  return (
    <span title={`${n} sickness reports in the last 90 days — see him properly`}
          style={{ marginLeft: 6, fontSize: 10.5, fontWeight: 700,
                   color: "#a3271b", background: "#fbeae8", borderRadius: 999,
                   padding: "1px 7px", whiteSpace: "nowrap" }}>
      sick ×{n}</span>
  );
}

// ---- new complaint -------------------------------------------------------------

function NewCase({ me, sites, siteId, onClose, onSaved }) {
  const [site, setSite] = useState(siteId || (sites.length === 1 ? sites[0].id : ""));
  const [workers, setWorkers] = useState([]);
  const [q, setQ] = useState("");
  const [f, setF] = useState({ employee_id: "", complaint: "FEVER", symptoms: "",
                               started_on: "", temperature: "", red_flag: false,
                               reported_on: new Date().toISOString().slice(0, 10) });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (p) => setF((s) => ({ ...s, ...p }));

  useEffect(() => {
    if (!site) { setWorkers([]); return; }
    api(`/health/workers?site=${site}`).then(setWorkers).catch(() => setWorkers([]));
  }, [site]);

  const shown = workers.filter((w) => !q
    || w.full_name.toLowerCase().includes(q.toLowerCase())
    || w.emp_no.toLowerCase().includes(q.toLowerCase())).slice(0, 60);
  const chosen = workers.find((w) => String(w.id) === String(f.employee_id));

  async function save() {
    if (!site || !f.employee_id) { setError("Choose the site and the worker."); return; }
    setBusy(true); setError(null);
    try {
      const d = await api("/health/cases", { method: "POST",
        body: { ...f, site_id: +site, employee_id: +f.employee_id } });
      onSaved(d);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  return (
    <section style={{ ...card, marginBottom: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <h3 style={{ margin: 0, color: "var(--navy)" }}>Record a health complaint</h3>
        <button onClick={onClose} style={ghostButton}>Close</button>
      </div>
      <p style={{ fontSize: 12.5, color: "#5a6b78", margin: "4px 0 12px" }}>
        Every complaint is taken seriously; only a doctor decides it is not. A man
        who was present this morning can still be recorded here.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        {!siteId && sites.length > 1 && (
          <label style={{ fontSize: 13 }}>Site
            <select value={site} onChange={(e) => { setSite(e.target.value); set({ employee_id: "" }); }}
                    style={inputStyle}>
              <option value="">— choose —</option>
              {sites.map((s) => <option key={s.id} value={s.id}>{s.code} — {s.name}</option>)}
            </select>
          </label>
        )}
        <label style={{ fontSize: 13 }}>Worker
          <input value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="Search by name or number" style={inputStyle} />
          <select value={f.employee_id} onChange={(e) => set({ employee_id: e.target.value })}
                  size={6} style={{ ...inputStyle, marginTop: 4, height: "auto" }}>
            {shown.map((w) => (
              <option key={w.id} value={w.id}>
                {w.emp_no} — {w.full_name}
                {w.repeat_cases ? `  (sick ×${w.repeat_cases})` : ""}
                {w.has_open_case ? "  · case open" : ""}
              </option>
            ))}
          </select>
          {chosen?.has_open_case && (
            <div style={{ fontSize: 12, color: "#8a6d00", marginTop: 4 }}>
              He already has an open case — this report joins it.
            </div>
          )}
        </label>
        <label style={{ fontSize: 13 }}>Complaint
          <select value={f.complaint} onChange={(e) => set({ complaint: e.target.value })}
                  style={inputStyle}>
            {COMPLAINTS.filter(([k]) => k !== "UNKNOWN").map(([k, l]) =>
              <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Reported on
          <input type="date" value={f.reported_on}
                 onChange={(e) => set({ reported_on: e.target.value })} style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Started on (if earlier)
          <input type="date" value={f.started_on}
                 onChange={(e) => set({ started_on: e.target.value })} style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Temperature °C (if fever)
          <input value={f.temperature} inputMode="decimal" placeholder="e.g. 38.4"
                 onChange={(e) => set({ temperature: e.target.value })} style={inputStyle} />
        </label>
        <label style={{ fontSize: 13, gridColumn: "1 / -1" }}>Symptoms, in his words
          <textarea value={f.symptoms} rows={2}
                    onChange={(e) => set({ symptoms: e.target.value })}
                    style={{ ...inputStyle, resize: "vertical" }} />
        </label>
        <div style={{ gridColumn: "1 / -1", padding: "8px 12px", borderRadius: 8,
                      background: f.red_flag ? "#fbeae8" : "#fbf7ec",
                      border: `1px solid ${f.red_flag ? "#e4b4ae" : "#e6dcc0"}` }}>
          <label style={{ fontSize: 13.5, fontWeight: 700, color: "#a3271b",
                          display: "flex", gap: 8, alignItems: "center" }}>
            <input type="checkbox" checked={f.red_flag}
                   onChange={(e) => set({ red_flag: e.target.checked })} />
            Red-flag sign — evacuate now, day or night. No approval needed.
          </label>
          <ul style={{ margin: "6px 0 0", paddingLeft: 24, fontSize: 12, color: "#5a3a36" }}>
            {RED_FLAGS.map((r) => <li key={r}>{r}</li>)}
          </ul>
        </div>
      </div>
      {error && <p style={{ color: "#a3271b", fontSize: 13 }}>{error}</p>}
      <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Saving…" : "Record"}</button>
        <span style={{ fontSize: 12, color: "#5a6b78", alignSelf: "center" }}>
          Recording as {me.full_name}.
        </span>
      </div>
    </section>
  );
}

// ---- case detail ----------------------------------------------------------------

function StepForm({ caseId, needsEscort, onSaved }) {
  const [f, setF] = useState({ kind: "FIRST_AID", detail: "", facility: "", escort: "",
                               at: "", fit_on: new Date().toISOString().slice(0, 10),
                               light_duties: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (p) => setF((s) => ({ ...s, ...p }));
  const travel = ["DOCTOR", "MALE", "EVACUATED", "ADMITTED"].includes(f.kind);

  async function save() {
    setBusy(true); setError(null);
    try {
      const d = await api(`/health/cases/${caseId}/events`, { method: "POST", body: f });
      set({ detail: "", facility: "", escort: "" });
      onSaved(d);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return (
    <div style={{ padding: 12, borderRadius: 8, background: "#f6f9fb",
                  border: "1px solid var(--line)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <label style={{ fontSize: 12.5 }}>Step
          <select value={f.kind} onChange={(e) => set({ kind: e.target.value })} style={inputStyle}>
            {STEPS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 12.5 }}>When (blank = now)
          <input type="datetime-local" value={f.at} onChange={(e) => set({ at: e.target.value })}
                 style={inputStyle} />
        </label>
        {travel && (
          <label style={{ fontSize: 12.5 }}>Where (clinic / health centre / hospital)
            <input value={f.facility} onChange={(e) => set({ facility: e.target.value })}
                   style={inputStyle} />
          </label>
        )}
        {travel && (
          <label style={{ fontSize: 12.5 }}>
            Escort{f.kind !== "DOCTOR" ? " (required)" : ""} — carries passport copy, permit, insurance card
            <input value={f.escort} onChange={(e) => set({ escort: e.target.value })}
                   style={inputStyle} />
          </label>
        )}
        {f.kind === "CLEARED" && (
          <>
            <label style={{ fontSize: 12.5 }}>Fit to work from
              <input type="date" value={f.fit_on} onChange={(e) => set({ fit_on: e.target.value })}
                     style={inputStyle} />
            </label>
            <label style={{ fontSize: 12.5, display: "flex", gap: 8, alignItems: "center",
                            marginTop: 18 }}>
              <input type="checkbox" checked={f.light_duties}
                     onChange={(e) => set({ light_duties: e.target.checked })} />
              Light duties advised
            </label>
          </>
        )}
        <label style={{ fontSize: 12.5, gridColumn: "1 / -1" }}>
          {f.kind === "FIRST_AID" ? "What was given / done" : "Detail"}
          <input value={f.detail} onChange={(e) => set({ detail: e.target.value })}
                 style={inputStyle} />
        </label>
      </div>
      {error && <p style={{ color: "#a3271b", fontSize: 13, margin: "6px 0 0" }}>{error}</p>}
      <div style={{ marginTop: 10 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Saving…" : "Add step"}</button>
        {needsEscort && f.kind === "MALE" && (
          <span style={{ fontSize: 12, color: "#8a6d00", marginLeft: 10 }}>
            Malé within 24 hours; the PM arranges it directly.
          </span>
        )}
      </div>
    </div>
  );
}

function ProfileCard({ employeeId, profile, canEdit, onSaved }) {
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState(profile || {});
  const [busy, setBusy] = useState(false);
  useEffect(() => setF(profile || {}), [profile]);
  if (!profile) return null;
  const rows = [["Blood group", "blood_group"], ["Known conditions", "medical_conditions"],
                ["Allergies", "allergies"], ["Regular medication", "medication"]];
  async function save() {
    setBusy(true);
    try {
      await api(`/health/employees/${employeeId}`, { method: "PATCH", body: f });
      setEdit(false); onSaved();
    } catch (e) { window.alert(e.message); }
    finally { setBusy(false); }
  }
  return (
    <div style={{ padding: 12, borderRadius: 8, background: "#fbf7ec",
                  border: "1px solid #e6dcc0", fontSize: 13 }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <b>Medical profile</b>
        {canEdit && !edit && <button onClick={() => setEdit(true)} style={{ ...ghostButton, padding: "2px 10px", fontSize: 12 }}>Edit</button>}
      </div>
      <div style={{ fontSize: 11.5, color: "#7a6a40", marginBottom: 6 }}>
        Seen by HR, the Director, Admin and the site PM only.
      </div>
      {rows.map(([l, k]) => (
        <div key={k} style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 8, padding: "2px 0" }}>
          <span style={{ color: "#5a6b78" }}>{l}</span>
          {edit ? <input value={f[k] || ""} onChange={(e) => setF((s) => ({ ...s, [k]: e.target.value }))}
                         style={{ ...inputStyle, padding: "3px 6px" }} />
                : <span>{profile[k] || "—"}</span>}
        </div>
      ))}
      <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 8, padding: "2px 0" }}>
        <span style={{ color: "#5a6b78" }}>Emergency contact</span>
        <span>{profile.emergency_contact || "—"}</span>
      </div>
      {edit && (
        <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
          <button onClick={save} disabled={busy} style={buttonStyle}>Save</button>
          <button onClick={() => setEdit(false)} style={ghostButton}>Cancel</button>
        </div>
      )}
    </div>
  );
}

export function CaseDetail({ me, caseId, onClose, onChanged }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [files, setFiles] = useState([]);
  const [label, setLabel] = useState("");
  const load = useCallback(() => api(`/health/cases/${caseId}`).then(setD)
    .catch((e) => setError(e.message)), [caseId]);
  useEffect(() => { load(); }, [load]);

  async function act(path, body = {}) {
    setError(null);
    try { setD(await api(`/health/cases/${caseId}/${path}`, { method: "POST", body })); onChanged?.(); }
    catch (e) { setError(e.message); }
  }
  async function upload() {
    if (!files.length) return;
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    if (label) fd.append("label", label);
    try { setD(await apiUpload(`/health/cases/${caseId}/files`, fd, "POST")); setFiles([]); setLabel(""); }
    catch (e) { setError(e.message); }
  }
  async function removeFile(fid) {
    if (!window.confirm("Remove this file?")) return;
    try { setD(await api(`/health/cases/${caseId}/files/${fid}`, { method: "DELETE" })); }
    catch (e) { setError(e.message); }
  }

  if (!d) return <section style={card}>{error || "Loading…"}</section>;
  const tone = DUE_TONE[d.due_level];
  return (
    <section style={{ ...card, borderLeft: d.red_flag ? "5px solid #a3271b" : undefined }}>
      <div style={{ display: "flex", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}>
        <h3 style={{ margin: 0, color: "var(--navy)" }}>
          {d.ref} · {d.full_name}
          <span style={{ fontWeight: 400, color: "#5a6b78", fontSize: 14 }}> {d.emp_no} · {d.site_code}</span>
          <RepeatChip n={d.is_repeat ? d.repeat_cases : 0} />
        </h3>
        <span style={{ fontSize: 12.5, color: d.status === "OPEN" ? "#1a7f37" : "#5a6b78", fontWeight: 700 }}>
          {d.status === "OPEN" ? "OPEN" : `CLOSED${d.fit_on ? ` · fit from ${fmtDate(d.fit_on)}` : ""}`}
          {d.light_duties ? " · light duties" : ""}
        </span>
        <button onClick={onClose} style={{ ...ghostButton, marginLeft: "auto" }}>Close</button>
      </div>
      {d.red_flag && (
        <div style={{ marginTop: 8, padding: "6px 12px", background: "#fbeae8", color: "#a3271b",
                      border: "1px solid #e4b4ae", borderRadius: 6, fontWeight: 700, fontSize: 13 }}>
          RED FLAG — emergency evacuation by the fastest means, day or night. No approval is needed to start it. Inform the MD and the Director by phone.
        </div>
      )}
      {tone && d.due && (
        <div style={{ marginTop: 8, padding: "6px 12px", background: tone.bg, color: tone.fg,
                      border: `1px solid ${tone.border}`, borderRadius: 6, fontSize: 13, fontWeight: 600 }}>
          Due now: {d.due}
        </div>
      )}
      {error && <p style={{ color: "#a3271b", fontSize: 13 }}>{error}</p>}

      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 16, marginTop: 12 }}>
        <div>
          <table style={{ fontSize: 13, borderCollapse: "collapse", marginBottom: 10 }}>
            <tbody>
              {[["Complaint", d.complaint_label],
                ["Reported", `${fmtDate(d.reported_on)}${d.started_on ? ` (started ${fmtDate(d.started_on)})` : ""} by ${d.reported_by || "—"}`],
                ["Temperature", d.temperature ? `${d.temperature} °C` : "—"],
                ["Symptoms", d.symptoms || "—"],
                ["Sick days on register", d.days_sick],
                ["Same complaint in 7 days", d.earlier_same ? `${d.earlier_same} earlier` : "no"],
                ["Reports in 90 days", d.repeat_cases],
                ["Source", d.source === "ATTENDANCE" ? "Marked sick on attendance"
                  : d.source === "INCIDENT" ? `HSE incident ${d.incident_ref || ""}` : "Reported on site"],
              ].map(([l, v]) => (
                <tr key={l}><td style={{ color: "#5a6b78", padding: "2px 10px 2px 0", verticalAlign: "top" }}>{l}</td>
                            <td style={{ padding: "2px 0" }}>{v}</td></tr>
              ))}
            </tbody>
          </table>

          <b style={{ fontSize: 13 }}>Steps taken</b>
          {d.events.length === 0 && (
            <div style={{ fontSize: 12.5, color: "#a3271b", margin: "4px 0 8px" }}>
              Nothing recorded yet — first aid, check on him, and write it here today.
            </div>
          )}
          <ol style={{ margin: "4px 0 10px", paddingLeft: 20, fontSize: 13 }}>
            {d.events.map((e) => (
              <li key={e.id} style={{ marginBottom: 4 }}>
                <b>{e.label}</b>
                <span style={{ color: "#5a6b78" }}> · {fmtWhen(e.at)} · {e.by}</span>
                {e.facility && <div>At: {e.facility}</div>}
                {e.escort && <div>Escort: {e.escort}</div>}
                {e.detail && <div style={{ color: "#2d3a44" }}>{e.detail}</div>}
              </li>
            ))}
          </ol>
          {d.can_record && <StepForm caseId={caseId} needsEscort={d.needs_clearance}
                                     onSaved={(x) => { setD(x); onChanged?.(); }} />}

          <div style={{ marginTop: 12 }}>
            <b style={{ fontSize: 13 }}>Doctor's report, prescription, medical certificate</b>
            <ul style={{ margin: "4px 0", paddingLeft: 20, fontSize: 13 }}>
              {d.files.map((f) => (
                <li key={f.id}>
                  <a href={f.url} target="_blank" rel="noreferrer">{f.file_name}</a>
                  {f.label && <span> — {f.label}</span>}
                  <span style={{ color: "#5a6b78" }}> · {f.by}</span>
                  {d.can_record && <button onClick={() => removeFile(f.id)} title="Remove"
                          style={{ marginLeft: 6, border: "none", background: "transparent", cursor: "pointer", color: "#a3271b" }}>✕</button>}
                </li>
              ))}
            </ul>
            {d.can_record && (
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <input type="file" multiple accept="image/*,.pdf" style={{ fontSize: 12.5 }}
                       onChange={(e) => setFiles(Array.from(e.target.files || []))} />
                <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Label (e.g. medical certificate)"
                       style={{ ...inputStyle, width: 220 }} />
                <button onClick={upload} disabled={!files.length} style={ghostButton}>Upload</button>
              </div>
            )}
          </div>

          {d.can_record && (
            <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
              {d.status === "OPEN" && !d.needs_clearance && (
                <button onClick={() => { const note = window.prompt("Closing note (optional)") ?? null; if (note !== null) act("close", { note }); }}
                        style={ghostButton}>Close case (no doctor needed)</button>
              )}
              {d.status === "OPEN" && d.needs_clearance && (
                <span style={{ fontSize: 12.5, color: "#5a6b78", alignSelf: "center" }}>
                  He saw a doctor or had a fever: record <b>Cleared by doctor</b> to close.
                </span>
              )}
              {d.status === "CLOSED" && (
                <button onClick={() => { const r = window.prompt("Why reopen?"); if (r !== null) act("reopen", { reason: r }); }}
                        style={ghostButton}>Reopen</button>
              )}
            </div>
          )}
        </div>

        <div style={{ display: "grid", gap: 12, alignContent: "start" }}>
          <ProfileCard employeeId={d.employee_id} profile={d.profile}
                       canEdit={!!d.profile && ["HO_HR", "DIRECTOR", "ADMIN", "PM"].includes(me.role)}
                       onSaved={load} />
          <div style={{ fontSize: 12.5 }}>
            <b>The ladder</b>
            <ol style={{ margin: "4px 0", paddingLeft: 18, color: "#2d3a44" }}>
              <li>First complaint: first aid on site, check again evening and next morning.</li>
              <li>2nd of the same in 7 days, sick over 2 days, or fever: resort doctor / nearest health centre <b>today</b>.</li>
              <li>3rd, no improvement, or the doctor refers on: <b>Malé within 24 hours</b>.</li>
              <li>Any red-flag sign: evacuate <b>now</b>, then Malé.</li>
            </ol>
            <div style={{ color: "#5a6b78" }}>
              A sick man does not work. A fever works only when a doctor clears it. Cost is never a reason to delay.
            </div>
          </div>
          {d.history.length > 0 && (
            <div style={{ fontSize: 12.5 }}>
              <b>Earlier cases</b>
              <ul style={{ margin: "4px 0", paddingLeft: 18 }}>
                {d.history.map((h) => (
                  <li key={h.id}>{fmtDate(h.reported_on)} · {h.complaint_label} · {h.site_code} · {h.status.toLowerCase()}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
      <Discussion threadKey={`health:${caseId}`} me={me} />
    </section>
  );
}

// ---- medical plan -----------------------------------------------------------------

const PLAN_FIELDS = [
  ["hotline", "Site sickness hotline (day and night)"],
  ["focal_point_backup", "Backup for nights / days off"],
  ["hse_lead", "HSE lead / first aid lead"],
  ["first_aiders", "Trained first aiders"],
  ["nearest_health_centre", "Nearest health centre and doctor"],
  ["travel_time", "Travel time by boat"],
  ["resort_clinic", "Resort clinic / doctor arrangement (agreed in writing)"],
  ["male_hospitals", "Malé hospitals used for referrals"],
  ["boat_arrangement", "Emergency boat — ours, the resort's or contracted; leaves within 30 minutes at any hour"],
  ["sick_bay", "Sick bay — separate, ventilated, bed, water, toilet nearby"],
  ["emergency_contacts", "Emergency contacts (ambulance, Coast Guard, police 119, Director escalation)"],
];

function PlanTab({ me, siteId, sites }) {
  const [p, setP] = useState(null);
  const [users, setUsers] = useState([]);
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState({});
  const [error, setError] = useState(null);
  const site = sites.find((s) => String(s.id) === String(siteId));
  useEffect(() => {
    if (!siteId) return;
    api(`/health/plan/${siteId}`).then((x) => { setP(x); setF(x); }).catch((e) => setError(e.message));
    api(`/discussion/att:${siteId}:${new Date().toISOString().slice(0, 10)}/people`)
      .then((r) => setUsers(r.people || [])).catch(() => setUsers([]));
  }, [siteId]);
  if (!siteId) return <p style={{ fontSize: 13, color: "#5a6b78" }}>Choose a site to see its medical plan.</p>;
  if (!p) return <p style={{ fontSize: 13 }}>{error || "Loading…"}</p>;
  const canEdit = ["DIRECTOR", "ADMIN", "HO_HR", "PM"].includes(me.role);
  async function save() {
    try {
      const body = { ...f };
      setP(await api(`/health/plan/${siteId}`, { method: "PUT", body }));
      setEdit(false);
    } catch (e) { setError(e.message); }
  }
  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <h3 style={{ margin: 0, color: "var(--navy)" }}>Site medical plan — {site?.code}</h3>
        {canEdit && !edit && <button onClick={() => setEdit(true)} style={ghostButton}>Edit</button>}
      </div>
      <p style={{ fontSize: 12.5, color: "#5a6b78" }}>
        Agreed before anyone falls ill (SOP-HR-04 §A). Display it in the site office, the camp and on every crew board, in English and the workers' languages.
        {p.updated_at && <span> Last updated {fmtWhen(p.updated_at)} by {p.updated_by}.</span>}
      </p>
      {error && <p style={{ color: "#a3271b", fontSize: 13 }}>{error}</p>}
      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: "6px 12px", fontSize: 13 }}>
        <span style={{ color: "#5a6b78" }}>Health Focal Point (holds the hotline, keeps this log)</span>
        {edit ? (
          <select value={f.focal_point_id || ""} onChange={(e) => setF((s) => ({ ...s, focal_point_id: e.target.value ? +e.target.value : null }))}
                  style={inputStyle}>
            <option value="">— the Site Admin, or whoever the PM names —</option>
            {users.map((u) => <option key={u.id} value={u.id}>{u.name}{u.role ? ` (${u.role})` : ""}</option>)}
          </select>
        ) : <b>{p.focal_point || "— not named —"}</b>}
        {PLAN_FIELDS.map(([k, l]) => (
          <>
            <span key={`${k}-l`} style={{ color: "#5a6b78" }}>{l}</span>
            {edit ? <textarea key={`${k}-i`} rows={k === "hotline" || k === "travel_time" ? 1 : 2} value={f[k] || ""}
                              onChange={(e) => setF((s) => ({ ...s, [k]: e.target.value }))}
                              style={{ ...inputStyle, resize: "vertical" }} />
                  : <span key={`${k}-v`} style={{ whiteSpace: "pre-wrap" }}>{p[k] || "—"}</span>}
          </>
        ))}
      </div>
      {edit && (
        <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
          <button onClick={save} style={buttonStyle}>Save</button>
          <button onClick={() => { setEdit(false); setF(p); }} style={ghostButton}>Cancel</button>
        </div>
      )}
    </section>
  );
}

// ---- the page ------------------------------------------------------------------------

export default function HealthPage({ me, sites = [], site, openCaseId, onOpened }) {
  const [tab, setTab] = useState("cases");
  const [siteFilter, setSiteFilter] = useState(site?.id || (sites.length === 1 ? sites[0].id : ""));
  const [summary, setSummary] = useState(null);
  const [rows, setRows] = useState([]);
  const [repeat, setRepeat] = useState([]);
  const [followUps, setFollowUps] = useState([]);
  const [openOnly, setOpenOnly] = useState(true);
  const [q, setQ] = useState("");
  const [recording, setRecording] = useState(false);
  const [caseId, setCaseId] = useState(openCaseId || null);
  const [error, setError] = useState(null);
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const canRecord = CAN_RECORD.includes(me.role);
  const sq = siteFilter ? `site=${siteFilter}` : "";

  const load = useCallback(() => {
    const qs = [sq, openOnly ? "status=open" : "", q ? `q=${encodeURIComponent(q)}` : ""]
      .filter(Boolean).join("&");
    api(`/health/cases${qs ? `?${qs}` : ""}`).then(setRows).catch((e) => setError(e.message));
    api(`/health/summary${sq ? `?${sq}` : ""}`).then(setSummary).catch(() => setSummary(null));
    api(`/health/repeat${sq ? `?${sq}` : ""}`).then(setRepeat).catch(() => setRepeat([]));
    api(`/health/follow-ups${sq ? `?${sq}` : ""}`).then(setFollowUps).catch(() => setFollowUps([]));
  }, [sq, openOnly, q]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (openCaseId) { setCaseId(openCaseId); onOpened?.(); } }, [openCaseId, onOpened]);

  const unattended = rows.filter((r) => r.status === "OPEN" && !r.attended);

  return (
    <section>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap", marginBottom: 4 }}>
        <h2 style={{ margin: 0, color: "var(--navy)" }}>Health</h2>
        <p style={{ margin: 0, fontSize: 13, color: "#5a6b78" }}>
          Every complaint logged the same day, attended the same day, and the ladder followed.
        </p>
        {canRecord && (
          <button onClick={() => setRecording(true)} style={{ ...BTN.primary, marginLeft: "auto" }}>
            Record a complaint
          </button>
        )}
      </div>
      {error && <p style={{ color: "#a3271b", fontSize: 13 }}>{error}</p>}

      {summary?.alerts?.length > 0 && (
        <div style={{ margin: "10px 0", padding: "8px 12px", background: "#fbeae8", color: "#a3271b",
                      border: "1px solid #e4b4ae", borderRadius: 8, fontSize: 13, fontWeight: 600 }}>
          Possible outbreak: {summary.alerts.map((a) =>
            `${a.site_code} — ${a.label}, ${a.count} cases since ${fmtDate(a.since)}`).join(" · ")}.
          Separate the sick, every one sees a doctor, tell the client's representative and the resort today.
        </div>
      )}

      {summary && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", margin: "12px 0 16px" }}>
          <Stat value={summary.open} label="Open cases" />
          <Stat value={summary.unattended} label="Not yet attended" alarm />
          <Stat value={summary.overdue} label="Over 24 h unattended" alarm />
          <Stat value={summary.referred_out} label="With a doctor / away" />
          <Stat value={summary.repeat} label="Repeat sickness" alarm onClick={() => setTab("repeat")} />
          <Stat value={summary.follow_ups_due} label="Follow-ups due" onClick={() => setTab("followups")} />
          <Stat value={summary.cases_last_days} label={`Cases, last ${summary.last_days} days`} />
          <Stat value={summary.new_today} label="New today" />
        </div>
      )}

      {recording && (
        <NewCase me={me} sites={sites} siteId={site?.id} onClose={() => setRecording(false)}
                 onSaved={(d) => { setRecording(false); setCaseId(d.id); load(); }} />
      )}
      {caseId && (
        <div style={{ marginBottom: 14 }}>
          <CaseDetail me={me} caseId={caseId} onClose={() => setCaseId(null)} onChanged={load} />
        </div>
      )}

      <div style={{ display: "flex", gap: 2, marginBottom: 12, flexWrap: "wrap", alignItems: "flex-end",
                    borderBottom: "2px solid var(--line)" }}>
        {[["cases", `Cases (${rows.length})`],
          ["repeat", `Repeat sickness (${repeat.length})`],
          ["followups", `Follow-ups due (${followUps.length})`],
          ["plan", "Medical plan"]].map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
                  style={{ background: "transparent", border: "none", cursor: "pointer",
                           padding: "7px 16px 8px", fontSize: 13.5, marginBottom: -2, fontFamily: "inherit",
                           color: tab === key ? "var(--navy)" : "#5a6b78",
                           fontWeight: tab === key ? 700 : 500,
                           borderBottom: tab === key ? "2.5px solid var(--navy)" : "2.5px solid transparent" }}>
            {label}
          </button>
        ))}
        {tab === "cases" && (
          <>
            <label style={{ marginLeft: "auto", fontSize: 12.5, color: "#5a6b78", display: "flex",
                            alignItems: "center", gap: 6, paddingBottom: 6 }}>
              <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} />
              Open only
            </label>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name / number / ref"
                   style={{ ...inputStyle, width: 200, marginBottom: 5, marginLeft: 10 }} />
          </>
        )}
        {!site && sites.length > 1 && (
          <select value={siteFilter} onChange={(e) => setSiteFilter(e.target.value)}
                  style={{ ...inputStyle, width: "auto", marginBottom: 5, marginLeft: tab === "cases" ? 10 : "auto" }}>
            <option value="">All sites</option>
            {sites.map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}
          </select>
        )}
        {siteFilter && (
          <span style={{ display: "flex", gap: 4, alignItems: "center", marginBottom: 5, marginLeft: 8 }}>
            <input type="month" value={month} onChange={(e) => setMonth(e.target.value)}
                   style={{ ...inputStyle, width: "auto" }} />
            <button onClick={() => apiDownload(`/health/log.pdf?site=${siteFilter}&year=${month.slice(0, 4)}&month=${+month.slice(5, 7)}`)
                      .catch((e) => setError(e.message))}
                    style={{ ...ghostButton, padding: "5px 10px", fontSize: 12.5 }}
                    title="The month's health log for the weekly review and the file">
              📄 Month log</button>
          </span>
        )}
      </div>

      {tab === "cases" && (
        <>
          {unattended.length > 0 && (
            <p style={{ fontSize: 12.5, color: "#a3271b", margin: "0 0 8px" }}>
              {unattended.length} report{unattended.length === 1 ? "" : "s"} not yet attended — every one acted on the same day.
            </p>
          )}
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={{ ...th, width: 110 }}>Ref</th>
              <th style={{ ...th, width: 80 }}>Reported</th>
              {!siteFilter && <th style={{ ...th, width: 56 }}>Site</th>}
              <th style={th}>Worker</th>
              <th style={{ ...th, width: 170 }}>Complaint</th>
              <th style={{ ...th, width: 60 }}>Sick d</th>
              <th style={th}>Due</th>
              <th style={{ ...th, width: 70 }}>Status</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} onClick={() => setCaseId(r.id)} style={{ cursor: "pointer",
                    background: r.red_flag ? "#fff5f4" : undefined }}>
                  <td style={{ ...td, fontFamily: "monospace", whiteSpace: "nowrap" }}>{r.ref}</td>
                  <td style={td}>{fmtDate(r.reported_on)}</td>
                  {!siteFilter && <td style={td}>{r.site_code}</td>}
                  <td style={td}>{r.full_name} <span style={{ color: "#5a6b78", fontSize: 12 }}>{r.emp_no}</span>
                    <RepeatChip n={r.is_repeat ? r.repeat_cases : 0} />
                    {r.red_flag && <span style={{ marginLeft: 6, color: "#a3271b", fontWeight: 700, fontSize: 11 }}>RED FLAG</span>}
                  </td>
                  <td style={td}>{r.complaint_label}{r.temperature ? ` · ${r.temperature}°` : ""}</td>
                  <td style={{ ...td, textAlign: "center" }}>{r.days_sick || ""}</td>
                  <td style={td}><DueChip level={r.due_level} text={r.due} small /></td>
                  <td style={{ ...td, fontSize: 12, fontWeight: 700,
                               color: r.status === "OPEN" ? "#1a7f37" : "#5a6b78" }}>{r.status}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td colSpan={8} style={{ ...td, color: "#5a6b78" }}>No cases{openOnly ? " open" : ""}.</td></tr>
              )}
            </tbody>
          </table>
        </>
      )}

      {tab === "repeat" && (
        <>
          <p style={{ fontSize: 12.5, color: "#5a6b78", margin: "0 0 8px" }}>
            Three or more reports in 90 days. See each of these men properly — a repeat complaint is a referral, not a note.
          </p>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={{ ...th, width: 100 }}>Emp No</th><th style={th}>Worker</th>
              <th style={{ ...th, width: 60 }}>Site</th><th style={{ ...th, width: 70 }}>Cases</th>
              <th style={th}>Complaints</th><th style={{ ...th, width: 90 }}>Last</th>
              <th style={{ ...th, width: 80 }}>Open now</th>
            </tr></thead>
            <tbody>
              {repeat.map((r) => (
                <tr key={r.employee_id} onClick={() => { setQ(r.emp_no); setOpenOnly(false); setTab("cases"); }}
                    style={{ cursor: "pointer" }}>
                  <td style={{ ...td, fontFamily: "monospace" }}>{r.emp_no}</td>
                  <td style={td}>{r.full_name}</td>
                  <td style={td}>{r.site_code}</td>
                  <td style={{ ...td, textAlign: "center", fontWeight: 700, color: "#a3271b" }}>{r.cases}</td>
                  <td style={td}>{r.complaints.join(", ")}</td>
                  <td style={td}>{fmtDate(r.last_on)}</td>
                  <td style={td}>{r.open ? "yes" : ""}</td>
                </tr>
              ))}
              {repeat.length === 0 && <tr><td colSpan={7} style={{ ...td, color: "#5a6b78" }}>Nobody at the moment.</td></tr>}
            </tbody>
          </table>
        </>
      )}

      {tab === "followups" && (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={{ ...th, width: 110 }}>Ref</th><th style={th}>Worker</th>
            <th style={{ ...th, width: 60 }}>Site</th><th style={{ ...th, width: 90 }}>Fit from</th>
            <th style={th}>Due</th>
          </tr></thead>
          <tbody>
            {followUps.map((r) => (
              <tr key={r.id} onClick={() => setCaseId(r.id)} style={{ cursor: "pointer" }}>
                <td style={{ ...td, fontFamily: "monospace" }}>{r.ref}</td>
                <td style={td}>{r.full_name}</td><td style={td}>{r.site_code}</td>
                <td style={td}>{fmtDate(r.fit_on)}</td>
                <td style={td}><DueChip level={1} text={r.due} small /></td>
              </tr>
            ))}
            {followUps.length === 0 && <tr><td colSpan={5} style={{ ...td, color: "#5a6b78" }}>No checks due.</td></tr>}
          </tbody>
        </table>
      )}

      {tab === "plan" && <PlanTab me={me} siteId={siteFilter} sites={sites} />}
    </section>
  );
}

// A worker's health on his own profile (Workforce / Employees): his repeat
// count, his cases, and — for HR, the Director, Admin and his site's PM —
// his medical profile.
export function EmployeeHealth({ employeeId, onOpenCase }) {
  const [d, setD] = useState(null);
  const load = useCallback(() => api(`/health/employees/${employeeId}`).then(setD).catch(() => setD(null)),
                           [employeeId]);
  useEffect(() => { load(); }, [load]);
  if (!d) return null;
  return (
    <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
      <div style={{ fontSize: 13 }}>
        <b>Health log</b>
        <RepeatChip n={d.is_repeat ? d.repeat_cases : 0} />
        <span style={{ color: "#5a6b78" }}> · {d.cases.length} case{d.cases.length === 1 ? "" : "s"} on record
          {d.repeat_cases ? `, ${d.repeat_cases} in the last ${d.repeat_days} days` : ""}</span>
        {d.cases.length > 0 && (
          <ul style={{ margin: "4px 0 0", paddingLeft: 18, fontSize: 12.5 }}>
            {d.cases.slice(0, 6).map((c) => (
              <li key={c.id}>
                <a href="#health" onClick={(e) => { e.preventDefault(); onOpenCase?.(c.id); }}>{c.ref}</a>
                {" "}· {fmtDate(c.reported_on)} · {c.complaint_label} · {c.site_code} · {c.status.toLowerCase()}
                {c.due && c.status === "OPEN" && <> · <DueChip level={c.due_level} text={c.due} small /></>}
              </li>
            ))}
          </ul>
        )}
      </div>
      {d.sees_profile && (
        <ProfileCard employeeId={employeeId} profile={d.profile} canEdit onSaved={load} />
      )}
    </div>
  );
}

