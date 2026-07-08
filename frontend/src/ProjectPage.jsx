import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import ProgrammePage from "./ProgrammePage.jsx";
import { Chip, Eyebrow, RefStamp, Stat, StatusChip, card, ghostButton, td,
         th } from "./ui.jsx";

// Dedicated project workspace (owner, Phase A): a project has many
// components — programme, documents, and later manpower plan, BOM
// (built by the QS from the BOQ), budget and tender. Overview +
// Programme + Documents now; the other tabs are reserved slots.

const TABS = [
  ["overview", "Overview", true],
  ["programme", "Programme", true],
  ["manpower", "Manpower plan", true],
  ["documents", "Documents", true],
  ["bom", "BOM · Phase B", false],
  ["budget", "Budget · later", false],
  ["tender", "Tender · later", false],
];

const money = (v) => v == null ? null
  : Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });

export default function ProjectPage({ projectId, me, onClose, onOpenDoc }) {
  const [project, setProject] = useState(null);
  const [tab, setTab] = useState("overview");
  const [docs, setDocs] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api(`/projects/${projectId}`).then(setProject)
      .catch((e) => setError(e.message));
  }, [projectId]);
  useEffect(load, [load]);

  useEffect(() => {
    if (tab === "documents") {
      api(`/projects/${projectId}/documents`).then(setDocs)
        .catch((e) => setError(e.message));
    }
  }, [tab, projectId]);

  if (error) return <section style={card}>{error}</section>;
  if (!project) return <section style={card}>Loading…</section>;

  const elapsed = (() => {
    if (!project.start_date || !project.planned_completion) return null;
    const s = new Date(project.start_date).getTime();
    const f = new Date(project.planned_completion).getTime();
    if (f <= s) return null;
    return Math.min(Math.max(Math.round(100 * (Date.now() - s) / (f - s)),
                             0), 100);
  })();
  const behind = elapsed != null &&
    Number(project.overall_progress) < elapsed - 10;

  return (
    <>
      <section style={{ ...card, paddingBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                      flexWrap: "wrap" }}>
          <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 18 }}>
            <RefStamp>{project.code}</RefStamp>{" "}
            {project.title}
          </h2>
          <StatusChip status={project.status} />
          <span style={{ fontSize: 13, color: "var(--muted)" }}>
            {project.site_code}</span>
          <a href={`/api/v1/projects/${project.id}/programme.pdf`}
             target="_blank" rel="noreferrer"
             title="The award package: programme Gantt + activity table +
