import { useEffect, useState } from "react";
import { api } from "./api.js";
import { ghostButton, inputStyle, td, th } from "./ui.jsx";

// The month's overtime on one page: every man with OT, every day, what was
// requested and what the PM decided. Approving stays on the day's table, where
// each man's hours sit beside their cost, so a day here opens that table
// (owner 2026-11-01).
const hrs = (v) => Number(v || 0).toLocaleString("en-US",
  { maximumFractionDigits: 2 });

const num = { ...td, textAlign: "right", whiteSpace: "nowrap" };
const dcell = { ...td, textAlign: "center", padding: "3px 4px", minWidth: 26,
                fontSize: 11 };

function cellLook(c) {
  if (c.flat) return { color: "#8796a3", label: c.a ?? c.r,
    title: "Friday — the flat Friday pay covers this day; these hours aren't paid" };
  if (c.a === null) return { color: "#b35900", label: `${c.r}?`,
    outline: "inset 0 0 0 1.5px #d98e04",
    title: `${c.r} h requested — waiting for approval` };
  if (Number(c.a) === 0) return { color: "#a3271b", label: "0",
    title: `Refused — ${c.r} h requested${c.by ? `, by ${c.by}` : ""}` };
  return { color: "#1a7f37", label: c.a,
    title: `Approved ${c.a} h${c.a !== c.r ? ` of ${c.r} requested` : ""}`
      + `${c.by ? ` by ${c.by}` : ""}` };
}

