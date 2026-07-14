import { useEffect, useState } from "react";
import { api } from "./api.js";
import { StatusChip, card, ghostButton, td, th } from "./ui.jsx";

// Register of Project Material Requisitions for HO / Purchasing / Director to
// track — especially those sized-and-released but not yet ordered (owner).

const FILTERS = [["pending_order", "Pending order"], ["open", "In flight"],
                 ["", "All"]];

export default function PmrRegister({ onOpenDoc }) {
  const [flt, setFlt] = useState("pending_order");
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setRows(null);
    setError(null);
    api(`/pmr/register${flt ? `?filter=${flt}` : ""}`)
      .then(setRows).catch((e) => setError(e.message));
  }, [flt]);

  const pendingCount = (rows || []).filter((r) => r.pending_order).length;

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 18 }}>
          🌍 Import requests (PMR) register</h2>
        <p style={{ color: "var(--muted)", fontSize: 12.5, margin: "4px 0 0" }}>
          Project material requisitions in flight. <strong>Pending order</strong>{" "}
          are sized &amp; released — Purchasing must raise the overseas order.</p>
      </div>

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {FILTERS.map(([key, label]) => (
          <button key={key} onClick={() => setFlt(key)}
                  style={{ ...ghostButton, padding: "4px 14px", fontSize: 13,
                           background: flt === key ? "var(--sp-navy)" : "#fff",
                           color: flt === key ? "#fff" : "var(--sp-navy)",
                           borderColor: flt === key ? "var(--sp-navy)"
                             : "var(--sp-border)" }}>
            {label}</button>
        ))}
        {flt !== "pending_order" && pendingCount > 0 && (
          <span style={{ alignSelf: "center", fontSize: 12.5, color: "#b35900",
                         fontWeight: 600 }}>
            {pendingCount} pending order</span>
        )}
      </div>

      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <section style={card}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
            <thead><tr>
              <th style={th}>PMR</th><th style={th}>Project · Site</th>
              <th style={th}>Discipline</th><th style={th}>Items</th>
              <th style={th}>Status</th><th style={th}>Next step</th>
              <th style={{ ...th, textAlign: "right" }}>Age</th>
            </tr></thead>
            <tbody>
              {(rows || []).map((r) => (
                <tr key={r.ref} style={{ background: r.pending_order
                  ? "#fff8ef" : "transparent" }}>
                  <td style={td}>
                    <a href="#" onClick={(e) => { e.preventDefault();
                                                  onOpenDoc(r.ref); }}
                       style={{ color: "var(--sp-navy)", fontWeight: 600 }}>
                      {r.ref}</a>
                    {r.ipr_ref && (
                      <div style={{ fontSize: 11, color: "#8a97a1" }}>
                        → {r.ipr_ref}</div>
                    )}
                  </td>
                  <td style={td}>{r.project || "—"} · {r.site}</td>
                  <td style={td}>{r.discipline || "—"}</td>
                  <td style={td}>
                    {r.items.slice(0, 2).map((it, i) => (
                      <div key={i} style={{ fontSize: 12 }}>
                        {it.description} — {Number(it.qty)} {it.unit}</div>
                    ))}
                    {r.lines_count > 2 && (
                      <div style={{ fontSize: 11, color: "#8a97a1" }}>
                        +{r.lines_count - 2} more</div>
                    )}
                  </td>
                  <td style={td}><StatusChip status={r.status} /></td>
                  <td style={{ ...td, color: r.pending_order
                    ? "#b35900" : "var(--muted)", fontWeight: r.pending_order
                    ? 600 : 400 }}>{r.next_action}</td>
                  <td style={{ ...td, textAlign: "right",
                               color: r.days_open > 7 ? "#c0392b" : "inherit" }}>
                    {r.days_open != null ? `${r.days_open}d` : "—"}</td>
                </tr>
              ))}
              {rows && rows.length === 0 && (
                <tr><td colSpan={7} style={{ ...td, textAlign: "center",
                  color: "var(--muted)" }}>
                  {flt === "pending_order"
                    ? "No requisitions waiting to be ordered."
                    : "No import requests."}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
