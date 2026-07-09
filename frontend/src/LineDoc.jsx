import { useEffect, useMemo, useState } from "react";
import { api, apiUpload } from "./api.js";
import { QuotationsSummary } from "./QuotationsPanel.jsx";
import { SectionTitle, StatusChip, buttonStyle, card, ghostButton, inputStyle,
         td, th } from "./ui.jsx";

export const DOC_LABELS = {
  MR: "Material Requisition",
  PR: "Procurement Requisition",
  LM: "Loading Manifest",
  GRN: "Goods Received Note",
  PO: "Purchase Order",
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
    // Signatory authorisation is the commitment point (§6C.2); Finance
    // may authorise below the threshold
    ["authorise", "Authorise", ["APPROVED"],
     ["SIGNATORY", "FINANCE", "ADMIN"], "comment"],
    ["return", "Return for review", ["SUBMITTED", "APPROVED"],
     ["DIRECTOR", "SIGNATORY", "FINANCE", "ADMIN"], "comment"],
    ["withdraw-authorisation", "Withdraw authorisation", ["AUTHORISED"],
     ["FINANCE", "ADMIN"], "comment"],
    ["record-payment", "Record payment / PO",
     ["AUTHORISED", "PAYMENT_PROCESSING"],
     ["FINANCE", "ADMIN"], "action_taken"],
    ["close", "Close", ["PAID_PO_ISSUED"], ["HO_PURCHASING", "ADMIN"]],
  ],
  LM: [["depart", "Depart (issue manifest)", ["DRAFT", "LOADING"],
        ["HO_PURCHASING", "ADMIN"]]],
  PO: [
    ["issue", "Issue to supplier", ["DRAFT"], ["HO_PURCHASING", "ADMIN"]],
    ["close", "Close", ["ISSUED"], ["HO_PURCHASING", "ADMIN"]],
  ],
  GRN: [
    ["count", "Confirm count", ["DRAFT"], ["SITE_ADMIN", "ADMIN"]],
    ["verify", "Verify (SE/PM)", ["COUNTED"], ["SITE_ENGINEER", "PM", "ADMIN"]],
  ],
};

function useItems() {
  const [items, setItems] = useState([]);
  const reload = () =>
    api("/items").then(setItems).catch(() => setItems([]));
  useEffect(() => { reload(); }, []);
  return { items, reload };
}

// Pick references from a dropdown instead of typing them (owner UX request)
function RefPicker({ label, refs, setRefs, options, hint }) {
  const chosen = refs.split(",").map((s) => s.trim()).filter(Boolean);
  const remaining = options.filter((o) => !chosen.includes(o.ref));
  return (
    <label style={{ fontSize: 13 }}>{label}
      <select value="" style={inputStyle}
              onChange={(e) => {
                if (e.target.value) {
                  setRefs([...chosen, e.target.value].join(","));
                }
              }}>
        <option value="">
          {remaining.length ? `Select… (${remaining.length} open)`
                            : (hint || "None open")}
        </option>
        {remaining.map((o) => (
          <option key={o.ref} value={o.ref}>{o.label}</option>
        ))}
      </select>
      {chosen.length > 0 && (
        <span style={{ display: "flex", gap: 6, flexWrap: "wrap",
                       marginTop: 4 }}>
          {chosen.map((ref) => (
            <span key={ref}
                  style={{ background: "var(--sp-navy)", color: "#fff",
                           borderRadius: 12, padding: "2px 10px",
                           fontSize: 12 }}>
              {ref}{" "}
              <a href="#" style={{ color: "var(--sp-sky)",
                                   textDecoration: "none" }}
                 onClick={(e) => { e.preventDefault();
                   setRefs(chosen.filter((r) => r !== ref).join(",")); }}>
                ×
              </a>
            </span>
          ))}
        </span>
      )}
    </label>
  );
}

