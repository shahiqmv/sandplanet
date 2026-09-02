import { Fragment, useEffect, useMemo, useRef, useState } from "react";
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
  // Fix a wrong order after authorisation: reverses the commitment + voids the
  // supplier PO, back to Draft to edit + re-authorise (Signatory/Admin).
  ["withdraw-authorisation", "Withdraw authorisation", ["AUTHORISED"],
   ["SIGNATORY", "ADMIN"], "comment"],
  // Admin void of a wrong order before it's authorised.
  ["void", "Void order", ["DRAFT", "SUBMITTED", "APPROVED"], ["ADMIN"],
   "reason"],
];

const SHIP_WORD = { BOOKED: "Booked", SHIPPED: "Shipped",
  IN_TRANSIT: "In transit", ARRIVED: "Arrived",
  UNDER_CLEARING: "Clearing", CLEARED: "Cleared" };
const PAY_TONE = { ok: "#1a7f37", due: "#b35900", part: "#1a6091",
                   none: "#8a97a1" };

export default function ImportOrders({ me, onOpenIpr }) {
  const [rows, setRows] = useState(null);
  const [tiles, setTiles] = useState(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");

  const load = () => api("/ipr").then((d) => {
    setRows(d.rows || d); setTiles(d.tiles || null);
  }).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const canCreate = ["HO_PURCHASING", "ADMIN"].includes(me.role);

  if (adding) {
    return <IprForm me={me} onCancel={() => setAdding(false)}
                    onSaved={(ref) => { setAdding(false); onOpenIpr(ref); }} />;
  }

  const shown = (rows || []).filter((r) => {
    const needle = q.trim().toLowerCase();
    return !needle || r.ref.toLowerCase().includes(needle)
      || r.supplier.toLowerCase().includes(needle)
      || (r.projects || []).some((p) => p.toLowerCase().includes(needle));
  });

  const tile = (label, n, hot) => (
    <div key={label} style={{ border: "1px solid var(--sp-border, #dde5ea)",
      borderRadius: 8, padding: "8px 14px", minWidth: 108,
      background: hot && n > 0 ? "#fdf6ec" : "#fafcfd" }}>
      <div style={{ fontSize: 21, fontWeight: 700,
        color: hot && n > 0 ? "#b35900" : "var(--sp-navy)" }}>{n}</div>
      <div style={{ fontSize: 11, color: "#5a6b78" }}>{label}</div>
    </div>
  );

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          🌍 International Orders (IPR)</h2>
        {canCreate && (
          <Btn onClick={() => setAdding(true)}>+ New order</Btn>
        )}
        <input placeholder="Search ref / supplier / project…" value={q}
               onChange={(e) => setQ(e.target.value)}
               style={{ ...inputStyle, width: 240, marginLeft: "auto" }} />
      </div>
      {tiles && (
        <div style={{ display: "flex", gap: 8, marginTop: 12,
                      flexWrap: "wrap" }}>
          {tile("draft", tiles.draft, false)}
          {tile("awaiting award", tiles.awaiting_award, true)}
          {tile("awaiting signatory", tiles.awaiting_authorisation, true)}
          {tile("active orders", tiles.active, false)}
          {tile("payments open", tiles.payments_open, true)}
          {tile("cargo moving", tiles.cargo_moving, false)}
          {tile("cargo at port", tiles.cargo_at_port, true)}
        </div>
      )}
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12,
                      fontSize: 13 }}>
        <thead><tr>
          <th style={th}>Ref</th><th style={th}>Supplier</th>
          <th style={th}>For</th>
          <th style={th}>Date</th>
          <th style={{ ...th, textAlign: "right" }}>Order value</th>
          <th style={th}>Payment</th>
          <th style={th}>Shipping</th>
          <th style={th}>Status</th>
        </tr></thead>
        <tbody>
          {shown.map((r) => (
            <tr key={r.ref} style={r.is_void ? { opacity: 0.55 } : undefined}>
              <td style={{ ...td, whiteSpace: "nowrap" }}>
                <a href="#" onClick={(e) => { e.preventDefault();
                                              onOpenIpr(r.ref); }}
                   style={{ color: "var(--sp-navy)", fontWeight: 600 }}>
                  {r.ref}</a>
              </td>
              <td style={td}>{r.supplier}</td>
              <td style={{ ...td, fontSize: 12 }}>
                {(r.projects || []).join(", ") || "—"}</td>
              <td style={{ ...td, whiteSpace: "nowrap" }}>{r.doc_date}</td>
              <td style={{ ...td, textAlign: "right", whiteSpace: "nowrap" }}>
                {r.currency} {money(r.order_total)}
                <div style={{ fontSize: 11, color: "#5a6b78" }}>
                  MVR {money(r.mvr_total)}</div>
              </td>
              <td style={{ ...td, fontSize: 12 }}>
                {r.payment ? (<>
                  <span style={{ color: PAY_TONE[r.payment.tone] || "#5a6b78",
                                 fontWeight: r.payment.tone === "due"
                                   ? 600 : 400 }}>
                    {r.payment.label}</span>
                  {r.payment.paid != null && r.payment.total > 0
                    && r.payment.tone !== "none" && (
                    <div style={{ fontSize: 11, color: "#5a6b78" }}>
                      {money(r.payment.paid)} / {money(r.payment.total)} paid
                    </div>)}
                </>) : "—"}
              </td>
              <td style={{ ...td, fontSize: 12, whiteSpace: "nowrap" }}>
                {r.shipping ? (<>
                  {r.shipping.mode === "AIR" ? "✈" : "🚢"}{" "}
                  {SHIP_WORD[r.shipping.status] || r.shipping.status}
                  {r.shipping.count > 1 ? ` ·${r.shipping.count}×` : ""}
                  {(r.shipping.live || r.shipping.eta) && (
                    <div style={{ fontSize: 11, color: "#5a6b78" }}>
                      {r.shipping.live
                        ? r.shipping.live.replace(/_/g, " ").toLowerCase()
                        : ""}
                      {r.shipping.eta ? ` · ETA ${r.shipping.eta}` : ""}
                    </div>)}
                </>) : <span style={{ color: "#8a97a1" }}>—</span>}
              </td>
              <td style={td}>
                <StatusChip status={r.is_void ? "VOID" : r.status} /></td>
            </tr>
          ))}
          {rows && shown.length === 0 && (
            <tr><td colSpan={8} style={{ ...td, textAlign: "center",
                                         color: "var(--muted)" }}>
              {q ? "Nothing matches the search."
                 : "No orders yet. Raise one from a sized-and-released PMR."}
            </td></tr>
          )}
        </tbody>
      </table>
      </div>
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
    misc_fee: o.misc_fee ?? "",
  } : { supplier_id: "", order_currency: "USD",
    exchange_rate: "", incoterm: "", loading_port: "", discharge_port: "",
    pi_ref: "", notes: "", discount: "", freight_handling: "", misc_fee: "" });
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
    + num(hdr.freight_handling) + num(hdr.misc_fee);
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
            {/* The description gets the whole first row — supplier item names
                ("DSW 6314FLW Exquisite Light - HPL SIZE: 3050 x 1320 x
                0.8mm") were unreadable squeezed beside four number fields
                (owner 2026-08-25). */}
            <input list="ipr-items" placeholder="Search catalog / describe"
                   title={l._itemText ?? (l.item_id
                     ? itemLabel(items.find((it) => it.id === l.item_id))
                     : l.free_text_desc)}
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
                   style={{ ...inputStyle, width: "100%",
                            boxSizing: "border-box", marginBottom: 6 }} />
            <div style={{ display: "grid",
              gridTemplateColumns: "0.8fr 1fr 1fr 1.6fr 30px", gap: 6,
              alignItems: "center" }}>
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
        <label style={{ fontSize: 13, alignSelf: "center" }}>
          Miscellaneous fee ({hdr.order_currency})
          <div style={{ fontSize: 10.5, color: "#8a97a1" }}>
            e.g. documentation — unrelated to shipping</div></label>
        <input type="number" value={hdr.misc_fee} placeholder="0"
               onChange={(e) => setH("misc_fee", e.target.value)}
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

