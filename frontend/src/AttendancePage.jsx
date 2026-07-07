import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

const REMARKS = ["PRESENT", "HALF_DAY", "ABSENT", "SICK", "LEAVE"];
const hhmm = (value) => (value ? String(value).slice(0, 5) : "");

export default function AttendancePage({ site, me, onClose }) {
  const [day, setDay] = useState(() => new Date().toISOString().slice(0, 10));
  const [grid, setGrid] = useState(null);
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  const canEnter = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "ADMIN"]
    .includes(me.role);
  const isPm = ["PM", "ADMIN"].includes(me.role);

  const load = useCallback(() => {
    setNotice(null);
    api(`/attendance?site=${site.id}&date=${day}`).then((data) => {
      setGrid(data);
      setRows(data.rows.map((r) => ({ ...r, check_in: hhmm(r.check_in),
                                      check_out: hhmm(r.check_out) })));
    }).catch((e) => setError(e.message));
  }, [site.id, day]);

  useEffect(load, [load]);

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
        return setNotice("No saved, unapproved OT requests for this day.");
      }
      await api("/attendance/ot-approve", { method: "POST", body: { ids } });
      setNotice(`OT approved for ${ids.length} row(s).`);
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function lockMonth() {
    const [y, m] = day.split("-");
    if (!window.confirm(`Sign off and LOCK ${y}-${m} for ${site.code}? ` +
                        "Corrections after lock need an HR reopen.")) return;
    setError(null);
    try {
      await api(`/timesheets/${site.id}/${+y}/${+m}/lock`, { method: "POST" });
      setNotice("Month signed off and locked.");
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline", flexWrap: "wrap", gap: 10 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
          Attendance — {site.code}
        </h2>
        <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input type="date" value={day}
                 onChange={(e) => setDay(e.target.value)}
                 style={{ ...inputStyle, width: 150 }} />
          <button onClick={onClose} style={ghostButton}>Close</button>
        </span>
      </div>

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
          {rows.map((row, i) => (
            <tr key={row.employee_id}>
              <td style={{ ...td, fontWeight: 600,
                           color: "var(--sp-navy)" }}>{row.emp_no}</td>
              <td style={td}>{row.full_name}</td>
              <td style={td}>{row.category}</td>
              <td style={{ padding: 3 }}>
                <input type="time" value={row.check_in || ""}
                       disabled={grid?.locked || !canEnter}
                       onChange={(e) => setRow(i, { check_in: e.target.value })}
                       style={{ ...inputStyle, width: 105 }} />
              </td>
              <td style={{ padding: 3 }}>
                <input type="time" value={row.check_out || ""}
                       disabled={grid?.locked || !canEnter}
                       onChange={(e) => setRow(i, { check_out: e.target.value })}
                       style={{ ...inputStyle, width: 105 }} />
              </td>
              <td style={{ padding: 3 }}>
                <select value={row.remark} disabled={grid?.locked || !canEnter}
                        onChange={(e) => setRow(i, { remark: e.target.value })}
                        style={{ ...inputStyle, width: 110 }}>
                  {REMARKS.map((r) => <option key={r}>{r}</option>)}
                </select>
              </td>
              <td style={{ padding: 3 }}>
                <input type="number" min="0" step="0.5"
                       value={row.ot_requested ?? 0}
                       disabled={grid?.locked || !canEnter}
                       onChange={(e) => setRow(i, { ot_requested:
                                                    e.target.value })}
                       style={{ ...inputStyle, width: 75 }} />
              </td>
              <td style={{ ...td, color: row.ot_approved ? "#1a7f37"
                                                         : "#5a6b78" }}>
                {row.ot_approved ?? "—"}
              </td>
            </tr>
          ))}
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
              Approve all requested OT (PM)
            </button>
            <button onClick={lockMonth}
                    style={{ ...ghostButton, color: "#b35900" }}>
              🔒 Sign off &amp; lock month (PM)
            </button>
          </>
        )}
      </div>
    </section>
  );
}
