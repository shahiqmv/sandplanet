// Take awarded items back off one vendor of an approved purchase request
// (owner 2026-10-01, PR-259): a fault found in one line of a quotation after
// the award. The ticked items go back to the MR for a new request; what is
// left is re-ordered from the vendor and sent to the signatory.
import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

const money = (v) => Number(v || 0).toLocaleString("en-US",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function AwardWithdrawModal({ prRef, row, onClose, onDone }) {
  const [info, setInfo] = useState(null);
  const [ticked, setTicked] = useState({});
  const [reason, setReason] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api(`/pr/${prRef}/withdraw-award?line_id=${row.id}`)
      .then(setInfo).catch((e) => setError(e.message));
  }, [prRef, row.id]);

  const lines = info?.lines || [];
  const out = lines.filter((l) => ticked[l.id]);
  const outAmt = out.reduce((s, l) => s + Number(l.amount || 0), 0);
  const leftCount = lines.length - out.length;
  const leftAmt = lines.reduce((s, l) => s + Number(l.amount || 0), 0) - outAmt;
  const all = lines.length > 0 && out.length === lines.length;

  async function submit() {
    setError(null);
    if (!out.length) { setError("Tick the items to withdraw."); return; }
    if (!reason.trim()) { setError("Say why they are being withdrawn."); return; }
    setBusy(true);
    try {
      const r = await api(`/pr/${prRef}/withdraw-award`, { method: "POST",
        body: { line_id: row.id, quote_line_ids: out.map((l) => l.id), reason } });
      onDone(r);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <div onClick={onClose}
         style={{ position: "fixed", inset: 0, zIndex: 70, overflow: "auto",
                  background: "rgba(15,32,45,.4)", padding: "5vh 16px" }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ ...card, maxWidth: 780, margin: "0 auto" }}>
        <div style={{ display: "flex", gap: 12, alignItems: "baseline" }}>
          <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 17 }}>
            Withdraw items — {row.vendor}</h2>
          <button onClick={onClose}
                  style={{ ...ghostButton, marginLeft: "auto" }}>Close</button>
        </div>
        <p style={{ fontSize: 13, color: "var(--muted)", margin: "6px 0 12px" }}>
          For a fault found after the award. The items you tick come off this
          vendor and go back to the material request, ready for a new purchase
          request. {info?.credit
            ? "The order for what is left is drawn up again and sent to the signatory."
            : "The cash to be paid to this vendor comes down by the same amount."}
          {" "}The Director is notified.
        </p>
        {!info && !error && <p>Loading…</p>}
        {info?.block && (
          <p style={{ background: "var(--amber-bg, #fff4e0)", borderRadius: 8,
                      padding: "10px 14px", fontSize: 13.5 }}>
            <strong>Not possible yet.</strong> {info.block}</p>
        )}
        {info && !info.block && (
          <>
            <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 13 }}>
              <thead><tr>
                <th style={{ ...th, width: 30 }}>
                  <input type="checkbox" checked={all} aria-label="Tick all"
                         onChange={() => setTicked(all ? {}
                           : Object.fromEntries(lines.map((l) => [l.id, true])))} />
                </th>
                <th style={th}>Item (as quoted)</th>
                <th style={{ ...th, textAlign: "right" }}>Qty</th>
                <th style={{ ...th, textAlign: "right" }}>Rate</th>
                <th style={{ ...th, textAlign: "right" }}>Amount</th>
              </tr></thead>
              <tbody>
                {lines.map((l) => (
                  <tr key={l.id} style={{ cursor: "pointer",
                        background: ticked[l.id] ? "var(--amber-bg, #fff4e0)" : undefined }}
                      onClick={() => setTicked({ ...ticked, [l.id]: !ticked[l.id] })}>
                    <td style={td}>
                      <input type="checkbox" checked={!!ticked[l.id]} readOnly
                             aria-label={`Withdraw ${l.supplier_desc}`} /></td>
                    <td style={{ ...td, textDecoration: ticked[l.id]
                      ? "line-through" : undefined }}>{l.supplier_desc}</td>
                    <td style={{ ...td, textAlign: "right" }}>
                      {Number(l.qty)} {l.unit}</td>
                    <td style={{ ...td, textAlign: "right" }}>{money(l.rate)}</td>
                    <td style={{ ...td, textAlign: "right" }}>{money(l.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ margin: "12px 0", fontSize: 13.5, lineHeight: 1.6 }}>
              <div><strong>Withdrawing:</strong> {out.length} item
                {out.length === 1 ? "" : "s"} · MVR {money(outAmt)}
                {info.gst_applicable ? " + GST" : ""}</div>
              <div><strong>Staying with {row.vendor}:</strong>{" "}
                {leftCount === 0 ? "nothing — no order will be raised"
                  : `${leftCount} item${leftCount === 1 ? "" : "s"} · MVR ${money(leftAmt)}`
                    + (info.gst_applicable ? " + GST" : "")}</div>
            </div>
            <input value={reason} onChange={(e) => setReason(e.target.value)}
                   placeholder="Reason — e.g. GI pipe quoted in the wrong size"
                   style={{ ...inputStyle, width: "100%" }} />
          </>
        )}
        {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
        {info && !info.block && (
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <Btn onClick={submit} disabled={busy || !out.length}>
              {busy ? "Withdrawing…" : `Withdraw ${out.length || ""} item${out.length === 1 ? "" : "s"}`}</Btn>
            <Btn variant="secondary" onClick={onClose}>Cancel</Btn>
          </div>
        )}
      </div>
    </div>
  );
}
