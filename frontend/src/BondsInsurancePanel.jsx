import { useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Chip, buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Project bonds & insurance (owner 2026-08-03): APB / Performance Bond / CAR /
// Third-Party Liability. QS records the insurer quote → raises a PYR for the
// premium → uploads the issued policy + expiry once paid.

const KINDS = [
  ["APB", "Advance Payment Bond"],
  ["PB", "Performance Bond"],
  ["CAR", "Contractor's All-Risk Insurance"],
  ["TPL", "Third-Party Liability Insurance"],
  ["OTHER", "Other cover"],
];
const TONE = {
  REQUIRED: "warn", QUOTED: "info", PAYMENT_RAISED: "info", PAID: "info",
  ISSUED: "ok", EXPIRED: "warn", CANCELLED: "muted",
};
const money = (v, c) => v == null || v === ""
  ? "—" : `${c || ""} ${Number(v).toLocaleString("en-US",
      { maximumFractionDigits: 2 })}`.trim();
const fmt = (s) => s ? new Date(s).toLocaleDateString("en-GB",
  { day: "2-digit", month: "short", year: "numeric" }) : "—";
const lbl = { fontSize: 12, color: "var(--muted)", display: "block",
  marginBottom: 2 };

export default function BondsInsurancePanel({ projectId, me }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [quoteId, setQuoteId] = useState(null);   // edit-quote form open
  const [issueId, setIssueId] = useState(null);   // issue-policy form open

  const load = () => api(`/projects/${projectId}/bonds`).then(setData)
    .catch((e) => setError(e.message));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [projectId]);

  async function run(fn) {
    setBusy(true); setError(null);
    try { await fn(); await load(); }
    catch (e) { setError(e.message); }
    setBusy(false);
  }
  const raisePyr = (id) => run(() =>
    api(`/project-bonds/${id}/raise-pyr`, { method: "POST" }));
  const cancel = (id) => { if (window.confirm("Cancel this cover?"))
    run(() => api(`/project-bonds/${id}/cancel`, { method: "POST" })); };
  const del = (id) => { if (window.confirm("Delete this cover?"))
    run(() => api(`/project-bonds/${id}`, { method: "DELETE" })); };

  if (error && !data) return <section style={card}>
    <p style={{ color: "var(--red-fg)" }}>{error}</p></section>;
  if (!data) return <section style={card}>Loading bonds & insurance…</section>;
  const canEdit = data.can_edit;

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ margin: 0, color: "var(--sp-navy)" }}>Bonds &amp; Insurance</h3>
        {canEdit && !adding && <button style={buttonStyle}
          onClick={() => setAdding(true)}>+ Add cover</button>}
      </div>
      <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 4 }}>
        Mark which covers this client requires. Record the insurer's quote,
        raise the premium payment, then upload the issued policy &amp; expiry.
      </p>

      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      {data.gaps.length > 0 && (
        <div style={{ background: "#FBF0DC", border: "1px solid #E9CF97",
          borderRadius: 8, padding: "8px 12px", fontSize: 13, margin: "6px 0" }}>
          ⚠ Required cover not yet issued: <b>{data.gaps.join(", ")}</b>.
          The client may not process claims until these are in place.
        </div>)}

      {adding && <CoverForm mode="add" busy={busy}
        onCancel={() => setAdding(false)}
        onSave={(fd) => run(async () => {
          await apiUpload(`/projects/${projectId}/bonds`, fd); setAdding(false);
        })} />}

      {!data.bonds.length && !adding && <p style={{ color: "var(--muted)" }}>
        No covers added yet.</p>}

      {data.bonds.map((b) => (
        <div key={b.id} style={{ border: "1px solid var(--line)",
          borderRadius: 10, padding: 12, margin: "10px 0" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10,
            flexWrap: "wrap" }}>
            <b style={{ color: "var(--sp-navy)" }}>{b.kind_label}</b>
            {b.required ? <Chip tone="warn">required</Chip>
              : <Chip tone="muted">not required</Chip>}
            <Chip tone={TONE[b.status]}>{b.status_label}</Chip>
            {b.expiry_date && <span style={{ fontSize: 12,
              color: "var(--muted)" }}>expires {fmt(b.expiry_date)}</span>}
          </div>
          <div style={{ fontSize: 13, color: "#4a5a66", marginTop: 6,
            display: "flex", gap: 18, flexWrap: "wrap" }}>
            <span>Insurer: <b>{b.insurer || "—"}</b></span>
            <span>Insured value: {money(b.insured_value, b.currency)}</span>
            <span>Premium: {money(b.premium, b.currency)}</span>
            {b.quote_file_url && <a href={b.quote_file_url} target="_blank"
              rel="noreferrer">📎 quote</a>}
            {b.pyr_ref && <span>PYR: <b>{b.pyr_ref}</b> ({b.pyr_status})</span>}
            {b.policy_file_url && <a href={b.policy_file_url} target="_blank"
              rel="noreferrer">📄 policy</a>}
            {b.policy_ref && <span>Policy: {b.policy_ref}</span>}
          </div>

          {canEdit && b.status !== "CANCELLED" && (
            <div style={{ display: "flex", gap: 8, marginTop: 10,
              flexWrap: "wrap" }}>
              {["REQUIRED", "QUOTED"].includes(b.status) &&
                <button style={ghostButton} disabled={busy}
                  onClick={() => setQuoteId(quoteId === b.id ? null : b.id)}>
                  {b.premium ? "Edit quote" : "Record quote"}</button>}
              {["REQUIRED", "QUOTED"].includes(b.status) && b.premium &&
                <button style={buttonStyle} disabled={busy}
                  onClick={() => raisePyr(b.id)}>Raise payment (PYR)</button>}
              {b.status === "PAID" &&
                <button style={buttonStyle} disabled={busy}
                  onClick={() => setIssueId(issueId === b.id ? null : b.id)}>
                  Upload issued policy</button>}
              {b.status === "ISSUED" &&
                <button style={ghostButton} disabled={busy}
                  onClick={() => setIssueId(issueId === b.id ? null : b.id)}>
                  Update policy / expiry</button>}
              {["REQUIRED", "QUOTED"].includes(b.status) &&
                <button style={ghostButton} disabled={busy}
                  onClick={() => del(b.id)}>Delete</button>}
              {!["REQUIRED", "QUOTED", "CANCELLED"].includes(b.status) &&
                <button style={ghostButton} disabled={busy}
                  onClick={() => cancel(b.id)}>Cancel cover</button>}
            </div>)}

          {quoteId === b.id && <CoverForm mode="quote" bond={b} busy={busy}
            onCancel={() => setQuoteId(null)}
            onSave={(fd) => run(async () => {
              await apiUpload(`/project-bonds/${b.id}`, fd, "PATCH");
              setQuoteId(null);
            })} />}
          {issueId === b.id && <IssueForm bond={b} busy={busy}
            onCancel={() => setIssueId(null)}
            onSave={(fd) => run(async () => {
              await apiUpload(`/project-bonds/${b.id}/issue`, fd);
              setIssueId(null);
            })} />}
        </div>))}
    </section>
  );
}

