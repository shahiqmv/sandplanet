import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";

const SITE_MANAGE = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "ADMIN"];
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

function CreateForm({ sub, onCancel, onDone }) {
  const [title, setTitle] = useState("");
  const [rows, setRows] = useState([{ ...BLANK_ROW }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const total = rows.reduce(
    (a, r) => a + (Number(r.qty) || 0) * (Number(r.rate) || 0), 0);

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const clean = rows.filter((r) => r.description.trim());
      await api(`/subcontractors/${sub.id}/agreements`,
                { method: "POST", body: { title, rows: clean } });
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
      </div>
      <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 2 }}>
        {a.title}{a.project_code ? ` · ${a.project_code}` : ""}</div>
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
    </div>
  );
}
