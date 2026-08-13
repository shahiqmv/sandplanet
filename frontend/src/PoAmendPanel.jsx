import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, card, inputStyle, td, th } from "./ui.jsx";

/* Amending a purchase order the supplier already holds (owner 2026-08-13).
 *
 * Not to be confused with the MR "Amend (new revision)" button in LineDoc:
 * that reopens a site's own request for editing with nobody's approval. This
 * one proposes a replacement revision that the supplier does NOT see until
 * the Director agrees — an issued order is a commitment to an outside party.
 */
const money = (v) => v == null || v === "" ? "—"
  : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2,
                                        maximumFractionDigits: 2 });

const PROPOSE = ["HO_PURCHASING", "ADMIN"];

export default function PoAmendPanel({ doc, me, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [diff, setDiff] = useState(null);
  const [error, setError] = useState(null);

  const pending = doc.status === "AMENDMENT_PENDING";

  useEffect(() => {
    if (!pending) { setDiff(null); return; }
    api(`/documents/${doc.ref}/amendment`)
      .then(setDiff)
      .catch((e) => setError(e.message));
  }, [doc.ref, doc.status]); // eslint-disable-line

  if (doc.doc_type !== "PO") return null;

  if (pending) {
    return <PendingAmendment doc={doc} diff={diff} error={error}
                             onChanged={onChanged} />;
  }
  if (doc.status !== "ISSUED" || !PROPOSE.includes(me.role)) return null;

  return editing
    ? <AmendForm doc={doc} onCancel={() => setEditing(false)}
                 onDone={() => { setEditing(false); onChanged(); }} />
    : (
      <div style={{ ...card, marginTop: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div>
            <strong>Need to change this order?</strong>
            <p style={{ margin: "4px 0 0", fontSize: 12.5, color: "#667" }}>
              Short stock, an unavailable item, a wrong quantity. The supplier
              keeps the order they have until the Director approves the change.
            </p>
          </div>
          <div style={{ flex: 1 }} />
          <Btn variant="secondary" onClick={() => setEditing(true)}>
            Amend order
          </Btn>
        </div>
      </div>
    );
}

/* ------------------------------------------------------------ the proposal */
function AmendForm({ doc, onCancel, onDone }) {
  const [rows, setRows] = useState(() =>
    (doc.lines || []).map((l) => ({
      id: l.id,
      description: l.description || l.item_name || "",
      unit: l.unit || "",
      qty_required: l.qty_required ?? "",
      rate: l.rate ?? "",
      remarks: l.remarks || "",
    })));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const set = (i, k) => (e) => {
    const next = [...rows];
    next[i] = { ...next[i], [k]: e.target.value };
    setRows(next);
  };
  const drop = (i) => setRows(rows.filter((_, x) => x !== i));
  const addRow = () => setRows([...rows, { description: "", unit: "",
                                           qty_required: "", rate: "",
                                           remarks: "" }]);

  const total = rows.reduce(
    (s, r) => s + (Number(r.qty_required) || 0) * (Number(r.rate) || 0), 0);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api(`/documents/${doc.ref}/amend`, {
        method: "POST",
        body: {
          reason,
          lines: rows.map((r) => ({
            ...r,
            amount: (Number(r.qty_required) || 0) * (Number(r.rate) || 0),
          })),
        },
      });
      onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ ...card, marginTop: 14 }}>
      <h3 style={{ marginTop: 0 }}>Amend {doc.ref}</h3>
      <p style={{ fontSize: 12.5, color: "#667", marginTop: 0 }}>
        Change a quantity or rate, or remove a line the supplier can’t fill.
        The supplier is not changed — buying elsewhere is a separate order.
      </p>
      {error && <p style={{ color: "#b00" }}>{error}</p>}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={th}>Description</th><th style={th}>Unit</th>
            <th style={{ ...th, textAlign: "right" }}>Qty</th>
            <th style={{ ...th, textAlign: "right" }}>Rate</th>
            <th style={{ ...th, textAlign: "right" }}>Amount</th>
            <th style={th}></th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td style={td}>
                  <input style={{ ...inputStyle, width: "100%" }}
                         value={r.description} onChange={set(i, "description")} />
                </td>
                <td style={td}>
                  <input style={{ ...inputStyle, width: 70 }}
                         value={r.unit} onChange={set(i, "unit")} />
                </td>
                <td style={{ ...td, textAlign: "right" }}>
                  <input style={{ ...inputStyle, width: 90, textAlign: "right" }}
                         value={r.qty_required} onChange={set(i, "qty_required")} />
                </td>
                <td style={{ ...td, textAlign: "right" }}>
                  <input style={{ ...inputStyle, width: 100, textAlign: "right" }}
                         value={r.rate} onChange={set(i, "rate")} />
                </td>
                <td style={{ ...td, textAlign: "right",
                             fontFamily: "var(--font-mono)" }}>
                  {money((Number(r.qty_required) || 0) * (Number(r.rate) || 0))}
                </td>
                <td style={{ ...td, textAlign: "right" }}>
                  <a href="#" style={{ fontSize: 12, color: "#b00" }}
                     onClick={(e) => { e.preventDefault(); drop(i); }}>remove</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                    marginTop: 8 }}>
        <Btn variant="secondary" onClick={addRow}>+ Add line</Btn>
        <div style={{ flex: 1 }} />
        <strong style={{ fontFamily: "var(--font-mono)" }}>
          Revised total {money(total)}</strong>
      </div>
      <div style={{ marginTop: 12 }}>
        <label style={{ fontSize: 12.5, color: "#556" }}>
          Why is this order changing? (the Director sees this)
        </label>
        <input style={{ ...inputStyle, width: "100%", marginTop: 4 }}
               value={reason} onChange={(e) => setReason(e.target.value)}
               placeholder="e.g. Supplier can only deliver 150 of 200 bags" />
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Btn onClick={submit} disabled={busy || !reason.trim() || !rows.length}>
          {busy ? "Sending…" : "Send to the Director"}
        </Btn>
        <Btn variant="secondary" onClick={onCancel}>Cancel</Btn>
      </div>
    </div>
  );
}

