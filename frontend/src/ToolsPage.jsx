import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

// Site Tools & Equipment register. Tools arrive from a verified GRN (items
// marked as tracked tools) or are added by the site: picked from the catalog
// or typed if the catalog lacks them, several units at a time. Site staff
// fill serial / model, manage the faulty → repair → in-use cycle, and take
// wrong entries off — back into counted stock when the thing is a hand tool
// rather than something tracked unit by unit (owner 2026-10-01).

const STATE_LABEL = { IN_USE: "In use", FAULTY: "Faulty",
                      UNDER_REPAIR: "Under repair", RETIRED: "Retired" };
const STATE_TONE = { IN_USE: "#1a7f37", FAULTY: "#c0392b",
                     UNDER_REPAIR: "#b35900", RETIRED: "#9fb0bc" };
const FILTERS = [["", "All"], ["IN_USE", "In use"], ["FAULTY", "Faulty"],
                 ["UNDER_REPAIR", "Under repair"], ["RETIRED", "Retired"]];

const EMPTY = { item_id: "", new_name: "", qty: "1", serial_no: "", model: "",
                brand: "", notes: "" };
const NEW = "__new__";          // "it's not in the list — let me type it"
const FROM = { MOBILISATION: "Added by site", MANUAL: "Added by site",
               STOCK: "Moved from stock" };