export default function OtRegister({ site, day, narrow, onOpenDay }) {
  const [month, setMonth] = useState(day.slice(0, 7));
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [waitingOnly, setWaitingOnly] = useState(false);

  useEffect(() => {
    const [y, m] = month.split("-");
    if (!y || !m) return;
    setData(null); setError(null);
    api(`/attendance/ot-register?site=${site.id}&year=${y}&month=${Number(m)}`)
      .then(setData).catch((e) => setError(e.message));
  }, [site.id, month]);

  const rows = (data?.rows || []).filter((r) => narrow.showRow(r)
    && (!waitingOnly || Number(r.waiting) > 0));
  const payroll = rows.filter((r) => !r.is_subcontract);
  const gang = rows.filter((r) => r.is_subcontract);
  const total = (list, k) => list.reduce((t, r) => t + Number(r[k] || 0), 0);
  const dayTotal = (d) => {
    let open = 0, sum = 0;
    payroll.forEach((r) => {
      const c = r.days[String(d)];
      if (!c || c.flat) return;
      if (c.a === null) open += Number(c.r); else sum += Number(c.a);
    });
    return { open, sum };
  };
  const dateOf = (d) => `${month}-${String(d).padStart(2, "0")}`;

  return (
    <section style={{ marginTop: 10 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center",
                    flexWrap: "wrap", marginBottom: 8 }}>
        <input type="month" value={month} aria-label="Month"
               onChange={(e) => setMonth(e.target.value)}
               style={{ ...inputStyle, width: 160, padding: "4px 8px",
                        fontSize: 13 }} />
        <input value={narrow.q} onChange={(e) => narrow.setQ(e.target.value)}
               placeholder="Find a man — no. or name"
               style={{ ...inputStyle, width: 190, padding: "4px 10px",
                        fontSize: 13 }} />
        <label style={{ fontSize: 12.5, color: "#5a6b78" }}>
          <input type="checkbox" checked={waitingOnly}
                 onChange={(e) => setWaitingOnly(e.target.checked)} />{" "}
          Waiting for approval only</label>
        {narrow.subFilter && (
          <span style={{ fontSize: 12.5, display: "inline-flex", gap: 6,
                         alignItems: "center", padding: "2px 8px",
                         borderRadius: 12, background: "#eef5fb",
                         color: "var(--sp-navy)" }}>
            {narrow.subFilter.name}'s men only
            <button onClick={() => narrow.setSubFilter(null)}
                    style={{ ...ghostButton, padding: "0 6px", fontSize: 11 }}>
              whole site</button>
          </span>)}
        {data?.locked && (
          <span style={{ fontSize: 12.5, color: "#1a7f37" }}>
            🔒 month signed off</span>)}
      </div>
      {error && <p style={{ color: "#a3271b", fontSize: 13 }}>{error}</p>}
      {!data && !error && <p style={{ fontSize: 13 }}>Loading…</p>}
      {data && (
        <>
          <p style={{ fontSize: 13, margin: "0 0 4px", color: "#5a6b78" }}>
            Requested <b>{hrs(total(payroll, "requested"))} h</b> · approved{" "}
            <b style={{ color: "#1a7f37" }}>
              {hrs(total(payroll, "approved"))} h</b> · waiting{" "}
            <b style={{ color: "#b35900" }}>
              {hrs(total(payroll, "waiting"))} h</b>
            {gang.length > 0 && (
              <> · gang extra hours {hrs(total(gang, "approved"))} h approved,
                {" "}{hrs(total(gang, "waiting"))} h waiting — not payroll</>)}
          </p>
          <p style={{ fontSize: 12, margin: "0 0 8px", color: "#5a6b78" }}>
            <span style={{ color: "#1a7f37", fontWeight: 700 }}>3</span> approved
            {" · "}<span style={{ color: "#b35900", fontWeight: 700 }}>3?</span>
            {" "}waiting · <span style={{ color: "#a3271b", fontWeight: 700 }}>0
            </span> refused · <span style={{ color: "#8796a3", fontWeight: 700 }}>
            3</span> on a Friday, covered by the flat pay. Hover a day to see who
            approved it{onOpenDay ? "; click it to open that day's approval" : ""}.
          </p>
          {rows.length === 0 ? (
            <p style={{ fontSize: 13, color: "#5a6b78" }}>
              {waitingOnly ? "No overtime is waiting for approval this month."
                : "No overtime recorded this month."}</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ borderCollapse: "collapse", fontSize: 11 }}>
                <thead><tr>
                  <th style={{ ...th, position: "sticky", left: 0,
                               background: "#fff" }}>Employee</th>
                  {data.days.map((d) => (
                    <th key={d.day} title={d.dow}
                        onClick={onOpenDay
                          ? () => onOpenDay(dateOf(d.day)) : undefined}
                        style={{ ...dcell, fontWeight: 600,
                          background: d.rest ? "#eef4fb" : "#f6f8fa",
                          cursor: onOpenDay ? "pointer" : "default",
                          color: "var(--sp-navy)" }}>{d.day}</th>))}
                  <th style={{ ...th, textAlign: "right" }}>Requested</th>
                  <th style={{ ...th, textAlign: "right" }}>Approved</th>
                  <th style={{ ...th, textAlign: "right" }}>Waiting</th>
                </tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.emp_no}>
                      <td style={{ ...td, whiteSpace: "nowrap",
                                   position: "sticky", left: 0,
                                   background: "#fff" }}>
                        <b style={{ color: "var(--sp-navy)" }}>{r.emp_no}</b>{" "}
                        {r.full_name}
                        {r.is_subcontract && (
                          <span style={{ marginLeft: 6, fontSize: 10.5,
                                         color: "var(--muted)" }}>SUB</span>)}
                      </td>
                      {data.days.map((d) => {
                        const c = r.days[String(d.day)];
                        const look = c ? cellLook(c) : null;
                        return (
                          <td key={d.day} title={look?.title}
                              onClick={c && onOpenDay
                                ? () => onOpenDay(dateOf(d.day)) : undefined}
                              style={{ ...dcell, fontWeight: 700,
                                background: d.rest ? "#f7f9fc" : "#fff",
                                color: look?.color,
                                boxShadow: look?.outline,
                                cursor: c && onOpenDay ? "pointer" : "default"
                              }}>{look?.label ?? ""}</td>);
                      })}
                      <td style={num}>{hrs(r.requested)}</td>
                      <td style={{ ...num, color: "#1a7f37", fontWeight: 600 }}>
                        {hrs(r.approved)}</td>
                      <td style={{ ...num, color: "#b35900", fontWeight: 600 }}>
                        {Number(r.waiting) ? hrs(r.waiting) : ""}</td>
                    </tr>))}
                </tbody>
                {payroll.length > 0 && (
                  <tfoot><tr style={{ fontWeight: 700,
                                      borderTop: "2px solid var(--sp-navy)" }}>
                    <td style={{ ...td, position: "sticky", left: 0,
                                 background: "#fff" }}>Payroll total</td>
                    {data.days.map((d) => {
                      const t = dayTotal(d.day);
                      const open = t.open > 0;
                      return (
                        <td key={d.day}
                            title={open ? `${hrs(t.open)} h waiting` : undefined}
                            style={{ ...dcell,
                              color: open ? "#b35900" : "#1a7f37" }}>
                          {t.sum + t.open ? hrs(t.sum + t.open) : ""}</td>);
                    })}
                    <td style={num}>{hrs(total(payroll, "requested"))}</td>
                    <td style={{ ...num, color: "#1a7f37" }}>
                      {hrs(total(payroll, "approved"))}</td>
                    <td style={{ ...num, color: "#b35900" }}>
                      {hrs(total(payroll, "waiting"))}</td>
                  </tr></tfoot>)}
              </table>
            </div>)}
        </>)}
    </section>
  );
}
