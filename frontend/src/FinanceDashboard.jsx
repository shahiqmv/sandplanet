import { useEffect, useState } from "react";
import { api } from "./api.js";
import { RefStamp, card } from "./ui.jsx";

// Finance operational dashboard (M6f): money in motion — what needs a
// voucher, vouchers in flight, what is waiting to be paid, outstanding
// payables, and petty-cash floats below their trigger.

const money = (v) => v == null ? "—"
  : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2 });

function Tile({ label, value, sub, tone, onClick }) {
  return (
    <div onClick={onClick}
         style={{ ...card, margin: 0, padding: "14px 16px", minWidth: 180,
                  cursor: onClick ? "pointer" : "default",
                  borderTop: `3px solid ${tone || "var(--navy)"}` }}>
      <div style={{ fontSize: 12, color: "var(--muted)" }}>{label}</div>
      <div style={{ fontSize: 22, fontFamily: "var(--font-mono)",
                    color: "var(--navy)" }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: "var(--muted)",
                            marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

export default function FinanceDashboard({ me, onVouchers, onNewPayment }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/finance/dashboard").then(setD).catch((e) => setError(e.message));
  }, []);

  if (error) return <section style={card}><p style={{ color:
    "var(--red-fg)" }}>{error}</p></section>;
  if (!d) return <section style={card}><p>Loading…</p></section>;

  const lowFloats = d.petty_cash.filter((f) => f.below_trigger);

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12,
                    flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 18 }}>
          Finance — money in motion</h2>
        {onNewPayment && (
          <button onClick={onNewPayment}
                  style={{ marginLeft: "auto", background: "var(--navy)",
                           color: "#fff", border: "none", borderRadius: 8,
                           padding: "8px 14px", fontSize: 13, fontWeight: 600,
                           cursor: "pointer" }}>
            ＋ Raise a payment (MVR / USD)</button>
        )}
      </div>
      <p style={{ margin: "-6px 0 0", fontSize: 12.5, color: "var(--muted)" }}>
        Accounts-initiated payments (rent, salaries, utilities) go straight to
        a Payment Voucher for the signatory — no Director step.</p>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <Tile label="Awaiting a voucher"
              value={d.awaiting_voucher.count}
              sub={`MVR ${money(d.awaiting_voucher.total)} to batch`}
              tone="var(--sky)" onClick={onVouchers} />
        <Tile label="Vouchers with the signatory"
              value={d.vouchers.submitted}
              sub={`${d.vouchers.draft} draft in preparation`}
              onClick={onVouchers} />
        <Tile label="Vouchers to pay"
              value={d.vouchers.to_pay.length}
              sub="approved, lines still unpaid"
              tone={d.vouchers.to_pay.length ? "var(--red-fg)" : undefined}
              onClick={onVouchers} />
        <Tile label="Payment requests to pay"
              value={d.pyr_to_pay.count}
              sub={`MVR ${money(d.pyr_to_pay.total)}`} />
        <Tile label="Outstanding payables"
              value={d.payables.count}
              sub={`MVR ${money(d.payables.total)} on credit terms`}
              onClick={onVouchers} />
      </div>
      {d.payables.count > 0 && (
        <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "0 0 8px" }}>
          Credit payables appear in the voucher builder — raise a Payment
          Voucher for them when due, or early if a vendor withdraws credit.</p>
      )}

      {d.vouchers.to_pay.length > 0 && (
        <div style={card}>
          <h3 style={{ margin: "0 0 8px", fontSize: 14,
                       color: "var(--navy)" }}>Approved vouchers to settle</h3>
          {d.vouchers.to_pay.map((v) => (
            <div key={v.ref} style={{ display: "flex", gap: 12,
                                      alignItems: "center", padding: "4px 0" }}>
              <a href="#" onClick={(e) => { e.preventDefault(); onVouchers(); }}
                 style={{ textDecoration: "none" }}>
                <RefStamp small>{v.ref}</RefStamp></a>
              <span style={{ fontSize: 13, color: "var(--muted)" }}>
                {v.paid}/{v.lines} lines paid</span>
              <span style={{ marginLeft: "auto",
                             fontFamily: "var(--font-mono)", fontSize: 14 }}>
                MVR {money(v.total)}</span>
            </div>
          ))}
        </div>
      )}

      <div style={card}>
        <h3 style={{ margin: "0 0 8px", fontSize: 14, color: "var(--navy)" }}>
          Petty cash floats</h3>
        {d.petty_cash.length === 0 && (
          <p style={{ fontSize: 13, color: "var(--muted)" }}>
            No floats set up yet.</p>
        )}
        {d.petty_cash.map((f) => (
          <div key={f.site} style={{ display: "flex", gap: 12,
                                     alignItems: "center", padding: "4px 0" }}>
            <strong style={{ width: 60 }}>{f.site}</strong>
            <span style={{ fontSize: 13, color: "var(--muted)" }}>
              {f.custodian}</span>
            <span style={{ marginLeft: "auto",
                           fontFamily: "var(--font-mono)", fontSize: 14,
                           color: f.below_trigger ? "var(--red-fg)"
                             : "var(--navy)" }}>
              MVR {money(f.cash_in_hand)} / {money(f.imprest)}</span>
            {f.below_trigger && (
              <span style={{ background: "var(--red-bg)",
                             color: "var(--red-fg)", padding: "2px 8px",
                             borderRadius: 6, fontSize: 11 }}>low</span>
            )}
          </div>
        ))}
        {lowFloats.length > 0 && (
          <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
            {lowFloats.length} float{lowFloats.length === 1 ? "" : "s"} below
            trigger — a replenishment PYR will come through the normal chain.
          </p>
        )}
      </div>
    </section>
  );
}
