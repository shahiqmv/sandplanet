// What the transaction forms share — expense, deposit, bill, invoice: the
// accounts and names to pick from, the lines with their GST, and voiding.
import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { Btn, card, ghostButton, inputStyle } from "../ui.jsx";
import { money, tree } from "./shared.jsx";

export const num = (v) => Number(String(v ?? "").replace(/,/g, "")) || 0;
export const r2 = (v) => Math.round(v * 100) / 100;
export const MONEY = ["BANK", "CREDIT_CARD"];
export const blank = () => ({ account: "", text: "", description: "", amount: "", gst_treatment: "NONE", gst: "", site: "" });
export const field = { display: "flex", flexDirection: "column", gap: 4, fontSize: 13 };
export const lab = (t) => <span style={{ fontWeight: 600, opacity: .8 }}>{t}</span>;

export function useBooks() {
  const [accounts, setAccounts] = useState([]);
  const [meta, setMeta] = useState(null);
  const [sites, setSites] = useState([]);
  const [fx, setFx] = useState("");
  useEffect(() => {
    api("/ledger/accounts").then((d) => setAccounts(tree(d.accounts).filter((a) => !a.is_group && a.is_active)));
    api("/ledger/meta").then(setMeta).catch(() => {});
    api("/sites").then((s) => setSites(Array.isArray(s) ? s : s.results || [])).catch(() => {});
    api("/fx/usd-rate").then((r) => setFx(String(r.rate))).catch(() => {});
  }, []);
  // what a line can be posted to: not a bank (that is a transfer), not a
  // foreign-currency account
  const pick = useMemo(() => accounts.filter((a) => !MONEY.includes(a.type) && !a.currency), [accounts]);
  const byLabel = useMemo(() => Object.fromEntries(pick.map((a) => [`${a.code} ${a.name}`, a])), [pick]);
  return { accounts, meta, sites, fx, pick, byLabel, banks: accounts.filter((a) => MONEY.includes(a.type)) };
}

// What each line comes to: the amount before GST and the GST. Typed
// inclusive, the GST is taken out of the figure; exclusive, it is added, and
// can be corrected to the invoice's own figure.
export function lineSums(lines, rate, inclusive) {
  const sums = lines.map((l) => {
    const v = num(l.amount);
    if (l.gst_treatment !== "STANDARD") return { net: v, gst: 0 };
    if (inclusive) { const net = r2(v / (1 + rate / 100)); return { net, gst: r2(v - net) }; }
    return { net: v, gst: l.gst !== "" ? num(l.gst) : r2(v * rate / 100) };
  });
  const net = r2(sums.reduce((s, x) => s + x.net, 0));
  const gst = r2(sums.reduce((s, x) => s + x.gst, 0));
  return { sums, net, gst, total: r2(net + gst) };
}

export const linesPayload = (lines, sums) => lines.map((l, i) => ({
  account: l.account || null, description: l.description, amount: sums[i].net, gst_treatment: l.gst_treatment,
  gst_amount: l.gst_treatment === "STANDARD" ? sums[i].gst : 0, site: l.site ? Number(l.site) : null,
})).filter((l) => l.account || l.amount);

export const linesFromTxn = (t) => t.lines.map((l) => ({
  account: l.account, text: `${l.account_code} ${l.account_name}`, description: l.description, amount: String(l.amount),
  gst_treatment: l.gst_treatment, gst: Number(l.gst_amount) ? String(l.gst_amount) : "", site: l.site || "" }));

