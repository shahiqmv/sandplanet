// The rental fleet (MARINE_BUILD_BRIEF.md §4): the vehicle register, each
// vehicle's rate card and documents, and the expiry watch. Shown only on
// an instance with the rental module switched on.
import { useEffect, useRef, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";
import AgreementsPanel from "./FleetRental.jsx";
import { InvoicesPanel, ReceivablesPanel } from "./FleetMoney.jsx";

const STATUS = [["AVAILABLE", "Available"], ["ON_HIRE", "On hire"], ["MAINTENANCE", "In maintenance"],
                ["OFF_ROAD", "Off road"], ["DISPOSED", "Disposed"]];
const STATUS_LABEL = Object.fromEntries(STATUS);
const STATUS_TONE = { AVAILABLE: "ok", ON_HIRE: "info", MAINTENANCE: "warn", OFF_ROAD: "alert", DISPOSED: "alert" };
const DOC_KINDS = [["REGISTRATION", "Registration"], ["INSURANCE", "Insurance"], ["ROADWORTHINESS", "Roadworthiness"],
                   ["PERMIT", "Permit / licence"], ["OTHER", "Other"]];
const DOC_TONE = { ok: "ok", d30: "warn", d7: "alert", overdue: "alert", none: "info" };
const DOC_LABEL = { ok: "valid", d30: "expires within 30 days", d7: "expires within 7 days", overdue: "EXPIRED", none: "no expiry" };

const fmtDate = (v) => (v ? new Date(v).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "");
const fmtMoney = (v) => (v == null || v === "" ? "" : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

function Field({ label, children, wide }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13, marginBottom: 10,
                    gridColumn: wide ? "1 / -1" : undefined }}>
      <span style={{ fontWeight: 600, opacity: .8 }}>{label}</span>{children}
    </label>
  );
}

const EMPTY = { reg_no: "", fleet_no: "", vehicle_class: "", make: "", model: "", year: "", capacity: "",
                engine_no: "", chassis_no: "", status: "AVAILABLE", rate_currency: "MVR", rate_hourly: "",
                rate_daily: "", rate_weekly: "", rate_monthly: "", operator_included: true,
                operator_rate_daily: "", minimum_charge_days: 1, fuel_basis: "WITHOUT_FUEL",
                purchase_date: "", purchase_cost: "", hour_meter: "", default_operator: "", notes: "" };

