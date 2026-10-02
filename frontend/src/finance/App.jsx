// Sand Planet Finance — app shell: session gate, navigation, pages.
//
// The finance team's own surface (FINANCE_BUILD_BRIEF.md): the payment and
// receivable pages that used to sit in a corner of the Projects menu, and
// the books — chart of accounts, journals, trial balance, ledgers. Same
// login and same database as Planet, so nothing is keyed twice. Documents
// (a PYR, a PO, an import order) still open in Projects, where they live.
import { useEffect, useState } from "react";
import { api, resetSessionNotice, SESSION_EXPIRED } from "../api.js";
import { AppSwitcher, Btn, card } from "../ui.jsx";
import { getBrand, nameParts, onBrand } from "../brand.js";
import CostHeadsPage from "../CostHeadsPage.jsx";
import FinanceDashboard from "../FinanceDashboard.jsx";
import { ImportPaymentsDue } from "../ImportOrders.jsx";
import PayablesPage from "../PayablesPage.jsx";
import PaymentVouchersPage from "../PaymentVouchersPage.jsx";
import ReceivablesPage from "../ReceivablesPage.jsx";
import AccountsPage from "./AccountsPage.jsx";
import BankingPage from "./BankingPage.jsx";
import { BalanceSheetPage, ProfitLossPage } from "./StatementsPage.jsx";
import JournalsPage from "./JournalsPage.jsx";
import { LedgerPage, TrialBalancePage } from "./ReportsPages.jsx";
import { fmtDate, money } from "./shared.jsx";

const READERS = new Set(["FINANCE", "ADMIN", "SIGNATORY", "DIRECTOR", "PA", "QS"]);
const BOOKS = new Set(["FINANCE", "ADMIN", "SIGNATORY", "DIRECTOR", "PA"]);
const PAYERS = ["FINANCE", "ADMIN", "SIGNATORY"];
const RECEIVABLE = ["FINANCE", "DIRECTOR", "ADMIN", "QS", "PA", "SIGNATORY"];
const BOOK_ROLES = [...BOOKS];

// section → its pages: [key, label, roles]
const SECTIONS = [
  ["overview", "Overview", [["home", "Overview", [...READERS]]]],
  ["banking", "Banking", [["banking", "Banking", BOOK_ROLES]]],
  ["payments", "Payments", [
    ["dashboard", "Dashboard", PAYERS],
    ["vouchers", "Payment vouchers", PAYERS],
    ["payables", "Payables", PAYERS],
    ["import-payments", "International payables", PAYERS]]],
  ["receivables", "Receivables", [["receivables", "Receivables", RECEIVABLE]]],
  ["books", "Books", [
    ["accounts", "Chart of accounts", BOOK_ROLES],
    ["journals", "Journal entries", BOOK_ROLES]]],
  ["reports", "Reports", [
    ["pnl", "Profit and loss", BOOK_ROLES],
    ["bs", "Balance sheet", BOOK_ROLES],
    ["tb", "Trial balance", BOOK_ROLES],
    ["ledger", "Account ledger", BOOK_ROLES]]],
  ["setup", "Setup", [
    ["cost-heads", "Cost heads", ["FINANCE", "ADMIN", "DIRECTOR", "SIGNATORY"]],
    ["settings", "Books settings", BOOK_ROLES]]],
];
const ALL_PAGES = SECTIONS.flatMap(([, , pages]) => pages);
const ROLE_LABEL = { FINANCE: "Finance", ADMIN: "Admin", SIGNATORY: "Signatory",
                     DIRECTOR: "Director", PA: "PA", QS: "QS" };

