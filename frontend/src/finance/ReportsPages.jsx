// Trial balance and the account ledger — the two reports that prove the
// books and open any number to the entries behind it. Both export to Excel
// for the auditor (FINANCE_BUILD_BRIEF.md).
import { useEffect, useState } from "react";
import { api, apiDownload } from "../api.js";
import { Btn, card, inputStyle } from "../ui.jsx";
import { TYPE_ORDER, amt, fmtDate, money, today, tree } from "./shared.jsx";

function Range({ from, to, setFrom, setTo, start }) {
  const y = new Date().getFullYear();
  const presets = [["Year to date", `${y}-01-01`, today()],
                   ["Since the books opened", start || `${y}-01-01`, today()]];
  return (
    <>
      <input type="date" style={{ ...inputStyle, width: 150 }} value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From" />
      <span style={{ color: "var(--muted)" }}>to</span>
      <input type="date" style={{ ...inputStyle, width: 150 }} value={to} onChange={(e) => setTo(e.target.value)} aria-label="To" />
      {presets.map(([l, a, b]) => (
        <button key={l} className="f-link" style={{ fontSize: 12.5 }} onClick={() => { setFrom(a); setTo(b); }}>{l}</button>
      ))}
    </>
  );
}

export function TrialBalancePage({ go, settings }) {
  const start = settings?.books_start_date;
  const [from, setFrom] = useState(start || `${new Date().getFullYear()}-01-01`);
  const [to, setTo] = useState(today());
  const [tb, setTb] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { if (start) setFrom(start); }, [start]);
  useEffect(() => {
    if (!from || !to) return;
    api(`/ledger/trial-balance?from=${from}&to=${to}`).then(setTb).catch((e) => setError(e.message));
  }, [from, to]);

  const byType = {};
  (tb?.rows || []).forEach((r) => { (byType[r.type] = byType[r.type] || []).push(r); });
  const t = tb?.totals;
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>Trial balance</h1>
        {tb && (tb.balanced ? <span className="f-ok">✓ In balance</span>
          : <span className="f-bad">Out of balance by MVR {money(Math.abs(tb.difference))}</span>)}
        <span className="spacer" />
        <Btn variant="secondary" onClick={() => apiDownload(`/ledger/trial-balance?from=${from}&to=${to}&export=xlsx`).catch((e) => setError(e.message))}>⬇ Excel</Btn>
      </div>
      <div className="f-bar"><Range from={from} to={to} setFrom={setFrom} setTo={setTo} start={start} /></div>
      {error && <p className="f-bad">{error}</p>}
      {!tb ? <div style={card}>Loading…</div> : tb.rows.length === 0 ? (
        <div style={card}>Nothing is posted in this period yet.</div>
      ) : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table className="f-table">
            <thead>
              <tr><th rowSpan={2}>Code</th><th rowSpan={2}>Account</th>
                <th colSpan={2} style={{ textAlign: "center" }}>Brought forward</th>
                <th colSpan={2} style={{ textAlign: "center" }}>Period</th>
                <th colSpan={2} style={{ textAlign: "center" }}>Carried forward</th></tr>
              <tr>{["Debit", "Credit", "Debit", "Credit", "Debit", "Credit"].map((h, i) => <th key={i} style={{ textAlign: "right" }}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {TYPE_ORDER.filter((ty) => byType[ty]).map((ty) => (
                [<tr key={ty} className="f-group"><td colSpan={8}>{byType[ty][0].type_label}</td></tr>,
                 ...byType[ty].map((r) => (
                  <tr key={r.account} className="f-click" onClick={() => go("ledger", r.account)}>
                    <td style={{ fontFamily: "var(--font-mono)" }}>{r.code}</td><td>{r.name}</td>
                    <td className="f-num">{amt(r.opening_debit)}</td><td className="f-num">{amt(r.opening_credit)}</td>
                    <td className="f-num">{amt(r.debit)}</td><td className="f-num">{amt(r.credit)}</td>
                    <td className="f-num">{amt(r.closing_debit)}</td><td className="f-num">{amt(r.closing_credit)}</td>
                  </tr>))]
              ))}
              <tr className="f-total"><td colSpan={2}>Total (MVR)</td>
                <td className="f-num">{money(t.opening_debit)}</td><td className="f-num">{money(t.opening_credit)}</td>
                <td className="f-num">{money(t.debit)}</td><td className="f-num">{money(t.credit)}</td>
                <td className="f-num">{money(t.closing_debit)}</td><td className="f-num">{money(t.closing_credit)}</td></tr>
            </tbody>
          </table>
        </div>
      )}
      <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
        Posted entries only — drafts are not in the books. Click an account to see the entries behind its figures.</p>
    </div>
  );
}

