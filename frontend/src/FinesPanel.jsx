// Worker fines (owner 2026-09-29): the site team records a breach of the
// safety or disciplinary code, the site PM approves it, and an approved fine
// comes off that month's payroll as the deduction. Stands alone — not tied to
// an HSE record. One panel serves the site (Workforce → Fines) and head
// office (People → Worker Fines, every site).
import { Fragment, useCallback, useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, Chip, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

const money = (v) => Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtDay = (s) => (s ? new Date(s + "T00:00").toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" }) : "");
const TONE = { PENDING: "warn", APPROVED: "ok", REJECTED: "alert", CANCELLED: "info" };
const CATEGORIES = [["SAFETY", "Safety"], ["DISCIPLINARY", "Disciplinary"], ["OTHER", "Other"]];
const RECORD_ROLES = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "HO_HR", "ADMIN"];

function today() {
  const t = new Date();
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
}

// ---- recording a fine -------------------------------------------------------

function FineForm({ site, sites, offences, onSaved, onCancel }) {
  const [siteId, setSiteId] = useState(site?.id || "");
  const [day, setDay] = useState(today());
  const [workers, setWorkers] = useState([]);
  const [f, setF] = useState({ employee: "", offence: "", category: "SAFETY", amount: "", description: "" });
  const [evidence, setEvidence] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");

  useEffect(() => {
    if (!siteId || !day) { setWorkers([]); return; }
    api(`/fines/workers?site=${siteId}&date=${day}`).then(setWorkers).catch((e) => { setWorkers([]); setError(e.message); });
  }, [siteId, day]);

  function pickOffence(id) {
    const o = offences.find((x) => String(x.id) === String(id));
    setF({ ...f, offence: id, category: o ? o.category : f.category,
           amount: o && Number(o.default_amount) > 0 ? o.default_amount : f.amount });
  }
  async function save(e) {
    e.preventDefault(); setBusy(true); setError(null);
    const fd = new FormData();
    fd.append("site", siteId); fd.append("employee", f.employee); fd.append("violation_date", day);
    if (f.offence) fd.append("offence", f.offence);
    fd.append("category", f.category); fd.append("amount", f.amount); fd.append("description", f.description);
    if (evidence) fd.append("evidence", evidence);
    try { onSaved(await apiUpload("/fines", fd)); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  const shown = workers.filter((w) => !q || `${w.emp_no} ${w.full_name}`.toLowerCase().includes(q.toLowerCase()));
  const label = (t) => <span style={{ fontWeight: 600, opacity: .8 }}>{t}</span>;
  const field = { display: "flex", flexDirection: "column", gap: 4, fontSize: 13 };
  return (
    <form onSubmit={save} style={{ ...card, background: "var(--sky-soft)", marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>Record a fine</h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "10px 16px" }}>
        {sites && (
          <label style={field}>{label("Site")}
            <select style={inputStyle} value={siteId} onChange={(e) => { setSiteId(e.target.value); setF({ ...f, employee: "" }); }} required>
              <option value="">— pick a site —</option>
              {sites.map((s) => <option key={s.id} value={s.id}>{s.code} · {s.name}</option>)}
            </select></label>
        )}
        <label style={field}>{label("Date of the breach")}
          <input type="date" style={inputStyle} value={day} max={today()} onChange={(e) => { setDay(e.target.value); setF({ ...f, employee: "" }); }} required /></label>
        <label style={{ ...field, gridColumn: "1 / -1" }}>{label("Worker")}
          <input style={inputStyle} placeholder="Search by number or name…" value={q} onChange={(e) => setQ(e.target.value)} />
          <select style={{ ...inputStyle, minHeight: 34 }} value={f.employee} onChange={(e) => setF({ ...f, employee: e.target.value })} required size={shown.length > 8 ? 8 : undefined}>
            <option value="">— {workers.length ? `${workers.length} at this site that day` : "pick the site and date first"} —</option>
            {shown.map((w) => <option key={w.id} value={w.id}>{w.emp_no} · {w.full_name}{w.category ? ` · ${w.category}` : ""}</option>)}
          </select></label>
        <label style={field}>{label("Offence")}
          <select style={inputStyle} value={f.offence} onChange={(e) => pickOffence(e.target.value)}>
            <option value="">Other — describe below</option>
            {CATEGORIES.map(([k, l]) => {
              const rows = offences.filter((o) => o.category === k);
              return rows.length ? <optgroup key={k} label={l}>{rows.map((o) => <option key={o.id} value={o.id}>{o.name}{Number(o.default_amount) > 0 ? ` — MVR ${money(o.default_amount)}` : ""}</option>)}</optgroup> : null;
            })}
          </select></label>
        <label style={field}>{label("Kind")}
          <select style={inputStyle} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} disabled={!!f.offence}>
            {CATEGORIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select></label>
        <label style={field}>{label("Fine (MVR)")}
          <input type="number" min="1" step="0.01" style={inputStyle} value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} required /></label>
        <label style={field}>{label("Photo or document (optional)")}
          <input type="file" accept="image/*,.pdf" style={{ fontSize: 12 }} onChange={(e) => setEvidence(e.target.files[0] || null)} /></label>
        <label style={{ ...field, gridColumn: "1 / -1" }}>{label("What happened")}
          <textarea style={{ ...inputStyle, minHeight: 64 }} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })}
                    placeholder="Where, what was seen, who was present. The PM reads this before deciding." required /></label>
      </div>
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
        <Btn type="submit" disabled={busy || !f.employee || !f.amount}>{busy ? "Saving…" : "Record fine"}</Btn>
        <Btn type="button" variant="secondary" onClick={onCancel}>Cancel</Btn>
        <span style={{ fontSize: 12, color: "var(--muted)" }}>Goes to the site PM to approve. Approved fines are deducted on that month's payroll.</span>
      </div>
    </form>
  );
}