// #/journals/12 → {page: "journals", sub: "12"}
function routeFromHash() {
  const parts = (window.location.hash || "").replace(/^#\/?/, "").split("/");
  const page = ALL_PAGES.some(([k]) => k === parts[0]) ? parts[0] : "home";
  return { page, sub: parts[1] || null };
}

function Login({ onLogin, expired }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError(null);
    try { onLogin(await api("/auth/login", { method: "POST", body: { username, password } })); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return (
    <div className="t-login">
      <form onSubmit={submit} style={card}>
        <div className="t-brand" style={{ marginBottom: 14 }}>
          <span className="t-brand-name">Sand Planet</span>
          <span className="t-brand-arm" style={{ color: "#c9952c" }}>Finance</span>
        </div>
        <h2 style={{ marginTop: 0, color: "var(--sp-navy)" }}>Sign in</h2>
        {expired && <p className="t-note t-note-amber">Your session has expired — sign in again to carry on.</p>}
        <label className="t-field"><span>Username</span>
          <input value={username} autoFocus autoComplete="username" onChange={(e) => setUsername(e.target.value)} /></label>
        <label className="t-field"><span>Password</span>
          <input type="password" value={password} autoComplete="current-password" onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <p className="t-note t-note-red">{error}</p>}
        <Btn type="submit" disabled={busy || !username || !password} style={{ width: "100%", marginTop: 8 }}>
          {busy ? "Signing in…" : "Sign in"}</Btn>
      </form>
    </div>
  );
}

function NotFinance({ me, planetUrl, onSignOut }) {
  return (
    <div className="t-login">
      <div style={card}>
        <h2 style={{ marginTop: 0 }}>This is the finance app</h2>
        <p><b>{me.full_name}</b>, your account isn't set up for finance work. Your pages are in the main app.</p>
        <div style={{ display: "flex", gap: 8 }}>
          <a href={planetUrl} className="t-btn-link">Open Projects</a>
          <Btn variant="secondary" onClick={onSignOut}>Sign out</Btn>
        </div>
      </div>
    </div>
  );
}

function Home({ me, go, can, settings }) {
  const [books, setBooks] = useState(null);
  const [tb, setTb] = useState(null);
  const [jr, setJr] = useState(null);
  const seesBooks = BOOKS.has(me.role);
  useEffect(() => {
    if (!seesBooks) return;
    api("/ledger/accounts").then(setBooks).catch(() => setBooks({ accounts: [] }));
    api("/ledger/trial-balance").then(setTb).catch(() => {});
    api("/ledger/journals?limit=1").then(setJr).catch(() => {});
  }, [seesBooks]);
  const empty = books && books.accounts.length === 0;
  const cash = (books?.accounts || []).filter((a) => !a.is_group && (a.is_bank || /cash/i.test(a.name)))
    .reduce((s, a) => s + Number(a.balance || 0), 0);
  return (
    <div className="t-page">
      <h1 className="t-h1">Good day, {me.full_name.split(" ")[0]}</h1>
      {seesBooks && empty && (
        <div className="t-note t-note-amber" style={{ maxWidth: 760 }}>
          <b>The books aren't set up yet.</b> Start with the chart of accounts, then enter the opening balances
          from the audited statements. <button className="f-link" onClick={() => go("accounts")}>Set up the chart of accounts</button>
        </div>
      )}
      {seesBooks && !empty && books && (
        <div className="t-tiles">
          <button className="t-tile" onClick={() => go("tb")}>
            <span className="t-tile-n" style={{ fontSize: 20 }}>
              {tb ? (tb.rows.length === 0 ? "No entries" : tb.balanced ? "In balance" : "Out of balance") : "…"}</span>
            <span className="t-tile-l">Trial balance</span>
            <span className="t-tile-s">{tb && tb.rows.length ? `MVR ${money(tb.totals.closing_debit)}` : "nothing posted yet"}</span>
          </button>
          <button className="t-tile" onClick={() => go("journals")}>
            <span className="t-tile-n">{jr ? jr.total : "…"}</span>
            <span className="t-tile-l">Journal entries</span>
            <span className="t-tile-s">{jr?.drafts ? `${jr.drafts} draft${jr.drafts === 1 ? "" : "s"} to post` : "all posted"}</span>
          </button>
          <button className="t-tile" onClick={() => go("accounts")}>
            <span className="t-tile-n" style={{ fontSize: 20 }}>MVR {money(cash)}</span>
            <span className="t-tile-l">Cash and bank, per the books</span>
            <span className="t-tile-s">{books.accounts.filter((a) => !a.is_group).length} accounts</span>
          </button>
        </div>
      )}
      <div className="t-tiles">
        {can("vouchers") && <button className="t-tile" onClick={() => go("vouchers")}><span className="t-tile-l">Payment vouchers</span><span className="t-tile-s">build, approve, pay</span></button>}
        {can("payables") && <button className="t-tile" onClick={() => go("payables")}><span className="t-tile-l">Payables</span><span className="t-tile-s">what we owe and when</span></button>}
        {can("receivables") && <button className="t-tile" onClick={() => go("receivables")}><span className="t-tile-l">Receivables</span><span className="t-tile-s">invoices, aging, statements</span></button>}
        {can("banking") && <button className="t-tile" onClick={() => go("banking")}><span className="t-tile-l">Banking</span><span className="t-tile-s">expenses, deposits, transfers</span></button>}
        {can("pnl") && <button className="t-tile" onClick={() => go("pnl")}><span className="t-tile-l">Profit and loss</span><span className="t-tile-s">and the balance sheet</span></button>}
      </div>
      {seesBooks && settings && (
        <p style={{ fontSize: 12.5, color: "var(--muted)" }}>
          Books open {fmtDate(settings.books_start_date)} · statements in {settings.base_currency}
          {settings.lock_date ? ` · closed up to ${fmtDate(settings.lock_date)}` : " · no period closed yet"}
        </p>
      )}
    </div>
  );
}

function SettingsPage({ me, settings, onSaved }) {
  const [lock, setLock] = useState(settings?.lock_date || "");
  const [msg, setMsg] = useState(null);
  const canEdit = ["FINANCE", "ADMIN"].includes(me.role);
  useEffect(() => { setLock(settings?.lock_date || ""); }, [settings]);
  async function save() {
    setMsg(null);
    try { onSaved(await api("/ledger/settings", { method: "POST", body: { lock_date: lock || "" } })); setMsg("Saved."); }
    catch (e) { setMsg(e.message); }
  }
  if (!settings) return <div style={card}>Loading…</div>;
  return (
    <div className="t-page" style={{ maxWidth: 720 }}>
      <h1 className="t-h1">Books settings</h1>
      <div style={card}>
        <p><b>Books start:</b> {fmtDate(settings.books_start_date)}. Opening balances are dated {fmtDate(settings.opening_date)},
          the day before. Nothing else can be dated earlier.</p>
        <p><b>Statements:</b> in {settings.base_currency}. An entry in another currency keeps its own amount and
          the rate beside the rufiyaa value.</p>
        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13, maxWidth: 320 }}>
          <span style={{ fontWeight: 600 }}>Books closed up to (lock date)</span>
          <input type="date" value={lock} disabled={!canEdit} onChange={(e) => setLock(e.target.value)}
                 style={{ padding: "8px 10px", border: "1px solid var(--line)", borderRadius: 6, font: "inherit" }} />
        </label>
        <p style={{ fontSize: 12.5, color: "var(--muted)" }}>
          No entry can be posted on or before this date. Set it once a month has been checked and reconciled;
          clear it to reopen. Each change is recorded.</p>
        {canEdit && <Btn onClick={save}>Save</Btn>}
        {msg && <span style={{ marginLeft: 10, fontSize: 13 }}>{msg}</span>}
      </div>
    </div>
  );
}

