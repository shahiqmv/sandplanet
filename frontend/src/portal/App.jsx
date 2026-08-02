import { useEffect, useState } from "react";
import { api, getToken, setToken } from "./api.js";

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

function SiteView({ id, single, onBack }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { api(`/sites/${id}`).then(setD)
    .catch((e) => setErr(e.message)); }, [id]);
  if (err) return <div className="wrap"><div className="card err">{err}</div></div>;
  if (!d) return <div className="wrap"><div className="card muted">Loading…</div></div>;
  const wf = d.workforce;
  return (
    <div className="wrap">
      {!single && <p><a href="#" onClick={(e) => { e.preventDefault(); onBack(); }}>
        ‹ All projects</a></p>}
      <div className="card">
        <div className="eyebrow">{d.site.code}</div>
        <h1>{d.site.name}</h1>
        <div className="metric" style={{ marginTop: 10 }}>
          <div><div className="n">{wf.attendance_entered
            ? wf.on_site : wf.stationed}</div>
            <div className="l">{wf.attendance_entered
              ? "on site today" : "assigned to site"}</div></div>
          <div><div className="n">{d.recent_progress.length}</div>
            <div className="l">recent daily reports</div></div>
        </div>
      </div>

      <div className="card">
        <h2>Daily progress</h2>
        {!d.recent_progress.length && <p className="muted">
          No daily reports yet.</p>}
        {d.recent_progress.length > 0 && (
          <table className="list"><thead><tr>
            <th>Date</th><th>Report</th><th>Status</th></tr></thead><tbody>
            {d.recent_progress.map((r) => (
              <tr key={r.ref}><td>{fmt(r.date)}</td>
                <td>{r.ref}</td>
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
