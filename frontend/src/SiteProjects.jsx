import { Btn } from "./ui.jsx";

// Which project you are looking at, as a box rather than a bare row of
// chips. The site header is the one part of the page everybody passes
// through, so it is worth reading well (owner 2026-08-30).
function ProjectCard({ p, on, onClick }) {
  const pct = Math.max(0, Math.min(100, p.overall_progress ?? 0));
  return (
    <button onClick={onClick} title={p.title}
            style={{ textAlign: "left", padding: "9px 13px", borderRadius: 10,
                     cursor: "pointer", fontFamily: "inherit", minWidth: 150,
                     border: `1px solid ${on ? "var(--sp-navy)"
                                             : "var(--line)"}`,
                     background: on ? "var(--sp-navy)" : "#fff",
                     color: on ? "#fff" : "var(--sp-navy)" }}>
      <span style={{ display: "block", fontSize: 13, fontWeight: 700 }}>
        {p.code}
      </span>
      <span style={{ display: "block", fontSize: 11.5, marginTop: 1,
                     opacity: .78, whiteSpace: "nowrap", overflow: "hidden",
                     textOverflow: "ellipsis", maxWidth: 170 }}>
        {p.title}
      </span>
      {/* Progress as a bar as well as a number: a row of percentages is read
          one at a time, a row of bars is read at a glance. */}
      <span style={{ display: "block", marginTop: 7, height: 4,
                     borderRadius: 3, overflow: "hidden",
                     background: on ? "rgba(255,255,255,.3)"
                                    : "var(--line)" }}>
        <span style={{ display: "block", height: "100%", width: `${pct}%`,
                       borderRadius: 3,
                       background: on ? "#fff" : "var(--sp-sky, #1B7FB8)" }} />
      </span>
      <span style={{ display: "block", fontSize: 11, marginTop: 3,
                     opacity: .78, fontVariantNumeric: "tabular-nums" }}>
        {pct}% complete
      </span>
    </button>
  );
}

export default function SiteProjects({ projects = [], project, onProject,
                                       onOpenProject, canAdd, onAddProject,
                                       adding }) {
  if (!projects.length && !canAdd) return null;
  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 12,
                  padding: "12px 14px", marginBottom: 16,
                  background: "var(--paper)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                    marginBottom: 10, flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".08em",
                       textTransform: "uppercase", color: "var(--faint)" }}>
          Projects
        </span>
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
          {project ? `Showing ${project.code} only`
                   : projects.length
                     ? "Showing the whole site — pick a project to raise an "
                       + "IR / MAR / SD / MS"
                     : "No projects yet"}
        </span>
        {project && (
          <Btn variant="secondary" onClick={onOpenProject}
               style={{ marginLeft: "auto", padding: "5px 12px",
                        fontSize: 13 }}>
            Open {project.code} →</Btn>
        )}
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {projects.length > 0 && (
          // An explicit way back to the whole site. Un-picking the selected
          // project by clicking it a second time was the only way out, and
          // nothing on screen said so.
          <button onClick={() => onProject(null)}
                  style={{ padding: "9px 15px", borderRadius: 10,
                           cursor: "pointer", fontFamily: "inherit",
                           fontSize: 13, fontWeight: 600, minWidth: 96,
                           border: `1px solid ${!project ? "var(--sp-navy)"
                                                         : "var(--line)"}`,
                           background: !project ? "var(--sp-navy)" : "#fff",
                           color: !project ? "#fff" : "var(--sp-navy)" }}>
            All projects
          </button>
        )}
        {projects.map((p) => (
          <ProjectCard key={p.id} p={p} on={project?.id === p.id}
                       onClick={() => onProject(
                         project?.id === p.id ? null : p)} />
        ))}
        {canAdd && !adding && (
          <button onClick={onAddProject}
                  style={{ padding: "9px 15px", borderRadius: 10,
                           cursor: "pointer", fontFamily: "inherit",
                           fontSize: 13, fontWeight: 600, minWidth: 96,
                           border: "1px dashed var(--line)",
                           background: "transparent",
                           color: "var(--muted)" }}>
            + Project
          </button>
        )}
      </div>
    </div>
  );
}
