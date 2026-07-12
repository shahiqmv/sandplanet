import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Chip, Eyebrow, RefStamp, Stat, StatusChip, card, td, th }
  from "./ui.jsx";

// Senior-management portfolio (spec §7.4): every project — value, PM,
// % time elapsed vs programme progress, open items, health status.

const HEALTH = {
  on_track: ["ok", "On track"],
  watch: ["warn", "Watch"],
  attention: ["alert", "Attention"],
  info: ["info", "—"],
};

const money = (v) => v == null ? "—"
  : Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });

export default function PortfolioPage({ refresh, onOpenProject }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/dashboards/portfolio").then(setData)
      .catch((e) => setError(e.message));
  }, [refresh]);

  if (error) return <section style={card}>{error}</section>;
  if (!data) return <section style={card}>Loading…</section>;

  const attention = data.projects.filter(
    (p) => p.health === "attention").length;

  return (
    <>
      <Eyebrow>Portfolio</Eyebrow>
      <section style={{ ...card, display: "flex", gap: 18,
                        flexWrap: "wrap" }}>
        <Stat label="Active projects" value={data.counts.ACTIVE || 0}
              tone="info" context="across all sites" />
        <Stat label="On hold" value={data.counts.ON_HOLD || 0}
              tone={data.counts.ON_HOLD ? "warn" : "ok"}
              context={data.counts.ON_HOLD ? "suspended works" : "none"} />
        <Stat label="Needing attention" value={attention}
              tone={attention ? "alert" : "ok"}
              context={attention ? "progress well behind programme"
                                 : "no project flagged"} />
      </section>

      <section style={card}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>Project</th><th style={th}>Site</th>
              <th style={th}>PM</th>
              <th style={{ ...th, textAlign: "right" }}>Value (USD)</th>
              <th style={th}>Finish</th>
              <th style={{ ...th, textAlign: "right" }}>Time</th>
              <th style={{ ...th, textAlign: "right" }}>Progress</th>
              <th style={{ ...th, textAlign: "right" }}>Open</th>
              <th style={th}>Health</th>
            </tr></thead>
            <tbody>
              {data.projects.map((p) => {
                const [tone, label] = HEALTH[p.health] || HEALTH.info;
                return (
                  <tr key={p.project_id}
                      style={p.status === "CLOSED" ? { opacity: 0.55 } : {}}>
                    <td style={td}>
                      <a href="#" onClick={(e) => { e.preventDefault();
                                    onOpenProject?.(p.project_id); }}
                         style={{ textDecoration: "none" }}>
                        <RefStamp small>{p.code}</RefStamp>
                      </a>
                      <div style={{ fontSize: 11.5, color: "var(--faint)",
                                    marginTop: 2 }}>{p.title}</div>
                    </td>
                    <td style={td}>{p.site_code}</td>
                    <td style={td}>{p.pm_name || "—"}</td>
                    <td style={{ ...td, textAlign: "right",
                                 fontFamily: "var(--font-mono)" }}>
                      {money(p.contract_value)}</td>
                    <td style={td}>{p.planned_completion || "—"}</td>
                    <td style={{ ...td, textAlign: "right",
                                 fontFamily: "var(--font-mono)" }}>
                      {p.pct_time_elapsed == null ? "—"
                        : `${p.pct_time_elapsed}%`}</td>
                    <td style={{ ...td, textAlign: "right",
                                 fontFamily: "var(--font-mono)" }}>
                      {p.overall_progress}%</td>
                    <td style={{ ...td, textAlign: "right",
                                 fontFamily: "var(--font-mono)" }}>
                      {p.open_items}</td>
                    <td style={td}>
                      {p.status === "ACTIVE"
                        ? <Chip tone={tone}>{label}</Chip>
                        : <StatusChip status={p.status} />}
                    </td>
                  </tr>
                );
              })}
              {data.projects.length === 0 && (
                <tr><td style={td} colSpan={9}>
                  No projects yet — add them under Site Setup.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