function ItemCell({ items, row, set, me, onItemCreated }) {
  const label = (it) => `${it.code} — ${it.description}`;
  const canCreate = ["HO_PURCHASING", "ADMIN"].includes(me?.role);
  if (row.free_text) {
    return (
      <input value={row.free_text_desc || ""} placeholder="New item description"
             onChange={(e) => set({ free_text_desc: e.target.value })}
             style={{ ...inputStyle, background: "#fff8e6" }} />
    );
  }
  const selected = items.find((it) => it.id === row.item_id);
  const text = row._itemText ?? (selected ? label(selected) : "");
  // Purchasing/Admin typed something with no catalog match → offer to
  // create it in the catalog on the spot (owner)
  const typedNoMatch = canCreate && text.trim() && !row.item_id &&
    !items.some((it) => label(it) === text);

  async function createFromText() {
    const description = text.trim();
    const unit = window.prompt(`Create "${description}" in the catalog.\n\n`
                               + "Unit (nos, kg, ltr, bag, m, m2, m3…):", "");
    if (unit === null) return;
    const category = window.prompt("Category (leave blank if unsure):", "");
    if (category === null) return;
    try {
      const item = await api("/items", { method: "POST",
        body: { description, unit: unit.trim(),
                category: category.trim() } });
      await onItemCreated?.();
      set({ item_id: item.id, _itemText: label(item), unit: item.unit });
    } catch (e) {
      window.alert(e.message);
    }
  }

  return (
    <>
      <input list="sp-items" value={text}
             placeholder="Search catalog…"
             onChange={(e) => {
               const v = e.target.value;
               const match = items.find((it) => label(it) === v);
               set(match ? { item_id: match.id, _itemText: v,
                             unit: match.unit }
                         : { item_id: null, _itemText: v });
             }}
             style={inputStyle} />
      <datalist id="sp-items">
        {items.map((it) => <option key={it.id} value={label(it)} />)}
      </datalist>
      {typedNoMatch && (
        <button type="button" onClick={createFromText}
                style={{ ...ghostButton, padding: "2px 8px", fontSize: 11.5,
                         marginTop: 3, color: "var(--sp-navy)" }}>
          + Add "{text.trim().slice(0, 24)}
          {text.trim().length > 24 ? "…" : ""}" to catalog
        </button>
      )}
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
  const { items, reload: reloadItems } = useItems();
  const [payload, setPayload] = useState(existing?.payload ||
    (docType === "LM" ? { departure_point: "Male'" } : {}));
  const [siteId, setSiteId] = useState(existing?.site || site?.id || "");
  const [mrRefs, setMrRefs] = useState("");
  const [prRefs, setPrRefs] = useState("");
  const [poRefs, setPoRefs] = useState("");
  const [openMrs, setOpenMrs] = useState([]);
  const [related, setRelated] = useState({ prs: [], pos: [] });

  const isRefForm = (docType === "PR" || docType === "LM") && !existing;

  useEffect(() => {
    if (!isRefForm) return;
    const params = siteId ? `&site=${siteId}` : "";
    // A new PR offers only MRs at HO with no active PR yet; the LM loader
    // offers MRs through the loading stages.
    const filter = docType === "PR" ? "for_pr=1" : "open=1";
    api(`/documents/list?doc_type=MR&${filter}${params}`).then(setOpenMrs);
  }, [isRefForm, siteId, docType]);

  useEffect(() => {
    if (docType !== "LM" || existing) return;
    const first = mrRefs.split(",")[0]?.trim();
    if (!first) return setRelated({ prs: [], pos: [] });
    api(`/mr/${first}/related`).then(setRelated)
      .catch(() => setRelated({ prs: [], pos: [] }));
  }, [docType, existing, mrRefs]);

  // Picking an MR pins the site (PR/LM follow the MR's site)
  useEffect(() => {
    if (!isRefForm || siteId) return;
    const first = mrRefs.split(",")[0]?.trim();
    const mr = openMrs.find((m) => m.ref === first);
    if (mr) setSiteId(mr.site);
  }, [mrRefs, openMrs, isRefForm, siteId]);
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

  async function prefillFromPo() {
    const first = poRefs.split(",")[0]?.trim();
    if (!first) return setError("Enter a PO ref first.");
    try {
      const data = await api(`/po/${first}/lm-prefill`);
      setSiteId(data.site_id);
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
      let effectiveSite = siteId;
      if (!effectiveSite && mrRefs.trim()) {
        // PR/LM follow the MR's site — resolve it instead of asking again
        const mr = await api(`/documents/${mrRefs.split(",")[0].trim()}`);
        effectiveSite = mr.site;
        setSiteId(mr.site);
      }
      let doc;
      if (existing) {
        doc = await api(`/documents/${existing.ref}`, {
          method: "PATCH",
          body: { payload, lines: linesForSave() },
        });
      } else {
        const body = {
          doc_type: docType, site_id: effectiveSite, payload,
          lines: linesForSave(),
        };
        if (mrRefs.trim()) body.mr_refs = mrRefs.split(",").map((s) => s.trim());
        if (prRefs.trim()) body.pr_refs = prRefs.split(",").map((s) => s.trim());
        if (poRefs.trim()) body.po_refs = poRefs.split(",").map((s) => s.trim());
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
          <RefPicker label="MR Reference(s)" refs={mrRefs} setRefs={setMrRefs}
                     options={openMrs.map((m) => ({
                       ref: m.ref,
                       label: `${m.ref} · ${m.site_code} · ${m.status
                         .replace(/_/g, " ")}${m.payload?.planned_loading
                         ? " · " + m.payload.planned_loading : ""}`,
                     }))} />
        )}
        {docType === "LM" && !existing && (
          <>
            <RefPicker label="PR Reference(s)" refs={prRefs} setRefs={setPrRefs}
                       hint={mrRefs ? "No PRs for this MR" : "Pick an MR first"}
                       options={related.prs.map((p) => ({
                         ref: p.ref,
                         label: `${p.ref} · ${p.status.replace(/_/g, " ")}`,
                       }))} />
            <RefPicker label="PO Reference(s)" refs={poRefs} setRefs={setPoRefs}
                       hint={mrRefs ? "No POs for this MR" : "Pick an MR first"}
                       options={related.pos.map((p) => ({
                         ref: p.ref,
                         label: `${p.ref} · ${p.supplier} · ${p.status}`,
                       }))} />
          </>
        )}
      </div>

      {docType === "LM" && !existing && (
        <div style={{ display: "flex", gap: 8, marginTop: 10,
                      alignItems: "center" }}>
          <button onClick={prefillFromPo} style={ghostButton}
                  disabled={!poRefs.trim()}>
            Prefill lines from PO
          </button>
          <button onClick={prefillFromMr} style={ghostButton}
                  disabled={!mrRefs.trim()}>
            Prefill lines from MR (cash purchases)
          </button>
          <span style={{ fontSize: 12, color: "#5a6b78" }}>
            No PO? Prefill from the MR and edit the loaded quantities.
          </span>
        </div>
      )}

      {docType === "PR" && !existing ? (
        <p style={{ background: "#e8f0f7", borderRadius: 8, padding: "10px 14px",
                    fontSize: 13, color: "var(--sp-navy)", marginTop: 16 }}>
          Save the draft first — then capture each supplier's quotation and
          match it to the MR lines on the next screen. The vendor summary
          builds itself from the quotes.
        </p>
      ) : (
      <>
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
                      <ItemCell items={items} row={row} me={me}
                                onItemCreated={reloadItems}
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
      </>
      )}

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

export function LineDocView({ doc: initial, me, onClose, onChanged, onEdit,
                              onOpenMatch, onOpenDoc }) {
  const [doc, setDoc] = useState(initial);
  const [error, setError] = useState(null);
  const [gstRate, setGstRate] = useState(8);
  const [quoteFiles, setQuoteFiles] = useState({});
  const [payRow, setPayRow] = useState(null);
  const [payRef, setPayRef] = useState("");
  const [payFile, setPayFile] = useState(null);

  useEffect(() => {
    if (initial.doc_type === "PR") {
      api("/parameters/gst_rate").then((p) => setGstRate(+p.value))
        .catch(() => {});
      api(`/pr/${initial.ref}/quotations`).then((qs) =>
        setQuoteFiles(Object.fromEntries(
          qs.filter((q) => q.file_url)
            .map((q) => [q.supplier_name, q.file_url])))).catch(() => {});
    }
  }, [initial.doc_type, initial.ref]);

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
  const canRecordPay = isPR && !doc.is_void &&
    ["HO_PURCHASING", "FINANCE", "ADMIN"].includes(me.role) &&
    ["AUTHORISED", "PAYMENT_PROCESSING"].includes(doc.status);
  const slipByVendor = {};
  for (const a of doc.attachments || []) {
    if (a.kind === "PAYMENT_SLIP") slipByVendor[a.caption] = a.url;
  }

  async function recordPayment(line) {
    setError(null);
    try {
      const fd = new FormData();
      fd.append("line_id", line.id);
      fd.append("payment_ref", payRef);
      if (payFile) fd.append("file", payFile);
      const fresh = await apiUpload(`/pr/${doc.ref}/vendor-payment`, fd);
      delete fresh.slip_url;
      setDoc(fresh);
      setPayRow(null);
      setPayRef("");
      setPayFile(null);
      onChanged?.();
    } catch (e) {
      setError(e.message);
    }
  }

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
                <th style={th}>Vendor</th><th style={th}>Quotation Ref</th>
                <th style={th}>Terms</th>
                <th style={th}>PO / Payment Ref</th>
                <th style={{ ...th, textAlign: "right" }}>Cash</th>
                <th style={{ ...th, textAlign: "right" }}>Credit</th>
                <th style={{ ...th, textAlign: "right" }}>Total</th>
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
                {doc.doc_type === "PO" && (<>
                  <th style={th}>Qty</th><th style={th}>Rate</th>
                  <th style={th}>Amount</th>
                </>)}
              </>)}
              {!isPR && <th style={th}>Remarks</th>}
            </tr>
          </thead>
          <tbody>
            {doc.lines.map((line) => (
              <tr key={line.id}
                  style={line.is_changed ? { background: "#fff8e6" } : {}}>
                {isPR ? (<>
                  <td style={td}>{line.vendor}</td>
                  <td style={td}>
                    {line.quotation_ref}
                    {quoteFiles[line.vendor] && (
                      <>
                        {line.quotation_ref ? " " : ""}
                        <a href={quoteFiles[line.vendor]} target="_blank"
                           rel="noreferrer"
                           title="Open the uploaded quotation">📎 quote</a>
                      </>
                    )}
                  </td>
                  <td style={td}>{line.payment_terms}</td>
                  <td style={td}>
                    {/* slip no. for cash, PO no. for credit */}
                    {line.action_taken ? (
                      <>
                        <span style={{ color: "#1a7f37", fontWeight: 600 }}>
                          {line.action_taken}
                        </span>
                        {slipByVendor[line.vendor] && (
                          <>
                            {" "}
                            <a href={slipByVendor[line.vendor]} target="_blank"
                               rel="noreferrer" title="Payment slip / voucher">
                              📎 slip
                            </a>
                          </>
                        )}
                      </>
                    ) : line.po_ref ? (
                      <a href="#" style={{ color: "var(--sp-navy)",
                                           fontWeight: 600 }}
                         onClick={(e) => { e.preventDefault();
                                           onOpenDoc?.(line.po_ref); }}>
                        {line.po_ref}
                      </a>
                    ) : canRecordPay && payRow !== line.id ? (
                      <button onClick={() => { setPayRow(line.id);
                                               setPayRef(""); setPayFile(null); }}
                              style={{ ...ghostButton, padding: "2px 10px",
                                       fontSize: 12 }}>
                        Record payment
                      </button>
                    ) : payRow === line.id ? (
                      <span style={{ display: "flex", gap: 6,
                                     flexWrap: "wrap" }}>
                        <input placeholder="Slip / voucher no." value={payRef}
                               onChange={(e) => setPayRef(e.target.value)}
                               style={{ ...inputStyle, width: 140 }} />
                        <input type="file" accept=".pdf,image/*"
                               onChange={(e) => setPayFile(e.target.files[0])}
                               style={{ fontSize: 12, maxWidth: 170 }} />
                        <button onClick={() => recordPayment(line)}
                                disabled={!payRef.trim()}
                                style={{ ...buttonStyle, padding: "3px 10px",
                                         fontSize: 12 }}>
                          Save
                        </button>
                      </span>
                    ) : "—"}
                  </td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {line.amount_cash
                      ? Number(line.amount_cash).toLocaleString() : ""}</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {line.amount_credit
                      ? Number(line.amount_credit).toLocaleString() : ""}</td>
                  <td style={{ ...td, textAlign: "right", fontWeight: 600 }}>
                    {(num(line.amount_cash) + num(line.amount_credit))
                      .toLocaleString()}</td>
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
                  {doc.doc_type === "PO" && (<>
                    <td style={td}>{line.qty_required}</td>
                    <td style={td}>{line.rate}</td>
                    <td style={td}>
                      {Number(line.amount || 0).toLocaleString()}</td>
                  </>)}
                </>)}
                {!isPR && <td style={td}>{line.remarks}</td>}
              </tr>
            ))}
          </tbody>
          {isPR && (() => {
            const cash = doc.lines.reduce((a, l) => a + num(l.amount_cash), 0);
            const credit = doc.lines.reduce(
              (a, l) => a + num(l.amount_credit), 0);
            const untaxed = cash + credit;
            const gst = untaxed * gstRate / 100;
            const fmt = (v) => v.toLocaleString(undefined,
              { maximumFractionDigits: 2 });
            const right = { ...td, textAlign: "right", borderTop: "none" };
            const label = { ...td, textAlign: "right", color: "#5a6b78",
                            borderTop: "none" };
            const bold = { fontWeight: 700,
                           borderTop: "1.5px solid var(--sp-navy)" };
            return (
              <tfoot>
                <tr>
                  <td colSpan={4} style={label}>Untaxed Amount</td>
                  <td style={right}>{fmt(cash)}</td>
                  <td style={right}>{fmt(credit)}</td>
                  <td style={{ ...right, fontWeight: 600 }}>{fmt(untaxed)}</td>
                </tr>
                <tr>
                  <td colSpan={4} style={label}>GST ({gstRate}%)</td>
                  <td style={right} />
                  <td style={right} />
                  <td style={right}>{fmt(gst)}</td>
                </tr>
                <tr>
                  <td colSpan={4} style={{ ...label, ...bold,
                                           color: "var(--sp-navy)" }}>
                    Total incl. GST</td>
                  <td style={{ ...right, ...bold }} />
                  <td style={{ ...right, ...bold }} />
                  <td style={{ ...right, ...bold }}>MVR {fmt(untaxed + gst)}</td>
                </tr>
              </tfoot>
            );
          })()}
        </table>
      </div>

      {doc.doc_type === "PR" && (
        <QuotationsSummary doc={doc} me={me}
                           onOpenWorkspace={() => onOpenMatch(doc)} />
      )}

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
