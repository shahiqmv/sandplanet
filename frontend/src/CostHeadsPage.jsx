import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

/* The cost head master (owner 2026-09-07).
 *
 * Cost heads used to exist only because migrations and feature code created
 * them, with no screen at all. Two things make this page safe to give people:
 * every head carries a fixed internal code, so renaming one cannot break the
 * posting path that reaches for it; and a head that has carried money can be
 * switched off but never deleted.
 */
const MANAGE = ["ADMIN", "FINANCE"];
const money = (n) => (n == null ? "—" : Number(n).toLocaleString("en-US",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

export default function CostHeadsPage({ me }) {
  const [heads, setHeads] = useState(null);
  const [overheads, setOverheads] = useState(null);
  const [editing, setEditing] = useState(null);   // head id
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);
  const can = MANAGE.includes(me.role);

  const load = () => {
    api("/cost-head-master").then(setHeads).catch((e) => setError(e.message));
    api("/cost-heads/overheads").then(setOverheads).catch(() => {});
  };
  useEffect(load, []);

  async function patch(h, body) {
    setError(null);
    try {
      await api(`/cost-head-master/${h.id}`, { method: "PATCH", body });
      load();
    } catch (e) { setError(e.message); }
  }
  async function remove(h) {
    setError(null);
    try {
      await api(`/cost-head-master/${h.id}`, { method: "DELETE" });
      load();
    } catch (e) { setError(e.message); }
  }

  const project = (heads || []).filter((h) => !h.overhead && !h.is_pool);
  const company = (heads || []).filter((h) => h.overhead);
  const pools = (heads || []).filter((h) => h.is_pool && !h.overhead);

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap", marginBottom: 4 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Cost heads</h2>
        {can && !adding && (
          <button style={{ ...buttonStyle, marginLeft: "auto" }}
                  onClick={() => setAdding(true)}>➕ Add a cost head</button>)}
      </div>
      <p style={{ color: "var(--muted)", fontSize: 12.5, margin: "0 0 12px" }}>
        Every cost the company books lands on one of these. A head marked
        <strong> company overhead</strong> is a running cost no project causes
        — it is kept out of every project cost report and totalled below
        instead.
      </p>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {adding && can && (
        <AddForm onDone={(ok) => { setAdding(false); if (ok) load(); }} />)}

      <Group title="Project cost" hint="Charged to the site or project that
        caused them." rows={project} {...{ can, editing, setEditing, patch,
        remove }} />
      <Group title="Company overhead"
        hint="Kept out of every project cost report — the company's own
        running costs." rows={company} {...{ can, editing, setEditing, patch,
        remove }} />
      <Group title="Head office pools"
        hint="Internal holding buckets, never charged to a project."
        rows={pools} {...{ can, editing, setEditing, patch, remove }} />

      {overheads && overheads.by_cost_head.length > 0 && (
        <>
          <h3 style={{ color: "var(--sp-navy)", fontSize: 15,
                       margin: "22px 0 4px" }}>
            What the company spent on itself</h3>
          <p style={{ color: "var(--muted)", fontSize: 12,
                      margin: "0 0 8px" }}>
            USD at {overheads.usd_rate}. These figures appear in no project
            report — this is where they are counted.
          </p>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
            <thead><tr>
              <th style={th}>Cost head</th>
              <th style={{ ...th, textAlign: "right" }}>Committed</th>
              <th style={{ ...th, textAlign: "right" }}>Incurred</th>
              <th style={{ ...th, textAlign: "right" }}>Paid</th>
            </tr></thead>
            <tbody>
              {overheads.by_cost_head.map((r) => (
                <tr key={r.code}>
                  <td style={td}>{r.cost_head}</td>
                  <td style={{ ...td, textAlign: "right",
                               fontVariantNumeric: "tabular-nums" }}>
                    {money(r.committed)}</td>
                  <td style={{ ...td, textAlign: "right",
                               fontVariantNumeric: "tabular-nums" }}>
                    {money(r.incurred)}</td>
                  <td style={{ ...td, textAlign: "right",
                               fontVariantNumeric: "tabular-nums" }}>
                    {money(r.paid)}</td>
                </tr>))}
              <tr>
                <td style={{ ...td, fontWeight: 700 }}>Total</td>
                {["committed", "incurred", "paid"].map((k) => (
                  <td key={k} style={{ ...td, textAlign: "right",
                                       fontWeight: 700,
                                       fontVariantNumeric: "tabular-nums" }}>
                    {money(overheads.totals[k])}</td>))}
              </tr>
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

function Group({ title, hint, rows, can, editing, setEditing, patch, remove }) {
  return (
    <>
      <h3 style={{ color: "var(--sp-navy)", fontSize: 15,
                   margin: "18px 0 2px" }}>{title}</h3>
      <p style={{ color: "var(--muted)", fontSize: 12, margin: "0 0 6px" }}>
        {hint}</p>
      <table style={{ width: "100%", borderCollapse: "collapse",
                      fontSize: 13, marginBottom: 6 }}>
        <thead><tr>
          <th style={th}>Cost head</th>
          <th style={{ ...th, width: 70, textAlign: "right" }}>Order</th>
          <th style={{ ...th, textAlign: "right" }}>Postings</th>
          <th style={th}>State</th>
          {can && <th style={{ ...th, width: 210 }} />}
        </tr></thead>
        <tbody>
          {rows.map((h) => (editing === h.id ? (
            <tr key={h.id}><td style={td} colSpan={can ? 5 : 4}>
              <EditForm head={h} onSave={(body) => {
                setEditing(null); patch(h, body); }}
                onCancel={() => setEditing(null)} />
            </td></tr>
          ) : (
            <tr key={h.id}>
              <td style={td}>
                <strong>{h.name}</strong>
                {h.commercial && <Chip tone="info">Director-approved</Chip>}
                <div style={{ fontSize: 11, color: "var(--muted)",
                              fontFamily: "var(--font-mono)" }}>{h.code}</div>
              </td>
              <td style={{ ...td, textAlign: "right" }}>{h.sort_order}</td>
              <td style={{ ...td, textAlign: "right",
                           fontVariantNumeric: "tabular-nums" }}>
                {h.postings}</td>
              <td style={td}>
                {h.is_active ? <Chip tone="ok">In use</Chip>
                  : <Chip tone="info">Off</Chip>}
                {h.is_system && <Chip tone="warn">System</Chip>}
              </td>
              {can && (
                <td style={td}>
                  <button style={{ ...ghostButton, padding: "1px 6px",
                                   fontSize: 11 }}
                          onClick={() => setEditing(h.id)}>Edit</button>
                  {/* A system head must stay switched on: a posting path
                      reaches for it, and payroll would silently skip the
                      staff cost if it were off. */}
                  {!h.is_system && (
                    <button style={{ ...ghostButton, padding: "1px 6px",
                                     fontSize: 11, marginLeft: 4 }}
                            onClick={() => patch(h,
                              { is_active: !h.is_active })}>
                      {h.is_active ? "Switch off" : "Switch on"}</button>)}
                  {h.can_delete && (
                    <button style={{ ...ghostButton, padding: "1px 6px",
                                     fontSize: 11, marginLeft: 4,
                                     color: "#c0392b" }}
                            onClick={() => remove(h)}>Remove</button>)}
                </td>)}
            </tr>)))}
          {rows.length === 0 && (
            <tr><td style={{ ...td, color: "var(--muted)" }}
                    colSpan={can ? 5 : 4}>None.</td></tr>)}
        </tbody>
      </table>
    </>
  );
}

function Fields({ f, set, head }) {
  return (
    <>
      <input value={f.name} onChange={set("name")} placeholder="Name"
             style={{ ...inputStyle, width: 210 }} />
      <input value={f.sort_order} onChange={set("sort_order")} type="number"
             placeholder="Order" style={{ ...inputStyle, width: 90 }} />
      <label style={{ fontSize: 12.5, display: "flex", gap: 4,
                      alignItems: "center" }}>
        <input type="checkbox" checked={f.overhead}
               onChange={set("overhead")} />
        Company overhead — off project cost
      </label>
      <label style={{ fontSize: 12.5, display: "flex", gap: 4,
                      alignItems: "center" }}>
        <input type="checkbox" checked={f.commercial}
               onChange={set("commercial")} />
        Director approves its payments
      </label>
      {/* is_pool is not offered: the pools are the three internal buckets the
          ledger itself writes to, not something to create by hand. */}
      {head?.is_system && (
        <div style={{ fontSize: 11.5, color: "var(--muted)", width: "100%" }}>
          The system posts to this head by an internal code, so renaming it is
          safe — it cannot be switched off or removed.
        </div>)}
    </>
  );
}

function EditForm({ head, onSave, onCancel }) {
  const [f, setF] = useState({
    name: head.name, sort_order: head.sort_order,
    overhead: head.overhead, commercial: head.commercial });
  const set = (k) => (e) => setF({ ...f,
    [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                  alignItems: "center" }}>
      <Fields f={f} set={set} head={head} />
      <Btn onClick={() => onSave(f)} disabled={!f.name.trim()}>Save</Btn>
      <Btn variant="secondary" onClick={onCancel}>Cancel</Btn>
    </div>
  );
}

function AddForm({ onDone }) {
  const [f, setF] = useState({ name: "", sort_order: 100, overhead: false,
                               commercial: false });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setF({ ...f,
    [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function save() {
    setBusy(true); setErr(null);
    try {
      await api("/cost-head-master", { method: "POST", body: f });
      onDone(true);
    } catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <div style={{ border: "1px solid var(--sp-border, #d8e1e8)",
                  borderRadius: 8, padding: 12, marginBottom: 14,
                  display: "flex", gap: 8, flexWrap: "wrap",
                  alignItems: "center" }}>
      <Fields f={f} set={set} />
      <Btn onClick={save} disabled={busy || !f.name.trim()}>
        {busy ? "Saving…" : "Add"}</Btn>
      <Btn variant="secondary" onClick={() => onDone(false)}>Cancel</Btn>
      {err && <div style={{ color: "#c0392b", fontSize: 12.5, width: "100%" }}>
        {err}</div>}
    </div>
  );
}
