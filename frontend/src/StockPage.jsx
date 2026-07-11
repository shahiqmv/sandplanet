import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

// Site inventory (Phase 1A). A simple on-hand quantity ledger: GRN receipts
// add stock automatically, admin staff issue stock to projects, and a
// physical count reconciles the balance. Click any balance to see its history.

const qty = (v) => v == null ? "—"
  : Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 });

const CAN_ISSUE = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "ADMIN"];

export default function StockPage({ site, me, onClose }) {
  const [data, setData] = useState(null);       // { balances, can_issue }
  const [projects, setProjects] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [panel, setPanel] = useState(null);     // "issue" | null
  const [history, setHistory] = useState(null); // { item, on_hand, history }
  const [recon, setRecon] = useState(null);     // item row being reconciled

  const load = () => {
    setError(null);
    api(`/stock/${site.id}`).then(setData).catch((e) => setError(e.message));
  };
  useEffect(() => {
    load();
    api(`/sites/${site.id}/projects`).then(setProjects).catch(() => {});
  }, [site.id]);

  const run = async (fn) => {
    setBusy(true); setError(null);
    try { await fn(); } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const balances = data?.balances || [];
  const canIssue = data?.can_issue && CAN_ISSUE.includes(me.role);

  const openHistory = (row) => run(async () => {
    const h = await api(`/stock/${site.id}/${row.item_id}/history`);
    setHistory(h);
  });

  const header = (
    <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                  flexWrap: "wrap" }}>
      <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 17 }}>
        Site Stock — {site.code}</h2>
      {canIssue && (
        <>
          <button onClick={() => setPanel(panel === "issue" ? null : "issue")}
                  style={buttonStyle}>📦 Issue Stock</button>
        </>
      )}
      <button onClick={onClose}
              style={{ ...ghostButton, marginLeft: "auto" }}>← Back</button>
    </div>
  );

  return (
    <section style={card}>
      {header}
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}

      {panel === "issue" && canIssue && (
        <IssueForm site={site} projects={projects} balances={balances}
                   busy={busy} onDone={() => { setPanel(null); load(); }}
                   onError={setError} />
      )}

      <p style={{ color: "var(--muted)", fontSize: 13, margin: "14px 0 6px" }}>
        On-hand balances. Click a balance to see its movement history.
      </p>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead><tr>
          <th style={th}>Code</th><th style={th}>Material</th>
          <th style={th}>Category</th>
          <th style={{ ...th, textAlign: "right" }}>On hand</th>
          <th style={th}>Unit</th>
          {canIssue && <th style={th}></th>}
        </tr></thead>
        <tbody>
          {balances.map((r) => (
            <tr key={r.item_id}>
              <td style={td}>{r.code}</td>
              <td style={td}>{r.description}</td>
              <td style={td}>{r.category || "—"}</td>
              <td style={{ ...td, textAlign: "right", fontWeight: 600,
                           color: Number(r.on_hand) < 0 ? "var(--red-fg)"
                                                        : "var(--navy)" }}>
                <button onClick={() => openHistory(r)}
                        style={{ background: "none", border: "none",
                                 color: "inherit", font: "inherit",
                                 cursor: "pointer", textDecoration: "underline",
                                 padding: 0 }}>
                  {qty(r.on_hand)}
                </button>
              </td>
              <td style={td}>{r.unit}</td>
              {canIssue && (
                <td style={td}>
                  <button onClick={() => setRecon(r)}
                          style={{ ...ghostButton, padding: "2px 8px",
                                   fontSize: 12 }}>Reconcile</button>
                </td>
              )}
            </tr>
          ))}
          {balances.length === 0 && (
            <tr><td colSpan={canIssue ? 6 : 5} style={{ ...td,
                    color: "var(--muted)", textAlign: "center" }}>
              No stock recorded yet. Verified GRNs add stock automatically.
            </td></tr>
          )}
        </tbody>
      </table>

      {history && (
        <HistoryModal data={history} onClose={() => setHistory(null)} />
      )}
      {recon && (
        <ReconcileModal site={site} row={recon} busy={busy}
                        onClose={() => setRecon(null)}
                        onDone={() => { setRecon(null); load(); }}
                        onError={setError} />
      )}
    </section>
  );
}

