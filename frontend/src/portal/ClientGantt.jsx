import { useEffect, useRef } from "react";
import Gantt from "frappe-gantt";
// package exports don't expose the css subpath — reach it relatively
import "../../node_modules/frappe-gantt/dist/frappe-gantt.css";

// Read-only Frappe Gantt for the client portal: the project programme with
// per-activity % complete. Clients can never edit — no API, no drag handlers.
export default function ClientGantt({ activities }) {
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
        custom_class: a.is_milestone ? "sp-ms"
          : a.indent === 0 ? "sp-sum" : "",
      }));
    ref.current.innerHTML = "";
    if (!tasks.length) return;
    const gantt = new Gantt(ref.current, tasks, {
      view_mode: "Week",
      readonly: true,            // clients can't drag / resize / edit
      readonly_progress: true,
      popup_on: "hover",
      column_width: 62,          // wider weeks so labels are legible
      bar_height: 26,
      padding: 20,
    });
    // Frappe scrolls to "today" by default, which hides earlier activities on
    // a programme that started in the past — start at the beginning instead.
    requestAnimationFrame(() => {
      const c = ref.current && ref.current.querySelector(".gantt-container");
      if (c) c.scrollLeft = 0;
    });
    return () => { gantt?.destroy?.(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(activities.map((a) =>
        [a.id, a.start, a.finish, a.progress, a.predecessors]))]);

  return (
    <div>
      <style>{`
        .gantt .bar { fill: #cddde4; }
        .gantt .bar-progress { fill: var(--accent); }
        .gantt .sp-sum .bar { fill: var(--ink); }
        .gantt .sp-ms .bar { fill: var(--warn); }
        .gantt .bar-label { fill: #fff; font-size: 12px; }
        .gantt .bar-label.big { fill: var(--ink); font-size: 12px; }
        .gantt-container { border: 1px solid var(--line); border-radius: 10px;
          background: var(--card); }
        .gantt .grid-header { fill: var(--line-2); }
        .gantt .tick { stroke: var(--line); }
        /* read-only: no move cursor, no drag handles */
        .gantt .bar-wrapper, .gantt .bar { cursor: default; }
        .gantt .handle { display: none; }
      `}</style>
      <div ref={ref} style={{ overflowX: "auto" }} />
    </div>
  );
}
