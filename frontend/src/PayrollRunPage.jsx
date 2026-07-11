import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Monthly payroll runs (owner's salary sheet). MVR runs are per site; the USD
// run is one combined run across sites. Generate → edit the grid → lock.

const money = (v) => v == null || v === "" ? ""
  : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2,
                                        maximumFractionDigits: 2 });
const now = new Date();

export default function PayrollRunPage({ me, sites }) {
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);  // last month is common
  const [runs, setRuns] = useState([]);
  const [ready, setReady] = useState(null);
  const [openRun, setOpenRun] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  const canGenerate = ["HO_HR", "ADMIN"].includes(me.role);

  function loadRuns() {
    api(`/payroll/runs?year=${year}&month=${month}`).then(setRuns)
      .catch((e) => setError(e.message));
    api(`/payroll/readiness?year=${year}&month=${month}`).then(setReady)
      .catch(() => setReady(null));
  }
  useEffect(() => { if (!openRun) loadRuns(); },
    [year, month, openRun]); // eslint-disable-line

  async function generate() {
    setBusy(true); setError(null); setNotice(null);
    try {
      const r = await api("/payroll/generate",
                          { method: "POST", body: { year, month } });
      const made = r.created.length;
      const skips = r.skipped.filter((s) => s.reason !== "already generated");
      setNotice(`${made} run${made === 1 ? "" : "s"} generated.`
        + (skips.length ? ` Not ready: ${skips.map((s) =>
            `${s.site} (${s.reason})`).join(", ")}.` : ""));
      loadRuns();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  if (openRun) {
    return <RunDetail runId={openRun.id} onBack={() => setOpenRun(null)}
                      me={me} />;
  }

  const pending = (ready?.sites || []).filter((s) => !s.locked);

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
        {canGenerate && (
          <Btn onClick={generate} disabled={busy} style={{ marginLeft: "auto" }}>
            {busy ? "Generating…" : "Generate payroll"}</Btn>
        )}
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      {notice && <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>}

      {ready && pending.length > 0 && (
        <p style={{ fontSize: 12.5, color: "#b35900", margin: "10px 0 0" }}>
          ⚠ Attendance not locked yet (won't run): {pending.map((s) =>
            s.site_code + (s.is_head_office ? " (HO)" : "")).join(", ")}.
          {" "}Lock the month on Attendance first.
        </p>
      )}
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "6px 0 12px" }}>
        Generating creates one MVR run per site with locked attendance
        (Head Office included) plus the combined USD run. Runs already made are
        left as-is.
      </p>

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

const EDITABLE = [
  ["days_worked", "Days", 55], ["fridays_worked", "Fri", 45],
  ["ot_hours", "OT hrs", 60], ["allowance", "Allow.", 80],
  ["advance", "Advance", 80], ["penalty", "Penalty", 75],
  ["loan", "Loan", 80], ["amount_to_site", "To site", 85],
  ["amount_to_office", "To office", 85],
];

function RunDetail({ runId, onBack, me }) {
  const [run, setRun] = useState(null);
  const [error, setError] = useState(null);
  const canLock = ["HO_HR", "ADMIN"].includes(me.role);

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
        <button onClick={onBack} style={ghostButton}>← Runs</button>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 16 }}>
          {run.site_code || "USD — all sites"} · {monthName} {run.year}
        </h2>
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
          {run.currency} · {run.working_days} working days · {lines.length}{" "}
          workers · {locked
            ? <b style={{ color: "#1a7f37" }}>🔒 Locked</b> : "Draft"}</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <a href={`/api/v1/payroll/runs/${runId}/report.pdf`} target="_blank"
             rel="noreferrer" style={{ ...ghostButton, textDecoration: "none" }}>
            📄 Report PDF</a>
          {!locked && canLock && (
            <button onClick={lock} style={buttonStyle}>Lock run</button>
          )}
        </div>
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

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
                   onSave={saveField} />
            ))}
          </tbody>
          <tfoot>
            <tr style={{ fontWeight: 700, borderTop: "2px solid var(--sp-navy)" }}>
              <td style={td} colSpan={run.site_id == null ? 4 : 3}>TOTAL</td>
              <td style={{ ...td, textAlign: "right" }}>{money(sum("basic_pay"))}</td>
              <td style={{ ...td, textAlign: "right" }}>{sum("days_worked")}</td>
              <td style={{ ...td, textAlign: "right" }}>{sum("fridays_worked")}</td>
              <td style={{ ...td, textAlign: "right" }}>{sum("ot_hours")}</td>
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

function Row({ line, locked, showSite, onSave }) {
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
    <tr>
      <td style={{ ...td, fontWeight: 600 }}>{line.emp_no}</td>
      <td style={td}>{line.full_name}</td>
      {showSite && <td style={td}>{line.site_code}</td>}
      <td style={td}>{line.job_title}</td>
      {ro(line.basic_pay)}
      {cell("days_worked", 45)}{cell("fridays_worked", 40)}
      {cell("ot_hours", 50)}
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
      </td>
    </tr>
  );
}
