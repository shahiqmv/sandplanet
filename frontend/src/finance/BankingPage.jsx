// Banking, QuickBooks-style: the bank and cash accounts with their registers,
// and the three forms that move money — Expense, Deposit, Transfer. Each form
// posts its own balanced entry; nobody types debits and credits here
// (FINANCE_BUILD_BRIEF.md, stage 2).
import { useCallback, useEffect, useState } from "react";
import { api, apiDownload, apiUpload } from "../api.js";
import { Btn, Chip, card, ghostButton, inputStyle } from "../ui.jsx";
import { amt, fmtDate, money, today, tree } from "./shared.jsx";
import { LinesTable, MONEY, VoidBar, blank, field, lab, lineSums, linesFromTxn, linesPayload, num, useBooks } from "./forms.jsx";

const TITLE = { EXPENSE: "Expense", DEPOSIT: "Deposit", TRANSFER: "Transfer" };
// payments made and received live with their bills and invoices
const ELSEWHERE = { BILL_PAY: "bills", RECEIPT: "invoices" };

// ---- Expense / Deposit ------------------------------------------------------------

function MoneyForm({ type, id, presetAccount, go }) {
  const books = useBooks();
  const { meta, fx, banks, pick } = books;
  const expense = type === "EXPENSE";
  const [h, setH] = useState({ date: today(), account: presetAccount || "", party: "", party_tin: "", reference: "",
                               memo: "", fx_rate: "", tax_invoice_no: "", tax_invoice_date: "", tax_invoice_held: false });
  const [lines, setLines] = useState([blank(), blank()]);
  const [inclusive, setInclusive] = useState(false);
  const [file, setFile] = useState(null);
  const [existing, setExisting] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const bank = banks.find((b) => String(b.id) === String(h.account));
  const ccy = bank?.currency || "MVR";

  useEffect(() => { if (!h.account && banks.length && !id) setH((x) => ({ ...x, account: String((banks.find((b) => b.is_bank && !b.currency) || banks.find((b) => !b.currency) || banks[0]).id) })); }, [banks]); // eslint-disable-line
  useEffect(() => { if (bank?.currency && !h.fx_rate && fx) setH((x) => ({ ...x, fx_rate: fx })); }, [bank, fx]); // eslint-disable-line
  useEffect(() => {
    if (!id || !pick.length) return;
    api(`/ledger/txns/${id}`).then((t) => {
      setExisting(t);
      setH({ date: t.date, account: String(t.account), party: t.party, party_tin: t.party_tin, reference: t.reference,
             memo: t.memo, fx_rate: t.fx_rate || "", tax_invoice_no: t.tax_invoice_no,
             tax_invoice_date: t.tax_invoice_date || "", tax_invoice_held: t.tax_invoice_held });
      setLines(linesFromTxn(t));
    }).catch((e) => setError(e.message));
  }, [id, pick.length]);

  const { sums, gst, total } = lineSums(lines, num(meta?.gst_rate), inclusive);

  async function save() {
    setBusy(true); setError(null);
    const payload = { type, ...h, account: Number(h.account), fx_rate: bank?.currency ? h.fx_rate : null,
      lines: linesPayload(lines, sums) };
    try {
      const path = existing ? `/ledger/txns/${existing.id}` : "/ledger/txns";
      const method = existing ? "PATCH" : "POST";
      let saved;
      if (file) {
        const fd = new FormData(); fd.append("payload", JSON.stringify(payload)); fd.append("attachment", file);
        saved = await apiUpload(path, fd, method);
      } else saved = await api(path, { method, body: payload });
      go("banking", `reg-${saved.account}`);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  const isVoid = existing?.status === "VOID";
  const hasGst = gst > 0;
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>{existing ? `${TITLE[type]} ${existing.number}` : `New ${TITLE[type].toLowerCase()}`}</h1>
        {isVoid && <Chip tone="alert">Void — {existing.void_reason}</Chip>}
        {existing?.journal_ref && <button className="f-link" onClick={() => go("journals", existing.journal)}>entry {existing.journal_ref}</button>}
        <span className="spacer" />
        <button style={ghostButton} onClick={() => go("banking", h.account ? `reg-${h.account}` : null)}>← Back</button>
      </div>

      <div style={{ ...card, marginBottom: 12 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: "10px 16px" }}>
          <label style={field}>{lab(expense ? "Paid from" : "Deposit to")}
            <select style={inputStyle} value={h.account} onChange={(e) => setH({ ...h, account: e.target.value, fx_rate: "" })}>
              <option value="">— pick —</option>
              {banks.map((b) => <option key={b.id} value={b.id}>{b.name}{b.currency ? ` (${b.currency})` : ""}</option>)}
            </select></label>
          <label style={field}>{lab("Date")}
            <input type="date" style={inputStyle} value={h.date} onChange={(e) => setH({ ...h, date: e.target.value })} /></label>
          <label style={{ ...field, gridColumn: "span 2" }}>{lab(expense ? "Paid to" : "Received from")}
            <input list="f-payees" style={inputStyle} value={h.party} onChange={(e) => setH({ ...h, party: e.target.value })}
                   placeholder={expense ? "Supplier or person" : "Customer or source"} />
            <datalist id="f-payees">{(meta?.payees || []).map((p) => <option key={p} value={p} />)}</datalist></label>
          <label style={field}>{lab(expense ? "Cheque / transfer ref" : "Deposit slip / ref")}
            <input style={inputStyle} value={h.reference} onChange={(e) => setH({ ...h, reference: e.target.value })} /></label>
          {bank?.currency && (
            <label style={field}>{lab(`${bank.currency} rate to MVR`)}
              <input style={inputStyle} value={h.fx_rate} onChange={(e) => setH({ ...h, fx_rate: e.target.value })} /></label>
          )}
        </div>
      </div>

      <LinesTable books={books} lines={lines} setLines={setLines} inclusive={inclusive} setInclusive={setInclusive}
                  ccy={ccy} heading={expense ? "What for (account)" : "From (account)"} word={expense ? "paid" : "deposited"}
                  mvrRate={bank?.currency ? num(h.fx_rate) : 0} />

      {expense && (
        <div style={{ ...card, marginTop: 12, background: hasGst && !h.tax_invoice_held ? "var(--amber-bg, #fff4de)" : undefined }}>
          <div style={{ fontWeight: 700, fontSize: 13.5, marginBottom: 8 }}>Supplier's tax invoice</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: "10px 16px" }}>
            <label style={field}>{lab("Supplier TIN")}
              <input style={inputStyle} value={h.party_tin} onChange={(e) => setH({ ...h, party_tin: e.target.value })} /></label>
            <label style={field}>{lab("Tax invoice no.")}
              <input style={inputStyle} value={h.tax_invoice_no} onChange={(e) => setH({ ...h, tax_invoice_no: e.target.value })} /></label>
            <label style={field}>{lab("Tax invoice date")}
              <input type="date" style={inputStyle} value={h.tax_invoice_date} onChange={(e) => setH({ ...h, tax_invoice_date: e.target.value })} /></label>
          </div>
          <label style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 10, fontSize: 13.5, cursor: "pointer" }}>
            <input type="checkbox" checked={h.tax_invoice_held} style={{ marginTop: 3 }}
                   onChange={(e) => setH({ ...h, tax_invoice_held: e.target.checked })} />
            <span><b>We hold a valid tax invoice for this.</b>{" "}
              {h.tax_invoice_held
                ? "The GST goes to input tax, to be claimed on the GST return."
                : hasGst ? `Without one the GST of ${ccy} ${money(gst)} can't be claimed (MIRA) — it is added to the cost.`
                  : "Tick it when the supplier's tax invoice is in hand — input tax can only be claimed against one."}</span>
          </label>
        </div>
      )}

      <div style={{ ...card, marginTop: 12 }}>
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16 }}>
          <label style={field}>{lab("Memo")}
            <input style={inputStyle} value={h.memo} onChange={(e) => setH({ ...h, memo: e.target.value })} /></label>
          <label style={field}>{lab(expense ? "Attach the bill or receipt" : "Attach the slip")}
            <input type="file" accept="image/*,.pdf" style={{ fontSize: 12 }} onChange={(e) => setFile(e.target.files[0] || null)} />
            {existing?.attachment_url && <a href={existing.attachment_url} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>Open the attached document</a>}
          </label>
        </div>
      </div>

      {error && <p className="f-bad" style={{ fontSize: 13 }}>{error}</p>}
      {!isVoid && (
        <div className="f-bar" style={{ marginTop: 12 }}>
          <Btn disabled={busy || !h.account || total <= 0} onClick={save}>{busy ? "Saving…" : existing ? "Save changes" : `Save ${TITLE[type].toLowerCase()}`}</Btn>
          {existing && <VoidBar txnId={existing.id} onError={setError} onDone={() => go("banking", `reg-${existing.account}`)} />}
          {existing && <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
            Saving a change reverses the old entry and posts a new one — the history stays in the journals.</span>}
        </div>
      )}
    </div>
  );
}