function IssueForm({ site, projects, balances, onDone, onError }) {
  const [projectId, setProjectId] = useState("");
  const [lines, setLines] = useState([{ item_id: "", qty: "" }]);
  const [busy, setBusy] = useState(false);

  const setLine = (i, patch) =>
    setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const addLine = () => setLines((ls) => [...ls, { item_id: "", qty: "" }]);
  const rmLine = (i) => setLines((ls) => ls.filter((_, j) => j !== i));

  const onHand = (id) =>
    balances.find((b) => String(b.item_id) === String(id))?.on_hand;

  const submit = async () => {
    const clean = lines
      .filter((l) => l.item_id && Number(l.qty) > 0)
      .map((l) => ({ item_id: Number(l.item_id), qty: Number(l.qty) }));
    if (!clean.length) { onError("Add at least one item and quantity."); return; }
    setBusy(true); onError(null);
    try {
      await api(`/stock/${site.id}/issue`,
                { method: "POST", body: { project_id: projectId || null,
                                          lines: clean } });
      onDone();
    } catch (e) { onError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div style={{ background: "var(--sp-tint, #f5f8fb)", borderRadius: 8,
                  padding: 14, margin: "10px 0" }}>
      <h3 style={{ margin: "0 0 10px", fontSize: 14 }}>Issue stock to a project</h3>
      <label style={{ fontSize: 13, display: "block", marginBottom: 10 }}>
        Project&nbsp;
        <select value={projectId} onChange={(e) => setProjectId(e.target.value)}
                style={{ ...inputStyle, maxWidth: 320 }}>
          <option value="">— General / site-wide —</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.code} — {p.title}</option>
          ))}
        </select>
      </label>
      {lines.map((l, i) => (
        <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8,
                              alignItems: "center", flexWrap: "wrap" }}>
          <select value={l.item_id}
                  onChange={(e) => setLine(i, { item_id: e.target.value })}
                  style={{ ...inputStyle, flex: "1 1 260px" }}>
            <option value="">— Select item —</option>
            {balances.map((b) => (
              <option key={b.item_id} value={b.item_id}>
                {b.code} — {b.description} ({qty(b.on_hand)} {b.unit})
              </option>
            ))}
          </select>
          <input type="number" min="0" step="any" placeholder="Qty"
                 value={l.qty}
                 onChange={(e) => setLine(i, { qty: e.target.value })}
                 style={{ ...inputStyle, width: 100 }} />
          {l.item_id && Number(l.qty) > Number(onHand(l.item_id) ?? 0) && (
            <span style={{ color: "var(--red-fg)", fontSize: 12 }}>
              over stock ({qty(onHand(l.item_id))})</span>
          )}
          {lines.length > 1 && (
            <button onClick={() => rmLine(i)}
                    style={{ ...ghostButton, padding: "2px 8px" }}>✕</button>
          )}
        </div>
      ))}
      <div style={{ display: "flex", gap: 10, marginTop: 6 }}>
        <button onClick={addLine} style={ghostButton}>+ Add line</button>
        <Btn onClick={submit} disabled={busy}>
          {busy ? "Issuing…" : "Issue"}</Btn>
      </div>
    </div>
  );
}

function ReconcileModal({ site, row, onClose, onDone, onError }) {
  const [counted, setCounted] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!reason.trim()) { onError("A reason is required."); return; }
    setBusy(true); onError(null);
    try {
      await api(`/stock/${site.id}/reconcile`,
                { method: "POST", body: { item_id: row.item_id,
                                          counted_qty: counted, reason } });
      onDone();
    } catch (e) { onError(e.message); }
    finally { setBusy(false); }
  };

  const variance = counted === "" ? null
    : Number(counted) - Number(row.on_hand);

  return (
    <Modal onClose={onClose} title={`Reconcile — ${row.code}`}>
      <p style={{ fontSize: 13, color: "var(--muted)" }}>
        {row.description}<br />
        System on-hand: <strong>{qty(row.on_hand)} {row.unit}</strong>
      </p>
      <label style={{ fontSize: 13, display: "block", margin: "10px 0" }}>
        Physically counted quantity<br />
        <input type="number" step="any" value={counted}
               onChange={(e) => setCounted(e.target.value)}
               style={{ ...inputStyle, width: 160 }} />
        {variance != null && variance !== 0 && (
          <span style={{ marginLeft: 10, fontSize: 12,
                         color: variance < 0 ? "var(--red-fg)" : "#1a7f37" }}>
            variance {variance > 0 ? "+" : ""}{qty(variance)}
          </span>
        )}
      </label>
      <label style={{ fontSize: 13, display: "block", marginBottom: 10 }}>
        Reason (required)<br />
        <textarea value={reason} onChange={(e) => setReason(e.target.value)}
                  rows={2} style={{ ...inputStyle, width: "100%" }}
                  placeholder="e.g. 5 bags damaged, count correction" />
      </label>
      <Btn onClick={submit} disabled={busy}>
        {busy ? "Saving…" : "Book adjustment"}</Btn>
    </Modal>
  );
}

function HistoryModal({ data, onClose }) {
  const KIND = { RECEIPT: "Receipt", ISSUE: "Issue", ADJUST: "Adjustment" };
  return (
    <Modal onClose={onClose}
           title={`${data.item.code} — history`}>
      <p style={{ fontSize: 13, color: "var(--muted)" }}>
        {data.item.description} · on-hand{" "}
        <strong>{qty(data.on_hand)} {data.item.unit}</strong>
      </p>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead><tr>
          <th style={th}>Date</th><th style={th}>Type</th>
          <th style={{ ...th, textAlign: "right" }}>Qty</th>
          <th style={{ ...th, textAlign: "right" }}>Balance</th>
          <th style={th}>Ref / Project</th><th style={th}>By</th>
        </tr></thead>
        <tbody>
          {data.history.map((h) => (
            <tr key={h.id}>
              <td style={td}>{h.date}</td>
              <td style={td}>{KIND[h.kind] || h.kind}</td>
              <td style={{ ...td, textAlign: "right",
                           color: Number(h.qty) < 0 ? "var(--red-fg)"
                                                     : "#1a7f37" }}>
                {Number(h.qty) > 0 ? "+" : ""}{qty(h.qty)}</td>
              <td style={{ ...td, textAlign: "right" }}>{qty(h.running)}</td>
              <td style={td}>
                {h.document || h.project || "—"}
                {h.reason && (
                  <div style={{ color: "var(--muted)", fontSize: 11 }}>
                    {h.reason}</div>
                )}
              </td>
              <td style={td}>{h.by || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Modal>
  );
}

function Modal({ title, children, onClose }) {
  return (
    <div onClick={onClose}
         style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.35)",
                  display: "flex", alignItems: "center",
                  justifyContent: "center", zIndex: 50, padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ ...card, maxWidth: 640, width: "100%", maxHeight: "85vh",
                    overflow: "auto" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 16 }}>
            {title}</h2>
          <button onClick={onClose}
                  style={{ ...ghostButton, marginLeft: "auto" }}>Close</button>
        </div>
        <div style={{ marginTop: 12 }}>{children}</div>
      </div>
    </div>
  );
}
