// Finance app — small shared pieces.
export const money = (v) => Number(v || 0).toLocaleString("en-US",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });
// A blank instead of 0.00, so a ledger reads like a ledger.
export const amt = (v) => (Number(v) ? money(v) : "");
export const fmtDate = (s) => (s ? new Date(`${String(s).slice(0, 10)}T00:00`)
  .toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "—");
export const today = () => {
  const t = new Date();
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
};
// QuickBooks' account types, in its order.
export const TYPE_ORDER = ["BANK", "AR", "OTHER_CURRENT_ASSET", "FIXED_ASSET", "OTHER_ASSET", "AP", "CREDIT_CARD",
  "OTHER_CURRENT_LIABILITY", "LONG_TERM_LIABILITY", "EQUITY", "INCOME", "COGS", "EXPENSE", "OTHER_INCOME",
  "OTHER_EXPENSE"];
export const KIND_TONE = { MANUAL: "info", OPENING: "ok", REVERSAL: "warn", AUTO: "info" };

// Accounts as a depth-first list with their indent, for a chart or a picker.
export function tree(accounts) {
  const kids = {};
  accounts.forEach((a) => { (kids[a.parent || 0] = kids[a.parent || 0] || []).push(a); });
  const out = [];
  const walk = (pid, depth) => (kids[pid] || [])
    .sort((x, y) => (TYPE_ORDER.indexOf(x.type) - TYPE_ORDER.indexOf(y.type))
      || x.code.localeCompare(y.code, undefined, { numeric: true }))
    .forEach((a) => { out.push({ ...a, depth }); walk(a.id, depth + 1); });
  walk(0, 0);
  return out;
}
