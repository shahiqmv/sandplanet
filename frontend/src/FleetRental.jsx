// Rental agreements and the daily register (MARINE_BUILD_BRIEF.md §4).
// An agreement puts vehicles on hire with a customer at agreed daily
// rates; the register records each vehicle's day and the customer's
// representative approves it; invoices bill the approved days.
import { useEffect, useRef, useState } from "react";
import { api, apiUpload } from "./api.js";
import { API_BASE } from "./brand.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";
import { AgreementInvoices } from "./FleetMoney.jsx";
import { CustomerDetails, CustomerForm } from "./FleetCustomers.jsx";

const fmtDate = (v) => (v ? new Date(v).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "");
const fmtMoney = (v) => (v == null || v === "" ? "" : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const STATUS_TONE = { DRAFT: "warn", ACTIVE: "ok", COMPLETED: "info", TERMINATED: "alert" };
const STATES = [["", "—"], ["WORKED", "Worked"], ["STANDBY", "Standby"], ["BREAKDOWN", "Breakdown"], ["OFF_HIRE", "Off hire"]];
const STATE_SHORT = { WORKED: "W", STANDBY: "S", BREAKDOWN: "B", OFF_HIRE: "O" };
const STATE_BG = { WORKED: "#e6f3ea", STANDBY: "#eaf3f9", BREAKDOWN: "#fdecec", OFF_HIRE: "#f1f1f1" };

function Field({ label, children, wide }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13, marginBottom: 10, gridColumn: wide ? "1 / -1" : undefined }}>
      <span style={{ fontWeight: 600, opacity: .8 }}>{label}</span>{children}
    </label>
  );
}

// ---- customers (the hirer; the record lives on the Customers tab) --------------
function CustomerPicker({ value, onChange }) {
  const [list, setList] = useState([]);
  const [clients, setClients] = useState([]);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);
  const load = () => Promise.all([api("/fleet/customers").then(setList), api("/fleet/project-clients").then(setClients)]).catch(() => {});
  useEffect(() => { load(); }, []);
  const chosen = list.find((c) => String(c.id) === String(value));
  // A project client who is not yet a customer: picking them makes the
  // customer record from the site's client block — nothing typed twice.
  async function pick(v) {
    setError(null);
    if (!v.startsWith("site:")) { onChange(v); return; }
    try { const c = await api("/fleet/customers", { method: "POST", body: { from_site: Number(v.slice(5)) } }); await load(); onChange(String(c.id)); }
    catch (e) { setError(e.message); }
  }
  const newClients = clients.filter((c) => !c.customer);
  return (
    <div>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
        <Field label="Customer (the hirer)">
          <select style={{ ...inputStyle, minWidth: 300 }} value={value} onChange={(e) => pick(e.target.value)} required>
            <option value="">— pick —</option>
            <optgroup label="Customers">
              {list.map((c) => <option key={c.id} value={c.id}>{c.name}{c.project_client_code ? ` · our client at ${c.project_client_code}` : ""}</option>)}
            </optgroup>
            {newClients.length > 0 && (
              <optgroup label="Our project clients (not yet a customer — pick to use their record)">
                {newClients.map((c) => <option key={c.site} value={`site:${c.site}`}>{c.name} · {c.code}</option>)}
              </optgroup>
            )}
          </select>
        </Field>
        {!adding && <Btn type="button" variant="ghost" onClick={() => setAdding(true)} style={{ marginBottom: 10 }}>+ new customer</Btn>}
      </div>
      {adding && <CustomerForm compact onSaved={async (c) => { await load(); onChange(String(c.id)); setAdding(false); }} onCancel={() => setAdding(false)} />}
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      {chosen && (
        <div style={{ fontSize: 12, marginTop: -4, marginBottom: 10 }}>
          <CustomerDetails c={{ address: chosen.billing_address, tin: chosen.tin, reg_no: chosen.business_reg_no, contact: chosen.contact_person,
                                phone: chosen.phone, email: chosen.email, credit_days: chosen.credit_days, gst_exempt: chosen.gst_exempt,
                                project_client: chosen.project_client_code ? { code: chosen.project_client_code } : null }} />
          {!chosen.tin && !chosen.gst_exempt && <div style={{ color: "var(--amber-fg, #8a5a00)", marginTop: 4 }}>No GST TIN on this customer — a tax invoice will need it. Add it on the Customers tab.</div>}
        </div>
      )}
    </div>
  );
}

