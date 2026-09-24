// Trading customers — who Sales quote, deliver to and invoice. Delivery is
// to the customer's boat at Malé harbour, so the record carries the island
// the goods end up on and the vessels they usually send.
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Btn, Chip, card, inputStyle, td, th } from "../ui.jsx";

const EMPTY = {
  name: "", tin: "", business_reg_no: "", billing_address: "", island: "",
  vessels: "", contact_person: "", phone: "", email: "",
  default_currency: "MVR", credit_days: "", gst_exempt: false, notes: "",
  is_active: true,
};

function Field({ label, children, wide }) {
  return (
    <label className={"t-field" + (wide ? " t-field-wide" : "")}>
      <span>{label}</span>
      {children}
    </label>
  );
}

export function CustomerForm({ initial, onSaved, onCancel }) {
  const [d, setD] = useState({ ...EMPTY, ...(initial || {}) });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) =>
    setD({ ...d, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = { ...d, credit_days: d.credit_days === "" ? null : Number(d.credit_days) };
    try {
      const saved = initial?.id
        ? await api(`/trading/customers/${initial.id}`, { method: "PATCH", body })
        : await api("/trading/customers", { method: "POST", body });
      onSaved(saved);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} style={{ ...card, marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>{initial?.id ? "Edit customer" : "New customer"}</h3>
      <div className="t-grid">
        <Field label="Customer name" wide>
          <input style={inputStyle} value={d.name} onChange={set("name")} autoFocus required />
        </Field>
        <Field label="GST TIN">
          <input style={inputStyle} value={d.tin} onChange={set("tin")}
                 placeholder="printed on the tax invoice" />
        </Field>
        <Field label="Business registration no.">
          <input style={inputStyle} value={d.business_reg_no} onChange={set("business_reg_no")} />
        </Field>
        <Field label="Billing address" wide>
          <textarea style={{ ...inputStyle, minHeight: 56 }} value={d.billing_address}
                    onChange={set("billing_address")} />
        </Field>
        <Field label="Island / destination">
          <input style={inputStyle} value={d.island} onChange={set("island")}
                 placeholder="where the goods end up" />
        </Field>
        <Field label="Vessels">
          <input style={inputStyle} value={d.vessels} onChange={set("vessels")}
                 placeholder="boats they send to Malé harbour" />
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
        <Field label="Quote currency">
          <select style={inputStyle} value={d.default_currency} onChange={set("default_currency")}>
            <option value="MVR">MVR</option>
            <option value="USD">USD</option>
          </select>
        </Field>
        <Field label="Credit days">
          <input style={inputStyle} type="number" min="0" value={d.credit_days}
                 onChange={set("credit_days")} placeholder="blank = pay on invoice" />
        </Field>
        <Field label="Notes" wide>
          <textarea style={{ ...inputStyle, minHeight: 56 }} value={d.notes}
                    onChange={set("notes")} />
        </Field>
        <label className="t-check">
          <input type="checkbox" checked={!!d.gst_exempt} onChange={set("gst_exempt")} />
          GST exempt — no output GST on this customer's invoices
        </label>
        {initial?.id && (
          <label className="t-check">
            <input type="checkbox" checked={!!d.is_active} onChange={set("is_active")} />
            Active
          </label>
        )}
      </div>
      {error && <p className="t-note t-note-red">{error}</p>}
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Btn type="submit" disabled={busy || !d.name.trim()}>
          {busy ? "Saving…" : "Save customer"}
        </Btn>
        <Btn type="button" variant="secondary" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}

export default function CustomersPage({ canWrite }) {
  const [rows, setRows] = useState(null);
  const [search, setSearch] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [editing, setEditing] = useState(null);   // null | {} | customer

  function load() {
    const q = new URLSearchParams();
    if (search.trim()) q.set("search", search.trim());
    if (showAll) q.set("active", "all");
    return api(`/trading/customers?${q}`).then(setRows).catch(() => setRows([]));
  }
  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [search, showAll]);

  return (
    <div className="t-page">
      <div className="t-page-head">
        <h1 className="t-h1">Customers</h1>
        <div className="t-tools">
          <input style={{ ...inputStyle, width: 240 }} placeholder="Search name, island, vessel…"
                 value={search} onChange={(e) => setSearch(e.target.value)} />
          <label className="t-check">
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
            include inactive
          </label>
          {canWrite && !editing && (
            <Btn onClick={() => setEditing({})}>+ New customer</Btn>
          )}
        </div>
      </div>

      {editing && (
        <CustomerForm initial={editing.id ? editing : null}
                      onSaved={() => { setEditing(null); load(); }}
                      onCancel={() => setEditing(null)} />
      )}

      {rows === null ? <p>Loading…</p> : rows.length === 0 ? (
        <p className="t-empty">
          {search ? "No customer matches that." :
            "No customers yet. Every inquiry, quotation and delivery will hang off a customer, so start here."}
        </p>
      ) : (
        <table className="t-table">
          <thead>
            <tr>
              <th style={th}>Customer</th>
              <th style={th}>Island</th>
              <th style={th}>Vessels</th>
              <th style={th}>Contact</th>
              <th style={th}>Currency</th>
              <th style={th}>Credit</th>
              <th style={th}>GST</th>
              <th style={th}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className={c.is_active ? "" : "is-inactive"}>
                <td style={td}>
                  <b>{c.name}</b>
                  {c.tin && <div className="t-sub">TIN {c.tin}</div>}
                </td>
                <td style={td}>{c.island}</td>
                <td style={td}>{c.vessels}</td>
                <td style={td}>
                  {c.contact_person}
                  {c.phone && <div className="t-sub">{c.phone}</div>}
                </td>
                <td style={td}>{c.default_currency}</td>
                <td style={td}>{c.credit_days != null ? `${c.credit_days} d` : "on invoice"}</td>
                <td style={td}>
                  {c.gst_exempt ? <Chip tone="warn">exempt</Chip> : <Chip tone="info">GST</Chip>}
                  {!c.is_active && <> <Chip tone="alert">inactive</Chip></>}
                </td>
                <td style={td}>
                  {canWrite && (
                    <button className="t-link" onClick={() => setEditing(c)}>Edit</button>
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
