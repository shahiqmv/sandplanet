import { useEffect, useRef } from "react";
import Gantt from "frappe-gantt";
// the package's exports map doesn't expose the css subpath — reach it
// relatively
import "../node_modules/frappe-gantt/dist/frappe-gantt.css";
import { api } from "./api.js";

// Frappe Gantt wrapper (Phase A of the project workspace). Bars are the
// programme activities; dragging a bar reschedules it (PATCH — audited
// like any manual programme edit). Progress comes from issued DPRs, so
// the fill is read-only here.

const iso = (d) => d.toISOString().slice(0, 10);

export default function GanttChart({ activities, canManage, onChanged }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!ref.current) return;
    const tasks = activities
      .filter((a) => a.start && (a.finish || a.is_milestone))
      .map((a) => ({
        id: String(a.id),
        name: (a.is_milestone ? "◆ " : "") + a.name,
        start: a.start,
        end: a.finish || a.start,
        progress: Number(a.progress) || 0,
        dependencies: a.predecessors || "",
        custom_class: a.is_milestone ? "sp-milestone"
          : a.indent === 0 ? "sp-summary" : "",
      }));
    ref.current.innerHTML = "";
    if (!tasks.length) return;
    const gantt = new Gantt(ref.current, tasks, {
      view_mode: "Week",
      readonly_progress: true,
      readonly: !canManage,
      popup_on: "hover",
      on_date_change: async (task, start, end) => {
        try {
          await api(`/programme-activities/${task.id}`, {
            method: "PATCH",
            body: { start: iso(start), finish: iso(end) },
          });
          onChanged?.();
        } catch {
          onChanged?.();  // reload restores the true dates
        }
      },
    });
    return () => { gantt?.destroy?.(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(activities.map((a) =>
        [a.id, a.start, a.finish, a.progress, a.predecessors])), canManage]);

  return (
    <div>
      <style>{`
        .gantt .bar-progress { fill: var(--sky); }
        .gantt .sp-summary .bar { fill: var(--navy); }
        .gantt .sp-milestone .bar { fill: var(--amber-fg); }
        .gantt-container { border: 1px solid var(--line); border-radius: 8px; }
      `}</style>
      <div ref={ref} style={{ overflowX: "auto" }} />
    </div>
  );
}
