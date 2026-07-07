import { useEffect, useMemo, useState } from "react";
import { api } from "./api.js";
import { SectionTitle, StatusChip, buttonStyle, card, ghostButton, inputStyle,
         td, th } from "./ui.jsx";

export const DOC_LABELS = {
  MR: "Material Requisition",
  PR: "Procurement Requisition",
  LM: "Loading Manifest",
  GRN: "Goods Received Note",
};

const HEADER_FIELDS = {
  MR: [
    ["planned_loading", "Planned Loading / Trip", "text"],
    ["trades_covered", "Trades Covered", "text"],
    ["required_by", "Required On Site By", "date"],
  ],
  PR: [["requested_delivery", "Requested Delivery", "date"]],
  LM: [
    ["vessel", "Vessel / Boat", "text"],
    ["departure_point", "Departure Point", "text"],
    ["expected_arrival", "Expected Arrival", "date"],
    ["trip_no", "Trip / Load No.", "text"],
  ],
  GRN: [["date_received", "Date Received", "date"]],
};

// Which actions the UI offers; the server is the authority.
const ACTIONS = {
  MR: [
    ["submit", "Submit", ["DRAFT"], ["SITE_ADMIN", "PM", "ADMIN"]],
    ["approve", "Approve (PM)", ["SUBMITTED"], ["PM", "ADMIN"]],
    ["return", "Return with comment", ["SUBMITTED"], ["PM", "ADMIN"], "comment"],
    ["send", "Send to HO", ["PM_APPROVED"], ["SITE_ADMIN", "PM", "ADMIN"]],
    ["close", "Close", ["PARTIALLY_LOADED", "LOADED"],
     ["SITE_ADMIN", "PM", "HO_PURCHASING", "ADMIN"]],
  ],
  PR: [
    ["submit", "Submit", ["DRAFT"], ["HO_PURCHASING", "ADMIN"]],
    ["approve", "Approve (Director)", ["SUBMITTED"], ["DIRECTOR", "ADMIN"]],
    ["return", "Return with comment", ["SUBMITTED"], ["DIRECTOR", "ADMIN"],
     "comment"],
    ["record-payment", "Record payment / PO", ["APPROVED", "PAYMENT_PROCESSING"],
     ["HO_PURCHASING", "ADMIN"], "action_taken"],
    ["close", "Close", ["PAID_PO_ISSUED"], ["HO_PURCHASING", "ADMIN"]],
  ],
  LM: [["depart", "Depart (issue manifest)", ["DRAFT", "LOADING"],
        ["HO_PURCHASING", "ADMIN"]]],
  GRN: [
    ["count", "Confirm count", ["DRAFT"], ["SITE_ADMIN", "ADMIN"]],
    ["verify", "Verify (SE/PM)", ["COUNTED"], ["SITE_ENGINEER", "PM", "ADMIN"]],
  ],
};

function useItems() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    api("/items").then(setItems).catch(() => setItems([]));
  }, []);
  return items;
}

function ItemCell({ items, row, set }) {
  const label = (it) => `${it.code} — ${it.description}`;
  if (row.free_text) {
    return (
      <input value={row.free_text_desc || ""} placeholder="New item description"
             onChange={(e) => set({ free_text_desc: e.target.value })}
             style={{ ...inputStyle, background: "#fff8e6" }} />
    );
  }
  const selected = items.find((it) => it.id === row.item_id);
  return (
    <>
      <input list="sp-items" value={row._itemText ?? (selected ? label(selected) : "")}
             placeholder="Search catalog…"
             onChange={(e) => {
               const text = e.target.value;
               const match = items.find((it) => label(it) === text);
               set(match ? { item_id: match.id, _itemText: text,
                             unit: match.unit }
                         : { item_id: null, _itemText: text });
             }}
             style={inputStyle} />
      <datalist id="sp-items">
        {items.map((it) => <option key={it.id} value={label(it)} />)}
      </datalist>
    </>
  );
}

const LINE_DEFAULTS = {
  MR: { priority: "NORMAL" },
  PR: {},
  LM: {},
  GRN: {},
};

