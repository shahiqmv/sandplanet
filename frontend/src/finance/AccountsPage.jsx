// Chart of accounts. PLANET lays down a standard chart that follows the
// company's audited statements; the accounting consultant then shapes it —
// adds, renames, re-codes, re-groups, closes (FINANCE_BUILD_BRIEF.md).
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Btn, Chip, card, ghostButton, inputStyle } from "../ui.jsx";
import { money, tree } from "./shared.jsx";

const BLANK = { code: "", name: "", type: "EXPENSE", parent: "", is_group: false,
                currency: "", description: "", is_active: true };

function AccountForm({ initial, accounts, types, onSaved, onCancel }) {
  const [d, setD] = useState({ ...BLANK, ...initial, parent: initial?.parent || "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setD({ ...d, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const groups = tree(accounts).filter((a) => a.is_group && a.type === d.type && a.id !== d.id);

  async function save(e) {
    e.preventDefault(); setBusy(true); setError(null);
    const body = { code: d.code, name: d.name, type: d.type, is_group: d.is_group,
                   parent: d.parent ? Number(d.parent) : null, currency: d.currency,
                   description: d.description, is_active: d.is_active };
    try {
      onSaved(d.id ? await api(`/ledger/accounts/${d.id}`, { method: "PATCH", body })
                   : await api("/ledger/accounts", { method: "POST", body }));
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  const field = { display: "flex", flexDirection: "column", gap: 4, fontSize: 13 };
  const lab = (t) => <span style={{ fontWeight: 600, opacity: .8 }}>{t}</span>;
  return (
    <form onSubmit={save} style={{ ...card, background: "#fbf6ea", marginBottom: 14 }}>
      <h3 style={{ marginTop: 0 }}>{d.id ? `Edit ${initial.code} ${initial.name}` : "New account"}</h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: "10px 16px" }}>
        <label style={field}>{lab("Code")}
          <input style={inputStyle} value={d.code} onChange={set("code")} required maxLength={12} /></label>
        <label style={{ ...field, gridColumn: "span 2" }}>{lab("Name")}
          <input style={inputStyle} value={d.name} onChange={set("name")} required /></label>
        <label style={field}>{lab("Type")}
          <select style={inputStyle} value={d.type} onChange={(e) => setD({ ...d, type: e.target.value, parent: "" })}>
            {types.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select></label>
        <label style={{ ...field, gridColumn: "span 2" }}>{lab("Sub-account of")}
          <select style={inputStyle} value={d.parent} onChange={set("parent")}>
            <option value="">— none —</option>
            {groups.map((g) => <option key={g.id} value={g.id}>{"  ".repeat(g.depth)}{g.code} {g.name}</option>)}
          </select></label>
        <label style={field}>{lab("Currency")}
          <select style={inputStyle} value={d.currency} onChange={set("currency")} disabled={d.is_group}>
            <option value="">MVR</option><option value="USD">USD — held in dollars</option>
          </select></label>
        <label style={{ ...field, gridColumn: "1 / -1" }}>{lab("Note (optional)")}
          <input style={inputStyle} value={d.description} onChange={set("description")}
                 placeholder="What goes in this account" /></label>
        <label style={{ fontSize: 13 }}><input type="checkbox" checked={d.is_group} onChange={set("is_group")} />{" "}
          A group — a heading that holds other accounts and takes no entries</label>
        {d.id && <label style={{ fontSize: 13 }}><input type="checkbox" checked={d.is_active} onChange={set("is_active")} /> In use</label>}
      </div>
      {initial?.system && (
        <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "10px 0 0" }}>
          PLANET posts to this account automatically. You can rename it, re-code it and move it; it can't be deleted.</p>
      )}
      {error && <p className="f-bad" style={{ fontSize: 13 }}>{error}</p>}
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Btn type="submit" disabled={busy}>{busy ? "Saving…" : "Save account"}</Btn>
        <Btn type="button" variant="secondary" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}

export default function AccountsPage({ go }) {
  const [data, setData] = useState(null);
  const [editing, setEditing] = useState(null);     // null | {} | account
  const [q, setQ] = useState("");
  const [showClosed, setShowClosed] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => api("/ledger/accounts").then(setData).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function setup() {
    setBusy(true); setError(null);
    try { await api("/ledger/setup", { method: "POST", body: {} }); await load(); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function remove(a) {
    if (!window.confirm(`Delete ${a.code} ${a.name}?`)) return;
    try { await api(`/ledger/accounts/${a.id}`, { method: "DELETE" }); load(); }
    catch (e) { setError(e.message); }
  }

  if (error && !data) return <div style={card}>{error}</div>;
  if (!data) return <div style={card}>Loading…</div>;
  const { accounts, types, can_edit: canEdit } = data;

  if (accounts.length === 0) {
    return (
      <div style={{ ...card, maxWidth: 720 }}>
        <h2 style={{ marginTop: 0 }}>Set up the chart of accounts</h2>
        <p>The books are empty. PLANET can lay down a standard chart to start from: it follows the
          headings and account names of the company's audited statements, and adds the accounts the
          operations need (supplier payables, retention, client advances, input GST, stock,
          accumulated depreciation), plus one account for each company bank account.</p>
        <p>Nothing in it is fixed. Every account can be renamed, re-coded, moved or closed, and new
          ones added, before or after entries are posted.</p>
        {error && <p className="f-bad">{error}</p>}
        {canEdit ? <Btn onClick={setup} disabled={busy}>{busy ? "Setting up…" : "Start with the standard chart"}</Btn>
          : <p style={{ color: "var(--muted)" }}>Finance sets this up.</p>}
      </div>
    );
  }

  const needle = q.trim().toLowerCase();
  const rows = tree(accounts).filter((a) => (showClosed || a.is_active)
    && (!needle || `${a.code} ${a.name}`.toLowerCase().includes(needle)));
  const typeLabel = Object.fromEntries(types.map((t) => [t.value, t.label]));
  return (
    <div className="t-page">
      <div className="f-bar">
        <h1 className="t-h1" style={{ margin: 0 }}>Chart of accounts</h1>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>{accounts.filter((a) => !a.is_group).length} accounts ·
          balances in MVR</span>
        <span className="spacer" />
        <input style={{ ...inputStyle, width: 220 }} placeholder="Find code or name…" value={q} onChange={(e) => setQ(e.target.value)} />
        <label style={{ fontSize: 13 }}><input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} /> show closed</label>
        {canEdit && editing === null && <Btn onClick={() => setEditing({})}>+ New account</Btn>}
      </div>
      {error && <p className="f-bad" style={{ fontSize: 13 }}>{error}</p>}
      {editing !== null && (
        <AccountForm initial={editing} accounts={accounts} types={types}
                     onSaved={() => { setEditing(null); setError(null); load(); }} onCancel={() => setEditing(null)} />
      )}
      <div style={{ ...card, padding: 0, overflowX: "auto" }}>
        <table className="f-table">
          <thead><tr><th>Code</th><th>Account</th><th>Type</th><th>Currency</th>
            <th style={{ textAlign: "right" }}>Balance</th>{canEdit && <th />}</tr></thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id} className={a.is_group ? "f-group" : "f-click"} style={{ opacity: a.is_active ? 1 : .5 }}
                  onClick={() => !a.is_group && go("ledger", a.id)}>
                <td style={{ fontFamily: "var(--font-mono)" }}>{a.code}</td>
                <td style={{ paddingLeft: 10 + (needle ? 0 : a.depth * 18) }}>{a.name}
                  {a.system && <span title="PLANET posts to this account automatically" style={{ marginLeft: 6, fontSize: 11, color: "var(--muted)" }}>auto</span>}
                  {!a.is_active && <> <Chip tone="info">closed</Chip></>}</td>
                <td>{typeLabel[a.type]}</td>
                <td>{a.is_group ? "" : (a.currency || "MVR")}</td>
                <td className="f-num">{a.is_group || a.balance == null ? "" : money(a.balance)}</td>
                {canEdit && (
                  <td style={{ whiteSpace: "nowrap" }} onClick={(e) => e.stopPropagation()}>
                    <button className="f-link" onClick={() => { setEditing(a); window.scrollTo({ top: 0, behavior: "smooth" }); }}>edit</button>
                    {!a.system && !a.is_bank && <>{" · "}<button className="f-link" onClick={() => remove(a)}>delete</button></>}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
        Click an account to open its ledger. A balance shows on the account's normal side: a liability's credit
        balance and an asset's debit balance are both shown as positive figures.
        {canEdit && (
          <button style={{ ...ghostButton, marginLeft: 10, padding: "2px 10px", fontSize: 12 }}
                  onClick={() => api("/ledger/sync-banks", { method: "POST", body: {} }).then(load)}>
            Add accounts for new bank accounts</button>
        )}
      </p>
    </div>
  );
}
