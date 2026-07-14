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
                email: "", country: "", default_currency: "", address: "" };

export default function SuppliersPage({ me }) {
  const [suppliers, setSuppliers] = useState([]);
  const [search, setSearch] = useState("");
  const [draft, setDraft] = useState(EMPTY);
  const [error, setError] = useState(null);

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
                {s.name}</td>
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
