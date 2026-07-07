import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { SectionTitle, buttonStyle, ghostButton, inputStyle, td, th }
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
                <input value={line.unit || ""} style={{ ...inputStyle, width: 55 }}
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

export default function QuotationsPanel({ doc, me, onChanged }) {
  const [quotations, setQuotations] = useState([]);
  const [coverage, setCoverage] = useState(null);
  const [suppliers, setSuppliers] = useState([]);
  const [adding, setAdding] = useState(false);
  const [newSupplier, setNewSupplier] = useState("");
  const [newRef, setNewRef] = useState("");
  const [newLines, setNewLines] = useState([{ ...emptyLine }]);
  const [editing, setEditing] = useState({}); // quotation id -> lines state
  const [error, setError] = useState(null);

  const canEdit = ["HO_PURCHASING", "ADMIN"].includes(me.role) &&
    ["DRAFT", "SUBMITTED"].includes(doc.status);

  const load = useCallback(() => {
    api(`/pr/${doc.ref}/quotations`).then(setQuotations);
    api(`/pr/${doc.ref}/coverage`).then(setCoverage);
    api("/suppliers").then(setSuppliers);
  }, [doc.ref]);

  useEffect(load, [load]);

  const mrOptions = coverage?.rows || [];

  async function addQuotation() {
    setError(null);
    try {
      await api(`/pr/${doc.ref}/quotations`, {
        method: "POST",
        body: { supplier: +newSupplier, quote_ref: newRef,
                lines: newLines.filter((l) => l.supplier_desc) },
      });
      setAdding(false);
      setNewLines([{ ...emptyLine }]);
      setNewRef("");
      load();
      onChanged?.();
    } catch (e) {
      setError(e.message);
    }
  }

  async function saveQuotation(q) {
    setError(null);
    try {
      await api(`/quotations/${q.id}`, {
        method: "PATCH",
        body: { lines: editing[q.id] },
      });
      setEditing((s) => { const n = { ...s }; delete n[q.id]; return n; });
      load();
      onChanged?.();
    } catch (e) {
      setError(e.message);
    }
  }

  async function syncVendors() {
    setError(null);
    try {
      await api(`/pr/${doc.ref}/sync-vendor-rows`, { method: "POST" });
      onChanged?.();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div style={{ marginTop: 8 }}>
      <SectionTitle>Quotations &amp; MR coverage</SectionTitle>

      {coverage && (
        <div style={{ borderRadius: 8, padding: "10px 14px", marginBottom: 10,
                      fontSize: 13,
                      background: coverage.uncovered.length ||
                                  coverage.unawarded.length
                        ? "#fdeceb" : "#effaf1" }}>
          {coverage.uncovered.length === 0 && coverage.unawarded.length === 0
            ? "✓ Every MR line is quoted and awarded."
            : (<>
                {coverage.uncovered.length > 0 && (
                  <div><strong>Not quoted:</strong>{" "}
                    {coverage.uncovered.join(", ")}</div>
                )}
                {coverage.unawarded.length > 0 && (
                  <div><strong>Quoted but not awarded:</strong>{" "}
                    {coverage.unawarded.join(", ")}</div>
                )}
              </>)}
        </div>
      )}

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
                {q.quote_ref} {q.payment_terms && `· ${q.payment_terms}`} ·
                total MVR {Number(q.total).toLocaleString()}
              </span>
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
                </tbody>
              </table>
            )}
          </div>
        );
      })}

      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {canEdit && !adding && (
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={() => setAdding(true)} style={buttonStyle}>
            + Add quotation
          </button>
          {doc.status === "DRAFT" && quotations.length > 0 && (
            <button onClick={syncVendors} style={ghostButton}>
              Rebuild vendor summary from quotes
            </button>
          )}
        </div>
      )}

      {adding && (
        <div style={{ border: "1px dashed var(--sp-border)", borderRadius: 8,
                      padding: 14 }}>
          <div style={{ display: "flex", gap: 10, marginBottom: 8 }}>
            <select value={newSupplier}
                    onChange={(e) => setNewSupplier(e.target.value)}
                    style={{ ...inputStyle, width: 260 }}>
              <option value="">Select supplier…</option>
              {suppliers.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
            <input placeholder="Quote ref" value={newRef}
                   onChange={(e) => setNewRef(e.target.value)}
                   style={{ ...inputStyle, width: 140 }} />
          </div>
          <QuoteLinesEditor lines={newLines} setLines={setNewLines}
                            mrOptions={mrOptions} />
          <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
            <button onClick={addQuotation} disabled={!newSupplier}
                    style={buttonStyle}>Save quotation</button>
            <button onClick={() => setAdding(false)} style={ghostButton}>
              Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
