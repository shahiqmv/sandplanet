import { useState } from "react";
import { api } from "./api.js";
import { Btn, card, inputStyle } from "./ui.jsx";

// A man who came in on the subcontractor's visa and turned out to be worth
// keeping. He is already on the site's manpower list; what he is not is an
// employee — a subcontract worker deliberately carries no pay and is barred
// from payroll, so hiring him needs a salary and a category, not a flag flip
// (owner 2026-09-10).
export default function HireForm({ worker, cats, onCancel, onDone }) {
  const [f, setF] = useState({ basic_pay: "", currency: "MVR",
    job_category_id: worker.job_category_id || "",
    employment_type: "CONTRACT", join_date: worker.join_date || "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api(`/employees/${worker.id}/take-on-directly`,
                { method: "POST", body: f });
      onDone();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit} style={{ ...card, background: "var(--paper)",
                                     margin: "8px 0" }}>
      <strong style={{ fontSize: 14 }}>Hire {worker.full_name} directly</strong>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      <div style={{ display: "grid", gap: 8, gridTemplateColumns: "1fr 1fr",
                    marginTop: 8 }}>
        <input style={inputStyle} placeholder="Basic pay *" value={f.basic_pay}
               onChange={set("basic_pay")} autoFocus />
        <select style={inputStyle} value={f.currency}
                onChange={set("currency")}>
          <option value="MVR">MVR</option><option value="USD">USD</option>
        </select>
        <select style={inputStyle} value={f.job_category_id}
                onChange={set("job_category_id")}>
          <option value="">Worker category *…</option>
          {cats.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>))}
        </select>
        <select style={inputStyle} value={f.employment_type}
                onChange={set("employment_type")}>
          <option value="CONTRACT">Contract</option>
          <option value="PERMANENT">Permanent</option>
        </select>
        <label style={{ fontSize: 12, color: "var(--muted)" }}>
          Our employment starts
          <input type="date" style={inputStyle} value={f.join_date}
                 onChange={set("join_date")} />
        </label>
      </div>
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "8px 0 0" }}>
        He leaves the subcontractor's team and joins the payroll from this
        date. If he worked for them first, that is the day you hire him — not
        the day he arrived.
      </p>
      <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
        <Btn variant="navy" disabled={busy || !f.basic_pay.trim()
                                      || !f.job_category_id}>
          Hire onto payroll</Btn>
        <Btn type="button" variant="ghost" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}
