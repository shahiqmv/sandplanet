import { useEffect, useState } from "react";
import { api } from "./api.js";
import { RefStamp, StatusChip, card, ghostButton, td, th } from "./ui.jsx";

// A requester's own payment requests, across sites — so a Head-Office raiser
// (Purchasing, HR, QS…) can follow a PYR after it leaves their queue, instead
// of it vanishing on submit. Read-only; uses documents/list?mine=1.

const money = (v) => v == null ? "—"
  : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2 });
// Still moving through the chain (raised → not yet paid/rejected).
const OPEN = ["DRAFT", "SUBMITTED", "PM_APPROVED", "DIRECTOR_APPROVED",
  "AUTHORISED", "PAYMENT_PROCESSING"];

// A plain-language "where is it now" line for the requester.
const WHERE = {
  DRAFT: "Draft — not submitted yet",
  SUBMITTED: "With the approver",
  PM_APPROVED: "Approved by PM — with the Director",
  DIRECTOR_APPROVED: "Cleared — with Finance for a payment voucher",
  AUTHORISED: "Authorised — awaiting payment",
  PAYMENT_PROCESSING: "Payment in progress",
  PAID: "Paid",
  REJECTED: "Rejected",
};

export default function MyPaymentRequests({ me, onOpenDoc }) {
  const [pyrs, setPyrs] = useState(null);
  const [tab, setTab] = useState("open");
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/documents/list?doc_type=PYR&mine=1").then(setPyrs)
      .catch((e) => setError(e.message));
  }, []);

  const rows = (pyrs || []).filter((p) =>
    tab === "all" ? true
    : tab === "open" ? (OPEN.includes(p.status) && !p.is_void)
    : p.status === "PAID");

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 17 }}>
          My payment requests</h2>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>
          Everything you've raised, and where it is now</span>
      </div>

      <div style={{ display: "flex", gap: 6, margin: "14px 0" }}>
        {[["open", "In progress"], ["paid", "Paid"], ["all", "All"]].map(
          ([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
                  style={{ ...ghostButton, padding: "4px 14px", fontSize: 13,
                           background: tab === key ? "var(--navy)" : "#fff",
                           color: tab === key ? "#fff" : "var(--navy)" }}>
            {label}
          </button>
        ))}
      </div>

      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={th}>Ref</th><th style={th}>Date</th>
            <th style={th}>Site</th><th style={th}>Cost head</th>
            <th style={th}>Payee</th>
            <th style={{ ...th, textAlign: "right" }}>Requested</th>
            <th style={th}>Status</th><th style={th}>Where it is</th>
          </tr></thead>
          <tbody>
            {rows.map((p) => {
              const pr = p.payment_request || {};
              return (
                <tr key={p.ref}>
                  <td style={{ ...td, width: 120 }}>
                    <a href="#" onClick={(e) => { e.preventDefault();
                                                  onOpenDoc(p.ref); }}
                       style={{ textDecoration: "none" }}>
                      <RefStamp small>{p.ref}</RefStamp></a>
                  </td>
                  <td style={td}>{p.doc_date}</td>
                  <td style={td}>{p.site_code}</td>
                  <td style={td}>{pr.cost_head}</td>
                  <td style={td}>{pr.payee}</td>
                  <td style={{ ...td, textAlign: "right",
                               fontFamily: "var(--font-mono)" }}>
                    {money(pr.amount_requested)}</td>
                  <td style={td}>
                    <StatusChip status={p.is_void ? "VOID" : p.status} /></td>
                  <td style={{ ...td, fontSize: 12, color: "var(--muted)" }}>
                    {p.is_void ? "Cancelled"
                      : (WHERE[p.status] || p.status)}</td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr><td style={td} colSpan={8}>
                {pyrs == null ? "Loading…"
                  : `No payment requests${tab !== "all" ? ` (${tab})` : ""}.`}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
