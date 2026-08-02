import { useEffect, useState } from "react";
import { api, downloadFile, fetchHtml, getToken, setToken } from "./api.js";

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
        <div className="eyebrow">Your sites</div>
        <h1>Sites</h1>
        {sites.map((s) => (
          <div key={s.id} className="sitecard" onClick={() => onOpen(s.id)}>
            <span className="code">{s.code}</span>
            <span>{s.name}</span>
            <div style={{ flex: 1 }} />
            <span className="muted">›</span>
          </div>
        ))}
        {!sites.length && <p className="muted">No sites assigned yet.</p>}
      </div>
    </div>
  );
}

function ProcurementPlan({ projectId, code }) {
  const [open, setOpen] = useState(false);
  const [plan, setPlan] = useState(null);
  const load = () => { setOpen(true);
    if (!plan) api(`/projects/${projectId}/procurement`).then(setPlan)
      .catch(() => {}); };
  const file = `${code || "Procurement"}-Plan.xlsx`;
  return (
    <>
      <button className="btn" onClick={open ? () => setOpen(false) : load}>
        {open ? "Hide procurement plan" : "View procurement plan"}</button>{" "}
      <button className="btn" style={{ background: "#fff", color: "var(--navy)",
        border: "1px solid #C9D9E5" }}
        onClick={() => downloadFile(`/projects/${projectId}/procurement.xlsx`,
          file).catch(() => {})}>
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

// A report (DPR / DMA / LM) opened inline — server-rendered HTML in an iframe,
// with a client-side "Download PDF" button.
function DocViewer({ docRef, label, onClose }) {
  const [html, setHtml] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { setHtml(null); setErr(null);
    fetchHtml(`/documents/${docRef}`).then(setHtml)
      .catch((e) => setErr(e.message)); }, [docRef]);
  return (
    <div style={{ position: "fixed", inset: 0, background: "#eef2f6",
      zIndex: 50, display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12,
        padding: "10px 16px", background: "var(--navy)", color: "#fff" }}>
        <button className="btn" onClick={onClose}
          style={{ background: "rgba(255,255,255,.14)" }}>‹ Back</button>
        <b>{label || docRef}</b>
        <span style={{ flex: 1 }} />
        <button className="btn"
          onClick={() => downloadFile(`/documents/${docRef}.pdf`,
            `${docRef}.pdf`).catch(() => {})}>⬇ Download PDF</button>
      </div>
      <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
        {err && <div className="card err">{err}</div>}
        {!html && !err && <div className="card muted">Opening report…</div>}
        {html && <iframe title={docRef} srcDoc={html}
          style={{ width: "100%", height: "100%", minHeight: "70vh",
            border: "1px solid var(--line)", borderRadius: 10,
            background: "#fff" }} />}
      </div>
    </div>
  );
}

function DocRow({ label, sub, onView }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12,
      padding: "10px 0", borderBottom: "1px solid var(--line)" }}>
      <div>
        <div style={{ fontWeight: 600, color: "var(--navy)" }}>{label}</div>
        {sub && <div className="muted" style={{ fontSize: 13 }}>{sub}</div>}
      </div>
      <span style={{ flex: 1 }} />
      <button className="btn" onClick={onView}>View</button>
    </div>
  );
}

function CamerasPage({ onBack }) {
  return (
    <div className="wrap">
      <p><a href="#" onClick={(e) => { e.preventDefault(); onBack(); }}>
        ‹ Back to site</a></p>
      <div className="card">
        <h2>Site cameras</h2>
        <div className="soon">
          <div className="icon">📹</div>
          <h3>Coming soon</h3>
          <p>Live site views and daily time-lapse are on the way — you'll see
             them here once your site's camera is installed.</p>
        </div>
      </div>
    </div>
  );
}

