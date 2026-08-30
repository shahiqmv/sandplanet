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

function What({ r }) {
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
  const [f, setF] = useState({ amount: "", from_date: "", to_date: "",
                               reason: "" });
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
      setKind(""); setF({ amount: "", from_date: "", to_date: "",
                          reason: "" });
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
              : kind === "LEAVE_ANNUAL" ? "Request annual leave"
              : "Request emergency leave"}
          </b>
          <p style={{ fontSize: 12, color: "var(--muted)",
                      margin: "6px 0 10px" }}>
            {kind === "ADVANCE"
              ? "Recovered in full from your next salary, so it can't be more "
                + "than a month's pay. The Director decides, then Finance pays."
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
              Reason{kind === "ADVANCE" ? "" : " (optional)"}
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
                  {r.pyr_ref ? `Paid on ${r.pyr_ref}`
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
export function StaffRequestQueue({ me }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api("/staff-requests/queue").then(setRows).catch(() => setRows([]));
  }, []);
  useEffect(load, [load]);

  const act = (id, path, body) => api(`/staff-requests/${id}/${path}`,
    { method: "POST", body }).then(load).catch((e) => setError(e.message));

  const isPd = ["DIRECTOR", "ADMIN"].includes(me.role);
  const isHr = ["HO_HR", "ADMIN", "PA"].includes(me.role);
  const isFin = ["FINANCE", "ADMIN"].includes(me.role);

  if (!rows || rows.length === 0) return null;

  return (
    <section style={card}>
      <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 15 }}>
        Staff requests
        <span style={{ fontSize: 12.5, color: "var(--muted)",
                       fontWeight: 400, marginLeft: 8 }}>
          {isPd ? "waiting for your decision"
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
                {isPd && r.status === "SUBMITTED" && (
                  <span style={{ display: "flex", gap: 6,
                                 justifyContent: "flex-end" }}>
                    <Btn variant="primary"
                         style={{ fontSize: 12, padding: "3px 12px" }}
                         onClick={() => act(r.id, "decide",
                                            { approve: true })}>
                      Approve</Btn>
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
                {isHr && r.status === "APPROVED" && r.kind !== "ADVANCE" && (
                  <span style={{ display: "flex", gap: 6,
                                 justifyContent: "flex-end" }}>
                    {/* Paid or unpaid is HR's call — it is the one decision
                        that changes what payroll does. */}
                    <Btn variant="primary"
                         style={{ fontSize: 12, padding: "3px 12px" }}
                         onClick={() => act(r.id, "grant-leave",
                                            { kind: "PAID" })}>
                      Grant as paid</Btn>
                    <Btn variant="secondary"
                         style={{ fontSize: 12, padding: "3px 12px" }}
                         onClick={() => act(r.id, "grant-leave",
                                            { kind: "UNPAID" })}>
                      Without pay</Btn>
                  </span>
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
