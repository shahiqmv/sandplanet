import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, RefStamp, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

// Outstanding credit payables on their own page (moved off the voucher builder
// — the list was accumulating and bloating that page, owner 2026-08-08). Finance
// ticks the invoice(s) to settle — when due or early — and raises a voucher for
// just those. Payables are MVR.
const money = (v) => Number(v || 0).toLocaleString("en-US",
  { minimumFractionDigits: 2 });
const mono = { fontFamily: "var(--font-mono)" };

export default function PayablesPage({ me, onOpenDoc }) {
  const isFinance = ["FINANCE", "ADMIN"].includes(me.role);
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
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

  const rows = data?.payables || [];
  const pickedRows = rows.filter((r) => picked[r.payable_id]);
  const pickedTotal = pickedRows.reduce((s, r) => s + Number(r.amount || 0), 0);
  const mvrBanks = banks.filter((b) => !b.currency || b.currency === "MVR");

  async function createVoucher() {
    if (!pickedRows.length) return;
    setBusy(true); setError(null); setMsg(null);
    try {
      const pv = await api("/payment-vouchers", { method: "POST",
        body: { payable_ids: pickedRows.map((r) => r.payable_id),
                bank_account_id: debit || null } });
      setPicked({}); setDebit("");
      setMsg(`Voucher ${pv.ref} raised for ${pickedRows.length} `
        + `payable(s) — submit it on the Payment Vouchers page.`);
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
    const reason = window.prompt("Why is the date changing?");
    if (!reason) return;
    setError(null);
    try {
      await api(`/finance/payables/${r.payable_id}/due-date`,
                { method: "POST", body: { due_date: when, reason } });
      load();
    } catch (e) { setError(e.message); }
  }

  if (!data && !error) return <div style={card}>Loading…</div>;

  return (
    <section style={{ ...card, margin: 0 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap", marginBottom: 8 }}>
        <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 18 }}>
          Outstanding payables</h2>
        <span style={{ fontSize: 13, color: "var(--muted)" }}>
          {data?.count ?? 0} on credit · MVR {money(data?.total)} total
          {data?.overdue ? ` · ${data.overdue} overdue` : ""}</span>
        <form onSubmit={(e) => { e.preventDefault(); load(); }}
              style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
          <input value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="Search vendor / ref…"
                 style={{ ...inputStyle, padding: "4px 10px", fontSize: 13,
                          width: 180 }} />
          <button type="submit" style={{ ...ghostButton, padding: "4px 12px",
            fontSize: 13 }}>Search</button>
        </form>
      </div>
      <p style={{ fontSize: 13, color: "var(--muted)", margin: "0 0 10px" }}>
        These aren't queued for payment. Tick the invoice(s) to settle — when
        due, or early if a vendor withdraws credit — and raise a voucher for
        just those. A signatory approves it on the Payment Vouchers page.
      </p>

      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}
      {msg && <p style={{ color: "var(--green-fg, #137333)", fontSize: 13,
        background: "var(--green-bg, #e6f4ea)", padding: "8px 12px",
        borderRadius: 8 }}>{msg}</p>}

      {isFinance && pickedRows.length > 0 && (
        <div style={{ display: "flex", gap: 12, alignItems: "center",
          flexWrap: "wrap", padding: "8px 12px", borderRadius: 8,
          background: "var(--sky-soft)", marginBottom: 10 }}>
          <span style={{ fontSize: 13.5 }}>{pickedRows.length} selected ·{" "}
            <strong style={mono}>MVR {money(pickedTotal)}</strong></span>
          <select value={debit} onChange={(e) => setDebit(e.target.value)}
            style={{ ...inputStyle, padding: "4px 8px", fontSize: 13,
              marginLeft: "auto" }}>
            <option value="">Debit account…</option>
            {mvrBanks.map((b) => (
              <option key={b.id} value={b.id}>{b.label}</option>
            ))}
          </select>
          <Btn variant="primary" disabled={busy}
               onClick={createVoucher}>Create voucher</Btn>
        </div>
      )}

      {rows.length === 0 ? (
        <p style={{ fontSize: 13.5, color: "var(--muted)", margin: 0 }}>
          {q.trim() ? "No payables match." : "No outstanding payables. 🎉"}</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              {isFinance && <th style={{ ...th, width: 34 }}></th>}
              <th style={th}>Ref</th><th style={th}>Vendor</th>
              <th style={th}>Site</th><th style={th}>Due</th>
              <th style={{ ...th, textAlign: "right" }}>Amount</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.payable_id} style={{ background:
                  picked[r.payable_id] ? "var(--sky-soft)" : "transparent" }}>
                  {isFinance && (
                    <td style={{ ...td, textAlign: "center" }}>
                      <input type="checkbox" checked={!!picked[r.payable_id]}
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
                  <td style={td}>{r.payee}</td>
                  <td style={td}>{r.site_code}</td>
                  <td style={td}>{r.due_date || "—"}
                    {r.overdue && <> <Chip tone="alert">overdue</Chip></>}
                    {isFinance && (
                      <button onClick={() => moveDueDate(r)}
                              title="Change the due date"
                              style={{ ...ghostButton, padding: "0 6px",
                                       fontSize: 11, marginLeft: 6 }}>
                        edit</button>)}
                  </td>
                  <td style={{ ...td, textAlign: "right", ...mono }}>
                    {money(r.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
