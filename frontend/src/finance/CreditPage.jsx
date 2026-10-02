// Buying and selling on credit, QuickBooks-style: Bills and Pay bills,
// Invoices and Receive payment, the suppliers and customers behind them, and
// what is owed either way by age. One set of screens serves both sides —
// `side` is "AP" (purchases) or "AR" (sales). (FINANCE_BUILD_BRIEF.md, stage 2)
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { api, apiDownload, apiUpload } from "../api.js";
import { Btn, Chip, card, ghostButton, inputStyle } from "../ui.jsx";
import { amt, fmtDate, money, today } from "./shared.jsx";
import { LinesTable, VoidBar, blank, field, lab, lineSums, linesFromTxn, linesPayload, num, r2, useBooks } from "./forms.jsx";

const SIDE = {
  AP: { doc: "BILL", pay: "BILL_PAY", kind: "SUPPLIER", page: "bills", partyPage: "suppliers", control: "AP",
        Doc: "Bill", docs: "bills", Party: "Supplier", party: "supplier", names: "suppliers",
        payTitle: "Pay bills", payName: "Bill payment", payments: "Payments made", newPay: "Pay bills",
        refLabel: "Supplier's bill / invoice no.", heading: "What for (account)", word: "billed",
        bankLabel: "Paid from", moved: "left", owe: "we owe" },
  AR: { doc: "INVOICE", pay: "RECEIPT", kind: "CUSTOMER", page: "invoices", partyPage: "customers", control: "AR",
        Doc: "Invoice", docs: "invoices", Party: "Customer", party: "customer", names: "customers",
        payTitle: "Receive payment", payName: "Payment received", payments: "Payments received", newPay: "Receive payment",
        refLabel: "Invoice no. (as issued)", heading: "Income (account)", word: "invoiced",
        bankLabel: "Deposited to", moved: "reached", owe: "owed to us" },
};
const CURRENCIES = ["MVR", "USD", "EUR", "GBP", "SGD", "AED", "INR", "LKR", "CNY"];
const addDays = (iso, n) => {
  const d = new Date(`${iso}T00:00`); d.setDate(d.getDate() + Number(n || 0));
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const daysLate = (due) => Math.floor((new Date(`${today()}T00:00`) - new Date(`${due}T00:00`)) / 86400000);

function StatusChip({ t }) {
  if (t.status === "VOID") return <Chip tone="alert">Void</Chip>;
  if (Number(t.balance) <= 0) return <Chip tone="ok">Paid</Chip>;
  const late = t.due_date ? daysLate(t.due_date) : 0;
  if (late > 0) return <Chip tone="alert">Overdue {late} day{late === 1 ? "" : "s"}</Chip>;
  return <Chip tone={Number(t.paid) > 0 ? "warn" : "info"}>{Number(t.paid) > 0 ? "Part paid" : "Open"}</Chip>;
}

// ---- the list --------------------------------------------------------------------

function DocList({ S, go, canEdit }) {
  const [view, setView] = useState("open");          // open | all | payments
  const [q, setQ] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    setData(null);
    const base = view === "payments" ? `type=${S.pay}` : view === "open" ? `type=${S.doc}&open=1` : `type=${S.doc}&status=all`;
    const t = setTimeout(() => {
      api(`/ledger/txns?${base}&limit=300${q.trim() ? `&q=${encodeURIComponent(q.trim())}` : ""}`).then(setData).catch((e) => setError(e.message));
    }, q ? 250 : 0);
    return () => clearTimeout(t);
  }, [view, q, S]);
  const rows = data?.txns || [];
  const openMvr = view === "open" ? rows.reduce((s, t) => s + Number(t.balance) * (Number(t.fx_rate) || 1), 0) : 0;
  const overdue = view === "open" ? rows.filter((t) => t.due_date && daysLate(t.due_date) > 0).length : 0;
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>{S.Doc}s</h1>
        {view === "open" && data && (
          <span style={{ color: "var(--muted)", fontSize: 13 }}>
            {rows.length === 0 ? `Nothing ${S.owe}.` : <>MVR <b style={{ color: "var(--ink)" }}>{money(openMvr)}</b> {S.owe} on {rows.length} {rows.length === 1 ? S.Doc.toLowerCase() : S.docs}
              {overdue ? <> · <span className="f-bad">{overdue} overdue</span></> : null}</>}
          </span>)}
        <span className="spacer" />
        {canEdit && <>
          <Btn onClick={() => go(S.page, "new")}>+ {S.Doc}</Btn>
          <Btn onClick={() => go(S.page, "pay")}>{S.newPay}</Btn>
          <Btn variant="secondary" onClick={() => go(S.page, "opening")} title="Something still unpaid from before the books opened">+ Opening {S.Doc.toLowerCase()}</Btn>
        </>}
      </div>
      <div className="f-bar">
        {[["open", "Open"], ["all", `All ${S.docs}`], ["payments", S.payments]].map(([k, l]) => (
          <button key={k} className={"f-sub-item" + (view === k ? " is-active" : "")} onClick={() => setView(k)}>{l}</button>))}
        <span className="spacer" />
        <input style={{ ...inputStyle, width: 240 }} placeholder={`Search ${S.party}, number…`} value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {error && <p className="f-bad">{error}</p>}
      {!data ? <div style={card}>Loading…</div> : rows.length === 0 ? (
        <div style={card}>{view === "open" ? `No open ${S.docs}.` : view === "payments" ? "No payments yet." : `No ${S.docs} entered yet.`}
          {view === "open" && canEdit && <> Enter one with <b>+ {S.Doc}</b>{S.doc === "BILL"
            ? " when a supplier's bill arrives and will be paid later; something paid on the spot is an Expense, under Banking."
            : " for a sale to be paid later; money received on the spot is a Deposit, under Banking."}</>}</div>
      ) : view === "payments" ? (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table className="f-table">
            <thead><tr><th>Date</th><th>Number</th><th>{S.Party}</th><th>Account</th><th>Reference</th><th style={{ textAlign: "right" }}>Amount</th></tr></thead>
            <tbody>{rows.map((t) => (
              <tr key={t.id} className="f-click" onClick={() => go(S.page, `payment-${t.id}`)}>
                <td style={{ whiteSpace: "nowrap" }}>{fmtDate(t.date)}</td><td style={{ fontFamily: "var(--font-mono)" }}>{t.number}</td>
                <td>{t.party}</td><td>{t.account_name}</td><td>{t.reference}</td>
                <td className="f-num">{t.currency} {money(t.amount)}</td></tr>))}</tbody>
          </table>
        </div>
      ) : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table className="f-table">
            <thead><tr><th>Date</th><th>Number</th><th>{S.Party}</th><th>{S.doc === "BILL" ? "Their no." : "Invoice no."}</th><th>Due</th>
              <th style={{ textAlign: "right" }}>Amount</th><th style={{ textAlign: "right" }}>Open</th><th /></tr></thead>
            <tbody>{rows.map((t) => (
              <tr key={t.id} className="f-click" onClick={() => go(S.page, String(t.id))}>
                <td style={{ whiteSpace: "nowrap" }}>{fmtDate(t.date)}</td><td style={{ fontFamily: "var(--font-mono)" }}>{t.number}</td>
                <td>{t.party}</td><td>{t.reference}</td><td style={{ whiteSpace: "nowrap" }}>{fmtDate(t.due_date)}</td>
                <td className="f-num">{t.currency} {money(t.amount)}</td>
                <td className="f-num" style={{ fontWeight: 700 }}>{t.status === "VOID" ? "" : amt(t.balance)}</td>
                <td><StatusChip t={t} />{t.is_opening && <span style={{ marginLeft: 6, fontSize: 11.5, color: "var(--muted)" }}>opening</span>}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---- a bill / an invoice ---------------------------------------------------------

function DocForm({ S, id, opening, go, settings, canEdit }) {
  const books = useBooks();
  const { meta, fx, pick, accounts } = books;
  const supplier = S.doc === "BILL";
  const [h, setH] = useState({ party: "", party_tin: "", reference: "", date: opening ? (settings?.opening_date || "") : today(),
    due_date: "", currency: "MVR", fx_rate: "", account: "", memo: "", tax_invoice_held: false, is_opening: !!opening, amount: "" });
  const [dueTouched, setDueTouched] = useState(false);
  const [lines, setLines] = useState([blank(), blank()]);
  const [inclusive, setInclusive] = useState(false);
  const [file, setFile] = useState(null);
  const [existing, setExisting] = useState(null);
  const [parties, setParties] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const controls = useMemo(() => accounts.filter((a) => a.type === S.control && !a.currency), [accounts, S]);
  const known = useMemo(() => Object.fromEntries(parties.map((p) => [p.name.toLowerCase(), p])), [parties]);

  useEffect(() => { api(`/ledger/parties?kind=${S.kind}`).then((d) => setParties(d.parties)).catch(() => {}); }, [S]);
  useEffect(() => { if (!h.account && controls.length && !id) setH((x) => ({ ...x, account: String(controls[0].id) })); }, [controls]); // eslint-disable-line
  useEffect(() => { if (opening && !h.date && settings?.opening_date) setH((x) => ({ ...x, date: settings.opening_date })); }, [settings]); // eslint-disable-line
  useEffect(() => { if (h.currency === "USD" && !h.fx_rate && fx && !id) setH((x) => ({ ...x, fx_rate: fx })); }, [h.currency, fx]); // eslint-disable-line
  useEffect(() => {
    if (!id || !pick.length) return;
    api(`/ledger/txns/${id}`).then((t) => {
      setExisting(t); setDueTouched(true);
      setH({ party: t.party, party_tin: t.party_tin, reference: t.reference, date: t.date, due_date: t.due_date || "",
             currency: t.currency, fx_rate: t.fx_rate || "", account: String(t.account), memo: t.memo,
             tax_invoice_held: t.tax_invoice_held, is_opening: t.is_opening, amount: t.is_opening ? String(t.amount) : "" });
      if (t.lines.length) setLines(linesFromTxn(t));
    }).catch((e) => setError(e.message));
  }, [id, pick.length]);

  // a known supplier or customer brings their TIN, terms and currency
  const who = known[h.party.trim().toLowerCase()];
  function pickParty(name) {
    const p = known[name.trim().toLowerCase()];
    setH((x) => ({ ...x, party: name, ...(p ? { party_tin: x.party_tin || p.tin,
      currency: !existing && p.currency && p.currency !== "MVR" ? p.currency : x.currency } : {}) }));
  }
  const due = dueTouched ? h.due_date : (h.date ? addDays(h.date, who?.credit_days || 0) : "");
  const { sums, gst, total } = lineSums(lines, num(meta?.gst_rate), inclusive);
  const foreign = h.currency !== "MVR";
  const amount = h.is_opening ? num(h.amount) : total;
  const settled = existing && Number(existing.paid) > 0;
  const isVoid = existing?.status === "VOID";
  const readOnly = !canEdit || settled || isVoid;

  async function save() {
    setBusy(true); setError(null);
    const payload = { type: S.doc, ...h, due_date: due || null, account: h.account ? Number(h.account) : null,
      fx_rate: foreign ? h.fx_rate : null, amount: h.is_opening ? num(h.amount) : null,
      lines: h.is_opening ? [] : linesPayload(lines, sums) };
    try {
      const path = existing ? `/ledger/txns/${existing.id}` : "/ledger/txns";
      const method = existing ? "PATCH" : "POST";
      if (file) {
        const fd = new FormData(); fd.append("payload", JSON.stringify(payload)); fd.append("attachment", file);
        await apiUpload(path, fd, method);
      } else await api(path, { method, body: payload });
      go(S.page);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>{existing ? `${S.Doc} ${existing.number}` : h.is_opening ? `Opening ${S.Doc.toLowerCase()}` : `New ${S.Doc.toLowerCase()}`}</h1>
        {existing && <StatusChip t={existing} />}
        {isVoid && <span style={{ fontSize: 13, color: "var(--muted)" }}>{existing.void_reason}</span>}
        {existing?.journal_ref && <button className="f-link" onClick={() => go("journals", existing.journal)}>entry {existing.journal_ref}</button>}
        <span className="spacer" />
        {existing && !isVoid && Number(existing.balance) > 0 && canEdit &&
          <Btn onClick={() => go(S.page, `pay-${existing.party_ref}`)}>{S.newPay}</Btn>}
        <button style={ghostButton} onClick={() => go(S.page)}>← {S.Doc}s</button>
      </div>

      {h.is_opening && (
        <div className="t-note t-note-amber" style={{ maxWidth: 860 }}>
          <b>Still unpaid from before the books opened.</b> Its amount is already inside the opening balances
          ({supplier ? "accounts payable" : "accounts receivable"}), so this posts no entry — it is listed here so that the payment,
          when it comes, has something to be set against. Enter only what was still unpaid on {fmtDate(settings?.opening_date)}.
        </div>)}

      <div style={{ ...card, marginBottom: 12 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: "10px 16px" }}>
          <label style={{ ...field, gridColumn: "span 2" }}>{lab(S.Party)}
            <input list="f-parties" style={inputStyle} value={h.party} disabled={readOnly} onChange={(e) => pickParty(e.target.value)}
                   placeholder={`Type or pick the ${S.party}`} />
            <datalist id="f-parties">{(meta?.[S.names] || []).map((p) => <option key={p} value={p} />)}</datalist>
            {h.party.trim() && !who && !existing && <span style={{ fontSize: 12, color: "var(--muted)" }}>New — will be added to the {S.party} list.</span>}
          </label>
          <label style={field}>{lab(S.refLabel)}
            <input style={inputStyle} value={h.reference} disabled={readOnly} onChange={(e) => setH({ ...h, reference: e.target.value })} /></label>
          <label style={field}>{lab(supplier ? "Supplier TIN" : "Customer TIN")}
            <input style={inputStyle} value={h.party_tin} disabled={readOnly} onChange={(e) => setH({ ...h, party_tin: e.target.value })} /></label>
          <label style={field}>{lab(supplier ? "Bill date" : "Invoice date")}
            <input type="date" style={inputStyle} value={h.date} disabled={readOnly} onChange={(e) => setH({ ...h, date: e.target.value })} /></label>
          <label style={field}>{lab("Due")}
            <input type="date" style={inputStyle} value={due} disabled={readOnly}
                   onChange={(e) => { setDueTouched(true); setH({ ...h, due_date: e.target.value }); }} />
            {!dueTouched && who?.credit_days ? <span style={{ fontSize: 12, color: "var(--muted)" }}>{who.credit_days} days' credit</span> : null}</label>
          <label style={field}>{lab("Currency")}
            <select style={inputStyle} value={h.currency} disabled={readOnly} onChange={(e) => setH({ ...h, currency: e.target.value, fx_rate: "" })}>
              {[...new Set([...CURRENCIES, h.currency])].map((c) => <option key={c}>{c}</option>)}</select></label>
          {foreign && (
            <label style={field}>{lab(`${h.currency} rate to MVR`)}
              <input style={inputStyle} value={h.fx_rate} disabled={readOnly} onChange={(e) => setH({ ...h, fx_rate: e.target.value })} /></label>)}
          <label style={field}>{lab(supplier ? "Payable account" : "Receivable account")}
            <select style={inputStyle} value={h.account} disabled={readOnly} onChange={(e) => setH({ ...h, account: e.target.value })}>
              {controls.map((a) => <option key={a.id} value={a.id}>{a.code} {a.name}</option>)}</select></label>
          {h.is_opening && (
            <label style={field}>{lab(`Still unpaid (${h.currency})`)}
              <input style={{ ...inputStyle, textAlign: "right" }} value={h.amount} disabled={readOnly} onChange={(e) => setH({ ...h, amount: e.target.value })} />
              {foreign && num(h.fx_rate) && num(h.amount) ? <span style={{ fontSize: 12, color: "var(--muted)" }}>= MVR {money(num(h.amount) * num(h.fx_rate))} in the opening balances</span> : null}</label>)}
        </div>
      </div>

      {!h.is_opening && (
        <LinesTable books={books} lines={lines} setLines={setLines} inclusive={inclusive} setInclusive={setInclusive} ccy={h.currency}
                    heading={S.heading} word={S.word} mvrRate={foreign ? num(h.fx_rate) : 0} readOnly={readOnly} />)}

      {supplier && !h.is_opening && (
        <div style={{ ...card, marginTop: 12, background: gst > 0 && !h.tax_invoice_held ? "var(--amber-bg, #fff4de)" : undefined }}>
          <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13.5, cursor: "pointer" }}>
            <input type="checkbox" checked={h.tax_invoice_held} disabled={readOnly} style={{ marginTop: 3 }}
                   onChange={(e) => setH({ ...h, tax_invoice_held: e.target.checked })} />
            <span><b>This bill is a valid tax invoice, and we hold it.</b>{" "}
              {h.tax_invoice_held
                ? "The GST goes to input tax, to be claimed on the GST return. The supplier's TIN is needed."
                : gst > 0 ? `Without one the GST of ${h.currency} ${money(gst)} can't be claimed (MIRA) — it is added to the cost.`
                  : "Tick it when the supplier's tax invoice is in hand — input tax can only be claimed against one."}</span>
          </label>
        </div>)}

      <div style={{ ...card, marginTop: 12 }}>
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16 }}>
          <label style={field}>{lab("Memo")}
            <input style={inputStyle} value={h.memo} disabled={readOnly} onChange={(e) => setH({ ...h, memo: e.target.value })} /></label>
          <label style={field}>{lab(supplier ? "Attach the bill" : "Attach the invoice")}
            {!readOnly && <input type="file" accept="image/*,.pdf" style={{ fontSize: 12 }} onChange={(e) => setFile(e.target.files[0] || null)} />}
            {existing?.attachment_url && <a href={existing.attachment_url} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>Open the attached document</a>}
          </label>
        </div>
      </div>

      {existing?.payments?.length > 0 && (
        <div style={{ ...card, marginTop: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 13.5, marginBottom: 6 }}>Payments against it</div>
          {existing.payments.map((p) => (
            <div key={p.id} style={{ fontSize: 13.5, display: "flex", gap: 14, padding: "3px 0" }}>
              <button className="f-link" onClick={() => go(S.page, `payment-${p.id}`)}>{p.number}</button>
              <span>{fmtDate(p.date)}</span><span className="f-num">{existing.currency} {money(p.amount)}</span></div>))}
          <div style={{ fontSize: 13.5, marginTop: 6 }}>Still open: <b>{existing.currency} {money(existing.balance)}</b></div>
        </div>)}

      {error && <p className="f-bad" style={{ fontSize: 13 }}>{error}</p>}
      {settled && !isVoid && canEdit && <p style={{ fontSize: 12.5, color: "var(--muted)" }}>
        It has a payment against it, so it can't be changed. To correct it, void the payment first.</p>}
      {!readOnly && (
        <div className="f-bar" style={{ marginTop: 12 }}>
          <Btn disabled={busy || !h.party.trim() || !h.reference.trim() || amount <= 0} onClick={save}>
            {busy ? "Saving…" : existing ? "Save changes" : `Save ${S.Doc.toLowerCase()}`}</Btn>
          {existing && <VoidBar txnId={existing.id} onError={setError} onDone={() => go(S.page)} />}
          {existing && !h.is_opening && <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
            Saving a change reverses the old entry and posts a new one — the history stays in the journals.</span>}
        </div>)}
    </div>
  );
}

// ---- pay bills / receive payment -------------------------------------------------

function PayForm({ S, partyId, go }) {
  const { banks, fx } = useBooks();
  const [parties, setParties] = useState(null);
  const [party, setParty] = useState(partyId || "");
  const [open, setOpen] = useState(null);
  const [pay, setPay] = useState({});                 // doc id → amount typed
  const [h, setH] = useState({ account: "", date: today(), reference: "", memo: "", fx_rate: "", amount: "" });
  const [file, setFile] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api(`/ledger/parties?kind=${S.kind}`).then((d) => setParties(d.parties.filter((p) => p.open > 0))).catch((e) => setError(e.message)); }, [S]);
  useEffect(() => {
    setOpen(null); setPay({});
    if (party) api(`/ledger/txns?type=${S.doc}&open=1&party=${party}&limit=300`).then((d) => setOpen(d.txns)).catch((e) => setError(e.message));
  }, [party, S]);
  useEffect(() => { if (!h.account && banks.length) setH((x) => ({ ...x, account: String((banks.find((b) => b.is_bank && !b.currency) || banks[0]).id) })); }, [banks]); // eslint-disable-line

  const bank = banks.find((b) => String(b.id) === String(h.account));
  const bankCur = bank?.currency || "MVR";
  const ticked = (open || []).filter((t) => num(pay[t.id]) > 0);
  const cur = ticked[0]?.currency || (open || [])[0]?.currency || "MVR";
  const mixed = ticked.some((t) => t.currency !== cur);
  const applied = r2(ticked.reduce((s, t) => s + num(pay[t.id]), 0));
  const sameFc = cur === bankCur && cur !== "MVR";
  const needMvr = cur !== "MVR" && bankCur === "MVR";       // foreign bills from a rufiyaa account
  const needFc = cur === "MVR" && bankCur !== "MVR";        // rufiyaa bills from a foreign account
  useEffect(() => { if (sameFc && !h.fx_rate && fx) setH((x) => ({ ...x, fx_rate: fx })); }, [sameFc, fx]); // eslint-disable-line
  const tick = (t, on) => setPay((p) => ({ ...p, [t.id]: on ? String(t.balance) : "" }));

  async function save() {
    setBusy(true); setError(null);
    const payload = { type: S.pay, account: Number(h.account), date: h.date, reference: h.reference, memo: h.memo,
      fx_rate: sameFc ? h.fx_rate : null, amount: needMvr || needFc ? num(h.amount) : null,
      applies: ticked.map((t) => ({ doc: t.id, amount: num(pay[t.id]) })) };
    try {
      if (file) {
        const fd = new FormData(); fd.append("payload", JSON.stringify(payload)); fd.append("attachment", file);
        await apiUpload("/ledger/txns", fd, "POST");
      } else await api("/ledger/txns", { method: "POST", body: payload });
      go(S.page);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>{S.payTitle}</h1>
        <span className="spacer" />
        <button style={ghostButton} onClick={() => go(S.page)}>← {S.Doc}s</button>
      </div>
      {parties && parties.length === 0 ? <div style={card}>There are no open {S.docs} to settle.</div> : (
        <>
          <div style={{ ...card, marginBottom: 12 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: "10px 16px" }}>
              <label style={{ ...field, gridColumn: "span 2" }}>{lab(S.Party)}
                <select style={inputStyle} value={party} onChange={(e) => setParty(e.target.value)}>
                  <option value="">— pick the {S.party} —</option>
                  {(parties || []).map((p) => <option key={p.id} value={p.id}>{p.name} · MVR {money(p.balance)} open</option>)}</select></label>
              <label style={field}>{lab(S.bankLabel)}
                <select style={inputStyle} value={h.account} onChange={(e) => setH({ ...h, account: e.target.value, fx_rate: "", amount: "" })}>
                  {banks.map((b) => <option key={b.id} value={b.id}>{b.name}{b.currency ? ` (${b.currency})` : ""}</option>)}</select></label>
              <label style={field}>{lab("Date")}
                <input type="date" style={inputStyle} value={h.date} onChange={(e) => setH({ ...h, date: e.target.value })} /></label>
              <label style={field}>{lab(S.doc === "BILL" ? "Cheque / transfer ref" : "Their transfer / slip ref")}
                <input style={inputStyle} value={h.reference} onChange={(e) => setH({ ...h, reference: e.target.value })} /></label>
              <label style={{ ...field, gridColumn: "span 2" }}>{lab("Memo")}
                <input style={inputStyle} value={h.memo} onChange={(e) => setH({ ...h, memo: e.target.value })} /></label>
              <label style={field}>{lab(S.doc === "BILL" ? "Attach the payment advice" : "Attach the slip")}
                <input type="file" accept="image/*,.pdf" style={{ fontSize: 12 }} onChange={(e) => setFile(e.target.files[0] || null)} /></label>
            </div>
          </div>
          {party && (!open ? <div style={card}>Loading…</div> : (
            <div style={{ ...card, padding: 0, overflowX: "auto" }}>
              <table className="f-table f-lines">
                <thead><tr><th style={{ width: 34 }} /><th>Date</th><th>Number</th><th>{S.doc === "BILL" ? "Their no." : "Invoice no."}</th><th>Due</th>
                  <th style={{ textAlign: "right" }}>Amount</th><th style={{ textAlign: "right" }}>Open</th>
                  <th style={{ width: 150, textAlign: "right" }}>{S.doc === "BILL" ? "Pay now" : "Received"}</th></tr></thead>
                <tbody>{open.map((t) => (
                  <tr key={t.id}>
                    <td><input type="checkbox" checked={num(pay[t.id]) > 0} onChange={(e) => tick(t, e.target.checked)} aria-label={`Settle ${t.number}`} /></td>
                    <td style={{ whiteSpace: "nowrap" }}>{fmtDate(t.date)}</td><td style={{ fontFamily: "var(--font-mono)" }}>{t.number}</td>
                    <td>{t.reference}</td>
                    <td style={{ whiteSpace: "nowrap" }}>{fmtDate(t.due_date)}{t.due_date && daysLate(t.due_date) > 0 && <span className="f-bad" style={{ fontSize: 12 }}> · {daysLate(t.due_date)}d late</span>}</td>
                    <td className="f-num">{t.currency} {money(t.amount)}</td><td className="f-num">{money(t.balance)}</td>
                    <td><input className="f-amt" value={pay[t.id] || ""} onChange={(e) => setPay({ ...pay, [t.id]: e.target.value })} /></td>
                  </tr>))}</tbody>
                <tfoot><tr><td colSpan={7} style={{ textAlign: "right", fontWeight: 700, paddingTop: 10 }}>
                  {ticked.length} {ticked.length === 1 ? S.Doc.toLowerCase() : S.docs} · {cur}</td>
                  <td className="f-num" style={{ fontWeight: 800, fontSize: 15, paddingTop: 10 }}>{money(applied)}</td></tr></tfoot>
              </table>
            </div>))}
          {(sameFc || needMvr || needFc) && applied > 0 && (
            <div style={{ ...card, marginTop: 12, maxWidth: 560 }}>
              {sameFc && <label style={field}>{lab(`${cur} rate to MVR on the day`)}
                <input style={{ ...inputStyle, maxWidth: 200 }} value={h.fx_rate} onChange={(e) => setH({ ...h, fx_rate: e.target.value })} /></label>}
              {needMvr && <label style={field}>{lab(`Rufiyaa that ${S.moved} ${bank?.name} for ${cur} ${money(applied)}`)}
                <input style={{ ...inputStyle, maxWidth: 200, textAlign: "right" }} value={h.amount} onChange={(e) => setH({ ...h, amount: e.target.value })} /></label>}
              {needFc && <label style={field}>{lab(`${bankCur} that ${S.moved} ${bank?.name} for MVR ${money(applied)}`)}
                <input style={{ ...inputStyle, maxWidth: 200, textAlign: "right" }} value={h.amount} onChange={(e) => setH({ ...h, amount: e.target.value })} /></label>}
              <p style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 0 }}>
                {needFc ? "The books take the rate from the two amounts."
                  : `Each ${S.Doc.toLowerCase()} leaves the books at the rate it was entered at; a different rate today goes to exchange gain or loss.`}</p>
            </div>)}
          {mixed && <p className="f-bad" style={{ fontSize: 13 }}>Those {S.docs} are in different currencies — settle each currency with its own payment.</p>}
          {error && <p className="f-bad" style={{ fontSize: 13 }}>{error}</p>}
          <div className="f-bar" style={{ marginTop: 12 }}>
            <Btn disabled={busy || !h.account || applied <= 0 || mixed} onClick={save}>
              {busy ? "Saving…" : S.doc === "BILL" ? `Pay ${cur} ${money(applied)}` : `Receive ${cur} ${money(applied)}`}</Btn>
          </div>
        </>
      )}
    </div>
  );
}

