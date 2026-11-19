// One voucher per payee (owner 2026-11-19): a single "Create voucher" can
// raise several. The server returns the first voucher as before plus
// `created`, every one raised; this says which.
export function raisedVouchers(pv) {
  const made = pv?.created?.length ? pv.created
    : [{ ref: pv?.ref, payee: "" }];
  if (made.length === 1) return `Voucher ${made[0].ref} raised`;
  return `${made.length} vouchers raised, one per payee — `
    + made.map((v) => `${v.ref}${v.payee ? ` (${v.payee})` : ""}`).join(", ");
}
