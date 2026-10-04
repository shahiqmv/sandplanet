// External audits: a register of each audit of the company by an outside
// auditor — who, for which year, where it stands — and its papers: the
// engagement letter, the draft, the signed report. The fee is paid on an
// ordinary payment requisition; only its reference is noted here.
// (owner 2026-10-04 — core/ext_audit.py)
import { useCallback, useEffect, useState } from "react";
import { api, apiUpload } from "../api.js";
import { Btn, Chip, card, inputStyle } from "../ui.jsx";
import { fmtDate, money } from "./shared.jsx";
import { field, lab } from "./forms.jsx";

const BLANK = { kind: "FINANCIAL", title: "", period_start: "", period_end: "", auditor: "", partner: "", auditor_contact: "",
  status: "PLANNED", started_on: "", report_date: "", opinion: "", fee_currency: "MVR", fee_amount: "", payment_ref: "", notes: "" };
const TONE = { PLANNED: "info", IN_PROGRESS: "warn", DRAFT: "warn", COMPLETED: "ok", CANCELLED: "info" };

function List({ go }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { api("/audits").then(setData).catch((e) => setError(e.message)); }, []);
  if (!data) return <div style={card}>{error || "Loading…"}</div>;
  const rows = data.audits;
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>External audits</h1>
        <span className="spacer" />
        {data.can_edit && <Btn onClick={() => go("audits", "new")}>+ Audit</Btn>}
      </div>
      <p style={{ fontSize: 13.5, color: "var(--muted)", marginTop: -4, maxWidth: 860 }}>
        Each audit of the company by an outside auditor, with its papers and the signed report. The auditor&rsquo;s fee is
        paid on a payment requisition like any other payment.</p>
      {rows.length === 0 ? <div style={card}>No audits recorded yet.{data.can_edit && <> Add one with <b>+ Audit</b>, then upload its report.</>}</div> : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table className="f-table">
            <thead><tr><th>Ref</th><th>Audit</th><th>Period</th><th>Auditor</th><th>Status</th><th>Report dated</th><th>Papers</th><th /></tr></thead>
            <tbody>{rows.map((a) => (
              <tr key={a.id}>
                <td><button className="f-link" onClick={() => go("audits", a.ref)}>{a.ref}</button></td>
                <td>{a.title}</td>
                <td style={{ whiteSpace: "nowrap" }}>{fmtDate(a.period_start)} – {fmtDate(a.period_end)}</td>
                <td>{a.auditor}</td>
                <td><Chip tone={TONE[a.status]}>{a.status_label}</Chip>{a.opinion_label && <span style={{ fontSize: 12, color: "var(--muted)" }}> {a.opinion_label}</span>}</td>
                <td style={{ whiteSpace: "nowrap" }}>{a.report_date ? fmtDate(a.report_date) : ""}</td>
                <td>{a.file_count || ""}</td>
                <td>{a.report_url && <a href={a.report_url} target="_blank" rel="noreferrer" style={{ fontSize: 13 }}>Open the report</a>}</td>
              </tr>))}</tbody>
          </table>
        </div>)}
    </div>
  );
}

