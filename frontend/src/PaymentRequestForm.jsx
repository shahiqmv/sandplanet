import { useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, card, ghostButton, inputStyle } from "./ui.jsx";

// Raise a Payment Request (PYR) — non-purchase site expenditure (§5.9).
// Site users raise it; it flows Site → PM → Director → Signatory → Finance.

const TYPES = [
  ["DIRECT", "Direct payment"], ["ADVANCE", "Advance"],
  ["REIMBURSEMENT", "Reimbursement"],
];
const METHODS = [["BANK", "Bank transfer"], ["CASH", "Cash"],
                 ["CHEQUE", "Cheque"]];

export default function PaymentRequestForm({ site, onSaved, onCancel }) {
  const [heads, setHeads] = useState([]);
  const [f, setF] = useState({
    payment_type: "DIRECT", cost_head_id: "", payee: "",
    payment_method: "BANK", payee_account: "", amount_requested: "",
    required_by: "", purpose: "", is_urgent: false, urgent_reason: "",
    has_supporting_doc: true, no_doc_reason: "",
  });
  const [file, setFile] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/cost-heads").then(setHeads).catch(() => {});
  }, []);

  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const doc = await api("/documents", { method: "POST", body: {
        doc_type: "PYR", site_id: site.id, payload: {},
        cost_head_id: f.cost_head_id, payee: f.payee,
        payment_type: f.payment_type, payment_method: f.payment_method,
        payee_account: f.payee_account,
        amount_requested: f.amount_requested,
        required_by: f.required_by || null, purpose: f.purpose,
        is_urgent: f.is_urgent, urgent_reason: f.urgent_reason,
        has_supporting_doc: f.has_supporting_doc && !!file,
        no_doc_reason: f.no_doc_reason,
      } });
      if (file) {
        const fd = new FormData();
        fd.append("file", file);
        fd.append("kind", "EVIDENCE");
        await apiUpload(`/documents/${doc.ref}/attachments`, fd);
      }
      onSaved(doc.ref);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline" }}>
        <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 17 }}>
          New Payment Request — {site.code}
        </h2>
        <button onClick={onCancel} style={ghostButton}>Cancel</button>
      </div>
      <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 4 }}>
        For non-purchase spend — boat hire, subcontractors, rentals,
        permits, staff transport. Material purchases go through an MR.
      </p>

      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "1fr 1fr",
                    marginTop: 12 }}>
        <label style={{ fontSize: 13 }}>Payment type
          <select value={f.payment_type}
                  onChange={(e) => set("payment_type", e.target.value)}
                  style={inputStyle}>
            {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Cost head
          <select value={f.cost_head_id}
                  onChange={(e) => set("cost_head_id", e.target.value)}
                  style={inputStyle}>
            <option value="">— select —</option>
            {heads.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Payee / vendor
          <input value={f.payee} onChange={(e) => set("payee", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Payment method
          <select value={f.payment_method}
                  onChange={(e) => set("payment_method", e.target.value)}
                  style={inputStyle}>
            {METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Payee account / details
          <input value={f.payee_account}
                 onChange={(e) => set("payee_account", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Amount (MVR)
          <input type="number" min="0" value={f.amount_requested}
                 onChange={(e) => set("amount_requested", e.target.value)}
                 style={{ ...inputStyle, fontFamily: "var(--font-mono)" }} />
        </label>
        <label style={{ fontSize: 13 }}>Required by
          <input type="date" value={f.required_by}
                 onChange={(e) => set("required_by", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13, display: "flex", alignItems: "center",
                        gap: 6, marginTop: 20 }}>
          <input type="checkbox" checked={f.is_urgent}
                 onChange={(e) => set("is_urgent", e.target.checked)} />
          Urgent
        </label>
      </div>

      <label style={{ fontSize: 13, display: "block", marginTop: 12 }}>
        Purpose / description
        <textarea rows={2} value={f.purpose}
                  onChange={(e) => set("purpose", e.target.value)}
                  style={{ ...inputStyle, resize: "vertical" }} />
      </label>
      {f.is_urgent && (
        <label style={{ fontSize: 13, display: "block", marginTop: 8 }}>
          Reason for urgency
          <input value={f.urgent_reason}
                 onChange={(e) => set("urgent_reason", e.target.value)}
                 style={inputStyle} />
        </label>
      )}

      <div style={{ marginTop: 12, padding: 12, borderRadius: 8,
                    border: "1px dashed var(--line)" }}>
        <label style={{ fontSize: 13 }}>Supporting document (bill / quote /
          receipt){" "}
          <input type="file" onChange={(e) => setFile(e.target.files[0])} />
        </label>
        {!file && (
          <label style={{ fontSize: 13, display: "block", marginTop: 8 }}>
            No supporting document — reason (required if none attached)
            <input value={f.no_doc_reason}
                   onChange={(e) => set("no_doc_reason", e.target.value)}
                   placeholder="e.g. informal boat-crew payment"
                   style={inputStyle} />
          </label>
        )}
        <p style={{ fontSize: 11.5, color: "var(--faint)", margin: "6px 0 0" }}>
          Above MVR 5,000 an attachment (or a PM override) is required.
        </p>
      </div>

      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      <div style={{ marginTop: 14 }}>
        <Btn variant="primary" onClick={save}
             disabled={busy || !f.cost_head_id || !f.payee ||
                       !f.amount_requested || !f.purpose}>
          Save draft
        </Btn>
      </div>
    </section>
  );
}
