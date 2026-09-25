// A vehicle's cost centre — its job cards, the PYRs charged to it and its
// P&L — and the fleet P&L tab (MARINE_BUILD_BRIEF.md §4, phase 6).
import { useEffect, useRef, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";

const fmtDate = (v) => (v ? new Date(v).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "");
const fmtMoney = (v) => (v == null || v === "" ? "" : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const KINDS = [["SERVICE", "Scheduled service"], ["REPAIR", "Repair"], ["INSPECTION", "Inspection"], ["TYRES", "Tyres / tracks"], ["OTHER", "Other"]];
const COSTS = [["RNT_MAINTENANCE", "Maintenance"], ["RNT_FUEL", "Fuel"], ["RNT_OPERATOR", "Operator"], ["RNT_INSURANCE", "Insurance"]];
const PYR_TONE = { DRAFT: "warn", SUBMITTED: "info", APPROVED: "info", AUTHORISED: "info", PAID: "ok", RETURNED: "alert", CANCELLED: "alert", REJECTED: "alert" };
const link = { background: "none", border: 0, color: "var(--sp-navy)", font: "inherit", fontSize: 13, textDecoration: "underline", cursor: "pointer", padding: 0 };

function yearStart() { return iso(new Date(new Date().getFullYear(), 0, 1)); }

// ---- job cards ------------------------------------------------------------------------
function JobCards({ v, jobs, onChanged }) {
  const [adding, setAdding] = useState(false);
  const [d, setD] = useState({ kind: "REPAIR", description: "", hour_meter_at: "", opened_on: iso(new Date()), vendor: "" });
  const [closing, setClosing] = useState(null);
  const [c, setC] = useState({ work_done: "", closed_on: iso(new Date()), hour_meter_at: "", next_service_hours: "", next_service_date: "" });
  const [error, setError] = useState(null);
  async function open(e) {
    e.preventDefault(); setError(null);
    try { await api(`/fleet/vehicles/${v.id}/jobs`, { method: "POST", body: d }); setAdding(false); setD({ ...d, description: "", vendor: "" }); onChanged(); }
    catch (err) { setError(err.message); }
  }
  async function close(e) {
    e.preventDefault(); setError(null);
    try { await api(`/fleet/jobs/${closing}`, { method: "POST", body: { action: "close", ...c } }); setClosing(null); onChanged(); }
    catch (err) { setError(err.message); }
  }
  return (
    <div style={{ ...card, marginTop: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>Job cards</h3>
        {v.can_write && !adding && <Btn variant="secondary" onClick={() => setAdding(true)}>+ Open a job card</Btn>}
      </div>
      {adding && (
        <form onSubmit={open} style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 10px", fontSize: 13, marginTop: 10 }}>
          <select style={inputStyle} value={d.kind} onChange={(e) => setD({ ...d, kind: e.target.value })}>{KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          <input style={inputStyle} type="date" value={d.opened_on} onChange={(e) => setD({ ...d, opened_on: e.target.value })} />
          <textarea style={{ ...inputStyle, gridColumn: "1 / -1", minHeight: 50 }} placeholder="what is wrong / what is due" value={d.description} onChange={(e) => setD({ ...d, description: e.target.value })} required />
          <input style={inputStyle} type="number" step="0.1" placeholder="hour meter now" value={d.hour_meter_at} onChange={(e) => setD({ ...d, hour_meter_at: e.target.value })} />
          <input style={inputStyle} placeholder="workshop / vendor (if outside)" value={d.vendor} onChange={(e) => setD({ ...d, vendor: e.target.value })} />
          <div style={{ gridColumn: "1 / -1", display: "flex", gap: 8 }}><Btn type="submit">Open job card</Btn><Btn type="button" variant="secondary" onClick={() => setAdding(false)}>Cancel</Btn></div>
        </form>
      )}
      {jobs.length === 0 ? <p style={{ fontSize: 13, opacity: .7, marginBottom: 0 }}>No job cards. Open one when the vehicle goes in for service or repair; the PYRs for parts and outside work are charged to it.</p> : (
        <table style={{ width: "100%", fontSize: 13, marginTop: 8, borderCollapse: "collapse" }}>
          <thead><tr><th style={th}>Job</th><th style={th}>What</th><th style={th}>Opened</th><th style={th}>Closed</th><th style={{ ...th, textAlign: "right" }}>Cost</th><th style={th}></th></tr></thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id}>
                <td style={td}><b>{j.ref}</b><div style={{ fontSize: 11, opacity: .7 }}>{j.kind_label}</div></td>
                <td style={td}>{j.description}{j.work_done ? <div style={{ fontSize: 12, opacity: .75 }}>Done: {j.work_done}</div> : null}{j.vendor ? <div style={{ fontSize: 11, opacity: .7 }}>{j.vendor}</div> : null}</td>
                <td style={td}>{fmtDate(j.opened_on)}{j.hour_meter_at ? <div style={{ fontSize: 11, opacity: .7 }}>{j.hour_meter_at} h</div> : null}</td>
                <td style={td}>{j.status === "CLOSED" ? <>{fmtDate(j.closed_on)}<div style={{ fontSize: 11, opacity: .7 }}>{j.downtime_days} day{j.downtime_days === 1 ? "" : "s"} down{j.next_service_hours ? ` · next at ${j.next_service_hours} h` : ""}{j.next_service_date ? ` · ${fmtDate(j.next_service_date)}` : ""}</div></> : <Chip tone="warn">open</Chip>}</td>
                <td style={{ ...td, textAlign: "right" }}>{Number(j.cost) ? fmtMoney(j.cost) : ""}</td>
                <td style={td}>{v.can_write && j.status === "OPEN" && closing !== j.id && <button style={link} onClick={() => setClosing(j.id)}>close</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {closing && (
        <form onSubmit={close} style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 10px", fontSize: 13, marginTop: 10, borderTop: "1px solid var(--line)", paddingTop: 10 }}>
          <b style={{ gridColumn: "1 / -1" }}>Close {jobs.find((j) => j.id === closing)?.ref}</b>
          <textarea style={{ ...inputStyle, gridColumn: "1 / -1", minHeight: 50 }} placeholder="work done" value={c.work_done} onChange={(e) => setC({ ...c, work_done: e.target.value })} required />
          <label>closed on <input style={inputStyle} type="date" value={c.closed_on} onChange={(e) => setC({ ...c, closed_on: e.target.value })} /></label>
          <label>hour meter <input style={inputStyle} type="number" step="0.1" value={c.hour_meter_at} onChange={(e) => setC({ ...c, hour_meter_at: e.target.value })} /></label>
          <label>next service at (h) <input style={inputStyle} type="number" step="0.1" value={c.next_service_hours} onChange={(e) => setC({ ...c, next_service_hours: e.target.value })} /></label>
          <label>next service by <input style={inputStyle} type="date" value={c.next_service_date} onChange={(e) => setC({ ...c, next_service_date: e.target.value })} /></label>
          <div style={{ gridColumn: "1 / -1", display: "flex", gap: 8 }}><Btn type="submit">Close job card</Btn><Btn type="button" variant="secondary" onClick={() => setClosing(null)}>Cancel</Btn></div>
        </form>
      )}
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
    </div>
  );
}

// ---- costs: the PYRs charged to the vehicle ------------------------------------------
function RaiseCost({ v, hoSite, jobs, onSaved, onCancel }) {
  const [heads, setHeads] = useState([]);
  const [d, setD] = useState({ cost_head_id: "", maintenance_job_id: "", payee: "", purpose: "", amount_requested: "", currency: "MVR", payment_method: "BANK", payee_account: "", no_doc_reason: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const file = useRef(null);
  useEffect(() => { api("/cost-heads?rental=1").then(setHeads).catch(() => {}); }, []);
  const set = (k) => (e) => setD({ ...d, [k]: e.target.value });
  async function save(e) {
    e.preventDefault(); setBusy(true); setError(null);
    const hasFile = !!file.current?.files?.[0];
    try {
      const doc = await api("/documents", { method: "POST", body: {
        doc_type: "PYR", site_id: hoSite, payload: {}, payment_type: "DIRECT",
        cost_head_id: Number(d.cost_head_id), vehicle_id: v.id,
        maintenance_job_id: d.maintenance_job_id ? Number(d.maintenance_job_id) : null,
        payee: d.payee, purpose: d.purpose, amount_requested: d.amount_requested, currency: d.currency,
        payment_method: d.payment_method, payee_account: d.payee_account,
        has_supporting_doc: hasFile, no_doc_reason: hasFile ? "" : d.no_doc_reason } });
      if (hasFile) { const fd = new FormData(); fd.append("file", file.current.files[0]); await apiUpload(`/documents/${doc.ref}/attachments`, fd); }
      await api(`/documents/${doc.ref}/actions/submit`, { method: "POST", body: {} });
      onSaved(doc);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={save} style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 10px", fontSize: 13, marginTop: 10, borderTop: "1px solid var(--line)", paddingTop: 10 }}>
      <b style={{ gridColumn: "1 / -1" }}>Charge a cost to {v.fleet_no || v.reg_no} — a payment request on the Head-Office chain</b>
      <select style={inputStyle} value={d.cost_head_id} onChange={set("cost_head_id")} required><option value="">— cost head —</option>{heads.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}</select>
      <select style={inputStyle} value={d.maintenance_job_id} onChange={set("maintenance_job_id")}><option value="">— job card (optional) —</option>{jobs.map((j) => <option key={j.id} value={j.id}>{j.ref} · {j.description.slice(0, 40)}</option>)}</select>
      <input style={inputStyle} placeholder="payee" value={d.payee} onChange={set("payee")} required />
      <div style={{ display: "flex", gap: 6 }}>
        <select style={{ ...inputStyle, width: 80 }} value={d.currency} onChange={set("currency")}><option>MVR</option><option>USD</option></select>
        <input style={inputStyle} type="number" step="0.01" min="0" placeholder="amount" value={d.amount_requested} onChange={set("amount_requested")} required />
      </div>
      <input style={{ ...inputStyle, gridColumn: "1 / -1" }} placeholder="purpose" value={d.purpose} onChange={set("purpose")} required />
      <select style={inputStyle} value={d.payment_method} onChange={set("payment_method")}><option value="BANK">Bank transfer</option><option value="CASH">Cash</option><option value="CHEQUE">Cheque</option></select>
      <input style={inputStyle} placeholder="payee account (if bank)" value={d.payee_account} onChange={set("payee_account")} />
      <label style={{ gridColumn: "1 / -1" }}>bill / quotation <input type="file" ref={file} accept=".pdf,image/*" style={{ fontSize: 12 }} /></label>
      <input style={{ ...inputStyle, gridColumn: "1 / -1" }} placeholder="if no bill attached: why" value={d.no_doc_reason} onChange={set("no_doc_reason")} />
      {error && <p style={{ gridColumn: "1 / -1", color: "var(--red-fg)", margin: 0 }}>{error}</p>}
      <div style={{ gridColumn: "1 / -1", display: "flex", gap: 8 }}><Btn type="submit" disabled={busy}>{busy ? "Raising…" : "Raise and submit"}</Btn><Btn type="button" variant="secondary" onClick={onCancel}>Cancel</Btn></div>
    </form>
  );
}

function PnlTable({ p, single, openVehicle }) {
  const rows = single ? p.rows.filter((r) => r.vehicle) : p.rows;
  return (
    <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
      <thead><tr>
        {!single && <th style={th}>Vehicle</th>}
        <th style={{ ...th, textAlign: "right" }}>Revenue</th>
        {COSTS.map(([c, l]) => <th key={c} style={{ ...th, textAlign: "right" }}>{l}</th>)}
        <th style={{ ...th, textAlign: "right" }}>Other</th>
        <th style={{ ...th, textAlign: "right" }}>Margin</th>
        <th style={{ ...th, textAlign: "right" }}>Days on hire</th>
        <th style={{ ...th, textAlign: "right" }}>Util.</th>
      </tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.vehicle ?? "fleet"}>
            {!single && <td style={td}>{r.vehicle ? <><button style={{ ...link, fontWeight: 700 }} onClick={() => openVehicle?.(r.vehicle)}>{r.fleet_no || r.reg_no}</button> <span style={{ opacity: .7 }}>{r.vehicle_class}</span></> : <i>Fleet, not on a vehicle</i>}</td>}
            <td style={{ ...td, textAlign: "right" }}>{fmtMoney(r.revenue)}</td>
            {COSTS.map(([c]) => <td key={c} style={{ ...td, textAlign: "right" }}>{Number(r.costs[c]) ? fmtMoney(r.costs[c]) : ""}</td>)}
            <td style={{ ...td, textAlign: "right" }}>{Number(r.other_cost) ? fmtMoney(r.other_cost) : ""}</td>
            <td style={{ ...td, textAlign: "right", color: Number(r.margin) < 0 ? "var(--red-fg)" : undefined }}><b>{fmtMoney(r.margin)}</b>{r.margin_pct != null && <div style={{ fontSize: 11, opacity: .7 }}>{r.margin_pct}%</div>}</td>
            <td style={{ ...td, textAlign: "right" }}>{r.hire_days}{r.breakdown_days ? <div style={{ fontSize: 11, color: "var(--red-fg)" }}>{r.breakdown_days} down</div> : null}</td>
            <td style={{ ...td, textAlign: "right" }}>{r.utilisation != null ? `${r.utilisation}%` : ""}</td>
          </tr>
        ))}
        {!single && (
          <tr style={{ fontWeight: 700 }}>
            <td style={td}>Fleet</td>
            <td style={{ ...td, textAlign: "right" }}>{fmtMoney(p.fleet.revenue)}</td>
            {COSTS.map(([c]) => <td key={c} style={{ ...td, textAlign: "right" }}>{Number(p.fleet.costs[c]) ? fmtMoney(p.fleet.costs[c]) : ""}</td>)}
            <td style={{ ...td, textAlign: "right" }}>{Number(p.fleet.other_cost) ? fmtMoney(p.fleet.other_cost) : ""}</td>
            <td style={{ ...td, textAlign: "right", color: Number(p.fleet.margin) < 0 ? "var(--red-fg)" : undefined }}>{fmtMoney(p.fleet.margin)}{p.fleet.margin_pct != null && <div style={{ fontSize: 11, opacity: .7 }}>{p.fleet.margin_pct}%</div>}</td>
            <td style={{ ...td, textAlign: "right" }}>{p.fleet.hire_days}</td>
            <td style={{ ...td, textAlign: "right" }}>{p.fleet.utilisation != null ? `${p.fleet.utilisation}%` : ""}</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

// ---- the vehicle's cost centre (on the vehicle page) -------------------------------
export function VehicleCostCentre({ v }) {
  const [from, setFrom] = useState(yearStart());
  const [to, setTo] = useState(iso(new Date()));
  const [data, setData] = useState(null);
  const [raising, setRaising] = useState(false);
  const [error, setError] = useState(null);
  const load = () => api(`/fleet/vehicles/${v.id}/costs?from=${from}&to=${to}`).then(setData).catch((e) => setError(e.message));
  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [v.id, from, to]);
  if (!data) return error ? <p style={{ color: "var(--red-fg)" }}>{error}</p> : null;
  const open = data.jobs.filter((j) => j.status === "OPEN");
  return (
    <>
      <div style={{ ...card, marginTop: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
          <h3 style={{ margin: 0 }}>Cost centre · P&L</h3>
          <div style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12 }}>
            <input type="date" style={inputStyle} value={from} onChange={(e) => setFrom(e.target.value)} />
            <input type="date" style={inputStyle} value={to} onChange={(e) => setTo(e.target.value)} />
          </div>
        </div>
        <div style={{ overflowX: "auto", marginTop: 8 }}><PnlTable p={data.pnl} single /></div>
        <p style={{ fontSize: 11, opacity: .65, margin: "6px 0 0" }}>MVR. Revenue is the vehicle's share of issued rental invoices; the operator line is the payroll share for the days this vehicle was run; USD at {data.pnl.usd_rate}.</p>
      </div>
      <JobCards v={v} jobs={data.jobs} onChanged={load} />
      <div style={{ ...card, marginTop: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0 }}>Costs charged</h3>
          {data.can_raise && !raising && <Btn variant="secondary" onClick={() => setRaising(true)}>+ Charge a cost</Btn>}
        </div>
        {raising && <RaiseCost v={v} hoSite={data.ho_site} jobs={open} onSaved={() => { setRaising(false); load(); }} onCancel={() => setRaising(false)} />}
        {data.pyrs.length === 0 ? <p style={{ fontSize: 13, opacity: .7, marginBottom: 0 }}>Nothing charged yet. Fuel, parts, workshop bills and insurance for this vehicle are raised here as payment requests.</p> : (
          <table style={{ width: "100%", fontSize: 13, marginTop: 8, borderCollapse: "collapse" }}>
            <thead><tr><th style={th}>PYR</th><th style={th}>Head</th><th style={th}>Payee · purpose</th><th style={th}>Job</th><th style={{ ...th, textAlign: "right" }}>Amount</th><th style={th}>Status</th></tr></thead>
            <tbody>
              {data.pyrs.map((p) => (
                <tr key={p.ref}>
                  <td style={td}><b>{p.ref}</b><div style={{ fontSize: 11, opacity: .7 }}>{fmtDate(p.paid_date || p.doc_date)}</div></td>
                  <td style={td}>{p.cost_head}</td>
                  <td style={td}>{p.payee}<div style={{ fontSize: 12, opacity: .75 }}>{p.purpose}</div></td>
                  <td style={td}>{p.job || ""}</td>
                  <td style={{ ...td, textAlign: "right" }}>{p.currency} {fmtMoney(p.amount)}</td>
                  <td style={td}><Chip tone={PYR_TONE[p.status] || "info"}>{p.status.toLowerCase()}</Chip></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

// ---- the fleet P&L tab -------------------------------------------------------------
export function PnlPanel({ openVehicle }) {
  const [from, setFrom] = useState(yearStart());
  const [to, setTo] = useState(iso(new Date()));
  const [p, setP] = useState(null);
  useEffect(() => { api(`/fleet/pnl?from=${from}&to=${to}`).then(setP).catch(() => setP({ rows: [], fleet: { costs: {} } })); }, [from, to]);
  const month = (off) => { const d = new Date(); const s = new Date(d.getFullYear(), d.getMonth() + off, 1); const e = new Date(d.getFullYear(), d.getMonth() + off + 1, 0); setFrom(iso(s)); setTo(iso(e)); };
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>Vehicle P&L</h2>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <button style={link} onClick={() => month(-1)}>last month</button>
          <button style={link} onClick={() => month(0)}>this month</button>
          <button style={link} onClick={() => { setFrom(yearStart()); setTo(iso(new Date())); }}>year to date</button>
          <input type="date" style={inputStyle} value={from} onChange={(e) => setFrom(e.target.value)} />
          <input type="date" style={inputStyle} value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
      </div>
      {!p ? <p>Loading…</p> : p.rows.length === 0 ? <p style={{ opacity: .7, marginTop: 12 }}>Nothing posted to the fleet in this period.</p> : (
        <div style={{ ...card, marginTop: 12, overflowX: "auto" }}>
          <PnlTable p={p} openVehicle={openVehicle} />
          <p style={{ fontSize: 11, opacity: .65, margin: "8px 0 0" }}>MVR, {p.days} days. Utilisation = days on hire (worked + standby, approved or not) over calendar days. USD postings at {p.usd_rate}. Open a vehicle from the Vehicles tab for its job cards and the costs charged.</p>
        </div>
      )}
    </div>
  );
}
