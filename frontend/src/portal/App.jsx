import { useEffect, useState } from "react";
import { api, downloadFile, getToken, setToken } from "./api.js";

const fmt = (s) => s ? new Date(s).toLocaleDateString("en-GB",
  { day: "2-digit", month: "short", year: "numeric" }) : "—";

function TopBar({ me, onLogout }) {
  return (
    <div className="topbar">
      <div className="wrap">
        <div>
          <div className="brand"><span className="dim">SAND</span>PLANET</div>
          <div className="brand-tag">Client Portal</div>
        </div>
        <div className="spacer" />
        {me && <span style={{ fontSize: 13, color: "#cfe3f1" }}>
          {me.org_name}</span>}
        {me && <button onClick={onLogout}>Sign out</button>}
      </div>
    </div>
  );
}

function Login({ onIn }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  async function submit(e) {
    e.preventDefault(); setBusy(true); setErr(null);
    try {
      const d = await api("/auth/login", { method: "POST",
        body: { email, password } });
      setToken(d.token); onIn(d);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <div className="wrap center">
      <form className="card" style={{ width: 360 }} onSubmit={submit}>
        <div className="eyebrow">Sand Planet</div>
        <h1>Client Portal</h1>
        <p className="muted" style={{ marginTop: 0, fontSize: 13.5 }}>
          Sign in to see progress on your project.</p>
        {err && <p className="err">{err}</p>}
        <div className="field"><label>Email</label>
          <input type="email" value={email} autoFocus
            onChange={(e) => setEmail(e.target.value)} /></div>
        <div className="field"><label>Password</label>
          <input type="password" value={password}
            onChange={(e) => setPassword(e.target.value)} /></div>
        <button className="btn block" disabled={busy || !email || !password}>
          {busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </div>
  );
}

function ChangePassword({ onDone }) {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  async function submit(e) {
    e.preventDefault(); setBusy(true); setErr(null);
    try {
      await api("/auth/change-password", { method: "POST",
        body: { current_password: cur, new_password: next } });
      onDone();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <div className="wrap center">
      <form className="card" style={{ width: 360 }} onSubmit={submit}>
        <h2>Set your password</h2>
        <p className="muted" style={{ marginTop: 0, fontSize: 13.5 }}>
          Choose your own password to continue.</p>
        {err && <p className="err">{err}</p>}
        <div className="field"><label>Current (temporary) password</label>
          <input type="password" value={cur} autoFocus
            onChange={(e) => setCur(e.target.value)} /></div>
        <div className="field"><label>New password (min 8 characters)</label>
          <input type="password" value={next}
            onChange={(e) => setNext(e.target.value)} /></div>
        <button className="btn block" disabled={busy || next.length < 8}>
          {busy ? "Saving…" : "Save password"}</button>
      </form>
    </div>
  );
}

function SiteList({ sites, onOpen }) {
  return (
    <div className="wrap">
      <div className="card">
        <div className="eyebrow">Your projects</div>
        <h1>Projects</h1>
        {sites.map((s) => (
          <div key={s.id} className="sitecard" onClick={() => onOpen(s.id)}>
            <span className="code">{s.code}</span>
            <span>{s.name}</span>
            <div style={{ flex: 1 }} />
            <span className="muted">›</span>
          </div>
        ))}
        {!sites.length && <p className="muted">No projects assigned yet.</p>}
      </div>
    </div>
  );
}

function ProcurementPlan({ id }) {
  const [open, setOpen] = useState(false);
  const [plan, setPlan] = useState(null);
  const load = () => { setOpen(true);
    if (!plan) api(`/sites/${id}/procurement`).then(setPlan).catch(() => {}); };
  return (
    <>
      <button className="btn" onClick={open ? () => setOpen(false) : load}>
        {open ? "Hide procurement plan" : "View procurement plan"}</button>{" "}
      <button className="btn" style={{ background: "#fff", color: "var(--navy)",
        border: "1px solid #C9D9E5" }}
        onClick={() => downloadFile(`/sites/${id}/procurement.xlsx`,
          "Procurement-Plan.xlsx").catch(() => {})}>
        ⬇ Excel</button>
      {open && plan && plan.available && (
        <div style={{ marginTop: 12 }}>
          {plan.sections.map((sec, i) => (
            <div key={i} style={{ marginTop: 10 }}>
              {sec.title && <div style={{ fontWeight: 600, color: "var(--navy)",
                margin: "6px 0" }}>{sec.code ? `${sec.code} · ` : ""}
                {sec.title}</div>}
              <div style={{ overflowX: "auto" }}>
                <table className="list"><thead><tr>
                  <th>Item</th><th>Qty</th><th>Required</th>
                  <th>ETA</th><th>Status</th></tr></thead><tbody>
                  {sec.rows.map((r, j) => (
                    <tr key={j}><td>{r.description}</td>
                      <td>{r.quantity} {r.uom}</td>
                      <td>{fmt(r.required_date)}</td>
                      <td>{fmt(r.eta)}</td>
                      <td>{r.status || "—"}</td></tr>))}
                </tbody></table>
              </div>
            </div>))}
        </div>)}
      {open && plan && !plan.available && (
        <p className="muted" style={{ marginTop: 8 }}>
          No procurement plan published yet.</p>)}
    </>
  );
}

function SiteView({ id, single, onBack }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { api(`/sites/${id}`).then(setD)
    .catch((e) => setErr(e.message)); }, [id]);
  if (err) return <div className="wrap"><div className="card err">{err}</div></div>;
  if (!d) return <div className="wrap"><div className="card muted">Loading…</div></div>;
  const s = d.summary;
  return (
    <div className="wrap">
      {!single && <p><a href="#" onClick={(e) => { e.preventDefault(); onBack(); }}>
        ‹ All projects</a></p>}

      {/* Day summary */}
      <div className="card">
        <div className="eyebrow">{d.site.code} · {fmt(s.date)}</div>
        <h1>{d.site.name}</h1>
        <div className="metric" style={{ marginTop: 12 }}>
          <div><div className="n">{s.workforce}</div>
            <div className="l">{s.workforce_label}</div></div>
          <div><div className="n">{s.latest_report ? fmt(s.latest_report)
            : "—"}</div><div className="l">latest daily report</div></div>
          <div><div className="n">{s.next_delivery ? fmt(s.next_delivery)
            : "—"}</div><div className="l">next delivery due</div></div>
        </div>
      </div>

      {/* Manpower — total + today's allocation by trade */}
      <div className="card">
        <h2>Manpower {d.manpower.attendance_entered ? "on site today"
          : "assigned"}</h2>
        {!d.manpower.by_trade.length && <p className="muted">
          No manpower recorded yet.</p>}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
          marginTop: 6 }}>
          {d.manpower.by_trade.map((t) => (
            <span key={t.trade} style={{ border: "1px solid var(--line)",
              borderRadius: 8, padding: "6px 12px", background: "#fff" }}>
              <b style={{ color: "var(--navy)" }}>{t.count}</b>{" "}
              <span className="muted">{t.trade}</span></span>))}
        </div>
      </div>

      {/* Inbound deliveries */}
      {d.inbound.length > 0 && (
        <div className="card">
          <h2>Materials & deliveries</h2>
          <table className="list"><thead><tr>
            <th>Item</th><th>Qty</th><th>Due</th><th>Status</th>
          </tr></thead><tbody>
            {d.inbound.map((r, i) => (
              <tr key={i}><td>{r.description}</td>
                <td>{r.quantity} {r.uom}</td>
                <td>{fmt(r.eta)}</td>
                <td>{r.status || r.stage || "—"}</td></tr>))}
          </tbody></table>
        </div>)}

      {/* Procurement plan */}
      {d.procurement.available && (
        <div className="card">
          <h2>Procurement plan</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            {d.procurement.items} items planned · {d.procurement.upcoming}{" "}
            upcoming.</p>
          <ProcurementPlan id={id} />
        </div>)}

      {/* Daily progress */}
      <div className="card">
        <h2>Daily progress</h2>
        {!d.recent_progress.length && <p className="muted">
          No daily reports yet.</p>}
        {d.recent_progress.length > 0 && (
          <table className="list"><thead><tr>
            <th>Date</th><th>Report</th><th>Status</th></tr></thead><tbody>
            {d.recent_progress.map((r) => (
              <tr key={r.ref}><td>{fmt(r.date)}</td><td>{r.ref}</td>
                <td><span className={`pill ${r.verified ? "ok" : "wait"}`}>
                  {r.verified ? "Verified" : "Reported"}</span></td></tr>))}
          </tbody></table>)}
      </div>

      {d.recent_works.length > 0 && (
        <div className="card">
          <h2>Works submissions</h2>
          <table className="list"><thead><tr>
            <th>Date</th><th>Reference</th></tr></thead><tbody>
            {d.recent_works.map((r) => (
              <tr key={r.ref}><td>{fmt(r.date)}</td><td>{r.ref}</td></tr>))}
          </tbody></table>
        </div>)}

      {/* Cameras */}
      <div className="card">
        <h2>Site cameras</h2>
        <div className="soon">
          <div className="icon">📹</div>
          <h3>Coming soon</h3>
          <p>Live site views and daily time-lapse are on the way — you'll see
             them here once your site's camera is installed.</p>
        </div>
      </div>

      <div className="footer">Sand Planet (Pvt) Ltd · Client Portal</div>
    </div>
  );
}

