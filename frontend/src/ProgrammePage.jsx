import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

const CAN_MANAGE = ["PM", "DIRECTOR", "ADMIN"];

export default function ProgrammePage({ project, me, onClose }) {
  const [activities, setActivities] = useState([]);
  const [detail, setDetail] = useState(project);
  const [paste, setPaste] = useState("");
  const [importing, setImporting] = useState(false);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ name: "", indent: 1, duration_days: "",
                                       start: "", finish: "",
                                       is_milestone: false });
  const [editRow, setEditRow] = useState(null); // { id, ...fields }
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);

  const canManage = CAN_MANAGE.includes(me.role);

  const load = useCallback(() => {
    api(`/projects/${project.id}/programme`).then(setActivities);
    api(`/projects/${project.id}`).then(setDetail);
  }, [project.id]);

  useEffect(load, [load]);

  async function doImport() {
    setError(null);
    setNotice(null);
    try {
      const r = await api(`/projects/${project.id}/programme`, {
        method: "POST", body: { paste, replace: true },
      });
      setNotice(`Imported ${r.imported} programme rows.`);
      setPaste("");
      setImporting(false);
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function addActivity() {
    setError(null);
    try {
      await api(`/projects/${project.id}/programme`, {
        method: "POST",
        body: {
          replace: false,
          activities: [{
            name: draft.name, indent: +draft.indent,
            duration_days: draft.duration_days === ""
              ? null : +draft.duration_days,
            start: draft.start || null, finish: draft.finish || null,
            is_milestone: draft.is_milestone,
          }],
        },
      });
      setDraft({ name: "", indent: draft.indent, duration_days: "",
                 start: "", finish: "", is_milestone: false });
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function saveRow() {
    setError(null);
    try {
      const { id, ...fields } = editRow;
      await api(`/programme-activities/${id}`, {
        method: "PATCH",
        body: { ...fields,
                duration_days: fields.duration_days === ""
                  ? null : +fields.duration_days,
                start: fields.start || null,
                finish: fields.finish || null },
      });
      setEditRow(null);
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function removeRow(a) {
    if (!window.confirm(`Delete "${a.name}" from the programme?`)) return;
    setError(null);
    try {
      await api(`/programme-activities/${a.id}`, { method: "DELETE" });
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
          {detail.code} — {detail.title}
        </h2>
        <button onClick={onClose} style={ghostButton}>← Back</button>
      </div>
      <p style={{ fontSize: 13, color: "#5a6b78", margin: "6px 0 0" }}>
        Programme: {activities.length} activities ·
        overall progress <strong>{detail.overall_progress}%</strong>
        {detail.start_date && ` · ${detail.start_date} → `}
        {detail.planned_completion || ""}
      </p>

      {notice && <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>}
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {canManage && !importing && (
        <div style={{ display: "flex", gap: 8, margin: "12px 0" }}>
          <button onClick={() => setAdding(!adding)} style={buttonStyle}>
            + Add activity
          </button>
          <button onClick={() => setImporting(true)} style={ghostButton}>
            {activities.length ? "Re-import from MS Project"
                               : "Import from MS Project (paste)"}
          </button>
        </div>
      )}

      {adding && canManage && (
        <div style={{ border: "1px dashed var(--sp-border)", borderRadius: 8,
                      padding: 14, margin: "0 0 12px",
                      display: "flex", gap: 8, flexWrap: "wrap",
                      alignItems: "center" }}>
          <input placeholder="Activity / milestone name" value={draft.name}
                 onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                 style={{ ...inputStyle, flex: 2, minWidth: 220 }} />
          <select value={draft.indent} title="Outline level"
                  onChange={(e) => setDraft({ ...draft,
                                              indent: e.target.value })}
                  style={{ ...inputStyle, width: 110 }}>
            <option value={0}>Heading</option>
            <option value={1}>Level 1</option>
            <option value={2}>Level 2</option>
            <option value={3}>Level 3</option>
          </select>
          <input type="number" min="0" placeholder="Days"
                 value={draft.duration_days} title="Duration (days)"
                 onChange={(e) => setDraft({ ...draft,
                                             duration_days: e.target.value })}
                 style={{ ...inputStyle, width: 75 }} />
          <input type="date" value={draft.start} title="Start"
                 onChange={(e) => setDraft({ ...draft, start: e.target.value })}
                 style={{ ...inputStyle, width: 140 }} />
          <input type="date" value={draft.finish} title="Finish"
                 onChange={(e) => setDraft({ ...draft,
                                             finish: e.target.value })}
                 style={{ ...inputStyle, width: 140 }} />
          <label style={{ fontSize: 13 }}>
            <input type="checkbox" checked={draft.is_milestone}
                   onChange={(e) => setDraft({ ...draft,
                                               is_milestone:
                                               e.target.checked })} />
            {" "}Milestone
          </label>
          <button onClick={addActivity} disabled={!draft.name.trim()}
                  style={buttonStyle}>
            Add
          </button>
          <span style={{ fontSize: 12, color: "#5a6b78", width: "100%" }}>
            Rows are added to the end of the programme in entry order —
            enter them top-down like the printed programme.
          </span>
        </div>
      )}
      {importing && (
        <div style={{ border: "1px dashed var(--sp-border)", borderRadius: 8,
                      padding: 14, margin: "12px 0" }}>
          <p style={{ fontSize: 13, margin: "0 0 8px" }}>
            In MS Project, select the rows (ID, Task Name, Duration, Start,
            Finish), copy, and paste here. Indentation and 0-day milestones
            are detected automatically.
          </p>
          <textarea value={paste} onChange={(e) => setPaste(e.target.value)}
                    rows={10} placeholder={"1\tPROJECT NAME\t233 days\t"
                      + "Fri 4/17/26\tSat 12/5/26\n…"}
                    style={{ ...inputStyle, fontFamily: "monospace",
                             resize: "vertical" }} />
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button onClick={doImport} disabled={!paste.trim()}
                    style={buttonStyle}>
              Import {activities.length ? "(replaces current programme)" : ""}
            </button>
            <button onClick={() => setImporting(false)} style={ghostButton}>
              Cancel</button>
          </div>
        </div>
      )}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={th}>Activity</th>
          <th style={{ ...th, width: 80 }}>Duration</th>
          <th style={{ ...th, width: 95 }}>Start</th>
          <th style={{ ...th, width: 95 }}>Finish</th>
          <th style={{ ...th, width: 210 }}>Progress</th>
          {canManage && <th style={{ ...th, width: 70 }} />}
        </tr></thead>
        <tbody>
          {activities.map((a) => editRow?.id === a.id ? (
            <tr key={a.id} style={{ background: "#fff8e6" }}>
              <td style={{ padding: 4 }} colSpan={4}>
                <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <input value={editRow.name}
                         onChange={(e) => setEditRow({ ...editRow,
                                                       name: e.target.value })}
                         style={{ ...inputStyle, flex: 2, minWidth: 200 }} />
                  <input type="number" min="0" value={editRow.duration_days ?? ""}
                         title="Duration (days)"
                         onChange={(e) => setEditRow({ ...editRow,
                           duration_days: e.target.value })}
                         style={{ ...inputStyle, width: 70 }} />
                  <input type="date" value={editRow.start || ""}
                         onChange={(e) => setEditRow({ ...editRow,
                                                       start: e.target.value })}
                         style={{ ...inputStyle, width: 135 }} />
                  <input type="date" value={editRow.finish || ""}
                         onChange={(e) => setEditRow({ ...editRow,
                                                       finish: e.target.value })}
                         style={{ ...inputStyle, width: 135 }} />
                </span>
              </td>
              <td style={{ padding: 4 }}>
                <input type="number" min="0" max="100"
                       value={editRow.progress}
                       title="Progress % (manual correction — audited)"
                       onChange={(e) => setEditRow({ ...editRow,
                                                     progress: e.target.value })}
                       style={{ ...inputStyle, width: 75 }} />
              </td>
              <td style={{ padding: 4, whiteSpace: "nowrap" }}>
                <button onClick={saveRow}
                        style={{ ...buttonStyle, padding: "3px 10px",
                                 fontSize: 12 }}>Save</button>{" "}
                <button onClick={() => setEditRow(null)}
                        style={{ ...ghostButton, padding: "3px 8px",
                                 fontSize: 12 }}>×</button>
              </td>
            </tr>
          ) : (
            <tr key={a.id}
                style={a.indent === 0 ? { background: "#f0f3f6" } : {}}>
              <td style={{ ...td, paddingLeft: 8 + a.indent * 18,
                           fontWeight: a.indent <= 1 ? 600 : 400 }}>
                {a.is_milestone && "◆ "}{a.name}
              </td>
              <td style={td}>
                {a.duration_days != null ? `${a.duration_days} d` : ""}</td>
              <td style={td}>{a.start || ""}</td>
              <td style={td}>{a.finish || ""}</td>
              <td style={td}>
                {!a.is_milestone && (
                  <span style={{ display: "flex", alignItems: "center",
                                 gap: 8 }}>
                    <span style={{ flex: 1, height: 10, borderRadius: 5,
                                   background: "#e6edf3", overflow: "hidden" }}>
                      <span style={{ display: "block", height: "100%",
                                     width: `${a.progress}%`,
                                     background: +a.progress >= 100
                                       ? "#1a7f37" : "var(--sp-sky)" }} />
                    </span>
                    <span style={{ fontSize: 12, width: 44,
                                   textAlign: "right" }}>
                      {Number(a.progress)}%</span>
                  </span>
                )}
                {a.is_milestone && (
                  <span style={{ fontSize: 12,
                                 color: +a.progress >= 100 ? "#1a7f37"
                                                           : "#5a6b78" }}>
                    {+a.progress >= 100 ? "✓ achieved" : "pending"}
                  </span>
                )}
              </td>
              {canManage && (
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  <button onClick={() => setEditRow({ id: a.id, name: a.name,
                            duration_days: a.duration_days, start: a.start,
                            finish: a.finish, progress: a.progress })}
                          title="Edit"
                          style={{ ...ghostButton, padding: "2px 8px",
                                   fontSize: 12 }}>✎</button>{" "}
                  <button onClick={() => removeRow(a)} title="Delete"
                          style={{ ...ghostButton, padding: "2px 8px",
                                   fontSize: 12, color: "#c0392b" }}>×</button>
                </td>
              )}
            </tr>
          ))}
          {activities.length === 0 && (
            <tr><td style={td} colSpan={canManage ? 6 : 5}>
              No programme yet.{canManage &&
                " Add activities manually or paste from MS Project above."}
            </td></tr>
          )}
        </tbody>
      </table>
    </section>
  );
}
