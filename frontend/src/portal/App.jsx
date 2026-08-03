import { useEffect, useMemo, useState } from "react";
import { api, downloadFile, getToken, setToken } from "./api.js";
import ClientGantt from "./ClientGantt.jsx";

const fmt = (s) => s ? new Date(s).toLocaleDateString("en-GB",
  { day: "2-digit", month: "short", year: "numeric" }) : "—";
const fmtDay = (s) => s ? new Date(s).toLocaleDateString("en-GB",
  { weekday: "long", day: "2-digit", month: "long", year: "numeric" }) : "—";
const daysTo = (s) => {
  if (!s) return null;
  const d = Math.ceil((new Date(s) - new Date()) / 86400000);
  return d;
};

/* ------------------------------------------------------------------ chrome */
function TopBar({ me, onLogout }) {
  return (
    <div className="topbar">
      <div className="wrap">
        <div>
          <div className="brand"><span className="dim">SAND</span>PLANET</div>
          <div className="brand-tag">Client Portal</div>
        </div>
        <div className="spacer" />
        {me && <div className="whoami"><b>{me.org_name}</b><br />{me.full_name}</div>}
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
      const d = await api("/auth/login", { method: "POST", body: { email, password } });
      setToken(d.token); onIn(d);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <div className="wrap center">
      <form className="card" style={{ width: 380 }} onSubmit={submit}>
        <div className="eyebrow">Sand Planet</div>
        <h1 className="login-t serif">Client Portal</h1>
        <p className="muted" style={{ marginTop: 0, fontSize: 13.5 }}>
          Sign in to follow progress on your project.</p>
        {err && <p className="err">{err}</p>}
        <div className="field"><label>Email</label>
          <input type="email" value={email} autoFocus
            onChange={(e) => setEmail(e.target.value)} /></div>
        <div className="field"><label>Password</label>
          <input type="password" value={password}
            onChange={(e) => setPassword(e.target.value)} /></div>
        <button className="btn pri block" disabled={busy || !email || !password}>
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
      <form className="card" style={{ width: 380 }} onSubmit={submit}>
        <h2 className="serif" style={{ fontSize: 22 }}>Set your password</h2>
        <p className="muted" style={{ marginTop: 4, fontSize: 13.5 }}>
          Choose your own password to continue.</p>
        {err && <p className="err">{err}</p>}
        <div className="field"><label>Current (temporary) password</label>
          <input type="password" value={cur} autoFocus
            onChange={(e) => setCur(e.target.value)} /></div>
        <div className="field"><label>New password (min 8 characters)</label>
          <input type="password" value={next}
            onChange={(e) => setNext(e.target.value)} /></div>
        <button className="btn pri block" disabled={busy || next.length < 8}>
          {busy ? "Saving…" : "Save password"}</button>
      </form>
    </div>
  );
}

