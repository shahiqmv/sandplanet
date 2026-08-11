import { Fragment, useEffect, useRef, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Chip, Eyebrow, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

const EDIT_ROLES = ["PM", "ADMIN", "DIRECTOR", "QS"];
// BOQ rates and values carry 3 dp (QS working precision, owner 2026-07-27).
const fmt = (v) =>
  Number(v || 0).toLocaleString("en-US", { minimumFractionDigits: 3,
    maximumFractionDigits: 3 });

// Row reordering helpers for the BOQ editors — the backend stores rows in the
// order sent (sort_order = array index), so shuffling the array is all it takes.
const moveRow = (rows, i, dir) => {
  const j = i + dir;
  if (j < 0 || j >= rows.length) return rows;
  const next = rows.slice();
  [next[i], next[j]] = [next[j], next[i]];
  return next;
};
const insertBelow = (rows, i, row) => {
  const next = rows.slice();
  next.splice(i + 1, 0, row);
  return next;
};
const miniBtn = { ...ghostButton, padding: "1px 6px", fontSize: 12,
  lineHeight: 1.3, minWidth: 22 };
// The compact per-row toolbar: move up / down, insert below, delete.
function RowTools({ rows, i, setRows, blank }) {
  return (
    <div style={{ display: "flex", gap: 2 }}>
      <button type="button" title="Move up" disabled={i === 0}
        onClick={() => setRows(moveRow(rows, i, -1))} style={miniBtn}>▲</button>
      <button type="button" title="Move down" disabled={i === rows.length - 1}
        onClick={() => setRows(moveRow(rows, i, 1))} style={miniBtn}>▼</button>
      <button type="button" title="Insert a row below"
        onClick={() => setRows(insertBelow(rows, i, blank()))} style={miniBtn}>＋</button>
      <button type="button" title="Delete row"
        onClick={() => setRows(rows.filter((_, j) => j !== i))}
        style={{ ...miniBtn, color: "#c0392b" }}>×</button>
    </div>
  );
}

// The project's Bill of Quantities — the priced contract schedule the QS runs
// progress claims against. Import from Excel (or edit by hand), reconcile to
// the contract value, then lock it to start claiming.
export default function BoqPanel({ projectId, project, me }) {
  const [boq, setBoq] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(null);   // BOQ-capture review draft
  const [pending, setPending] = useState(null); // an un-committed capture draft
  const [unitDraft, setUnitDraft] = useState(null); // reviewed unit categories
  const fileRef = useRef(null);
  const captureRef = useRef(null);
  const unitRef = useRef(null);
  const canEdit = EDIT_ROLES.includes(me.role);

  function load() {
    setError(null);
    api(`/projects/${projectId}/boq`).then(setBoq)
      .catch((e) => setError(e.message));
    api(`/projects/${projectId}/boq/capture/draft`).then(setPending)
      .catch(() => {});
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
  async function captureFile(file) {
    if (!file) return;
    setError(null); setBusy(true);
    const fd = new FormData();
    fd.append("file", file);
    try {
      setDraft(await apiUpload(`/projects/${projectId}/boq/capture`, fd));
    } catch (e) { setError(e.message); }
    setBusy(false);
  }
  async function captureUnit(file) {
    if (!file) return;
    setError(null); setBusy(true);
    const fd = new FormData();
    fd.append("file", file);
    try {
      setUnitDraft(await apiUpload(
        `/projects/${projectId}/boq/capture-unit`, fd));
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
  async function delBoq() {
    if (!window.confirm(
      "Delete this draft BOQ and all its lines? This can't be undone — "
      + "you'll need to re-enter or re-capture it.")) return;
    setError(null); setBusy(true);
    try {
      const data = await api(`/projects/${projectId}/boq/delete`,
        { method: "DELETE" });
      setBoq(data); setDraft(null); setUnitDraft(null); setPending(null);
    } catch (e) { setError(e.message); }
    setBusy(false);
  }

  if (error && !boq) return <section style={card}>{error}</section>;
  if (!boq) return <section style={card}>Loading…</section>;

  const editable = canEdit && !boq.is_locked;
  const isUnit = boq.exists && boq.mode === "UNIT";
  // Unit BOQs are counted by category; lump-only bills have no BoqItem rows, so
  // items.length would read 0 and (below) hide the Lock button.
  const lineCount = isUnit ? (boq.categories?.length || 0)
    : (boq.exists ? boq.items.length : 0);
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

  if (draft) {
    return <BoqCaptureReview draft={draft} onDone={(loaded) => {
      if (loaded) setBoq(loaded);
      setDraft(null); setPending(null);
    }} />;
  }

  if (unitDraft) {
    return <BoqUnitReview projectId={projectId} draft={unitDraft}
      currency={boq.currency} onDone={(done) => {
        setUnitDraft(null); if (done) load();
      }} />;
  }

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "center", gap: 12,
                    flexWrap: "wrap", marginBottom: 6 }}>
        <Eyebrow meta={boq.exists
          ? `${lineCount} ${isUnit ? "categories" : "lines"}` : ""}>
          Bill of Quantities{isUnit ? " · unit-based" : ""}
        </Eyebrow>
        {boq.exists && (
          <Chip tone={boq.is_locked ? "alert" : "info"}>
            {boq.is_locked ? "Locked" : "Draft"}</Chip>
        )}
        {boq.exists && boq.split_rates && <Chip tone="info">Supply + Install</Chip>}
        {boq.exists && isUnit
          && boq.categories?.some((c) => c.is_split) && (
          <label style={{ fontSize: 12, color: "var(--muted)" }}
                 title="CATEGORY: claim units delivered/installed × the per-unit rates. DETAIL: the client certifies actual material quantities from the build-ups — material and workmanship both derive from each quantity. Delete + recreate an open draft claim after switching.">
            Claims{" "}
            <select value={boq.claim_level || "CATEGORY"} disabled={!canEdit}
                    onChange={async (e) => {
                      try {
                        setBoq(await api(
                          `/projects/${projectId}/boq/claim-level`,
                          { method: "POST",
                            body: { level: e.target.value } }));
                      } catch (err) { setError(err.message); }
                    }}
                    style={{ ...inputStyle, width: 210, padding: "2px 6px",
                             fontSize: 12 }}>
              <option value="CATEGORY">per unit (summary)</option>
              <option value="DETAIL">per material (build-up qty)</option>
            </select>
          </label>
        )}
        {canEdit && (
          <div style={{ marginLeft: "auto", display: "flex", gap: 8,
                        flexWrap: "wrap" }}>
            {!isUnit && (
              <a href={`/api/v1/projects/${projectId}/boq/template`}
                 style={{ ...ghostButton, textDecoration: "none",
                          padding: "4px 12px" }}>⬇ Template</a>
            )}
            {editable && (
              <>
                {(!boq.exists || isUnit) && (
                  <>
                    <button style={{ ...buttonStyle, padding: "4px 12px" }}
                            disabled={busy}
                            onClick={() => unitRef.current?.click()}
                            title={"Capture a unit-based BOQ — works priced per "
                              + "unit (villa/room) × quantity, plus lump bills. "
                              + "Excel gives the cleanest capture (one sheet per "
                              + "bill); PDF also accepted."}>
                      {busy ? "Reading…" : "✦ Unit-based BOQ"}</button>
                    <input ref={unitRef} type="file" accept=".xlsx,.xlsm,.xls,.pdf"
                           style={{ display: "none" }}
                           onChange={(e) => captureUnit(e.target.files[0])} />
                  </>
                )}
                {!isUnit && (
                  <>
                    <button style={{ ...buttonStyle, padding: "4px 12px" }}
                            disabled={busy}
                            onClick={() => captureRef.current?.click()}
                            title={"Extract a client BOQ PDF or Excel into a "
                              + "reviewable draft"}>
                      {busy ? "Reading…" : "✦ Capture from PDF/Excel"}</button>
                    <input ref={captureRef} type="file" accept=".pdf,.xlsx,.xlsm"
                           style={{ display: "none" }}
                           onChange={(e) => captureFile(e.target.files[0])} />
                    <button style={{ ...ghostButton, padding: "4px 12px" }}
                            disabled={busy}
                            onClick={() => fileRef.current?.click()}>
                      ⬆ Import template</button>
                    <input ref={fileRef} type="file" accept=".xlsx"
                           style={{ display: "none" }}
                           onChange={(e) => importFile(e.target.files[0])} />
                    <button style={{ ...ghostButton, padding: "4px 12px" }}
                            onClick={() => setEditing(true)}>
                      ✎ {boq.exists ? "Edit" : "Enter manually"}</button>
                  </>
                )}
              </>
            )}
            {boq.exists && !boq.is_locked && lineCount > 0 && (
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
            {boq.exists && !boq.is_locked && (
              <button style={{ ...ghostButton, padding: "4px 12px",
                        color: "#c0392b", borderColor: "#e2b6b6" }}
                      disabled={busy} onClick={delBoq}
                      title="Delete this draft BOQ so it can be re-entered">
                🗑 Delete BOQ</button>
            )}
          </div>
        )}
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      {busy && <p style={{ color: "#5a6b78", fontSize: 12.5 }}>
        Reading the bill… a large BOQ can take a minute or two — please keep
        this tab open.</p>}

      {pending && editable && !draft && (
        <div style={{ display: "flex", alignItems: "center", gap: 10,
          padding: "8px 10px", borderRadius: 8, background: "#eef6f0",
          fontSize: 13, marginBottom: 8 }}>
          <span>A captured draft from <strong>{pending.filename
            || "a file"}</strong> is awaiting review
            ({pending.rows.length} lines).</span>
          <button style={{ ...buttonStyle, padding: "3px 12px",
            marginLeft: "auto" }} onClick={() => setDraft(pending)}>
            Resume review</button>
        </div>
      )}

      {!boq.exists ? (
        <p style={{ color: "var(--muted)", fontSize: 13 }}>
          No BOQ yet.{canEdit ? " Import your priced Excel bill, or enter it "
            + "manually — supply (material) and installation (labour) can be "
            + "separate columns or a single combined rate." : ""}
        </p>
      ) : boq.mode === "UNIT" ? (
        <BoqUnitSummary boq={boq} projectId={projectId} editable={editable}
          onChanged={setBoq} />
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

const cellIn = { ...inputStyle, padding: "3px 6px", fontSize: 12.5, width: 70 };

// Unit-based BOQ — category summary (per-unit × qty, or lump). A priced
// category expands to the works that build up its per-unit rate.
function BoqUnitSummary({ boq, projectId, editable, onChanged }) {
  const [open, setOpen] = useState(null);
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse",
                      fontSize: 12.5 }}>
        <thead><tr>
          <th style={{ ...th, width: 44 }}>Ref</th>
          <th style={th}>Description</th>
          <th style={{ ...th, textAlign: "right", width: 90 }}>Qty</th>
          <th style={{ ...th, textAlign: "right", width: 120 }}>Per unit</th>
          <th style={{ ...th, textAlign: "right", width: 130 }}>Amount</th>
          <th style={{ ...th, width: 90 }}></th>
        </tr></thead>
        <tbody>
          {boq.categories.map((c) => (
            <Fragment key={c.id}>
              <tr>
                <td style={td}>{c.ref}</td>
                <td style={td}>{c.name}{c.is_lump && <span style={{
                  color: "var(--muted)", fontSize: 11 }}> · lump sum</span>}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {c.is_lump ? "—" : `${fmt(c.qty)} ${c.unit}`}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {c.is_lump ? "—" : fmt(c.per_unit_total)}
                  {c.is_split && (
                    <div style={{ fontSize: 10.5, color: "var(--muted)",
                                  whiteSpace: "nowrap" }}
                         title="Material and workmanship certified separately on claims">
                      M {fmt(c.unit_amount_supply)} + W {fmt(c.unit_amount_install)}
                    </div>)}
                </td>
                <td style={{ ...td, textAlign: "right", fontWeight: 600 }}>
                  {fmt(c.line_total)}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {!c.is_lump && (
                    <button style={{ ...ghostButton, padding: "2px 8px",
                      fontSize: 11 }}
                      onClick={() => setOpen(open === c.id ? null : c.id)}>
                      {open === c.id ? "▾ Detail" : `▸ Detail`}
                      {c.items?.length > 1 ? ` (${c.items.length})` : ""}
                    </button>)}
                </td>
              </tr>
              {open === c.id && !c.is_lump && (
                <tr><td colSpan={6} style={{ padding: "0 8px 10px",
                  background: "var(--sky-soft)" }}>
                  <CategoryDetail cat={c} projectId={projectId}
                    editable={editable} onChanged={onChanged} />
                </td></tr>)}
            </Fragment>
          ))}
        </tbody>
      </table>
      <div style={{ textAlign: "right", marginTop: 10, fontSize: 15 }}>
        Contract value <strong>{boq.currency} {fmt(boq.contract_value)}</strong>
      </div>
    </div>
  );
}

// The works that build up one category's per-unit rate — view or edit.
function CategoryDetail({ cat, projectId, editable, onChanged }) {
  const blank = () => ({ description: "", unit: "", quantity: "1",
    rate_material: "", rate_labour: "" });
  const start = () => (cat.items?.length
    ? cat.items.map((i) => ({ description: i.description, unit: i.unit,
        quantity: i.qty, rate_material: i.rate_material ?? "",
        rate_labour: i.rate_labour ?? "" }))
    : [blank()]);
  const [rows, setRows] = useState(start);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  // material + labour, like a conventional split-rate BOQ line
  const amt = (r) => Number(r.quantity || 0) *
    (Number(r.rate_material || 0) + Number(r.rate_labour || 0));
  const total = rows.reduce((s, r) => s + amt(r), 0);
  const setR = (i, k, v) => setRows((rs) =>
    rs.map((r, j) => j === i ? { ...r, [k]: v } : r));

  async function save() {
    setErr(null); setBusy(true);
    try {
      const data = await api(
        `/projects/${projectId}/boq/categories/${cat.id}/items`,
        { method: "POST", body: { rows: rows.filter((r) =>
          r.description.trim() &&
          (Number(r.rate_material) > 0 || Number(r.rate_labour) > 0)) } });
      onChanged(data);
    } catch (e) { setErr(e.message); }
    setBusy(false);
  }

  return (
    <div style={{ padding: "8px 4px" }}>
      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>
        Works building the per-{cat.unit || "unit"} rate
        {!editable && " (read-only — BOQ locked)"}</div>
      <table style={{ width: "100%", borderCollapse: "collapse",
        fontSize: 12 }}>
        <thead><tr style={{ color: "var(--muted)" }}>
          <th style={{ ...th, textAlign: "left" }}>Work / item</th>
          <th style={{ ...th, width: 54 }}>Unit</th>
          <th style={{ ...th, textAlign: "right", width: 60 }}>Qty</th>
          <th style={{ ...th, textAlign: "right", width: 84 }}>Material</th>
          <th style={{ ...th, textAlign: "right", width: 84 }}>Labour</th>
          <th style={{ ...th, textAlign: "right", width: 100 }}>Amount</th>
          <th style={{ ...th, width: 108 }}></th>
        </tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ padding: 2 }}>
                <input value={r.description} disabled={!editable}
                  onChange={(e) => setR(i, "description", e.target.value)}
                  style={{ ...inputStyle, width: "100%" }} /></td>
              <td style={{ padding: 2 }}>
                <input value={r.unit} disabled={!editable}
                  onChange={(e) => setR(i, "unit", e.target.value)}
                  style={{ ...inputStyle, width: "100%" }} /></td>
              <td style={{ padding: 2 }}>
                <input type="number" value={r.quantity} disabled={!editable}
                  onChange={(e) => setR(i, "quantity", e.target.value)}
                  style={{ ...inputStyle, width: "100%", textAlign: "right" }} />
              </td>
              <td style={{ padding: 2 }}>
                <input type="number" value={r.rate_material} disabled={!editable}
                  onChange={(e) => setR(i, "rate_material", e.target.value)}
                  style={{ ...inputStyle, width: "100%", textAlign: "right" }} />
              </td>
              <td style={{ padding: 2 }}>
                <input type="number" value={r.rate_labour} disabled={!editable}
                  onChange={(e) => setR(i, "rate_labour", e.target.value)}
                  style={{ ...inputStyle, width: "100%", textAlign: "right" }} />
              </td>
              <td style={{ ...td, textAlign: "right" }}>{fmt(amt(r))}</td>
              <td style={{ padding: 2, textAlign: "center" }}>
                {editable && (
                  <RowTools rows={rows} i={i} setRows={setRows} blank={blank} />
                )}</td>
            </tr>
          ))}
          <tr style={{ fontWeight: 600 }}>
            <td style={td} colSpan={5}>Per-unit total</td>
            <td style={{ ...td, textAlign: "right" }}>{fmt(total)}</td>
            <td style={td}></td>
          </tr>
        </tbody>
      </table>
      {err && <div style={{ color: "var(--red-fg)", fontSize: 12 }}>{err}</div>}
      {editable && (
        <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
          <button style={{ ...ghostButton, padding: "3px 10px", fontSize: 12 }}
            onClick={() => setRows((rs) => [...rs, blank()])}>+ Add work</button>
          <button style={{ ...buttonStyle, padding: "3px 12px", fontSize: 12 }}
            disabled={busy} onClick={save}>
            {busy ? "Saving…" : "Save build-up"}</button>
        </div>)}
    </div>
  );
}

