// Rental customers — who we hire vehicles to. A customer is a hirer; a
// client is who we build for (on a site). The same company is often both,
// so a customer record can be started from a project's client block and
// says which site it is the client of (owner 2026-09-25).
import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";

const EMPTY = { name: "", tin: "", business_reg_no: "", billing_address: "", island: "", contact_person: "", phone: "",
                email: "", default_currency: "MVR", credit_days: "", gst_exempt: false, notes: "", is_active: true, project_client: "" };

function Field({ label, children, wide }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13, gridColumn: wide ? "1 / -1" : undefined }}>
      <span style={{ fontWeight: 600, opacity: .8 }}>{label}</span>{children}
    </label>
  );
}

export function CustomerForm({ initial, onSaved, onCancel, compact }) {
  const [d, setD] = useState({ ...EMPTY, ...(initial || {}), project_client: initial?.project_client || "" });
  const [clients, setClients] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("/fleet/project-clients").then(setClients).catch(() => {}); }, []);
  const set = (k) => (e) => setD({ ...d, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  function fromClient(siteId) {
    const c = clients.find((x) => String(x.site) === String(siteId));
    if (!c) { setD({ ...d, project_client: "" }); return; }
    setD({ ...d, project_client: c.site, name: d.name || c.name, tin: d.tin || c.tin, billing_address: d.billing_address || c.billing_address,
           contact_person: d.contact_person || c.contact_person, phone: d.phone || c.phone, email: d.email || c.email });
  }
  async function save(e) {
    e.preventDefault(); setBusy(true); setError(null);
    const body = { ...d, credit_days: d.credit_days === "" ? null : Number(d.credit_days), project_client: d.project_client ? Number(d.project_client) : null };
    try { onSaved(initial?.id ? await api(`/fleet/customers/${initial.id}`, { method: "PATCH", body }) : await api("/fleet/customers", { method: "POST", body })); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={save} style={{ ...card, marginBottom: 16, ...(compact ? { background: "var(--sky-soft)" } : {}) }}>
      <h3 style={{ marginTop: 0 }}>{initial?.id ? `Edit ${initial.name}` : "New customer"}</h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "10px 16px" }}>
        <Field label="Also our project client at" wide>
          <select style={inputStyle} value={d.project_client} onChange={(e) => fromClient(e.target.value)}>
            <option value="">— not a project client / not linked —</option>
            {clients.map((c) => <option key={c.site} value={c.site} disabled={!!c.customer && c.customer !== initial?.id}>{c.code} · {c.name}{c.customer && c.customer !== initial?.id ? " (already a customer)" : ""}</option>)}
          </select>
          <span style={{ fontSize: 11, opacity: .65 }}>Picking a site copies its client's name, address, TIN and contact into the blanks below.</span>
        </Field>
        <Field label="Customer name" wide><input style={inputStyle} value={d.name} onChange={set("name")} required /></Field>
        <Field label="GST TIN"><input style={inputStyle} value={d.tin} onChange={set("tin")} placeholder="printed on the tax invoice" /></Field>
        <Field label="Business registration no."><input style={inputStyle} value={d.business_reg_no} onChange={set("business_reg_no")} /></Field>
        <Field label="Billing address" wide><textarea style={{ ...inputStyle, minHeight: 56 }} value={d.billing_address} onChange={set("billing_address")} /></Field>
        <Field label="Island / location"><input style={inputStyle} value={d.island} onChange={set("island")} /></Field>
        <Field label="Contact person"><input style={inputStyle} value={d.contact_person} onChange={set("contact_person")} /></Field>
        <Field label="Phone"><input style={inputStyle} value={d.phone} onChange={set("phone")} /></Field>
        <Field label="Email"><input style={inputStyle} type="email" value={d.email} onChange={set("email")} /></Field>
        <Field label="Billing currency"><select style={inputStyle} value={d.default_currency} onChange={set("default_currency")}><option value="MVR">MVR</option><option value="USD">USD</option></select></Field>
        <Field label="Credit days"><input style={inputStyle} type="number" min="0" value={d.credit_days} onChange={set("credit_days")} placeholder="blank = pay on invoice" /></Field>
        <Field label="Notes" wide><textarea style={{ ...inputStyle, minHeight: 44 }} value={d.notes} onChange={set("notes")} /></Field>
        <label style={{ fontSize: 13 }}><input type="checkbox" checked={!!d.gst_exempt} onChange={set("gst_exempt")} /> GST exempt — no output GST on this customer's invoices</label>
        {initial?.id && <label style={{ fontSize: 13 }}><input type="checkbox" checked={!!d.is_active} onChange={set("is_active")} /> Active</label>}
      </div>
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Btn type="submit" disabled={busy || !d.name.trim()}>{busy ? "Saving…" : "Save customer"}</Btn>
        <Btn type="button" variant="secondary" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}

export function CustomerDetails({ c }) {
  if (!c) return null;
  const line = (l, v) => (v ? <div><span style={{ opacity: .65 }}>{l}</span> {v}</div> : null);
  return (
    <div style={{ fontSize: 13, display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "2px 16px", marginTop: 6 }}>
      {line("Address", c.address)}
      {line("GST TIN", c.tin)}
      {line("Reg No", c.reg_no)}
      {line("Contact", [c.contact, c.phone, c.email].filter(Boolean).join(" · "))}
      {line("Credit", c.credit_days != null ? `${c.credit_days} days` : "on invoice")}
      {c.gst_exempt ? <div><Chip tone="warn">GST exempt</Chip></div> : null}
      {c.project_client ? <div><Chip tone="info">project client · {c.project_client.code}</Chip></div> : null}
    </div>
  );
}

export function CustomersPanel() {
  const [rows, setRows] = useState(null);
  const [editing, setEditing] = useState(null);      // null | {} | customer
  const [canWrite, setCanWrite] = useState(false);
  const [search, setSearch] = useState("");
  const load = () => api(`/fleet/customers?active=all${search.trim() ? `&search=${encodeURIComponent(search.trim())}` : ""}`).then(setRows).catch(() => setRows([]));
  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [search]);
  useEffect(() => { api("/fleet/summary").then((s) => setCanWrite(s.can_write)).catch(() => {}); }, []);
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>Customers <span style={{ fontSize: 13, fontWeight: 400, opacity: .7 }}>who we hire to; a project client is on its site</span></h2>
        <div style={{ display: "flex", gap: 10 }}>
          <input style={{ ...inputStyle, width: 220 }} placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)} />
          {canWrite && editing === null && <Btn onClick={() => setEditing({})}>+ New customer</Btn>}
        </div>
      </div>
      {editing !== null && <div style={{ marginTop: 12 }}><CustomerForm initial={editing.id ? editing : null} onSaved={() => { setEditing(null); load(); }} onCancel={() => setEditing(null)} /></div>}
      {rows === null ? <p>Loading…</p> : rows.length === 0 ? <p style={{ opacity: .7, marginTop: 12 }}>No customers yet.</p> : (
        <table style={{ width: "100%", borderCollapse: "collapse", background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 8, marginTop: 12 }}>
          <thead><tr><th style={th}>Customer</th><th style={th}>GST TIN</th><th style={th}>Contact</th><th style={th}>Terms</th><th style={th}>Project client</th><th style={th}></th></tr></thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} style={{ opacity: c.is_active ? 1 : .55 }}>
                <td style={td}><b>{c.name}</b>{c.billing_address ? <div style={{ fontSize: 12, opacity: .7, whiteSpace: "pre-line" }}>{c.billing_address}</div> : null}</td>
                <td style={td}>{c.tin || ""}{c.gst_exempt ? <div><Chip tone="warn">exempt</Chip></div> : null}</td>
                <td style={td}>{[c.contact_person, c.phone, c.email].filter(Boolean).join(" · ")}</td>
                <td style={td}>{c.default_currency}{c.credit_days != null ? ` · ${c.credit_days} days` : " · on invoice"}</td>
                <td style={td}>{c.project_client_code ? <Chip tone="info">{c.project_client_code}</Chip> : ""}</td>
                <td style={td}>{canWrite && <button style={{ background: "none", border: 0, color: "var(--sp-navy)", textDecoration: "underline", cursor: "pointer", font: "inherit", fontSize: 13, padding: 0 }} onClick={() => setEditing(c)}>edit</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