function SiteList({ sites, onOpen }) {
  return (
    <div className="wrap" style={{ paddingTop: 8 }}>
      <div className="card">
        <div className="eyebrow">Your sites</div>
        <h1 className="serif" style={{ fontSize: 26, margin: "4px 0 14px" }}>Sites</h1>
        {sites.map((s) => (
          <div key={s.id} className="sitecard" onClick={() => onOpen(s.id)}>
            <span className="code">{s.code}</span><span>{s.name}</span>
            <div style={{ flex: 1 }} /><span className="muted">›</span>
          </div>))}
        {!sites.length && <p className="muted">No sites assigned yet.</p>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- doc row bits */
function DocRow({ icon, label, sub, status, onView }) {
  return (
    <div className="drow">
      <div className="ic">{icon}</div>
      <div><div className="lbl">{label}</div>{sub && <div className="sub">{sub}</div>}</div>
      <div className="grow" />
      {status && <span className={`pill ${status.cls}`}>{status.text}</span>}
      <button className="btn" onClick={onView}>View</button>
    </div>
  );
}

/* --------------------------------------------------------------- overview */
function Overview({ d, proj, setProj, openDoc, goProc, goProgramme, goCameras }) {
  const projects = d.projects || [];
  const active = projects[proj] || null;
  const mp = d.manpower;
  const maxCt = Math.max(1, ...mp.by_trade.map((t) => t.count));
  const prog = active ? (active.progress || {})
    : { percent: d.site.progress, source: "programme" };
  const percent = prog.percent;
  const note = prog.note || "";
  const published = prog.source === "published";
  const target = active ? active.target_date : null;
  const start = active ? active.start_date : null;
  const dTo = daysTo(target);

  return (
    <>
      <div className="card hero">
        <div className="row">
          <div className="lead">
            <div className="eyebrow">{d.site.code} · {d.site.name}</div>
            {active
              ? <>
                  <div className="proj-name serif">{active.title}</div>
                  <div className="proj-sub">{active.code}</div>
                </>
              : <div className="proj-name serif">{d.site.name}</div>}
            {projects.length > 1 && (
              <div className="switch">
                <select value={proj} onChange={(e) => setProj(+e.target.value)}>
                  {projects.map((p, i) => (
                    <option key={p.id} value={i}>{p.code} — {p.title}</option>))}
                </select>
              </div>)}
          </div>
          <div className="pct-wrap">
            <div className="pct serif tnum">
              {percent == null ? "—" : percent}<small>%</small></div>
            <div className="pct-l">Overall progress</div>
          </div>
        </div>

        <div className="bar"><i style={{ width: `${percent || 0}%` }} /></div>
        <div className="ticks">
          <span>{start ? `Started ${fmt(start)}` : "In progress"}</span>
          <span>{percent == null ? "Not yet reported"
            : published ? "As reported by the project team"
            : "To date, from the construction programme"}</span>
          <span>{target ? `Target ${fmt(target)}` : ""}</span>
        </div>
        {note && <div className="brief-s" style={{ marginTop: 16,
          paddingTop: 14, borderTop: "1px solid var(--line-2)" }}>
          <span className="eyebrow">Latest update</span>
          <div style={{ marginTop: 4 }}>{note}</div></div>}

        <div className="meta-strip">
          <div className="mstat"><div className="k">On site today</div>
            <div className="v tnum">{mp.grand_total} <span>workers</span></div></div>
          <div className="mstat"><div className="k">Last report</div>
            <div className="v">{d.recent_dprs.length ? fmt(d.recent_dprs[0].date) : "—"}</div></div>
          <div className="mstat"><div className="k">Next delivery</div>
            <div className="v">{d.materials_on_the_way.length
              ? fmt(d.materials_on_the_way[0].date) : "—"}</div></div>
          {dTo != null && <div className="mstat"><div className="k">Days to target</div>
            <div className="v tnum">{dTo}</div></div>}
        </div>
      </div>

      {active && active.scope && (
        <div className="card">
          <div className="sec-title"><h2>Project brief</h2></div>
          <div className="brief-s">{active.scope}</div>
        </div>)}

      <div className="two">
        {/* site workforce */}
        <div className="card">
          <div className="sec-title"><h2>Site workforce</h2>
            <span className="hint">{mp.as_of ? `as reported ${fmt(mp.as_of)}` : "current"}</span></div>
          <div className="wf-top"><div className="wf-total serif tnum">{mp.grand_total}</div>
            <div className="wf-cap">total on site</div></div>
          <div className="trades">
            {mp.by_trade.map((t) => (
              <div key={t.trade} className="trade">
                <span className="nm">{t.trade}</span>
                <span className="tk"><i style={{ width: `${Math.max(6, t.count / maxCt * 100)}%` }} /></span>
                <span className="ct tnum">{t.count}</span></div>))}
          </div>
          {!mp.by_trade.length && <p className="muted">No manpower recorded yet.</p>}
          {mp.by_trade.length > 0 && <div className="split-note">
            Site staff &amp; labour combined — the full team working on your site.</div>}
        </div>

        {/* allocation + materials */}
        <div className="card">
          <div className="sec-title"><h2>Work allocation</h2></div>
          {!d.dma.today && !d.dma.tomorrow && <p className="muted">No allocation issued yet.</p>}
          {d.dma.today && <DocRow icon="▦" label="Today's allocation"
            sub={fmt(d.dma.today.date)} onView={() => openDoc(d.dma.today.ref)} />}
          {d.dma.tomorrow && <DocRow icon="◷" label="Tomorrow's allocation"
            sub={fmt(d.dma.tomorrow.date)} onView={() => openDoc(d.dma.tomorrow.ref)} />}

          {d.materials_on_the_way.length > 0 && <>
            <div className="sec-title" style={{ marginTop: 24 }}><h2>Materials on the way</h2></div>
            {d.materials_on_the_way.slice(0, 4).map((m) => (
              <DocRow key={m.ref} icon="⛴" label={`Loading manifest · ${fmt(m.date)}`}
                sub="In transit to site" onView={() => openDoc(m.ref)} />))}
          </>}
        </div>
      </div>

      {/* daily reports */}
      <div className="card">
        <div className="sec-title"><h2>Daily progress reports</h2>
          <span className="hint">last 7 days</span></div>
        {!d.recent_dprs.length && <p className="muted">No daily reports in the last week.</p>}
        {d.recent_dprs.map((r) => (
          <DocRow key={r.ref} icon="▤" label={`Daily report · ${fmt(r.date)}`}
            status={r.verified ? { cls: "ok", text: "Verified" } : { cls: "mut", text: "Reported" }}
            onView={() => openDoc(r.ref)} />))}
      </div>

      {/* quick links */}
      <div className="quick">
        <div className="qcard" onClick={goProgramme}>
          <div className="qic">📅</div>
          <div><h3>Construction programme</h3><p>Timeline &amp; % complete per activity</p></div>
          <div className="arw">→</div>
        </div>
        <div className="qcard" onClick={goProc}>
          <div className="qic">◧</div>
          <div><h3>Procurement plan</h3><p>Material pipeline, ETAs &amp; delivery status</p></div>
          <div className="arw">→</div>
        </div>
        <div className="qcard" onClick={goCameras}>
          <div className="qic">📹</div>
          <div><h3>Site cameras</h3><p>Live views &amp; daily time-lapse</p></div>
          <div className="arw">→</div>
        </div>
      </div>
      <div className="footer">Sand Planet (Pvt) Ltd · Client Portal</div>
    </>
  );
}

/* ---------------------------------------------------- web-native report view */
function ReportView({ docRef, onBack }) {
  const [r, setR] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { setR(null); setErr(null);
    api(`/documents/${docRef}`).then(setR).catch((e) => setErr(e.message)); }, [docRef]);

  return (
    <>
      <button className="btn" style={{ marginBottom: 16 }} onClick={onBack}>‹ Back to overview</button>
      <div className="card">
        {err && <p className="err">{err}</p>}
        {!r && !err && <p className="loading">Opening report…</p>}
        {r && <>
          <div className="rpt-head">
            <div className="t">
              <div className="rpt-kind">{r.title}</div>
              <h1>{r.type === "DPR" ? fmtDay(r.date) : `${r.doc_no} · ${fmt(r.date)}`}</h1>
              <ReportMeta r={r} />
            </div>
            <button className="btn pri"
              onClick={() => downloadFile(`/documents/${docRef}.pdf`, `${docRef}.pdf`).catch(() => {})}>
              ⬇ Download PDF</button>
          </div>
          {r.type === "DPR" && <DPRBody r={r} />}
          {r.type === "DMA" && <DMABody r={r} />}
          {r.type === "TWS" && <TWSBody r={r} />}
          {r.type === "LM" && <LMBody r={r} />}
        </>}
      </div>
      <div className="footer">Sand Planet (Pvt) Ltd · Client Portal</div>
    </>
  );
}

function Meta({ k, v }) {
  return <div><div className="k">{k}</div><div className="v">{v || "—"}</div></div>;
}
function ReportMeta({ r }) {
  return (
    <div className="rpt-meta">
      <Meta k="Reference" v={r.doc_no} />
      {r.working_hours && <Meta k="Working hours" v={r.working_hours} />}
      {r.type === "DPR" && (r.weather_am || r.weather_pm) &&
        <Meta k="Weather" v={[r.weather_am, r.weather_pm].filter(Boolean).join(" / ")} />}
      {r.type === "DMA" && r.based_on_tws && <Meta k="Based on" v={r.based_on_tws} />}
      {r.type === "LM" && <Meta k="Vessel" v={r.vessel} />}
      {r.type === "LM" && <Meta k="Expected arrival" v={r.arrival ? fmt(r.arrival) : "—"} />}
      {r.site && <Meta k="Site" v={r.site} />}
    </div>
  );
}

function DPRBody({ r }) {
  const m = r.manpower;
  return (
    <>
      <div className="rsec"><h3>Work done today</h3>
        {!r.work_groups.length && <p className="muted" style={{ marginTop: 12 }}>No activities recorded.</p>}
        {r.work_groups.map((g, gi) => (
          <div key={gi}>
            {r.work_groups.length > 1 || g.label !== "General Works"
              ? <div className="grp-h">{g.label}</div> : null}
            {g.rows.map((row) => (
              <div key={row.no} className="act">
                <div>
                  <div className="a">{row.activity}
                    {row.off_programme && <span className="offp"> · off-programme</span>}</div>
                  <div className="sub">
                    {row.trade && <span className="chip">{row.trade}</span>}
                    {row.location && <span className="chip">{row.location}</span>}
                    {row.remarks && <span>{row.remarks}</span>}</div>
                </div>
                <div className="prog">
                  <span className="mini"><i style={{ width: `${pct(row.todate)}%` }} /></span>
                  <div className="n tnum">{cell(row.today) && `${cell(row.today)}% today`}
                    {cell(row.today) && cell(row.todate) ? " · " : ""}
                    {cell(row.todate) ? `${cell(row.todate)}% to date` : (!cell(row.today) ? "—" : "")}</div>
                </div>
              </div>))}
          </div>))}
      </div>

      <div className="rsec"><h3>Manpower on site — {m.total}</h3>
        <div className="mp">
          <div><h4>Staff</h4>
            {m.staff.length ? m.staff.map(([n, c]) => (
              <div key={n} className="li"><span>{n}</span><b className="tnum">{c}</b></div>))
              : <div className="li muted">—</div>}</div>
          <div><h4>Trades &amp; Labour</h4>
            {m.labour.length ? m.labour.map(([n, c]) => (
              <div key={n} className="li"><span>{n}</span><b className="tnum">{c}</b></div>))
              : <div className="li muted">—</div>}</div>
        </div>
        <div className="mp-total"><span>Total manpower at site</span><span className="tnum">{m.total}</span></div>
      </div>

      {r.materials.length > 0 && <div className="rsec"><h3>Key materials at site</h3>
        <div className="scroll-x"><table className="data">
          <thead><tr><th>Material</th><th>Unit</th><th className="num">Opening</th>
            <th className="num">Received</th><th className="num">Consumed</th><th className="num">Balance</th></tr></thead>
          <tbody>{r.materials.map((x, i) => (
            <tr key={i}><td>{x.material}</td><td>{x.unit}</td><td className="num">{cell(x.opening)}</td>
              <td className="num">{cell(x.received)}</td><td className="num">{cell(x.consumed)}</td>
              <td className="num">{cell(x.balance)}</td></tr>))}</tbody>
        </table></div></div>}

      {r.machinery.length > 0 && <div className="rsec"><h3>Machinery &amp; equipment</h3>
        <div className="scroll-x"><table className="data">
          <thead><tr><th>Item</th><th className="num">Nos</th><th>Remarks</th></tr></thead>
          <tbody>{r.machinery.map((x, i) => (
            <tr key={i}><td>{x.item}</td><td className="num">{cell(x.nos)}</td><td>{x.remarks}</td></tr>))}</tbody>
        </table></div></div>}

      {r.photos.length > 0 && <div className="rsec"><h3>Progress photos</h3>
        <div className="photos">{r.photos.map((p, i) => (
          <div key={i} className="ph"><img src={p.url} alt={p.caption || "site photo"} loading="lazy" />
            {p.caption && <div className="cap">{p.caption}</div>}</div>))}</div></div>}
    </>
  );
}

function DMABody({ r }) {
  return (
    <>
      <div className="rsec"><h3>Task allocation</h3>
        <div className="scroll-x"><table className="data">
          <thead><tr><th>#</th><th>Task</th><th>Project</th><th>Location</th>
            <th>Category</th><th className="num">Workers</th><th>Remarks</th></tr></thead>
          <tbody>{r.tasks.map((t) => (
            <tr key={t.no}><td>{t.no}</td><td>{t.task}</td><td>{t.project}</td>
              <td>{t.location}</td><td>{t.category}</td><td className="num">{cell(t.workers)}</td>
              <td>{t.remarks}</td></tr>))}</tbody>
        </table></div></div>
      <div className="rsec"><h3>Manpower at work — {r.total}</h3>
        <div className="mp"><div>
          {r.totals.map(([n, c]) => (
            <div key={n} className="li"><span>{n}</span><b className="tnum">{c}</b></div>))}
          <div className="mp-total"><span>Total</span><span className="tnum">{r.total}</span></div>
        </div><div /></div></div>
      {r.notes && <div className="rsec"><h3>Notes</h3><div className="rtext">{r.notes}</div></div>}
    </>
  );
}

function TWSBody({ r }) {
  return (
    <>
      <div className="rsec"><h3>Planned activities</h3>
        <div className="scroll-x"><table className="data">
          <thead><tr><th>#</th><th>Activity</th><th>Project</th><th>Location</th>
            <th>Trade</th><th>Remarks</th></tr></thead>
          <tbody>{r.activities.map((a) => (
            <tr key={a.no}><td>{a.no}</td><td>{a.activity}</td><td>{a.project}</td>
              <td>{a.location}</td><td>{a.trade}</td><td>{a.remarks}</td></tr>))}</tbody>
        </table></div></div>
      <div className="rsec"><h3>Planned manpower — {r.total}</h3>
        <div className="mp"><div>
          {r.manpower.map(([n, c]) => (
            <div key={n} className="li"><span>{n}</span><b className="tnum">{c}</b></div>))}
          <div className="mp-total"><span>Total</span><span className="tnum">{r.total}</span></div>
        </div><div /></div></div>
      <div className="rsec"><h3>Access / support required from client</h3>
        <div className="rtext">{r.access_support}</div></div>
    </>
  );
}

function LMBody({ r }) {
  return (
    <>
      <div className="rsec"><h3>Items loaded</h3>
        <div className="scroll-x"><table className="data">
          <thead><tr><th>#</th><th>Item description</th><th>Unit</th>
            <th className="num">Qty loaded</th><th className="num">Qty pending</th><th>Remarks</th></tr></thead>
          <tbody>{r.items.map((x) => (
            <tr key={x.no}><td>{x.no}</td><td>{x.description}</td><td>{x.unit}</td>
              <td className="num">{cell(x.qty_loaded)}</td><td className="num">{cell(x.qty_pending)}</td>
              <td>{x.remarks}</td></tr>))}</tbody>
        </table></div></div>
      <div className="rsec"><h3>Shipment</h3>
        <div className="rpt-meta" style={{ marginTop: 0 }}>
          <Meta k="Vessel / boat" v={r.vessel} /><Meta k="Departure" v={r.departure} />
          <Meta k="Expected arrival" v={r.arrival ? fmt(r.arrival) : "—"} />
          <Meta k="Trip / load no." v={r.trip} /></div></div>
    </>
  );
}

const pct = (v) => { const n = parseFloat(String(v).replace("%", "")); return isNaN(n) ? 0 : Math.min(100, n); };
const cell = (v) => (v === 0 || v) ? String(v).replace(/\.0+$/, "") : "";

/* ------------------------------------------------------- procurement page */
const statusClass = (s) => {
  const t = (s || "").toLowerCase();
  if (t.includes("late") || t.includes("overdue")) return "late";
  if (t.includes("risk")) return "warn";
  if (t.includes("track") || t.includes("on order") || t.includes("delivered")) return "ok";
  return "mut";
};

function ProcurementPage({ project, onBack }) {
  const [plan, setPlan] = useState(null);
  const [err, setErr] = useState(null);
  const [filter, setFilter] = useState("all");
  useEffect(() => { setPlan(null);
    api(`/projects/${project.id}/procurement`).then(setPlan).catch((e) => setErr(e.message)); },
    [project.id]);

  const rows = useMemo(() => plan && plan.available
    ? plan.sections.flatMap((s) => s.rows.map((r) => ({ ...r, _sec: s }))) : [], [plan]);
  const counts = useMemo(() => {
    const c = { total: rows.length, ok: 0, warn: 0, late: 0 };
    rows.forEach((r) => { const k = statusClass(r.status); if (c[k] != null) c[k]++; });
    return c;
  }, [rows]);

  return (
    <>
      <button className="btn" style={{ marginBottom: 16 }} onClick={onBack}>‹ Back to overview</button>
      <div className="card">
        <div className="rpt-head" style={{ border: 0, padding: 0 }}>
          <div className="t">
            <div className="rpt-kind">Procurement plan</div>
            <h1>{project.title}</h1>
            <div className="proj-sub" style={{ marginTop: 6 }}>{project.code} · material pipeline for your project</div>
          </div>
          <button className="btn pri"
            onClick={() => downloadFile(`/projects/${project.id}/procurement.xlsx`,
              `${project.code}-Procurement-Plan.xlsx`).catch(() => {})}>⬇ Excel</button>
        </div>
        {plan && plan.available && (
          <div className="tiles" style={{ marginTop: 22 }}>
            <div className="tile"><div className="n tnum">{counts.total}</div><div className="k">Planned items</div></div>
            <div className="tile ok"><div className="n tnum">{counts.ok}</div><div className="k">On track</div></div>
            <div className="tile warn"><div className="n tnum">{counts.warn}</div><div className="k">At risk</div></div>
            <div className="tile late"><div className="n tnum">{counts.late}</div><div className="k">Late</div></div>
          </div>)}
      </div>

      {err && <div className="card"><p className="err">{err}</p></div>}
      {plan && !plan.available && <div className="card"><p className="muted">No procurement plan published yet.</p></div>}

      {plan && plan.available && (
        <div className="card">
          <div className="legend">
            <span><i style={{ background: "var(--ok)" }} />On track</span>
            <span><i style={{ background: "var(--warn)" }} />At risk</span>
            <span><i style={{ background: "var(--late)" }} />Late</span>
            <span style={{ marginLeft: "auto", color: "var(--ink-3)" }}>Status reflects ETA vs required-on-site date</span>
          </div>
          <div className="filters">
            {[["all", "All"], ["ok", "On track"], ["warn", "At risk"], ["late", "Late"]].map(([k, l]) => (
              <button key={k} className={`fchip ${filter === k ? "on" : ""}`} onClick={() => setFilter(k)}>{l}</button>))}
          </div>
          {plan.sections.map((sec, i) => {
            const srows = sec.rows.filter((r) => filter === "all" || statusClass(r.status) === filter);
            if (!srows.length) return null;
            return (
              <div key={i}>
                <div className="pgrp-h">{sec.title || "Items"}
                  {sec.code && <span className="c">· {sec.code}</span>}
                  <span className="c">· {srows.length} item{srows.length > 1 ? "s" : ""}</span></div>
                <div className="scroll-x"><table className="data">
                  <thead><tr><th>Item</th><th className="num">Qty</th><th>Required on site</th>
                    <th>Pipeline</th><th>ETA</th><th>Status</th></tr></thead>
                  <tbody>{srows.map((r, j) => (
                    <tr key={j}>
                      <td>{r.description}</td>
                      <td className="num">{cell(r.quantity)} {r.uom}</td>
                      <td>{fmt(r.required_date)}</td>
                      <td>{r.shipment ? <span className="stage"><span className="dot" />{r.shipment}</span> : "—"}</td>
                      <td>{fmt(r.eta)}</td>
                      <td><span className={`pill ${statusClass(r.status)}`}>{r.status || "—"}</span></td>
                    </tr>))}</tbody>
                </table></div>
              </div>);
          })}
        </div>)}
      <div className="footer">Sand Planet (Pvt) Ltd · Client Portal</div>
    </>
  );
}

function ProgrammeView({ project, onBack }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { setD(null); setErr(null);
    api(`/projects/${project.id}/programme`).then(setD)
      .catch((e) => setErr(e.message)); }, [project.id]);
  return (
    <>
      <button className="btn" style={{ marginBottom: 16 }} onClick={onBack}>‹ Back to overview</button>
      <div className="card">
        <div className="rpt-head" style={{ border: 0, padding: 0 }}>
          <div className="t">
            <div className="rpt-kind">Construction programme</div>
            <h1>{project.title}</h1>
            <div className="proj-sub" style={{ marginTop: 6 }}>{project.code}
              {d && d.overall != null && ` · ${Math.round(d.overall)}% complete`}</div>
          </div>
        </div>
        {err && <p className="err">{err}</p>}
        {!d && !err && <p className="loading">Loading programme…</p>}
        {d && !d.activities.length && <p className="muted" style={{ marginTop: 12 }}>
          No programme published for this project yet.</p>}
        {d && d.activities.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <ClientGantt activities={d.activities} />
            <div className="split-note" style={{ marginTop: 10 }}>
              Bars show planned dates; the fill is % complete. ◆ = milestone.
            </div>
          </div>)}
      </div>
      <div className="footer">Sand Planet (Pvt) Ltd · Client Portal</div>
    </>
  );
}

