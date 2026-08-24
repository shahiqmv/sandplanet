import { useEffect, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Supplier.Category choices (models.py) — INTERNATIONAL suppliers are the ones
// offered when raising an overseas import order (IPR).
const CATEGORIES = [
  ["LOCAL", "Local"],
  ["INTERNATIONAL", "International (overseas)"],
  ["FORWARDER", "Freight forwarder"],
  ["CLEARING_AGENT", "Clearing agent"],
];
const CAT_LABEL = Object.fromEntries(CATEGORIES);

const EMPTY = { name: "", category: "LOCAL", contact_person: "", phone: "",
                email: "", country: "", default_currency: "", credit_days: "",
                address: "" };

export default function SuppliersPage({ me }) {
  const [suppliers, setSuppliers] = useState([]);
  const [search, setSearch] = useState("");
  const [draft, setDraft] = useState(EMPTY);
  const [error, setError] = useState(null);
  // The row being edited. The table only ever let you flip category and
  // active — a changed phone number, a new contact or an address for the PO
  // had no way in (owner 2026-08-22).
  const [editing, setEditing] = useState(null);

  const canEdit = ["HO_PURCHASING", "ADMIN"].includes(me.role);
  const isOverseas = draft.category !== "LOCAL";

  function load() {
    api(`/suppliers?search=${encodeURIComponent(search)}&active=all`)
      .then(setSuppliers);
  }
  useEffect(load, [search]);

  async function add() {
    setError(null);
    try {
      await api("/suppliers", { method: "POST", body: draft });
      setDraft(EMPTY);
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function patch(s, body) {
    setError(null);
    try {
      await api(`/suppliers/${s.id}`, { method: "PATCH", body });
      load();
    } catch (e) { setError(e.message); }
  }

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline" }}>
        <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Suppliers
        </h2>
        <input placeholder="Search…" value={search}
               onChange={(e) => setSearch(e.target.value)}
               style={{ ...inputStyle, width: 240 }} />
      </div>

      {canEdit && (
        <div style={{ display: "flex", gap: 8, margin: "12px 0",
                      flexWrap: "wrap", alignItems: "center" }}>
          <input placeholder="Supplier name" value={draft.name}
                 onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                 style={{ ...inputStyle, flex: 2, minWidth: 200 }} />
          <select value={draft.category}
                  onChange={(e) => setDraft({ ...draft,
                                              category: e.target.value })}
                  style={{ ...inputStyle, width: 190 }}>
            {CATEGORIES.map(([v, label]) => (
              <option key={v} value={v}>{label}</option>
            ))}
          </select>
          <input placeholder="Contact person" value={draft.contact_person}
                 onChange={(e) => setDraft({ ...draft,
                                             contact_person: e.target.value })}
                 style={{ ...inputStyle, width: 150 }} />
          <input placeholder="Phone" value={draft.phone}
                 onChange={(e) => setDraft({ ...draft, phone: e.target.value })}
                 style={{ ...inputStyle, width: 120 }} />
          <input placeholder="Email" value={draft.email}
                 onChange={(e) => setDraft({ ...draft, email: e.target.value })}
                 style={{ ...inputStyle, width: 180 }} />
          {isOverseas && (
            <>
              <input placeholder="Country" value={draft.country}
                     onChange={(e) => setDraft({ ...draft,
                                                 country: e.target.value })}
                     style={{ ...inputStyle, width: 120 }} />
              <input placeholder="Currency (e.g. USD)"
                     value={draft.default_currency}
                     onChange={(e) => setDraft({ ...draft,
                       default_currency: e.target.value.toUpperCase() })}
                     style={{ ...inputStyle, width: 120 }} maxLength={3} />
            </>
          )}
          <input type="number" min="0" placeholder="Credit days"
                 title="Agreed credit period in days — sets the payment due date on this supplier's credit orders"
                 value={draft.credit_days ?? ""}
                 onChange={(e) => setDraft({ ...draft,
                                             credit_days: e.target.value })}
                 style={{ ...inputStyle, width: 110 }} />
          <input placeholder="Address (shown on POs)"
                 value={draft.address}
                 onChange={(e) => setDraft({ ...draft,
                                             address: e.target.value })}
                 style={{ ...inputStyle, width: 200 }} />
          <button onClick={add} disabled={!draft.name} style={buttonStyle}>
            Add supplier</button>
        </div>
      )}
      {canEdit && (
        <p style={{ color: "#5a6b78", fontSize: 12, margin: "0 0 8px" }}>
          Mark a supplier <strong>International (overseas)</strong> for it to
          appear when raising an import order (IPR). You can reclassify an
          existing supplier from the Category column below.
        </p>
      )}
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {editing && (
        <SupplierEditor supplier={editing} canEdit={canEdit}
          seesBank={["HO_PURCHASING", "FINANCE", "ADMIN"].includes(me.role)}
          agentName={suppliers.find((x) => x.is_clearing_agent)?.name}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }} />
      )}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={th}>Name</th><th style={th}>Category</th>
          <th style={th}>Contact</th>
          <th style={th}>Phone</th><th style={th}>Email</th>
          <th style={th}>Address</th>{canEdit && <th style={th} />}
        </tr></thead>
        <tbody>
          {suppliers.map((s) => (
            <tr key={s.id} style={{ opacity: s.is_active ? 1 : 0.5 }}>
              <td style={{ ...td, fontWeight: 600, color: "var(--sp-navy)" }}>
                <a href="#" onClick={(e) => { e.preventDefault();
                                              setEditing(s); }}
                   style={{ color: "inherit" }}
                   title={canEdit ? "Open to edit" : "Open"}>{s.name}</a>
                {s.is_clearing_agent && (
                  <span title="Shipping documents are emailed to this supplier when purchasing shares a shipment"
                        style={{ marginLeft: 6, fontSize: 10, fontWeight: 600,
                                 color: "#fff", background: "var(--sp-navy)",
                                 borderRadius: 4, padding: "1px 6px",
                                 verticalAlign: "middle",
                                 whiteSpace: "nowrap" }}>
                    CLEARING AGENT</span>)}
                {s.credit_days != null && s.credit_days !== "" && (
                  <div style={{ fontSize: 11, color: "#5a6b78",
                                fontWeight: 400 }}>
                    {s.credit_days} days credit</div>)}
              </td>
              <td style={td}>
                {canEdit ? (
                  <select value={s.category}
                          onChange={(e) => patch(s,
                                                 { category: e.target.value })}
                          style={{ ...inputStyle, width: 170, fontSize: 12,
                                   padding: "3px 6px" }}>
                    {CATEGORIES.map(([v, label]) => (
                      <option key={v} value={v}>{label}</option>
                    ))}
                  </select>
                ) : (CAT_LABEL[s.category] || s.category)}
                {s.category !== "LOCAL" && s.country && (
                  <div style={{ fontSize: 11, color: "#5a6b78", marginTop: 2 }}>
                    {s.country}{s.default_currency
                      ? ` · ${s.default_currency}` : ""}</div>
                )}
              </td>
              <td style={td}>{s.contact_person}</td>
              <td style={td}>{s.phone}</td>
              <td style={td}>{s.email}</td>
              <td style={td}>{s.address}</td>
              {canEdit && (
                <td style={td}>
                  <button onClick={() => patch(s,
                                               { is_active: !s.is_active })}
                          style={{ ...ghostButton, padding: "2px 10px",
                                   fontSize: 12 }}>
                    {s.is_active ? "Deactivate" : "Reactivate"}
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {suppliers.length === 0 && (
        <p style={{ color: "#5a6b78", fontSize: 13 }}>No suppliers yet.</p>
      )}
    </section>
  );
}

// Every field on the supplier record, in one place. Bank details are shown
// only to the roles the API returns them to.
const FIELDS = [
  ["name", "Supplier name", "text"],
  ["contact_person", "Contact person", "text"],
  ["phone", "Phone", "text"],
  ["email", "Email", "text"],
  ["address", "Address (shown on POs)", "text"],
  ["country", "Country", "text"],
  ["default_currency", "Default currency (e.g. USD)", "text"],
  ["default_incoterm", "Default incoterm (e.g. FOB)", "text"],
  ["credit_days", "Credit period (days)", "number"],
];

function SupplierEditor({ supplier, canEdit, seesBank, agentName,
                          onClose, onSaved }) {
  const [form, setForm] = useState({ ...supplier });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setForm({ ...form, [k]: v });

  // ONE clearing agent company-wide — setting it here moves the flag off
  // whoever held it. "Share with clearing agent" on a shipment emails the
  // shipping documents to this supplier.
  async function setClearingAgent(want) {
    if (want && agentName && !supplier.is_clearing_agent
        && !window.confirm(
          `${agentName} is the clearing agent now. Move it to `
          + `${supplier.name}? All shipping-document emails will go to `
          + `${supplier.name} from here on.`)) return;
    setBusy(true); setErr(null);
    try {
      await api(`/suppliers/${supplier.id}/clearing-agent`,
                { method: "POST", body: { set: want } });
      onSaved();
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  async function save() {
    setBusy(true); setErr(null);
    try {
      const body = {};
      for (const k of Object.keys(form)) {
        if (k === "id") continue;
        if (form[k] !== supplier[k]) body[k] = form[k];
      }
      if (Object.keys(body).length) {
        await api(`/suppliers/${supplier.id}`, { method: "PATCH", body });
      }
      onSaved();
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  const field = ([k, label, type]) => (
    <label key={k} style={{ display: "flex", flexDirection: "column",
                            gap: 3, fontSize: 12, color: "#5a6b78",
                            minWidth: 200, flex: 1 }}>
      {label}
      <input type={type} value={form[k] ?? ""} disabled={!canEdit}
        onChange={(e) => set(k, k === "default_currency"
          ? e.target.value.toUpperCase() : e.target.value)}
        style={inputStyle} />
    </label>
  );

  return (
    <div style={{ border: "1px solid #dde5ea", borderRadius: 8,
                  padding: 14, margin: "10px 0 14px",
                  background: "#fafcfd" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline", marginBottom: 8 }}>
        <strong style={{ color: "var(--sp-navy)" }}>{supplier.name}</strong>
        <button onClick={onClose} style={{ ...ghostButton, padding: "2px 10px",
                                           fontSize: 12 }}>Close</button>
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {FIELDS.slice(0, 5).map(field)}
        <label style={{ display: "flex", flexDirection: "column", gap: 3,
                        fontSize: 12, color: "#5a6b78", minWidth: 200 }}>
          Category
          <select value={form.category} disabled={!canEdit}
                  onChange={(e) => set("category", e.target.value)}
                  style={inputStyle}>
            {CATEGORIES.map(([v, label]) => (
              <option key={v} value={v}>{label}</option>))}
          </select>
        </label>
        {FIELDS.slice(5).map(field)}
      </div>
      {seesBank && (
        <label style={{ display: "flex", flexDirection: "column", gap: 3,
                        fontSize: 12, color: "#5a6b78", marginTop: 10 }}>
          Bank / remittance details
          <textarea rows={3} value={form.bank_details ?? ""} disabled={!canEdit}
            onChange={(e) => set("bank_details", e.target.value)}
            style={{ ...inputStyle, fontFamily: "inherit" }} />
        </label>
      )}
      <label style={{ display: "flex", flexDirection: "column", gap: 3,
                      fontSize: 12, color: "#5a6b78", marginTop: 10 }}>
        Notes
        <textarea rows={2} value={form.notes ?? ""} disabled={!canEdit}
          onChange={(e) => set("notes", e.target.value)}
          style={{ ...inputStyle, fontFamily: "inherit" }} />
      </label>
      <div style={{ marginTop: 12, padding: "8px 10px", borderRadius: 6,
                    background: supplier.is_clearing_agent
                      ? "#eef6ee" : "#f4f7f9",
                    fontSize: 12, color: "#41525f" }}>
        {supplier.is_clearing_agent ? (
          <>This is the company's <strong>clearing agent</strong> — "Share
            with clearing agent" on a shipment emails the shipping documents
            {supplier.email ? ` to ${supplier.email}` : ""}.
            {!supplier.email && (
              <span style={{ color: "#c0392b" }}> No email on file — add one
                above or sharing will fail.</span>)}
            {canEdit && (
              <button onClick={() => setClearingAgent(false)} disabled={busy}
                      style={{ ...ghostButton, padding: "2px 10px",
                               fontSize: 12, marginLeft: 10 }}>
                Remove clearing-agent role</button>)}
          </>
        ) : (
          <>Clearing agent: <strong>{agentName || "none set"}</strong>.
            The company has one clearing agent; shipping documents are
            emailed to them.
            {canEdit && (
              <button onClick={() => setClearingAgent(true)} disabled={busy}
                      style={{ ...ghostButton, padding: "2px 10px",
                               fontSize: 12, marginLeft: 10 }}>
                Make {supplier.name} the clearing agent</button>)}
          </>
        )}
      </div>
      {err && <p style={{ color: "#c0392b", fontSize: 13 }}>{err}</p>}
      {canEdit && (
        <div style={{ marginTop: 10 }}>
          <button onClick={save} disabled={busy || !form.name}
                  style={buttonStyle}>{busy ? "Saving…" : "Save changes"}</button>
        </div>
      )}
    </div>
  );
}
