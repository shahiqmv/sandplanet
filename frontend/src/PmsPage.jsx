import { useEffect, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

// PM management (R5): site PM is a special duty, so assignments get their
// own board — every PM with the sites and projects they run, reassignment
// controls, and the assignment history. Accounts still live under Users.

const EMPTY = { username: "", full_name: "", password: "" };

export default function PmsPage({ me, sites }) {
  const [data, setData] = useState(null);
  const [draft, setDraft] = useState(EMPTY);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [showHistory, setShowHistory] = useState(false);

  const projectSites = sites.filter((s) => !s.is_head_office);

  function load() {
    api("/pm-overview").then(setData).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function createPm() {
    setError(null);
    try {
      const user = await api("/users", { method: "POST",
        body: { ...draft, role: "PM" } });
      setNotice(`PM account ${user.username} created — assign a site below.`);
      setDraft(EMPTY);
      setAdding(false);
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function assignSite(pm, siteId) {
    if (!siteId) return;
    setError(null);
    setNotice(null);
    try {
      await api(`/sites/${siteId}/assign-pm`,
                { method: "POST", body: { pm_user_id: pm.id } });
      setNotice(`${pm.full_name} is now the Site PM there (previous PM's ` +
                "assignment closed today — history kept).");
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  if (!data) return <section style={card}>{error || "Loading…"}</section>;

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Project Managers
        </h2>
        <span style={{ fontSize: 12, color: "#5a6b78" }}>
          Site PM drives approval routing; project PM overrides it per project
          (set on Site Setup).
        </span>
        {me.role === "ADMIN" && !adding && (
          <button onClick={() => setAdding(true)}
                  style={{ ...buttonStyle, marginLeft: "auto",
                           padding: "5px 14px", fontSize: 13 }}>
            + New PM account
          </button>
        )}
      </div>

      {adding && (
        <div style={{ display: "flex", gap: 8, margin: "14px 0",
                      flexWrap: "wrap", alignItems: "center" }}>
          <input placeholder="Username" value={draft.username}
                 onChange={(e) => setDraft({ ...draft,
                   username: e.target.value })}
                 style={{ ...inputStyle, width: 140 }} />
          <input placeholder="Full name" value={draft.full_name}
                 onChange={(e) => setDraft({ ...draft,
                   full_name: e.target.value })}
                 style={{ ...inputStyle, width: 200 }} />
          <input type="password" placeholder="Password"
                 value={draft.password}
                 onChange={(e) => setDraft({ ...draft,
                   password: e.target.value })}
                 style={{ ...inputStyle, width: 150 }} />
          <button onClick={createPm}
                  disabled={!draft.username || !draft.full_name ||
                            !draft.password}
                  style={{ ...buttonStyle, padding: "5px 14px" }}>
            Create
          </button>
          <button onClick={() => setAdding(false)}
                  style={{ ...ghostButton, padding: "5px 10px" }}>×</button>
        </div>
      )}

      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      {notice && <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>}

      <table style={{ width: "100%", borderCollapse: "collapse",
                      marginTop: 10 }}>
        <thead>
          <tr>
            <th style={th}>PM</th>
            <th style={th}>Site PM of</th>
            <th style={th}>Project PM of</th>
            <th style={th}>Assign as Site PM</th>
          </tr>
        </thead>
        <tbody>
          {data.pms.map((pm) => (
            <tr key={pm.id}
                style={pm.is_active ? {} : { opacity: 0.5 }}>
              <td style={td}>
                <b style={{ color: "var(--sp-navy)" }}>{pm.full_name}</b>
                <div style={{ fontSize: 12, color: "#5a6b78" }}>
                  {pm.username}{pm.is_active ? "" : " · deactivated"}
                </div>
              </td>
              <td style={td}>
                {pm.sites.length ? pm.sites.map((s) => (
                  <div key={s.site_id} style={{ fontSize: 13 }}>
                    <b>{s.code}</b> {s.name}
                    <span style={{ color: "#5a6b78" }}> · since {s.since}</span>
                  </div>
                )) : <span style={{ color: "#5a6b78" }}>—</span>}
              </td>
              <td style={td}>
                {pm.projects.length ? pm.projects.map((p) => (
                  <div key={p.project_id} style={{ fontSize: 13 }}>
                    <b>{p.code}</b> @ {p.site_code}
                    {p.status !== "ACTIVE" && (
                      <span style={{ color: "#5a6b78" }}>
                        {" "}· {p.status.toLowerCase()}</span>
                    )}
                  </div>
                )) : <span style={{ color: "#5a6b78" }}>—</span>}
              </td>
              <td style={td}>
                {pm.is_active && (
                  <select defaultValue=""
                          onChange={(e) => { assignSite(pm, e.target.value);
                                             e.target.value = ""; }}
                          style={{ ...inputStyle, width: 170,
                                   padding: "4px 6px" }}>
                    <option value="">site…</option>
                    {projectSites.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.code} — {s.name}</option>
                    ))}
                  </select>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <button onClick={() => setShowHistory(!showHistory)}
              style={{ ...ghostButton, marginTop: 16, fontSize: 13 }}>
        {showHistory ? "Hide" : "Show"} assignment history
      </button>
      {showHistory && (
        <table style={{ width: "100%", borderCollapse: "collapse",
                        marginTop: 8 }}>
          <thead>
            <tr>
              <th style={th}>Site</th><th style={th}>PM</th>
              <th style={th}>From</th><th style={th}>To</th>
            </tr>
          </thead>
          <tbody>
            {data.history.map((h, i) => (
              <tr key={i}>
                <td style={td}><b>{h.site_code}</b> {h.site_name}</td>
                <td style={td}>{h.pm_name}</td>
                <td style={td}>{h.from_date}</td>
                <td style={td}>{h.to_date ||
                  <b style={{ color: "#1a7f37" }}>current</b>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
