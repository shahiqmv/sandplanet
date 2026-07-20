import { useEffect, useState } from "react";
import { api } from "./api.js";
import DPRForm from "./DPRForm.jsx";
import DPRView from "./DPRView.jsx";
import HODashboard from "./HODashboard.jsx";
import ItemsPage from "./ItemsPage.jsx";
import ItemCategoriesPage from "./ItemCategoriesPage.jsx";
import WorkerCategoriesPage from "./WorkerCategoriesPage.jsx";
import OvertimeRatesPage from "./OvertimeRatesPage.jsx";
import SuppliersPage from "./SuppliersPage.jsx";
import ImportOrders, { IprView, IprForm, IrnView, StoreLots,
  ImportPaymentsDue, ImportTracker } from "./ImportOrders.jsx";
import NotificationBell from "./NotificationBell.jsx";
import EmployeesPage from "./EmployeesPage.jsx";
import UsersPage from "./UsersPage.jsx";
import PayrollRunPage from "./PayrollRunPage.jsx";
import ProgrammePage from "./ProgrammePage.jsx";
import SitesManagePage from "./SitesManagePage.jsx";
import AttendancePage from "./AttendancePage.jsx";
import DMAPage from "./DMAPage.jsx";
import ManpowerPage from "./ManpowerPage.jsx";
import ProjectPage from "./ProjectPage.jsx";
import PaymentRequestForm from "./PaymentRequestForm.jsx";
import PaymentRequestView from "./PaymentRequestView.jsx";
import PaymentRegisterPage from "./PaymentRegisterPage.jsx";
import CostControlPage from "./CostControlPage.jsx";
import FinanceDashboard from "./FinanceDashboard.jsx";
import PmrRegister from "./PmrRegister.jsx";
import PaymentVouchersPage from "./PaymentVouchersPage.jsx";
import PettyCashPage from "./PettyCashPage.jsx";
import StaffCostPage from "./StaffCostPage.jsx";
import StockPage from "./StockPage.jsx";
import ToolsPage from "./ToolsPage.jsx";
import PmsPage from "./PmsPage.jsx";
import CompanyPage from "./CompanyPage.jsx";
import ApprovalsPage from "./ApprovalsPage.jsx";
import HRDashboard from "./HRDashboard.jsx";
import PortfolioPage from "./PortfolioPage.jsx";

// Grouped menu (owner, 2026-07-08): five top-level groups, trimmed by
// role; approver roles land on the Approvals queue.
const APPROVERS = ["PM", "HO_PURCHASING", "DIRECTOR", "SIGNATORY",
                   "FINANCE", "ADMIN"];
const NAV_GROUPS = [
  // Not everything in the queue is an approval (DMA issues, MRs to
  // action, payments) — "My Tasks", not "Approvals" (owner, 2026-07-08)
  { key: "approvals", label: "My Tasks", roles: [...APPROVERS, "QS"],
    subs: [["approvals", "My Tasks", APPROVERS],
           ["portfolio", "Portfolio", ["DIRECTOR", "ADMIN", "QS",
                                       "SIGNATORY"]],
           ["cost", "Project Cost", ["DIRECTOR", "FINANCE", "ADMIN", "QS",
                                     "SIGNATORY"]]] },
  { key: "sitesGrp", label: "Sites", roles: null,
    subs: [["sites", "Sites", null]] },
  { key: "procurement", label: "Procurement",
    roles: ["HO_PURCHASING", "DIRECTOR", "FINANCE", "ADMIN", "QS"],
    // QS shares the Director's overseas-procurement authority, so it only sees
    // the import chain (Requests / Orders / Tracker / Store), not domestic
    // purchasing pages (owner 2026-07-14).
    subs: [["dashboard", "Purchasing Dashboard",
            ["HO_PURCHASING", "DIRECTOR", "FINANCE", "ADMIN"]],
           ["items", "Items",
            ["HO_PURCHASING", "DIRECTOR", "FINANCE", "ADMIN"]],
           ["item-categories", "Item Categories",
            ["HO_PURCHASING", "ADMIN"]],
           ["pmr-register", "Import Requests", null],
           ["imports", "International Orders", null],
           ["import-tracker", "Import Tracker", null],
           ["store", "HO Store", null],
           ["suppliers", "Suppliers",
            ["HO_PURCHASING", "DIRECTOR", "FINANCE", "ADMIN"]]] },
  { key: "finance", label: "Finance",
    roles: ["FINANCE", "SIGNATORY", "ADMIN"],
    subs: [["finance-dash", "Dashboard", ["FINANCE", "ADMIN"]],
           ["vouchers", "Payment Vouchers", ["FINANCE", "SIGNATORY",
                                             "ADMIN"]],
           ["import-payments", "Import Payments", ["FINANCE", "ADMIN"]]] },
  { key: "people", label: "People",
    roles: ["HO_HR", "FINANCE", "DIRECTOR", "ADMIN"],
    subs: [["hr", "HR Dashboard", ["HO_HR", "FINANCE", "ADMIN"]],
           ["employees", "Employees", null],
           ["worker-categories", "Worker Categories", ["ADMIN"]],
           ["overtime-rates", "Overtime Rates", ["HO_HR", "ADMIN"]],
           ["payroll", "Payroll", ["HO_HR", "FINANCE", "ADMIN"]],
           ["staff-cost", "Staff Cost",
            ["HO_HR", "FINANCE", "DIRECTOR", "ADMIN"]],
           ["pms", "PMs", ["DIRECTOR", "ADMIN"]]] },
  { key: "adminGrp", label: "Admin", roles: ["DIRECTOR", "ADMIN"],
    subs: [["manage", "Site Setup", ["DIRECTOR", "ADMIN"]],
           ["users", "Users", ["ADMIN"]],
           ["company", "Company", ["ADMIN"]]] },
];

