// Reconcile, QuickBooks-style: agree a bank or cash account to the bank's
// statement. Tick off what the bank also shows; when the ticks come to the
// statement's closing balance it is finished, and what is left is outstanding.
// The bank's own file (Excel / CSV) can do most of the ticking.
// (FINANCE_BUILD_BRIEF.md, stage 2)
import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiDownload, apiUpload } from "../api.js";
import { Btn, Chip, card, ghostButton, inputStyle } from "../ui.jsx";
import { fmtDate, money, today, tree } from "./shared.jsx";
import { MONEY, field, lab, num } from "./forms.jsx";

const ELSEWHERE = { BILL_PAY: "bills", RECEIPT: "invoices" };
const openLine = (go, r) => (!r.txn ? go("journals", r.entry)
  : ELSEWHERE[r.txn_type] ? go(ELSEWHERE[r.txn_type], `payment-${r.txn}`) : go("banking", `txn-${r.txn}`));

// ---- every account, and how far each is reconciled ---------------------------------

function Accounts({ go }) {
  const [accounts, setAccounts] = useState(null);
  useEffect(() => {
    api("/ledger/accounts").then((d) => setAccounts(tree(d.accounts).filter((a) => !a.is_group && MONEY.includes(a.type) && a.is_active)));
  }, []);
  if (!accounts) return <div style={card}>Loading…</div>;
  return (
    <div className="t-page">
      <h1 className="t-h1">Reconcile</h1>
      <p style={{ fontSize: 13.5, color: "var(--muted)", marginTop: -6, maxWidth: 760 }}>
        Agree each account to the bank's statement, month by month. What the bank shows is ticked off; what is left is
        outstanding — a cheque not yet presented, a deposit not yet credited.</p>
      {accounts.length === 0 ? <div style={card}>No bank or cash accounts yet.</div> : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table className="f-table">
            <thead><tr><th>Account</th><th>Currency</th><th>Reconciled to</th><th style={{ textAlign: "right" }}>Balance per the books</th><th /></tr></thead>
            <tbody>{accounts.map((a) => (
              <tr key={a.id} className="f-click" onClick={() => go("reconcile", a.reconciling ? String(a.reconciling) : `acct-${a.id}`)}>
                <td style={{ fontWeight: 600 }}>{a.name}</td><td>{a.currency || "MVR"}</td>
                <td>{a.reconciled_to ? fmtDate(a.reconciled_to) : <span style={{ color: "var(--muted)" }}>never</span>}</td>
                <td className="f-num">{a.currency ? `${a.currency} ${money(a.balance_fc)}` : money(a.balance)}</td>
                <td>{a.reconciling ? <Chip tone="warn">In progress — continue</Chip> : <span className="f-link">Reconcile</span>}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---- one account: start a statement, and the ones already done --------------------------

function AccountRecs({ accountId, go }) {
  const [data, setData] = useState(null);
  const [f, setF] = useState({ statement_date: "", statement_balance: "" });
  const [error, setError] = useState(null);
  useEffect(() => { api(`/ledger/accounts/${accountId}/reconciliations`).then(setData).catch((e) => setError(e.message)); }, [accountId]);
  async function start() {
    setError(null);
    try {
      const rec = await api(`/ledger/accounts/${accountId}/reconciliations`, { method: "POST",
        body: { statement_date: f.statement_date, statement_balance: num(f.statement_balance) } });
      go("reconcile", String(rec.id));
    } catch (e) { setError(e.message); }
  }
  if (!data) return <div style={card}>{error || "Loading…"}</div>;
  const c = data.account.currency;
  return (
    <div className="t-page" style={{ maxWidth: 860 }}>
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>Reconcile {data.account.name}</h1>
        <Chip tone="info">{c}</Chip>
        <span className="spacer" />
        <button style={ghostButton} onClick={() => go("reconcile")}>← All accounts</button>
      </div>
      {data.draft ? (
        <div style={card}>A reconciliation of this account is in progress.{" "}
          <button className="f-link" onClick={() => go("reconcile", String(data.draft))}>Continue it</button></div>
      ) : data.can_edit && (
        <div style={card}>
          <div style={{ fontWeight: 700, marginBottom: 8 }}>
            {data.reconciled_to ? `Next statement — the last one ended ${fmtDate(data.reconciled_to)} at ${c} ${money(data.reconciled_balance)}` : "First statement"}</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: "10px 16px" }}>
            <label style={field}>{lab("Statement ends on")}
              <input type="date" style={inputStyle} max={today()} value={f.statement_date} onChange={(e) => setF({ ...f, statement_date: e.target.value })} /></label>
            <label style={field}>{lab(`Closing balance on the statement (${c})`)}
              <input style={{ ...inputStyle, textAlign: "right" }} value={f.statement_balance} onChange={(e) => setF({ ...f, statement_balance: e.target.value })} /></label>
          </div>
          {!data.reconciled_to && <p style={{ fontSize: 12.5, color: "var(--muted)" }}>
            The first time, the opening balance from the audited statements is in the list as a line of its own — tick it with the rest.</p>}
          <div className="f-bar" style={{ marginTop: 10 }}>
            <Btn disabled={!f.statement_date || f.statement_balance === ""} onClick={start}>Start reconciling</Btn>
          </div>
        </div>
      )}
      {error && <p className="f-bad" style={{ fontSize: 13 }}>{error}</p>}
      <h3 style={{ margin: "18px 0 8px" }}>Statements reconciled</h3>
      {data.reconciliations.filter((r) => r.status === "DONE").length === 0 ? <div style={card}>None yet.</div> : (
        <div style={{ ...card, padding: 0 }}>
          <table className="f-table">
            <thead><tr><th>Statement to</th><th style={{ textAlign: "right" }}>Closing balance</th><th>Reconciled by</th><th>On</th></tr></thead>
            <tbody>{data.reconciliations.filter((r) => r.status === "DONE").map((r) => (
              <tr key={r.id} className="f-click" onClick={() => go("reconcile", String(r.id))}>
                <td>{fmtDate(r.statement_date)}</td><td className="f-num">{c} {money(r.statement_balance)}</td>
                <td>{r.finished_by}</td><td>{fmtDate(r.finished_at)}</td></tr>))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---- the working screen ------------------------------------------------------------------

function Side({ title, rows, canTick, onTick, go, c }) {
  const all = rows.length > 0 && rows.every((r) => r.ticked);
  const total = rows.filter((r) => r.ticked).reduce((s, r) => s + Math.abs(Number(r.amount)), 0);
  return (
    <div style={{ ...card, padding: 0, overflowX: "auto", alignSelf: "start" }}>
      <table className="f-table">
        <thead><tr>
          <th style={{ width: 30 }}>{canTick && rows.length > 0 &&
            <input type="checkbox" checked={all} aria-label={`Tick all ${title}`} onChange={(e) => onTick(rows.map((r) => r.id), e.target.checked)} />}</th>
          <th colSpan={3}>{title} · {rows.filter((r) => r.ticked).length} of {rows.length} ticked</th>
          <th style={{ textAlign: "right" }}>{c} {money(total)}</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} style={r.ticked ? { background: "#f3faf4" } : undefined}>
              <td>{canTick ? <input type="checkbox" checked={r.ticked} aria-label={`Tick ${r.number}`} onChange={(e) => onTick([r.id], e.target.checked)} />
                : r.ticked ? "✓" : ""}</td>
              <td style={{ whiteSpace: "nowrap" }}>{fmtDate(r.date)}</td>
              <td><button className="f-link" style={{ fontFamily: "var(--font-mono)" }} onClick={() => openLine(go, r)}>{r.number}</button></td>
              <td>{r.payee || r.memo}{r.reference && <span style={{ color: "var(--muted)" }}> · {r.reference}</span>}
                {r.on_statement && <span style={{ marginLeft: 6, fontSize: 11.5, color: "var(--green-fg, #1a7f37)" }}>on statement {fmtDate(r.statement_date)}</span>}</td>
              <td className="f-num">{money(Math.abs(Number(r.amount)))}</td>
            </tr>))}
          {rows.length === 0 && <tr><td colSpan={5} style={{ color: "var(--muted)" }}>Nothing to tick.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function Working({ id, go }) {
  const [d, setD] = useState(null);
  const [h, setH] = useState(null);                  // statement date / balance being edited
  const [note, setNote] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);
  const take = useCallback((x) => { setD(x); setH({ statement_date: x.statement_date, statement_balance: String(x.statement_balance) }); }, []);
  useEffect(() => {
    api(`/ledger/reconciliations/${id}`).then(async (x) => {
      // back from entering a line the bank showed: pair it now
      if (x.status === "DRAFT" && x.can_edit && x.unmatched.length) {
        try { x = await api(`/ledger/reconciliations/${id}/match`, { method: "POST", body: {} }); } catch { /* shown as loaded */ }
      }
      take(x);
    }).catch((e) => setError(e.message));
  }, [id, take]);

  async function act(action, body = {}) {
    setError(null); setBusy(true);
    try { const x = await api(`/ledger/reconciliations/${id}/${action}`, { method: "POST", body }); take(x); return x; }
    catch (e) { setError(e.message); return null; } finally { setBusy(false); }
  }
  async function onTick(lines, on) {
    // show it at once; the server's answer is the truth
    setD((x) => ({ ...x, rows: x.rows.map((r) => (lines.includes(r.id) ? { ...r, ticked: on } : r)) }));
    await act("tick", { lines, on });
  }
  async function saveHead() {
    if (h.statement_date === d.statement_date && num(h.statement_balance) === Number(d.statement_balance)) return;
    setError(null);
    try { take(await api(`/ledger/reconciliations/${id}`, { method: "PATCH",
      body: { statement_date: h.statement_date, statement_balance: num(h.statement_balance) } })); }
    catch (e) { setError(e.message); setH({ statement_date: d.statement_date, statement_balance: String(d.statement_balance) }); }
  }
  async function importFile(file) {
    if (!file) return;
    setError(null); setNote(null); setBusy(true);
    const fd = new FormData(); fd.append("file", file);
    try {
      const x = await apiUpload(`/ledger/reconciliations/${id}/import`, fd, "POST");
      take(x);
      const i = x.imported;
      setNote(`${i.lines} statement line${i.lines === 1 ? "" : "s"} read — ${i.matched} found in the books and ticked`
        + (x.unmatched.length ? `, ${x.unmatched.length} not in the books` : "")
        + (i.skipped_after_date ? `; ${i.skipped_after_date} dated after the statement date left out` : "")
        + (i.file_closing_balance != null && Number(i.file_closing_balance) !== Number(x.statement_balance)
          ? `. The file's last balance is ${money(i.file_closing_balance)}, not the closing balance entered.` : "."));
    } catch (e) { setError(e.message); } finally { setBusy(false); if (fileRef.current) fileRef.current.value = ""; }
  }
  async function discard() {
    if (!window.confirm("Discard this reconciliation? Every tick made in it is removed.")) return;
    try { await api(`/ledger/reconciliations/${id}`, { method: "DELETE" }); go("reconcile", `acct-${d.account.id}`); }
    catch (e) { setError(e.message); }
  }
  function enter(s) {
    // the bank shows it, the books don't: open the form with it filled in
    const out = Number(s.amount) < 0;
    try {
      sessionStorage.setItem("f_prefill", JSON.stringify({ type: out ? "EXPENSE" : "DEPOSIT", account: d.account.id, date: s.date,
        amount: Math.abs(Number(s.amount)), memo: s.description, reference: s.reference, back: ["reconcile", String(id)] }));
    } catch { /* the form opens blank */ }
    go("banking", out ? `new-expense-${d.account.id}` : `new-deposit-${d.account.id}`);
  }

  if (!d) return <div style={card}>{error || "Loading…"}</div>;
  const c = d.account.currency;
  const draft = d.status === "DRAFT";
  const canTick = draft && d.can_edit;
  const diff = Number(d.difference);
  const outs = d.rows.filter((r) => Number(r.amount) < 0), ins = d.rows.filter((r) => Number(r.amount) > 0);
  const cell = { display: "flex", flexDirection: "column", gap: 2, minWidth: 130 };
  const big = { fontSize: 16, fontWeight: 700, fontVariantNumeric: "tabular-nums" };
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>{d.account.name}</h1>
        <Chip tone={draft ? "warn" : "ok"}>{draft ? "Reconciling" : `Reconciled to ${fmtDate(d.statement_date)}`}</Chip>
        {!draft && d.finished_by && <span style={{ fontSize: 12.5, color: "var(--muted)" }}>by {d.finished_by}, {fmtDate(d.finished_at)}</span>}
        <span className="spacer" />
        {canTick && <>
          <input ref={fileRef} type="file" accept=".xlsx,.xlsm,.csv,.txt" style={{ display: "none" }} onChange={(e) => importFile(e.target.files[0])} />
          <Btn variant="secondary" disabled={busy} onClick={() => fileRef.current?.click()}>⬆ Import the bank's statement</Btn>
        </>}
        <Btn variant="secondary" onClick={() => apiDownload(`/ledger/reconciliations/${id}?export=xlsx`).catch((e) => setError(e.message))}>⬇ Excel</Btn>
        <button style={ghostButton} onClick={() => go("reconcile", `acct-${d.account.id}`)}>← {d.account.name}</button>
      </div>

      <div style={{ ...card, marginBottom: 12, display: "flex", flexWrap: "wrap", gap: "12px 26px", alignItems: "flex-end" }}>
        {canTick ? <>
          <label style={{ ...field, minWidth: 150 }}>{lab("Statement ends on")}
            <input type="date" style={inputStyle} max={today()} value={h.statement_date}
                   onChange={(e) => setH({ ...h, statement_date: e.target.value })} onBlur={saveHead} /></label>
          <label style={{ ...field, minWidth: 170 }}>{lab(`Closing balance (${c})`)}
            <input style={{ ...inputStyle, textAlign: "right" }} value={h.statement_balance}
                   onChange={(e) => setH({ ...h, statement_balance: e.target.value })} onBlur={saveHead} /></label>
        </> : <div style={cell}>{lab("Statement to")}<span style={big}>{fmtDate(d.statement_date)}</span></div>}
        <div style={cell}>{lab("Opening balance")}<span style={big}>{money(d.opening_balance)}</span></div>
        <div style={cell}>{lab("− Money out ticked")}<span style={big}>{money(d.ticked_payments)}</span></div>
        <div style={cell}>{lab("+ Money in ticked")}<span style={big}>{money(d.ticked_deposits)}</span></div>
        <div style={cell}>{lab("= Ticked balance")}<span style={big}>{money(d.cleared_balance)}</span></div>
        {!canTick && <div style={cell}>{lab("Statement balance")}<span style={big}>{money(d.statement_balance)}</span></div>}
        <div style={cell}>{lab("Difference")}
          <span style={big} className={diff === 0 ? "f-ok" : "f-bad"}>{diff === 0 ? "✓ 0.00" : money(d.difference)}</span></div>
        <span style={{ flex: 1 }} />
        {canTick && <Btn disabled={busy || diff !== 0} onClick={() => act("finish")}>Finish</Btn>}
        {canTick && <button className="f-link" onClick={discard}>Discard</button>}
        {!draft && d.can_edit && <Btn variant="secondary" disabled={busy} onClick={() => act("reopen")}>Reopen</Btn>}
      </div>
      {note && <p style={{ fontSize: 13 }} className="t-note">{note}</p>}
      {error && <p className="f-bad" style={{ fontSize: 13 }}>{error}</p>}

      {!draft && (
        <div style={{ ...card, marginBottom: 12, maxWidth: 560 }}>
          <table className="f-table"><tbody>
            <tr><td>Balance per the bank statement</td><td className="f-num">{money(d.statement_balance)}</td></tr>
            <tr><td>Add: deposits not yet on the statement</td><td className="f-num">{money(d.outstanding_deposits)}</td></tr>
            <tr><td>Less: payments not yet on the statement</td><td className="f-num">({money(d.outstanding_payments)})</td></tr>
            <tr className="f-total"><td>Balance per the books at {fmtDate(d.statement_date)}</td><td className="f-num">{c} {money(d.book_balance)}</td></tr>
          </tbody></table>
        </div>)}

      {draft && d.unmatched.length > 0 && (
        <div style={{ ...card, padding: 0, marginBottom: 12, overflowX: "auto", borderColor: "#e0b252" }}>
          <table className="f-table">
            <thead><tr><th colSpan={5}>On the bank's statement, not in the books — enter each, and it is ticked off</th></tr></thead>
            <tbody>{d.unmatched.map((s) => (
              <tr key={s.id}>
                <td style={{ whiteSpace: "nowrap" }}>{fmtDate(s.date)}</td><td>{s.description}</td><td>{s.reference}</td>
                <td className="f-num">{Number(s.amount) < 0 ? `(${money(-s.amount)})` : money(s.amount)}</td>
                <td>{d.can_edit && <button className="f-link" onClick={() => enter(s)}>{Number(s.amount) < 0 ? "Enter as an expense" : "Enter as a deposit"}</button>}</td>
              </tr>))}</tbody>
          </table>
        </div>)}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(440px, 1fr))", gap: 12 }}>
        <Side title={draft ? "Money out" : "Money out — unticked are still outstanding"} rows={outs} canTick={canTick} onTick={onTick} go={go} c={c} />
        <Side title={draft ? "Money in" : "Money in — unticked are not yet credited"} rows={ins} canTick={canTick} onTick={onTick} go={go} c={c} />
      </div>
      {draft && <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
        Tick what the bank's statement also shows, up to {fmtDate(d.statement_date)}. Ticks are kept as you go — you can leave and come back.
        Once finished, a ticked transaction can't be changed without reopening the reconciliation.</p>}
    </div>
  );
}

// sub: null | acct-<id> | <reconciliation id>
export default function ReconcilePage({ sub, go }) {
  const a = /^acct-(\d+)$/.exec(sub || "");
  if (a) return <AccountRecs accountId={a[1]} go={go} key={a[1]} />;
  if (sub && /^\d+$/.test(sub)) return <Working id={sub} go={go} key={sub} />;
  return <Accounts go={go} />;
}