export function IprView({ me, refIpr, onClose, onOpenIrn, onEdit,
                          onOpenDoc, focusShipment }) {
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
  // A voided order keeps its number and stays readable, but nothing on it
  // may move — no workflow buttons, and the chip says VOID, not the status
  // it died in.
  const actions = doc.is_void ? [] : ACTIONS.filter(([, , st, roles]) =>
    st.includes(doc.status) && roles.includes(me.role));

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
          {doc.ref} <StatusChip status={doc.is_void ? "VOID" : doc.status} />
        </h2>
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
              if (prompt) {
                const c = window.prompt(
                  `${prompt === "reason" ? "Reason" : "Comment"} (required):`);
                if (c) act(action, { comment: c, reason: c });
              } else act(action);
            }}>{label}</button>
        ))}
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      {doc.is_void && (
        <p style={{ background: "#fdecea", border: "1px solid #f2b8b5",
                    borderRadius: 6, padding: "8px 12px", fontSize: 13,
                    color: "#8a1f1a" }}>
          This order was <strong>voided</strong>
          {doc.void_reason ? <> — {doc.void_reason}</> : null}. It is kept
          for the record only; nothing on it can be actioned.
        </p>
      )}
      {doc.status === "APPROVED" && !doc.is_void && (
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
            {(Number(o.discount) > 0 || Number(o.freight_handling) > 0
              || Number(o.misc_fee) > 0) && (
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
                {Number(o.misc_fee) > 0 && (
                  <tr>
                    <td colSpan={4} style={{ ...td, textAlign: "right",
                                             color: "#5a6b78" }}>
                      Miscellaneous fee</td>
                    <td style={{ ...td, textAlign: "right" }}>
                      + {o.order_currency} {money(o.misc_fee)}</td>
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

      <ChargeCorrectionPanel doc={doc} refIpr={refIpr} onChanged={load}
                             onError={setError} />
      <MilestonePanel doc={doc} me={me} refIpr={refIpr} onChanged={load}
                      onError={setError} />
      <ShipmentsPanel doc={doc} refIpr={refIpr} onChanged={load}
                      onError={setError} onOpenIrn={onOpenIrn}
                      onOpenDoc={onOpenDoc} focusSeq={focusShipment}
                      isAdmin={me.role === "ADMIN"} />
    </section>
  );
}

// Commercial-charge correction on an authorised order (owner 2026-08-10): the
// PI's discount / freight / misc was entered wrong and the order is already
// in flight (shipment booked, part paid). Purchasing proposes the corrected
// charges with a reason; the Director approves, a signatory authorises — the
// committed total, ledger and PO move while paid milestones stay untouched.
function ChargeCorrectionPanel({ doc, refIpr, onChanged, onError }) {
  const o = doc.order;
  const corr = doc.charge_correction;
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ discount: "", freight_handling: "",
                               misc_fee: "", reason: "" });
  const [foldIds, setFoldIds] = useState([]);
  const [dropIds, setDropIds] = useState([]);
  if (!corr && !doc.can_correct) return null;

  async function propose() {
    onError(null);
    try {
      await api(`/ipr/${refIpr}/correct-charges`,
                { method: "POST", body: { ...f, fold_line_ids: foldIds,
                                          drop_line_ids: dropIds } });
      setOpen(false); onChanged();
    } catch (e) { onError(e.message); }
  }
  // Two intents, and the difference is the whole point: FOLD moves the
  // line's value into supplier freight (total unchanged); REMOVE takes the
  // item off the order (total falls, the unpaid milestones absorb it). The
  // form used to offer only the fold, worded for freight, so a last-minute
  // deletion had nowhere to go (owner 2026-09-02, IPR-017).
  function setIntent(line, intent) {
    const wasFold = foldIds.includes(line.id);
    const delta = Number(line.line_value) || 0;
    const cur = Number(f.freight_handling) || 0;
    setFoldIds(intent === "fold" ? [...foldIds, line.id]
                                 : foldIds.filter((i) => i !== line.id));
    setDropIds(intent === "drop" ? [...dropIds, line.id]
                                 : dropIds.filter((i) => i !== line.id));
    // Folding seeds the freight box with the line's value, so the usual case
    // (freight typed as a line) is one click. Removing must not.
    if (intent === "fold" && !wasFold) {
      setF({ ...f, freight_handling: String(cur + delta) });
    } else if (wasFold && intent !== "fold") {
      setF({ ...f, freight_handling: String(cur - delta) });
    }
  }
  async function decide(action) {
    let reason = "";
    if (action === "reject") {
      reason = window.prompt("Reason for rejecting the correction:") || "";
      if (!reason) return;
    }
    onError(null);
    try {
      await api(`/ipr/${refIpr}/correct-charges/decide`,
                { method: "POST", body: { action, reason } });
      onChanged();
    } catch (e) { onError(e.message); }
  }

  if (corr) {
    const stage = corr.status === "PENDING_DIRECTOR"
      ? "awaiting the Director" : "awaiting a Signatory";
    return (
      <div style={{ border: "1px solid #e0c66b", background: "#fdf8e7",
                    borderRadius: 8, padding: "8px 12px", margin: "10px 0",
                    fontSize: 13 }}>
        <strong style={{ color: "#8a6d00" }}>
          Charge correction {stage}</strong>{" — "}
        discount {o.order_currency} {money(corr.discount || 0)} · freight{" "}
        {o.order_currency} {money(corr.freight_handling || 0)} · misc{" "}
        {o.order_currency} {money(corr.misc_fee || 0)}
        {corr.fold_lines?.length > 0 && (
          <div style={{ color: "#8a6d00", marginTop: 2 }}>
            Folds into supplier freight:{" "}
            {corr.fold_lines.map((l) => l.description).join(" · ")}</div>
        )}
        {corr.drop_lines?.length > 0 && (
          <div style={{ color: "#8a6d00", marginTop: 2 }}>
            <strong>Removes from the order:</strong>{" "}
            {corr.drop_lines.map((l) => l.description).join(" · ")}</div>
        )}
        {/* The approver is authorising a new committed total and a new
            schedule. Show them both rather than the inputs (owner
            2026-09-02). */}
        {corr.effect && Number(corr.effect.delta) !== 0 && (
          <div style={{ marginTop: 6, paddingTop: 6,
                        borderTop: "1px solid #e8dcae" }}>
            <div>
              Order total {corr.effect.currency}{" "}
              {money(corr.effect.old_total)} →{" "}
              <strong>{money(corr.effect.new_total)}</strong>{" "}
              <span style={{ color: Number(corr.effect.delta) < 0
                ? "#a3271b" : "#1a7f37" }}>
                ({Number(corr.effect.delta) > 0 ? "+" : ""}
                {money(corr.effect.delta)})</span>
            </div>
            {corr.effect.milestones?.length > 0 ? (
              <div style={{ marginTop: 2 }}>
                Payment schedule re-adjusts:{" "}
                {corr.effect.milestones.map((m) => (
                  <span key={m.label} style={{ marginRight: 10 }}>
                    {m.label} {money(m.from)} →{" "}
                    <strong>{money(m.to)}</strong></span>
                ))}
              </div>
            ) : (
              <div style={{ marginTop: 2, color: "#5a6b78" }}>
                No milestone moves — nothing unpaid is left to absorb it.</div>
            )}
            <div style={{ marginTop: 2, color: "#5a6b78" }}>
              Already paid or vouchered: {corr.effect.currency}{" "}
              {money(corr.effect.settled)} — untouched.</div>
          </div>
        )}
        <div style={{ color: "#5a6b78", marginTop: 2 }}>
          {corr.reason} — {corr.created_by}</div>
        {doc.can_decide_correction && (
          <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
            <button style={buttonStyle} onClick={() => decide("approve")}>
              {corr.status === "PENDING_DIRECTOR"
                ? "Approve correction" : "Authorise corrected total"}</button>
            <button style={ghostButton} onClick={() => decide("reject")}>
              Reject</button>
          </div>
        )}
      </div>
    );
  }
  if (!open) return (
    <p style={{ margin: "8px 0", fontSize: 12.5 }}>
      <button style={ghostButton}
        onClick={() => { setF({ discount: o.discount ?? "",
          freight_handling: o.freight_handling ?? "",
          misc_fee: o.misc_fee ?? "", reason: "" }); setOpen(true); }}>
        Correct order…</button>
      <span style={{ color: "#8a97a1", marginLeft: 8 }}>
        remove an item, or fix discount / freight / misc after authorisation
      </span>
    </p>
  );
  return (
    <div style={{ border: "1px solid var(--sp-border)", borderRadius: 8,
                  padding: 10, margin: "10px 0" }}>
      <strong style={{ fontSize: 13, color: "var(--sp-navy)" }}>
        Correct the authorised order</strong>
      <p style={{ fontSize: 12, color: "#5a6b78", margin: "4px 0 8px" }}>
        Routed to the Director, then a Signatory who authorises the new
        committed total. The payment schedule re-adjusts with it — paid and
        vouchered milestones stay exactly as they are.</p>
      <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
        {[["discount", "Discount"], ["freight_handling", "Freight / handling"],
          ["misc_fee", "Miscellaneous fee"]].map(([k, label]) => (
          <label key={k} style={{ fontSize: 11, color: "#5a6b78" }}>
            {label} ({o.order_currency})
            <input type="number" value={f[k]} placeholder="0"
              style={inputStyle}
              onChange={(e) => setF({ ...f, [k]: e.target.value })} />
          </label>
        ))}
      </div>
      {o.lines.filter((l) => Number(l.line_value) > 0).length > 1 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 11, color: "#5a6b78", marginBottom: 4 }}>
            Taking a line off the order. Either way it is zeroed and comes off
            the shipment manifest — the difference is what happens to the
            money:
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 12.5 }}>
            <thead>
              <tr style={{ fontSize: 10.5, color: "#5a6b78",
                           textAlign: "left" }}>
                <th style={{ fontWeight: 500 }}>Line</th>
                <th style={{ fontWeight: 500, width: 62, textAlign: "center" }}>
                  Keep</th>
                <th style={{ fontWeight: 500, width: 108, textAlign: "center" }}
                    title="Value moves into supplier freight — order total
                           unchanged">
                  Fold&nbsp;to&nbsp;freight</th>
                <th style={{ fontWeight: 500, width: 92, textAlign: "center" }}
                    title="Item comes off the order — total falls and the
                           unpaid milestones absorb it">
                  Remove</th>
              </tr>
            </thead>
            <tbody>
              {o.lines.filter((l) => Number(l.line_value) > 0).map((l) => {
                const intent = foldIds.includes(l.id) ? "fold"
                  : dropIds.includes(l.id) ? "drop" : "keep";
                return (
                  <tr key={l.id}>
                    <td style={{ padding: "2px 0" }}>
                      {l.description}{" "}
                      <span style={{ color: "#8a97a1" }}>
                        {o.order_currency} {money(l.line_value)}</span>
                    </td>
                    {["keep", "fold", "drop"].map((v) => (
                      <td key={v} style={{ textAlign: "center" }}>
                        <input type="radio" name={`intent-${l.id}`}
                               checked={intent === v}
                               onChange={() => setIntent(l, v)} />
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {dropIds.length > 0 && (
            <div style={{ fontSize: 11.5, color: "#8a6d00", marginTop: 5 }}>
              Removing brings the order total down. Milestones already paid or
              on a voucher are untouched; the unpaid ones re-adjust to the new
              total, and you will see exactly how before anyone authorises it.
            </div>
          )}
        </div>
      )}
      <input placeholder="Reason (e.g. the PI includes freight)"
        value={f.reason} style={{ ...inputStyle, width: "100%", marginTop: 8 }}
        onChange={(e) => setF({ ...f, reason: e.target.value })} />
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <button style={buttonStyle} onClick={propose}>
          Submit for approval</button>
        <button style={ghostButton} onClick={() => setOpen(false)}>
          Cancel</button>
      </div>
    </div>
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
  // health-only states (state stays ACTIVE, but the provider isn't delivering)
  UNTRACKED: { bg: "#fbeae8", fg: "#b0402f", label: "Not trackable" },
  STALE: { bg: "#fdf3e7", fg: "#8a5a00", label: "No recent movement" },
};
const MILE_LABEL = { DEPARTED: "Departed origin",
  TRANSSHIPMENT: "Transshipment", ARRIVED: "Arrived Malé",
  ETA_UPDATED: "ETA updated", OTHER: "Update" };

// The full provider movement list (ShipsGo-style) — move · location · vessel ·
// date, actual (green) vs estimated. Shared by the IPR panel + health list.
export function MovementsTable({ movements }) {
  if (!movements || movements.length === 0) return null;
  const hc = { padding: "0 10px 4px 0", fontWeight: 500 };
  return (
    <div style={{ marginTop: 8, maxHeight: 240, overflowY: "auto",
      overflowX: "auto" }}>
      <table style={{ borderCollapse: "collapse", fontSize: 11.5,
        width: "100%" }}>
        <thead><tr style={{ color: "#8a97a1", textAlign: "left" }}>
          <th style={{ ...hc, paddingLeft: 16 }}>Move</th>
          <th style={hc}>Location</th><th style={hc}>Vessel</th>
          <th style={hc}>Date</th>
        </tr></thead>
        <tbody>
          {movements.map((m, i) => (
            <tr key={i} style={{ color: "#41505c" }}>
              <td style={{ padding: "2px 8px 2px 0", whiteSpace: "nowrap",
                fontWeight: m.is_milestone ? 600 : 400 }}>
                <span style={{ marginRight: 6, color: m.is_actual
                  ? "#1f7a3d" : "#c4ccd2" }}>●</span>{m.label}</td>
              <td style={{ padding: "2px 10px 2px 0" }}>{m.location}</td>
              <td style={{ padding: "2px 10px 2px 0", color: "#5a6b78" }}>
                {m.vessel_flight || "—"}</td>
              <td style={{ padding: "2px 10px 2px 0", color: "#5a6b78",
                whiteSpace: "nowrap" }}>
                {m.event_time ? m.event_time.slice(0, 10) : "—"}
                {!m.is_actual && <span style={{ color: "#8a97a1" }}>
                  {" "}· est.</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TrackingBlock({ s, canManage, onChanged, onError }) {
  const t = s.tracking;
  const [logging, setLogging] = useState(false);
  const [ev, setEv] = useState({ code: "DEPARTED", description: "",
    location: "" });
  if (!t) return null;
  const st = TRACK_STATE_STYLE[t.health] || TRACK_STATE_STYLE[t.state]
    || TRACK_STATE_STYLE.MANUAL;

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
          style={{ fontSize: 12, color: "var(--sp-navy)", fontWeight: 600 }}>
          📍 Live position ↗</a>)}
        {canManage && ["FAILED", "PENDING_REGISTRATION", "UNTRACKED",
          "STALE"].includes(t.health) && (
          <button style={{ ...ghostButton, padding: "2px 10px" }}
            onClick={() => post("retry", {})}>Retry</button>)}
        {canManage && t.state !== "MANUAL" && t.state !== "ARRIVED" && (
          <button style={{ ...ghostButton, padding: "2px 10px" }}
            onClick={() => post("manual", { action: "switch" })}>
            Switch to manual</button>)}
      </div>
      <div style={{ fontSize: 11, color: "#8a97a1", marginTop: 3,
        display: "flex", gap: 10, flexWrap: "wrap" }}>
        <span>{t.mode === "AIR" ? "AWB" : "Carrier"}:{" "}
          {t.carrier_scac || (t.mode === "AIR" ? "—" : "auto-detect")}</span>
        {t.tracking_key && <span>Key: {t.tracking_key}</span>}
        {t.raw_status && <span>Provider: {t.raw_status}</span>}
        {t.registered_at && <span>Registered {t.registered_at.slice(0, 10)}</span>}
        {t.last_polled_at && <span>Checked {t.last_polled_at.slice(0, 10)}</span>}
        {t.register_attempts > 1 && <span>{t.register_attempts} attempts</span>}
      </div>
      {t.reason && ["FAILED", "STALE", "UNTRACKED",
        "PENDING_REGISTRATION"].includes(t.health) && (
        <div style={{ fontSize: 11.5, color: HEALTH_TONE[t.health] || "#b0402f",
          marginTop: 4 }}>⚠ {t.reason}</div>)}
      <MovementsTable movements={t.movements} />
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
                          onOpenDoc, isAdmin, focusSeq }) {
  const ships = doc.shipments || [];
  const canManage = doc.can_manage;
  const [adding, setAdding] = useState(false);
  const blankF = { mode: "SEA", forwarder_id: "", vessel_flight: "",
    carrier_scac: "", bl_no: "", container_awb: "", etd: "", eta: "",
    tracking_ref: "" };
  const [f, setF] = useState(blankF);
  const [split, setSplit] = useState(false);
  const [alloc, setAlloc] = useState([]);
  const [carriers, setCarriers] = useState([]);
  const [carrierMeta, setCarrierMeta] = useState(null);
  const [forwarders, setForwarders] = useState([]);
  const [agents, setAgents] = useState([]);

  useEffect(() => {
    Promise.all([
      api("/suppliers?category=FORWARDER").catch(() => []),
      api("/suppliers?category=CLEARING_AGENT").catch(() => []),
    ]).then(([fw, cl]) => {
      setForwarders(fw || []);
      setAgents([...(fw || []), ...(cl || [])]);
    });
  }, []);

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
                  onOpenIrn={onOpenIrn} isAdmin={isAdmin}
                  forwarders={forwarders} agents={agents}
                  onOpenDoc={onOpenDoc}
                  focused={focusSeq != null
                           && String(focusSeq) === String(s.seq)}
                  supplierChargesFreight={doc.supplier_charges_freight} />
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
            <select value={f.forwarder_id || ""} style={inputStyle}
                    onChange={(e) => setF({ ...f,
                      forwarder_id: e.target.value })}>
              <option value="">Forwarder (agent)…</option>
              {forwarders.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>))}
            </select>
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
                    onOpenIrn, isAdmin, forwarders = [], agents = [],
                    onOpenDoc, supplierChargesFreight, focused }) {
  const fileRef = useRef(null);
  const [docType, setDocType] = useState("BL_AWB");
  // Landed here from the Cargo Clearance board — bring this shipment's
  // card to the user instead of the top of the order (owner 2026-08-26).
  const cardRef = useRef(null);
  useEffect(() => {
    if (!focused) return;
    // Instant, and re-asserted twice: late-rendering content above the card
    // (images, tracking) shifts the layout after the first scroll and left
    // long orders (IPR-020) sitting back at the top.
    const go = () => cardRef.current
      && cardRef.current.scrollIntoView({ block: "start" });
    go();
    const t1 = setTimeout(go, 350);
    const t2 = setTimeout(go, 1000);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [focused]);
  const [charges, setCharges] = useState(Object.fromEntries(
    CHARGE_LABELS.map(([k]) => [k, s[k] ?? ""])));
  const [editing, setEditing] = useState(false);
  const [ef, setEf] = useState(null);
  const [carriers, setCarriers] = useState([]);
  const [carrierMeta, setCarrierMeta] = useState(null);
  const at = SHIP_STEPS.indexOf(s.status);
  const arrived = at >= SHIP_STEPS.indexOf("ARRIVED");

  function startEdit() {
    setEf({ mode: s.mode, forwarder_id: s.forwarder || "",
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
    <div ref={cardRef}
         style={{ border: focused ? "2px solid var(--sp-navy)"
                                  : "1px solid var(--sp-border)",
                  borderRadius: 8, padding: 10, marginBottom: 10,
                  boxShadow: focused ? "0 0 0 3px #dcebf7" : undefined,
                  scrollMarginTop: 12 }}>
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
            <select value={ef.forwarder_id || ""} style={inputStyle}
                    onChange={(e) => setEf({ ...ef,
                      forwarder_id: e.target.value })}>
              <option value="">Forwarder (agent)…</option>
              {forwarders.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>))}
            </select>
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
      {/* CLEARED is the end of the status chain, but not of the work —
          the Receive button must survive it (owner 2026-08-27). */}
      {canManage && (s.next_statuses.length > 0 || arrived) && (
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
                    title="Emails every uploaded shipping document to the company's clearing agent"
                    onClick={() => window.confirm(
                        "Email all uploaded shipping documents to the "
                        + "clearing agent?")
                      && call(`/shipments/${s.id}/share`, {})}>
              Share with clearing agent</button>
          )}
          {s.shared_with_agent_at && (
            <span style={{ fontSize: 11.5, color: "#1a7f37" }}>
              ✓ emailed to agent{" "}
              {new Date(s.shared_with_agent_at).toLocaleDateString("en-GB")}
              <button style={{ ...ghostButton, padding: "1px 8px",
                               fontSize: 11, marginLeft: 6 }}
                      title="Email the documents again — e.g. after uploading more"
                      onClick={() => window.confirm(
                          "Email all uploaded shipping documents to the "
                          + "clearing agent again?")
                        && call(`/shipments/${s.id}/share`, {})}>
                send again</button>
            </span>
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
              (DOC_TYPES.find((t) => t[0] === m) || ["", m])[1]).join(", ")})</span>
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

      {/* import charge payments (forwarder / DO / port / duty) */}
      {(canManage || (s.payments || []).length > 0) && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11.5, color: "#5a6b78", marginBottom: 4 }}>
            Import charges — paid to the agent or direct to port / customs,
            capitalized into landed cost</div>
          <ChargePayments s={s} refIpr={refIpr} canManage={canManage}
                          onChanged={onChanged} onError={onError}
                          agents={agents} onOpenDoc={onOpenDoc}
                          supplierChargesFreight={supplierChargesFreight} />
          <span style={{ fontSize: 12.5, fontWeight: 600,
                         color: "var(--sp-navy)" }}>
            Landed-cost charges: MVR {money(s.clearing_total)}</span>
        </div>
      )}
    </div>
  );
}

const CHARGE_KINDS = [
  ["FREIGHT", "Forwarding agent freight"],
  ["DO", "Delivery-order charges"],
  ["PORT", "Port charges"],
  ["DUTY", "Import duty"],
];

function ChargePayments({ s, refIpr, canManage, onChanged, onError, agents = [],
                          onOpenDoc, supplierChargesFreight }) {
  // A kind can carry several charges. A port bills a container more than
  // once — handling, then shifting, then demurrage while it sits — and each
  // invoice needs its own payment (owner 2026-08-30).
  const [extra, setExtra] = useState({});      // kind -> show a blank row
  const all = s.payments || [];
  return (
    <div style={{ marginBottom: 6 }}>
      {CHARGE_KINDS.map(([kind, label]) => {
        if (kind === "FREIGHT" && supplierChargesFreight) {
          return (
            <div key={kind} style={{ fontSize: 12, color: "#8a97a3",
                                     padding: "3px 0" }}>
              {label}: n/a — the supplier charges freight on the order</div>
          );
        }
        const rows = all.filter((p) => p.kind === kind);
        const blank = rows.length === 0 || extra[kind];
        return (
          <Fragment key={kind}>
            {rows.map((p, i) => (
              <ChargeRow key={p.id} kind={kind}
                         label={rows.length > 1
                           ? `${label} — ${p.display_label || `#${i + 1}`}`
                           : label}
                         p={p} s={s} refIpr={refIpr}
                         canManage={canManage} onChanged={onChanged}
                         onError={onError} agents={agents}
                         onOpenDoc={onOpenDoc} />
            ))}
            {blank && (
              <ChargeRow key={`${kind}-new`} kind={kind}
                         label={rows.length ? `${label} — another` : label}
                         p={undefined} isNew={rows.length > 0} s={s}
                         refIpr={refIpr} canManage={canManage}
                         onChanged={() => { setExtra((x) => ({ ...x,
                                              [kind]: false })); onChanged(); }}
                         onError={onError} agents={agents}
                         onOpenDoc={onOpenDoc} />
            )}
            {canManage && rows.length > 0 && !extra[kind] && (
              <button onClick={() => setExtra((x) => ({ ...x, [kind]: true }))}
                      style={{ background: "transparent", border: "none",
                               color: "var(--navy)", cursor: "pointer",
                               fontSize: 12, padding: "2px 0 8px",
                               fontFamily: "inherit" }}>
                + another {label.toLowerCase()} (shifting, demurrage…)
              </button>
            )}
          </Fragment>
        );
      })}
    </div>
  );
}

// Port dues go to the port and duty to customs — not to the shipment's
// agents, who may not even be on file (owner 2026-08-24, IPR-020). Each
// charge offers its direct payee alongside the agents, plus a typed name.
const DIRECT_PAYEES = {
  PORT: ["Maldives Ports Limited"],
  DUTY: ["Maldives Customs Service"],
};

function ChargeRow({ kind, label, p, s, refIpr, canManage, onChanged,
                    onError, agents = [], onOpenDoc, isNew = false }) {
  // Forwarder freight is always paid to the shipment's forwarder — no picker.
  const freightToForwarder = kind === "FREIGHT" && !!s.forwarder;
  const directs = DIRECT_PAYEES[kind] || [];
  const [payeeId, setPayeeId] = useState(p?.payee || "");
  const [payeeName, setPayeeName] = useState(p?.payee_name || "");
  const preset = payeeId ? `id:${payeeId}`
    : payeeName && directs.includes(payeeName) ? `name:${payeeName}`
    : payeeName ? "other" : "";
  const [choice, setChoice] = useState(preset);
  const [amount, setAmount] = useState(p?.amount ?? "");
  const [currency, setCurrency] = useState(p?.currency || "MVR");
  const [invRef, setInvRef] = useState(p?.invoice_ref || "");
  const [chargeLabel, setChargeLabel] = useState(p?.label || "");
  const [file, setFile] = useState(null);
  const fileRef = useRef(null);
  const raised = !!p?.pyr_ref;

  async function save() {
    onError(null);
    const fd = new FormData();
    // Freight-to-forwarder needs no payee (the server uses the forwarder).
    if (!freightToForwarder) {
      if (payeeId) fd.append("payee_id", payeeId);
      else fd.append("payee_name", payeeName || "");
    }
    fd.append("amount", amount);
    fd.append("currency", currency); fd.append("invoice_ref", invRef);
    fd.append("label", chargeLabel);
    // Say which charge. Without an id the server edits the open one, and a
    // blank "another" row must start a fresh one rather than overwrite it.
    if (p?.id) fd.append("charge_id", p.id);
    else if (isNew) fd.append("new", "1");
    if (file) fd.append("invoice", file);
    try {
      await apiUpload(`/ipr/${refIpr}/shipments/${s.id}/payments/${kind}`, fd);
      setFile(null); onChanged();
    } catch (e) { onError(e.message); }
  }
  async function raise() {
    onError(null);
    try {
      await api(`/ipr/${refIpr}/shipments/${s.id}/payments/${kind}/raise`,
                { method: "POST", body: p?.id ? { charge_id: p.id } : {} });
      onChanged();
    } catch (e) { onError(e.message); }
  }

  return (
    <div style={{ border: "1px solid #e6ebf0", borderRadius: 6,
                  padding: "5px 8px", marginBottom: 4 }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center",
                    flexWrap: "wrap" }}>
        <span style={{ fontSize: 12, fontWeight: 600, width: 160,
                       color: "var(--sp-navy)" }}>{label}</span>
        {raised ? (
          <>
            <span style={{ fontSize: 12.5 }}>{p.payee_display} · {p.currency}
              {" "}{money(p.amount)}</span>
            {p.invoice_url && (
              <a href={p.invoice_url} target="_blank" rel="noreferrer"
                 style={{ fontSize: 12 }}>📎 invoice</a>)}
            <span style={{ fontSize: 12, marginLeft: "auto" }}>
              {onOpenDoc ? (
                <a href="#" onClick={(e) => { e.preventDefault();
                                              onOpenDoc(p.pyr_ref); }}
                   style={{ color: "var(--sp-navy)", fontWeight: 600 }}>
                  PYR {p.pyr_ref}</a>
              ) : <b>PYR {p.pyr_ref}</b>}
              {" "}· {String(p.pyr_status).replace(/_/g, " ")}</span>
          </>
        ) : (
          <>
            {freightToForwarder ? (
              <span style={{ fontSize: 12, color: "#5a6b78", width: 150 }}>
                → {s.forwarder_display}</span>
            ) : (<>
              <select value={choice} disabled={!canManage}
                      style={{ ...inputStyle, width: 170 }}
                      onChange={(e) => {
                        const v = e.target.value;
                        setChoice(v);
                        if (v.startsWith("id:")) {
                          setPayeeId(v.slice(3)); setPayeeName("");
                        } else if (v.startsWith("name:")) {
                          setPayeeId(""); setPayeeName(v.slice(5));
                        } else {
                          setPayeeId(""); setPayeeName(v === "other"
                            ? payeeName : "");
                        }
                      }}>
                <option value="">Paid to…</option>
                {directs.map((n) => (
                  <option key={n} value={`name:${n}`}>{n} (direct)</option>))}
                {agents.map((a) => (
                  <option key={a.id} value={`id:${a.id}`}>
                    {a.name} (agent)</option>))}
                <option value="other">Other — type a name…</option>
              </select>
              {choice === "other" && (
                <input placeholder="Payee name" value={payeeName}
                       disabled={!canManage}
                       style={{ ...inputStyle, width: 150 }}
                       onChange={(e) => setPayeeName(e.target.value)} />
              )}
            </>)}
            <input type="number" placeholder="Amount" value={amount}
                   disabled={!canManage} style={{ ...inputStyle, width: 90 }}
                   onChange={(e) => setAmount(e.target.value)} />
            <select value={currency} disabled={!canManage}
                    style={{ ...inputStyle, width: 68 }}
                    onChange={(e) => setCurrency(e.target.value)}>
              <option>MVR</option><option>USD</option></select>
            <input placeholder="Inv #" value={invRef} disabled={!canManage}
                   style={{ ...inputStyle, width: 80 }}
                   onChange={(e) => setInvRef(e.target.value)} />
            {/* What this particular invoice is for, when a kind is billed
                more than once. */}
            <input placeholder="what for?" value={chargeLabel}
                   disabled={!canManage}
                   title="Container shifting, demurrage, storage…"
                   style={{ ...inputStyle, width: 118 }}
                   onChange={(e) => setChargeLabel(e.target.value)} />
            <input ref={fileRef} type="file" style={{ display: "none" }}
                   onChange={(e) => setFile(e.target.files[0])} />
            {canManage && (
              <button style={{ ...ghostButton, padding: "3px 8px",
                               fontSize: 12 }}
                      onClick={() => fileRef.current?.click()}>
                {file ? `✓ ${file.name.slice(0, 14)}`
                      : p?.invoice_url ? "Replace invoice" : "Attach invoice"}
              </button>)}
            {p?.invoice_url && !file && (
              <a href={p.invoice_url} target="_blank" rel="noreferrer"
                 style={{ fontSize: 12 }}>📎</a>)}
            {canManage && (
              <button style={{ ...ghostButton, padding: "3px 8px",
                               fontSize: 12 }} onClick={save}>Save</button>)}
            {canManage && (
              <button style={{ ...buttonStyle, padding: "3px 10px",
                               fontSize: 12 }} onClick={raise}>Raise PYR</button>)}
          </>
        )}
      </div>
    </div>
  );
}

// A single shipment's clearing workspace (owner 2026-08-26) — the clearance
// board opens THIS, not the whole order: same card, own page, with the full
// order one click away.
export function ShipmentView({ me, refIpr, seq, shipmentId, onClose,
                               onOpenIrn, onOpenDoc, onOpenIpr }) {
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState(null);
  const [forwarders, setForwarders] = useState([]);
  const [agents, setAgents] = useState([]);

  const load = () => api(`/ipr/${refIpr}`).then(setDoc)
    .catch((e) => setError(e.message));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [refIpr]);
  useEffect(() => {
    Promise.all([
      api("/suppliers?category=FORWARDER").catch(() => []),
      api("/suppliers?category=CLEARING_AGENT").catch(() => []),
    ]).then(([fw, cl]) => {
      setForwarders(fw || []);
      setAgents([...(fw || []), ...(cl || [])]);
    });
  }, []);

  async function call(path, body) {
    setError(null);
    try { await api(`/ipr/${refIpr}${path}`, { method: "POST", body });
      load(); } catch (e) { setError(e.message); }
  }

  if (!doc) return <section style={card}>{error || "Loading…"}</section>;
  const o = doc.order;
  const s = (doc.shipments || []).find(
    (x) => (shipmentId != null && x.id === shipmentId)
        || (seq != null && String(x.seq) === String(seq)))
    || (doc.shipments || [])[0];

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10,
                    flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
          Clearing — {doc.ref}{s ? ` · Shipment ${s.seq}` : ""}
        </h2>
        {s && <StatusChip status={s.status} />}
        <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          {onOpenIpr && (
            <button onClick={() => onOpenIpr(doc.ref)} style={ghostButton}
                    title="Order details, payment schedule, all shipments">
              Full order ↗</button>
          )}
          <button onClick={onClose} style={ghostButton}>Close</button>
        </span>
      </div>
      <p style={{ color: "#5a6b78", fontSize: 13, margin: "6px 0 12px" }}>
        {o.supplier_name}
        {o.incoterm ? ` · ${o.incoterm}` : ""}
        {o.loading_port ? ` · ${o.loading_port}` : ""}
        {o.discharge_port ? ` → ${o.discharge_port}` : ""}
        {o.pi_ref ? ` · PI ${o.pi_ref}` : ""}
      </p>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      {s ? (
        <Shipment s={s} refIpr={refIpr} canManage={doc.can_manage}
                  call={call} onChanged={load} onError={setError}
                  onOpenIrn={onOpenIrn} isAdmin={me.role === "ADMIN"}
                  forwarders={forwarders} agents={agents}
                  onOpenDoc={onOpenDoc}
                  supplierChargesFreight={doc.supplier_charges_freight} />
      ) : (
        <p style={{ color: "#5a6b78", fontSize: 13 }}>
          No shipments booked on this order yet.</p>
      )}
    </section>
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
  STALE: "#c0392b", UNTRACKED: "#b0402f" };