function CamerasPage({ onBack }) {
  return (
    <>
      <button className="btn" style={{ marginBottom: 16 }} onClick={onBack}>‹ Back to overview</button>
      <div className="card">
        <div className="sec-title"><h2>Site cameras</h2></div>
        <div className="soon">
          <div className="icon">📹</div>
          <h3>Coming soon</h3>
          <p>Live site views and daily time-lapse are on the way — you'll see them
            here once your site's camera is installed.</p>
        </div>
      </div>
    </>
  );
}

/* -------------------------------------------------------------- site portal */
function SitePortal({ id, single, onBackToSites }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [proj, setProj] = useState(0);
  const [view, setView] = useState({ name: "overview" });   // overview|proc|cameras|report
  useEffect(() => { api(`/sites/${id}`).then(setD).catch((e) => setErr(e.message)); }, [id]);

  if (err) return <div className="wrap"><div className="card"><p className="err">{err}</p></div></div>;
  if (!d) return <div className="wrap"><div className="card loading">Loading…</div></div>;

  const projects = d.projects || [];
  const activeProject = projects[proj] || null;
  const seg = view.name;

  return (
    <>
      <div className="segbar"><div className="segs">
        {!single && <button className="seg" onClick={onBackToSites}>‹ Sites</button>}
        <button className={`seg ${seg === "overview" ? "on" : ""}`}
          onClick={() => setView({ name: "overview" })}>Overview</button>
        <button className={`seg ${seg === "programme" ? "on" : ""}`}
          onClick={() => setView({ name: "programme" })} disabled={!activeProject}>Programme</button>
        <button className={`seg ${seg === "proc" ? "on" : ""}`}
          onClick={() => setView({ name: "proc" })} disabled={!activeProject}>Procurement</button>
        <button className={`seg ${seg === "cameras" ? "on" : ""}`}
          onClick={() => setView({ name: "cameras" })}>Cameras</button>
      </div></div>

      <div className="wrap">
        {seg === "overview" && <Overview d={d} proj={proj} setProj={setProj}
          openDoc={(ref) => setView({ name: "report", ref })}
          goProc={() => setView({ name: "proc" })}
          goProgramme={() => setView({ name: "programme" })}
          goCameras={() => setView({ name: "cameras" })} />}
        {seg === "report" && <ReportView docRef={view.ref}
          onBack={() => setView({ name: "overview" })} />}
        {seg === "programme" && (activeProject
          ? <ProgrammeView project={activeProject} onBack={() => setView({ name: "overview" })} />
          : <div className="card"><p className="muted">No project to show a programme for yet.</p></div>)}
        {seg === "proc" && (activeProject
          ? <ProcurementPage project={activeProject} onBack={() => setView({ name: "overview" })} />
          : <div className="card"><p className="muted">No project to show a plan for yet.</p></div>)}
        {seg === "cameras" && <CamerasPage onBack={() => setView({ name: "overview" })} />}
      </div>
    </>
  );
}

