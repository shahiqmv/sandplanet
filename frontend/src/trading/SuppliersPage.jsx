// Suppliers — the one directory Purchasing and Trading share (owner
// 2026-11-18). Every local and international supplier is listed, the ones
// already used in trading first. Sales add sources themselves; a name that
// resembles one on file is offered back rather than copied, and a supplier
// Purchasing also relies on keeps its name, type and status with Purchasing.
import { useEffect, useState } from "react";
import { api } from "../api.js";
import SimilarSuppliers from "../SimilarSuppliers.jsx";
import { Btn, Chip, card, inputStyle, td, th } from "../ui.jsx";

const EMPTY = {
  name: "", category: "INTERNATIONAL", country: "", default_currency: "USD",
  default_incoterm: "", contact_person: "", phone: "", email: "", address: "",
  notes: "", is_active: true,
};

const CATEGORY = { LOCAL: "Local", INTERNATIONAL: "International" };

function Field({ label, children, wide }) {
  return (
    <label className={"t-field" + (wide ? " t-field-wide" : "")}>
      <span>{label}</span>
      {children}
    </label>
  );
}

export function SupplierForm({ initial, onSaved, onCancel }) {
  const [d, setD] = useState({ ...EMPTY, ...(initial || {}) });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [similar, setSimilar] = useState(null);
  const set = (k) => (e) =>
    setD({ ...d, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  // Purchasing relies on this record too: its name, type and status are
  // theirs to change (owner 2026-11-18)
  const shared = !!initial?.shared;

  async function save(e, confirmNew = false) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      let body = confirmNew ? { ...d, confirm_new: true } : d;
      if (initial?.id && shared) {
        body = { ...d };
        delete body.name; delete body.category; delete body.is_active;
      }
      const saved = initial?.id
        ? await api(`/trading/suppliers/${initial.id}`, { method: "PATCH", body })
        : await api("/trading/suppliers", { method: "POST", body });
      onSaved(saved);
    } catch (err) {
      if (err.status === 409 && err.data?.similar) setSimilar(err.data.similar);
      else setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function useExisting(s) {
    setBusy(true);
    setError(null);
    try {
      onSaved(await api(`/trading/suppliers/${s.id}/adopt`, { method: "POST" }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} style={{ ...card, marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>{initial?.id ? "Edit supplier" : "New supplier"}</h3>
      {!initial?.id && (
        <p className="t-note">
          One supplier list is shared with Purchasing. Search above before
          adding — a name close to one already on file is offered back to you
          rather than copied.
        </p>
      )}
      {shared && (
        <p className="t-note">
          Purchasing also uses this supplier, so its name, type and status are
          changed on Purchasing's Suppliers page. You can update the contact
          and trading terms here.
        </p>
      )}
      <div className="t-grid">
        <Field label="Supplier name" wide>
          <input style={inputStyle} value={d.name} onChange={set("name")} autoFocus required
                 disabled={shared} />
        </Field>
        <Field label="Type">
          <select style={inputStyle} value={d.category} onChange={set("category")} disabled={shared}>
            <option value="INTERNATIONAL">International</option>
            <option value="LOCAL">Local</option>
          </select>
        </Field>
        <Field label="Country">
          <input style={inputStyle} value={d.country} onChange={set("country")} />
        </Field>
        <Field label="Quotes in">
          <select style={inputStyle} value={d.default_currency} onChange={set("default_currency")}>
            <option value="USD">USD</option>
            <option value="MVR">MVR</option>
            <option value="EUR">EUR</option>
            <option value="CNY">CNY</option>
            <option value="INR">INR</option>
            <option value="AED">AED</option>
            <option value="LKR">LKR</option>
          </select>
        </Field>
        <Field label="Usual terms (incoterm)">
          <input style={inputStyle} value={d.default_incoterm} onChange={set("default_incoterm")}
                 placeholder="FOB, CIF…" />
        </Field>
        <Field label="Contact person">
          <input style={inputStyle} value={d.contact_person} onChange={set("contact_person")} />
        </Field>
        <Field label="Phone">
          <input style={inputStyle} value={d.phone} onChange={set("phone")} />
        </Field>
        <Field label="Email">
          <input style={inputStyle} type="email" value={d.email} onChange={set("email")} />
        </Field>
        <Field label="Address" wide>
          <textarea style={{ ...inputStyle, minHeight: 56 }} value={d.address}
                    onChange={set("address")} />
        </Field>
        <Field label="Notes" wide>
          <textarea style={{ ...inputStyle, minHeight: 56 }} value={d.notes}
                    onChange={set("notes")} />
        </Field>
        {initial?.id && (
          <label className="t-check">
            <input type="checkbox" checked={!!d.is_active} onChange={set("is_active")}
                   disabled={shared} />
            Active
          </label>
        )}
      </div>
      {similar && (
        <SimilarSuppliers similar={similar} busy={busy}
          useLabel="Use this one for trading"
          onUse={useExisting}
          onCreateAnyway={() => { setSimilar(null); save(null, true); }}
          onCancel={() => setSimilar(null)} />
      )}
      {error && <p className="t-note t-note-red">{error}</p>}
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Btn type="submit" disabled={busy || !d.name.trim()}>
          {busy ? "Saving…" : "Save supplier"}
        </Btn>
        <Btn type="button" variant="secondary" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}

export default function SuppliersPage({ canWrite }) {
  const [rows, setRows] = useState(null);
  const [search, setSearch] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [tradingOnly, setTradingOnly] = useState(false);
  const [editing, setEditing] = useState(null);

  function load() {
    const q = new URLSearchParams();
    if (search.trim()) q.set("search", search.trim());
    if (showAll) q.set("active", "all");
    if (tradingOnly) q.set("trading", "1");
    return api(`/trading/suppliers?${q}`).then(setRows).catch(() => setRows([]));
  }
  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [search, showAll, tradingOnly]);

  return (
    <div className="t-page">
      <div className="t-page-head">
        <h1 className="t-h1">Suppliers</h1>
        <div className="t-tools">
          <input style={{ ...inputStyle, width: 240 }} placeholder="Search name, country…"
                 value={search} onChange={(e) => setSearch(e.target.value)} />
          <label className="t-check">
            <input type="checkbox" checked={tradingOnly} onChange={(e) => setTradingOnly(e.target.checked)} />
            used in trading only
          </label>
          <label className="t-check">
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
            include inactive
          </label>
          {canWrite && !editing && (
            <Btn onClick={() => setEditing({})}>+ New supplier</Btn>
          )}
        </div>
      </div>

      {editing && (
        <SupplierForm initial={editing.id ? editing : null}
                      onSaved={() => { setEditing(null); load(); }}
                      onCancel={() => setEditing(null)} />
      )}

      {rows === null ? <p>Loading…</p> : rows.length === 0 ? (
        <p className="t-empty">
          {search ? "No supplier matches that." : tradingOnly
            ? "No supplier has been used in trading yet. Pick one on a pricing-sheet line and it is tagged here."
            : "No suppliers on file yet."}
        </p>
      ) : (
        <table className="t-table">
          <thead>
            <tr>
              <th style={th}>Supplier</th>
              <th style={th}>Type</th>
              <th style={th}>Country</th>
              <th style={th}>Quotes in</th>
              <th style={th}>Terms</th>
              <th style={th}>Contact</th>
              <th style={th}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id} className={s.is_active ? "" : "is-inactive"}>
                <td style={td}><b>{s.name}</b>
                  {s.is_trading && <> <Chip tone="ok">trading</Chip></>}</td>
                <td style={td}><Chip tone="info">{CATEGORY[s.category] || s.category}</Chip>
                  {!s.is_active && <> <Chip tone="alert">inactive</Chip></>}</td>
                <td style={td}>{s.country}</td>
                <td style={td}>{s.default_currency}</td>
                <td style={td}>{s.default_incoterm}</td>
                <td style={td}>
                  {s.contact_person}
                  {(s.phone || s.email) && <div className="t-sub">{[s.phone, s.email].filter(Boolean).join(" · ")}</div>}
                </td>
                <td style={td}>
                  {canWrite && (
                    <button className="t-link" onClick={() => setEditing(s)}>Edit</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