function PaymentView({ S, id, go, canEdit }) {
  const [t, setT] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { api(`/ledger/txns/${id}`).then(setT).catch((e) => setError(e.message)); }, [id]);
  if (!t) return <div style={card}>{error || "Loading…"}</div>;
  const isVoid = t.status === "VOID";
  return (
    <div className="t-page" style={{ maxWidth: 860 }}>
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>{S.payName} {t.number}</h1>
        {isVoid && <Chip tone="alert">Void — {t.void_reason}</Chip>}
        {t.journal_ref && <button className="f-link" onClick={() => go("journals", t.journal)}>entry {t.journal_ref}</button>}
        <span className="spacer" />
        <button style={ghostButton} onClick={() => go(S.page)}>← {S.Doc}s</button>
      </div>
      <div style={card}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: "10px 16px", fontSize: 13.5 }}>
          <div>{lab(S.Party)}<div><button className="f-link" onClick={() => go(S.partyPage, String(t.party_ref))}>{t.party}</button></div></div>
          <div>{lab("Date")}<div>{fmtDate(t.date)}</div></div>
          <div>{lab(S.bankLabel)}<div>{t.account_name}</div></div>
          <div>{lab("Amount")}<div style={{ fontWeight: 700 }}>{t.currency} {money(t.amount)}{t.currency !== "MVR" ? ` = MVR ${money(t.amount_mvr)}` : ""}</div></div>
          {t.reference && <div>{lab("Reference")}<div>{t.reference}</div></div>}
          {t.memo && <div style={{ gridColumn: "span 2" }}>{lab("Memo")}<div>{t.memo}</div></div>}
          {t.attachment_url && <div>{lab("Attached")}<div><a href={t.attachment_url} target="_blank" rel="noreferrer">Open the document</a></div></div>}
        </div>
      </div>
      <div style={{ ...card, padding: 0, marginTop: 12 }}>
        <table className="f-table">
          <thead><tr><th>{S.Doc}</th><th>{S.doc === "BILL" ? "Their no." : "Invoice no."}</th><th>Dated</th><th style={{ textAlign: "right" }}>Settled</th></tr></thead>
          <tbody>{(t.applies || []).map((a) => (
            <tr key={a.doc} className="f-click" onClick={() => go(S.page, String(a.doc))}>
              <td style={{ fontFamily: "var(--font-mono)" }}>{a.number}</td><td>{a.reference}</td><td>{fmtDate(a.date)}</td>
              <td className="f-num">{a.currency} {money(a.amount)}</td></tr>))}</tbody>
        </table>
      </div>
      {error && <p className="f-bad" style={{ fontSize: 13 }}>{error}</p>}
      {!isVoid && canEdit && (
        <div className="f-bar" style={{ marginTop: 12 }}>
          <VoidBar txnId={t.id} onError={setError} onDone={() => go(S.page)} />
          <span style={{ fontSize: 12.5, color: "var(--muted)" }}>A payment isn't changed — void it and enter it again. Voiding reopens the {S.docs} it settled.</span>
        </div>)}
    </div>
  );
}

