// Profit & Loss and Balance Sheet, laid out the QuickBooks way: accounts
// under their type, sub-accounts indented under their parent with a
// subtotal, every figure opening the entries behind it
// (FINANCE_BUILD_BRIEF.md, stage 2).
import { useEffect, useState } from "react";
import { api, apiDownload } from "../api.js";
import { Btn, card, inputStyle } from "../ui.jsx";
import { fmtDate, money, today } from "./shared.jsx";

const neg = (v) => (Number(v) < 0 ? `(${money(Math.abs(v))})` : money(v));

function Section({ sec, go, label }) {
  if (!sec.rows.length) return null;
  return (
    <>
      <tr className="f-group"><td colSpan={2}>{label || sec.label}</td></tr>
      {sec.rows.map((r) => (
        <tr key={r.account} className={r.is_group ? "" : "f-click"} onClick={() => !r.is_group && go("ledger", r.account)}>
          <td style={{ paddingLeft: 22 + r.depth * 20, fontWeight: r.is_group ? 600 : 400 }}>
            <span style={{ fontFamily: "var(--font-mono)", color: "var(--muted)", marginRight: 8 }}>{r.code}</span>{r.name}</td>
          <td className="f-num" style={{ fontWeight: r.is_group ? 600 : 400 }}>{neg(r.amount)}</td>
        </tr>
      ))}
    </>
  );
}
const Total = ({ label, value, strong }) => (
  <tr className={strong ? "f-total" : ""}><td style={{ fontWeight: 700, paddingLeft: strong ? 10 : 22 }}>{label}</td>
    <td className="f-num" style={{ fontWeight: 700 }}>{neg(value)}</td></tr>
);

export function ProfitLossPage({ go, settings }) {
  const y = new Date().getFullYear();
  const [from, setFrom] = useState(`${y}-01-01`);
  const [to, setTo] = useState(today());
  const [r, setR] = useState(null);
  const [error, setError] = useState(null);
  const [site, setSite] = useState("");             // "" = the whole company
  const [sites, setSites] = useState([]);
  useEffect(() => { api("/sites").then((x) => setSites(Array.isArray(x) ? x : x.results || [])).catch(() => {}); }, []);
  const q = `from=${from}&to=${to}${site ? `&site=${site}` : ""}`;
  useEffect(() => {
    api(`/ledger/reports/pnl?${q}`).then(setR).catch((e) => setError(e.message));
  }, [q]);
  const s = r?.sections;
  const empty = s && Object.values(s).every((x) => x.rows.length === 0);
  return (
    <div className="t-page" style={{ maxWidth: 900 }}>
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>Profit and loss</h1>
        <span className="spacer" />
        <Btn variant="secondary" onClick={() => apiDownload(`/ledger/reports/pnl?${q}&export=xlsx`).catch((e) => setError(e.message))}>⬇ Excel</Btn>
      </div>
      <div className="f-bar">
        <input type="date" style={{ ...inputStyle, width: 150 }} value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From" />
        <span style={{ color: "var(--muted)" }}>to</span>
        <input type="date" style={{ ...inputStyle, width: 150 }} value={to} onChange={(e) => setTo(e.target.value)} aria-label="To" />
        <button className="f-link" style={{ fontSize: 12.5 }} onClick={() => { setFrom(`${y}-01-01`); setTo(today()); }}>This year to date</button>
        <select style={{ ...inputStyle, width: 190 }} value={site} onChange={(e) => setSite(e.target.value)} aria-label="Site">
          <option value="">The whole company</option>
          {sites.map((x) => <option key={x.id} value={x.id}>{x.code} only</option>)}
        </select>
        {settings?.books_start_date && <span style={{ fontSize: 12.5, color: "var(--muted)" }}>books open {fmtDate(settings.books_start_date)}</span>}
      </div>
      {error && <p className="f-bad">{error}</p>}
      {!r ? <div style={card}>Loading…</div> : empty ? <div style={card}>{site ? "Nothing in this period is marked to this site. A line belongs to a site when the site is chosen on it." : "No income or expense is posted in this period yet."}</div> : (
        <div style={{ ...card, padding: 0 }}>
          <table className="f-table">
            <thead><tr><th>{fmtDate(r.date_from)} to {fmtDate(r.date_to)}</th><th style={{ textAlign: "right" }}>MVR</th></tr></thead>
            <tbody>
              <Section sec={s.INCOME} go={go} /><Total label="Total income" value={s.INCOME.total} />
              <Section sec={s.COGS} go={go} /><Total label="Total cost of goods sold" value={s.COGS.total} />
              <Total label="Gross profit" value={r.gross_profit} strong />
              <Section sec={s.EXPENSE} go={go} /><Total label="Total expenses" value={s.EXPENSE.total} />
              <Total label="Operating profit" value={r.operating_profit} strong />
              <Section sec={s.OTHER_INCOME} go={go} />
              <Section sec={s.OTHER_EXPENSE} go={go} />
              <Total label="Net profit" value={r.net_profit} strong />
            </tbody>
          </table>
        </div>
      )}
      <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>Posted entries only. Click an account to see what makes up its figure.</p>
    </div>
  );
}

