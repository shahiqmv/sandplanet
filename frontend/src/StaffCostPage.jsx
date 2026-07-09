import { Fragment, useEffect, useState } from "react";
import { api } from "./api.js";
import { card, td, th } from "./ui.jsx";

// Staff cost (§6C.3.5): a live run-rate from the current headcount, and a
// past-months salary summary from the locked Labour & Staff postings.

const money = (v) => v == null ? "—"
  : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2 });
const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug",
                "Sep", "Oct", "Nov", "Dec"];

export default function StaffCostPage() {
  const [rr, setRr] = useState(null);
  const [hist, setHist] = useState([]);
  const [openSite, setOpenSite] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/staff-cost/current").then(setRr).catch((e) => setError(e.message));
    api("/staff-cost/history").then(setHist).catch(() => {});
  }, []);

  if (error) return <section style={card}><p style={{ color:
    "var(--red-fg)" }}>{error}</p></section>;
  if (!rr) return <section style={card}><p>Loading…</p></section>;

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 18 }}>
        Staff cost</h2>

      {/* Current run-rate */}
      <div style={card}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <h3 style={{ margin: 0, fontSize: 14, color: "var(--navy)" }}>
            Current monthly manpower cost</h3>
          <span style={{ fontSize: 12, color: "var(--muted)" }}>
            run-rate from {rr.total_headcount} active
            {" "}worker{rr.total_headcount === 1 ? "" : "s"} · basic pay</span>
          <span style={{ marginLeft: "auto", fontSize: 20,
                         fontFamily: "var(--font-mono)", color: "var(--navy)" }}>
            MVR {money(rr.total_monthly_basic)}</span>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        marginTop: 8 }}>
          <thead><tr>
            <th style={th}>Site</th>
            <th style={{ ...th, textAlign: "right" }}>Headcount</th>
            <th style={{ ...th, textAlign: "right" }}>Monthly basic (MVR)</th>
            <th style={th}></th>
          </tr></thead>
          <tbody>
            {rr.sites.map((s) => (
              <Fragment key={s.site}>
                <tr>
                  <td style={td}><strong>{s.site}</strong>
                    <span style={{ color: "var(--muted)", marginLeft: 6,
                                   fontSize: 12 }}>{s.site_name}</span></td>
                  <td style={{ ...td, textAlign: "right" }}>{s.headcount}</td>
                  <td style={{ ...td, textAlign: "right",
                               fontFamily: "var(--font-mono)" }}>
                    {money(s.monthly_basic)}</td>
                  <td style={td}>
                    <a href="#" style={{ fontSize: 12 }}
                       onClick={(e) => { e.preventDefault();
                         setOpenSite(openSite === s.site ? null : s.site); }}>
                      {openSite === s.site ? "hide" : "by category"}</a>
                  </td>
                </tr>
                {openSite === s.site && s.by_category.map((c) => (
                  <tr key={s.site + c.category}
                      style={{ background: "var(--sand)" }}>
                    <td style={{ ...td, paddingLeft: 24, fontSize: 12 }}>
                      {c.category}</td>
                    <td style={{ ...td, textAlign: "right", fontSize: 12 }}>
                      {c.count}</td>
                    <td style={{ ...td, textAlign: "right", fontSize: 12,
                                 fontFamily: "var(--font-mono)" }}>
                      {money(c.monthly_basic)}</td>
                    <td style={td}></td>
                  </tr>
                ))}
              </Fragment>
            ))}
            {rr.sites.length === 0 && (
              <tr><td style={td} colSpan={4}>
                No active workers allocated.</td></tr>
            )}
          </tbody>
        </table>
        <p style={{ fontSize: 11, color: "var(--muted)", marginTop: 6 }}>
          Basic pay only — overtime is variable and appears in the locked
          monthly cost below. Per-employee pay is never shown.</p>
      </div>

      {/* Past months */}
      <div style={card}>
        <h3 style={{ margin: "0 0 8px", fontSize: 14, color: "var(--navy)" }}>
          Past months — salary summary</h3>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={th}>Period</th><th style={th}>Site</th>
            <th style={{ ...th, textAlign: "right" }}>
              Labour &amp; Staff (MVR)</th>
          </tr></thead>
          <tbody>
            {hist.map((h, i) => (
              <tr key={i}>
                <td style={td}>{MONTHS[h.month]} {h.year}</td>
                <td style={td}>{h.site}</td>
                <td style={{ ...td, textAlign: "right",
                             fontFamily: "var(--font-mono)" }}>
                  {money(h.amount)}</td>
              </tr>
            ))}
            {hist.length === 0 && (
              <tr><td style={td} colSpan={3}>
                No locked months yet — staff cost posts when the site PM
                signs off the month's timesheet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
