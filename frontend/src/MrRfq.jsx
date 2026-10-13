import { useCallback, useEffect, useState } from "react";
import { api, apiDownload, apiUpload } from "./api.js";
import { SectionTitle, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

// Requests for quotation on an MR (owner 2026-10-13). Purchasing picks the
// items, names the supplier (mandatory: the RFQ stays on the MR's record),
// adds a remark for the supplier and prints the RFQ. The supplier's quote
// is uploaded against it here, and the PR picks it up from here.

function fmt(d) {
  if (!d) return "";
  const x = new Date(d);
  return Number.isNaN(x.getTime()) ? String(d)
    : x.toLocaleDateString("en-GB", { day: "2-digit", month: "short",
                                       year: "numeric" });
}

function NewRfq({ mrRef, lines, onClose, onDone }) {
  const [pick, setPick] = useState(() => Object.fromEntries(
    lines.filter((l) => !l.ordered_pr).map((l) => [l.id, true])));
  const [suppliers, setSuppliers] = useState([]);
  const [supplierId, setSupplierId] = useState("");
  const [newName, setNewName] = useState("");
  const [remark, setRemark] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => {
    api("/suppliers").then((l) => setSuppliers(
      (l || []).filter((s) => s.is_active !== false)
        .sort((a, b) => a.name.localeCompare(b.name))))
      .catch(() => setSuppliers([]));
  }, []);
  const chosen = lines.filter((l) => pick[l.id]).map((l) => l.id);
  const allOn = lines.length > 0 && chosen.length === lines.length;

  async function create() {
    if (!chosen.length) { setError("Tick the items to ask for."); return; }
    if (supplierId === "new" ? !newName.trim() : !supplierId) {
      setError("Name the supplier — the RFQ is kept on the MR's record.");
      return;
    }
    setBusy(true); setError(null);
    try {
      const rfq = await api(`/mr/${mrRef}/rfqs`, { method: "POST", body: {
        line_ids: chosen, remark,
        ...(supplierId === "new" ? { supplier_name: newName.trim() }
                                 : { supplier_id: +supplierId }) } });
      await apiDownload(`/mr-rfqs/${rfq.id}/pdf`);
      onDone();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div onClick={onClose}
         style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.4)",
                  display: "flex", alignItems: "flex-start",
                  justifyContent: "center", zIndex: 60, padding: "40px 16px",
                  overflowY: "auto" }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ ...card, maxWidth: 720, width: "100%" }}>
        <h3 style={{ marginTop: 0 }}>Request for quotation — {mrRef}</h3>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 13 }}>
          <thead><tr>
            <th style={{ ...th, width: 34 }}>
              <input type="checkbox" checked={allOn}
                title="All items"
                onChange={() => setPick(Object.fromEntries(
                  lines.map((l) => [l.id, !allOn])))} /></th>
            <th style={th}>Item</th>
            <th style={{ ...th, width: 70 }}>Unit</th>
            <th style={{ ...th, width: 80, textAlign: "right" }}>Qty</th>
          </tr></thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.id} onClick={() => setPick((p) => ({ ...p, [l.id]: !p[l.id] }))}
                  style={{ cursor: "pointer",
                           background: pick[l.id] ? "#fff7e0" : undefined }}>
                <td style={td}><input type="checkbox" checked={!!pick[l.id]}
                  onChange={() => {}} /></td>
                <td style={td}>{l.description}
                  {l.ordered_pr && <span style={{ color: "#8a949c", fontSize: 11.5 }}>
                    {" "}· on {l.ordered_pr}</span>}</td>
                <td style={td}>{l.unit}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {l.qty != null ? Number(l.qty) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                      gap: 10, marginTop: 12 }}>
          <label style={{ fontSize: 13 }}>Supplier *
            <select style={inputStyle} value={supplierId}
              onChange={(e) => setSupplierId(e.target.value)}>
              <option value="">Choose the supplier…</option>
              <option value="new">+ A supplier not on the list</option>
              {suppliers.map((s) => <option key={s.id} value={s.id}>
                {s.name}</option>)}
            </select>
          </label>
          {supplierId === "new" && (
            <label style={{ fontSize: 13 }}>New supplier's name *
              <input style={inputStyle} value={newName} autoFocus
                onChange={(e) => setNewName(e.target.value)} />
            </label>)}
          <label style={{ fontSize: 13, gridColumn: "1 / -1" }}>
            Remark for the supplier (printed on the RFQ)
            <textarea rows={3} style={{ ...inputStyle, resize: "vertical" }}
              value={remark} onChange={(e) => setRemark(e.target.value)}
              placeholder="e.g. Quote ex-stock items only; delivery to the Malé jetty." />
          </label>
        </div>
        {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
        <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
          <button onClick={create} disabled={busy} style={buttonStyle}>
            {busy ? "Preparing…" : `Create RFQ for ${chosen.length} item${
              chosen.length === 1 ? "" : "s"} and download`}</button>
          <button onClick={onClose} style={ghostButton}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

function UploadQuote({ rfq, onDone }) {
  const [file, setFile] = useState(null);
  const [qref, setQref] = useState("");
  const [qdate, setQdate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function save() {
    if (!file) { setError("Choose the quote file."); return; }
    setBusy(true); setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (qref) fd.append("quote_ref", qref);
      if (qdate) fd.append("quote_date", qdate);
      await apiUpload(`/mr-rfqs/${rfq.id}/quote`, fd, "POST");
      onDone();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return (
    <div style={{ display: "flex", gap: 6, alignItems: "center",
                  flexWrap: "wrap", marginTop: 4 }}>
      <input type="file" accept="image/*,.pdf" style={{ fontSize: 12 }}
        onChange={(e) => setFile(e.target.files?.[0] || null)} />
      <input placeholder="Supplier's quote no." value={qref}
        onChange={(e) => setQref(e.target.value)}
        style={{ ...inputStyle, width: 150, padding: "4px 6px" }} />
      <input type="date" value={qdate} onChange={(e) => setQdate(e.target.value)}
        style={{ ...inputStyle, width: 140, padding: "4px 6px" }} />
      <button onClick={save} disabled={busy}
        style={{ ...ghostButton, padding: "4px 10px", fontSize: 12.5 }}>
        Upload quote</button>
      {error && <span style={{ color: "#c0392b", fontSize: 12 }}>{error}</span>}
    </div>
  );
}

export default function MrRfqPanel({ doc, me }) {
  const [d, setD] = useState(null);
  const [making, setMaking] = useState(false);
  const [upFor, setUpFor] = useState(null);
  const load = useCallback(() => {
    api(`/mr/${doc.ref}/rfqs`).then(setD).catch(() => setD(null));
  }, [doc.ref]);
  useEffect(() => { load(); }, [load]);
  if (!d || (!d.rfqs.length && !d.can_send)) return null;
  const purchasing = ["HO_PURCHASING", "ADMIN"].includes(me.role);

  return (
    <div style={{ ...card, marginTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <SectionTitle>Requests for quotation</SectionTitle>
        {d.can_send && (
          <button onClick={() => setMaking(true)}
            style={{ ...buttonStyle, marginLeft: "auto" }}>
            📨 Request quotes</button>)}
      </div>
      {!d.rfqs.length ? (
        <p style={{ fontSize: 13, color: "#5a6b78", margin: "6px 0 0" }}>
          No RFQ sent yet. Pick the items, name the supplier, and print an RFQ
          to send; upload the supplier's quote here when it comes back.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 13, marginTop: 6 }}>
          <thead><tr>
            <th style={th}>RFQ</th><th style={th}>Supplier</th>
            <th style={th}>Items</th><th style={th}>Sent</th>
            <th style={th}>Quote</th><th style={th}></th>
          </tr></thead>
          <tbody>
            {d.rfqs.map((r) => (
              <tr key={r.id}>
                <td style={{ ...td, fontFamily: "monospace" }}>{r.ref}</td>
                <td style={td}>{r.supplier}
                  {r.remark && <div style={{ fontSize: 11.5, color: "#5a6b78" }}>
                    “{r.remark}”</div>}</td>
                <td style={td} title={r.lines.map((l) => l.description).join("\n")}>
                  {r.lines.length}</td>
                <td style={td}>{fmt(r.created_at)}
                  <div style={{ fontSize: 11.5, color: "#5a6b78" }}>{r.created_by}</div></td>
                <td style={td}>
                  {r.quote_url ? (<>
                    <a href={r.quote_url} target="_blank" rel="noreferrer">
                      {r.quote_ref || r.quote_name || "quote"}</a>
                    <div style={{ fontSize: 11.5, color: "#5a6b78" }}>
                      received {fmt(r.received_at)}
                      {r.used_on.length > 0 && ` · on ${r.used_on.join(", ")}`}</div>
                  </>) : purchasing ? (
                    upFor === r.id
                      ? <UploadQuote rfq={r} onDone={() => { setUpFor(null); load(); }} />
                      : <button onClick={() => setUpFor(r.id)}
                          style={{ ...ghostButton, padding: "3px 9px", fontSize: 12 }}>
                          Upload quote</button>
                  ) : <span style={{ color: "#8a949c" }}>awaiting</span>}
                </td>
                <td style={td}>
                  <button onClick={() => apiDownload(`/mr-rfqs/${r.id}/pdf`)}
                    style={{ ...ghostButton, padding: "3px 9px", fontSize: 12 }}
                    title="Print the RFQ again">PDF</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {making && <NewRfq mrRef={doc.ref} lines={d.lines}
        onClose={() => setMaking(false)}
        onDone={() => { setMaking(false); load(); }} />}
    </div>
  );
}

// On the PR: quotes that came back against its MRs' RFQs, ready to take in.
export function RfqQuotePicker({ prRef, onTaken }) {
  const [list, setList] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    api(`/pr/${prRef}/rfq-quotes`).then(setList).catch(() => setList([]));
  }, [prRef]);
  useEffect(() => { load(); }, [load]);
  if (!list.length) return null;
  async function take(id) {
    setBusy(true); setError(null);
    try {
      await api(`/pr/${prRef}/rfq-quotes`, { method: "POST",
                                             body: { rfq_id: id } });
      load();
      onTaken?.();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return (
    <div style={{ marginTop: 10, padding: "8px 12px", borderRadius: 8,
                  background: "#eef4fb", border: "1px solid #bcd3e8",
                  fontSize: 13 }}>
      <b>Quotes received against this MR's RFQs</b>
      {list.map((r) => (
        <div key={r.id} style={{ display: "flex", gap: 10, alignItems: "center",
                                 marginTop: 6, flexWrap: "wrap" }}>
          <span style={{ fontFamily: "monospace" }}>{r.ref}</span>
          <span>{r.supplier}</span>
          <span style={{ color: "#5a6b78" }}>{r.lines.length} item(s)
            {r.quote_ref ? ` · ${r.quote_ref}` : ""}</span>
          {r.quote_url && <a href={r.quote_url} target="_blank" rel="noreferrer">
            view quote</a>}
          <button disabled={busy} onClick={() => take(r.id)}
            style={{ ...buttonStyle, padding: "4px 12px", marginLeft: "auto" }}>
            Use this quote</button>
        </div>
      ))}
      {error && <p style={{ color: "#c0392b", margin: "6px 0 0" }}>{error}</p>}
    </div>
  );
}