function SiteView({ id, single, onBack }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [proj, setProj] = useState(0);       // active project tab index
  const [viewDoc, setViewDoc] = useState(null);   // {ref,label} | null
  const [showCameras, setShowCameras] = useState(false);
  useEffect(() => { api(`/sites/${id}`).then(setD)
    .catch((e) => setErr(e.message)); }, [id]);
  if (err) return <div className="wrap"><div className="card err">{err}</div></div>;
  if (!d) return <div className="wrap"><div className="card muted">Loading…</div></div>;
  if (viewDoc) return <DocViewer docRef={viewDoc.ref} label={viewDoc.label}
    onClose={() => setViewDoc(null)} />;
  if (showCameras) return <CamerasPage onBack={() => setShowCameras(false)} />;

  const mp = d.manpower;
  const projects = d.projects || [];
  const active = projects[proj] || null;
  const open = (ref, label) => setViewDoc({ ref, label });

  return (
    <div className="wrap">
      {!single && <p><a href="#" onClick={(e) => { e.preventDefault(); onBack(); }}>
        ‹ All sites</a></p>}

      {/* Header */}
      <div className="card">
        <div className="eyebrow">{d.site.code}</div>
        <h1>{d.site.name}</h1>
      </div>

      {/* Project switcher — brief + procurement per project */}
      {projects.length > 0 && (
        <div className="card">
          <h2>Project{projects.length > 1 ? "s" : ""}</h2>
          {projects.length > 1 && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
              margin: "8px 0 14px" }}>
              {projects.map((p, i) => (
                <button key={p.id}
                  className={`btn ${i === proj ? "" : "ghost"}`}
                  style={i === proj ? {} : { background: "#fff",
                    color: "var(--navy)", border: "1px solid #C9D9E5" }}
                  onClick={() => setProj(i)}>{p.code}</button>))}
            </div>)}
          {active && (
            <>
              <div style={{ fontWeight: 700, color: "var(--navy)",
                fontSize: 17 }}>{active.title}</div>
              {active.scope
                ? <p style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>
                    {active.scope}</p>
                : <p className="muted" style={{ marginTop: 6 }}>
                    No project brief published yet.</p>}
              <div style={{ marginTop: 12 }}>
                <ProcurementPlan projectId={active.id} code={active.code} />
              </div>
            </>)}
        </div>)}

      {/* Manpower — current strength by trade + grand total */}
      <div className="card">
        <h2>Manpower {mp.attendance_entered ? "on site today" : "assigned"}</h2>
        <div className="metric" style={{ marginTop: 6 }}>
          <div><div className="n">{mp.grand_total}</div>
            <div className="l">total workforce</div></div>
        </div>
        {mp.by_trade.length > 0 && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
            marginTop: 12 }}>
            {mp.by_trade.map((t) => (
              <span key={t.trade} style={{ border: "1px solid var(--line)",
                borderRadius: 8, padding: "6px 12px", background: "#fff" }}>
                <b style={{ color: "var(--navy)" }}>{t.count}</b>{" "}
                <span className="muted">{t.trade}</span></span>))}
          </div>)}
        {!mp.by_trade.length && <p className="muted">
          No manpower recorded yet.</p>}
      </div>

      {/* Work allocation — today & tomorrow (DMA) */}
      <div className="card">
        <h2>Work &amp; manpower allocation</h2>
        {!d.dma.today && !d.dma.tomorrow && <p className="muted">
          No allocation issued yet.</p>}
        {d.dma.today && <DocRow label="Today's allocation"
          sub={fmt(d.dma.today.date)}
          onView={() => open(d.dma.today.ref, "Today's allocation")} />}
        {d.dma.tomorrow && <DocRow label="Tomorrow's allocation"
          sub={fmt(d.dma.tomorrow.date)}
          onView={() => open(d.dma.tomorrow.ref, "Tomorrow's allocation")} />}
      </div>

      {/* Daily progress reports — last 7 days */}
      <div className="card">
        <h2>Daily progress reports</h2>
        <p className="muted" style={{ marginTop: 0 }}>Last 7 days.</p>
        {!d.recent_dprs.length && <p className="muted">
          No daily reports in the last week.</p>}
        {d.recent_dprs.map((r) => (
          <DocRow key={r.ref} label={`Daily report · ${fmt(r.date)}`}
            sub={r.verified ? "Verified" : "Reported"}
            onView={() => open(r.ref, `Daily report · ${fmt(r.date)}`)} />))}
      </div>

      {/* Materials on the way — LMs in transit to site */}
      {d.materials_on_the_way.length > 0 && (
        <div className="card">
          <h2>Materials on the way</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            Loads currently in transit to site.</p>
          {d.materials_on_the_way.map((r) => (
            <DocRow key={r.ref} label={`Loading manifest · ${fmt(r.date)}`}
              onView={() => open(r.ref, `Loading manifest · ${fmt(r.date)}`)} />))}
        </div>)}

      {/* Cameras — own page */}
      <div className="card">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div><h2 style={{ margin: 0 }}>Site cameras</h2>
            <span className="muted">Live views &amp; time-lapse.</span></div>
          <span style={{ flex: 1 }} />
          <button className="btn" onClick={() => setShowCameras(true)}>
            Open →</button>
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