// ---- Transfer ----------------------------------------------------------------------

function TransferForm({ id, presetAccount, go }) {
  const { banks, fx } = useBooks();
  const [h, setH] = useState({ date: today(), account: presetAccount || "", to_account: "", amount: "", amount_to: "",
                               fx_rate: "", reference: "", memo: "" });
  const [existing, setExisting] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!id) return;
    api(`/ledger/txns/${id}`).then((t) => {
      setExisting(t);
      setH({ date: t.date, account: String(t.account), to_account: String(t.to_account), amount: String(t.amount),
             amount_to: t.amount_to ? String(t.amount_to) : "", fx_rate: t.fx_rate || "", reference: t.reference, memo: t.memo });
    }).catch((e) => setError(e.message));
  }, [id]);
  const src = banks.find((b) => String(b.id) === String(h.account));
  const dst = banks.find((b) => String(b.id) === String(h.to_account));
  const c1 = src?.currency || "MVR", c2 = dst?.currency || "MVR";
  const cross = src && dst && c1 !== c2;
  const bothFc = src && dst && c1 === c2 && c1 !== "MVR";
  useEffect(() => { if (bothFc && !h.fx_rate && fx) setH((x) => ({ ...x, fx_rate: fx })); }, [bothFc, fx]); // eslint-disable-line
  const implied = cross && num(h.amount) && num(h.amount_to)
    ? (c1 === "MVR" ? num(h.amount) / num(h.amount_to) : num(h.amount_to) / num(h.amount)) : null;

  async function save() {
    setBusy(true); setError(null);
    const body = { type: "TRANSFER", date: h.date, account: Number(h.account), to_account: Number(h.to_account),
                   amount: num(h.amount), amount_to: cross ? num(h.amount_to) : null, fx_rate: bothFc ? h.fx_rate : null,
                   reference: h.reference, memo: h.memo };
    try {
      const saved = existing ? await api(`/ledger/txns/${existing.id}`, { method: "PATCH", body })
                             : await api("/ledger/txns", { method: "POST", body });
      go("banking", `reg-${saved.account}`);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const isVoid = existing?.status === "VOID";
  const opt = (b) => <option key={b.id} value={b.id}>{b.name}{b.currency ? ` (${b.currency})` : ""}</option>;
  return (
    <div className="t-page" style={{ maxWidth: 760 }}>
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>{existing ? `Transfer ${existing.number}` : "New transfer"}</h1>
        {isVoid && <Chip tone="alert">Void — {existing.void_reason}</Chip>}
        <span className="spacer" />
        <button style={ghostButton} onClick={() => go("banking", h.account ? `reg-${h.account}` : null)}>← Back</button>
      </div>
      <div style={card}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px 16px" }}>
          <label style={field}>{lab("From")}
            <select style={inputStyle} value={h.account} onChange={(e) => setH({ ...h, account: e.target.value })}>
              <option value="">— pick —</option>{banks.map(opt)}</select></label>
          <label style={field}>{lab("To")}
            <select style={inputStyle} value={h.to_account} onChange={(e) => setH({ ...h, to_account: e.target.value })}>
              <option value="">— pick —</option>{banks.filter((b) => String(b.id) !== String(h.account)).map(opt)}</select></label>
          <label style={field}>{lab(`Amount sent (${c1})`)}
            <input style={{ ...inputStyle, textAlign: "right" }} value={h.amount} onChange={(e) => setH({ ...h, amount: e.target.value })} /></label>
          {cross ? (
            <label style={field}>{lab(`Amount received (${c2})`)}
              <input style={{ ...inputStyle, textAlign: "right" }} value={h.amount_to} onChange={(e) => setH({ ...h, amount_to: e.target.value })} />
              {implied && <span style={{ fontSize: 12, color: "var(--muted)" }}>That is a rate of MVR {implied.toFixed(4)} per {c1 === "MVR" ? c2 : c1}.</span>}
            </label>
          ) : bothFc ? (
            <label style={field}>{lab(`${c1} rate to MVR`)}
              <input style={{ ...inputStyle, textAlign: "right" }} value={h.fx_rate} onChange={(e) => setH({ ...h, fx_rate: e.target.value })} /></label>
          ) : <span />}
          <label style={field}>{lab("Date")}
            <input type="date" style={inputStyle} value={h.date} onChange={(e) => setH({ ...h, date: e.target.value })} /></label>
          <label style={field}>{lab("Reference")}
            <input style={inputStyle} value={h.reference} onChange={(e) => setH({ ...h, reference: e.target.value })} /></label>
          <label style={{ ...field, gridColumn: "1 / -1" }}>{lab("Memo")}
            <input style={inputStyle} value={h.memo} onChange={(e) => setH({ ...h, memo: e.target.value })} /></label>
        </div>
        <p style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 0 }}>
          Moves money between two of the company's own accounts. A bank's charge for it is entered as an expense.</p>
      </div>
      {error && <p className="f-bad" style={{ fontSize: 13 }}>{error}</p>}
      {!isVoid && (
        <div className="f-bar" style={{ marginTop: 12 }}>
          <Btn disabled={busy || !h.account || !h.to_account || !num(h.amount)} onClick={save}>{busy ? "Saving…" : existing ? "Save changes" : "Save transfer"}</Btn>
          {existing && <VoidBar txnId={existing.id} onError={setError} onDone={() => go("banking", `reg-${existing.account}`)} />}
        </div>
      )}
    </div>
  );
}

