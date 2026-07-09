import { useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, StatusChip, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Petty cash — imprest float per site (§6B). The custodian records
// expenses against the float, the PM approves them (posting cost), and a
// replenishment PYR restores the float when Finance pays it.

const money = (v) => v == null ? "—"
  : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2 });

export default function PettyCashPage({ site, me, onOpenDoc, onClose }) {
  const [data, setData] = useState(null);     // { summary, entries }
  const [heads, setHeads] = useState([]);
  const [notConfigured, setNotConfigured] = useState(false);
  const [candidates, setCandidates] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState({});
  const [panel, setPanel] = useState(null);   // "add" | "reconcile" | "setup"

  // add-entry form
  const [f, setF] = useState({ amount: "", cost_head_id: "", payee: "",
                               purpose: "", has_receipt: true,
                               no_receipt_reason: "" });
  const [receipt, setReceipt] = useState(null);
  // reconcile + setup forms
  const [counted, setCounted] = useState("");
  const [explanation, setExplanation] = useState("");
  const [setupF, setSetupF] = useState({ imprest_amount: "", custodian_id: "",
                                         trigger_pct: 30, per_txn_cap: 1500 });

  const load = () => {
    setError(null);
    api(`/petty-cash/${site.id}`).then((fl) => {
      setCandidates(fl.custodian_candidates || []);
      if (!fl.configured) { setNotConfigured(true); setData(null); return; }
      setNotConfigured(false);
      api(`/petty-cash/${site.id}/entries`).then(setData)
        .catch((e) => setError(e.message));
    }).catch((e) => setError(e.message));
  };
  useEffect(() => {
    load();
    api("/cost-heads").then((h) => setHeads(h.filter((x) => !x.is_pool)))
      .catch(() => {});
  }, [site.id]);

  const s = data?.summary;
  const entries = data?.entries || [];
  const isCustodian = me.role === "ADMIN" || (s && me.id === s.custodian_id);
  const isPM = ["PM", "ADMIN"].includes(me.role);
  const isFinance = ["FINANCE", "ADMIN"].includes(me.role);
  const recorded = entries.filter((e) => e.status === "RECORDED");
  const pickedIds = Object.keys(picked).filter((k) => picked[k]).map(Number);

  const run = async (fn) => {
    setBusy(true); setError(null);
    try { await fn(); } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const addEntry = () => run(async () => {
    const fd = new FormData();
    fd.append("amount", f.amount);
    fd.append("cost_head_id", f.cost_head_id);
    fd.append("payee", f.payee);
    fd.append("purpose", f.purpose);
    fd.append("has_receipt", receipt ? "true" : String(f.has_receipt));
    fd.append("no_receipt_reason", f.no_receipt_reason);
    if (receipt) fd.append("receipt", receipt);
    await apiUpload(`/petty-cash/${site.id}/entries`, fd);
    setPanel(null); setF({ amount: "", cost_head_id: "", payee: "",
                           purpose: "", has_receipt: true,
                           no_receipt_reason: "" });
    setReceipt(null); load();
  });

  const approve = () => run(async () => {
    await api(`/petty-cash/${site.id}/entries/approve`,
              { method: "POST", body: { entry_ids: pickedIds } });
    setPicked({}); load();
  });

  const replenish = () => run(async () => {
    const r = await api(`/petty-cash/${site.id}/replenish`,
                        { method: "POST", body: {} });
    load();
    if (r.pyr_ref && onOpenDoc) onOpenDoc(r.pyr_ref);
  });

  const reconcile = () => run(async () => {
    await api(`/petty-cash/${site.id}/reconcile`,
              { method: "POST", body: { counted_cash: counted,
                                        explanation } });
    setPanel(null); setCounted(""); setExplanation(""); load();
  });

  const saveSetup = () => run(async () => {
    await api(`/petty-cash/${site.id}`,
              { method: "PUT", body: setupF });
    setPanel(null); load();
  });

  const header = (
    <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                  flexWrap: "wrap" }}>
      <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 17 }}>
        Petty Cash — {site.code}</h2>
      <button onClick={onClose}
              style={{ ...ghostButton, marginLeft: "auto" }}>← Back</button>
    </div>
  );

  if (notConfigured) {
    return (
      <section style={card}>
        {header}
        {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
        <p style={{ color: "var(--muted)", fontSize: 14, marginTop: 12 }}>
          No petty cash float is set up for this site yet.
        </p>
        {isFinance ? (
          <SetupForm setupF={setupF} setSetupF={setSetupF}
                     onSave={saveSetup} busy={busy} candidates={candidates} />
        ) : (
          <p style={{ fontSize: 13 }}>Finance sets up the imprest float and
            names the custodian.</p>
        )}
      </section>
    );
  }

  if (!s) return <section style={card}>{header}<p>Loading…</p></section>;

  return (
    <section style={card}>
      {header}
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}

      {/* Float summary */}
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap",
                    margin: "14px 0", alignItems: "flex-end" }}>
        <div>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>Cash in hand</div>
          <div style={{ fontSize: 26, fontFamily: "var(--font-mono)",
                        color: s.needs_replenish ? "var(--red-fg)"
                          : "var(--navy)" }}>
            MVR {money(s.cash_in_hand)}</div>
        </div>
        <div style={{ fontSize: 13, color: "var(--muted)" }}>
          Imprest MVR {money(s.imprest)} · trigger {s.trigger_pct}%
          (MVR {money(s.trigger_amount)})<br />
          Custodian {s.custodian} · cap MVR {money(s.per_txn_cap)} / txn<br />
          Cycle {s.cycle_no} · <StatusChip status={s.cycle_status} />
        </div>
        {s.needs_replenish && (
          <span style={{ background: "var(--red-bg)", color: "var(--red-fg)",
                         padding: "4px 10px", borderRadius: 8, fontSize: 12 }}>
            Below trigger — replenish
          </span>
        )}
      </div>

      {/* Actions */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                    marginBottom: 12 }}>
        {isCustodian && s.cycle_status === "OPEN" && (
          <Btn variant="primary" style={{ padding: "5px 14px", fontSize: 13 }}
               onClick={() => setPanel(panel === "add" ? null : "add")}>
            + Expense</Btn>
        )}
        {(isCustodian || isPM) && (
          <Btn variant="secondary" style={{ padding: "5px 14px", fontSize: 13 }}
               onClick={() => setPanel(panel === "reconcile" ? null
                                       : "reconcile")}>Reconcile</Btn>
        )}
        {(isCustodian || isPM) && s.approved_unreimbursed > 0
          && s.cycle_status === "OPEN" && (
          <Btn variant="navy" style={{ padding: "5px 14px", fontSize: 13 }}
               disabled={busy} onClick={replenish}>
            Replenish (claim MVR {money(s.approved_unreimbursed)})</Btn>
        )}
        {isFinance && (
          <button onClick={() => setPanel(panel === "setup" ? null : "setup")}
                  style={ghostButton}>Edit float</button>
        )}
      </div>

      {panel === "add" && (
        <div style={{ ...formBox }}>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <label style={lbl}>Amount (MVR)
              <input type="number" value={f.amount} style={inputStyle}
                     onChange={(e) => setF({ ...f, amount: e.target.value })} />
            </label>
            <label style={lbl}>Cost head
              <select value={f.cost_head_id} style={inputStyle}
                      onChange={(e) => setF({ ...f,
                                              cost_head_id: e.target.value })}>
                <option value="">— select —</option>
                {heads.map((h) => <option key={h.id} value={h.id}>{h.name}
                </option>)}
              </select>
            </label>
            <label style={lbl}>Payee / purpose
              <input value={f.payee} style={inputStyle}
                     onChange={(e) => setF({ ...f, payee: e.target.value })} />
            </label>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                        marginTop: 8, alignItems: "center" }}>
            <label style={{ fontSize: 13 }}>Receipt
              <input type="file" style={{ display: "block" }}
                     onChange={(e) => setReceipt(e.target.files[0])} /></label>
            {!receipt && (
              <label style={lbl}>…or reason for no receipt
                <input value={f.no_receipt_reason} style={inputStyle}
                       onChange={(e) => setF({ ...f,
                         no_receipt_reason: e.target.value,
                         has_receipt: false })} /></label>
            )}
            <Btn variant="primary" disabled={busy} onClick={addEntry}
                 style={{ alignSelf: "flex-end" }}>Save expense</Btn>
          </div>
        </div>
      )}

      {panel === "reconcile" && (
        <div style={formBox}>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                        alignItems: "flex-end" }}>
            <label style={lbl}>Counted cash (MVR)
              <input type="number" value={counted} style={inputStyle}
                     onChange={(e) => setCounted(e.target.value)} /></label>
            <span style={{ fontSize: 13, color: "var(--muted)" }}>
              System says MVR {money(s.cash_in_hand)}
              {counted !== "" && ` · variance MVR ${money(
                Number(counted) - Number(s.cash_in_hand))}`}</span>
          </div>
          <label style={{ ...lbl, display: "block", marginTop: 8 }}>
            Explanation (required if variance)
            <input value={explanation} style={{ ...inputStyle, width: "100%" }}
                   onChange={(e) => setExplanation(e.target.value)} /></label>
          <Btn variant="primary" disabled={busy} onClick={reconcile}
               style={{ marginTop: 8 }}>Record count</Btn>
        </div>
      )}

      {panel === "setup" && (
        <SetupForm setupF={{ ...setupF, imprest_amount: s.imprest,
                             custodian_id: s.custodian_id,
                             trigger_pct: s.trigger_pct,
                             per_txn_cap: s.per_txn_cap }}
                   setSetupF={setSetupF} onSave={saveSetup} busy={busy}
                   candidates={candidates} />
      )}

      {/* PM approval bar */}
      {isPM && recorded.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 12,
                      margin: "6px 0" }}>
          <span style={{ fontSize: 13, color: "var(--muted)" }}>
            {pickedIds.length} of {recorded.length} recorded entries selected
          </span>
          {pickedIds.length > 0 && (
            <Btn variant="primary" disabled={busy} onClick={approve}
                 style={{ padding: "4px 12px", fontSize: 13 }}>
              Approve selected</Btn>
          )}
        </div>
      )}

      {/* Entries table */}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            {isPM && <th style={{ ...th, width: 28 }}></th>}
            <th style={th}>Date</th>
            <th style={{ ...th, textAlign: "right" }}>Amount</th>
            <th style={th}>Cost head</th><th style={th}>Payee / purpose</th>
            <th style={th}>Receipt</th><th style={th}>Status</th>
          </tr></thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                {isPM && (
                  <td style={td}>
                    {e.status === "RECORDED" && (
                      <input type="checkbox" checked={!!picked[e.id]}
                             onChange={(ev) => setPicked(
                               { ...picked, [e.id]: ev.target.checked })} />
                    )}
                  </td>
                )}
                <td style={td}>{e.date}</td>
                <td style={{ ...td, textAlign: "right",
                             fontFamily: "var(--font-mono)" }}>
                  {money(e.amount)}</td>
                <td style={td}>{e.cost_head}</td>
                <td style={td}>{e.payee}
                  {e.purpose ? <span style={{ color: "var(--muted)" }}>
                    {" "}· {e.purpose}</span> : ""}</td>
                <td style={{ ...td, fontSize: 12 }}>
                  {e.receipt_url
                    ? <a href={e.receipt_url} target="_blank"
                         rel="noreferrer">🧾</a>
                    : <span style={{ color: "var(--red-fg)" }}
                            title={e.no_receipt_reason}>none</span>}
                </td>
                <td style={td}><StatusChip status={e.status} /></td>
              </tr>
            ))}
            {entries.length === 0 && (
              <tr><td style={td} colSpan={isPM ? 7 : 6}>
                No expenses this cycle yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {s.no_receipt_total > 0 && (
        <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
          No-receipt spend this cycle: MVR {money(s.no_receipt_total)}</p>
      )}
    </section>
  );
}