const HEALTH_LABEL = { PENDING_REGISTRATION: "Registering",
  UNTRACKED: "Untracked", STALE: "Stale", FAILED: "Failed",
  ACTIVE: "Active", ARRIVED: "Arrived", MANUAL: "Manual" };
const ATTENTION = ["FAILED", "STALE", "PENDING_REGISTRATION", "UNTRACKED"];
const dt = (s) => (s ? s.slice(0, 10) : "—");

function TrackingHealth({ canManage }) {
  const [rows, setRows] = useState(null);
  const [channels, setChannels] = useState(null);
  const [busy, setBusy] = useState(null);
  const [open, setOpen] = useState({});
  const load = () => api("/tracking/health")
    .then((d) => { setRows(d.items || []); setChannels(d.channels || null); })
    .catch(() => setRows([]));
  useEffect(() => { load(); }, []);
  async function retry(id) {
    setBusy(id);
    try { await api(`/tracking/shipments/${id}/retry`, { method: "POST" }); }
    catch { /* surfaced by the reason on reload */ }
    finally { setBusy(null); load(); }
  }
  if (!rows || rows.length === 0) return null;
  const attention = rows.filter((r) => ATTENTION.includes(r.health)).length;
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
      {channels && (() => {
        // The tracker once ran for weeks with webhooks dead and the poll
        // frozen, silently — these lines make a dead channel visible.
        const hours = (iso) => iso
          ? (Date.now() - new Date(iso).getTime()) / 36e5 : null;
        const wh = hours(channels.webhook_last_at);
        const pl = hours(channels.poll_last_run);
        const problems = [];
        if (!channels.webhook_secret_set) {
          problems.push("Webhook secret not configured — live updates are "
            + "rejected; set SHIPSGO_WEBHOOK_SECRET on the server.");
        } else if (wh == null) {
          problems.push("No webhook has ever been received — check the "
            + "ShipsGo dashboard webhook URL.");
        } else if (wh > 96) {
          problems.push(`No webhook for ${Math.round(wh / 24)} days — check `
            + "the ShipsGo dashboard.");
        }
        if (pl == null || pl > 30) {
          problems.push(pl == null
            ? "The daily poll has never run — check the server cron."
            : `Daily poll last ran ${Math.round(pl)}h ago — check the `
              + "server cron.");
        }
        return (
          <div style={{ fontSize: 11.5, marginTop: 6,
                        color: problems.length ? "#c0392b" : "#5a6b78" }}>
            {problems.length
              ? problems.map((p, i) => <div key={i}>⚠ {p}</div>)
              : <>Channels OK — webhook {Math.round(wh)}h ago · poll{" "}
                  {Math.round(pl)}h ago</>}
          </div>
        );
      })()}
      <div style={{ overflowX: "auto", marginTop: 8 }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 12.5 }}>
          <thead><tr>
            <th style={th}>Shipment</th><th style={th}>Mode</th>
            <th style={th}>Carrier</th><th style={th}>Key</th>
            <th style={th}>Health</th><th style={th}>Live status</th>
            <th style={th}>ETA</th><th style={th}>Last event</th>
            <th style={th}>Checked</th><th style={th} />
          </tr></thead>
          <tbody>
            {rows.map((r, i) => {
              const needs = ATTENTION.includes(r.health);
              const hasMoves = r.movements && r.movements.length > 0;
              const isOpen = open[i];
              return (
                <Fragment key={i}>
                  <tr>
                    <td style={{ ...td, cursor: hasMoves ? "pointer" : "default",
                      whiteSpace: "nowrap" }}
                      onClick={() => hasMoves
                        && setOpen((o) => ({ ...o, [i]: !isOpen }))}>
                      {hasMoves && <span style={{ color: "#8a97a1",
                        marginRight: 4 }}>{isOpen ? "▾" : "▸"}</span>}
                      <b style={{ color: "var(--sp-navy)" }}>
                        {r.shipment_ref || `S${r.shipment_seq}`}</b>
                      <div style={{ fontSize: 11, color: "#5a6b78",
                                    fontWeight: 400, marginLeft: 14 }}>
                        {(r.orders && r.orders.length
                          ? r.orders : [r.ipr_ref]).join(" + ")}
                        {r.orders && r.orders.length > 1 && (
                          <b style={{ color: "#8a6d00" }}> · consol.</b>)}
                      </div></td>
                    <td style={td}>{r.mode}</td>
                    <td style={td}>{r.carrier_scac
                      || <span style={{ color: "#8a97a1" }}>auto</span>}</td>
                    <td style={{ ...td, fontVariantNumeric: "tabular-nums" }}>
                      {r.tracking_key || "—"}</td>
                    <td style={{ ...td, color: HEALTH_TONE[r.health]
                      || "#41505c", fontWeight: 600 }}>
                      {HEALTH_LABEL[r.health] || r.health}
                      {r.register_attempts > 1
                        ? ` ·${r.register_attempts}×` : ""}</td>
                    <td style={td}>{r.raw_status || "—"}</td>
                    <td style={td}>{dt(r.current_eta)}</td>
                    <td style={td}>{dt(r.last_event_at)}</td>
                    <td style={{ ...td, color: "#8a97a1" }}>
                      {dt(r.last_polled_at)}</td>
                    <td style={td}>{canManage && needs && r.shipment_id && (
                      <button style={{ ...ghostButton, padding: "1px 9px",
                        fontSize: 11.5 }} disabled={busy === r.shipment_id}
                        onClick={() => retry(r.shipment_id)}>
                        {busy === r.shipment_id ? "…" : "Retry"}</button>)}</td>
                  </tr>
                  {needs && r.reason && (
                    <tr>
                      <td /><td colSpan={9} style={{ padding: "0 8px 7px 8px",
                        fontSize: 11.5, color: HEALTH_TONE[r.health]
                        || "#b0402f" }}>↳ {r.reason}</td>
                    </tr>
                  )}
                  {isOpen && hasMoves && (
                    <tr><td /><td colSpan={9} style={{ padding: "0 8px 8px 8px" }}>
                      <MovementsTable movements={r.movements} /></td></tr>
                  )}
                </Fragment>
              );
            })}
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

