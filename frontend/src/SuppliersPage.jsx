import { useEffect, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

const EMPTY = { name: "", contact_person: "", phone: "", email: "",
                payment_terms_default: "" };

export default function SuppliersPage({ me }) {
  const [suppliers, setSuppliers] = useState([]);
  const [search, setSearch] = useState("");
  const [draft, setDraft] = useState(EMPTY);
  const [error, setError] = useState(null);

  const canEdit = ["HO_PURCHASING", "ADMIN"].includes(me.role);

  function load() {
    api(`/suppliers?search=${encodeURIComponent(search)}`).then(setSuppliers);
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
                      flexWrap: "wrap" }}>
          <input placeholder="Supplier name" value={draft.name}
                 onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                 style={{ ...inputStyle, flex: 2, minWidth: 200 }} />
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
          <input placeholder="Default payment terms"
                 value={draft.payment_terms_default}
                 onChange={(e) => setDraft({ ...draft,
                                             payment_terms_default:
                                             e.target.value })}
                 style={{ ...inputStyle, width: 160 }} />
          <button onClick={add} disabled={!draft.name} style={buttonStyle}>
            Add supplier</button>
        </div>
      )}
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={th}>Name</th><th style={th}>Contact</th>
          <th style={th}>Phone</th><th style={th}>Email</th>
          <th style={th}>Payment terms</th>{canEdit && <th style={th} />}
        </tr></thead>
        <tbody>
          {suppliers.map((s) => (
            <tr key={s.id}>
              <td style={{ ...td, fontWeight: 600, color: "var(--sp-navy)" }}>
                {s.name}</td>
              <td style={td}>{s.contact_person}</td>
              <td style={td}>{s.phone}</td>
              <td style={td}>{s.email}</td>
              <td style={td}>{s.payment_terms_default}</td>
              {canEdit && (
                <td style={td}>
                  <button onClick={async () => {
                            await api(`/suppliers/${s.id}`, { method: "PATCH",
                              body: { is_active: !s.is_active } });
                            load();
                          }}
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
