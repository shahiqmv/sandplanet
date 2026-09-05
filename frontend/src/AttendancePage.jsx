import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import ShiftAllocation from "./ShiftAllocation.jsx";
import { buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";
import OtApprovalPanel from "./OtApprovalPanel.jsx";

const NORMAL_REMARKS = ["PRESENT", "HALF_DAY", "ABSENT", "SICK", "LEAVE"];
const REST_REMARKS = ["OFF", "PRESENT", "HALF_DAY"];
const hhmm = (value) => (value ? String(value).slice(0, 5) : "");
// Compact grid cells — the roster should show as many men as the screen
// allows (owner 2026-08-26).
const gtd = { padding: "3px 8px", fontSize: 13,
              borderTop: "1px solid var(--row-line, #e3ecf2)",
              verticalAlign: "middle" };
const gin = { padding: "4px 6px", fontSize: 13 };

export default function AttendancePage({ site, me, onClose,
                                         initialMode = "day",
                                         initialDay = null }) {
  const [mode, setMode] = useState(initialMode);   // day | register | shifts | ot
  const [day, setDay] = useState(() =>
    initialDay || new Date().toISOString().slice(0, 10));
  const [grid, setGrid] = useState(null);
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  // Click a face to see it big — a thumbnail can only do so much
  // (owner 2026-08-26).
  const [photoView, setPhotoView] = useState(null);

  const canEnter = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "HO_HR", "DIRECTOR",
                    "ADMIN", "PA"].includes(me.role);
  const isPm = ["PM", "HO_HR", "ADMIN", "PA"].includes(me.role);

  const load = useCallback(() => {
    setNotice(null);
    api(`/attendance?site=${site.id}&date=${day}`).then((data) => {
      setGrid(data);
      // Shift sites read best crew by crew: normal-hours staff first, then
      // each shift in start order.
      const order = new Map((data.shifts || []).map((s, ix) => [s.id, ix]));
      data.rows.sort((a, b) => {
        const ka = a.shift_id != null ? order.get(a.shift_id) ?? 99 : -1;
        const kb = b.shift_id != null ? order.get(b.shift_id) ?? 99 : -1;
        return ka - kb || String(a.emp_no).localeCompare(String(b.emp_no));
      });
      setRows(data.rows.map((r) => {
        const row = { ...r, check_in: hhmm(r.check_in),
                      check_out: hhmm(r.check_out) };
        // The gate's proposal fills unsaved rows AUTOMATICALLY — times,
        // remark and OT, zero clicks (owner clarified 2026-08-26: sign-in
        // auto-updates; the earlier read of "only OT" was mine). The clerk
        // adjusts anything wrong and saves; the PM approves OT as always.
        const p = r.device?.proposal;
        if (!r.saved && p) {
          row.check_in = p.check_in || row.check_in;
          row.check_out = p.check_out || row.check_out;
          row.remark = p.remark || row.remark;
          const ot = parseFloat(p.ot_requested) || 0;
          if (ot > 0) {
            if (r.is_subcontract) row.sub_extra_hours = p.ot_requested;
            else row.ot_requested = p.ot_requested;
          }
          row._fromGate = true;
        }
        return row;
      }));
    }).catch((e) => setError(e.message));
  }, [site.id, day]);

  useEffect(() => { if (mode === "day") load(); }, [load, mode]);

  const setRow = (i, patch) =>
    setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const hasShifts = (grid?.shifts || []).length > 0;
  // Moving a man between shifts is an assignment from this day on (history
  // kept, like site transfers) — then the grid re-reads so his defaults and
  // gate judging follow the new shift.
  async function assignShift(row, shiftId) {
    setError(null);
    try {
      await api("/attendance/shift-assign", { method: "POST",
        body: { site: site.id, date: day,
                employee_ids: [row.employee_id], shift_id: shiftId } });
      load();
    } catch (e) { setError(e.message); }
  }

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
                (result.late_edit ? " (late edit — audited)." : ".") +
                (result.ot_approval_withdrawn?.length
                  ? ` OT changed on ${result.ot_approval_withdrawn.length} ` +
                    "row(s) — the earlier approval is withdrawn and the PM " +
                    "must approve again."
                  : ""));
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
        {isPm && (
          <button onClick={() => setMode("ot")}
                  style={mode === "ot" ? buttonStyle : ghostButton}>
            OT approval</button>
        )}
        {(hasShifts || mode === "shifts") && (
          <button onClick={() => setMode("shifts")}
                  style={mode === "shifts" ? buttonStyle : ghostButton}>
            Shift allocation</button>
        )}
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

  if (mode === "shifts") {
    return (
      <section style={card}>
        {header}
        <ShiftAllocation site={site} canEnter={canEnter} />
      </section>
    );
  }

  // OT is approved on its own tab. It sat under the day grid for an
  // afternoon; on a site with a few hundred men that is a long way down
  // (owner 2026-09-03).
  if (mode === "ot") {
    return (
      <section style={card}>
        {header}
        <div style={{ display: "flex", gap: 10, alignItems: "center",
                      margin: "12px 0 4px", flexWrap: "wrap" }}>
          <input type="date" value={day}
                 onChange={(e) => setDay(e.target.value)}
                 style={{ ...inputStyle, width: 140, padding: "4px 8px" }} />
          <span style={{ fontSize: 12, color: "var(--muted)" }}>
            {new Date(day + "T00:00").toLocaleDateString("en",
              { weekday: "long" })}</span>
          {grid?.locked && (
            <span style={{ fontSize: 12.5, color: "#1a7f37" }}>
              🔒 month signed off — nothing to approve</span>
          )}
        </div>
        {error && <p style={{ color: "#a3271b", fontSize: 13 }}>{error}</p>}
        {notice && <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>}
        <OtApprovalPanel site={site} day={day} locked={!!grid?.locked}
                         onChanged={load} onError={setError}
                         onNotice={setNotice} />
      </section>
    );
  }

  return (
    <section style={{ ...card, padding: "14px 18px 18px" }}>
      {/* One compact bar: everything above the roster in two thin lines, so
          the crew list owns the screen (owner 2026-08-26). */}
      <div style={{ display: "flex", gap: 10, alignItems: "center",
                    flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Attendance — {site.code}
        </h2>
        <input type="date" value={day}
               onChange={(e) => setDay(e.target.value)}
               style={{ ...inputStyle, width: 140, padding: "4px 8px" }} />
        {grid && <span style={{ fontSize: 12, color: "var(--muted)" }}>
          {new Date(day + "T00:00").toLocaleDateString("en",
            { weekday: "long" })}</span>}
        <span style={{ marginLeft: "auto", display: "flex", gap: 6,
                       alignItems: "center" }}>
          <button onClick={() => setMode("day")}
                  style={{ ...buttonStyle, padding: "4px 12px",
                           fontSize: 13 }}>Day entry</button>
          <button onClick={() => setMode("register")}
                  style={{ ...ghostButton, padding: "4px 12px",
                           fontSize: 13 }}>Month register</button>
          {isPm && (
            <button onClick={() => setMode("ot")}
                    style={{ ...ghostButton, padding: "4px 12px",
                             fontSize: 13 }}>OT approval</button>
          )}
          {hasShifts && (
            <button onClick={() => setMode("shifts")}
                    style={{ ...ghostButton, padding: "4px 12px",
                             fontSize: 13 }}>Shift allocation</button>
          )}
          <button onClick={onClose}
                  style={{ ...ghostButton, padding: "4px 12px",
                           fontSize: 13 }}>Close</button>
        </span>
      </div>

      {rows.length > 0 && (() => {
        // The day at a glance, before the clerk scrolls 60 rows.
        const n = (f) => rows.filter(f).length;
        const present = n((r) => r.remark === "PRESENT");
        const half = n((r) => r.remark === "HALF_DAY");
        const away = n((r) => ["ABSENT", "SICK", "LEAVE"].includes(r.remark));
        const gate = n((r) => r._fromGate);
        const saved = n((r) => r.saved);
        const ot = rows.reduce((a, r) => a
          + (parseFloat(r.ot_requested) || 0)
          + (parseFloat(r.sub_extra_hours) || 0), 0);
        const chip = (label, value, tone) => (
          <span key={label} style={{ fontSize: 11.5, padding: "2px 10px",
            borderRadius: 999, background: tone === "ok" ? "#e8f3eb"
              : tone === "warn" ? "#f9efe2" : "#eef3f7",
            color: tone === "ok" ? "#1a7f37" : tone === "warn" ? "#8a5b00"
              : "var(--sp-navy)", fontWeight: 600 }}>
            {value} {label}</span>
        );
        return (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap",
                        margin: "8px 0 0", alignItems: "center" }}>
            {chip("on roster", rows.length)}
            {chip("present", present, "ok")}
            {half > 0 && chip("half day", half, "warn")}
            {away > 0 && chip("absent / sick / leave", away, "warn")}
            {grid?.has_devices && chip("filled from gate", gate,
                                       gate > 0 ? "ok" : undefined)}
            {ot > 0 && chip("OT hours", ot % 1 ? ot.toFixed(1) : ot, "warn")}
            <span style={{ fontSize: 12, color: "var(--muted, #5a6b78)" }}>
              {saved === rows.length ? "✓ day saved"
                : `${rows.length - saved} row(s) not saved yet`}</span>
          </div>
        );
      })()}

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
          {/* Name is the flexible column — it absorbs the page's width so
              long names fit; everything else is fixed, and OT-approved is
              just a number (owner 2026-08-26). */}
          {[["Emp No", 78], ["Name", null], ["Category", 118],
            ...(hasShifts ? [["Shift", 114]] : []),
            ["In", 98], ["Out", 98], ["Remark", 118],
            ...(grid?.has_devices ? [["Gate", 150]] : []),
            ["OT / Extra (h)", 78], ["OT approved", 72]].map(([label, w]) => (
            <th key={label}
                style={{ ...th, width: w || undefined, position: "sticky",
                         top: 0, background: "var(--sp-paper, #fff)",
                         zIndex: 2, boxShadow: "0 1.5px 0 var(--sp-sky, #29abe2)" }}>
              {label}</th>
          ))}
        </tr></thead>
        <tbody>
          {rows.map((row, i) => {
            const off = row.remark === "OFF";
            const sub = row.is_subcontract;
            return (
            <tr key={row.employee_id}
                style={{ background: sub ? "#eef5fb"
                           : i % 2 ? "#fafcfd" : undefined }}>
              <td style={{ ...gtd, fontWeight: 600,
                           color: "var(--sp-navy)" }}>{row.emp_no}</td>
              <td style={gtd}>
                {/* photo identity — big crews, similar names (owner
                    2026-08-26) */}
                {row.photo_url
                  ? <img src={row.photo_url} alt=""
                         onClick={() => setPhotoView(row)}
                         title="Click to enlarge"
                         style={{ width: 36, height: 42, objectFit: "cover",
                                  borderRadius: 4, verticalAlign: "middle",
                                  marginRight: 7, cursor: "zoom-in",
                                  border: "1px solid #dde5ea" }} />
                  : <span style={{ display: "inline-grid", width: 36,
                                   height: 42, placeItems: "center",
                                   borderRadius: 4, marginRight: 7,
                                   border: "1px dashed #d5ccb4",
                                   background: "#fbf7ec", fontSize: 12,
                                   verticalAlign: "middle" }}
                          title="No photo — add one on the Workforce page">
                      👤</span>}
                {row.full_name}
                {/* Not on this site's roster for the day — he is listed only
                    because he carries a mark. Mark him OFF to take it back
                    (owner 2026-09-02). */}
                {row.off_roster && (
                  <span title="Not allocated to this site on this day — shown
                               so the mark can be corrected. Mark OFF to
                               remove it."
                        style={{ marginLeft: 6, fontSize: 10.5,
                                 fontWeight: 700, color: "#a3271b",
                                 background: "#fbeae8", borderRadius: 999,
                                 padding: "1px 7px", whiteSpace: "nowrap" }}>
                    not on roster</span>
                )}
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
              <td style={gtd}>{row.category}</td>
              {hasShifts && (
                <td style={{ padding: 3 }}>
                  <select value={row.shift_id || ""}
                          disabled={!canEnter}
                          title="Moves the worker to this shift from this day on (his history is kept)"
                          onChange={(e) => assignShift(row,
                                                       e.target.value || null)}
                          style={{ ...inputStyle, width: 110, fontSize: 12,
                                   padding: "3px 6px" }}>
                    <option value="">site hours</option>
                    {grid.shifts.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name} {s.start}–{s.end}{s.overnight ? " +1d" : ""}
                      </option>
                    ))}
                  </select>
                </td>
              )}
              <td style={{ padding: 3 }}>
                <input type="time" value={row.check_in || ""}
                       disabled={grid?.locked || !canEnter || off}
                       onChange={(e) => setRow(i, { check_in: e.target.value })}
                       title={row._fromGate ? "Filled from the gate punch" : undefined}
                       style={{ ...inputStyle, ...gin, width: 92,
                                background: row._fromGate && !row.saved
                                  ? "#eef8f0" : undefined }} />
              </td>
              <td style={{ padding: 3 }}>
                <input type="time" value={row.check_out || ""}
                       disabled={grid?.locked || !canEnter || off}
                       title={row._fromGate ? "Filled from the gate punch" : undefined}
                       onChange={(e) => setRow(i, { check_out: e.target.value })}
                       style={{ ...inputStyle, ...gin, width: 92 }} />
              </td>
              <td style={{ padding: 3 }}>
                <select value={row.remark} disabled={grid?.locked || !canEnter}
                        onChange={(e) => setRow(i, { remark: e.target.value })}
                        style={{ ...inputStyle, ...gin, width: 110 }}>
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
                         style={{ ...inputStyle, ...gin, width: 75 }} />
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
                           style={{ ...inputStyle, ...gin, width: 75 }} />
                  </td>
                  <td style={{ ...gtd, color: row.ot_approved ? "#1a7f37"
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
      {photoView && (
        <div onClick={() => setPhotoView(null)}
             style={{ position: "fixed", inset: 0,
                      background: "rgba(10,20,30,.55)", display: "flex",
                      alignItems: "center", justifyContent: "center",
                      zIndex: 80, cursor: "zoom-out" }}>
          <div style={{ textAlign: "center" }}>
            <img src={photoView.photo_url} alt={photoView.full_name}
                 style={{ maxWidth: "min(420px, 88vw)",
                          maxHeight: "70vh", borderRadius: 10,
                          border: "3px solid #fff",
                          boxShadow: "0 10px 40px rgba(0,0,0,.4)" }} />
            <div style={{ color: "#fff", fontWeight: 600, marginTop: 10,
                          fontSize: 16, textShadow: "0 1px 4px rgba(0,0,0,.6)" }}>
              {photoView.full_name}
              <span style={{ fontWeight: 400, opacity: 0.85 }}>
                {" "}· {photoView.emp_no}
                {photoView.category ? ` · ${photoView.category}` : ""}</span>
            </div>
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 10, marginTop: 14,
                    flexWrap: "wrap" }}>
        {canEnter && !grid?.locked && rows.length > 0 && (
          <button onClick={save} disabled={busy} style={buttonStyle}>
            Save day
          </button>
        )}
        {isPm && !grid?.locked && (
          <>
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
  // The client's attendance record: any range the user picks, defaulting
  // to the month on screen. Headcount and marks only — no OT (owner
  // 2026-09-03, for housekeeping and food).
  const [range, setRange] = useState({ from: "", to: "" });
  const monthStart = `${year}-${String(month).padStart(2, "0")}-01`;
  const monthEnd = `${year}-${String(month).padStart(2, "0")}-` +
    String(new Date(year, month, 0).getDate()).padStart(2, "0");
  const pdfFrom = range.from || monthStart;
  const pdfTo = range.to || monthEnd;
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
      <div style={{ display: "flex", gap: 8, alignItems: "center",
                    flexWrap: "wrap", marginTop: 8, fontSize: 12.5 }}>
        <span style={{ color: "var(--muted)" }}>Client attendance record</span>
        <input type="date" value={pdfFrom}
               onChange={(e) => setRange({ ...range, from: e.target.value })}
               style={{ ...inputStyle, width: 140, padding: "3px 6px" }} />
        <span style={{ color: "var(--muted)" }}>to</span>
        <input type="date" value={pdfTo}
               onChange={(e) => setRange({ ...range, to: e.target.value })}
               style={{ ...inputStyle, width: 140, padding: "3px 6px" }} />
        <a href={`/api/v1/sites/${site.id}/attendance.pdf?from=${pdfFrom}&to=${pdfTo}`}
           target="_blank" rel="noreferrer"
           title="Headcount and attendance marks for the client — no overtime"
           style={{ ...ghostButton, padding: "3px 10px", fontSize: 12.5,
                    textDecoration: "none", color: "var(--navy)" }}>
          ⬇ PDF for client</a>
        <span style={{ color: "var(--muted)", fontSize: 11.5 }}>
          headcount and marks only — no OT</span>
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
