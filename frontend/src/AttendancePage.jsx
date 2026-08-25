import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

const NORMAL_REMARKS = ["PRESENT", "HALF_DAY", "ABSENT", "SICK", "LEAVE"];
const REST_REMARKS = ["OFF", "PRESENT", "HALF_DAY"];
const hhmm = (value) => (value ? String(value).slice(0, 5) : "");

export default function AttendancePage({ site, me, onClose }) {
  const [mode, setMode] = useState("day");   // "day" | "register"
  const [day, setDay] = useState(() => new Date().toISOString().slice(0, 10));
  const [grid, setGrid] = useState(null);
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  const canEnter = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "HO_HR", "DIRECTOR",
                    "ADMIN"].includes(me.role);
  const isPm = ["PM", "HO_HR", "ADMIN"].includes(me.role);

  const load = useCallback(() => {
    setNotice(null);
    api(`/attendance?site=${site.id}&date=${day}`).then((data) => {
      setGrid(data);
      setRows(data.rows.map((r) => {
        const row = { ...r, check_in: hhmm(r.check_in),
                      check_out: hhmm(r.check_out) };
        // The gate's OT proposal pre-fills the OT box on rows not yet saved
        // — nothing to click; the clerk adjusts if wrong and saves, the PM
        // approves as always. In/out stay the site's official hours: punch
        // times are evidence, not the timesheet (owner 2026-08-25).
        const p = r.device?.proposal;
        if (!r.saved && p && parseFloat(p.ot_requested) > 0) {
          if (r.is_subcontract) row.sub_extra_hours = p.ot_requested;
          else row.ot_requested = p.ot_requested;
        }
        return row;
      }));
    }).catch((e) => setError(e.message));
  }, [site.id, day]);

  useEffect(() => { if (mode === "day") load(); }, [load, mode]);

  const setRow = (i, patch) =>
    setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const result = await api("/attendance/bulk", {
        method: "PUT",
        body: { site: site.id, date: day, rows },
      });
      // load() clears the notice, so say it AFTER reloading or the
      // confirmation never reaches the screen.
      load();
      setNotice(`Saved ${result.saved} row(s)` +
                (result.late_edit ? " (late edit — audited)." : "."));
      // The server refuses individual rows it cannot accept — a day before the
      // man joined, or a day of leave without pay. It was saying so and the
      // screen was throwing it away, which is how a mark silently fails to
      // take (owner 2026-08-20).
      if (result.refused?.length) {
        setError("Not recorded: " + result.refused.join("; ") + ".");
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function approveAllOt() {
    setError(null);
    try {
      const fresh = await api(`/attendance?site=${site.id}&date=${day}`);
      const ids = fresh.rows
        .filter((r) => r.attendance_id && parseFloat(r.ot_requested) > 0 &&
                       r.ot_approved == null)
        .map((r) => r.attendance_id);
      if (!ids.length) {
        setNotice("No requested OT awaiting approval.");
        return;
      }
      await api("/attendance/ot-approve", { method: "POST", body: { ids } });
      setNotice(`Approved OT on ${ids.length} row(s).`);
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function lockMonth() {
    const [y, m] = day.split("-");
    setError(null);
    try {
      await api(`/timesheets/${site.id}/${+y}/${+m}/lock`, { method: "POST" });
      setNotice("Month signed off and locked.");
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function unlockMonth() {
    const [y, m] = day.split("-");
    const reason = window.prompt("Reopen this month for edits — reason "
      + "(e.g. locked by mistake):");
    if (reason === null) return;
    if (!reason.trim()) { setError("A reason is required to reopen."); return; }
    setError(null);
    try {
      await api(`/timesheets/${site.id}/${+y}/${+m}/reopen`,
        { method: "POST", body: { reason: reason.trim() } });
      setNotice("Month reopened — you can edit attendance again.");
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  const restDay = grid?.is_rest_day;
  const remarkOptions = restDay ? REST_REMARKS : NORMAL_REMARKS;

  const header = (
    <div style={{ display: "flex", justifyContent: "space-between",
                  alignItems: "baseline", flexWrap: "wrap", gap: 10 }}>
      <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
        Attendance — {site.code}
      </h2>
      <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button onClick={() => setMode("day")}
                style={mode === "day" ? buttonStyle : ghostButton}>
          Day entry</button>
        <button onClick={() => setMode("register")}
                style={mode === "register" ? buttonStyle : ghostButton}>
          Month register</button>
        <button onClick={onClose} style={ghostButton}>Close</button>
      </span>
    </div>
  );

  if (mode === "register") {
    return (
      <section style={card}>
        {header}
        <Register site={site} canEnter={canEnter}
          onOpenDay={(dateStr) => { setDay(dateStr); setMode("day"); }} />
      </section>
    );
  }

  return (
    <section style={card}>
      {header}
      <div style={{ display: "flex", gap: 8, alignItems: "center",
                    marginTop: 10 }}>
        <input type="date" value={day}
               onChange={(e) => setDay(e.target.value)}
               style={{ ...inputStyle, width: 150 }} />
        {grid && <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
          {new Date(day + "T00:00").toLocaleDateString("en",
            { weekday: "long" })}</span>}
      </div>

      {restDay && (
        <p style={{ background: "#eef4fb", borderRadius: 8,
                    padding: "8px 12px", fontSize: 13, marginTop: 10 }}>
          🗓 Rest day — everyone is OFF by default. Mark only those who worked
          this day; a worked rest day is paid as an extra (7th) day in payroll.
        </p>
      )}
      {grid?.device_unmatched?.length > 0 && (
        <p style={{ fontSize: 12.5, color: "#b35900", marginTop: 8 }}>
          At the gate but not on this register:{" "}
          {grid.device_unmatched.map((u) =>
            `${u.full_name || `ID ${u.device_user_id}`} (${u.punched_at} — ${
              u.why})`).join(" · ")}
        </p>)}
      {grid?.locked && (
        <div style={{ background: "#fdeceb", borderRadius: 8,
                      padding: "8px 12px", fontSize: 13, display: "flex",
                      alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span>🔒 This month is signed off and locked.
            {isPm ? " Reopen it if it was locked by mistake." : " Ask the "
              + "site PM or HR to reopen it for corrections."}</span>
          {isPm && (
            <button onClick={unlockMonth}
                    style={{ ...ghostButton, marginLeft: "auto",
                             color: "#b35900" }}>
              🔓 Unlock month</button>
          )}
        </div>
      )}
      {notice && <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>}
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <table style={{ width: "100%", borderCollapse: "collapse",
                      marginTop: 10 }}>
        <thead><tr>
          <th style={{ ...th, width: 80 }}>Emp No</th>
          <th style={{ ...th, width: 240 }}>Name</th>
          <th style={{ ...th, width: 130 }}>Category</th>
          <th style={{ ...th, width: 120 }}>In</th>
          <th style={{ ...th, width: 120 }}>Out</th>
          <th style={{ ...th, width: 130 }}>Remark</th>
          {grid?.has_devices && <th style={{ ...th, width: 125 }}>Gate</th>}
          <th style={{ ...th, width: 90 }}>OT / Extra (h)</th>
          <th style={th}>OT approved</th>
        </tr></thead>
        <tbody>
          {rows.map((row, i) => {
            const off = row.remark === "OFF";
            const sub = row.is_subcontract;
            return (
            <tr key={row.employee_id}
                style={sub ? { background: "#eef5fb" } : undefined}>
              <td style={{ ...td, fontWeight: 600,
                           color: "var(--sp-navy)" }}>{row.emp_no}</td>
              <td style={td}>{row.full_name}
                {sub && (
                  <span title={row.subcontractor || "Subcontract worker"}
                        style={{ marginLeft: 6, fontSize: 10.5,
                                 fontWeight: 700, color: "#1a6091",
                                 background: "#d5e6f3", borderRadius: 4,
                                 padding: "1px 5px" }}>
                    SUB
                  </span>
                )}
              </td>
              <td style={td}>{row.category}</td>
              <td style={{ padding: 3 }}>
                <input type="time" value={row.check_in || ""}
                       disabled={grid?.locked || !canEnter || off}
                       onChange={(e) => setRow(i, { check_in: e.target.value })}
                       style={{ ...inputStyle, width: 105 }} />
              </td>
              <td style={{ padding: 3 }}>
                <input type="time" value={row.check_out || ""}
                       disabled={grid?.locked || !canEnter || off}
                       onChange={(e) => setRow(i, { check_out: e.target.value })}
                       style={{ ...inputStyle, width: 105 }} />
              </td>
              <td style={{ padding: 3 }}>
                <select value={row.remark} disabled={grid?.locked || !canEnter}
                        onChange={(e) => setRow(i, { remark: e.target.value })}
                        style={{ ...inputStyle, width: 110 }}>
                  {/* PAID_LEAVE is never offered — leave is granted on the
                      Worker Leave screen, which also moves the man to Head
                      Office. It is listed only when the day already carries
                      it, so a pre-marked leave day reads correctly instead of
                      showing blank (owner 2026-08-20). */}
                  {(row.remark === "PAID_LEAVE"
                    ? ["PAID_LEAVE", ...remarkOptions]
                    : remarkOptions).map((r) => <option key={r}>{r}</option>)}
                </select>
              </td>
              {grid?.has_devices && (
                <td style={{ padding: "3px 6px", fontSize: 11.5,
                             lineHeight: 1.35 }}>
                  {row.device ? (<>
                    <span style={{ fontWeight: 600 }}>
                      {row.device.first}
                      {row.device.last ? `–${row.device.last}` : ""}</span>
                    {row.device.flags.length > 0 && (
                      <div style={{ color:
                        row.device.flags.includes("REST_DAY")
                        || row.device.flags.includes("NO_OUT")
                          ? "#b35900" : "#5a6b78" }}>
                        {row.device.flags.map((f) => ({
                          NO_OUT: "no punch-out", SHORT: "short day",
                          LATE: "late",
                          OT: `OT ${row.device.proposal?.ot_requested}h`,
                          REST_DAY: "rest day — you decide",
                        }[f] || f)).join(" · ")}
                      </div>)}
                  </>) : <span style={{ color: "#9aa8b3" }}>—</span>}
                </td>)}
              {sub ? (
                <td style={{ padding: 3, whiteSpace: "nowrap" }} colSpan={2}>
                  <input type="number" min="0" step="0.5"
                         value={row.sub_extra_hours ?? 0}
                         disabled={grid?.locked || !canEnter || off}
                         onChange={(e) => setRow(i, { sub_extra_hours:
                                                      e.target.value })}
                         style={{ ...inputStyle, width: 75 }} />
                  <span style={{ marginLeft: 8, fontSize: 11,
                                 color: "#5a6b78" }}>
                    extra hours
                  </span>
                </td>
              ) : (
                <>
                  <td style={{ padding: 3 }}>
                    <input type="number" min="0" step="0.5"
                           value={row.ot_requested ?? 0}
                           disabled={grid?.locked || !canEnter || off}
                           onChange={(e) => setRow(i, { ot_requested:
                                                        e.target.value })}
                           style={{ ...inputStyle, width: 75 }} />
                  </td>
                  <td style={{ ...td, color: row.ot_approved ? "#1a7f37"
                                                             : "#5a6b78" }}>
                    {row.ot_approved ?? "—"}
                  </td>
                </>
              )}
            </tr>
            );
          })}
          {rows.length === 0 && (
            <tr><td style={td} colSpan={8}>
              No active employees allocated to this site. HO HR allocates
              employees on the Employees page.
            </td></tr>
          )}
        </tbody>
      </table>

      <div style={{ display: "flex", gap: 10, marginTop: 14,
                    flexWrap: "wrap" }}>
        {canEnter && !grid?.locked && rows.length > 0 && (
          <button onClick={save} disabled={busy} style={buttonStyle}>
            Save day
          </button>
        )}
        {isPm && !grid?.locked && (
          <>
            <button onClick={approveAllOt} style={ghostButton}>
              Approve all requested OT
            </button>
            <button onClick={lockMonth}
                    style={{ ...ghostButton, color: "#b35900" }}>
              🔒 Sign off &amp; lock month
            </button>
          </>
        )}
      </div>
    </section>
  );
}

const CODE_STYLE = {
  P: { bg: "#e7f5ec", c: "#1a7f37" }, F: { bg: "#e5eefb", c: "#2b5fa6" },
  A: { bg: "#fdecea", c: "#c0392b" }, L: { bg: "#fff5e6", c: "#b35900" },
  S: { bg: "#fff5e6", c: "#b35900" }, "½": { bg: "#f0f0f0", c: "#5a6b78" },
};

function Register({ site, canEnter, onOpenDay }) {
  const nowD = new Date();
  const [year, setYear] = useState(nowD.getFullYear());
  const [month, setMonth] = useState(nowD.getMonth() + 1);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const isPastMonth = year < nowD.getFullYear() ||
    (year === nowD.getFullYear() && month < nowD.getMonth() + 1);
  const isCurrentMonth = year === nowD.getFullYear() &&
    month === nowD.getMonth() + 1;
  const dayOpen = (dn) => canEnter && onOpenDay &&
    (isPastMonth || (isCurrentMonth && dn <= (data?.today || 0)));
  const dateStr = (dn) => `${year}-${String(month).padStart(2, "0")}-`
    + `${String(dn).padStart(2, "0")}`;

  useEffect(() => {
    setError(null);
    api(`/attendance/register?site=${site.id}&year=${year}&month=${month}`)
      .then(setData).catch((e) => setError(e.message));
  }, [site.id, year, month]);

  const dcell = { ...td, textAlign: "center", padding: "3px 4px",
                  minWidth: 22, fontSize: 11 };

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center",
                    flexWrap: "wrap" }}>
        <input type="number" value={year}
               onChange={(e) => setYear(+e.target.value)}
               style={{ ...inputStyle, width: 90 }} />
        <select value={month} onChange={(e) => setMonth(+e.target.value)}
                style={{ ...inputStyle, width: 130 }}>
          {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
            <option key={m} value={m}>
              {new Date(2000, m - 1).toLocaleString("en", { month: "long" })}
            </option>
          ))}
        </select>
        {data?.locked && <span style={{ fontSize: 12.5, color: "#1a7f37" }}>
          🔒 Locked</span>}
        <span style={{ fontSize: 11.5, color: "var(--muted)", marginLeft: 8 }}>
          P present · F Friday/rest worked · A absent · L leave (no pay) ·
          PL leave (paid) · S sick · ½ half
        </span>
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      {canEnter && onOpenDay && !data?.locked && (
        <p style={{ fontSize: 12, color: "var(--muted)", margin: "6px 0 0" }}>
          Tip: click any day column below to open that day and enter or fix
          attendance (past days included).</p>
      )}

      {data && (
        <div style={{ overflowX: "auto", marginTop: 10 }}>
          <table style={{ borderCollapse: "collapse", fontSize: 11 }}>
            <thead><tr>
              <th style={{ ...th, position: "sticky", left: 0,
                           background: "#fff" }}>Employee</th>
              {data.days.map((d) => {
                const open = dayOpen(d.day);
                return (
                <th key={d.day}
                    onClick={open ? () => onOpenDay(dateStr(d.day)) : undefined}
                    style={{ ...dcell, fontWeight: 600,
                      background: d.rest ? "#eef4fb"
                        : d.day === data.today ? "#fff8e6" : "#f6f8fa",
                      color: open ? "var(--sp-navy)" : "#3a4750",
                      cursor: open ? "pointer" : "default",
                      textDecoration: open ? "underline" : "none" }}
                    title={open ? `${d.dow} — click to enter attendance`
                      : d.dow}>{d.day}</th>
                );
              })}
              <th style={{ ...th, textAlign: "right" }}>Pr</th>
              <th style={{ ...th, textAlign: "right" }}>Fr</th>
              <th style={{ ...th, textAlign: "right" }}>OT</th>
              <th style={{ ...th, textAlign: "right" }}>Ab</th>
              <th style={{ ...th, textAlign: "right" }}>Lv</th>
            </tr></thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.emp_no}>
                  <td style={{ ...td, whiteSpace: "nowrap", position: "sticky",
                               left: 0, background: "#fff" }}>
                    <b style={{ color: "var(--sp-navy)" }}>{r.emp_no}</b>{" "}
                    {r.full_name}</td>
                  {data.days.map((d) => {
                    // Days before the worker's join date are outside their
                    // engagement — shown hatched, not blank (never counted).
                    const preJoin = r.start_day && d.day < r.start_day;
                    if (preJoin) {
                      return (
                        <td key={d.day} title="before joining"
                            style={{ ...dcell, background: "#eef1f4",
                              color: "#c3ccd3" }}>–</td>
                      );
                    }
                    const c = r.days[String(d.day)] || "";
                    const s = CODE_STYLE[c];
                    return (
                      <td key={d.day} style={{ ...dcell,
                            background: s ? s.bg : (d.rest ? "#f7f9fc" : "#fff"),
                            color: s ? s.c : "#c3ccd3", fontWeight: 600 }}>
                        {c || "·"}</td>
                    );
                  })}
                  <td style={{ ...td, textAlign: "right" }}>{r.present}</td>
                  <td style={{ ...td, textAlign: "right",
                               color: r.fridays ? "#2b5fa6" : "" }}>
                    {r.fridays || ""}</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {Number(r.ot_hours) || ""}</td>
                  <td style={{ ...td, textAlign: "right",
                               color: r.absent ? "#c0392b" : "" }}>
                    {r.absent || ""}</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {(r.leave + r.sick) || ""}</td>
                </tr>
              ))}
              {data.rows.length === 0 && (
                <tr><td style={td} colSpan={data.days.length + 6}>
                  No employees allocated to this site.</td></tr>
              )}
            </tbody>
            <tfoot>
              <tr style={{ fontWeight: 700,
                           borderTop: "2px solid var(--sp-navy)" }}>
                <td style={{ ...td, position: "sticky", left: 0,
                             background: "#fff" }}>Site totals</td>
                <td style={dcell} colSpan={data.days.length} />
                <td style={{ ...td, textAlign: "right" }}>
                  {data.totals.present}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {data.totals.fridays}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {Number(data.totals.ot_hours)}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {data.totals.absent}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {data.totals.leave + data.totals.sick}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}
