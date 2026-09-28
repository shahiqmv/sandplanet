// One person's cost over a date range — attendance, overtime and what payroll
// paid them, on screen with a letterhead PDF and a workbook (owner
// 2026-09-28). Opened from the employee record; HR / Finance / Admin only,
// the same people who see salaries there.
import { useEffect, useState } from "react";
import { api, apiDownload } from "./api.js";
import { Btn, Chip, Stat, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const n = (v) => Number(v || 0);
const hrs = (v) => `${n(v).toLocaleString(undefined, { maximumFractionDigits: 1 })} h`;
const money = (v) => n(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtDay = (s) => new Date(s + "T00:00").toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });

function presets() {
  const t = new Date();
  const y = t.getFullYear(), m = t.getMonth();
  return [
    ["This month", iso(new Date(y, m, 1)), iso(t)],
    ["Last month", iso(new Date(y, m - 1, 1)), iso(new Date(y, m, 0))],
    ["Last 3 months", iso(new Date(y, m - 2, 1)), iso(t)],
    ["Year to date", iso(new Date(y, 0, 1)), iso(t)],
  ];
}

const num = { ...td, textAlign: "right", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" };
const numH = { ...th, textAlign: "right" };

export default function StaffCostReport({ employee, onClose }) {
  const [range, setRange] = useState(() => { const p = presets()[0]; return { from: p[1], to: p[2] }; });
  const [rep, setRep] = useState(null);
  const [error, setError] = useState(null);
  const [showDays, setShowDays] = useState(false);
  const q = `?from=${range.from}&to=${range.to}`;
  const base = `/employees/${employee.id}/cost-report`;

  useEffect(() => {
    if (!range.from || !range.to) return;
    setError(null);
    api(base + q).then(setRep).catch((e) => { setRep(null); setError(e.message); });
  }, [base, q, range.from, range.to]);

  async function excel() {
    try { await apiDownload(`${base}${q}&export=xlsx`); } catch (e) { setError(e.message); }
  }

  const e = rep?.employee;
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 60, background: "rgba(15,32,45,.35)",
                  overflow: "auto", padding: "4vh 16px" }} onClick={onClose}>
      <div style={{ ...card, maxWidth: 1080, margin: "0 auto" }} onClick={(ev) => ev.stopPropagation()}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 240 }}>
            <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>Staff cost report</h2>
            <div style={{ fontSize: 13, color: "var(--muted)" }}>
              {employee.emp_no} · {employee.full_name}
              {e ? ` · ${e.category || "no category"}` : ""}</div>
          </div>
          <button onClick={onClose} style={ghostButton}>Close</button>
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", margin: "14px 0 6px" }}>
          <input type="date" value={range.from} onChange={(ev) => setRange({ ...range, from: ev.target.value })}
                 style={{ ...inputStyle, width: 150 }} aria-label="From" />
          <span style={{ color: "var(--muted)" }}>to</span>
          <input type="date" value={range.to} onChange={(ev) => setRange({ ...range, to: ev.target.value })}
                 style={{ ...inputStyle, width: 150 }} aria-label="To" />
          {presets().map(([label, f, t]) => (
            <button key={label} onClick={() => setRange({ from: f, to: t })}
                    style={{ ...ghostButton, padding: "4px 10px", fontSize: 12.5,
                             ...(range.from === f && range.to === t ? { background: "var(--sky-soft)" } : {}) }}>
              {label}</button>
          ))}
          <span style={{ flex: 1 }} />
          <a href={`/api/v1${base}${q}&export=pdf`} target="_blank" rel="noreferrer"
             style={{ ...ghostButton, textDecoration: "none", color: "var(--navy)", padding: "5px 12px" }}>⬇ PDF</a>
          <Btn variant="secondary" onClick={excel}>⬇ Excel</Btn>
        </div>

        {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
        {!rep && !error && <p style={{ color: "var(--muted)" }}>Loading…</p>}

        {rep && (
          <>
            <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 10 }}>
              Basic {e.currency} {money(e.basic_pay)} / month
              {n(e.usd_basic_pay) > 0 && ` · USD basic ${money(e.usd_basic_pay)}`}
              {" · "}OT {n(e.ot_rate) > 0 ? `${e.ot_currency} ${money(e.ot_rate)} / h` : "none"}
              {" · "}{e.employment_type}{e.subcontract ? ` · subcontract (${e.subcontractor})` : ""}
              {e.join_date && ` · joined ${fmtDay(e.join_date)}`}{e.left_on && ` · left ${fmtDay(e.left_on)}`}
            </div>

            <div style={{ display: "flex", gap: 18, flexWrap: "wrap", padding: "12px 0",
                          borderTop: "1px solid var(--line)", borderBottom: "1px solid var(--line)" }}>
              <Stat value={n(rep.attendance.worked).toLocaleString()} label="Days worked"
                    context={`of ${rep.employed_days} employed · ${rep.attendance.rest_days_worked} rest day${rep.attendance.rest_days_worked === 1 ? "" : "s"} worked`} />
              <Stat value={hrs(rep.ot.approved)} label="OT approved"
                    context={`${hrs(rep.ot.workday)} paid as OT${n(rep.ot.rest_day) ? ` · ${hrs(rep.ot.rest_day)} on rest days` : ""}`} />
              <Stat value={hrs(rep.ot.pending)} label="OT awaiting approval"
                    tone={n(rep.ot.pending) ? "warn" : "info"}
                    context={`${rep.ot.pending_days} day${rep.ot.pending_days === 1 ? "" : "s"}`} />
              <Stat value={rep.pay_totals.length ? rep.pay_totals.map((t) => `${t.currency} ${money(t.net)}`).join(" + ") : "—"}
                    label="Net pay" tone={rep.pay.some((p) => !p.locked) ? "warn" : "info"}
                    context={!rep.pay.length ? "no payroll run in range"
                      : `${rep.pay.length} payroll line${rep.pay.length === 1 ? "" : "s"}${rep.pay.some((p) => !p.locked) ? " · not all locked yet" : ""}`} />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 18, marginTop: 14 }}>
              <div>
                <h3 style={{ margin: "0 0 6px", fontSize: 14 }}>Attendance</h3>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <tbody>
                    {rep.attendance.counts.filter((c) => c.days).map((c) => (
                      <tr key={c.key}><td style={td}>{c.label}</td><td style={num}>{c.days}</td></tr>
                    ))}
                    <tr><td style={td}>Not on the register</td>
                        <td style={num}>{rep.attendance.unmarked ? <Chip tone="warn">{rep.attendance.unmarked}</Chip> : 0}</td></tr>
                    <tr><td style={{ ...td, fontWeight: 700 }}>Days worked (half day = ½)</td>
                        <td style={{ ...num, fontWeight: 700 }}>{n(rep.attendance.worked).toLocaleString()}</td></tr>
                  </tbody>
                </table>
              </div>
              <div>
                <h3 style={{ margin: "0 0 6px", fontSize: 14 }}>By site</h3>
                {rep.attendance.by_site.length === 0 ? <p style={{ color: "var(--muted)", fontSize: 13 }}>No attendance in this range.</p> : (
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead><tr><th style={th}>Site</th><th style={numH}>Marked</th><th style={numH}>Worked</th><th style={numH}>OT approved</th></tr></thead>
                    <tbody>
                      {rep.attendance.by_site.map((s) => (
                        <tr key={s.site}><td style={td}><b>{s.site}</b> <span style={{ color: "var(--muted)" }}>{s.name}</span></td>
                          <td style={num}>{s.days}</td><td style={num}>{n(s.worked).toLocaleString()}</td><td style={num}>{hrs(s.ot)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>

            <h3 style={{ margin: "18px 0 6px", fontSize: 14 }}>Salary — payroll runs in these months</h3>
            {rep.pay.length === 0 ? <p style={{ color: "var(--muted)", fontSize: 13 }}>No payroll line in these months.</p> : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                  <thead><tr>
                    <th style={th}>Run</th><th style={th}>Period</th><th style={th}>Status</th>
                    <th style={numH}>Days</th><th style={numH}>Fridays</th><th style={numH}>OT h</th>
                    <th style={numH}>Earned basic</th><th style={numH}>Friday pay</th><th style={numH}>OT pay</th>
                    <th style={numH}>Allowance</th><th style={numH}>Gross</th><th style={numH}>Deductions</th><th style={numH}>Net</th>
                  </tr></thead>
                  <tbody>
                    {rep.pay.map((p) => (
                      <tr key={p.line_id} style={{ opacity: p.excluded ? .55 : 1 }}>
                        <td style={td}>{p.run}<div style={{ fontSize: 11, color: "var(--muted)" }}>{p.site}</div></td>
                        <td style={td}>{p.period}{p.part_month && <span title="A payroll run covers the whole month; your range covers only part of it" style={{ color: "var(--amber-fg)" }}> *</span>}</td>
                        <td style={td}>{p.locked ? p.status : <Chip tone="warn">{p.status}</Chip>}{p.excluded && <div style={{ fontSize: 11 }}>excluded — settled in cash</div>}</td>
                        <td style={num}>{n(p.days_worked).toLocaleString()}</td><td style={num}>{p.fridays_worked}</td><td style={num}>{n(p.ot_hours).toLocaleString()}</td>
                        <td style={num}>{money(p.earned_basic)}</td><td style={num}>{money(p.friday_pay)}</td><td style={num}>{money(p.ot_pay)}</td>
                        <td style={num}>{money(p.allowance)}</td><td style={num}>{money(p.gross)}</td><td style={num}>{money(p.deductions)}</td>
                        <td style={{ ...num, fontWeight: 700 }}>{p.currency} {money(p.net)}</td>
                      </tr>
                    ))}
                    {rep.pay_totals.map((t) => (
                      <tr key={t.currency} style={{ background: "var(--sky-soft)", fontWeight: 700 }}>
                        <td style={td} colSpan={4}>Total {t.currency}</td><td style={num}>{t.fridays}</td><td style={num}>{n(t.ot_hours).toLocaleString()}</td>
                        <td style={num}>{money(t.earned_basic)}</td><td style={num}>{money(t.friday_pay)}</td><td style={num}>{money(t.ot_pay)}</td>
                        <td style={num}>{money(t.allowance)}</td><td style={num}>{money(t.gross)}</td><td style={num}>{money(t.deductions)}</td>
                        <td style={num}>{t.currency} {money(t.net)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {rep.pay.some((p) => p.part_month) && <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 4 }}>* A payroll run covers the whole month; the range covers only part of it.</div>}
              </div>
            )}
            {rep.not_run.length > 0 && <p style={{ fontSize: 12.5, color: "var(--amber-fg)", margin: "6px 0 0" }}>No payroll run yet for {rep.not_run.join(", ")}.</p>}

            {rep.advances.length > 0 && (
              <>
                <h3 style={{ margin: "18px 0 6px", fontSize: 14 }}>Advances and loans raised in the range</h3>
                <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
                  <thead><tr><th style={th}>PYR</th><th style={th}>Kind</th><th style={numH}>Amount</th><th style={numH}>Instalments</th><th style={th}>Recovered from</th><th style={th}>Status</th></tr></thead>
                  <tbody>{rep.advances.map((a) => (
                    <tr key={a.ref}><td style={td}>{a.ref}</td><td style={td}>{a.kind}</td><td style={num}>{money(a.amount)}</td><td style={num}>{a.months}</td><td style={td}>{a.from}</td><td style={td}>{a.status}</td></tr>
                  ))}</tbody>
                </table>
              </>
            )}

            <div style={{ marginTop: 18 }}>
              <button onClick={() => setShowDays(!showDays)} style={{ ...ghostButton, padding: "4px 10px", fontSize: 12.5 }}>
                {showDays ? "Hide" : "Show"} day by day ({rep.days.length})</button>
              {showDays && (
                <div style={{ overflowX: "auto", marginTop: 8 }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
                    <thead><tr><th style={th}>Date</th><th style={th}>Site</th><th style={th}>Mark</th><th style={th}>In</th><th style={th}>Out</th>
                      <th style={numH}>OT requested</th><th style={numH}>OT approved</th><th style={th}></th></tr></thead>
                    <tbody>{rep.days.map((d) => (
                      <tr key={d.day} style={d.rest ? { background: "var(--sky-soft)" } : undefined}>
                        <td style={td}>{d.dow} {fmtDay(d.day)}</td><td style={td}>{d.site}</td><td style={td}>{d.mark}</td>
                        <td style={td}>{d.in}</td><td style={td}>{d.out}</td>
                        <td style={num}>{n(d.ot_requested) ? n(d.ot_requested) : ""}</td>
                        <td style={num}>{d.ot_approved != null ? n(d.ot_approved) : ""}</td>
                        <td style={td}>{d.pending ? <Chip tone="warn">awaiting approval</Chip>
                          : d.rest && d.remark === "PRESENT" && n(d.ot_approved) ? <span style={{ fontSize: 11.5, color: "var(--muted)" }}>rest day — flat Friday pay</span> : null}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
