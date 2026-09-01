import { Fragment, useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Chip, Eyebrow, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

const EDIT_ROLES = ["PM", "ADMIN", "DIRECTOR", "QS"];
const fmt = (v) =>
  Number(v || 0).toLocaleString("en-US", { minimumFractionDigits: 2,
    maximumFractionDigits: 2 });
const signed = (v) => (Number(v) < 0 ? `(${fmt(-v)})` : fmt(v));
// Two approvals, not one (owner 2026-08-22): the Director approves the
// priced draft INTERNALLY; only the Employer's approval puts it in the
// contract sum. "Approved" here always means the Employer.
const STATUS_TONE = { DRAFT: "info", PD_PENDING: "warn", PD_APPROVED: "info",
  SUBMITTED: "info", APPROVED: "ok", REJECTED: "alert" };
const DIRECTOR_ROLES = ["DIRECTOR", "ADMIN"];

// Variation orders (VOs) — additions/omissions to the contract that adjust the
// revised sum once approved and become claimable alongside the BOQ.
export default function VariationsPanel({ projectId, me }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);
  const [editId, setEditId] = useState(null);
  const [approvingId, setApprovingId] = useState(null);  // employer form
  const canEdit = EDIT_ROLES.includes(me.role);
  const isDirector = DIRECTOR_ROLES.includes(me.role);

  function load() {
    setError(null);
    api(`/projects/${projectId}/variations`).then(setData)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function status(id, s, extra) {
    setError(null);
    try { setData(await api(`/variations/${id}/status`,
      { method: "POST", body: { status: s, ...(extra || {}) } })); }
    catch (e) { setError(e.message); }
  }
  function returnToDraft(id) {
    const comment = window.prompt("Reason for sending it back:");
    if (!comment) return;
    status(id, "DRAFT", { comment });
  }
  async function del(id) {
    setError(null);
    try { setData(await api(`/variations/${id}`, { method: "DELETE" })); }
    catch (e) { setError(e.message); }
  }

  if (error && !data) return <section style={card}>{error}</section>;
  if (!data) return <section style={card}>Loading…</section>;
  const ccy = data.currency;
  const c = data.contract;

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "center", gap: 12,
                    marginBottom: 8 }}>
        <Eyebrow meta={`${data.variations.length}`}>Variations</Eyebrow>
        {canEdit && !adding && !editId && (
          <button style={{ ...ghostButton, marginLeft: "auto",
                           padding: "4px 12px" }}
                  onClick={() => setAdding(true)}>+ New variation</button>
        )}
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {/* Contract summary — the IPA §C–E block */}
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap",
                    fontSize: 13, marginBottom: 12 }}>
        <Fig label="Original contract" v={`${ccy} ${fmt(c.original)}`} />
        <Fig label="Approved VOs"
             v={`${ccy} ${signed(c.approved_net)}`} tone />
        <Fig label="Revised contract" v={`${ccy} ${fmt(c.revised)}`} strong />
        {Number(c.pending_net) !== 0 && (
          <>
            <Fig label="With the Employer"
                 v={`${ccy} ${signed(c.pending_net)}`} />
            <Fig label="Forecast" v={`${ccy} ${fmt(c.forecast)}`} />
          </>
        )}
        {Number(c.internal_net || 0) !== 0 && (
          <Fig label="Internal — not yet sent"
               v={`${ccy} ${signed(c.internal_net)}`} />
        )}
      </div>

      {adding && (
        <VariationEditor projectId={projectId} onDone={(d) => {
          if (d) setData(d); setAdding(false); }} />
      )}

      {data.variations.length === 0 && !adding ? (
        <p style={{ color: "var(--muted)", fontSize: 13 }}>
          No variations yet.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
            <thead><tr>
              <th style={th}>Ref</th><th style={th}>Title</th>
              <th style={th}>Type</th><th style={th}>Status</th>
              <th style={{ ...th, textAlign: "right" }}>Net {ccy}</th>
              <th style={th} />
            </tr></thead>
            <tbody>
              {data.variations.map((v) => (
                <Fragment key={v.id}>
                  <tr>
                    <td style={td}>{v.ref}</td>
                    <td style={td}>{v.title || "—"}
                      {v.status === "APPROVED" && v.employer_approved_on && (
                        <div style={{ fontSize: 11, color: "var(--muted)" }}>
                          Employer approved {v.employer_approved_on}
                          {v.employer_ref ? ` · ${v.employer_ref}` : ""}
                          {v.employer_copy_url && (<>
                            {" · "}<a href={v.employer_copy_url} target="_blank"
                              rel="noreferrer">signed copy</a></>)}
                        </div>)}
                      {["PD_APPROVED", "SUBMITTED"].includes(v.status)
                        && v.pd_approved_by_name && (
                        <div style={{ fontSize: 11, color: "var(--muted)" }}>
                          PD approved · {v.pd_approved_by_name}
                          {v.sent_at ? ` · sent ${v.sent_at}` : ""}
                        </div>)}
                    </td>
                    <td style={td}>{v.kind === "OMISSION" ? "Omission"
                      : "Addition"}</td>
                    <td style={td}>
                      <Chip tone={STATUS_TONE[v.status] || "info"}>
                        {v.status_label || v.status}</Chip></td>
                    <td style={{ ...td, textAlign: "right", fontWeight: 600,
                      color: Number(v.signed_total) < 0 ? "#b0402f"
                        : "inherit" }}>
                      {signed(v.signed_total)}</td>
                    <td style={{ ...td, textAlign: "right",
                                 whiteSpace: "nowrap" }}>
                      {/* A variation changes what the client owes, so it goes
                          to them as a document they can file and sign. Not on
                          a draft — that price is not one we stand behind yet
                          (owner 2026-08-22). */}
                      {!["DRAFT", "PD_PENDING"].includes(v.status) && (
                        <a href={`/api/v1/variations/${v.id}/vo.pdf`}
                           target="_blank" rel="noreferrer"
                           title="Variation order to send to the client"
                           style={{ ...ghostButton, padding: "2px 7px",
                                    fontSize: 12, color: "var(--navy)",
                                    textDecoration: "none",
                                    display: "inline-block" }}>
                          ⬇ VO PDF</a>
                      )}
                      {/* The working copy, unlike the PDF, IS offered on a
                          draft — working the price before we stand behind it
                          is the point of it (owner 2026-09-01). */}
                      <a href={`/api/v1/variations/${v.id}/vo.xlsx`}
                         title="Spreadsheet working copy — live formulas"
                         style={{ ...ghostButton, padding: "2px 7px",
                                  fontSize: 12, color: "var(--navy)",
                                  textDecoration: "none",
                                  display: "inline-block" }}>
                        ⬇ Excel</a>
                      {canEdit && v.status === "DRAFT" && (<>
                        <A onClick={() => setEditId(
                          editId === v.id ? null : v.id)}>edit</A>
                        <A onClick={() => status(v.id, "PD_PENDING")}>
                          send to PD</A>
                        <A danger onClick={() => del(v.id)}>delete</A>
                      </>)}
                      {v.status === "PD_PENDING" && (<>
                        {isDirector && (
                          <A onClick={() => status(v.id, "PD_APPROVED")}>
                            approve (PD)</A>)}
                        {(isDirector || canEdit) && (
                          <A danger onClick={() => returnToDraft(v.id)}>
                            {isDirector ? "return" : "withdraw"}</A>)}
                      </>)}
                      {canEdit && v.status === "PD_APPROVED" && (<>
                        <A onClick={() => status(v.id, "SUBMITTED")}>
                          send to Employer</A>
                        <A onClick={() => setEditId(
                          editId === v.id ? null : v.id)}>
                          {editId === v.id ? "close" : "view / edit"}</A>
                      </>)}
                      {canEdit && v.status === "SUBMITTED" && (<>
                        <A onClick={() => setApprovingId(
                          approvingId === v.id ? null : v.id)}>
                          record Employer approval</A>
                        <A danger onClick={() => status(v.id, "REJECTED")}>
                          rejected by Employer</A>
                        <A onClick={() => returnToDraft(v.id)}>withdraw</A>
                      </>)}
                      {/* an approved VO stays viewable — and editable until
                          a submitted/certified claim carries it (the server
                          refuses after that); editing invalidates both
                          approvals and it runs the chain again */}
                      {canEdit && v.status === "APPROVED" && (
                        <A onClick={() => setEditId(
                          editId === v.id ? null : v.id)}>
                          {editId === v.id ? "close" : "view / edit"}</A>
                      )}
                      {canEdit && v.status === "REJECTED" && (
                        <A onClick={() => status(v.id, "DRAFT")}>reopen</A>
                      )}
                    </td>
                  </tr>
                  {editId === v.id && (
                    <tr><td colSpan={6} style={{ padding: 0 }}>
                      <VariationEditor variation={v} onDone={(d) => {
                        if (d) setData(d); setEditId(null); }} />
                    </td></tr>
                  )}
                  {approvingId === v.id && (
                    <tr><td colSpan={6} style={{ padding: 0 }}>
                      <EmployerApprovalForm variation={v} onDone={(d) => {
                        if (d) setData(d); setApprovingId(null); }} />
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// The Employer's approval is a fact — a date and the client's reference —
// not a button. The countersigned copy is optional: many clients approve by
// email (owner 2026-08-22).
function EmployerApprovalForm({ variation, onDone }) {
  const [on, setOn] = useState("");
  const [ref, setRef] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function save() {
    setBusy(true); setErr(null);
    try {
      let d = await api(`/variations/${variation.id}/status`,
        { method: "POST", body: { status: "APPROVED",
                                  employer_approved_on: on,
                                  employer_ref: ref } });
      if (file) {
        const fd = new FormData();
        fd.append("file", file);
        d = await apiUpload(`/variations/${variation.id}/employer-copy`, fd);
      }
      onDone(d);
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  return (
    <div style={{ padding: "10px 12px", background: "var(--sky-soft)",
                  display: "flex", gap: 10, flexWrap: "wrap",
                  alignItems: "flex-end" }}>
      <label style={{ fontSize: 12, color: "var(--muted)",
                      display: "flex", flexDirection: "column", gap: 3 }}>
        Employer approved on
        <input type="date" value={on} onChange={(e) => setOn(e.target.value)}
               style={inputStyle} />
      </label>
      <label style={{ fontSize: 12, color: "var(--muted)", flex: 1,
                      minWidth: 220, display: "flex",
                      flexDirection: "column", gap: 3 }}>
        Employer's reference (letter / email / instruction)
        <input value={ref} onChange={(e) => setRef(e.target.value)}
               placeholder="e.g. Email from J. Smith, 15 Aug 2026"
               style={inputStyle} />
      </label>
      <label style={{ fontSize: 12, color: "var(--muted)",
                      display: "flex", flexDirection: "column", gap: 3 }}>
        Countersigned copy (optional)
        <input type="file" accept="application/pdf,image/*"
               onChange={(e) => setFile(e.target.files?.[0] || null)} />
      </label>
      <button style={buttonStyle} disabled={busy || !on || !ref.trim()}
              onClick={save}>{busy ? "Saving…" : "Mark approved by Employer"}</button>
      <button style={ghostButton} onClick={() => onDone(null)}>Cancel</button>
      {err && <div style={{ color: "#c0392b", fontSize: 12.5,
                            width: "100%" }}>{err}</div>}
    </div>
  );
}

function Fig({ label, v, strong, tone }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: "var(--muted)",
                    textTransform: "uppercase", letterSpacing: ".04em" }}>
        {label}</div>
      <div style={{ fontWeight: strong ? 700 : 500,
                    fontSize: strong ? 15 : 13,
                    color: tone ? "var(--navy)" : "inherit" }}>{v}</div>
    </div>
  );
}

function A({ children, onClick, danger }) {
  return (
    <button style={{ ...ghostButton, padding: "2px 7px", fontSize: 12,
                     color: danger ? "#c0392b" : "var(--navy)" }}
            onClick={onClick}>{children}</button>
  );
}

const cell = (w) => ({ ...inputStyle, width: w, padding: "3px 5px",
  fontSize: 12 });

// Create (no `variation`) or edit an existing draft variation's header + items.
function VariationEditor({ projectId, variation, onDone }) {
  const isNew = !variation;
  const [title, setTitle] = useState(variation?.title || "");
  const [kind, setKind] = useState(variation?.kind || "ADDITION");
  const blank = () => ({ section: "", item_code: "", description: "",
    unit: "", qty: "", rate_supply: "", rate_install: "", is_heading: false });
  const [rows, setRows] = useState(
    variation?.items?.length
      ? variation.items.map((i) => ({ section: i.section,
          item_code: i.item_code, description: i.description, unit: i.unit,
          qty: i.qty ?? "", rate_supply: i.rate_supply ?? "",
          rate_install: i.rate_install ?? "", is_heading: i.is_heading }))
      : [blank()]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (i, k, v) =>
    setRows(rows.map((r, j) => j === i ? { ...r, [k]: v } : r));

  async function save() {
    setError(null); setBusy(true);
    try {
      if (isNew) {
        const d = await api(`/projects/${projectId}/variations/create`,
          { method: "POST", body: { title, kind, rows } });
        onDone(d);
      } else {
        await api(`/variations/${variation.id}/meta`,
          { method: "POST", body: { title, kind } });
        const d = await api(`/variations/${variation.id}/items`,
          { method: "POST", body: { rows } });
        onDone(d);
      }
    } catch (e) { setError(e.message); setBusy(false); }
  }

  return (
    <div style={{ ...card, margin: "8px 0", background: "var(--sp-tint,#f5f8fb)" }}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                    alignItems: "center", marginBottom: 8 }}>
        <strong style={{ fontSize: 13, color: "var(--navy)" }}>
          {isNew ? "New variation" : `Edit ${variation.ref}`}</strong>
        {variation?.status === "APPROVED" && (
          <span style={{ fontSize: 12, color: "#8a6d00" }}>
            ⚠ Saving changes sends this VO back through approval — it leaves
            the revised contract sum until re-approved.</span>)}
        <input placeholder="Title (e.g. Extra coping stone)" value={title}
               onChange={(e) => setTitle(e.target.value)}
               style={{ ...inputStyle, flex: "1 1 240px" }} />
        <select value={kind} onChange={(e) => setKind(e.target.value)}
                style={{ ...inputStyle, width: 130 }}>
          <option value="ADDITION">Addition</option>
          <option value="OMISSION">Omission</option>
        </select>
        <button style={{ ...buttonStyle, padding: "4px 14px" }} disabled={busy}
                onClick={save}>{busy ? "Saving…" : "Save"}</button>
        <button style={ghostButton} onClick={() => onDone(null)}>Cancel</button>
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 12 }}>
          <thead><tr>
            {["", "Code", "Description", "Unit", "Qty", "Material", "Labour", ""]
              .map((h, i) => <th key={i} style={th}>{h}</th>)}
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td style={td}><input type="checkbox" checked={r.is_heading}
                  title="Heading row"
                  onChange={(e) => set(i, "is_heading", e.target.checked)} /></td>
                <td style={td}><input value={r.item_code} style={cell(56)}
                  onChange={(e) => set(i, "item_code", e.target.value)} /></td>
                <td style={td}><input value={r.description} style={cell(240)}
                  onChange={(e) => set(i, "description", e.target.value)} /></td>
                <td style={td}><input value={r.unit} style={cell(50)}
                  disabled={r.is_heading}
                  onChange={(e) => set(i, "unit", e.target.value)} /></td>
                <td style={td}><input value={r.qty} type="number" style={cell(64)}
                  disabled={r.is_heading}
                  onChange={(e) => set(i, "qty", e.target.value)} /></td>
                <td style={td}><input value={r.rate_supply} type="number"
                  style={cell(76)} disabled={r.is_heading}
                  onChange={(e) => set(i, "rate_supply", e.target.value)} /></td>
                <td style={td}><input value={r.rate_install} type="number"
                  style={cell(76)} disabled={r.is_heading}
                  onChange={(e) => set(i, "rate_install", e.target.value)} /></td>
                <td style={td}>
                  <button style={{ ...ghostButton, color: "#c0392b",
                                   padding: "2px 8px" }}
                          onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                    ×</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button style={{ ...ghostButton, padding: "3px 10px", marginTop: 8 }}
              onClick={() => setRows([...rows, blank()])}>+ row</button>
    </div>
  );
}
