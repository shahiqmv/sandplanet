// The inquiry register — every trading inquiry, by stage, with the chase
// date. Everyone in trading sees every row; the owner (or the Sales
// Manager) works it.
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Btn, Chip, card, inputStyle, td, th } from "../ui.jsx";
import { StageChip, fmtDate, fmtMoney } from "./shared.jsx";

const VIA = [["EMAIL", "Email"], ["PHONE", "Phone"], ["WHATSAPP", "WhatsApp"],
             ["VISIT", "Visit"], ["OTHER", "Other"]];

export function NewInquiryForm({ onSaved, onCancel }) {
  const [customers, setCustomers] = useState([]);
  const [d, setD] = useState({ customer: "", title: "", received_via: "EMAIL",
                               customer_ref: "", currency: "", next_action: "",
                               next_action_date: "", notes: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("/trading/customers").then(setCustomers).catch(() => {}); }, []);
  const set = (k) => (e) => setD({ ...d, [k]: e.target.value });
  const cust = customers.find((c) => String(c.id) === String(d.customer));

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = { ...d, customer: Number(d.customer) };
    if (!body.currency) delete body.currency;
    if (!body.next_action_date) body.next_action_date = null;
    try {
      onSaved(await api("/trading/orders", { method: "POST", body }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} style={{ ...card, marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>New inquiry</h3>
      <div className="t-grid">
        <label className="t-field t-field-wide">
          <span>Customer</span>
          <select style={inputStyle} value={d.customer} onChange={set("customer")} required autoFocus>
            <option value="">— pick the customer —</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.name}{c.island ? ` · ${c.island}` : ""}</option>)}
          </select>
        </label>
        <label className="t-field t-field-wide">
          <span>What they asked for</span>
          <input style={inputStyle} value={d.title} onChange={set("title")}
                 placeholder="e.g. Pool tiles and grout for the new wing" required />
        </label>
        <label className="t-field">
          <span>Received via</span>
          <select style={inputStyle} value={d.received_via} onChange={set("received_via")}>
            {VIA.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="t-field">
          <span>Their reference</span>
          <input style={inputStyle} value={d.customer_ref} onChange={set("customer_ref")}
                 placeholder="their RFQ / email ref" />
        </label>
        <label className="t-field">
          <span>Quote in</span>
          <select style={inputStyle} value={d.currency} onChange={set("currency")}>
            <option value="">{cust ? `${cust.default_currency} (customer default)` : "customer default"}</option>
            <option value="MVR">MVR</option>
            <option value="USD">USD</option>
          </select>
        </label>
        <label className="t-field">
          <span>Next action</span>
          <input style={inputStyle} value={d.next_action} onChange={set("next_action")}
                 placeholder="e.g. get supplier prices" />
        </label>
        <label className="t-field">
          <span>By</span>
          <input style={inputStyle} type="date" value={d.next_action_date} onChange={set("next_action_date")} />
        </label>
        <label className="t-field t-field-wide">
          <span>Notes</span>
          <textarea style={{ ...inputStyle, minHeight: 56 }} value={d.notes} onChange={set("notes")} />
        </label>
      </div>
      {error && <p className="t-note t-note-red">{error}</p>}
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Btn type="submit" disabled={busy || !d.customer || !d.title.trim()}>
          {busy ? "Saving…" : "Log inquiry"}
        </Btn>
        <Btn type="button" variant="secondary" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}

const FILTERS = [["open", "Open"], ["INQUIRY", "Inquiry"], ["SOURCING", "Sourcing"],
                 ["PRICING", "Pricing"], ["QUOTED", "Quoted"], ["WON", "Won"],
                 ["LOST", "Lost"], ["", "All"]];

export default function InquiriesPage({ me, canWrite, open, initialStage }) {
  const [rows, setRows] = useState(null);
  const [stage, setStage] = useState(initialStage || "open");
  const [mine, setMine] = useState(me.role === "SALES" || ((me.extra_roles || []).includes("SALES") && !(me.extra_roles || []).includes("SALES_MANAGER") && me.role !== "SALES_MANAGER" && me.role !== "ADMIN"));
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);

  function load() {
    const q = new URLSearchParams();
    if (stage) q.set("stage", stage);
    if (mine) q.set("mine", "1");
    if (search.trim()) q.set("search", search.trim());
    return api(`/trading/orders?${q}`).then(setRows).catch(() => setRows([]));
  }
  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [stage, mine, search]);

  const today = new Date().toISOString().slice(0, 10);

  return (
    <div className="t-page">
      <div className="t-page-head">
        <h1 className="t-h1">Inquiries</h1>
        <div className="t-tools">
          <input style={{ ...inputStyle, width: 220 }} placeholder="Search ref, customer, title…"
                 value={search} onChange={(e) => setSearch(e.target.value)} />
          <label className="t-check">
            <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />
            mine only
          </label>
          {canWrite && !creating && <Btn onClick={() => setCreating(true)}>+ New inquiry</Btn>}
        </div>
      </div>

      <div className="t-filters">
        {FILTERS.map(([v, l]) => (
          <button key={v || "all"} className={"t-filter" + (stage === v ? " is-active" : "")}
                  onClick={() => setStage(v)}>{l}</button>
        ))}
      </div>

      {creating && (
        <NewInquiryForm onSaved={(o) => { setCreating(false); open(o.id); }}
                        onCancel={() => setCreating(false)} />
      )}

      {rows === null ? <p>Loading…</p> : rows.length === 0 ? (
        <p className="t-empty">
          {search || stage !== "open" ? "Nothing matches." :
            "No open inquiries. Log the next one the moment a customer asks — the register is the chase list."}
        </p>
      ) : (
        <table className="t-table">
          <thead>
            <tr>
              <th style={th}>Ref</th>
              <th style={th}>Customer</th>
              <th style={th}>Inquiry</th>
              <th style={th}>Stage</th>
              <th style={th}>Owner</th>
              <th style={th}>Next action</th>
              <th style={{ ...th, textAlign: "right" }}>Quoted</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((o) => (
              <tr key={o.id} className="t-row-link" onClick={() => open(o.id)}>
                <td style={td}>
                  <b>{o.ref}</b>
                  {o.so_ref && <div className="t-sub">{o.so_ref}</div>}
                </td>
                <td style={td}>{o.customer_name}</td>
                <td style={td}>
                  {o.title}
                  <div className="t-sub">since {fmtDate(o.inquiry_date)}</div>
                </td>
                <td style={td}><StageChip stage={o.stage} /></td>
                <td style={td}>{o.owner_name}</td>
                <td style={td}>
                  {o.next_action}
                  {o.next_action_date && (
                    <div className="t-sub">
                      {o.next_action_date < today && !["WON", "LOST"].includes(o.stage)
                        ? <Chip tone="alert">overdue {fmtDate(o.next_action_date)}</Chip>
                        : fmtDate(o.next_action_date)}
                    </div>
                  )}
                </td>
                <td style={{ ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {o.n_lines ? `${o.currency} ${fmtMoney(o.total)}` : <span className="t-sub">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
