import { useEffect, useState } from "react";
import { api } from "./api.js";
import DPRForm from "./DPRForm.jsx";
import DPRView from "./DPRView.jsx";
import HODashboard from "./HODashboard.jsx";
import ItemsPage from "./ItemsPage.jsx";
import SuppliersPage from "./SuppliersPage.jsx";
import EmployeesPage from "./EmployeesPage.jsx";
import UsersPage from "./UsersPage.jsx";
import PayrollPage from "./PayrollPage.jsx";
import ProgrammePage from "./ProgrammePage.jsx";
import SitesManagePage from "./SitesManagePage.jsx";
import AttendancePage from "./AttendancePage.jsx";
import DMAPage from "./DMAPage.jsx";
import PmsPage from "./PmsPage.jsx";
import { LineDocForm, LineDocView } from "./LineDoc.jsx";
import { QADocView, QAForm } from "./QADocs.jsx";
import { MatchingWorkspace } from "./QuotationsPanel.jsx";
import SiteDashboard from "./SiteDashboard.jsx";
import { StatusChip, buttonStyle, card, ghostButton, inputStyle } from "./ui.jsx";

function Login({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onLogin(await api("/auth/login", { method: "POST",
                                         body: { username, password } }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 380, margin: "10vh auto", padding: "0 16px" }}>
      <form onSubmit={submit} style={card}>
        <h2 style={{ marginTop: 0, color: "var(--sp-navy)" }}>Sign in</h2>
        <label style={{ display: "block", fontSize: 13, marginBottom: 4 }}>
          Username</label>
        <input value={username} onChange={(e) => setUsername(e.target.value)}
               autoFocus style={inputStyle} />
        <label style={{ display: "block", fontSize: 13, margin: "12px 0 4px" }}>
          Password</label>
        <input type="password" value={password}
               onChange={(e) => setPassword(e.target.value)} style={inputStyle} />
        {error && <p style={{ color: "#c0392b", fontSize: 13,
                              margin: "12px 0 0" }}>{error}</p>}
        <button type="submit" disabled={busy}
                style={{ ...buttonStyle, width: "100%", marginTop: 16 }}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

function SiteList({ sites, onOpen }) {
  return (
    <section style={card}>
      <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
        Sites &amp; projects
      </h2>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <tbody>
          {sites.map((s) => (
            <tr key={s.id} onClick={() => onOpen(s)}
                style={{ borderTop: "1px solid var(--sp-border)",
                         cursor: "pointer" }}>
              <td style={{ padding: "10px 8px 10px 0", fontWeight: 600,
                           color: "var(--sp-navy)", width: 56 }}>{s.code}</td>
              <td style={{ padding: 10 }}>
                {s.name}{s.is_head_office ? " (Head Office)" : ""}
              </td>
              <td style={{ padding: 10, textAlign: "right" }}>
                <StatusChip status={s.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

const navBtn = (active) => ({
  background: "transparent",
  color: active ? "#fff" : "var(--sp-sky)",
  border: "none",
  borderBottom: active ? "2px solid var(--sp-sky)" : "2px solid transparent",
  padding: "4px 10px",
  cursor: "pointer",
  fontSize: 14,
});

export default function App() {
  const [me, setMe] = useState(null);
  const [sites, setSites] = useState([]);
  const [openSite, setOpenSite] = useState(null);
  const [projects, setProjects] = useState([]);
  const [project, setProject] = useState(null);  // selected project (R4)
  const [addingProject, setAddingProject] = useState(false);
  const [projDraft, setProjDraft] = useState({ code: "", title: "",
                                               start_date: "" });
  const [hoPage, setHoPage] = useState("dashboard");
  const [docView, setDocView] = useState(null);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/auth/me").then(setMe).catch(() => setMe({ authenticated: false }));
  }, []);

  useEffect(() => {
    if (!me?.authenticated) return;
    api("/sites").then((list) => {
      setSites(list);
      if (me.landing_site_id) {
        setOpenSite(list.find((s) => s.id === me.landing_site_id) || null);
      }
    });
  }, [me]);

  useEffect(() => {
    setProjects([]);
    setProject(null);
    if (!openSite) return;
    api(`/sites/${openSite.id}/projects`).then((list) => {
      setProjects(list);
      const active = list.filter((p) => p.status === "ACTIVE");
      if (active.length === 1) setProject(active[0]);
    }).catch(() => {});
  }, [openSite, refresh]);

  async function createProject() {
    try {
      const created = await api(`/sites/${openSite.id}/projects`, {
        method: "POST",
        body: { ...projDraft,
                start_date: projDraft.start_date || null },
      });
      setAddingProject(false);
      setProjDraft({ code: "", title: "", start_date: "" });
      setProjects([...projects, created]);
      setProject(created);
    } catch (e) {
      setError(e.message);
    }
  }

  async function logoutUser() {
    await api("/auth/logout", { method: "POST" });
    setMe({ authenticated: false });
    setSites([]);
    setOpenSite(null);
    setDocView(null);
  }

  async function openDoc(ref) {
    setError(null);
    try {
      const doc = await api(`/documents/${ref}`);
      const mode = doc.doc_type === "DPR" ? "dpr-view"
                 : ["IR", "MAR", "TWS"].includes(doc.doc_type) ? "qa-view"
                 : "line-view";
      setDocView({ mode, doc });
    } catch (e) {
      setError(e.message);
    }
  }

  function resubmitIr(doc) {
    const payload = { ...doc.payload };
    delete payload.client_result;
    delete payload.closure;
    setDocView({ mode: "qa-form", docType: "IR", doc: null,
                 prefill: { previous_ir_ref: doc.ref, payload } });
  }

  async function createGrn(lmRef) {
    setError(null);
    try {
      const doc = await api("/documents", {
        method: "POST",
        body: { doc_type: "GRN", site_id: openSite.id, lm_ref: lmRef },
      });
      setDocView({ mode: "line-form", docType: "GRN", doc });
    } catch (e) {
      setError(e.message);
    }
  }

  function bump() {
    setRefresh((n) => n + 1);
  }

  function closeDoc() {
    setDocView(null);
    bump();
  }

  if (me === null) return null;

  const showHoNav = me.authenticated && me.is_ho;

  return (
    <div>
      <header style={{ background: "var(--sp-navy)", color: "#fff",
                       padding: "14px 28px",
                       borderBottom: "4px solid var(--sp-sky)",
                       display: "flex", alignItems: "baseline", gap: 16 }}>
        <h1 style={{ margin: 0, fontSize: 20, letterSpacing: 0.5,
                     cursor: "pointer" }}
            onClick={() => { setDocView(null); setHoPage("dashboard");
                             if (!me.landing_site_id) setOpenSite(null); }}>
          SAND PLANET
        </h1>
        <span style={{ color: "var(--sp-sky)", fontSize: 14 }}>
          Project Management</span>
        {showHoNav && (
          <nav style={{ display: "flex", gap: 4 }}>
            {[["dashboard", "HO Dashboard"], ["sites", "Sites"],
              ["manage", "Site Setup"],
              ["items", "Items"], ["suppliers", "Suppliers"],
              ["employees", "Employees"],
              ...(["HO_HR", "FINANCE", "ADMIN"].includes(me.role)
                ? [["payroll", "Payroll"]] : []),
              ...(["DIRECTOR", "ADMIN"].includes(me.role)
                ? [["pms", "PMs"]] : []),
              ...(me.role === "ADMIN" ? [["users", "Users"]] : [])]
              .map(([key, label]) => (
              <button key={key}
                      style={navBtn(hoPage === key && !openSite && !docView)}
                      onClick={() => { setHoPage(key); setOpenSite(null);
                                       setDocView(null); }}>
                {label}
              </button>
            ))}
          </nav>
        )}
        {me.authenticated && (
          <span style={{ marginLeft: "auto", fontSize: 13 }}>
            {me.full_name} · {me.role.replace(/_/g, " ")}
            <button onClick={logoutUser}
                    style={{ marginLeft: 14, background: "transparent",
                             color: "var(--sp-sky)",
                             border: "1px solid var(--sp-sky)",
                             borderRadius: 6, padding: "3px 10px",
                             cursor: "pointer", fontSize: 12 }}>
              Sign out
            </button>
          </span>
        )}
      </header>

      {!me.authenticated ? (
        <Login onLogin={setMe} />
      ) : (
        <main style={{ maxWidth: 1000, margin: "32px auto", padding: "0 16px" }}>
          {error && <p style={{ color: "#c0392b" }}>{error}</p>}

          {docView?.mode === "dpr-form" && (
            <DPRForm site={openSite} existing={docView.doc} project={project}
                     onSaved={closeDoc} onCancel={closeDoc} />
          )}
          {docView?.mode === "dpr-view" && (
            <DPRView doc={docView.doc} me={me} onClose={closeDoc}
                     onChanged={bump}
                     onEdit={(doc) => setDocView({ mode: "dpr-form", doc })} />
          )}
          {docView?.mode === "line-form" && (
            <LineDocForm docType={docView.docType} site={openSite}
                         sites={sites} me={me} existing={docView.doc}
                         onSaved={(doc) => { bump();
                           setDocView({ mode: "line-view", doc }); }}
                         onCancel={closeDoc} />
          )}
          {docView?.mode === "line-view" && (
            <LineDocView doc={docView.doc} me={me} onClose={closeDoc}
                         onChanged={bump} onOpenDoc={openDoc}
                         onOpenMatch={(doc) => setDocView({
                           mode: "pr-match", doc })}
                         onEdit={(doc) => setDocView({
                           mode: "line-form", docType: doc.doc_type, doc })} />
          )}
          {docView?.mode === "pr-match" && (
            <MatchingWorkspace doc={docView.doc} me={me} onChanged={bump}
                               onClose={() => openDoc(docView.doc.ref)} />
          )}
          {docView?.mode === "qa-form" && (
            <QAForm docType={docView.docType} site={openSite} project={project}
                    existing={docView.doc} prefill={docView.prefill}
                    onSaved={(doc) => { bump();
                      setDocView({ mode: "qa-view", doc }); }}
                    onCancel={closeDoc} />
          )}
          {docView?.mode === "qa-view" && (
            <QADocView doc={docView.doc} me={me} onClose={closeDoc}
                       onChanged={bump} onResubmit={resubmitIr}
                       onEdit={(doc) => setDocView({
                         mode: "qa-form", docType: doc.doc_type, doc })} />
          )}

          {docView?.mode === "programme" && (
            <ProgrammePage project={docView.project} me={me}
                           onClose={closeDoc} />
          )}

          {!docView && openSite && (
            <>
              <div style={{ display: "flex", justifyContent: "space-between",
                            alignItems: "baseline", marginBottom: 10 }}>
                <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
                  {openSite.code} — {openSite.name}{" "}
                  <StatusChip status={openSite.status} />
                </h2>
                {(me.is_ho || me.allocations.length > 1) && (
                  <button onClick={() => setOpenSite(null)} style={ghostButton}>
                    ← All sites
                  </button>
                )}
              </div>

              {/* Projects within the site (R4) */}
              <div style={{ display: "flex", gap: 6, alignItems: "center",
                            flexWrap: "wrap", marginBottom: 16 }}>
                {projects.map((p) => (
                  <button key={p.id}
                          onClick={() => setProject(
                            project?.id === p.id ? null : p)}
                          title={p.title}
                          style={{
                            ...ghostButton, padding: "4px 14px", fontSize: 13,
                            background: project?.id === p.id
                              ? "var(--sp-navy)" : "#fff",
                            color: project?.id === p.id ? "#fff"
                              : "var(--sp-navy)",
                          }}>
                    {p.code} · {p.overall_progress}%
                  </button>
                ))}
                {project && (
                  <button onClick={() => setDocView({ mode: "programme",
                                                      project })}
                          style={{ ...ghostButton, padding: "4px 12px",
                                   fontSize: 13 }}>
                    Programme →
                  </button>
                )}
                {["PM", "DIRECTOR", "ADMIN"].includes(me.role) &&
                  !addingProject && (
                  <button onClick={() => setAddingProject(true)}
                          style={{ ...ghostButton, padding: "4px 12px",
                                   fontSize: 13 }}>
                    + Project
                  </button>
                )}
                {addingProject && (
                  <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <input placeholder="Code (e.g. POOLS17)"
                           value={projDraft.code}
                           onChange={(e) => setProjDraft({ ...projDraft,
                             code: e.target.value.toUpperCase() })}
                           style={{ ...inputStyle, width: 130 }} />
                    <input placeholder="Project title" value={projDraft.title}
                           onChange={(e) => setProjDraft({ ...projDraft,
                             title: e.target.value })}
                           style={{ ...inputStyle, width: 240 }} />
                    <input type="date" value={projDraft.start_date}
                           title="Start date"
                           onChange={(e) => setProjDraft({ ...projDraft,
                             start_date: e.target.value })}
                           style={{ ...inputStyle, width: 140 }} />
                    <button onClick={createProject}
                            disabled={!projDraft.code || !projDraft.title}
                            style={{ ...buttonStyle, padding: "4px 12px" }}>
                      Create
                    </button>
                    <button onClick={() => setAddingProject(false)}
                            style={{ ...ghostButton, padding: "4px 10px" }}>
                      ×
                    </button>
                  </span>
                )}
                {projects.length > 0 && !project && (
                  <span style={{ fontSize: 12, color: "#b35900" }}>
                    Select a project to create DPR / TWS / IR / MAR.
                  </span>
                )}
              </div>
              <SiteDashboard
                site={openSite} me={me} refresh={refresh} project={project}
                onNewDpr={() => setDocView({ mode: "dpr-form", doc: null })}
                onNewMr={() => setDocView({ mode: "line-form", docType: "MR",
                                            doc: null })}
                onNewQa={(docType) => setDocView({ mode: "qa-form", docType,
                                                   doc: null })}
                onAttendance={() => setDocView({ mode: "attendance" })}
                onDma={() => setDocView({ mode: "dma" })}
                onCreateGrn={createGrn}
                onOpenDoc={openDoc}
              />
            </>
          )}

          {!docView && !openSite && me.is_ho && hoPage === "dashboard" && (
            <HODashboard me={me} refresh={refresh} onOpenDoc={openDoc}
                         onNew={(docType) => setDocView({ mode: "line-form",
                                                          docType, doc: null })} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "manage" && (
            <SitesManagePage me={me} onChanged={bump} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "items" && (
            <ItemsPage me={me} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "suppliers" && (
            <SuppliersPage me={me} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "employees" && (
            <EmployeesPage me={me} sites={sites} />
          )}
          {!docView && !openSite && me.role === "ADMIN" &&
            hoPage === "users" && (
            <UsersPage me={me} sites={sites} />
          )}
          {!docView && !openSite &&
            ["HO_HR", "FINANCE", "ADMIN"].includes(me.role) &&
            hoPage === "payroll" && (
            <PayrollPage sites={sites} />
          )}
          {docView?.mode === "attendance" && openSite && (
            <AttendancePage site={openSite} me={me} onClose={closeDoc} />
          )}
          {docView?.mode === "dma" && openSite && (
            <DMAPage site={openSite} me={me} onClose={closeDoc} />
          )}
          {!docView && !openSite &&
            ["DIRECTOR", "ADMIN"].includes(me.role) && hoPage === "pms" && (
            <PmsPage me={me} sites={sites} />
          )}
          {!docView && !openSite &&
            (!me.is_ho || hoPage === "sites") && (
            <SiteList sites={sites} onOpen={setOpenSite} />
          )}
        </main>
      )}
    </div>
  );
}