export function ImportTracker({ me, onOpenIpr, onOpenShipment }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("live");
  useEffect(() => {
    api("/imports/tracker").then(setData).catch((e) => setError(e.message));
  }, []);

  const orders = data?.orders || [];
  const isLive = (o) => !["CLOSED", "CANCELLED", "REJECTED"].includes(o.status)
    && !(o.receipts.length > 0 && o.shipments.every(
      (s) => s.status === "CLEARED"));
  const matches = (o) => {
    const n = q.trim().toLowerCase();
    if (!n) return true;
    return o.ref.toLowerCase().includes(n)
      || o.supplier.toLowerCase().includes(n)
      || (o.pmrs || []).some((p) => p.toLowerCase().includes(n))
      || (o.shipments || []).some((s) => (s.ref || "").toLowerCase()
                                           .includes(n));
  };
  const shown = orders.filter(matches).filter((o) =>
    filter === "all" ? true
    : filter === "live" ? isLive(o)
    : filter === "moving" ? o.shipments.some(
        (s) => ["SHIPPED", "IN_TRANSIT"].includes(s.status))
    : filter === "port" ? o.shipments.some(
        (s) => ["ARRIVED", "UNDER_CLEARING"].includes(s.status))
    : filter === "unshipped" ? o.shipments.length === 0
    : true);

  // The pipeline a PM/purchaser reads left to right.
  const stageOf = (o) => {
    const done = (x) => ({ state: x });
    const anyShip = o.shipments.length > 0;
    const cleared = anyShip && o.shipments.every((s) => s.status === "CLEARED");
    const atPort = o.shipments.some(
      (s) => ["ARRIVED", "UNDER_CLEARING"].includes(s.status));
    const moving = o.shipments.some(
      (s) => ["SHIPPED", "IN_TRANSIT"].includes(s.status));
    return [
      ["Ordered", o.status === "AUTHORISED" || anyShip ? "done" : "now"],
      ["Shipped", moving ? "now" : (atPort || cleared ? "done"
        : anyShip ? "next" : "wait")],
      ["At port", atPort ? "now" : (cleared ? "done" : "wait")],
      ["Cleared", cleared ? "done" : "wait"],
      ["Received", o.receipts.length ? "done" : "wait"],
    ].map(([label, state]) => ({ label, state, ...done(state) }));
  };
  const DOT = { done: "#1a7f37", now: "#b35900", next: "#8fb3c9",
                wait: "#d7e1e8" };

  const chip = (key, label, n) => (
    <button key={key} onClick={() => setFilter(key)}
            style={{ ...(filter === key ? buttonStyle : ghostButton),
                     padding: "4px 12px", fontSize: 12.5 }}>
      {label}{n != null ? ` · ${n}` : ""}</button>
  );

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 18 }}>
          🌍 Import tracker</h2>
        <p style={{ color: "var(--muted)", fontSize: 12.5, margin: "4px 0 0" }}>
          Every overseas order and where it stands — demand (PMR) → order
          (IPR) → shipment → clearance → receipt (IRN) → payments.</p>
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <CarrierAdmin isAdmin={me && me.role === "ADMIN"} />
      <TrackingHealth canManage={me
        && ["HO_PURCHASING", "ADMIN"].includes(me.role)} />

      {data?.awaiting_order?.length > 0 && (
        <section style={card}>
          <h3 style={{ margin: "0 0 8px", fontSize: 14, color: "#b35900" }}>
            Awaiting an order — sized &amp; released demand
            ({data.awaiting_order.length})</h3>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {data.awaiting_order.map((p) => (
              <span key={p.ref} style={{ fontSize: 12.5, padding: "3px 10px",
                border: "1px solid var(--sp-border)", borderRadius: 20 }}>
                {p.ref}{p.project ? ` · ${p.project}` : ""} · {p.status}</span>
            ))}
          </div>
        </section>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center",
                    flexWrap: "wrap" }}>
        {chip("live", "In flight", orders.filter(isLive).length)}
        {chip("moving", "On the water", orders.filter((o) =>
          o.shipments.some((s) => ["SHIPPED", "IN_TRANSIT"]
            .includes(s.status))).length)}
        {chip("port", "At the port", orders.filter((o) =>
          o.shipments.some((s) => ["ARRIVED", "UNDER_CLEARING"]
            .includes(s.status))).length)}
        {chip("unshipped", "Not shipped yet", orders.filter((o) =>
          o.shipments.length === 0).length)}
        {chip("all", "All orders", orders.length)}
        <input placeholder="Search order / supplier / shipment / PMR…"
               value={q} onChange={(e) => setQ(e.target.value)}
               style={{ ...inputStyle, width: 280, marginLeft: "auto" }} />
      </div>

      {!data && <section style={card}>Loading…</section>}
      {data && shown.length === 0 && (
        <section style={card}>
          <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>
            Nothing here — try another filter or clear the search.</p>
        </section>
      )}

      {shown.map((o) => (
        <section key={o.ref} style={{ ...card, padding: "14px 18px" }}>
          {/* header */}
          <div style={{ display: "flex", gap: 12, alignItems: "baseline",
                        flexWrap: "wrap" }}>
            <a href="#" onClick={(e) => { e.preventDefault();
                                          onOpenIpr(o.ref); }}
               style={{ color: "var(--sp-navy)", fontWeight: 700,
                        fontSize: 16, textDecoration: "none" }}>{o.ref}</a>
            <StatusChip status={o.status} />
            <span style={{ fontSize: 13, color: "#41525f" }}>{o.supplier}</span>
            <span style={{ marginLeft: "auto", fontSize: 13,
                           fontWeight: 600, color: "var(--sp-navy)" }}>
              {o.currency} {money(o.order_total)}</span>
          </div>
          <div style={{ fontSize: 11.5, color: "#8a97a1", marginTop: 2 }}>
            {o.doc_date}
            {o.pmrs.length > 0 ? ` · from ${o.pmrs.join(", ")}` : ""}
            {o.created_by ? ` · raised by ${o.created_by}` : ""}
          </div>

          {/* pipeline */}
          <div style={{ display: "flex", gap: 0, alignItems: "center",
                        margin: "12px 0 4px", flexWrap: "wrap" }}>
            {stageOf(o).map((st, i, arr) => (
              <span key={st.label} style={{ display: "flex",
                alignItems: "center" }}>
                <span style={{ display: "inline-flex", alignItems: "center",
                               gap: 6 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 5,
                                 background: DOT[st.state],
                                 display: "inline-block" }} />
                  <span style={{ fontSize: 12,
                    fontWeight: st.state === "now" ? 700 : 500,
                    color: st.state === "wait" ? "#a9b7c2"
                      : st.state === "now" ? "#b35900" : "#41525f" }}>
                    {st.label}</span>
                </span>
                {i < arr.length - 1 && (
                  <span style={{ width: 26, height: 2, margin: "0 8px",
                    background: arr[i + 1].state === "wait"
                      ? "#e3ecf2" : "#bcd4e3" }} />
                )}
              </span>
            ))}
          </div>

          {/* detail strip */}
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                        marginTop: 10 }}>
            <div style={{ flex: 2, minWidth: 280 }}>
              <div style={{ fontSize: 11, color: "#8a97a1",
                            marginBottom: 4 }}>SHIPMENTS</div>
              {o.shipments.length === 0
                ? <span style={{ fontSize: 12.5, color: "#8a97a1" }}>
                    not booked yet</span>
                : o.shipments.map((s) => (
                  <div key={s.id || s.seq}
                       onClick={() => onOpenShipment?.(o.ref, s)}
                       style={{ fontSize: 12.5, marginBottom: 4,
                                cursor: onOpenShipment ? "pointer" : "default",
                                border: "1px solid #e3ecf2", borderRadius: 6,
                                padding: "5px 9px" }}>
                    <b style={{ color: "var(--sp-navy)" }}>
                      {s.mode === "AIR" ? "✈" : "🚢"} {s.ref}</b>
                    {" — "}
                    <span style={{ color: SHIP_TONE[s.status] || "inherit",
                                   fontWeight: 600 }}>{s.status_display}</span>
                    {s.eta ? ` · ETA ${s.eta}` : ""}
                    {s.live ? ` · live: ${String(s.live).replace(/_/g, " ")
                      .toLowerCase()}` : ""}
                    <div style={{ fontSize: 11, color: "#8a97a1" }}>
                      {s.key || "no key entered"}
                      {s.with && s.with.length > 0 && (
                        <b style={{ color: "#8a6d00" }}>
                          {" "}· consolidated with {s.with.join(", ")}</b>)}
                    </div>
                  </div>
                ))}
            </div>
            <div style={{ flex: 1, minWidth: 150 }}>
              <div style={{ fontSize: 11, color: "#8a97a1",
                            marginBottom: 4 }}>PAYMENTS</div>
              {o.milestones_total === 0
                ? <span style={{ fontSize: 12.5, color: "#8a97a1" }}>
                    no schedule</span>
                : (<>
                    <div style={{ fontSize: 12.5, fontWeight: 600, color:
                      o.milestones_paid === o.milestones_total
                        ? "#1a7f37" : "#b35900" }}>
                      {o.milestones_paid} of {o.milestones_total} paid</div>
                    <div style={{ height: 6, borderRadius: 3,
                                  background: "#e8eef3", marginTop: 4,
                                  maxWidth: 140 }}>
                      <div style={{ height: 6, borderRadius: 3,
                        width: `${100 * o.milestones_paid
                          / o.milestones_total}%`,
                        background: o.milestones_paid === o.milestones_total
                          ? "#1a7f37" : "#e0a458" }} />
                    </div>
                  </>)}
            </div>
            <div style={{ flex: 1, minWidth: 150 }}>
              <div style={{ fontSize: 11, color: "#8a97a1",
                            marginBottom: 4 }}>RECEIPT</div>
              {o.receipts.length === 0
                ? <span style={{ fontSize: 12.5, color: "#8a97a1" }}>
                    not counted in yet</span>
                : o.receipts.map((r) => (
                  <div key={r.ref} style={{ fontSize: 12.5 }}>
                    {r.ref} · {r.status.toLowerCase()}</div>))}
            </div>
          </div>
        </section>
      ))}
    </section>
  );
}

