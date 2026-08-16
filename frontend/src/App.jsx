import { useEffect, useState } from "react";
import { api } from "./api.js";
import DPRForm from "./DPRForm.jsx";
import DPRView from "./DPRView.jsx";
import HODashboard from "./HODashboard.jsx";
import ItemsPage from "./ItemsPage.jsx";
import ItemCategoriesPage from "./ItemCategoriesPage.jsx";
import LiveFeedsPage from "./LiveFeedsPage.jsx";
import WorkerCategoriesPage from "./WorkerCategoriesPage.jsx";
import OvertimeRatesPage from "./OvertimeRatesPage.jsx";
import SuppliersPage from "./SuppliersPage.jsx";
import ImportOrders, { IprView, IprForm, IrnView, StoreLots,
  ImportPaymentsDue, ImportTracker } from "./ImportOrders.jsx";
import NotificationBell from "./NotificationBell.jsx";
import { VesselsPage } from "./Vessels.jsx";
import ClientUsersPage from "./ClientUsersPage.jsx";
import EmployeesPage from "./EmployeesPage.jsx";
import HeadOfficePage from "./HeadOfficePage.jsx";
import OnboardingPage from "./OnboardingPage.jsx";
import BvRegisterPage from "./BvRegisterPage.jsx";
import AppointmentSignoff from "./AppointmentSignoff.jsx";
import ProcurementSchedulePage from "./ProcurementSchedulePage.jsx";
import UsersPage from "./UsersPage.jsx";
import PayrollRunPage from "./PayrollRunPage.jsx";
import ProgrammePage from "./ProgrammePage.jsx";
import SitesManagePage from "./SitesManagePage.jsx";
import AttendancePage from "./AttendancePage.jsx";
import WorkforcePage from "./WorkforcePage.jsx";
import DMAPage from "./DMAPage.jsx";
import ManpowerPage from "./ManpowerPage.jsx";
import ProjectPage from "./ProjectPage.jsx";
import PaymentRequestForm from "./PaymentRequestForm.jsx";
import PaymentRequestView from "./PaymentRequestView.jsx";
import PaymentRegisterPage from "./PaymentRegisterPage.jsx";
import MyPaymentRequests from "./MyPaymentRequests.jsx";
import MeetingsPage from "./MeetingsPage.jsx";
import CostControlPage from "./CostControlPage.jsx";
import FinanceDashboard from "./FinanceDashboard.jsx";
import ReceivablesPage from "./ReceivablesPage.jsx";
import PmrRegister from "./PmrRegister.jsx";
import PaymentVouchersPage from "./PaymentVouchersPage.jsx";
import PayablesPage from "./PayablesPage.jsx";
import PettyCashPage from "./PettyCashPage.jsx";
import StaffCostPage from "./StaffCostPage.jsx";
import StockPage from "./StockPage.jsx";
import TransfersPanel from "./TransfersPanel.jsx";
import ToolsPage from "./ToolsPage.jsx";
import PmsPage from "./PmsPage.jsx";
import CompanyPage from "./CompanyPage.jsx";
import ActivityPage from "./ActivityPage.jsx";
import ProfilePage from "./ProfilePage.jsx";
import ApprovalsPage from "./ApprovalsPage.jsx";
import HRDashboard from "./HRDashboard.jsx";
import PortfolioPage from "./PortfolioPage.jsx";

// Grouped menu (owner, 2026-07-08): five top-level groups, trimmed by
// role; approver roles land on the Approvals queue.
const APPROVERS = ["PM", "HO_PURCHASING", "DIRECTOR", "SIGNATORY",
                   "FINANCE", "ADMIN"];
// Company Profile is office-only marketing; MARKETING is a minimal role that
// sees ONLY this section.
const PROFILE_ROLES = ["ADMIN", "DIRECTOR", "SIGNATORY", "MARKETING", "PA"];
// Who could reach the overseas import chain before Procurement absorbed the
// Planning tab. Spelled out so widening the GROUP never widens these pages.
const IMPORT_CHAIN = ["HO_PURCHASING", "DIRECTOR", "FINANCE", "ADMIN", "QS",
                      "PA", "SIGNATORY"];
