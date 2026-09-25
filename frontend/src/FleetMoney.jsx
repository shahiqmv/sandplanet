// Rental money: invoices raised from the approved daily register, the
// receipts Finance records against them, the aging and the statement of
// account (MARINE_BUILD_BRIEF.md §4, phase 5).
import { Fragment, useEffect, useState } from "react";
import { api } from "./api.js";
import { API_BASE } from "./brand.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";

const fmtDate = (v) => (v ? new Date(v).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "");
const fmtMoney = (v) => (v == null || v === "" ? "" : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const INV_TONE = { DRAFT: "warn", ISSUED: "info", PAID: "ok", VOID: "alert" };
const METHODS = [["TT", "Telegraphic transfer"], ["CHEQUE", "Cheque"], ["CASH", "Cash"], ["CARD", "Card"], ["OTHER", "Other"]];
const link = { background: "none", border: 0, color: "var(--sp-navy)", font: "inherit", fontSize: 13, textDecoration: "underline", cursor: "pointer", padding: 0 };

// ---- invoices under one agreement ----------------------------------------------------
export function AgreementInvoices({ a }) {
  const today = new Date();
  const [from, setFrom] = useState(iso(new Date(today.getFullYear(), today.getMonth(), 1)));
  const [to, setTo] = useState(iso(today));
  const [data, setData] = useState(null);
  const [opts, setOpts] = useState({ include_mobilisation: true, include_demobilisation: false, invoice_date: iso(today) });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const load = () => api(`/fleet/agreements/${a.id}/invoices?from=${from}&to=${to}`).then(setData).catch((e) => setError(e.message));
  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [a.id, from, to]);
  async function raise_() {
    setBusy(true); setError(null);
    try { await api(`/fleet/agreements/${a.id}/invoices`, { method: "POST", body: { from, to, ...opts } }); await load(); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function act(inv, action) {
    const body = { action };
    if (action === "void") { const r = window.prompt(`Void ${inv.ref} — why?`); if (!r) return; body.reason = r; }
    if (action === "issue" && !window.confirm(`Issue ${inv.ref} for ${inv.currency} ${fmtMoney(inv.total)}? Revenue posts to the vehicles' cost centres.`)) return;
    try { await api(`/fleet/invoices/${inv.id}`, { method: "POST", body }); await load(); } catch (e) { setError(e.message); }
  }
  if (!data) return error ? <p style={{ color: "var(--red-fg)" }}>{error}</p> : null;
  const pv = data.preview;
  return (
    <div style={{ ...card, marginTop: 12 }}>
      <h3 style={{ marginTop: 0 }}>Invoices</h3>
      {data.invoices.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginBottom: 12 }}>
          <thead><tr><th style={th}>Invoice</th><th style={th}>Period</th><th style={{ ...th, textAlign: "right" }}>Days</th>
            <th style={{ ...th, textAlign: "right" }}>Total</th><th style={{ ...th, textAlign: "right" }}>Outstanding</th><th style={th}>Status</th><th style={th}></th></tr></thead>
          <tbody>
            {data.invoices.map((inv) => (
              <tr key={inv.id}>
                <td style={td}><b>{inv.ref}</b><div style={{ fontSize: 11, opacity: .7 }}>{fmtDate(inv.invoice_date)}{inv.due_date ? ` · due ${fmtDate(inv.due_date)}` : ""}</div></td>
                <td style={td}>{fmtDate(inv.period_from)} – {fmtDate(inv.period_to)}</td>
                <td style={{ ...td, textAlign: "right" }}>{inv.days}</td>
                <td style={{ ...td, textAlign: "right" }}>{inv.currency} {fmtMoney(inv.total)}</td>
                <td style={{ ...td, textAlign: "right" }}>{inv.status === "ISSUED" ? fmtMoney(inv.outstanding) : ""}</td>
                <td style={td}><Chip tone={INV_TONE[inv.status]}>{inv.status.toLowerCase()}</Chip>{inv.void_reason ? <div style={{ fontSize: 11, opacity: .7 }}>{inv.void_reason}</div> : null}</td>
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  <a style={link} href={`${API_BASE}/fleet/invoices/${inv.id}/pdf`} target="_blank" rel="noreferrer">{inv.status === "DRAFT" ? "Draft PDF" : "PDF"}</a>
                  {a.can_manage && inv.status === "DRAFT" && <> · <button style={link} onClick={() => act(inv, "issue")}>Issue</button></>}
                  {a.can_manage && inv.status !== "VOID" && inv.status !== "PAID" && <> · <button style={{ ...link, color: "var(--red-fg)" }} onClick={() => act(inv, "void")}>Void</button></>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {a.can_write && a.status !== "DRAFT" && (
        <div style={{ borderTop: data.invoices.length ? "1px solid var(--line)" : 0, paddingTop: data.invoices.length ? 10 : 0 }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>Bill approved days</span>
            <input type="date" style={inputStyle} value={from} onChange={(e) => setFrom(e.target.value)} />
            <input type="date" style={inputStyle} value={to} onChange={(e) => setTo(e.target.value)} />
            <label style={{ fontSize: 13 }}>dated <input type="date" style={{ ...inputStyle, marginLeft: 4 }} value={opts.invoice_date} onChange={(e) => setOpts({ ...opts, invoice_date: e.target.value })} /></label>
          </div>
          {pv && (
            <div style={{ fontSize: 13, marginTop: 8 }}>
              {pv.rows.length === 0 ? <span style={{ opacity: .7 }}>No approved, unbilled days in this window.{pv.unapproved_days ? ` ${pv.unapproved_days} billable days await the representative's approval.` : ""}</span> : (
                <>
                  {pv.rows.map((r) => <div key={r.line}><b>{r.fleet_no || r.reg_no}</b> {r.days} days ({r.worked} worked{r.standby ? `, ${r.standby} standby` : ""}) × {fmtMoney(r.rate)} = {fmtMoney(r.amount)}{Number(r.operator_amount) ? ` + operator ${fmtMoney(r.operator_amount)}` : ""}</div>)}
                  {pv.unapproved_days ? <div style={{ color: "var(--amber-fg, #8a5a00)" }}>{pv.unapproved_days} more billable days in this window await approval and are not included.</div> : null}
                </>
              )}
              <div style={{ display: "flex", gap: 14, alignItems: "center", marginTop: 6, flexWrap: "wrap" }}>
                {pv.mobilisation && <label><input type="checkbox" checked={opts.include_mobilisation} onChange={(e) => setOpts({ ...opts, include_mobilisation: e.target.checked })} /> mobilisation {fmtMoney(pv.mobilisation)}</label>}
                {pv.demobilisation && <label><input type="checkbox" checked={opts.include_demobilisation} onChange={(e) => setOpts({ ...opts, include_demobilisation: e.target.checked })} /> demobilisation {fmtMoney(pv.demobilisation)}</label>}
                <Btn onClick={raise_} disabled={busy || (pv.rows.length === 0 && !(pv.mobilisation && opts.include_mobilisation) && !(pv.demobilisation && opts.include_demobilisation))}>
                  {busy ? "Raising…" : `Raise invoice · ${pv.currency} ${fmtMoney(Number(pv.subtotal) + (pv.mobilisation && opts.include_mobilisation ? Number(pv.mobilisation) : 0) + (pv.demobilisation && opts.include_demobilisation ? Number(pv.demobilisation) : 0))} + GST`}
                </Btn>
              </div>
            </div>
          )}
        </div>
      )}
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
    </div>
  );
}

// ---- all invoices ----------------------------------------------------------------------
export function InvoicesPanel({ openAgreement }) {
  const [rows, setRows] = useState(null);
  const [status, setStatus] = useState("");
  useEffect(() => { api(`/fleet/invoices${status ? `?status=${status}` : ""}`).then(setRows).catch(() => setRows([])); }, [status]);
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>Rental invoices</h2>
        <select style={inputStyle} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All</option><option value="DRAFT">Draft</option><option value="ISSUED">Issued</option><option value="PAID">Paid</option><option value="VOID">Void</option>
        </select>
      </div>
      {rows === null ? <p>Loading…</p> : rows.length === 0 ? <p style={{ opacity: .7, marginTop: 12 }}>No invoices yet. They are raised on an agreement from its approved register days.</p> : (
        <table style={{ width: "100%", borderCollapse: "collapse", background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 8, marginTop: 12 }}>
          <thead><tr><th style={th}>Invoice</th><th style={th}>Customer</th><th style={th}>Agreement</th><th style={th}>Period</th>
            <th style={{ ...th, textAlign: "right" }}>Total</th><th style={{ ...th, textAlign: "right" }}>Outstanding</th><th style={th}>Status</th><th style={th}></th></tr></thead>
          <tbody>
            {rows.map((inv) => (
              <tr key={inv.id}>
                <td style={td}><b>{inv.ref}</b><div style={{ fontSize: 11, opacity: .7 }}>{fmtDate(inv.invoice_date)}</div></td>
                <td style={td}>{inv.customer_name}</td>
                <td style={td}><button style={link} onClick={() => openAgreement(inv.agreement)}>{inv.agreement_ref}</button></td>
                <td style={td}>{fmtDate(inv.period_from)} – {fmtDate(inv.period_to)}</td>
                <td style={{ ...td, textAlign: "right" }}>{inv.currency} {fmtMoney(inv.total)}</td>
                <td style={{ ...td, textAlign: "right" }}>{inv.status === "ISSUED" ? fmtMoney(inv.outstanding) : ""}</td>
                <td style={td}><Chip tone={INV_TONE[inv.status]}>{inv.status.toLowerCase()}</Chip></td>
                <td style={td}><a style={link} href={`${API_BASE}/fleet/invoices/${inv.id}/pdf`} target="_blank" rel="noreferrer">PDF</a></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ---- receivables ----------------------------------------------------------------------
function ReceiptForm({ customers, onSaved, onCancel, preset }) {
  const [d, setD] = useState({ customer: preset || "", receipt_date: iso(new Date()), method: "TT", reference: "", bank_account: "", note: "", amount: "" });
  const [info, setInfo] = useState(null);
  const [alloc, setAlloc] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setD({ ...d, [k]: e.target.value });
  useEffect(() => {
    if (!d.customer) { setInfo(null); return; }
    api(`/fleet/receipts/allocate?customer=${d.customer}&amount=${d.amount || 0}`).then((x) => { setInfo(x); setAlloc(x.allocations); }).catch((e) => setError(e.message));
  }, [d.customer, d.amount]);
  const allocated = alloc.reduce((s, x) => s + (Number(x.amount) || 0), 0);
  function setAmount(invId, v) {
    setAlloc((rows) => {
      const inv = info.open_invoices.find((i) => i.id === invId);
      const row = { invoice_id: invId, invoice: inv.ref, amount: v, outstanding: inv.outstanding };
      return rows.some((r) => r.invoice_id === invId) ? rows.map((r) => (r.invoice_id === invId ? row : r)) : [...rows, row];
    });
  }
  async function save(e) {
    e.preventDefault(); setBusy(true); setError(null);
    try { onSaved(await api("/fleet/receipts", { method: "POST", body: { ...d, customer: Number(d.customer), bank_account: d.bank_account || null, allocations: alloc.filter((x) => Number(x.amount) > 0) } })); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  const F = ({ label, children }) => <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13 }}><span style={{ fontWeight: 600, opacity: .8 }}>{label}</span>{children}</label>;
  return (
    <form onSubmit={save} style={{ ...card, marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>Record a customer payment</h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12 }}>
        <F label="Customer"><select style={inputStyle} value={d.customer} onChange={set("customer")} required><option value="">— pick —</option>{customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></F>
        <F label="Amount received"><input style={inputStyle} type="number" step="0.01" min="0" value={d.amount} onChange={set("amount")} /></F>
        <F label="Date"><input style={inputStyle} type="date" value={d.receipt_date} onChange={set("receipt_date")} required /></F>
        <F label="How"><select style={inputStyle} value={d.method} onChange={set("method")}>{METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></F>
        <F label="Reference (TT / cheque no.)"><input style={inputStyle} value={d.reference} onChange={set("reference")} /></F>
        <F label="Into bank account"><select style={inputStyle} value={d.bank_account} onChange={set("bank_account")}><option value="">—</option>{(info?.bank_accounts || []).map((b) => <option key={b.id} value={b.id}>{b.label} ({b.currency})</option>)}</select></F>
        <F label="Note"><input style={inputStyle} value={d.note} onChange={set("note")} /></F>
      </div>
      {info && (info.open_invoices.length === 0 ? <p style={{ fontSize: 13, opacity: .7 }}>This customer has no open invoices.</p> : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginTop: 12 }}>
          <thead><tr><th style={th}>Invoice</th><th style={th}>Agreement</th><th style={th}>Due</th><th style={{ ...th, textAlign: "right" }}>Outstanding</th><th style={{ ...th, textAlign: "right" }}>Allocate</th></tr></thead>
          <tbody>
            {info.open_invoices.map((inv) => {
              const row = alloc.find((x) => x.invoice_id === inv.id);
              return (
                <tr key={inv.id}>
                  <td style={td}><b>{inv.ref}</b></td><td style={td}>{inv.agreement}</td><td style={td}>{fmtDate(inv.due_date)}</td>
                  <td style={{ ...td, textAlign: "right" }}>{inv.currency} {fmtMoney(inv.outstanding)}</td>
                  <td style={{ ...td, textAlign: "right" }}><input type="number" step="0.01" min="0" value={row?.amount ?? ""} onChange={(e) => setAmount(inv.id, e.target.value)} style={{ ...inputStyle, width: 120, textAlign: "right", padding: "4px 6px" }} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ))}
      {info && <div style={{ fontSize: 12, opacity: .75, marginTop: 6 }}>Allocated {fmtMoney(allocated)} of {fmtMoney(d.amount || 0)}, oldest invoice first; adjust any line.</div>}
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
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
    const q = new URLSearchParams(); if (range.from) q.set("from", range.from); if (range.to) q.set("to", range.to);
    api(`/fleet/customers/${customer.customer}/statement?${q}`).then(setSt).catch(() => setSt(null));
  }, [customer, range]);
  const q = new URLSearchParams({ pdf: "1", ...(range.from ? { from: range.from } : {}), ...(range.to ? { to: range.to } : {}) });
  return (
    <div style={{ ...card, marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
        <h3 style={{ margin: 0 }}>Statement — {customer.customer_name}</h3>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input type="date" style={inputStyle} value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })} />
          <input type="date" style={inputStyle} value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })} />
          <a className="btn btn-secondary" style={{ textDecoration: "none" }} href={`${API_BASE}/fleet/customers/${customer.customer}/statement?${q}`} target="_blank" rel="noreferrer">PDF</a>
          <button style={link} onClick={onClose}>Close</button>
        </div>
      </div>
      {!st ? <p>Loading…</p> : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginTop: 10 }}>
          <thead><tr><th style={th}>Date</th><th style={th}>Ref</th><th style={th}>Detail</th><th style={{ ...th, textAlign: "right" }}>Invoiced</th><th style={{ ...th, textAlign: "right" }}>Received</th><th style={{ ...th, textAlign: "right" }}>Balance</th></tr></thead>
          <tbody>
            {st.date_from && <tr><td style={td} colSpan={5}><i>Balance brought forward</i></td><td style={{ ...td, textAlign: "right" }}>{fmtMoney(st.opening)}</td></tr>}
            {st.rows.map((r, i) => (
              <tr key={i}><td style={td}>{fmtDate(r.date)}</td><td style={td}><b>{r.ref}</b></td><td style={td}>{r.detail}</td>
                <td style={{ ...td, textAlign: "right" }}>{r.debit ? fmtMoney(r.debit) : ""}</td><td style={{ ...td, textAlign: "right" }}>{r.credit ? fmtMoney(r.credit) : ""}</td>
                <td style={{ ...td, textAlign: "right" }}>{fmtMoney(r.balance)}</td></tr>
            ))}
            <tr><td style={td} colSpan={5}><b>Balance due</b></td><td style={{ ...td, textAlign: "right" }}><b>{fmtMoney(st.closing)}</b></td></tr>
          </tbody>
        </table>
      )}
    </div>
  );
}

export function ReceivablesPanel({ openAgreement }) {
  const [data, setData] = useState(null);
  const [customers, setCustomers] = useState([]);
  const [receipts, setReceipts] = useState([]);
  const [recording, setRecording] = useState(null);
  const [statementFor, setStatementFor] = useState(null);
  const [expanded, setExpanded] = useState(null);
  function load() {
    api("/fleet/receivables").then(setData).catch(() => setData({ customers: [], total: "0" }));
    api("/fleet/receipts").then(setReceipts).catch(() => {});
  }
  useEffect(() => { load(); api("/fleet/customers").then(setCustomers).catch(() => {}); }, []);
  if (!data) return <p>Loading…</p>;
  const B = ["current", "d30", "d60", "d90", "d90plus"];
  const BL = { current: "Not due", d30: "1–30", d60: "31–60", d90: "61–90", d90plus: "90+" };
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12, marginBottom: 12 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>Receivables <span style={{ fontSize: 13, fontWeight: 400, opacity: .7 }}>as of {fmtDate(data.as_of)}</span></h2>
        {data.can_receipt && recording === null && <Btn onClick={() => setRecording("")}>+ Record payment</Btn>}
      </div>
      {recording !== null && <ReceiptForm customers={customers} preset={recording} onSaved={() => { setRecording(null); load(); }} onCancel={() => setRecording(null)} />}
      {statementFor && <Statement customer={statementFor} onClose={() => setStatementFor(null)} />}
      {data.customers.length === 0 ? <p style={{ opacity: .7 }}>Nothing outstanding. Every issued invoice is settled.</p> : (
        <table style={{ width: "100%", borderCollapse: "collapse", background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 8 }}>
          <thead><tr><th style={th}>Customer</th>{B.map((b) => <th key={b} style={{ ...th, textAlign: "right" }}>{BL[b]}</th>)}<th style={{ ...th, textAlign: "right" }}>Total due</th><th style={th}></th></tr></thead>
          <tbody>
            {data.customers.map((c) => (
              <Fragment key={c.customer}>
                <tr style={{ cursor: "pointer" }} onClick={() => setExpanded(expanded === c.customer ? null : c.customer)}>
                  <td style={td}><b>{c.customer_name}</b> <span style={{ opacity: .7, fontSize: 12 }}>{c.currency}</span></td>
                  {B.map((b) => <td key={b} style={{ ...td, textAlign: "right", color: b === "d90plus" && Number(c[b]) ? "var(--red-fg)" : undefined }}>{Number(c[b]) ? fmtMoney(c[b]) : ""}</td>)}
                  <td style={{ ...td, textAlign: "right" }}><b>{fmtMoney(c.total)}</b></td>
                  <td style={{ ...td, whiteSpace: "nowrap" }} onClick={(e) => e.stopPropagation()}>
                    <button style={link} onClick={() => setStatementFor(c)}>Statement</button>
                    {data.can_receipt && <> · <button style={link} onClick={() => setRecording(String(c.customer))}>Receipt</button></>}
                  </td>
                </tr>
                {expanded === c.customer && c.invoices.map((inv) => (
                  <tr key={inv.id}>
                    <td style={{ ...td, paddingLeft: 28 }}><b>{inv.ref}</b> <span style={{ fontSize: 12, opacity: .7 }}>· <button style={link} onClick={() => openAgreement(inv.agreement_id)}>{inv.agreement}</button> · issued {fmtDate(inv.invoice_date)} · due {fmtDate(inv.due_date)}</span></td>
                    <td style={td} colSpan={5}>{inv.overdue_days > 0 ? <Chip tone="alert">{inv.overdue_days} days overdue</Chip> : <Chip tone="info">not due</Chip>}</td>
                    <td style={{ ...td, textAlign: "right" }}>{fmtMoney(inv.outstanding)} <span style={{ fontSize: 12, opacity: .7 }}>of {fmtMoney(inv.total)}</span></td>
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
      {receipts.length === 0 ? <p style={{ opacity: .7 }}>No customer receipts yet.</p> : (
        <table style={{ width: "100%", borderCollapse: "collapse", background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 8 }}>
          <thead><tr><th style={th}>Receipt</th><th style={th}>Date</th><th style={th}>Customer</th><th style={th}>How</th><th style={th}>Settles</th><th style={{ ...th, textAlign: "right" }}>Amount</th><th style={th}></th></tr></thead>
          <tbody>
            {receipts.map((r) => (
              <tr key={r.id}>
                <td style={td}><b>{r.receipt_no}</b></td><td style={td}>{fmtDate(r.receipt_date)}</td><td style={td}>{r.client}</td>
                <td style={td}>{r.method_label}{r.reference ? ` · ${r.reference}` : ""}</td>
                <td style={td}>{r.lines.map((l) => l.invoice_no).join(", ")}</td>
                <td style={{ ...td, textAlign: "right" }}>{r.currency} {fmtMoney(r.total)}</td>
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  <a style={link} href={`${API_BASE}/fleet/receipts/${r.id}`} target="_blank" rel="noreferrer">PDF</a>
                  {data.can_receipt && <> · <button style={link} onClick={async () => {
                    if (!window.confirm(`Delete ${r.receipt_no}? The invoices it settled reopen.`)) return;
                    try { await api(`/fleet/receipts/${r.id}`, { method: "DELETE" }); load(); } catch (e) { window.alert(e.message); }
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