// ---- Register ----------------------------------------------------------------------

function Register({ accountId, go, settings, canEdit }) {
  const start = settings?.books_start_date;
  const [from, setFrom] = useState(start || `${new Date().getFullYear()}-01-01`);
  const [to, setTo] = useState(today());
  const [reg, setReg] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { if (start) setFrom(start); }, [start]);
  useEffect(() => {
    setReg(null);
    api(`/ledger/accounts/${accountId}/register?from=${from}&to=${to}`).then(setReg).catch((e) => setError(e.message));
  }, [accountId, from, to]);
  const openRow = (r) => (!r.txn ? go("journals", r.entry)
    : ELSEWHERE[r.txn_type] ? go(ELSEWHERE[r.txn_type], `payment-${r.txn}`) : go("banking", `txn-${r.txn}`));
  const c = reg?.account.currency;
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>{reg ? reg.account.name : "Register"}</h1>
        {reg && <Chip tone="info">{c}</Chip>}
        {reg && <span style={{ fontSize: 15, fontWeight: 700 }}>Balance {c} {money(reg.closing)}</span>}
        <span className="spacer" />
        <button style={ghostButton} onClick={() => go("banking")}>← All accounts</button>
      </div>
      <div className="f-bar">
        {canEdit && <>
          <Btn onClick={() => go("banking", `new-expense-${accountId}`)}>+ Expense</Btn>
          <Btn onClick={() => go("banking", `new-deposit-${accountId}`)}>+ Deposit</Btn>
          <Btn variant="secondary" onClick={() => go("banking", `new-transfer-${accountId}`)}>+ Transfer</Btn>
        </>}
        <span className="spacer" />
        <input type="date" style={{ ...inputStyle, width: 150 }} value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From" />
        <span style={{ color: "var(--muted)" }}>to</span>
        <input type="date" style={{ ...inputStyle, width: 150 }} value={to} onChange={(e) => setTo(e.target.value)} aria-label="To" />
        <Btn variant="secondary" onClick={() => apiDownload(`/ledger/accounts/${accountId}/register?from=${from}&to=${to}&export=xlsx`).catch((e) => setError(e.message))}>⬇ Excel</Btn>
      </div>
      {error && <p className="f-bad">{error}</p>}
      {!reg ? <div style={card}>Loading…</div> : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table className="f-table">
            <thead><tr><th>Date</th><th>Number</th><th>Payee</th><th>Memo</th><th>Account</th>
              <th style={{ textAlign: "right" }}>Payment</th><th style={{ textAlign: "right" }}>Deposit</th>
              <th style={{ textAlign: "right" }}>Balance</th></tr></thead>
            <tbody>
              <tr className="f-group"><td colSpan={7}>Brought forward at {fmtDate(reg.date_from)}</td><td className="f-num">{money(reg.opening)}</td></tr>
              {reg.rows.map((r, i) => (
                <tr key={i} className="f-click" onClick={() => openRow(r)}>
                  <td style={{ whiteSpace: "nowrap" }}>{fmtDate(r.date)}</td>
                  <td style={{ fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>{r.number}</td>
                  <td>{r.payee}</td>
                  <td>{r.memo}{r.reference && <span style={{ color: "var(--muted)" }}> · {r.reference}</span>}</td>
                  <td style={{ color: "var(--muted)" }}>{r.split}</td>
                  <td className="f-num">{amt(r.payment)}</td>
                  <td className="f-num" style={{ color: "var(--green-fg, #1a7f37)" }}>{amt(r.deposit)}</td>
                  <td className="f-num">{money(r.balance)}</td>
                </tr>
              ))}
              {reg.rows.length === 0 && <tr><td colSpan={8} style={{ color: "var(--muted)" }}>Nothing in this period.</td></tr>}
              <tr className="f-total"><td colSpan={5}>Total · balance at {fmtDate(reg.date_to)}</td>
                <td className="f-num">{money(reg.payments)}</td><td className="f-num">{money(reg.deposits)}</td>
                <td className="f-num">{money(reg.closing)}</td></tr>
            </tbody>
          </table>
        </div>
      )}
      <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
        Click a line to open it. A changed or voided transaction shows once here, as on the bank statement; its full
        history is in the journals.</p>
    </div>
  );
}

