import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

const CAN_MANAGE = ["PM", "DIRECTOR", "ADMIN"];

export default function ProgrammePage({ project, me, onClose }) {
  const [activities, setActivities] = useState([]);
  const [detail, setDetail] = useState(project);
  const [paste, setPaste] = useState("");
  const [importing, setImporting] = useState(false);
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
        <button onClick={() => setImporting(true)}
                style={{ ...buttonStyle, margin: "12px 0" }}>
          {activities.length ? "Re-import programme" : "Import programme"}
        </button>
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
        </tr></thead>
        <tbody>
          {activities.map((a) => (
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
            </tr>
          ))}
          {activities.length === 0 && (
            <tr><td style={td} colSpan={5}>
              No programme yet.{canManage &&
                " Import it by pasting from MS Project above."}
            </td></tr>
          )}
        </tbody>
      </table>
    </section>
  );
}
