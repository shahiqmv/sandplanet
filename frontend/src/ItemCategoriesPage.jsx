import { useEffect, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Controlled item categories, managed by HO Purchasing (owner). The Item
// Master's category field selects from this list.

export default function ItemCategoriesPage({ me }) {
  const [rows, setRows] = useState([]);
  const [name, setName] = useState("");
  const [error, setError] = useState(null);

  const canEdit = ["HO_PURCHASING", "ADMIN"].includes(me.role);

  function load() {
    api("/item-categories").then(setRows).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function add() {
    setError(null);
    try {
      await api("/item-categories", { method: "POST",
                                      body: { name: name.trim() } });
      setName("");
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function toggle(c) {
    await api(`/item-categories/${c.id}`, { method: "PATCH",
                                            body: { is_active: !c.is_active } });
    load();
  }

  async function toggleTool(c) {
    await api(`/item-categories/${c.id}`, { method: "PATCH",
                                            body: { is_tool: !c.is_tool } });
    load();
  }

  async function remove(c) {
    if (!window.confirm(`Remove category "${c.name}"? If items still use `
                        + "it, it is kept but deactivated.")) return;
    await api(`/item-categories/${c.id}`, { method: "DELETE" });
    load();
  }

  return (
    <section style={card}>
      <h2 style={{ marginTop: 0, color: "var(--navy)", fontSize: 17 }}>
        Item Categories
      </h2>
      <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: -6 }}>
        The Item Master's category is chosen from this list — keeping
        descriptions and reporting consistent across the whole chain.
      </p>

      {canEdit && (
        <div style={{ display: "flex", gap: 8, margin: "12px 0" }}>
          <input placeholder="New category name" value={name}
                 onChange={(e) => setName(e.target.value)}
                 style={{ ...inputStyle, width: 240 }} />
          <button onClick={add} disabled={!name.trim()}
                  style={buttonStyle}>Add category</button>
        </div>
      )}
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}

      <p style={{ fontSize: 12, color: "#5a6b78", margin: "0 0 6px" }}>
        Tick <b>Tool</b> for equipment/machinery categories — items received in
        them go to the site Tools &amp; Equipment register (as assets), not the
        consumable stock ledger.
      </p>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={th}>Category</th>
          <th style={{ ...th, textAlign: "center" }}>Tool</th>
          <th style={th}>Status</th>
          {canEdit && <th style={th} />}
        </tr></thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id} style={c.is_active ? {} : { opacity: 0.5 }}>
              <td style={td}>{c.name}</td>
              <td style={{ ...td, textAlign: "center" }}>
                <input type="checkbox" checked={!!c.is_tool}
                       disabled={!canEdit}
                       onChange={() => toggleTool(c)} />
              </td>
              <td style={td}>{c.is_active ? "Active" : "Inactive"}</td>
              {canEdit && (
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  <button onClick={() => toggle(c)}
                          style={{ ...ghostButton, padding: "2px 10px",
                                   fontSize: 12 }}>
                    {c.is_active ? "Deactivate" : "Reactivate"}</button>{" "}
                  <button onClick={() => remove(c)}
                          style={{ ...ghostButton, padding: "2px 8px",
                                   fontSize: 12, color: "var(--red-fg)" }}>
                    ×</button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
