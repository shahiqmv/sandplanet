// GST return: a taxable period's figures box by box as on MIRA 205, and the
// Output and Input Tax Statements behind them, in MIRA's own column layout
// for Excel. Everything comes from the transaction forms; nothing is typed
// here. (FINANCE_BUILD_BRIEF.md — MIRA compliance)
import { useEffect, useState } from "react";
import { api, apiDownload } from "../api.js";
import { Btn, card, inputStyle } from "../ui.jsx";
import { amt, fmtDate, money } from "./shared.jsx";

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
// a month (span 1) or a calendar quarter (span 3), `back` periods ago
function period(span, back) {
  const now = new Date();
  const first = span === 1 ? now.getMonth() : Math.floor(now.getMonth() / 3) * 3;
  const start = new Date(now.getFullYear(), first - back * span, 1);
  return [iso(start), iso(new Date(start.getFullYear(), start.getMonth() + span, 0))];
}
const whole = (v) => Number(v || 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
const ELSEWHERE = { INVOICE: "invoices", BILL: "bills" };

export default function GstPage({ go }) {
  const [[from, to], setRange] = useState(period(1, 1));
  const [d, setD] = useState(null);
  const [tab, setTab] = useState("output");
  const [error, setError] = useState(null);
  useEffect(() => {
    if (!from || !to) return;
    setD(null); setError(null);
    api(`/ledger/reports/gst?from=${from}&to=${to}`).then(setD).catch((e) => setError(e.message));
  }, [from, to]);
  const open = (r) => go(ELSEWHERE[r.type] || "banking", ELSEWHERE[r.type] ? String(r.txn) : `txn-${r.txn}`);
  const get = (which) => apiDownload(`/ledger/reports/gst?from=${from}&to=${to}&export=${which}`).catch((e) => setError(e.message));
  // MIRA: the return and the payment are due by the 28th of the month after the period
  const due = to ? (() => { const e = new Date(`${to}T00:00`); return iso(new Date(e.getFullYear(), e.getMonth() + 1, 28)); })() : null;
  const quick = [["Last month", period(1, 1)], ["This month", period(1, 0)], ["Last quarter", period(3, 1)], ["This quarter", period(3, 0)]];
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>GST return</h1>
        {d && <span style={{ color: "var(--muted)", fontSize: 13 }}>{d.form} · General Goods and Services</span>}
        <span className="spacer" />
        {quick.map(([l, r]) => (
          <button key={l} className={"f-sub-item" + (r[0] === from && r[1] === to ? " is-active" : "")} onClick={() => setRange(r)}>{l}</button>))}
        <input type="date" style={{ ...inputStyle, width: 150 }} value={from} onChange={(e) => setRange([e.target.value, to])} aria-label="From" />
        <span style={{ color: "var(--muted)" }}>to</span>
        <input type="date" style={{ ...inputStyle, width: 150 }} value={to} onChange={(e) => setRange([from, e.target.value])} aria-label="To" />
      </div>
      {error && <p className="f-bad">{error}</p>}
      {!d ? <div style={card}>{error ? "" : "Loading…"}</div> : (
        <>
          {d.warnings.length > 0 && (
            <div className="t-note t-note-amber" style={{ maxWidth: 900 }}>
              {d.warnings.map((w, i) => <div key={i} style={{ margin: "2px 0" }}>• {w}</div>)}
            </div>)}
          <div style={{ display: "grid", gridTemplateColumns: "minmax(420px, 640px) minmax(260px, 1fr)", gap: 14, alignItems: "start" }}>
            <div style={{ ...card, padding: 0 }}>
              <table className="f-table">
                <thead><tr><th style={{ width: 44 }}>Box</th><th>Taxable period {fmtDate(d.date_from)} to {fmtDate(d.date_to)}</th>
                  <th style={{ textAlign: "right" }}>Rufiyaa</th></tr></thead>
                <tbody>{d.boxes.map((b) => (
                  <tr key={b.box} className={b.box === 5 || b.box === 10 ? "f-total" : undefined}>
                    <td style={{ fontWeight: 700 }}>{b.box}</td>
                    <td>{b.label}{!b.derived && <span style={{ color: "var(--muted)", fontSize: 12 }}> — not from the books; fill in by hand if it applies</span>}</td>
                    <td className="f-num">{b.derived ? whole(b.amount) : "—"}</td></tr>))}</tbody>
              </table>
            </div>
            <div style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.55 }}>
              <p style={{ marginTop: 0 }}><b style={{ color: "var(--ink)" }}>{d.company.name}</b> · TIN {d.company.tin}</p>
              <p>The return is filled in rounded to the nearest rufiyaa. To the laari: output tax {money(d.exact.output_tax)},
                input tax {money(d.exact.input_tax)}, {Number(d.exact.net) >= 0 ? "payable" : "input tax in excess"} {money(Math.abs(d.exact.net))}.</p>
              {Number(d.exact.net) < 0 && <p>MIRA does not refund excess input tax — it is carried forward against later output tax.</p>}
              <p>Return and payment are due by <b style={{ color: "var(--ink)" }}>{fmtDate(due)}</b>, filed with the two statements below.</p>
              <p>A sale is on the return by its invoice date; input tax only where a valid tax invoice is held. Check the figures
                against MIRAconnect before filing.</p>
            </div>
          </div>

          <div className="f-bar" style={{ marginTop: 16 }}>
            {[["output", `Output tax statement · ${d.output.length}`], ["input", `Input tax statement · ${d.input.length}`],
              ["other", `Other entries on the GST accounts · ${d.other_entries.length}`]].map(([k, l]) => (
              <button key={k} className={"f-sub-item" + (tab === k ? " is-active" : "")} onClick={() => setTab(k)}>{l}</button>))}
            <span className="spacer" />
            {tab !== "other" && <Btn variant="secondary" onClick={() => get(tab)}>⬇ Excel, in MIRA's layout</Btn>}
          </div>

          {tab === "output" && (
            <div style={{ ...card, padding: 0, overflowX: "auto" }}>
              <table className="f-table">
                <thead><tr><th>Customer TIN</th><th>Customer</th><th>Invoice no.</th><th>Date</th>
                  <th style={{ textAlign: "right" }}>Subject to GST (excl.)</th><th style={{ textAlign: "right" }}>Zero-rated</th>
                  <th style={{ textAlign: "right" }}>Exempt</th><th style={{ textAlign: "right" }}>Out of scope</th>
                  <th style={{ textAlign: "right" }}>GST</th></tr></thead>
                <tbody>
                  {d.output.map((r) => (
                    <tr key={r.txn} className="f-click" onClick={() => open(r)}>
                      <td>{r.customer_tin}</td><td>{r.customer}</td><td>{r.invoice_no}</td><td style={{ whiteSpace: "nowrap" }}>{fmtDate(r.date)}</td>
                      <td className="f-num">{amt(r.standard)}</td><td className="f-num">{amt(r.zero)}</td><td className="f-num">{amt(r.exempt)}</td>
                      <td className="f-num">{amt(r.oos)}</td><td className="f-num">{amt(r.gst)}</td></tr>))}
                  {d.output.length === 0 && <tr><td colSpan={9} style={{ color: "var(--muted)" }}>No sales in this period.</td></tr>}
                  <tr className="f-total"><td colSpan={4}>Total</td><td className="f-num">{money(d.output_total.standard)}</td>
                    <td className="f-num">{money(d.output_total.zero)}</td><td className="f-num">{money(d.output_total.exempt)}</td>
                    <td className="f-num">{money(d.output_total.oos)}</td><td className="f-num">{money(d.output_total.output_tax)}</td></tr>
                </tbody>
              </table>
            </div>)}
          {tab === "input" && (
            <div style={{ ...card, padding: 0, overflowX: "auto" }}>
              <table className="f-table">
                <thead><tr><th>Supplier TIN</th><th>Supplier</th><th>Tax invoice no.</th><th>Invoice date</th>
                  <th style={{ textAlign: "right" }}>Invoice total (excl. GST)</th><th style={{ textAlign: "right" }}>GST charged</th><th>Revenue / capital</th></tr></thead>
                <tbody>
                  {d.input.map((r) => (
                    <tr key={r.txn} className="f-click" onClick={() => open(r)}>
                      <td>{r.supplier_tin || <span className="f-bad">missing</span>}</td><td>{r.supplier}</td>
                      <td>{r.invoice_no || <span className="f-bad">missing</span>}</td>
                      <td style={{ whiteSpace: "nowrap" }}>{fmtDate(r.date)}{r.stale && <span className="f-bad"> · over 12 months</span>}</td>
                      <td className="f-num">{money(r.net)}</td><td className="f-num">{money(r.gst_total)}</td><td>{r.kind}</td></tr>))}
                  {d.input.length === 0 && <tr><td colSpan={7} style={{ color: "var(--muted)" }}>No purchases with a tax invoice in this period.</td></tr>}
                  <tr className="f-total"><td colSpan={4}>Total input tax</td><td className="f-num">{money(d.input_total.net)}</td>
                    <td className="f-num">{money(d.input_total.gst)}</td><td /></tr>
                </tbody>
              </table>
            </div>)}
          {tab === "other" && (
            <div style={{ ...card, padding: 0, overflowX: "auto" }}>
              <table className="f-table">
                <thead><tr><th>Date</th><th>Entry</th><th>Account</th><th>What</th><th style={{ textAlign: "right" }}>Debit</th><th style={{ textAlign: "right" }}>Credit</th></tr></thead>
                <tbody>
                  {d.other_entries.map((o, i) => (
                    <tr key={i} className="f-click" onClick={() => go("journals", o.entry)}>
                      <td style={{ whiteSpace: "nowrap" }}>{fmtDate(o.date)}</td><td style={{ fontFamily: "var(--font-mono)" }}>{o.ref}</td>
                      <td>{o.account}</td><td>{o.memo}</td><td className="f-num">{amt(o.debit)}</td><td className="f-num">{amt(o.credit)}</td></tr>))}
                  {d.other_entries.length === 0 && <tr><td colSpan={6} style={{ color: "var(--muted)" }}>Nothing else touched the GST accounts in this period.</td></tr>}
                </tbody>
              </table>
              <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "8px 12px" }}>
                Postings to the GST accounts that are not a sale or a purchase with a tax invoice — the payment to MIRA, a journal.
                They are not on the return; they are here so nothing on those accounts goes unexplained.</p>
            </div>)}
        </>
      )}
    </div>
  );
}
