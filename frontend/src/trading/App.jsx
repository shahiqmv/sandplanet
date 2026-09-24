// Sand Planet Trading — app shell: session gate, navigation, pages.
//
// The trading arm lives on the Planet backend but on its own surface
// (TRADING_BUILD_BRIEF.md §5): a Sales user signs in here and sees only
// trading; a site role that lands here is sent back to Planet. Finance,
// the Signatory and Admin can enter both worlds.
import { useEffect, useState } from "react";
import { api, resetSessionNotice, SESSION_EXPIRED } from "../api.js";
import { Btn, card } from "../ui.jsx";
import CustomersPage from "./CustomersPage.jsx";
import SuppliersPage from "./SuppliersPage.jsx";

const TRADING_ROLES = new Set(["SALES", "SALES_MANAGER"]);
const READERS = new Set([...TRADING_ROLES, "FINANCE", "SIGNATORY", "ADMIN"]);
const WRITERS = new Set(["SALES", "SALES_MANAGER", "ADMIN"]);

const PAGES = [
  ["home", "Dashboard"],
  ["inquiries", "Inquiries"],
  ["customers", "Customers"],
  ["suppliers", "Suppliers"],
];

const ROLE_LABEL = {
  SALES: "Sales",
  SALES_MANAGER: "Sales Manager",
  FINANCE: "Finance",
  SIGNATORY: "Signatory",
  ADMIN: "Admin",
};

// The main app's own origin: /t/ in production is served beside /, and the
// Vite dev server serves index.html at /.
const PLANET_URL = "/";

function pageFromHash() {
  const key = (window.location.hash || "").replace(/^#\/?/, "").split("/")[0];
  return PAGES.some(([k]) => k === key) ? key : "home";
}

function Login({ onLogin, expired }) {
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
    <div className="t-login">
      <form onSubmit={submit} style={card}>
        <div className="t-brand" style={{ marginBottom: 14 }}>
          <span className="t-brand-name">Sand Planet</span>
          <span className="t-brand-arm">Trading</span>
        </div>
        <h2 style={{ marginTop: 0, color: "var(--sp-navy)" }}>Sign in</h2>
        {expired && (
          <p className="t-note t-note-amber">
            Your session has expired — sign in again to carry on.
          </p>
        )}
        <label className="t-field">
          <span>Username</span>
          <input value={username} autoFocus autoComplete="username"
                 onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label className="t-field">
          <span>Password</span>
          <input type="password" value={password} autoComplete="current-password"
                 onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <p className="t-note t-note-red">{error}</p>}
        <Btn type="submit" disabled={busy || !username || !password}
             style={{ width: "100%", marginTop: 8 }}>
          {busy ? "Signing in…" : "Sign in"}
        </Btn>
      </form>
    </div>
  );
}

function NotTrading({ me, onSignOut }) {
  return (
    <div className="t-login">
      <div style={card}>
        <h2 style={{ marginTop: 0 }}>This is the trading app</h2>
        <p>
          <b>{me.full_name}</b>, your Planet account is set up for project
          work, not trading. Your pages are in the main app.
        </p>
        <div style={{ display: "flex", gap: 8 }}>
          <a href={PLANET_URL} className="t-btn-link">Open Planet</a>
          <Btn variant="secondary" onClick={onSignOut}>Sign out</Btn>
        </div>
      </div>
    </div>
  );
}

function Home({ me, canWrite, go }) {
  const [info, setInfo] = useState(null);
  useEffect(() => {
    api("/trading/home").then(setInfo).catch(() => setInfo({}));
  }, []);
  return (
    <div className="t-page">
      <h1 className="t-h1">Good day, {me.full_name.split(" ")[0]}</h1>
      <p className="t-lead">
        Inquiries, quotations, orders and deliveries for Sand Planet's trading
        customers. The inquiry desk opens with the next release; the
        directories are ready now.
      </p>
      <div className="t-tiles">
        <button className="t-tile" onClick={() => go("customers")}>
          <span className="t-tile-n">{info ? info.customers ?? "—" : "…"}</span>
          <span className="t-tile-l">Customers</span>
        </button>
        <button className="t-tile" onClick={() => go("suppliers")}>
          <span className="t-tile-n">{info ? info.suppliers ?? "—" : "…"}</span>
          <span className="t-tile-l">Trading suppliers</span>
        </button>
        <div className="t-tile t-tile-soon">
          <span className="t-tile-n">—</span>
          <span className="t-tile-l">Open inquiries</span>
          <span className="t-tile-s">next release</span>
        </div>
      </div>
      {!canWrite && (
        <p className="t-note">
          You are reading the trading world as {ROLE_LABEL[me.role] || me.role}.
          Sales enter customers, suppliers and orders; Finance pays and receipts.
        </p>
      )}
    </div>
  );
}

function Inquiries() {
  return (
    <div className="t-page">
      <h1 className="t-h1">Inquiries</h1>
      <p className="t-lead">
        The inquiry register, pricing sheet, quotations and sales orders arrive
        with phase 2. Until then, get the customer and supplier directories in
        order — every inquiry will hang off them.
      </p>
    </div>
  );
}

export default function App() {
  const [me, setMe] = useState(null);
  const [page, setPage] = useState(pageFromHash);

  useEffect(() => {
    api("/auth/me").then(setMe).catch(() => setMe({ authenticated: false }));
  }, []);

  useEffect(() => {
    const onExpired = () => setMe({ authenticated: false, expired: true });
    window.addEventListener(SESSION_EXPIRED, onExpired);
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => {
      window.removeEventListener(SESSION_EXPIRED, onExpired);
      window.removeEventListener("hashchange", onHash);
    };
  }, []);

  function go(key) {
    window.location.hash = `#/${key}`;
    setPage(key);
  }

  async function signOut() {
    try { await api("/auth/logout", { method: "POST", body: {} }); } catch { /* gone anyway */ }
    setMe({ authenticated: false });
  }

  if (me === null) return <div className="t-login"><p>Loading…</p></div>;
  if (!me.authenticated) {
    return <Login expired={me.expired}
                  onLogin={(u) => { resetSessionNotice(); setMe(u); }} />;
  }
  if (!READERS.has(me.role)) return <NotTrading me={me} onSignOut={signOut} />;
  const canWrite = WRITERS.has(me.role);

  return (
    <div className="t-app">
      <header className="t-header">
        <div className="t-brand">
          <span className="t-brand-name">Sand Planet</span>
          <span className="t-brand-arm">Trading</span>
        </div>
        <nav className="t-nav">
          {PAGES.map(([key, label]) => (
            <button key={key} className={"t-nav-item" + (page === key ? " is-active" : "")}
                    onClick={() => go(key)}>{label}</button>
          ))}
        </nav>
        <div className="t-user">
          <span className="t-user-name">{me.full_name}</span>
          <span className="t-user-role">{ROLE_LABEL[me.role] || me.role}</span>
          {!TRADING_ROLES.has(me.role) && (
            <a href={PLANET_URL} className="t-user-link">Planet</a>
          )}
          <button className="t-user-link" onClick={signOut}>Sign out</button>
        </div>
      </header>
      <main className="t-main">
        {page === "home" && <Home me={me} canWrite={canWrite} go={go} />}
        {page === "inquiries" && <Inquiries />}
        {page === "customers" && <CustomersPage canWrite={canWrite} />}
        {page === "suppliers" && <SuppliersPage canWrite={canWrite} />}
      </main>
    </div>
  );
}
