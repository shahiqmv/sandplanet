import { useEffect, useMemo, useRef, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, buttonStyle, card, ghostButton, inputStyle, SectionTitle,
         StatusChip, td, th } from "./ui.jsx";

// International Purchase Requisition (IPR) — the overseas order (Phase 1B).
// HO raises it from sized-and-released PMRs; the Director awards it; a
// signatory authorises it on a Payment Voucher (where the commitment posts).

const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; };
const money = (v) => num(v).toLocaleString(undefined, { maximumFractionDigits: 2 });

// IPR workflow buttons (server is the authority)
const ACTIONS = [
  ["submit", "Submit", ["DRAFT"], ["HO_PURCHASING", "ADMIN"]],
  ["approve", "Award (Director/QS)", ["SUBMITTED"], ["DIRECTOR", "QS",
                                                     "ADMIN"]],
  ["authorise", "Authorise order (Signatory)", ["APPROVED"],
   ["SIGNATORY", "ADMIN"]],
  ["return", "Return with comment", ["SUBMITTED", "APPROVED"],
   ["DIRECTOR", "QS", "HO_PURCHASING", "ADMIN"], "comment"],
  ["cancel", "Cancel", ["DRAFT", "SUBMITTED"], ["HO_PURCHASING", "ADMIN"],
   "comment"],
];

export default function ImportOrders({ me, onOpenIpr }) {
  const [rows, setRows] = useState(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);

  const load = () => api("/ipr").then(setRows).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const canCreate = ["HO_PURCHASING", "ADMIN"].includes(me.role);

  if (adding) {
    return <IprForm me={me} onCancel={() => setAdding(false)}
                    onSaved={(ref) => { setAdding(false); onOpenIpr(ref); }} />;
  }

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          🌍 International Orders (IPR)</h2>
        {canCreate && (
          <Btn onClick={() => setAdding(true)}>+ New order</Btn>
        )}
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12,
                      fontSize: 13 }}>
        <thead><tr>
          <th style={th}>Ref</th><th style={th}>Supplier</th>
          <th style={th}>Date</th>
          <th style={{ ...th, textAlign: "right" }}>Order value</th>
          <th style={{ ...th, textAlign: "right" }}>MVR</th>
          <th style={th}>Status</th>
        </tr></thead>
        <tbody>
          {(rows || []).map((r) => (
            <tr key={r.ref}>
              <td style={td}>
                <a href="#" onClick={(e) => { e.preventDefault();
                                              onOpenIpr(r.ref); }}
                   style={{ color: "var(--sp-navy)", fontWeight: 600 }}>
                  {r.ref}</a>
              </td>
              <td style={td}>{r.supplier}</td>
              <td style={td}>{r.doc_date}</td>
              <td style={{ ...td, textAlign: "right" }}>
                {r.currency} {money(r.order_total)}</td>
              <td style={{ ...td, textAlign: "right" }}>{money(r.mvr_total)}</td>
              <td style={td}><StatusChip status={r.status} /></td>
            </tr>
          ))}
          {rows && rows.length === 0 && (
            <tr><td colSpan={6} style={{ ...td, textAlign: "center",
                                         color: "var(--muted)" }}>
              No orders yet. Raise one from a sized-and-released PMR.</td></tr>
          )}
        </tbody>
      </table>
    </section>
  );
}

function newLine() {
  return { free_text_desc: "", item_id: null, unit: "", spec: "",
           order_qty: "", unit_price: "", cost_head_id: "", remarks: "",
           allocations: [{ project_id: "", qty: "" }] };
}

