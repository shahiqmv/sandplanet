// Part payment (owner 2026-10-27): what goes on a voucher can be less than
// what is owed — the balance stays in the queue for a later voucher. These
// are the pieces the voucher builders share: the "this time" amount, the
// suppliers of a PR to pay now, and closing a balance left unpaid on purpose.
import { api } from "./api.js";

const money = (v) => Number(v || 0).toLocaleString("en-US",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// "of 1,000.00 · 400.00 paid" under an amount that is a balance
export function BalanceNote({ row }) {
  if (!row.full_amount || Number(row.full_amount) === Number(row.amount)) return null;
  return (
    <div style={{ fontSize: 11, color: "var(--muted)", fontWeight: 400 }}>
      balance of {money(row.full_amount)}
      {Number(row.paid_so_far) > 0 ? ` · ${money(row.paid_so_far)} paid` : ""}
    </div>
  );
}

// The amount this voucher pays: the whole balance unless Finance enters less.
export function PartAmount({ row, value, onChange }) {
  if (row.whole_only) {
    return <div style={{ fontSize: 11, color: "var(--muted)" }}>{row.whole_only}</div>;
  }
  const over = value !== "" && Number(value) > Number(row.amount);
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2 }}>
      <input type="number" step="0.01" min="0.01" max={row.amount}
             value={value} placeholder={money(row.amount)}
             onChange={(e) => onChange(e.target.value)}
             title="Pay part now and leave the balance for a later voucher"
             style={{ width: 120, textAlign: "right", padding: "3px 6px",
                      border: `1px solid ${over ? "var(--red-fg, #b3261e)" : "var(--line)"}`,
                      borderRadius: 4, fontFamily: "var(--font-mono, monospace)" }} />
      <span style={{ fontSize: 10.5, color: over ? "var(--red-fg, #b3261e)" : "var(--muted)" }}>
        {over ? "more than is left" : "this time — blank pays all"}</span>
    </div>
  );
}

// A PR is paid supplier by supplier: tick who goes on this voucher.
export function PrRowPicker({ row, chosen, onChange }) {
  const rows = row.pr_rows || [];
  if (rows.length < 2) return null;
  const all = !chosen || chosen.length === 0;
  const has = (id) => all || chosen.includes(id);
  const toggle = (id) => {
    const cur = all ? rows.map((r) => r.id) : chosen;
    const next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
    onChange(next.length === rows.length ? [] : next);
  };
  return (
    <div style={{ display: "flex", gap: 10, flexWrap: "wrap", fontSize: 12, marginTop: 4 }}>
      <span style={{ color: "var(--muted)" }}>Pay now:</span>
      {rows.map((r) => (
        <label key={r.id} style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
          <input type="checkbox" checked={has(r.id)} onChange={() => toggle(r.id)} />
          {r.vendor} · {money(r.amount)}
        </label>
      ))}
    </div>
  );
}

// Close what is left unpaid on purpose, with a reason.
export async function closeBalance(row) {
  const reason = window.prompt(
    `Close the balance of ${money(row.amount)} on ${row.ref}? It will not be paid `
    + "and its commitment comes off the books. Reason (e.g. supplier discount):");
  if (!reason || !reason.trim()) return false;
  const body = row.kind === "PAYABLE" ? { kind: "PAYABLE", id: row.payable_id, reason }
    : row.kind === "MILESTONE" ? { kind: "MILESTONE", id: row.milestone_id, reason }
      : { kind: "DOC", ref: row.ref, reason };
  await api("/payment-vouchers/close-balance", { method: "POST", body });
  return true;
}

// How the server names a row in `amounts`.
export const serverKey = (d) => (d.kind === "PAYABLE" ? `P:${d.payable_id}`
  : d.kind === "MILESTONE" ? `M:${d.milestone_id}` : `DOC:${d.ref}`);

// The voucher body: { amounts, pr_rows } from what was picked and entered.
export function partBody(rows, amounts, prRows, keyOf) {
  const out = { amounts: {}, pr_rows: {} };
  rows.forEach((d) => {
    const k = keyOf(d);
    const v = amounts[k];
    if (d.doc_type === "PR") {
      if (prRows[d.ref] && prRows[d.ref].length) out.pr_rows[d.ref] = prRows[d.ref];
    } else if (v !== undefined && v !== "" && Number(v) !== Number(d.amount)) {
      out.amounts[serverKey(d)] = v;
    }
  });
  return out;
}

// What a picked row puts on the voucher, for the running total.
export function pickedAmount(d, amounts, prRows, keyOf) {
  if (d.doc_type === "PR" && prRows[d.ref] && prRows[d.ref].length) {
    return (d.pr_rows || []).filter((r) => prRows[d.ref].includes(r.id))
      .reduce((s, r) => s + Number(r.amount || 0), 0);
  }
  const v = amounts[keyOf(d)];
  return v !== undefined && v !== "" ? Number(v) : Number(d.amount || 0);
}
