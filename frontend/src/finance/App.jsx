// Sand Planet Finance — app shell: session gate, navigation, pages.
//
// The finance team's own surface (FINANCE_BUILD_BRIEF.md): the payment and
// receivable pages that used to sit in a corner of the Projects menu, and
// the books — chart of accounts, journals, trial balance, ledgers. Same
// login and same database as Planet, so nothing is keyed twice. Documents
// (a PYR, a PO, an import order) still open in Projects, where they live.
import { useEffect, useRef, useState } from "react";
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
import AuditsPage from "./AuditsPage.jsx";
import BankingPage from "./BankingPage.jsx";
import { AgingPage, DocsPage, PartiesPage } from "./CreditPage.jsx";
import { BalanceSheetPage, ProfitLossPage } from "./StatementsPage.jsx";
import GstPage from "./GstPage.jsx";
import ImportPage from "./ImportPage.jsx";
import JournalsPage from "./JournalsPage.jsx";
import PostingPage from "./PostingPage.jsx";
import ReconcilePage from "./ReconcilePage.jsx";
import RentalsPage from "./RentalsPage.jsx";
import { LedgerPage, TrialBalancePage } from "./ReportsPages.jsx";
import UtilitiesPage from "./UtilitiesPage.jsx";
import { fmtDate, money } from "./shared.jsx";

const READERS = new Set(["FINANCE", "ADMIN", "SIGNATORY", "DIRECTOR", "PA", "QS"]);
const BOOKS = new Set(["FINANCE", "ADMIN", "SIGNATORY", "DIRECTOR", "PA"]);
const PAYERS = ["FINANCE", "ADMIN", "SIGNATORY"];
const RECEIVABLE = ["FINANCE", "DIRECTOR", "ADMIN", "QS", "PA", "SIGNATORY"];
const BOOK_ROLES = [...BOOKS];

