import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { DOC_LABELS } from "./LineDoc.jsx";
import { Chip, Eyebrow, Pager, RefStamp, Stat, StatusChip, buttonStyle, card,
         ghostButton, inputStyle, td, th } from "./ui.jsx";
const money = (v) => Number(v || 0).toLocaleString("en-US",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// A paid PR stands out on the register (owner 2026-11-17): Procurement
// arranges the collection and the loading once its suppliers are paid.
const prPaidState = (row) => {
  const cash = Number(row.pay_cash_rows || 0);
  const paid = Number(row.pay_paid_rows || 0);
  if (!cash || row.status === "VOID") return null;
  return paid >= cash ? "PAID" : paid > 0 ? "PART" : "UNPAID";
};
const prPaidStyle = (row) => ({
  PAID: { background: "#e8f5ec", boxShadow: "inset 3px 0 0 #2e9e57" },
  PART: { background: "#fff6e0", boxShadow: "inset 3px 0 0 #d9a520" },
}[prPaidState(row)] || {});
const shortDay = (iso) => (iso ? new Date(iso).toLocaleDateString("en-GB",
  { day: "numeric", month: "short" }) : "");

// The registers are drawn a page at a time (owner 2026-11-25): sending the
// newest 300 rows was slow and silently dropped everything older — with 490
// PRs the list stopped at PR-191. The search runs on the server, across the
// whole register.
const PAGE = 50;
// Opening a document unmounts the dashboard; the search and the page each
// register was on are kept here so closing it returns to the same place.
const kept = { q: "", offsets: {} };

function PrPaid({ row }) {
  const state = prPaidState(row);
  if (!state) return <span style={{ color: "var(--faint)" }}>—</span>;
  if (state === "UNPAID") {
    return <span style={{ fontSize: 12, color: "var(--muted)" }}>
      not paid</span>;
  }
  const paid = state === "PAID";
  return (
    <span style={{ display: "inline-flex", flexDirection: "column", gap: 1 }}>
      <span style={{ fontSize: 11.5, fontWeight: 700, padding: "1px 8px",
        borderRadius: 10, alignSelf: "flex-start",
        background: paid ? "#2e9e57" : "#d9a520", color: "#fff" }}>
        {paid ? "Paid" : `${row.pay_paid_rows} of ${row.pay_cash_rows} paid`}
      </span>
      {row.pay_last_at && <span style={{ fontSize: 10.5,
        color: "var(--muted)" }}>{shortDay(row.pay_last_at)}</span>}
    </span>
  );
}

export default function HODashboard({ me, tab, onTab, onOpenDoc, onNew,
                                     onNewPayment,
                                      onPmrRegister, onVessels, refresh }) {
  const [stats, setStats] = useState(null);
  // The tab lives in App, not here. Opening a document unmounts this
  // dashboard, so a tab held locally was lost on the way back: you opened a
  // PO from the PO register, closed it, and landed on MR
  // (owner 2026-09-01).
  const setTab = onTab;
  const isPo = tab === "PO";
  const isPr = tab === "PR";
  const [rows, setRows] = useState([]);
  const [pending, setPending] = useState([]);
  // Lengthy registers need finding, not scrolling: one box matches the
  // reference, site, status, supplier, linked refs and who raised it
  // (owner 2026-09-15). Words are ANDed, so "VKR PO-14" narrows twice;
  // on the PR register "paid" finds PRs with a payment and "part" the
  // half-paid ones (owner 2026-11-17). The server does the matching, over
  // the whole register and not only the page on screen.
  const [q, setQ] = useState(kept.q);
  const [query, setQuery] = useState(kept.q.trim());
  useEffect(() => {
    kept.q = q;
    const t = setTimeout(() => setQuery(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [offsets, setOffsets] = useState(kept.offsets);
  const at = `${tab}|${query}`;
  const offset = offsets[at] || 0;
  const setOffset = (o) => setOffsets((m) => {
    kept.offsets = { ...m, [at]: o };
    return kept.offsets;
  });
  const asked = useRef(0);

  useEffect(() => {
    api("/dashboards/ho").then(setStats).catch(() => setStats(null));
  }, [tab, refresh]);

  useEffect(() => {
    if (tab === "PENDING") {
      api("/pending-items").then(setPending);
      return;
    }
    const mine = ++asked.current;       // a slower, older answer is dropped
    const p = new URLSearchParams({ limit: PAGE, offset });
    if (query) p.set("q", query);
    setBusy(true);
    api(`/registers/${tab.toLowerCase()}?${p}`).then((d) => {
      if (mine !== asked.current) return;
      setRows(d.rows);
      setTotal(d.total);
      // a remembered page beyond the end of a register that has since
      // shrunk falls back to the newest
      if (d.rows.length === 0 && d.total > 0 && offset > 0) {
        setOffsets((m) => {
          kept.offsets = { ...m, [`${tab}|${query}`]: 0 };
          return kept.offsets;
        });
      }
    }).catch(() => {}).finally(() => {
      if (mine === asked.current) setBusy(false);
    });
  }, [tab, query, offset, refresh]);

  const canPurchase = ["HO_PURCHASING", "ADMIN"].includes(me.role);

  return (
    <>
      <Eyebrow>Purchasing overview</Eyebrow>
      <section style={{ ...card, display: "flex", gap: 18, flexWrap: "wrap" }}>
        <Stat label="MRs awaiting action" value={stats?.mrs_awaiting_action ?? "–"}
              tone={stats?.mrs_awaiting_action ? "warn" : "ok"}
              context={stats?.mrs_awaiting_action
                ? "process before the next loading" : "queue clear"} />
        <Stat label="PRs with Director" value={stats?.prs_awaiting_approval ?? "–"}
              tone={stats?.prs_awaiting_approval ? "warn" : "ok"}
              context={stats?.prs_awaiting_approval
                ? "awaiting award approval" : "none waiting"} />
        <Stat label="PRs awaiting payment" value={stats?.prs_awaiting_payment ?? "–"}
              tone={stats?.prs_awaiting_payment ? "warn" : "ok"}
              context={stats?.prs_awaiting_payment
                ? "Finance to record slips/POs" : "all settled"} />
        <Stat label="Boats in transit" value={stats?.lms_in_transit ?? "–"}
              tone="info"
              context={stats?.lms_in_transit
                ? "manifests at sea — GRN on arrival" : "none at sea"} />
        <Stat label="Pending items" value={stats?.pending_items_open ?? "–"}
              tone={stats?.pending_items_open ? "warn" : "ok"}
              context={stats?.pending_items_open
                ? "plan onto the next manifest" : "log clear"} />
        <Stat label="GRN shortages" value={stats?.grn_shortages ?? "–"}
              tone={stats?.grn_shortages ? "alert" : "ok"}
              context={stats?.grn_shortages
                ? "chase vendors within 24h" : "none open"} />
        <div onClick={stats?.pmrs_pending_order && onPmrRegister
               ? onPmrRegister : undefined}
             style={{ cursor: stats?.pmrs_pending_order && onPmrRegister
               ? "pointer" : "default" }}>
          <Stat label="Import requests to order"
                value={stats?.pmrs_pending_order ?? "–"}
                tone={stats?.pmrs_pending_order ? "alert" : "ok"}
                context={stats?.pmrs_pending_order
                  ? "sized & released — raise the overseas order"
                  : "none waiting"} />
        </div>
      </section>

      <Eyebrow>Registers</Eyebrow>
      <section style={card}>
        <div style={{ display: "flex", gap: 8, alignItems: "center",
                      flexWrap: "wrap", marginBottom: 12 }}>
          {["MR", "PR", "PO", "LM", "GRN", "PENDING"].map((key) => (
            <button key={key} onClick={() => setTab(key)}
                    style={tab === key ? buttonStyle
                                       : { ...ghostButton }}>
              {key === "PENDING" ? "Pending Items" : `${key} Register`}
            </button>
          ))}
          {tab !== "PENDING" && (
            <input value={q} onChange={(e) => setQ(e.target.value)}
                   placeholder={`Search ${tab}s — number, site, status, supplier…`}
                   style={{ ...inputStyle, width: 280, marginLeft: 4 }} />)}
          <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            {onVessels && (
              <button onClick={onVessels} style={ghostButton}
                      title="Live positions of local vessels (FollowMe)">
                🛥️ Vessels nearby</button>
            )}
            {canPurchase && (
              <>
                <button onClick={() => onNew("PR")} style={ghostButton}>
                  + New PR</button>
                <button onClick={() => onNew("LM")} style={ghostButton}>
                  + New LM</button>
              </>
            )}
            {onNewPayment && (
              <button onClick={onNewPayment} style={ghostButton}>
                + Payment request</button>
            )}
          </span>
        </div>

        {tab === "PENDING" ? (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>Site</th><th style={th}>Item</th>
              <th style={th}>Qty Pending</th><th style={th}>From LM</th>
              <th style={th}>Reason</th><th style={th}>Status</th>
              <th style={th}>Cleared</th>
            </tr></thead>
            <tbody>
              {pending.map((row) => (
                <tr key={row.id}>
                  <td style={td}>{row.site_code}</td>
                  <td style={td}>{row.description}</td>
                  <td style={td}>{row.qty_pending} {row.unit}</td>
                  <td style={td}>
                    <a href="#" onClick={(e) => { e.preventDefault();
                                                  onOpenDoc(row.lm_ref); }}
                       style={{ textDecoration: "none" }}>
                      <RefStamp small>{row.lm_ref}</RefStamp></a>
                  </td>
                  <td style={td}>{row.reason}</td>
                  <td style={td}>
                    <Chip tone={row.status === "PENDING" ? "warn" : "ok"}>
                      {row.status}</Chip>
                  </td>
                  <td style={td}>
                    {row.cleared_lm_ref || row.cleared_reason || "—"}
                  </td>
                </tr>
              ))}
              {pending.length === 0 && (
                <tr><td style={td} colSpan={7}>No pending items. 🎉</td></tr>
              )}
            </tbody>
          </table>
        ) : (
          <>
          <Pager offset={offset} total={total} count={rows.length}
                 busy={busy} onPage={setOffset} page={PAGE} />
          <table style={{ width: "100%", borderCollapse: "collapse",
                          opacity: busy ? 0.6 : 1 }}>
            <thead><tr>
              <th style={th}>Ref</th><th style={th}>Rev</th>
              <th style={th}>Date</th><th style={th}>Site</th>
              {/* An order is read by who it is with and what it is worth
                  (owner 2026-09-01). */}
              {isPo && <th style={th}>Supplier</th>}
              {isPo && <th style={{ ...th, textAlign: "right" }}>Value</th>}
              {isPo && <th style={th}>Terms</th>}
              <th style={th}>Status</th>
              {/* how far the suppliers are paid (owner 2026-11-17) */}
              {isPr && <th style={th}>Payment</th>}
              <th style={th}>Refs</th>
              {/* Nothing in a PO payload reaches the summary whitelist, so
                  on this tab the column is only width (owner 2026-09-01). */}
              {!isPo && <th style={th}>Details</th>}
              <th style={th}>By</th>
            </tr></thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={`${row.ref}-${row.rev}-${i}`}
                    style={{ ...(row.is_current_rev ? {} : { opacity: 0.55 }),
                             ...(isPr ? prPaidStyle(row) : {}) }}>
                  <td style={td}>
                    <a href="#" onClick={(e) => { e.preventDefault();
                                                  onOpenDoc(row.ref); }}
                       style={{ textDecoration: "none" }}>
                      <RefStamp small>{row.ref}</RefStamp>
                    </a>
                  </td>
                  <td style={{ ...td, fontFamily: "var(--font-mono)",
                               color: "var(--faint)", fontSize: 12 }}>
                    {row.rev}</td>
                  <td style={td}>{row.date}</td>
                  <td style={td}>{row.site_code}</td>
                  {isPo && (
                    <td style={td}>
                      <div style={{ fontWeight: 600 }}>
                        {row.supplier || "—"}</div>
                      {row.supplier_contact && (
                        <div style={{ fontSize: 11, color: "var(--muted)" }}>
                          {row.supplier_contact}</div>
                      )}
                      {row.source_kind && (
                        <div style={{ fontSize: 10.5, color: "var(--muted)" }}>
                          {row.source_kind === "IMPORT" ? "import" : "local"}
                          {/* The ref only earns its place when Refs is not
                              already showing it. */}
                          {row.source_ref
                           && !Object.values(row.links).flat()
                                .includes(row.source_ref)
                            ? ` · ${row.source_ref}` : ""}
                        </div>
                      )}
                    </td>
                  )}
                  {isPo && (
                    <td style={{ ...td, textAlign: "right",
                                 whiteSpace: "nowrap",
                                 fontVariantNumeric: "tabular-nums" }}>
                      {Number(row.order_value) > 0 ? (
                        <>
                          {money(row.order_value)}
                          <span style={{ fontSize: 10.5,
                                         color: "var(--muted)" }}>
                            {" "}{row.currency}</span>
                        </>
                      ) : "—"}
                    </td>
                  )}
                  {isPo && (
                    <td style={{ ...td, fontSize: 12 }}>
                      {row.payment_terms || "—"}
                      {row.expected_delivery && (
                        <div style={{ fontSize: 10.5, color: "var(--muted)" }}>
                          due {row.expected_delivery}</div>
                      )}
                    </td>
                  )}
                  <td style={td}><StatusChip status={row.status} /></td>
                  {isPr && <td style={{ ...td, whiteSpace: "nowrap" }}>
                    <PrPaid row={row} /></td>}
                  <td style={{ ...td, fontSize: 12 }}>
                    {Object.values(row.links).flat().join(" · ")}
                  </td>
                  {!isPo && (
                    <td style={{ ...td, fontSize: 12 }}>
                      {Object.entries(row.payload_summary)
                        .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`)
                        .join(" · ")}
                    </td>
                  )}
                  <td style={td}>{row.created_by}</td>
                </tr>
              ))}
              {rows.length === 0 && !busy && !query && (
                <tr><td style={td} colSpan={isPo ? 10 : isPr ? 9 : 8}>
                  No {DOC_LABELS[tab]}s yet.</td></tr>
              )}
              {rows.length === 0 && !busy && query && (
                <tr><td style={td} colSpan={isPo ? 10 : isPr ? 9 : 8}>
                  Nothing matches “{query}” in the {DOC_LABELS[tab]}{" "}
                  register.</td></tr>
              )}
            </tbody>
          </table>
          {rows.length > 15 && (
            <Pager offset={offset} total={total} count={rows.length}
                   busy={busy} onPage={setOffset} page={PAGE} />)}
          </>
        )}
      </section>
    </>
  );
}
