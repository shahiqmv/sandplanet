import { useEffect, useState } from "react";
import { api } from "./api.js";
import { UNITS } from "./constants.js";
import { SelectOrOther, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

const EMPTY = { description: "", unit: "", category: "", brand: "" };

export default function ItemsPage({ me }) {
  const [items, setItems] = useState([]);
  const [categories, setCategories] = useState([]);
  const [search, setSearch] = useState("");
  const [draft, setDraft] = useState(EMPTY);
  const [error, setError] = useState(null);

  const canEdit = ["HO_PURCHASING", "ADMIN"].includes(me.role);

  function load() {
    api(`/items?search=${encodeURIComponent(search)}`).then(setItems);
  }
  useEffect(load, [search]);
  useEffect(() => {
    api("/item-categories").then((c) =>
      setCategories(c.filter((x) => x.is_active))).catch(() => {});
  }, []);

  async function add() {
    setError(null);
    try {
      await api("/items", { method: "POST", body: draft });
      setDraft(EMPTY);
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function toggle(item) {
    await api(`/items/${item.id}`, { method: "PATCH",
                                     body: { is_active: !item.is_active } });
    load();
  }

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline" }}>
        <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Item Master
        </h2>
        <input placeholder="Search description / code / category…"
               value={search} onChange={(e) => setSearch(e.target.value)}
               style={{ ...inputStyle, width: 280 }} />
      </div>

      {canEdit && (
        <div style={{ display: "flex", gap: 8, margin: "12px 0",
                      flexWrap: "wrap" }}>
          <input placeholder="Description (size, grade, spec, brand)"
                 value={draft.description}
                 onChange={(e) => setDraft({ ...draft,
                                             description: e.target.value })}
                 style={{ ...inputStyle, flex: 2, minWidth: 240 }} />
          <SelectOrOther value={draft.unit} options={UNITS}
                         placeholder="Unit…" width={90}
                         onChange={(v) => setDraft({ ...draft, unit: v })} />
          <select value={draft.category}
                  onChange={(e) => setDraft({ ...draft,
                                              category: e.target.value })}
                  style={{ ...inputStyle, width: 140 }}>
            <option value="">Category…</option>
            {categories.map((c) => (
              <option key={c.id} value={c.name}>{c.name}</option>
            ))}
          </select>
          <input placeholder="Brand" value={draft.brand}
                 onChange={(e) => setDraft({ ...draft, brand: e.target.value })}
                 style={{ ...inputStyle, width: 110 }} />
          <button onClick={add} disabled={!draft.description || !draft.unit}
                  style={buttonStyle}>Add item</button>
        </div>
      )}
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={th}>Code</th><th style={th}>Description</th>
          <th style={th}>Unit</th><th style={th}>Category</th>
          <th style={th}>Brand</th>{canEdit && <th style={th} />}
        </tr></thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td style={{ ...td, fontWeight: 600, color: "var(--sp-navy)" }}>
                {item.code}</td>
              <td style={td}>{item.description}</td>
              <td style={td}>{item.unit}</td>
              <td style={td}>{item.category}</td>
              <td style={td}>{item.brand}</td>
              {canEdit && (
                <td style={td}>
                  <button onClick={() => toggle(item)}
                          style={{ ...ghostButton, padding: "2px 10px",
                                   fontSize: 12 }}>
                    {item.is_active ? "Discontinue" : "Reactivate"}
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 && (
        <p style={{ color: "#5a6b78", fontSize: 13 }}>
          No items{search ? " match the search" : " yet"}.
        </p>
      )}
    </section>
  );
}