// ---- agreement form --------------------------------------------------------------
const EMPTY = { customer: "", title: "", site_location: "", start_date: "", end_date: "", billing_cycle: "MONTHLY",
                currency: "MVR", deposit: "", mobilisation_charge: "", demobilisation_charge: "", customer_rep: "",
                customer_rep_phone: "", customer_po: "", payment_terms: "", extra_terms: "", notes: "" };

function AgreementForm({ initial, onSaved, onCancel }) {
  const [d, setD] = useState({ ...EMPTY, ...(initial || {}) });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => { if (!initial) api("/fleet/terms").then((t) => setD((x) => ({ ...x, payment_terms: t.payment_terms, extra_terms: t.extra_terms }))).catch(() => {}); }, [initial]);
  const set = (k) => (e) => setD({ ...d, [k]: e.target.value });
  const active = initial?.status === "ACTIVE";
  async function save(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    const body = { ...d };
    ["deposit", "mobilisation_charge", "demobilisation_charge"].forEach((k) => { if (body[k] === "" || body[k] == null) body[k] = "0"; });
    if (!body.end_date) body.end_date = null;
    if (!body.start_date) body.start_date = null;
    delete body.vehicles;
    try {
      if (initial?.id) {
        const allowed = active ? ["customer_rep", "customer_rep_phone", "customer_po", "notes", "end_date", "site_location"] : Object.keys(EMPTY).filter((k) => k !== "customer");
        onSaved(await api(`/fleet/agreements/${initial.id}`, { method: "PATCH", body: Object.fromEntries(allowed.map((k) => [k, body[k]])) }));
      } else {
        onSaved(await api("/fleet/agreements", { method: "POST", body: { ...body, customer: Number(body.customer) } }));
      }
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={save} style={{ ...card, marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>{initial?.id ? `Edit ${initial.ref}` : "New hire agreement"}</h3>
      {!initial?.id && <CustomerPicker value={d.customer} onChange={(v) => setD({ ...d, customer: v })} />}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", columnGap: 16 }}>
        <Field label="Job / purpose" wide><input style={inputStyle} value={d.title} onChange={set("title")} disabled={active} placeholder="e.g. Harbour reclamation works" /></Field>
        <Field label="Site / location"><input style={inputStyle} value={d.site_location} onChange={set("site_location")} /></Field>
        <Field label="Customer's PO"><input style={inputStyle} value={d.customer_po} onChange={set("customer_po")} /></Field>
        <Field label="Hire starts"><input style={inputStyle} type="date" value={d.start_date || ""} onChange={set("start_date")} disabled={active} /></Field>
        <Field label="Hire ends (blank = open-ended)"><input style={inputStyle} type="date" value={d.end_date || ""} onChange={set("end_date")} /></Field>
        <Field label="Billing">
          <select style={inputStyle} value={d.billing_cycle} onChange={set("billing_cycle")} disabled={active}>
            <option value="MONTHLY">Monthly, in arrears</option><option value="ON_COMPLETION">On completion</option>
          </select></Field>
        <Field label="Currency"><select style={inputStyle} value={d.currency} onChange={set("currency")} disabled={active}><option>MVR</option><option>USD</option></select></Field>
        <Field label="Customer's representative (approves the register)"><input style={inputStyle} value={d.customer_rep} onChange={set("customer_rep")} /></Field>
        <Field label="Representative's phone"><input style={inputStyle} value={d.customer_rep_phone} onChange={set("customer_rep_phone")} /></Field>
        <Field label="Security deposit"><input style={inputStyle} type="number" min="0" step="0.01" value={d.deposit ?? ""} onChange={set("deposit")} disabled={active} /></Field>
        <Field label="Mobilisation charge"><input style={inputStyle} type="number" min="0" step="0.01" value={d.mobilisation_charge ?? ""} onChange={set("mobilisation_charge")} disabled={active} /></Field>
        <Field label="Demobilisation charge"><input style={inputStyle} type="number" min="0" step="0.01" value={d.demobilisation_charge ?? ""} onChange={set("demobilisation_charge")} disabled={active} /></Field>
        <Field label="Payment terms" wide><input style={inputStyle} value={d.payment_terms} onChange={set("payment_terms")} disabled={active} /></Field>
        <Field label="Conditions of hire — one per line" wide><textarea style={{ ...inputStyle, minHeight: 90 }} value={d.extra_terms} onChange={set("extra_terms")} disabled={active} /></Field>
        <Field label="Notes (internal)" wide><textarea style={{ ...inputStyle, minHeight: 50 }} value={d.notes} onChange={set("notes")} /></Field>
      </div>
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      <div style={{ display: "flex", gap: 8 }}>
        <Btn type="submit" disabled={busy || (!initial?.id && !d.customer)}>{busy ? "Saving…" : "Save agreement"}</Btn>
        <Btn type="button" variant="secondary" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}

// ---- agreement vehicles ---------------------------------------------------------
function VehicleLines({ a, onSaved }) {
  const [fleet, setFleet] = useState([]);
  const [rows, setRows] = useState(a.vehicles.map((v) => ({ ...v })));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => { api("/fleet/vehicles").then(setFleet).catch(() => {}); }, []);
  useEffect(() => { setRows(a.vehicles.map((v) => ({ ...v }))); setDirty(false); }, [a]);
  const editable = a.can_write && a.status !== "COMPLETED" && a.status !== "TERMINATED";
  function add(vid) {
    const v = fleet.find((x) => String(x.id) === String(vid));
    if (!v || rows.some((r) => r.vehicle === v.id)) return;
    setRows([...rows, { vehicle: v.id, reg_no: v.reg_no, fleet_no: v.fleet_no, vehicle_class: v.vehicle_class, card_rate: v.rate_daily,
                        rate_daily: v.rate_daily || "", operator_included: v.operator_included, operator_rate_daily: "", from_date: "", to_date: "", notes: "" }]);
    setDirty(true);
  }
  const upd = (i, patch) => { setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r))); setDirty(true); };
  async function save() {
    setBusy(true); setError(null);
    try {
      onSaved(await api(`/fleet/agreements/${a.id}/vehicles`, { method: "PUT", body: { vehicles: rows.map((r) => ({
        vehicle: r.vehicle, rate_daily: r.rate_daily, operator_included: r.operator_included,
        operator_rate_daily: r.operator_rate_daily || null, from_date: r.from_date || null, to_date: r.to_date || null, notes: r.notes })) } }));
      setDirty(false);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return (
    <div style={{ ...card, marginTop: 12 }}>
      <h3 style={{ marginTop: 0 }}>Vehicles on hire</h3>
      {rows.length === 0 ? <p style={{ fontSize: 13, opacity: .7 }}>No vehicles yet.</p> : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead><tr><th style={th}>Vehicle</th><th style={{ ...th, textAlign: "right" }}>Card rate</th><th style={{ ...th, textAlign: "right" }}>Agreed / day</th>
            <th style={th}>Operator</th><th style={th}>From</th><th style={th}>To</th><th style={th}></th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.vehicle}>
                <td style={td}><b>{r.fleet_no || r.reg_no}</b> <span style={{ opacity: .7 }}>{r.vehicle_class}</span>{r.register_days ? <div style={{ fontSize: 11, opacity: .7 }}>{r.register_days} register days</div> : null}</td>
                <td style={{ ...td, textAlign: "right" }}>{fmtMoney(r.card_rate)}</td>
                <td style={td}><input type="number" min="0" step="0.01" value={r.rate_daily ?? ""} disabled={!editable || !a.can_manage}
                                      onChange={(e) => upd(i, { rate_daily: e.target.value })} style={{ ...inputStyle, width: 110, textAlign: "right", padding: "4px 6px" }} /></td>
                <td style={td}>
                  <label style={{ fontSize: 12 }}><input type="checkbox" checked={!!r.operator_included} disabled={!editable} onChange={(e) => upd(i, { operator_included: e.target.checked })} /> included</label>
                  {!r.operator_included && <input type="number" min="0" step="0.01" placeholder="/ day" value={r.operator_rate_daily ?? ""} disabled={!editable}
                                                  onChange={(e) => upd(i, { operator_rate_daily: e.target.value })} style={{ ...inputStyle, width: 90, padding: "4px 6px", marginLeft: 6 }} />}
                </td>
                <td style={td}><input type="date" value={r.from_date || ""} disabled={!editable} onChange={(e) => upd(i, { from_date: e.target.value })} style={{ ...inputStyle, padding: "4px 6px" }} /></td>
                <td style={td}><input type="date" value={r.to_date || ""} disabled={!editable} onChange={(e) => upd(i, { to_date: e.target.value })} style={{ ...inputStyle, padding: "4px 6px" }} /></td>
                <td style={td}>{editable && !r.register_days && <button style={{ background: "none", border: 0, cursor: "pointer", color: "var(--red-fg)" }} onClick={() => { setRows(rows.filter((_, j) => j !== i)); setDirty(true); }}>×</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editable && (
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 10, flexWrap: "wrap" }}>
          <select style={inputStyle} value="" onChange={(e) => add(e.target.value)}>
            <option value="">+ add a vehicle…</option>
            {fleet.filter((v) => !rows.some((r) => r.vehicle === v.id)).map((v) => (
              <option key={v.id} value={v.id}>{v.fleet_no || v.reg_no} · {v.vehicle_class}{v.status !== "AVAILABLE" ? ` (${v.status.toLowerCase().replace("_", " ")})` : ""}</option>
            ))}
          </select>
          <Btn onClick={save} disabled={busy || !dirty}>{busy ? "Saving…" : dirty ? "Save vehicles" : "Saved"}</Btn>
          {!a.can_manage && <span style={{ fontSize: 12, opacity: .7 }}>Rates come from the card; the Rental Manager can negotiate them.</span>}
        </div>
      )}
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
    </div>
  );
}

