import { useEffect, useState } from "react";
import { api } from "./api.js";
import AttendancePage from "./AttendancePage.jsx";
import { Chip, buttonStyle, card, td, th } from "./ui.jsx";

// Head Office is an attendance/payroll home for office staff — NOT a project.
// This page is HR's entry: the HO staff roster + a way to record their
// attendance, without any of the project-site chrome (owner 2026-08-02).
export default function HeadOfficePage({ me, sites }) {
  const ho = (sites || []).find((s) => s.is_head_office);
  const [staff, setStaff] = useState([]);
  // Men on leave sit here until they are back, so the roster would otherwise
  // read as if they were office staff (owner 2026-08-20).
  const [away, setAway] = useState({});
  const [showAtt, setShowAtt] = useState(false);
  const seesPay = ["HO_HR", "FINANCE", "ADMIN", "PA",
                  "SIGNATORY"].includes(me.role);

  useEffect(() => {
    if (ho) api(`/employees?site=${ho.id}`).then(setStaff).catch(() => {});
    api("/leaves?open=1").then((rows) => setAway(Object.fromEntries(
      rows.filter((r) => r.on_leave_today).map((r) => [r.employee_id, r]))))
      .catch(() => {});
  }, [ho?.id]);

  if (!ho) return <div style={card}>
    The Head Office record isn't set up yet — it's created automatically the
    first time it's used elsewhere in the system.</div>;
  if (showAtt) return <AttendancePage site={ho} me={me}
    onClose={() => setShowAtt(false)} />;

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline", flexWrap: "wrap", gap: 10 }}>
        <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Head Office — staff</h2>
        <button onClick={() => setShowAtt(true)} style={buttonStyle}>
          🕐 Record attendance</button>
      </div>
      <p style={{ color: "#5a6b78", fontSize: 12, margin: "0 0 8px" }}>
        Office staff posted to Head Office ({ho.code}). Add staff here via the
        Employees page (post to Head Office), and transfer to/from a site there.
      </p>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={th}>Emp No</th><th style={th}>Name</th>
          <th style={th}>Category</th>
          <th style={th}>Permit</th>
          {seesPay && <th style={{ ...th, textAlign: "right" }}>Basic pay</th>}
        </tr></thead>
        <tbody>
          {staff.map((e) => (
            <tr key={e.id}>
              <td style={td}>{e.emp_no}</td>
              <td style={td}>{e.full_name}{away[e.id] && <>
                {" "}<Chip tone={away[e.id].kind === "PAID" ? "info" : "warn"}>
                  On leave to {away[e.id].to_date}
                  {away[e.id].kind === "PAID" ? "" : " (no pay)"}</Chip></>}
              </td>
              <td style={td}>{e.job_category_name || "—"}</td>
              <td style={td}>{e.permit_state === "EXPIRED"
                ? <span style={{ color: "#c0392b" }}>⚠ Expired</span>
                : (e.work_permit_expiry || "—")}</td>
              {seesPay && <td style={{ ...td, textAlign: "right" }}>
                {e.basic_pay ?? "—"}</td>}
            </tr>
          ))}
          {!staff.length && (
            <tr><td style={td} colSpan={seesPay ? 5 : 4}>
              No Head Office staff yet.</td></tr>)}
        </tbody>
      </table>
    </section>
  );
}
