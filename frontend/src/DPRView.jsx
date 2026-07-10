import { useEffect, useState } from "react";
import { api } from "./api.js";
import { SectionTitle, StatusChip, buttonStyle, card, ghostButton, td, th }
  from "./ui.jsx";

export default function DPRView({ doc: initial, me, onClose, onChanged, onEdit }) {
  const [doc, setDoc] = useState(initial);
  const [error, setError] = useState(null);
  const [categories, setCategories] = useState([]);
  const p = doc.payload || {};

  useEffect(() => {
    api("/manpower-categories").then((all) =>
      setCategories(all.filter((c) => c.list_type === "DPR")))
      .catch(() => {});
  }, []);

  // Manpower resolved to category names; zero counts hidden; grouped/ordered
  const catById = Object.fromEntries(categories.map((c) => [String(c.id), c]));
  const manpowerRows = Object.entries(p.manpower || {})
    .map(([id, n]) => ({ cat: catById[id], count: +n || 0 }))
    .filter((r) => r.count > 0)
    .sort((a, b) => (a.cat?.grp || "").localeCompare(b.cat?.grp || "")
                    || (a.cat?.sort_order || 0) - (b.cat?.sort_order || 0));
  const manpowerTotal = manpowerRows.reduce((s, r) => s + r.count, 0);

  async function act(action, body) {
    setError(null);
    try {
      const fresh = await api(`/documents/${doc.ref}/actions/${action}`,
                              { method: "POST", body });
      setDoc(fresh);
      onChanged?.();
    } catch (e) {
      setError(e.message);
    }
  }

  const photos = (doc.attachments || []).filter((a) => a.kind === "PHOTO");
  const pdfs = (doc.attachments || []).filter((a) => a.kind === "GENERATED_PDF");
  const canVerify = doc.status === "ISSUED" &&
    (me.role === "PM" || me.role === "ADMIN") && !doc.is_void;
  const canEdit = doc.status === "DRAFT" && !doc.is_void;
  const canVoid = !doc.is_void && (me.role === "PM" || me.role === "ADMIN");

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
          {doc.ref}{" "}
          <StatusChip status={doc.is_void ? "VOID" : doc.status} />
        </h2>
        <button onClick={onClose} style={ghostButton}>Close</button>
      </div>
      <p style={{ color: "#5a6b78", fontSize: 13, margin: "6px 0 0" }}>
        {doc.site_name} · {doc.doc_date} · prepared by {doc.created_by_name}
        {doc.is_void && ` · VOID: ${doc.void_reason}`}
      </p>

      <div style={{ display: "flex", gap: 10, margin: "14px 0" }}>
        {canEdit && <button onClick={() => onEdit(doc)} style={buttonStyle}>
          Continue editing</button>}
        {canVerify && <button onClick={() => act("verify")} style={buttonStyle}>
          Verify (PM)</button>}
        {canVoid && (
          <button
            onClick={() => {
              const reason = window.prompt("Void reason (required):");
              if (reason) act("void", { reason });
            }}
            style={{ ...ghostButton, color: "#c0392b" }}
          >
            Void
          </button>
        )}
        {pdfs.map((f) => (
          <a key={f.id} href={f.url} target="_blank" rel="noreferrer"
             style={{ ...ghostButton, textDecoration: "none",
                      display: "inline-block" }}>
            PDF — {f.file_name}
          </a>
        ))}
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <tbody>
          <tr>
            <td style={td}>Weather: {p.weather_am || "—"} / {p.weather_pm || "—"}</td>
            <td style={td}>Working hours: {p.working_hours || "—"}</td>
            <td style={td}>Time lost: {p.work_time_lost || "0"} h</td>
          </tr>
        </tbody>
      </table>

      {p.work_done?.length > 0 && (
        <>
          <SectionTitle>1. Work Done Today</SectionTitle>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>Project</th>
              <th style={th}>Activity / Milestone</th>
              <th style={th}>Location</th>
              <th style={th}>Today %</th><th style={th}>To-date %</th>
              <th style={th}>Remarks</th>
            </tr></thead>
            <tbody>
              {p.work_done.map((r, i) => (
                <tr key={i}>
                  <td style={td}>{r.project || "General"}</td>
                  <td style={td}>
                    {r.activity}
                    {r.activity_id && (
                      <span style={{ color: "#1a7f37", fontSize: 11 }}>
                        {" "}◆ programme</span>
                    )}
                  </td>
                  <td style={td}>{r.location}</td>
                  <td style={td}>{r.progress_today ?? ""}</td>
                  <td style={td}>{r.progress_todate ?? r.progress_pct ?? ""}</td>
                  <td style={td}>{r.remarks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {manpowerRows.length > 0 && (
        <>
          <SectionTitle>2. Manpower — total {manpowerTotal}</SectionTitle>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr><th style={th}>Category</th>
              <th style={{ ...th, textAlign: "right" }}>Count</th></tr></thead>
            <tbody>
              {manpowerRows.map((r, i) => (
                <tr key={i}>
                  <td style={td}>{r.cat?.name || "—"}</td>
                  <td style={{ ...td, textAlign: "right" }}>{r.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {p.machinery?.length > 0 && (
        <>
          <SectionTitle>3. Machinery &amp; Equipment in Use</SectionTitle>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr><th style={th}>Item</th><th style={th}>Nos</th>
              <th style={th}>Remarks</th></tr></thead>
            <tbody>
              {p.machinery.map((m, i) => (
                <tr key={i}><td style={td}>{m.item}</td>
                  <td style={td}>{m.nos}</td><td style={td}>{m.remarks}</td></tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {p.materials?.length > 0 && (
        <>
          <SectionTitle>4. Key Materials at Site</SectionTitle>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr><th style={th}>Material</th><th style={th}>Unit</th>
              <th style={th}>Opening</th><th style={th}>Received</th>
              <th style={th}>Consumed</th><th style={th}>Balance</th>
              <th style={th}>Remarks</th></tr></thead>
            <tbody>
              {p.materials.map((m, i) => (
                <tr key={i}><td style={td}>{m.material}</td>
                  <td style={td}>{m.unit}</td><td style={td}>{m.opening}</td>
                  <td style={td}>{m.received}</td><td style={td}>{m.consumed}</td>
                  <td style={td}>{m.balance}</td><td style={td}>{m.remarks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {p.matters_affecting && (
        <>
          <SectionTitle>5. Matters Affecting Progress</SectionTitle>
          <p style={{ fontSize: 13 }}>{p.matters_affecting}</p>
        </>
      )}

      {p.visitors_instructions && (
        <>
          <SectionTitle>6. Visitors / Special Events / Instructions</SectionTitle>
          <p style={{ fontSize: 13 }}>{p.visitors_instructions}</p>
        </>
      )}

      <SectionTitle>7. Safety</SectionTitle>
      <p style={{ fontSize: 13 }}>
        Incident today: <strong>{p.safety?.incident ? "YES" : "No"}</strong>
        {p.safety?.incident && ` — ${p.safety.details}`}
      </p>

      {photos.length > 0 && (
        <>
          <SectionTitle>Progress Photos ({photos.length})</SectionTitle>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
            {photos.map((ph) => (
              <figure key={ph.id} style={{ margin: 0, width: 160 }}>
                <img src={ph.url} alt={ph.caption}
                     style={{ width: "100%", borderRadius: 6,
                              border: "1px solid var(--sp-border)" }} />
                <figcaption style={{ fontSize: 11, color: "#5a6b78" }}>
                  {ph.caption}
                </figcaption>
              </figure>
            ))}
          </div>
        </>
      )}

      {doc.approvals?.length > 0 && (
        <>
          <SectionTitle>Workflow trail</SectionTitle>
          {doc.approvals.map((a) => (
            <p key={a.id} style={{ fontSize: 12, color: "#1a7f37", margin: "4px 0" }}>
              {a.action} — {a.actor_name} ({a.actor_role.replace(/_/g, " ")}) —{" "}
              {new Date(a.acted_at).toLocaleString()}
              {a.comment && ` — "${a.comment}"`}
            </p>
          ))}
        </>
      )}
    </section>
  );
}