export function LedgerPage({ accountId, go, settings }) {
  const start = settings?.books_start_date;
  const [accounts, setAccounts] = useState([]);
  const [from, setFrom] = useState(start || `${new Date().getFullYear()}-01-01`);
  const [to, setTo] = useState(today());
  const [led, setLed] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { if (start) setFrom(start); }, [start]);
  useEffect(() => { api("/ledger/accounts").then((d) => setAccounts(tree(d.accounts).filter((a) => !a.is_group))); }, []);
  useEffect(() => {
    setLed(null); setError(null);
    if (!accountId || !from || !to) return;
    api(`/ledger/accounts/${accountId}/ledger?from=${from}&to=${to}`).then(setLed).catch((e) => setError(e.message));
  }, [accountId, from, to]);

  const a = led?.account;
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>Account ledger</h1>
        <span className="spacer" />
        {accountId && <Btn variant="secondary" onClick={() => apiDownload(`/ledger/accounts/${accountId}/ledger?from=${from}&to=${to}&export=xlsx`).catch((e) => setError(e.message))}>⬇ Excel</Btn>}
      </div>
      <div className="f-bar">
        <select style={{ ...inputStyle, width: 340 }} value={accountId || ""} onChange={(e) => go("ledger", e.target.value || null)}>
          <option value="">— pick an account —</option>
          {accounts.map((x) => <option key={x.id} value={x.id}>{x.code} {x.name}</option>)}
        </select>
        <Range from={from} to={to} setFrom={setFrom} setTo={setTo} start={start} />
      </div>
      {error && <p className="f-bad">{error}</p>}
      {!accountId ? <div style={card}>Pick an account to see every entry posted to it, with a running balance.</div>
        : !led ? <div style={card}>Loading…</div> : (
        <>
          <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 8 }}>
            <b style={{ color: "var(--ink)" }}>{a.code} {a.name}</b> · {a.type_label} · held in {a.currency} ·
            balance shown as a {a.debit_normal ? "debit" : "credit"} balance
          </div>
          <div style={{ ...card, padding: 0, overflowX: "auto" }}>
            <table className="f-table">
              <thead><tr><th>Date</th><th>Entry</th><th>Description</th><th>Party</th><th>Site</th>
                <th style={{ textAlign: "right" }}>Debit</th><th style={{ textAlign: "right" }}>Credit</th>
                <th style={{ textAlign: "right" }}>Balance</th></tr></thead>
              <tbody>
                <tr className="f-group"><td colSpan={7}>Brought forward at {fmtDate(led.date_from)}</td>
                  <td className="f-num">{money(led.opening)}</td></tr>
                {led.rows.map((r, i) => (
                  <tr key={i} className="f-click" onClick={() => go("journals", r.entry)}>
                    <td style={{ whiteSpace: "nowrap" }}>{fmtDate(r.date)}</td>
                    <td style={{ fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>{r.ref}</td>
                    <td>{r.description || r.memo}
                      {r.currency !== "MVR" && <span style={{ color: "var(--muted)" }}> · {r.currency} {money(r.amount_fc)}</span>}</td>
                    <td>{r.party}</td><td>{r.site}</td>
                    <td className="f-num">{amt(r.debit)}</td><td className="f-num">{amt(r.credit)}</td>
                    <td className="f-num">{money(r.balance)}</td>
                  </tr>
                ))}
                {led.rows.length === 0 && <tr><td colSpan={8} style={{ color: "var(--muted)" }}>No entries in this period.</td></tr>}
                <tr className="f-total"><td colSpan={5}>Carried forward at {fmtDate(led.date_to)}</td>
                  <td className="f-num">{money(led.debit)}</td><td className="f-num">{money(led.credit)}</td>
                  <td className="f-num">{money(led.closing)}</td></tr>
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
