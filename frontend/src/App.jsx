import { useEffect, useState } from "react";
import { api } from "./api.js";
import DPRForm from "./DPRForm.jsx";
import DPRView from "./DPRView.jsx";
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
          Username
        </label>
        <input value={username} onChange={(e) => setUsername(e.target.value)}
               autoFocus style={inputStyle} />
        <label style={{ display: "block", fontSize: 13, margin: "12px 0 4px" }}>
          Password
        </label>
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

export default function App() {
  const [me, setMe] = useState(null);
  const [sites, setSites] = useState([]);
  const [openSite, setOpenSite] = useState(null);
  const [docView, setDocView] = useState(null); // {mode:'form'|'view', doc}
  const [refresh, setRefresh] = useState(0);

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
    const doc = await api(`/documents/${ref}`);
    setDocView({ mode: "view", doc });
  }

  function bumpAndClose() {
    setDocView(null);
    setRefresh((n) => n + 1);
  }

  if (me === null) return null;

  return (
    <div>
      <header style={{ background: "var(--sp-navy)", color: "#fff",
                       padding: "14px 28px",
                       borderBottom: "4px solid var(--sp-sky)",
                       display: "flex", alignItems: "baseline", gap: 12 }}>
        <h1 style={{ margin: 0, fontSize: 20, letterSpacing: 0.5,
                     cursor: "pointer" }}
            onClick={() => { setDocView(null);
                             if (!me.landing_site_id) setOpenSite(null); }}>
          SAND PLANET
        </h1>
        <span style={{ color: "var(--sp-sky)", fontSize: 14 }}>Site Documents</span>
        {me.authenticated && (
          <span style={{ marginLeft: "auto", fontSize: 13 }}>
            {me.full_name} · {me.role.replace(/_/g, " ")}
            <button onClick={logoutUser}
                    style={{ marginLeft: 14, background: "transparent",
                             color: "var(--sp-sky)",
                             border: "1px solid var(--sp-sky)", borderRadius: 6,
                             padding: "3px 10px", cursor: "pointer",
                             fontSize: 12 }}>
              Sign out
            </button>
          </span>
        )}
      </header>

      {!me.authenticated ? (
        <Login onLogin={setMe} />
      ) : (
        <main style={{ maxWidth: 900, margin: "32px auto", padding: "0 16px" }}>
          {!openSite && <SiteList sites={sites} onOpen={setOpenSite} />}

          {openSite && !docView && (
            <>
              <div style={{ display: "flex", justifyContent: "space-between",
                            alignItems: "baseline", marginBottom: 16 }}>
                <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
                  {openSite.code} — {openSite.name}{" "}
                  <StatusChip status={openSite.status} />
                </h2>
                {(sites.length > 1 && (me.is_ho || me.allocations.length > 1)) && (
                  <button onClick={() => setOpenSite(null)} style={ghostButton}>
                    ← All sites
                  </button>
                )}
              </div>
              <SiteDashboard
                site={openSite} me={me} refresh={refresh}
                onNewDpr={() => setDocView({ mode: "form", doc: null })}
                onOpenDoc={openDoc}
              />
            </>
          )}

          {openSite && docView?.mode === "form" && (
            <DPRForm site={openSite} existing={docView.doc}
                     onSaved={bumpAndClose} onCancel={bumpAndClose} />
          )}

          {openSite && docView?.mode === "view" && (
            <DPRView doc={docView.doc} me={me}
                     onClose={bumpAndClose}
                     onChanged={() => setRefresh((n) => n + 1)}
                     onEdit={(doc) => setDocView({ mode: "form", doc })} />
          )}
        </main>
      )}
    </div>
  );
}
