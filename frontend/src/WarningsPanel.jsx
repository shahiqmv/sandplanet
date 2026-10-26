// Employee warning notices, SP-HSE-F02 (owner 2026-10-26, HSE forms brief
// C.2). The site team raises a warning for a direct or subcontract worker,
// the site PM approves it (never the person who raised it), the form is
// printed and served, and the signed copy uploaded makes it active. Sits on
// the Workforce page beside Fines and is never linked to a fine. One panel
// serves the site and head office (People → Worker Warnings, every site).
import { Fragment, useCallback, useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";

const fmtDay = (s) => (s ? new Date(String(s).slice(0, 10) + "T00:00").toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" }) : "");
const TONE = { PENDING: "warn", RETURNED: "alert", APPROVED: "info", ACTIVE: "ok", CANCELLED: "info" };
const LEVEL_TONE = { VERBAL: "info", FIRST: "warn", FINAL: "alert", REMOVAL: "alert" };
const RECORD_ROLES = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "HO_HR", "ADMIN"];

function today() {
  const t = new Date();
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
}

// ---- the warning's content (raise and correct) ---------------------------------

function WarningFields({ meta, f, setF, suggested }) {
  const toggle = (code) => setF({ ...f, offences: f.offences.includes(code)
    ? f.offences.filter((c) => c !== code) : [...f.offences, code] });
  const lbl = { fontSize: 13, display: "block" };
  const levelName = (c) => meta.levels.find((l) => l.code === c)?.label || c;
  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 20px", marginTop: 8 }}>
        {["SAFETY", "CONDUCT"].map((g) => (
          <div key={g}>
            <b style={{ fontSize: 12.5, color: "var(--sp-navy)" }}>{g === "SAFETY" ? "Safety" : "Conduct"}</b>
            {meta.offences.filter((o) => o.group === g).map((o) => (
              <label key={o.code} style={{ ...lbl, display: "flex", gap: 6, alignItems: "center" }}>
                <input type="checkbox" checked={f.offences.includes(o.code)} onChange={() => toggle(o.code)} />
                {o.label}</label>
            ))}
          </div>
        ))}
      </div>
      <label style={{ ...lbl, marginTop: 6 }}>Other offence
        <input style={inputStyle} value={f.other_offence} onChange={(e) => setF({ ...f, other_offence: e.target.value })} placeholder="Only if none of the above" /></label>
      <label style={{ ...lbl, marginTop: 6 }}>What happened — date, time and place
        <textarea rows={3} style={inputStyle} value={f.what_happened} onChange={(e) => setF({ ...f, what_happened: e.target.value })} /></label>
      <label style={{ ...lbl, marginTop: 6 }}>Corrective action required
        <textarea rows={2} style={inputStyle} value={f.corrective_action} onChange={(e) => setF({ ...f, corrective_action: e.target.value })} /></label>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 6, alignItems: "flex-end" }}>
        <label style={lbl}>Supervisor
          <input style={{ ...inputStyle, width: 200 }} value={f.supervisor} onChange={(e) => setF({ ...f, supervisor: e.target.value })} /></label>
        <label style={lbl}>Level
          <select style={{ ...inputStyle, width: 230 }} value={f.level || suggested || ""} onChange={(e) => setF({ ...f, level: e.target.value })}>
            {meta.levels.map((l) => <option key={l.code} value={l.code}>{l.label}{l.code === suggested ? " (suggested)" : ""}</option>)}
          </select></label>
      </div>
      {suggested && (f.level || suggested) !== suggested && (
        <label style={{ ...lbl, marginTop: 6 }}>Why not the suggested {levelName(suggested).toLowerCase()}?
          <input style={inputStyle} value={f.level_reason} onChange={(e) => setF({ ...f, level_reason: e.target.value })} placeholder="Required when the level differs" /></label>
      )}
    </>
  );
}

const EMPTY = { offences: [], other_offence: "", what_happened: "", corrective_action: "", supervisor: "", level: "", level_reason: "" };

