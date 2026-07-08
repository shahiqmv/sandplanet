import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Chip, Eyebrow, card, ghostButton, td, th } from "./ui.jsx";

// Full site manpower view (R9 "more data" page behind the dashboard
// card): every category roster vs today's attendance, plus the roster
// with each person's status. Names and categories only — never pay.

const STATUS_TONE = { PRESENT: "ok", HALF_DAY: "warn", ABSENT: "alert",
                      SICK: "warn", LEAVE: "info" };

function Bar({ value, max, color }) {
  return (
    <div style={{ background: "var(--row-line)", borderRadius: 4,
                  height: 10, width: "100%" }}>
      <div style={{ width: max ? `${(100 * value) / max}%` : 0,
                    background: color, height: 10, borderRadius: 4 }} />
    </div>
  );
}

export default function ManpowerPage({ site, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api(`/sites/${site.id}/manpower`).then(setData)
      .catch((e) => setError(e.message));
  }, [site.id]);

  if (error) return <section style={card}>{error}</section>;
  if (!data) return <section style={card}>Loading…</section>;

  const maxRoster = Math.max(...data.categories.map((c) => c.roster), 1);

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 17 }}>
          Manpower — {site.code} · {data.date}
        </h2>
        <span style={{ fontSize: 13, color: "var(--muted)" }}>
          {data.roster_total} on roster
          {data.attendance_entered
            ? ` · ${data.present} present · ${data.absent} absent/leave`
            : " · attendance not entered yet today"}
        </span>
        <button onClick={onClose}
                style={{ ...ghostButton, marginLeft: "auto" }}>← Back</button>
      </div>

      <Eyebrow>By category — roster vs present</Eyebrow>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={th}>Category</th>
          <th style={{ ...th, width: "40%" }}>Roster</th>
          <th style={{ ...th, width: 70, textAlign: "right" }}>Roster</th>
          <th style={{ ...th, width: 70, textAlign: "right" }}>Present</th>
          <th style={{ ...th, width: 70, textAlign: "right" }}>Absent</th>
        </tr></thead>
        <tbody>
          {data.categories.map((c) => (
            <tr key={c.id}>
              <td style={td}>{c.name}</td>
              <td style={{ ...td, paddingTop: 12 }}>
                <Bar value={c.roster} max={maxRoster} color="var(--sky)" />
              </td>
              <td style={{ ...td, textAlign: "right",
                           fontFamily: "var(--font-mono)" }}>{c.roster}</td>
              <td style={{ ...td, textAlign: "right",
                           fontFamily: "var(--font-mono)",
                           color: "var(--green-fg)" }}>
                {data.attendance_entered ? c.present : "—"}</td>
              <td style={{ ...td, textAlign: "right",
                           fontFamily: "var(--font-mono)",
                           color: c.absent ? "var(--red-fg)"
                                           : "var(--faint)" }}>
                {data.attendance_entered ? c.absent : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <Eyebrow meta={String(data.employees.length)}>Roster today</Eyebrow>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={th}>Emp No</th><th style={th}>Name</th>
          <th style={th}>Category</th><th style={th}>Today</th>
        </tr></thead>
        <tbody>
          {data.employees.map((e) => (
            <tr key={e.emp_no}>
              <td style={{ ...td, fontFamily: "var(--font-mono)" }}>
                {e.emp_no}</td>
              <td style={td}>{e.full_name}</td>
              <td style={td}>{e.category}</td>
              <td style={td}>
                <Chip tone={STATUS_TONE[e.today] || "info"}>
                  {e.today.replace(/_/g, " ")}</Chip>
              </td>
            </tr>
          ))}
          {data.employees.length === 0 && (
            <tr><td style={td} colSpan={4}>
              No employees allocated to this site — HR allocates them on
              the Employees page.</td></tr>
          )}
        </tbody>
      </table>
    </section>
  );
}
