import { useCallback, useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { SectionTitle, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

function num(v) {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : 0;
}

const emptyLine = { supplier_desc: "", unit: "", qty: "", rate: "",
                    mr_line: "", awarded: false, remarks: "" };

function QuoteLinesEditor({ lines, setLines, mrOptions }) {
  const setLine = (i, patch) =>
    setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={th}>Supplier's description (verbatim)</th>
          <th style={th}>Unit</th><th style={th}>Qty</th>
          <th style={th}>Rate</th><th style={th}>Amount</th>
          <th style={th}>Matches MR line</th><th style={th}>Award</th><th />
        </tr></thead>
        <tbody>
          {lines.map((line, i) => (
            <tr key={i}>
              <td style={{ padding: 3, minWidth: 200 }}>
                <input value={line.supplier_desc}
                       onChange={(e) => setLine(i, { supplier_desc:
                                                     e.target.value })}
                       style={inputStyle} />
              </td>
              <td style={{ padding: 3 }}>
                <input value={line.unit || ""}
                       style={{ ...inputStyle, width: 55 }}
                       onChange={(e) => setLine(i, { unit: e.target.value })} />
              </td>
              <td style={{ padding: 3 }}>
                <input type="number" value={line.qty ?? ""}
                       style={{ ...inputStyle, width: 75 }}
                       onChange={(e) => setLine(i, { qty: e.target.value })} />
              </td>
              <td style={{ padding: 3 }}>
                <input type="number" value={line.rate ?? ""}
                       style={{ ...inputStyle, width: 85 }}
                       onChange={(e) => setLine(i, { rate: e.target.value })} />
              </td>
              <td style={{ padding: 3, fontSize: 13, textAlign: "right" }}>
                {(num(line.qty) * num(line.rate)).toLocaleString()}
              </td>
              <td style={{ padding: 3 }}>
                <select value={line.mr_line || ""}
                        onChange={(e) => setLine(i, { mr_line:
                                                      e.target.value || null })}
                        style={{ ...inputStyle, width: 190,
                                 background: line.mr_line ? "#effaf1"
                                                          : "#fdeceb" }}>
                  <option value="">— unmatched —</option>
                  {mrOptions.map((o) => (
                    <option key={o.mr_line_id} value={o.mr_line_id}>
                      {o.mr_ref}: {o.description}
                    </option>
                  ))}
                </select>
              </td>
              <td style={{ padding: 3, textAlign: "center" }}>
                <input type="checkbox" checked={!!line.awarded}
                       onChange={(e) => setLine(i, { awarded:
                                                     e.target.checked })} />
              </td>
              <td style={{ width: 30 }}>
                <button onClick={() => setLines(lines.filter((_, j) => j !== i))}
                        style={{ ...ghostButton, padding: "2px 8px",
                                 color: "#c0392b" }}>×</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button onClick={() => setLines([...lines, { ...emptyLine }])}
              style={{ ...ghostButton, padding: "4px 12px", marginTop: 6 }}>
        + Add quote line
      </button>
    </div>
  );
}

function CoverageBanner({ coverage }) {
  if (!coverage) return null;
  const clean = coverage.uncovered.length === 0 &&
                coverage.unawarded.length === 0;
  return (
    <div style={{ borderRadius: 8, padding: "10px 14px", marginBottom: 10,
                  fontSize: 13, background: clean ? "#effaf1" : "#fdeceb" }}>
      {clean ? "✓ Every MR line is quoted and awarded." : (<>
        {coverage.uncovered.length > 0 && (
          <div><strong>Not quoted:</strong> {coverage.uncovered.join(", ")}</div>
        )}
        {coverage.unawarded.length > 0 && (
          <div><strong>Quoted but not awarded:</strong>{" "}
            {coverage.unawarded.join(", ")}</div>
        )}
      </>)}
    </div>
  );
}

function useQuoteData(docRef) {
  const [quotations, setQuotations] = useState([]);
  const [coverage, setCoverage] = useState(null);
  const load = useCallback(() => {
    api(`/pr/${docRef}/quotations`).then(setQuotations);
    api(`/pr/${docRef}/coverage`).then(setCoverage);
  }, [docRef]);
  useEffect(load, [load]);
  return { quotations, coverage, load };
}

// Compact block shown on the PR page itself
export function QuotationsSummary({ doc, me, onOpenWorkspace }) {
  const { quotations, coverage } = useQuoteData(doc.ref);
  const canEdit = ["HO_PURCHASING", "ADMIN"].includes(me.role) &&
    ["DRAFT", "SUBMITTED"].includes(doc.status);

  return (
    <div style={{ marginTop: 8 }}>
      <SectionTitle>Quotations &amp; MR coverage</SectionTitle>
      <CoverageBanner coverage={coverage} />
      {quotations.map((q) => {
        const matched = q.lines.filter((l) => l.mr_line).length;
        return (
          <div key={q.id}
               style={{ display: "flex", gap: 12, alignItems: "baseline",
                        padding: "6px 2px", flexWrap: "wrap",
                        borderTop: "1px solid var(--sp-border)" }}>
            <strong style={{ color: "var(--sp-navy)" }}>{q.supplier_name}</strong>
            <span style={{ fontSize: 12, color: "#5a6b78" }}>
              {q.quote_ref}{q.payment_terms && ` · ${q.payment_terms}`} ·
              MVR {Number(q.total).toLocaleString()} ·
              {" "}{matched}/{q.lines.length} lines matched ·
              {" "}{q.lines.filter((l) => l.awarded).length} awarded
            </span>
            {q.file_url && (
              <a href={q.file_url} target="_blank" rel="noreferrer"
                 style={{ fontSize: 12 }}>quotation file</a>
            )}
          </div>
        );
      })}
      <div style={{ marginTop: 10 }}>
        <button onClick={onOpenWorkspace} style={buttonStyle}>
          {canEdit ? "Open matching workspace →" : "View quotations →"}
        </button>
      </div>
    </div>
  );
}

// Full-page workspace: capture quotes (file upload = auto-extract), match, award
export function MatchingWorkspace({ doc, me, onClose, onChanged }) {
  const { quotations, coverage, load } = useQuoteData(doc.ref);
  const [suppliers, setSuppliers] = useState([]);
  const [adding, setAdding] = useState(false);
  const [newSupplier, setNewSupplier] = useState("");
  const [newRef, setNewRef] = useState("");
  const [newTerms, setNewTerms] = useState("Cash");
  const [newGst, setNewGst] = useState(true);
  const [newFile, setNewFile] = useState(null);
  const [newLines, setNewLines] = useState([]);
  const [notice, setNotice] = useState(null);
  const [editing, setEditing] = useState({});
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/suppliers").then(setSuppliers);
  }, []);

  const canEdit = ["HO_PURCHASING", "ADMIN"].includes(me.role) &&
    ["DRAFT", "SUBMITTED"].includes(doc.status);
  const mrOptions = coverage?.rows || [];

  async function addQuotation() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const q = await api(`/pr/${doc.ref}/quotations`, {
        method: "POST",
        body: { supplier: +newSupplier, quote_ref: newRef,
                payment_terms: newTerms, gst_applicable: newGst,
                lines: newLines.filter((l) => l.supplier_desc) },
      });
      if (newFile) {
        const fd = new FormData();
        fd.append("file", newFile);
        const res = await apiUpload(`/quotations/${q.id}/file`, fd);
        setNotice(res.extracted
          ? `✓ ${res.extracted} line item(s) captured automatically from the `
            + "file — review, match and award them below."
          : "File attached. No line items could be read automatically "
            + "(scanned copy?) — add the lines below manually.");
      }
      setAdding(false);
      setNewSupplier("");
      setNewRef("");
      setNewTerms("Cash");
      setNewGst(true);
      setNewFile(null);
      setNewLines([]);
      load();
      onChanged?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function saveQuotation(q) {
    setError(null);
    try {
      await api(`/quotations/${q.id}`, { method: "PATCH",
                                         body: { lines: editing[q.id] } });
      setEditing((s) => { const n = { ...s }; delete n[q.id]; return n; });
      load();
      onChanged?.();
    } catch (e) {
      setError(e.message);
    }
  }

  async function toggleGst(q) {
    setError(null);
    try {
      await api(`/quotations/${q.id}`, { method: "PATCH",
        body: { gst_applicable: !q.gst_applicable } });
      load();
      onChanged?.();
    } catch (e) { setError(e.message); }
  }

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
          Quotation matching — {doc.ref}
          <span style={{ color: "#5a6b78", fontSize: 14 }}>
            {" "}· {doc.site_code}</span>
        </h2>
        <button onClick={onClose} style={ghostButton}>← Back to PR</button>
      </div>
      <p style={{ fontSize: 13, color: "#5a6b78", margin: "6px 0 14px" }}>
        Capture each supplier's quotation, match their lines to the MR items,
        and tick the winning (awarded) lines. POs are generated per supplier
        on Director approval.
      </p>

      <CoverageBanner coverage={coverage} />
      {notice && <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>}
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {quotations.map((q) => {
        const lines = editing[q.id] ?? q.lines.map((l) => ({
          supplier_desc: l.supplier_desc, unit: l.unit, qty: l.qty,
          rate: l.rate, mr_line: l.mr_line, awarded: l.awarded,
          remarks: l.remarks,
        }));
        const isEditing = editing[q.id] !== undefined;
        return (
          <div key={q.id} style={{ border: "1px solid var(--sp-border)",
                                   borderRadius: 8, padding: 14,
                                   marginBottom: 10 }}>
            <div style={{ display: "flex", gap: 12, alignItems: "baseline",
                          flexWrap: "wrap" }}>
              <strong style={{ color: "var(--sp-navy)" }}>
                {q.supplier_name}</strong>
              <span style={{ fontSize: 12, color: "#5a6b78" }}>
                {q.quote_ref}{q.payment_terms && ` · ${q.payment_terms}`} ·
                net MVR {Number(q.total).toLocaleString()}
              </span>
              <label style={{ fontSize: 12, display: "flex", gap: 4,
                              alignItems: "center",
                              color: q.gst_applicable ? "var(--sp-navy)"
                                : "#8a97a1", cursor: canEdit ? "pointer"
                                : "default" }}
                     title="Vendor is GST-registered — adds GST at the company rate">
                <input type="checkbox" checked={!!q.gst_applicable}
                       disabled={!canEdit}
                       onChange={() => toggleGst(q)} />
                GST</label>
              {q.file_url && (
                <a href={q.file_url} target="_blank" rel="noreferrer"
                   style={{ fontSize: 12 }}>quotation file</a>
              )}
              {canEdit && !isEditing && (
                <button onClick={() => setEditing((s) => ({ ...s,
                                                            [q.id]: lines }))}
                        style={{ ...ghostButton, marginLeft: "auto",
                                 padding: "3px 12px", fontSize: 12 }}>
                  Edit / match lines
                </button>
              )}
              {isEditing && (
                <button onClick={() => saveQuotation(q)}
                        style={{ ...buttonStyle, marginLeft: "auto",
                                 padding: "3px 12px", fontSize: 12 }}>
                  Save matches
                </button>
              )}
            </div>
            {isEditing ? (
              <QuoteLinesEditor lines={editing[q.id]}
                                setLines={(ls) => setEditing((s) =>
                                  ({ ...s, [q.id]: ls }))}
                                mrOptions={mrOptions} />
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse",
                              marginTop: 8 }}>
                <tbody>
                  {q.lines.map((l) => (
                    <tr key={l.id}>
                      <td style={td}>{l.supplier_desc}</td>
                      <td style={td}>{l.qty} {l.unit}</td>
                      <td style={td}>@ {l.rate}</td>
                      <td style={td}>{Number(l.amount || 0).toLocaleString()}</td>
                      <td style={{ ...td, color: l.mr_line ? "#1a7f37"
                                                           : "#c0392b" }}>
                        {l.mr_line ? `→ ${l.mr_line_desc}` : "unmatched"}
                      </td>
                      <td style={td}>{l.awarded ? "★ awarded" : ""}</td>
                    </tr>
                  ))}
                  {q.lines.length === 0 && (
                    <tr><td style={td} colSpan={6}>
                      No lines yet — click "Edit / match lines" to add them.
                    </td></tr>
                  )}
                </tbody>
              </table>
            )}
          </div>
        );
      })}

      {canEdit && !adding && (
        <button onClick={() => setAdding(true)} style={buttonStyle}>
          + Add quotation
        </button>
      )}

      {adding && (
        <div style={{ border: "1px dashed var(--sp-border)", borderRadius: 8,
                      padding: 14 }}>
          <div style={{ display: "flex", gap: 10, marginBottom: 8,
                        flexWrap: "wrap", alignItems: "center" }}>
            <select value={newSupplier}
                    onChange={(e) => setNewSupplier(e.target.value)}
                    style={{ ...inputStyle, width: 240 }}>
              <option value="">Select supplier…</option>
              {suppliers.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
            <input placeholder="Quote ref" value={newRef}
                   onChange={(e) => setNewRef(e.target.value)}
                   style={{ ...inputStyle, width: 130 }} />
            <select value={newTerms}
                    onChange={(e) => setNewTerms(e.target.value)}
                    style={{ ...inputStyle, width: 110 }}>
              <option>Cash</option>
              <option>Credit</option>
            </select>
            <label style={{ fontSize: 13, display: "flex", gap: 4,
                            alignItems: "center" }}
                   title="Vendor is GST-registered — adds GST at the company rate">
              <input type="checkbox" checked={newGst}
                     onChange={(e) => setNewGst(e.target.checked)} />
              GST-registered</label>
            <label style={{ fontSize: 13 }}>
              Quotation file (PDF):{" "}
              <input type="file" accept=".pdf,image/*"
                     onChange={(e) => setNewFile(e.target.files[0])} />
            </label>
          </div>
          <p style={{ fontSize: 12, color: "#5a6b78", margin: "0 0 8px" }}>
            Upload a digital PDF and the line items are captured automatically
            for matching. Scanned copies attach as reference — enter their
            lines manually.
          </p>
          {!newFile && (
            <QuoteLinesEditor lines={newLines} setLines={setNewLines}
                              mrOptions={mrOptions} />
          )}
          <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
            <button onClick={addQuotation} disabled={!newSupplier || busy}
                    style={buttonStyle}>
              {busy ? "Saving…" : "Save quotation"}
            </button>
            <button onClick={() => setAdding(false)} style={ghostButton}>
              Cancel</button>
          </div>
        </div>
      )}
    </section>
  );
}
