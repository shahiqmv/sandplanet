// Safety induction sessions, SP-HSE-F01 (owner 2026-10-26, HSE forms brief
// C.1). Pick the men on the site not yet inducted there, print the form with
// them on it, run it, upload the signed copy — each man who signed gets his
// induction on this site — and the PM verifies. Attendance only flags a man
// with no induction; it never refuses the mark.
import { Fragment, useCallback, useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";

const fmtDay = (s) => (s ? new Date(String(s).slice(0, 10) + "T00:00").toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" }) : "");
const TONE = { DRAFT: "info", PRINTED: "warn", SIGNED: "warn", VERIFIED: "ok", CANCELLED: "info" };
const RECORD_ROLES = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "DIRECTOR", "ADMIN", "HO_HR", "PA"];

function today() {
  const t = new Date();
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
}

function NewSession({ siteId, sites, meta, onSaved, onCancel }) {
  const [site, setSite] = useState(siteId || "");
  const [day, setDay] = useState(today());
  const [language, setLanguage] = useState("BN");
  const [langTouched, setLangTouched] = useState(false);
  const [trainer, setTrainer] = useState("");
  const [men, setMen] = useState([]);
  const [picked, setPicked] = useState(() => new Set());
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!site || !day) { setMen([]); return; }
    api(`/hse-inductions/candidates?site=${site}&date=${day}`)
      .then(setMen)
      .catch((e) => { setMen([]); setError(e.message); });
  }, [site, day]);
  // A session is run in one language (owner 2026-10-26): the list is grouped
  // by each man's language, and the session's language group is ticked —
  // the others are inducted in their own session.
  const langOf = (m) => (m.language === "EN" ? "" : m.language || "");
  useEffect(() => {
    if (!men.length) { setPicked(new Set()); return; }
    let lang = language;
    if (!langTouched) {        // start with the biggest group's language
      const counts = {};
      men.forEach((m) => { counts[langOf(m)] = (counts[langOf(m)] || 0) + 1; });
      lang = Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
      setLanguage(lang);
    }
    setPicked(new Set(men.filter((m) => langOf(m) === lang).map((m) => m.id)));
  }, [men, language]); // eslint-disable-line react-hooks/exhaustive-deps
  const langLabel = (c) => (c ? meta.languages.find((l) => l.code === c)?.label || c : "English / not set");
  const [q, setQ] = useState("");
  const toggle = (id) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  // bulk tick / untick acts on the men shown, so "untick all, search the
  // subcontractor, tick all shown" picks one gang
  const shown = men.filter((m) => !q.trim() || `${m.emp_no} ${m.full_name} ${m.trade} ${m.subcontractor || "Sand Planet"}`
    .toLowerCase().includes(q.trim().toLowerCase()));
  const tickShown = (on) => setPicked((p) => { const n = new Set(p); shown.forEach((m) => (on ? n.add(m.id) : n.delete(m.id))); return n; });
  async function save(e) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      onSaved(await api("/hse-inductions", { method: "POST", body: {
        site, held_on: day, language, trainer_name: trainer, employees: [...picked] } }));
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={save} style={{ ...card, background: "var(--sky-soft)" }}>
      <h3 style={{ margin: "0 0 8px", color: "var(--navy)", fontSize: 15 }}>New induction session (SP-HSE-F01)</h3>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
        {!siteId && (
          <label style={{ fontSize: 13 }}>Site
            <select style={{ ...inputStyle, width: 200 }} value={site} onChange={(e) => setSite(e.target.value)}>
              <option value="">Choose…</option>
              {sites.map((s) => <option key={s.id} value={s.id}>{s.code} — {s.name}</option>)}
            </select></label>)}
        <label style={{ fontSize: 13 }}>Date
          <input type="date" style={{ ...inputStyle, width: 160 }} value={day} onChange={(e) => setDay(e.target.value)} /></label>
        <label style={{ fontSize: 13 }}>Language of training
          <select style={{ ...inputStyle, width: 150 }} value={language} onChange={(e) => { setLangTouched(true); setLanguage(e.target.value); }}>
            <option value="">English</option>
            {meta.languages.filter((l) => l.code !== "EN").map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
          </select></label>
        <label style={{ fontSize: 13, flex: 1, minWidth: 200 }}>Trained by (anyone — ours, the resort's or a subcontractor's)
          <input style={inputStyle} value={trainer} onChange={(e) => setTrainer(e.target.value)} /></label>
      </div>
      {language && !meta.translated.includes(language) && <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>The form prints in English only for this language — explain it to the men verbally.</div>}
      <div style={{ marginTop: 10, fontSize: 13 }}>
        <b>Men on the site not yet inducted here</b> <span style={{ color: "var(--muted)" }}>— new hires, bring-backs, transfers in, newly approved subcontract workers</span>
      </div>
      {men.length > 0 && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 6 }}>
          <input style={{ ...inputStyle, width: 260 }} placeholder="Search name, number, trade or subcontractor…" value={q} onChange={(e) => setQ(e.target.value)} />
          <Btn type="button" variant="secondary" onClick={() => tickShown(true)}>Tick all{q.trim() ? " shown" : ""}</Btn>
          <Btn type="button" variant="secondary" onClick={() => tickShown(false)}>Untick all{q.trim() ? " shown" : ""}</Btn>
          <span style={{ fontSize: 12.5, color: "var(--muted)" }}>{picked.size} of {men.length} ticked{q.trim() ? ` · ${shown.length} shown` : ""}</span>
        </div>
      )}
      <div style={{ maxHeight: 260, overflowY: "auto", border: "1px solid var(--line)", borderRadius: 6, marginTop: 6, background: "var(--paper)" }}>
        {[...new Set(shown.map(langOf))]
          .sort((a, b) => (a === language ? -1 : b === language ? 1 : shown.filter((m) => langOf(m) === b).length - shown.filter((m) => langOf(m) === a).length))
          .map((g) => {
            const group = shown.filter((m) => langOf(m) === g);
            const allOn = group.every((m) => picked.has(m.id));
            return (
              <Fragment key={g || "none"}>
                <div style={{ display: "flex", gap: 10, alignItems: "center", padding: "5px 8px", background: g === language ? "var(--sky-soft)" : "var(--sand, #f7f4ee)", borderBottom: "1px solid var(--line)", fontSize: 12.5 }}>
                  <b>{langLabel(g)} — {group.length}</b>
                  {g === language ? <span style={{ color: "var(--muted)" }}>this session's language</span>
                    : <span style={{ color: "var(--muted)" }}>run a separate session in {langLabel(g)}</span>}
                  <button type="button" onClick={() => setPicked((p) => { const n = new Set(p); group.forEach((m) => (allOn ? n.delete(m.id) : n.add(m.id))); return n; })}
                          style={{ marginLeft: "auto", background: "none", border: 0, color: "var(--navy)", cursor: "pointer", fontWeight: 600 }}>{allOn ? "Untick group" : "Tick group"}</button>
                </div>
                {group.map((m) => (
                  <label key={m.id} style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 8px 4px 16px", fontSize: 13, borderBottom: "1px solid var(--line)" }}>
                    <input type="checkbox" checked={picked.has(m.id)} onChange={() => toggle(m.id)} />
                    <b>{m.emp_no}</b> {m.full_name}
                    <span style={{ color: "var(--muted)", fontSize: 12 }}>{m.trade}{m.subcontractor ? ` · ${m.subcontractor}` : ""}</span>
                  </label>
                ))}
              </Fragment>
            );
          })}
        {men.length > 0 && shown.length === 0 && <div style={{ padding: 8, fontSize: 13, color: "var(--muted)" }}>No one matches the search.</div>}
        {men.length === 0 && <div style={{ padding: 8, fontSize: 13, color: "var(--muted)" }}>{site ? "Everyone on the site that day is inducted." : "Choose the site."}</div>}
      </div>
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center" }}>
        <Btn type="submit" disabled={busy || picked.size === 0 || !trainer.trim()}>{busy ? "Saving…" : `Create — ${picked.size} men`}</Btn>
        <Btn type="button" variant="secondary" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}

