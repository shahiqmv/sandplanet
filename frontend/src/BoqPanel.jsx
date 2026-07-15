import { useEffect, useRef, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Chip, Eyebrow, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

const EDIT_ROLES = ["PM", "ADMIN", "DIRECTOR", "QS"];
const fmt = (v) =>
  Number(v || 0).toLocaleString("en-US", { minimumFractionDigits: 2,
    maximumFractionDigits: 2 });

// The project's Bill of Quantities — the priced contract schedule the QS runs
// progress claims against. Import from Excel (or edit by hand), reconcile to
// the contract value, then lock it to start claiming.
export default function BoqPanel({ projectId, project, me }) {
  const [boq, setBoq] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const fileRef = useRef(null);
  const canEdit = EDIT_ROLES.includes(me.role);

  function load() {
    setError(null);
    api(`/projects/${projectId}/boq`).then(setBoq)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function importFile(file) {
    if (!file) return;
    setError(null); setBusy(true);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const data = await apiUpload(`/projects/${projectId}/boq/import`, fd);
      setBoq(data);
    } catch (e) { setError(e.message); }
    setBusy(false);
  }
  async function lock(locked) {
    setError(null); setBusy(true);
    try {
      const data = await api(`/projects/${projectId}/boq/lock`,
        { method: "POST", body: { locked } });
      setBoq(data);
    } catch (e) { setError(e.message); }
    setBusy(false);
  }

  if (error && !boq) return <section style={card}>{error}</section>;
  if (!boq) return <section style={card}>Loading…</section>;

  const editable = canEdit && !boq.is_locked;
  const contractVal = project.contract_value != null
    ? Number(project.contract_value) : null;
  const delta = contractVal != null ? boq.total - contractVal : null;
  const reconciled = delta != null && Math.abs(delta) < 0.5;

  if (editing) {
    return <BoqEditor projectId={projectId} boq={boq} onDone={(saved) => {
      if (saved) setBoq(saved);
      setEditing(false);
    }} />;
  }

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "center", gap: 12,
                    flexWrap: "wrap", marginBottom: 6 }}>
        <Eyebrow meta={boq.exists ? `${boq.items.length} lines` : ""}>
          Bill of Quantities
        </Eyebrow>
        {boq.exists && (
          <Chip tone={boq.is_locked ? "alert" : "info"}>
            {boq.is_locked ? "Locked" : "Draft"}</Chip>
        )}
        {boq.exists && boq.split_rates && <Chip tone="info">Supply + Install</Chip>}
        {canEdit && (
          <div style={{ marginLeft: "auto", display: "flex", gap: 8,
                        flexWrap: "wrap" }}>
            <a href={`/api/v1/projects/${projectId}/boq/template`}
               style={{ ...ghostButton, textDecoration: "none",
                        padding: "4px 12px" }}>⬇ Template</a>
            {editable && (
              <>
                <button style={{ ...ghostButton, padding: "4px 12px" }}
                        disabled={busy}
                        onClick={() => fileRef.current?.click()}>
                  ⬆ Import Excel</button>
                <input ref={fileRef} type="file" accept=".xlsx"
                       style={{ display: "none" }}
                       onChange={(e) => importFile(e.target.files[0])} />
                <button style={{ ...ghostButton, padding: "4px 12px" }}
                        onClick={() => setEditing(true)}>
                  ✎ {boq.exists ? "Edit" : "Enter manually"}</button>
              </>
            )}
            {boq.exists && !boq.is_locked && boq.items.length > 0 && (
              <button style={{ ...buttonStyle, padding: "4px 12px" }}
                      disabled={busy} onClick={() => lock(true)}
                      title="Locks the contract baseline so claims can start">
                🔒 Lock BOQ</button>
            )}
            {boq.is_locked && ["ADMIN", "DIRECTOR"].includes(me.role) && (
              <button style={{ ...ghostButton, padding: "4px 12px" }}
                      disabled={busy} onClick={() => lock(false)}>
                Unlock</button>
            )}
          </div>
        )}
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {!boq.exists ? (
        <p style={{ color: "var(--muted)", fontSize: 13 }}>
          No BOQ yet.{canEdit ? " Import your priced Excel bill, or enter it "
            + "manually — supply (material) and installation (labour) can be "
            + "separate columns or a single combined rate." : ""}
        </p>
      ) : (
        <>
          <BoqTable boq={boq} />
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 24,
                        marginTop: 10, fontSize: 13, flexWrap: "wrap" }}>
            {boq.split_rates && (
              <>
                <span>Supply <strong>{boq.currency} {fmt(boq.total_supply)}</strong></span>
                <span>Install <strong>{boq.currency} {fmt(boq.total_install)}</strong></span>
              </>
            )}
            <span style={{ fontSize: 15 }}>
              BOQ total <strong>{boq.currency} {fmt(boq.total)}</strong></span>
          </div>
          {contractVal != null && (
            <p style={{ textAlign: "right", fontSize: 12.5, marginTop: 4,
              color: reconciled ? "#1a7f37" : "#b35900" }}>
              {reconciled ? "✓ reconciles with the contract value"
                : `⚠ contract value is ${boq.currency} ${fmt(contractVal)} — `
                  + `off by ${boq.currency} ${fmt(Math.abs(delta))}`}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function BoqTable({ boq }) {
  const split = boq.split_rates;
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse",
                      fontSize: 12.5 }}>
        <thead>
          <tr>
            <th style={{ ...th, width: 54 }}>Code</th>
            <th style={th}>Description</th>
            <th style={{ ...th, width: 44 }}>Unit</th>
            <th style={{ ...th, textAlign: "right", width: 70 }}>Qty</th>
            {split ? (
              <>
                <th style={{ ...th, textAlign: "right" }}>Material</th>
                <th style={{ ...th, textAlign: "right" }}>Labour</th>
              </>
            ) : (
              <th style={{ ...th, textAlign: "right" }}>Rate</th>
            )}
            <th style={{ ...th, textAlign: "right", width: 100 }}>Amount</th>
          </tr>
        </thead>
        <tbody>
          {boq.items.map((it) => it.is_heading ? (
            <tr key={it.id}>
              <td colSpan={split ? 7 : 6}
                  style={{ ...td, fontWeight: 700, color: "var(--navy)",
                           background: "#f4f7fa" }}>
                {it.item_code ? `${it.item_code}  ` : ""}{it.description
                  || it.section}</td>
            </tr>
          ) : (
            <tr key={it.id}>
              <td style={td}>{it.item_code}</td>
              <td style={{ ...td, whiteSpace: "pre-wrap" }}>{it.description}</td>
              <td style={td}>{it.unit}</td>
              <td style={{ ...td, textAlign: "right" }}>
                {it.qty != null ? fmt(it.qty) : ""}</td>
              {split ? (
                <>
                  <td style={{ ...td, textAlign: "right" }}>
                    {it.rate_supply != null ? fmt(it.rate_supply) : ""}</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {it.rate_install != null ? fmt(it.rate_install) : ""}</td>
                </>
              ) : (
                <td style={{ ...td, textAlign: "right" }}>
                  {fmt(it.rate_total)}</td>
              )}
              <td style={{ ...td, textAlign: "right", fontWeight: 600 }}>
                {fmt(it.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// A lightweight editable grid for manual entry / corrections. Import handles
// the bulk; this is for tweaks and small BOQs.
function BoqEditor({ projectId, boq, onDone }) {
  const blank = () => ({ section: "", item_code: "", description: "",
    unit: "", qty: "", rate_supply: "", rate_install: "", is_heading: false });
  const [rows, setRows] = useState(
    boq.items.length
      ? boq.items.map((i) => ({ section: i.section, item_code: i.item_code,
          description: i.description, unit: i.unit,
          qty: i.qty ?? "", rate_supply: i.rate_supply ?? "",
          rate_install: i.rate_install ?? "", is_heading: i.is_heading }))
      : [blank()]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (i, k, v) =>
    setRows(rows.map((r, j) => j === i ? { ...r, [k]: v } : r));

  async function save() {
    setError(null); setBusy(true);
    try {
      const data = await api(`/projects/${projectId}/boq/items`,
        { method: "POST", body: { rows } });
      onDone(data);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                    marginBottom: 8 }}>
        <Eyebrow>Edit BOQ</Eyebrow>
        <span style={{ fontSize: 12, color: "var(--muted)" }}>
          Tick a row as a heading for a bill/section title. Leave Labour blank
          for a combined rate.</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <button style={ghostButton} disabled={busy}
                  onClick={() => onDone(null)}>Cancel</button>
          <button style={{ ...buttonStyle, padding: "4px 14px" }}
                  disabled={busy} onClick={save}>
            {busy ? "Saving…" : "Save BOQ"}</button>
        </div>
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 12 }}>
          <thead><tr>
            {["", "Section", "Code", "Description", "Unit", "Qty", "Material",
              "Labour", ""].map((h, i) => <th key={i} style={th}>{h}</th>)}
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td style={td}>
                  <input type="checkbox" checked={r.is_heading}
                         title="Heading row"
                         onChange={(e) => set(i, "is_heading",
                           e.target.checked)} /></td>
                <td style={td}><input value={r.section} style={cell(120)}
                  onChange={(e) => set(i, "section", e.target.value)} /></td>
                <td style={td}><input value={r.item_code} style={cell(56)}
                  onChange={(e) => set(i, "item_code", e.target.value)} /></td>
                <td style={td}><input value={r.description} style={cell(280)}
                  onChange={(e) => set(i, "description", e.target.value)} /></td>
                <td style={td}><input value={r.unit} style={cell(50)}
                  disabled={r.is_heading}
                  onChange={(e) => set(i, "unit", e.target.value)} /></td>
                <td style={td}><input value={r.qty} type="number" style={cell(70)}
                  disabled={r.is_heading}
                  onChange={(e) => set(i, "qty", e.target.value)} /></td>
                <td style={td}><input value={r.rate_supply} type="number"
                  style={cell(80)} disabled={r.is_heading}
                  onChange={(e) => set(i, "rate_supply", e.target.value)} /></td>
                <td style={td}><input value={r.rate_install} type="number"
                  style={cell(80)} disabled={r.is_heading}
                  onChange={(e) => set(i, "rate_install", e.target.value)} /></td>
                <td style={td}>
                  <button style={{ ...ghostButton, color: "#c0392b",
                                   padding: "2px 8px" }}
                          onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                    ×</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button style={{ ...ghostButton, padding: "3px 10px", marginTop: 8 }}
              onClick={() => setRows([...rows, blank()])}>+ row</button>
    </section>
  );
}

const cell = (w) => ({ ...inputStyle, width: w, padding: "3px 5px",
  fontSize: 12 });