function Audit({ ident, go }) {
  const isNew = ident === "new";
  const [a, setA] = useState(null);
  const [f, setF] = useState(BLANK);
  const [meta, setMeta] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  const [up, setUp] = useState({ kind: "REPORT", label: "", file: null });
  const take = useCallback((x) => {
    setA(x); if (x.meta) setMeta(x.meta);
    const next = { ...BLANK };
    Object.keys(BLANK).forEach((k) => { next[k] = x[k] ?? ""; });
    setF(next);
  }, []);
  useEffect(() => {
    if (isNew) api("/audits").then((d) => setMeta(d.meta)).catch((e) => setError(e.message));
    else api(`/audits/${ident}`).then(take).catch((e) => setError(e.message));
  }, [ident, isNew, take]);
  const set = (k) => (e) => setF((p) => ({ ...p, [k]: e.target.value }));
  async function save() {
    setBusy(true); setError(null); setMsg(null);
    try {
      const saved = await api(isNew ? "/audits" : `/audits/${ident}`, { method: isNew ? "POST" : "PATCH", body: f });
      if (isNew) go("audits", saved.ref); else { take(saved); setMsg("Saved."); }
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function upload() {
    if (!up.file) { setError("Choose the file."); return; }
    setBusy(true); setError(null); setMsg(null);
    try {
      const fd = new FormData(); fd.append("file", up.file); fd.append("kind", up.kind); fd.append("label", up.label);
      const x = await apiUpload(`/audits/${ident}/files`, fd);
      setA((p) => ({ ...p, ...x })); setUp({ kind: "OTHER", label: "", file: null }); setMsg("Uploaded.");
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function remove(file) {
    if (!window.confirm(`Remove ${file.name || file.kind_label}?`)) return;
    setError(null); setMsg(null);
    try { const x = await api(`/audits/${ident}/files/${file.id}`, { method: "DELETE" }); setA((p) => ({ ...p, ...x })); }
    catch (e) { setError(e.message); }
  }
  if (!meta) return <div style={card}>{error || "Loading…"}</div>;
  const canEdit = isNew ? true : a?.can_edit;
  const ro = !canEdit;
  const grid = { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: "10px 16px" };
  const sel = (k, opts, blank) => (
    <select style={inputStyle} disabled={ro} value={f[k]} onChange={set(k)}>
      {blank && <option value="">{blank}</option>}
      {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>);
  const inp = (k, props = {}) => <input style={inputStyle} disabled={ro} value={f[k]} onChange={set(k)} {...props} />;
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>{isNew ? "New audit" : `${a.ref} · ${a.title}`}</h1>
        {!isNew && <Chip tone={TONE[a.status]}>{a.status_label}</Chip>}
        <span className="spacer" />
        <Btn variant="secondary" onClick={() => go("audits")}>‹ All audits</Btn>
      </div>
      {msg && <p className="f-ok" style={{ fontSize: 13.5 }}>{msg}</p>}
      {error && <p className="f-bad" style={{ fontSize: 13.5 }}>{error}</p>}
      <div style={card}>
        <div style={grid}>
          <label style={field}>{lab("Kind of audit")}{sel("kind", meta.kinds)}</label>
          <label style={field}>{lab("Period from")}{inp("period_start", { type: "date" })}</label>
          <label style={field}>{lab("Period to")}{inp("period_end", { type: "date" })}</label>
          <label style={field}>{lab("Status")}{sel("status", meta.statuses)}</label>
          <label style={field}>{lab("Auditor (firm)")}{inp("auditor", { placeholder: "e.g. Emmjay Associates" })}</label>
          <label style={field}>{lab("Partner in charge")}{inp("partner")}</label>
          <label style={field}>{lab("Auditor's contact")}{inp("auditor_contact", { placeholder: "phone or email" })}</label>
          <label style={field}>{lab("Title")}{inp("title", { placeholder: "left blank, named from the kind and year" })}</label>
          <label style={field}>{lab("Work started")}{inp("started_on", { type: "date" })}</label>
          <label style={field}>{lab("Date on the report")}{inp("report_date", { type: "date" })}</label>
          <label style={field}>{lab("Opinion")}{sel("opinion", meta.opinions, "—")}</label>
        </div>
        <div style={{ ...grid, marginTop: 14 }}>
          <label style={field}>{lab("Agreed fee")}
            <span style={{ display: "flex", gap: 6 }}>
              <select style={{ ...inputStyle, width: 80 }} disabled={ro} value={f.fee_currency} onChange={set("fee_currency")}><option>MVR</option><option>USD</option></select>
              {inp("fee_amount", { inputMode: "decimal", placeholder: "0.00" })}</span></label>
          <label style={field}>{lab("Paid on (payment requisition)")}{inp("payment_ref", { placeholder: "e.g. PYR-MLE-401" })}</label>
        </div>
        <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "6px 0 0" }}>
          The fee is for the record. Pay the auditor on a payment requisition and note its reference here.</p>
        <label style={{ ...field, marginTop: 12 }}>{lab("Notes")}
          <textarea style={{ ...inputStyle, minHeight: 70 }} disabled={ro} value={f.notes} onChange={set("notes")} /></label>
        {canEdit && <div style={{ marginTop: 12 }}><Btn disabled={busy} onClick={save}>{isNew ? "Save the audit" : "Save"}</Btn></div>}
      </div>
      {!isNew && (<>
        <h2 className="t-h2" style={{ marginTop: 22 }}>Papers</h2>
        {a.files.length === 0 ? <div style={card}>Nothing uploaded yet.</div> : (
          <div style={{ ...card, padding: 0, overflowX: "auto" }}>
            <table className="f-table">
              <thead><tr><th>Document</th><th>File</th><th>Uploaded</th><th /></tr></thead>
              <tbody>{a.files.map((x) => (
                <tr key={x.id}>
                  <td><b>{x.kind_label}</b>{x.label && <span style={{ color: "var(--muted)" }}> · {x.label}</span>}</td>
                  <td><a href={x.url} target="_blank" rel="noreferrer">{x.name || "Open"}</a></td>
                  <td style={{ fontSize: 13, color: "var(--muted)" }}>{fmtDate(x.uploaded_at)}{x.uploaded_by ? ` · ${x.uploaded_by}` : ""}</td>
                  <td>{canEdit && <button className="f-link" onClick={() => remove(x)}>Remove</button>}</td>
                </tr>))}</tbody>
            </table>
          </div>)}
        {canEdit && (
          <div style={{ ...card, marginTop: 10 }}>
            <div className="f-bar" style={{ margin: 0, alignItems: "flex-end", flexWrap: "wrap" }}>
              <label style={{ ...field, width: 210 }}>{lab("Document")}
                <select style={inputStyle} value={up.kind} onChange={(e) => setUp({ ...up, kind: e.target.value })}>
                  {meta.file_kinds.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></label>
              <label style={{ ...field, width: 220 }}>{lab("Note (optional)")}
                <input style={inputStyle} value={up.label} onChange={(e) => setUp({ ...up, label: e.target.value })} /></label>
              <label style={field}>{lab("File")}
                <input type="file" key={a.files.length} onChange={(e) => setUp({ ...up, file: e.target.files[0] || null })} /></label>
              <Btn disabled={busy || !up.file} onClick={upload}>Upload</Btn>
            </div>
          </div>)}
        {a.fee_amount && <p style={{ fontSize: 13, color: "var(--muted)" }}>Agreed fee {a.fee_currency} {money(a.fee_amount)}{a.payment_ref ? ` · paid on ${a.payment_ref}` : " · no payment noted yet"}</p>}
      </>)}
    </div>
  );
}

// sub: null | new | <ref or id>
export default function AuditsPage({ sub, go }) {
  return sub ? <Audit ident={sub} go={go} key={sub} /> : <List go={go} />;
}