// Review the AI-captured unit categories (editable) before committing.
function BoqUnitReview({ projectId, draft, currency, onDone }) {
  const [cats, setCats] = useState(draft.categories.map((c) => ({ ...c })));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const upd = (i, k, v) => setCats((cs) =>
    cs.map((c, j) => (j === i ? { ...c, [k]: v } : c)));
  // Split-priced rows (material + workmanship per unit): editing either leg
  // keeps the combined amount_per_unit = their sum.
  const isSplit = (c) => !c.is_lump && (c.amount_per_unit_material !== ""
    && c.amount_per_unit_material != null
    || c.amount_per_unit_labour !== "" && c.amount_per_unit_labour != null);
  const updSplit = (i, k, v) => setCats((cs) => cs.map((c, j) => {
    if (j !== i) return c;
    const next = { ...c, [k]: v };
    next.amount_per_unit = String(
      Number(next.amount_per_unit_material || 0)
      + Number(next.amount_per_unit_labour || 0));
    return next;
  }));
  const lineTotal = (c) => c.is_lump ? Number(c.amount_per_unit || 0)
    : Number(c.amount_per_unit || 0) * Number(c.quantity || 0);
  const total = cats.reduce((a, c) => a + lineTotal(c), 0);
  async function commit() {
    setBusy(true); setErr(null);
    try {
      await api(`/projects/${projectId}/boq/commit-unit`,
        { method: "POST", body: { categories: cats } });
      onDone(true);
    } catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10,
                    flexWrap: "wrap" }}>
        <Eyebrow>Review unit-based BOQ</Eyebrow>
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
          {cats.length} categories{draft.gst_percent
            ? ` · GST ${draft.gst_percent}%` : ""} — fix any misread values,
          then import.</span>
      </div>
      {err && <p style={{ color: "#c0392b", fontSize: 13 }}>{err}</p>}
      <div style={{ overflowX: "auto", marginTop: 8 }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 12.5 }}>
          <thead><tr>
            <th style={{ ...th, width: 44 }}>Ref</th>
            <th style={th}>Description</th>
            <th style={{ ...th, width: 70 }}>Qty</th>
            <th style={{ ...th, width: 56 }}>Unit</th>
            <th style={{ ...th, textAlign: "right", width: 120 }}>Amount/unit</th>
            <th style={{ ...th, width: 52 }}>Works</th>
            <th style={{ ...th, width: 46 }}>Lump</th>
            <th style={{ ...th, textAlign: "right", width: 130 }}>Line total</th>
          </tr></thead>
          <tbody>
            {cats.map((c, i) => (
              <tr key={i}>
                <td style={td}><input style={cellIn} value={c.ref || ""}
                  onChange={(e) => upd(i, "ref", e.target.value)} /></td>
                <td style={td}><input style={{ ...cellIn, width: "100%" }}
                  value={c.name}
                  onChange={(e) => upd(i, "name", e.target.value)} /></td>
                <td style={td}><input style={cellIn} type="number"
                  disabled={c.is_lump} value={c.is_lump ? 1 : c.quantity}
                  onChange={(e) => upd(i, "quantity", e.target.value)} /></td>
                <td style={td}><input style={cellIn} value={c.unit}
                  onChange={(e) => upd(i, "unit", e.target.value)} /></td>
                <td style={td}>
                  {isSplit(c) ? (
                    <span style={{ whiteSpace: "nowrap" }}
                          title="Material + workmanship per unit — certified separately on claims">
                      <input style={{ ...cellIn, width: 64,
                          textAlign: "right" }} type="number" placeholder="Mat"
                        value={c.amount_per_unit_material || ""}
                        onChange={(e) => updSplit(i, "amount_per_unit_material",
                                                  e.target.value)} />
                      {" + "}
                      <input style={{ ...cellIn, width: 60,
                          textAlign: "right" }} type="number" placeholder="Wm"
                        value={c.amount_per_unit_labour || ""}
                        onChange={(e) => updSplit(i, "amount_per_unit_labour",
                                                  e.target.value)} />
                    </span>
                  ) : (
                    <input style={{ ...cellIn, textAlign: "right" }}
                      type="number" value={c.amount_per_unit}
                      onChange={(e) => upd(i, "amount_per_unit",
                                           e.target.value)} />
                  )}</td>
                <td style={{ ...td, textAlign: "center",
                  color: c.items?.length ? "var(--navy)" : "var(--muted)" }}
                  title="Detail works captured — review/fix after import">
                  {c.items?.length || "—"}</td>
                <td style={{ ...td, textAlign: "center" }}>
                  <input type="checkbox" checked={!!c.is_lump}
                    onChange={(e) => upd(i, "is_lump", e.target.checked)} /></td>
                <td style={{ ...td, textAlign: "right", fontWeight: 600 }}>
                  {fmt(lineTotal(c))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ textAlign: "right", marginTop: 10, fontSize: 15 }}>
        Total <strong>{currency} {fmt(total)}</strong></div>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button style={buttonStyle} disabled={busy || !cats.length}
          onClick={commit}>
          {busy ? "Importing…" : `Import ${cats.length} categories`}</button>
        <button style={ghostButton} onClick={() => onDone(false)}>Cancel</button>
      </div>
      <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
        Importing replaces the project's current BOQ and sets it to unit-based
        mode.</p>
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
          ) : it.is_discount ? (
            <tr key={it.id}>
              <td style={td}>{it.item_code}</td>
              <td style={{ ...td, whiteSpace: "pre-wrap" }}>{it.description}
                <span style={{ marginLeft: 6, fontSize: 10, color: "#8a1f2f",
                  background: "#fde8ec", padding: "0 5px", borderRadius: 8 }}>
                  Discount</span></td>
              <td style={td} colSpan={split ? 3 : 2} />
              <td style={{ ...td, textAlign: "right", fontWeight: 600,
                           color: "#b0402f" }}>{fmt(it.amount)}</td>
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
    unit: "", qty: "", rate_supply: "", rate_install: "", is_heading: false,
    is_discount: false });
  const [rows, setRows] = useState(
    boq.items.length
      ? boq.items.map((i) => ({ section: i.section, item_code: i.item_code,
          description: i.description, unit: i.unit,
          qty: i.qty ?? "", rate_supply: i.rate_supply ?? "",
          rate_install: i.rate_install ?? "", is_heading: i.is_heading,
          is_discount: i.is_discount }))
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
          Tick <b>H</b> for a bill/section heading. Tick <b>D</b> for a discount
          — enter the amount in Material; it lowers the BOQ total and is claimed
          by % like any line. Leave Labour blank for a combined rate.</span>
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
            {["H", "D", "Section", "Code", "Description", "Unit", "Qty",
              "Material", "Labour", ""].map((h, i) =>
              <th key={i} style={th}>{h}</th>)}
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td style={td}>
                  <input type="checkbox" checked={r.is_heading}
                         title="Heading row" disabled={r.is_discount}
                         onChange={(e) => set(i, "is_heading",
                           e.target.checked)} /></td>
                <td style={td}>
                  <input type="checkbox" checked={r.is_discount}
                         title="Discount line (enter amount in Material)"
                         disabled={r.is_heading}
                         onChange={(e) => set(i, "is_discount",
                           e.target.checked)} /></td>
                <td style={td}><input value={r.section} style={cell(120)}
                  onChange={(e) => set(i, "section", e.target.value)} /></td>
                <td style={td}><input value={r.item_code} style={cell(56)}
                  onChange={(e) => set(i, "item_code", e.target.value)} /></td>
                <td style={td}><input value={r.description} style={cell(280)}
                  onChange={(e) => set(i, "description", e.target.value)} /></td>
                <td style={td}><input value={r.unit} style={cell(50)}
                  disabled={r.is_heading || r.is_discount}
                  onChange={(e) => set(i, "unit", e.target.value)} /></td>
                <td style={td}><input value={r.qty} type="number" style={cell(70)}
                  disabled={r.is_heading || r.is_discount}
                  onChange={(e) => set(i, "qty", e.target.value)} /></td>
                <td style={td}><input value={r.rate_supply} type="number"
                  style={cell(80)} disabled={r.is_heading}
                  placeholder={r.is_discount ? "Discount amt" : ""}
                  onChange={(e) => set(i, "rate_supply", e.target.value)} /></td>
                <td style={td}><input value={r.rate_install} type="number"
                  style={cell(80)} disabled={r.is_heading || r.is_discount}
                  onChange={(e) => set(i, "rate_install", e.target.value)} /></td>
                <td style={td}>
                  <RowTools rows={rows} i={i} setRows={setRows} blank={blank} />
                </td>
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

// Review the draft captured from a client PDF/Excel: correct any cell, watch
// the reconciliation banner, then load it into the live BOQ.
function BoqCaptureReview({ draft, onDone }) {
  const clean = (rows) => rows.map((r) => ({
    section: r.section || "", item_code: r.item_code || "",
    description: r.description || "", unit: r.unit || "",
    qty: r.qty ?? "", rate_supply: r.rate_supply ?? "",
    rate_install: r.rate_install ?? "", rate_combined: r.rate_combined ?? "",
    is_heading: !!r.is_heading }));
  const blank = () => ({ section: "", item_code: "", description: "", unit: "",
    qty: "", rate_supply: "", rate_install: "", rate_combined: "",
    is_heading: false });
  const [d, setD] = useState(draft);
  const [rows, setRows] = useState(clean(draft.rows));
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const split = d.rate_mode === "SPLIT";
  const set = (i, k, v) =>
    setRows(rows.map((r, j) => j === i ? { ...r, [k]: v } : r));

  async function save() {
    setError(null); setBusy(true);
    try {
      const upd = await api(`/boq-imports/${d.id}`,
        { method: "PUT", body: { rows } });
      setD(upd); setRows(clean(upd.rows));
    } catch (e) { setError(e.message); }
    setBusy(false);
  }
  async function confirm() {
    setError(null); setBusy(true);
    try {
      await api(`/boq-imports/${d.id}`, { method: "PUT", body: { rows } });
      const boq = await api(`/boq-imports/${d.id}/commit`, { method: "POST" });
      onDone(boq);
    } catch (e) { setError(e.message); setBusy(false); }
  }
  async function discard() {
    if (!window.confirm("Discard this captured draft?")) return;
    try { await api(`/boq-imports/${d.id}`, { method: "DELETE" }); } catch { /* */ }
    onDone(null);
  }

  const m = d.meta || {};
  const priced = rows.filter((r) => !r.is_heading).length;
  const warnCount = (d.rows || []).reduce(
    (s, r) => s + (r.warnings?.length || 0), 0);

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                    marginBottom: 8, flexWrap: "wrap" }}>
        <Eyebrow meta={d.filename}>Review captured BOQ</Eyebrow>
        <Chip tone="info">{split ? "Supply + Install" : "Single rate"}</Chip>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <button style={{ ...ghostButton, color: "#c0392b" }} disabled={busy}
                  onClick={discard}>Discard</button>
          <button style={ghostButton} disabled={busy} onClick={save}>
            {busy ? "…" : "Save draft"}</button>
          <button style={{ ...buttonStyle, padding: "4px 14px" }} disabled={busy}
                  onClick={confirm}>Confirm &amp; load into BOQ</button>
        </div>
      </div>

      {/* reconciliation + warnings banner */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 12.5,
        padding: "8px 10px", borderRadius: 8, marginBottom: 8,
        background: m.reconciled === false ? "#fff4e5" : "#eef6f0" }}>
        <span>Extracted total <strong>{fmt(m.extracted_total)}</strong></span>
        {m.printed_total != null && (
          <span>PDF total <strong>{fmt(m.printed_total)}</strong>{" "}
            {m.reconciled === true ? "✓ matches"
              : m.reconciled === false ? "⚠ differs — check for missed lines"
              : ""}</span>
        )}
        {m.printed_total == null && (
          <span style={{ color: "var(--muted)" }}>
            no printed total found to reconcile against</span>
        )}
        <span style={{ marginLeft: "auto" }}>{priced} priced lines ·{" "}
          {warnCount > 0
            ? <strong style={{ color: "#b35900" }}>{warnCount} to check</strong>
            : "no warnings"}</span>
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "0 0 6px" }}>
        Correct anything the extractor got wrong, then confirm. Nothing touches
        the live BOQ until you load it. Save draft keeps your edits for later.
      </p>

      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 12 }}>
          <thead><tr>
            {["", "Section", "Code", "Description", "Unit", "Qty",
              ...(split ? ["Material", "Labour"] : ["Rate"]), "⚠", ""]
              .map((h, i) => <th key={i} style={th}>{h}</th>)}
          </tr></thead>
          <tbody>
            {rows.map((r, i) => {
              const w = d.rows[i]?.warnings || [];
              return (
                <tr key={i} style={w.length
                  ? { background: "#fff8ef" } : undefined}>
                  <td style={td}>
                    <input type="checkbox" checked={r.is_heading}
                      title="Heading row"
                      onChange={(e) => set(i, "is_heading", e.target.checked)} />
                  </td>
                  <td style={td}><input value={r.section} style={cell(110)}
                    onChange={(e) => set(i, "section", e.target.value)} /></td>
                  <td style={td}><input value={r.item_code} style={cell(52)}
                    onChange={(e) => set(i, "item_code", e.target.value)} /></td>
                  <td style={td}><input value={r.description} style={cell(260)}
                    onChange={(e) => set(i, "description", e.target.value)} /></td>
                  <td style={td}><input value={r.unit} style={cell(46)}
                    disabled={r.is_heading}
                    onChange={(e) => set(i, "unit", e.target.value)} /></td>
                  <td style={td}><input value={r.qty} style={cell(66)}
                    disabled={r.is_heading}
                    onChange={(e) => set(i, "qty", e.target.value)} /></td>
                  {split ? (
                    <>
                      <td style={td}><input value={r.rate_supply} style={cell(74)}
                        disabled={r.is_heading}
                        onChange={(e) => set(i, "rate_supply",
                          e.target.value)} /></td>
                      <td style={td}><input value={r.rate_install} style={cell(74)}
                        disabled={r.is_heading}
                        onChange={(e) => set(i, "rate_install",
                          e.target.value)} /></td>
                    </>
                  ) : (
                    <td style={td}><input value={r.rate_combined} style={cell(74)}
                      disabled={r.is_heading}
                      onChange={(e) => set(i, "rate_combined",
                        e.target.value)} /></td>
                  )}
                  <td style={{ ...td, color: "#b35900", fontSize: 11,
                    maxWidth: 130 }} title={w.join(", ")}>
                    {w.length ? w.join(", ") : ""}</td>
                  <td style={td}>
                    <RowTools rows={rows} i={i} setRows={setRows}
                      blank={blank} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <button style={{ ...ghostButton, padding: "3px 10px", marginTop: 8 }}
        onClick={() => setRows([...rows, blank()])}>
        + row</button>
      <span style={{ fontSize: 11, color: "var(--muted)", marginLeft: 10 }}>
        Warnings refresh on Save draft.</span>
    </section>
  );
}
