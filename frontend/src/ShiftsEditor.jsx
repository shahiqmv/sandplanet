import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Shift definitions for one site (owner 2026-08-25). Lives on the Sites page
// site modal (Admin/Director) and on the site dashboard for the site's PM —
// the same editor in both places. Workers are put ON a shift from the
// attendance day grid; this is only the timetable.
const EMPTY = { name: "", start: "07:00", end: "15:00", ot_counts_from: "" };

export default function ShiftsEditor({ siteId, canEdit }) {
  const [shifts, setShifts] = useState(null);
  const [draft, setDraft] = useState(EMPTY);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api(`/sites/${siteId}/shifts`).then(setShifts)
      .catch((e) => setError(e.message));
  }, [siteId]);
  useEffect(load, [load]);

  async function add() {
    setError(null);
    try {
      await api(`/sites/${siteId}/shifts`, { method: "POST", body: draft });
      setDraft(EMPTY);
      load();
    } catch (e) { setError(e.message); }
  }
  async function patch(id, body) {
    setError(null);
    try {
      await api(`/shifts/${id}`, { method: "PATCH", body });
      load();
    } catch (e) { setError(e.message); }
  }

  if (!shifts) return error
    ? <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p> : null;

  return (
    <div>
      {shifts.length === 0 && (
        <p style={{ color: "#5a6b78", fontSize: 12.5, margin: "4px 0" }}>
          No shifts — everyone follows the site's normal working hours.
          Define shifts only for sites that run morning / afternoon / night
          crews.</p>
      )}
      {shifts.length > 0 && (
        <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
          <thead><tr>
            <th style={th}>Shift</th><th style={th}>Start</th>
            <th style={th}>End</th><th style={th}>OT counts from</th>
            <th style={th}>Workers now</th>{canEdit && <th style={th} />}
          </tr></thead>
          <tbody>
            {shifts.map((s) => (
              <tr key={s.id} style={{ opacity: s.is_active ? 1 : 0.5 }}>
                <td style={{ ...td, fontWeight: 600,
                             color: "var(--sp-navy)" }}>{s.name}</td>
                <td style={td}>{s.start}</td>
                <td style={td}>{s.end}
                  {s.overnight && (
                    <span title="Runs past midnight — the day belongs to the date the shift starts"
                          style={{ marginLeft: 4, fontSize: 10.5,
                                   color: "#8a6d00", fontWeight: 600 }}>
                      +1d</span>)}
                </td>
                <td style={td}>{s.ot_counts_from || "at end"}</td>
                <td style={{ ...td, textAlign: "right" }}>{s.workers}</td>
                {canEdit && (
                  <td style={td}>
                    <button onClick={() => patch(s.id,
                                                 { is_active: !s.is_active })}
                            style={{ ...ghostButton, padding: "1px 8px",
                                     fontSize: 11.5 }}>
                      {s.is_active ? "Retire" : "Restore"}</button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {canEdit && (
        <div style={{ display: "flex", gap: 8, marginTop: 8,
                      flexWrap: "wrap", alignItems: "flex-end" }}>
          <label style={{ fontSize: 12 }}>Shift name
            <input placeholder="e.g. Night" value={draft.name}
                   onChange={(e) => setDraft({ ...draft,
                                               name: e.target.value })}
                   style={{ ...inputStyle, width: 130 }} />
          </label>
          <label style={{ fontSize: 12 }}>Start
            <input type="time" value={draft.start}
                   onChange={(e) => setDraft({ ...draft,
                                               start: e.target.value })}
                   style={{ ...inputStyle, width: 105 }} />
          </label>
          <label style={{ fontSize: 12 }}>End
            <input type="time" value={draft.end}
                   onChange={(e) => setDraft({ ...draft,
                                               end: e.target.value })}
                   style={{ ...inputStyle, width: 105 }} />
          </label>
          <label style={{ fontSize: 12 }}
                 title="OT proposed past this time; blank counts from the shift's end">
            OT from
            <input type="time" value={draft.ot_counts_from}
                   onChange={(e) => setDraft({ ...draft,
                                               ot_counts_from: e.target.value })}
                   style={{ ...inputStyle, width: 105 }} />
          </label>
          <button onClick={add} disabled={!draft.name}
                  style={{ ...buttonStyle, padding: "6px 14px" }}>
            Add shift</button>
          <span style={{ fontSize: 11.5, color: "#5a6b78", width: "100%" }}>
            An end at or before the start means the shift runs past midnight
            — that day (and its pay) belongs to the date the shift starts.
            Workers are put on a shift from the attendance day grid.
          </span>
        </div>
      )}
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
    </div>
  );
}