// The lines of a form. `heading` names the first column ("What for", "From",
// "Income account"); `word` is what the total is ("paid", "billed").
export function LinesTable({ books, lines, setLines, inclusive, setInclusive, ccy, heading, word, mvrRate, readOnly }) {
  const { pick, byLabel, meta, sites } = books;
  const rate = num(meta?.gst_rate);
  const { sums, net, gst, total } = lineSums(lines, rate, inclusive);
  const setLine = (i, patch) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  return (
    <div style={{ ...card, padding: 10, overflowX: "auto" }}>
      <div className="f-bar" style={{ margin: "2px 6px 8px", fontSize: 13 }}>
        <span>Amounts in <b>{ccy}</b> are</span>
        <label><input type="radio" disabled={readOnly} checked={!inclusive} onChange={() => setInclusive(false)} /> before GST</label>
        <label><input type="radio" disabled={readOnly} checked={inclusive} onChange={() => setInclusive(true)} /> including GST</label>
        <span style={{ color: "var(--muted)" }}>GST rate {rate}%</span>
      </div>
      <datalist id="f-lineacc">{pick.map((a) => <option key={a.id} value={`${a.code} ${a.name}`} />)}</datalist>
      <table className="f-table f-lines" style={{ minWidth: 940 }}>
        <thead><tr>
          <th style={{ width: "26%" }}>{heading}</th><th>Description</th>
          <th style={{ width: 130, textAlign: "right" }}>Amount</th><th style={{ width: 150 }}>GST</th>
          <th style={{ width: 110, textAlign: "right" }}>GST amount</th><th style={{ width: 100 }}>Site</th><th style={{ width: 26 }} />
        </tr></thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={i}>
              <td><input list="f-lineacc" value={l.text} placeholder="Code or name…" disabled={readOnly}
                         style={l.text && !l.account ? { borderColor: "var(--red-fg, #b3261e)" } : undefined}
                         onChange={(e) => setLine(i, { text: e.target.value, account: byLabel[e.target.value]?.id || "" })} /></td>
              <td><input value={l.description} disabled={readOnly} onChange={(e) => setLine(i, { description: e.target.value })} /></td>
              <td><input className="f-amt" value={l.amount} disabled={readOnly} onChange={(e) => setLine(i, { amount: e.target.value, gst: "" })} /></td>
              <td><select value={l.gst_treatment} disabled={readOnly} onChange={(e) => setLine(i, { gst_treatment: e.target.value, gst: "" })}>
                {(meta?.gst_treatments || []).map((g) => <option key={g.value} value={g.value}>{g.value === "STANDARD" ? `${g.label} ${rate}%` : g.label}</option>)}
              </select></td>
              <td>{l.gst_treatment === "STANDARD"
                ? <input className="f-amt" disabled={inclusive || readOnly} value={inclusive || l.gst === "" ? (sums[i].gst ? sums[i].gst.toFixed(2) : "") : l.gst}
                         onChange={(e) => setLine(i, { gst: e.target.value })} />
                : null}</td>
              <td><select value={l.site} disabled={readOnly} onChange={(e) => setLine(i, { site: e.target.value })}>
                <option value="">—</option>{sites.map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}</select></td>
              <td>{!readOnly && <button className="f-link" style={{ textDecoration: "none", color: "var(--muted)" }} title="Remove line"
                          onClick={() => setLines((ls) => (ls.length > 1 ? ls.filter((_, j) => j !== i) : ls))}>✕</button>}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr><td colSpan={2} style={{ paddingTop: 10 }}>
            {!readOnly && <button style={{ ...ghostButton, padding: "4px 12px", fontSize: 13 }} onClick={() => setLines((ls) => [...ls, blank()])}>+ Add line</button>}</td>
            <td className="f-num" style={{ paddingTop: 10 }}>{money(net)}</td><td style={{ paddingTop: 10 }}>before GST</td><td colSpan={3} /></tr>
          <tr><td colSpan={2} /><td className="f-num">{money(gst)}</td><td>GST</td><td colSpan={3} /></tr>
          <tr><td colSpan={2} /><td className="f-num" style={{ fontWeight: 800, fontSize: 15 }}>{ccy} {money(total)}</td>
            <td style={{ fontWeight: 700 }}>{word}
              {mvrRate ? <span style={{ fontWeight: 400, color: "var(--muted)" }}> = MVR {money(total * mvrRate)}</span> : null}</td>
            <td colSpan={3} /></tr>
        </tfoot>
      </table>
    </div>
  );
}

// "Void…" → a reason → "Void it". A void reverses the entry; nothing is deleted.
export function VoidBar({ txnId, onDone, onError }) {
  const [reason, setReason] = useState(null);
  async function doVoid() {
    if (!reason.trim()) { onError("Say why it is being voided."); return; }
    try { await api(`/ledger/txns/${txnId}/void`, { method: "POST", body: { reason } }); onDone(); }
    catch (e) { onError(e.message); }
  }
  if (reason === null) return <Btn variant="secondary" onClick={() => setReason("")}>Void…</Btn>;
  return (
    <>
      <input style={{ ...inputStyle, width: 280 }} placeholder="Why is it being voided?" value={reason}
             onChange={(e) => setReason(e.target.value)} />
      <Btn variant="secondary" onClick={doVoid}>Void it</Btn>
      <button className="f-link" onClick={() => setReason(null)}>cancel</button>
    </>
  );
}
