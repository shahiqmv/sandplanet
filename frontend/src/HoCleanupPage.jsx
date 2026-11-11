import { useEffect, useMemo, useState } from "react";
import { api } from "./api.js";
import { Btn, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Head-office payments still booked as cost, each with what it most likely
// is from its own words (owner 2026-11-10). Finance confirms in batches:
// every "Dollar exchange" request becomes a currency exchange in one go, the
// MIRA ones a tax payment. A cheque against a vendor's statement is applied
// to that vendor's payables one request at a time, from the request itself,
// because which invoices it paid is a judgement.

const money = (v) => Number(v || 0).toLocaleString("en-US",
  { minimumFractionDigits: 2 });
const KIND = {
  CURRENCY_EXCHANGE: ["Currency exchange", "Dollars bought or sold. A contra, not a cost."],
  GST_SETTLEMENT: ["GST / tax payments", "GST collected from clients and handed to MIRA."],
  PAYABLES: ["Cheques against orders", "The sites booked these orders as cost when they were signed. Open each and apply it to the vendor's payables."],
  PRIOR_PERIOD: ["Prior-period creditors", "Balances from before the books. The earlier year's accounts, not this year's cost."],
  "": ["Still to look at", "Office rent, visas, tickets, audit fees and the rest: genuine head-office cost, unless one was raised for a site without saying so."],
};
const ORDER = ["CURRENCY_EXCHANGE", "GST_SETTLEMENT", "PAYABLES",
               "PRIOR_PERIOD", ""];
const BOOKINGS = [["CURRENCY_EXCHANGE", "Currency exchange"],
                  ["GST_SETTLEMENT", "GST / tax payment"],
                  ["PRIOR_PERIOD", "Prior-period creditor"]];

export default function HoCleanupPage({ onOpenDoc }) {
  const [rows, setRows] = useState(null);
  const [picked, setPicked] = useState({});
  const [booking, setBooking] = useState("CURRENCY_EXCHANGE");
  const [reason, setReason] = useState("Head-office cost cleanup");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [msg, setMsg] = useState(null);
  const [open, setOpen] = useState({ CURRENCY_EXCHANGE: true, GST_SETTLEMENT: true,
                                     PAYABLES: true, PRIOR_PERIOD: true, "": false });

  const load = () => api("/finance/pyr-backlog").then((d) => setRows(d.rows))
    .catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  const groups = useMemo(() => {
    const g = {};
    (rows || []).forEach((r) => { (g[r.suggestion] ||= []).push(r); });
    return g;
  }, [rows]);
  const chosen = (rows || []).filter((r) => picked[r.ref]);
  const chosenUsd = chosen.reduce((s, r) => s + Number(r.usd), 0);

  function tickGroup(kind, on) {
    const next = { ...picked };
    (groups[kind] || []).forEach((r) => { next[r.ref] = on; });
    setPicked(next);
  }

  async function apply() {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const d = await api("/finance/pyr-backlog", { method: "POST",
        body: { refs: chosen.map((r) => r.ref), booking, reason } });
      const failed = d.results.filter((r) => r.error);
      setMsg(`${d.done} reclassified as ${BOOKINGS.find(([k]) => k === booking)[1].toLowerCase()}`
        + (failed.length ? `; ${failed.length} refused: ${failed.map((f) => `${f.ref} (${f.error})`).join(", ")}` : "."));
      setPicked({});
      load();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  const totalUsd = (rows || []).reduce((s, r) => s + Number(r.usd), 0);
  return (
    <div>
      <div style={card}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Head-office cost cleanup</h2>
        <p style={{ color: "var(--muted)", fontSize: 12.5, margin: "6px 0 0" }}>
          Payments raised at head office and still booked as its cost, sorted
          by what each most likely is from its payee and purpose. Tick what
          is right, choose the kind, and reclassify in one go; the ledger is
          reversed and re-posted on the original dates, with your reason on
          the audit trail. A cheque against a vendor's statement is applied to
          their payables from the request itself.
        </p>
        {rows && (
          <div style={{ marginTop: 10, fontSize: 13 }}>
            <b>{rows.length}</b> requests · USD <b>{money(totalUsd)}</b> still
            booked as head-office cost
          </div>)}
        {err && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{err}</p>}
        {msg && <p style={{ color: "var(--green-fg, #1b6e3a)", fontSize: 13 }}>{msg}</p>}
      </div>

      {chosen.length > 0 && (
        <div style={{ ...card, marginTop: 12, position: "sticky", top: 8,
                      zIndex: 2, display: "flex", gap: 10, alignItems: "end",
                      flexWrap: "wrap" }}>
          <div style={{ fontSize: 13 }}>
            <b>{chosen.length}</b> ticked · USD {money(chosenUsd)}</div>
          <label style={{ fontSize: 13 }}>Become
            <select value={booking} onChange={(e) => setBooking(e.target.value)}
                    style={inputStyle}>
              {BOOKINGS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <label style={{ fontSize: 13, flex: 1, minWidth: 220 }}>Why
            <input value={reason} onChange={(e) => setReason(e.target.value)}
                   style={inputStyle} />
          </label>
          <Btn variant="navy" onClick={apply}
               disabled={busy || !reason.trim()}>Reclassify {chosen.length}</Btn>
          <button style={ghostButton} onClick={() => setPicked({})}>Clear</button>
        </div>)}

      {rows && ORDER.filter((k) => groups[k]?.length).map((kind) => {
        const list = groups[kind];
        const usd = list.reduce((s, r) => s + Number(r.usd), 0);
        const allOn = list.every((r) => picked[r.ref]);
        return (
          <div key={kind || "none"} style={{ ...card, marginTop: 12 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10,
                          flexWrap: "wrap" }}>
              <button onClick={() => setOpen({ ...open, [kind]: !open[kind] })}
                      style={{ ...ghostButton, padding: "2px 8px" }}>
                {open[kind] ? "▾" : "▸"}</button>
              <h3 style={{ margin: 0, fontSize: 15 }}>{KIND[kind][0]}</h3>
              <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
                {list.length} · USD {money(usd)}</span>
              {kind !== "PAYABLES" && (
                <button onClick={() => tickGroup(kind, !allOn)}
                        style={{ ...ghostButton, marginLeft: "auto",
                                 padding: "2px 10px", fontSize: 12.5 }}>
                  {allOn ? "Untick all" : "Tick all"}</button>)}
            </div>
            <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "4px 0 8px" }}>
              {KIND[kind][1]}</p>
            {open[kind] && (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse",
                                fontSize: 12.5 }}>
                  <thead><tr>
                    <th style={th}></th><th style={th}>Ref</th>
                    <th style={th}>Date</th><th style={th}>Payee</th>
                    <th style={th}>Purpose</th><th style={th}>Head</th>
                    <th style={{ ...th, textAlign: "right" }}>Amount</th>
                    <th style={{ ...th, textAlign: "right" }}>USD</th>
                    {kind === "PAYABLES" && <th style={th}>Open payables</th>}
                    <th style={th}></th>
                  </tr></thead>
                  <tbody>
                    {list.map((r) => (
                      <tr key={r.ref}>
                        <td style={td}>
                          <input type="checkbox" checked={!!picked[r.ref]}
                                 onChange={(e) => setPicked({ ...picked,
                                   [r.ref]: e.target.checked })} /></td>
                        <td style={{ ...td, whiteSpace: "nowrap",
                                     fontFamily: "var(--font-mono)" }}>{r.ref}</td>
                        <td style={{ ...td, whiteSpace: "nowrap" }}>{r.date}</td>
                        <td style={td}>{r.payee}</td>
                        <td style={{ ...td, maxWidth: 360 }}>{r.purpose}</td>
                        <td style={td}>{r.cost_head}</td>
                        <td style={{ ...td, textAlign: "right", whiteSpace: "nowrap",
                                     fontFamily: "var(--font-mono)" }}>
                          {r.currency} {money(r.amount)}</td>
                        <td style={{ ...td, textAlign: "right",
                                     fontFamily: "var(--font-mono)" }}>{money(r.usd)}</td>
                        {kind === "PAYABLES" && (
                          <td style={{ ...td, whiteSpace: "nowrap" }}>
                            {r.open_payables
                              ? `${r.open_payables} · ${r.currency} ${money(r.open_payables_total)}`
                              : "none for this vendor"}</td>)}
                        <td style={td}>
                          <button onClick={() => onOpenDoc?.(r.ref)}
                                  style={{ ...ghostButton, padding: "2px 8px",
                                           fontSize: 12 }}>Open</button></td>
                      </tr>))}
                  </tbody>
                </table>
              </div>)}
          </div>);
      })}
      {rows && rows.length === 0 && (
        <div style={{ ...card, marginTop: 12, fontSize: 13 }}>
          Nothing left: every head-office payment is booked as what it is.</div>)}
    </div>
  );
}