/* --------------------------------------------------------------------- app */
export default function App() {
  const [state, setState] = useState("loading");     // loading|login|change|ready
  const [me, setMe] = useState(null);
  const [openSite, setOpenSite] = useState(null);

  useEffect(() => {
    if (!getToken()) { setState("login"); return; }
    api("/me").then((m) => { setMe(m); setState(m.must_change_password ? "change" : "ready"); })
      .catch(() => setState("login"));
  }, []);

  const onIn = (d) => { setMe(d); setState(d.must_change_password ? "change" : "ready"); };
  const logout = () => {
    api("/auth/logout", { method: "POST" }).catch(() => {});
    setToken(""); setMe(null); setOpenSite(null); setState("login");
  };

  if (state === "loading") return null;
  if (state === "login") return <><TopBar /><Login onIn={onIn} /></>;
  if (state === "change") return <><TopBar me={me} onLogout={logout} />
    <ChangePassword onDone={() => { setMe({ ...me, must_change_password: false }); setState("ready"); }} /></>;

  const sites = me.sites || [];
  const single = sites.length === 1;
  const activeId = openSite || (single ? sites[0].id : null);
  return (
    <>
      <TopBar me={me} onLogout={logout} />
      {activeId
        ? <SitePortal id={activeId} single={single} onBackToSites={() => setOpenSite(null)} />
        : <SiteList sites={sites} onOpen={setOpenSite} />}
    </>
  );
}
