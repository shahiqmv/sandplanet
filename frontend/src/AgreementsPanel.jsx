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
  retention_percent: "", payment_days: "", ld_amount: "", ld_cap_percent: "",
  contractor_signatory_name: "", contractor_signatory_title: "",
  scope_of_work: "",
};

function CreateForm({ sub, onCancel, onDone }) {
  const [title, setTitle] = useState("");
  const [t, setT] = useState({ ...TERMS0 });
  const [rows, setRows] = useState([{ ...BLANK_ROW }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
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
      const clean = rows.filter((r) => r.description.trim());
      await api(`/subcontractors/${sub.id}/agreements`,
                { method: "POST", body: { title, rows: clean, ...t } });
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
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                    marginTop: 8 }}>
        <F k="currency" label="Currency" w={64} />
        <F k="start_date" label="Commencement" type="date" w={140} />
        <F k="end_date" label="Completion" type="date" w={140} />
        <F k="advance_percent" label="Advance %" type="number" w={80} />
        <F k="retention_percent" label="Retention % (0 = none)" type="number"
           w={130} />
        <F k="payment_days" label="Payment days" type="number" w={100} />
        <F k="ld_amount" label="LD / day" type="number" w={100} />
        <F k="ld_cap_percent" label="LD cap %" type="number" w={80} />
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
      <div style={{ fontSize: 12, color: "var(--muted)", margin: "10px 0 2px" }}>
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
  const terms = [
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
      {(doc.approvals || []).length > 0 && (
        <div style={{ marginTop: 10, fontSize: 12, color: "var(--muted)" }}>
          {doc.approvals.map((ap, i) => (
            <div key={i}>{ap.action} · {ap.actor_role}
              {ap.comment ? ` — ${ap.comment}` : ""}</div>
          ))}
        </div>
      )}

      {s === "APPROVED" && (
        <Valuations scaRef={doc.ref} me={me} currency={a.currency} />)}
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

function Valuations({ scaRef, me, currency }) {
  const [list, setList] = useState(null);
  const [openRef, setOpenRef] = useState(null);
  const [error, setError] = useState(null);
  const canRaise = SITE_TEAM_V.includes(me.role);
  const load = () => api(`/subcontract-agreements/${scaRef}/valuations`)
    .then(setList).catch((e) => setError(e.message));
  // NOT useEffect(load, …): load returns a promise, and React treats an
  // effect's return value as the cleanup fn — it crashed the panel on unmount.
  useEffect(() => { load(); }, [scaRef]);

  async function create() {
    setError(null);
    try {
      const v = await api(`/subcontract-agreements/${scaRef}/valuations`,
                          { method: "POST" });
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
        {canRaise && <Btn variant="navy" onClick={create}
          style={{ marginLeft: "auto" }}>+ New valuation</Btn>}
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
  const save = () => run(async () => {
    const v = await api(`/subcontract-valuations/${vref}`,
      { method: "PATCH", body: { rows, ...hdr } });
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
        { method: "PATCH", body: { rows, ...hdr } });   // save before submit
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
  if (editable) {
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
    // Mirrors subcontract._svc_net_cumulative: no advance recovery — what has
    // genuinely been paid is netted off once, at now_due (owner 2026-08-13).
    const retention = n(v.retention_pct) / 100 * gross;
    const net = gross - retention - n(hdr.deductions) + n(hdr.adjustment);
    live = { ...v, lines, gross_cumulative: gross,
      retention_held: retention,
      deductions: n(hdr.deductions), adjustment: n(hdr.adjustment),
      net_cumulative: net, paid_to_date: n(v.paid_to_date),
      now_due: net - n(v.paid_to_date),
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
        {d.status !== "DRAFT" && ["PM", "DIRECTOR", "SIGNATORY", "FINANCE",
                                  "ADMIN", "QS"].includes(me.role) && (
          <a href={`/api/v1/subcontract-valuations/${d.ref}/certificate.pdf`}
             target="_blank" rel="noreferrer"
             style={{ marginLeft: "auto", fontSize: 13, fontWeight: 600,
                      color: "var(--navy)", textDecoration: "none" }}>
            ↓ Certificate PDF</a>)}
      </div>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
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
            ["Less paid to date (advances + settled valuations)",
             neg(live.paid_to_date)]].map(
            ([k, val], i) => (
            <tr key={i}><td style={{ padding: "2px 16px 2px 0",
              color: "var(--muted)" }}>{k}</td>
              <td style={{ padding: "2px 0", textAlign: "right",
                fontFamily: "var(--font-mono)" }}>{money(val)}</td></tr>))}
          <tr><td style={{ padding: "4px 16px 4px 0", fontWeight: 700 }}>
            Amount now payable</td>
            <td style={{ padding: "4px 0", textAlign: "right", fontWeight: 700,
              fontFamily: "var(--font-mono)" }}>
              {v.currency} {money(live.now_due)}</td></tr>
        </tbody>
      </table>

      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        {editable && <Btn variant="secondary" disabled={busy}
          onClick={save}>Save</Btn>}
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