// sub: null | new | opening | <id> | pay | pay-<party> | payment-<id>
export function DocsPage({ side, sub, go, settings, canEdit }) {
  const S = SIDE[side];
  if (!sub) return <DocList S={S} go={go} canEdit={canEdit} />;
  if (sub === "new" || sub === "opening") return <DocForm S={S} opening={sub === "opening"} go={go} settings={settings} canEdit={canEdit} />;
  const pay = /^pay(?:-(\d+))?$/.exec(sub);
  if (pay) return <PayForm S={S} partyId={pay[1]} go={go} />;
  const pv = /^payment-(\d+)$/.exec(sub);
  if (pv) return <PaymentView S={S} id={pv[1]} go={go} canEdit={canEdit} />;
  if (/^\d+$/.test(sub)) return <DocForm S={S} id={sub} go={go} settings={settings} canEdit={canEdit} />;
  return <DocList S={S} go={go} canEdit={canEdit} />;
}

// ---- suppliers / customers --------------------------------------------------------

const BLANK_PARTY = { name: "", tin: "", contact: "", address: "", credit_days: "", currency: "MVR" };

function PartyFields({ f, setF }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "10px 16px" }}>
      <label style={{ ...field, gridColumn: "span 2" }}>{lab("Name")}
        <input style={inputStyle} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
      <label style={field}>{lab("TIN")}
        <input style={inputStyle} value={f.tin} onChange={(e) => setF({ ...f, tin: e.target.value })} /></label>
      <label style={field}>{lab("Credit days")}
        <input style={inputStyle} value={f.credit_days ?? ""} onChange={(e) => setF({ ...f, credit_days: e.target.value })} /></label>
      <label style={field}>{lab("Usual currency")}
        <select style={inputStyle} value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })}>
          {[...new Set([...CURRENCIES, f.currency])].map((c) => <option key={c}>{c}</option>)}</select></label>
      <label style={field}>{lab("Phone / email")}
        <input style={inputStyle} value={f.contact} onChange={(e) => setF({ ...f, contact: e.target.value })} /></label>
      <label style={{ ...field, gridColumn: "span 2" }}>{lab("Address")}
        <input style={inputStyle} value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} /></label>
    </div>
  );
}

