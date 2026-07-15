import { Fragment, useEffect, useState } from "react";
import { api } from "./api.js";
import { Chip, Eyebrow, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

const EDIT_ROLES = ["PM", "ADMIN", "DIRECTOR", "QS"];
const fmt = (v) =>
  Number(v || 0).toLocaleString("en-US", { minimumFractionDigits: 2,
    maximumFractionDigits: 2 });
const signed = (v) => (Number(v) < 0 ? `(${fmt(-v)})` : fmt(v));
const STATUS_TONE = { DRAFT: "info", SUBMITTED: "info", APPROVED: "ok",
  REJECTED: "alert" };

// Variation orders (VOs) — additions/omissions to the contract that adjust the
// revised sum once approved and become claimable alongside the BOQ.
export default function VariationsPanel({ projectId, me }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);
  const [editId, setEditId] = useState(null);
  const canEdit = EDIT_ROLES.includes(me.role);

  function load() {
    setError(null);
    api(`/projects/${projectId}/variations`).then(setData)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function status(id, s) {
    setError(null);
    try { setData(await api(`/variations/${id}/status`,
      { method: "POST", body: { status: s } })); }
    catch (e) { setError(e.message); }
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
            <Fig label="Pending VOs"
                 v={`${ccy} ${signed(c.pending_net)}`} />
            <Fig label="Forecast" v={`${ccy} ${fmt(c.forecast)}`} />
          </>
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
                    <td style={td}>{v.title || "—"}</td>
                    <td style={td}>{v.kind === "OMISSION" ? "Omission"
                      : "Addition"}</td>
                    <td style={td}>
                      <Chip tone={STATUS_TONE[v.status] || "info"}>
                        {v.status}</Chip></td>
                    <td style={{ ...td, textAlign: "right", fontWeight: 600,
                      color: Number(v.signed_total) < 0 ? "#b0402f"
                        : "inherit" }}>
                      {signed(v.signed_total)}</td>
                    <td style={{ ...td, textAlign: "right",
                                 whiteSpace: "nowrap" }}>
                      {canEdit && v.status === "DRAFT" && (<>
                        <A onClick={() => setEditId(
                          editId === v.id ? null : v.id)}>edit</A>
                        <A onClick={() => status(v.id, "SUBMITTED")}>
                          submit</A>
                        <A danger onClick={() => del(v.id)}>delete</A>
                      </>)}
                      {canEdit && v.status === "SUBMITTED" && (<>
                        <A onClick={() => status(v.id, "APPROVED")}>
                          approve</A>
                        <A danger onClick={() => status(v.id, "REJECTED")}>
                          reject</A>
                      </>)}
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
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
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
