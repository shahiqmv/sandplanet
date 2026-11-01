import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";

const TONE = { SUBMITTED: "warn", APPROVED: "info", DONE: "ok",
               DECLINED: "alert", CANCELLED: "info" };

const nice = (d) => d ? new Date(d).toLocaleDateString(undefined,
  { day: "numeric", month: "short", year: "numeric" }) : "—";

const money = (v, c) => v == null ? "—"
  : `${c || ""} ${Number(v).toLocaleString("en-US",
      { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim();

const monthName = (ym) => ym ? new Date(`${ym}-01T00:00:00`)
  .toLocaleDateString(undefined, { month: "short", year: "numeric" }) : "";

const isLeave = (r) => r.kind.startsWith("LEAVE");

// HR's half of an approved leave request: the dates actually taken, paid or
// unpaid, or that it never happened. The site has had the person on its
// register until now, so what it marked is shown before granting replaces it.
function GrantLeave({ r, act }) {
  const [from, setFrom] = useState(r.from_date);
  const [to, setTo] = useState(r.to_date);
  const marked = r.marked_at_work;
  const name = r.employee.full_name;
  const grant = (kind) => {
    if (marked?.days && !window.confirm(
      `${name} is marked present at ${marked.sites.join(", ")} on `
      + `${marked.days} of the approved days. Granting replaces the marks `
      + "for the dates entered. Go ahead?")) return;
    act(r.id, "grant-leave", { kind, from_date: from, to_date: to });
  };
  return (
    <div style={{ display: "grid", gap: 6, justifyItems: "end" }}>
      <span style={{ display: "flex", gap: 6, alignItems: "center",
                     fontSize: 12, flexWrap: "wrap",
                     justifyContent: "flex-end" }}>
        <input type="date" aria-label="Leave from" value={from}
               style={{ ...inputStyle, fontSize: 12, width: 140 }}
               onChange={(e) => setFrom(e.target.value)} />
        to
        <input type="date" aria-label="Leave to" value={to}
               style={{ ...inputStyle, fontSize: 12, width: 140 }}
               onChange={(e) => setTo(e.target.value)} />
      </span>
      {marked?.days > 0 && (
        <span style={{ fontSize: 12, color: "var(--red-fg)",
                       whiteSpace: "normal", textAlign: "right" }}>
          Marked present at {marked.sites.join(", ")} on {marked.days} of these
          days. Check they went, and correct the dates if needed.</span>)}
      <span style={{ display: "flex", gap: 6, justifyContent: "flex-end",
                     flexWrap: "wrap" }}>
        {/* Paid or unpaid is HR's call — it is the one decision that changes
            what payroll does. */}
        <Btn variant="primary" style={{ fontSize: 12, padding: "3px 12px" }}
             onClick={() => grant("PAID")}>Grant as paid</Btn>
        <Btn variant="secondary" style={{ fontSize: 12, padding: "3px 12px" }}
             onClick={() => grant("UNPAID")}>Without pay</Btn>
        <Btn variant="ghost" style={{ fontSize: 12, padding: "3px 12px" }}
             onClick={() => {
               const note = window.prompt("Why was this leave not taken? "
                 + "(the requester is told it was closed)");
               if (note) act(r.id, "leave-not-taken", { note });
             }}>Not taken</Btn>
      </span>
    </div>
  );
}

// Approved leave doesn't exist until HR grants it, so the register shows what
// is still waiting. Without this a person away on approved leave looked like
// nobody on leave at all (owner 2026-11-01).
export function LeaveToGrant({ onGranted }) {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    api("/staff-requests/queue")
      .then((d) => setRows(d.filter((r) => isLeave(r)
                                    && r.status === "APPROVED")))
      .catch(() => setRows([]));
  }, []);
  useEffect(load, [load]);
  const act = (id, path, body) => api(`/staff-requests/${id}/${path}`,
    { method: "POST", body })
    .then(() => { setError(null); load(); onGranted?.(); })
    .catch((e) => setError(e.message));

  if (!rows.length) return null;
  return (
    <div style={{ marginBottom: 16 }}>
      <h3 style={{ margin: "0 0 2px", color: "var(--sp-navy)", fontSize: 14 }}>
        Approved, waiting to be granted ({rows.length})</h3>
      <p style={{ margin: "0 0 6px", fontSize: 12, color: "var(--muted)" }}>
        The Director has approved these. They stay on their site's register and
        off the list below until granted here.</p>
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 13 }}>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td style={{ ...td, width: 190 }}>
                  <b>{r.employee.full_name}</b>
                  <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
                    {r.employee.emp_no}</div>
                </td>
                <td style={td}><What r={r} />
                  <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
                    {r.reason}</div></td>
                <td style={{ ...td, textAlign: "right" }}>
                  <GrantLeave r={r} act={act} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function What({ r }) {
  if (r.kind === "LOAN") {
    const changed = r.approved_amount != null && (
      Number(r.approved_amount) !== Number(r.amount)
      || r.approved_months !== r.months);
    return (
      <>Loan of <b>{money(r.amount, r.currency)}</b> over {r.months} months
        {r.approved_amount != null && (
          <div style={{ fontSize: 12, color: changed ? "var(--amber-fg)"
            : "var(--muted)" }}>
            {changed ? "Approved: " : ""}
            {changed && <>{money(r.approved_amount, r.currency)} over{" "}
              {r.approved_months} months · </>}
            {money(Number(r.approved_amount) / r.approved_months,
                   r.currency)} a month from {monthName(r.first_month)}
          </div>)}
      </>);
  }
  return r.kind === "ADVANCE"
    ? <>Advance of <b>{money(r.amount, r.currency)}</b></>
    : <>{r.kind_label}, {nice(r.from_date)} – {nice(r.to_date)}{" "}
       <span style={{ color: "var(--muted)" }}>({r.days} days)</span></>;
}

// What a person may ask the company for. The request itself is thin: an
// advance ends as the payment request Finance already raises, and leave ends
// in the leave system HR already runs (owner 2026-08-30).
export function MyRequests({ isStaff }) {
  const [data, setData] = useState(null);
  const [kind, setKind] = useState("");
  const [f, setF] = useState({ amount: "", months: "", from_date: "",
                               to_date: "", reason: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api("/me/requests").then(setData).catch(() => setData(null));
  }, []);
  useEffect(load, [load]);

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api("/me/requests", { method: "POST", body: { kind, ...f } });
      setKind(""); setF({ amount: "", months: "", from_date: "",
                          to_date: "", reason: "" });
      load();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  if (!data) return <p style={{ fontSize: 13.5 }}>Loading…</p>;
  if (!data.linked) {
    return (
      <p style={{ fontSize: 13.5 }}>
        Your login isn&rsquo;t linked to an employee record yet. Ask HR to
        link it.
      </p>
    );
  }

  const isLeave = kind.startsWith("LEAVE");

  return (
    <>
      {!kind ? (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                      marginBottom: 16 }}>
          <Btn variant="navy" onClick={() => setKind("ADVANCE")}>
            Ask for an advance</Btn>
          <Btn variant="navy" onClick={() => setKind("LOAN")}>
            Ask for a loan</Btn>
          {isStaff && (
            <>
              <Btn variant="navy" onClick={() => setKind("LEAVE_ANNUAL")}>
                Request annual leave</Btn>
              <Btn variant="secondary"
                   onClick={() => setKind("LEAVE_EMERGENCY")}>
                Emergency leave</Btn>
            </>
          )}
        </div>
      ) : (
        <form onSubmit={submit}
              style={{ ...card, marginBottom: 16, maxWidth: 460 }}>
          <b style={{ fontSize: 13.5, color: "var(--sp-navy)" }}>
            {kind === "ADVANCE" ? "Ask for a salary advance"
              : kind === "LOAN" ? "Ask for a staff loan"
              : kind === "LEAVE_ANNUAL" ? "Request annual leave"
              : "Request emergency leave"}
          </b>
          <p style={{ fontSize: 12, color: "var(--muted)",
                      margin: "6px 0 10px" }}>
            {kind === "ADVANCE"
              ? "Recovered in full from your next salary, so it can't be more "
                + "than a month's pay. The Director decides, then Finance pays."
              : kind === "LOAN"
                ? "Repaid from your salary in equal monthly amounts over the "
                  + "months you choose (up to 24). The Director approves the "
                  + "amount and the months, a Signatory authorises it, then "
                  + "Finance pays."
              : kind === "LEAVE_ANNUAL"
                ? "Planned ahead — pick dates in the future. The Director "
                  + "decides, then HR arranges it."
                : "For something that can't wait. The Director decides, then "
                  + "HR arranges it."}
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {kind === "ADVANCE" ? (
              <label style={fld}>Amount
                <input type="number" step="0.01" value={f.amount}
                       onChange={(e) => setF({ ...f, amount: e.target.value })}
                       style={inputStyle} />
              </label>
            ) : kind === "LOAN" ? (
              <>
                <div style={{ display: "flex", gap: 8 }}>
                  <label style={{ ...fld, flex: 2 }}>Amount
                    <input type="number" step="0.01" value={f.amount}
                           onChange={(e) => setF({ ...f,
                             amount: e.target.value })}
                           style={inputStyle} />
                  </label>
                  <label style={{ ...fld, flex: 1 }}>Repay over (months)
                    <input type="number" min="1" max="24" step="1"
                           value={f.months}
                           onChange={(e) => setF({ ...f,
                             months: e.target.value })}
                           style={inputStyle} />
                  </label>
                </div>
                {Number(f.amount) > 0 && Number(f.months) > 0 && (
                  <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
                    About <b>{money(Number(f.amount) / Number(f.months))}</b>
                    {" "}deducted from each salary.</span>)}
              </>
            ) : (
              <div style={{ display: "flex", gap: 8 }}>
                <label style={{ ...fld, flex: 1 }}>First day away
                  <input type="date" value={f.from_date}
                         onChange={(e) => setF({ ...f,
                           from_date: e.target.value })}
                         style={inputStyle} />
                </label>
                <label style={{ ...fld, flex: 1 }}>Last day away
                  <input type="date" value={f.to_date}
                         onChange={(e) => setF({ ...f,
                           to_date: e.target.value })}
                         style={inputStyle} />
                </label>
              </div>
            )}
            <label style={fld}>
              {kind === "LOAN" ? "Purpose" : "Reason"}
              {kind === "ADVANCE" || kind === "LOAN" ? "" : " (optional)"}
              <input value={f.reason}
                     onChange={(e) => setF({ ...f, reason: e.target.value })}
                     style={inputStyle} />
            </label>
          </div>
          {error && (
            <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <Btn variant="primary" type="submit"
                 disabled={busy || (kind === "ADVANCE"
                   ? !f.amount || !f.reason
                   : kind === "LOAN" ? !f.amount || !f.months || !f.reason
                   : !f.from_date || !f.to_date)}>
              Send to the Director</Btn>
            <Btn variant="ghost" onClick={() => { setKind("");
                                                  setError(null); }}>
              Cancel</Btn>
          </div>
        </form>
      )}

      {data.requests.length === 0 ? (
        <p style={{ fontSize: 13.5, color: "var(--muted)" }}>
          You haven&rsquo;t asked for anything yet.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 13 }}>
          <thead><tr>
            <th style={th}>What</th><th style={th}>Reason</th>
            <th style={th}>Status</th><th style={th}>Outcome</th>
            <th style={th} />
          </tr></thead>
          <tbody>
            {data.requests.map((r) => (
              <tr key={r.id}>
                <td style={td}><What r={r} /></td>
                <td style={td}>{r.reason || "—"}</td>
                <td style={td}>
                  <Chip tone={TONE[r.status]}>{r.status_label}</Chip>
                </td>
                <td style={{ ...td, fontSize: 12.5,
                             color: "var(--muted)" }}>
                  {r.kind === "LOAN" && r.pyr_ref
                    ? `Authorised · payment ${r.pyr_ref}`
                    : r.pyr_ref ? `Paid on ${r.pyr_ref}`
                    : r.leave_id ? "Leave arranged"
                    : r.decision_note || "—"}
                </td>
                <td style={td}>
                  {r.can_cancel && (
                    <Btn variant="ghost"
                         style={{ fontSize: 12, padding: "2px 10px" }}
                         onClick={() => api(
                           `/staff-requests/${r.id}/cancel`,
                           { method: "POST" }).then(load)}>
                      Withdraw</Btn>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

// The other side: what the Director must decide, what HR must arrange, and
// what Finance must pay. One queue, filtered by role on the server.
export function StaffRequestQueue({ me, showEmpty = false }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api("/staff-requests/queue").then(setRows).catch(() => setRows([]));
  }, []);
  useEffect(load, [load]);

  // resolves true when it went through, so a refused form can stay open
  const act = (id, path, body) => api(`/staff-requests/${id}/${path}`,
    { method: "POST", body }).then(() => { setError(null); load(); return true; })
    .catch((e) => { setError(e.message); return false; });

  const isPd = ["DIRECTOR", "ADMIN"].includes(me.role);
  const isHr = ["HO_HR", "ADMIN", "PA"].includes(me.role);
  const isFin = ["FINANCE", "ADMIN"].includes(me.role);
  const isSig = ["SIGNATORY", "ADMIN"].includes(me.role);
  // the loan whose terms the Director is setting
  const [terms, setTerms] = useState(null);

  if (!rows) return null;
  if (rows.length === 0) {
    return showEmpty ? (
      <section style={card}>
        <p style={{ margin: 0, fontSize: 13, color: "var(--muted)" }}>
          Nothing is waiting for you.</p>
      </section>) : null;
  }

  return (
    <section style={card}>
      <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 15 }}>
        Staff requests
        <span style={{ fontSize: 12.5, color: "var(--muted)",
                       fontWeight: 400, marginLeft: 8 }}>
          {isPd ? "waiting for your decision"
            : isSig ? "staff loans to authorise"
            : isHr ? "approved — arrange the leave"
            : "approved — raise the payment"}
        </span>
      </h2>
      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      <table style={{ width: "100%", borderCollapse: "collapse",
                      fontSize: 13 }}>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td style={{ ...td, width: 190 }}>
                <b>{r.employee.full_name}</b>
                <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
                  {r.employee.emp_no}</div>
              </td>
              <td style={td}><What r={r} /></td>
              <td style={{ ...td, color: "var(--muted)" }}>
                {r.reason || "—"}</td>
              <td style={{ ...td, textAlign: "right", whiteSpace: "nowrap" }}>
                {isPd && r.status === "SUBMITTED" && r.kind === "LOAN"
                  && terms?.id === r.id && (
                  <LoanTerms r={r} t={terms} setT={setTerms}
                    onApprove={(body) => act(r.id, "decide",
                      { approve: true, ...body })
                      .then((ok) => ok && setTerms(null))}
                    onCancel={() => setTerms(null)} />
                )}
                {isSig && r.status === "APPROVED" && r.kind === "LOAN" && (
                  <span style={{ display: "flex", gap: 6,
                                 justifyContent: "flex-end" }}>
                    <Btn variant="primary"
                         style={{ fontSize: 12, padding: "3px 12px" }}
                         onClick={() => {
                           if (window.confirm(`Authorise a loan of `
                             + `${money(r.approved_amount, r.currency)} to `
                             + `${r.employee.full_name}, repaid over `
                             + `${r.approved_months} months? The payment `
                             + "request goes to Finance.")) {
                             act(r.id, "authorise", { approve: true });
                           }
                         }}>
                      Authorise</Btn>
                    <Btn variant="ghost"
                         style={{ fontSize: 12, padding: "3px 12px",
                                  color: "var(--red-fg)" }}
                         onClick={() => {
                           const note = window.prompt("Why are you "
                             + "declining? (the requester sees this)");
                           if (note) act(r.id, "authorise",
                                         { approve: false, note });
                         }}>
                      Decline</Btn>
                  </span>
                )}
                {isPd && r.status === "SUBMITTED" && terms?.id !== r.id && (
                  <span style={{ display: "flex", gap: 6,
                                 justifyContent: "flex-end" }}>
                    <Btn variant="primary"
                         style={{ fontSize: 12, padding: "3px 12px" }}
                         onClick={() => (r.kind === "LOAN"
                           ? setTerms({ id: r.id,
                               approved_amount: String(Number(r.amount)),
                               approved_months: String(r.months),
                               first_month: r.suggested_first_month,
                               note: "" })
                           : act(r.id, "decide", { approve: true }))}>
                      {r.kind === "LOAN" ? "Approve…" : "Approve"}</Btn>
                    <Btn variant="ghost"
                         style={{ fontSize: 12, padding: "3px 12px",
                                  color: "var(--red-fg)" }}
                         onClick={() => {
                           const note = window.prompt("Why are you "
                             + "declining? (the requester sees this)");
                           if (note) act(r.id, "decide",
                                         { approve: false, note });
                         }}>
                      Decline</Btn>
                  </span>
                )}
                {isHr && r.status === "APPROVED" && isLeave(r) && (
                  <GrantLeave r={r} act={act} />
                )}
                {isFin && r.status === "APPROVED"
                  && r.kind === "ADVANCE" && (
                  <Btn variant="secondary"
                       style={{ fontSize: 12, padding: "3px 12px" }}
                       onClick={() => {
                         const ref = window.prompt("Raise the payment "
                           + "request as usual, then enter its reference "
                           + "to tie it to this request:");
                         if (ref) act(r.id, "link-payment",
                                      { ref: ref.trim().toUpperCase() });
                       }}>
                    Record the PYR</Btn>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

const fld = { display: "flex", flexDirection: "column", gap: 3, fontSize: 12,
  color: "var(--muted)" };

// The Director approves a loan with its terms: the amount and months (the
// ask, unless changed) and the payroll month the first instalment comes off.
function LoanTerms({ r, t, setT, onApprove, onCancel }) {
  const amt = Number(t.approved_amount) || 0;
  const n = Number(t.approved_months) || 0;
  const each = amt > 0 && n > 0 ? amt / n : 0;
  const tooBig = r.basic_pay && each > Number(r.basic_pay);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6,
                  alignItems: "flex-end", textAlign: "left" }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap",
                    justifyContent: "flex-end" }}>
        <label style={fld}>Approved amount
          <input type="number" step="0.01" value={t.approved_amount}
                 onChange={(e) => setT({ ...t,
                   approved_amount: e.target.value })}
                 style={{ ...inputStyle, width: 120 }} /></label>
        <label style={fld}>Months
          <input type="number" min="1" max="24" value={t.approved_months}
                 onChange={(e) => setT({ ...t,
                   approved_months: e.target.value })}
                 style={{ ...inputStyle, width: 70 }} /></label>
        <label style={fld}>First deduction
          <input type="month" value={t.first_month || ""}
                 onChange={(e) => setT({ ...t, first_month: e.target.value })}
                 style={{ ...inputStyle, width: 150 }} /></label>
      </div>
      <span style={{ fontSize: 12, color: tooBig ? "var(--red-fg)"
        : "var(--muted)" }}>
        {each ? `${money(each, r.currency)} a month` : ""}
        {r.basic_pay ? ` · monthly pay ${money(r.basic_pay, r.currency)}` : ""}
        {tooBig ? " — more than the pay; spread it over more months" : ""}
      </span>
      <input placeholder="Note (optional — the requester sees it)"
             value={t.note} onChange={(e) => setT({ ...t, note: e.target.value })}
             style={{ ...inputStyle, width: 330 }} />
      <span style={{ display: "flex", gap: 6 }}>
        <Btn variant="primary" style={{ fontSize: 12, padding: "3px 12px" }}
             disabled={!each || tooBig}
             onClick={() => onApprove({
               approved_amount: t.approved_amount,
               approved_months: t.approved_months,
               first_month: t.first_month, note: t.note })}>
          Approve and send to the Signatory</Btn>
        <Btn variant="ghost" style={{ fontSize: 12, padding: "3px 12px" }}
             onClick={onCancel}>Cancel</Btn>
      </span>
    </div>
  );
}
