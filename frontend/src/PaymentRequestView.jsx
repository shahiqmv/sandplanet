import { useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, Chip, RefStamp, StatusChip, card, ghostButton, inputStyle,
         td, th } from "./ui.jsx";

// PYR detail + workflow actions (§5.9, §7.5). Which actions show depends
// on the viewer's role and the request's stage.

const RETURN_REASONS = [
  ["INCORRECT_DETAILS", "Incorrect details"],
  ["MISSING_DOCUMENT", "Missing documentation"],
  ["DUPLICATE", "Duplicate request"],
  ["ON_HOLD", "Held — budget or timing"],
  ["SIGNATORY_DECLINED", "Signatory declined"],
  ["OTHER", "Other"],
];
const money = (v) => v == null ? "—"
  : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2 });

export default function PaymentRequestView({ doc, me, onClose, onChanged }) {
  const [panel, setPanel] = useState(null);  // "return" | "pay"
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("INCORRECT_DETAILS");
  const [note, setNote] = useState("");
  const [pay, setPay] = useState({ amount_paid: "", payment_ref: "",
                                   variance_reason: "" });
  const [slip, setSlip] = useState(null);

  const pr = doc.payment_request || {};
  const st = doc.status;
  const role = me.role;
  const isPmHere = role === "PM";  // server re-checks the actual site PM
  const isFinance = role === "FINANCE";
  const isSignatory = role === "SIGNATORY";
  const isDirector = role === "DIRECTOR";
  const isAdmin = role === "ADMIN";
  const isRaiser = doc.created_by_name === me.full_name;

  async function act(action, body = {}) {
    setBusy(true);
    setError(null);
    try {
      await api(`/documents/${doc.ref}/actions/${action}`,
                { method: "POST", body });
      setPanel(null);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function doReturn() {
    if (!note.trim()) { setError("A note to the raiser is required."); return; }
    act("return", { reason_category: reason, note });
  }
  async function doPay() {
    setBusy(true);
    setError(null);
    try {
      // Multipart when a slip is attached; JSON otherwise
      if (slip) {
        const fd = new FormData();
        fd.append("amount_paid", pay.amount_paid || pr.amount_requested);
        fd.append("payment_ref", pay.payment_ref);
        fd.append("variance_reason", pay.variance_reason);
        fd.append("file", slip);
        await apiUpload(`/documents/${doc.ref}/actions/pay`, fd);
      } else {
        await api(`/documents/${doc.ref}/actions/pay`, { method: "POST",
          body: { amount_paid: pay.amount_paid || pr.amount_requested,
                  payment_ref: pay.payment_ref,
                  variance_reason: pay.variance_reason } });
      }
      setPanel(null);
      setSlip(null);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  // Available actions per stage
  const canSubmit = st === "DRAFT" && (isRaiser || isAdmin);
  const canPmApprove = st === "SUBMITTED" && (isPmHere || isAdmin);
  const canDirApprove = st === "PM_APPROVED" && (isDirector || isAdmin);
  // A Director-approved PYR is authorised on a Payment Voucher (M6d), not
  // here — Finance batches it and a signatory approves the batch.
  const awaitingVoucher = st === "DIRECTOR_APPROVED";
  const canPay = st === "AUTHORISED" && (isFinance || isAdmin);
  const canWithdraw = st === "AUTHORISED" && (isFinance || isAdmin);
  const canReturn = ["SUBMITTED", "PM_APPROVED", "DIRECTOR_APPROVED"]
    .includes(st) && (isPmHere || isDirector || isSignatory || isFinance ||
                      isAdmin);

  const pdf = doc.attachments?.filter((a) => a.kind === "GENERATED_PDF")
    .slice(-1)[0];
  const evidence = doc.attachments?.filter((a) => a.kind === "EVIDENCE") || [];
  const slips = doc.attachments?.filter((a) => a.kind === "PAYMENT_SLIP") || [];

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 17 }}>
          <RefStamp>{doc.ref}</RefStamp> Payment Request
        </h2>
        <StatusChip status={st} />
        {pr.is_urgent && <Chip tone="alert">URGENT</Chip>}
        <button onClick={onClose}
                style={{ ...ghostButton, marginLeft: "auto" }}>← Back</button>
      </div>

      {pr.returned_reason && st === "DRAFT" && (
        <p style={{ background: "var(--amber-bg)", color: "var(--amber-fg)",
                    padding: "8px 12px", borderRadius: 8, fontSize: 13,
                    marginTop: 12 }}>
          ↩ Returned ({pr.returned_reason.replace(/_/g, " ").toLowerCase()}):
          {" "}{pr.returned_note}
        </p>
      )}
      {pr.withdrawn_reason && (
        <p style={{ background: "var(--red-bg)", color: "var(--red-fg)",
                    padding: "8px 12px", borderRadius: 8, fontSize: 13,
                    marginTop: 12 }}>
          ⚠ Authorisation withdrawn: {pr.withdrawn_reason}
        </p>
      )}

      <table style={{ width: "100%", borderCollapse: "collapse",
                      marginTop: 12 }}>
        <tbody>
          {[["Site", doc.site_code],
            ["Payment type", pr.payment_type],
            ["Cost head", pr.cost_head],
            ["Payee", pr.payee],
            ["Method", `${pr.payment_method}${pr.payee_account
              ? " · " + pr.payee_account : ""}`],
            ["Amount requested", `MVR ${money(pr.amount_requested)}`],
            ["Required by", pr.required_by || "—"],
            ["Purpose", pr.purpose],
            ["Supporting doc", pr.has_supporting_doc
              ? `Yes (${evidence.length} attached)`
              : `No — ${pr.no_doc_reason || "(no reason)"}`],
            ...(pr.amount_paid != null
              ? [["Amount paid", `MVR ${money(pr.amount_paid)}`],
                 ["Payment ref", pr.payment_ref || "—"],
                 ...(pr.variance_reason
                   ? [["Variance", pr.variance_reason]] : [])] : []),
          ].map(([k, v]) => (
            <tr key={k}>
              <td style={{ ...td, width: 160, color: "var(--muted)",
                           fontWeight: 600 }}>{k}</td>
              <td style={td}>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {evidence.length > 0 && (
        <p style={{ fontSize: 13, marginTop: 8 }}>
          {evidence.map((a) => (
            <a key={a.id} href={a.url} target="_blank" rel="noreferrer"
               style={{ marginRight: 12 }}>📎 {a.file_name}</a>
          ))}
        </p>
      )}
      {slips.length > 0 && (
        <p style={{ fontSize: 13, marginTop: 4 }}>
          {slips.map((a) => (
            <a key={a.id} href={a.url} target="_blank" rel="noreferrer"
               style={{ marginRight: 12 }}>🧾 payment slip ({a.file_name})</a>
          ))}
        </p>
      )}
      {pdf && (
        <p style={{ fontSize: 13 }}>
          <a href={pdf.url} target="_blank" rel="noreferrer">📄 PDF</a></p>
      )}

      {doc.approvals?.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse",
                        marginTop: 12 }}>
          <thead><tr>
            <th style={th}>Action</th><th style={th}>By</th>
            <th style={th}>When</th><th style={th}>Comment</th>
          </tr></thead>
          <tbody>
            {doc.approvals.map((a) => (
              <tr key={a.id}>
                <td style={td}>{a.action.replace(/_/g, " ")}</td>
                <td style={td}>{a.actor_name} ({a.actor_role})</td>
                <td style={td}>{new Date(a.acted_at).toLocaleString()}</td>
                <td style={{ ...td, color: "var(--muted)" }}>{a.comment}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}

      {/* Inline panels */}
      {panel === "return" && (
        <div style={{ marginTop: 12, padding: 12, borderRadius: 8,
                      border: "1px solid var(--line)" }}>
          <label style={{ fontSize: 13 }}>Reason
            <select value={reason} onChange={(e) => setReason(e.target.value)}
                    style={inputStyle}>
              {RETURN_REASONS.map(([v, l]) =>
                <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label style={{ fontSize: 13, display: "block", marginTop: 8 }}>
            Note to the raiser (what must change)
            <textarea rows={2} value={note}
                      onChange={(e) => setNote(e.target.value)}
                      style={{ ...inputStyle, resize: "vertical" }} />
          </label>
          <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
            <Btn variant="navy" onClick={doReturn} disabled={busy}>
              Return for review</Btn>
            <button onClick={() => setPanel(null)} style={ghostButton}>
              Cancel</button>
          </div>
        </div>
      )}
      {panel === "pay" && (
        <div style={{ marginTop: 12, padding: 12, borderRadius: 8,
                      border: "1px solid var(--line)" }}>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <label style={{ fontSize: 13 }}>Amount paid (MVR)
              <input type="number" value={pay.amount_paid}
                     placeholder={pr.amount_requested}
                     onChange={(e) => setPay({ ...pay,
                       amount_paid: e.target.value })}
                     style={{ ...inputStyle, width: 140 }} />
            </label>
            <label style={{ fontSize: 13 }}>Payment reference
              <input value={pay.payment_ref}
                     onChange={(e) => setPay({ ...pay,
                       payment_ref: e.target.value })}
                     placeholder="slip / cheque / TT no."
                     style={{ ...inputStyle, width: 200 }} />
            </label>
          </div>
          <label style={{ fontSize: 13, display: "block", marginTop: 8 }}>
            Variance reason (only if paid ≠ requested)
            <input value={pay.variance_reason}
                   onChange={(e) => setPay({ ...pay,
                     variance_reason: e.target.value })}
                   style={inputStyle} />
          </label>
          <label style={{ fontSize: 13, display: "block", marginTop: 8 }}>
            Payment slip (transfer copy / cheque) — recommended
            <input type="file"
                   onChange={(e) => setSlip(e.target.files[0] || null)}
                   style={{ display: "block", marginTop: 4 }} />
          </label>
          <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
            <Btn variant="navy" onClick={doPay} disabled={busy}>
              Record payment</Btn>
            <button onClick={() => setPanel(null)} style={ghostButton}>
              Cancel</button>
          </div>
        </div>
      )}

      {/* Action bar */}
      <div style={{ marginTop: 14, display: "flex", gap: 8,
                    flexWrap: "wrap" }}>
        {canSubmit && <Btn variant="primary" onClick={() => act("submit")}
                           disabled={busy}>Submit</Btn>}
        {canPmApprove && <Btn variant="navy" onClick={() => act("approve")}
                              disabled={busy}>PM approve</Btn>}
        {canDirApprove && <Btn variant="navy" onClick={() => act("approve")}
                               disabled={busy}>Director approve</Btn>}
        {awaitingVoucher && (
          <span className="text-sm text-slate-500">
            Awaiting a payment voucher — Finance batches this for a
            signatory to approve.</span>
        )}
        {canPay && <Btn variant="navy" onClick={() => setPanel("pay")}
                        disabled={busy}>Record payment</Btn>}
        {canReturn && (
          <button onClick={() => setPanel("return")}
                  style={{ ...ghostButton }}>Return for review</button>
        )}
        {canWithdraw && (
          <button onClick={() => {
                    const n = window.prompt("Withdraw authorisation — reason "
                      + "(this reverses the committed cost):");
                    if (n) act("withdraw-authorisation", { note: n });
                  }}
                  style={{ ...ghostButton, color: "var(--red-fg)",
                           borderColor: "var(--red-fg)" }}>
            Withdraw authorisation</button>
        )}
        {canSubmit && (
          <button onClick={() => act("cancel")} style={ghostButton}>
            Cancel request</button>
        )}
      </div>
    </section>
  );
}
