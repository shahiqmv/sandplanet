import { useEffect, useRef, useState } from "react";
import { api, apiUpload } from "./api.js";
import { shrinkPhoto } from "./imageResize.js";
import { UNITS } from "./constants.js";
import { SelectOrOther, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

const EMPTY = { description: "", unit: "", category: "", brand: "" };


// Clicking an item used to open inputs INSIDE the table row — a description
// box a couple of hundred pixels wide for what is often a full specification,
// and no way at all to reach `notes` (owner 2026-08-18). The whole record
// opens in a dialog instead, with room to write.
function ItemDialog({ item, categories, onClose, onSaved, onError }) {
  const [draft, setDraft] = useState({
    description: item.description || "", unit: item.unit || "",
    category: item.category || "", brand: item.brand || "",
    spec_ref: item.spec_ref || "", notes: item.notes || "",
    is_major: !!item.is_major, is_active: !!item.is_active,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const photoRef = useRef();
  const [photoUrl, setPhotoUrl] = useState(item.photo_url);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const set = (k) => (e) => setDraft({ ...draft, [k]: e.target.value });

  async function save() {
    setErr(null);
    setBusy(true);
    try {
      await api(`/items/${item.id}`, { method: "PATCH", body: draft });
      onSaved();
      onClose();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  async function photo(file) {
    if (!file) return;
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("photo", await shrinkPhoto(file));
      const saved = await apiUpload(`/items/${item.id}`, fd, "PATCH");
      setPhotoUrl(saved.photo_url);
      onSaved();                       // the row behind picks the photo up too
    } catch (e) { setErr(e.message); }
  }

  const label = { fontSize: 11.5, fontWeight: 700, color: "var(--sp-navy)",
                  display: "block", marginBottom: 3 };
  const field = { marginBottom: 12 };

  return (
    <div onClick={onClose}
         style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.4)",
                  display: "flex", alignItems: "center",
                  justifyContent: "center", zIndex: 60, padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ ...card, maxWidth: 680, width: "100%", maxHeight: "90vh",
                    overflow: "auto" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                      marginBottom: 14 }}>
          <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 16,
                       fontFamily: "var(--font-mono)" }}>{item.code}</h2>
          {item.is_provisional && (
            <span style={{ background: "#fdf1d6", color: "#8a5a00",
                           fontSize: 10.5, padding: "1px 6px",
                           borderRadius: 5 }}>provisional</span>
          )}
          <button onClick={onClose}
                  style={{ ...ghostButton, marginLeft: "auto" }}>Close</button>
        </div>

        {err && <p style={{ color: "#c0392b", fontSize: 13 }}>{err}</p>}

        <div style={{ display: "flex", gap: 18, alignItems: "flex-start",
                      flexWrap: "wrap" }}>
          <div style={{ width: 150 }}>
            <span style={label}>Photo</span>
            <input type="file" accept="image/*" ref={photoRef}
                   style={{ display: "none" }}
                   onChange={(e) => photo(e.target.files[0])} />
            {photoUrl ? (
              <img src={photoUrl} alt="" onClick={() => photoRef.current?.click()}
                   style={{ width: 150, height: 150, objectFit: "cover",
                            borderRadius: 8, cursor: "pointer",
                            border: "1px solid var(--sp-border)" }} />
            ) : (
              <button onClick={() => photoRef.current?.click()}
                      style={{ width: 150, height: 150, borderRadius: 8,
                               border: "1px dashed var(--sp-border)",
                               background: "#fafbfc", cursor: "pointer",
                               color: "#8a94a0", fontSize: 12 }}>
                + Add photo</button>
            )}
            {photoUrl && (
              <button onClick={() => photoRef.current?.click()}
                      style={{ ...ghostButton, padding: "2px 10px",
                               fontSize: 12, marginTop: 6, width: 150 }}>
                Replace photo</button>
            )}
          </div>

          <div style={{ flex: 1, minWidth: 300 }}>
            <div style={field}>
              <span style={label}>Description</span>
              <textarea value={draft.description} rows={4}
                        onChange={set("description")}
                        placeholder="Size, grade, spec, standard — write it in full"
                        style={{ ...inputStyle, width: "100%",
                                 resize: "vertical", lineHeight: 1.45 }} />
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <div style={{ ...field, width: 100 }}>
                <span style={label}>Unit</span>
                <SelectOrOther value={draft.unit} options={UNITS} width={100}
                               placeholder="Unit…"
                               onChange={(v) => setDraft({ ...draft, unit: v })} />
              </div>
              <div style={{ ...field, flex: 1, minWidth: 150 }}>
                <span style={label}>Category</span>
                <select value={draft.category} onChange={set("category")}
                        style={{ ...inputStyle, width: "100%" }}>
                  <option value="">—</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.name}>{c.name}</option>
                  ))}
                </select>
              </div>
              <div style={{ ...field, flex: 1, minWidth: 130 }}>
                <span style={label}>Brand</span>
                <input value={draft.brand} onChange={set("brand")}
                       style={{ ...inputStyle, width: "100%" }} />
              </div>
            </div>
            <div style={field}>
              <span style={label}>Spec reference</span>
              <input value={draft.spec_ref} onChange={set("spec_ref")}
                     placeholder="BS / ASTM / drawing reference (optional)"
                     style={{ ...inputStyle, width: "100%" }} />
            </div>
            <div style={field}>
              <span style={label}>Notes</span>
              <textarea value={draft.notes} rows={3} onChange={set("notes")}
                        placeholder="Anything procurement should know — approved suppliers, handling, substitutes"
                        style={{ ...inputStyle, width: "100%",
                                 resize: "vertical", lineHeight: 1.45 }} />
            </div>
            <div style={{ display: "flex", gap: 18, flexWrap: "wrap",
                          fontSize: 13 }}>
              <label style={{ display: "flex", gap: 6, alignItems: "center",
                              cursor: "pointer" }}>
                <input type="checkbox" checked={draft.is_major}
                       onChange={(e) => setDraft({ ...draft,
                                          is_major: e.target.checked })} />
                ★ Major material <span style={{ color: "var(--muted)",
                  fontSize: 11.5 }}>(loads into a DPR)</span>
              </label>
              <label style={{ display: "flex", gap: 6, alignItems: "center",
                              cursor: "pointer" }}>
                <input type="checkbox" checked={draft.is_active}
                       onChange={(e) => setDraft({ ...draft,
                                          is_active: e.target.checked })} />
                In use
              </label>
            </div>
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 16,
                      borderTop: "1px solid var(--sp-border)",
                      paddingTop: 14 }}>
          <button onClick={save} style={buttonStyle}
                  disabled={busy || !draft.description.trim() || !draft.unit}>
            {busy ? "Saving…" : "Save"}</button>
          <button onClick={onClose} style={ghostButton}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

