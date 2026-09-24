// One trading inquiry, end to end: header, the pricing sheet, quotation
// revisions, and the customer's order. Money on screen comes from the
// server's calc; the sheet mirrors the same formula only so a typed figure
// shows its effect before the save lands.
import { useEffect, useRef, useState } from "react";
import { api, apiUpload } from "../api.js";
import { Btn, Chip, card, inputStyle, td, th } from "../ui.jsx";
import { STAGES, STAGE_LABEL, StageChip, fmtDate, fmtDateTime, fmtMoney, fmtQty } from "./shared.jsx";

const VIA = [["EMAIL", "Email"], ["PHONE", "Phone"], ["WHATSAPP", "WhatsApp"],
             ["VISIT", "Visit"], ["OTHER", "Other"]];
const TABS = [["overview", "Overview"], ["pricing", "Pricing sheet"],
              ["quotation", "Quotation"], ["order", "Order"], ["supply", "Supply"],
              ["deliveries", "Deliveries"], ["invoices", "Invoices"],
              ["activity", "Activity"]];

const IPR_STATUS = { DRAFT: "draft — with Purchasing", SUBMITTED: "awaiting award",
                     APPROVED: "awaiting authorisation", AUTHORISED: "ordered",
                     CLOSED: "closed", CANCELLED: "cancelled" };
const SHIP_STATUS = { PLANNED: "planned", SHIPPED: "shipped", IN_TRANSIT: "in transit",
                      ARRIVED: "arrived", UNDER_CLEARING: "under clearing", CLEARED: "cleared" };

// ---- local mirror of trading.calc (display only) -----------------------------
function fxFor(row, sellCcy, usdRate) {
  if (row.fx && Number(row.fx) > 0) return Number(row.fx);
  const cc = (row.cost_currency || sellCcy).toUpperCase();
  if (cc === sellCcy) return 1;
  if (cc === "USD" && sellCcy === "MVR") return usdRate;
  if (cc === "MVR" && sellCcy === "USD") return 1 / usdRate;
  return null;
}
function calcRow(row, sellCcy, usdRate) {
  const qty = Number(row.qty) || 0;
  const cost = row.cost === "" || row.cost === null || row.cost === undefined ? null : Number(row.cost);
  const fx = fxFor(row, sellCcy, usdRate);
  const unitCost = cost !== null && fx !== null ? cost * fx : null;
  let unitSell = null;
  if (row.sell !== "" && row.sell !== null && row.sell !== undefined) unitSell = Number(row.sell);
  else if (unitCost !== null && row.margin_percent !== "" && row.margin_percent !== null && row.margin_percent !== undefined)
    unitSell = unitCost * (1 + Number(row.margin_percent) / 100);
  else if (unitCost !== null) unitSell = unitCost;
  const margin = unitCost && unitSell !== null ? (unitSell / unitCost - 1) * 100 : null;
  return { fx, unitCost, unitSell, lineCost: unitCost !== null ? unitCost * qty : null,
           lineSell: unitSell !== null ? unitSell * qty : null, margin, fxMissing: cost !== null && fx === null };
}

function Num({ value, onChange, disabled, width = 90, step = "0.01", placeholder }) {
  return <input type="number" step={step} min="0" value={value ?? ""} disabled={disabled}
                placeholder={placeholder}
                onChange={(e) => onChange(e.target.value)}
                style={{ ...inputStyle, width, textAlign: "right", padding: "4px 6px" }} />;
}