function SessionCard({ s, meta, onChanged }) {
  const [files, setFiles] = useState([]);
  const [absent, setAbsent] = useState(() => new Set());
  const [na, setNa] = useState(() => new Set());
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function upload() {
    if (!files.length) { setError("Choose the signed copy — a PDF or a photo of each page."); return; }
    setBusy(true); setError(null);
    const fd = new FormData();
    [...files].forEach((f) => fd.append("files", f));
    [...absent].forEach((id) => fd.append("absent", id));
    [...na].forEach((t) => fd.append("topics_na", t));
    try { onChanged(await apiUpload(`/hse-inductions/${s.id}/upload`, fd)); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function act(action, body) {
    setBusy(true); setError(null);
    try { onChanged(await api(`/hse-inductions/${s.id}/${action}`, { method: "POST", body: body || {} })); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function remove(id) {
    setBusy(true); setError(null);
    try { onChanged(await api(`/hse-inductions/${s.id}`, { method: "PATCH", body: { remove: [id] } })); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const tick = (setter, val) => setter((p) => { const n = new Set(p); if (n.has(val)) n.delete(val); else n.add(val); return n; });
  const canUpload = s.can_edit && s.status === "PRINTED";
  return (
    <div style={{ ...card, background: "var(--sky-soft)", marginTop: 4, marginBottom: 8, fontSize: 13 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "2px 16px" }}>
        <div><span style={{ opacity: .65 }}>Trained by</span> {s.trainer_name}</div>
        <div><span style={{ opacity: .65 }}>Language</span> {s.language_label}</div>
        <div><span style={{ opacity: .65 }}>Created by</span> {s.created_by}</div>
        {s.uploaded_at && <div><span style={{ opacity: .65 }}>Signed copy</span> {s.uploaded_by} · {new Date(s.uploaded_at).toLocaleString()}</div>}
        {s.verified_at && <div><span style={{ opacity: .65 }}>Verified</span> {s.verified_by} · {new Date(s.verified_at).toLocaleString()}</div>}
        {s.topics_na?.length > 0 && <div><span style={{ opacity: .65 }}>Not applicable</span> topics {s.topics_na.join(", ")}</div>}
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8 }}>
        <tbody>
          {s.attendees.map((a) => (
            <tr key={a.id} style={{ opacity: a.attended ? 1 : .5 }}>
              <td style={{ ...td, padding: "3px 6px" }}><b>{a.emp_no}</b> {a.full_name}</td>
              <td style={{ ...td, padding: "3px 6px", color: "var(--muted)" }}>{a.trade}{a.subcontractor ? ` · ${a.subcontractor}` : ""}</td>
              <td style={{ ...td, padding: "3px 6px" }}>
                {!a.attended && "did not sign"}
                {canUpload && <label style={{ fontSize: 12 }}><input type="checkbox" checked={absent.has(a.id)} onChange={() => tick(setAbsent, a.id)} /> did not sign</label>}
                {s.can_edit && s.status === "DRAFT" && <button onClick={() => remove(a.id)} disabled={busy} style={{ background: "none", border: 0, color: "var(--red-fg)", cursor: "pointer" }}>remove</button>}
              </td>
            </tr>))}
        </tbody>
      </table>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
        {s.status !== "CANCELLED" && <a href={`/api/v1/hse-inductions/${s.id}/pdf`} target="_blank" rel="noreferrer" style={{ fontWeight: 600 }}
           onClick={() => { if (s.status === "DRAFT") setTimeout(() => onChanged(null), 1500); }}>⬇ Print the induction sheet (F01)</a>}
        {s.signed_copy_url && <a href={s.signed_copy_url} target="_blank" rel="noreferrer" style={{ fontWeight: 600 }}>Signed copy</a>}
        {s.can_verify && <Btn onClick={() => act("verify")} disabled={busy}>Verify — {s.attendees.filter((a) => a.attended).length} inducted</Btn>}
        {s.can_edit && <Btn variant="secondary" onClick={() => { const r = window.prompt("Cancel this session? Reason:"); if (r) act("cancel", { reason: r }); }} disabled={busy}>Cancel session</Btn>}
      </div>
      {canUpload && (
        <div style={{ borderTop: "1px solid var(--line)", marginTop: 10, paddingTop: 8 }}>
          <b>Upload the signed sheet</b>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>Tick anyone above who did not sign, and any topic the trainer marked N/A. Each man who signed gets his induction on this site.</div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 6 }}>
            {meta.topics.map((t) => (
              <label key={t.no} style={{ fontSize: 12 }}><input type="checkbox" checked={na.has(t.no)} onChange={() => tick(setNa, t.no)} /> {t.no} {t.title} N/A</label>))}
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "flex-end", marginTop: 6, flexWrap: "wrap" }}>
            <label style={{ fontSize: 13 }}>Signed copy — PDF or a photo of each page
              <input type="file" multiple accept="application/pdf,image/*" capture="environment" onChange={(e) => setFiles(e.target.files)} style={{ display: "block" }} /></label>
            <Btn onClick={upload} disabled={busy}>Upload</Btn>
          </div>
        </div>
      )}
      {s.status === "DRAFT" && s.can_edit && <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>Print the sheet to run the session; the signed copy is uploaded here afterwards.</div>}
      {error && <p style={{ color: "var(--red-fg)", margin: "6px 0 0" }}>{error}</p>}
    </div>
  );
}

