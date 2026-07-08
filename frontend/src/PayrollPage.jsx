import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, card, inputStyle, td, th } from "./ui.jsx";

export default function PayrollPage({ sites }) {
  const [period, setPeriod] = useState(() =>
    new Date().toISOString().slice(0, 7));
  const [siteId, setSiteId] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const [year, month] = period.split("-");

  const load = useCallback(() => {
    setError(null);
    api(`/payroll-export/${year}/${+month}${siteId ? `?site=${siteId}` : ""}`)
      .then(setData).catch((e) => setError(e.message));
  }, [year, month, siteId]);

  useEffect(load, [load]);

  const exportUrl = `/api/v1/payroll-export/${year}/${+month}?export=xlsx` +
    (siteId ? `&site=${siteId}` : "");
  const fmt = (v) => Number(v).toLocaleString(undefined,
    { maximumFractionDigits: 2 });
  const totalGross = (data?.rows || []).reduce((a, r) => a + +r.gross, 0);

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline", flexWrap: "wrap", gap: 10 }}>
        <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Payroll — {period}
        </h2>
        <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input type="month" value={period}
                 onChange={(e) => setPeriod(e.target.value)}
                 style={{ ...inputStyle, width: 150 }} />
          <select value={siteId} onChange={(e) => setSiteId(e.target.value)}
                  style={{ ...inputStyle, width: 170 }}>
            <option value="">All sites (consolidated)</option>
            {sites.filter((s) => !s.is_head_office).map((s) => (
              <option key={s.id} value={s.id}>{s.code} — {s.name}</option>
            ))}
          </select>
          <a href={exportUrl}
             style={{ ...buttonStyle, textDecoration: "none" }}>
            ⬇ Download Excel
          </a>
        </span>
      </div>
      {data && (
        <p style={{ fontSize: 12, color: "#5a6b78" }}>
          OT multiplier ×{data.ot_multiplier} · hourly rate = basic ÷{" "}
          {data.hourly_rate_divisor} (company parameters)
        </p>
      )}
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={th}>Emp No</th><th style={th}>Name</th>
          <th style={th}>Site(s)</th>
          <th style={{ ...th, textAlign: "right" }}>Days</th>
          <th style={{ ...th, textAlign: "right" }}>Absences</th>
          <th style={{ ...th, textAlign: "right" }}>Hours</th>
          <th style={{ ...th, textAlign: "right" }}>OT (appr.)</th>
          <th style={{ ...th, textAlign: "right" }}>Basic</th>
          <th style={{ ...th, textAlign: "right" }}>OT Amount</th>
          <th style={{ ...th, textAlign: "right" }}>Gross</th>
        </tr></thead>
        <tbody>
          {(data?.rows || []).map((row) => (
            <tr key={row.emp_no}>
              <td style={{ ...td, fontWeight: 600,
                           color: "var(--sp-navy)" }}>{row.emp_no}</td>
              <td style={td}>{row.full_name}</td>
              <td style={td}>{row.sites}</td>
              <td style={{ ...td, textAlign: "right" }}>{row.days_worked}</td>
              <td style={{ ...td, textAlign: "right" }}>{row.absences}</td>
              <td style={{ ...td, textAlign: "right" }}>
                {fmt(row.normal_hours)}</td>
              <td style={{ ...td, textAlign: "right" }}>
                {fmt(row.ot_hours_approved)}</td>
              <td style={{ ...td, textAlign: "right" }}>
                {fmt(row.basic_pay)}</td>
              <td style={{ ...td, textAlign: "right" }}>
                {fmt(row.ot_amount)}</td>
              <td style={{ ...td, textAlign: "right", fontWeight: 700 }}>
                {fmt(row.gross)}</td>
            </tr>
          ))}
          {data?.rows?.length > 0 && (
            <tr style={{ fontWeight: 700 }}>
              <td style={td} colSpan={9}>Total gross</td>
              <td style={{ ...td, textAlign: "right" }}>
                MVR {fmt(totalGross)}</td>
            </tr>
          )}
          {data && data.rows.length === 0 && (
            <tr><td style={td} colSpan={10}>
              No attendance recorded for this period.</td></tr>
          )}
        </tbody>
      </table>
    </section>
  );
}