function PartyList({ S, go, canEdit }) {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => api(`/ledger/parties?kind=${S.kind}`).then(setData).catch((e) => setError(e.message)), [S]);
  useEffect(() => { load(); }, [load]);
  async function add() {
    setError(null);
    try { await api("/ledger/parties", { method: "POST", body: { ...adding, kind: S.kind } }); setAdding(null); load(); }
    catch (e) { setError(e.message); }
  }
  const rows = (data?.parties || []).filter((p) => !q.trim() || p.name.toLowerCase().includes(q.trim().toLowerCase()));
  const total = rows.reduce((s, p) => s + Number(p.balance), 0);
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>{S.Party}s</h1>
        {data && <span style={{ color: "var(--muted)", fontSize: 13 }}>MVR <b style={{ color: "var(--ink)" }}>{money(total)}</b> {S.owe}</span>}
        <span className="spacer" />
        <input style={{ ...inputStyle, width: 220 }} placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />
        {canEdit && !adding && <Btn onClick={() => setAdding({ ...BLANK_PARTY })}>+ {S.Party}</Btn>}
      </div>
      {adding && (
        <div style={{ ...card, marginBottom: 12 }}>
          <PartyFields f={adding} setF={setAdding} />
          <div className="f-bar" style={{ marginTop: 12 }}>
            <Btn disabled={!adding.name.trim()} onClick={add}>Add {S.party}</Btn>
            <button className="f-link" onClick={() => setAdding(null)}>cancel</button>
          </div>
        </div>)}
      {error && <p className="f-bad">{error}</p>}
      {!data ? <div style={card}>Loading…</div> : rows.length === 0 ? (
        <div style={card}>No {S.party}s in the books yet. One is added the first time a {S.Doc.toLowerCase()} names them.</div>
      ) : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table className="f-table">
            <thead><tr><th>{S.Party}</th><th>TIN</th><th>Terms</th><th>Currency</th><th style={{ textAlign: "right" }}>Open {S.docs}</th>
              <th style={{ textAlign: "right" }}>Balance (MVR)</th></tr></thead>
            <tbody>{rows.map((p) => (
              <tr key={p.id} className="f-click" onClick={() => go(S.partyPage, String(p.id))} style={p.is_active ? undefined : { opacity: .55 }}>
                <td style={{ fontWeight: 600 }}>{p.name}{p.linked && <span style={{ fontWeight: 400, fontSize: 11.5, color: "var(--muted)" }}> · on {p.linked}</span>}</td>
                <td>{p.tin}</td><td>{p.credit_days != null ? `${p.credit_days} days` : ""}</td><td>{p.currency}</td>
                <td className="f-num">{p.open || ""}</td><td className="f-num" style={{ fontWeight: 700 }}>{amt(p.balance)}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function PartyAccount({ S, id, go }) {
  const [st, setSt] = useState(null);
  const [edit, setEdit] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => api(`/ledger/parties/${id}`).then(setSt).catch((e) => setError(e.message)), [id]);
  useEffect(() => { load(); }, [load]);
  async function save() {
    setError(null);
    try { setSt({ ...(await api(`/ledger/parties/${id}`, { method: "PATCH", body: edit })), can_edit: true }); setEdit(null); }
    catch (e) { setError(e.message); }
  }
  if (!st) return <div style={card}>{error || "Loading…"}</div>;
  const p = st.party;
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>{p.name}</h1>
        <span style={{ fontSize: 15, fontWeight: 700 }}>MVR {money(st.balance)} {S.owe}</span>
        <span className="spacer" />
        {st.can_edit && Number(st.balance) > 0 && <Btn onClick={() => go(S.page, `pay-${p.id}`)}>{S.newPay}</Btn>}
        {st.can_edit && !edit && <Btn variant="secondary" onClick={() => setEdit({ ...p, credit_days: p.credit_days ?? "" })}>Edit details</Btn>}
        <Btn variant="secondary" onClick={() => apiDownload(`/ledger/parties/${id}?export=xlsx`).catch((e) => setError(e.message))}>⬇ Excel</Btn>
        <button style={ghostButton} onClick={() => go(S.partyPage)}>← {S.Party}s</button>
      </div>
      {edit ? (
        <div style={{ ...card, marginBottom: 12 }}>
          <PartyFields f={edit} setF={setEdit} />
          <div className="f-bar" style={{ marginTop: 12 }}>
            <Btn onClick={save}>Save</Btn><button className="f-link" onClick={() => setEdit(null)}>cancel</button>
          </div>
        </div>
      ) : (
        <p style={{ fontSize: 13, color: "var(--muted)", marginTop: 0 }}>
          {[p.tin && `TIN ${p.tin}`, p.credit_days != null && `${p.credit_days} days' credit`, p.currency !== "MVR" && `billed in ${p.currency}`,
            p.contact, p.address, p.linked && `on ${p.linked}`].filter(Boolean).join(" · ") || "No details yet."}</p>
      )}
      {error && <p className="f-bad">{error}</p>}
      <div style={{ ...card, padding: 0, overflowX: "auto" }}>
        <table className="f-table">
          <thead><tr><th>Date</th><th>Number</th><th>What</th><th>{S.doc === "BILL" ? "Their no." : "Reference"}</th><th>Due</th>
            <th style={{ textAlign: "right" }}>Amount</th><th style={{ textAlign: "right" }}>Change (MVR)</th><th style={{ textAlign: "right" }}>Balance (MVR)</th></tr></thead>
          <tbody>
            {st.rows.map((r) => (
              <tr key={r.id} className="f-click" onClick={() => go(S.page, r.type === S.doc ? String(r.id) : `payment-${r.id}`)}>
                <td style={{ whiteSpace: "nowrap" }}>{fmtDate(r.date)}</td><td style={{ fontFamily: "var(--font-mono)" }}>{r.number}</td>
                <td>{r.type_label}{r.is_opening ? " (opening)" : ""}</td><td>{r.reference}</td>
                <td style={{ whiteSpace: "nowrap" }}>{r.due_date ? fmtDate(r.due_date) : ""}</td>
                <td className="f-num">{r.currency} {money(r.amount)}</td>
                <td className="f-num">{money(r.change)}</td><td className="f-num">{money(r.balance)}</td></tr>))}
            {st.rows.length === 0 && <tr><td colSpan={8} style={{ color: "var(--muted)" }}>Nothing with this {S.party} yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function PartiesPage({ side, sub, go, canEdit }) {
  const S = SIDE[side];
  return sub && /^\d+$/.test(sub) ? <PartyAccount S={S} id={sub} go={go} key={sub} /> : <PartyList S={S} go={go} canEdit={canEdit} />;
}

// ---- aging ------------------------------------------------------------------------

const BUCKETS = [["current", "Not yet due"], ["d30", "1–30 days"], ["d60", "31–60 days"], ["d90", "61–90 days"], ["older", "Over 90 days"]];

export function AgingPage({ side, go }) {
  const S = SIDE[side];
  const [asOf, setAsOf] = useState(today());
  const [r, setR] = useState(null);
  const [openRow, setOpenRow] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { setR(null); api(`/ledger/reports/aging?kind=${S.kind}&as_of=${asOf}`).then(setR).catch((e) => setError(e.message)); }, [S, asOf]);
  const agrees = r && Number(r.difference) === 0;
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>{side === "AP" ? "What we owe" : "What we are owed"}</h1>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>by due date · MVR</span>
        <span className="spacer" />
        <span style={{ fontSize: 13 }}>As at</span>
        <input type="date" style={{ ...inputStyle, width: 150 }} value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        <Btn variant="secondary" onClick={() => apiDownload(`/ledger/reports/aging?kind=${S.kind}&as_of=${asOf}&export=xlsx`).catch((e) => setError(e.message))}>⬇ Excel</Btn>
      </div>
      {error && <p className="f-bad">{error}</p>}
      {!r ? <div style={card}>Loading…</div> : (
        <>
          <div style={{ ...card, padding: 0, overflowX: "auto" }}>
            <table className="f-table">
              <thead><tr><th>{S.Party}</th>{BUCKETS.map(([k, l]) => <th key={k} style={{ textAlign: "right" }}>{l}</th>)}<th style={{ textAlign: "right" }}>Total</th></tr></thead>
              <tbody>
                {r.rows.map((row) => (
                  <Fragment key={row.party}>
                    <tr className="f-click" onClick={() => setOpenRow(openRow === row.party ? null : row.party)}>
                      <td style={{ fontWeight: 600 }}>{openRow === row.party ? "▾ " : "▸ "}{row.name}</td>
                      {BUCKETS.map(([k]) => <td key={k} className={"f-num" + (k !== "current" && Number(row[k]) ? " f-bad" : "")}>{amt(row[k])}</td>)}
                      <td className="f-num" style={{ fontWeight: 700 }}>{money(row.total)}</td></tr>
                    {openRow === row.party && row.docs.map((d) => (
                      <tr key={d.id} className="f-click" style={{ fontSize: 12.5 }} onClick={() => go(S.page, String(d.id))}>
                        <td colSpan={5} style={{ paddingLeft: 30, color: "var(--muted)" }}>
                          {d.number} · {d.reference} · {fmtDate(d.date)} · due {fmtDate(d.due_date)}
                          {d.days_late ? ` · ${d.days_late} days late` : ""}{d.currency !== "MVR" ? ` · ${d.currency} ${money(d.balance_fc)}` : ""}</td>
                        <td /><td className="f-num">{money(d.balance)}</td></tr>))}
                  </Fragment>))}
                {r.rows.length === 0 && <tr><td colSpan={7} style={{ color: "var(--muted)" }}>Nothing open at {fmtDate(r.as_of)}.</td></tr>}
                <tr className="f-total"><td>Total</td>{BUCKETS.map(([k]) => <td key={k} className="f-num">{money(r.total[k])}</td>)}
                  <td className="f-num">{money(r.total.total)}</td></tr>
              </tbody>
            </table>
          </div>
          <p style={{ fontSize: 13, marginTop: 10 }} className={agrees ? "f-ok" : "f-bad"}>
            {agrees ? "✓ " : ""}{side === "AP" ? "Accounts payable" : "Accounts receivable"} per the books: MVR {money(r.per_books)}
            {agrees ? ` — agrees with the ${S.docs} above.` : ` — MVR ${money(Math.abs(r.difference))} ${Number(r.difference) > 0 ? "more" : "less"} than the ${S.docs} above.`}
          </p>
          {!agrees && <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 0 }}>
            The difference is whatever sits on the {side === "AP" ? "payable" : "receivable"} accounts without {side === "AP" ? "a bill" : "an invoice"} behind it — usually
            opening balances not yet listed as opening {S.docs}, or a journal posted straight to the account.</p>}
        </>
      )}
    </div>
  );
}
