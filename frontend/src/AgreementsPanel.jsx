import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";

const SITE_MANAGE = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "DIRECTOR", "ADMIN"];
const SCA_TONE = {
  DRAFT: "info", SUBMITTED: "warn", PM_APPROVED: "warn", APPROVED: "ok",
  REJECTED: "alert", CANCELLED: "alert", CLOSED: "info",
};
const money = (v) => Number(v || 0).toLocaleString("en-US",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// Subcontract Agreements under one subcontractor (subcontractor module P3).
// The site raises a priced-scope SCA; PM approves, Director activates. View +
// approval ride the generic document endpoints.
export default function AgreementsPanel({ sub, me }) {
  const [list, setList] = useState(null);
  const [openRef, setOpenRef] = useState(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);
  const canManage = SITE_MANAGE.includes(me.role);

  function load() {
    api(`/subcontractors/${sub.id}/agreements`).then(setList)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [sub.id]);

  if (openRef) {
    return <AgreementView docRef={openRef} me={me}
                          onBack={() => { setOpenRef(null); load(); }} />;
  }
  return (
    <div style={{ marginTop: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center" }}>
        <h4 style={{ margin: 0, color: "var(--navy)" }}>Agreements (SCA)</h4>
        {canManage && !creating && (
          <Btn variant="secondary"
               onClick={() => setCreating(true)}>+ New agreement</Btn>
        )}
      </div>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      {creating && (
        <CreateForm sub={sub} onCancel={() => setCreating(false)}
                    onDone={() => { setCreating(false); load(); }} />
      )}
      {list && list.length === 0 && !creating && (
        <p style={{ fontSize: 12.5, color: "var(--muted)" }}>
          No agreements yet.</p>
      )}
      {list && list.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse",
                        marginTop: 8 }}>
          <thead><tr>
            <th style={th}>Ref</th><th style={th}>Title</th>
            <th style={{ ...th, textAlign: "right" }}>Value</th>
            <th style={th}>Status</th><th style={th}></th>
          </tr></thead>
          <tbody>
            {list.map((a) => (
              <tr key={a.ref}>
                <td style={{ ...td, fontFamily: "var(--font-mono)" }}>
                  {a.ref}</td>
                <td style={td}>{a.title}</td>
                <td style={{ ...td, textAlign: "right",
                             fontFamily: "var(--font-mono)" }}>
                  {a.currency} {money(a.value)}</td>
                <td style={td}><Chip tone={SCA_TONE[a.status] || "info"}>
                  {a.status.replace(/_/g, " ")}</Chip></td>
                <td style={{ ...td, textAlign: "right" }}>
                  <Btn variant="secondary"
                       onClick={() => setOpenRef(a.ref)}>Open</Btn></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

const BLANK_ROW = { description: "", unit: "", qty: "", rate: "" };

function ScopeEditor({ rows, setRows }) {
  const set = (i, k) => (e) => {
    const next = rows.slice();
    next[i] = { ...next[i], [k]: e.target.value };
    setRows(next);
  };
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8 }}>
      <thead><tr>
        <th style={th}>Description</th><th style={{ ...th, width: 60 }}>Unit</th>
        <th style={{ ...th, width: 70 }}>Qty</th>
        <th style={{ ...th, width: 90 }}>Rate</th>
        <th style={{ ...th, width: 90, textAlign: "right" }}>Amount</th>
        <th style={{ ...th, width: 30 }}></th>
      </tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            <td style={td}><input style={{ ...inputStyle, width: "100%" }}
              value={r.description} onChange={set(i, "description")} /></td>
            <td style={td}><input style={{ ...inputStyle, width: "100%" }}
              value={r.unit} onChange={set(i, "unit")} /></td>
            <td style={td}><input style={{ ...inputStyle, width: "100%" }}
              value={r.qty} onChange={set(i, "qty")} inputMode="decimal" /></td>
            <td style={td}><input style={{ ...inputStyle, width: "100%" }}
              value={r.rate} onChange={set(i, "rate")} inputMode="decimal" /></td>
            <td style={{ ...td, textAlign: "right",
                         fontFamily: "var(--font-mono)" }}>
              {money((Number(r.qty) || 0) * (Number(r.rate) || 0))}</td>
            <td style={td}>
              <Btn variant="ghost" type="button"
                   onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                ✕</Btn></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const TERMS0 = {
  currency: "MVR", start_date: "", end_date: "", advance_percent: "",
  gst_percent: "", retention_percent: "", payment_days: "", ld_amount: "",
  ld_cap_percent: "", markup_percent: "", ot_rate_per_hour: "",
  friday_rate_per_day: "", day_rate_divisor: "30",
  contractor_signatory_name: "", contractor_signatory_title: "",
  scope_of_work: "",
};

// The agreed cost of one category per day under a day-work agreement. On
// the agreement, not global: every gang negotiates its own, and the rate
// written onto a certificate stays what it was when it was signed (owner
// 2026-09-10). The OT rate is the standard hourly rate the company pays for
// that trade, recorded here so the certificate can be checked against the
// contract rather than against a table that has since moved.
function CreateForm({ sub, onCancel, onDone }) {
  const [title, setTitle] = useState("");
  const [t, setT] = useState({ ...TERMS0 });
  const [rows, setRows] = useState([{ ...BLANK_ROW }]);
  // Measured work prices a scope by quantity; day work hires men by the day
  // at the monthly rate on each man's record and charges a markup. One basis per agreement —
  // a gang doing both signs two (owner 2026-09-10).
  const [basis, setBasis] = useState("MEASURED");
  const [cats, setCats] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const daywork = basis === "DAYWORK";
  useEffect(() => {
    api("/manpower-categories").then((all) => setCats(
      all.filter((c) => c.list_type === "DPR" && c.is_active))).catch(() => {});
  }, []);
  const total = rows.reduce(
    (a, r) => a + (Number(r.qty) || 0) * (Number(r.rate) || 0), 0);
  const set = (k) => (e) => setT((s) => ({ ...s, [k]: e.target.value }));
  const F = ({ k, label, w = 120, type = "text", ph = "" }) => (
    <label style={{ fontSize: 12, color: "var(--muted)" }}>{label}<br />
      <input type={type} value={t[k]} onChange={set(k)} placeholder={ph}
        style={{ ...inputStyle, width: w }} /></label>
  );

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const clean = daywork ? [] : rows.filter((r) => r.description.trim());
      await api(`/subcontractors/${sub.id}/agreements`, { method: "POST",
                body: { title, rows: clean, basis, ...t } });
      onDone();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit} style={{ ...card, background: "var(--paper)",
                                     margin: "8px 0" }}>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      <input style={{ ...inputStyle, width: "100%" }} autoFocus
             placeholder="Agreement title * (e.g. Blockwork package)"
             value={title} onChange={(e) => setTitle(e.target.value)} />
      <div style={{ display: "flex", gap: 14, alignItems: "center",
                    marginTop: 10, fontSize: 13 }}>
        <span style={{ color: "var(--muted)", fontSize: 12 }}>Valued by</span>
        {[["MEASURED", "Measured work — a priced scope"],
          ["DAYWORK", "Day work — men by the day"]].map(([k, label]) => (
          <label key={k} style={{ display: "inline-flex", gap: 5,
                                  alignItems: "center", cursor: "pointer" }}>
            <input type="radio" name="basis" value={k} checked={basis === k}
                   onChange={() => setBasis(k)} />{label}</label>))}
      </div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                    marginTop: 8 }}>
        <F k="currency" label="Currency" w={64} />
        <F k="start_date" label="Commencement" type="date" w={140} />
        <F k="end_date" label="Completion" type="date" w={140} />
        <F k="advance_percent" label="Advance %" type="number" w={80} />
        <F k="gst_percent" label="GST % (0 = unregistered)" type="number"
           w={110} />
        <F k="retention_percent" label="Retention % (0 = none)" type="number"
           w={130} />
        <F k="payment_days" label="Payment days" type="number" w={100} />
        <F k="ld_amount" label="LD / day" type="number" w={100} />
        <F k="ld_cap_percent" label="LD cap %" type="number" w={80} />
        {daywork && (<>
          <F k="markup_percent" label="Markup % (on all labour)" type="number"
             w={150} />
          <F k="ot_rate_per_hour" label="Extra hours / hr" type="number"
             w={120} />
          <F k="friday_rate_per_day" label="Friday rate / day" type="number"
             w={130} />
          <F k="day_rate_divisor" label="Day rate = monthly ÷" type="number"
             w={130} />
        </>)}
      </div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 8 }}>
        <F k="contractor_signatory_name" label="Contractor signatory" w={180}
           ph="defaults to Director, Projects" />
        <F k="contractor_signatory_title" label="Signatory title" w={160} />
      </div>
      <label style={{ fontSize: 12, color: "var(--muted)", display: "block",
                      marginTop: 8 }}>Scope of work (Annexure A)<br />
        <textarea value={t.scope_of_work} onChange={set("scope_of_work")}
          rows={3} placeholder="Narrative description of the works…"
          style={{ ...inputStyle, width: "100%", fontFamily: "inherit",
                   resize: "vertical" }} /></label>
      {daywork ? (
        <div style={{ fontSize: 12, color: "var(--muted)",
                      margin: "10px 0 2px" }}>
          Each man is priced from the monthly rate on his own record — set it
          on the team table above. His day rate is that figure ÷ the divisor;
          a Friday worked earns the flat Friday rate; extra hours the hourly
          rate; the markup goes on all of it.</div>
      ) : (<>
        <div style={{ fontSize: 12, color: "var(--muted)",
                      margin: "10px 0 2px" }}>
          Priced scope (Annexure B)</div>
        <ScopeEditor rows={rows} setRows={setRows} />
        <div style={{ display: "flex", justifyContent: "space-between",
                      marginTop: 8 }}>
          <Btn type="button" variant="ghost"
               onClick={() => setRows([...rows, { ...BLANK_ROW }])}>
            + Add line</Btn>
          <span style={{ fontWeight: 600, color: "var(--navy)" }}>
            Total {money(total)}</span>
        </div>
      </>)}
      <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
        <Btn variant="navy" disabled={busy || !title.trim()}>
          Create draft</Btn>
        <Btn type="button" variant="ghost" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}

function AgreementView({ docRef, me, onBack }) {
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  function load() {
    api(`/documents/${docRef}`).then(setDoc).catch((e) => setError(e.message));
  }
  useEffect(load, [docRef]);

  async function act(action, needComment) {
    let comment = "";
    if (needComment) {
      comment = window.prompt("Reason for returning to the site:") || "";
      if (!comment.trim()) return;
    }
    setBusy(true); setError(null);
    try {
      const updated = await api(`/documents/${docRef}/actions/${action}`,
                                { method: "POST", body: { comment } });
      setDoc(updated);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  if (!doc) {
    return <div><Btn variant="ghost" onClick={onBack}>← Back</Btn>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}</div>;
  }
  const a = doc.subcontract_agreement || {};
  const s = doc.status;
  const isPM = ["PM", "ADMIN"].includes(me.role);
  const isDir = ["DIRECTOR", "ADMIN"].includes(me.role);
  const isSite = SITE_MANAGE.includes(me.role);
  // The agreement PDF carries rates → PM and above (matches the backend gate).
  const canPdf = ["PM", "DIRECTOR", "SIGNATORY", "FINANCE", "QS", "ADMIN"]
    .includes(me.role);
  const daywork = a.basis === "DAYWORK";
  const terms = [
    daywork && "day work",
    daywork && Number(a.markup_percent) > 0 && `${a.markup_percent}% markup`,
    a.advance_percent > 0 && `${a.advance_percent}% advance`,
    a.retention_percent > 0 && `${a.retention_percent}% retention`,
    a.payment_days && `pay in ${a.payment_days} days`,
    a.start_date && a.end_date && `${a.start_date} → ${a.end_date}`,
  ].filter(Boolean).join(" · ");

  const actions = [];
  if (s === "DRAFT" && isSite)
    actions.push(["submit", "Submit for approval", "navy", false]);
  if (s === "SUBMITTED" && isPM) {
    actions.push(["approve", "Approve (PM)", "navy", false]);
    actions.push(["return", "Return", "secondary", true]);
  }
  if (s === "PM_APPROVED" && isDir) {
    actions.push(["approve", "Activate (Director)", "navy", false]);
    actions.push(["return", "Return", "secondary", true]);
  }

  return (
    <div>
      <Btn variant="ghost" onClick={onBack}>← Back</Btn>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                    marginTop: 6 }}>
        <h4 style={{ margin: 0, color: "var(--navy)" }}>{doc.ref}</h4>
        <Chip tone={SCA_TONE[s] || "info"}>{s.replace(/_/g, " ")}</Chip>
        {canPdf && <a href={`/api/v1/subcontract-agreements/${doc.ref}/pdf`}
          target="_blank" rel="noreferrer" style={{ marginLeft: "auto",
            fontSize: 12.5, color: "var(--sky)", textDecoration: "none" }}>
          ⬇ Agreement PDF</a>}
        {/* The percentage could be set and there was no way to pay it, so
            the money was arranged off the system and nothing was recovered
            against it (owner 2026-09-09). */}
        {s === "APPROVED" && Number(a.advance_percent) > 0 && (isSite || isPM
          || isDir) && (
          <Btn variant="secondary" disabled={busy}
               onClick={async () => {
                    setBusy(true); setError(null);
                    try {
                      const r = await api(
                        `/subcontract-agreements/${doc.ref}/advance`,
                        { method: "POST", body: {} });
                      setError(r.detail);
                    } catch (e) { setError(e.message); }
                    finally { setBusy(false); }
                  }}>
            Raise the {Number(a.advance_percent)}% advance</Btn>)}
      </div>
      <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 2 }}>
        {a.title}{a.project_code ? ` · ${a.project_code}` : ""}
        {terms ? ` · ${terms}` : ""}</div>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      {actions.length > 0 && (
        <div style={{ display: "flex", gap: 8, margin: "12px 0" }}>
          {actions.map(([action, label, variant, needC]) => (
            <Btn key={action} variant={variant} disabled={busy}
                 onClick={() => act(action, needC)}>{label}</Btn>
          ))}
        </div>
      )}
      {daywork ? (
        <table style={{ borderCollapse: "collapse", marginTop: 10 }}>
          <tbody>
            {[["Day rate", `monthly rate on each man ÷ ${a.day_rate_divisor || 30}`],
              ["Friday worked", money(a.friday_rate_per_day) + " / day"],
              ["Extra hours", money(a.ot_rate_per_hour) + " / hr"],
              ["Markup", `${Number(a.markup_percent) || 0}% on all labour`]]
              .map(([k, val]) => (
              <tr key={k}>
                <td style={{ ...td, color: "var(--muted)", paddingRight: 16 }}>{k}</td>
                <td style={{ ...td, fontFamily: "var(--font-mono)" }}>{val}</td>
              </tr>))}
          </tbody>
          <tfoot><tr>
            <td colSpan={2} style={{ ...td, fontSize: 12,
                                     color: "var(--muted)" }}>
              Valued monthly off the attendance register. A man with no
              monthly rate on his record blocks the certificate.</td>
          </tr></tfoot>
        </table>
      ) : (
      <table style={{ width: "100%", borderCollapse: "collapse",
                      marginTop: 10 }}>
        <thead><tr>
          <th style={th}>Description</th><th style={th}>Unit</th>
          <th style={{ ...th, textAlign: "right" }}>Qty</th>
          <th style={{ ...th, textAlign: "right" }}>Rate</th>
          <th style={{ ...th, textAlign: "right" }}>Amount</th>
        </tr></thead>
        <tbody>
          {(a.items || []).map((it) => (
            <tr key={it.id} style={it.is_heading ? { fontWeight: 600 } : {}}>
              <td style={td}>{it.section && it.is_heading
                ? it.section : it.description}</td>
              <td style={td}>{it.unit}</td>
              <td style={{ ...td, textAlign: "right" }}>{it.is_heading
                ? "" : it.qty}</td>
              <td style={{ ...td, textAlign: "right" }}>{it.is_heading
                ? "" : money(it.rate)}</td>
              <td style={{ ...td, textAlign: "right",
                           fontFamily: "var(--font-mono)" }}>
                {it.is_heading ? "" : money(it.amount)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot><tr>
          <td style={{ ...td, fontWeight: 700 }} colSpan={4}>
            Agreement value</td>
          <td style={{ ...td, textAlign: "right", fontWeight: 700,
                       fontFamily: "var(--font-mono)" }}>
            {a.currency} {money(a.value)}</td>
        </tr></tfoot>
      </table>
      )}
      {(doc.approvals || []).length > 0 && (
        <div style={{ marginTop: 10, fontSize: 12, color: "var(--muted)" }}>
          {doc.approvals.map((ap, i) => (
            <div key={i}>{ap.action} · {ap.actor_role}
              {ap.comment ? ` — ${ap.comment}` : ""}</div>
          ))}
        </div>
      )}

      {s === "APPROVED" && (
        <Valuations scaRef={doc.ref} me={me} currency={a.currency}
                    basis={a.basis} />)}
    </div>
  );
}

const SITE_TEAM_V = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "DIRECTOR", "ADMIN"];
// The action offered at each SVC status, and who may take it.
const SVC_ACTIONS = {
  DRAFT: [["submit", "Submit for verification", SITE_TEAM_V]],
  SUBMITTED: [["verify", "Verify quantities (PM)", ["PM", "ADMIN"]],
              ["return", "Return", ["PM", "ADMIN"]]],
  PM_VERIFIED: [["approve", "Approve (Director)", ["DIRECTOR", "ADMIN"]],
                ["return", "Return", ["DIRECTOR", "ADMIN"]]],
  DIRECTOR_APPROVED: [["authorise", "Authorise (Signatory)",
                       ["SIGNATORY", "ADMIN"]],
                      ["return", "Return", ["SIGNATORY", "ADMIN"]]],
};

function Valuations({ scaRef, me, currency, basis }) {
  const [list, setList] = useState(null);
  const [openRef, setOpenRef] = useState(null);
  const [error, setError] = useState(null);
  // Day work is valued a month at a time, off the register; the month is
  // the one thing the site has to say. Defaults to last month, which is the
  // one just closed.
  const lastMonth = (() => {
    const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  })();
  const [period, setPeriod] = useState(lastMonth);
  const daywork = basis === "DAYWORK";
  const canRaise = SITE_TEAM_V.includes(me.role);
  const load = () => api(`/subcontract-agreements/${scaRef}/valuations`)
    .then(setList).catch((e) => setError(e.message));
  // NOT useEffect(load, …): load returns a promise, and React treats an
  // effect's return value as the cleanup fn — it crashed the panel on unmount.
  useEffect(() => { load(); }, [scaRef]);

  async function create() {
    setError(null);
    try {
      const body = {};
      if (daywork) {
        const [y, m] = period.split("-");
        body.year = Number(y); body.month = Number(m);
      }
      const v = await api(`/subcontract-agreements/${scaRef}/valuations`,
                          { method: "POST", body });
      setOpenRef(v.ref); load();
    } catch (e) { setError(e.message); }
  }
  if (openRef) return <ValuationView vref={openRef} me={me}
    onBack={() => { setOpenRef(null); load(); }} />;
  return (
    <div style={{ marginTop: 14, borderTop: "1px solid var(--line)",
                  paddingTop: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <h4 style={{ margin: 0, color: "var(--navy)" }}>Valuations</h4>
        {canRaise && daywork && (
          <input type="month" value={period}
                 onChange={(e) => setPeriod(e.target.value)}
                 style={{ ...inputStyle, width: 150, marginLeft: "auto" }} />)}
        {canRaise && <Btn variant="navy" onClick={create}
          style={daywork ? {} : { marginLeft: "auto" }}>
          {daywork ? "Value this month" : "+ New valuation"}</Btn>}
      </div>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      {list && !list.length && (
        <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 6 }}>
          No valuations yet.</div>)}
      {(list || []).map((v) => (
        <div key={v.id} onClick={() => setOpenRef(v.ref)}
          style={{ display: "flex", gap: 10, padding: "6px 0", cursor: "pointer",
            borderBottom: "1px solid var(--line)", fontSize: 13 }}>
          <span style={{ fontFamily: "var(--font-mono)" }}>{v.ref}</span>
          <Chip tone={SCA_TONE[v.status] || "info"}>
            {v.status.replace(/_/g, " ")}</Chip>
          <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono)" }}>
            {currency} {money(v.now_due)}</span>
        </div>
      ))}
    </div>
  );
}