const formBox = { border: "1px solid var(--line)", borderRadius: 8,
                  padding: 12, marginBottom: 12, background: "var(--sand)" };
const lbl = { fontSize: 13, display: "flex", flexDirection: "column" };

function SetupForm({ setupF, setSetupF, onSave, busy, candidates = [] }) {
  const set = (k, v) => setSetupF({ ...setupF, [k]: v });
  return (
    <div style={formBox}>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <label style={lbl}>Imprest amount (MVR)
          <input type="number" value={setupF.imprest_amount} style={inputStyle}
                 onChange={(e) => set("imprest_amount", e.target.value)} />
        </label>
        <label style={lbl}>Custodian
          <select value={setupF.custodian_id} style={inputStyle}
                  onChange={(e) => set("custodian_id", e.target.value)}>
            <option value="">— select —</option>
            {candidates.map((u) => <option key={u.id} value={u.id}>
              {u.full_name}{u.role ? ` (${u.role.replace("_", " ")
                .toLowerCase()})` : ""}</option>)}
          </select>
        </label>
        <label style={lbl}>Replenish trigger (%)
          <input type="number" value={setupF.trigger_pct} style={inputStyle}
                 onChange={(e) => set("trigger_pct", e.target.value)} />
        </label>
        <label style={lbl}>Per-txn cap (MVR)
          <input type="number" value={setupF.per_txn_cap} style={inputStyle}
                 onChange={(e) => set("per_txn_cap", e.target.value)} />
        </label>
      </div>
      <Btn variant="primary" disabled={busy} onClick={onSave}
           style={{ marginTop: 8 }}>Save float</Btn>
    </div>
  );
}
