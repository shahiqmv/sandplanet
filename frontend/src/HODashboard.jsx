import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { DOC_LABELS } from "./LineDoc.jsx";
import { Chip, Eyebrow, RefStamp, Stat, StatusChip, buttonStyle, card,
         ghostButton, td, th } from "./ui.jsx";

export default function HODashboard({ me, onOpenDoc, onNew, refresh }) {
  const [stats, setStats] = useState(null);
  const [tab, setTab] = useState("MR");
  const [rows, setRows] = useState([]);
  const [pending, setPending] = useState([]);

  const load = useCallback(() => {
    api("/dashboards/ho").then(setStats).catch(() => setStats(null));
    if (tab === "PENDING") {
      api("/pending-items").then(setPending);
    } else {
      api(`/registers/${tab.toLowerCase()}`).then((d) => setRows(d.rows));
    }
  }, [tab]);

  useEffect(load, [load, refresh]);

  const canPurchase = ["HO_PURCHASING", "ADMIN"].includes(me.role);

  return (
    <>
      <Eyebrow>Purchasing overview</Eyebrow>
      <section style={{ ...card, display: "flex", gap: 18, flexWrap: "wrap" }}>
        <Stat label="MRs awaiting action" value={stats?.mrs_awaiting_action ?? "–"}
              tone={stats?.mrs_awaiting_action ? "warn" : "ok"}
              context={stats?.mrs_awaiting_action
                ? "process before the next loading" : "queue clear"} />
        <Stat label="PRs with Director" value={stats?.prs_awaiting_approval ?? "–"}
              tone={stats?.prs_awaiting_approval ? "warn" : "ok"}
              context={stats?.prs_awaiting_approval
                ? "awaiting award approval" : "none waiting"} />
        <Stat label="PRs awaiting payment" value={stats?.prs_awaiting_payment ?? "–"}
              tone={stats?.prs_awaiting_payment ? "warn" : "ok"}
              context={stats?.prs_awaiting_payment
                ? "Finance to record slips/POs" : "all settled"} />
        <Stat label="Boats in transit" value={stats?.lms_in_transit ?? "–"}
              tone="info"
              context={stats?.lms_in_transit
                ? "manifests at sea — GRN on arrival" : "none at sea"} />
        <Stat label="Pending items" value={stats?.pending_items_open ?? "–"}
              tone={stats?.pending_items_open ? "warn" : "ok"}
              context={stats?.pending_items_open
                ? "plan onto the next manifest" : "log clear"} />
        <Stat label="GRN shortages" value={stats?.grn_shortages ?? "–"}
              tone={stats?.grn_shortages ? "alert" : "ok"}
              context={stats?.grn_shortages
                ? "chase vendors within 24h" : "none open"} />
      </section>

      <Eyebrow>Registers</Eyebrow>
      <section style={card}>
        <div style={{ display: "flex", gap: 8, alignItems: "center",
                      flexWrap: "wrap", marginBottom: 12 }}>
          {["MR", "PR", "PO", "LM", "GRN", "PENDING"].map((key) => (
            <button key={key} onClick={() => setTab(key)}
                    style={tab === key ? buttonStyle
                                       : { ...ghostButton }}>
              {key === "PENDING" ? "Pending Items" : `${key} Register`}
            </button>
          ))}
          <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            {canPurchase && (
              <>
                <button onClick={() => onNew("PR")} style={ghostButton}>
                  + New PR</button>
                <button onClick={() => onNew("LM")} style={ghostButton}>
                  + New LM</button>
              </>
            )}
          </span>
        </div>

        {tab === "PENDING" ? (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>Site</th><th style={th}>Item</th>
              <th style={th}>Qty Pending</th><th style={th}>From LM</th>
              <th style={th}>Reason</th><th style={th}>Status</th>
              <th style={th}>Cleared</th>
            </tr></thead>
            <tbody>
              {pending.map((row) => (
                <tr key={row.id}>
                  <td style={td}>{row.site_code}</td>
                  <td style={td}>{row.description}</td>
                  <td style={td}>{row.qty_pending} {row.unit}</td>
                  <td style={td}>
                    <a href="#" onClick={(e) => { e.preventDefault();
                                                  onOpenDoc(row.lm_ref); }}
                       style={{ textDecoration: "none" }}>
                      <RefStamp small>{row.lm_ref}</RefStamp></a>
                  </td>
                  <td style={td}>{row.reason}</td>
                  <td style={td}>
                    <Chip tone={row.status === "PENDING" ? "warn" : "ok"}>
                      {row.status}</Chip>
                  </td>
                  <td style={td}>
                    {row.cleared_lm_ref || row.cleared_reason || "—"}
                  </td>
                </tr>
              ))}
              {pending.length === 0 && (
                <tr><td style={td} colSpan={7}>No pending items. 🎉</td></tr>
              )}
            </tbody>
          </table>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>Ref</th><th style={th}>Rev</th>
              <th style={th}>Date</th><th style={th}>Site</th>
              <th style={th}>Status</th><th style={th}>Refs</th>
              <th style={th}>Details</th><th style={th}>By</th>
            </tr></thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={`${row.ref}-${row.rev}-${i}`}
                    style={row.is_current_rev ? {} : { opacity: 0.55 }}>
                  <td style={td}>
                    <a href="#" onClick={(e) => { e.preventDefault();
                                                  onOpenDoc(row.ref); }}
                       style={{ textDecoration: "none" }}>
                      <RefStamp small>{row.ref}</RefStamp>
                    </a>
                  </td>
                  <td style={{ ...td, fontFamily: "var(--font-mono)",
                               color: "var(--faint)", fontSize: 12 }}>
                    {row.rev}</td>
                  <td style={td}>{row.date}</td>
                  <td style={td}>{row.site_code}</td>
                  <td style={td}><StatusChip status={row.status} /></td>
                  <td style={{ ...td, fontSize: 12 }}>
                    {Object.values(row.links).flat().join(" · ")}
                  </td>
                  <td style={{ ...td, fontSize: 12 }}>
                    {Object.entries(row.payload_summary)
                      .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`)
                      .join(" · ")}
                  </td>
                  <td style={td}>{row.created_by}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td style={td} colSpan={8}>
                  No {DOC_LABELS[tab]}s yet.</td></tr>
              )}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