function RaiseForm({ site, sites, meta, onSaved, onCancel, preset }) {
  const [siteId, setSiteId] = useState(site?.id || "");
  const [day, setDay] = useState(preset?.day || today());
  const [workers, setWorkers] = useState([]);
  const [emp, setEmp] = useState(preset?.employee || "");
  const [f, setF] = useState(EMPTY);
  const [q, setQ] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!siteId || !day) { setWorkers([]); return; }
    api(`/hse-warnings/workers?site=${siteId}&date=${day}`).then(setWorkers)
      .catch((e) => { setWorkers([]); setError(e.message); });
  }, [siteId, day]);
  const worker = workers.find((w) => String(w.id) === String(emp));
  async function save(e) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      onSaved(await api("/hse-warnings", { method: "POST", body: {
        ...f, level: f.level || worker?.suggested_level, site: siteId, employee: emp, event_date: day,
        incident: preset?.incident || undefined } }));
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  const shown = workers.filter((w) => !q || `${w.emp_no} ${w.full_name} ${w.subcontractor}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <form onSubmit={save} style={{ ...card, background: "var(--sky-soft)" }}>
      <h3 style={{ margin: "0 0 8px", color: "var(--sp-navy)", fontSize: 15 }}>Raise a warning notice (SP-HSE-F02)</h3>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
        {sites && (
          <label style={{ fontSize: 13 }}>Site
            <select style={{ ...inputStyle, width: 200 }} value={siteId} onChange={(e) => { setSiteId(e.target.value); setEmp(""); }}>
              <option value="">Choose…</option>
              {sites.map((s) => <option key={s.id} value={s.id}>{s.code} — {s.name}</option>)}
            </select></label>)}
        <label style={{ fontSize: 13 }}>Date of the offence
          <input type="date" max={today()} style={{ ...inputStyle, width: 160 }} value={day} onChange={(e) => setDay(e.target.value)} /></label>
        <label style={{ fontSize: 13, flex: 1, minWidth: 220 }}>Worker on the site that day
          <input style={inputStyle} placeholder="Search name, number or subcontractor…" value={q} onChange={(e) => setQ(e.target.value)} /></label>
      </div>
      <div style={{ maxHeight: 170, overflowY: "auto", border: "1px solid var(--line)", borderRadius: 6, marginTop: 6, background: "var(--paper)" }}>
        {shown.map((w) => (
          <label key={w.id} style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 8px", fontSize: 13, borderBottom: "1px solid var(--line)", background: String(emp) === String(w.id) ? "var(--sky-soft)" : undefined }}>
            <input type="radio" name="wn-emp" checked={String(emp) === String(w.id)} onChange={() => { setEmp(w.id); setF({ ...f, level: "" }); }} />
            <b>{w.emp_no}</b> {w.full_name}
            <span style={{ color: "var(--muted)", fontSize: 12 }}>{w.trade}{w.subcontractor ? ` · ${w.subcontractor}` : ""}</span>
            {w.active > 0 && <Chip tone="warn">{w.active} active warning{w.active > 1 ? "s" : ""}</Chip>}
          </label>
        ))}
        {shown.length === 0 && <div style={{ padding: 8, fontSize: 13, color: "var(--muted)" }}>{siteId ? "No one on the site that day." : "Choose the site."}</div>}
      </div>
      {worker && <WarningFields meta={meta} f={f} setF={setF} suggested={worker.suggested_level} />}
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center", flexWrap: "wrap" }}>
        <Btn type="submit" disabled={busy || !worker}>{busy ? "Saving…" : "Send to the PM"}</Btn>
        <Btn type="button" variant="secondary" onClick={onCancel}>Cancel</Btn>
        <span style={{ fontSize: 12, color: "var(--muted)" }}>The site PM approves it, then you print, serve and upload the signed copy. No money is involved — a fine is recorded separately if wanted.</span>
      </div>
    </form>
  );
}

// From an HSE incident: the same form, its site and date fixed, the warning
// carrying the incident (HSE forms brief C.2). People on an incident are
// mostly typed names, so the worker is picked from those on the site that day.
export function WarnFromIncident({ incident, onDone, onCancel }) {
  const [meta, setMeta] = useState(null);
  const [saved, setSaved] = useState(null);
  useEffect(() => { api("/hse-warnings/meta").then(setMeta).catch(() => {}); }, []);
  if (saved) return <p style={{ fontSize: 13, color: "var(--green-fg, #1e6b3a)" }}>{saved.ref} sent to the PM — it is under Workforce → Warnings. <button onClick={onDone} style={{ background: "none", border: 0, color: "var(--navy)", cursor: "pointer", fontWeight: 600 }}>Close</button></p>;
  if (!meta) return <p style={{ fontSize: 13 }}>Loading…</p>;
  const d = new Date(incident.occurred_at);
  const day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const linked = (incident.people || []).filter((p) => p.employee);
  return (
    <RaiseForm site={{ id: incident.site_id }} meta={meta} onCancel={onCancel} onSaved={setSaved}
               preset={{ day, incident: incident.id, employee: linked.length === 1 ? linked[0].employee : "" }} />
  );
}

// ---- one warning: decide, correct, serve ------------------------------------------

function WarningCard({ w, meta, onChanged }) {
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(false);
  const [f, setF] = useState(null);
  const [serve, setServe] = useState({ served_on: today(), refused: false, witness: "" });
  const [files, setFiles] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function act(action, body) {
    setBusy(true); setError(null);
    try { onChanged(await api(`/hse-warnings/${w.id}/${action}`, { method: "POST", body })); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function saveEdit() {
    setBusy(true); setError(null);
    try { onChanged(await api(`/hse-warnings/${w.id}`, { method: "PATCH", body: f })); setEditing(false); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function doServe() {
    if (!files.length) { setError("Choose the signed copy — a PDF or photos of each page."); return; }
    setBusy(true); setError(null);
    const fd = new FormData();
    fd.append("served_on", serve.served_on);
    fd.append("refused_to_sign", serve.refused ? "true" : "false");
    fd.append("witness_name", serve.witness);
    [...files].forEach((x) => fd.append("files", x));
    try { onChanged(await apiUpload(`/hse-warnings/${w.id}/serve`, fd)); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const line = (l, v) => (v ? <div><span style={{ opacity: .65 }}>{l}</span> {v}</div> : null);
  const offenceNames = (w.offences || []).map((c) => meta.offences.find((o) => o.code === c)?.label || c)
    .concat(w.other_offence ? [`Other: ${w.other_offence}`] : []);
  return (
    <div style={{ ...card, background: "var(--sky-soft)", marginTop: 4, marginBottom: 8, fontSize: 13 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: "2px 16px" }}>
        {line("Offence", offenceNames.join(" · "))}
        {line("Raised by", `${w.raised_by} · ${new Date(w.created_at).toLocaleString()}`)}
        {line("Decided by", w.decided_by ? `${w.decided_by} · ${new Date(w.decided_at).toLocaleString()}` : "")}
        {line("PM's note", w.decision_note)}
        {w.level !== w.suggested_level && line("Level reason", `${w.level_reason} (Planet suggested ${meta.levels.find((l) => l.code === w.suggested_level)?.label.toLowerCase()})`)}
        {line("Supervisor", w.supervisor)}
        {line("Incident", w.incident_ref)}
        {line("Served", w.served_on ? `${fmtDay(w.served_on)}${w.refused_to_sign ? ` · refused to sign, witness ${w.witness_name}` : ""}` : "")}
        {line("Active until", w.active_until ? fmtDay(w.active_until) : "")}
        {line("Removal", w.removal_batch ? "Remove batch opened for the PM on Direct workers" : "")}
        {line("Cancelled", w.cancel_reason)}
      </div>
      {!editing && <>
        <p style={{ whiteSpace: "pre-wrap", margin: "8px 0 4px" }}>{w.what_happened}</p>
        {w.corrective_action && <p style={{ whiteSpace: "pre-wrap", margin: "0 0 4px", color: "var(--muted)" }}>Corrective action: {w.corrective_action}</p>}
      </>}
      {editing && f && <WarningFields meta={meta} f={f} setF={setF} suggested={w.suggested_level} />}
      {w.history && w.history.length > 0 && (
        <div style={{ marginTop: 6 }}>
          <b>His other warnings:</b>
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
            {w.history.map((h) => <li key={h.ref}>{fmtDay(h.date)} · {h.site} · {h.level} · {h.status.toLowerCase()}{h.active ? " (counts now)" : ""}</li>)}
          </ul>
        </div>
      )}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 8, alignItems: "center" }}>
        {["APPROVED", "ACTIVE"].includes(w.status) && (
          <a href={`/api/v1/hse-warnings/${w.id}/pdf`} target="_blank" rel="noreferrer" style={{ fontWeight: 600 }}>⬇ Print the form (F02)</a>)}
        {w.signed_copy_url && <a href={w.signed_copy_url} target="_blank" rel="noreferrer" style={{ fontWeight: 600 }}>Signed copy</a>}
      </div>
      {w.can_decide && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 10 }}>
          <input style={{ ...inputStyle, flex: 1, minWidth: 220 }} placeholder="Note (required to return it)" value={note} onChange={(e) => setNote(e.target.value)} />
          <Btn onClick={() => act("approve", { note })} disabled={busy}>Approve — {w.level_label.toLowerCase()}</Btn>
          <Btn variant="secondary" onClick={() => { if (!note.trim()) { setError("Say why it is going back."); return; } act("return", { note }); }} disabled={busy}>Return to the site</Btn>
        </div>
      )}
      {w.can_edit && !editing && (
        <div style={{ marginTop: 8 }}><Btn variant="secondary" onClick={() => { setF({ offences: w.offences, other_offence: w.other_offence, what_happened: w.what_happened, corrective_action: w.corrective_action, supervisor: w.supervisor, level: w.level, level_reason: w.level_reason }); setEditing(true); }}>Correct it</Btn></div>
      )}
      {editing && (
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <Btn onClick={saveEdit} disabled={busy}>Save — send to the PM</Btn>
          <Btn variant="secondary" onClick={() => setEditing(false)}>Cancel</Btn>
        </div>
      )}
      {w.can_serve && (
        <div style={{ borderTop: "1px solid var(--line)", marginTop: 10, paddingTop: 8 }}>
          <b>Served it? Upload the signed copy</b>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end", marginTop: 6 }}>
            <label style={{ fontSize: 13 }}>Served on
              <input type="date" max={today()} style={{ ...inputStyle, width: 160 }} value={serve.served_on} onChange={(e) => setServe({ ...serve, served_on: e.target.value })} /></label>
            <label style={{ fontSize: 13, display: "flex", gap: 6, alignItems: "center" }}>
              <input type="checkbox" checked={serve.refused} onChange={(e) => setServe({ ...serve, refused: e.target.checked })} />
              He refused to sign</label>
            {serve.refused && <label style={{ fontSize: 13 }}>Witness who signed
              <input style={{ ...inputStyle, width: 200 }} value={serve.witness} onChange={(e) => setServe({ ...serve, witness: e.target.value })} /></label>}
            <label style={{ fontSize: 13 }}>Signed copy — PDF or a photo of each page
              <input type="file" multiple accept="application/pdf,image/*" capture="environment" onChange={(e) => setFiles(e.target.files)} style={{ display: "block" }} /></label>
            <Btn onClick={doServe} disabled={busy}>Upload — make it active</Btn>
          </div>
          {w.level === "REMOVAL" && <div style={{ fontSize: 12, color: "var(--amber-fg)", marginTop: 4 }}>A removal takes effect when uploaded: a direct worker gets a Remove batch for the PM; a subcontract worker comes off the site.</div>}
        </div>
      )}
      {error && <p style={{ color: "var(--red-fg)", margin: "6px 0 0" }}>{error}</p>}
    </div>
  );
}

// ---- the register -----------------------------------------------------------------

export default function WarningsPanel({ site, sites, me, openId }) {
  const [rows, setRows] = useState(null);
  const [meta, setMeta] = useState(null);
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState(openId || null);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [error, setError] = useState(null);
  const canRecord = RECORD_ROLES.includes(me.role);
  const load = useCallback(() => {
    const p = new URLSearchParams();
    if (site) p.set("site", site.id);
    if (status) p.set("status", status);
    if (q.trim()) p.set("q", q.trim());
    api(`/hse-warnings?${p}`).then((d) => setRows(d.results)).catch((e) => { setRows([]); setError(e.message); });
  }, [site, status, q]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api("/hse-warnings/meta").then(setMeta).catch(() => {}); }, []);
  const replace = (w) => setRows((rs) => rs.map((r) => (r.id === w.id ? w : r)));
  const pending = (rows || []).filter((r) => r.status === "PENDING").length;
  const toServe = (rows || []).filter((r) => r.status === "APPROVED").length;
  if (!meta) return <p>Loading…</p>;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>Warning notices{site ? "" : " — all sites"}</h2>
          <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
            Raised by the site team, approved by the PM, served on form SP-HSE-F02. Active for {meta.active_months} months. Separate from fines.
            {pending > 0 && <> <b style={{ color: "var(--amber-fg)" }}>{pending} awaiting the PM</b></>}
            {toServe > 0 && <> <b style={{ color: "var(--amber-fg)" }}>· {toServe} to serve</b></>}
          </div>
        </div>
        {canRecord && !adding && <Btn onClick={() => setAdding(true)}>+ Raise a warning</Btn>}
      </div>
      {adding && <div style={{ marginTop: 12 }}><RaiseForm site={site} sites={site ? null : sites} meta={meta}
        onSaved={(w) => { setAdding(false); setRows((rs) => [w, ...(rs || [])]); setOpen(w.id); }} onCancel={() => setAdding(false)} /></div>}
      <div style={{ display: "flex", gap: 8, margin: "12px 0", flexWrap: "wrap" }}>
        <select style={{ ...inputStyle, width: 190 }} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="PENDING">Awaiting PM</option><option value="RETURNED">Returned</option>
          <option value="APPROVED">To serve</option><option value="ACTIVE">Active</option>
          <option value="CANCELLED">Cancelled</option>
        </select>
        <input style={{ ...inputStyle, width: 220 }} placeholder="Worker or ref…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      {rows === null ? <p>Loading…</p> : rows.length === 0 ? <p style={{ opacity: .7 }}>No warnings{status || q ? " match" : " yet"}.</p> : (
        <table style={{ width: "100%", borderCollapse: "collapse", background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 13 }}>
          <thead><tr>
            <th style={th}>Ref</th><th style={th}>Date</th>{!site && <th style={th}>Site</th>}<th style={th}>Worker</th>
            <th style={th}>Level</th><th style={th}>Status</th><th style={th}></th>
          </tr></thead>
          <tbody>
            {rows.map((r) => (
              <Fragment key={r.id}>
                <tr style={{ cursor: "pointer", background: open === r.id ? "var(--sky-soft)" : undefined }} onClick={() => setOpen(open === r.id ? null : r.id)}>
                  <td style={td}>{r.ref}</td>
                  <td style={{ ...td, whiteSpace: "nowrap" }}>{fmtDay(r.event_date)}</td>
                  {!site && <td style={td}>{r.site_code}</td>}
                  <td style={td}><b>{r.emp_no}</b> {r.full_name}<div style={{ fontSize: 11.5, color: "var(--muted)" }}>{r.trade}{r.subcontractor ? ` · ${r.subcontractor}` : ""}</div></td>
                  <td style={td}><Chip tone={LEVEL_TONE[r.level]}>{r.level_label}</Chip></td>
                  <td style={td}><Chip tone={TONE[r.status]}>{r.status_label}</Chip></td>
                  <td style={td}>{r.can_decide && <Chip tone="warn">decide</Chip>}{r.can_serve && <Chip tone="warn">serve</Chip>}</td>
                </tr>
                {open === r.id && <tr><td style={{ ...td, padding: 0 }} colSpan={site ? 6 : 7}><WarningCard w={r} meta={meta} onChanged={replace} /></td></tr>}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