function VehicleForm({ initial, canSetRates, onSaved, onCancel }) {
  const [d, setD] = useState({ ...EMPTY, ...(initial || {}) });
  const [ops, setOps] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => { api("/fleet/operators").then(setOps).catch(() => {}); }, []);
  const set = (k) => (e) => setD({ ...d, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const num = (k, label, step = "0.01") => (
    <Field label={label}>
      <input style={inputStyle} type="number" min="0" step={step} value={d[k] ?? ""} onChange={set(k)}
             disabled={!canSetRates && k.startsWith("rate")} />
    </Field>
  );
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = { ...d };
    ["rate_hourly", "rate_daily", "rate_weekly", "rate_monthly", "operator_rate_daily", "purchase_cost", "hour_meter", "year"]
      .forEach((k) => { if (body[k] === "") body[k] = null; });
    if (!body.purchase_date) body.purchase_date = null;
    if (!body.default_operator) body.default_operator = null;
    delete body.documents; delete body.photo;
    try {
      onSaved(initial?.id ? await api(`/fleet/vehicles/${initial.id}`, { method: "PATCH", body })
                          : await api("/fleet/vehicles", { method: "POST", body }));
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={save} style={{ ...card, marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>{initial?.id ? `Edit ${initial.reg_no}` : "Add a vehicle"}</h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", columnGap: 16 }}>
        <Field label="Registration no."><input style={inputStyle} value={d.reg_no} onChange={set("reg_no")} required autoFocus /></Field>
        <Field label="Fleet no."><input style={inputStyle} value={d.fleet_no} onChange={set("fleet_no")} placeholder="e.g. SPM-EX-01" /></Field>
        <Field label="Class"><input style={inputStyle} value={d.vehicle_class} onChange={set("vehicle_class")} placeholder="excavator, tipper, crane…" required /></Field>
        <Field label="Make"><input style={inputStyle} value={d.make} onChange={set("make")} /></Field>
        <Field label="Model"><input style={inputStyle} value={d.model} onChange={set("model")} /></Field>
        <Field label="Year"><input style={inputStyle} type="number" value={d.year ?? ""} onChange={set("year")} /></Field>
        <Field label="Capacity"><input style={inputStyle} value={d.capacity} onChange={set("capacity")} placeholder="20 t, 1.2 m³…" /></Field>
        <Field label="Engine no."><input style={inputStyle} value={d.engine_no} onChange={set("engine_no")} /></Field>
        <Field label="Chassis no."><input style={inputStyle} value={d.chassis_no} onChange={set("chassis_no")} /></Field>
        <Field label="Status">
          <select style={inputStyle} value={d.status} onChange={set("status")}>
            {STATUS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></Field>
        <Field label="Default operator">
          <select style={inputStyle} value={d.default_operator || ""} onChange={set("default_operator")}>
            <option value="">—</option>
            {ops.map((o) => <option key={o.id} value={o.id}>{o.full_name} ({o.emp_no})</option>)}
          </select></Field>
        <Field label="Hour meter"><input style={inputStyle} type="number" step="0.1" min="0" value={d.hour_meter ?? ""} onChange={set("hour_meter")} /></Field>
      </div>
      <h4 style={{ margin: "8px 0 6px" }}>Rate card {!canSetRates && <span style={{ fontWeight: 400, opacity: .7 }}>— the Rental Manager sets these</span>}</h4>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", columnGap: 16 }}>
        <Field label="Currency">
          <select style={inputStyle} value={d.rate_currency} onChange={set("rate_currency")} disabled={!canSetRates}>
            <option>MVR</option><option>USD</option>
          </select></Field>
        {num("rate_daily", "Per day (billing basis)")}
        {num("rate_hourly", "Per hour")}
        {num("rate_weekly", "Per week")}
        {num("rate_monthly", "Per month")}
        <Field label="Minimum charge (days)"><input style={inputStyle} type="number" min="1" value={d.minimum_charge_days} onChange={set("minimum_charge_days")} disabled={!canSetRates} /></Field>
        <Field label="Fuel">
          <select style={inputStyle} value={d.fuel_basis} onChange={set("fuel_basis")} disabled={!canSetRates}>
            <option value="WITHOUT_FUEL">Customer supplies fuel</option>
            <option value="WITH_FUEL">Fuel included in the rate</option>
          </select></Field>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, marginTop: 20 }}>
          <input type="checkbox" checked={!!d.operator_included} onChange={set("operator_included")} disabled={!canSetRates} /> operator included
        </label>
        {!d.operator_included && num("operator_rate_daily", "Operator per day")}
      </div>
      <h4 style={{ margin: "8px 0 6px" }}>Cost centre</h4>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", columnGap: 16 }}>
        <Field label="Purchased on"><input style={inputStyle} type="date" value={d.purchase_date || ""} onChange={set("purchase_date")} /></Field>
        {num("purchase_cost", "Purchase cost")}
        <Field label="Notes" wide><textarea style={{ ...inputStyle, minHeight: 56 }} value={d.notes} onChange={set("notes")} /></Field>
      </div>
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      <div style={{ display: "flex", gap: 8 }}>
        <Btn type="submit" disabled={busy || !d.reg_no.trim() || !d.vehicle_class.trim()}>{busy ? "Saving…" : "Save vehicle"}</Btn>
        <Btn type="button" variant="secondary" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}

function VehicleDetail({ id, onBack, onChanged }) {
  const [v, setV] = useState(null);
  const [editing, setEditing] = useState(false);
  const [doc, setDoc] = useState({ kind: "INSURANCE", reference: "", issued_on: "", expires_on: "" });
  const [error, setError] = useState(null);
  const file = useRef(null);
  const photo = useRef(null);
  const load = () => api(`/fleet/vehicles/${id}`).then(setV).catch((e) => setError(e.message));
  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [id]);
  async function addDoc(e) {
    e.preventDefault();
    const fd = new FormData();
    Object.entries(doc).forEach(([k, val]) => fd.append(k, val));
    if (file.current?.files?.[0]) fd.append("file", file.current.files[0]);
    try { setV(await apiUpload(`/fleet/vehicles/${id}/documents`, fd)); setDoc({ ...doc, reference: "", issued_on: "", expires_on: "" }); if (file.current) file.current.value = ""; onChanged(); }
    catch (err) { setError(err.message); }
  }
  async function removeDoc(d) {
    if (!window.confirm(`Remove the ${d.kind_label} document?`)) return;
    try { setV(await api(`/fleet/vehicles/${id}/documents/${d.id}`, { method: "DELETE" })); onChanged(); }
    catch (err) { setError(err.message); }
  }
  async function uploadPhoto() {
    const fd = new FormData();
    fd.append("photo", photo.current.files[0]);
    try { setV(await apiUpload(`/fleet/vehicles/${id}`, fd, "PATCH")); } catch (err) { setError(err.message); }
  }
  if (!v) return error ? <p style={{ color: "var(--red-fg)" }}>{error}</p> : <p>Loading…</p>;
  if (editing) return <VehicleForm initial={v} canSetRates={v.can_set_rates} onSaved={(nv) => { setV(nv); setEditing(false); onChanged(); }} onCancel={() => setEditing(false)} />;
  return (
    <div>
      <button className="t-link" style={{ background: "none", border: 0, color: "var(--sp-navy)", cursor: "pointer", padding: 0 }} onClick={onBack}>← Fleet</button>
      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 16, marginTop: 8 }}>
        <div style={card}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>{v.fleet_no ? `${v.fleet_no} · ` : ""}{v.reg_no}</h2>
            <Chip tone={STATUS_TONE[v.status]}>{STATUS_LABEL[v.status]}</Chip>
          </div>
          <div style={{ fontSize: 14, marginTop: 4 }}>{v.vehicle_class}{v.make ? ` · ${v.make}` : ""}{v.model ? ` ${v.model}` : ""}{v.year ? ` (${v.year})` : ""}{v.capacity ? ` · ${v.capacity}` : ""}</div>
          {v.photo && <img src={v.photo} alt={v.reg_no} style={{ maxWidth: "100%", maxHeight: 220, marginTop: 10, borderRadius: 8 }} />}
          <table style={{ marginTop: 12, fontSize: 13 }}><tbody>
            <tr><td style={{ paddingRight: 16, opacity: .7 }}>Engine / chassis</td><td>{v.engine_no || "—"} / {v.chassis_no || "—"}</td></tr>
            <tr><td style={{ paddingRight: 16, opacity: .7 }}>Default operator</td><td>{v.default_operator_name || "—"}</td></tr>
            <tr><td style={{ paddingRight: 16, opacity: .7 }}>Hour meter</td><td>{v.hour_meter ?? "—"}</td></tr>
            <tr><td style={{ paddingRight: 16, opacity: .7 }}>Purchased</td><td>{v.purchase_date ? `${fmtDate(v.purchase_date)} · ${v.rate_currency} ${fmtMoney(v.purchase_cost)}` : "—"}</td></tr>
          </tbody></table>
          {v.notes && <p style={{ fontSize: 13, whiteSpace: "pre-line" }}>{v.notes}</p>}
          {v.can_write && (
            <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center", flexWrap: "wrap" }}>
              <Btn onClick={() => setEditing(true)}>Edit</Btn>
              <input type="file" accept="image/*" ref={photo} style={{ fontSize: 12 }} onChange={uploadPhoto} />
            </div>
          )}
        </div>
        <div>
          <div style={card}>
            <h3 style={{ marginTop: 0 }}>Rate card</h3>
            <table style={{ fontSize: 13.5, width: "100%" }}><tbody>
              {[["Per day", v.rate_daily, true], ["Per hour", v.rate_hourly], ["Per week", v.rate_weekly], ["Per month", v.rate_monthly]].map(([l, x, b]) => (
                <tr key={l}><td style={{ opacity: .7 }}>{l}</td><td style={{ textAlign: "right", fontWeight: b ? 700 : 400 }}>{x ? `${v.rate_currency} ${fmtMoney(x)}` : "—"}</td></tr>
              ))}
              <tr><td style={{ opacity: .7 }}>Operator</td><td style={{ textAlign: "right" }}>{v.operator_included ? "included" : `${v.rate_currency} ${fmtMoney(v.operator_rate_daily)} / day`}</td></tr>
              <tr><td style={{ opacity: .7 }}>Fuel</td><td style={{ textAlign: "right" }}>{v.fuel_basis === "WITH_FUEL" ? "included" : "customer supplies"}</td></tr>
              <tr><td style={{ opacity: .7 }}>Minimum charge</td><td style={{ textAlign: "right" }}>{v.minimum_charge_days} day{v.minimum_charge_days === 1 ? "" : "s"}</td></tr>
            </tbody></table>
          </div>
          <div style={{ ...card, marginTop: 12 }}>
            <h3 style={{ marginTop: 0 }}>Documents</h3>
            {v.documents.length === 0 ? <p style={{ fontSize: 13, opacity: .7 }}>No documents on file.</p> : (
              <table style={{ width: "100%", fontSize: 13 }}><tbody>
                {v.documents.map((d) => (
                  <tr key={d.id}>
                    <td style={{ padding: "4px 0" }}><b>{d.kind_label}</b>{d.reference ? ` · ${d.reference}` : ""}</td>
                    <td>{d.expires_on ? fmtDate(d.expires_on) : ""}</td>
                    <td><Chip tone={DOC_TONE[d.state]}>{DOC_LABEL[d.state]}</Chip></td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {d.file && <a href={d.file} target="_blank" rel="noreferrer">file</a>}
                      {v.can_write && <> · <button style={{ background: "none", border: 0, color: "var(--red-fg)", cursor: "pointer", padding: 0, font: "inherit" }} onClick={() => removeDoc(d)}>remove</button></>}
                    </td>
                  </tr>
                ))}
              </tbody></table>
            )}
            {v.can_write && (
              <form onSubmit={addDoc} style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 10px", fontSize: 13 }}>
                <select style={inputStyle} value={doc.kind} onChange={(e) => setDoc({ ...doc, kind: e.target.value })}>
                  {DOC_KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
                <input style={inputStyle} placeholder="reference / policy no." value={doc.reference} onChange={(e) => setDoc({ ...doc, reference: e.target.value })} />
                <label>issued <input style={inputStyle} type="date" value={doc.issued_on} onChange={(e) => setDoc({ ...doc, issued_on: e.target.value })} /></label>
                <label>expires <input style={inputStyle} type="date" value={doc.expires_on} onChange={(e) => setDoc({ ...doc, expires_on: e.target.value })} /></label>
                <input type="file" ref={file} accept=".pdf,image/*" style={{ gridColumn: "1 / -1", fontSize: 12 }} />
                <div style={{ gridColumn: "1 / -1" }}><Btn type="submit" variant="secondary">+ Add document</Btn></div>
              </form>
            )}
          </div>
        </div>
      </div>
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
    </div>
  );
}

const TABS = [["vehicles", "Vehicles"], ["agreements", "Hire agreements"], ["invoices", "Invoices"], ["receivables", "Receivables"]];

export default function FleetPage() {
  const [tab, setTab] = useState("vehicles");
  const [jump, setJump] = useState(null);           // agreement id opened from a money tab
  const openAgreement = (id) => { setJump(id); setTab("agreements"); };
  const tabs = (
    <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--line)", marginBottom: 14 }}>
      {TABS.map(([k, l]) => (
        <button key={k} onClick={() => setTab(k)} style={{ background: "none", border: 0, cursor: "pointer", padding: "8px 14px", fontSize: 14,
          fontWeight: tab === k ? 700 : 500, color: tab === k ? "var(--sp-navy)" : "var(--muted)",
          borderBottom: tab === k ? "2px solid var(--sp-navy)" : "2px solid transparent", marginBottom: -1 }}>{l}</button>
      ))}
    </div>
  );
  if (tab === "agreements") return <div>{tabs}<AgreementsPanel initialOpen={jump} onOpened={() => setJump(null)} /></div>;
  if (tab === "invoices") return <div>{tabs}<InvoicesPanel openAgreement={openAgreement} /></div>;
  if (tab === "receivables") return <div>{tabs}<ReceivablesPanel openAgreement={openAgreement} /></div>;
  return <div>{tabs}<VehiclesPanel /></div>;
}

