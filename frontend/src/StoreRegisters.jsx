import { Fragment, useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { StatusChip, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

/* Registers for the Head Office store (owner 2026-10-24).
 *
 * The HO Store page lists only what is still on the shelf, so a receipt whose
 * stock was all issued straight out (IRN-006 → SIN-002) could not be found
 * anywhere. These list every receipt and every store issue, whatever is left.
 */

const money = (v) => (v == null ? "—"
  : Number(v).toLocaleString(undefined, { minimumFractionDigits: 2,
                                           maximumFractionDigits: 2 }));
const num = { ...td, textAlign: "right", fontVariantNumeric: "tabular-nums",
              whiteSpace: "nowrap" };
const numTh = { ...th, textAlign: "right" };
const small = { fontSize: 11.5, color: "var(--muted)" };

function Filters({ f, setF, statuses, sites }) {
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "0 0 12px",
                  alignItems: "flex-end" }}>
      <label style={small}>Search
        <input style={{ ...inputStyle, width: 220 }} value={f.q}
               placeholder="Ref, IPR, supplier, site…" onChange={set("q")} />
      </label>
      <label style={small}>Status
        <select style={inputStyle} value={f.status} onChange={set("status")}>
          <option value="">All</option>
          {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select></label>
      {sites && (
        <label style={small}>To site
          <select style={inputStyle} value={f.site} onChange={set("site")}>
            <option value="">All</option>
            {sites.map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}
          </select></label>)}
      <label style={small}>From
        <input type="date" style={inputStyle} value={f.from}
               onChange={set("from")} /></label>
      <label style={small}>To
        <input type="date" style={inputStyle} value={f.to}
               onChange={set("to")} /></label>
    </div>
  );
}

function query(f) {
  const p = new URLSearchParams();
  Object.entries(f).forEach(([k, v]) => { if (v) p.set(k, v); });
  return p.toString();
}

export function IrnRegister({ onOpenIrn }) {
  const [f, setF] = useState({ q: "", status: "", from: "", to: "" });
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    const t = setTimeout(() => {
      api(`/irn-register?${query(f)}`).then((d) => setRows(d.rows))
        .catch((e) => setError(e.message));
    }, 250);
    return () => clearTimeout(t);
  }, [f]);

  const total = (k) => (rows || []).reduce((s, r) => s + Number(r[k] || 0), 0);
  return (
    <section style={card}>
      <h2 style={{ margin: "0 0 4px", color: "var(--sp-navy)", fontSize: 17 }}>
        Import receipts (IRN)</h2>
      <p style={{ ...small, margin: "0 0 12px" }}>
        Every shipment counted into the Head Office store, at landed cost —
        what came in, what has left the shelf since (store issues to site,
        trading deliveries) and what is still there.</p>
      <Filters f={f} setF={setF} statuses={["DRAFT", "RECEIVED"]} />
      {error && <p style={{ color: "#c0392b" }}>{error}</p>}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead><tr>
            <th style={th}>IRN</th><th style={th}>Date</th>
            <th style={th}>Order / supplier</th><th style={th}>Shipment</th>
            <th style={numTh}>Received</th>
            <th style={numTh} title="Everything that has left the shelf: store
                                     issues, trading deliveries and the rest">
              Gone out</th>
            <th style={numTh}>On hand</th><th style={th}>Store issues</th>
            <th style={th}>Status</th>
          </tr></thead>
          <tbody>
            {(rows || []).map((r) => (
              <tr key={r.ref} onClick={() => onOpenIrn?.(r.ref)}
                  style={{ cursor: onOpenIrn ? "pointer" : "default" }}>
                <td style={{ ...td, fontFamily: "var(--font-mono)", fontSize: 12 }}>
                  {r.ref}<div style={small}>{r.lines} lines</div></td>
                <td style={{ ...td, whiteSpace: "nowrap" }}>{r.doc_date}
                  <div style={small}>{r.created_by}</div></td>
                <td style={td}>{r.iprs.join(", ")}
                  <div style={small}>{r.suppliers.join(", ")}</div></td>
                <td style={td}>{r.shipment}</td>
                <td style={num}>{money(r.value_received)}</td>
                <td style={num}>{money(r.value_out)}</td>
                <td style={{ ...num, fontWeight: Number(r.value_on_hand) ? 600 : 400 }}>
                  {money(r.value_on_hand)}</td>
                <td style={{ ...td, fontSize: 12 }}>{r.sins.join(", ") || "—"}
                  {Number(r.value_on_sins) > 0 && Number(r.value_on_sins) !== Number(r.value_out) && (
                    <div style={small}>{money(r.value_on_sins)} on store issues</div>)}</td>
                <td style={td}><StatusChip status={r.status} /></td>
              </tr>))}
            {rows && rows.length === 0 && (
              <tr><td style={td} colSpan={9}>No receipts match.</td></tr>)}
          </tbody>
          {rows && rows.length > 0 && (
            <tfoot><tr>
              <td style={{ ...td, fontWeight: 600 }} colSpan={4}>
                {rows.length} receipt{rows.length === 1 ? "" : "s"}</td>
              <td style={{ ...num, fontWeight: 600 }}>{money(total("value_received"))}</td>
              <td style={{ ...num, fontWeight: 600 }}>{money(total("value_out"))}</td>
              <td style={{ ...num, fontWeight: 600 }}>{money(total("value_on_hand"))}</td>
              <td style={td} colSpan={2} />
            </tr></tfoot>)}
        </table>
      </div>
    </section>
  );
}

