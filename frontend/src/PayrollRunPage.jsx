import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Monthly payroll runs (owner's salary sheet). MVR runs are per site; the USD
// run is one combined run across sites. Generate → edit the grid → lock.

const money = (v) => v == null || v === "" ? ""
  : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2,
                                        maximumFractionDigits: 2 });
const now = new Date();

export default function PayrollRunPage({ me, sites, initialRunId,
                                        onLeaveRun }) {
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);  // last month is common
  const [runs, setRuns] = useState([]);
  const [ready, setReady] = useState(null);
  const [summary, setSummary] = useState(null);
  const [openRun, setOpenRun] = useState(
    initialRunId ? { id: initialRunId } : null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  const canGenerate = ["HO_HR", "ADMIN"].includes(me.role);

  function loadRuns() {
    api(`/payroll/runs?year=${year}&month=${month}`).then(setRuns)
      .catch((e) => setError(e.message));
    api(`/payroll/readiness?year=${year}&month=${month}`).then(setReady)
      .catch(() => setReady(null));
    api(`/payroll/attendance-summary?year=${year}&month=${month}`)
      .then(setSummary).catch(() => setSummary(null));
  }
  // Opened straight from My Tasks on one run: don't fetch the run LIST — a PM
  // isn't permitted to list runs and the 403 would mask the run they came for.
  const focused = !!initialRunId;
  useEffect(() => { if (!openRun && !focused) loadRuns(); },
    [year, month, openRun]); // eslint-disable-line

  async function runOne(body, label) {
    setBusy(true); setError(null); setNotice(null);
    try {
      await api("/payroll/runs", { method: "POST", body: { year, month,
        ...body } });
      setNotice(`${label} payroll run generated.`);
      loadRuns();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  const generateSite = (s) =>
    runOne({ currency: "MVR", site_id: s.site_id }, s.site_code);
  const generateUsd = () => runOne({ currency: "USD" }, "USD / Head Office");

  if (openRun) {
    return <RunDetail runId={openRun.id} me={me}
                      backLabel={focused ? "‹ Back to My Tasks" : undefined}
                      onBack={() => {
                        setOpenRun(null);
                        if (focused && onLeaveRun) onLeaveRun();
                      }} />;
  }

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Payroll</h2>
        <label style={{ fontSize: 13 }}>Period{" "}
          <input type="number" value={year}
                 onChange={(e) => setYear(+e.target.value)}
                 style={{ ...inputStyle, width: 90, display: "inline" }} />
          <select value={month} onChange={(e) => setMonth(+e.target.value)}
                  style={{ ...inputStyle, width: 130, display: "inline",
                           marginLeft: 6 }}>
            {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
              <option key={m} value={m}>
                {new Date(2000, m - 1).toLocaleString("en", { month: "long" })}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      {notice && <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>}

      <p style={{ fontSize: 12, color: "var(--muted)", margin: "6px 0 12px" }}>
        Run each site on its own once its attendance is locked for the month —
        no need to wait for the others. The USD / Head Office run is one combined
        run and needs every USD-staffed site locked first.
      </p>

      {summary && <AttendanceReview summary={summary} year={year}
                                    month={month} />}

      {canGenerate && ready && (
        <div style={{ marginBottom: 18 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 13.5,
                       color: "var(--sp-navy)" }}>Generate a run</h3>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
            <thead><tr>
              <th style={th}>Site</th>
              <th style={{ ...th, textAlign: "right" }}>MVR staff</th>
              <th style={th}>Attendance</th>
              <th style={th} />
            </tr></thead>
            <tbody>
              {ready.sites.map((s) => (
                <tr key={s.site_id}>
                  <td style={{ ...td, fontWeight: 600 }}>
                    {s.site_code}{s.is_head_office ? " (HO)" : ""}</td>
                  <td style={{ ...td, textAlign: "right" }}>{s.mvr_staff}</td>
                  <td style={td}>{s.locked
                    ? <span style={{ color: "#1a7f37" }}>🔒 Locked</span>
                    : <span style={{ color: "#b35900" }}>Not locked</span>}</td>
                  <td style={td}>
                    {s.has_run
                      ? <span style={{ color: "var(--muted)" }}>Run made ✓</span>
                      : s.locked
                        ? <Btn onClick={() => generateSite(s)} disabled={busy}
                               style={{ padding: "3px 12px", fontSize: 12 }}>
                            Generate run</Btn>
                        : <span style={{ fontSize: 12, color: "var(--muted)" }}>
                            Lock attendance first</span>}
                  </td>
                </tr>
              ))}
              {ready.usd_staff > 0 && (
                <tr>
                  <td style={{ ...td, fontWeight: 600 }}>USD / Head Office
                    <span style={{ fontWeight: 400, color: "var(--muted)" }}>
                      {" "}· combined</span></td>
                  <td style={{ ...td, textAlign: "right" }}>{ready.usd_staff}</td>
                  <td style={td} />
                  <td style={td}>
                    {ready.usd_has_run
                      ? <span style={{ color: "var(--muted)" }}>Run made ✓</span>
                      : <Btn onClick={generateUsd} disabled={busy}
                             style={{ padding: "3px 12px", fontSize: 12 }}>
                          Generate USD run</Btn>}
                  </td>
                </tr>
              )}
              {ready.sites.length === 0 && ready.usd_staff === 0 && (
                <tr><td colSpan={4} style={{ ...td, color: "var(--muted)" }}>
                  No payroll-eligible staff for this period.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead><tr>
          <th style={th}>Run</th><th style={th}>Currency</th>
          <th style={th}>Working days</th><th style={th}>Status</th>
          <th style={th} />
        </tr></thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id}>
              <td style={td}>{r.site_code || "USD — all sites"}</td>
              <td style={td}>{r.currency}</td>
              <td style={td}>{r.working_days}</td>
              <td style={td}>{r.status === "LOCKED"
                ? <span style={{ color: "#1a7f37" }}>🔒 Locked</span>
                : "Draft"}</td>
              <td style={td}>
                <button onClick={() => api(`/payroll/runs/${r.id}`)
                          .then(setOpenRun)}
                        style={{ ...ghostButton, padding: "2px 12px",
                                 fontSize: 12 }}>Open</button>
              </td>
            </tr>
          ))}
          {runs.length === 0 && (
            <tr><td colSpan={5} style={{ ...td, color: "var(--muted)" }}>
              No runs for this period yet — generate one above.</td></tr>
          )}
        </tbody>
      </table>
    </section>
  );
}

const hrs = (v) => Number(v || 0).toLocaleString("en-US",
  { maximumFractionDigits: 2 });
const rnum = { ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" };

// Pre-run review: per-site attendance + OT totals for the month, a company-wide
// roll-up, and a drill-down into the OT detail — so HR checks the figures
// feeding payroll before generating (owner 2026-08-05).
function AttendanceReview({ summary, year, month }) {
  const [ot, setOt] = useState(null);   // {siteId|null, label} or null
  const { sites, totals } = summary;
  if (!sites.length) {
    return (
      <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "0 0 14px" }}>
        No payroll-eligible workers on any site for this period.</p>
    );
  }
  const otBtn = (siteId, label) => (
    <button onClick={() => setOt(ot && ot.siteId === siteId
      ? null : { siteId, label })}
      style={{ ...ghostButton, padding: "2px 10px", fontSize: 11.5 }}>
      {ot && ot.siteId === siteId ? "Hide OT" : "OT details"}</button>
  );
  const H = ({ children, r }) => (
    <th style={{ ...th, textAlign: r ? "right" : "left" }}>{children}</th>);
  return (
    <div style={{ marginBottom: 18, border: "1px solid var(--sp-border)",
                  borderRadius: 8, padding: "10px 12px",
                  background: "var(--sp-bg-subtle, #f8fafc)" }}>
      <h3 style={{ margin: "0 0 2px", fontSize: 13.5, color: "var(--sp-navy)" }}>
        Review attendance &amp; OT before you run</h3>
      <p style={{ fontSize: 11.5, color: "var(--muted)", margin: "0 0 8px" }}>
        These are the days and overtime from the locked attendance — exactly what
        each run will post. Check them before generating.</p>
      <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead><tr>
          <H>Site</H><H r>Workers</H><H r>Days worked</H><H r>OT hrs</H>
          <H r>Absences</H><H r>Rest-day work</H><H>Attendance</H><H />
        </tr></thead>
        <tbody>
          {sites.map((s) => (
            <tr key={s.site_id}>
              <td style={{ ...td, fontWeight: 600 }}>
                {s.site_code}{s.is_head_office ? " (HO)" : ""}</td>
              <td style={rnum}>{s.workers}</td>
              <td style={rnum}>{s.days_worked}</td>
              <td style={{ ...rnum, fontWeight: 600 }}>{hrs(s.ot_hours)}</td>
              <td style={rnum}>{s.absences || ""}</td>
              <td style={rnum}>{s.rest_day_work || ""}</td>
              <td style={td}>{s.locked
                ? <span style={{ color: "#1a7f37" }}>🔒 Locked</span>
                : <span style={{ color: "#b35900" }}>Provisional</span>}</td>
              <td style={{ ...td, textAlign: "right" }}>
                {s.ot_hours > 0 ? otBtn(s.site_id, s.site_code) : null}</td>
            </tr>
          ))}
          <tr style={{ fontWeight: 700, borderTop: "2px solid var(--sp-navy)" }}>
            <td style={td}>All sites</td>
            <td style={rnum}>{totals.workers}</td>
            <td style={rnum}>{totals.days_worked}</td>
            <td style={rnum}>{hrs(totals.ot_hours)}</td>
            <td style={rnum}>{totals.absences || ""}</td>
            <td style={rnum}>{totals.rest_day_work || ""}</td>
            <td style={td} />
            <td style={{ ...td, textAlign: "right" }}>
              {totals.ot_hours > 0 ? otBtn(null, "All sites") : null}</td>
          </tr>
        </tbody>
      </table>
      </div>
      {!summary.all_locked && (
        <p style={{ fontSize: 11.5, color: "#b35900", margin: "8px 0 0" }}>
          ⚠ "Provisional" sites aren't locked yet — their figures are as-of-today
          and can still change. Lock the month before running them.</p>
      )}
      {ot && <OtBreakdown year={year} month={month} siteId={ot.siteId}
                          label={ot.label} onClose={() => setOt(null)} />}
    </div>
  );
}

function OtBreakdown({ year, month, siteId, label, onClose }) {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState({});
  const [err, setErr] = useState(null);
  useEffect(() => {
    setData(null); setErr(null);
    const q = `year=${year}&month=${month}` + (siteId ? `&site_id=${siteId}` : "");
    api(`/payroll/ot-breakdown?${q}`).then(setData)
      .catch((e) => setErr(e.message));
  }, [year, month, siteId]);
  return (
    <div style={{ marginTop: 10, border: "1px solid var(--sp-border)",
                  borderRadius: 8, padding: "10px 12px", background: "#fff" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <strong style={{ fontSize: 12.5, color: "var(--sp-navy)" }}>
          Overtime detail — {label}</strong>
        {data && <span style={{ fontSize: 12, color: "var(--muted)" }}>
          {data.worker_count} worker{data.worker_count === 1 ? "" : "s"} ·
          {" "}{hrs(data.total_ot)} hrs total</span>}
        <button onClick={onClose} style={{ ...ghostButton, marginLeft: "auto",
          padding: "2px 10px", fontSize: 11.5 }}>Close</button>
      </div>
      {err && <p style={{ color: "#c0392b", fontSize: 12 }}>{err}</p>}
      {data && data.workers.length === 0 && (
        <p style={{ fontSize: 12, color: "var(--muted)", margin: "8px 0 0" }}>
          No approved overtime recorded for this period.</p>
      )}
      {data && data.workers.map((w) => {
        const isOpen = open[w.emp_no];
        return (
          <div key={w.emp_no} style={{ borderTop: "1px solid var(--line, #eee)",
            padding: "6px 0" }}>
            <div style={{ display: "flex", gap: 8, alignItems: "baseline",
              cursor: "pointer", fontSize: 12.5 }}
              onClick={() => setOpen((o) => ({ ...o, [w.emp_no]: !isOpen }))}>
              <span style={{ color: "var(--muted)", width: 12 }}>
                {isOpen ? "▾" : "▸"}</span>
              <b>{w.emp_no}</b> {w.full_name}
              <span style={{ color: "var(--muted)" }}>
                {w.job_title ? ` · ${w.job_title}` : ""}
                {siteId ? "" : ` · ${w.site_code}`}</span>
              <span style={{ marginLeft: "auto", fontWeight: 700 }}>
                {hrs(w.total_ot)} hrs</span>
            </div>
            {isOpen && (
              <table style={{ margin: "4px 0 4px 20px", fontSize: 12,
                borderCollapse: "collapse" }}>
                <tbody>
                  {w.days.map((d, i) => (
                    <tr key={i}>
                      <td style={{ padding: "1px 14px 1px 0" }}>{d.day}</td>
                      <td style={{ padding: "1px 14px 1px 0",
                        textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                        {hrs(d.hours)} hrs</td>
                      <td style={{ padding: "1px 0", color: "var(--muted)" }}>
                        {d.approved_by ? `approved by ${d.approved_by}` : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        );
      })}
    </div>
  );
}

// What the register holds, next to what we are paying. A month has four or
// five unmarked rest days, so a small gap is normal and stays quiet; an empty
// register or a wide gap is the shape of both July faults — two BVR men paid
// 31 days with no attendance at all, and a whole site paid eleven days short
// of what it had marked (owner 2026-08-14).
function Marked({ line }) {
  const marked = line.days_marked ?? 0;
  const gap = Number(line.days_worked) - marked;
  const clash = line.joined_after;
  const bad = marked === 0 || !!clash;
  const warn = !bad && Math.abs(gap) > 6;
  const colour = bad ? "#c0392b" : warn ? "#b35900" : "#5a6b78";
  const title = clash
    ? `Marked here in this month, but recorded as joining on ${clash}. `
      + "One of the two is wrong — either the join date or the attendance. "
      + "Days paid follow the register until someone settles it."
    : marked === 0
      ? "Nothing marked for this worker all month — paid days cannot be "
        + "checked against anything. Fix the register, then refresh."
      : `${line.days_present ?? 0} present, ${line.days_absent ?? 0} absent, `
        + `${marked} days marked in total`;
  return (
    <td style={{ ...td, textAlign: "right", color: colour,
                 fontWeight: bad || warn ? 700 : 400 }} title={title}>
      {marked === 0 ? "none" : marked}{clash ? " ⚠" : ""}
    </td>
  );
}

const EDITABLE = [
  ["days_worked", "Days", 55], ["fridays_worked", "Fri", 45],
  ["ot_hours", "OT hrs", 60], ["allowance", "Allow.", 80],
  ["advance", "Advance", 80], ["penalty", "Penalty", 75],
  ["loan", "Loan", 80], ["amount_to_site", "To site", 85],
  ["amount_to_office", "To office", 85],
];

function RunDetail({ runId, onBack, me, backLabel }) {
  const [run, setRun] = useState(null);
  const [error, setError] = useState(null);
  const canLock = ["HO_HR", "ADMIN", "FINANCE", "PA"].includes(me.role);
  // Draft salary verification (owner 2026-08-12): HR submits → the site PM
  // verifies → the PD approves → HR/Finance locks.
  const isHR = ["HO_HR", "ADMIN", "FINANCE", "PA"].includes(me.role);
  const isPM = ["PM", "ADMIN"].includes(me.role);
  const isPD = ["DIRECTOR", "ADMIN"].includes(me.role);

  function load() {
    api(`/payroll/runs/${runId}`).then(setRun).catch((e) => setError(e.message));
  }
  useEffect(load, [runId]);

  const locked = run?.status === "LOCKED";

  async function saveField(lineId, field, value) {
    try {
      const updated = await api(`/payroll/lines/${lineId}`,
        { method: "PATCH", body: { [field]: value } });
      setRun((r) => ({ ...r, lines: r.lines.map((l) =>
        l.id === lineId ? { ...l, ...updated } : l) }));
    } catch (e) { setError(e.message); }
  }

  // The rest-day decision belongs to the site PM, so unlike an HR field edit
  // it must NOT bounce the run back to draft — the PM is making the call
  // during their own verification (owner 2026-08-13).
  async function setRestDay(line, revoked) {
    if (revoked && !window.confirm(
      `Strike ${line.emp_no} ${line.full_name}'s unworked rest days off their `
      + "pay? Use this when they were absent through the week.")) return;
    try {
      setRun(await api(`/payroll/lines/${line.id}/rest-day`,
                       { method: "POST", body: { revoked } }));
    } catch (e) { setError(e.message); }
  }

  // A leaver settled in cash on the way out would otherwise be paid twice by
  // the monthly run (owner 2026-08-14). The line stays, at zero, with the
  // reason on it — the man did work the month.
  async function setExcluded(line, excluded) {
    let reason = "";
    if (excluded) {
      reason = window.prompt(
        `Leave ${line.emp_no} ${line.full_name} off this payout?\n\n`
        + "Their days and attendance stay on the run for the record, but they "
        + "will be paid nothing. Why?",
        "Paid off in full when they left");
      if (reason === null || !reason.trim()) return;
    }
    try {
      setRun(await api(`/payroll/lines/${line.id}/exclude`,
                       { method: "POST", body: { excluded, reason } }));
    } catch (e) { setError(e.message); }
  }

  async function act(action) {
    let reason = "";
    if (action === "return") {
      reason = window.prompt("Why are you returning this salary draft to HR?")
               || "";
      if (!reason.trim()) return;
    }
    try {
      setRun(await api(`/payroll/runs/${runId}`,
                       { method: "POST", body: { action, reason } }));
      setError(null);
    } catch (e) { setError(e.message); }
  }

  async function refresh() {
    if (!window.confirm(
      "Re-pull attendance, rates and pay policy into this run?\n\n"
      + "Days, OT hours, Fridays, OT rate and basic are recalculated from "
      + "current data; your allowance and penalty entries are kept. Newly "
      + "eligible workers are added.")) return;
    try {
      const d = await api(`/payroll/runs/${runId}`,
                          { method: "POST", body: { action: "refresh" } });
      setRun(d);
      const r = d.refresh || {};
      const bits = [`${(r.changed || []).length} line(s) updated`];
      if ((r.added || []).length) bits.push(`${r.added.length} added`);
      if ((r.no_longer_eligible || []).length)
        bits.push(`${r.no_longer_eligible.length} no longer eligible `
                  + `(${r.no_longer_eligible.join(", ")}) — review these`);
      setError(null);
      window.alert("Refreshed — " + bits.join(", ") + ".");
    } catch (e) { setError(e.message); }
  }

  async function lock() {
    if (!window.confirm("Lock this run? It posts labour cost and can't be "
                        + "edited afterwards.")) return;
    try { setRun(await api(`/payroll/runs/${runId}`, { method: "POST" })); }
    catch (e) { setError(e.message); }
  }

  if (!run) return <section style={card}>Loading…</section>;
  const lines = run.lines || [];
  const sum = (k) => lines.reduce((a, l) => a + Number(l[k] || 0), 0);
  const monthName = new Date(2000, run.month - 1)
    .toLocaleString("en", { month: "long" });

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap" }}>
        <button onClick={onBack} style={ghostButton}>
          {backLabel || "← Runs"}
        </button>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 16 }}>
          {run.site_code || "USD — all sites"} · {monthName} {run.year}
        </h2>
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
          {run.currency} · {run.working_days} working days · {lines.length}{" "}
          workers · {locked
            ? <b style={{ color: "#1a7f37" }}>🔒 Locked</b>
            : <b style={{ color: run.status === "APPROVED" ? "#1a7f37"
                          : run.status === "RETURNED" ? "#c0392b"
                          : "#8a6d00" }}>{run.status_label || run.status}</b>}
          {run.verified_by && <span style={{ color: "var(--muted)" }}>
            {" "}· verified by {run.verified_by}</span>}
          {run.approved_by && <span style={{ color: "var(--muted)" }}>
            {" "}· approved by {run.approved_by}</span>}</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <a href={`/api/v1/payroll/runs/${runId}/report.pdf`} target="_blank"
             rel="noreferrer" style={{ ...ghostButton, textDecoration: "none" }}>
            📄 Report PDF</a>
          {!locked && isHR && ["DRAFT", "RETURNED"].includes(run.status) && (
            <button onClick={refresh} style={ghostButton}
              title="Re-pull attendance, OT rates and pay policy — keeps your allowance/penalty entries">
              ↻ Refresh from attendance</button>
          )}
          {!locked && isHR && ["DRAFT", "RETURNED"].includes(run.status) && (
            <button onClick={() => act("submit")} style={buttonStyle}
              title="Send to the site PM to verify">
              Submit for verification</button>
          )}
          {run.status === "PM_REVIEW" && isPM && (
            <button onClick={() => act("verify")} style={buttonStyle}>
              ✓ Verify (PM)</button>
          )}
          {run.status === "PD_REVIEW" && isPD && (
            <button onClick={() => act("approve")} style={buttonStyle}>
              ✓ Approve (PD)</button>
          )}
          {["PM_REVIEW", "PD_REVIEW"].includes(run.status) && (isPM || isPD) && (
            <button onClick={() => act("return")} style={ghostButton}>
              Return to HR</button>
          )}
          {run.status === "APPROVED" && canLock && (
            <button onClick={lock} style={buttonStyle}>Lock run</button>
          )}
        </div>
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      {run.status === "RETURNED" && run.return_reason && (
        <p style={{ fontSize: 12.5, color: "#c0392b", margin: "6px 0 0" }}>
          Returned to HR: {run.return_reason}</p>)}
      {/* Named in the register but with no payable day. They are correctly
          off the run — an August joiner does not belong on a July payroll —
          but something put a mark against them, so it is said out loud rather
          than left for the next person to find (owner 2026-08-15). */}
      {run.marked_but_unpayable?.length > 0 && (
        <div style={{ marginTop: 8, padding: "7px 10px", fontSize: 12.5,
                      background: "#fff6e5", border: "1px solid #f0d9a8",
                      borderRadius: 6, color: "#7a5b12" }}>
          <strong>Marked in this month but not payable — not on this run:</strong>
          {" "}
          {run.marked_but_unpayable.map((w) =>
            `${w.emp_no} ${w.full_name} (${w.marked} day`
            + `${w.marked === 1 ? "" : "s"} marked`
            + `${w.join_date ? `, joined ${w.join_date}` : ""})`).join("; ")}
          . Either the join date or the attendance is wrong — fix whichever it
          is and refresh.
        </div>)}

      <div style={{ overflowX: "auto", marginTop: 12 }}>
        <table style={{ borderCollapse: "collapse", fontSize: 12,
                        minWidth: 1100 }}>
          <thead><tr>
            <th style={th}>Emp</th><th style={th}>Name</th>
            {run.site_id == null && <th style={th}>Site</th>}
            <th style={th}>Title</th>
            <th style={{ ...th, textAlign: "right" }}>Basic</th>
            {EDITABLE.slice(0, 3).map(([k, l]) =>
              <th key={k} style={{ ...th, textAlign: "right" }}>{l}</th>)}
            <th style={{ ...th, textAlign: "right" }}
                title="Days the site actually marked this worker in the
                       attendance register — the evidence behind Days.">
              Marked</th>
            <th style={{ ...th, textAlign: "right" }}>Earned</th>
            <th style={{ ...th, textAlign: "right" }}>OT pay</th>
            <th style={{ ...th, textAlign: "right" }}>Allow.</th>
            <th style={{ ...th, textAlign: "right" }}>Gross</th>
            {["advance", "penalty", "loan"].map((k) =>
              <th key={k} style={{ ...th, textAlign: "right",
                textTransform: "capitalize" }}>{k}</th>)}
            <th style={{ ...th, textAlign: "right" }}>Net</th>
            <th style={{ ...th, textAlign: "right" }}>To site</th>
            <th style={{ ...th, textAlign: "right" }}>To office</th>
          </tr></thead>
          <tbody>
            {lines.map((l) => (
              <Row key={l.id} line={l} locked={locked} showSite={run.site_id == null}
                   onSave={saveField}
                   onRestDay={!locked && (isPM || isHR || isPD)
                     ? setRestDay : null}
                   onExclude={!locked && isHR ? setExcluded : null} />
            ))}
          </tbody>
          <tfoot>
            <tr style={{ fontWeight: 700, borderTop: "2px solid var(--sp-navy)" }}>
              <td style={td} colSpan={run.site_id == null ? 4 : 3}>TOTAL</td>
              <td style={{ ...td, textAlign: "right" }}>{money(sum("basic_pay"))}</td>
              <td style={{ ...td, textAlign: "right" }}>{sum("days_worked")}</td>
              <td style={{ ...td, textAlign: "right" }}>{sum("fridays_worked")}</td>
              <td style={{ ...td, textAlign: "right" }}>{sum("ot_hours")}</td>
              <td style={{ ...td, textAlign: "right" }}>{sum("days_marked")}</td>
              <td style={{ ...td, textAlign: "right" }}>{money(sum("earned_basic"))}</td>
              <td style={{ ...td, textAlign: "right" }}>{money(sum("ot_pay"))}</td>
              <td style={{ ...td, textAlign: "right" }}>{money(sum("allowance"))}</td>
              <td style={{ ...td, textAlign: "right" }}>{money(sum("gross"))}</td>
              <td style={{ ...td, textAlign: "right" }}>{money(sum("advance"))}</td>
              <td style={{ ...td, textAlign: "right" }}>{money(sum("penalty"))}</td>
              <td style={{ ...td, textAlign: "right" }}>{money(sum("loan"))}</td>
              <td style={{ ...td, textAlign: "right" }}>{money(sum("net"))}</td>
              <td style={{ ...td, textAlign: "right" }}>{money(sum("amount_to_site"))}</td>
              <td style={{ ...td, textAlign: "right" }}>{money(sum("amount_to_office"))}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}

function Row({ line, locked, showSite, onSave, onRestDay, onExclude }) {
  const [v, setV] = useState(line);
  useEffect(() => setV(line), [line]);
  const cell = (k, w) => (
    <td style={{ padding: 2 }}>
      <input value={v[k] ?? ""} disabled={locked}
             onChange={(e) => setV((s) => ({ ...s, [k]: e.target.value }))}
             onBlur={(e) => e.target.value !== String(line[k] ?? "") &&
                            onSave(line.id, k, e.target.value)}
             style={{ ...inputStyle, width: w, textAlign: "right",
                      padding: "3px 5px" }} />
    </td>
  );
  const ro = (val) => <td style={{ ...td, textAlign: "right" }}>{money(val)}</td>;
  return (
    <tr style={line.excluded
      ? { opacity: 0.55, textDecoration: "line-through" } : undefined}>
      <td style={{ ...td, fontWeight: 600 }}>{line.emp_no}</td>
      <td style={td}>{line.full_name}</td>
      {showSite && <td style={td}>{line.site_code}</td>}
      <td style={td}>{line.job_title}</td>
      {ro(line.basic_pay)}
      {cell("days_worked", 45)}{cell("fridays_worked", 40)}
      {cell("ot_hours", 50)}
      <Marked line={line} />
      {ro(line.earned_basic)}{ro(line.ot_pay)}
      {cell("allowance", 70)}
      {ro(line.gross)}
      {cell("advance", 70)}{cell("penalty", 65)}{cell("loan", 70)}
      {ro(line.net)}
      {cell("amount_to_site", 75)}{cell("amount_to_office", 75)}
      <td style={{ ...td, whiteSpace: "nowrap" }}>
        <a href={`/api/v1/payroll/lines/${line.id}/payslip.pdf`}
           target="_blank" rel="noreferrer" title="Salary slip"
           style={{ textDecoration: "none" }}>🧾</a>
        {/* The rest day is unmarked in attendance and paid as part of the
            month. The site PM knows who was absent through the week and
            plainly did not earn it (owner 2026-08-13). */}
        {onRestDay && (
          <a href="#" onClick={(e) => { e.preventDefault();
                                        onRestDay(line, !line.rest_day_revoked); }}
             title={line.rest_day_revoked
               ? "Rest days struck off — click to restore them"
               : "Strike this worker's unworked rest days off their pay"}
             style={{ marginLeft: 8, fontSize: 11, textDecoration: "none",
                      color: line.rest_day_revoked ? "#b00" : "#8a94a0" }}>
            {line.rest_day_revoked ? "no rest day" : "rest day"}
          </a>
        )}
        {onExclude && (
          <a href="#" onClick={(e) => { e.preventDefault();
                                        onExclude(line, !line.excluded); }}
             title={line.excluded
               ? `Left off this payout — ${line.excluded_reason}. `
                 + "Click to put them back."
               : "Leave this worker off the payout — already settled in cash"}
             style={{ marginLeft: 8, fontSize: 11, textDecoration: "none",
                      color: line.excluded ? "#b00" : "#8a94a0" }}>
            {line.excluded ? "not paid" : "exclude"}
          </a>
        )}
      </td>
    </tr>
  );
}