export function ImportPaymentsDue({ onOpenIpr }) {
  // The International Payables register (owner 2026-08-23). The IPR's own
  // payment schedule stays the source of truth; this is where Finance sees
  // every unpaid milestone on an authorised order, in three bands:
  //   Coming   — pending: the balance-on-arrival, with its trigger
  //   Payable  — due, with a pay-by date (trigger day + the credit days
  //              written into the schedule; movable with a reason)
  //   TT ready — voucher-approved, waiting for the transfer
  // Payable rows are ticked ONE SUPPLIER at a time and vouchered from here;
  // they no longer appear in the generic voucher builder.
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [picked, setPicked] = useState({});
  const [busy, setBusy] = useState(false);
  const isFinance = true;

  const load = () => api("/ipr/payments-due").then(setRows)
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const bySupplier = (band) => {
    const out = new Map();
    (rows || []).filter((r) => r.band === band).forEach((r) => {
      if (!out.has(r.supplier)) out.set(r.supplier, []);
      out.get(r.supplier).push(r);
    });
    return [...out.entries()];
  };
  const pickedRows = (rows || []).filter((r) => picked[r.milestone_id]);
  const pickedSuppliers = new Set(pickedRows.map((r) => r.supplier_id));

  async function raiseVoucher() {
    if (!pickedRows.length) return;
    setBusy(true); setError(null); setMsg(null);
    try {
      const pv = await api("/payment-vouchers", { method: "POST",
        body: { milestone_ids: pickedRows.map((r) => r.milestone_id) } });
      setMsg(`Voucher ${pv.ref} raised for ${pickedRows.length} `
             + `milestone${pickedRows.length > 1 ? "s" : ""} — `
             + `${pickedRows[0].supplier}. A signatory approves it on the `
             + `Payment Vouchers page.`);
      setPicked({});
      load();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function movePayBy(r) {
    const on = window.prompt(`New pay-by date for ${r.ipr_ref} · ${r.label} `
                             + `(YYYY-MM-DD):`, r.pay_by || "");
    if (!on) return;
    const reason = window.prompt("Reason (e.g. supplier agreed 60 days):");
    if (!reason) return;
    setError(null);
    try {
      await api(`/ipr/milestones/${r.milestone_id}/pay-by`,
                { method: "POST", body: { pay_by: on, reason } });
      load();
    } catch (e) { setError(e.message); }
  }

  const head = (extra) => (
    <thead><tr>
      {extra === "pick" && <th style={{ ...th, width: 30 }}></th>}
      <th style={th}>Order</th><th style={th}>Milestone</th>
      <th style={th}>{extra === "coming" ? "Falls due" : "Pay by"}</th>
      <th style={{ ...th, textAlign: "right" }}>Amount</th>
      <th style={{ ...th, textAlign: "right" }}>≈ MVR</th>
      {extra === "ready" && <th style={th}>Voucher</th>}
    </tr></thead>);

  const orderCell = (r) => (
    <td style={td}>
      <a href="#" onClick={(e) => { e.preventDefault(); onOpenIpr(r.ipr_ref); }}
         style={{ color: "var(--sp-navy)", fontWeight: 600 }}>{r.ipr_ref}</a>
    </td>);
  const amountCells = (r) => (<>
    <td style={{ ...td, textAlign: "right" }}>{r.currency} {money(r.due_amount)}</td>
    <td style={{ ...td, textAlign: "right" }}>{money(r.expected_mvr)}</td>
  </>);
  const supplierHead = (name, list, band) => (
    <div style={{ display: "flex", alignItems: "baseline", gap: 10,
                  margin: "12px 0 4px" }}>
      <strong style={{ color: "var(--sp-navy)" }}>{name}</strong>
      <span style={{ fontSize: 12, color: "var(--muted)" }}>
        {list.length} milestone{list.length > 1 ? "s" : ""} ·{" "}
        {list[0].currency} {money(list.reduce((a, r) => a + Number(r.due_amount), 0))}
        {list.some((r) => r.credit_days > 0) && " · on credit"}
      </span>
      {band === "PAYABLE" && isFinance && (
        <button style={{ ...buttonStyle, padding: "3px 10px", fontSize: 12,
                         marginLeft: "auto",
                         opacity: pickedRows.length && pickedSuppliers.size === 1
                                  && pickedRows[0].supplier === name ? 1 : 0.45 }}
                disabled={busy || !pickedRows.length || pickedSuppliers.size !== 1
                          || pickedRows[0].supplier !== name}
                onClick={raiseVoucher}>
          Raise voucher{pickedRows.length && pickedRows[0].supplier === name
            ? ` (${pickedRows.length})` : ""}</button>)}
    </div>);

  const coming = bySupplier("COMING");
  const payable = bySupplier("PAYABLE");
  const ready = bySupplier("TT_READY");
  const overdueN = (rows || []).filter((r) => r.overdue).length;

  return (
    <section style={card}>
      <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
        🌍 International payables</h2>
      <p style={{ color: "var(--muted)", fontSize: 12.5, margin: "4px 0 0" }}>
        Every unpaid milestone on an authorised import order. The schedule on
        the order decides when each falls due; the credit days written into it
        decide the pay-by date. Tick payable milestones for <strong>one
        supplier</strong> and raise the voucher here; a signatory approves it
        on the Payment Vouchers page, then record the TT against the milestone.
      </p>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      {msg && <p style={{ color: "#1a7f37", fontSize: 13 }}>{msg}</p>}
      {pickedSuppliers.size > 1 && (
        <p style={{ color: "#b35900", fontSize: 12.5 }}>
          One voucher pays one supplier — untick the other supplier's rows.</p>)}

      <h3 style={{ fontSize: 13.5, color: "var(--sp-navy)", marginTop: 14 }}>
        Payable now
        {overdueN > 0 && <span style={{ color: "#c0392b", fontWeight: 600,
          marginLeft: 8, fontSize: 12 }}>{overdueN} past pay-by</span>}</h3>
      {payable.length === 0 && <p style={{ color: "var(--muted)",
        fontSize: 12.5 }}>Nothing payable. Purchasing marks a milestone due when
        its trigger is met; it lands here with its pay-by date.</p>}
      {payable.map(([name, list]) => (
        <div key={name}>
          {supplierHead(name, list, "PAYABLE")}
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            {head("pick")}
            <tbody>{list.map((r) => (
              <tr key={r.milestone_id} style={{ background:
                picked[r.milestone_id] ? "var(--sky-soft)" : "transparent" }}>
                <td style={{ ...td, textAlign: "center" }}>
                  <input type="checkbox" checked={!!picked[r.milestone_id]}
                    disabled={r.on_voucher}
                    title={r.on_voucher ? "Already on a voucher in progress" : ""}
                    onChange={(e) => setPicked({ ...picked,
                      [r.milestone_id]: e.target.checked })} /></td>
                {orderCell(r)}
                <td style={td}>{r.label}
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>
                    {r.trigger_label} · fell due {r.fell_due_on || "—"}
                    {r.credit_days > 0 ? ` · ${r.credit_days}d credit` : ""}
                    {r.on_voucher ? " · on a voucher" : ""}</div></td>
                <td style={td}>
                  <span style={{ color: r.overdue ? "#c0392b" : "inherit",
                                 fontWeight: r.overdue ? 700 : 400 }}>
                    {r.pay_by || "—"}{r.overdue ? " · overdue" : ""}</span>
                  {" "}<a href="#" style={{ fontSize: 11 }}
                    onClick={(e) => { e.preventDefault(); movePayBy(r); }}>edit</a>
                </td>
                {amountCells(r)}
              </tr>))}
            </tbody>
          </table>
        </div>))}

      <h3 style={{ fontSize: 13.5, color: "var(--sp-navy)", marginTop: 18 }}>
        TT ready — voucher approved</h3>
      {ready.length === 0 && <p style={{ color: "var(--muted)", fontSize: 12.5 }}>
        No transfers waiting.</p>}
      {ready.map(([name, list]) => (
        <div key={name}>
          {supplierHead(name, list, "TT_READY")}
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            {head("ready")}
            <tbody>{list.map((r) => (
              <tr key={r.milestone_id}>
                {orderCell(r)}
                <td style={td}>{r.label}</td>
                <td style={td}>{r.pay_by || "—"}</td>
                {amountCells(r)}
                <td style={td}><span style={{ color: "#1d6fb8", fontWeight: 600 }}>
                  {r.voucher_ref} → record TT on the order</span></td>
              </tr>))}
            </tbody>
          </table>
        </div>))}

      <h3 style={{ fontSize: 13.5, color: "var(--sp-navy)", marginTop: 18 }}>
        Coming — not yet due</h3>
      {coming.length === 0 && <p style={{ color: "var(--muted)", fontSize: 12.5 }}>
        No pending milestones.</p>}
      {coming.map(([name, list]) => (
        <div key={name}>
          {supplierHead(name, list, "COMING")}
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            {head("coming")}
            <tbody>{list.map((r) => (
              <tr key={r.milestone_id}>
                {orderCell(r)}
                <td style={td}>{r.label}</td>
                <td style={td}>{r.trigger_label}
                  {r.due_date ? ` · ${r.due_date}` : ""}
                  {r.credit_days > 0 ? ` · then ${r.credit_days}d credit` : ""}</td>
                {amountCells(r)}
              </tr>))}
            </tbody>
          </table>
        </div>))}
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
                    || ["", m.trigger])[1]}
                    {m.percent ? ` · ${num(m.percent)}%`
                      : (m.fixed_amount != null ? " · fixed" : "")}
                    {m.credit_days > 0 && ` · ${m.credit_days}d credit`}
                    {m.status === "DUE" && m.pay_by && (
                      <div style={{ fontSize: 11, color: "#b35900" }}>
                        pay by {m.pay_by}</div>)}</td>
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
                      credit_days: m.credit_days ?? "",
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
              {/* Credit written into the schedule: days after the trigger
                  the supplier lets us pay. Blank = the supplier's agreed
                  period on its record (owner 2026-08-23). */}
              <input type="number" min="0" placeholder="credit d"
                title="Days after the trigger the supplier allows — blank uses the supplier's agreed credit period"
                value={r.credit_days ?? ""}
                style={{ ...inputStyle, width: 80 }}
                onChange={(e) => setRows(rows.map((x, j) => j === i
                  ? { ...x, credit_days: e.target.value } : x))} />
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
                      trigger: "BALANCE", basis: "pct", value: "",
                      credit_days: "" }])}>
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
                      credit_days: r.credit_days,
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
