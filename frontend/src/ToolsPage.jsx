import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

// Site Tools & Equipment register. Tools arrive from a verified GRN (tool
// categories) or are added manually on mobilisation; site staff fill serial /
// model and manage the faulty → repair → in-use cycle.

const STATE_LABEL = { IN_USE: "In use", FAULTY: "Faulty",
                      UNDER_REPAIR: "Under repair", RETIRED: "Retired" };
const STATE_TONE = { IN_USE: "#1a7f37", FAULTY: "#c0392b",
                     UNDER_REPAIR: "#b35900", RETIRED: "#9fb0bc" };
const FILTERS = [["", "All"], ["IN_USE", "In use"], ["FAULTY", "Faulty"],
                 ["UNDER_REPAIR", "Under repair"], ["RETIRED", "Retired"]];

const EMPTY = { name: "", category: "", serial_no: "", model: "", brand: "",
                notes: "" };

export default function ToolsPage({ site, me, onClose }) {
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState(EMPTY);
  const [edit, setEdit] = useState(null);   // asset being edited

  const canManage = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "ADMIN"]
    .includes(me.role);

  function load() {
    setError(null);
    api(`/tools/${site.id}${filter ? `?state=${filter}` : ""}`)
      .then(setData).catch((e) => setError(e.message));
  }
  useEffect(load, [site.id, filter]); // eslint-disable-line

  async function run(fn) {
    setError(null);
    try { await fn(); load(); } catch (e) { setError(e.message); }
  }

  const addTool = () => run(async () => {
    if (!draft.name.trim()) { setError("Tool name is required."); return; }
    await api(`/tools/${site.id}`, { method: "POST", body: draft });
    setDraft(EMPTY); setAdding(false);
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

  const tools = data?.tools || [];
  const c = data?.counts || {};

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

      {adding && (
        <div style={{ background: "var(--sp-tint,#f5f8fb)", borderRadius: 8,
                      padding: 12, margin: "10px 0", display: "flex", gap: 8,
                      flexWrap: "wrap" }}>
          <input placeholder="Tool name" value={draft.name}
                 onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                 style={{ ...inputStyle, flex: "1 1 200px" }} />
          <input placeholder="Category" value={draft.category}
                 onChange={(e) => setDraft({ ...draft,
                                             category: e.target.value })}
                 style={{ ...inputStyle, width: 130 }} />
          <input placeholder="Serial no." value={draft.serial_no}
                 onChange={(e) => setDraft({ ...draft,
                                             serial_no: e.target.value })}
                 style={{ ...inputStyle, width: 120 }} />
          <input placeholder="Model" value={draft.model}
                 onChange={(e) => setDraft({ ...draft, model: e.target.value })}
                 style={{ ...inputStyle, width: 110 }} />
          <input placeholder="Brand" value={draft.brand}
                 onChange={(e) => setDraft({ ...draft, brand: e.target.value })}
                 style={{ ...inputStyle, width: 110 }} />
          <Btn onClick={addTool}>Add</Btn>
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
      </div>

      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead><tr>
          <th style={th}>Tool</th><th style={th}>Category</th>
          <th style={th}>Serial</th><th style={th}>Model</th>
          <th style={th}>Brand</th><th style={th}>State</th>
          <th style={th}>From</th>{canManage && <th style={th} />}
        </tr></thead>
        <tbody>
          {tools.map((t) => (
            <tr key={t.id}>
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
              <td style={td}>{t.grn || (t.source === "MOBILISATION"
                ? "Mobilisation" : "Manual")}</td>
              {canManage && <td style={td}>{actions(t)}</td>}
            </tr>
          ))}
          {tools.length === 0 && (
            <tr><td colSpan={canManage ? 8 : 7}
                    style={{ ...td, color: "var(--muted)", textAlign: "center" }}>
              No tools {filter ? "in this state" : "yet"}. Verified GRNs in a
              tool category add them automatically.
            </td></tr>
          )}
        </tbody>
      </table>

      {edit && (
        <EditModal asset={edit} onClose={() => setEdit(null)}
          onSaved={() => { setEdit(null); load(); }} onError={setError} />
      )}
    </section>
  );
}

function EditModal({ asset, onClose, onSaved, onError }) {
  const [f, setF] = useState({ serial_no: asset.serial_no || "",
    model: asset.model || "", brand: asset.brand || "",
    category: asset.category || "", notes: asset.notes || "" });
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

  async function save() {
    setBusy(true); onError(null);
    try {
      await api(`/tools/asset/${asset.id}`, { method: "PATCH", body: f });
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
        <div style={{ marginTop: 12 }}>
          <L label="Serial no." k="serial_no" />
          <L label="Model" k="model" />
          <L label="Brand" k="brand" />
          <L label="Category" k="category" />
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