// section → its pages: [key, label, roles]
const SECTIONS = [
  ["overview", "Overview", [["home", "Overview", [...READERS]]]],
  ["banking", "Banking", [
    ["banking", "Accounts", BOOK_ROLES],
    ["reconcile", "Reconcile", BOOK_ROLES]]],
  // the books' own purchases and sales on credit, QuickBooks-style
  ["purchases", "Purchases", [
    ["bills", "Bills", BOOK_ROLES],
    ["suppliers", "Suppliers", BOOK_ROLES],
    ["ap-aging", "What we owe", BOOK_ROLES]]],
  ["sales", "Sales", [
    ["invoices", "Invoices", BOOK_ROLES],
    ["customers", "Customers", BOOK_ROLES],
    ["ar-aging", "What we are owed", BOOK_ROLES]]],
  // what Projects and Trading feed in: requisitions to pay, claims to collect
  ["operations", "Operations", [
    ["dashboard", "Dashboard", PAYERS],
    ["vouchers", "Payment vouchers", PAYERS],
    ["payables", "Payables", PAYERS],
    ["import-payments", "International payables", PAYERS],
    ["rentals", "Rentals", BOOK_ROLES],
    ["utilities", "Phone & utility bills", BOOK_ROLES],
    ["receivables", "Receivables", RECEIVABLE]]],
  ["books", "Books", [
    ["accounts", "Chart of accounts", BOOK_ROLES],
    ["journals", "Journal entries", BOOK_ROLES],
    ["import", "Import from Excel", BOOK_ROLES],
    ["audits", "External audits", BOOK_ROLES]]],
  ["reports", "Reports", [
    ["pnl", "Profit and loss", BOOK_ROLES],
    ["bs", "Balance sheet", BOOK_ROLES],
    ["gst", "GST return", BOOK_ROLES],
    ["tb", "Trial balance", BOOK_ROLES],
    ["ledger", "Account ledger", BOOK_ROLES]]],
  ["setup", "Setup", [
    ["posting", "Posting from Planet", BOOK_ROLES],
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
        {can("bills") && <button className="t-tile" onClick={() => go("bills")}><span className="t-tile-l">Bills</span><span className="t-tile-s">enter, pay, what we owe</span></button>}
        {can("invoices") && <button className="t-tile" onClick={() => go("invoices")}><span className="t-tile-l">Invoices</span><span className="t-tile-s">enter, receive, what we are owed</span></button>}
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

// ---- open pages: several at once, parked in a bar at the bottom -----------
// (owner 2026-10-27). Finance often has a bill half entered when a supplier
// rings about another, or a reconciliation open while checking a ledger.
// Every open page stays alive — what was typed, the filters, the scroll —
// and only the one in front is shown. The page list (not what was typed)
// survives a reload.
const MAX_PAGES = 6;
const WIN_KEY = "f-open-pages";
let winSeq = 0;
const newWin = (page, sub = null) => ({ id: ++winSeq, page, sub, dirty: false, nonce: 0, scroll: 0 });

function loadWindows() {
  try {
    const saved = JSON.parse(localStorage.getItem(WIN_KEY) || "null");
    if (saved && Array.isArray(saved.pages) && saved.pages.length) {
      const wins = saved.pages.slice(0, MAX_PAGES).map((w) => newWin(w.page, w.sub || null));
      return { wins, active: wins[Math.min(saved.active || 0, wins.length - 1)].id };
    }
  } catch { /* storage unavailable or bad */ }
  return null;
}

export default function App() {
  const [me, setMe] = useState(null);
  const [wins, setWins] = useState(() => {
    const r = routeFromHash();
    const saved = loadWindows();
    if (!saved) return [newWin(r.page, r.sub)];
    // the address the page was opened on wins over what was saved
    const at = saved.wins.find((w) => w.page === r.page && (w.sub || null) === r.sub);
    if (!at && window.location.hash) saved.wins[saved.wins.findIndex((w) => w.id === saved.active)] = newWin(r.page, r.sub);
    return saved.wins;
  });
  const [activeId, setActiveId] = useState(() => wins.find((w) => {
    const r = routeFromHash();
    return w.page === r.page && (w.sub || null) === r.sub;
  })?.id || wins[0].id);
  const [winMsg, setWinMsg] = useState(null);
  const winsRef = useRef(wins);
  winsRef.current = wins;
  const activeRef = useRef(activeId);
  activeRef.current = activeId;
  const route = wins.find((w) => w.id === activeId) || wins[0];
  const [brand, setBrand] = useState(getBrand());
  const [settings, setSettings] = useState(null);
  useEffect(() => onBrand(setBrand), []);
  const brandName = nameParts(brand?.name).join(" ").replace(/\b\w+/g, (w) => w[0] + w.slice(1).toLowerCase());
  const planetUrl = (brand?.apps || []).find((a) => a.key === "planet")?.url || "/";

  useEffect(() => { api("/auth/me").then(setMe).catch(() => setMe({ authenticated: false })); }, []);
  useEffect(() => {
    const onExpired = () => setMe({ authenticated: false, expired: true });
    window.addEventListener(SESSION_EXPIRED, onExpired);
    // back / forward in the browser moves the page in front
    const onHash = () => {
      const r = routeFromHash();
      const cur = winsRef.current.find((w) => w.id === activeRef.current);
      if (cur && (cur.page !== r.page || (cur.sub || null) !== r.sub)) navWin(activeRef.current, r.page, r.sub, false);
    };
    window.addEventListener("hashchange", onHash);
    return () => { window.removeEventListener(SESSION_EXPIRED, onExpired); window.removeEventListener("hashchange", onHash); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- navWin reads refs only
  useEffect(() => {
    if (me?.authenticated && BOOKS.has(me.role)) api("/ledger/settings").then(setSettings).catch(() => {});
  }, [me]);

  // remember the page list (not what was typed) for the next visit
  useEffect(() => {
    try {
      localStorage.setItem(WIN_KEY, JSON.stringify({
        pages: wins.map((w) => ({ page: w.page, sub: w.sub })),
        active: Math.max(0, wins.findIndex((w) => w.id === activeId)) }));
    } catch { /* storage unavailable */ }
  }, [wins, activeId]);

  const setHash = (w) => {
    const h = w.sub ? `#/${w.page}/${w.sub}` : `#/${w.page}`;
    if (window.location.hash !== h) window.location.hash = h;
  };
  // move one open page to another screen — its own links do this
  function navWin(id, key, sub = null, top = true) {
    setWins((ws) => ws.map((w) => (w.id === id ? { ...w, page: key, sub: sub || null, dirty: false } : w)));
    if (id === activeRef.current) {
      setHash({ page: key, sub });
      if (top) window.scrollTo({ top: 0 });
    }
  }
  // bring an open page to the front, keeping where each one was scrolled
  function focusWin(id) {
    if (id === activeRef.current) return;
    const y = window.scrollY;
    setWins((ws) => ws.map((w) => (w.id === activeRef.current ? { ...w, scroll: y } : w)));
    setActiveId(id);
    const w = winsRef.current.find((x) => x.id === id);
    if (w) { setHash(w); setTimeout(() => window.scrollTo({ top: w.scroll || 0 }), 0); }
  }
  // a new page in front; the oldest untouched page makes room past the cap
  function openWin(key, sub = null) {
    let ws = winsRef.current;
    if (ws.length >= MAX_PAGES) {
      const spare = ws.find((w) => w.id !== activeRef.current && !w.dirty);
      if (!spare) { setWinMsg(`${MAX_PAGES} pages are open with entries in them — save or close one first.`); return; }
      ws = ws.filter((w) => w.id !== spare.id);
    }
    const w = newWin(key, sub);
    const y = window.scrollY;
    setWins([...ws.map((x) => (x.id === activeRef.current ? { ...x, scroll: y } : x)), w]);
    setActiveId(w.id);
    setHash(w);
    window.scrollTo({ top: 0 });
    setWinMsg(null);
  }
  // the menu: replace the page in front — unless something was typed on it,
  // in which case it is parked in the bar and the new page opens beside it
  function go(key, sub = null) {
    const cur = winsRef.current.find((w) => w.id === activeRef.current);
    if (cur && cur.dirty && (cur.page !== key || (cur.sub || null) !== sub)) openWin(key, sub);
    else navWin(activeRef.current, key, sub);
  }
  function minimize() {
    const home = winsRef.current.find((w) => w.id !== activeRef.current && w.page === "home" && !w.dirty);
    if (home) focusWin(home.id); else openWin("home");
  }
  function closeWin(id) {
    const w = winsRef.current.find((x) => x.id === id);
    if (w?.dirty && !window.confirm("This page has entries that may not be saved. Close it?")) return;
    const rest = winsRef.current.filter((x) => x.id !== id);
    if (!rest.length) { setWins([newWin("home")]); setActiveId(winSeq); setHash({ page: "home" }); return; }
    setWins(rest);
    if (id === activeRef.current) {
      const next = rest[rest.length - 1];
      setActiveId(next.id); setHash(next);
      setTimeout(() => window.scrollTo({ top: next.scroll || 0 }), 0);
    }
    setWinMsg(null);
  }
  const refreshWin = (id) => setWins((ws) => ws.map((w) => (w.id === id ? { ...w, nonce: w.nonce + 1, dirty: false } : w)));
  const markDirty = (id, e) => {
    const t = e.target;
    // searching and filtering a list is not unsaved work
    if (t && (t.type === "search" || /search|filter/i.test(t.placeholder || "") || t.closest?.("[data-not-entry]"))) return;
    setWins((ws) => (ws.find((w) => w.id === id)?.dirty ? ws : ws.map((w) => (w.id === id ? { ...w, dirty: true } : w))));
  };
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
  const active = sections.find(([, , pages]) => pages.some(([k]) => k === page)) || sections[0];
  const canWrite = ["FINANCE", "ADMIN"].includes(me.role);
  const label = (key) => ALL_PAGES.find(([k]) => k === key)?.[1] || "Overview";
  const title = (w) => label(can(w.page) ? w.page : "home") + (w.sub ? ` · ${w.sub}` : "");

  // one page's screen; its own links move that page, not the one in front
  function screen(w) {
    const pg = can(w.page) ? w.page : "home";
    const { sub } = w;
    const go = (key, s = null) => navWin(w.id, key, s);
    // A document opens where it lives — in Projects, in its own tab.
    const openDoc = (ref) => (/^RENT-/i.test(ref || "") ? go("rentals", ref)
      : /^UTL-/i.test(ref || "") ? go("utilities", ref)
      : window.open(`${planetUrl}#/open/${encodeURIComponent(ref)}`, "_blank", "noopener"));
    return (<>
        {pg === "home" && <Home me={me} go={go} can={can} settings={settings} />}
        {pg === "dashboard" && (
          <FinanceDashboard me={me} onVouchers={() => go("vouchers")}
            onNewPayment={["FINANCE", "ADMIN"].includes(me.role)
              ? () => window.open(`${planetUrl}#/doc/central-pyr-form`, "_blank", "noopener") : null} />
        )}
        {pg === "vouchers" && <PaymentVouchersPage me={me} onOpenDoc={openDoc} openRef={sub} key={sub || "list"} />}
        {pg === "payables" && <PayablesPage me={me} onOpenDoc={openDoc} />}
        {pg === "rentals" && <RentalsPage sub={sub} go={go} key={sub || "list"} />}
        {pg === "audits" && <AuditsPage sub={sub} go={go} key={sub || "list"} />}
        {pg === "utilities" && <UtilitiesPage sub={sub} go={go} />}
        {pg === "import-payments" && <ImportPaymentsDue onOpenIpr={openDoc} />}
        {pg === "receivables" && <ReceivablesPage me={me} />}
        {pg === "banking" && <BankingPage sub={sub} go={go} settings={settings} canEdit={canWrite} key={sub || "home"} />}
        {pg === "reconcile" && <ReconcilePage sub={sub} go={go} />}
        {pg === "bills" && <DocsPage side="AP" sub={sub} go={go} settings={settings} canEdit={canWrite} key={sub || "list"} />}
        {pg === "suppliers" && <PartiesPage side="AP" sub={sub} go={go} canEdit={canWrite} />}
        {pg === "ap-aging" && <AgingPage side="AP" go={go} />}
        {pg === "invoices" && <DocsPage side="AR" sub={sub} go={go} settings={settings} canEdit={canWrite} key={sub || "list"} />}
        {pg === "customers" && <PartiesPage side="AR" sub={sub} go={go} canEdit={canWrite} />}
        {pg === "ar-aging" && <AgingPage side="AR" go={go} />}
        {pg === "pnl" && <ProfitLossPage go={go} settings={settings} />}
        {pg === "bs" && <BalanceSheetPage go={go} />}
        {pg === "gst" && <GstPage go={go} />}
        {pg === "journals" && <JournalsPage sub={sub} go={go} settings={settings} planetUrl={planetUrl} key={sub || "list"} />}
        {pg === "accounts" && <AccountsPage go={go} />}
        {pg === "import" && <ImportPage canEdit={canWrite} />}
        {pg === "tb" && <TrialBalancePage go={go} settings={settings} />}
        {pg === "ledger" && <LedgerPage accountId={sub ? Number(sub) : null} go={go} settings={settings} />}
        {pg === "posting" && <PostingPage />}
        {pg === "cost-heads" && <CostHeadsPage me={me} />}
        {pg === "settings" && <SettingsPage me={me} settings={settings} onSaved={setSettings} />}
    </>);
  }

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
        {wins.map((w) => (
          <div key={w.id} hidden={w.id !== activeId}
               onInputCapture={(e) => markDirty(w.id, e)} onChangeCapture={(e) => markDirty(w.id, e)}>
            {w.id === activeId && (wins.length > 1 || w.page !== "home") && (
              <div className="f-winbar">
                <span className="f-winbar-title">{title(w)}{w.dirty && <span className="f-dot" title="Has entries that may not be saved"> •</span>}</span>
                <span className="spacer" />
                <button className="f-link" onClick={() => refreshWin(w.id)} title="Load this page again with the latest figures">Refresh</button>
                <span className="f-winctl">
                  <button onClick={minimize} title="Minimize — park this page in the bar below, keeping what is on it" aria-label="Minimize">–</button>
                  <button className="is-close" onClick={() => closeWin(w.id)} title="Close this page" aria-label="Close">×</button>
                </span>
              </div>
            )}
            <div key={w.nonce}>{screen(w)}</div>
          </div>
        ))}
      </main>
      {winMsg && <div className="f-winmsg">{winMsg}</div>}
      <nav className="f-dock" aria-label="Open pages">
        {wins.map((w) => (
          <span key={w.id} className={"f-chip" + (w.id === activeId ? " is-active" : "")}>
            <button className="f-chip-open" onClick={() => focusWin(w.id)} title={w.id === activeId ? "In front" : "Bring to the front"}>
              {title(w)}{w.dirty && <span className="f-dot"> •</span>}
            </button>
            {wins.length > 1 && <button className="f-chip-x" onClick={() => closeWin(w.id)} title="Close this page" aria-label={`Close ${title(w)}`}>×</button>}
          </span>
        ))}
        <button className="f-chip-new" onClick={() => openWin("home")} disabled={wins.length >= MAX_PAGES}
                title={wins.length >= MAX_PAGES ? `At most ${MAX_PAGES} pages` : "Open another page"}>+ New page</button>
      </nav>
    </div>
  );
}
