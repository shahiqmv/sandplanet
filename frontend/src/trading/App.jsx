// Sand Planet Trading — app shell: session gate, navigation, pages.
//
// The trading arm lives on the Planet backend but on its own surface
// (TRADING_BUILD_BRIEF.md §5): a Sales user signs in here and sees only
// trading; a site role that lands here is sent back to Planet. Finance,
// the Signatory and Admin can enter both worlds.
import { useEffect, useState } from "react";
import { api, resetSessionNotice, SESSION_EXPIRED } from "../api.js";
import { AppSwitcher, Btn, Chip, card } from "../ui.jsx";
import { getBrand, nameParts, onBrand } from "../brand.js";
import CustomersPage from "./CustomersPage.jsx";
import InquiriesPage from "./InquiriesPage.jsx";
import OrderPage from "./OrderPage.jsx";
import ReceivablesPage from "./ReceivablesPage.jsx";
import SuppliersPage from "./SuppliersPage.jsx";
import { STAGE_LABEL, StageChip, fmtDate, fmtMoney } from "./shared.jsx";

const TRADING_ROLES = new Set(["SALES", "SALES_MANAGER"]);
const READERS = new Set([...TRADING_ROLES, "FINANCE", "SIGNATORY", "ADMIN"]);
const WRITERS = new Set(["SALES", "SALES_MANAGER", "ADMIN"]);