export default function InductionsPanel({ me, sites, siteFilter, openId }) {
  const [rows, setRows] = useState(null);
  const [meta, setMeta] = useState(null);
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState(openId || null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState(null);
  const canRecord = RECORD_ROLES.includes(me.role);
  const load = useCallback(() => {
    const p = new URLSearchParams();
    if (siteFilter) p.set("site", siteFilter);
    if (status) p.set("status", status);
    api(`/hse-inductions?${p}`).then((d) => setRows(d.results)).catch((e) => { setRows([]); setError(e.message); });
  }, [siteFilter, status]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api("/hse-inductions/meta").then(setMeta).catch(() => {}); }, []);
  const replace = (s) => { if (!s) { load(); return; } setRows((rs) => rs.map((r) => (r.id === s.id ? s : r))); };
  if (!meta) return <p>Loading…</p>;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <div style={{ fontSize: 12.5, color: "var(--muted)", maxWidth: 720 }}>
          Induction is per site. Men marked present without one show "Not inducted" on attendance — a flag, never a block.
          The site box on the sheet comes from the site's medical plan (Health → Medical plan).
        </div>
        {canRecord && !adding && <Btn onClick={() => setAdding(true)}>+ New induction session</Btn>}
      </div>
      {adding && <div style={{ marginTop: 10 }}><NewSession siteId={siteFilter} sites={sites} meta={meta}
        onSaved={(s) => { setAdding(false); setRows((rs) => [s, ...(rs || [])]); setOpen(s.id); }} onCancel={() => setAdding(false)} /></div>}
      <div style={{ display: "flex", gap: 8, margin: "12px 0" }}>
        <select style={{ ...inputStyle, width: 220 }} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All sessions</option>
          <option value="DRAFT">Being prepared</option><option value="PRINTED">Signed copy to upload</option>
          <option value="SIGNED">PM to verify</option><option value="VERIFIED">Verified</option>
          <option value="CANCELLED">Cancelled</option>
        </select>
      </div>
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      {rows === null ? <p>Loading…</p> : rows.length === 0 ? <p style={{ opacity: .7 }}>No induction sessions yet.</p> : (
        <table style={{ width: "100%", borderCollapse: "collapse", background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 13 }}>
          <thead><tr><th style={th}>Ref</th><th style={th}>Date</th><th style={th}>Site</th><th style={th}>Men</th><th style={th}>Status</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <Fragment key={r.id}>
                <tr style={{ cursor: "pointer", background: open === r.id ? "var(--sky-soft)" : undefined }} onClick={() => setOpen(open === r.id ? null : r.id)}>
                  <td style={td}>{r.ref}</td><td style={td}>{fmtDay(r.held_on)}</td><td style={td}>{r.site_code}</td>
                  <td style={td}>{r.attendees.filter((a) => a.attended).length}</td>
                  <td style={td}><Chip tone={TONE[r.status]}>{r.status_label}</Chip></td>
                </tr>
                {open === r.id && <tr><td colSpan={5} style={{ ...td, padding: 0 }}><SessionCard s={r} meta={meta} onChanged={replace} /></td></tr>}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