function SinLines({ refText }) {
  const [d, setD] = useState(null);
  useEffect(() => { api(`/sin/${refText}`).then(setD).catch(() => setD({})); },
            [refText]);
  if (!d) return <div style={small}>Loading…</div>;
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
      <thead><tr>
        <th style={th}>Item</th><th style={numTh}>Qty</th>
        <th style={numTh}>Unit cost</th><th style={numTh}>Value</th>
        <th style={th}>From</th><th style={th}>Reserved for</th>
      </tr></thead>
      <tbody>
        {(d.lines || []).map((l) => (
          <tr key={l.id}>
            <td style={td}>{l.description}</td>
            <td style={num}>{money(l.qty)} {l.unit}</td>
            <td style={num}>{money(l.unit_landed_cost)}</td>
            <td style={num}>{money(l.value)}</td>
            <td style={td}>{l.source_irn}</td>
            <td style={td}>{l.reserved_for}</td>
          </tr>))}
      </tbody>
    </table>
  );
}

export function SinRegister({ sites }) {
  const [f, setF] = useState({ q: "", status: "", site: "", from: "", to: "" });
  const [d, setD] = useState(null);
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    api(`/store/issues?register=1&${query(f)}`).then(setD)
      .catch((e) => setError(e.message));
  }, [f]);
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); },
            [load]);

  async function act(path, body, confirmText) {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(true); setError(null);
    try { await api(path, { method: "POST", body }); load(); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  const rows = d?.rows || [];
  const total = (k) => rows.reduce((s, r) => s + Number(r[k] || 0), 0);
  return (
    <section style={card}>
      <h2 style={{ margin: "0 0 4px", color: "var(--sp-navy)", fontSize: 17 }}>
        Store issues (SIN)</h2>
      <p style={{ ...small, margin: "0 0 12px" }}>
        Stock sent from the Head Office store to a site. An issued store issue
        is in transit: put it on a Loading Manifest for its site (Load store
        items) and the site receives it on the GRN, which is when the cost
        lands on the site. Click a row for its items.</p>
      <Filters f={f} setF={setF} sites={sites}
               statuses={["DRAFT", "ISSUED", "RECEIVED", "CANCELLED"]} />
      {error && <p style={{ color: "#c0392b" }}>{error}</p>}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead><tr>
            <th style={th}>SIN</th><th style={th}>Date</th>
            <th style={th}>To site</th><th style={th}>From receipt</th>
            <th style={numTh}>Value</th><th style={th}>Where it is</th>
            <th style={th}>Status</th>
          </tr></thead>
          <tbody>
            {rows.map((r) => (
              <Fragment key={r.ref}>
                <tr onClick={() => setOpen(open === r.ref ? null : r.ref)}
                    style={{ cursor: "pointer" }}>
                  <td style={{ ...td, fontFamily: "var(--font-mono)", fontSize: 12 }}>
                    {open === r.ref ? "▾" : "▸"} {r.ref}
                    <div style={small}>{r.lines} lines</div></td>
                  <td style={{ ...td, whiteSpace: "nowrap" }}>{r.doc_date}
                    <div style={small}>{r.issued_by || r.created_by}</div></td>
                  <td style={td}>{r.to_site}
                    {r.to_project && <div style={small}>{r.to_project}</div>}</td>
                  <td style={{ ...td, fontSize: 12 }}>{r.irns.join(", ") || "Opening stock"}</td>
                  <td style={num}>{money(r.value)}</td>
                  <td style={{ ...td, fontSize: 12 }}>
                    {r.status === "ISSUED" && (r.lms.length
                      ? <>On {r.lms.join(", ")} — the site receives it on the GRN</>
                      : <span style={{ color: "#b26a00" }}>
                          In transit — put it on a Loading Manifest for {r.to_site}
                        </span>)}
                    {r.status === "RECEIVED" && (r.grns.length
                      ? <>Received on {r.grns.join(", ")}</>
                      : <span style={{ color: "#b26a00" }}>
                          Marked received directly (no GRN)</span>)}
                    {r.status === "DRAFT" && "Not issued yet"}
                  </td>
                  <td style={td} onClick={(e) => e.stopPropagation()}>
                    <StatusChip status={r.status} />
                    {r.status === "ISSUED" && d.can_receive && !r.lms.length && (
                      <div><button style={{ ...ghostButton, padding: "2px 8px",
                                            fontSize: 11.5, marginTop: 4 }}
                        disabled={busy}
                        onClick={() => act(`/sin/${r.ref}/receive`, {},
                          `Mark ${r.ref} received at ${r.to_site} without a GRN? `
                          + "Use this only when it did not travel on a manifest.")}>
                        Mark received</button></div>)}
                    {r.received_direct && d.can_reverse && (
                      <div><button style={{ ...ghostButton, padding: "2px 8px",
                                            fontSize: 11.5, marginTop: 4 }}
                        disabled={busy}
                        onClick={() => {
                          const reason = window.prompt(
                            `Put ${r.ref} back in transit so it can go on a `
                            + "Loading Manifest? Its cost comes off the site "
                            + "until the GRN. Reason:");
                          if (reason) act(`/sin/${r.ref}/reverse-receipt`,
                                          { reason });
                        }}>
                        Reverse receipt</button></div>)}
                  </td>
                </tr>
                {open === r.ref && (
                  <tr><td colSpan={7} style={{ ...td, background: "#f7f9fb" }}>
                    <SinLines refText={r.ref} /></td></tr>)}
              </Fragment>))}
            {d && rows.length === 0 && (
              <tr><td style={td} colSpan={7}>No store issues match.</td></tr>)}
          </tbody>
          {rows.length > 0 && (
            <tfoot><tr>
              <td style={{ ...td, fontWeight: 600 }} colSpan={4}>
                {rows.length} store issue{rows.length === 1 ? "" : "s"}</td>
              <td style={{ ...num, fontWeight: 600 }}>{money(total("value"))}</td>
              <td style={td} colSpan={2} />
            </tr></tfoot>)}
        </table>
      </div>
    </section>
  );
}