function visibleGroups(me) {
  const can = (roles) => !roles || roles.includes(me.role);
  return NAV_GROUPS.filter((g) => can(g.roles)).map((g) => ({
    ...g, subs: g.subs.filter(([, , roles]) => can(roles)),
  })).filter((g) => g.subs.length);
}

function landingPage(me) {
  if (me.role === "FINANCE") return "finance-dash";
  if (me.role === "SIGNATORY") return "vouchers";
  if (APPROVERS.includes(me.role)) return "approvals";
  if (me.role === "HO_HR") return "hr";
  if (me.role === "QS") return "portfolio";
  return "sites";
}
import { LineDocForm, LineDocView } from "./LineDoc.jsx";
import { QADocView, QAForm } from "./QADocs.jsx";
import { MatchingWorkspace } from "./QuotationsPanel.jsx";
import SiteDashboard from "./SiteDashboard.jsx";
import { StatusChip, buttonStyle, card, ghostButton, inputStyle } from "./ui.jsx";

function ChangePassword({ forced, onDone }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (next !== confirm) { setError("The two new passwords don't match."); return; }
    setBusy(true); setError(null);
    try {
      await api("/auth/change-password", { method: "POST",
        body: { current_password: current, new_password: next } });
      onDone();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  return (
    <div style={{ maxWidth: 380, margin: "10vh auto", padding: "0 16px" }}>
      <form onSubmit={submit} style={card}>
        <h2 style={{ marginTop: 0, color: "var(--sp-navy)" }}>
          {forced ? "Set your password" : "Change password"}</h2>
        {forced && (
          <p style={{ fontSize: 13, color: "#5a6b78", marginTop: 0 }}>
            You signed in with a temporary password. Choose your own to
            continue.
          </p>
        )}
        <label style={{ display: "block", fontSize: 13, marginBottom: 4 }}>
          {forced ? "Temporary password" : "Current password"}</label>
        <input type="password" value={current} autoFocus
               onChange={(e) => setCurrent(e.target.value)} style={inputStyle} />
        <label style={{ display: "block", fontSize: 13, margin: "12px 0 4px" }}>
          New password (min 8 characters)</label>
        <input type="password" value={next}
               onChange={(e) => setNext(e.target.value)} style={inputStyle} />
        <label style={{ display: "block", fontSize: 13, margin: "12px 0 4px" }}>
          Confirm new password</label>
        <input type="password" value={confirm}
               onChange={(e) => setConfirm(e.target.value)} style={inputStyle} />
        {error && <p style={{ color: "#c0392b", fontSize: 13,
                              margin: "12px 0 0" }}>{error}</p>}
        <button type="submit" disabled={busy || !current || next.length < 8}
                style={{ ...buttonStyle, width: "100%", marginTop: 16 }}>
          {busy ? "Saving…" : "Save password"}
        </button>
      </form>
    </div>
  );
}

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
  const [pms, setPms] = useState([]);
  const PROJ_EMPTY = { code: "", title: "", loa_date: "", start_date: "",
                       planned_completion: "", pm: "", scope: "" };
  const [projDraft, setProjDraft] = useState(PROJ_EMPTY);
  const [hoPage, setHoPage] = useState("sites");
  const [docView, setDocView] = useState(null);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState(null);
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    if (me?.authenticated) setHoPage(landingPage(me));
  }, [me]);

  useEffect(() => {
    if (!me?.authenticated || !APPROVERS.includes(me.role)) return;
    api("/approvals/pending").then((d) => setPendingCount(d.total))
      .catch(() => {});
  }, [me, refresh]);

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
        body: { code: projDraft.code, title: projDraft.title,
                scope: projDraft.scope,
                loa_date: projDraft.loa_date || null,
                start_date: projDraft.start_date || null,
                planned_completion: projDraft.planned_completion || null,
                pm: projDraft.pm || null },
      });
      setAddingProject(false);
      setProjDraft(PROJ_EMPTY);
      setProjects([...projects, created]);
      setProject(created);
      setDocView({ mode: "project", projectId: created.id });
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
      if (doc.doc_type === "IPR") {
        setDocView({ mode: "ipr-view", doc });
        return;
      }
      if (doc.doc_type === "IRN") {
        setDocView({ mode: "irn-view", doc });
        return;
      }
      const mode = doc.doc_type === "DPR" ? "dpr-view"
                 : ["IR", "MAR", "TWS"].includes(doc.doc_type) ? "qa-view"
                 : doc.doc_type === "PYR" ? "pyr-view"
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

  function createGrn(lmRef) {
    // Open the GRN form without creating anything yet — the reference is only
    // minted when the user saves, so abandoning the form leaves no empty draft.
    setError(null);
    setDocView({ mode: "line-form", docType: "GRN", doc: null,
                 grnLmRef: lmRef || null });
  }

  function bump() {
    setRefresh((n) => n + 1);
  }

  function closeDoc() {
    setDocView(null);
    bump();
  }

  if (me === null) return null;

  // PMs get the grouped nav too (Approvals + Sites); site users keep the
  // plain site view
  const showHoNav = me.authenticated && (me.is_ho || me.role === "PM");
  const groups = me.authenticated ? visibleGroups(me) : [];
  const activeGroup = groups.find((g) =>
    g.subs.some(([key]) => key === hoPage));

  function openApprovalItem(item) {
    if (item.doc_type === "DMA") {
      const site = sites.find((s) => s.code === item.site_code);
      if (site) { setOpenSite(site); setDocView({ mode: "dma" }); }
      return;
    }
    openDoc(item.ref);
  }

  return (
    <div>
      <header style={{ background: "var(--navy)", color: "#fff",
                       padding: "14px 28px",
                       borderBottom: "3px solid var(--sky)",
                       display: "flex", alignItems: "baseline", gap: 16 }}>
        <h1 style={{ margin: 0, fontSize: 22,
                     fontFamily: "var(--font-display)", fontWeight: 700,
                     letterSpacing: "0.14em", cursor: "pointer" }}
            onClick={() => { setDocView(null); setHoPage(landingPage(me));
                             if (!me.landing_site_id) setOpenSite(null); }}>
          SAND PLANET
        </h1>
        <span style={{ color: "var(--sp-sky)", fontSize: 14 }}>
          Project Management</span>
        {showHoNav && (
          <nav style={{ display: "flex", gap: 4 }}>
            {groups.map((g) => (
              <button key={g.key}
                      style={navBtn(activeGroup?.key === g.key && !openSite
                                    && !docView)}
                      onClick={() => { setHoPage(g.subs[0][0]);
                                       setOpenSite(null);
                                       setDocView(null); }}>
                {g.label}
                {g.key === "approvals" && pendingCount > 0 && (
                  <span style={{ background: "#c0392b", color: "#fff",
                                 borderRadius: 10, padding: "1px 7px",
                                 fontSize: 11, marginLeft: 6 }}>
                    {pendingCount}
                  </span>
                )}
              </button>
            ))}
          </nav>
        )}
        {me.authenticated && (
          <NotificationBell onOpen={(ref, docType) => {
            if (docType === "PV") { setDocView(null); setOpenSite(null);
                                    setHoPage("vouchers"); }
            else openDoc(ref);
          }} />
        )}
        {me.authenticated && (
          <span style={{ marginLeft: 16, fontSize: 13 }}>
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
      ) : me.must_change_password ? (
        <ChangePassword forced onDone={() =>
          api("/auth/me").then(setMe)} />
      ) : (
        <main style={{ maxWidth: 900, margin: "28px auto", padding: "0 20px" }}>
          {error && <p style={{ color: "#c0392b" }}>{error}</p>}

          {!docView && !openSite && activeGroup &&
            activeGroup.subs.length > 1 && (
            <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
              {activeGroup.subs.map(([key, label]) => (
                <button key={key} onClick={() => setHoPage(key)}
                        style={{
                          ...ghostButton, padding: "4px 14px", fontSize: 13,
                          background: hoPage === key ? "var(--sp-navy)"
                                                     : "#fff",
                          color: hoPage === key ? "#fff" : "var(--sp-navy)",
                        }}>
                  {label}
                </button>
              ))}
            </div>
          )}

          {!docView && !openSite && APPROVERS.includes(me.role) &&
            hoPage === "approvals" && (
            <ApprovalsPage me={me} refresh={refresh}
                           onOpen={openApprovalItem} />
          )}
          {!docView && !openSite &&
            ["DIRECTOR", "FINANCE", "ADMIN", "QS", "SIGNATORY"]
              .includes(me.role) &&
            hoPage === "cost" && (
            <CostControlPage onOpenDoc={openDoc} me={me} />
          )}
          {!docView && !openSite &&
            ["DIRECTOR", "ADMIN", "QS", "SIGNATORY"].includes(me.role) &&
            hoPage === "portfolio" && (
            <PortfolioPage refresh={refresh}
                           onOpenProject={(id) => setDocView({
                             mode: "project", projectId: id })} />
          )}
          {!docView && !openSite &&
            ["HO_HR", "FINANCE", "ADMIN"].includes(me.role) &&
            hoPage === "hr" && (
            <HRDashboard refresh={refresh} />
          )}

          {docView?.mode === "dpr-form" && (
            <DPRForm site={openSite} existing={docView.doc}
                     projects={projects}
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
                         grnLmRef={docView.grnLmRef}
                         project={project} projects={projects}
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
          {docView?.mode === "ipr-view" && (
            <IprView me={me} refIpr={docView.doc.ref} onClose={closeDoc}
                     onOpenIrn={(ref) =>
                       setDocView({ mode: "irn-view", doc: { ref } })}
                     onEdit={(doc) =>
                       setDocView({ mode: "ipr-edit", doc })} />
          )}
          {docView?.mode === "ipr-edit" && (
            <IprForm me={me} existing={docView.doc}
                     onSaved={(ref) =>
                       setDocView({ mode: "ipr-view", doc: { ref } })}
                     onCancel={() =>
                       setDocView({ mode: "ipr-view",
                                    doc: { ref: docView.doc.ref } })} />
          )}
          {docView?.mode === "irn-view" && (
            <IrnView me={me} refIrn={docView.doc.ref} onClose={closeDoc} />
          )}
          {docView?.mode === "qa-form" && (
            <QAForm docType={docView.docType} site={openSite} project={project}
                    projects={projects}
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
          {docView?.mode === "project" && (
            <ProjectPage projectId={docView.projectId} me={me}
                         onClose={closeDoc} onOpenDoc={openDoc} />
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
                  <button onClick={() => setDocView({ mode: "project",
                                                      projectId: project.id })}
                          style={{ ...ghostButton, padding: "4px 12px",
                                   fontSize: 13 }}>
                    Open project →
                  </button>
                )}
                {["PM", "DIRECTOR", "ADMIN"].includes(me.role) &&
                  !addingProject && (
                  <button onClick={() => { setAddingProject(true);
                            api("/pms").then(setPms).catch(() => {}); }}
                          style={{ ...ghostButton, padding: "4px 12px",
                                   fontSize: 13 }}>
                    + Project
                  </button>
                )}
                {projects.length > 0 && !project && (
                  <span style={{ fontSize: 12, color: "#b35900" }}>
                    Select a project to create IR / MAR.
                  </span>
                )}
              </div>

              {/* Full project creation (owner: a project deserves more
                  than a one-line form) — dates, PM and scope up front */}
              {addingProject && (
                <section style={{ background: "var(--paper)",
                                  border: "1px dashed var(--line)",
                                  borderRadius: 12, padding: 18,
                                  marginBottom: 16 }}>
                  <h3 style={{ margin: "0 0 12px", color: "var(--navy)",
                               fontSize: 15 }}>
                    New project at {openSite.code}
                  </h3>
                  <div style={{ display: "grid", gap: 10,
                                gridTemplateColumns: "1fr 2fr" }}>
                    <label style={{ fontSize: 13 }}>Project code
                      <input placeholder="e.g. MPOOL" value={projDraft.code}
                             onChange={(e) => setProjDraft({ ...projDraft,
                               code: e.target.value.toUpperCase() })}
                             style={inputStyle} />
                    </label>
                    <label style={{ fontSize: 13 }}>Project title
                      <input placeholder="e.g. Restaurant Pool"
                             value={projDraft.title}
                             onChange={(e) => setProjDraft({ ...projDraft,
                               title: e.target.value })}
                             style={inputStyle} />
                    </label>
                  </div>
                  <div style={{ display: "grid", gap: 10, marginTop: 10,
                                gridTemplateColumns: "1fr 1fr 1fr 1fr" }}>
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
                    <label style={{ fontSize: 13 }}>Planned finish
                      <input type="date"
                             value={projDraft.planned_completion}
                             onChange={(e) => setProjDraft({ ...projDraft,
                               planned_completion: e.target.value })}
                             style={inputStyle} />
                    </label>
                    <label style={{ fontSize: 13 }}>Project PM
                      <select value={projDraft.pm}
                              onChange={(e) => setProjDraft({ ...projDraft,
                                pm: e.target.value })}
                              style={inputStyle}>
                        <option value="">— site PM handles it —</option>
                        {pms.map((u) => (
                          <option key={u.id} value={u.id}>
                            {u.full_name}</option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <label style={{ fontSize: 13, display: "block",
                                  marginTop: 10 }}>
                    Scope / general summary
                    <textarea rows={2} value={projDraft.scope}
                              onChange={(e) => setProjDraft({ ...projDraft,
                                scope: e.target.value })}
                              style={{ ...inputStyle, resize: "vertical" }} />
                  </label>
                  <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                    <button onClick={createProject}
                            disabled={!projDraft.code || !projDraft.title}
                            style={buttonStyle}>
                      Create project
                    </button>
                    <button onClick={() => setAddingProject(false)}
                            style={ghostButton}>Cancel</button>
                    <span style={{ fontSize: 12, color: "var(--faint)",
                                   alignSelf: "center" }}>
                      Programme, manpower requirement and documents are
                      added on the project page after creation.
                    </span>
                  </div>
                </section>
              )}
              <SiteDashboard
                site={openSite} me={me} refresh={refresh} project={project}
                onNewDpr={() => setDocView({ mode: "dpr-form", doc: null })}
                onNewMr={() => setDocView({ mode: "line-form", docType: "MR",
                                            doc: null })}
                onNewQa={(docType) => setDocView({ mode: "qa-form", docType,
                                                   doc: null })}
                onAttendance={() => setDocView({ mode: "attendance" })}
                onDma={() => setDocView({ mode: "dma" })}
                onManpower={() => setDocView({ mode: "manpower" })}
                onNewPyr={() => setDocView({ mode: "pyr-form" })}
                onPyrRegister={() => setDocView({ mode: "pyr-register" })}
                onPettyCash={() => setDocView({ mode: "petty-cash" })}
                onStock={() => setDocView({ mode: "stock" })}
                onTools={() => setDocView({ mode: "tools" })}
                onCreateGrn={createGrn}
                onNewPmr={() => setDocView({ mode: "line-form",
                                            docType: "PMR", doc: null })}
                onOpenDoc={openDoc}
              />
            </>
          )}

          {!docView && !openSite && me.is_ho && hoPage === "dashboard" && (
            <HODashboard me={me} refresh={refresh} onOpenDoc={openDoc}
                         onNewPayment={() => setDocView({
                           mode: "central-pyr-form" })}
                         onPmrRegister={() => setHoPage("pmr-register")}
                         onNew={(docType) => setDocView({ mode: "line-form",
                                                          docType, doc: null })} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "finance-dash" && (
            <FinanceDashboard me={me}
              onVouchers={() => setHoPage("vouchers")}
              onNewPayment={() => setDocView({ mode: "central-pyr-form" })} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "vouchers" && (
            <PaymentVouchersPage me={me} onOpenDoc={openDoc} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "manage" && (
            <SitesManagePage me={me} onChanged={bump} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "items" && (
            <ItemsPage me={me} />
          )}
          {!docView && !openSite &&
            ["HO_PURCHASING", "ADMIN"].includes(me.role) &&
            hoPage === "item-categories" && (
            <ItemCategoriesPage me={me} />
          )}
          {!docView && !openSite && me.is_ho &&
            hoPage === "pmr-register" && (
            <PmrRegister onOpenDoc={openDoc} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "imports" && (
            <ImportOrders me={me} onOpenIpr={(ref) =>
              setDocView({ mode: "ipr-view", doc: { ref } })} />
          )}
          {!docView && !openSite && me.is_ho &&
            hoPage === "import-tracker" && (
            <ImportTracker me={me} onOpenIpr={(ref) =>
              setDocView({ mode: "ipr-view", doc: { ref } })} />
          )}
          {!docView && !openSite && me.is_ho &&
            hoPage === "import-payments" && (
            <ImportPaymentsDue onOpenIpr={(ref) =>
              setDocView({ mode: "ipr-view", doc: { ref } })} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "store" && (
            <StoreLots me={me} onOpenIrn={(ref) =>
              setDocView({ mode: "irn-view", doc: { ref } })} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "suppliers" && (
            <SuppliersPage me={me} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "employees" && (
            <EmployeesPage me={me} sites={sites} />
          )}
          {!docView && !openSite && me.role === "ADMIN" &&
            hoPage === "worker-categories" && (
            <WorkerCategoriesPage me={me} />
          )}
          {!docView && !openSite &&
            ["HO_HR", "ADMIN"].includes(me.role) &&
            hoPage === "overtime-rates" && (
            <OvertimeRatesPage me={me} />
          )}
          {!docView && !openSite && me.role === "ADMIN" &&
            hoPage === "users" && (
            <UsersPage me={me} sites={sites} />
          )}
          {!docView && !openSite &&
            ["HO_HR", "FINANCE", "ADMIN"].includes(me.role) &&
            hoPage === "payroll" && (
            <PayrollRunPage me={me} sites={sites} />
          )}
          {!docView && !openSite &&
            ["HO_HR", "FINANCE", "DIRECTOR", "ADMIN"].includes(me.role) &&
            hoPage === "staff-cost" && (
            <StaffCostPage />
          )}
          {docView?.mode === "attendance" && openSite && (
            <AttendancePage site={openSite} me={me} onClose={closeDoc} />
          )}
          {docView?.mode === "dma" && openSite && (
            <DMAPage site={openSite} me={me} onClose={closeDoc} />
          )}
          {docView?.mode === "manpower" && openSite && (
            <ManpowerPage site={openSite} onClose={closeDoc} />
          )}
          {docView?.mode === "pyr-form" && openSite && (
            <PaymentRequestForm site={openSite} me={me}
              onSaved={(ref) => { bump(); openDoc(ref); }}
              onCancel={closeDoc} />
          )}
          {docView?.mode === "central-pyr-form" && (
            <PaymentRequestForm sites={sites} me={me}
              onSaved={(ref) => { bump(); openDoc(ref); }}
              onCancel={closeDoc} />
          )}
          {docView?.mode === "pyr-view" && (
            <PaymentRequestView doc={docView.doc} me={me} onClose={closeDoc}
              onChanged={() => openDoc(docView.doc.ref)} />
          )}
          {docView?.mode === "pyr-register" && openSite && (
            <PaymentRegisterPage site={openSite} me={me} onOpenDoc={openDoc}
              onNewPyr={() => setDocView({ mode: "pyr-form" })}
              onClose={closeDoc} />
          )}
          {docView?.mode === "petty-cash" && openSite && (
            <PettyCashPage site={openSite} me={me} onOpenDoc={openDoc}
              onClose={closeDoc} />
          )}
          {docView?.mode === "stock" && openSite && (
            <StockPage site={openSite} me={me} onClose={closeDoc} />
          )}
          {docView?.mode === "tools" && openSite && (
            <ToolsPage site={openSite} me={me} onClose={closeDoc} />
          )}
          {!docView && !openSite &&
            ["DIRECTOR", "ADMIN"].includes(me.role) && hoPage === "pms" && (
            <PmsPage me={me} sites={sites} />
          )}
          {!docView && !openSite && me.role === "ADMIN" &&
            hoPage === "company" && (
            <CompanyPage />
          )}
          {!docView && !openSite &&
            (!showHoNav || hoPage === "sites") && (
            <SiteList sites={sites} onOpen={setOpenSite} />
          )}
        </main>
      )}
    </div>
  );
}