// ---- one fine's detail + decision --------------------------------------------

function FineCard({ fine, onChanged }) {
  const [note, setNote] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function act(action) {
    if (action !== "approve" && !note.trim()) { setError(action === "reject" ? "Give the reason for rejecting it." : "Give the reason for cancelling it."); return; }
    if (action === "cancel" && !window.confirm(`Cancel ${fine.ref}? It will not be deducted.`)) return;
    setBusy(true); setError(null);
    try { onChanged(await api(`/fines/${fine.id}/${action}`, { method: "POST", body: { note } })); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const line = (l, v) => (v ? <div><span style={{ opacity: .65 }}>{l}</span> {v}</div> : null);
  return (
    <div style={{ ...card, background: "var(--sky-soft)", marginTop: 4, marginBottom: 8, fontSize: 13 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: "2px 16px" }}>
        {line("Recorded by", `${fine.recorded_by} · ${new Date(fine.created_at).toLocaleString()}`)}
        {line("Decided by", fine.decided_by ? `${fine.decided_by} · ${new Date(fine.decided_at).toLocaleString()}` : "")}
        {line("Decision note", fine.decision_note)}
        {line("Payroll month", fine.deduct_period)}
        {line("Deducted on", fine.deducted_on)}
        {line("Carried", fine.carried_note)}
        {line("Cancelled", fine.cancel_reason)}
        {fine.evidence_url && <div><a href={fine.evidence_url} target="_blank" rel="noreferrer">Open the photo / document</a></div>}
      </div>
      <p style={{ whiteSpace: "pre-wrap", margin: "8px 0" }}>{fine.description}</p>
      {fine.history && fine.history.length > 0 && (
        <div style={{ marginTop: 6 }}>
          <b>Other fines in the last 6 months:</b>
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
            {fine.history.map((h) => <li key={h.ref}>{fmtDay(h.date)} · {h.offence} · MVR {money(h.amount)} · {h.status.toLowerCase()}</li>)}
          </ul>
        </div>
      )}
      {(fine.can_decide || fine.can_cancel) && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 10 }}>
          <input style={{ ...inputStyle, flex: 1, minWidth: 220 }} placeholder={fine.can_decide ? "Note (required to reject)" : "Reason for cancelling"} value={note} onChange={(e) => setNote(e.target.value)} />
          {fine.can_decide && <Btn onClick={() => act("approve")} disabled={busy}>Approve — deduct MVR {money(fine.amount)}</Btn>}
          {fine.can_decide && <Btn variant="secondary" onClick={() => act("reject")} disabled={busy}>Reject</Btn>}
          {fine.can_cancel && <Btn variant="secondary" onClick={() => act("cancel")} disabled={busy}>Cancel fine</Btn>}
        </div>
      )}
      {error && <p style={{ color: "var(--red-fg)", margin: "6px 0 0" }}>{error}</p>}
    </div>
  );
}

