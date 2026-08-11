import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Eyebrow, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

// Bill of Materials — the project's material QUANTITY budget and its live
// variance (owner 2026-08-11). Columns: BOM qty, requested (MRs), ordered
// (awarded domestic + authorised imports), issued from site stock, balance.
// Anything procured or issued with no BOM line shows in the red OFF-BOM
// section. Seeds from the unit BOQ's build-ups; the QS maps rows to
// Item-Master codes before committing.

const qf = (v) => v == null ? "—"
  : Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 });

export default function BomPanel({ projectId, me }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [mode, setMode] = useState("view");   // view | edit | seed
  const [items, setItems] = useState([]);

  const load = () => api(`/projects/${projectId}/bom`).then(setData)
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { api("/items").then(setItems).catch(() => {}); }, []);

  if (error) return <section style={card}>
    <p style={{ color: "#c0392b" }}>{error}</p></section>;
  if (!data) return <section style={card}>Loading…</section>;

  if (mode === "seed") return (
    <SeedReview projectId={projectId} items={items}
      onDone={(ok) => { setMode("view"); if (ok) load(); }}
      onError={setError} />
  );
  if (mode === "edit") return (
    <BomEditor projectId={projectId} items={items} current={data.rows}
      onDone={(ok) => { setMode("view"); if (ok) load(); }} />
  );

  const over = data.totals.over_count;
  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap" }}>
        <Eyebrow>Bill of Materials — quantity budget & variance</Eyebrow>
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
          {data.totals.bom_items} budgeted items
          {over > 0 && <strong style={{ color: "#c0392b" }}>
            {" "}· {over} over / off BOM</strong>}
        </span>
        <span style={{ flex: 1 }} />
        {data.can_edit && (
          <>
            {data.can_seed && (
              <button style={ghostButton} onClick={() => setMode("seed")}>
                ✦ Seed from BOQ build-ups</button>
            )}
            <button style={buttonStyle} onClick={() => setMode("edit")}>
              {data.rows.length ? "✏️ Edit BOM" : "+ Build BOM"}</button>
          </>
        )}
      </div>

      {!data.rows.length && !data.off_bom.length && (
        <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 12 }}>
          No BOM yet. {data.can_seed
            ? "Seed it from the BOQ's per-unit build-ups, or build it manually."
            : "Build it manually — this project's BOQ has no per-unit "
              + "build-ups to seed from."}</p>
      )}

      {data.rows.length > 0 && (
        <div style={{ overflowX: "auto", marginTop: 10 }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 12.5 }}>
            <thead><tr>
              <th style={th}>Code</th><th style={th}>Description</th>
              <th style={th}>Unit</th>
              <th style={{ ...th, textAlign: "right" }}>BOM qty</th>
              <th style={{ ...th, textAlign: "right" }}
                  title="Live MR demand (qty to order)">Requested</th>
              <th style={{ ...th, textAlign: "right" }}
                  title="Awarded local quotes + authorised import allocations">
                Ordered</th>
              <th style={{ ...th, textAlign: "right" }}
                  title="Issued from site stock to this project (incl. DPR consumption)">
                Issued</th>
              <th style={{ ...th, textAlign: "right" }}
                  title="BOM qty less ordered">Balance</th>
              <th style={th}>Remarks</th>
            </tr></thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.item_id}
                    style={r.over ? { background: "#fdecec" } : undefined}>
                  <td style={td}>{r.code}</td>
                  <td style={{ ...td, maxWidth: 320 }}>{r.description}</td>
                  <td style={td}>{r.unit}</td>
                  <td style={{ ...td, textAlign: "right", fontWeight: 600 }}>
                    {qf(r.bom_qty)}</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {qf(r.requested)}</td>
                  <td style={{ ...td, textAlign: "right" }}>{qf(r.ordered)}</td>
                  <td style={{ ...td, textAlign: "right" }}>{qf(r.issued)}</td>
                  <td style={{ ...td, textAlign: "right", fontWeight: 600,
                               color: r.over ? "#c0392b" : "#1a7f37" }}>
                    {qf(r.variance)}{r.over ? " ⚠" : ""}</td>
                  <td style={{ ...td, fontSize: 11.5,
                               color: "var(--muted)" }}>{r.remarks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.off_bom.length > 0 && (
        <>
          <h3 style={{ margin: "16px 0 4px", fontSize: 13.5,
                       color: "#c0392b" }}>
            Outside the BOM — procured or issued with no budget line</h3>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 12.5 }}>
              <thead><tr>
                <th style={th}>Code</th><th style={th}>Description</th>
                <th style={th}>Unit</th>
                <th style={{ ...th, textAlign: "right" }}>Requested</th>
                <th style={{ ...th, textAlign: "right" }}>Ordered</th>
                <th style={{ ...th, textAlign: "right" }}>Issued</th>
              </tr></thead>
              <tbody>
                {data.off_bom.map((r) => (
                  <tr key={r.item_id} style={{ background: "#fdecec" }}>
                    <td style={td}>{r.code}</td>
                    <td style={{ ...td, maxWidth: 320 }}>{r.description}</td>
                    <td style={td}>{r.unit}</td>
                    <td style={{ ...td, textAlign: "right" }}>
                      {qf(r.requested)}</td>
                    <td style={{ ...td, textAlign: "right" }}>
                      {qf(r.ordered)}</td>
                    <td style={{ ...td, textAlign: "right" }}>
                      {qf(r.issued)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

// Manual BOM editor — the full list, replace-on-save (like the BOQ grid).
function BomEditor({ projectId, items, current, onDone }) {
  const [rows, setRows] = useState(current.map((r) => ({
    item_id: r.item_id, qty: String(r.bom_qty ?? ""),
    remarks: r.remarks || "", source: r.source || "MANUAL" })));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const label = (it) => `${it.code} — ${it.description}`;
  const upd = (i, patch) => setRows((rs) =>
    rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const save = async () => {
    setBusy(true); setErr(null);
    try {
      await api(`/projects/${projectId}/bom/save`, { method: "POST",
        body: { rows: rows.filter((r) => r.item_id && Number(r.qty) > 0) } });
      onDone(true);
    } catch (e) { setErr(e.message); setBusy(false); }
  };

  return (
    <section style={card}>
      <Eyebrow>Edit BOM</Eyebrow>
      {err && <p style={{ color: "#c0392b", fontSize: 13 }}>{err}</p>}
      <table style={{ width: "100%", borderCollapse: "collapse",
                      fontSize: 12.5, marginTop: 8 }}>
        <thead><tr>
          <th style={th}>Item</th>
          <th style={{ ...th, width: 110, textAlign: "right" }}>BOM qty</th>
          <th style={{ ...th, width: 220 }}>Remarks</th>
          <th style={{ ...th, width: 40 }}></th>
        </tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={td}>
                <input list="bom-items" style={{ ...inputStyle, width: "100%" }}
                  value={(() => { const it = items.find(
                    (x) => x.id === r.item_id);
                    return r._text ?? (it ? label(it) : ""); })()}
                  onChange={(e) => {
                    const v = e.target.value;
                    const it = items.find((x) => label(x) === v);
                    upd(i, { _text: it ? undefined : v,
                             item_id: it ? it.id : null });
                  }} placeholder="Type to search the catalogue…" />
              </td>
              <td style={td}>
                <input type="number" style={{ ...inputStyle, width: 100,
                    textAlign: "right" }} value={r.qty}
                  onChange={(e) => upd(i, { qty: e.target.value })} /></td>
              <td style={td}>
                <input style={{ ...inputStyle, width: "100%" }}
                  value={r.remarks}
                  onChange={(e) => upd(i, { remarks: e.target.value })} /></td>
              <td style={td}>
                <button style={{ ...ghostButton, padding: "2px 8px" }}
                  onClick={() => setRows((rs) =>
                    rs.filter((_, j) => j !== i))}>✕</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <datalist id="bom-items">
        {items.map((it) => <option key={it.id} value={label(it)} />)}
      </datalist>
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button style={ghostButton} onClick={() => setRows(
          (rs) => [...rs, { item_id: null, qty: "", remarks: "",
                            source: "MANUAL" }])}>+ Add item</button>
        <span style={{ flex: 1 }} />
        <button style={ghostButton} onClick={() => onDone(false)}>Cancel</button>
        <button style={buttonStyle} disabled={busy} onClick={save}>
          {busy ? "Saving…" : "Save BOM"}</button>
      </div>
    </section>
  );
}

// Review the BOQ-seeded draft: aggregated build-up quantities, each row
// mapped to an Item-Master code (auto-matched where the description is
// identical). Unmapped rows are left out with a count shown.
function SeedReview({ projectId, items, onDone, onError }) {
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const label = (it) => `${it.code} — ${it.description}`;

  useEffect(() => {
    api(`/projects/${projectId}/bom/seed`)
      .then((d) => setRows(d.rows.map((r) => ({ ...r }))))
      .catch((e) => { onError(e.message); onDone(false); });
  }, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!rows) return <section style={card}>Reading the BOQ build-ups…</section>;
  const mapped = rows.filter((r) => r.item_id);

  const commit = async () => {
    setBusy(true); setErr(null);
    try {
      await api(`/projects/${projectId}/bom/save`, { method: "POST",
        body: { rows: mapped.map((r) => ({ item_id: r.item_id, qty: r.qty,
          source: "BOQ", remarks: r.remarks || "" })) } });
      onDone(true);
    } catch (e) { setErr(e.message); setBusy(false); }
  };

  return (
    <section style={card}>
      <div style={{ display: "flex", gap: 10, alignItems: "baseline",
                    flexWrap: "wrap" }}>
        <Eyebrow>Seed BOM from BOQ build-ups</Eyebrow>
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
          {rows.length} materials aggregated across the unit models ·{" "}
          {mapped.length} mapped to the catalogue
          {rows.length - mapped.length > 0 &&
            ` · ${rows.length - mapped.length} unmapped (left out — map them
             or add via Edit BOM later)`}
        </span>
      </div>
      {err && <p style={{ color: "#c0392b", fontSize: 13 }}>{err}</p>}
      <div style={{ overflowX: "auto", marginTop: 8,
                    maxHeight: 480, overflowY: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 12.5 }}>
          <thead><tr>
            <th style={th}>BOQ description</th>
            <th style={{ ...th, width: 70 }}>Unit</th>
            <th style={{ ...th, width: 100, textAlign: "right" }}>Total qty</th>
            <th style={{ ...th, width: 300 }}>Item-Master code</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} style={!r.item_id ? { background: "#fff8e6" }
                                            : undefined}>
                <td style={{ ...td, maxWidth: 340 }}>{r.description}</td>
                <td style={td}>{r.unit}</td>
                <td style={{ ...td, textAlign: "right" }}>{qf(r.qty)}</td>
                <td style={td}>
                  <input list="bom-items-seed"
                    style={{ ...inputStyle, width: "100%" }}
                    value={(() => { const it = items.find(
                      (x) => x.id === r.item_id);
                      return r._text ?? (it ? label(it) : ""); })()}
                    onChange={(e) => {
                      const v = e.target.value;
                      const it = items.find((x) => label(x) === v);
                      setRows((rs) => rs.map((x, j) => j === i
                        ? { ...x, _text: it ? undefined : v,
                            item_id: it ? it.id : null } : x));
                    }} placeholder="Type to map…" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <datalist id="bom-items-seed">
        {items.map((it) => <option key={it.id} value={label(it)} />)}
      </datalist>
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <span style={{ flex: 1 }} />
        <button style={ghostButton} onClick={() => onDone(false)}>Cancel</button>
        <button style={buttonStyle} disabled={busy || !mapped.length}
                onClick={commit}>
          {busy ? "Loading…" : `Commit ${mapped.length} rows to the BOM`}</button>
      </div>
    </section>
  );
}
