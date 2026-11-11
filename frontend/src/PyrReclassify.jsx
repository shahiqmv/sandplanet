import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Putting a head-office payment where it belongs (owner 2026-11-10).
// Finance opens an authorised or paid request and says what it really is:
// a currency exchange, a GST payment or a prior-period creditor (none of
// them a cost), a cost under another head, site or project — or the cheque
// that paid a vendor's payables, which the site had already booked as cost
// when the order was signed. The ledger is reversed and re-posted, never
// edited.

const money = (v) => Number(v || 0).toLocaleString("en-US",
  { minimumFractionDigits: 2 });
export const BOOKING_LABEL = {
  COST: "A cost", CURRENCY_EXCHANGE: "Currency exchange",
  GST_SETTLEMENT: "GST / tax payment", PRIOR_PERIOD: "Prior-period creditor",
  PAYABLE_SETTLEMENT: "Settles payables",
};
const panel = { marginTop: 12, padding: 12, borderRadius: 8,
                border: "1px solid var(--line)" };

export function ReclassifyPanel({ doc, onDone, onCancel }) {
  const [opts, setOpts] = useState(null);
  const [f, setF] = useState(null);
  const [projects, setProjects] = useState([]);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api(`/documents/${doc.ref}/reclassify`).then((d) => {
      setOpts(d);
      setProjects(d.projects);
      setF({ booking: d.booking === "PAYABLE_SETTLEMENT" ? "COST" : d.booking,
             cost_head_id: d.cost_head_id || "", site_id: d.site_id,
             project_id: d.project_id || "", shared_cost: d.shared_cost });
    }).catch((e) => setErr(e.message));
  }, [doc.ref]);

  async function siteChanged(id) {
    setF({ ...f, site_id: id, project_id: "" });
    try {
      const d = await api(`/documents/${doc.ref}/reclassify?site=${id}`);
      setProjects(d.projects);
    } catch { setProjects([]); }
  }

  async function save() {
    setBusy(true); setErr(null);
    try {
      const body = { booking: f.booking, reason };
      if (f.booking === "COST") {
        body.cost_head_id = f.cost_head_id || null;
        body.site_id = f.site_id;
        body.project_id = f.project_id || null;
        body.shared_cost = !!f.shared_cost;
      }
      await api(`/documents/${doc.ref}/reclassify`, { method: "POST", body });
      onDone();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  if (!opts || !f) return <div style={panel}>{err || "Loading…"}</div>;
  if (opts.fixed) return <div style={panel}>{opts.fixed}</div>;
  const site = opts.sites.find((s) => String(s.id) === String(f.site_id));
  const isCost = f.booking === "COST";
  return (
    <div style={panel}>
      <div style={{ fontWeight: 700, fontSize: 13.5, marginBottom: 6 }}>
        What is this payment?</div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <label style={{ fontSize: 13 }}>Kind
          <select value={f.booking} style={inputStyle}
                  onChange={(e) => setF({ ...f, booking: e.target.value })}>
            {opts.bookings.map((b) => (
              <option key={b.key} value={b.key}>{b.label}</option>))}
          </select>
        </label>
        {isCost && (
          <label style={{ fontSize: 13 }}>Cost head
            <select value={f.cost_head_id} style={inputStyle}
                    onChange={(e) => setF({ ...f, cost_head_id: e.target.value })}>
              {opts.heads.map((h) => (
                <option key={h.id} value={h.id}>{h.name}</option>))}
            </select>
          </label>)}
        {isCost && (
          <label style={{ fontSize: 13 }}>Site
            <select value={f.site_id} style={inputStyle}
                    onChange={(e) => siteChanged(e.target.value)}>
              {opts.sites.map((s) => (
                <option key={s.id} value={s.id}>{s.code} — {s.name}</option>))}
            </select>
          </label>)}
        {isCost && projects.length > 0 && (
          <label style={{ fontSize: 13 }}>Project
            <select value={f.project_id} style={inputStyle}
                    onChange={(e) => setF({ ...f, project_id: e.target.value })}>
              <option value="">— none —</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.code} — {p.title}</option>))}
            </select>
          </label>)}
      </div>
      {!isCost && (
        <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "8px 0 0" }}>
          {f.booking === "CURRENCY_EXCHANGE"
            && "Rufiyaa paid for dollars, or dollars for rufiyaa: money in one currency for money in another. Nobody's cost."}
          {f.booking === "GST_SETTLEMENT"
            && "GST collected from clients and handed on to MIRA. Not a cost."}
          {f.booking === "PRIOR_PERIOD"
            && "A balance owed from before the books started. It belongs to the earlier year's accounts, not to this year's cost."}
          {site && !site.is_head_office && " It stays at head office."}
        </p>)}
      <label style={{ fontSize: 13, display: "block", marginTop: 8 }}>
        Why
        <input value={reason} onChange={(e) => setReason(e.target.value)}
               placeholder="e.g. dollars bought for October salaries"
               style={inputStyle} />
      </label>
      {err && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{err}</p>}
      <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
        <Btn variant="navy" onClick={save} disabled={busy || !reason.trim()}>
          Reclassify</Btn>
        <button onClick={onCancel} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}

