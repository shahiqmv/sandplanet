import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { StatusChip, card, td, th } from "./ui.jsx";
import { LockBar, PinGate, PinSettings, useSalaryLock }
  from "./SalaryPin.jsx";

const MONTHS = ["", "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November",
                "December"];

const money = (v, c) => `${c || ""} ${Number(v || 0).toLocaleString("en-US",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim();

const nice = (d) => d ? new Date(d).toLocaleDateString(undefined,
  { day: "numeric", month: "short", year: "numeric" }) : "—";

// Days until a date; negative means it has passed.
const daysTo = (d) => d
  ? Math.round((new Date(d) - new Date()) / 86400000) : null;

function Expiry({ label, value, number }) {
  const n = daysTo(value);
  const tone = n == null ? "var(--muted)"
    : n < 0 ? "var(--red-fg)"
    : n < 60 ? "var(--amber-fg)" : "var(--muted)";
  return (
    <div style={{ padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
      <div style={{ fontSize: 12, color: "var(--muted)" }}>{label}</div>
      <div style={{ fontSize: 14 }}>
        {number && <span style={{ marginRight: 8 }}>{number}</span>}
        <b>{nice(value)}</b>
        {n != null && (
          <span style={{ color: tone, fontSize: 12.5, marginLeft: 8 }}>
            {n < 0 ? `expired ${-n} days ago`
                   : n < 60 ? `${n} days left` : ""}
          </span>
        )}
      </div>
    </div>
  );
}

function Row({ k, children }) {
  return (
    <div style={{ padding: "7px 0", borderBottom: "1px solid var(--line)",
                  display: "flex", gap: 12 }}>
      <span style={{ fontSize: 12.5, color: "var(--muted)", width: 150 }}>
        {k}</span>
      <span style={{ fontSize: 13.5 }}>{children}</span>
    </div>
  );
}

// A person's own record. Everything here comes from /me/* endpoints that
// take no employee id at all, so this page can only ever show you yourself.
export default function MyProfilePage() {
  const [p, setP] = useState(null);
  const [slips, setSlips] = useState(null);
  const [cash, setCash] = useState(null);
  const [leave, setLeave] = useState(null);
  const [tab, setTab] = useState("employment");
  const lock = useSalaryLock();

  // Re-fetched whenever the lock opens or closes: the money endpoints refuse
  // while it is shut, so the page must ask again once it opens.
  const loadMoney = useCallback(() => {
    api("/me/profile").then(setP).catch(() => setP({ linked: false }));
    api("/me/payslips").then(setSlips).catch(() => setSlips(null));
    api("/me/money").then(setCash).catch(() => setCash(null));
  }, []);

  useEffect(() => {
    loadMoney();
    api("/me/leave").then(setLeave).catch(() => setLeave(null));
  }, [loadMoney]);

  // The server closes the window on its own clock; when the countdown here
  // reaches zero, drop what was on screen so the pay does not linger.
  const shut = lock.pin?.has_pin && lock.left <= 0;
  useEffect(() => { if (shut) loadMoney(); }, [shut, loadMoney]);

  if (!p) return <section style={card}>Loading…</section>;

  if (!p.linked) {
    return (
      <section style={card}>
        <h2 style={{ marginTop: 0, color: "var(--sp-navy)" }}>My record</h2>
        <p style={{ fontSize: 14 }}>{p.detail}</p>
      </section>
    );
  }

  const e = p.employment;
  const outstanding = cash
    ? Number(cash.outstanding?.advance || 0) + Number(cash.outstanding?.loan || 0)
    : 0;

  return (
    <section style={card}>
      <div style={{ display: "flex", gap: 16, alignItems: "center",
                    flexWrap: "wrap" }}>
        {e.photo && (
          <img src={e.photo} alt="" style={{ width: 64, height: 64,
            borderRadius: "50%", objectFit: "cover",
            border: "1px solid var(--line)" }} />
        )}
        <div>
          <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>{e.full_name}</h2>
          <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 2 }}>
            {e.emp_no}
            {e.job_category ? ` · ${e.job_category}` : ""}
            {e.site ? ` · ${e.site.code}` : ""}
            {" · joined "}{nice(e.join_date)}
          </div>
        </div>
        <span style={{ marginLeft: "auto" }}>
          <StatusChip status={e.is_active ? "ACTIVE" : "INACTIVE"} />
        </span>
      </div>

      <div style={{ display: "flex", gap: 2, flexWrap: "wrap",
                    borderBottom: "1px solid var(--line)",
                    margin: "16px 0 14px" }}>
        {[["employment", "Employment"], ["pay", "Pay"],
          ["payslips", `Payslips${slips?.payslips?.length
            ? ` (${slips.payslips.length})` : ""}`],
          ["leave", "Leave"]].map(([id, label]) => (
          <button key={id} onClick={() => setTab(id)}
                  style={{ padding: "8px 14px", background: "transparent",
                           border: 0, marginBottom: -1, cursor: "pointer",
                           fontFamily: "inherit", fontSize: 13.5,
                           borderBottom: `2px solid ${tab === id
                             ? "var(--sp-navy)" : "transparent"}`,
                           fontWeight: tab === id ? 700 : 500,
                           color: tab === id ? "var(--sp-navy)"
                                             : "var(--muted)" }}>
            {label}
          </button>
        ))}
      </div>

      {tab === "employment" && (
        <>
          <Row k="Employee number">{e.emp_no}</Row>
          <Row k="Job">{e.job_category || "—"}</Row>
          <Row k="Employment type">{e.employment_type}</Row>
          <Row k="Site">{e.site ? `${e.site.code} — ${e.site.name}` : "—"}</Row>
          <Row k="Joined">{nice(e.join_date)}</Row>
          {e.left_on && <Row k="Left">{nice(e.left_on)}</Row>}
          <Row k="Nationality">{e.nationality || "—"}</Row>
          <h3 style={{ fontSize: 14, color: "var(--sp-navy)",
                       margin: "18px 0 4px" }}>
            Documents
          </h3>
          <p style={{ fontSize: 12, color: "var(--muted)", margin: "0 0 6px" }}>
            Tell HR early if any of these are close to expiring.
          </p>
          <Expiry label="Passport" number={p.documents.passport_no}
                  value={p.documents.passport_expiry} />
          <Expiry label="Work permit" number={p.documents.work_permit_no}
                  value={p.documents.work_permit_expiry} />
          <Expiry label="Medical" value={p.documents.medical_expiry} />
          <Expiry label="Insurance" value={p.documents.insurance_expiry} />
        </>
      )}

      {/* Gate on the payload, not on the lock flag: the flag flips the
          instant the PIN is accepted, while `p` is still the profile fetched
          while it was shut — whose `pay` is null. Rendering that threw inside
          render, which in React is a white screen, not a blank section
          (owner 2026-08-30). */}
      {tab === "pay" && !p.pay && (
        <PinGate lock={lock} onOpened={loadMoney} />
      )}
      {tab === "pay" && p.pay && (
        <>
          <LockBar lock={lock} onLocked={loadMoney} />
          <Row k="Basic pay">
            {money(p.pay.basic_pay, p.pay.currency)} per month</Row>
          {Number(p.pay.usd_basic_pay) > 0 && (
            <Row k="USD basic">{money(p.pay.usd_basic_pay, "USD")}</Row>
          )}
          <Row k="Overtime rate">
            {Number(p.pay.ot_rate) > 0
              ? `${money(p.pay.ot_rate, p.pay.currency)} per hour`
              : "No overtime rate applies"}
          </Row>
          {cash && (
            <>
              <h3 style={{ fontSize: 14, color: "var(--sp-navy)",
                           margin: "18px 0 8px" }}>
                Advances &amp; loans
              </h3>
              {cash.advances.length === 0 ? (
                <p style={{ fontSize: 13.5, color: "var(--muted)" }}>
                  Nothing outstanding.</p>
              ) : (
                <>
                  <table style={{ width: "100%", borderCollapse: "collapse",
                                  fontSize: 13 }}>
                    <thead><tr>
                      <th style={th}>Reference</th><th style={th}>Type</th>
                      <th style={{ ...th, textAlign: "right" }}>Amount</th>
                      <th style={{ ...th, textAlign: "right" }}>
                        Per month</th>
                      <th style={th}>From</th>
                    </tr></thead>
                    <tbody>
                      {cash.advances.map((a) => (
                        <tr key={a.ref}>
                          <td style={td}>{a.ref}</td>
                          <td style={td}>{a.kind}</td>
                          <td style={numTd}>{money(a.amount)}</td>
                          <td style={numTd}>{money(a.installment)}</td>
                          <td style={td}>{a.from_period}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p style={{ fontSize: 13.5, marginTop: 8 }}>
                    Still to be recovered from your pay:{" "}
                    <b>{money(outstanding, p.pay.currency)}</b>
                  </p>
                </>
              )}
            </>
          )}
        </>
      )}

      {tab === "payslips" && lock.locked && !slips?.payslips && (
        <PinGate lock={lock} onOpened={loadMoney} />
      )}
      {tab === "payslips" && (!lock.locked || slips?.payslips) && (
        <>
        <LockBar lock={lock} onLocked={loadMoney} />
        {slips?.payslips?.length ? (
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
            <thead><tr>
              <th style={th}>Period</th><th style={th}>Site</th>
              <th style={{ ...th, textAlign: "right" }}>Days</th>
              <th style={{ ...th, textAlign: "right" }}>Gross</th>
              <th style={{ ...th, textAlign: "right" }}>Deductions</th>
              <th style={{ ...th, textAlign: "right" }}>Net paid</th>
              <th style={th} />
            </tr></thead>
            <tbody>
              {slips.payslips.map((s) => (
                <tr key={s.line_id}>
                  <td style={td}>
                    {MONTHS[s.month]} {s.year}
                    {s.kind === "SETTLEMENT" && (
                      <span style={{ marginLeft: 6, fontSize: 11,
                                     color: "var(--muted)" }}>
                        final settlement</span>
                    )}
                  </td>
                  <td style={td}>{s.site || "—"}</td>
                  <td style={numTd}>{s.days_worked}</td>
                  <td style={numTd}>{money(s.gross, s.currency)}</td>
                  <td style={numTd}>{money(s.deductions, s.currency)}</td>
                  <td style={{ ...numTd, fontWeight: 700 }}>
                    {money(s.net, s.currency)}</td>
                  <td style={td}>
                    <a href={`/api/v1/me/payslips/${s.line_id}.pdf`}
                       target="_blank" rel="noreferrer"
                       style={{ color: "var(--sp-navy)", fontWeight: 600,
                                fontSize: 12.5 }}>
                      Payslip
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={{ fontSize: 13.5, color: "var(--muted)" }}>
            No payslips yet. A month appears here once its payroll run has
            been approved and locked.
          </p>
        )}
        </>
      )}

      {tab === "pay" && p.pay && (
        <PinSettings lock={lock} onChanged={loadMoney} />
      )}

      {tab === "leave" && (
        leave?.leave?.length ? (
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
            <thead><tr>
              <th style={th}>Type</th><th style={th}>From</th>
              <th style={th}>To</th><th style={th}>Returned</th>
              <th style={th}>Reason</th>
            </tr></thead>
            <tbody>
              {leave.leave.map((l, i) => (
                <tr key={i}>
                  <td style={td}>{l.kind}</td>
                  <td style={td}>{nice(l.from_date)}</td>
                  <td style={td}>{nice(l.to_date)}</td>
                  <td style={td}>
                    {l.returned_on ? nice(l.returned_on) : "not yet"}</td>
                  <td style={td}>{l.reason || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={{ fontSize: 13.5, color: "var(--muted)" }}>
            No leave recorded.</p>
        )
      )}
    </section>
  );
}

const numTd = { ...td, textAlign: "right",
                fontVariantNumeric: "tabular-nums" };
