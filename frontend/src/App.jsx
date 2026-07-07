import { useEffect, useState } from "react";
import { api } from "./api.js";
import DPRForm from "./DPRForm.jsx";
import DPRView from "./DPRView.jsx";
import HODashboard from "./HODashboard.jsx";
import ItemsPage from "./ItemsPage.jsx";
import SuppliersPage from "./SuppliersPage.jsx";
import { LineDocForm, LineDocView } from "./LineDoc.jsx";
import { QADocView, QAForm } from "./QADocs.jsx";
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
          Site Documents</span>
        {showHoNav && (
          <nav style={{ display: "flex", gap: 4 }}>
            {[["dashboard", "HO Dashboard"], ["sites", "Sites"],
              ["items", "Items"], ["suppliers", "Suppliers"]]
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
            <DPRForm site={openSite} existing={docView.doc}
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
                         onChanged={bump}
                         onEdit={(doc) => setDocView({
                           mode: "line-form", docType: doc.doc_type, doc })} />
          )}
          {docView?.mode === "qa-form" && (
            <QAForm docType={docView.docType} site={openSite}
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

          {!docView && openSite && (
            <>
              <div style={{ display: "flex", justifyContent: "space-between",
                            alignItems: "baseline", marginBottom: 16 }}>
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
              <SiteDashboard
                site={openSite} me={me} refresh={refresh}
                onNewDpr={() => setDocView({ mode: "dpr-form", doc: null })}
                onNewMr={() => setDocView({ mode: "line-form", docType: "MR",
                                            doc: null })}
                onNewQa={(docType) => setDocView({ mode: "qa-form", docType,
                                                   doc: null })}
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
          {!docView && !openSite && me.is_ho && hoPage === "items" && (
            <ItemsPage me={me} />
          )}
          {!docView && !openSite && me.is_ho && hoPage === "suppliers" && (
            <SuppliersPage me={me} />
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