/* --------------------------------------------------------- the decision */
const TONE = {
  changed: { background: "#fff8e1" },
  added: { background: "#e8f5e9" },
  dropped: { background: "#ffebee", textDecoration: "line-through",
             color: "#8a1f1f" },
  same: {},
};

function PendingAmendment({ doc, diff, error, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function decide(approve) {
    const note = approve ? "" : (window.prompt("Why is it rejected?") || "");
    if (!approve && !note) return;
    setBusy(true);
    setErr(null);
    try {
      await api(`/documents/${doc.ref}/amend-decision`, {
        method: "POST", body: { approve, note },
      });
      onChanged();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <div style={{ ...card, marginTop: 14 }}>{error}</div>;
  if (!diff) return <div style={{ ...card, marginTop: 14 }}>Loading…</div>;

  const rows = [...diff.after, ...diff.dropped];
  const up = Number(diff.delta) > 0;

  return (
    <div style={{ ...card, marginTop: 14, borderLeft: "4px solid #e0a800" }}>
      <h3 style={{ marginTop: 0 }}>
        Amendment {diff.revision} awaiting approval
      </h3>
      <p style={{ margin: "0 0 4px", fontSize: 13 }}>
        <strong>{diff.reason}</strong>
      </p>
      <p style={{ margin: "0 0 12px", fontSize: 12.5, color: "#667" }}>
        Proposed by {diff.proposed_by || "Purchasing"} · replaces{" "}
        {diff.from_revision}. The supplier still holds {diff.from_revision}
        {" "}until this is approved.
      </p>
      {err && <p style={{ color: "#b00" }}>{err}</p>}

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={th}>Description</th><th style={th}>Unit</th>
            <th style={{ ...th, textAlign: "right" }}>Was</th>
            <th style={{ ...th, textAlign: "right" }}>Now</th>
            <th style={{ ...th, textAlign: "right" }}>Rate</th>
            <th style={{ ...th, textAlign: "right" }}>Amount</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} style={TONE[r.change] || {}}>
                <td style={td}>
                  {r.description}
                  {r.change === "added" && (
                    <span style={{ fontSize: 11, color: "#2e7d32" }}> · new</span>)}
                  {r.change === "dropped" && (
                    <span style={{ fontSize: 11 }}> · removed</span>)}
                </td>
                <td style={td}>{r.unit}</td>
                <td style={{ ...td, textAlign: "right",
                             fontFamily: "var(--font-mono)", color: "#8a8f98" }}>
                  {r.change === "changed" ? money(r.was_qty)
                   : r.change === "dropped" ? money(r.qty) : ""}
                </td>
                <td style={{ ...td, textAlign: "right",
                             fontFamily: "var(--font-mono)" }}>
                  {r.change === "dropped" ? "—" : money(r.qty)}
                </td>
                <td style={{ ...td, textAlign: "right",
                             fontFamily: "var(--font-mono)" }}>
                  {money(r.rate)}
                  {r.change === "changed" && r.was_rate !== r.rate && (
                    <span style={{ color: "#8a8f98" }}> (was {money(r.was_rate)})</span>
                  )}
                </td>
                <td style={{ ...td, textAlign: "right",
                             fontFamily: "var(--font-mono)" }}>
                  {r.change === "dropped" ? "—" : money(r.amount)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 14,
                    marginTop: 12, flexWrap: "wrap" }}>
        <span style={{ fontSize: 13 }}>
          Order value {money(diff.was_total)} → <strong>{money(diff.now_total)}</strong>
          {" "}
          <span style={{ color: up ? "#b00" : "#2e7d32" }}>
            ({up ? "+" : ""}{money(diff.delta)})
          </span>
        </span>
        <div style={{ flex: 1 }} />
        {diff.can_decide && (
          <>
            <Btn onClick={() => decide(true)} disabled={busy}>
              Approve the amendment</Btn>
            <Btn variant="secondary" onClick={() => decide(false)} disabled={busy}>
              Reject</Btn>
          </>
        )}
      </div>
    </div>
  );
}