function CoverForm({ mode, bond, busy, onCancel, onSave }) {
  const [f, setF] = useState({
    kind: bond?.kind || "PB", required: bond ? bond.required : true,
    insurer: bond?.insurer || "", insured_value: bond?.insured_value || "",
    currency: bond?.currency || "MVR", quote_ref: bond?.quote_ref || "",
    quote_date: bond?.quote_date || "", premium: bond?.premium || "",
  });
  const [file, setFile] = useState(null);
  const set = (k) => (e) => setF({ ...f,
    [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const submit = () => {
    const fd = new FormData();
    if (mode === "add") fd.append("kind", f.kind);
    fd.append("required", f.required ? "true" : "false");
    ["insurer", "insured_value", "currency", "quote_ref", "quote_date",
     "premium"].forEach((k) => fd.append(k, f[k] ?? ""));
    if (file) fd.append("quote_file", file);
    onSave(fd);
  };
  return (
    <div style={{ background: "var(--sky-soft, #eef6fb)", borderRadius: 8,
      padding: 12, marginTop: 10 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
        gap: 10 }}>
        {mode === "add" && <label><span style={lbl}>Cover type</span>
          <select style={inputStyle} value={f.kind} onChange={set("kind")}>
            {KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></label>}
        <label><span style={lbl}>Insurer</span>
          <input style={inputStyle} value={f.insurer} onChange={set("insurer")} /></label>
        <label style={{ alignSelf: "end", fontSize: 13 }}>
          <input type="checkbox" checked={f.required}
            onChange={set("required")} /> Required by this client</label>
        <label><span style={lbl}>Insured / bond value</span>
          <input type="number" style={inputStyle} value={f.insured_value}
            onChange={set("insured_value")} /></label>
        <label><span style={lbl}>Currency</span>
          <select style={inputStyle} value={f.currency} onChange={set("currency")}>
            <option>MVR</option><option>USD</option></select></label>
        <label><span style={lbl}>Premium (to pay)</span>
          <input type="number" style={inputStyle} value={f.premium}
            onChange={set("premium")} /></label>
        <label><span style={lbl}>Quote ref</span>
          <input style={inputStyle} value={f.quote_ref} onChange={set("quote_ref")} /></label>
        <label><span style={lbl}>Quote date</span>
          <input type="date" style={inputStyle} value={f.quote_date}
            onChange={set("quote_date")} /></label>
        <label><span style={lbl}>Quote file</span>
          <input type="file" onChange={(e) => setFile(e.target.files[0])} /></label>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button style={buttonStyle} disabled={busy} onClick={submit}>Save</button>
        <button style={ghostButton} disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function IssueForm({ bond, busy, onCancel, onSave }) {
  const [f, setF] = useState({ policy_ref: bond.policy_ref || "",
    issue_date: bond.issue_date || "", expiry_date: bond.expiry_date || "" });
  const [file, setFile] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = () => {
    const fd = new FormData();
    ["policy_ref", "issue_date", "expiry_date"].forEach((k) =>
      fd.append(k, f[k] ?? ""));
    if (file) fd.append("policy_file", file);
    onSave(fd);
  };
  return (
    <div style={{ background: "var(--sky-soft, #eef6fb)", borderRadius: 8,
      padding: 12, marginTop: 10 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
        gap: 10 }}>
        <label><span style={lbl}>Policy / bond ref</span>
          <input style={inputStyle} value={f.policy_ref}
            onChange={set("policy_ref")} /></label>
        <label><span style={lbl}>Issue date</span>
          <input type="date" style={inputStyle} value={f.issue_date}
            onChange={set("issue_date")} /></label>
        <label><span style={lbl}>Expiry date</span>
          <input type="date" style={inputStyle} value={f.expiry_date}
            onChange={set("expiry_date")} /></label>
        <label style={{ gridColumn: "1 / -1" }}>
          <span style={lbl}>Policy document</span>
          <input type="file" onChange={(e) => setFile(e.target.files[0])} /></label>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button style={buttonStyle} disabled={busy} onClick={submit}>
          Save policy</button>
        <button style={ghostButton} disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