function num(v) {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : 0;
}

export function LineDocForm({ docType, site, sites, me, existing, onSaved,
                              onCancel }) {
  const items = useItems();
  const [payload, setPayload] = useState(existing?.payload ||
    (docType === "LM" ? { departure_point: "Male'" } : {}));
  const [siteId, setSiteId] = useState(existing?.site || site?.id || "");
  const [mrRefs, setMrRefs] = useState("");
  const [prRefs, setPrRefs] = useState("");
  const [rows, setRows] = useState(
    existing?.lines?.map((l) => ({
      item_id: l.item, free_text: l.is_free_text,
      free_text_desc: l.free_text_desc, unit: l.unit,
      qty_required: l.qty_required, qty_stock: l.qty_stock,
      qty_to_order: l.qty_to_order, qty_loaded: l.qty_loaded,
      qty_pending: l.qty_pending, qty_manifest: l.qty_manifest,
      qty_received: l.qty_received, priority: l.priority || "NORMAL",
      urgent_reason: l.urgent_reason, vendor: l.vendor,
      quotation_ref: l.quotation_ref, payment_terms: l.payment_terms,
      amount_cash: l.amount_cash, amount_credit: l.amount_credit,
      remarks: l.remarks,
    })) || [{ ...LINE_DEFAULTS[docType] }]
  );
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const setP = (k, v) => setPayload({ ...payload, [k]: v });
  const setRow = (i, patch) =>
    setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  async function prefillFromMr() {
    const first = mrRefs.split(",")[0]?.trim();
    if (!first) return setError("Enter an MR ref first.");
    try {
      const data = await api(`/mr/${first}/lm-prefill`);
      setSiteId(data.site_id);  // destination = the MR's site
      setRows(data.lines.map((l) => ({
        item_id: l.item_id, free_text: !l.item_id,
        free_text_desc: l.free_text_desc, unit: l.unit,
        qty_loaded: l.qty_loaded, qty_pending: l.qty_pending,
        remarks: l.remarks,
      })));
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }

  function linesForSave() {
    return rows
      .filter((r) => r.item_id || (r.free_text_desc || "").trim() ||
                     (r.vendor || "").trim())
      .map((r) => ({
        item_id: r.free_text ? null : r.item_id,
        free_text_desc: r.free_text ? r.free_text_desc
                        : (r.item_id ? "" : (r.free_text_desc ||
                                             r.vendor || "")),
        unit: r.unit, qty_required: r.qty_required, qty_stock: r.qty_stock,
        qty_to_order: r.qty_to_order, qty_loaded: r.qty_loaded,
        qty_pending: r.qty_pending, qty_manifest: r.qty_manifest,
        qty_received: r.qty_received, priority: r.priority,
        urgent_reason: r.urgent_reason, vendor: r.vendor,
        quotation_ref: r.quotation_ref, payment_terms: r.payment_terms,
        amount_cash: r.amount_cash, amount_credit: r.amount_credit,
        remarks: r.remarks,
      }));
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      let doc;
      if (existing) {
        doc = await api(`/documents/${existing.ref}`, {
          method: "PATCH",
          body: { payload, lines: linesForSave() },
        });
      } else {
        const body = {
          doc_type: docType, site_id: siteId, payload,
          lines: linesForSave(),
        };
        if (mrRefs.trim()) body.mr_refs = mrRefs.split(",").map((s) => s.trim());
        if (prRefs.trim()) body.pr_refs = prRefs.split(",").map((s) => s.trim());
        doc = await api("/documents", { method: "POST", body });
      }
      onSaved(doc);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const isHOForm = docType === "PR" || docType === "LM";

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
          {existing ? `${existing.ref} (draft)` : `New ${DOC_LABELS[docType]}`}
        </h2>
        <button onClick={onCancel} style={ghostButton}>Close</button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
                    gap: 12, marginTop: 16 }}>
        {isHOForm && !existing && (
          <label style={{ fontSize: 13 }}>Site / Project
            <select value={siteId} onChange={(e) => setSiteId(+e.target.value)}
                    style={inputStyle}>
              <option value="">Select site…</option>
              {(sites || []).filter((s) => !s.is_head_office).map((s) => (
                <option key={s.id} value={s.id}>{s.code} — {s.name}</option>
              ))}
            </select>
          </label>
        )}
        {HEADER_FIELDS[docType].map(([key, label, type]) => (
          <label key={key} style={{ fontSize: 13 }}>{label}
            <input type={type} value={payload[key] || ""}
                   onChange={(e) => setP(key, e.target.value)}
                   style={inputStyle} />
          </label>
        ))}
        {isHOForm && !existing && (
          <label style={{ fontSize: 13 }}>MR Reference(s), comma-separated
            <input value={mrRefs} onChange={(e) => setMrRefs(e.target.value)}
                   placeholder="MR-SJR-001" style={inputStyle} />
          </label>
        )}
        {docType === "LM" && !existing && (
          <label style={{ fontSize: 13 }}>PR Reference(s)
            <input value={prRefs} onChange={(e) => setPrRefs(e.target.value)}
                   placeholder="PR-001" style={inputStyle} />
          </label>
        )}
      </div>

      {docType === "LM" && !existing && (
        <button onClick={prefillFromMr} style={{ ...ghostButton, marginTop: 10 }}>
          Prefill lines from MR
        </button>
      )}

      <SectionTitle>
        {docType === "PR" ? "Vendors" : "Items"}
      </SectionTitle>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              {docType === "PR" ? (
                <>
                  <th style={th}>Vendor</th><th style={th}>Quotation Ref</th>
                  <th style={th}>Payment Terms</th>
                  <th style={th}>Amount Cash (MVR)</th>
                  <th style={th}>Amount Credit (MVR)</th>
                </>
              ) : (
                <>
                  <th style={{ ...th, minWidth: 220 }}>Item</th>
                  <th style={th}>New?</th><th style={th}>Unit</th>
                  {docType === "MR" && (<>
                    <th style={th}>Required</th><th style={th}>Stock</th>
                    <th style={th}>To Order</th><th style={th}>Priority</th>
                  </>)}
                  {docType === "LM" && (<>
                    <th style={th}>Loaded</th><th style={th}>Pending</th>
                  </>)}
                  {docType === "GRN" && (<>
                    <th style={th}>Manifest</th><th style={th}>Received</th>
                  </>)}
                </>
              )}
              <th style={th}>Remarks</th><th />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {docType === "PR" ? (
                  <>
                    <td style={{ padding: 3 }}><input value={row.vendor || ""}
                      onChange={(e) => setRow(i, { vendor: e.target.value })}
                      style={inputStyle} /></td>
                    <td style={{ padding: 3 }}><input value={row.quotation_ref || ""}
                      onChange={(e) => setRow(i, { quotation_ref: e.target.value })}
                      style={{ ...inputStyle, width: 110 }} /></td>
                    <td style={{ padding: 3 }}><input value={row.payment_terms || ""}
                      onChange={(e) => setRow(i, { payment_terms: e.target.value })}
                      style={{ ...inputStyle, width: 130 }} /></td>
                    <td style={{ padding: 3 }}><input type="number"
                      value={row.amount_cash ?? ""}
                      onChange={(e) => setRow(i, { amount_cash: e.target.value })}
                      style={{ ...inputStyle, width: 110 }} /></td>
                    <td style={{ padding: 3 }}><input type="number"
                      value={row.amount_credit ?? ""}
                      onChange={(e) => setRow(i, { amount_credit: e.target.value })}
                      style={{ ...inputStyle, width: 110 }} /></td>
                  </>
                ) : (
                  <>
                    <td style={{ padding: 3 }}>
                      <ItemCell items={items} row={row}
                                set={(patch) => setRow(i, patch)} />
                    </td>
                    <td style={{ padding: 3, textAlign: "center" }}>
                      <input type="checkbox" checked={!!row.free_text}
                             title="New item — not in catalog"
                             onChange={(e) =>
                               setRow(i, { free_text: e.target.checked,
                                           item_id: null, _itemText: "" })} />
                    </td>
                    <td style={{ padding: 3 }}>
                      <input value={row.unit || ""} disabled={!!row.item_id}
                             onChange={(e) => setRow(i, { unit: e.target.value })}
                             style={{ ...inputStyle, width: 60 }} />
                    </td>
                    {docType === "MR" && (<>
                      <td style={{ padding: 3 }}><input type="number"
                        value={row.qty_required ?? ""}
                        onChange={(e) => {
                          const required = e.target.value;
                          setRow(i, { qty_required: required,
                                      qty_to_order: Math.max(
                                        num(required) - num(row.qty_stock), 0) });
                        }}
                        style={{ ...inputStyle, width: 80 }} /></td>
                      <td style={{ padding: 3 }}><input type="number"
                        value={row.qty_stock ?? ""}
                        onChange={(e) => {
                          const stock = e.target.value;
                          setRow(i, { qty_stock: stock,
                                      qty_to_order: Math.max(
                                        num(row.qty_required) - num(stock), 0) });
                        }}
                        style={{ ...inputStyle, width: 80 }} /></td>
                      <td style={{ padding: 3 }}><input type="number"
                        value={row.qty_to_order ?? ""}
                        onChange={(e) => setRow(i, { qty_to_order: e.target.value })}
                        style={{ ...inputStyle, width: 80 }} /></td>
                      <td style={{ padding: 3 }}>
                        <select value={row.priority || "NORMAL"}
                                onChange={(e) => setRow(i, { priority: e.target.value })}
                                style={{ ...inputStyle, width: 90 }}>
                          <option>NORMAL</option><option>URGENT</option>
                        </select>
                        {row.priority === "URGENT" && (
                          <input placeholder="Urgent reason (required)"
                                 value={row.urgent_reason || ""}
                                 onChange={(e) =>
                                   setRow(i, { urgent_reason: e.target.value })}
                                 style={{ ...inputStyle, marginTop: 4,
                                          background: "#fff8e6" }} />
                        )}
                      </td>
                    </>)}
                    {docType === "LM" && (<>
                      <td style={{ padding: 3 }}><input type="number"
                        value={row.qty_loaded ?? ""}
                        onChange={(e) => setRow(i, { qty_loaded: e.target.value })}
                        style={{ ...inputStyle, width: 80 }} /></td>
                      <td style={{ padding: 3 }}><input type="number"
                        value={row.qty_pending ?? ""}
                        onChange={(e) => setRow(i, { qty_pending: e.target.value })}
                        style={{ ...inputStyle, width: 80 }} /></td>
                    </>)}
                    {docType === "GRN" && (<>
                      <td style={{ padding: 3 }}>{row.qty_manifest ?? ""}</td>
                      <td style={{ padding: 3 }}><input type="number"
                        value={row.qty_received ?? ""}
                        onChange={(e) => setRow(i, { qty_received: e.target.value })}
                        style={{ ...inputStyle, width: 80 }} /></td>
                    </>)}
                  </>
                )}
                <td style={{ padding: 3 }}><input value={row.remarks || ""}
                  onChange={(e) => setRow(i, { remarks: e.target.value })}
                  style={{ ...inputStyle, width: 130 }} /></td>
                <td style={{ width: 30 }}>
                  <button onClick={() => setRows(rows.filter((_, j) => j !== i))}
                          style={{ ...ghostButton, padding: "2px 8px",
                                   color: "#c0392b" }}>×</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button onClick={() => setRows([...rows, { ...LINE_DEFAULTS[docType] }])}
              style={{ ...ghostButton, padding: "4px 12px", marginTop: 6 }}>
        + Add row
      </button>

      {docType === "MR" && (
        <p style={{ fontSize: 12, color: "#5a6b78", marginTop: 10 }}>
          <label>
            <input type="checkbox" checked={!!payload.stock_attested}
                   onChange={(e) => setP("stock_attested", e.target.checked)} />{" "}
            Site stock quantities are from a physical count today (MR rule 5)
          </label>
        </p>
      )}

      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {existing ? "Save changes" : "Save draft"}
        </button>
      </div>
    </section>
  );
}

