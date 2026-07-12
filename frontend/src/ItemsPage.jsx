import { useEffect, useRef, useState } from "react";
import { api, apiUpload } from "./api.js";
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
  const [preview, setPreview] = useState(null);   // photo lightbox url
  const fileRefs = useRef({});                     // per-item hidden inputs

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

  async function patch(item, body) {
    setError(null);
    try {
      await api(`/items/${item.id}`, { method: "PATCH", body });
      load();
    } catch (e) { setError(e.message); }
  }

  async function approve(item) {
    setError(null);
    try {
      await api(`/items/${item.id}/approve`, { method: "POST" });
      load();
    } catch (e) { setError(e.message); }
  }

  const provisionalCount = items.filter((i) => i.is_provisional).length;

  async function uploadPhoto(item, file) {
    if (!file) return;
    setError(null);
    try {
      const fd = new FormData();
      fd.append("photo", file);
      await apiUpload(`/items/${item.id}`, fd, "PATCH");
      load();
    } catch (e) { setError(e.message); }
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
      {canEdit && provisionalCount > 0 && (
        <p style={{ background: "#fdf6ef", border: "1px solid #f0c9a8",
                    borderRadius: 6, padding: "6px 10px", fontSize: 12.5,
                    color: "#8a5a00", margin: "0 0 8px" }}>
          {provisionalCount} site-added item(s) awaiting review — check the
          spelling/category and click <strong>Approve</strong>.
        </p>
      )}
      {canEdit && (
        <p style={{ color: "#5a6b78", fontSize: 12, margin: "0 0 8px" }}>
          Mark ★ Major for key project materials — site staff can load these
          straight into a DPR. Add a photo so procurement can identify the item.
        </p>
      )}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={th}>Photo</th>
          <th style={th}>Code</th><th style={th}>Description</th>
          <th style={th}>Unit</th><th style={th}>Category</th>
          <th style={th}>Brand</th>
          <th style={{ ...th, textAlign: "center" }}>Major</th>
          {canEdit && <th style={th} />}
        </tr></thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td style={td}>
                {item.photo_url ? (
                  <img src={item.photo_url} alt=""
                       onClick={() => setPreview(item.photo_url)}
                       style={{ width: 40, height: 40, objectFit: "cover",
                                borderRadius: 4, cursor: "pointer",
                                border: "1px solid var(--sp-border)" }} />
                ) : (
                  <span style={{ color: "#c3ccd3", fontSize: 11 }}>—</span>
                )}
              </td>
              <td style={{ ...td, fontWeight: 600, color: "var(--sp-navy)" }}>
                {item.code}</td>
              <td style={td}>{item.description}
                {item.is_provisional && (
                  <span style={{ marginLeft: 6, background: "#fdf1d6",
                                 color: "#8a5a00", fontSize: 10.5,
                                 padding: "1px 6px", borderRadius: 5 }}>
                    provisional</span>
                )}
              </td>
              <td style={td}>{item.unit}</td>
              <td style={td}>{item.category}</td>
              <td style={td}>{item.brand}</td>
              <td style={{ ...td, textAlign: "center" }}>
                {canEdit ? (
                  <button title={item.is_major ? "Major material"
                                               : "Mark as major"}
                          onClick={() => patch(item,
                                               { is_major: !item.is_major })}
                          style={{ background: "none", border: "none",
                                   cursor: "pointer", fontSize: 18,
                                   lineHeight: 1,
                                   color: item.is_major ? "#e0a52a" : "#ccd4da",
                                   padding: 0 }}>
                    {item.is_major ? "★" : "☆"}
                  </button>
                ) : (item.is_major ? "★" : "")}
              </td>
              {canEdit && (
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  <input type="file" accept="image/*"
                         ref={(el) => (fileRefs.current[item.id] = el)}
                         style={{ display: "none" }}
                         onChange={(e) => uploadPhoto(item,
                                                      e.target.files[0])} />
                  <button onClick={() => fileRefs.current[item.id]?.click()}
                          style={{ ...ghostButton, padding: "2px 10px",
                                   fontSize: 12 }}>
                    {item.photo_url ? "Replace photo" : "Add photo"}
                  </button>
                  {item.is_provisional && (
                    <button onClick={() => approve(item)}
                            style={{ ...ghostButton, padding: "2px 10px",
                                     fontSize: 12, marginLeft: 6,
                                     color: "#1a7f37" }}>Approve</button>
                  )}
                  <button onClick={() => patch(item,
                                               { is_active: !item.is_active })}
                          style={{ ...ghostButton, padding: "2px 10px",
                                   fontSize: 12, marginLeft: 6 }}>
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

      {preview && (
        <div onClick={() => setPreview(null)}
             style={{ position: "fixed", inset: 0,
                      background: "rgba(0,0,0,.6)", display: "flex",
                      alignItems: "center", justifyContent: "center",
                      zIndex: 60, padding: 24 }}>
          <img src={preview} alt="" style={{ maxWidth: "90%",
                 maxHeight: "90%", borderRadius: 8 }} />
        </div>
      )}
    </section>
  );
}