// ---- the register ---------------------------------------------------------------

export default function FinesPanel({ site, sites, me, openId }) {
  const [rows, setRows] = useState(null);
  const [offences, setOffences] = useState([]);
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState(openId || null);
  const [status, setStatus] = useState("");
  const [month, setMonth] = useState("");
  const [q, setQ] = useState("");
  const [error, setError] = useState(null);
  const canRecord = RECORD_ROLES.includes(me.role);

  const load = useCallback(() => {
    const p = new URLSearchParams();
    if (site) p.set("site", site.id);
    if (status) p.set("status", status);
    if (month) p.set("month", month);
    if (q.trim()) p.set("q", q.trim());
    api(`/fines?${p}`).then((d) => setRows(d.results)).catch((e) => { setRows([]); setError(e.message); });
  }, [site, status, month, q]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api("/fines/offences").then((d) => setOffences(d.results)).catch(() => {}); }, []);

  const replace = (f) => { setRows((rs) => rs.map((r) => (r.id === f.id ? f : r))); };
  const pending = (rows || []).filter((r) => r.status === "PENDING");
  const totalPending = pending.reduce((t, r) => t + Number(r.amount), 0);
  const num = { ...td, textAlign: "right", whiteSpace: "nowrap" };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>Fines{site ? "" : " — all sites"}</h2>
          <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
            Recorded by the site team, approved by the site PM, deducted on that month's payroll.
            {pending.length > 0 && <> <b style={{ color: "var(--amber-fg)" }}>{pending.length} awaiting approval · MVR {money(totalPending)}</b></>}
          </div>
        </div>
        {canRecord && !adding && <Btn onClick={() => setAdding(true)}>+ Record a fine</Btn>}
      </div>
      {adding && <div style={{ marginTop: 12 }}><FineForm site={site} sites={site ? null : sites} offences={offences}
                    onSaved={(f) => { setAdding(false); setRows((rs) => [f, ...(rs || [])]); setOpen(f.id); }} onCancel={() => setAdding(false)} /></div>}
      <div style={{ display: "flex", gap: 8, margin: "12px 0", flexWrap: "wrap" }}>
        <select style={{ ...inputStyle, width: 170 }} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="PENDING">Awaiting PM</option><option value="APPROVED">Approved</option>
          <option value="REJECTED">Rejected</option><option value="CANCELLED">Cancelled</option>
        </select>
        <input type="month" style={{ ...inputStyle, width: 160 }} value={month} onChange={(e) => setMonth(e.target.value)} title="Month of the breach" />
        <input style={{ ...inputStyle, width: 220 }} placeholder="Worker or ref…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      {rows === null ? <p>Loading…</p> : rows.length === 0 ? <p style={{ opacity: .7 }}>No fines{status || month || q ? " match" : " yet"}.</p> : (
        <table style={{ width: "100%", borderCollapse: "collapse", background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 13 }}>
          <thead><tr>
            <th style={th}>Ref</th><th style={th}>Date</th>{!site && <th style={th}>Site</th>}<th style={th}>Worker</th>
            <th style={th}>Offence</th><th style={{ ...th, textAlign: "right" }}>MVR</th><th style={th}>Status</th><th style={th}>Payroll</th><th style={th}></th>
          </tr></thead>
          <tbody>
            {rows.map((r) => (
              <Fragment key={r.id}>
                <tr style={{ cursor: "pointer", background: open === r.id ? "var(--sky-soft)" : undefined }} onClick={() => setOpen(open === r.id ? null : r.id)}>
                  <td style={td}>{r.ref}</td>
                  <td style={{ ...td, whiteSpace: "nowrap" }}>{fmtDay(r.violation_date)}</td>
                  {!site && <td style={td}>{r.site_code}</td>}
                  <td style={td}><b>{r.emp_no}</b> {r.full_name}<div style={{ fontSize: 11.5, color: "var(--muted)" }}>{r.category_name}</div></td>
                  <td style={td}>{r.offence_name || r.category_label}{r.offence_name && <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{r.category_label}</div>}</td>
                  <td style={num}>{money(r.amount)}</td>
                  <td style={td}><Chip tone={TONE[r.status]}>{r.status_label}</Chip></td>
                  <td style={{ ...td, fontSize: 12 }}>{r.deducted_on ? `Deducted · ${r.deducted_on}` : r.deduct_period || ""}</td>
                  <td style={td}>{r.can_decide && <Chip tone="warn">decide</Chip>}</td>
                </tr>
                {open === r.id && <tr><td style={{ ...td, padding: 0 }} colSpan={site ? 8 : 9}><FineCard fine={r} onChanged={(f) => { replace(f); }} /></td></tr>}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ---- HR's offence list ----------------------------------------------------------

export function OffencesPanel() {
  const [rows, setRows] = useState(null);
  const [canEdit, setCanEdit] = useState(false);
  const [draft, setDraft] = useState(null);     // null | {} | offence
  const [error, setError] = useState(null);
  const load = () => api("/fines/offences?all=1").then((d) => { setRows(d.results); setCanEdit(d.can_edit); }).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);
  async function save(e) {
    e.preventDefault(); setError(null);
    try {
      if (draft.id) await api(`/fines/offences/${draft.id}`, { method: "PATCH", body: draft });
      else await api("/fines/offences", { method: "POST", body: draft });
      setDraft(null); load();
    } catch (err) { setError(err.message); }
  }
  const set = (k) => (e) => setDraft({ ...draft, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>Offence list</h2>
          <div style={{ fontSize: 12.5, color: "var(--muted)" }}>The standard fines a site picks from, so the same breach costs the same everywhere. Sites can still record "Other".</div>
        </div>
        {canEdit && !draft && <Btn onClick={() => setDraft({ name: "", category: "SAFETY", default_amount: "", is_active: true, sort_order: 0 })}>+ Add offence</Btn>}
      </div>
      {draft && (
        <form onSubmit={save} style={{ ...card, background: "var(--sky-soft)", margin: "12px 0", display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label style={{ fontSize: 13, flex: 2, minWidth: 220 }}>Offence<input style={inputStyle} value={draft.name} onChange={set("name")} required /></label>
          <label style={{ fontSize: 13 }}>Kind<select style={inputStyle} value={draft.category} onChange={set("category")}>{CATEGORIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          <label style={{ fontSize: 13 }}>Standard fine (MVR)<input type="number" min="0" step="0.01" style={{ ...inputStyle, width: 130 }} value={draft.default_amount} onChange={set("default_amount")} /></label>
          <label style={{ fontSize: 13 }}>Order<input type="number" style={{ ...inputStyle, width: 70 }} value={draft.sort_order} onChange={set("sort_order")} /></label>
          {draft.id && <label style={{ fontSize: 13 }}><input type="checkbox" checked={!!draft.is_active} onChange={set("is_active")} /> Active</label>}
          <Btn type="submit">Save</Btn><Btn type="button" variant="secondary" onClick={() => setDraft(null)}>Cancel</Btn>
        </form>
      )}
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      {rows === null ? <p>Loading…</p> : rows.length === 0 ? <p style={{ opacity: .7, marginTop: 12 }}>No offences listed yet — sites can still record a fine as "Other".</p> : (
        <table style={{ width: "100%", borderCollapse: "collapse", background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 8, marginTop: 12, fontSize: 13 }}>
          <thead><tr><th style={th}>Offence</th><th style={th}>Kind</th><th style={{ ...th, textAlign: "right" }}>Standard fine</th><th style={th}></th></tr></thead>
          <tbody>{rows.map((o) => (
            <tr key={o.id} style={{ opacity: o.is_active ? 1 : .5 }}>
              <td style={td}>{o.name}{!o.is_active && <Chip tone="info">retired</Chip>}</td><td style={td}>{o.category_label}</td>
              <td style={{ ...td, textAlign: "right" }}>{Number(o.default_amount) > 0 ? `MVR ${money(o.default_amount)}` : "—"}</td>
              <td style={td}>{canEdit && <button style={{ background: "none", border: 0, color: "var(--sp-navy)", textDecoration: "underline", cursor: "pointer", font: "inherit", padding: 0 }} onClick={() => setDraft(o)}>edit</button>}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
