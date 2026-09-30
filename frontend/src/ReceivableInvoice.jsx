// One receivable opened up (owner 2026-09-30): Finance had the ledger line in
// Receivables and on the statement but no way to see the invoice behind it
// or print it. InvoiceModal shows what was billed, what has come in and the
// documents; InvoicesTab is the register of every invoice; InvoiceRef is the
// clickable number used wherever an invoice is listed.
import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, card, ghostButton, td, th } from "./ui.jsx";

const money = (v) => (v == null ? "—" : Number(v).toLocaleString("en-US",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const mono = { fontFamily: "var(--font-mono)" };
const fmtDate = (s) => (s ? new Date(s).toLocaleDateString("en-GB",
  { day: "2-digit", month: "short", year: "numeric" }) : "—");
const TONE = { PAID: "ok", OVERDUE: "alert", CURRENT: "info" };
const LABEL = { PAID: "Paid", OVERDUE: "Overdue", CURRENT: "Not yet due" };
const num = { ...td, textAlign: "right", ...mono, whiteSpace: "nowrap" };
const linkBtn = { background: "none", border: 0, padding: 0, cursor: "pointer",
  font: "inherit", color: "var(--navy)", textDecoration: "underline" };

// What identifies an invoice row, whichever list it came from.
export const invKey = (r) => (r.claim_id
  ? { source: "claim", id: r.claim_id }
  : r.manual_invoice_id ? { source: "manual", id: r.manual_invoice_id } : null);

// The invoice number as a link that opens the detail, with its PDF beside it.
export function InvoiceRef({ row, label, onOpen }) {
  const key = invKey(row);
  const text = label || row.invoice_no || row.ref || "—";
  if (!key) return <span style={mono}>{text}</span>;
  const doc = row.pdf_url || row.attachment_url;
  return (
    <span style={{ whiteSpace: "nowrap" }}>
      <button style={{ ...linkBtn, ...mono }} title="Open the invoice"
              onClick={(e) => { e.stopPropagation(); onOpen(key); }}>{text}</button>
      {doc && (
        <a href={doc} target="_blank" rel="noreferrer" title="Invoice PDF"
           onClick={(e) => e.stopPropagation()}
           style={{ marginLeft: 8, fontSize: 12 }}>PDF</a>
      )}
    </span>
  );
}

export function InvoiceModal({ invoice, onClose }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    setD(null); setError(null);
    api(`/receivables/invoices/${invoice.source}/${invoice.id}`)
      .then(setD).catch((e) => setError(e.message));
  }, [invoice.source, invoice.id]);
  useEffect(() => {
    const esc = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const row = (l, v, strong) => (
    <tr key={l}>
      <td style={{ ...td, fontWeight: strong ? 700 : 400 }}>{l}</td>
      <td style={{ ...num, fontWeight: strong ? 700 : 400 }}>{v}</td>
    </tr>
  );
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 60, overflow: "auto",
                  background: "rgba(15,32,45,.35)", padding: "5vh 16px" }}
         onClick={onClose}>
      <div style={{ ...card, maxWidth: 860, margin: "0 auto" }}
           onClick={(e) => e.stopPropagation()}>
        {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
        {!d && !error && <p style={{ color: "var(--muted)" }}>Loading…</p>}
        {d && (
          <>
            <div style={{ display: "flex", gap: 12, alignItems: "flex-start",
                          flexWrap: "wrap" }}>
              <div style={{ flex: 1, minWidth: 240 }}>
                <div style={{ fontSize: 12, color: "var(--muted)",
                              textTransform: "uppercase", letterSpacing: ".05em" }}>
                  {d.type_label}</div>
                <h2 style={{ margin: "2px 0", color: "var(--navy)", ...mono }}>
                  {d.invoice_no}</h2>
                <div style={{ fontSize: 13.5 }}>
                  <strong>{d.client}</strong> · {d.project_code} {d.project_title}
                </div>
              </div>
              <Chip tone={TONE[d.status]}>{LABEL[d.status]}
                {d.status === "OVERDUE" ? ` · ${d.days_overdue} days` : ""}</Chip>
              <button onClick={onClose} style={ghostButton}>Close</button>
            </div>

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                          margin: "14px 0" }}>
              {d.pdf_url && (
                <a href={d.pdf_url} target="_blank" rel="noreferrer">
                  <Btn>⬇ Tax invoice PDF</Btn></a>
              )}
              {d.ipc_url && (
                <a href={d.ipc_url} target="_blank" rel="noreferrer">
                  <Btn variant="secondary">⬇ Payment certificate
                    {d.ipc_ref ? ` (${d.ipc_ref})` : ""}</Btn></a>
              )}
              {d.attachment_url && (
                <a href={d.attachment_url} target="_blank" rel="noreferrer">
                  <Btn variant="secondary">⬇ Scanned invoice</Btn></a>
              )}
              {!d.pdf_url && !d.attachment_url && (
                <span style={{ fontSize: 13, color: "var(--muted)",
                               alignSelf: "center" }}>
                  A historical invoice entered by hand — no document was
                  attached to it.</span>
              )}
            </div>

            <div style={{ display: "grid", gap: 18,
                          gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
              <div>
                <h3 style={{ margin: "0 0 6px", fontSize: 14 }}>Invoice</h3>
                <table style={{ width: "100%", borderCollapse: "collapse",
                                fontSize: 13 }}>
                  <tbody>
                    <tr><td style={td}>Invoice date</td>
                        <td style={{ ...td, textAlign: "right" }}>{fmtDate(d.invoice_date)}</td></tr>
                    <tr><td style={td}>Due date</td>
                        <td style={{ ...td, textAlign: "right" }}>{fmtDate(d.due_date)}</td></tr>
                    {d.claim_ref && (
                      <tr><td style={td}>Claim</td>
                          <td style={{ ...td, textAlign: "right", ...mono }}>{d.claim_ref}</td></tr>
                    )}
                    {row(`Net (${d.currency})`, money(d.net_due))}
                    {row(`GST ${Number(d.gst_pct || 0)}%`, money(d.gst))}
                    {d.deductions.map((x) => row(`Less: ${x.label}`,
                      `(${money(x.amount)})`))}
                    {row(`Invoice total (${d.currency})`, money(d.amount), true)}
                  </tbody>
                </table>
                {d.description && (
                  <p style={{ fontSize: 13, margin: "8px 0 0" }}>{d.description}</p>
                )}
                {(d.prepared_by || d.certified_by) && (
                  <p style={{ fontSize: 12, color: "var(--muted)", margin: "8px 0 0" }}>
                    {d.prepared_by && `Prepared by ${d.prepared_by}`}
                    {d.certified_by && ` · certified by ${d.certified_by}`
                      + (d.certified_at ? ` on ${fmtDate(d.certified_at)}` : "")}
                  </p>
                )}
                {d.superseded_by && (
                  <p style={{ fontSize: 12.5, color: "var(--amber-fg)" }}>
                    Taken over by claim {d.superseded_by} — no longer owed on
                    its own.</p>
                )}
              </div>
              <div>
                <h3 style={{ margin: "0 0 6px", fontSize: 14 }}>Received against it</h3>
                <table style={{ width: "100%", borderCollapse: "collapse",
                                fontSize: 13 }}>
                  <tbody>
                    {d.receipts.length === 0 && (
                      <tr><td style={{ ...td, color: "var(--muted)" }} colSpan={2}>
                        Nothing received yet.</td></tr>
                    )}
                    {d.receipts.map((r, i) => (
                      <tr key={i}>
                        <td style={td}>{fmtDate(r.date)}
                          {r.reference && <span style={{ color: "var(--muted)" }}> · {r.reference}</span>}
                          {r.receipt_id && (
                            <a href={`/api/v1/receivables/receipts/${r.receipt_id}.pdf`}
                               target="_blank" rel="noreferrer"
                               style={{ marginLeft: 8, fontSize: 12, ...mono }}>
                              {r.receipt_no}</a>
                          )}
                        </td>
                        <td style={{ ...num, color: "var(--green-fg)" }}>{money(r.amount)}</td>
                      </tr>
                    ))}
                    {row("Total received", money(d.received))}
                    <tr>
                      <td style={{ ...td, fontWeight: 700 }}>Outstanding</td>
                      <td style={{ ...num, fontWeight: 800,
                        color: Number(d.outstanding) > 0 ? "var(--red-fg)" : "var(--green-fg)" }}>
                        {money(d.outstanding)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {d.summary && d.summary.length > 0 && (
              <>
                <h3 style={{ margin: "18px 0 6px", fontSize: 14 }}>
                  Payment summary — as printed on the invoice</h3>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse",
                                  fontSize: 12.5 }}>
                    <thead><tr>
                      <th style={{ ...th, textAlign: "left" }}>Item</th>
                      <th style={{ ...th, textAlign: "right" }}>Contract</th>
                      <th style={{ ...th, textAlign: "right" }}>Cumulative</th>
                      <th style={{ ...th, textAlign: "right" }}>Previous</th>
                      <th style={{ ...th, textAlign: "right" }}>This invoice</th>
                    </tr></thead>
                    <tbody>
                      {d.summary.map((s, i) => {
                        const b = /total|net/.test(s.style || "") ? 700 : 400;
                        return (
                          <tr key={i}>
                            <td style={{ ...td, fontWeight: b }}>{s.label}</td>
                            <td style={{ ...num, fontWeight: b }}>{s.contract}</td>
                            <td style={{ ...num, fontWeight: b }}>{s.cumulative}</td>
                            <td style={{ ...num, fontWeight: b }}>{s.previous}</td>
                            <td style={{ ...num, fontWeight: b }}>{s.present}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {d.lines.length > 0 && (
              <>
                <h3 style={{ margin: "18px 0 6px", fontSize: 14 }}>Lines</h3>
                <table style={{ width: "100%", borderCollapse: "collapse",
                                fontSize: 13 }}>
                  <thead><tr>
                    <th style={{ ...th, textAlign: "left" }}>Description</th>
                    <th style={{ ...th, textAlign: "right" }}>Qty</th>
                    <th style={{ ...th, textAlign: "right" }}>Unit price</th>
                    <th style={{ ...th, textAlign: "right" }}>Amount</th>
                  </tr></thead>
                  <tbody>{d.lines.map((l, i) => (
                    <tr key={i}><td style={td}>{l.description}</td>
                      <td style={num}>{Number(l.quantity)}</td>
                      <td style={num}>{money(l.unit_price)}</td>
                      <td style={num}>{money(l.amount)}</td></tr>
                  ))}</tbody>
                </table>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// Every invoice — certified claims and manual ones — in one register.
export function InvoicesTab({ onOpen }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [only, setOnly] = useState(true);       // outstanding only
  const [q, setQ] = useState("");
  useEffect(() => {
    setRows(null);
    api(`/receivables/invoices${only ? "?outstanding=1" : ""}`)
      .then((r) => setRows(r.invoices)).catch((e) => setError(e.message));
  }, [only]);
  if (error) return <div style={card}>{error}</div>;
  const needle = q.trim().toLowerCase();
  const shown = (rows || []).filter((r) => !needle
    || `${r.invoice_no} ${r.ref} ${r.project_code} ${r.project_title}`
      .toLowerCase().includes(needle));
  return (
    <>
      <div style={{ display: "flex", gap: 12, alignItems: "center",
                    flexWrap: "wrap", marginBottom: 12 }}>
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Invoice no. or project…"
               style={{ padding: "6px 10px", border: "1px solid var(--line)",
                        borderRadius: 6, fontSize: 13, width: 230 }} />
        <label style={{ fontSize: 13, display: "flex", gap: 6,
                        alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={only}
                 onChange={(e) => setOnly(e.target.checked)} />
          Outstanding only</label>
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
          {rows ? `${shown.length} invoice${shown.length === 1 ? "" : "s"}` : ""}
          {" "}· click an invoice number to open it</span>
      </div>
      {!rows ? <div style={card}>Loading…</div> : shown.length === 0 ? (
        <div style={card}>{only ? "No outstanding invoices." : "No invoices yet."}</div>
      ) : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead><tr>
              <th style={{ ...th, textAlign: "left" }}>Invoice</th>
              <th style={{ ...th, textAlign: "left" }}>Project</th>
              <th style={{ ...th, textAlign: "left" }}>Date</th>
              <th style={{ ...th, textAlign: "left" }}>Due</th>
              <th style={{ ...th, textAlign: "right" }}>Amount</th>
              <th style={{ ...th, textAlign: "right" }}>Received</th>
              <th style={{ ...th, textAlign: "right" }}>Outstanding</th>
              <th style={{ ...th, textAlign: "left" }}>Status</th>
            </tr></thead>
            <tbody>
              {shown.map((r) => (
                <tr key={`${r.source}-${r.claim_id || r.manual_invoice_id}`}
                    style={{ cursor: "pointer" }}
                    onClick={() => onOpen(invKey(r))}>
                  <td style={td}><InvoiceRef row={r} onOpen={onOpen} />
                    {r.source === "CLAIM" && r.ref !== r.invoice_no && (
                      <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{r.ref}</div>
                    )}
                  </td>
                  <td style={td}>{r.project_code}
                    <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{r.project_title}</div></td>
                  <td style={{ ...td, whiteSpace: "nowrap" }}>{fmtDate(r.invoice_date)}</td>
                  <td style={{ ...td, whiteSpace: "nowrap" }}>{fmtDate(r.due_date)}</td>
                  <td style={num}>{r.currency} {money(r.amount)}</td>
                  <td style={num}>{Number(r.received) ? money(r.received) : "—"}</td>
                  <td style={{ ...num, fontWeight: 700 }}>
                    {Number(r.outstanding) > 0 ? money(r.outstanding) : "—"}</td>
                  <td style={td}><Chip tone={TONE[r.status]}>{LABEL[r.status]}
                    {r.status === "OVERDUE" ? ` · ${r.days_overdue} d` : ""}</Chip></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