// ---- pricing sheet ---------------------------------------------------------
function PricingSheet({ o, onSaved }) {
  const withText = (l) => ({ ...l, description: l.spec ? `${l.description}\n${l.spec}` : l.description });
  const [rows, setRows] = useState(o.lines.map(withText));
  const [freightCost, setFreightCost] = useState(o.freight_cost ?? "0");
  const [freightSell, setFreightSell] = useState(o.freight_sell ?? "");
  const [suppliers, setSuppliers] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const locked = !o.can_manage || o.is_closed;
  const usdRate = Number(o.calc.usd_rate) || 15.42;
  const ccy = o.currency;

  useEffect(() => { api("/trading/suppliers").then(setSuppliers).catch(() => {}); }, []);
  useEffect(() => {
    setRows(o.lines.map(withText));
    setFreightCost(o.freight_cost ?? "0");
    setFreightSell(o.freight_sell ?? "");
    setDirty(false);
  }, [o]);

  function upd(i, patch) {
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
    setDirty(true);
  }
  function add(section) {
    const last = rows[rows.length - 1];
    setRows([...rows, { description: "", qty: "1", uom: last?.uom || "", section: section ?? (last?.section || ""),
                        supplier: last?.supplier || null, cost: "", cost_currency: last?.cost_currency || "USD",
                        fx: "", margin_percent: last?.margin_percent ?? "", sell: "", notes: "" }]);
    setDirty(true);
  }
  function move(i, dir) {
    const j = i + dir;
    if (j < 0 || j >= rows.length) return;
    const rs = [...rows];
    [rs[i], rs[j]] = [rs[j], rs[i]];
    setRows(rs);
    setDirty(true);
  }
  function setAllMargins() {
    const v = window.prompt("Set every line's margin % to:");
    if (v === null || v === "") return;
    setRows(rows.map((r) => ({ ...r, margin_percent: v, sell: "" })));
    setDirty(true);
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api(`/trading/orders/${o.id}`, { method: "PATCH",
        body: { freight_cost: freightCost || "0", freight_sell: freightSell === "" ? null : freightSell } });
      const d = await api(`/trading/orders/${o.id}/lines`, { method: "PUT",
        body: { lines: rows.map((r) => ({ ...r, id: r.id || null, supplier: r.supplier || null,
                                           cost: r.cost === "" ? null : r.cost,
                                           sell: r.sell === "" ? null : r.sell,
                                           margin_percent: r.margin_percent === "" ? null : r.margin_percent,
                                           fx: r.fx === "" ? null : r.fx })) } });
      setDirty(false);
      onSaved(d);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  // The sheet needs the whole window: 13 columns do not fit in the reading
  // width the other tabs use (owner 2026-09-24).
  useEffect(() => {
    document.body.dataset.wide = "1";
    return () => { delete document.body.dataset.wide; };
  }, []);

  const calcs = rows.map((r) => calcRow(r, ccy, usdRate));
  const costLines = calcs.reduce((a, c) => a + (c.lineCost || 0), 0);
  const sellLines = calcs.reduce((a, c) => a + (c.lineSell || 0), 0);
  const costTotal = costLines + (Number(freightCost) || 0);
  const subtotal = sellLines + (freightSell === "" ? 0 : Number(freightSell) || 0);
  const gstPct = Number(o.calc.gst_percent) || 0;
  const gst = subtotal * gstPct / 100;
  const marginAmt = subtotal - costTotal;

  return (
    <div>
      {locked && (
        <p className="t-note">
          {o.is_closed ? `This order is ${STAGE_LABEL[o.stage].toLowerCase()} — the pricing sheet is locked.`
                       : "You can read this sheet; only the inquiry's owner or the Sales Manager can change it."}
        </p>
      )}
      <div className="t-sheet-wrap">
        <table className="t-table t-sheet">
          <thead>
            <tr>
              <th style={th}>#</th>
              <th style={th}>Section</th>
              <th style={th}>Description</th>
              <th style={{ ...th, textAlign: "right" }}>Qty</th>
              <th style={th}>Unit</th>
              <th style={th}>Supplier</th>
              <th style={{ ...th, textAlign: "right" }}>Cost</th>
              <th style={th}>Ccy</th>
              <th style={{ ...th, textAlign: "right" }}>FX</th>
              <th style={{ ...th, textAlign: "right" }}>Cost {ccy}</th>
              <th style={{ ...th, textAlign: "right" }}>Margin %</th>
              <th style={{ ...th, textAlign: "right" }}>Sell {ccy}</th>
              <th style={{ ...th, textAlign: "right" }}>Amount</th>
              <th style={th}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const c = calcs[i];
              return (
                <tr key={r.id || `n${i}`}>
                  <td style={td} className="t-sub">{i + 1}</td>
                  <td style={td}><input style={{ ...inputStyle, width: 80, padding: "4px 6px" }} value={r.section || ""}
                                        disabled={locked} placeholder="heading" onChange={(e) => upd(i, { section: e.target.value })} /></td>
                  <td style={td} className="t-desc-cell">
                    <textarea className="t-desc" value={r.description || ""} disabled={locked} rows={Math.max(2, (r.description || "").split("\n").length)}
                              placeholder={"Product name\nspecs on the lines below"}
                              onChange={(e) => upd(i, { description: e.target.value })} />
                  </td>
                  <td style={td}><Num value={r.qty} width={64} disabled={locked} onChange={(v) => upd(i, { qty: v })} /></td>
                  <td style={td}><input style={{ ...inputStyle, width: 48, padding: "4px 6px" }} value={r.uom || ""}
                                        disabled={locked} onChange={(e) => upd(i, { uom: e.target.value })} /></td>
                  <td style={td}>
                    <select style={{ ...inputStyle, width: 110, padding: "4px 6px" }} value={r.supplier || ""} disabled={locked}
                            onChange={(e) => {
                              const s = suppliers.find((x) => String(x.id) === e.target.value);
                              upd(i, { supplier: e.target.value ? Number(e.target.value) : null,
                                       cost_currency: s?.default_currency || r.cost_currency });
                            }}>
                      <option value="">—</option>
                      {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                  </td>
                  <td style={td}><Num value={r.cost} step="0.0001" width={80} disabled={locked} onChange={(v) => upd(i, { cost: v })} /></td>
                  <td style={td}>
                    <select style={{ ...inputStyle, width: 60, padding: "4px 6px" }} value={r.cost_currency || "USD"} disabled={locked}
                            onChange={(e) => upd(i, { cost_currency: e.target.value })}>
                      {["USD", "MVR", "EUR", "CNY", "INR", "AED", "LKR"].map((x) => <option key={x}>{x}</option>)}
                    </select>
                  </td>
                  <td style={td}><Num value={r.fx} step="0.000001" width={70} disabled={locked}
                                      placeholder={c.fx !== null ? String(+c.fx.toFixed(4)) : "rate?"}
                                      onChange={(v) => upd(i, { fx: v })} /></td>
                  <td style={{ ...td, textAlign: "right" }} className={c.fxMissing ? "t-bad" : ""}>
                    {c.fxMissing ? "no rate" : c.unitCost !== null ? fmtMoney(c.unitCost, 4) : ""}
                  </td>
                  <td style={td}><Num value={r.margin_percent} width={62} disabled={locked}
                                      placeholder={c.margin !== null ? c.margin.toFixed(2) : ""}
                                      onChange={(v) => upd(i, { margin_percent: v, sell: "" })} /></td>
                  <td style={td}><Num value={r.sell} step="0.0001" width={90} disabled={locked}
                                      placeholder={c.unitSell !== null ? c.unitSell.toFixed(4) : ""}
                                      onChange={(v) => upd(i, { sell: v })} /></td>
                  <td style={{ ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                    {c.lineSell !== null ? fmtMoney(c.lineSell) : ""}
                  </td>
                  <td style={{ ...td, whiteSpace: "nowrap" }}>
                    {!locked && (<>
                      <button className="t-link" title="Move up" onClick={() => move(i, -1)}>↑</button>{" "}
                      <button className="t-link" title="Move down" onClick={() => move(i, 1)}>↓</button>{" "}
                      <button className="t-link" title="Remove" onClick={() => { setRows(rows.filter((_, j) => j !== i)); setDirty(true); }}>×</button>
                    </>)}
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr><td style={td} colSpan={14} className="t-sub">No lines yet. Add what the customer asked for, one line each.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {!locked && (
        <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          <Btn variant="secondary" onClick={() => add()}>+ Line</Btn>
          <Btn variant="secondary" onClick={() => add(window.prompt("Section heading:") || "")}>+ Section</Btn>
          <Btn variant="secondary" onClick={setAllMargins}>Set all margins…</Btn>
        </div>
      )}

      <div className="t-totals">
        <div style={card}>
          <div className="t-kv"><span>Freight to harbour — our cost</span>
            <Num value={freightCost} disabled={locked} onChange={(v) => { setFreightCost(v); setDirty(true); }} /></div>
          <div className="t-kv"><span>Freight charged to customer <i className="t-sub">(blank = absorbed)</i></span>
            <Num value={freightSell} disabled={locked} onChange={(v) => { setFreightSell(v); setDirty(true); }} /></div>
        </div>
        <div style={card}>
          <div className="t-kv"><span>Cost of lines</span><b>{fmtMoney(costLines)}</b></div>
          <div className="t-kv"><span>Total cost incl. freight</span><b>{fmtMoney(costTotal)}</b></div>
          <div className="t-kv"><span>Subtotal to customer</span><b>{fmtMoney(subtotal)}</b></div>
          <div className="t-kv"><span>GST @ {gstPct}%</span><b>{fmtMoney(gst)}</b></div>
          <div className="t-kv t-kv-total"><span>Total {ccy}</span><b>{fmtMoney(subtotal + gst)}</b></div>
          <div className="t-kv"><span>Margin</span>
            <b className={marginAmt < 0 ? "t-bad" : ""}>{fmtMoney(marginAmt)}{costTotal ? ` · ${(marginAmt / costTotal * 100).toFixed(1)}%` : ""}</b></div>
          <div className="t-sub">USD rate {usdRate} · {o.n_lines} line{o.n_lines === 1 ? "" : "s"} saved</div>
        </div>
      </div>
      {error && <p className="t-note t-note-red">{error}</p>}
      {!locked && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
          <Btn onClick={save} disabled={busy || !dirty}>{busy ? "Saving…" : dirty ? "Save sheet" : "Saved"}</Btn>
          {dirty && <span className="t-sub">Unsaved changes — the quotation uses the saved sheet.</span>}
        </div>
      )}
    </div>
  );
}

// ---- overview -----------------------------------------------------------------
function Overview({ o, onSaved }) {
  const [d, setD] = useState({});
  const [users, setUsers] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const locked = !o.can_manage;
  useEffect(() => {
    setD({ title: o.title, received_via: o.received_via, customer_ref: o.customer_ref,
           currency: o.currency, next_action: o.next_action, next_action_date: o.next_action_date || "",
           notes: o.notes, owner: o.owner, inquiry_date: o.inquiry_date });
  }, [o]);
  useEffect(() => { if (o.can_authorise) api("/trading/users").then(setUsers).catch(() => {}); }, [o.can_authorise]);
  const set = (k) => (e) => setD({ ...d, [k]: e.target.value });

  async function save() {
    setBusy(true);
    setError(null);
    const body = o.is_closed
      ? { next_action: d.next_action, next_action_date: d.next_action_date || null, notes: d.notes }
      : { ...d, next_action_date: d.next_action_date || null, owner: Number(d.owner) };
    if (!o.can_authorise) delete body.owner;
    try {
      onSaved(await api(`/trading/orders/${o.id}`, { method: "PATCH", body }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const ro = locked || o.is_closed;
  return (
    <div className="t-two">
      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Inquiry</h3>
        <label className="t-field"><span>What they asked for</span>
          <input style={inputStyle} value={d.title || ""} onChange={set("title")} disabled={ro} /></label>
        <div className="t-grid">
          <label className="t-field"><span>Received via</span>
            <select style={inputStyle} value={d.received_via || "EMAIL"} onChange={set("received_via")} disabled={ro}>
              {VIA.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select></label>
          <label className="t-field"><span>Inquiry date</span>
            <input style={inputStyle} type="date" value={d.inquiry_date || ""} onChange={set("inquiry_date")} disabled={ro} /></label>
          <label className="t-field"><span>Their reference</span>
            <input style={inputStyle} value={d.customer_ref || ""} onChange={set("customer_ref")} disabled={ro} /></label>
          <label className="t-field"><span>Quote in</span>
            <select style={inputStyle} value={d.currency || "MVR"} onChange={set("currency")} disabled={ro || o.quotations.length > 0}>
              <option>MVR</option><option>USD</option>
            </select></label>
          {o.can_authorise && (
            <label className="t-field"><span>Owner</span>
              <select style={inputStyle} value={d.owner || ""} onChange={set("owner")} disabled={o.is_closed}>
                {users.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
              </select></label>
          )}
        </div>
        <label className="t-field"><span>Next action</span>
          <input style={inputStyle} value={d.next_action || ""} onChange={set("next_action")} disabled={locked} /></label>
        <label className="t-field"><span>By</span>
          <input style={inputStyle} type="date" value={d.next_action_date || ""} onChange={set("next_action_date")} disabled={locked} /></label>
        <label className="t-field"><span>Notes</span>
          <textarea style={{ ...inputStyle, minHeight: 70 }} value={d.notes || ""} onChange={set("notes")} disabled={locked} /></label>
      </div>
      <div>
        <div style={card}>
          <h3 style={{ marginTop: 0 }}>Customer</h3>
          <b>{o.customer_detail.name}</b>
          {o.customer_detail.island && <div className="t-sub">{o.customer_detail.island}</div>}
          {o.customer_detail.address && <div className="t-sub" style={{ whiteSpace: "pre-line" }}>{o.customer_detail.address}</div>}
          {o.customer_detail.contact && <div className="t-sub">{o.customer_detail.contact}</div>}
          {o.customer_detail.tin ? <div className="t-sub">GST TIN {o.customer_detail.tin}</div>
                                 : <div className="t-sub t-bad">No GST TIN on file — needed on the tax invoice</div>}
          {o.customer_detail.gst_exempt && <Chip tone="warn">GST exempt</Chip>}
        </div>
        <p className="t-sub" style={{ marginTop: 12 }}>The commercial terms that print on the quotation are on the Quotation tab.</p>
        {error && <p className="t-note t-note-red" style={{ marginTop: 12 }}>{error}</p>}
        {!locked && <Btn style={{ marginTop: 12 }} onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</Btn>}
      </div>
    </div>
  );
}

// ---- quotation ------------------------------------------------------------------
const TERM_FIELDS = [
  ["payment_terms", "Payment terms", "e.g. 50% with the order, balance before delivery"],
  ["delivery_terms", "Delivery", "e.g. Delivered to your vessel at Malé harbour"],
  ["lead_time", "Lead time", "e.g. 6–8 weeks from receipt of order and advance"],
  ["incoterm", "Incoterms", "e.g. Delivered Malé (local supply)"],
];

function TermsCard({ o, onSaved }) {
  const [d, setD] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [dirty, setDirty] = useState(false);
  const locked = !o.can_manage || o.is_closed;
  useEffect(() => {
    setD({ payment_terms: o.payment_terms, delivery_terms: o.delivery_terms, lead_time: o.lead_time,
           incoterm: o.incoterm, extra_terms: o.extra_terms, quote_valid_days: o.quote_valid_days });
    setDirty(false);
  }, [o]);
  const set = (k) => (e) => { setD({ ...d, [k]: e.target.value }); setDirty(true); };
  async function save() {
    setBusy(true);
    setError(null);
    try { onSaved(await api(`/trading/orders/${o.id}`, { method: "PATCH", body: d })); setDirty(false); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  async function resetToStandard() {
    try {
      const st = await api("/trading/terms");
      setD({ payment_terms: st.payment_terms, delivery_terms: st.delivery_terms, lead_time: st.lead_time,
             incoterm: st.incoterm, extra_terms: st.extra_terms, quote_valid_days: st.quote_valid_days });
      setDirty(true);
    } catch (err) { setError(err.message); }
  }
  return (
    <div style={{ ...card, marginBottom: 16 }}>
      <div className="t-page-head" style={{ marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>Terms on this quotation</h3>
        {!locked && <button className="t-link" onClick={resetToStandard}>Reset to the standard lines</button>}
      </div>
      <div className="t-grid">
        {TERM_FIELDS.map(([k, label, ph]) => (
          <label key={k} className="t-field"><span>{label}</span>
            <input style={inputStyle} value={d[k] || ""} onChange={set(k)} disabled={locked} placeholder={ph} /></label>
        ))}
        <label className="t-field"><span>Valid for (days)</span>
          <input style={inputStyle} type="number" min="1" value={d.quote_valid_days || 14} onChange={set("quote_valid_days")} disabled={locked} /></label>
        <label className="t-field t-field-wide"><span>Additional terms — one per line</span>
          <textarea style={{ ...inputStyle, minHeight: 72 }} value={d.extra_terms || ""} onChange={set("extra_terms")} disabled={locked}
                    placeholder={"Prices are valid for the quantities quoted.\nGoods remain our property until paid in full."} /></label>
      </div>
      {error && <p className="t-note t-note-red">{error}</p>}
      {!locked && (
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Btn onClick={save} disabled={busy || !dirty}>{busy ? "Saving…" : dirty ? "Save terms" : "Saved"}</Btn>
          {dirty && <span className="t-sub">Unsaved — a revision issued now would print the saved terms.</span>}
        </div>
      )}
    </div>
  );
}

function StandardTerms() {
  const [st, setSt] = useState(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => { api("/trading/terms").then(setSt).catch(() => {}); }, []);
  if (!st || !st.can_edit) return null;
  const set = (k) => (e) => setSt({ ...st, [k]: e.target.value });
  async function save() {
    setBusy(true);
    setError(null);
    try { setSt(await api("/trading/terms", { method: "PUT", body: st })); setOpen(false); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return (
    <div style={{ ...card, marginBottom: 16 }}>
      <div className="t-page-head" style={{ marginBottom: open ? 8 : 0 }}>
        <h3 style={{ margin: 0 }}>Standard lines <span className="t-sub">— what every new inquiry starts with</span></h3>
        <button className="t-link" onClick={() => setOpen(!open)}>{open ? "Close" : "Edit"}</button>
      </div>
      {open && (<>
        <div className="t-grid">
          {TERM_FIELDS.map(([k, label]) => (
            <label key={k} className="t-field"><span>{label}</span>
              <input style={inputStyle} value={st[k] || ""} onChange={set(k)} /></label>
          ))}
          <label className="t-field"><span>Valid for (days)</span>
            <input style={inputStyle} type="number" min="1" value={st.quote_valid_days || 14} onChange={set("quote_valid_days")} /></label>
          <label className="t-field t-field-wide"><span>Additional terms — one per line</span>
            <textarea style={{ ...inputStyle, minHeight: 72 }} value={st.extra_terms || ""} onChange={set("extra_terms")} /></label>
        </div>
        {error && <p className="t-note t-note-red">{error}</p>}
        <Btn onClick={save} disabled={busy}>{busy ? "Saving…" : "Save standard lines"}</Btn>
        <span className="t-sub" style={{ marginLeft: 10 }}>Changes apply to inquiries logged from now on; open ones keep their own terms.</span>
      </>)}
    </div>
  );
}

function Quotation({ o, onSaved }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function act(path) {
    setBusy(true);
    setError(null);
    try { onSaved(await api(path, { method: "POST", body: {} })); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  const pdf = (q) => `/api/v1/trading/orders/${o.id}/quotations/${q.id}/pdf`;
  return (
    <div>
      <TermsCard o={o} onSaved={onSaved} />
      {o.can_manage && !o.is_closed && (
        <div style={{ ...card, marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Issue a quotation</h3>
          {o.quotation_blocker ? <p className="t-note t-note-amber">{o.quotation_blocker}</p> : (
            <p className="t-sub">
              Freezes the saved pricing sheet as revision {o.quotations.length + 1}
              {o.can_authorise ? " and authorises it — the PDF is ready to send." :
                " and hands it to the Sales Manager. The customer copy prints only once it is authorised."}
            </p>
          )}
          <Btn disabled={busy || !!o.quotation_blocker} onClick={() => act(`/trading/orders/${o.id}/quotations`)}>
            {o.quotations.length ? "Issue revision" : "Issue quotation"}
          </Btn>
        </div>
      )}
      {error && <p className="t-note t-note-red">{error}</p>}
      <StandardTerms />
      {o.quotations.length === 0 ? <p className="t-empty">No quotation yet.</p> : (
        <table className="t-table">
          <thead><tr>
            <th style={th}>Quotation</th><th style={th}>Status</th>
            <th style={{ ...th, textAlign: "right" }}>Total</th>
            <th style={th}>Issued</th><th style={th}>Authorised</th><th style={th}>Valid until</th><th style={th}></th>
          </tr></thead>
          <tbody>
            {[...o.quotations].reverse().map((q) => (
              <tr key={q.id}>
                <td style={td}><b>{q.ref}</b><div className="t-sub">{q.n_lines} lines</div></td>
                <td style={td}><Chip tone={q.status === "AUTHORISED" ? "ok" : q.status === "AWAITING_AUTH" ? "warn" : "alert"}>
                  {q.status.replace("_", " ").toLowerCase()}</Chip></td>
                <td style={{ ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{q.currency} {fmtMoney(q.total)}</td>
                <td style={td}>{fmtDate(q.created_at)}<div className="t-sub">{q.created_by}</div></td>
                <td style={td}>{q.authorised_at ? <>{fmtDate(q.authorised_at)}<div className="t-sub">{q.authorised_by}</div></> : "—"}</td>
                <td style={td}>{fmtDate(q.valid_until)}</td>
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  <a className="t-link" href={pdf(q)} target="_blank" rel="noreferrer">
                    {q.status === "AUTHORISED" ? "PDF" : "Draft PDF"}
                  </a>
                  {q.status === "AWAITING_AUTH" && o.can_authorise && (
                    <> · <button className="t-link" disabled={busy}
                                 onClick={() => act(`/trading/orders/${o.id}/quotations/${q.id}/authorise`)}>Authorise</button></>
                  )}
                  {["AWAITING_AUTH", "AUTHORISED"].includes(q.status) && o.can_manage && !o.is_closed && (
                    <> · <button className="t-link" disabled={busy}
                                 onClick={() => window.confirm(`Withdraw ${q.ref}?`) &&
                                   act(`/trading/orders/${o.id}/quotations/${q.id}/withdraw`)}>Withdraw</button></>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ---- order (won / lost) ---------------------------------------------------------
function Order({ o, onSaved }) {
  const [po, setPo] = useState({ po_number: "", po_date: "" });
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const file = useRef(null);
  const authorised = o.quotations.find((q) => q.status === "AUTHORISED");

  async function win(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const fd = new FormData();
    fd.append("po_number", po.po_number);
    fd.append("po_date", po.po_date);
    if (file.current?.files?.[0]) fd.append("po_file", file.current.files[0]);
    try { onSaved(await apiUpload(`/trading/orders/${o.id}/won`, fd)); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function lose() {
    if (!window.confirm("Mark this inquiry as lost?")) return;
    setBusy(true);
    setError(null);
    try { onSaved(await api(`/trading/orders/${o.id}/lost`, { method: "POST", body: { reason } })); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  if (o.stage === "WON") {
    return (
      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Sales order {o.so_ref}</h3>
        <div className="t-kv"><span>Customer PO</span><b>{o.po_number}</b></div>
        <div className="t-kv"><span>PO date</span><b>{fmtDate(o.po_date)}</b></div>
        <div className="t-kv"><span>Against quotation</span><b>{authorised?.ref} · {authorised?.currency} {fmtMoney(authorised?.total)}</b></div>
        <div className="t-kv"><span>Recorded</span><b>{fmtDateTime(o.won_at)} by {o.won_by}</b></div>
        {o.po_file && <a className="t-link" href={o.po_file} target="_blank" rel="noreferrer">Customer's PO copy</a>}
        <p className="t-note" style={{ marginTop: 12 }}>
          Next: raise the import orders on the <b>Supply</b> tab, deliver on <b>Deliveries</b>, invoice on <b>Invoices</b>.
        </p>
      </div>
    );
  }
  if (o.stage === "LOST") {
    return (
      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Lost</h3>
        <p>{o.lost_reason}</p>
        <div className="t-sub">{fmtDateTime(o.lost_at)}</div>
      </div>
    );
  }
  return (
    <div className="t-two">
      <form onSubmit={win} style={card}>
        <h3 style={{ marginTop: 0 }}>Record the customer's order</h3>
        {!authorised && <p className="t-note t-note-amber">Needs an authorised quotation first — nothing is ordered against a price the customer has not seen.</p>}
        <label className="t-field"><span>Customer PO number</span>
          <input style={inputStyle} value={po.po_number} onChange={(e) => setPo({ ...po, po_number: e.target.value })} disabled={!o.can_manage} /></label>
        <label className="t-field"><span>PO date</span>
          <input style={inputStyle} type="date" value={po.po_date} onChange={(e) => setPo({ ...po, po_date: e.target.value })} disabled={!o.can_manage} /></label>
        <label className="t-field"><span>PO copy (PDF or photo)</span>
          <input type="file" ref={file} accept=".pdf,image/*" disabled={!o.can_manage} /></label>
        {error && <p className="t-note t-note-red">{error}</p>}
        <Btn type="submit" disabled={busy || !o.can_manage || !authorised || !po.po_number || !po.po_date}>
          {busy ? "Saving…" : "Won — issue sales order"}
        </Btn>
      </form>
      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Or mark it lost</h3>
        <label className="t-field"><span>Why</span>
          <input style={inputStyle} value={reason} onChange={(e) => setReason(e.target.value)} disabled={!o.can_manage}
                 placeholder="price, lead time, bought elsewhere…" /></label>
        <Btn variant="danger" onClick={lose} disabled={busy || !o.can_manage || !reason.trim()}>Mark lost</Btn>
      </div>
    </div>
  );
}

// ---- supply (won orders) ------------------------------------------------------------
function Supply({ o }) {
  const [sup, setSup] = useState(null);
  const [picked, setPicked] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [raised, setRaised] = useState(null);

  function load() {
    return api(`/trading/orders/${o.id}/supply`).then((d) => {
      setSup(d);
      setPicked(new Set(d.orderable));
    }).catch((e) => setError(e.message));
  }
  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [o.id]);

  async function raise_() {
    setBusy(true);
    setError(null);
    try {
      const d = await api(`/trading/orders/${o.id}/import-orders`,
                          { method: "POST", body: { line_ids: [...picked] } });
      setRaised(d.raised);
      setSup(d);
      setPicked(new Set(d.orderable));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (o.stage !== "WON") {
    return <p className="t-empty">The supply leg opens once the order is won — import orders are raised against the sales order.</p>;
  }
  if (!sup) return error ? <p className="t-note t-note-red">{error}</p> : <p>Loading…</p>;
  const toggle = (id) => setPicked((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });

  return (
    <div>
      {raised && (
        <p className="t-note">
          Raised {raised.join(", ")} as draft import order{raised.length === 1 ? "" : "s"}. Purchasing completes the
          draft (ports, proforma, payment schedule); it is then awarded and authorised like any other import.
        </p>
      )}
      {error && <p className="t-note t-note-red">{error}</p>}
      <table className="t-table">
        <thead><tr>
          <th style={th}></th><th style={th}>#</th><th style={th}>Line</th>
          <th style={{ ...th, textAlign: "right" }}>Qty</th><th style={th}>Supplier</th>
          <th style={{ ...th, textAlign: "right" }}>Cost</th><th style={th}>Import order</th>
          <th style={{ ...th, textAlign: "right" }}>Shipped</th><th style={{ ...th, textAlign: "right" }}>Received</th>
          <th style={{ ...th, textAlign: "right" }}>In store</th><th style={{ ...th, textAlign: "right" }}>Landed MVR/unit</th>
        </tr></thead>
        <tbody>
          {sup.lines.map((l) => (
            <tr key={l.id}>
              <td style={td}>{l.orderable && o.can_manage && (
                <input type="checkbox" checked={picked.has(l.id)} onChange={() => toggle(l.id)} />)}</td>
              <td style={td} className="t-sub">{l.sr_no}</td>
              <td style={td}>{l.section && <div className="t-sub">{l.section}</div>}<b>{l.description}</b>{l.spec && <div className="t-spec">{l.spec}</div>}</td>
              <td style={{ ...td, textAlign: "right" }}>{fmtQty(l.qty)} {l.uom}</td>
              <td style={td}>{l.supplier_name || <span className="t-sub">no supplier</span>}</td>
              <td style={{ ...td, textAlign: "right" }}>{l.cost ? `${l.cost_currency} ${fmtMoney(l.cost, 4)}` : ""}</td>
              <td style={td}>{l.ipr ? <><b>{l.ipr}</b><div className="t-sub">{IPR_STATUS[l.ipr_status] || l.ipr_status}</div></>
                                    : l.orderable ? <span className="t-sub">not yet ordered</span> : <span className="t-sub">—</span>}</td>
              <td style={{ ...td, textAlign: "right" }}>{l.shipped_qty ? fmtQty(l.shipped_qty) : ""}</td>
              <td style={{ ...td, textAlign: "right" }}>{l.received_qty ? fmtQty(l.received_qty) : ""}</td>
              <td style={{ ...td, textAlign: "right" }}>{Number(l.on_hand) ? fmtQty(l.on_hand) : ""}</td>
              <td style={{ ...td, textAlign: "right" }}>{l.unit_landed_mvr ? fmtMoney(l.unit_landed_mvr, 4) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {o.can_manage && sup.orderable.length > 0 && (
        <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 10 }}>
          <Btn onClick={raise_} disabled={busy || picked.size === 0}>
            {busy ? "Raising…" : `Raise import order${picked.size > 1 ? "s" : ""} for ${picked.size} line${picked.size === 1 ? "" : "s"}`}
          </Btn>
          <span className="t-sub">One import order per supplier, reserved to {o.so_ref}, in the trading book.</span>
        </div>
      )}

      {sup.import_orders.length > 0 && (
        <div className="t-tiles" style={{ marginTop: 20 }}>
          {sup.import_orders.map((io) => (
            <div key={io.ref} className="t-tile t-tile-soon" style={{ opacity: 1, cursor: "default", alignItems: "stretch" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <b>{io.ref}</b>
                <Chip tone={io.status === "AUTHORISED" ? "ok" : io.status === "CANCELLED" || io.is_void ? "alert" : "warn"}>
                  {IPR_STATUS[io.status] || io.status}</Chip>
              </div>
              <div className="t-sub">{io.supplier} · {io.currency} {fmtMoney(io.order_total)} @ {io.exchange_rate}</div>
              <div className="t-sub">MVR {fmtMoney(io.mvr_total)} goods{Number(io.charges_mvr) ? ` + ${fmtMoney(io.charges_mvr)} charges (${io.uplift_pct}%)` : ""}</div>
              <div className="t-sub"><b>Landed MVR {fmtMoney(io.landed_total_mvr)}</b></div>
              {io.shipments.map((sh) => (
                <div key={sh.ref} className="t-sub">
                  {sh.ref} · {sh.mode} · {SHIP_STATUS[sh.status] || sh.status}{sh.eta ? ` · ETA ${fmtDate(sh.eta)}` : ""}{sh.live ? ` · ${sh.live}` : ""}
                </div>
              ))}
              {io.received.length > 0 && <div className="t-sub">received: {io.received.join(", ")}</div>}
            </div>
          ))}
        </div>
      )}
      {Number(sup.lots_on_hand) > 0 && (
        <p className="t-note" style={{ marginTop: 12 }}>
          {fmtQty(sup.lots_on_hand)} units are in the HO store reserved to {o.so_ref}. Raise a delivery note on the Deliveries tab to take them to the customer's boat.
        </p>
      )}
    </div>
  );
}

// ---- deliveries ----------------------------------------------------------------------
function DeliveryForm({ o, deliverable, onSaved, onCancel }) {
  const [d, setD] = useState({ delivery_date: new Date().toISOString().slice(0, 10),
                               vessel: "", jetty: "Malé harbour", receiver: "", notes: "" });
  const [qty, setQty] = useState(() => Object.fromEntries(deliverable.map((l) => [l.id, ""])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setD({ ...d, [k]: e.target.value });
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSaved(await api(`/trading/orders/${o.id}/deliveries`, { method: "POST", body: {
        ...d, lines: Object.entries(qty).filter(([, v]) => Number(v) > 0).map(([k, v]) => ({ line_id: Number(k), qty: v })) } }));
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={save} style={{ ...card, marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>New delivery note</h3>
      <div className="t-grid">
        <label className="t-field"><span>Delivery date</span>
          <input style={inputStyle} type="date" value={d.delivery_date} onChange={set("delivery_date")} /></label>
        <label className="t-field"><span>Customer's vessel</span>
          <input style={inputStyle} value={d.vessel} onChange={set("vessel")} placeholder={o.customer_detail?.vessels || "boat name"} /></label>
        <label className="t-field"><span>Jetty</span>
          <input style={inputStyle} value={d.jetty} onChange={set("jetty")} /></label>
        <label className="t-field"><span>Received on board by</span>
          <input style={inputStyle} value={d.receiver} onChange={set("receiver")} placeholder="captain / crew name" /></label>
        <label className="t-field t-field-wide"><span>Notes</span>
          <input style={inputStyle} value={d.notes} onChange={set("notes")} /></label>
      </div>
      <table className="t-table">
        <thead><tr><th style={th}>Line</th><th style={{ ...th, textAlign: "right" }}>Ordered</th>
          <th style={{ ...th, textAlign: "right" }}>On notes</th><th style={{ ...th, textAlign: "right" }}>In store</th>
          <th style={{ ...th, textAlign: "right" }}>Deliver now</th></tr></thead>
        <tbody>
          {deliverable.map((l) => (
            <tr key={l.id}>
              <td style={td}>{l.section && <div className="t-sub">{l.section}</div>}{l.description}</td>
              <td style={{ ...td, textAlign: "right" }}>{fmtQty(l.qty)} {l.uom}</td>
              <td style={{ ...td, textAlign: "right" }}>{fmtQty(l.delivered)}</td>
              <td style={{ ...td, textAlign: "right" }}>{l.needs_stock ? fmtQty(l.on_hand) : <span className="t-sub">n/a</span>}</td>
              <td style={{ ...td, textAlign: "right" }}>
                <Num value={qty[l.id]} width={90} disabled={Number(l.can_deliver) <= 0}
                     placeholder={`≤ ${fmtQty(l.can_deliver)}`} onChange={(v) => setQty({ ...qty, [l.id]: v })} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {error && <p className="t-note t-note-red">{error}</p>}
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Btn type="submit" disabled={busy || !Object.values(qty).some((v) => Number(v) > 0)}>{busy ? "Saving…" : "Create delivery note"}</Btn>
        <Btn type="button" variant="secondary" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}

const DN_TONE = { DRAFT: "warn", DESPATCHED: "info", RECEIVED: "ok", CANCELLED: "alert" };

function Deliveries({ o }) {
  const [data, setData] = useState(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);
  const file = useRef({});
  function load() { return api(`/trading/orders/${o.id}/deliveries`).then(setData).catch((e) => setError(e.message)); }
  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [o.id]);
  async function act(dn, action) {
    if (action === "despatch" && !window.confirm(`Despatch ${dn.ref}? The goods leave the store and cost of sales is posted.`)) return;
    try { await api(`/trading/orders/${o.id}/deliveries/${dn.id}`, { method: "POST", body: { action } }); load(); }
    catch (e) { setError(e.message); }
  }
  async function receive(dn) {
    const fd = new FormData();
    const f = file.current[dn.id]?.files?.[0];
    if (f) fd.append("signed_copy", f);
    try { await apiUpload(`/trading/orders/${o.id}/deliveries/${dn.id}/receive`, fd); load(); }
    catch (e) { setError(e.message); }
  }
  if (o.stage !== "WON") return <p className="t-empty">Deliveries are made against a won order.</p>;
  if (!data) return error ? <p className="t-note t-note-red">{error}</p> : <p>Loading…</p>;
  const canNew = o.can_manage && data.deliverable.some((l) => Number(l.can_deliver) > 0);
  return (
    <div>
      {error && <p className="t-note t-note-red">{error}</p>}
      {creating ? <DeliveryForm o={o} deliverable={data.deliverable} onSaved={() => { setCreating(false); load(); }} onCancel={() => setCreating(false)} />
        : canNew && <Btn onClick={() => setCreating(true)} style={{ marginBottom: 12 }}>+ New delivery note</Btn>}
      {data.deliveries.length === 0 ? <p className="t-empty">Nothing delivered yet. A delivery note takes goods from the store to the customer's boat; the invoice follows the despatch.</p> : (
        <table className="t-table">
          <thead><tr><th style={th}>Note</th><th style={th}>Status</th><th style={th}>Date</th><th style={th}>Vessel · receiver</th>
            <th style={th}>Lines</th><th style={{ ...th, textAlign: "right" }}>Cost of sale MVR</th><th style={th}>Invoice</th><th style={th}></th></tr></thead>
          <tbody>
            {data.deliveries.map((dn) => (
              <tr key={dn.id}>
                <td style={td}><b>{dn.ref}</b></td>
                <td style={td}><Chip tone={DN_TONE[dn.status]}>{dn.status.toLowerCase()}</Chip></td>
                <td style={td}>{fmtDate(dn.delivery_date)}</td>
                <td style={td}>{dn.vessel || <span className="t-sub">vessel?</span>}<div className="t-sub">{dn.receiver}</div></td>
                <td style={td}>{dn.lines.map((l) => `${fmtQty(l.qty)} ${l.uom} ${l.description}`).join("; ")}</td>
                <td style={{ ...td, textAlign: "right" }}>{Number(dn.cogs_mvr) ? fmtMoney(dn.cogs_mvr) : ""}</td>
                <td style={td}>{dn.invoice || <span className="t-sub">—</span>}</td>
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  <a className="t-link" href={`/api/v1/trading/orders/${o.id}/deliveries/${dn.id}/pdf`} target="_blank" rel="noreferrer">PDF</a>
                  {o.can_manage && dn.status === "DRAFT" && <> · <button className="t-link" onClick={() => act(dn, "despatch")}>Despatch</button>
                    · <button className="t-link" onClick={() => act(dn, "cancel")}>Cancel</button></>}
                  {o.can_manage && dn.status === "DESPATCHED" && <>
                    <div style={{ marginTop: 4 }}><input type="file" accept=".pdf,image/*" ref={(el) => { file.current[dn.id] = el; }} style={{ fontSize: 12 }} />
                    <button className="t-link" onClick={() => receive(dn)}>Mark received</button></div></>}
                  {dn.signed_copy && <> · <a className="t-link" href={dn.signed_copy} target="_blank" rel="noreferrer">Signed copy</a></>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ---- invoices ------------------------------------------------------------------------
const INV_TONE = { DRAFT: "warn", ISSUED: "info", PAID: "ok", VOID: "alert" };

function InvoiceForm({ o, data, onSaved, onCancel }) {
  const [picked, setPicked] = useState(new Set(data.invoiceable.map((d) => d.id)));
  const [freight, setFreight] = useState(!data.freight_billed && !!data.freight_sell);
  const [charges, setCharges] = useState([]);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const toggle = (id) => setPicked((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSaved(await api(`/trading/orders/${o.id}/invoices`, { method: "POST", body: {
        delivery_ids: [...picked], include_freight: freight, charges, invoice_date: date } }));
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={save} style={{ ...card, marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>New tax invoice</h3>
      <label className="t-field" style={{ maxWidth: 200 }}><span>Invoice date</span>
        <input style={inputStyle} type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
      <p className="t-sub">Deliveries to invoice, at the quoted prices:</p>
      {data.invoiceable.map((dn) => (
        <label key={dn.id} className="t-check">
          <input type="checkbox" checked={picked.has(dn.id)} onChange={() => toggle(dn.id)} />
          <b>{dn.ref}</b> · {fmtDate(dn.delivery_date)} · {dn.lines.map((l) => `${fmtQty(l.qty)} ${l.uom} ${l.description}`).join("; ")}
        </label>
      ))}
      {data.freight_sell && (
        <label className="t-check" style={{ marginTop: 8 }}>
          <input type="checkbox" checked={freight} disabled={data.freight_billed} onChange={(e) => setFreight(e.target.checked)} />
          Bill the quoted freight ({o.currency} {fmtMoney(data.freight_sell)}){data.freight_billed ? " — already billed" : ""}
        </label>
      )}
      <div style={{ marginTop: 8 }}>
        <span className="t-sub">Extra charges on this invoice</span>
        {charges.map((c, i) => (
          <div key={i} style={{ display: "flex", gap: 8, marginTop: 4 }}>
            <input style={{ ...inputStyle, flex: 1 }} placeholder="label" value={c.label}
                   onChange={(e) => setCharges(charges.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
            <Num value={c.amount} width={120} onChange={(v) => setCharges(charges.map((x, j) => (j === i ? { ...x, amount: v } : x)))} />
            <button type="button" className="t-link" onClick={() => setCharges(charges.filter((_, j) => j !== i))}>×</button>
          </div>
        ))}
        <button type="button" className="t-link" style={{ marginTop: 4 }} onClick={() => setCharges([...charges, { label: "", amount: "" }])}>+ charge</button>
      </div>
      {error && <p className="t-note t-note-red">{error}</p>}
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Btn type="submit" disabled={busy || picked.size === 0}>{busy ? "Saving…" : "Create draft invoice"}</Btn>
        <Btn type="button" variant="secondary" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}

function Invoices({ o }) {
  const [data, setData] = useState(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);
  function load() { return api(`/trading/orders/${o.id}/invoices`).then(setData).catch((e) => setError(e.message)); }
  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [o.id]);
  async function act(inv, action, extra = {}) {
    try { await api(`/trading/orders/${o.id}/invoices/${inv.id}`, { method: "POST", body: { action, ...extra } }); load(); }
    catch (e) { setError(e.message); }
  }
  if (o.stage !== "WON") return <p className="t-empty">Invoices are raised against a won order.</p>;
  if (!data) return error ? <p className="t-note t-note-red">{error}</p> : <p>Loading…</p>;
  const m = data.money;
  return (
    <div>
      {error && <p className="t-note t-note-red">{error}</p>}
      <div className="t-tiles" style={{ marginTop: 0 }}>
        {[["Invoiced", m.invoiced], ["Credited", m.credited], ["Received", m.received], ["Outstanding", m.outstanding]].map(([l, v]) => (
          <div key={l} className="t-tile t-tile-soon" style={{ opacity: 1, cursor: "default" }}>
            <span className="t-tile-n" style={{ fontSize: 20 }}>{o.currency} {fmtMoney(v)}</span><span className="t-tile-l">{l}</span>
          </div>
        ))}
      </div>
      {creating ? <InvoiceForm o={o} data={data} onSaved={() => { setCreating(false); load(); }} onCancel={() => setCreating(false)} />
        : o.can_manage && data.invoiceable.length > 0 && <Btn onClick={() => setCreating(true)} style={{ marginBottom: 12 }}>+ Invoice {data.invoiceable.length} despatched deliver{data.invoiceable.length === 1 ? "y" : "ies"}</Btn>}
      {data.invoices.length === 0 ? <p className="t-empty">No invoice yet. Despatch a delivery note first; the invoice follows it.</p> : (
        <table className="t-table">
          <thead><tr><th style={th}>Invoice</th><th style={th}>Status</th><th style={th}>Date · due</th><th style={th}>Deliveries</th>
            <th style={{ ...th, textAlign: "right" }}>Total</th><th style={{ ...th, textAlign: "right" }}>Outstanding</th><th style={th}></th></tr></thead>
          <tbody>
            {data.invoices.map((inv) => (
              <tr key={inv.id}>
                <td style={td}><b>{inv.ref}</b>{inv.credit_notes.map((c) => <div key={c.id} className="t-sub">{c.ref} −{fmtMoney(c.amount)} · {c.reason}</div>)}
                  {inv.receipts.map((r, i) => <div key={i} className="t-sub">{r.receipt_no} {fmtDate(r.date)} {fmtMoney(r.amount)}</div>)}</td>
                <td style={td}><Chip tone={INV_TONE[inv.status]}>{inv.status.toLowerCase()}</Chip>{inv.void_reason && <div className="t-sub">{inv.void_reason}</div>}</td>
                <td style={td}>{fmtDate(inv.invoice_date)}<div className="t-sub">due {fmtDate(inv.due_date)}</div></td>
                <td style={td}>{inv.deliveries.join(", ")}{inv.includes_freight ? " + freight" : ""}</td>
                <td style={{ ...td, textAlign: "right" }}>{inv.currency} {fmtMoney(inv.total)}<div className="t-sub">GST {fmtMoney(inv.gst)}</div></td>
                <td style={{ ...td, textAlign: "right" }}>{inv.status === "VOID" ? "" : fmtMoney(inv.outstanding)}</td>
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  <a className="t-link" href={`/api/v1/trading/orders/${o.id}/invoices/${inv.id}/pdf`} target="_blank" rel="noreferrer">{inv.status === "DRAFT" ? "Draft PDF" : "PDF"}</a>
                  {inv.status === "DRAFT" && o.can_authorise && <> · <button className="t-link" onClick={() => act(inv, "issue")}>Issue</button></>}
                  {inv.status !== "VOID" && o.can_manage && <> · <button className="t-link" onClick={() => { const r = window.prompt(`Void ${inv.ref} — why?`); if (r) act(inv, "void", { reason: r }); }}>Void</button></>}
                  {["ISSUED", "PAID"].includes(inv.status) && o.can_authorise && <> · <button className="t-link" onClick={() => {
                    const a = window.prompt("Credit note amount (incl. GST):"); if (!a) return;
                    const r = window.prompt("Reason:"); if (!r) return; act(inv, "credit", { amount: a, reason: r }); }}>Credit note</button></>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Activity({ o }) {
  const [rows, setRows] = useState(null);
  useEffect(() => { api(`/trading/orders/${o.id}/activity`).then(setRows).catch(() => setRows([])); }, [o]);
  if (rows === null) return <p>Loading…</p>;
  return (
    <table className="t-table">
      <tbody>
        {rows.map((a, i) => (
          <tr key={i}>
            <td style={{ ...td, whiteSpace: "nowrap" }}>{fmtDateTime(a.at)}</td>
            <td style={td}>{a.actor}</td>
            <td style={td}><b>{a.event.replace(/_/g, " ").toLowerCase()}</b>
              {a.from && a.to ? ` ${STAGE_LABEL[a.from] || a.from} → ${STAGE_LABEL[a.to] || a.to}` : ""}
              {a.detail?.quotation ? ` · ${a.detail.quotation}` : ""}
              {a.detail?.so ? ` · ${a.detail.so}` : ""}
              {a.detail?.reason ? ` · ${a.detail.reason}` : ""}
              {a.detail?.lines !== undefined ? ` · ${a.detail.lines} lines` : ""}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ---- page -------------------------------------------------------------------------
export default function OrderPage({ id, back, initialTab }) {
  const [o, setO] = useState(null);
  const [tab, setTab] = useState(initialTab || "overview");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setO(null);
    api(`/trading/orders/${id}`).then(setO).catch((e) => setError(e.message));
  }, [id]);
  // A deep link into a tab (#/inquiries/12/quotation) opens that tab even
  // when the order page is already showing.
  useEffect(() => { if (initialTab) setTab(initialTab); }, [initialTab]);

  async function pick(stage) {
    setBusy(true);
    try { setO(await api(`/trading/orders/${id}/stage`, { method: "POST", body: { stage } })); }
    catch (e) { window.alert(e.message); }
    finally { setBusy(false); }
  }

  if (error) return <div className="t-page"><p className="t-note t-note-red">{error}</p><button className="t-link" onClick={back}>Back</button></div>;
  if (!o) return <div className="t-page"><p>Loading…</p></div>;
  const idx = STAGES.indexOf(o.stage);

  return (
    <div className="t-page">
      <button className="t-link" onClick={back}>← Inquiries</button>
      <div className="t-page-head" style={{ marginTop: 6 }}>
        <div>
          <h1 className="t-h1">{o.ref} <span className="t-h1-sub">{o.title}</span></h1>
          <div className="t-sub">{o.customer_name} · owner {o.owner_name}
            {o.quote_ref && <> · {o.quote_ref}</>}{o.so_ref && <> · <b>{o.so_ref}</b></>}</div>
        </div>
        <div className="t-tools">
          <StageChip stage={o.stage} />
          {o.stage !== "LOST" && (
            <div className="t-stepper">
              {STAGES.map((s, i) => (
                <button key={s} className={"t-step" + (i <= idx ? " is-done" : "") + (s === o.stage ? " is-now" : "")}
                        disabled={busy || !o.can_manage || o.is_closed || i <= idx || s === "WON"}
                        title={s === "WON" ? "Recorded on the Order tab with the customer's PO" : i > idx ? `Move to ${STAGE_LABEL[s]}` : ""}
                        onClick={() => pick(s)}>{STAGE_LABEL[s]}</button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="t-tabs">
        {TABS.map(([k, l]) => (
          <button key={k} className={"t-tab" + (tab === k ? " is-active" : "")} onClick={() => setTab(k)}>
            {l}{k === "quotation" && o.quotations.some((q) => q.status === "AWAITING_AUTH") ? " •" : ""}
          </button>
        ))}
      </div>

      {tab === "overview" && <Overview o={o} onSaved={setO} />}
      {tab === "pricing" && <PricingSheet o={o} onSaved={setO} />}
      {tab === "quotation" && <Quotation o={o} onSaved={setO} />}
      {tab === "order" && <Order o={o} onSaved={setO} />}
      {tab === "supply" && <Supply o={o} />}
      {tab === "deliveries" && <Deliveries o={o} />}
      {tab === "invoices" && <Invoices o={o} />}
      {tab === "activity" && <Activity o={o} />}
      <div className="t-sub" style={{ marginTop: 16 }}>
        {o.n_lines} line{o.n_lines === 1 ? "" : "s"} · quoted {o.currency} {fmtMoney(o.total)}
        {o.calc.margin_percent && o.can_manage ? ` · margin ${o.calc.margin_percent}%` : ""} · {fmtQty(o.calc.n_priced)}/{o.n_lines} priced
      </div>
    </div>
  );
}
