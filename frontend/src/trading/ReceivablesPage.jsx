// Receivables — what trading customers owe, by age; Finance records the
// money that comes in (one receipt, many invoices, oldest first) and any
// customer's statement of account prints from here.
import { Fragment, useEffect, useState } from "react";
import { api } from "../api.js";
import { Btn, Chip, card, inputStyle, td, th } from "../ui.jsx";
import { fmtDate, fmtMoney } from "./shared.jsx";

const METHODS = [["TT", "Telegraphic transfer"], ["CHEQUE", "Cheque"], ["CASH", "Cash"],
                 ["CARD", "Card"], ["OTHER", "Other"]];

function ReceiptForm({ customers, onSaved, onCancel, preset }) {
  const [d, setD] = useState({ customer: preset || "", receipt_date: new Date().toISOString().slice(0, 10),
                               method: "TT", reference: "", bank_account: "", note: "", amount: "" });
  const [info, setInfo] = useState(null);
  const [alloc, setAlloc] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setD({ ...d, [k]: e.target.value });

  useEffect(() => {
    if (!d.customer) { setInfo(null); return; }
    api(`/trading/receipts/allocate?customer=${d.customer}&amount=${d.amount || 0}`)
      .then((x) => { setInfo(x); setAlloc(x.allocations); })
      .catch((e) => setError(e.message));
  }, [d.customer, d.amount]);

  const allocated = alloc.reduce((a, x) => a + (Number(x.amount) || 0), 0);
  function setAmount(invId, v) {
    setAlloc((rows) => {
      const has = rows.find((r) => r.invoice_id === invId);
      const inv = info.open_invoices.find((i) => i.id === invId);
      const row = { invoice_id: invId, invoice: inv.ref, amount: v, outstanding: inv.outstanding };
      return has ? rows.map((r) => (r.invoice_id === invId ? row : r)) : [...rows, row];
    });
  }

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSaved(await api("/trading/receipts", { method: "POST", body: {
        ...d, customer: Number(d.customer), bank_account: d.bank_account || null,
        allocations: alloc.filter((a) => Number(a.amount) > 0) } }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} style={{ ...card, marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>Record a customer payment</h3>
      <div className="t-grid">
        <label className="t-field"><span>Customer</span>
          <select style={inputStyle} value={d.customer} onChange={set("customer")} required autoFocus>
            <option value="">— pick —</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select></label>
        <label className="t-field"><span>Amount received</span>
          <input style={inputStyle} type="number" step="0.01" min="0" value={d.amount} onChange={set("amount")} /></label>
        <label className="t-field"><span>Date</span>
          <input style={inputStyle} type="date" value={d.receipt_date} onChange={set("receipt_date")} required /></label>
        <label className="t-field"><span>How</span>
          <select style={inputStyle} value={d.method} onChange={set("method")}>
            {METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></label>
        <label className="t-field"><span>Reference (TT / cheque no.)</span>
          <input style={inputStyle} value={d.reference} onChange={set("reference")} /></label>
        <label className="t-field"><span>Into bank account</span>
          <select style={inputStyle} value={d.bank_account} onChange={set("bank_account")}>
            <option value="">—</option>
            {(info?.bank_accounts || []).map((b) => <option key={b.id} value={b.id}>{b.label} ({b.currency})</option>)}
          </select></label>
        <label className="t-field t-field-wide"><span>Note</span>
          <input style={inputStyle} value={d.note} onChange={set("note")} /></label>
      </div>
      {info && (
        <>
          <p className="t-sub">Allocated oldest-first from the amount above; adjust any line.</p>
          {info.open_invoices.length === 0 ? <p className="t-empty">This customer has no open invoices.</p> : (
            <table className="t-table">
              <thead><tr><th style={th}>Invoice</th><th style={th}>Order</th><th style={th}>Due</th>
                <th style={{ ...th, textAlign: "right" }}>Outstanding</th><th style={{ ...th, textAlign: "right" }}>Allocate</th></tr></thead>
              <tbody>
                {info.open_invoices.map((inv) => {
                  const row = alloc.find((a) => a.invoice_id === inv.id);
                  return (
                    <tr key={inv.id}>
                      <td style={td}><b>{inv.ref}</b></td>
                      <td style={td}>{inv.so_ref || inv.order}</td>
                      <td style={td}>{fmtDate(inv.due_date)}</td>
                      <td style={{ ...td, textAlign: "right" }}>{inv.currency} {fmtMoney(inv.outstanding)}</td>
                      <td style={{ ...td, textAlign: "right" }}>
                        <input type="number" step="0.01" min="0" value={row?.amount ?? ""}
                               onChange={(e) => setAmount(inv.id, e.target.value)}
                               style={{ ...inputStyle, width: 120, textAlign: "right", padding: "4px 6px" }} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          <div className="t-sub" style={{ marginTop: 6 }}>
            Allocated {fmtMoney(allocated)} of {fmtMoney(d.amount || 0)}
            {Number(d.amount) && Math.abs(allocated - Number(d.amount)) > 0.005 ? " — the difference stays unallocated; adjust the lines." : ""}
          </div>
        </>
      )}
      {error && <p className="t-note t-note-red">{error}</p>}
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Btn type="submit" disabled={busy || !d.customer || allocated <= 0}>{busy ? "Saving…" : "Issue official receipt"}</Btn>
        <Btn type="button" variant="secondary" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}

function Statement({ customer, onClose }) {
  const [range, setRange] = useState({ from: "", to: "" });
  const [st, setSt] = useState(null);
  useEffect(() => {
    const q = new URLSearchParams();
    if (range.from) q.set("from", range.from);
    if (range.to) q.set("to", range.to);
    api(`/trading/customers/${customer.customer}/statement?${q}`).then(setSt).catch(() => setSt(null));
  }, [customer, range]);
  const q = new URLSearchParams({ pdf: "1", ...(range.from ? { from: range.from } : {}), ...(range.to ? { to: range.to } : {}) });
  return (
    <div style={{ ...card, marginBottom: 16 }}>
      <div className="t-page-head">
        <h3 style={{ margin: 0 }}>Statement — {customer.customer_name}</h3>
        <div className="t-tools">
          <input type="date" style={inputStyle} value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })} />
          <input type="date" style={inputStyle} value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })} />
          <a className="t-btn-link" href={`/api/v1/trading/customers/${customer.customer}/statement?${q}`} target="_blank" rel="noreferrer">PDF</a>
          <button className="t-link" onClick={onClose}>Close</button>
        </div>
      </div>
      {!st ? <p>Loading…</p> : (
        <table className="t-table">
          <thead><tr><th style={th}>Date</th><th style={th}>Ref</th><th style={th}>Detail</th>
            <th style={{ ...th, textAlign: "right" }}>Invoiced</th><th style={{ ...th, textAlign: "right" }}>Received / credited</th>
            <th style={{ ...th, textAlign: "right" }}>Balance</th></tr></thead>
          <tbody>
            {st.date_from && <tr><td style={td} colSpan={5}><i>Balance brought forward</i></td><td style={{ ...td, textAlign: "right" }}>{fmtMoney(st.opening)}</td></tr>}
            {st.rows.map((r, i) => (
              <tr key={i}>
                <td style={td}>{fmtDate(r.date)}</td><td style={td}><b>{r.ref}</b></td><td style={td}>{r.detail}</td>
                <td style={{ ...td, textAlign: "right" }}>{r.debit ? fmtMoney(r.debit) : ""}</td>
                <td style={{ ...td, textAlign: "right" }}>{r.credit ? fmtMoney(r.credit) : ""}</td>
                <td style={{ ...td, textAlign: "right" }}>{fmtMoney(r.balance)}</td>
              </tr>
            ))}
            <tr><td style={td} colSpan={5}><b>Balance due</b></td><td style={{ ...td, textAlign: "right" }}><b>{fmtMoney(st.closing)}</b></td></tr>
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function ReceivablesPage({ open }) {
  const [data, setData] = useState(null);
  const [customers, setCustomers] = useState([]);
  const [receipts, setReceipts] = useState([]);
  const [recording, setRecording] = useState(null);      // null | customer id | ""
  const [statementFor, setStatementFor] = useState(null);
  const [expanded, setExpanded] = useState(null);

  function load() {
    api("/trading/receivables").then(setData).catch(() => setData({ customers: [], total: "0" }));
    api("/trading/receipts").then(setReceipts).catch(() => {});
  }
  useEffect(() => {
    load();
    api("/trading/customers").then(setCustomers).catch(() => {});
  }, []);

  if (!data) return <div className="t-page"><p>Loading…</p></div>;
  const B = ["current", "d30", "d60", "d90", "d90plus"];
  const BL = { current: "Not due", d30: "1–30", d60: "31–60", d90: "61–90", d90plus: "90+" };

  return (
    <div className="t-page">
      <div className="t-page-head">
        <h1 className="t-h1">Receivables</h1>
        <div className="t-tools">
          <span className="t-sub">as of {fmtDate(data.as_of)}</span>
          {data.can_receipt && recording === null && <Btn onClick={() => setRecording("")}>+ Record payment</Btn>}
        </div>
      </div>
      {recording !== null && (
        <ReceiptForm customers={customers} preset={recording}
                     onSaved={() => { setRecording(null); load(); }} onCancel={() => setRecording(null)} />
      )}
      {statementFor && <Statement customer={statementFor} onClose={() => setStatementFor(null)} />}

      {data.customers.length === 0 ? <p className="t-empty">Nothing outstanding. Every issued invoice is settled.</p> : (
        <table className="t-table">
          <thead><tr>
            <th style={th}>Customer</th>
            {B.map((b) => <th key={b} style={{ ...th, textAlign: "right" }}>{BL[b]}</th>)}
            <th style={{ ...th, textAlign: "right" }}>Total due</th><th style={th}></th>
          </tr></thead>
          <tbody>
            {data.customers.map((c) => (
              <Fragment key={c.customer}>
                <tr className="t-row-link" onClick={() => setExpanded(expanded === c.customer ? null : c.customer)}>
                  <td style={td}><b>{c.customer_name}</b> <span className="t-sub">{c.currency}</span></td>
                  {B.map((b) => (
                    <td key={b} style={{ ...td, textAlign: "right" }} className={b === "d90plus" && Number(c[b]) ? "t-bad" : ""}>
                      {Number(c[b]) ? fmtMoney(c[b]) : ""}
                    </td>
                  ))}
                  <td style={{ ...td, textAlign: "right" }}><b>{fmtMoney(c.total)}</b></td>
                  <td style={{ ...td, whiteSpace: "nowrap" }} onClick={(e) => e.stopPropagation()}>
                    <button className="t-link" onClick={() => setStatementFor(c)}>Statement</button>
                    {data.can_receipt && <> · <button className="t-link" onClick={() => setRecording(String(c.customer))}>Receipt</button></>}
                  </td>
                </tr>
                {expanded === c.customer && c.invoices.map((inv) => (
                  <tr key={inv.id}>
                    <td style={{ ...td, paddingLeft: 28 }}>
                      <button className="t-link" onClick={() => open(inv, "invoices")}>{inv.ref}</button>
                      <span className="t-sub"> · {inv.so_ref} · issued {fmtDate(inv.invoice_date)} · due {fmtDate(inv.due_date)}</span>
                    </td>
                    <td style={td} colSpan={5} className="t-sub">
                      {inv.overdue_days > 0 ? <Chip tone="alert">{inv.overdue_days} days overdue</Chip> : <Chip tone="info">not due</Chip>}
                    </td>
                    <td style={{ ...td, textAlign: "right" }}>{fmtMoney(inv.outstanding)} <span className="t-sub">of {fmtMoney(inv.total)}</span></td>
                    <td style={td}></td>
                  </tr>
                ))}
              </Fragment>
            ))}
            <tr><td style={td} colSpan={6}><b>Total receivable</b></td><td style={{ ...td, textAlign: "right" }}><b>{fmtMoney(data.total)}</b></td><td style={td}></td></tr>
          </tbody>
        </table>
      )}

      <h3 style={{ marginTop: 24 }}>Receipts</h3>
      {receipts.length === 0 ? <p className="t-sub">No customer receipts yet.</p> : (
        <table className="t-table">
          <thead><tr><th style={th}>Receipt</th><th style={th}>Date</th><th style={th}>Customer</th><th style={th}>How</th>
            <th style={th}>Settles</th><th style={{ ...th, textAlign: "right" }}>Amount</th><th style={th}></th></tr></thead>
          <tbody>
            {receipts.map((r) => (
              <tr key={r.id}>
                <td style={td}><b>{r.receipt_no}</b></td>
                <td style={td}>{fmtDate(r.receipt_date)}</td>
                <td style={td}>{r.client}</td>
                <td style={td}>{r.method_label}{r.reference ? ` · ${r.reference}` : ""}</td>
                <td style={td}>{r.lines.map((l) => l.invoice_no).join(", ")}</td>
                <td style={{ ...td, textAlign: "right" }}>{r.currency} {fmtMoney(r.total)}</td>
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  <a className="t-link" href={`/api/v1/trading/receipts/${r.id}`} target="_blank" rel="noreferrer">PDF</a>
                  {data.can_receipt && <> · <button className="t-link" onClick={async () => {
                    if (!window.confirm(`Delete ${r.receipt_no}? The invoices it settled reopen.`)) return;
                    try { await api(`/trading/receipts/${r.id}`, { method: "DELETE" }); load(); }
                    catch (e) { window.alert(e.message); }
                  }}>Delete</button></>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