export default function ToolsPage({ site, me, onClose }) {
  const [data, setData] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState(EMPTY);
  const [edit, setEdit] = useState(null);   // asset being edited
  const [q, setQ] = useState("");            // search the register
  const [picked, setPicked] = useState({});  // asset id -> ticked, to remove
  const [removing, setRemoving] = useState(null);  // {reason, to_stock}
  const [note, setNote] = useState(null);    // result of the last action

  const canManage = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "DIRECTOR", "ADMIN"]
    .includes(me.role);

  function load() {
    setError(null);
    api(`/tools/${site.id}${filter ? `?state=${filter}` : ""}`)
      .then(setData).catch((e) => setError(e.message));
  }
  useEffect(load, [site.id, filter]); // eslint-disable-line
  useEffect(() => {
    api("/tool-catalog").then(setCatalog).catch(() => setCatalog(
      { categories: [], items: [] }));
  }, []);

  async function run(fn) {
    setError(null);
    try { await fn(); load(); } catch (e) { setError(e.message); }
  }

  const typing = draft.item_id === NEW
    || (catalog && catalog.items.length === 0);
  const qty = Number(draft.qty) || 0;

  const addTool = () => run(async () => {
    setNote(null);
    if (typing ? !draft.new_name.trim() : !draft.item_id) {
      setError(typing ? "Type the tool's name." : "Pick the tool."); return;
    }
    const body = { qty, serial_no: draft.serial_no, model: draft.model,
                   brand: draft.brand, notes: draft.notes };
    if (typing) body.new_name = draft.new_name; else body.item_id = draft.item_id;
    const r = await api(`/tools/${site.id}`, { method: "POST", body });
    setNote(`Added ${r.added.length} × ${r.added[0].name}.`);
    if (typing) setCatalog(await api("/tool-catalog"));
    setDraft(EMPTY); setAdding(false);
  });

  // A tool type the catalog lacks, from the Edit window: named there and
  // then, created as a tracked tool, and returned to be picked.
  async function createToolType() {
    const name = window.prompt(
      "New tool type name (e.g. Circular Saw 8 Inch):");
    if (!name || !name.trim()) return null;
    const item = await api("/items", { method: "POST",
      body: { description: name.trim(), unit: "nos", tracked_tool: true,
              category: catalog?.categories?.[0] || "Tools & Equipment" } });
    setCatalog(await api("/tool-catalog"));
    return item;
  }

  const ids = Object.keys(picked).filter((k) => picked[k]).map(Number);
  const removeTicked = () => run(async () => {
    setNote(null);
    if (!removing.reason.trim()) { setError("Say why they are being removed."); return; }
    const r = await api(`/tools/${site.id}/remove`, { method: "POST",
      body: { ids, reason: removing.reason, to_stock: removing.to_stock } });
    setNote(`Removed ${r.removed} from the register`
      + (removing.to_stock ? " and returned them to stock." : ".")
      + (r.kept.length ? ` ${r.kept.length} could not be removed because they `
        + "have been transferred between sites — retire those instead." : ""));
    setPicked({}); setRemoving(null);
  });

  const changeState = (t, state, needNote) => run(async () => {
    const note = window.prompt(
      state === "FAULTY" ? "What's the fault? (required)"
      : state === "RETIRED" ? "Reason for retiring (required)"
      : state === "UNDER_REPAIR" ? "Repair note (where sent, etc.)"
      : "Note (optional)");
    if (needNote && !(note || "").trim()) return;
    if (note === null && needNote) return;
    await api(`/tools/asset/${t.id}/state`,
              { method: "POST", body: { state, note: note || "" } });
  });

  const needle = q.trim().toLowerCase();
  const tools = (data?.tools || []).filter((t) => !needle
    || `${t.name} ${t.serial_no} ${t.model} ${t.brand} ${t.grn || ""}`
      .toLowerCase().includes(needle));
  const c = data?.counts || {};
  const allTicked = tools.length > 0 && tools.every((t) => picked[t.id]);

  const actions = (t) => {
    if (!canManage || t.state === "RETIRED") return null;
    const b = { ...ghostButton, padding: "2px 8px", fontSize: 11 };
    return (
      <span style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        <button style={b} onClick={() => setEdit({ ...t })}>Edit</button>
        {t.state === "IN_USE" && (
          <button style={{ ...b, color: "#c0392b" }}
                  onClick={() => changeState(t, "FAULTY", true)}>Faulty</button>
        )}
        {t.state === "FAULTY" && (
          <button style={b}
                  onClick={() => changeState(t, "UNDER_REPAIR", false)}>
            Send for repair</button>
        )}
        {(t.state === "FAULTY" || t.state === "UNDER_REPAIR") && (
          <button style={{ ...b, color: "#1a7f37" }}
                  onClick={() => changeState(t, "IN_USE", false)}>
            Return to use</button>
        )}
        <button style={b} onClick={() => changeState(t, "RETIRED", true)}>
          Retire</button>
      </span>
    );
  };

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 17 }}>
          Tools &amp; Equipment — {site.code}</h2>
        {canManage && (
          <Btn onClick={() => setAdding((v) => !v)}>🔧 Add tool</Btn>
        )}
        <button onClick={onClose}
                style={{ ...ghostButton, marginLeft: "auto" }}>← Back</button>
      </div>
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      {note && <p style={{ color: "var(--green-fg)", fontSize: 13 }}>{note}</p>}

      {adding && (
        <div style={{ background: "var(--sp-tint,#f5f8fb)", borderRadius: 8,
                      padding: 12, margin: "10px 0", display: "flex", gap: 8,
                      flexWrap: "wrap", alignItems: "center" }}>
          {catalog && catalog.items.length > 0 && (
            <select value={draft.item_id}
                    onChange={(e) => setDraft({ ...draft,
                                                item_id: e.target.value })}
                    style={{ ...inputStyle, flex: "1 1 240px" }}>
              <option value="">— choose tool —</option>
              <option value={NEW}>✎ Not in the list — type its name</option>
              {(catalog?.categories || []).map((cat) => (
                <optgroup key={cat} label={cat}>
                  {catalog.items.filter((i) => i.category === cat).map((i) => (
                    <option key={i.id} value={i.id}>{i.description}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          )}
          {typing && (
            <input autoFocus placeholder="Tool name, e.g. Plate Compactor"
                   value={draft.new_name}
                   onChange={(e) => setDraft({ ...draft,
                                               new_name: e.target.value })}
                   style={{ ...inputStyle, flex: "1 1 240px" }} />
          )}
          <label style={{ fontSize: 12.5, display: "flex", gap: 6,
                          alignItems: "center" }}>
            How many
            <input type="number" min="1" max="50" value={draft.qty}
                   onChange={(e) => setDraft({ ...draft, qty: e.target.value })}
                   style={{ ...inputStyle, width: 70 }} /></label>
          <input placeholder={qty > 1 ? "Serials — fill in after" : "Serial no."}
                 value={qty > 1 ? "" : draft.serial_no} disabled={qty > 1}
                 onChange={(e) => setDraft({ ...draft,
                                             serial_no: e.target.value })}
                 style={{ ...inputStyle, width: 150 }} />
          <input placeholder="Model" value={draft.model}
                 onChange={(e) => setDraft({ ...draft, model: e.target.value })}
                 style={{ ...inputStyle, width: 110 }} />
          <input placeholder="Brand" value={draft.brand}
                 onChange={(e) => setDraft({ ...draft, brand: e.target.value })}
                 style={{ ...inputStyle, width: 110 }} />
          <Btn onClick={addTool}>
            {qty > 1 ? `Add ${qty} units` : "Add"}</Btn>
          <div style={{ flexBasis: "100%", fontSize: 12,
                        color: "var(--muted)" }}>
            {typing
              ? "A tool you type is added to the catalog as a tracked tool; "
                + "Purchasing checks the spelling later. Serial numbers are "
                + "optional and can be filled in afterwards."
              : "Serial numbers are optional and can be filled in afterwards."}
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 6, margin: "10px 0",
                    flexWrap: "wrap" }}>
        {FILTERS.map(([v, l]) => (
          <button key={v} onClick={() => setFilter(v)}
                  style={filter === v ? { ...buttonStyle, padding: "3px 12px",
                                          fontSize: 12 }
                                      : { ...ghostButton, padding: "3px 12px",
                                          fontSize: 12 }}>
            {l}{v && c[v] ? ` (${c[v]})` : ""}
          </button>
        ))}
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Find a tool, serial, GRN…"
               style={{ ...inputStyle, width: 210, padding: "3px 10px",
                        fontSize: 12.5, marginLeft: "auto" }} />
      </div>

      {canManage && ids.length > 0 && (
        <div style={{ border: "1px solid var(--sky)", borderRadius: 8,
                      background: "var(--sky-soft)", padding: "10px 14px",
                      marginBottom: 10, fontSize: 13 }}>
          {!removing ? (
            <div style={{ display: "flex", gap: 12, alignItems: "center",
                          flexWrap: "wrap" }}>
              <strong>{ids.length} ticked</strong>
              <Btn variant="secondary"
                   onClick={() => setRemoving({ reason: "", to_stock: true })}>
                Remove from register…</Btn>
              <button onClick={() => setPicked({})}
                      style={{ ...ghostButton, padding: "3px 10px",
                               fontSize: 12 }}>Clear</button>
              <span style={{ color: "var(--muted)", fontSize: 12 }}>
                For wrong entries and hand tools. A tool that is broken or
                gone is retired instead, so its history stays.</span>
            </div>
          ) : (
            <div style={{ display: "flex", gap: 10, alignItems: "center",
                          flexWrap: "wrap" }}>
              <strong>Remove {ids.length}:</strong>
              <label style={{ display: "flex", gap: 6, alignItems: "center",
                              cursor: "pointer" }}>
                <input type="radio" checked={removing.to_stock}
                       onChange={() => setRemoving({ ...removing,
                                                     to_stock: true })} />
                back into counted stock (hand tools, consumables)</label>
              <label style={{ display: "flex", gap: 6, alignItems: "center",
                              cursor: "pointer" }}>
                <input type="radio" checked={!removing.to_stock}
                       onChange={() => setRemoving({ ...removing,
                                                     to_stock: false })} />
                just remove (entered by mistake, not at site)</label>
              <input placeholder="Reason" value={removing.reason}
                     onChange={(e) => setRemoving({ ...removing,
                                                    reason: e.target.value })}
                     style={{ ...inputStyle, flex: "1 1 200px" }} />
              <Btn onClick={removeTicked}>Remove</Btn>
              <button onClick={() => setRemoving(null)}
                      style={{ ...ghostButton, padding: "4px 10px",
                               fontSize: 12 }}>Cancel</button>
            </div>
          )}
        </div>
      )}

      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead><tr>
          {canManage && (
            <th style={{ ...th, width: 28 }}>
              <input type="checkbox" checked={allTicked}
                     aria-label="Tick all shown"
                     onChange={() => setPicked(allTicked ? {}
                       : Object.fromEntries(tools.map((t) => [t.id, true])))} />
            </th>
          )}
          <th style={th}>Tool</th><th style={th}>Category</th>
          <th style={th}>Serial</th><th style={th}>Model</th>
          <th style={th}>Brand</th><th style={th}>State</th>
          <th style={th}>From</th>{canManage && <th style={th} />}
        </tr></thead>
        <tbody>
          {tools.map((t) => (
            <tr key={t.id}
                style={picked[t.id] ? { background: "var(--sky-soft)" }
                                    : undefined}>
              {canManage && (
                <td style={td}>
                  <input type="checkbox" checked={!!picked[t.id]}
                         aria-label={`Tick ${t.name}`}
                         onChange={() => setPicked({ ...picked,
                                                     [t.id]: !picked[t.id] })} />
                </td>
              )}
              <td style={{ ...td, fontWeight: 600 }}>{t.name}
                {t.state_note && (
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>
                    {t.state_note}</div>
                )}
              </td>
              <td style={td}>{t.category || "—"}</td>
              <td style={td}>{t.serial_no || "—"}</td>
              <td style={td}>{t.model || "—"}</td>
              <td style={td}>{t.brand || "—"}</td>
              <td style={{ ...td, color: STATE_TONE[t.state], fontWeight: 600 }}>
                {STATE_LABEL[t.state]}</td>
              <td style={td}>{t.source === "STOCK"
                ? `Stock${t.grn ? ` · ${t.grn}` : ""}`
                : t.grn || FROM[t.source] || "Added by site"}</td>
              {canManage && <td style={td}>{actions(t)}</td>}
            </tr>
          ))}
          {tools.length === 0 && (
            <tr><td colSpan={canManage ? 9 : 7}
                    style={{ ...td, color: "var(--muted)", textAlign: "center" }}>
              {needle ? "Nothing matches." : <>No tools {filter
                ? "in this state" : "yet"}. Tracked tools on a verified GRN
                are added automatically; add the rest with “Add tool”.</>}
            </td></tr>
          )}
        </tbody>
      </table>

      {edit && (
        <EditModal asset={edit} catalog={catalog} onNewType={createToolType}
          onClose={() => setEdit(null)}
          onSaved={() => { setEdit(null); load(); }} onError={setError} />
      )}
    </section>
  );
}

function EditModal({ asset, catalog, onNewType, onClose, onSaved, onError }) {
  const [f, setF] = useState({ serial_no: asset.serial_no || "",
    model: asset.model || "", brand: asset.brand || "",
    notes: asset.notes || "" });
  const [itemId, setItemId] = useState(String(asset.item_id || ""));
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

  async function addType() {
    onError(null);
    try {
      const item = await onNewType();
      if (item) setItemId(String(item.id));
    } catch (e) { onError(e.message); }
  }

  async function save() {
    setBusy(true); onError(null);
    try {
      await api(`/tools/asset/${asset.id}`,
                { method: "PATCH", body: { ...f, item_id: itemId } });
      onSaved();
    } catch (e) { onError(e.message); }
    finally { setBusy(false); }
  }

  const L = ({ label, k }) => (
    <label style={{ fontSize: 12.5, display: "block", marginBottom: 8 }}>
      <span style={{ color: "#5a6b78" }}>{label}</span>
      <input value={f[k]} onChange={(e) => set(k, e.target.value)}
             style={inputStyle} />
    </label>
  );

  return (
    <div onClick={onClose}
         style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.4)",
                  display: "flex", alignItems: "center",
                  justifyContent: "center", zIndex: 60, padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ ...card, maxWidth: 460, width: "100%" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 16 }}>
            {asset.name}</h2>
          <button onClick={onClose}
                  style={{ ...ghostButton, marginLeft: "auto" }}>Close</button>
        </div>
        <p style={{ fontSize: 12, color: "var(--muted)", margin: "2px 0 10px" }}>
          Tool type comes from the catalog — pick a different one to rename this
          unit (keeps every report consistent).
        </p>
        <div style={{ marginTop: 4 }}>
          <label style={{ fontSize: 12.5, display: "block", marginBottom: 8 }}>
            <span style={{ color: "#5a6b78" }}>Tool type</span>
            <div style={{ display: "flex", gap: 6 }}>
              <select value={itemId} onChange={(e) => setItemId(e.target.value)}
                      style={{ ...inputStyle, flex: "1 1 auto" }}>
                {!catalog?.items?.some((i) => String(i.id) === itemId) && (
                  <option value={itemId}>{asset.name}</option>
                )}
                {(catalog?.categories || []).map((cat) => (
                  <optgroup key={cat} label={cat}>
                    {(catalog?.items || []).filter((i) => i.category === cat)
                      .map((i) => (
                        <option key={i.id} value={String(i.id)}>
                          {i.description}</option>
                      ))}
                  </optgroup>
                ))}
              </select>
              <button onClick={addType} type="button"
                      style={{ ...ghostButton, padding: "6px 10px",
                               fontSize: 12, whiteSpace: "nowrap" }}
                      title="Add a tool type that isn't in the list">
                + New type</button>
            </div>
          </label>
          <L label="Serial no." k="serial_no" />
          <L label="Model" k="model" />
          <L label="Brand" k="brand" />
          <label style={{ fontSize: 12.5, display: "block" }}>
            <span style={{ color: "#5a6b78" }}>Notes</span>
            <textarea value={f.notes} rows={2}
                      onChange={(e) => set("notes", e.target.value)}
                      style={{ ...inputStyle, width: "100%" }} />
          </label>
        </div>
        <Btn onClick={save} disabled={busy} style={{ marginTop: 12 }}>
          {busy ? "Saving…" : "Save details"}</Btn>
      </div>
    </div>
  );
}
