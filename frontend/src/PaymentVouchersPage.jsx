import { useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, RefStamp, StatusChip, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

// Payment Voucher workspace (M6d). Finance batches Director-approved
// requisitions (PR / PYR) onto a voucher; a signatory approves the batch
// or queries individual lines. Approval is the commitment point. After
// approval Finance records the actual disbursements (transfer slip / cheque)
// per line from here, reusing the per-document payment endpoints.
// Import orders (IPR) authorise on the voucher but are paid on the Import
// Payments page (milestones), so they're not settled here.

const money = (v) => v == null ? "—"
  : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2 });

const mono = { fontFamily: "var(--font-mono)" };
const TABS = [["all", "All"], ["DRAFT", "Draft"],
              ["SUBMITTED", "Awaiting signatory"], ["APPROVED", "Approved"]];

// A voucher line's human description varies by source document type
function lineDetail(l) {
  if (l.doc_type === "IPR") return "Overseas order — paid on Import Payments";
  if (l.doc_type === "PR") return "Procurement — pay each vendor";
  return [l.payee, l.purpose].filter(Boolean).join(" · ");
}

export default function PaymentVouchersPage({ me, onOpenDoc }) {
  const isFinance = ["FINANCE", "ADMIN"].includes(me.role);
  const isSignatory = ["SIGNATORY", "ADMIN"].includes(me.role);

  const [awaiting, setAwaiting] = useState([]);
  const [vouchers, setVouchers] = useState([]);
  const [picked, setPicked] = useState({});     // source ref -> bool
  const [open, setOpen] = useState(null);        // expanded voucher ref
  const [tab, setTab] = useState("all");
  const [queries, setQueries] = useState({});    // line_id -> bool
  const [note, setNote] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  // Inline payment form: one active target at a time
  const [payKey, setPayKey] = useState(null);    // "pyr:REF" | "pr:REF:LINEID"
  const [payRef, setPayRef] = useState("");
  const [payAmount, setPayAmount] = useState("");
  const [payVariance, setPayVariance] = useState("");
  const [paySlip, setPaySlip] = useState(null);

  const reload = () => {
    setError(null);
    if (isFinance) {
      api("/finance/awaiting-voucher").then(setAwaiting)
        .catch((e) => setError(e.message));
    }
    api("/payment-vouchers").then(setVouchers)
      .catch((e) => setError(e.message));
  };
  useEffect(reload, []);

  const pickedRefs = Object.keys(picked).filter((r) => picked[r]);
  const pickedTotal = awaiting
    .filter((d) => picked[d.ref])
    .reduce((s, d) => s + Number(d.amount || 0), 0);
  const shown = vouchers.filter((v) => tab === "all" || v.status === tab);

  const run = async (fn) => {
    setBusy(true); setError(null);
    try { await fn(); } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const createVoucher = () => run(async () => {
    await api("/payment-vouchers",
              { method: "POST", body: { source_refs: pickedRefs } });
    setPicked({}); reload();
  });

  const voucherAction = (ref, action, body) => run(async () => {
    await api(`/payment-vouchers/${ref}/actions/${action}`,
              { method: "POST", body: body || {} });
    setOpen(null); setQueries({}); setNote(""); reload();
  });

  const approve = (pv) => {
    const queried_ids = pv.lines
      .filter((l) => queries[l.line_id]).map((l) => l.line_id);
    if (queried_ids.length && !note.trim()) {
      setError("Add a note explaining the query before approving.");
      return;
    }
    voucherAction(pv.ref, "approve", { queried_ids, note });
  };

  const openVoucher = (ref) => {
    setOpen(open === ref ? null : ref);
    setQueries({}); setNote(""); setError(null); cancelPay();
  };

  // ---- payment recording (reuses the per-document endpoints) ----------
  const startPay = (key, amount) => {
    setPayKey(key); setPayRef(""); setPayVariance("");
    setPayAmount(amount != null ? String(amount) : ""); setPaySlip(null);
  };
  const cancelPay = () => {
    setPayKey(null); setPayRef(""); setPayAmount(""); setPayVariance("");
    setPaySlip(null);
  };

  const payPyr = (ref, requested) => run(async () => {
    if (!payRef.trim()) throw new Error("A payment reference is required.");
    const fd = new FormData();
    fd.append("amount_paid", payAmount || requested);
    fd.append("payment_ref", payRef);
    fd.append("variance_reason", payVariance);
    if (paySlip) fd.append("file", paySlip);
    await apiUpload(`/documents/${ref}/actions/pay`, fd);
    cancelPay(); reload();
  });

  const payVendor = (prRef, lineId) => run(async () => {
    if (!payRef.trim()) throw new Error("A payment reference is required.");
    const fd = new FormData();
    fd.append("line_id", lineId);
    fd.append("payment_ref", payRef);
    if (paySlip) fd.append("file", paySlip);
    await apiUpload(`/pr/${prRef}/vendor-payment`, fd);
    cancelPay(); reload();
  });

  const payFormFields = (opts = {}) => (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8,
                  alignItems: "center", marginTop: 8, background: "#fff",
                  border: "1px solid var(--line)", borderRadius: 8,
                  padding: 10 }}>
      {opts.amount && (
        <input type="number" value={payAmount}
               onChange={(e) => setPayAmount(e.target.value)}
               placeholder="Amount paid"
               style={{ ...inputStyle, width: 130 }} />
      )}
      <input value={payRef} onChange={(e) => setPayRef(e.target.value)}
             placeholder="Transfer / cheque ref"
             style={{ ...inputStyle, width: 180 }} />
      <label style={{ fontSize: 13, color: "var(--muted)" }}>
        Slip <input type="file"
                    onChange={(e) => setPaySlip(e.target.files[0])} /></label>
      {opts.amount && (
        <input value={payVariance}
               onChange={(e) => setPayVariance(e.target.value)}
               placeholder="Variance reason (if amount differs)"
               style={{ ...inputStyle, width: 230 }} />
      )}
      <Btn variant="primary" disabled={busy} onClick={opts.onSave}>
        Save payment</Btn>
      <button onClick={cancelPay} style={ghostButton}>Cancel</button>
    </div>
  );

  const heading = { margin: 0, color: "var(--navy)", fontSize: 16,
                    fontWeight: 700 };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 20 }}>
          Payment Vouchers</h2>
        <p style={{ color: "var(--muted)", fontSize: 13.5, margin: "4px 0 0" }}>
          {isSignatory && !isFinance
            ? "Approve a voucher to authorise every payment on it, or query a "
              + "line to send it back for review."
            : "Batch Director-approved requisitions, submit for a signatory to "
              + "approve, then record each payment with its slip."}
        </p>
      </div>

      {error && (
        <p style={{ color: "var(--red-fg)", fontSize: 13.5, margin: 0,
                    background: "var(--red-bg)", padding: "8px 12px",
                    borderRadius: 8 }}>{error}</p>
      )}

      {/* Finance: pick requisitions awaiting a voucher */}
      {isFinance && (
        <section style={{ ...card, margin: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12,
                        flexWrap: "wrap", marginBottom: 4 }}>
            <h3 style={heading}>Awaiting a voucher</h3>
            <span style={{ fontSize: 13, color: "var(--muted)" }}>
              {awaiting.length} requisition{awaiting.length === 1 ? "" : "s"}
            </span>
            {pickedRefs.length > 0 && (
              <span style={{ marginLeft: "auto", display: "flex", gap: 12,
                             alignItems: "center" }}>
                <span style={{ fontSize: 13.5, color: "var(--navy)" }}>
                  {pickedRefs.length} selected ·{" "}
                  <strong style={mono}>MVR {money(pickedTotal)}</strong>
                </span>
                <Btn variant="primary" disabled={busy}
                     onClick={createVoucher}>Create voucher</Btn>
              </span>
            )}
          </div>
          {awaiting.length === 0 ? (
            <p style={{ fontSize: 13.5, color: "var(--muted)", margin: 0 }}>
              Nothing awaiting a voucher right now.</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead><tr>
                  <th style={{ ...th, width: 34 }}></th>
                  <th style={th}>Ref</th><th style={th}>Site</th>
                  <th style={th}>Payee</th><th style={th}>Cost head</th>
                  <th style={{ ...th, textAlign: "right" }}>Amount (MVR)</th>
                </tr></thead>
                <tbody>
                  {awaiting.map((d) => (
                    <tr key={d.ref} style={{ background: picked[d.ref]
                      ? "var(--sky-soft)" : "transparent" }}>
                      <td style={{ ...td, textAlign: "center" }}>
                        <input type="checkbox" checked={!!picked[d.ref]}
                               onChange={(e) => setPicked(
                                 { ...picked, [d.ref]: e.target.checked })} />
                      </td>
                      <td style={td}>
                        <a href="#" onClick={(e) => { e.preventDefault();
                                                      onOpenDoc(d.ref); }}
                           style={{ textDecoration: "none" }}>
                          <RefStamp small>{d.ref}</RefStamp></a>
                      </td>
                      <td style={td}>{d.site_code}</td>
                      <td style={td}>{d.payee}</td>
                      <td style={td}>{d.cost_head}</td>
                      <td style={{ ...td, textAlign: "right", ...mono }}>
                        {money(d.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* Vouchers list + history tabs */}
      <section style={{ ...card, margin: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12,
                      flexWrap: "wrap", marginBottom: 12 }}>
          <h3 style={heading}>Vouchers</h3>
          <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
            {TABS.map(([key, label]) => (
              <button key={key} onClick={() => setTab(key)}
                      style={{ ...ghostButton, padding: "4px 14px",
                               fontSize: 13,
                               background: tab === key
                                 ? "var(--navy)" : "#fff",
                               color: tab === key ? "#fff" : "var(--navy)",
                               borderColor: tab === key
                                 ? "var(--navy)" : "var(--line)" }}>
                {label}</button>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {shown.map((pv) => {
            const isOpen = open === pv.ref;
            const canSubmit = isFinance && pv.status === "DRAFT";
            const canApprove = isSignatory && pv.status === "SUBMITTED";
            const canPay = isFinance && pv.status === "APPROVED";
            const payable = pv.lines.filter((l) => l.status === "APPROVED"
              && l.doc_type !== "IPR");
            return (
              <div key={pv.ref} style={{ border: "1px solid var(--line)",
                borderRadius: 10, overflow: "hidden",
                boxShadow: isOpen ? "0 2px 10px rgba(0,0,0,.06)" : "none" }}>
                {/* header */}
                <div style={{ display: "flex", alignItems: "center", gap: 12,
                              cursor: "pointer", flexWrap: "wrap",
                              padding: "12px 16px",
                              background: isOpen ? "var(--sky-soft)"
                                : "transparent" }}
                     onClick={() => openVoucher(pv.ref)}>
                  <span style={{ color: "var(--muted)", fontSize: 13,
                                 width: 14 }}>{isOpen ? "▾" : "▸"}</span>
                  <RefStamp>{pv.ref}</RefStamp>
                  <StatusChip status={pv.status} />
                  {pv.status === "APPROVED" && (
                    <span style={{ fontSize: 12.5, padding: "2px 10px",
                      borderRadius: 20, fontWeight: 600,
                      background: pv.settled ? "var(--green-bg)"
                        : "var(--amber-bg, #fff4e0)",
                      color: pv.settled ? "var(--green-fg)" : "#8a6d00" }}>
                      {pv.settled ? "✓ all paid"
                        : `${pv.paid_count}/${pv.approved_count} paid`}</span>
                  )}
                  <span style={{ marginLeft: "auto", fontSize: 17,
                                 fontWeight: 700, color: "var(--navy)",
                                 ...mono }}>
                    MVR {money(pv.total)}</span>
                </div>
                {/* meta strip */}
                <div style={{ display: "flex", gap: 12, alignItems: "center",
                  flexWrap: "wrap", padding: "0 16px 10px 40px",
                  fontSize: 12.5, color: "var(--muted)",
                  background: isOpen ? "var(--sky-soft)" : "transparent" }}>
                  <span>{pv.lines.length} line
                    {pv.lines.length === 1 ? "" : "s"}</span>
                  {pv.prepared_by && <span>· prepared by {pv.prepared_by}</span>}
                  <a href={`/api/v1/payment-vouchers/${pv.ref}/pdf`}
                     target="_blank" rel="noreferrer"
                     onClick={(e) => e.stopPropagation()}
                     style={{ marginLeft: "auto" }}>📄 PDF</a>
                </div>

                {isOpen && (
                  <div style={{ padding: "4px 16px 16px" }}>
                    <div style={{ overflowX: "auto" }}>
                      <table style={{ width: "100%",
                                      borderCollapse: "collapse" }}>
                        <thead><tr>
                          {canApprove && <th style={{ ...th, width: 54,
                            textAlign: "center" }}>Query</th>}
                          <th style={th}>Ref</th><th style={th}>Site</th>
                          <th style={th}>Detail</th>
                          <th style={{ ...th, textAlign: "right" }}>
                            Amount (MVR)</th>
                          <th style={th}></th>
                        </tr></thead>
                        <tbody>
                          {pv.lines.map((l) => (
                            <tr key={l.line_id}>
                              {canApprove && (
                                <td style={{ ...td, textAlign: "center" }}>
                                  <input type="checkbox"
                                         checked={!!queries[l.line_id]}
                                         onChange={(e) => setQueries({
                                           ...queries,
                                           [l.line_id]: e.target.checked })} />
                                </td>
                              )}
                              <td style={td}>
                                <a href="#" onClick={(e) => {
                                     e.preventDefault(); onOpenDoc(l.ref); }}
                                   style={{ textDecoration: "none" }}>
                                  <RefStamp small>{l.ref}</RefStamp></a>
                              </td>
                              <td style={td}>{l.site_code}</td>
                              <td style={{ ...td, color: l.doc_type === "IPR"
                                ? "#8a6d00" : "inherit" }}>{lineDetail(l)}</td>
                              <td style={{ ...td, textAlign: "right", ...mono }}>
                                {money(l.amount)}</td>
                              <td style={td}>
                                {l.status !== "INCLUDED"
                                  ? <StatusChip status={l.status} /> : ""}
                                {l.query_note && (
                                  <div style={{ fontSize: 11.5,
                                                color: "var(--red-fg)" }}>
                                    {l.query_note}</div>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>

                    {canApprove && (
                      <div style={{ marginTop: 12, background: "#fff",
                        border: "1px solid var(--line)", borderRadius: 8,
                        padding: 12 }}>
                        <textarea rows={2} value={note}
                          onChange={(e) => setNote(e.target.value)}
                          placeholder="Note to the raiser for any queried line"
                          style={{ ...inputStyle, width: "100%" }} />
                        <div style={{ display: "flex", gap: 10, marginTop: 10,
                                      alignItems: "center", flexWrap: "wrap" }}>
                          <Btn variant="primary" disabled={busy}
                               onClick={() => approve(pv)}>
                            Approve voucher</Btn>
                          <span style={{ fontSize: 12.5,
                                         color: "var(--muted)" }}>
                            Ticked lines go back to their raiser; the rest are
                            authorised.</span>
                        </div>
                      </div>
                    )}

                    {canSubmit && (
                      <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
                        <Btn variant="primary" disabled={busy}
                             onClick={() => voucherAction(pv.ref, "submit")}>
                          Submit to signatory</Btn>
                        <Btn variant="secondary" disabled={busy}
                             onClick={() => voucherAction(pv.ref, "cancel")}>
                          Cancel</Btn>
                      </div>
                    )}

                    {/* Finance disbursement — record each payment + slip */}
                    {canPay && payable.length > 0 && (
                      <div style={{ marginTop: 14 }}>
                        <h4 style={{ margin: "0 0 4px", fontSize: 14,
                                     color: "var(--navy)" }}>
                          Record payments</h4>
                        {payable.map((l) => (
                          <div key={l.line_id}
                               style={{ borderTop: "1px solid var(--line)",
                                        padding: "10px 0" }}>
                            {l.doc_type === "PYR" && (
                              <PayLinePyr l={l} payKey={payKey}
                                startPay={startPay}
                                form={payFormFields({ amount: true,
                                  onSave: () => payPyr(l.ref,
                                                       l.amount) })} />
                            )}
                            {l.doc_type === "PR" && (
                              <PayLinePr l={l} payKey={payKey}
                                startPay={startPay}
                                fields={(row) => payFormFields({
                                  onSave: () => payVendor(l.ref,
                                                          row.line_id) })} />
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                    {canPay && pv.lines.some((l) => l.doc_type === "IPR"
                      && l.status === "APPROVED") && (
                      <p style={{ marginTop: 10, fontSize: 12.5,
                                  color: "#8a6d00" }}>
                        Overseas orders on this voucher are paid on the{" "}
                        <strong>Import Payments</strong> page against their
                        milestones, not here.</p>
                    )}

                    {pv.approvals?.length > 0 && (
                      <div style={{ marginTop: 14, paddingTop: 10,
                        borderTop: "1px solid var(--line)" }}>
                        {pv.approvals.map((a, i) => (
                          <div key={i} style={{ fontSize: 12.5,
                            color: "var(--muted)", padding: "2px 0" }}>
                            <strong style={{ color: "var(--navy)" }}>
                              {a.action}</strong> — {a.by} ({a.role})
                            {a.comment ? ` · ${a.comment}` : ""}</div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
          {shown.length === 0 && (
            <p style={{ fontSize: 13.5, color: "var(--muted)", margin: 0 }}>
              No vouchers{tab === "all" ? "" : ` (${tab.toLowerCase()})`} yet.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

// A single PYR line in the disbursement panel
function PayLinePyr({ l, payKey, startPay, form }) {
  const key = `pyr:${l.ref}`;
  return (
    <div>
      <div style={{ display: "flex", gap: 12, alignItems: "center",
                    flexWrap: "wrap" }}>
        <RefStamp small>{l.ref}</RefStamp>
        <span style={{ fontSize: 13.5 }}>{l.payee}</span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 13.5,
                       fontWeight: 600 }}>MVR {money(l.amount)}</span>
        {l.paid ? (
          <span style={{ color: "var(--green-fg)", fontSize: 13,
                         marginLeft: "auto" }}>
            ✓ paid · {l.payment_ref || "—"}</span>
        ) : payKey === key ? null : (
          <Btn variant="secondary" style={{ marginLeft: "auto" }}
               onClick={() => startPay(key, l.amount)}>Record payment</Btn>
        )}
      </div>
      {payKey === key && form}
    </div>
  );
}

// A PR line expands to its vendor rows for the disbursement panel
function PayLinePr({ l, payKey, startPay, fields }) {
  return (
    <div>
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <RefStamp small>{l.ref}</RefStamp>
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
          procurement · pay each vendor</span>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse",
                      marginTop: 6 }}>
        <tbody>
          {(l.vendor_rows || []).map((row) => {
            const key = `pr:${l.ref}:${row.line_id}`;
            const amt = Number(row.amount_cash || 0)
                      + Number(row.amount_credit || 0);
            return (
              <tr key={row.line_id}>
                <td style={{ ...td, borderTop: "none" }}>
                  {row.vendor}
                  <span style={{ fontSize: 11.5, color: "var(--muted)",
                                 marginLeft: 6 }}>
                    {row.is_credit ? "credit" : "cash"}
                    {row.po_ref ? ` · PO ${row.po_ref}` : ""}</span>
                </td>
                <td style={{ ...td, borderTop: "none", textAlign: "right",
                             fontFamily: "var(--font-mono)" }}>
                  MVR {money(amt)}</td>
                <td style={{ ...td, borderTop: "none" }}>
                  {row.paid ? (
                    <span style={{ color: "var(--green-fg)", fontSize: 13 }}>
                      ✓ paid · {row.payment_ref}</span>
                  ) : payKey === key ? (
                    fields(row)
                  ) : (
                    <Btn variant="secondary"
                         onClick={() => startPay(key)}>Record payment</Btn>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
