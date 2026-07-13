import { useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, card, ghostButton, inputStyle } from "./ui.jsx";

// Raise a Payment Request (PYR) — non-purchase site expenditure (§5.9).
// Site users raise it; it flows Site → PM → Director → Signatory → Finance.

const TYPES = [
  ["DIRECT", "Direct payment"], ["ADVANCE", "Advance"],
  ["REIMBURSEMENT", "Reimbursement"],
  ["SALARY_ADVANCE", "Salary advance / loan"],
];
const METHODS = [["BANK", "Bank transfer"], ["CASH", "Cash"],
                 ["CHEQUE", "Cheque"]];

const nextMonth = () => {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() + 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

// Head-Office centres may raise in USD as well as MVR; site teams are MVR only.
const USD_ROLES = ["HO_PURCHASING", "HO_HR", "FINANCE", "DIRECTOR",
                   "SIGNATORY", "QS", "ADMIN"];

export default function PaymentRequestForm({ site, sites, me, onSaved,
                                            onCancel }) {
  // Central raise (from a Head-Office area) passes `sites` to pick a filing
  // site; a site raise passes a fixed `site`.
  const central = !site && Array.isArray(sites);
  const allowUSD = me ? USD_ROLES.includes(me.role) : false;
  const [pickedSite, setPickedSite] = useState(() => {
    if (site) return site;
    const ho = (sites || []).find((s) => s.is_head_office);
    return ho || (sites || [])[0] || null;
  });
  const activeSite = site || pickedSite;

  const [heads, setHeads] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [f, setF] = useState({
    payment_type: "DIRECT", cost_head_id: "", payee: "",
    payment_method: "BANK", payee_account: "", amount_requested: "",
    currency: "MVR",
    required_by: "", purpose: "", is_urgent: false, urgent_reason: "",
    has_supporting_doc: true, no_doc_reason: "",
  });
  const [salaryLines, setSalaryLines] = useState([
    { employee_id: "", kind: "ADVANCE", amount: "", months: 1 }]);
  const [deductMonth, setDeductMonth] = useState(nextMonth());
  const [file, setFile] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const isSalary = f.payment_type === "SALARY_ADVANCE";
  const salaryTotal = salaryLines.reduce(
    (a, l) => a + (Number(l.amount) || 0), 0);

  useEffect(() => {
    api("/cost-heads").then(setHeads).catch(() => {});
    if (activeSite) {
      api(`/employees?site=${activeSite.id}`).then(setEmployees)
        .catch(() => {});
    }
  }, [activeSite?.id]);

  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  const setLine = (i, patch) => setSalaryLines((ls) =>
    ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  async function save() {
    // Explicit validation with a clear message — a disabled button reads
    // as "broken" (owner: site admin "can't save")
    const missing = [];
    if (!activeSite) missing.push("filing site / centre");
    if (!f.cost_head_id) missing.push("cost head");
    if (isSalary) {
      const clean = salaryLines.filter((l) => l.employee_id &&
                                              Number(l.amount) > 0);
      if (!clean.length) missing.push("at least one worker + amount");
    } else {
      if (!f.payee.trim()) missing.push("payee");
      if (!f.amount_requested) missing.push("amount");
    }
    if (!f.purpose.trim() && !isSalary) missing.push("purpose");
    if (missing.length) {
      setError(`Please fill in: ${missing.join(", ")}.`);
      return;
    }
    const [dy, dm] = deductMonth.split("-");
    setBusy(true);
    setError(null);
    try {
      const body = {
        doc_type: "PYR", site_id: activeSite.id, payload: {},
        cost_head_id: f.cost_head_id, payee: f.payee,
        payment_type: f.payment_type, payment_method: f.payment_method,
        payee_account: f.payee_account,
        currency: allowUSD ? f.currency : "MVR",
        amount_requested: f.amount_requested,
        required_by: f.required_by || null, purpose: f.purpose,
        is_urgent: f.is_urgent, urgent_reason: f.urgent_reason,
        has_supporting_doc: f.has_supporting_doc && !!file,
        no_doc_reason: f.no_doc_reason,
      };
      if (isSalary) {
        body.salary_lines = salaryLines
          .filter((l) => l.employee_id && Number(l.amount) > 0)
          .map((l) => ({ employee_id: +l.employee_id, kind: l.kind,
                         amount: Number(l.amount),
                         months: l.kind === "LOAN" ? +l.months || 1 : 1 }));
        body.deduct_year = +dy;
        body.deduct_month = +dm;
      }
      const doc = await api("/documents", { method: "POST", body });
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
          New Payment Request{activeSite ? ` — ${activeSite.code}` : ""}
        </h2>
        <button onClick={onCancel} style={ghostButton}>Cancel</button>
      </div>
      <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 4 }}>
        For non-purchase spend — rent, subcontractors, boat hire, permits,
        utilities, staff transport. Material purchases go through an MR.
        {central && " Head-Office requests skip the site PM."}
      </p>

      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "1fr 1fr",
                    marginTop: 12 }}>
        {central && (
          <label style={{ fontSize: 13 }}>File under
            <select value={pickedSite?.id || ""}
                    onChange={(e) => setPickedSite((sites || []).find(
                      (s) => String(s.id) === e.target.value) || null)}
                    style={inputStyle}>
              {(sites || []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.code} — {s.name}{s.is_head_office ? " (HO)" : ""}</option>
              ))}
            </select>
          </label>
        )}
        {allowUSD && (
          <label style={{ fontSize: 13 }}>Currency
            <select value={f.currency}
                    onChange={(e) => set("currency", e.target.value)}
                    style={inputStyle}>
              <option value="MVR">MVR</option>
              <option value="USD">USD</option>
            </select>
          </label>
        )}
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
        {!isSalary && (
        <label style={{ fontSize: 13 }}>Payee / vendor
          <input value={f.payee} onChange={(e) => set("payee", e.target.value)}
                 style={inputStyle} />
        </label>
        )}
        <label style={{ fontSize: 13 }}>Payment method
          <select value={f.payment_method}
                  onChange={(e) => set("payment_method", e.target.value)}
                  style={inputStyle}>
            {METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        {!isSalary && (
        <label style={{ fontSize: 13 }}>Payee account / details
          <input value={f.payee_account}
                 onChange={(e) => set("payee_account", e.target.value)}
                 style={inputStyle} />
        </label>
        )}
        {!isSalary && (
        <label style={{ fontSize: 13 }}>
          Amount ({allowUSD ? f.currency : "MVR"})
          <input type="number" min="0" value={f.amount_requested}
                 onChange={(e) => set("amount_requested", e.target.value)}
                 style={{ ...inputStyle, fontFamily: "var(--font-mono)" }} />
        </label>
        )}
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

      {isSalary && (
        <div style={{ marginTop: 14, padding: 12, borderRadius: 8,
                      background: "var(--sp-tint, #f5f8fb)" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                        flexWrap: "wrap", marginBottom: 8 }}>
            <strong style={{ fontSize: 13, color: "var(--navy)" }}>
              Workers</strong>
            <label style={{ fontSize: 12.5 }}>Deduct from payroll{" "}
              <input type="month" value={deductMonth}
                     onChange={(e) => setDeductMonth(e.target.value)}
                     style={{ ...inputStyle, width: 150, display: "inline" }} />
            </label>
            <span style={{ marginLeft: "auto", fontSize: 13, fontWeight: 700,
                           color: "var(--navy)" }}>
              Total: {salaryTotal.toLocaleString()}</span>
          </div>
          {salaryLines.map((l, i) => (
            <div key={i} style={{ display: "flex", gap: 8, marginBottom: 6,
                                  flexWrap: "wrap", alignItems: "center" }}>
              <select value={l.employee_id}
                      onChange={(e) => setLine(i, { employee_id: e.target.value })}
                      style={{ ...inputStyle, flex: "1 1 200px" }}>
                <option value="">— worker —</option>
                {employees.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.emp_no} — {e.full_name}</option>
                ))}
              </select>
              <select value={l.kind}
                      onChange={(e) => setLine(i, { kind: e.target.value })}
                      style={{ ...inputStyle, width: 110 }}>
                <option value="ADVANCE">Advance</option>
                <option value="LOAN">Loan</option>
              </select>
              <input type="number" min="0" placeholder="Amount" value={l.amount}
                     onChange={(e) => setLine(i, { amount: e.target.value })}
                     style={{ ...inputStyle, width: 110 }} />
              {l.kind === "LOAN" && (
                <input type="number" min="1" placeholder="months" value={l.months}
                       title="Number of months to spread the loan"
                       onChange={(e) => setLine(i, { months: e.target.value })}
                       style={{ ...inputStyle, width: 80 }} />
              )}
              {salaryLines.length > 1 && (
                <button onClick={() => setSalaryLines((ls) =>
                          ls.filter((_, j) => j !== i))}
                        style={{ ...ghostButton, padding: "2px 8px" }}>✕</button>
              )}
            </div>
          ))}
          <button onClick={() => setSalaryLines((ls) => [...ls,
                    { employee_id: "", kind: "ADVANCE", amount: "", months: 1 }])}
                  style={ghostButton}>+ Add worker</button>
          <p style={{ fontSize: 11.5, color: "var(--faint)", margin: "8px 0 0" }}>
            One PYR for the whole request. Advances deduct in full next payroll;
            loans spread over the months you set. Deductions appear once Finance
            pays this PYR.
          </p>
        </div>
      )}

      <label style={{ fontSize: 13, display: "block", marginTop: 12 }}>
        Purpose / description
        <textarea rows={2} value={f.purpose}
                  onChange={(e) => set("purpose", e.target.value)}
                  placeholder={isSalary ? "e.g. Ramadan advance for site crew"
                                        : ""}
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
        <Btn variant="primary" onClick={save} disabled={busy}>
          {busy ? "Saving…" : "Save draft"}
        </Btn>
        <span style={{ fontSize: 12, color: "var(--faint)", marginLeft: 12 }}>
          Saves a draft — submit it for approval on the next screen.
        </span>
      </div>
    </section>
  );
}