export function LineDocView({ doc: initial, me, onClose, onChanged, onEdit }) {
  const [doc, setDoc] = useState(initial);
  const [error, setError] = useState(null);

  async function act(action, body) {
    setError(null);
    try {
      const fresh = await api(`/documents/${doc.ref}/actions/${action}`,
                              { method: "POST", body });
      setDoc(fresh);
      onChanged?.();
    } catch (e) {
      setError(e.message);
    }
  }

  async function amend() {
    setError(null);
    try {
      const fresh = await api(`/documents/${doc.ref}/revisions`,
                              { method: "POST" });
      onEdit(fresh);
    } catch (e) {
      setError(e.message);
    }
  }

  const actions = useMemo(() => {
    if (doc.is_void) return [];
    return (ACTIONS[doc.doc_type] || []).filter(
      ([, , statuses, roles]) =>
        statuses.includes(doc.status) && roles.includes(me.role)
    );
  }, [doc, me.role]);

  const pdfs = (doc.attachments || []).filter((a) => a.kind === "GENERATED_PDF");
  const canEdit = doc.status === "DRAFT" && !doc.is_void;
  const canAmend = doc.doc_type === "MR" && !doc.is_void &&
    !["DRAFT", "SUBMITTED", "PM_APPROVED", "CLOSED"].includes(doc.status) &&
    ["SITE_ADMIN", "PM", "ADMIN"].includes(me.role);

  const isPR = doc.doc_type === "PR";
  const p = doc.payload || {};

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
          {doc.ref} <span style={{ color: "#5a6b78", fontSize: 14 }}>
            {doc.rev_label}</span>{" "}
          <StatusChip status={doc.is_void ? "VOID" : doc.status} />
        </h2>
        <button onClick={onClose} style={ghostButton}>Close</button>
      </div>
      <p style={{ color: "#5a6b78", fontSize: 13, margin: "6px 0 0" }}>
        {DOC_LABELS[doc.doc_type]} · {doc.site_name} · {doc.doc_date} ·
        prepared by {doc.created_by_name}
        {doc.is_void && ` · VOID: ${doc.void_reason}`}
      </p>
      {doc.links?.length > 0 && (
        <p style={{ fontSize: 12, color: "#5a6b78", margin: "4px 0 0" }}>
          References: {doc.links.map((l) => l.ref).join(" · ")}
        </p>
      )}

      <div style={{ display: "flex", gap: 10, margin: "14px 0",
                    flexWrap: "wrap" }}>
        {canEdit && <button onClick={() => onEdit(doc)} style={buttonStyle}>
          Continue editing</button>}
        {canAmend && <button onClick={amend} style={buttonStyle}>
          Amend (new revision)</button>}
        {actions.map(([action, label, , , prompt]) => (
          <button key={action} style={buttonStyle}
            onClick={() => {
              if (prompt === "comment") {
                const comment = window.prompt("Comment (required):");
                if (comment) act(action, { comment });
              } else if (prompt === "action_taken") {
                const value = window.prompt("Slip no. / PO no.:");
                if (value) act(action, { action_taken: value });
              } else {
                act(action);
              }
            }}>
            {label}
          </button>
        ))}
        {pdfs.map((f) => (
          <a key={f.id} href={f.url} target="_blank" rel="noreferrer"
             style={{ ...ghostButton, textDecoration: "none",
                      display: "inline-block" }}>
            PDF — {f.file_name}
          </a>
        ))}
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {Object.keys(p).length > 0 && (
        <table style={{ borderCollapse: "collapse", fontSize: 13,
                        marginBottom: 8 }}>
          <tbody>
            {Object.entries(p).filter(([, v]) => v !== "" && v != null &&
                                                 typeof v !== "object")
              .map(([k, v]) => (
                <tr key={k}>
                  <td style={{ ...td, color: "#5a6b78", borderTop: "none",
                               paddingRight: 18 }}>
                    {k.replace(/_/g, " ")}</td>
                  <td style={{ ...td, borderTop: "none" }}>{String(v)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      )}

      <SectionTitle>{isPR ? "Vendors" : "Items"}</SectionTitle>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              {isPR ? (<>
                <th style={th}>Vendor</th><th style={th}>Quotation</th>
                <th style={th}>Terms</th><th style={th}>Cash</th>
                <th style={th}>Credit</th>
              </>) : (<>
                <th style={th}>Description</th><th style={th}>Unit</th>
                {doc.doc_type === "MR" && (<>
                  <th style={th}>Required</th><th style={th}>Stock</th>
                  <th style={th}>To Order</th><th style={th}>Priority</th>
                </>)}
                {doc.doc_type === "LM" && (<>
                  <th style={th}>Loaded</th><th style={th}>Pending</th>
                </>)}
                {doc.doc_type === "GRN" && (<>
                  <th style={th}>Manifest</th><th style={th}>Received</th>
                  <th style={th}>Short/Excess</th>
                </>)}
              </>)}
              <th style={th}>Remarks</th>
            </tr>
          </thead>
          <tbody>
            {doc.lines.map((line) => (
              <tr key={line.id}
                  style={line.is_changed ? { background: "#fff8e6" } : {}}>
                {isPR ? (<>
                  <td style={td}>{line.vendor}</td>
                  <td style={td}>{line.quotation_ref}</td>
                  <td style={td}>{line.payment_terms}</td>
                  <td style={td}>{line.amount_cash}</td>
                  <td style={td}>{line.amount_credit}</td>
                </>) : (<>
                  <td style={td}>
                    {line.description}
                    {line.is_free_text && (
                      <span style={{ color: "#b35900", fontSize: 11,
                                     fontWeight: 700 }}> NEW ITEM</span>
                    )}
                    {line.is_changed && (
                      <span style={{ color: "#b35900", fontSize: 11,
                                     fontWeight: 700 }}> CHANGED</span>
                    )}
                  </td>
                  <td style={td}>{line.unit}</td>
                  {doc.doc_type === "MR" && (<>
                    <td style={td}>{line.qty_required}</td>
                    <td style={td}>{line.qty_stock}</td>
                    <td style={td}>{line.qty_to_order}</td>
                    <td style={td}>{line.priority}
                      {line.urgent_reason && ` — ${line.urgent_reason}`}</td>
                  </>)}
                  {doc.doc_type === "LM" && (<>
                    <td style={td}>{line.qty_loaded}</td>
                    <td style={td}>{line.qty_pending}</td>
                  </>)}
                  {doc.doc_type === "GRN" && (<>
                    <td style={td}>{line.qty_manifest}</td>
                    <td style={td}>{line.qty_received}</td>
                    <td style={{ ...td,
                                 color: num(line.qty_received) <
                                        num(line.qty_manifest)
                                   ? "#c0392b" : "inherit" }}>
                      {line.qty_received == null ? "" :
                        (num(line.qty_received) - num(line.qty_manifest))}
                    </td>
                  </>)}
                </>)}
                <td style={td}>{line.remarks}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {doc.revisions?.length > 1 && (
        <p style={{ fontSize: 12, color: "#5a6b78" }}>
          Revisions: {doc.revisions.map((r) =>
            r.is_current ? `${r.rev_label} (current)` : r.rev_label).join(" · ")}
        </p>
      )}

      {doc.approvals?.length > 0 && (
        <>
          <SectionTitle>Workflow trail</SectionTitle>
          {doc.approvals.map((a) => (
            <p key={a.id} style={{ fontSize: 12, color: "#1a7f37",
                                   margin: "4px 0" }}>
              {a.action} — {a.actor_name} ({a.actor_role.replace(/_/g, " ")}) —{" "}
              {new Date(a.acted_at).toLocaleString()}
              {a.comment && ` — "${a.comment}"`}
            </p>
          ))}
        </>
      )}
    </section>
  );
}
