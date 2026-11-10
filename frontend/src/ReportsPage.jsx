// Management reports (owner 2026-11-07): the ExCom reads every site and the
// company as a whole, a PM reads their own sites. Every report comes back in
// one shape (core/reports.py) — headline figures, then sections of rows — so
// this page draws any of them, and the same report downloads as PDF or Excel.
import { useEffect, useMemo, useState } from "react";
import { api, apiDownload } from "./api.js";
import { Btn, Stat, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

// the local date, not UTC: in Malé (+5) toISOString() puts midnight on the
// day before
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-`
  + String(d.getDate()).padStart(2, "0");

function presets(today) {
  const y = today.getFullYear(), m = today.getMonth();
  const qStart = new Date(y, m - (m % 3), 1);
  return [
    ["This month", iso(new Date(y, m, 1)), iso(today)],
    ["Last month", iso(new Date(y, m - 1, 1)), iso(new Date(y, m, 0))],
    ["This quarter", iso(qStart), iso(today)],
    ["Year to date", iso(new Date(y, 0, 1)), iso(today)],
  ];
}

export function fmt(value, kind) {
  if (value === null || value === undefined || value === "") {
    return kind === "text" ? "" : "—";
  }
  const n = Number(value);
  if (kind === "money") return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (kind === "num") return n.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  if (kind === "int") return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (kind === "pct") return `${n.toFixed(1)}%`;
  if (kind === "date") {
    const d = new Date(`${value}T00:00:00`);
    return Number.isNaN(d.getTime()) ? value
      : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  }
  return String(value);
}

function Section({ s }) {
  const right = (c) => (c.kind === "text" ? (c.wide ? { minWidth: 200 } : {})
    : { textAlign: "right", whiteSpace: "nowrap" });
  return (
    <div style={{ ...card, marginTop: 14 }}>
      <h3 style={{ margin: "0 0 4px", fontSize: 15 }}>{s.title}</h3>
      {s.note && <p style={{ margin: "0 0 8px", fontSize: 12, color: "var(--muted)" }}>{s.note}</p>}
      {s.rows.length === 0 ? (
        <p style={{ margin: 0, fontSize: 13, color: "var(--muted)" }}>Nothing in this period.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5,
                          fontVariantNumeric: "tabular-nums" }}>
            <thead><tr>{s.columns.map((c) => (
              <th key={c.key} style={{ ...th, ...right(c) }}>{c.label}</th>))}</tr></thead>
            <tbody>
              {s.rows.map((r, i) => (
                <tr key={i}>{s.columns.map((c) => (
                  <td key={c.key} style={{ ...td, ...right(c) }}>{fmt(r[c.key], c.kind)}</td>))}</tr>
              ))}
              {s.total && (
                <tr style={{ background: "var(--sky-soft)", fontWeight: 700 }}>
                  {s.columns.map((c) => (
                    <td key={c.key} style={{ ...td, ...right(c) }}>{fmt(s.total[c.key], c.kind)}</td>))}
                </tr>)}
            </tbody>
          </table>
        </div>)}
    </div>
  );
}

// Ask Claude about the report on screen (owner 2026-11-09). The question goes
// with the report to the server, which answers in the background from
// Planet's own figures within the asker's rights; the page polls, then draws
// the answer — headings, paragraphs, tables — and can print it.
const EXAMPLES = [
  "Compare the last three months and explain the biggest movement",
  "Who are the highest overtime earners, and is it concentrated in a few people?",
  "What should the director act on first here?",
];

function AnswerTable({ t }) {
  const right = (c) => (c.kind === "text" ? {} : { textAlign: "right", whiteSpace: "nowrap" });
  return (
    <div style={{ overflowX: "auto", margin: "6px 0 10px" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5,
                      fontVariantNumeric: "tabular-nums" }}>
        <thead><tr>{t.columns.map((c, i) => (
          <th key={i} style={{ ...th, ...right(c) }}>{c.label}</th>))}</tr></thead>
        <tbody>{t.rows.map((r, i) => (
          <tr key={i}>{t.columns.map((c, j) => (
            <td key={j} style={{ ...td, ...right(c) }}>{fmt(r[j], c.kind)}</td>))}</tr>))}
        </tbody>
      </table>
    </div>
  );
}

function Answer({ a }) {
  const ans = a.answer;
  return (
    <div style={{ marginTop: 8 }}>
      <h3 style={{ margin: "0 0 4px", fontSize: 15 }}>{ans.title}</h3>
      <p style={{ margin: "0 0 10px", fontSize: 13.5 }}>{ans.summary}</p>
      {ans.sections.map((s, i) => (
        <div key={i} style={{ marginTop: 10 }}>
          <h4 style={{ margin: "0 0 4px", fontSize: 13.5, color: "var(--navy)" }}>{s.heading}</h4>
          {s.paragraphs.map((p, j) => <p key={j} style={{ margin: "4px 0", fontSize: 13 }}>{p}</p>)}
          {s.bullets.length > 0 && (
            <ul style={{ margin: "4px 0", paddingLeft: 18, fontSize: 13 }}>
              {s.bullets.map((b, j) => <li key={j}>{b}</li>)}</ul>)}
          {s.table && <AnswerTable t={s.table} />}
        </div>))}
      {ans.caveats.length > 0 && (
        <ul style={{ margin: "10px 0 0", paddingLeft: 18, fontSize: 12.5, color: "var(--muted)" }}>
          {ans.caveats.map((c, j) => <li key={j}>{c}</li>)}</ul>)}
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 10, fontSize: 12,
                    color: "var(--muted)", flexWrap: "wrap" }}>
        <span>{a.model}{a.cost_usd && ` · USD ${Number(a.cost_usd).toFixed(2)}`}</span>
        <a href={`/api/v1/reports/ask/${a.id}?export=pdf`} target="_blank" rel="noreferrer"
           style={{ color: "var(--navy)" }}>⬇ PDF of this conversation</a>
      </div>
    </div>
  );
}

function AskPanel({ reportKey, scope, from, to, siteId }) {
  const [items, setItems] = useState([]);
  const [question, setQuestion] = useState("");
  const [cont, setCont] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setItems([]); setErr(null);
    api(`/reports/asks?report=${encodeURIComponent(reportKey)}&scope=${encodeURIComponent(scope)}`)
      .then((d) => setItems(d.analyses)).catch((e) => setErr(e.message));
  }, [reportKey, scope]);

  const running = items.filter((a) => a.status === "RUNNING");
  useEffect(() => {
    if (running.length === 0) return undefined;
    const id = setInterval(() => {
      running.forEach((r) => api(`/reports/ask/${r.id}`).then((d) => {
        setItems((cur) => cur.map((a) => (a.id === d.analysis.id ? d.analysis : a)));
      }).catch(() => {}));
    }, 3000);
    return () => clearInterval(id);
  }, [running.map((r) => r.id).join(",")]);  // eslint-disable-line react-hooks/exhaustive-deps

  const lastDone = [...items].reverse().find((a) => a.status === "DONE");

  async function ask(text) {
    const q = (text || question).trim();
    if (!q) return;
    setBusy(true); setErr(null);
    try {
      const body = { report: reportKey, site: siteId, from, to, question: q };
      if (cont && lastDone) body.follow_up_of = lastDone.id;
      const d = await api("/reports/ask", { method: "POST", body });
      setItems((cur) => [...cur, d.analysis]);
      setQuestion("");
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  const threads = [];
  items.forEach((a) => {
    const t = threads.find((x) => x.id === a.thread);
    if (t) t.items.push(a); else threads.push({ id: a.thread, items: [a] });
  });

  return (
    <div style={{ ...card, marginTop: 14 }}>
      <h3 style={{ margin: "0 0 4px", fontSize: 15 }}>Ask about this report</h3>
      <p style={{ margin: "0 0 10px", fontSize: 12.5, color: "var(--muted)" }}>
        Ask in plain words — compare months, rank people, explain a movement. Claude works from this
        report and Planet's own figures, within your access, and says what the data cannot show.
        Check any figure before it leaves the company.</p>

      {threads.map((t) => (
        <div key={t.id} style={{ borderTop: "1px solid var(--line)", paddingTop: 10, marginTop: 10 }}>
          {t.items.map((a) => (
            <div key={a.id} style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 13, color: "var(--muted)" }}>
                <b style={{ color: "var(--navy)" }}>You</b> · {new Date(a.started_at).toLocaleString("en-GB", {
                  day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</div>
              <div style={{ fontSize: 13.5, margin: "2px 0 6px", whiteSpace: "pre-wrap" }}>{a.question}</div>
              {a.status === "RUNNING" && (
                <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
                  <div>Working on it…</div>
                  {a.steps.map((s, i) => <div key={i}>· {s}</div>)}
                </div>)}
              {a.status === "FAILED" && (
                <p style={{ color: "var(--red-fg)", fontSize: 13, margin: 0 }}>{a.error}</p>)}
              {a.status === "DONE" && <Answer a={a} />}
            </div>))}
        </div>))}

      <div style={{ marginTop: 12 }}>
        {items.length === 0 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
            {EXAMPLES.map((x) => (
              <button key={x} onClick={() => ask(x)} disabled={busy || running.length > 0}
                style={{ ...ghostButton, padding: "4px 10px", fontSize: 12.5 }}>{x}</button>))}
          </div>)}
        <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={3}
          placeholder={lastDone && cont ? "Follow up on the answer above…" : "Your question…"}
          style={{ ...inputStyle, width: "100%", resize: "vertical", fontFamily: "inherit" }}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ask(); }} />
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 8, flexWrap: "wrap" }}>
          <Btn disabled={busy || running.length > 0 || !question.trim()} onClick={() => ask()}>
            {running.length > 0 ? "Answering…" : "Ask"}</Btn>
          {lastDone && (
            <label style={{ fontSize: 12.5, color: "var(--muted)" }}>
              <input type="checkbox" checked={cont} onChange={(e) => setCont(e.target.checked)} />
              {" "}continue the conversation above</label>)}
          <span style={{ fontSize: 12, color: "var(--muted)" }}>Answers take a minute or two.</span>
        </div>
        {err && <p style={{ color: "var(--red-fg)", fontSize: 13, margin: "8px 0 0" }}>{err}</p>}
      </div>
    </div>
  );
}

export default function ReportsPage() {
  const [meta, setMeta] = useState(null);
  const [key, setKey] = useState("");
  const [site, setSite] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [rep, setRep] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const today = useMemo(() => new Date(), []);

  useEffect(() => {
    api("/reports").then((d) => {
      setMeta(d);
      setKey(d.reports[0]?.key || "");
      setSite(d.company ? "all" : String(d.sites[0]?.id || ""));
      setFrom(d.default_from);
      setTo(d.default_to);
    }).catch((e) => setError(e.message));
  }, []);

  const q = `?site=${encodeURIComponent(site)}&from=${from}&to=${to}`;

  async function show() {
    setBusy(true); setError(null); setRep(null);
    try { setRep(await api(`/reports/${key}${q}`)); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  async function excel() {
    setError(null);
    try { await apiDownload(`/reports/${key}${q}&export=xlsx`); }
    catch (e) { setError(e.message); }
  }

  if (error && !meta) return <div style={card}><p style={{ color: "var(--red-fg)" }}>{error}</p></div>;
  if (!meta) return <p style={{ color: "var(--muted)" }}>Loading…</p>;
  const chosen = meta.reports.find((r) => r.key === key);
  const ready = key && site && from && to;

  return (
    <div>
      <div style={card}>
        <h2 style={{ margin: "0 0 4px" }}>Reports</h2>
        <p style={{ margin: "0 0 12px", fontSize: 13, color: "var(--muted)" }}>
          {meta.company
            ? "For the executive committee: every site, or the company as a whole."
            : "Your sites' reports. Company-wide reports are for the executive committee."}
          {" "}Amounts are in USD.</p>
        <div style={{ display: "grid", gap: 10,
                      gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))" }}>
          <label style={{ fontSize: 12.5 }}>Report
            <select value={key} style={{ ...inputStyle, width: "100%" }}
                    onChange={(e) => {
                      const next = meta.reports.find((r) => r.key === e.target.value);
                      setKey(e.target.value); setRep(null);
                      if (next?.company_only) setSite("all");
                    }}>
              {meta.reports.map((r) => <option key={r.key} value={r.key}>{r.title}</option>)}
            </select></label>
          <label style={{ fontSize: 12.5 }}>Site
            <select value={site} style={{ ...inputStyle, width: "100%" }}
                    onChange={(e) => { setSite(e.target.value); setRep(null); }}>
              {meta.company && <option value="all">Company-wide</option>}
              {!chosen?.company_only && meta.sites.map((s) => (
                <option key={s.id} value={s.id}>{s.code} — {s.name}</option>))}
            </select></label>
          <label style={{ fontSize: 12.5 }}>From
            <input type="date" value={from} max={to || undefined} style={{ ...inputStyle, width: "100%" }}
                   onChange={(e) => { setFrom(e.target.value); setRep(null); }} /></label>
          <label style={{ fontSize: 12.5 }}>To
            <input type="date" value={to} min={from || undefined} style={{ ...inputStyle, width: "100%" }}
                   onChange={(e) => { setTo(e.target.value); setRep(null); }} /></label>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
          {presets(today).map(([label, f, t]) => (
            <button key={label} onClick={() => { setFrom(f); setTo(t); setRep(null); }}
              style={{ ...ghostButton, padding: "4px 10px", fontSize: 12.5,
                       ...(from === f && to === t ? { background: "var(--sky-soft)" } : {}) }}>
              {label}</button>))}
        </div>
        {chosen && <p style={{ margin: "10px 0 0", fontSize: 12.5, color: "var(--muted)" }}>{chosen.description}</p>}
        {meta.sites.length === 0 && (
          <p style={{ margin: "10px 0 0", fontSize: 13, color: "var(--amber-fg)" }}>
            You are not the current PM of any site, so there is nothing to report on.</p>)}
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <Btn disabled={!ready || busy} onClick={show}>{busy ? "Preparing…" : "Show report"}</Btn>
          <a href={ready ? `/api/v1/reports/${key}${q}&export=pdf` : undefined}
             target="_blank" rel="noreferrer" aria-disabled={!ready}
             style={{ ...ghostButton, textDecoration: "none", color: "var(--navy)", padding: "6px 12px",
                      ...(ready ? {} : { opacity: 0.5, pointerEvents: "none" }) }}>⬇ PDF</a>
          <Btn variant="secondary" disabled={!ready} onClick={excel}>⬇ Excel</Btn>
        </div>
        {error && <p style={{ color: "var(--red-fg)", fontSize: 13, margin: "10px 0 0" }}>{error}</p>}
      </div>

      {rep && (
        <>
          <div style={{ ...card, marginTop: 14 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap",
                          alignItems: "baseline" }}>
              <h2 style={{ margin: 0 }}>{rep.title}</h2>
              <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
                {rep.scope} · {rep.period}{rep.months > 1 && ` (${rep.months} months)`} · {rep.currency}</span>
            </div>
            <div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginTop: 14 }}>
              {rep.kpis.map((k) => (
                <Stat key={k.label} value={fmt(k.value, k.kind)} label={k.label} context={k.sub} />))}
            </div>
            {rep.notes.length > 0 && (
              <ul style={{ margin: "14px 0 0", paddingLeft: 18, fontSize: 12.5, color: "var(--muted)" }}>
                {rep.notes.map((n) => <li key={n}>{n}</li>)}
              </ul>)}
          </div>
          <AskPanel reportKey={rep.key} siteId={site} from={from} to={to}
                    scope={site === "all" ? "all"
                      : (meta.sites.find((x) => String(x.id) === String(site))?.code || "")} />
          {rep.sections.map((s, i) => (
            <div key={`${i}-${s.title}`}>
              {s.chapter && <h2 style={{ margin: "26px 0 0", fontSize: 19 }}>{s.chapter}</h2>}
              <Section s={s} />
            </div>))}
        </>)}
    </div>
  );
}