export default function App() {
  const [state, setState] = useState("loading");   // loading|login|change|ready
  const [me, setMe] = useState(null);
  const [openSite, setOpenSite] = useState(null);

  useEffect(() => {
    if (!getToken()) { setState("login"); return; }
    api("/me").then((m) => {
      setMe(m);
      setState(m.must_change_password ? "change" : "ready");
    }).catch(() => setState("login"));
  }, []);

  const onIn = (d) => {
    setMe(d);
    setState(d.must_change_password ? "change" : "ready");
  };
  const logout = () => {
    api("/auth/logout", { method: "POST" }).catch(() => {});
    setToken(""); setMe(null); setOpenSite(null); setState("login");
  };

  if (state === "loading") return null;
  if (state === "login") return <><TopBar /><Login onIn={onIn} /></>;
  if (state === "change") return <><TopBar me={me} onLogout={logout} />
    <ChangePassword onDone={() => { setMe({ ...me,
      must_change_password: false }); setState("ready"); }} /></>;

  const sites = me.sites || [];
  const single = sites.length === 1;
  const activeId = openSite || (single ? sites[0].id : null);
  return (
    <>
      <TopBar me={me} onLogout={logout} />
      {activeId
        ? <SiteView id={activeId} single={single}
            onBack={() => setOpenSite(null)} />
        : <SiteList sites={sites} onOpen={setOpenSite} />}
    </>
  );
}