export function ApplyPayablesPanel({ doc, onDone, onCancel }) {
  const [data, setData] = useState(null);
  const [picked, setPicked] = useState({});
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api(`/documents/${doc.ref}/apply-to-payables`).then((d) => {
      setData(d);
      // the vendor's own payables are ticked to start with, oldest first,
      // while they fit the amount paid
      const pre = {};
      let left = Number(d.paid);
      d.payables.filter((p) => p.vendor_match).forEach((p) => {
        if (Number(p.amount) <= left + 0.005) {
          pre[p.payable_id] = true; left -= Number(p.amount);
        }
      });
      setPicked(pre);
    }).catch((e) => setErr(e.message));
  }, [doc.ref]);

  if (!data) return <div style={panel}>{err || "Loading…"}</div>;
  if (data.fixed) return <div style={panel}>{data.fixed}</div>;
  const rows = data.payables;
  const chosen = rows.filter((p) => picked[p.payable_id]);
  const total = chosen.reduce((s, p) => s + Number(p.amount), 0);
  const paid = Number(data.paid);
  const over = total > paid + 0.005;

  async function save() {
    setBusy(true); setErr(null);
    try {
      await api(`/documents/${doc.ref}/apply-to-payables`, { method: "POST",
        body: { payable_ids: chosen.map((p) => p.payable_id), reason } });
      onDone();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div style={panel}>
      <div style={{ fontWeight: 700, fontSize: 13.5 }}>
        Which payables did this payment settle?</div>
      <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "4px 0 8px" }}>
        {data.currency} {money(paid)} paid to {data.payee}. Tick the invoices
        on the vendor's statement. The request's own cost is reversed and the
        orders are marked paid at their sites, where the cost already sits.
      </p>
      {rows.length === 0 && (
        <p style={{ fontSize: 13 }}>No open {data.currency} payables on
          orders. If the vendor is owed, the orders were never raised in
          Planet — reclassify this as a prior-period creditor instead.</p>)}
      {rows.length > 0 && (
        <div style={{ maxHeight: 320, overflow: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 12.5 }}>
            <thead><tr>
              <th style={th}></th><th style={th}>Vendor</th>
              <th style={th}>Order</th><th style={th}>Site</th>
              <th style={th}>Due</th>
              <th style={{ ...th, textAlign: "right" }}>Amount</th>
            </tr></thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.payable_id}
                    style={{ opacity: p.vendor_match ? 1 : 0.7 }}>
                  <td style={td}>
                    <input type="checkbox" checked={!!picked[p.payable_id]}
                           onChange={(e) => setPicked({ ...picked,
                             [p.payable_id]: e.target.checked })} /></td>
                  <td style={td}>{p.vendor}</td>
                  <td style={td}>{p.po_ref || p.ref}</td>
                  <td style={td}>{p.site}</td>
                  <td style={td}>{p.due_date || "—"}</td>
                  <td style={{ ...td, textAlign: "right",
                               fontFamily: "var(--font-mono)" }}>
                    {money(p.amount)}</td>
                </tr>))}
            </tbody>
          </table>
        </div>)}
      {rows.length > 0 && (
        <div style={{ marginTop: 8, fontSize: 13,
                      color: over ? "var(--red-fg)" : "inherit" }}>
          Ticked {chosen.length}: {data.currency} {money(total)} of{" "}
          {money(paid)} paid
          {!over && total < paid - 0.005
            && ` — ${money(paid - total)} not matched to an order`}
          {over && " — more than was paid"}
        </div>)}
      <label style={{ fontSize: 13, display: "block", marginTop: 8 }}>
        Why
        <input value={reason} onChange={(e) => setReason(e.target.value)}
               placeholder="e.g. cheque 517 against Sonee statement to 30 Sep"
               style={inputStyle} />
      </label>
      {err && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{err}</p>}
      <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
        <Btn variant="navy" onClick={save}
             disabled={busy || over || chosen.length === 0 || !reason.trim()}>
          Apply to {chosen.length} payable{chosen.length === 1 ? "" : "s"}</Btn>
        <button onClick={onCancel} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}