export default function ItemsPage({ me }) {
  const [items, setItems] = useState([]);
  const [categories, setCategories] = useState([]);
  const [search, setSearch] = useState("");
  const [draft, setDraft] = useState(EMPTY);
  const [error, setError] = useState(null);
  const [preview, setPreview] = useState(null);   // photo lightbox url
  const [openItem, setOpenItem] = useState(null);  // item open in the dialog
  const [importResult, setImportResult] = useState(null);
  const [importing, setImporting] = useState(false);
  const importRef = useRef();

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

  async function importExcel(file) {
    if (!file) return;
    setError(null);
    setImportResult(null);
    setImporting(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await apiUpload("/items/import", fd);
      setImportResult(res);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setImporting(false);
      if (importRef.current) importRef.current.value = "";
    }
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

      {canEdit && (
        <div style={{ display: "flex", gap: 10, alignItems: "center",
                      flexWrap: "wrap", padding: "10px 12px",
                      background: "var(--sp-tint, #f5f8fb)", borderRadius: 8,
                      marginBottom: 10 }}>
          <strong style={{ fontSize: 13, color: "var(--sp-navy)" }}>
            Bulk add from Excel</strong>
          <a href="/api/v1/items/import-template"
             style={{ ...ghostButton, textDecoration: "none",
                      padding: "4px 12px", fontSize: 12.5 }}>
            ⬇ Download template</a>
          <input type="file" accept=".xlsx" ref={importRef}
                 style={{ display: "none" }}
                 onChange={(e) => importExcel(e.target.files[0])} />
          <button onClick={() => importRef.current?.click()} disabled={importing}
                  style={{ ...buttonStyle, padding: "4px 14px", fontSize: 12.5 }}>
            {importing ? "Importing…" : "⬆ Upload filled sheet"}</button>
          <span style={{ fontSize: 12, color: "var(--muted)" }}>
            Fill the template and upload — codes are assigned automatically;
            existing descriptions are skipped.</span>
        </div>
      )}
      {importResult && (
        <div style={{ background: "#eef7f0", border: "1px solid #bfe0c8",
                      borderRadius: 8, padding: "8px 12px", fontSize: 13,
                      marginBottom: 10 }}>
          <strong style={{ color: "#1a7f37" }}>
            Imported {importResult.created} item(s)</strong>
          {importResult.skipped > 0 && ` · ${importResult.skipped} skipped `
            + "(blank / duplicate / no unit)"}
          {importResult.errors?.length > 0 && (
            <ul style={{ margin: "6px 0 0", paddingLeft: 18, color: "#8a5a00" }}>
              {importResult.errors.slice(0, 12).map((er, i) => (
                <li key={i}>Row {er.row}: {er.message}</li>
              ))}
              {importResult.errors.length > 12 && (
                <li>…and {importResult.errors.length - 12} more</li>
              )}
            </ul>
          )}
          <button onClick={() => setImportResult(null)}
                  style={{ ...ghostButton, padding: "2px 10px", fontSize: 12,
                           marginTop: 6 }}>Dismiss</button>
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
                {canEdit ? (
                  <button onClick={() => setOpenItem(item)} title="Open item"
                          style={{ background: "none", border: "none", padding: 0,
                                   font: "inherit", color: "var(--sp-navy)",
                                   fontWeight: 600, cursor: "pointer",
                                   textDecoration: "underline" }}>
                    {item.code || "(no code)"}</button>
                ) : item.code}</td>
              <td style={td}>{item.description}
                {item.is_provisional && (
                  <span style={{ marginLeft: 6, background: "#fdf1d6",
                                 color: "#8a5a00", fontSize: 10.5,
                                 padding: "1px 6px", borderRadius: 5 }}>
                    provisional</span>
                )}
                {item.spec_ref && (
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>
                    {item.spec_ref}</div>
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
                  <button onClick={() => setOpenItem(item)}
                          style={{ ...ghostButton, padding: "2px 10px",
                                   fontSize: 12 }}>Open</button>
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

      {openItem && (
        <ItemDialog item={openItem} categories={categories}
                    onClose={() => setOpenItem(null)}
                    onSaved={load} onError={setError} />
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