// ---- the daily register --------------------------------------------------------
function Register({ a }) {
  // Local calendar dates: toISOString() is UTC and turns Maldives midnight
  // on the 1st into the 31st of the month before.
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const today = new Date();
  const [from, setFrom] = useState(iso(new Date(today.getFullYear(), today.getMonth(), 1)));
  const [to, setTo] = useState(iso(today));
  const [g, setG] = useState(null);
  const [cells, setCells] = useState({});
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [rep, setRep] = useState(a.customer_rep || "");
  const file = useRef(null);
  const load = () => api(`/fleet/agreements/${a.id}/register?from=${from}&to=${to}`).then((d) => { setG(d); setCells({}); setDirty(false); }).catch((e) => setError(e.message));
  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [a.id, from, to]);
  const key = (line, date) => `${line}|${date}`;
  const cellOf = (ln, c) => cells[key(ln.line, c.date)] || c;
  function setCell(ln, c, patch) { setCells({ ...cells, [key(ln.line, c.date)]: { ...cellOf(ln, c), ...patch } }); setDirty(true); }
  async function save() {
    setBusy(true); setError(null);
    const rows = Object.entries(cells).map(([k, v]) => { const [line, date] = k.split("|"); return { line: Number(line), date, state: v.state, hours: v.hours || null, operator: v.operator || null, remarks: v.remarks || "" }; });
    try { await api(`/fleet/agreements/${a.id}/register?from=${from}&to=${to}`, { method: "PUT", body: { rows } }); await load(); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function approve(reopen = false) {
    if (dirty) { setError("Save the register before approving."); return; }
    if (!reopen && !window.confirm(`Approve every recorded day from ${fmtDate(from)} to ${fmtDate(to)} as ${rep || a.customer_rep}?`)) return;
    const fd = new FormData();
    fd.append("from", from); fd.append("to", to); fd.append("approved_by", rep);
    if (reopen) fd.append("action", "reopen");
    if (file.current?.files?.[0]) { fd.append("file", file.current.files[0]); fd.append("via", "PAPER"); }
    setBusy(true); setError(null);
    try { await apiUpload(`/fleet/agreements/${a.id}/register/approve`, fd); await load(); if (file.current) file.current.value = ""; }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  if (!g) return error ? <p style={{ color: "var(--red-fg)" }}>{error}</p> : <p>Loading…</p>;
  const editable = a.can_write && a.status === "ACTIVE";
  return (
    <div style={{ ...card, marginTop: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
        <h3 style={{ margin: 0 }}>Daily register</h3>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input type="date" style={inputStyle} value={from} onChange={(e) => setFrom(e.target.value)} />
          <input type="date" style={inputStyle} value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
      </div>
      <p style={{ fontSize: 12, opacity: .7, margin: "6px 0" }}>W worked · S standby (billable) · B breakdown · O off hire. ✓ = approved by the customer's representative; approved days are locked.</p>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 12 }}>
          <thead><tr>
            <th style={{ ...th, position: "sticky", left: 0, background: "var(--paper)" }}>Vehicle</th>
            {g.days.map((d) => <th key={d} style={{ ...th, textAlign: "center", padding: "4px 3px", minWidth: 34 }}>{new Date(d).getDate()}</th>)}
            <th style={{ ...th, textAlign: "right" }}>Billable</th><th style={{ ...th, textAlign: "right" }}>Approved</th>
          </tr></thead>
          <tbody>
            {g.lines.map((ln) => (
              <tr key={ln.line}>
                <td style={{ ...td, position: "sticky", left: 0, background: "var(--paper)", whiteSpace: "nowrap" }}><b>{ln.fleet_no || ln.reg_no}</b><div style={{ fontSize: 11, opacity: .7 }}>{ln.vehicle_class}</div></td>
                {ln.cells.map((c) => {
                  const cur = cellOf(ln, c);
                  const locked = !editable || c.approved || c.invoiced || !c.in_period;
                  return (
                    <td key={c.date} title={`${fmtDate(c.date)}${c.approved ? ` · approved by ${c.approved_by}` : ""}${cur.remarks ? ` · ${cur.remarks}` : ""}`}
                        style={{ padding: 2, textAlign: "center", background: cur.state ? STATE_BG[cur.state] : (c.in_period ? "transparent" : "#f6f6f6"), borderBottom: "1px solid var(--row-line)" }}>
                      {locked ? <span style={{ fontWeight: 600 }}>{STATE_SHORT[cur.state] || ""}{c.approved && cur.state ? "✓" : ""}</span> : (
                        <select value={cur.state || ""} onChange={(e) => setCell(ln, c, { state: e.target.value })}
                                style={{ border: 0, background: "transparent", font: "inherit", width: 30, padding: 0, textAlign: "center" }}>
                          {STATES.map(([v, l]) => <option key={v} value={v}>{v ? STATE_SHORT[v] : "—"}{v ? "" : ""}</option>)}
                        </select>
                      )}
                    </td>
                  );
                })}
                <td style={{ ...td, textAlign: "right" }}>{ln.billable_days}</td>
                <td style={{ ...td, textAlign: "right" }}>{ln.approved_days}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editable && (
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginTop: 10 }}>
          <Btn onClick={save} disabled={busy || !dirty}>{busy ? "Saving…" : dirty ? "Save register" : "Saved"}</Btn>
          <span style={{ opacity: .5 }}>|</span>
          <input style={{ ...inputStyle, width: 200 }} placeholder="approved by (customer's rep)" value={rep} onChange={(e) => setRep(e.target.value)} />
          <input type="file" ref={file} accept=".pdf,image/*" style={{ fontSize: 12 }} title="signed paper register, if any" />
          <Btn variant="secondary" onClick={() => approve(false)} disabled={busy || dirty}>Approve {fmtDate(from)} – {fmtDate(to)}</Btn>
          {a.can_manage && <button style={{ background: "none", border: 0, color: "var(--muted)", cursor: "pointer", fontSize: 12 }} onClick={() => approve(true)}>reopen approved days</button>}
        </div>
      )}
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
    </div>
  );
}

// ---- agreement detail -----------------------------------------------------------
function AgreementDetail({ id, onBack }) {
  const [a, setA] = useState(null);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState(null);
  const signed = useRef(null);
  const load = () => api(`/fleet/agreements/${id}`).then(setA).catch((e) => setError(e.message));
  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [id]);
  async function act(action, extra = {}) {
    if (action === "terminate") { const r = window.prompt("Why is the agreement terminated?"); if (!r) return; extra.reason = r; }
    if (action === "complete" && !window.confirm("Mark the hire completed? The vehicles come off hire.")) return;
    try { setA(await api(`/fleet/agreements/${id}/action`, { method: "POST", body: { action, ...extra } })); }
    catch (e) { setError(e.message); }
  }
  async function uploadSigned() {
    const fd = new FormData(); fd.append("action", "signed"); fd.append("file", signed.current.files[0]);
    try { setA(await apiUpload(`/fleet/agreements/${id}/action`, fd)); } catch (e) { setError(e.message); }
  }
  if (!a) return error ? <p style={{ color: "var(--red-fg)" }}>{error}</p> : <p>Loading…</p>;
  if (editing) return <AgreementForm initial={a} onSaved={(na) => { setA(na); setEditing(false); }} onCancel={() => setEditing(false)} />;
  return (
    <div>
      <button style={{ background: "none", border: 0, color: "var(--sp-navy)", cursor: "pointer", padding: 0 }} onClick={onBack}>← Agreements</button>
      <div style={{ ...card, marginTop: 8 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
          <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>{a.ref} <span style={{ fontWeight: 500, fontSize: 18 }}>{a.customer_name}</span></h2>
          <Chip tone={STATUS_TONE[a.status]}>{a.status.toLowerCase()}</Chip>
        </div>
        <div style={{ fontSize: 13.5, marginTop: 6 }}>{a.title}{a.site_location ? ` · ${a.site_location}` : ""}</div>
        <CustomerDetails c={a.customer_info} />
        <div style={{ fontSize: 13, opacity: .8, marginTop: 4 }}>
          {a.start_date ? fmtDate(a.start_date) : "start?"} → {a.end_date ? fmtDate(a.end_date) : "open-ended"} · {a.billing_cycle === "MONTHLY" ? "monthly in arrears" : "on completion"} · {a.currency}
          {a.customer_rep && <> · rep {a.customer_rep}{a.customer_rep_phone ? ` (${a.customer_rep_phone})` : ""}</>}
          {a.customer_po && <> · PO {a.customer_po}</>}
        </div>
        {(Number(a.deposit) || Number(a.mobilisation_charge) || Number(a.demobilisation_charge)) ? (
          <div style={{ fontSize: 13, marginTop: 4 }}>
            {Number(a.deposit) ? `Deposit ${a.currency} ${fmtMoney(a.deposit)}` : ""}{Number(a.mobilisation_charge) ? ` · mobilisation ${fmtMoney(a.mobilisation_charge)}` : ""}{Number(a.demobilisation_charge) ? ` · demobilisation ${fmtMoney(a.demobilisation_charge)}` : ""}
          </div>
        ) : null}
        {a.close_reason && <p style={{ fontSize: 13 }}>Closed: {a.close_reason}</p>}
        <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap", alignItems: "center" }}>
          <a className="btn btn-secondary" href={`${API_BASE}/fleet/agreements/${id}/pdf`} target="_blank" rel="noreferrer" style={{ textDecoration: "none" }}>{a.status === "DRAFT" ? "Draft PDF" : "Agreement PDF"}</a>
          {a.can_write && a.status !== "COMPLETED" && a.status !== "TERMINATED" && <Btn variant="secondary" onClick={() => setEditing(true)}>Edit</Btn>}
          {a.can_manage && a.status === "DRAFT" && <Btn onClick={() => act("activate")}>Activate — vehicles go on hire</Btn>}
          {a.can_manage && a.status === "ACTIVE" && <><Btn variant="secondary" onClick={() => act("complete")}>Complete</Btn><Btn variant="danger" onClick={() => act("terminate")}>Terminate</Btn></>}
          {a.can_write && a.status !== "DRAFT" && (
            <label style={{ fontSize: 12 }}>signed copy: {a.signed_copy ? <a href={a.signed_copy} target="_blank" rel="noreferrer">on file</a> : "none"}{" "}
              <input type="file" ref={signed} accept=".pdf,image/*" onChange={uploadSigned} style={{ fontSize: 12 }} /></label>
          )}
        </div>
        {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      </div>
      <VehicleLines a={a} onSaved={setA} />
      {a.status !== "DRAFT" && <Register a={a} />}
      {a.status !== "DRAFT" && <AgreementInvoices a={a} />}
    </div>
  );
}

// ---- list ---------------------------------------------------------------------------
export default function AgreementsPanel({ initialOpen = null, onOpened }) {
  const [rows, setRows] = useState(null);
  const [status, setStatus] = useState("open");
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState(initialOpen);
  useEffect(() => { if (initialOpen) { setOpen(initialOpen); onOpened?.(); } }, [initialOpen, onOpened]);
  const [canWrite, setCanWrite] = useState(false);
  function load() {
    const q = new URLSearchParams(); if (status) q.set("status", status); if (search.trim()) q.set("search", search.trim());
    api(`/fleet/agreements?${q}`).then(setRows).catch(() => setRows([]));
  }
  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [status, search]);
  useEffect(() => { api("/fleet/summary").then((s) => setCanWrite(s.can_write)).catch(() => {}); }, []);
  if (open) return <AgreementDetail id={open} onBack={() => { setOpen(null); load(); }} />;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>Hire agreements</h2>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <input style={{ ...inputStyle, width: 220 }} placeholder="Search ref, customer, job…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <select style={inputStyle} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="open">Open</option><option value="DRAFT">Draft</option><option value="ACTIVE">Active</option>
            <option value="COMPLETED">Completed</option><option value="TERMINATED">Terminated</option><option value="">All</option>
          </select>
          {canWrite && !creating && <Btn onClick={() => setCreating(true)}>+ New agreement</Btn>}
        </div>
      </div>
      {creating && <AgreementForm onSaved={(a) => { setCreating(false); setOpen(a.id); }} onCancel={() => setCreating(false)} />}
      {rows === null ? <p>Loading…</p> : rows.length === 0 ? <p style={{ opacity: .7, marginTop: 12 }}>No agreements{status ? " in this state" : ""}. A hire agreement puts vehicles on hire with a customer; the daily register runs under it.</p> : (
        <table style={{ width: "100%", borderCollapse: "collapse", background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 8, marginTop: 12 }}>
          <thead><tr><th style={th}>Agreement</th><th style={th}>Customer</th><th style={th}>Job · site</th><th style={th}>Period</th><th style={th}>Status</th>
            <th style={{ ...th, textAlign: "right" }}>Vehicles</th><th style={{ ...th, textAlign: "right" }}>Unapproved days</th></tr></thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id} style={{ cursor: "pointer" }} onClick={() => setOpen(a.id)}>
                <td style={td}><b>{a.ref}</b></td>
                <td style={td}>{a.customer_name}</td>
                <td style={td}>{a.title}{a.site_location ? <div style={{ fontSize: 12, opacity: .7 }}>{a.site_location}</div> : null}</td>
                <td style={td}>{fmtDate(a.start_date) || "—"} → {a.end_date ? fmtDate(a.end_date) : "open"}</td>
                <td style={td}><Chip tone={STATUS_TONE[a.status]}>{a.status.toLowerCase()}</Chip></td>
                <td style={{ ...td, textAlign: "right" }}>{a.n_vehicles}</td>
                <td style={{ ...td, textAlign: "right" }}>{a.unapproved_days ? <Chip tone="warn">{a.unapproved_days}</Chip> : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