function VehiclesPanel() {
  const [summary, setSummary] = useState(null);
  const [rows, setRows] = useState(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState(null);
  function load() {
    api("/fleet/summary").then(setSummary).catch(() => setSummary({ fleet: 0, by_status: {}, expiring: [] }));
    const q = new URLSearchParams();
    if (search.trim()) q.set("search", search.trim());
    if (status) q.set("status", status);
    api(`/fleet/vehicles?${q}`).then(setRows).catch(() => setRows([]));
  }
  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [search, status]);

  if (open) return <VehicleDetail id={open} onBack={() => setOpen(null)} onChanged={load} />;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>Fleet</h2>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <input style={{ ...inputStyle, width: 220 }} placeholder="Search reg, fleet no, class…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <select style={inputStyle} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {STATUS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          {summary?.can_write && !adding && <Btn onClick={() => setAdding(true)}>+ Add vehicle</Btn>}
        </div>
      </div>
      {summary && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", margin: "14px 0" }}>
          {[["Fleet", summary.fleet], ...STATUS.filter(([v]) => v !== "DISPOSED").map(([v, l]) => [l, summary.by_status?.[v] ?? 0])].map(([l, n]) => (
            <div key={l} style={{ ...card, padding: "10px 16px", minWidth: 120 }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: "var(--sp-navy)", fontFamily: "var(--font-mono)" }}>{n}</div>
              <div style={{ fontSize: 12, opacity: .75 }}>{l}</div>
            </div>
          ))}
        </div>
      )}
      {summary?.expiring?.length > 0 && (
        <div style={{ ...card, marginBottom: 14, borderLeft: "4px solid var(--amber-fg)" }}>
          <b>Documents expiring</b>
          {summary.expiring.map((e, i) => (
            <div key={i} style={{ fontSize: 13, marginTop: 4, cursor: "pointer" }} onClick={() => setOpen(e.vehicle)}>
              <Chip tone={DOC_TONE[e.state]}>{DOC_LABEL[e.state]}</Chip> <b>{e.fleet_no || e.reg_no}</b> {e.kind} · {fmtDate(e.expires_on)}
            </div>
          ))}
        </div>
      )}
      {adding && <VehicleForm canSetRates={summary?.can_set_rates} onSaved={() => { setAdding(false); load(); }} onCancel={() => setAdding(false)} />}
      {rows === null ? <p>Loading…</p> : rows.length === 0 ? (
        <p style={{ opacity: .7 }}>{search || status ? "No vehicle matches." : "No vehicles yet. Add the fleet with each vehicle's rate card; every agreement and invoice will hang off them."}</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 8 }}>
          <thead><tr>
            <th style={th}>Vehicle</th><th style={th}>Class</th><th style={th}>Status</th>
            <th style={{ ...th, textAlign: "right" }}>Per day</th><th style={th}>Operator</th><th style={th}>Documents</th>
          </tr></thead>
          <tbody>
            {rows.map((v) => (
              <tr key={v.id} style={{ cursor: "pointer" }} onClick={() => setOpen(v.id)}>
                <td style={td}><b>{v.fleet_no || v.reg_no}</b>{v.fleet_no && <div style={{ fontSize: 12, opacity: .7 }}>{v.reg_no}</div>}</td>
                <td style={td}>{v.vehicle_class}{v.make ? ` · ${v.make} ${v.model}` : ""}{v.capacity ? ` · ${v.capacity}` : ""}</td>
                <td style={td}><Chip tone={STATUS_TONE[v.status]}>{STATUS_LABEL[v.status]}</Chip></td>
                <td style={{ ...td, textAlign: "right" }}>{v.rate_daily ? `${v.rate_currency} ${fmtMoney(v.rate_daily)}` : <span style={{ opacity: .6 }}>no rate</span>}</td>
                <td style={td}>{v.operator_included ? (v.default_operator_name || "included") : "not included"}</td>
                <td style={td}><Chip tone={DOC_TONE[v.docs_state]}>{v.n_docs ? DOC_LABEL[v.docs_state] : "none"}</Chip></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