export function IprForm({ me, existing, onSaved, onCancel }) {
  const o = existing?.order;
  const [ctx, setCtx] = useState(null);
  const [hdr, setHdr] = useState(o ? {
    supplier_id: String(o.supplier || ""), order_currency: o.order_currency,
    exchange_rate: String(o.exchange_rate ?? ""), incoterm: o.incoterm || "",
    loading_port: o.loading_port || "", discharge_port: o.discharge_port || "",
    pi_ref: o.pi_ref || "", notes: o.notes || "",
    discount: o.discount ?? "", freight_handling: o.freight_handling ?? "",
  } : { supplier_id: "", order_currency: "USD",
    exchange_rate: "", incoterm: "", loading_port: "", discharge_port: "",
    pi_ref: "", notes: "", discount: "", freight_handling: "" });
  const [pmrRefs, setPmrRefs] = useState(existing?.pmr_refs || []);
  const [lines, setLines] = useState(o ? o.lines.map((l) => ({
    ...newLine(), item_id: l.item || null,
    free_text_desc: l.item ? "" : l.description, unit: l.unit || "",
    spec: l.spec || "", order_qty: String(l.order_qty ?? ""),
    unit_price: String(l.unit_price ?? ""),
    cost_head_id: String(l.cost_head || ""), remarks: l.remarks || "",
    allocations: l.allocations?.length
      ? l.allocations.map((a) => ({ project_id: String(a.project || ""),
                                    qty: String(a.qty ?? "") }))
      : [{ project_id: "", qty: "" }],
  })) : [newLine()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/ipr/context").then(setCtx).catch((e) => setError(e.message));
  }, []);

  const items = ctx?.items || [];
  const itemLabel = (it) => it ? `${it.code} — ${it.description}` : "";
  const setH = (k, v) => setHdr((s) => ({ ...s, [k]: v }));
  const setLine = (i, patch) =>
    setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const setAlloc = (li, ai, patch) => setLines(lines.map((l, j) =>
    j === li ? { ...l, allocations: l.allocations.map((a, k) =>
      k === ai ? { ...a, ...patch } : a) } : l));

  function pickSupplier(id) {
    const s = (ctx?.suppliers || []).find((x) => String(x.id) === String(id));
    setHdr((h) => ({ ...h, supplier_id: id,
      order_currency: s?.default_currency || h.order_currency || "USD",
      incoterm: s?.default_incoterm || h.incoterm }));
  }

  function togglePmr(ref) {
    setPmrRefs((cur) => cur.includes(ref)
      ? cur.filter((r) => r !== ref) : [...cur, ref]);
  }

  // Build order lines from the selected PMRs' demand — each line pre-allocated
  // to the requesting project (the Director can then resize for MOQ).
  function buildFromPmrs() {
    const chosen = (ctx?.pmrs || []).filter((p) => pmrRefs.includes(p.ref));
    const rows = [];
    for (const p of chosen) {
      for (const ln of p.lines) {
        rows.push({ ...newLine(), free_text_desc: ln.item_id ? "" : ln.description,
          item_id: ln.item_id || null, unit: ln.unit || "", spec: ln.spec || "",
          order_qty: ln.qty || "",
          allocations: [{ project_id: String(p.project_id || ""),
                          qty: ln.qty || "" }] });
      }
    }
    if (rows.length) setLines(rows);
  }

  const lineSubtotal = useMemo(() =>
    lines.reduce((a, l) => a + num(l.order_qty) * num(l.unit_price), 0), [lines]);
  const orderTotal = lineSubtotal - num(hdr.discount)
    + num(hdr.freight_handling);
  const mvrTotal = orderTotal * num(hdr.exchange_rate);

  // Promote a free-text "new item" line to a real catalog item, so it becomes
  // a proper inventory item and can be amended in the Item Master (owner req).
  async function addToCatalog(i) {
    const l = lines[i];
    const desc = (l._itemText ?? l.free_text_desc ?? "").trim();
    if (!desc) return setError("Type the item description first.");
    if (!l.unit) return setError("Enter the unit before adding to the catalog.");
    setError(null);
    try {
      const item = await api("/items", { method: "POST",
        body: { description: desc, unit: l.unit } });
      setCtx((c) => ({ ...c, items: [...(c?.items || []), item] }));
      setLine(i, { item_id: item.id, free_text_desc: "", unit: item.unit,
        _itemText: `${item.code} — ${item.description}` });
    } catch (e) { setError(e.message); }
  }

  async function save() {
    setBusy(true); setError(null);
    try {
      const body = { ...hdr, pmr_refs: pmrRefs,
        lines: lines.map((l) => ({
          item_id: l.item_id || null, free_text_desc: l.free_text_desc,
          unit: l.unit, spec: l.spec, order_qty: l.order_qty,
          unit_price: l.unit_price, cost_head_id: l.cost_head_id,
          remarks: l.remarks,
          allocations: l.allocations.map((a) => ({
            project_id: a.project_id || null, qty: a.qty })),
        })) };
      const doc = existing
        ? await api(`/ipr/${existing.ref}`, { method: "PATCH", body })
        : await api("/ipr", { method: "POST", body });
      onSaved(doc.ref);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  if (!ctx) return <section style={card}>Loading…</section>;
  const projById = Object.fromEntries((ctx.projects || [])
    .map((p) => [String(p.id), p]));

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
          {existing ? `Edit order ${existing.ref}` : "New International Order"}</h2>
        <button onClick={onCancel} style={ghostButton}>Close</button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
                    gap: 12, marginTop: 16 }}>
        <label style={{ fontSize: 13 }}>Overseas supplier
          <select value={hdr.supplier_id} style={inputStyle}
                  onChange={(e) => pickSupplier(e.target.value)}>
            <option value="">Select supplier…</option>
            {ctx.suppliers.map((s) => (
              <option key={s.id} value={s.id}>{s.name}
                {s.country ? ` · ${s.country}` : ""}</option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Order currency
          <input value={hdr.order_currency} style={inputStyle}
                 onChange={(e) => setH("order_currency", e.target.value.toUpperCase())} />
        </label>
        <label style={{ fontSize: 13 }}>Exchange rate (→ MVR)
          <input type="number" value={hdr.exchange_rate} style={inputStyle}
                 placeholder="e.g. 15.42"
                 onChange={(e) => setH("exchange_rate", e.target.value)} />
        </label>
        <label style={{ fontSize: 13 }}>Incoterm
          <input value={hdr.incoterm} style={inputStyle}
                 onChange={(e) => setH("incoterm", e.target.value)} />
        </label>
        <label style={{ fontSize: 13 }}>Loading port
          <input value={hdr.loading_port} style={inputStyle}
                 onChange={(e) => setH("loading_port", e.target.value)} />
        </label>
        <label style={{ fontSize: 13 }}>Discharge port
          <input value={hdr.discharge_port} style={inputStyle}
                 onChange={(e) => setH("discharge_port", e.target.value)} />
        </label>
        <label style={{ fontSize: 13 }}>Proforma invoice ref
          <input value={hdr.pi_ref} style={inputStyle}
                 onChange={(e) => setH("pi_ref", e.target.value)} />
        </label>
      </div>

      {!existing && <SectionTitle>Demand — PMRs this order fulfils</SectionTitle>}
      {existing ? null : ctx.pmrs.length === 0 ? (
        <p style={{ fontSize: 13, color: "var(--muted)" }}>
          No sized-and-released import requests waiting to be ordered.</p>
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8,
                      alignItems: "center" }}>
          {ctx.pmrs.map((p) => (
            <label key={p.ref} style={{ fontSize: 12.5, border:
              "1px solid var(--sp-border)", borderRadius: 8, padding: "4px 8px" }}>
              <input type="checkbox" checked={pmrRefs.includes(p.ref)}
                     onChange={() => togglePmr(p.ref)} />{" "}
              {p.ref} · {p.project || p.site_code}
            </label>
          ))}
          <button onClick={buildFromPmrs} disabled={!pmrRefs.length}
                  style={{ ...ghostButton, padding: "4px 10px", fontSize: 12 }}>
            Build lines from selected</button>
        </div>
      )}

      <SectionTitle>Order lines</SectionTitle>
      <datalist id="ipr-items">
        {items.map((it) => <option key={it.id} value={itemLabel(it)} />)}
      </datalist>
      {lines.map((l, i) => {
        const lineVal = num(l.order_qty) * num(l.unit_price);
        const allocSum = l.allocations.reduce((a, x) => a + num(x.qty), 0);
        const balanced = allocSum === num(l.order_qty);
        return (
          <div key={i} style={{ border: "1px solid var(--sp-border)",
            borderRadius: 8, padding: 10, marginBottom: 10 }}>
            <div style={{ display: "grid",
              gridTemplateColumns: "2fr 0.7fr 1fr 1fr 1.4fr 30px", gap: 6,
              alignItems: "center" }}>
              <input list="ipr-items" placeholder="Search catalog / describe"
                     value={l._itemText ?? (l.item_id
                       ? itemLabel(items.find((it) => it.id === l.item_id))
                       : l.free_text_desc)}
                     onChange={(e) => {
                       const v = e.target.value;
                       const m = items.find((it) => itemLabel(it) === v);
                       if (m) setLine(i, { item_id: m.id, _itemText: v,
                         unit: m.unit, free_text_desc: "" });
                       else setLine(i, { item_id: null, _itemText: v,
                         free_text_desc: v });
                     }}
                     style={inputStyle} />
              <input placeholder="Unit" value={l.unit}
                     disabled={!!l.item_id}
                     onChange={(e) => setLine(i, { unit: e.target.value })}
                     style={inputStyle} />
              <input type="number" placeholder="Order qty" value={l.order_qty}
                     onChange={(e) => setLine(i, { order_qty: e.target.value })}
                     style={inputStyle} />
              <input type="number" placeholder="Unit price" value={l.unit_price}
                     onChange={(e) => setLine(i, { unit_price: e.target.value })}
                     style={inputStyle} />
              <select value={l.cost_head_id} style={inputStyle}
                      onChange={(e) => setLine(i, { cost_head_id: e.target.value })}>
                <option value="">Cost head…</option>
                {ctx.cost_heads.map((h) => (
                  <option key={h.id} value={h.id}>{h.name}</option>
                ))}
              </select>
              <button onClick={() => setLines(lines.filter((_, j) => j !== i))}
                      style={{ ...ghostButton, color: "#c0392b",
                               padding: "2px 8px" }}>×</button>
            </div>
            <div style={{ marginTop: 6, paddingLeft: 8 }}>
              {!l.item_id && (
                <div style={{ marginBottom: 6 }}>
                  <button onClick={() => addToCatalog(i)}
                          title="Create a catalogue item from this description so
                                 it becomes a proper inventory item"
                          style={{ ...ghostButton, padding: "2px 10px",
                                   fontSize: 12, color: "#b35900" }}>
                    ＋ Add “{(l._itemText ?? l.free_text_desc ?? "").slice(0, 28)
                      || "new item"}” to catalog</button>
                  <span style={{ fontSize: 11, color: "#8a97a1",
                                 marginLeft: 8 }}>
                    new item — not yet in the catalogue</span>
                </div>
              )}
              <div style={{ fontSize: 11.5, color: "#5a6b78", marginBottom: 4 }}>
                Allocate {money(l.order_qty)} {l.unit} · line value{" "}
                {money(lineVal)} {hdr.order_currency}
                {!balanced && (
                  <span style={{ color: "#c0392b" }}> · allocated {money(allocSum)}
                    {" "}(must equal order qty)</span>
                )}
              </div>
              {l.allocations.map((a, ai) => (
                <div key={ai} style={{ display: "flex", gap: 6, marginBottom: 4 }}>
                  <select value={a.project_id} style={{ ...inputStyle, width: 260 }}
                          onChange={(e) => setAlloc(i, ai, { project_id: e.target.value })}>
                    <option value="">General company stock</option>
                    {ctx.projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.code} · {p.site_code}</option>
                    ))}
                  </select>
                  <input type="number" placeholder="Qty" value={a.qty}
                         onChange={(e) => setAlloc(i, ai, { qty: e.target.value })}
                         style={{ ...inputStyle, width: 90 }} />
                  {l.allocations.length > 1 && (
                    <button onClick={() => setLine(i, { allocations:
                      l.allocations.filter((_, k) => k !== ai) })}
                            style={{ ...ghostButton, color: "#c0392b",
                                     padding: "2px 8px" }}>×</button>
                  )}
                </div>
              ))}
              <button onClick={() => setLine(i, { allocations:
                [...l.allocations, { project_id: "", qty: "" }] })}
                      style={{ ...ghostButton, padding: "2px 10px", fontSize: 12 }}>
                + allocation</button>
            </div>
          </div>
        );
      })}
      <button onClick={() => setLines([...lines, newLine()])}
              style={{ ...ghostButton, padding: "4px 12px" }}>+ Add line</button>

      <div style={{ marginTop: 14, display: "grid", gap: 8, maxWidth: 420,
                    gridTemplateColumns: "1fr auto" }}>
        <span style={{ fontSize: 13, color: "#5a6b78" }}>Line subtotal</span>
        <span style={{ fontSize: 13, textAlign: "right",
                       fontFamily: "var(--font-mono)" }}>
          {hdr.order_currency} {money(lineSubtotal)}</span>
        <label style={{ fontSize: 13, alignSelf: "center" }}>
          Discount ({hdr.order_currency})</label>
        <input type="number" value={hdr.discount} placeholder="0"
               onChange={(e) => setH("discount", e.target.value)}
               style={{ ...inputStyle, width: 130, textAlign: "right" }} />
        <label style={{ fontSize: 13, alignSelf: "center" }}>
          Freight / handling ({hdr.order_currency})</label>
        <input type="number" value={hdr.freight_handling} placeholder="0"
               onChange={(e) => setH("freight_handling", e.target.value)}
               style={{ ...inputStyle, width: 130, textAlign: "right" }} />
      </div>
      <p style={{ marginTop: 12, fontSize: 14, fontWeight: 600,
                  color: "var(--sp-navy)" }}>
        Order total: {hdr.order_currency} {money(orderTotal)}
        {num(hdr.exchange_rate) > 0 &&
          ` · ≈ MVR ${money(mvrTotal)} at ${hdr.exchange_rate}`}
      </p>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      <button onClick={save} disabled={busy} style={{ ...buttonStyle, marginTop: 8 }}>
        {busy ? "Saving…" : existing ? "Save changes" : "Save draft order"}</button>
      {/* projById kept for future per-allocation labels */}
      <span style={{ display: "none" }}>{Object.keys(projById).length}</span>
    </section>
  );
}