// The authorised signatory signs every rufiyaa out of the company, so they
// READ every module — HR, payroll, procurement, finance, onboarding — and were
// being stopped at half of them (owner 2026-08-16). Read only: each page still
// gates its own buttons, and the backend gates the writes. Deliberately NOT
// widened: Users / Settings / Login & Audit and the master-data editors
// (item + worker categories, OT rates), which are Admin's configuration.
const NAV_GROUPS = [
  // Not everything in the queue is an approval (DMA issues, MRs to
  // action, payments) — "My Tasks", not "Approvals" (owner, 2026-07-08)
  // HO_HR is in this group only for their own payment requests, which used to
  // be a separate "My Requests" tab — everything else names its roles.
  { key: "approvals", label: "My Tasks",
    roles: [...APPROVERS, "QS", "PA", "HO_HR"],
    subs: [["approvals", "My Tasks", APPROVERS],
           ["portfolio", "Portfolio", ["DIRECTOR", "ADMIN", "QS",
                                       "SIGNATORY", "PA"]],
           ["cost", "Project Cost", ["DIRECTOR", "FINANCE", "ADMIN", "QS",
                                     "SIGNATORY", "PA"]],
           // Head-Office raisers have no site register to fall back on, so
           // their own payment requests would vanish on submit — this is
           // their tracking view.
           ["my-pyr", "My Payment Requests",
            ["HO_PURCHASING", "HO_HR", "QS", "DIRECTOR", "SIGNATORY",
             "FINANCE", "ADMIN"]]] },
  // Live Feeds lives here rather than as its own tab: it is a view OF sites,
  // and site staff reach their own camera from the same place they reach
  // their site (owner 2026-08-12). Backend scopes it to sites they can see.
  { key: "sitesGrp", label: "Sites", roles: null,
    subs: [["sites", "Sites", null],
           ["live-feeds", "Live Feeds", null]] },
  { key: "procurement", label: "Procurement",
    // PM is here ONLY for the Procurement Schedule, which used to be its own
    // "Planning" tab. Every page below therefore names its roles explicitly —
    // leaving them null would silently hand PMs the whole import chain, which
    // they have never been able to see. SIGNATORY reads all of it (see above).
    roles: ["HO_PURCHASING", "DIRECTOR", "FINANCE", "ADMIN", "QS", "PA",
            "PM", "SIGNATORY"],
    // QS shares the Director's overseas-procurement authority, so it only sees
    // the import chain (Requests / Orders / Tracker / Store), not domestic
    // purchasing pages (owner 2026-07-14). PA views everything (read-only).
    subs: [["dashboard", "Purchasing Dashboard",
            ["HO_PURCHASING", "DIRECTOR", "FINANCE", "ADMIN", "PA",
             "SIGNATORY"]],
           ["items", "Items",
            ["HO_PURCHASING", "DIRECTOR", "FINANCE", "ADMIN", "PA",
             "SIGNATORY"]],
           ["item-categories", "Item Categories",
            ["HO_PURCHASING", "ADMIN", "PA"]],
           ["pmr-register", "Import Requests", IMPORT_CHAIN],
           ["imports", "International Orders", IMPORT_CHAIN],
           ["import-tracker", "Import Tracker", IMPORT_CHAIN],
           ["store", "HO Store", IMPORT_CHAIN],
           ["suppliers", "Suppliers",
            ["HO_PURCHASING", "DIRECTOR", "FINANCE", "ADMIN", "PA",
             "SIGNATORY"]],
           ["procurement-schedule", "Procurement Schedule",
            ["PM", "HO_PURCHASING", "DIRECTOR", "SIGNATORY", "QS", "ADMIN",
             "PA"]]] },
  { key: "meetingsGrp", label: "Meetings",
    roles: ["DIRECTOR", "ADMIN", "PM", "SITE_ADMIN", "SITE_ENGINEER", "QS",
            "MARKETING", "HO_PURCHASING", "SIGNATORY", "PA"],
    subs: [["meetings", "Meetings", null]] },
  { key: "finance", label: "Finance",
    roles: ["FINANCE", "SIGNATORY", "ADMIN", "DIRECTOR", "QS", "PA"],
    subs: [["finance-dash", "Dashboard", ["FINANCE", "ADMIN", "SIGNATORY"]],
           ["vouchers", "Payment Vouchers", ["FINANCE", "SIGNATORY",
                                             "ADMIN"]],
           ["payables", "Payables", ["FINANCE", "ADMIN", "SIGNATORY"]],
           ["import-payments", "Import Payments", ["FINANCE", "ADMIN",
                                                   "SIGNATORY"]],
           ["receivables", "Receivables", ["FINANCE", "DIRECTOR", "ADMIN",
                                           "QS", "PA", "SIGNATORY"]]] },
  { key: "people", label: "People",
    roles: ["HO_HR", "FINANCE", "DIRECTOR", "ADMIN", "PM", "PA", "SIGNATORY"],
    subs: [["hr", "HR Dashboard", ["HO_HR", "FINANCE", "ADMIN", "PA",
                                   "SIGNATORY"]],
           ["onboarding", "Onboarding", ["HO_HR", "DIRECTOR", "ADMIN", "PM",
                                         "PA", "SIGNATORY"]],
           ["bv-register", "Business Visas", ["HO_HR", "DIRECTOR", "ADMIN",
                                              "PA", "SIGNATORY"]],
           ["appointment-signoff", "Appointment Sign-off",
            ["SIGNATORY", "ADMIN"]],
           ["employees", "Employees", null],
           ["ho-staff", "Head Office", ["HO_HR", "FINANCE", "DIRECTOR",
                                        "ADMIN", "PA", "SIGNATORY"]],
           ["worker-categories", "Worker Categories", ["ADMIN", "PA"]],
           ["overtime-rates", "Overtime Rates", ["HO_HR", "ADMIN", "PA"]],
           ["payroll", "Payroll", ["HO_HR", "FINANCE", "ADMIN", "PA",
                                   "SIGNATORY"]],
           ["staff-cost", "Staff Cost",
            ["HO_HR", "FINANCE", "DIRECTOR", "ADMIN", "PA", "SIGNATORY"]],
           ["pms", "PMs", ["DIRECTOR", "ADMIN", "SIGNATORY"]]] },
  // "Company", not "Admin": Company Profile folds in here, and MARKETING is a
  // minimal role that sees ONLY that page — labelling their whole app "Admin"
  // would be plainly wrong. Every page below still names its own roles, so
  // widening the group to the profile audience exposes nothing else.
  { key: "adminGrp", label: "Company",
    roles: ["DIRECTOR", "ADMIN", ...PROFILE_ROLES],
    subs: [["manage", "Site Setup", ["DIRECTOR", "ADMIN"]],
           ["users", "Users", ["ADMIN"]],
           ["client-portal", "Client Portal", ["ADMIN"]],
           ["company", "Settings", ["ADMIN"]],
           ["activity", "Login & Audit", ["ADMIN"]],
           ["profile", "Company Profile", PROFILE_ROLES]] },
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
  if (me.role === "MARKETING") return "profile";
  if (me.role === "PA") return "meetings";   // her main workspace
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

// The landing page for most people. A list of codes and names answers "what
// exists" when the question is "where is everyone", so a site is a tile: the
// code, who runs it, and how many are stationed there (owner 2026-08-15).
const SITE_BANDS = [
  ["ACTIVE", "Active"],
  ["AWARDED", "Awarded — not started"],
  ["ON_HOLD", "On hold"],
];
// The accent stripe carries the status, so an active tile spends its room on
// the number instead of a chip.
const SITE_ACCENT = { ACTIVE: "#1a7f37", AWARDED: "#2f6f9f",
                      ON_HOLD: "#b35900" };

function SiteTile({ s, onOpen }) {
  return (
    <button onClick={() => onOpen(s)} title={`${s.code} — ${s.name}`}
      style={{ background: "#fff", cursor: "pointer", textAlign: "center",
               border: "1px solid var(--sp-border)", borderRadius: 10,
               borderTop: `3px solid ${SITE_ACCENT[s.status] || "#8a94a0"}`,
               padding: "6px 5px", display: "flex", flexDirection: "column",
               alignItems: "center", justifyContent: "center", gap: 2,
               font: "inherit", aspectRatio: "1 / 1", overflow: "hidden",
               width: "100%" }}>
      {/* exactly two lines, so a long resort name ellipsises rather than
          being sliced in half by the tile's edge */}
      <div style={{ fontSize: 8.5, color: "#6b7a86", lineHeight: 1.2,
                    height: "2.4em", flexShrink: 0, width: "100%",
                    display: "-webkit-box", WebkitLineClamp: 2,
                    WebkitBoxOrient: "vertical", overflow: "hidden" }}>
        {s.name}
      </div>
      <div style={{ fontWeight: 700, color: "var(--sp-navy)", fontSize: 19,
                    letterSpacing: .5, lineHeight: 1.05, flexShrink: 0 }}>
        {s.code}
      </div>
      <div style={{ fontSize: 8.5, color: "#8a94a0", whiteSpace: "nowrap",
                    overflow: "hidden", textOverflow: "ellipsis",
                    flexShrink: 0, width: "100%" }}>
        {s.pms?.length ? s.pms[0] : "\u00a0"}
      </div>
    </button>
  );
}

function SiteList({ sites, onOpen }) {
  const [live, setLive] = useState(null);
  useEffect(() => {
    api("/sites/summary").then((d) => setLive(d.sites)).catch(() => {});
  }, []);
  // Fall back to the plain list the moment the summary is unavailable — this
  // is the first screen after signing in and it must never be a blank page.
  const rows = live || sites.map((s) => ({ ...s, workforce: "–", pms: [] }));
  const bands = SITE_BANDS
    .map(([status, title]) => [title, rows.filter((s) => s.status === status)])
    .filter(([, list]) => list.length);
  const rest = rows.filter(
    (s) => !SITE_BANDS.some(([status]) => status === s.status));
  if (rest.length) bands.push(["Other", rest]);

  return (
    <section style={card}>
      <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
        Sites &amp; projects
      </h2>
      {bands.map(([title, list]) => (
        <div key={title} style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#6b7a86",
                        textTransform: "uppercase", letterSpacing: .5,
                        margin: "0 0 8px" }}>
            {title} <span style={{ fontWeight: 500 }}>({list.length})</span>
          </div>
          {/* clamp, not a fixed minimum: three to a phone row without
              scattering a dozen thumbnails across a desktop. */}
          <div style={{ display: "grid", gap: 7,
                        gridTemplateColumns:
                          "repeat(auto-fill, minmax(clamp(76px, 19vw, 124px),"
                          + " 1fr))" }}>
            {list.map((s) => (
              <SiteTile key={s.id} s={s} onOpen={onOpen} />
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}

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
  // Set when a payroll run is opened straight from My Tasks. A PM has no
  // Payroll nav entry and can't list runs, but they must be able to reach the
  // one run that is waiting on them (owner 2026-08-12).
  const [payrollRunId, setPayrollRunId] = useState(null);
  // Set when a voucher is opened straight from My Tasks, so the vouchers page
  // expands it instead of showing the list.
  const [voucherRef, setVoucherRef] = useState(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [docView, setDocView] = useState(null);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState(null);
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    if (me?.authenticated) setHoPage(landingPage(me));
  }, [me]);

  // Escape closes the drawer, and it must never be left open behind a page
  // the user reached some other way (a notification, an approval card).
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e) => { if (e.key === "Escape") setMenuOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

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
                 : ["IR", "MAR", "SD", "MS", "TWS"].includes(doc.doc_type)
                   ? "qa-view"
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

  // PMs get the grouped nav too (Approvals + Sites); site users (Site Admin /
  // Engineer) get a minimal Sites + Meetings nav so they can reach their
  // site's meeting minutes (owner 2026-08-02) — backend already scopes them.
  const showHoNav = me.authenticated && (me.is_ho || me.role === "PM"
                    || me.role === "MARKETING" || me.role === "SITE_ADMIN"
                    || me.role === "SITE_ENGINEER");
  const groups = me.authenticated ? visibleGroups(me) : [];
  const activeGroup = groups.find((g) =>
    g.subs.some(([key]) => key === hoPage));

  function openApprovalItem(item) {
    if (item.doc_type === "DMA") {
      const site = sites.find((s) => s.code === item.site_code);
      if (site) { setOpenSite(site); setDocView({ mode: "dma" }); }
      return;
    }
    // A payroll run is not a Document — sending its label to the document
    // viewer is what made PMs see "Not found." Open the run itself.
    if (item.doc_type === "PAY") {
      setDocView(null);
      setOpenSite(null);
      setPayrollRunId(item.run_id);
      setHoPage("payroll");
      return;
    }
    // A payment voucher has no document lines at all — the batch lives in
    // voucher lines — so the document viewer drew a header and nothing else.
    // The signatory tapped Open PV and got a blank page (owner 2026-08-16).
    if (item.doc_type === "PV") {
      setDocView(null);
      setOpenSite(null);
      setVoucherRef(item.ref);
      setHoPage("vouchers");
      return;
    }
    // An import order is authorised on its own screen, not in the document
    // viewer — so tapping it in My Tasks used to land the signatory somewhere
    // with no Authorise button, and they had to go and find the order
    // themselves (owner 2026-08-15).
    if (item.doc_type === "IPR") {
      setOpenSite(null);
      setDocView({ mode: "ipr-view", doc: { ref: item.ref } });
      return;
    }
    // An appointment sign-off is not done in the document viewer either — the
    // signatory has their own limited screen for it, which My Tasks never
    // pointed at (owner 2026-08-15).
    if (item.doc_type === "OBR" && item.status === "IN_PROGRESS") {
      setDocView(null);
      setOpenSite(null);
      setHoPage("appointment-signoff");
      return;
    }
    openDoc(item.ref);
  }

  return (
    <div>
      <header className="topbar">
        {showHoNav && (
          <button className="navtoggle" aria-label="Menu"
                  aria-expanded={menuOpen}
                  onClick={() => setMenuOpen((o) => !o)}>
            <span aria-hidden="true">{menuOpen ? "✕" : "☰"}</span>
            {!menuOpen && pendingCount > 0 && (
              <span className="nav-badge nav-badge-dot" />
            )}
          </button>
        )}
        <div className="brand"
             onClick={() => { setDocView(null); setHoPage(landingPage(me));
                              if (!me.landing_site_id) setOpenSite(null); }}>
          <h1 className="brand-name">SAND PLANET</h1>
          <span className="brand-sub">Project Management</span>
        </div>
        {showHoNav && (
          <nav className="navtabs">
            {groups.map((g) => (
              <button key={g.key}
                      className={"navtab" +
                        (activeGroup?.key === g.key && !openSite && !docView
                          ? " active" : "")}
                      onClick={() => { setHoPage(g.subs[0][0]);
                                       setOpenSite(null);
                                       setDocView(null); }}>
                {g.label}
                {g.key === "approvals" && pendingCount > 0 && (
                  <span className="nav-badge">{pendingCount}</span>
                )}
              </button>
            ))}
          </nav>
        )}
        {me.authenticated && (
          <div className="topbar-right">
            <NotificationBell onOpen={(ref, docType) => {
              if (docType === "PV") { setDocView(null); setOpenSite(null);
                                      setHoPage("vouchers"); }
              else openDoc(ref);
            }} />
            <span className="user-chip">
              <span className="u-name">{me.full_name}</span>
              <span className="u-role">{me.role.replace(/_/g, " ")}</span>
            </span>
            <button className="signout-btn" onClick={logoutUser}>
              Sign out
            </button>
          </div>
        )}
      </header>

      {/* Phone navigation: one tap to any page, instead of tab-then-subtab
          through a header that had nowhere near enough room for either. */}
      {menuOpen && (
        <div className="navdrawer-scrim" onClick={() => setMenuOpen(false)}>
          <nav className="navdrawer" onClick={(e) => e.stopPropagation()}>
            {groups.map((g) => (
              <div key={g.key} className="nd-group">
                <div className="nd-title">
                  {g.label}
                  {g.key === "approvals" && pendingCount > 0 && (
                    <span className="nav-badge">{pendingCount}</span>
                  )}
                </div>
                {g.subs.map(([key, label]) => (
                  <button key={key}
                          className={"nd-item" + (hoPage === key && !openSite
                                                  && !docView ? " on" : "")}
                          onClick={() => { setHoPage(key); setOpenSite(null);
                                           setDocView(null);
                                           setMenuOpen(false); }}>
                    {label}
                  </button>
                ))}
              </div>
            ))}
          </nav>
        </div>
      )}

      {!me.authenticated ? (
        <Login onLogin={setMe} />
      ) : me.must_change_password ? (
        <ChangePassword forced onDone={() =>
          api("/auth/me").then(setMe)} />
      ) : (
        <main style={{ maxWidth:
                         ["attendance", "workforce", "dma"].includes(docView?.mode)
                         || (!docView && hoPage === "meetings")
                           ? 1160
                         // The salary grid is 17 columns wide — at the 900px
                         // default it hid ~400px of every row behind a
                         // scrollbar, which is no way to check pay (owner
                         // 2026-08-13). maxWidth only caps, so a laptop still
                         // uses its full window.
                         : (!docView && hoPage === "payroll")
                           ? 1800
                         : (docView?.mode === "project"
                            || (!docView && hoPage === "procurement-schedule"))
                           ? 1500
                         : (!docView && hoPage === "employees")
                           ? 1300
                         : 900,
                       margin: "28px auto", padding: "0 20px" }}>
          {error && <p style={{ color: "#c0392b" }}>{error}</p>}

          {/* On a phone the drawer already lists every page, so this second
              row is redundant there — and it was one of the two rows making
              the header unusable (owner 2026-08-12). Its layout lives in CSS,
              not inline: an inline `display` would outrank the media query
              that hides it. */}
          {!docView && !openSite && activeGroup &&
            activeGroup.subs.length > 1 && (
            <div className="subtabs">
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
            ["DIRECTOR", "FINANCE", "ADMIN", "QS", "SIGNATORY", "PA"]
              .includes(me.role) &&
            hoPage === "cost" && (
            <CostControlPage onOpenDoc={openDoc} me={me} />
          )}
          {!docView && !openSite &&
            ["DIRECTOR", "ADMIN", "QS", "SIGNATORY", "PA"].includes(me.role) &&
            hoPage === "portfolio" && (
            <PortfolioPage refresh={refresh}
                           onOpenProject={(id) => setDocView({
                             mode: "project", projectId: id })} />
          )}
          {!docView && !openSite &&
            ["HO_HR", "FINANCE", "ADMIN", "PA", "SIGNATORY"].includes(me.role) &&
            hoPage === "hr" && (
            <HRDashboard me={me} refresh={refresh}
              onNewPayment={["HO_HR", "FINANCE", "ADMIN", "PA"].includes(me.role)
                ? () => setDocView({ mode: "central-pyr-form" }) : null} />
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
                     onOpenDoc={openDoc}
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
          {docView?.mode === "vessels" && (
            <VesselsPage onClose={closeDoc} />
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
                    Select a project to create IR / MAR / SD / MS.
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
                onWorkforce={() => setDocView({ mode: "workforce" })}
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
                onVessels={() => setDocView({ mode: "vessels" })}
              />
            </>
          )}

          {!docView && !openSite && me.is_ho && hoPage === "dashboard" && (
            <HODashboard me={me} refresh={refresh} onOpenDoc={openDoc}
                         onNewPayment={() => setDocView({
                           mode: "central-pyr-form" })}
                         onPmrRegister={() => setHoPage("pmr-register")}
                         onVessels={() => setDocView({ mode: "vessels" })}
                         onNew={(docType) => setDocView({ mode: "line-form",
                                                          docType, doc: null })} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "finance-dash" && (
            <FinanceDashboard me={me}
              onVouchers={() => setHoPage("vouchers")}
              onNewPayment={["FINANCE", "ADMIN"].includes(me.role)
                ? () => setDocView({ mode: "central-pyr-form" }) : null} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "vouchers" && (
            <PaymentVouchersPage me={me} onOpenDoc={openDoc}
                                 openRef={voucherRef} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "payables" && (
            <PayablesPage me={me} onOpenDoc={openDoc} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "my-pyr" && (
            <MyPaymentRequests me={me} onOpenDoc={openDoc} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "manage" && (
            <SitesManagePage me={me} onChanged={bump} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "items" && (
            <ItemsPage me={me} />
          )}
          {/* not gated on is_ho — site staff watch their own site's cameras */}
          {!docView && !openSite && hoPage === "live-feeds" && (
            <LiveFeedsPage me={me} />
          )}
          {!docView && !openSite &&
            ["HO_PURCHASING", "ADMIN", "PA"].includes(me.role) &&
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
          {!docView && !openSite &&
            ["FINANCE", "DIRECTOR", "ADMIN", "QS", "PA",
             "SIGNATORY"].includes(me.role) &&
            hoPage === "receivables" && (
            <ReceivablesPage me={me} />
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
          {!docView && !openSite &&
            ["HO_HR", "FINANCE", "DIRECTOR", "ADMIN", "PA",
             "SIGNATORY"].includes(me.role) &&
            hoPage === "ho-staff" && (
            <HeadOfficePage me={me} sites={sites} />
          )}
          {!docView && !openSite &&
            ["ADMIN", "PA"].includes(me.role) &&
            hoPage === "worker-categories" && (
            <WorkerCategoriesPage me={me} />
          )}
          {!docView && !openSite &&
            ["HO_HR", "ADMIN", "PA"].includes(me.role) &&
            hoPage === "overtime-rates" && (
            <OvertimeRatesPage me={me} />
          )}
          {!docView && !openSite && me.role === "ADMIN" &&
            hoPage === "users" && (
            <UsersPage me={me} sites={sites} />
          )}
          {!docView && !openSite && hoPage === "payroll" &&
            (["HO_HR", "FINANCE", "ADMIN", "PA", "SIGNATORY"].includes(me.role)
             || payrollRunId) && (
            <PayrollRunPage me={me} sites={sites} initialRunId={payrollRunId}
              onLeaveRun={() => {
                setPayrollRunId(null);
                bump();                     // the run may have just been acted on
                if (!["HO_HR", "FINANCE", "ADMIN", "PA",
                      "SIGNATORY"].includes(me.role)) {
                  setHoPage("approvals");   // PMs have nowhere else to land
                }
              }} />
          )}
          {!docView && !openSite &&
            ["HO_HR", "FINANCE", "DIRECTOR", "ADMIN", "PA",
             "SIGNATORY"].includes(me.role) &&
            hoPage === "staff-cost" && (
            <StaffCostPage />
          )}
          {!docView && !openSite &&
            ["HO_HR", "DIRECTOR", "ADMIN", "PM", "PA",
             "SIGNATORY"].includes(me.role) &&
            hoPage === "onboarding" && (
            <OnboardingPage me={me} sites={sites} />
          )}
          {!docView && !openSite &&
            ["HO_HR", "DIRECTOR", "ADMIN", "PA", "SIGNATORY"].includes(me.role) &&
            hoPage === "bv-register" && (
            <BvRegisterPage me={me} />
          )}
          {!docView && !openSite &&
            ["SIGNATORY", "ADMIN"].includes(me.role) &&
            hoPage === "appointment-signoff" && (
            <AppointmentSignoff />
          )}
          {!docView && !openSite &&
            ["PM", "HO_PURCHASING", "DIRECTOR", "SIGNATORY", "QS", "ADMIN", "PA"]
              .includes(me.role) &&
            hoPage === "procurement-schedule" && (
            <ProcurementSchedulePage me={me} sites={sites}
              onOpenDoc={openDoc} />
          )}
          {!docView && !openSite &&
            ["DIRECTOR", "ADMIN", "PM", "SITE_ADMIN", "SITE_ENGINEER", "QS",
             "MARKETING", "HO_PURCHASING", "SIGNATORY", "PA"].includes(me.role)
            && hoPage === "meetings" && (
            <MeetingsPage me={me} />
          )}
          {docView?.mode === "attendance" && openSite && (
            <AttendancePage site={openSite} me={me} onClose={closeDoc} />
          )}
          {docView?.mode === "workforce" && openSite && (
            <WorkforcePage site={openSite} me={me} onClose={closeDoc} />
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
            <>
              <StockPage key={`stock-${refresh}`} site={openSite} me={me}
                         onClose={closeDoc} />
              {/* Transfers sit under the ledger they move: a storeman looking
                  at what is on site is the person sending it elsewhere. The
                  ledger is remounted when one lands, so the on-hand above
                  never contradicts the transfer just actioned below. */}
              <TransfersPanel site={openSite} me={me} sites={sites}
                              onStockMoved={() => setRefresh((n) => n + 1)} />
            </>
          )}
          {docView?.mode === "tools" && openSite && (
            <ToolsPage site={openSite} me={me} onClose={closeDoc} />
          )}
          {!docView && !openSite &&
            ["DIRECTOR", "ADMIN", "SIGNATORY"].includes(me.role) && hoPage === "pms" && (
            <PmsPage me={me} sites={sites} />
          )}
          {!docView && !openSite && me.role === "ADMIN" &&
            hoPage === "company" && (
            <CompanyPage me={me} />
          )}
          {!docView && !openSite && me.role === "ADMIN" &&
            hoPage === "client-portal" && (
            <ClientUsersPage sites={sites} />
          )}
          {!docView && !openSite && me.role === "ADMIN" &&
            hoPage === "activity" && (
            <ActivityPage />
          )}
          {!docView && !openSite && PROFILE_ROLES.includes(me.role) &&
            hoPage === "profile" && (
            <ProfilePage />
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
