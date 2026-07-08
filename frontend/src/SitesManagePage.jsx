import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { StatusChip, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

const SITE_FIELDS = [
  ["name", "Site name", "text"],
  ["client_name", "Client name", "text"],
  ["client_address", "Client address", "text"],
  ["client_contact", "Client contact person", "text"],
  ["client_designation", "Designation", "text"],
  ["client_phone", "Client phone", "text"],
  ["client_email", "Client email", "text"],
  ["consultant_name", "Consultant", "text"],
  ["consultant_contact", "Consultant contact", "text"],
  ["award_date", "Award date", "date"],
  ["start_date", "Start date", "date"],
  ["planned_completion", "Planned completion", "date"],
];

const PROJECT_EMPTY = { code: "", title: "", loa_date: "", start_date: "",
                        scope: "", pm: "", manpower_summary: "" };

export default function SitesManagePage({ me, onChanged }) {
  const [sites, setSites] = useState([]);
  const [selected, setSelected] = useState(null);
  const [form, setForm] = useState({});
  const [siteProjects, setSiteProjects] = useState([]);
  const [pms, setPms] = useState([]);
  const [projDraft, setProjDraft] = useState(PROJECT_EMPTY);
  const [addingProject, setAddingProject] = useState(false);
  const [editProj, setEditProj] = useState(null);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);

  const canEditSite = ["ADMIN", "DIRECTOR"].includes(me.role);
  const canEditProject = ["ADMIN", "DIRECTOR", "PM"].includes(me.role);

  const loadSites = useCallback(() => {
    api("/sites").then(setSites);
  }, []);

  useEffect(() => {
    loadSites();
    api("/pms").then(setPms).catch(() => {});
  }, [loadSites]);

  const openSite = useCallback((site) => {
    setSelected(site);
    setNotice(null);
    setError(null);
    setForm(Object.fromEntries(
      SITE_FIELDS.map(([key]) => [key, site[key] || ""])));
    api(`/sites/${site.id}/projects`).then(setSiteProjects);
  }, []);

  async function saveSite() {
    setError(null);
    try {
      const body = { ...form };
      for (const [key, , kind] of SITE_FIELDS) {
        if (kind === "date" && !body[key]) body[key] = null;
      }
      const fresh = await api(`/sites/${selected.id}`,
                              { method: "PATCH", body });
      setNotice("Site details saved.");
      setSelected(fresh);
      loadSites();
      onChanged?.();
    } catch (e) {
      setError(e.message);
    }
  }

  async function assignSitePm(pmId) {
    if (!pmId) return;
    setError(null);
    try {
      const fresh = await api(`/sites/${selected.id}/assign-pm`,
                              { method: "POST", body: { pm_user_id: +pmId } });
      setSelected(fresh);
      setNotice("Site PM assigned.");
      loadSites();
    } catch (e) {
      setError(e.message);
    }
  }

  async function saveProject() {
    setError(null);
    const body = { ...projDraft, pm: projDraft.pm || null,
                   loa_date: projDraft.loa_date || null,
                   start_date: projDraft.start_date || null };
    try {
      if (editProj) {
        await api(`/projects/${editProj}`, { method: "PATCH", body });
      } else {
        await api(`/sites/${selected.id}/projects`,
                  { method: "POST", body });
      }
      setProjDraft(PROJECT_EMPTY);
      setAddingProject(false);
      setEditProj(null);
      api(`/sites/${selected.id}/projects`).then(setSiteProjects);
      onChanged?.();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <>
      <section style={card}>
        <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Sites &amp; Projects
        </h2>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={th}>Code</th><th style={th}>Site</th>
            <th style={th}>Client</th><th style={th}>Site PM</th>
            <th style={th}>Projects</th><th style={th}>Status</th>
          </tr></thead>
          <tbody>
            {sites.filter((s) => !s.is_head_office).map((s) => (
              <tr key={s.id} onClick={() => openSite(s)}
                  style={{ cursor: "pointer",
                           background: selected?.id === s.id
                             ? "#e8f0f7" : "transparent" }}>
                <td style={{ ...td, fontWeight: 700,
                             color: "var(--sp-navy)" }}>{s.code}</td>
                <td style={td}>{s.name}</td>
                <td style={td}>{s.client_name || "—"}</td>
                <td style={td}>{s.current_pm?.full_name || "—"}</td>
                <td style={td}>
                  {selected?.id === s.id ? siteProjects.length : ""}
                </td>
                <td style={td}><StatusChip status={s.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {selected && (
        <section style={card}>
          <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 16 }}>
            {selected.code} — site details
          </h2>
          {notice && <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>}
          {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
          <div style={{ display: "grid",
                        gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
            {SITE_FIELDS.map(([key, label, kind]) => (
              <label key={key} style={{ fontSize: 13 }}>{label}
                <input type={kind} value={form[key] || ""}
                       disabled={!canEditSite}
                       onChange={(e) => setForm({ ...form,
                                                  [key]: e.target.value })}
                       style={inputStyle} />
              </label>
            ))}
            <label style={{ fontSize: 13 }}>Site PM
              <select value="" disabled={!canEditSite}
                      onChange={(e) => assignSitePm(e.target.value)}
                      style={inputStyle}>
                <option value="">
                  {selected.current_pm?.full_name || "— not assigned —"}
                </option>
                {pms.filter((p) => p.id !== selected.current_pm?.id)
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      Assign: {p.full_name}</option>
                  ))}
              </select>
            </label>
          </div>
          {canEditSite && (
            <button onClick={saveSite} style={{ ...buttonStyle,
                                                marginTop: 14 }}>
              Save site details
            </button>
          )}

          <h3 style={{ color: "var(--sp-navy)", fontSize: 15,
                       borderBottom: "1px solid var(--sp-sky)",
                       paddingBottom: 4, marginTop: 26 }}>
            Projects at {selected.code}
          </h3>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>Code</th><th style={th}>Project</th>
              <th style={th}>LOA date</th><th style={th}>Start</th>
              <th style={th}>Project PM</th><th style={th}>Manpower</th>
              <th style={th}>Progress</th><th style={th}>Status</th>
              {canEditProject && <th style={th} />}
            </tr></thead>
            <tbody>
              {siteProjects.map((p) => (
                <tr key={p.id}>
                  <td style={{ ...td, fontWeight: 700,
                               color: "var(--sp-navy)" }}>{p.code}</td>
                  <td style={td} title={p.scope}>{p.title}</td>
                  <td style={td}>{p.loa_date || "—"}</td>
                  <td style={td}>{p.start_date || "—"}</td>
                  <td style={td}>{p.pm_name || "—"}</td>
                  <td style={td}>
                    {p.manpower_summary || "—"}
                    {p.latest_manpower != null && (
                      <span style={{ color: "#5a6b78", fontSize: 12 }}>
                        {" "}(last DPR: {p.latest_manpower})</span>
                    )}
                  </td>
                  <td style={td}>{p.overall_progress}%</td>
                  <td style={td}><StatusChip status={p.status} /></td>
                  {canEditProject && (
                    <td style={td}>
                      <button onClick={() => { setEditProj(p.id);
                          setAddingProject(true);
                          setProjDraft({ code: p.code, title: p.title,
                            loa_date: p.loa_date || "",
                            start_date: p.start_date || "",
                            scope: p.scope || "", pm: p.pm || "",
                            manpower_summary: p.manpower_summary || "" }); }}
                              style={{ ...ghostButton, padding: "2px 8px",
                                       fontSize: 12 }}>✎</button>
                    </td>
                  )}
                </tr>
              ))}
              {siteProjects.length === 0 && (
                <tr><td style={td} colSpan={9}>No projects yet.</td></tr>
              )}
            </tbody>
          </table>

          {canEditProject && !addingProject && (
            <button onClick={() => { setAddingProject(true);
                                     setEditProj(null);
                                     setProjDraft(PROJECT_EMPTY); }}
                    style={{ ...buttonStyle, marginTop: 12 }}>
              + Add project
            </button>
          )}
          {addingProject && (
            <div style={{ border: "1px dashed var(--sp-border)",
                          borderRadius: 8, padding: 14, marginTop: 12,
                          display: "grid",
                          gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
              <label style={{ fontSize: 13 }}>Project code
                <input value={projDraft.code} disabled={!!editProj}
                       onChange={(e) => setProjDraft({ ...projDraft,
                         code: e.target.value.toUpperCase() })}
                       style={inputStyle} />
              </label>
              <label style={{ fontSize: 13, gridColumn: "span 2" }}>
                Project name
                <input value={projDraft.title}
                       onChange={(e) => setProjDraft({ ...projDraft,
                                                       title: e.target.value })}
                       style={inputStyle} />
              </label>
              <label style={{ fontSize: 13 }}>LOA date
                <input type="date" value={projDraft.loa_date}
                       onChange={(e) => setProjDraft({ ...projDraft,
                         loa_date: e.target.value })}
                       style={inputStyle} />
              </label>
              <label style={{ fontSize: 13 }}>Start date
                <input type="date" value={projDraft.start_date}
                       onChange={(e) => setProjDraft({ ...projDraft,
                         start_date: e.target.value })}
                       style={inputStyle} />
              </label>
              <label style={{ fontSize: 13 }}>Project PM
                <select value={projDraft.pm}
                        onChange={(e) => setProjDraft({ ...projDraft,
                                                        pm: e.target.value })}
                        style={inputStyle}>
                  <option value="">— site PM handles it —</option>
                  {pms.map((p) => (
                    <option key={p.id} value={p.id}>{p.full_name}</option>
                  ))}
                </select>
              </label>
              <label style={{ fontSize: 13, gridColumn: "span 2" }}>
                General summary
                <textarea value={projDraft.scope} rows={2}
                          onChange={(e) => setProjDraft({ ...projDraft,
                            scope: e.target.value })}
                          style={{ ...inputStyle, resize: "vertical" }} />
              </label>
              <label style={{ fontSize: 13 }}>
                Manpower summary
                <input value={projDraft.manpower_summary}
                       placeholder="e.g. 1 SE, 2 masons, 12 labour"
                       onChange={(e) => setProjDraft({ ...projDraft,
                         manpower_summary: e.target.value })}
                       style={inputStyle} />
              </label>
              <div style={{ gridColumn: "1 / -1", display: "flex", gap: 8 }}>
                <button onClick={saveProject}
                        disabled={!projDraft.code || !projDraft.title}
                        style={buttonStyle}>
                  {editProj ? "Save project" : "Create project"}
                </button>
                <button onClick={() => { setAddingProject(false);
                                         setEditProj(null); }}
                        style={ghostButton}>Cancel</button>
              </div>
            </div>
          )}
        </section>
      )}
    </>
  );
}