manpower histogram, on the letterhead — send to the client"
             style={{ marginLeft: "auto", fontSize: 13,
                      color: "var(--navy)", fontWeight: 600 }}>
            ⬇ Programme PDF
          </a>
          <button onClick={onClose} style={ghostButton}>← Back</button>
        </div>
        <div style={{ display: "flex", gap: 6, marginTop: 14,
                      flexWrap: "wrap" }}>
          {TABS.map(([key, label, enabled]) => (
            <button key={key} disabled={!enabled}
                    onClick={() => enabled && setTab(key)}
                    title={enabled ? "" : "Reserved — coming in a later phase"}
                    style={{
                      ...ghostButton, padding: "4px 14px", fontSize: 13,
                      opacity: enabled ? 1 : 0.45,
                      cursor: enabled ? "pointer" : "default",
                      background: tab === key ? "var(--navy)" : "#fff",
                      color: tab === key ? "#fff" : "var(--navy)",
                    }}>
              {label}
            </button>
          ))}
        </div>
      </section>

      {tab === "overview" && (
        <>
          <section style={{ ...card, display: "flex", gap: 18,
                            flexWrap: "wrap" }}>
            <Stat label="Programme progress"
                  value={`${project.overall_progress}%`}
                  tone={behind ? "alert" : "ok"}
                  context={elapsed == null ? "no dates set"
                    : behind
                      ? `behind — ${elapsed}% of time elapsed`
                      : `${elapsed}% of time elapsed`} />
            <Stat label="Activities" value={project.activity_count}
                  tone="info" context="in the programme" />
            <Stat label="Manpower (last DPR)"
                  value={project.latest_manpower ?? "—"} tone="info"
                  context="reported at site" />
            {money(project.contract_value) && (
              <Stat label="Contract value"
                    value={money(project.contract_value)} tone="info"
                    context="MVR" />
            )}
          </section>
          <section style={card}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <tbody>
                {[["Project PM", project.pm_name || "—"],
                  ["LOA date", project.loa_date || "—"],
                  ["Start date", project.start_date || "—"],
                  ["Planned finish", project.planned_completion || "—"],
                  ["Actual completion", project.actual_completion || "—"],
                  ["BOQ ref", project.boq_ref || "—"],
                  ["Scope", project.scope || "—"],
                  ["Manpower summary", project.manpower_summary || "—"],
                ].map(([k, v]) => (
                  <tr key={k}>
                    <td style={{ ...td, width: 170, color: "var(--muted)",
                                 fontWeight: 600 }}>{k}</td>
                    <td style={td}>{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p style={{ fontSize: 12, color: "var(--faint)",
                        margin: "10px 0 0" }}>
              Project details are edited under Admin → Site Setup.
            </p>
          </section>
        </>
      )}

      {tab === "programme" && (
        <section style={card}>
          <ProgrammePage project={project} me={me} embedded />
        </section>
      )}

      {tab === "manpower" && (
        <ManpowerPlanTab project={project} me={me} onSaved={load} />
      )}

      {tab === "documents" && (
        <section style={card}>
          {!docs ? "Loading…" : (
            <>
              <Eyebrow meta={String(docs.project_docs.length)}>
                Project documents
              </Eyebrow>
              <DocTable rows={docs.project_docs} onOpenDoc={onOpenDoc}
                        empty="No inspection requests or material approvals
                               yet for this project." />
              <Eyebrow meta={String(docs.daily_docs.length)}>
                Daily reports carrying this project's rows
              </Eyebrow>
              <DocTable rows={docs.daily_docs} onOpenDoc={onOpenDoc}
                        empty="No DPR/TWS rows tagged to this project yet." />
            </>
          )}
        </section>
      )}
    </>
  );
}

// Planned manpower per month — feeds the histogram sent to the client
// with the programme upon award (owner).
function ManpowerPlanTab({ project, me, onSaved }) {
  const [rows, setRows] = useState(
    project.manpower_plan?.length ? project.manpower_plan
      : [{ month: "", workers: "" }]);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);
  const canManage = ["PM", "DIRECTOR", "ADMIN"].includes(me.role);
  const clean = rows.filter((r) => r.month && parseInt(r.workers, 10) > 0);
  const peak = Math.max(...clean.map((r) => parseInt(r.workers, 10)), 1);

  async function save() {
    setError(null);
    try {
      await api(`/projects/${project.id}`, {
        method: "PATCH",
        body: { manpower_plan: clean.map((r) => ({
          month: r.month, workers: parseInt(r.workers, 10) })) },
      });
      setNotice("Manpower plan saved — it prints on the Programme PDF.");
      onSaved();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <section style={card}>
      <Eyebrow meta={clean.length ? `peak ${peak}` : null}>
        Planned manpower by month
      </Eyebrow>
      {clean.length > 0 && (
        <div style={{ display: "flex", alignItems: "flex-end", gap: 6,
                      height: 120, borderBottom: "1px solid var(--line)",
                      borderLeft: "1px solid var(--line)",
                      padding: "0 6px", maxWidth: 640, marginBottom: 4 }}>
          {clean.map((r, i) => (
            <div key={i} style={{ flex: 1, display: "flex",
                                  flexDirection: "column",
                                  justifyContent: "flex-end",
                                  textAlign: "center", height: "100%" }}>
              <div style={{ fontSize: 11, fontWeight: 700,
                            color: "var(--navy)" }}>{r.workers}</div>
              <div style={{ background: "var(--sky)",
                            borderRadius: "3px 3px 0 0",
                            height: `${(100 * r.workers) / peak}%` }} />
            </div>
          ))}
        </div>
      )}
      {clean.length > 0 && (
        <div style={{ display: "flex", gap: 6, maxWidth: 640,
                      padding: "0 6px", marginBottom: 14 }}>
          {clean.map((r, i) => (
            <span key={i} style={{ flex: 1, textAlign: "center",
                                   fontSize: 10.5,
                                   color: "var(--faint)" }}>{r.month}</span>
          ))}
        </div>
      )}
      {canManage ? (
        <>
          {rows.map((r, i) => (
            <div key={i} style={{ display: "flex", gap: 8,
                                  alignItems: "center", marginBottom: 6 }}>
              <input type="month" value={r.month}
                     onChange={(e) => setRows(rows.map((x, j) =>
                       j === i ? { ...x, month: e.target.value } : x))}
                     style={{ padding: "6px 8px", borderRadius: 8,
                              border: "1px solid #BFD6E6" }} />
              <input type="number" min="0" value={r.workers}
                     placeholder="workers"
                     onChange={(e) => setRows(rows.map((x, j) =>
                       j === i ? { ...x, workers: e.target.value } : x))}
                     style={{ width: 100, padding: "6px 8px",
                              borderRadius: 8,
                              border: "1px solid #BFD6E6" }} />
              <button onClick={() => setRows(rows.filter((_, j) => j !== i))}
                      style={{ ...ghostButton, padding: "2px 8px",
                               color: "var(--red-fg)" }}>×</button>
            </div>
          ))}
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button onClick={() => setRows([...rows,
                                            { month: "", workers: "" }])}
                    style={{ ...ghostButton, padding: "4px 12px" }}>
              + Add month
            </button>
            <button onClick={save} disabled={!clean.length}
                    style={{ background: "var(--navy)", color: "#fff",
                             border: "none", borderRadius: 8,
                             padding: "6px 16px", fontWeight: 600,
                             cursor: "pointer" }}>
              Save plan
            </button>
          </div>
        </>
      ) : (
        !clean.length && (
          <p style={{ fontSize: 13, color: "var(--muted)" }}>
            No manpower plan yet — the PM enters the planned workers per
            month here.</p>
        )
      )}
      {notice && <p style={{ color: "var(--green-fg)", fontSize: 13 }}>
        {notice}</p>}
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>
        {error}</p>}
    </section>
  );
}

function DocTable({ rows, onOpenDoc, empty }) {
  if (!rows.length) {
    return <p style={{ fontSize: 13, color: "var(--muted)" }}>{empty}</p>;
  }
  return (
    <table style={{ width: "100%", borderCollapse: "collapse",
                    marginBottom: 14 }}>
      <thead><tr>
        <th style={th}>Ref</th><th style={th}>Type</th>
        <th style={th}>Date</th><th style={th}>Status</th>
        <th style={th}>Detail</th>
      </tr></thead>
      <tbody>
        {rows.map((d) => (
          <tr key={d.ref}>
            <td style={{ ...td, width: 130 }}>
              <a href="#" onClick={(e) => { e.preventDefault();
                                            onOpenDoc(d.ref); }}
                 style={{ textDecoration: "none" }}>
                <RefStamp small>{d.ref}</RefStamp>
              </a>
            </td>
            <td style={td}>{d.doc_type}</td>
            <td style={td}>{d.doc_date}</td>
            <td style={td}>
              {d.status === "VOID" ? <Chip tone="alert">VOID</Chip>
                                   : <StatusChip status={d.status} />}
            </td>
            <td style={{ ...td, color: "var(--muted)", fontSize: 12 }}>
              {d.detail}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