// ---- Banking home --------------------------------------------------------------------

function Home({ go, canEdit }) {
  const [accounts, setAccounts] = useState(null);
  const [recent, setRecent] = useState(null);
  const load = useCallback(() => {
    api("/ledger/accounts").then((d) => setAccounts(tree(d.accounts).filter((a) => !a.is_group && MONEY.includes(a.type) && a.is_active)));
    api("/ledger/txns?limit=15&type=EXPENSE,DEPOSIT,TRANSFER,BILL_PAY,RECEIPT").then(setRecent).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);
  if (!accounts) return <div style={card}>Loading…</div>;
  if (!accounts.length) return <div style={card}>No bank or cash accounts yet — set up the chart of accounts first.</div>;
  const total = accounts.reduce((s, a) => s + Number(a.balance || 0), 0);
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>Banking</h1>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>Cash and bank per the books: <b style={{ color: "var(--ink)" }}>MVR {money(total)}</b></span>
        <span className="spacer" />
        {canEdit && <>
          <Btn onClick={() => go("banking", "new-expense")}>+ Expense</Btn>
          <Btn onClick={() => go("banking", "new-deposit")}>+ Deposit</Btn>
          <Btn variant="secondary" onClick={() => go("banking", "new-transfer")}>+ Transfer</Btn>
        </>}
      </div>
      <div className="t-tiles">
        {accounts.map((a) => (
          <button key={a.id} className="t-tile" onClick={() => go("banking", `reg-${a.id}`)}>
            <span className="t-tile-n" style={{ fontSize: 19 }}>
              {a.currency ? `${a.currency} ${money(a.balance_fc)}` : `MVR ${money(a.balance)}`}
            </span>
            <span className="t-tile-l">{a.name}</span>
            <span className="t-tile-s">{a.currency ? `MVR ${money(a.balance)} in the books · ` : ""}open register</span>
          </button>
        ))}
      </div>
      <h3 style={{ margin: "18px 0 8px" }}>Latest transactions</h3>
      {!recent ? <div style={card}>Loading…</div> : recent.txns.length === 0 ? (
        <div style={card}>Nothing entered yet. Use the buttons above to record money going out, coming in, or moving between accounts.</div>
      ) : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table className="f-table">
            <thead><tr><th>Date</th><th>Number</th><th>Type</th><th>Account</th><th>Payee / to</th><th>Memo</th>
              <th style={{ textAlign: "right" }}>Amount</th></tr></thead>
            <tbody>{recent.txns.map((t) => (
              <tr key={t.id} className="f-click"
                  onClick={() => (ELSEWHERE[t.type] ? go(ELSEWHERE[t.type], `payment-${t.id}`) : go("banking", `txn-${t.id}`))}>
                <td style={{ whiteSpace: "nowrap" }}>{fmtDate(t.date)}</td>
                <td style={{ fontFamily: "var(--font-mono)" }}>{t.number}</td><td>{t.type_label}</td>
                <td>{t.account_name}</td><td>{t.party || t.to_account_name}</td><td>{t.memo}</td>
                <td className="f-num">{t.currency} {money(t.amount)}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// sub: null | reg-<id> | new-expense[-<acct>] | new-deposit[-<acct>] | new-transfer[-<acct>] | txn-<id>
export default function BankingPage({ sub, go, settings, canEdit }) {
  const [txn, setTxn] = useState(null);
  const m = /^txn-(\d+)$/.exec(sub || "");
  useEffect(() => {
    setTxn(null);
    if (m) api(`/ledger/txns/${m[1]}`).then(setTxn).catch(() => setTxn({ missing: true }));
  }, [sub]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!sub) return <Home go={go} canEdit={canEdit} />;
  const reg = /^reg-(\d+)$/.exec(sub);
  if (reg) return <Register accountId={Number(reg[1])} go={go} settings={settings} canEdit={canEdit} key={reg[1]} />;
  const nw = /^new-(expense|deposit|transfer)(?:-(\d+))?$/.exec(sub);
  if (nw) {
    return nw[1] === "transfer" ? <TransferForm presetAccount={nw[2]} go={go} />
      : <MoneyForm type={nw[1].toUpperCase()} presetAccount={nw[2]} go={go} />;
  }
  if (m) {
    if (!txn) return <div style={card}>Loading…</div>;
    if (txn.missing) return <div style={card}>That transaction can't be found.</div>;
    if (!TITLE[txn.type]) return <div style={card}>{txn.number} is kept under {txn.type === "BILL" || txn.type === "BILL_PAY" ? "Purchases" : "Sales"}.</div>;
    return txn.type === "TRANSFER" ? <TransferForm id={txn.id} go={go} /> : <MoneyForm type={txn.type} id={txn.id} go={go} />;
  }
  return <Home go={go} canEdit={canEdit} />;
}