export function BalanceSheetPage({ go }) {
  const [asOf, setAsOf] = useState(today());
  const [r, setR] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    api(`/ledger/reports/balance-sheet?as_of=${asOf}`).then(setR).catch((e) => setError(e.message));
  }, [asOf]);
  const s = r?.sections;
  return (
    <div className="t-page" style={{ maxWidth: 900 }}>
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>Balance sheet</h1>
        {r && (r.balanced ? <span className="f-ok">✓ Balances</span> : <span className="f-bad">Does not balance</span>)}
        <span className="spacer" />
        <Btn variant="secondary" onClick={() => apiDownload(`/ledger/reports/balance-sheet?as_of=${asOf}&export=xlsx`).catch((e) => setError(e.message))}>⬇ Excel</Btn>
      </div>
      <div className="f-bar">
        <span style={{ fontSize: 13 }}>As at</span>
        <input type="date" style={{ ...inputStyle, width: 160 }} value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        <button className="f-link" style={{ fontSize: 12.5 }} onClick={() => setAsOf(today())}>Today</button>
      </div>
      {error && <p className="f-bad">{error}</p>}
      {!r ? <div style={card}>Loading…</div> : (
        <div style={{ ...card, padding: 0 }}>
          <table className="f-table">
            <thead><tr><th>As at {fmtDate(r.as_of)}</th><th style={{ textAlign: "right" }}>MVR</th></tr></thead>
            <tbody>
              <tr className="f-group"><td colSpan={2} style={{ fontSize: 14 }}>ASSETS</td></tr>
              <Section sec={s.BANK} go={go} /><Section sec={s.AR} go={go} /><Section sec={s.OTHER_CURRENT_ASSET} go={go} />
              <Total label="Total current assets" value={r.current_assets} />
              <Section sec={s.FIXED_ASSET} go={go} /><Section sec={s.OTHER_ASSET} go={go} />
              <Total label="Total assets" value={r.total_assets} strong />
              <tr className="f-group"><td colSpan={2} style={{ fontSize: 14 }}>LIABILITIES</td></tr>
              <Section sec={s.AP} go={go} /><Section sec={s.CREDIT_CARD} go={go} /><Section sec={s.OTHER_CURRENT_LIABILITY} go={go} />
              <Total label="Total current liabilities" value={r.current_liabilities} />
              <Section sec={s.LONG_TERM_LIABILITY} go={go} />
              <Total label="Total liabilities" value={r.total_liabilities} />
              <tr className="f-group"><td colSpan={2} style={{ fontSize: 14 }}>EQUITY</td></tr>
              <Section sec={s.EQUITY} go={go} label="Equity accounts" />
              {Number(r.net_profit_earlier_years) !== 0 && (
                <tr><td style={{ paddingLeft: 22 }}>Net profit — earlier years, not yet closed</td>
                  <td className="f-num">{neg(r.net_profit_earlier_years)}</td></tr>
              )}
              <tr><td style={{ paddingLeft: 22 }}>Net profit for the year</td><td className="f-num">{neg(r.net_profit_this_year)}</td></tr>
              <Total label="Total equity" value={r.total_equity} />
              <Total label="Total liabilities and equity" value={r.total_liabilities_and_equity} strong />
            </tbody>
          </table>
        </div>
      )}
      <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
        Profit not yet moved to retained earnings shows on its own lines under equity, so the sheet balances on any date.</p>
    </div>
  );
}
