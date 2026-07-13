import { useEffect, useMemo, useState } from "react";
import { api } from "./api.js";
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
  ["approve", "Award (Director)", ["SUBMITTED"], ["DIRECTOR", "ADMIN"]],
  ["return", "Return with comment", ["SUBMITTED", "APPROVED"],
   ["DIRECTOR", "HO_PURCHASING", "ADMIN"], "comment"],
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

function IprForm({ me, onSaved, onCancel }) {
  const [ctx, setCtx] = useState(null);
  const [hdr, setHdr] = useState({ supplier_id: "", order_currency: "USD",
    exchange_rate: "", incoterm: "", loading_port: "", discharge_port: "",
    pi_ref: "", notes: "" });
  const [pmrRefs, setPmrRefs] = useState([]);
  const [lines, setLines] = useState([newLine()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/ipr/context").then(setCtx).catch((e) => setError(e.message));
  }, []);

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

  const orderTotal = useMemo(() =>
    lines.reduce((a, l) => a + num(l.order_qty) * num(l.unit_price), 0), [lines]);
  const mvrTotal = orderTotal * num(hdr.exchange_rate);

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
      const doc = await api("/ipr", { method: "POST", body });
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
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>New International Order</h2>
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

      <SectionTitle>Demand — PMRs this order fulfils</SectionTitle>
      {ctx.pmrs.length === 0 ? (
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
              <input placeholder="Description" value={l.free_text_desc}
                     onChange={(e) => setLine(i, { free_text_desc: e.target.value })}
                     style={inputStyle} />
              <input placeholder="Unit" value={l.unit}
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

      <p style={{ marginTop: 14, fontSize: 14, fontWeight: 600,
                  color: "var(--sp-navy)" }}>
        Order total: {hdr.order_currency} {money(orderTotal)}
        {num(hdr.exchange_rate) > 0 &&
          ` · ≈ MVR ${money(mvrTotal)} at ${hdr.exchange_rate}`}
      </p>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      <button onClick={save} disabled={busy} style={{ ...buttonStyle, marginTop: 8 }}>
        {busy ? "Saving…" : "Save draft order"}</button>
      {/* projById kept for future per-allocation labels */}
      <span style={{ display: "none" }}>{Object.keys(projById).length}</span>
    </section>
  );
}

export function IprView({ me, refIpr, onClose }) {
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
        <button onClick={onClose} style={ghostButton}>Close</button>
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
          Awarded — awaiting a Payment Voucher; the commitment posts when a
          signatory authorises it.</p>
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
    </section>
  );
}
