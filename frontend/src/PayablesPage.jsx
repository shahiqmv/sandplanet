import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, RefStamp, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

// Outstanding payables on their own page (moved off the voucher builder — the
// list was accumulating and bloating that page, owner 2026-08-08). Finance
// ticks what to settle and raises a voucher for just those.
//
// Two kinds now sit here. A CREDIT payable is a supplier invoice on terms, in
// rufiyaa. A SALARY payable is one person's pay on the combined USD run, which
// is transferred to their own account — so payroll arrives as a list of people
// to pay rather than one lump, and Finance chooses who goes in this batch
// (owner 2026-09-10). They are kept on separate tabs because a voucher is
// single-currency and because ticking through fifty-five salaries alongside
// supplier invoices is how the wrong one gets paid.
const money = (v) => Number(v || 0).toLocaleString("en-US",
  { minimumFractionDigits: 2 });
const mono = { fontFamily: "var(--font-mono)" };

export default function PayablesPage({ me, onOpenDoc }) {
  const isFinance = ["FINANCE", "ADMIN"].includes(me.role);
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [tab, setTab] = useState("CREDIT");
  const [picked, setPicked] = useState({});     // payable_id -> bool
  const [banks, setBanks] = useState([]);
  const [debit, setDebit] = useState("");
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    setError(null);
    const p = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
    api(`/finance/payables${p}`).then(setData).catch((e) => setError(e.message));
  };
  useEffect(() => { load(); }, []);            // eslint-disable-line
  useEffect(() => {
    if (isFinance) api("/receivables/bank-accounts?active=1")
      .then((r) => setBanks(r.accounts)).catch(() => {});
  }, [isFinance]);

  const all = data?.payables || [];
  const salaries = all.filter((r) => r.group === "SALARY");
  const credit = all.filter((r) => r.group !== "SALARY");
  const onSalaries = tab === "SALARY";
  const rows = onSalaries ? salaries : credit;
  const pickedRows = rows.filter((r) => picked[r.payable_id]);
  const pickedTotal = pickedRows.reduce((s, r) => s + Number(r.amount || 0), 0);
  const tabTotal = rows.reduce((s, r) => s + Number(r.amount || 0), 0);
  // A voucher is single-currency, so the batch's currency is the one the debit
  // account has to be in.
  const currency = pickedRows[0]?.currency || rows[0]?.currency || "MVR";
  const payBanks = banks.filter((b) => (b.currency || "MVR") === currency);
  // Nobody can be transferred to an account we do not hold.
  const blocked = onSalaries ? rows.filter((r) => !r.payable_now).length : 0;

  function switchTab(next) {          // never carry a selection across currencies
    setTab(next); setPicked({}); setDebit(""); setMsg(null);
  }

  function pickAllPayable() {
    const next = {};
    for (const r of rows) if (!onSalaries || r.payable_now)
      next[r.payable_id] = true;
    setPicked(next);
  }

  async function createVoucher() {
    if (!pickedRows.length) return;
    setBusy(true); setError(null); setMsg(null);
    try {
      const pv = await api("/payment-vouchers", { method: "POST",
        body: { payable_ids: pickedRows.map((r) => r.payable_id),
                bank_account_id: debit || null } });
      const what = onSalaries ? `${pickedRows.length} salaries`
        : `${pickedRows.length} payable(s)`;
      setPicked({}); setDebit("");
      setMsg(`Voucher ${pv.ref} raised for ${what} — submit it on the Payment `
        + `Vouchers page.${onSalaries ? " The transfer list downloads from "
          + "the voucher once it is approved." : ""}`);
      load();
    } catch (e) { setError(e.message); }
    setBusy(false);
  }

  // The due date comes from the vendor's agreed terms, but a supplier
  // withdraws credit, grants an extension, or the invoice says otherwise —
  // Finance needs to be able to move it rather than work around a wrong date
  // (owner 2026-08-22). A reason is required: it is agreed terms being
  // overridden.
  async function moveDueDate(r) {
    const when = window.prompt(
      `New due date for ${r.payee} (${r.ref})`, r.due_date || "");
    if (!when) return;
    const why = window.prompt("Why is it moving?", "");
    if (!why || !why.trim()) return;
    try {
      await api(`/finance/payables/${r.payable_id}/due-date`,
        { method: "POST", body: { due_date: when, reason: why.trim() } });
      load();
    } catch (e) { setError(e.message); }
  }

  if (!data && !error) return <div style={card}>Loading…</div>;

  const tabBtn = (key, label, n) => (
    <button key={key} onClick={() => switchTab(key)}
      style={{ ...ghostButton, padding: "4px 12px", fontSize: 13,
        background: tab === key ? "var(--sky-soft)" : "transparent",
        fontWeight: tab === key ? 600 : 400 }}>
      {label} {n > 0 && <span style={mono}>({n})</span>}</button>
  );

  return (
    <section style={{ ...card, margin: 0 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap", marginBottom: 8 }}>
        <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 18 }}>
          Outstanding payables</h2>
        <span style={{ fontSize: 13, color: "var(--muted)" }}>
          {rows.length} · {currency} {money(tabTotal)} total
          {data?.overdue && !onSalaries ? ` · ${data.overdue} overdue` : ""}</span>
        <form onSubmit={(e) => { e.preventDefault(); load(); }}
              style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
          <input value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="Search name / ref…"
                 style={{ ...inputStyle, padding: "4px 10px", fontSize: 13,
                          width: 180 }} />
          <button type="submit" style={{ ...ghostButton, padding: "4px 12px",
            fontSize: 13 }}>Search</button>
        </form>
      </div>

      <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
        {tabBtn("CREDIT", "Credit payables", credit.length)}
        {tabBtn("SALARY", "Salaries", salaries.length)}
      </div>

      <p style={{ fontSize: 13, color: "var(--muted)", margin: "0 0 10px" }}>
        {onSalaries
          ? "One line per person on an approved USD run, each transferred to "
            + "their own account. Tick who is being paid in this batch — "
            + "anyone left goes on the next one. A signatory approves the "
            + "voucher, then the transfer list downloads from it."
          : "These aren't queued for payment. Tick the invoice(s) to settle — "
            + "when due, or early if a vendor withdraws credit — and raise a "
            + "voucher for just those. A signatory approves it on the Payment "
            + "Vouchers page."}
      </p>

      {blocked > 0 && (
        <p style={{ fontSize: 13, color: "var(--red-fg)", margin: "0 0 10px" }}>
          {blocked} {blocked === 1 ? "person has" : "people have"} no bank
          account on file and cannot be transferred. HR adds it on the employee
          record; they stay outstanding until then.
        </p>)}

      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      {msg && <p style={{ color: "var(--green-fg, #137333)", fontSize: 13,
        background: "var(--green-bg, #e6f4ea)", padding: "8px 12px",
        borderRadius: 8 }}>{msg}</p>}

      {isFinance && rows.length > 0 && (
        <div style={{ display: "flex", gap: 12, alignItems: "center",
          flexWrap: "wrap", padding: "8px 12px", borderRadius: 8,
          background: pickedRows.length ? "var(--sky-soft)" : "transparent",
          marginBottom: 10 }}>
          <span style={{ fontSize: 13.5 }}>
            {pickedRows.length} selected ·{" "}
            <strong style={mono}>{currency} {money(pickedTotal)}</strong></span>
          <button onClick={pickAllPayable}
            style={{ ...ghostButton, padding: "2px 10px", fontSize: 12.5 }}>
            Select all{blocked > 0 ? " payable" : ""}</button>
          {pickedRows.length > 0 && (
            <button onClick={() => setPicked({})}
              style={{ ...ghostButton, padding: "2px 10px", fontSize: 12.5 }}>
              Clear</button>)}
          {pickedRows.length > 0 && (<>
            <select value={debit} onChange={(e) => setDebit(e.target.value)}
              style={{ ...inputStyle, padding: "4px 8px", fontSize: 13,
                marginLeft: "auto" }}>
              <option value="">Debit account…</option>
              {payBanks.map((b) => (
                <option key={b.id} value={b.id}>{b.label}</option>
              ))}
            </select>
            <Btn variant="primary" disabled={busy}
                 onClick={createVoucher}>Create voucher</Btn>
          </>)}
        </div>
      )}

      {rows.length === 0 ? (
        <p style={{ fontSize: 13.5, color: "var(--muted)", margin: 0 }}>
          {q.trim() ? "Nothing matches."
            : onSalaries ? "No salaries waiting to be paid."
              : "No outstanding payables. 🎉"}</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              {isFinance && <th style={{ ...th, width: 34 }}></th>}
              <th style={th}>Ref</th>
              <th style={th}>{onSalaries ? "Employee" : "Vendor"}</th>
              <th style={th}>{onSalaries ? "Account" : "Site"}</th>
              <th style={th}>{onSalaries ? "Period" : "Due"}</th>
              <th style={{ ...th, textAlign: "right" }}>Amount</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => {
                const stop = onSalaries && !r.payable_now;
                return (
                <tr key={r.payable_id} style={{ background:
                  picked[r.payable_id] ? "var(--sky-soft)" : "transparent",
                  opacity: stop ? 0.55 : 1 }}>
                  {isFinance && (
                    <td style={{ ...td, textAlign: "center" }}>
                      <input type="checkbox" disabled={stop}
                        checked={!!picked[r.payable_id]}
                        onChange={(e) => setPicked({ ...picked,
                          [r.payable_id]: e.target.checked })} /></td>
                  )}
                  <td style={td}>
                    {/* What we owe is owed under the ORDER, so that is the
                        reference shown; the requisition sits under it (owner
                        2026-08-22). */}
                    <a href="#" onClick={(e) => { e.preventDefault();
                                                  onOpenDoc?.(r.ref); }}
                       style={{ textDecoration: "none" }}>
                      <RefStamp small>{r.ref}</RefStamp></a>
                    {r.po_ref && r.pr_ref && (
                      <div style={{ fontSize: 11, color: "var(--muted)",
                                    marginTop: 2 }}>from {r.pr_ref}</div>)}
                  </td>
                  <td style={td}>{r.payee}
                    {r.emp_no && (
                      <div style={{ fontSize: 11, color: "var(--muted)",
                        ...mono }}>{r.emp_no}</div>)}
                  </td>
                  {onSalaries ? (
                    <td style={td}>
                      {r.payable_now
                        ? <>{r.bank || "—"}{" "}
                            <span style={{ ...mono, color: "var(--muted)" }}>
                              ····{r.account_tail}</span></>
                        : <Chip tone="alert">no account on file</Chip>}
                    </td>
                  ) : <td style={td}>{r.site_code}</td>}
                  {onSalaries ? (
                    <td style={{ ...td, ...mono }}>{r.period}</td>
                  ) : (
                    <td style={td}>{r.due_date || "—"}
                      {r.overdue && <> <Chip tone="alert">overdue</Chip></>}
                      {isFinance && (
                        <button onClick={() => moveDueDate(r)}
                                title="Change the due date"
                                style={{ ...ghostButton, padding: "0 6px",
                                         fontSize: 11, marginLeft: 6 }}>
                          edit</button>)}
                    </td>
                  )}
                  <td style={{ ...td, textAlign: "right", ...mono }}>
                    {money(r.amount)}</td>
                </tr>);
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