export default function App() {
  const [me, setMe] = useState(null);
  const [route, setRoute] = useState(routeFromHash);
  const [brand, setBrand] = useState(getBrand());
  const [settings, setSettings] = useState(null);
  useEffect(() => onBrand(setBrand), []);
  const brandName = nameParts(brand?.name).join(" ").replace(/\b\w+/g, (w) => w[0] + w.slice(1).toLowerCase());
  const planetUrl = (brand?.apps || []).find((a) => a.key === "planet")?.url || "/";

  useEffect(() => { api("/auth/me").then(setMe).catch(() => setMe({ authenticated: false })); }, []);
  useEffect(() => {
    const onExpired = () => setMe({ authenticated: false, expired: true });
    window.addEventListener(SESSION_EXPIRED, onExpired);
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => { window.removeEventListener(SESSION_EXPIRED, onExpired); window.removeEventListener("hashchange", onHash); };
  }, []);
  useEffect(() => {
    if (me?.authenticated && BOOKS.has(me.role)) api("/ledger/settings").then(setSettings).catch(() => {});
  }, [me]);

  function go(key, sub = null) {
    window.location.hash = sub ? `#/${key}/${sub}` : `#/${key}`;
    setRoute(routeFromHash());
    window.scrollTo({ top: 0 });
  }
  async function signOut() {
    try { await api("/auth/logout", { method: "POST", body: {} }); } catch { /* gone anyway */ }
    setMe({ authenticated: false });
  }

  if (me === null) return <div className="t-login"><p>Loading…</p></div>;
  if (!me.authenticated) return <Login expired={me.expired} onLogin={(u) => { resetSessionNotice(); setMe(u); }} />;
  if (!READERS.has(me.role)) return <NotFinance me={me} planetUrl={planetUrl} onSignOut={signOut} />;

  const can = (key) => (ALL_PAGES.find(([k]) => k === key)?.[2] || []).includes(me.role);
  const sections = SECTIONS.map(([key, label, pages]) => [key, label, pages.filter(([k]) => can(k))])
    .filter(([, , pages]) => pages.length);
  const page = can(route.page) ? route.page : "home";
  const { sub } = route;
  const active = sections.find(([, , pages]) => pages.some(([k]) => k === page)) || sections[0];
  // A document opens where it lives — in Projects, in its own tab.
  const openDoc = (ref) => window.open(`${planetUrl}#/open/${encodeURIComponent(ref)}`, "_blank", "noopener");

  return (
    <div className="t-app f-app">
      <header className="t-header">
        <div className="t-brand">
          <span className="t-brand-name">{brandName}</span>
          <span className="t-brand-arm">Finance</span>
        </div>
        <AppSwitcher apps={brand?.apps} current="finance" sso={!!brand?.sso} />
        <nav className="t-nav">
          {sections.map(([key, label, pages]) => (
            <button key={key} className={"t-nav-item" + (active[0] === key ? " is-active" : "")}
                    onClick={() => go(pages[0][0])}>{label}</button>
          ))}
        </nav>
        <div className="t-user">
          <span className="t-user-name">{me.full_name}</span>
          <span className="t-user-role">{ROLE_LABEL[me.role] || me.role}</span>
          <button className="t-user-link" onClick={signOut}>Sign out</button>
        </div>
      </header>
      {active[2].length > 1 && (
        <nav className="f-sub">
          {active[2].map(([key, label]) => (
            <button key={key} className={"f-sub-item" + (page === key ? " is-active" : "")}
                    onClick={() => go(key)}>{label}</button>
          ))}
        </nav>
      )}
      <main className="t-main">
        {page === "home" && <Home me={me} go={go} can={can} settings={settings} />}
        {page === "dashboard" && (
          <FinanceDashboard me={me} onVouchers={() => go("vouchers")}
            onNewPayment={["FINANCE", "ADMIN"].includes(me.role)
              ? () => window.open(`${planetUrl}#/doc/central-pyr-form`, "_blank", "noopener") : null} />
        )}
        {page === "vouchers" && <PaymentVouchersPage me={me} onOpenDoc={openDoc} openRef={sub} key={sub || "list"} />}
        {page === "payables" && <PayablesPage me={me} onOpenDoc={openDoc} />}
        {page === "import-payments" && <ImportPaymentsDue onOpenIpr={openDoc} />}
        {page === "receivables" && <ReceivablesPage me={me} />}
        {page === "banking" && <BankingPage sub={sub} go={go} settings={settings}
                                             canEdit={["FINANCE", "ADMIN"].includes(me.role)} key={sub || "home"} />}
        {page === "pnl" && <ProfitLossPage go={go} settings={settings} />}
        {page === "bs" && <BalanceSheetPage go={go} />}
        {page === "journals" && <JournalsPage sub={sub} go={go} settings={settings} planetUrl={planetUrl} key={sub || "list"} />}
        {page === "accounts" && <AccountsPage go={go} />}
        {page === "tb" && <TrialBalancePage go={go} settings={settings} />}
        {page === "ledger" && <LedgerPage accountId={sub ? Number(sub) : null} go={go} settings={settings} />}
        {page === "cost-heads" && <CostHeadsPage me={me} />}
        {page === "settings" && <SettingsPage me={me} settings={settings} onSaved={setSettings} />}
      </main>
    </div>
  );
}