const PAGES = [
  ["home", "Dashboard"],
  ["inquiries", "Inquiries"],
  ["customers", "Customers"],
  ["suppliers", "Suppliers"],
  ["receivables", "Receivables"],
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

// #/inquiries/12 → {page: "inquiries", id: 12}
function routeFromHash() {
  const parts = (window.location.hash || "").replace(/^#\/?/, "").split("/");
  const key = PAGES.some(([k]) => k === parts[0]) ? parts[0] : "home";
  const id = key === "inquiries" && /^\d+$/.test(parts[1] || "") ? Number(parts[1]) : null;
  return { page: key, id, tab: parts[2] || null };
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
          <a href={PLANET_URL} className="t-btn-link">Open Projects</a>
          <Btn variant="secondary" onClick={onSignOut}>Sign out</Btn>
        </div>
      </div>
    </div>
  );
}

function Home({ me, canWrite, go, open }) {
  const [info, setInfo] = useState(null);
  useEffect(() => {
    api("/trading/home").then(setInfo).catch(() => setInfo({}));
  }, []);
  const stages = info?.by_stage || {};
  return (
    <div className="t-page">
      <h1 className="t-h1">Good day, {me.full_name.split(" ")[0]}</h1>
      <div className="t-tiles">
        {["INQUIRY", "SOURCING", "PRICING", "QUOTED"].map((s) => (
          <button key={s} className="t-tile" onClick={() => go("inquiries", null, s)}>
            <span className="t-tile-n">{info ? stages[s] ?? 0 : "…"}</span>
            <span className="t-tile-l">{STAGE_LABEL[s]}</span>
          </button>
        ))}
        <button className="t-tile" onClick={() => go("customers")}>
          <span className="t-tile-n">{info ? info.customers ?? "—" : "…"}</span>
          <span className="t-tile-l">Customers</span>
        </button>
        <button className="t-tile" onClick={() => go("suppliers")}>
          <span className="t-tile-n">{info ? info.suppliers ?? "—" : "…"}</span>
          <span className="t-tile-l">Trading suppliers</span>
        </button>
      </div>

      {info?.awaiting_authorisation?.length > 0 && (
        <div style={{ ...card, marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Quotations awaiting your authorisation</h3>
          {info.awaiting_authorisation.map((q) => (
            <div key={q.quotation} className="t-kv t-row-link" onClick={() => open(q.order_id, "quotation")}>
              <span><b>{q.quotation}</b> · {q.customer} · {q.by}</span>
              <b>{q.currency} {fmtMoney(q.total)}</b>
            </div>
          ))}
        </div>
      )}

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Chase list — next actions due this week</h3>
        {!info ? <p>Loading…</p> : info.chase?.length ? info.chase.map((o) => (
          <div key={o.id} className="t-kv t-row-link" onClick={() => open(o.id)}>
            <span>
              {o.overdue ? <Chip tone="alert">overdue</Chip> : <Chip tone="info">{fmtDate(o.next_action_date)}</Chip>}
              {" "}<b>{o.ref}</b> {o.customer_name} — {o.next_action || o.title}
            </span>
            <StageChip stage={o.stage} />
          </div>
        )) : <p className="t-sub">Nothing due. Give every open inquiry a next action and a date, and this list becomes your morning.</p>}
      </div>

      {info?.recent_won?.length > 0 && (
        <div style={{ ...card, marginTop: 16 }}>
          <h3 style={{ marginTop: 0 }}>Recently won</h3>
          {info.recent_won.map((o) => (
            <div key={o.id} className="t-kv t-row-link" onClick={() => open(o.id, "order")}>
              <span><b>{o.so_ref}</b> · {o.customer_name} — {o.title}</span>
              <b>{o.currency} {fmtMoney(o.total)}</b>
            </div>
          ))}
        </div>
      )}
      {!canWrite && (
        <p className="t-note" style={{ marginTop: 16 }}>
          You are reading the trading world as {ROLE_LABEL[me.role] || me.role}.
          Sales enter customers, suppliers and orders; Finance pays and receipts.
        </p>
      )}
    </div>
  );
}

export default function App() {
  const [me, setMe] = useState(null);
  const [route, setRoute] = useState(routeFromHash);
  const [brand, setBrand] = useState(getBrand());
  useEffect(() => onBrand(setBrand), []);
  const brandName = nameParts(brand?.name).join(" ").replace(/\b\w+/g, (w) => w[0] + w.slice(1).toLowerCase());
  const [stageFilter, setStageFilter] = useState(null);

  useEffect(() => {
    api("/auth/me").then(setMe).catch(() => setMe({ authenticated: false }));
  }, []);

  useEffect(() => {
    const onExpired = () => setMe({ authenticated: false, expired: true });
    window.addEventListener(SESSION_EXPIRED, onExpired);
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => {
      window.removeEventListener(SESSION_EXPIRED, onExpired);
      window.removeEventListener("hashchange", onHash);
    };
  }, []);

  function go(key, id = null, stage = null) {
    setStageFilter(stage);
    window.location.hash = id ? `#/${key}/${id}` : `#/${key}`;
    setRoute(routeFromHash());
  }
  function open(id, tab = null) {
    window.location.hash = tab ? `#/inquiries/${id}/${tab}` : `#/inquiries/${id}`;
    setRoute(routeFromHash());
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
  const roles = [me.role, ...(me.extra_roles || [])];
  if (!roles.some((r) => READERS.has(r))) return <NotTrading me={me} onSignOut={signOut} />;
  const canWrite = roles.some((r) => WRITERS.has(r));
  const { page, id, tab } = route;

  return (
    <div className="t-app">
      <header className="t-header">
        <div className="t-brand">
          <span className="t-brand-name">{brandName}</span>
          <span className="t-brand-arm">Trading</span>
        </div>
        <AppSwitcher apps={brand?.apps} current="trading" />
        <nav className="t-nav">
          {PAGES.map(([key, label]) => (
            <button key={key} className={"t-nav-item" + (page === key ? " is-active" : "")}
                    onClick={() => go(key)}>{label}</button>
          ))}
        </nav>
        <div className="t-user">
          <span className="t-user-name">{me.full_name}</span>
          <span className="t-user-role">{ROLE_LABEL[me.role] || me.role}</span>
          <button className="t-user-link" onClick={signOut}>Sign out</button>
        </div>
      </header>
      <main className="t-main">
        {page === "home" && <Home me={me} canWrite={canWrite} go={go} open={open} />}
        {page === "inquiries" && !id && (
          <InquiriesPage me={me} canWrite={canWrite} open={open}
                         initialStage={stageFilter} key={stageFilter || "list"} />
        )}
        {page === "inquiries" && id && (
          <OrderPage id={id} initialTab={tab} back={() => go("inquiries")} key={id} />
        )}
        {page === "customers" && <CustomersPage canWrite={canWrite} />}
        {page === "suppliers" && <SuppliersPage canWrite={canWrite} />}
        {page === "receivables" && <ReceivablesPage open={(inv, tab) => open(inv.order_id || inv.id, tab)} />}
      </main>
    </div>
  );
}
