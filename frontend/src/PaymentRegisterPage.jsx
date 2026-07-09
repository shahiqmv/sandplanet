import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, RefStamp, StatusChip, card, ghostButton, td, th } from "./ui.jsx";

// Full Payment Request register for a site (§5.9). All PYRs, filterable;
// the dashboard card shows only the pending ones and links here.

const money = (v) => v == null ? "—"
  : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2 });
const PENDING = ["DRAFT", "SUBMITTED", "PM_APPROVED", "DIRECTOR_APPROVED",
                 "AUTHORISED"];

export default function PaymentRegisterPage({ site, me, onOpenDoc, onNewPyr,
                                             onClose }) {
  const [pyrs, setPyrs] = useState([]);
  const [tab, setTab] = useState("all");
  const [error, setError] = useState(null);

  useEffect(() => {
    api(`/documents/list?site=${site.id}&doc_type=PYR`).then(setPyrs)
      .catch((e) => setError(e.message));
  }, [site.id]);

  const rows = pyrs.filter((p) =>
    tab === "all" ? true
    : tab === "pending" ? PENDING.includes(p.status)
    : p.status === "PAID");
  const canRaise = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "ADMIN"]
    .includes(me.role);

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 17 }}>
          Payment Register — {site.code}
        </h2>
        {canRaise && onNewPyr && (
          <Btn variant="primary" onClick={onNewPyr}
               style={{ padding: "5px 14px", fontSize: 13 }}>
            + Payment</Btn>
        )}
        <button onClick={onClose}
                style={{ ...ghostButton, marginLeft: "auto" }}>← Back</button>
      </div>

      <div style={{ display: "flex", gap: 6, margin: "14px 0" }}>
        {[["all", "All"], ["pending", "Pending"], ["paid", "Paid"]].map(
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
            <th style={th}>Type</th><th style={th}>Cost head</th>
            <th style={th}>Payee</th>
            <th style={{ ...th, textAlign: "right" }}>Requested</th>
            <th style={{ ...th, textAlign: "right" }}>Paid</th>
            <th style={th}>Payment ref</th><th style={th}>Status</th>
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
                  <td style={{ ...td, fontSize: 12 }}>
                    {(pr.payment_type || "").replace(/_/g, " ").toLowerCase()}
                  </td>
                  <td style={td}>{pr.cost_head}</td>
                  <td style={td}>{pr.payee}</td>
                  <td style={{ ...td, textAlign: "right",
                               fontFamily: "var(--font-mono)" }}>
                    {money(pr.amount_requested)}</td>
                  <td style={{ ...td, textAlign: "right",
                               fontFamily: "var(--font-mono)",
                               color: "var(--muted)" }}>
                    {pr.amount_paid != null ? money(pr.amount_paid) : "—"}</td>
                  <td style={{ ...td, fontFamily: "var(--font-mono)",
                               fontSize: 12 }}>{pr.payment_ref || "—"}</td>
                  <td style={td}>
                    <StatusChip status={p.is_void ? "VOID" : p.status} />
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr><td style={td} colSpan={9}>
                No payment requests{tab !== "all" ? ` (${tab})` : ""} yet.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