export function IprView({ me, refIpr, onClose, onOpenIrn, onEdit }) {
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState(null);

  const load = () => api(`/ipr/${refIpr}`).then(setDoc)
    .catch((e) => setError(e.message));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [refIpr]);

  async function act(action, body) {
    setError(null);
    try {
      await api(`/documents/${refIpr}/actions/${action}`,
                { method: "POST", body });
      load();
    } catch (e) { setError(e.message); }
  }
  async function uploadPi(file) {
    if (!file) return;
    setError(null);
    const fd = new FormData();
    fd.append("file", file);
    try { await apiUpload(`/ipr/${refIpr}/proforma`, fd); load(); }
    catch (e) { setError(e.message); }
  }

  if (!doc) return <section style={card}>{error || "Loading…"}</section>;
  const o = doc.order;
  const actions = ACTIONS.filter(([, , st, roles]) =>
    st.includes(doc.status) && roles.includes(me.role));

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
          {doc.ref} <StatusChip status={doc.status} /></h2>
        <div style={{ display: "flex", gap: 8 }}>
          {doc.status === "DRAFT" && doc.can_manage && onEdit && (
            <button onClick={() => onEdit(doc)} style={buttonStyle}>
              ✏️ Edit order</button>
          )}
          <button onClick={onClose} style={ghostButton}>Close</button>
        </div>
      </div>
      <p style={{ color: "#5a6b78", fontSize: 13, margin: "6px 0 0" }}>
        {o.supplier_name}{o.supplier_country ? ` · ${o.supplier_country}` : ""}
        {" · "}{o.order_currency} @ {o.exchange_rate} → MVR
        {o.incoterm ? ` · ${o.incoterm}` : ""}
        {o.pi_ref ? ` · PI ${o.pi_ref}` : ""}
      </p>
      {doc.pmr_refs?.length > 0 && (
        <p style={{ fontSize: 12, color: "#5a6b78", margin: "4px 0 0" }}>
          Fulfils: {doc.pmr_refs.join(" · ")}</p>
      )}

      {/* Supplier proforma invoice — HO uploads; approvers view it */}
      <div style={{ marginTop: 8, display: "flex", alignItems: "center",
                    gap: 10, flexWrap: "wrap", fontSize: 13 }}>
        <strong style={{ color: "var(--sp-navy)" }}>Proforma invoice:</strong>
        {o.proforma_invoice_url ? (
          <a href={o.proforma_invoice_url} target="_blank" rel="noreferrer">
            📎 View{o.pi_ref ? ` (${o.pi_ref})` : ""}</a>
        ) : (
          <span style={{ color: "#8a97a1" }}>not uploaded yet</span>
        )}
        {doc.can_manage && (
          <label style={{ color: "var(--sp-navy)", cursor: "pointer",
                          fontSize: 12.5 }}>
            {o.proforma_invoice_url ? "Replace" : "Upload PI"}
            <input type="file" style={{ display: "none" }}
                   onChange={(e) => uploadPi(e.target.files[0])} />
          </label>
        )}
      </div>

      <div style={{ display: "flex", gap: 10, margin: "14px 0",
                    flexWrap: "wrap" }}>
        {actions.map(([action, label, , , prompt]) => (
          <button key={action} style={buttonStyle}
            onClick={() => {
              if (prompt === "comment") {
                const c = window.prompt("Comment (required):");
                if (c) act(action, { comment: c });
              } else act(action);
            }}>{label}</button>
        ))}
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      {doc.status === "APPROVED" && (
        <p style={{ fontSize: 12.5, color: "#1a7f37" }}>
          Awarded — awaiting a signatory to authorise the order. The MVR
          commitment posts on authorisation; each overseas TT is vouchered
          later when it is paid.</p>
      )}

      <SectionTitle>Order lines</SectionTitle>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead><tr>
            <th style={th}>Description</th><th style={th}>Unit</th>
            <th style={{ ...th, textAlign: "right" }}>Qty</th>
            <th style={{ ...th, textAlign: "right" }}>Unit price</th>
            <th style={{ ...th, textAlign: "right" }}>Value</th>
            <th style={th}>Cost head</th><th style={th}>Allocation</th>
          </tr></thead>
          <tbody>
            {o.lines.map((l) => (
              <tr key={l.id}>
                <td style={td}>{l.description}
                  {l.spec && <div style={{ fontSize: 11, color: "#5a6b78" }}>
                    {l.spec}</div>}</td>
                <td style={td}>{l.unit}</td>
                <td style={{ ...td, textAlign: "right" }}>{money(l.order_qty)}</td>
                <td style={{ ...td, textAlign: "right" }}>{money(l.unit_price)}</td>
                <td style={{ ...td, textAlign: "right" }}>{money(l.line_value)}</td>
                <td style={td}>{l.cost_head_name}</td>
                <td style={td}>
                  {l.allocations.map((a) => (
                    <div key={a.id} style={{ fontSize: 12 }}>
                      {a.is_general_stock
                        ? <span style={{ color: "#8a6d00" }}>General stock</span>
                        : `${a.project_code}`} — {money(a.qty)}
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            {(Number(o.discount) > 0 || Number(o.freight_handling) > 0) && (
              <>
                <tr>
                  <td colSpan={4} style={{ ...td, textAlign: "right",
                                           color: "#5a6b78" }}>Line subtotal</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {o.order_currency} {money(doc.line_subtotal)}</td>
                  <td colSpan={2} style={td}></td>
                </tr>
                {Number(o.discount) > 0 && (
                  <tr>
                    <td colSpan={4} style={{ ...td, textAlign: "right",
                                             color: "#5a6b78" }}>Discount</td>
                    <td style={{ ...td, textAlign: "right", color: "#c0392b" }}>
                      − {o.order_currency} {money(o.discount)}</td>
                    <td colSpan={2} style={td}></td>
                  </tr>
                )}
                {Number(o.freight_handling) > 0 && (
                  <tr>
                    <td colSpan={4} style={{ ...td, textAlign: "right",
                                             color: "#5a6b78" }}>
                      Freight / handling</td>
                    <td style={{ ...td, textAlign: "right" }}>
                      + {o.order_currency} {money(o.freight_handling)}</td>
                    <td colSpan={2} style={td}></td>
                  </tr>
                )}
              </>
            )}
            <tr>
              <td colSpan={4} style={{ ...td, textAlign: "right",
                                       fontWeight: 600 }}>Order total</td>
              <td style={{ ...td, textAlign: "right", fontWeight: 700 }}>
                {o.order_currency} {money(doc.order_total)}</td>
              <td colSpan={2} style={{ ...td, color: "var(--sp-navy)",
                                       fontWeight: 600 }}>
                ≈ MVR {money(doc.mvr_total)}</td>
            </tr>
          </tfoot>
        </table>
      </div>

      {doc.landed && num(doc.landed.total_charges) > 0 && (
        <p style={{ marginTop: 8, fontSize: 13 }}>
          <strong style={{ color: "var(--sp-navy)" }}>Landed cost:</strong>{" "}
          goods MVR {money(doc.landed.total_goods)} + charges{" "}
          {money(doc.landed.total_charges)} ={" "}
          <strong>MVR {money(doc.landed.total_landed)}</strong>
          <span style={{ color: "#8a6d00" }}>
            {" "}· {money(doc.landed.uplift_pct)}% uplift</span>
        </p>
      )}

      <MilestonePanel doc={doc} me={me} refIpr={refIpr} onChanged={load}
                      onError={setError} />
      <ShipmentsPanel doc={doc} refIpr={refIpr} onChanged={load}
                      onError={setError} onOpenIrn={onOpenIrn}
                      isAdmin={me.role === "ADMIN"} />
    </section>
  );
}

const DOC_TYPES = [["BL_AWB", "Bill of Lading / AWB"],
  ["PACKING_LIST", "Packing list"], ["COMMERCIAL_INVOICE", "Commercial invoice"],
  ["COO", "Certificate of origin"], ["INSURANCE", "Insurance"],
  ["TEST_CERT", "Test certificate"], ["PI", "Proforma invoice"],
  ["OTHER", "Other"]];
const SHIP_STEPS = ["BOOKED", "SHIPPED", "IN_TRANSIT", "ARRIVED",
  "UNDER_CLEARING", "CLEARED"];
const CHARGE_LABELS = [["freight", "Freight"], ["insurance", "Insurance"],
  ["customs_duty", "Customs duty"], ["import_gst", "Import GST"],
  ["port_handling", "Port & handling"], ["agent_charges", "Agent charges"],
  ["local_transport", "Local transport"]];

// Searchable carrier picker over the full synced list (~130+). The stored
// value is the SCAC; the input shows the name. An unknown / "Other" entry maps
// to an empty SCAC → ShipsGo v2 auto-detects the line from the container/booking.
function CarrierPicker({ scac, onPick, carriers, id }) {
  const nameFor = (code) =>
    (carriers.find((x) => x.scac === code) || {}).name || "";
  const [text, setText] = useState(nameFor(scac));
  useEffect(() => { setText(nameFor(scac)); },
    [scac, carriers.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const dlId = `carriers-${id}`;
  function commit(v) {
    setText(v);
    const t = v.trim().toUpperCase();
    if (!t || t === "OTHER / AUTO-DETECT") { onPick(""); return; }
    const c = carriers.find((x) => (x.name || "").toUpperCase() === t);
    onPick(c ? c.scac : "");        // unknown line → auto-detect
  }
  return (
    <>
      <input list={dlId} value={text} style={inputStyle}
        placeholder="Carrier (line) — type to search"
        title="Shipping line — needed for live tracking"
        onChange={(e) => commit(e.target.value)} />
      <datalist id={dlId}>
        <option value="Other / auto-detect" />
        {carriers.map((c) => <option key={c.scac} value={c.name} />)}
      </datalist>
    </>
  );
}

function CarrierWarning({ meta }) {
  if (!meta) return null;
  const problem = meta.never_synced || !meta.sync_ok || meta.count === 0;
  if (!problem) return null;
  const what = meta.never_synced ? "hasn't synced yet"
    : !meta.sync_ok ? "failed to sync" : "is empty";
  return (
    <div style={{ fontSize: 11.5, color: "#b0402f", background: "#fbeae8",
      border: "1px solid #e3b7b0", borderRadius: 6, padding: "5px 8px",
      marginTop: 6 }}>
      ⚠ Carrier list {what}
      {meta.synced_at ? ` (last ok ${meta.synced_at.slice(0, 10)})` : ""} —
      showing {meta.count || 0} carrier{meta.count === 1 ? "" : "s"}. An admin
      can refresh it from the Import tracker.
    </div>
  );
}

const TRACK_STATE_STYLE = {
  ACTIVE: { bg: "#e7f4ea", fg: "#1f7a3d", label: "Tracking active" },
  ARRIVED: { bg: "#e7f0fb", fg: "#1f5fae", label: "Arrived Malé" },
  PENDING_REGISTRATION: { bg: "#fdf3e7", fg: "#8a5a00", label: "Registering…" },
  FAILED: { bg: "#fbeae8", fg: "#b0402f", label: "Tracking failed" },
  MANUAL: { bg: "#eef0f2", fg: "#41505c", label: "Manual updates" },
};
const MILE_LABEL = { DEPARTED: "Departed origin",
  TRANSSHIPMENT: "Transshipment", ARRIVED: "Arrived Malé",
  ETA_UPDATED: "ETA updated", OTHER: "Update" };

function TrackingBlock({ s, canManage, onChanged, onError }) {
  const t = s.tracking;
  const [logging, setLogging] = useState(false);
  const [ev, setEv] = useState({ code: "DEPARTED", description: "",
    location: "" });
  if (!t) return null;
  const st = TRACK_STATE_STYLE[t.state] || TRACK_STATE_STYLE.MANUAL;

  async function post(action, body) {
    onError(null);
    try { await api(`/tracking/shipments/${s.id}/${action}`,
      { method: "POST", body }); onChanged(); }
    catch (e) { onError(e.message); }
  }

  return (
    <div style={{ marginTop: 8, borderTop: "1px dashed var(--sp-border)",
                  paddingTop: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                    flexWrap: "wrap" }}>
        <span style={{ fontSize: 11.5, fontWeight: 600, padding: "2px 8px",
          borderRadius: 10, background: st.bg, color: st.fg }}>
          🚢 {st.label}</span>
        {t.current_eta && (<span style={{ fontSize: 12, color: "#5a6b78" }}>
          Live ETA {t.current_eta.slice(0, 10)}</span>)}
        {t.map_url && (<a href={t.map_url} target="_blank" rel="noreferrer"
          style={{ fontSize: 12, color: "var(--sp-navy)" }}>Live map ↗</a>)}
        {canManage && (t.state === "FAILED"
          || t.state === "PENDING_REGISTRATION") && (
          <button style={{ ...ghostButton, padding: "2px 10px" }}
            onClick={() => post("retry", {})}>Retry</button>)}
        {canManage && t.state !== "MANUAL" && t.state !== "ARRIVED" && (
          <button style={{ ...ghostButton, padding: "2px 10px" }}
            onClick={() => post("manual", { action: "switch" })}>
            Switch to manual</button>)}
      </div>
      {t.last_error && t.state === "FAILED" && (
        <div style={{ fontSize: 11.5, color: "#b0402f", marginTop: 4 }}>
          {t.last_error}</div>)}
      {t.events && t.events.length > 0 && (
        <div style={{ marginTop: 6 }}>
          {t.events.map((e, i) => (
            <div key={i} style={{ fontSize: 12, color: "#41505c",
              display: "flex", gap: 8 }}>
              <span style={{ color: e.is_actual ? "#1f7a3d" : "#8a97a1" }}>
                ●</span>
              <span style={{ fontWeight: 500 }}>
                {MILE_LABEL[e.code] || e.code}</span>
              <span style={{ color: "#5a6b78" }}>
                {[e.location, e.vessel_flight,
                  e.event_time && e.event_time.slice(0, 10),
                  e.is_actual ? "" : "(est.)"].filter(Boolean).join(" · ")}
              </span>
            </div>
          ))}
        </div>
      )}
      {canManage && (logging ? (
        <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap",
                      alignItems: "center" }}>
          <select value={ev.code} style={{ ...inputStyle, width: 150 }}
            onChange={(e) => setEv({ ...ev, code: e.target.value })}>
            {Object.entries(MILE_LABEL).filter(([k]) => k !== "OTHER")
              .map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <input placeholder="Location" value={ev.location}
            style={{ ...inputStyle, width: 120 }}
            onChange={(e) => setEv({ ...ev, location: e.target.value })} />
          <input placeholder="Note" value={ev.description}
            style={{ ...inputStyle, width: 140 }}
            onChange={(e) => setEv({ ...ev, description: e.target.value })} />
          <button style={{ ...buttonStyle, padding: "3px 10px" }}
            onClick={async () => { await post("manual",
              { action: "event", ...ev }); setLogging(false);
              setEv({ code: "DEPARTED", description: "", location: "" }); }}>
            Log</button>
          <button style={ghostButton}
            onClick={() => setLogging(false)}>Cancel</button>
        </div>
      ) : (t.state === "MANUAL" && (
        <button style={{ ...ghostButton, padding: "2px 10px", marginTop: 6 }}
          onClick={() => setLogging(true)}>+ Log milestone</button>
      )))}
    </div>
  );
}

function ShipmentsPanel({ doc, refIpr, onChanged, onError, onOpenIrn,
                          isAdmin }) {
  const ships = doc.shipments || [];
  const canManage = doc.can_manage;
  const [adding, setAdding] = useState(false);
  const blankF = { mode: "SEA", forwarder_name: "", vessel_flight: "",
    carrier_scac: "", bl_no: "", container_awb: "", etd: "", eta: "",
    tracking_ref: "" };
  const [f, setF] = useState(blankF);
  const [split, setSplit] = useState(false);
  const [alloc, setAlloc] = useState([]);
  const [carriers, setCarriers] = useState([]);
  const [carrierMeta, setCarrierMeta] = useState(null);

  useEffect(() => {
    if (!adding || f.mode !== "SEA" || carriers.length) return;
    api("/tracking/carriers").then((d) => {
      setCarriers(d.carriers || []); setCarrierMeta(d);
    }).catch(() => {});
  }, [adding, f.mode]); // eslint-disable-line react-hooks/exhaustive-deps

  const orderLines = (doc.order && doc.order.lines) || [];
  const shippable = orderLines.filter((l) => num(l.remaining_qty) > 0);
  const fullyShipped = orderLines.length > 0 && shippable.length === 0;

  function startAdd() {
    setAlloc(shippable.map((l) => ({ ipr_line_id: l.id,
      qty: String(num(l.remaining_qty)), desc: l.description,
      unit: l.unit, max: num(l.remaining_qty) })));
    setSplit(false);
    setF(blankF);
    setAdding(true);
  }

  async function call(path, body) {
    onError(null);
    try { await api(`/ipr/${refIpr}${path}`, { method: "POST", body });
      onChanged(); } catch (e) { onError(e.message); }
  }
  async function create() {
    onError(null);
    const body = { ...f };
    if (split) {
      body.lines = alloc.filter((a) => num(a.qty) > 0)
        .map((a) => ({ ipr_line_id: a.ipr_line_id, qty: a.qty }));
      if (body.lines.length === 0) {
        onError("Add at least one item quantity to this shipment."); return;
      }
    }
    try { await api(`/ipr/${refIpr}/shipments`, { method: "POST", body });
      setAdding(false); setSplit(false); setF(blankF);
      onChanged(); } catch (e) { onError(e.message); }
  }

  return (
    <>
      <SectionTitle>Shipments &amp; clearing</SectionTitle>
      {ships.length === 0 && !adding && (
        <p style={{ fontSize: 12.5, color: "var(--muted)" }}>
          No shipments booked yet.</p>
      )}
      {ships.map((s) => (
        <Shipment key={s.id} s={s} refIpr={refIpr} canManage={canManage}
                  call={call} onChanged={onChanged} onError={onError}
                  onOpenIrn={onOpenIrn} isAdmin={isAdmin} />
      ))}

      {canManage && (adding ? (
        <div style={{ border: "1px solid var(--sp-border)", borderRadius: 8,
                      padding: 10, marginTop: 8 }}>
          <div style={{ display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
            <select value={f.mode} style={inputStyle}
                    onChange={(e) => setF({ ...f, mode: e.target.value })}>
              <option value="SEA">Sea</option><option value="AIR">Air</option>
            </select>
            <input placeholder="Forwarder" value={f.forwarder_name}
              style={inputStyle}
              onChange={(e) => setF({ ...f, forwarder_name: e.target.value })} />
            <input placeholder="Vessel / flight" value={f.vessel_flight}
              style={inputStyle}
              onChange={(e) => setF({ ...f, vessel_flight: e.target.value })} />
            {f.mode === "SEA" ? (
              <CarrierPicker scac={f.carrier_scac} carriers={carriers} id="book"
                onPick={(v) => setF({ ...f, carrier_scac: v })} />
            ) : (
              <span />
            )}
            {f.mode === "SEA" && (
              <input placeholder="Booking / B/L no." value={f.bl_no}
                style={inputStyle}
                onChange={(e) => setF({ ...f, bl_no: e.target.value })} />
            )}
            <input placeholder={f.mode === "AIR" ? "AWB (11 digits)"
              : "Container no."} value={f.container_awb}
              style={inputStyle}
              onChange={(e) => setF({ ...f, container_awb: e.target.value })} />
            <label style={{ fontSize: 11, color: "#5a6b78" }}>ETD
              <input type="date" value={f.etd} style={inputStyle}
                onChange={(e) => setF({ ...f, etd: e.target.value })} /></label>
            <label style={{ fontSize: 11, color: "#5a6b78" }}>ETA
              <input type="date" value={f.eta} style={inputStyle}
                onChange={(e) => setF({ ...f, eta: e.target.value })} /></label>
          </div>
          {f.mode === "SEA" && <CarrierWarning meta={carrierMeta} />}
          {shippable.length > 0 && (
            <div style={{ marginTop: 8, borderTop: "1px solid var(--sp-border)",
                          paddingTop: 8 }}>
              <label style={{ fontSize: 12, display: "flex", gap: 6,
                              alignItems: "center", cursor: "pointer" }}>
                <input type="checkbox" checked={split}
                  onChange={(e) => setSplit(e.target.checked)} />
                Split — ship only some items (default: the whole remaining order)
              </label>
              {split && (
                <div style={{ marginTop: 6 }}>
                  {alloc.map((a, i) => (
                    <div key={a.ipr_line_id} style={{ display: "flex", gap: 8,
                      alignItems: "center", marginBottom: 4, fontSize: 12.5 }}>
                      <span style={{ flex: "1 1 auto" }}>{a.desc}</span>
                      <input type="number" value={a.qty} min="0" max={a.max}
                        style={{ ...inputStyle, width: 80 }}
                        onChange={(e) => setAlloc(alloc.map((x, j) => j === i
                          ? { ...x, qty: e.target.value } : x))} />
                      <span style={{ color: "#8a97a1", width: 96 }}>
                        / {a.max} {a.unit} left</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button style={{ ...buttonStyle, padding: "4px 12px" }}
                    onClick={create}>Save shipment</button>
            <button style={ghostButton}
                    onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </div>
      ) : (
        <button style={{ ...ghostButton, padding: "4px 12px", marginTop: 8,
                         opacity: fullyShipped ? 0.5 : 1 }}
                disabled={fullyShipped}
                title={fullyShipped ? "The whole order is already on shipments"
                  : ""}
                onClick={startAdd}>+ Book shipment</button>
      ))}
    </>
  );
}

function Shipment({ s, refIpr, canManage, call, onChanged, onError,
                    onOpenIrn, isAdmin }) {
  const fileRef = useRef(null);
  const [docType, setDocType] = useState("BL_AWB");
  const [charges, setCharges] = useState(Object.fromEntries(
    CHARGE_LABELS.map(([k]) => [k, s[k] ?? ""])));
  const [editing, setEditing] = useState(false);
  const [ef, setEf] = useState(null);
  const [carriers, setCarriers] = useState([]);
  const [carrierMeta, setCarrierMeta] = useState(null);
  const at = SHIP_STEPS.indexOf(s.status);
  const arrived = at >= SHIP_STEPS.indexOf("ARRIVED");

  function startEdit() {
    setEf({ mode: s.mode, forwarder_name: s.forwarder_display || "",
      vessel_flight: s.vessel_flight || "", carrier_scac: s.carrier_scac || "",
      bl_no: s.bl_no || "", container_awb: s.container_awb || "",
      etd: s.etd || "", eta: s.eta || "" });
    if (!carriers.length) api("/tracking/carriers")
      .then((d) => { setCarriers(d.carriers || []); setCarrierMeta(d); })
      .catch(() => {});
    setEditing(true);
  }
  async function saveEdit() {
    onError(null);
    try { await api(`/ipr/${refIpr}/shipments/${s.id}/update`,
      { method: "POST", body: ef }); setEditing(false); onChanged(); }
    catch (e) { onError(e.message); }
  }
  async function removeShip() {
    if (!window.confirm(`Delete Shipment ${s.seq}? This frees its allocated `
      + `quantities back to the order and removes its tracking. This can't be `
      + `undone.`)) return;
    onError(null);
    try { await api(`/ipr/${refIpr}/shipments/${s.id}/delete`,
      { method: "POST" }); onChanged(); }
    catch (e) { onError(e.message); }
  }

  async function upload(file) {
    if (!file) return;
    onError(null);
    const fd = new FormData();
    fd.append("file", file); fd.append("doc_type", docType);
    try { await apiUpload(`/ipr/${refIpr}/shipments/${s.id}/documents`, fd);
      onChanged(); } catch (e) { onError(e.message); }
  }
  async function receive() {
    onError(null);
    try {
      const irn = await api(`/ipr/${refIpr}/shipments/${s.id}/receive`,
                            { method: "POST", body: { location: "" } });
      onOpenIrn?.(irn.ref);
    } catch (e) { onError(e.message); }
  }

  return (
    <div style={{ border: "1px solid var(--sp-border)", borderRadius: 8,
                  padding: 10, marginBottom: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                    flexWrap: "wrap" }}>
        <strong style={{ color: "var(--sp-navy)" }}>
          Shipment {s.seq} · {s.mode}</strong>
        <span style={{ fontSize: 12, color: "#5a6b78" }}>
          {s.forwarder_display}
          {s.carrier_scac ? ` · ${s.carrier_scac}` : ""}
          {s.bl_no ? ` · B/L ${s.bl_no}` : ""}
          {s.vessel_flight ? ` · ${s.vessel_flight}` : ""}
          {s.container_awb ? ` · ${s.container_awb}` : ""}
          {s.eta ? ` · ETA ${s.eta}` : ""}</span>
        {canManage && s.status !== "CLEARED" && !editing && (
          <button style={{ ...ghostButton, padding: "1px 9px", marginLeft:
            "auto", fontSize: 12 }} onClick={startEdit}>Edit details</button>
        )}
        {isAdmin && !editing && (
          <button title="Admin — delete this shipment"
            style={{ ...ghostButton, padding: "1px 9px", fontSize: 12,
              color: "#c0392b", borderColor: "#e3b7b0",
              marginLeft: canManage && s.status !== "CLEARED" ? 0 : "auto" }}
            onClick={removeShip}>Delete</button>
        )}
      </div>
      {editing && (
        <div style={{ border: "1px solid var(--sp-border)", borderRadius: 8,
                      padding: 10, marginTop: 8, background: "#f7f9fb" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
                        gap: 8 }}>
            <select value={ef.mode} style={inputStyle}
              onChange={(e) => setEf({ ...ef, mode: e.target.value })}>
              <option value="SEA">Sea</option><option value="AIR">Air</option>
            </select>
            <input placeholder="Forwarder" value={ef.forwarder_name}
              style={inputStyle}
              onChange={(e) => setEf({ ...ef, forwarder_name: e.target.value })} />
            <input placeholder="Vessel / flight" value={ef.vessel_flight}
              style={inputStyle}
              onChange={(e) => setEf({ ...ef, vessel_flight: e.target.value })} />
            {ef.mode === "SEA" ? (
              <CarrierPicker scac={ef.carrier_scac} carriers={carriers}
                id={`edit-${s.id}`}
                onPick={(v) => setEf({ ...ef, carrier_scac: v })} />
            ) : <span />}
            {ef.mode === "SEA" && (
              <input placeholder="Booking / B/L no." value={ef.bl_no}
                style={inputStyle}
                onChange={(e) => setEf({ ...ef, bl_no: e.target.value })} />
            )}
            <input placeholder={ef.mode === "AIR" ? "AWB (11 digits)"
              : "Container no."} value={ef.container_awb} style={inputStyle}
              onChange={(e) => setEf({ ...ef, container_awb: e.target.value })} />
            <label style={{ fontSize: 11, color: "#5a6b78" }}>ETD
              <input type="date" value={ef.etd} style={inputStyle}
                onChange={(e) => setEf({ ...ef, etd: e.target.value })} /></label>
            <label style={{ fontSize: 11, color: "#5a6b78" }}>ETA
              <input type="date" value={ef.eta} style={inputStyle}
                onChange={(e) => setEf({ ...ef, eta: e.target.value })} /></label>
          </div>
          {ef.mode === "SEA" && <CarrierWarning meta={carrierMeta} />}
          <p style={{ fontSize: 11.5, color: "var(--muted)", margin: "6px 0 0" }}>
            Adding the carrier + B/L on a shipped consignment starts live
            tracking automatically.</p>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button style={{ ...buttonStyle, padding: "4px 12px" }}
              onClick={saveEdit}>Save details</button>
            <button style={ghostButton}
              onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </div>
      )}
      {s.lines && s.lines.length > 0 && (
        <div style={{ fontSize: 12, color: "#5a6b78", marginTop: 3 }}>
          <strong style={{ color: "#41505c" }}>Contents:</strong>{" "}
          {s.lines.map((l) => `${num(l.qty)}${l.unit ? " " + l.unit : ""} `
            + `${l.description}`).join(" · ")}
        </div>
      )}
      <TrackingBlock s={s} canManage={canManage} onChanged={onChanged}
                     onError={onError} />
      {canManage && !s.tracking && !editing
        && at >= SHIP_STEPS.indexOf("SHIPPED") && (
        <div style={{ fontSize: 11.5, color: "#8a5a00", marginTop: 6 }}>
          🚢 Not tracked yet —{" "}
          <button onClick={startEdit} style={{ background: "none", border: 0,
            color: "var(--sp-navy)", cursor: "pointer", padding: 0,
            textDecoration: "underline", fontSize: 11.5 }}>
            add the carrier &amp; B/L</button>{" "}to start live tracking.
        </div>
      )}
      {/* status stepper */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 5, margin: "8px 0" }}>
        {SHIP_STEPS.map((st, i) => (
          <span key={st} style={{ fontSize: 11, padding: "2px 8px",
            borderRadius: 12, background: i === at ? "var(--sp-navy)"
              : i < at ? "#e6f0e8" : "#eef1f4",
            color: i === at ? "#fff" : i < at ? "#1a7f37" : "#8a97a1",
            fontWeight: i === at ? 700 : 500 }}>
            {i < at ? "✓ " : ""}{st.replace(/_/g, " ")}</span>
        ))}
      </div>
      {canManage && s.next_statuses.length > 0 && (
        <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
          {s.next_statuses.map((ns) => (
            <button key={ns} style={{ ...ghostButton, padding: "2px 10px",
                                      fontSize: 12 }}
                    onClick={() => call(`/shipments/${s.id}/status`,
                                        { status: ns })}>
              → {ns.replace(/_/g, " ")}</button>
          ))}
          {!s.shared_with_agent_at && (
            <button style={{ ...ghostButton, padding: "2px 10px", fontSize: 12 }}
                    onClick={() => call(`/shipments/${s.id}/share`, {})}>
              Share with clearing agent</button>
          )}
          {s.shared_with_agent_at && (
            <span style={{ fontSize: 11.5, color: "#1a7f37" }}>
              ✓ shared with agent</span>
          )}
          {arrived && (
            <button style={{ ...buttonStyle, padding: "2px 10px",
                             fontSize: 12 }}
                    onClick={receive}
                    title="Count into the HO store (creates an IRN)">
              📦 Receive at store</button>
          )}
        </div>
      )}

      {/* documents */}
      <div style={{ fontSize: 12.5 }}>
        {s.documents.map((d) => (
          <span key={d.id} style={{ marginRight: 10 }}>
            <a href={d.file_url} target="_blank" rel="noreferrer">
              📎 {d.doc_type_display}</a></span>
        ))}
        {s.missing_clearing.length > 0 && (
          <span style={{ color: "#b35900", marginLeft: 4 }}>
            (for clearing, still need: {s.missing_clearing.map((m) =>
              (DOC_TYPES.find((t) => t[0] === m) || [, m])[1]).join(", ")})</span>
        )}
      </div>
      {canManage && (
        <div style={{ display: "flex", gap: 6, marginTop: 6,
                      alignItems: "center" }}>
          <select value={docType} style={{ ...inputStyle, width: 200 }}
                  onChange={(e) => setDocType(e.target.value)}>
            {DOC_TYPES.map((t) => (
              <option key={t[0]} value={t[0]}>{t[1]}</option>
            ))}
          </select>
          <input type="file" ref={fileRef} style={{ display: "none" }}
                 onChange={(e) => upload(e.target.files[0])} />
          <button style={{ ...ghostButton, padding: "3px 10px", fontSize: 12 }}
                  onClick={() => fileRef.current?.click()}>Upload document</button>
        </div>
      )}

      {/* clearing charges */}
      {(canManage || s.clearing_total > 0) && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11.5, color: "#5a6b78", marginBottom: 3 }}>
            Clearing charges (MVR) — feed the landed cost</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap",
                        alignItems: "center" }}>
            {CHARGE_LABELS.map(([k, label]) => (
              <input key={k} type="number" placeholder={label}
                value={charges[k]} disabled={!canManage}
                style={{ ...inputStyle, width: 120 }}
                onChange={(e) => setCharges({ ...charges, [k]: e.target.value })}
                title={label} />
            ))}
            {canManage && (
              <button style={{ ...ghostButton, padding: "3px 10px",
                               fontSize: 12 }}
                      onClick={() => call(`/shipments/${s.id}/charges`,
                                          charges)}>Save charges</button>
            )}
            <span style={{ fontSize: 12.5, fontWeight: 600,
                           color: "var(--sp-navy)" }}>
              Total: MVR {money(s.clearing_total)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

export function IrnView({ me, refIrn, onClose }) {
  const [doc, setDoc] = useState(null);
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);

  function load() {
    api(`/irn/${refIrn}`).then((d) => {
      setDoc(d);
      setRows(d.lines.map((l) => ({ id: l.id,
        received_qty: l.received_qty ?? "", damaged_qty: l.damaged_qty ?? "",
        condition_note: l.condition_note || "" })));
    }).catch((e) => setError(e.message));
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [refIrn]);

  const setRow = (i, patch) =>
    setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  async function post() {
    setError(null);
    try {
      await api(`/irn/${refIrn}/post`, { method: "POST", body: { rows } });
      load();
    } catch (e) { setError(e.message); }
  }

  if (!doc) return <section style={card}>{error || "Loading…"}</section>;
  const draft = doc.status === "DRAFT";

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
          {doc.ref} <StatusChip status={doc.status} /></h2>
        <button onClick={onClose} style={ghostButton}>Close</button>
      </div>
      <p style={{ color: "#5a6b78", fontSize: 13, margin: "6px 0 0" }}>
        Import Receipt · {doc.supplier} · order {doc.ipr_ref} · shipment{" "}
        {doc.shipment_seq}</p>
      {doc.landed && (
        <p style={{ fontSize: 12.5, marginTop: 4 }}>
          Landed MVR {money(doc.landed.total_landed)} ·{" "}
          {money(doc.landed.uplift_pct)}% uplift over goods</p>
      )}
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <SectionTitle>Count against the order</SectionTitle>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 13 }}>
          <thead><tr>
            <th style={th}>Item</th><th style={th}>Unit</th>
            <th style={{ ...th, textAlign: "right" }}>Expected</th>
            <th style={{ ...th, textAlign: "right" }}>Received</th>
            <th style={{ ...th, textAlign: "right" }}>Damaged</th>
            <th style={{ ...th, textAlign: "right" }}>Unit landed (MVR)</th>
            <th style={th}>Condition</th>
          </tr></thead>
          <tbody>
            {doc.lines.map((l, i) => {
              const rec = num(rows[i]?.received_qty);
              const short = rec !== num(l.expected_qty);
              return (
                <tr key={l.id}>
                  <td style={td}>{l.description}</td>
                  <td style={td}>{l.unit}</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {money(l.expected_qty)}</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {draft ? (
                      <input type="number" value={rows[i]?.received_qty ?? ""}
                        onChange={(e) => setRow(i,
                          { received_qty: e.target.value })}
                        style={{ ...inputStyle, width: 80, textAlign: "right",
                          background: short ? "#fff8e6" : undefined }} />
                    ) : money(l.received_qty)}</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {draft ? (
                      <input type="number" value={rows[i]?.damaged_qty ?? ""}
                        onChange={(e) => setRow(i,
                          { damaged_qty: e.target.value })}
                        style={{ ...inputStyle, width: 70,
                                 textAlign: "right" }} />
                    ) : (l.damaged_qty ? money(l.damaged_qty) : "")}</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {money(l.unit_landed_cost)}</td>
                  <td style={td}>
                    {draft ? (
                      <input value={rows[i]?.condition_note ?? ""}
                        onChange={(e) => setRow(i,
                          { condition_note: e.target.value })}
                        style={{ ...inputStyle, width: 140 }} />
                    ) : l.condition_note}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {draft && doc.can_post && (
        <div style={{ marginTop: 12 }}>
          <button onClick={post} style={buttonStyle}>
            Post receipt — create stock lots</button>
          <p style={{ fontSize: 12, color: "#5a6b78", marginTop: 6 }}>
            Creates valued lots in the HO store at unit landed cost. A shortage
            or damage alerts the Director.</p>
        </div>
      )}
      {doc.status === "RECEIVED" && (
        <p style={{ fontSize: 12.5, color: "#1a7f37", marginTop: 10 }}>
          ✓ Received — stock lots created in the HO store.</p>
      )}
    </section>
  );
}

const EMPTY_OS = { item_id: "", qty: "", unit_cost: "", project_id: "",
                   location: "" };

export function StoreLots({ me, onOpenIrn }) {
  const [data, setData] = useState(null);
  const [sins, setSins] = useState([]);
  const [sites, setSites] = useState([]);
  const [items, setItems] = useState([]);
  const [projects, setProjects] = useState([]);
  const [sel, setSel] = useState({});          // lot id -> qty to issue
  const [destSite, setDestSite] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [osOpen, setOsOpen] = useState(false);        // opening-stock panel
  const [osLines, setOsLines] = useState([{ ...EMPTY_OS }]);
  const [osNote, setOsNote] = useState("");
  const [osMsg, setOsMsg] = useState(null);
  const canIssue = ["HO_PURCHASING", "ADMIN"].includes(me?.role);

  const reload = () => {
    api("/store/lots").then(setData).catch((e) => setError(e.message));
    api("/store/issues").then(setSins).catch(() => {});
    api("/sites").then(setSites).catch(() => {});
    if (["HO_PURCHASING", "ADMIN"].includes(me?.role)) {
      api("/items").then(setItems).catch(() => {});
      api("/ipr/context").then((c) => setProjects(c.projects || []))
        .catch(() => {});
    }
  };
  useEffect(reload, []);

  const setOsLine = (i, patch) =>
    setOsLines(osLines.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  const osValid = osLines.some((l) => l.item_id && Number(l.qty) > 0);

  const saveOpening = () => {
    setError(null); setOsMsg(null);
    const lines = osLines
      .filter((l) => l.item_id && Number(l.qty) > 0)
      .map((l) => ({ item_id: Number(l.item_id), qty: Number(l.qty),
                     unit_cost: Number(l.unit_cost) || 0,
                     project_id: l.project_id ? Number(l.project_id) : null,
                     location: l.location }));
    setBusy(true);
    api("/store/opening-stock", { method: "POST",
      body: { lines, note: osNote } })
      .then((r) => {
        setOsMsg(`✓ ${r.lots} lot(s) added — value MVR ${money(r.total_value)}.`);
        setOsLines([{ ...EMPTY_OS }]); setOsNote(""); setOsOpen(false);
        reload();
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  };

  const chosen = Object.entries(sel)
    .filter(([, q]) => Number(q) > 0)
    .map(([lot_id, qty]) => ({ lot_id: Number(lot_id), qty: Number(qty) }));

  const issue = () => {
    setError(null);
    if (!destSite) { setError("Choose the destination site."); return; }
    if (!chosen.length) { setError("Enter a quantity on the lots to issue."); return; }
    setBusy(true);
    api("/store/issues", { method: "POST",
      body: { to_site_id: Number(destSite), rows: chosen } })
      .then((sin) => api(`/sin/${sin.ref}/issue`, { method: "POST" }))
      .then(() => { setSel({}); setDestSite(""); reload(); })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  };

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <section style={card}>
        <div style={{ display: "flex", alignItems: "center", gap: 12,
                      flexWrap: "wrap" }}>
          <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
            🏬 HO Store — stock lots</h2>
          {canIssue && chosen.length === 0 && (
            <button onClick={() => { setOsOpen(!osOpen); setOsMsg(null); }}
                    style={{ ...ghostButton, padding: "3px 12px",
                             fontSize: 12.5 }}>
              {osOpen ? "Cancel" : "➕ Receive opening stock"}</button>
          )}
          {canIssue && chosen.length > 0 && (
            <span style={{ marginLeft: "auto", display: "flex", gap: 10,
                           alignItems: "center", flexWrap: "wrap" }}>
              <span style={{ fontSize: 13 }}>Issue {chosen.length} lot
                {chosen.length === 1 ? "" : "s"} to</span>
              <select value={destSite}
                      onChange={(e) => setDestSite(e.target.value)}
                      style={{ ...inputStyle, width: 200 }}>
                <option value="">— site —</option>
                {sites.filter((s) => !s.is_head_office).map((s) => (
                  <option key={s.id} value={s.id}>{s.code} — {s.name}</option>
                ))}
              </select>
              <Btn variant="primary" disabled={busy} onClick={issue}>
                Issue to site</Btn>
            </span>
          )}
        </div>
        {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
        <p style={{ fontSize: 12.5, color: "#5a6b78" }}>
          Imported stock at landed cost — reserved to a project or held as
          general company stock. A company asset until issued to a site
          {canIssue && "; tick a quantity to issue it out (SIN)"}.</p>
        {osMsg && (
          <p style={{ color: "#1a7f37", fontSize: 13 }}>{osMsg}</p>
        )}

        {osOpen && (
          <div style={{ border: "1px dashed var(--sp-border)", borderRadius: 8,
                        padding: 14, marginBottom: 12 }}>
            <strong style={{ color: "var(--sp-navy)", fontSize: 14 }}>
              Receive opening / manual stock</strong>
            <p style={{ fontSize: 12, color: "#5a6b78", margin: "4px 0 10px" }}>
              Record stock already sitting in the HO store at its unit cost.
              Creates a valued lot per line — a company asset until issued to a
              site (no purchase or import needed).</p>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse",
                              fontSize: 13 }}>
                <thead><tr>
                  <th style={th}>Item</th>
                  <th style={{ ...th, textAlign: "right" }}>Qty</th>
                  <th style={{ ...th, textAlign: "right" }}>Unit cost (MVR)</th>
                  <th style={th}>Reserve to project</th>
                  <th style={th}>Location</th><th />
                </tr></thead>
                <tbody>
                  {osLines.map((l, i) => (
                    <tr key={i}>
                      <td style={{ padding: 3, minWidth: 220 }}>
                        <select value={l.item_id}
                                onChange={(e) => setOsLine(i,
                                  { item_id: e.target.value })}
                                style={{ ...inputStyle, width: "100%" }}>
                          <option value="">Select item…</option>
                          {items.map((it) => (
                            <option key={it.id} value={it.id}>
                              {it.code} · {it.description}</option>
                          ))}
                        </select>
                      </td>
                      <td style={{ padding: 3 }}>
                        <input type="number" min="0" value={l.qty}
                               onChange={(e) => setOsLine(i,
                                 { qty: e.target.value })}
                               style={{ ...inputStyle, width: 80,
                                        textAlign: "right" }} />
                      </td>
                      <td style={{ padding: 3 }}>
                        <input type="number" min="0" value={l.unit_cost}
                               onChange={(e) => setOsLine(i,
                                 { unit_cost: e.target.value })}
                               style={{ ...inputStyle, width: 100,
                                        textAlign: "right" }} />
                      </td>
                      <td style={{ padding: 3 }}>
                        <select value={l.project_id}
                                onChange={(e) => setOsLine(i,
                                  { project_id: e.target.value })}
                                style={{ ...inputStyle, width: 190 }}>
                          <option value="">General stock</option>
                          {projects.map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.code} — {p.site_code || p.site?.code || ""}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td style={{ padding: 3 }}>
                        <input value={l.location}
                               onChange={(e) => setOsLine(i,
                                 { location: e.target.value })}
                               placeholder="Rack / bin"
                               style={{ ...inputStyle, width: 120 }} />
                      </td>
                      <td style={{ width: 30 }}>
                        {osLines.length > 1 && (
                          <button onClick={() => setOsLines(
                                    osLines.filter((_, j) => j !== i))}
                                  style={{ ...ghostButton, padding: "2px 8px",
                                           color: "#c0392b" }}>×</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button onClick={() => setOsLines([...osLines, { ...EMPTY_OS }])}
                    style={{ ...ghostButton, padding: "4px 12px",
                             marginTop: 6 }}>+ Add line</button>
            <div style={{ display: "flex", gap: 10, marginTop: 10,
                          alignItems: "center", flexWrap: "wrap" }}>
              <input value={osNote}
                     onChange={(e) => setOsNote(e.target.value)}
                     placeholder="Note / reference (optional)"
                     style={{ ...inputStyle, width: 260 }} />
              <Btn variant="primary" disabled={!osValid || busy}
                   onClick={saveOpening}>
                {busy ? "Saving…" : "Receive into store"}</Btn>
            </div>
          </div>
        )}
        <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 13 }}>
          <thead><tr>
            <th style={th}>Item</th><th style={th}>Reserved for</th>
            <th style={th}>Site</th>
            <th style={{ ...th, textAlign: "right" }}>On hand</th>
            <th style={{ ...th, textAlign: "right" }}>In transit</th>
            <th style={{ ...th, textAlign: "right" }}>Unit landed</th>
            <th style={{ ...th, textAlign: "right" }}>Value (MVR)</th>
            <th style={th}>Source</th>
            {canIssue && <th style={{ ...th, width: 100 }}>Issue qty</th>}
          </tr></thead>
          <tbody>
            {(data?.lots || []).map((l) => (
              <tr key={l.id}>
                <td style={td}>{l.description}</td>
                <td style={td}>{l.reserved_for === "General stock"
                  ? <span style={{ color: "#8a6d00" }}>General stock</span>
                  : l.reserved_for}</td>
                <td style={td}>{l.site}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {money(l.qty_on_hand)} {l.unit}</td>
                <td style={{ ...td, textAlign: "right",
                             color: Number(l.qty_in_transit) > 0
                               ? "#b35900" : "#8a97a1" }}>
                  {Number(l.qty_in_transit) > 0
                    ? money(l.qty_in_transit) : "—"}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {money(l.unit_landed_cost)}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {money(l.value_on_hand)}</td>
                <td style={td}>
                  {String(l.source_irn || "").startsWith("IRN") ? (
                    <a href="#" onClick={(e) => { e.preventDefault();
                                                  onOpenIrn?.(l.source_irn); }}
                       style={{ color: "var(--sp-navy)" }}>{l.source_irn}</a>
                  ) : (
                    <span style={{ color: "#8a97a1" }}>{l.source_irn}</span>
                  )}</td>
                {canIssue && (
                  <td style={td}>
                    <input type="number" min="0" max={l.qty_on_hand}
                           value={sel[l.id] || ""}
                           disabled={Number(l.qty_on_hand) <= 0}
                           onChange={(e) => setSel({ ...sel,
                             [l.id]: e.target.value })}
                           style={{ ...inputStyle, width: 80 }} />
                  </td>
                )}
              </tr>
            ))}
            {data && data.lots.length === 0 && (
              <tr><td colSpan={canIssue ? 9 : 8}
                      style={{ ...td, textAlign: "center",
                               color: "var(--muted)" }}>
                No stock in the store yet.</td></tr>
            )}
          </tbody>
          {data && data.lots.length > 0 && (
            <tfoot><tr>
              <td colSpan={6} style={{ ...td, textAlign: "right",
                                       fontWeight: 700 }}>Total store value</td>
              <td style={{ ...td, textAlign: "right", fontWeight: 700 }}>
                {money(data.total_value)}</td>
              <td colSpan={canIssue ? 2 : 1} style={td} />
            </tr></tfoot>
          )}
        </table>
        </div>
      </section>

      {sins.length > 0 && (
        <section style={card}>
          <h3 style={{ margin: "0 0 8px", fontSize: 15,
                       color: "var(--sp-navy)" }}>Store issues (SIN)</h3>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
            <thead><tr>
              <th style={th}>SIN</th><th style={th}>To site</th>
              <th style={th}>Lines</th><th style={th}>Date</th>
              <th style={th}>Status</th><th style={th} />
            </tr></thead>
            <tbody>
              {sins.map((s) => (
                <tr key={s.ref}>
                  <td style={td}>{s.ref}</td>
                  <td style={td}>{s.to_site}
                    {s.to_project ? ` · ${s.to_project}` : ""}</td>
                  <td style={td}>{s.lines}</td>
                  <td style={td}>{s.doc_date}</td>
                  <td style={td}><StatusChip status={s.status} /></td>
                  <td style={td}>
                    {s.status === "ISSUED" && (
                      <button style={{ ...ghostButton, padding: "2px 10px",
                                       fontSize: 12 }} disabled={busy}
                              onClick={() => {
                                setBusy(true);
                                api(`/sin/${s.ref}/receive`, { method: "POST" })
                                  .then(() => reload())
                                  .catch((e) => setError(e.message))
                                  .finally(() => setBusy(false));
                              }}>
                        Mark received at site</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ fontSize: 11.5, color: "var(--muted)", margin: "6px 0 0" }}>
            Receiving a store issue posts the material to the site project at
            landed cost.</p>
        </section>
      )}
    </section>
  );
}

const SHIP_TONE = { BOOKED: "#8a97a1", SHIPPED: "#1d6fb8",
  IN_TRANSIT: "#1d6fb8", ARRIVED: "#b35900", UNDER_CLEARING: "#b35900",
  CLEARED: "#1a7f37" };

const HEALTH_TONE = { ACTIVE: "#1a7f37", ARRIVED: "#1d6fb8",
  PENDING_REGISTRATION: "#b35900", FAILED: "#c0392b", MANUAL: "#6b7681",
  STALE: "#c0392b" };

function TrackingHealth() {
  const [rows, setRows] = useState(null);
  const load = () => api("/tracking/health")
    .then((d) => setRows(d.items || [])).catch(() => setRows([]));
  useEffect(() => { load(); }, []);
  if (!rows || rows.length === 0) return null;
  const attention = rows.filter((r) =>
    ["FAILED", "STALE", "PENDING_REGISTRATION"].includes(r.health)).length;
  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <h3 style={{ margin: 0, fontSize: 14, color: "var(--sp-navy)" }}>
          🚢 Shipment tracking health</h3>
        {attention > 0 && (
          <span style={{ fontSize: 11.5, color: "#c0392b" }}>
            {attention} need attention</span>)}
        <button style={{ ...ghostButton, padding: "2px 10px", marginLeft:
          "auto" }} onClick={load}>Refresh</button>
      </div>
      <div style={{ overflowX: "auto", marginTop: 8 }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 12.5 }}>
          <thead><tr>
            <th style={th}>Order</th><th style={th}>Mode</th>
            <th style={th}>Key</th><th style={th}>State</th>
            <th style={th}>Live status</th><th style={th}>ETA</th>
            <th style={th}>Last event</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td style={td}>{r.ipr_ref} · S{r.shipment_seq}</td>
                <td style={td}>{r.mode}</td>
                <td style={td}>{r.carrier_scac ? r.carrier_scac + " · " : ""}
                  {r.tracking_key || "—"}</td>
                <td style={{ ...td, color: HEALTH_TONE[r.health] || "#41505c",
                  fontWeight: 600 }}>{r.health}</td>
                <td style={td}>{r.raw_status || "—"}</td>
                <td style={td}>{r.current_eta
                  ? r.current_eta.slice(0, 10) : "—"}</td>
                <td style={td}>{r.last_event_at
                  ? r.last_event_at.slice(0, 10) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CarrierAdmin({ isAdmin }) {
  const [meta, setMeta] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const load = () => api("/tracking/carriers").then(setMeta).catch(() => {});
  useEffect(() => { load(); }, []);
  if (!meta) return null;
  const problem = meta.never_synced || !meta.sync_ok || meta.count === 0;
  async function refresh() {
    setBusy(true); setMsg("");
    try {
      const r = await api("/tracking/carriers/refresh", { method: "POST" });
      setMsg(`Synced ${r.count} carriers.`); load();
    } catch (e) { setMsg(e.message); }
    finally { setBusy(false); }
  }
  return (
    <section style={{ ...card, display: "flex", alignItems: "center",
      gap: 10, flexWrap: "wrap", padding: "10px 14px",
      borderColor: problem ? "#e3b7b0" : "var(--sp-border)" }}>
      <span style={{ fontSize: 13, color: "var(--sp-navy)", fontWeight: 600 }}>
        🚢 Shipping lines</span>
      <span style={{ fontSize: 12.5, color: problem ? "#b0402f" : "#5a6b78" }}>
        {problem
          ? `⚠ ${meta.never_synced ? "never synced" : !meta.sync_ok
              ? "last sync failed" : "empty"} — ${meta.count || 0} available`
          : `${meta.count} carriers · last synced ${(meta.synced_at || "")
              .slice(0, 10)}`}
        {meta.sync_error ? ` — ${meta.sync_error}` : ""}
      </span>
      {isAdmin && (
        <button style={{ ...ghostButton, padding: "3px 12px", marginLeft:
          "auto" }} disabled={busy} onClick={refresh}>
          {busy ? "Refreshing…" : "Refresh now"}</button>
      )}
      {msg && <span style={{ fontSize: 12, color: "#5a6b78" }}>{msg}</span>}
    </section>
  );
}

export function ImportTracker({ me, onOpenIpr }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    api("/imports/tracker").then(setData).catch((e) => setError(e.message));
  }, []);
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 18 }}>
          🌍 Import tracker</h2>
        <p style={{ color: "var(--muted)", fontSize: 12.5, margin: "4px 0 0" }}>
          Every overseas order and where it stands — demand (PMR) → order (IPR)
          → shipment → receipt (IRN) → payments.</p>
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <CarrierAdmin isAdmin={me && me.role === "ADMIN"} />
      <TrackingHealth />

      {data?.awaiting_order?.length > 0 && (
        <section style={card}>
          <h3 style={{ margin: "0 0 8px", fontSize: 14, color: "#b35900" }}>
            Awaiting an order — sized & released demand ({data.awaiting_order
              .length})</h3>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {data.awaiting_order.map((p) => (
              <span key={p.ref} style={{ fontSize: 12.5, padding: "3px 10px",
                border: "1px solid var(--sp-border)", borderRadius: 20 }}>
                {p.ref}{p.project ? ` · ${p.project}` : ""} · {p.status}</span>
            ))}
          </div>
        </section>
      )}

      <section style={card}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
            <thead><tr>
              <th style={th}>Order</th><th style={th}>Supplier</th>
              <th style={th}>Stage</th>
              <th style={{ ...th, textAlign: "right" }}>Value</th>
              <th style={th}>Shipments</th><th style={th}>Payments</th>
              <th style={th}>Receipt</th>
            </tr></thead>
            <tbody>
              {(data?.orders || []).map((o) => (
                <tr key={o.ref}>
                  <td style={td}>
                    <a href="#" onClick={(e) => { e.preventDefault();
                                                  onOpenIpr(o.ref); }}
                       style={{ color: "var(--sp-navy)", fontWeight: 600 }}>
                      {o.ref}</a>
                    {o.pmrs.length > 0 && (
                      <div style={{ fontSize: 11, color: "#8a97a1" }}>
                        ← {o.pmrs.join(", ")}</div>
                    )}
                  </td>
                  <td style={td}>{o.supplier}</td>
                  <td style={td}><StatusChip status={o.status} /></td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {o.currency} {money(o.order_total)}</td>
                  <td style={td}>
                    {o.shipments.length === 0
                      ? <span style={{ color: "#8a97a1" }}>—</span>
                      : o.shipments.map((s) => (
                        <div key={s.seq} style={{ fontSize: 12 }}>
                          #{s.seq}{" "}
                          <span style={{ color: SHIP_TONE[s.status] || "inherit",
                            fontWeight: 600 }}>{s.status_display}</span>
                          {s.eta ? ` · ETA ${s.eta}` : ""}</div>
                      ))}
                  </td>
                  <td style={td}>
                    {o.milestones_total === 0
                      ? <span style={{ color: "#8a97a1" }}>no schedule</span>
                      : <span style={{ fontWeight: 600, color:
                          o.milestones_paid === o.milestones_total
                            ? "#1a7f37" : "#b35900" }}>
                          {o.milestones_paid}/{o.milestones_total} paid</span>}
                  </td>
                  <td style={td}>
                    {o.receipts.length === 0
                      ? <span style={{ color: "#8a97a1" }}>—</span>
                      : o.receipts.map((r) => (
                        <div key={r.ref} style={{ fontSize: 12 }}>
                          {r.ref} · {r.status}</div>))}
                  </td>
                </tr>
              ))}
              {data && data.orders.length === 0 && (
                <tr><td colSpan={7} style={{ ...td, textAlign: "center",
                  color: "var(--muted)" }}>No overseas orders yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}

export function ImportPaymentsDue({ onOpenIpr }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    api("/ipr/payments-due").then(setRows).catch((e) => setError(e.message));
  }, []);
  return (
    <section style={card}>
      <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
        🌍 Import payments due</h2>
      <p style={{ color: "var(--muted)", fontSize: 12.5, margin: "4px 0 0" }}>
        Every overseas TT is authorised on a Payment Voucher first. Batch a
        due one on the <strong>Payment Vouchers</strong> page; once a signatory
        approves it, record the TT against its milestone.</p>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12,
                      fontSize: 13 }}>
        <thead><tr>
          <th style={th}>Order</th><th style={th}>Supplier</th>
          <th style={th}>Milestone</th>
          <th style={{ ...th, textAlign: "right" }}>Amount</th>
          <th style={{ ...th, textAlign: "right" }}>≈ MVR</th>
          <th style={th}>Due</th><th style={th}>Stage</th>
        </tr></thead>
        <tbody>
          {(rows || []).map((r) => (
            <tr key={r.milestone_id}>
              <td style={td}>
                <a href="#" onClick={(e) => { e.preventDefault();
                                              onOpenIpr(r.ipr_ref); }}
                   style={{ color: "var(--sp-navy)", fontWeight: 600 }}>
                  {r.ipr_ref}</a>
              </td>
              <td style={td}>{r.supplier}</td>
              <td style={td}>{r.label}</td>
              <td style={{ ...td, textAlign: "right" }}>
                {r.currency} {money(r.due_amount)}</td>
              <td style={{ ...td, textAlign: "right" }}>{money(r.expected_mvr)}</td>
              <td style={td}>{r.due_date || "—"}</td>
              <td style={td}>
                {r.stage === "READY"
                  ? <span style={{ color: "#1d6fb8", fontWeight: 600 }}>
                      Authorised · {r.voucher_ref} → record TT</span>
                  : <span style={{ color: "#b35900", fontWeight: 600 }}>
                      Awaiting voucher</span>}
              </td>
            </tr>
          ))}
          {rows && rows.length === 0 && (
            <tr><td colSpan={7} style={{ ...td, textAlign: "center",
                                         color: "var(--muted)" }}>
              No import payments due. Purchasing marks a milestone due when its
              trigger is met.</td></tr>
          )}
        </tbody>
      </table>
    </section>
  );
}

const TRIGGERS = [["ADVANCE", "Advance / on order"], ["BL", "On B/L"],
                  ["ARRIVAL", "On arrival"], ["DATE", "By date"],
                  ["BALANCE", "Balance / other"]];

function MilestonePanel({ doc, me, refIpr, onChanged, onError }) {
  const ms = doc.milestones || [];
  const [editing, setEditing] = useState(false);
  const [rows, setRows] = useState([{ label: "", trigger: "ADVANCE",
    basis: "pct", value: "" }]);
  const canManage = doc.can_manage;
  const canPay = doc.can_pay;
  const anyPaid = ms.some((m) => m.status === "PAID");

  async function call(path, body) {
    onError(null);
    try {
      await api(`/ipr/${refIpr}${path}`, { method: "POST", body });
      setEditing(false);
      onChanged();
    } catch (e) { onError(e.message); }
  }
  async function uploadTt(mId, file) {
    if (!file) return;
    onError(null);
    const fd = new FormData();
    fd.append("file", file);
    try { await apiUpload(`/ipr/${refIpr}/milestones/${mId}/tt-advice`, fd);
      onChanged(); } catch (e) { onError(e.message); }
  }

  const paidTotal = ms.filter((m) => m.status === "PAID")
    .reduce((a, m) => a + num(m.mvr_paid), 0);

  // Schedule balance while editing: each row is a % of the order value or a
  // fixed amount in the order currency; the sum must equal the order total.
  const orderTotal = num(doc.order_total);
  const ccy = (doc.order && doc.order.order_currency) || doc.currency || "";
  const scheduled = rows.reduce((a, r) => a + (r.basis === "fixed"
    ? num(r.value) : (num(r.value) / 100) * orderTotal), 0);
  const balanced = Math.abs(scheduled - orderTotal) < 0.01;

  return (
    <>
      <SectionTitle>Payment schedule</SectionTitle>
      {doc.status !== "AUTHORISED" && ms.length === 0 && (
        <p style={{ fontSize: 12.5, color: "var(--muted)" }}>
          Set the part-payment milestones here; Finance pays each once the order
          is authorised.</p>
      )}

      {ms.length > 0 && !editing && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
            <thead><tr>
              <th style={th}>Milestone</th><th style={th}>Trigger</th>
              <th style={{ ...th, textAlign: "right" }}>Amount</th>
              <th style={th}>Status</th><th style={th}>TT / paid</th>
              <th style={th} />
            </tr></thead>
            <tbody>
              {ms.map((m) => (
                <tr key={m.id}>
                  <td style={td}>{m.label}</td>
                  <td style={td}>{(TRIGGERS.find((t) => t[0] === m.trigger)
                    || [, m.trigger])[1]}
                    {m.percent ? ` · ${num(m.percent)}%`
                      : (m.fixed_amount != null ? " · fixed" : "")}</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {doc.order.order_currency} {money(m.due_amount)}</td>
                  <td style={td}>
                    {m.status === "PAID"
                      ? <span style={{ color: "#1a7f37", fontWeight: 600 }}>
                          Paid</span>
                      : m.status === "AUTHORISED"
                        ? <span style={{ color: "#1d6fb8", fontWeight: 600 }}>
                            Authorised{m.voucher_ref
                              ? ` · ${m.voucher_ref}` : ""}</span>
                        : m.status === "DUE"
                          ? <span style={{ color: "#b35900", fontWeight: 600 }}>
                              Due · needs voucher</span>
                          : <span style={{ color: "#8a97a1" }}>Pending</span>}
                  </td>
                  <td style={{ ...td, fontSize: 12 }}>
                    {m.status === "PAID" && (<>
                      {m.tt_ref || "—"} · MVR {money(m.mvr_paid)} @{" "}
                      {num(m.actual_rate)}
                      {m.tt_advice_url && (
                        <> · <a href={m.tt_advice_url} target="_blank"
                               rel="noreferrer">📎 advice</a></>
                      )}
                      {canPay && !m.tt_advice_url && (
                        <> · <label style={{ color: "var(--sp-navy)",
                          cursor: "pointer" }}>attach advice
                          <input type="file" style={{ display: "none" }}
                            onChange={(e) => uploadTt(m.id, e.target.files[0])}
                          /></label></>
                      )}
                    </>)}</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {canManage && m.status === "PENDING" && (
                      <button style={{ ...ghostButton, padding: "2px 8px",
                                       fontSize: 12 }}
                              onClick={() => call(
                                `/milestones/${m.id}/due`, {})}>
                        Mark due</button>
                    )}
                    {canPay && m.status === "DUE" && (
                      <span style={{ fontSize: 11.5, color: "#b35900" }}>
                        Batch on a Payment Voucher to authorise</span>
                    )}
                    {canPay && m.status === "AUTHORISED" && (
                      <button style={{ ...buttonStyle, padding: "2px 10px",
                                       fontSize: 12 }}
                              onClick={() => {
                                const mvr = window.prompt(
                                  `MVR actually paid for "${m.label}" `
                                  + `(${doc.order.order_currency} ${money(
                                      m.due_amount)}, authorised on `
                                  + `${m.voucher_ref || "voucher"}):`);
                                if (!mvr) return;
                                const tt = window.prompt("TT reference:") || "";
                                call(`/milestones/${m.id}/pay`,
                                     { mvr_paid: mvr, tt_ref: tt });
                              }}>
                        Record TT payment</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {paidTotal > 0 && (
            <p style={{ fontSize: 12.5, color: "#1a7f37", marginTop: 6 }}>
              Paid to date: MVR {money(paidTotal)}</p>
          )}
          {canManage && !anyPaid && (
            <button style={{ ...ghostButton, padding: "3px 10px", fontSize: 12,
                             marginTop: 6 }}
                    onClick={() => { setRows(ms.map((m) => ({ label: m.label,
                      trigger: m.trigger,
                      basis: m.fixed_amount != null ? "fixed" : "pct",
                      value: m.fixed_amount != null ? String(num(m.fixed_amount))
                        : (m.percent ? String(num(m.percent)) : "") })));
                      setEditing(true); }}>
              Edit schedule</button>
          )}
        </div>
      )}

      {canManage && (ms.length === 0 || editing) && (
        <div style={{ marginTop: 6 }}>
          {rows.map((r, i) => (
            <div key={i} style={{ display: "flex", gap: 6, marginBottom: 6 }}>
              <input placeholder="Milestone (e.g. Advance)" value={r.label}
                style={{ ...inputStyle, flex: "1 1 auto" }}
                onChange={(e) => setRows(rows.map((x, j) => j === i
                  ? { ...x, label: e.target.value } : x))} />
              <select value={r.trigger} style={{ ...inputStyle, width: 160 }}
                onChange={(e) => setRows(rows.map((x, j) => j === i
                  ? { ...x, trigger: e.target.value } : x))}>
                {TRIGGERS.map((t) => (
                  <option key={t[0]} value={t[0]}>{t[1]}</option>
                ))}
              </select>
              <select value={r.basis} style={{ ...inputStyle, width: 96 }}
                onChange={(e) => setRows(rows.map((x, j) => j === i
                  ? { ...x, basis: e.target.value } : x))}>
                <option value="pct">% of order</option>
                <option value="fixed">Fixed {ccy}</option>
              </select>
              <input type="number"
                placeholder={r.basis === "fixed" ? (ccy || "amount") : "%"}
                value={r.value}
                style={{ ...inputStyle, width: 90 }}
                onChange={(e) => setRows(rows.map((x, j) => j === i
                  ? { ...x, value: e.target.value } : x))} />
              {rows.length > 1 && (
                <button style={{ ...ghostButton, color: "#c0392b",
                                 padding: "2px 8px" }}
                        onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                  ×</button>
              )}
            </div>
          ))}
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button style={{ ...ghostButton, padding: "3px 10px", fontSize: 12 }}
                    onClick={() => setRows([...rows, { label: "",
                      trigger: "BALANCE", basis: "pct", value: "" }])}>
              + milestone</button>
            <span style={{ fontSize: 12, fontWeight: 600,
              color: balanced ? "#1a7f37" : "#b35900" }}>
              {ccy} {money(scheduled)} / {money(orderTotal)}
              {balanced ? " ✓" : " — must equal the order total"}
            </span>
            <button style={{ ...buttonStyle, padding: "4px 12px", fontSize: 13,
                             marginLeft: "auto", opacity: balanced ? 1 : 0.5 }}
                    disabled={!balanced}
                    onClick={() => call("/milestones", { rows: rows.map((r) => ({
                      label: r.label, trigger: r.trigger,
                      percent: r.basis === "pct" ? r.value : "",
                      fixed_amount: r.basis === "fixed" ? r.value : "" })) })}>
              Save schedule</button>
            {editing && (
              <button style={ghostButton}
                      onClick={() => setEditing(false)}>Cancel</button>
            )}
          </div>
        </div>
      )}
    </>
  );
}