function ValuationView({ vref, me, onBack }) {
  const [d, setD] = useState(null);
  const [rows, setRows] = useState([]);
  const [hdr, setHdr] = useState({ deductions: "", adjustment: "",
    work_done_upto: "", note: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = () => api(`/subcontract-valuations/${vref}`).then((v) => {
    setD(v);
    setRows(v.valuation.lines.map((l) => ({ id: l.id,
      cumulative_qty: l.cumulative_qty })));
    setHdr({ deductions: v.valuation.deductions || "",
      adjustment: v.valuation.adjustment || "",
      work_done_upto: v.work_done_upto || "", note: v.note || "" });
  }).catch((e) => setError(e.message));
  // See Valuations: load returns a promise — don't hand it to useEffect raw.
  useEffect(() => { load(); }, [vref]);

  async function run(fn) {
    setBusy(true); setError(null);
    try { await fn(); } catch (e) { setError(e.message); } finally {
      setBusy(false); }
  }
  const daywork = d?.basis === "DAYWORK";
  // Day-work lines are read, not typed: the PATCH carries only the header.
  const body = () => ({ rows: daywork ? [] : rows, ...hdr });
  const save = () => run(async () => {
    const v = await api(`/subcontract-valuations/${vref}`,
      { method: "PATCH", body: body() });
    setD(v);
  });
  // Attendance is the evidence, not the ledger. A certificate that quietly
  // followed a late edit to the register would not be a certificate, so
  // reading it again is a deliberate act on a draft (owner 2026-09-10).
  const refresh = () => run(async () => {
    const v = await api(`/subcontract-valuations/${vref}/refresh`,
      { method: "POST", body: {} });
    setD(v);
  });
  const act = (action) => {
    let note = "";
    if (action === "return") {
      note = window.prompt("Reason for returning to the site:") || "";
      if (!note.trim()) return;
    }
    run(async () => {
      if (d.status === "DRAFT") await api(`/subcontract-valuations/${vref}`,
        { method: "PATCH", body: body() });   // save before submit
      const v = await api(`/subcontract-valuations/${vref}/action`,
        { method: "POST", body: { action, note } });
      setD(v);
    });
  };

  if (!d) return <div style={{ marginTop: 12 }}>
    <Btn variant="ghost" onClick={onBack}>← Valuations</Btn>
    {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}</div>;
  const v = d.valuation;
  const editable = d.status === "DRAFT" && SITE_TEAM_V.includes(me.role);
  const setQ = (i, val) => setRows((rs) =>
    rs.map((r, j) => j === i ? { ...r, cumulative_qty: val } : r));
  const actions = (SVC_ACTIONS[d.status] || [])
    .filter(([, , roles]) => roles.includes(me.role));

  // While drafting, mirror the server's valuation math live from the typed
  // quantities — the team shouldn't have to Save just to see the numbers.
  // The server recomputes authoritatively on save/submit.
  const n = (x) => { const f = Number(x); return Number.isFinite(f) ? f : 0; };
  let live = v;
  if (editable && !daywork) {
    let gross = 0;
    const lines = v.lines.map((l, i) => {
      const cum = n(rows[i]?.cumulative_qty);
      const thisQty = cum - n(l.previous_qty);
      const thisValue = thisQty * n(l.rate);
      gross += cum * n(l.rate);
      return { ...l, cumulative_qty: cum, this_qty: thisQty,
               this_value: thisValue,
               over: n(l.contract_qty) > 0 && cum > n(l.contract_qty) };
    });
    // Mirrors subcontract.svc_valuation so the figures do not disagree with
    // the server while the clerk is typing. The advance comes off at the
    // contract percentage, capped at what was actually advanced, and GST
    // rides on the money changing hands (owner 2026-09-09).
    const retention = n(v.retention_pct) / 100 * gross;
    const net = gross - retention - n(hdr.deductions) + n(hdr.adjustment);
    const advPaid = n(v.advance_paid);
    const advRec = advPaid > 0
      ? Math.min(n(v.advance_percent) / 100 * gross, advPaid) : 0;
    const due = net - advRec - n(v.paid_to_date);
    const gstPct = n(v.gst_percent);
    const gst = due > 0 && gstPct > 0 ? due * gstPct / 100 : 0;
    live = { ...v, lines, gross_cumulative: gross,
      retention_held: retention,
      deductions: n(hdr.deductions), adjustment: n(hdr.adjustment),
      net_cumulative: net, paid_to_date: n(v.paid_to_date),
      advance_paid: advPaid, advance_recovered: advRec,
      advance_outstanding: advPaid - advRec,
      now_due: due, gst_percent: gstPct, gst, total_payable: due + gst,
      over_warning: lines.some((l) => l.over) };
  }

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Btn variant="ghost" onClick={onBack}>← Valuations</Btn>
        <b style={{ fontFamily: "var(--font-mono)" }}>{d.ref}</b>
        <Chip tone={SCA_TONE[d.status] || "info"}>
          {d.status.replace(/_/g, " ")}</Chip>
        {live.over_warning && <Chip tone="alert">over-contract qty</Chip>}
        {daywork && d.period_from && (
          <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
            {d.period_from} → {d.period_to}</span>)}
        {daywork && (v.unpriced || []).length > 0 && (
          <Chip tone="alert">{v.unpriced.length} without a monthly rate</Chip>)}
        {daywork && Number(v.pending_hours) > 0 && (
          <Chip tone="warn">{num(v.pending_hours)} extra hours on{" "}
            {v.pending_men} awaiting PM approval</Chip>)}
        {d.status !== "DRAFT" && ["PM", "DIRECTOR", "SIGNATORY", "FINANCE",
                                  "ADMIN", "QS"].includes(me.role) && (
          <a href={`/api/v1/subcontract-valuations/${d.ref}/certificate.pdf`}
             target="_blank" rel="noreferrer"
             style={{ marginLeft: "auto", fontSize: 13, fontWeight: 600,
                      color: "var(--navy)", textDecoration: "none" }}>
            ↓ Certificate PDF</a>)}
      </div>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      {daywork && (v.unpriced || []).length > 0 && (
        <p style={{ fontSize: 12.5, color: "var(--red-fg)", margin: "6px 0 0" }}>
          No monthly rate on record for {v.unpriced.join(", ")} — set it on
          the subcontractor's team table, then refresh this valuation.</p>)}
      {daywork ? (
      <div style={{ overflowX: "auto", marginTop: 8 }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
          fontSize: 12.5 }}>
          <thead><tr>
            {["Worker", "Category", "Weekdays", "Rate/day", "Fridays",
              "Friday rate", "Extra hrs", "Rate/hr", "Amount"].map((h, i) => (
              <th key={h} style={{ ...th, textAlign: i > 1 ? "right" : "left" }}>
                {h}</th>))}
          </tr></thead>
          <tbody>
            {v.lines.map((l) => (
              <tr key={l.id} style={l.priced ? {} : { background: "#FDECEA" }}>
                <td style={td}>{l.emp_no} · {l.name}</td>
                <td style={td}>{l.category || "—"}</td>
                <td style={{ ...td, textAlign: "right" }}>{num(l.days)}</td>
                <td style={{ ...td, textAlign: "right" }}>{money(l.rate_per_day)}</td>
                <td style={{ ...td, textAlign: "right" }}>{num(l.friday_days)}</td>
                <td style={{ ...td, textAlign: "right" }}>{money(l.friday_rate_per_day)}</td>
                <td style={{ ...td, textAlign: "right" }}>{num(l.ot_hours)}</td>
                <td style={{ ...td, textAlign: "right" }}>{money(l.ot_rate_per_hour)}</td>
                <td style={{ ...td, textAlign: "right",
                  fontFamily: "var(--font-mono)" }}>{money(l.amount)}</td>
              </tr>))}
            {!v.lines.length && (
              <tr><td colSpan={9} style={{ ...td, color: "var(--muted)" }}>
                Nobody was marked on the register for this period.</td></tr>)}
          </tbody>
          <tfoot>
            {[["Weekdays", v.days_value],
              ["Fridays", v.friday_value],
              ["Extra hours", v.ot_value],
              ["Labour supplied", v.labour],
              ...(Number(v.markup) > 0
                ? [[`Markup at ${Number(v.markup_percent)}%`, v.markup]] : []),
              ["Value of labour this period", v.period_gross]].map(
              ([k, val], i, arr) => (
              <tr key={k} style={i === arr.length - 1
                ? { fontWeight: 700, color: "var(--navy)" } : {}}>
                <td colSpan={8} style={{ ...td, textAlign: "right" }}>{k}</td>
                <td style={{ ...td, textAlign: "right",
                  fontFamily: "var(--font-mono)" }}>{money(val)}</td>
              </tr>))}
          </tfoot>
        </table>
      </div>
      ) : (
      <div style={{ overflowX: "auto", marginTop: 8 }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
          fontSize: 12.5 }}>
          <thead><tr>
            {["Item", "Unit", "Contract qty", "Prev", "Cumulative", "This",
              "This value"].map((h, i) => (
              <th key={h} style={{ ...th, textAlign: i > 1 ? "right" : "left" }}>
                {h}</th>))}
          </tr></thead>
          <tbody>
            {live.lines.map((l, i) => (
              <tr key={l.id} style={l.over ? { background: "#FDECEA" } : {}}>
                <td style={td}>{l.item_code ? `${l.item_code} · ` : ""}
                  {l.description}</td>
                <td style={td}>{l.unit}</td>
                <td style={{ ...td, textAlign: "right" }}>{num(l.contract_qty)}</td>
                <td style={{ ...td, textAlign: "right" }}>{num(l.previous_qty)}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {editable ? <input type="number" value={rows[i]?.cumulative_qty}
                    onChange={(e) => setQ(i, e.target.value)}
                    style={{ ...inputStyle, width: 80, textAlign: "right" }} />
                    : num(l.cumulative_qty)}</td>
                <td style={{ ...td, textAlign: "right" }}>{num(l.this_qty)}</td>
                <td style={{ ...td, textAlign: "right",
                  fontFamily: "var(--font-mono)" }}>{money(l.this_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}

      {editable && (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
          marginTop: 8 }}>
          <label style={{ fontSize: 12 }}>Deductions (cum.)<br />
            <input type="number" value={hdr.deductions} onChange={(e) =>
              setHdr({ ...hdr, deductions: e.target.value })}
              style={{ ...inputStyle, width: 110 }} /></label>
          <label style={{ fontSize: 12 }}>Adjustment (+/-)<br />
            <input type="number" value={hdr.adjustment} onChange={(e) =>
              setHdr({ ...hdr, adjustment: e.target.value })}
              style={{ ...inputStyle, width: 110 }} /></label>
          <label style={{ fontSize: 12 }}>Work done up to<br />
            <input type="date" value={hdr.work_done_upto} onChange={(e) =>
              setHdr({ ...hdr, work_done_upto: e.target.value })}
              style={{ ...inputStyle, width: 150 }} /></label>
        </div>)}

      <table style={{ marginTop: 10, fontSize: 13, borderCollapse: "collapse" }}>
        <tbody>
          {[["Gross certified to date", live.gross_cumulative],
            [`Less retention held (${Number(v.retention_pct) || 0}%)`,
             neg(live.retention_held)],
            ["Less deductions", neg(live.deductions)],
            ["Adjustment", live.adjustment],
            ["Net certified to date", live.net_cumulative],
            // The advance comes off at the contract percentage, capped at
            // what was actually advanced (owner 2026-09-09).
            ...(Number(live.advance_paid) > 0
              ? [[`Less advance recovered (${
                    Number(live.advance_percent) || 0}% of gross)`,
                  neg(live.advance_recovered)]]
              : []),
            ["Less paid to date (settled valuations)",
             neg(live.paid_to_date)]].map(
            ([k, val], i) => (
            <tr key={i}><td style={{ padding: "2px 16px 2px 0",
              color: "var(--muted)" }}>{k}</td>
              <td style={{ padding: "2px 0", textAlign: "right",
                fontFamily: "var(--font-mono)" }}>{money(val)}</td></tr>))}
          {Number(live.gst) > 0 && (
            <tr><td style={{ padding: "2px 16px 2px 0",
              color: "var(--muted)" }}>
              Certificate value</td>
              <td style={{ padding: "2px 0", textAlign: "right",
                fontFamily: "var(--font-mono)" }}>{money(live.now_due)}</td>
            </tr>)}
          {Number(live.gst) > 0 && (
            <tr><td style={{ padding: "2px 16px 2px 0",
              color: "var(--muted)" }}>
              GST at {Number(live.gst_percent)}%</td>
              <td style={{ padding: "2px 0", textAlign: "right",
                fontFamily: "var(--font-mono)" }}>{money(live.gst)}</td>
            </tr>)}
          <tr><td style={{ padding: "4px 16px 4px 0", fontWeight: 700 }}>
            Amount now payable</td>
            <td style={{ padding: "4px 0", textAlign: "right", fontWeight: 700,
              fontFamily: "var(--font-mono)" }}>
              {v.currency} {money(live.total_payable ?? live.now_due)}</td></tr>
          {Number(live.advance_outstanding) > 0 && (
            <tr><td colSpan={2} style={{ padding: "6px 0 0",
              fontSize: 11.5, color: "var(--muted)" }}>
              Advance outstanding after this certificate:{" "}
              {v.currency} {money(live.advance_outstanding)}</td></tr>)}
        </tbody>
      </table>

      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        {editable && <Btn variant="secondary" disabled={busy}
          onClick={save}>Save</Btn>}
        {editable && daywork && <Btn variant="ghost" disabled={busy}
          onClick={refresh}
          title="Read the attendance register again — only while this is a draft">
          ↻ Refresh from register</Btn>}
        {actions.map(([action, label]) => (
          <Btn key={action} variant={action === "return" ? "ghost" : "navy"}
            disabled={busy} onClick={() => act(action)}>{label}</Btn>))}
      </div>
    </div>
  );
}

const num = (v) => v == null || v === "" ? "" : Number(v).toLocaleString(
  "en-US", { maximumFractionDigits: 3 });
const neg = (v) => { const n = Number(v || 0); return n ? -n : 0; };
