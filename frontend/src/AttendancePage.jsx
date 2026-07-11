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

  const canEnter = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "HO_HR", "ADMIN"]
    .includes(me.role);
  const isPm = ["PM", "HO_HR", "ADMIN"].includes(me.role);

  const load = useCallback(() => {
    setNotice(null);
    api(`/attendance?site=${site.id}&date=${day}`).then((data) => {
      setGrid(data);
      setRows(data.rows.map((r) => ({ ...r, check_in: hhmm(r.check_in),
                                      check_out: hhmm(r.check_out) })));
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
      setNotice(`Saved ${result.saved} row(s)` +
                (result.late_edit ? " (late edit — audited)." : "."));
      load();
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
        <Register site={site} />
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
      {grid?.locked && (
        <p style={{ background: "#fdeceb", borderRadius: 8,
                    padding: "8px 12px", fontSize: 13 }}>
          🔒 This month is signed off and locked. Corrections require an
          HO HR reopen.
        </p>
      )}
      {notice && <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>}
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <table style={{ width: "100%", borderCollapse: "collapse",
                      marginTop: 10 }}>
        <thead><tr>
          <th style={th}>Emp No</th><th style={th}>Name</th>
          <th style={th}>Category</th><th style={th}>In</th>
          <th style={th}>Out</th><th style={th}>Remark</th>
          <th style={th}>OT req (h)</th><th style={th}>OT approved</th>
        </tr></thead>
        <tbody>
          {rows.map((row, i) => {
            const off = row.remark === "OFF";
            return (
            <tr key={row.employee_id}>
              <td style={{ ...td, fontWeight: 600,
                           color: "var(--sp-navy)" }}>{row.emp_no}</td>
              <td style={td}>{row.full_name}</td>
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
                  {remarkOptions.map((r) => <option key={r}>{r}</option>)}
                </select>
              </td>
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

function Register({ site }) {
  const nowD = new Date();
  const [year, setYear] = useState(nowD.getFullYear());
  const [month, setMonth] = useState(nowD.getMonth() + 1);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

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
          P present · F Friday/rest worked · A absent · L leave · S sick ·
          ½ half
        </span>
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {data && (
        <div style={{ overflowX: "auto", marginTop: 10 }}>
          <table style={{ borderCollapse: "collapse", fontSize: 11 }}>
            <thead><tr>
              <th style={{ ...th, position: "sticky", left: 0,
                           background: "#fff" }}>Employee</th>
              {data.days.map((d) => (
                <th key={d.day} style={{ ...dcell, fontWeight: 600,
                      background: d.rest ? "#eef4fb"
                        : d.day === data.today ? "#fff8e6" : "#f6f8fa",
                      color: "#3a4750" }}
                    title={d.dow}>{d.day}</th>
              ))}
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
