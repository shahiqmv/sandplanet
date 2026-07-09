import { useEffect, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Worker (manpower) categories management (owner). These drive DPR
// manpower, DMA allocation, the project manpower requirement, and the
// employee roster — one company-wide list. Admin-managed.

const EMPTY = { list_type: "DPR", grp: "STAFF", name: "", sort_order: 100 };

export default function WorkerCategoriesPage({ me }) {
  const [rows, setRows] = useState([]);
  const [draft, setDraft] = useState(EMPTY);
  const [error, setError] = useState(null);

  const canEdit = me.role === "ADMIN";

  function load() {
    api("/manpower-categories").then(setRows).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function add() {
    setError(null);
    try {
      await api("/manpower-categories", { method: "POST",
        body: { ...draft, name: draft.name.trim(),
                sort_order: +draft.sort_order || 100 } });
      setDraft({ ...EMPTY, list_type: draft.list_type, grp: draft.grp });
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function toggle(c) {
    await api(`/manpower-categories/${c.id}`, { method: "PATCH",
      body: { is_active: !c.is_active } });
    load();
  }

  async function remove(c) {
    if (!window.confirm(`Remove "${c.name}"? If employees use it, it is `
                        + "kept but deactivated.")) return;
    await api(`/manpower-categories/${c.id}`, { method: "DELETE" });
    load();
  }

  const lists = [["DPR", "DPR / daily manpower"], ["TWS", "TWS / planned"]];

  return (
    <section style={card}>
      <h2 style={{ marginTop: 0, color: "var(--navy)", fontSize: 17 }}>
        Worker Categories
      </h2>
      <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: -6 }}>
        One company-wide list driving DPR manpower, daily allocation, the
        project manpower requirement, and the employee roster.
      </p>

      {canEdit && (
        <div style={{ display: "flex", gap: 8, margin: "12px 0",
                      flexWrap: "wrap", alignItems: "center" }}>
          <select value={draft.list_type}
                  onChange={(e) => setDraft({ ...draft,
                                              list_type: e.target.value })}
                  style={{ ...inputStyle, width: 90 }}>
            <option value="DPR">DPR</option><option value="TWS">TWS</option>
          </select>
          <select value={draft.grp}
                  onChange={(e) => setDraft({ ...draft, grp: e.target.value })}
                  style={{ ...inputStyle, width: 150 }}>
            <option value="STAFF">Staff</option>
            <option value="LABOUR">Trades / Labour</option>
          </select>
          <input placeholder="Category name" value={draft.name}
                 onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                 style={{ ...inputStyle, width: 200 }} />
          <input type="number" placeholder="Order" value={draft.sort_order}
                 title="Sort order" onChange={(e) => setDraft({ ...draft,
                   sort_order: e.target.value })}
                 style={{ ...inputStyle, width: 80 }} />
          <button onClick={add} disabled={!draft.name.trim()}
                  style={buttonStyle}>Add</button>
        </div>
      )}
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}

      {lists.map(([lt, label]) => {
        const group = rows.filter((c) => c.list_type === lt);
        if (!group.length && !canEdit) return null;
        return (
          <div key={lt} style={{ marginTop: 8 }}>
            <h3 style={{ fontSize: 14, color: "var(--navy)",
                         margin: "12px 0 4px" }}>{label}</h3>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr>
                <th style={th}>Group</th><th style={th}>Category</th>
                <th style={th}>Order</th><th style={th}>Status</th>
                {canEdit && <th style={th} />}
              </tr></thead>
              <tbody>
                {group.sort((a, b) => a.grp.localeCompare(b.grp) ||
                            a.sort_order - b.sort_order).map((c) => (
                  <tr key={c.id} style={c.is_active ? {} : { opacity: 0.5 }}>
                    <td style={td}>{c.grp === "STAFF" ? "Staff"
                                    : "Trades / Labour"}</td>
                    <td style={td}>{c.name}</td>
                    <td style={td}>{c.sort_order}</td>
                    <td style={td}>{c.is_active ? "Active" : "Inactive"}</td>
                    {canEdit && (
                      <td style={{ ...td, whiteSpace: "nowrap" }}>
                        <button onClick={() => toggle(c)}
                                style={{ ...ghostButton, padding: "2px 10px",
                                         fontSize: 12 }}>
                          {c.is_active ? "Deactivate" : "Reactivate"}</button>
                        {" "}
                        <button onClick={() => remove(c)}
                                style={{ ...ghostButton, padding: "2px 8px",
                                         fontSize: 12,
                                         color: "var(--red-fg)" }}>×</button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </section>
  );
}
