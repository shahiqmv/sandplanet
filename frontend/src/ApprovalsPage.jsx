import { useEffect, useState } from "react";
import { api } from "./api.js";
import { ActionCard, Btn, Eyebrow, StatusChip, card } from "./ui.jsx";

// Per-role "waiting on you" queue (owner, 2026-07-08) — the landing page
// for approver roles. Design brief: action cards, severity then age.

const GROUP_SEVERITY = [
  ["To approve", "warn"], ["To award", "warn"], ["Payments", "warn"],
  ["To issue — morning", "warn"],
];

function severityFor(title) {
  const hit = GROUP_SEVERITY.find(([prefix]) => title.startsWith(prefix));
  return hit ? hit[1] : "info";
}

function ageLine(docDate) {
  const days = Math.floor((Date.now() - new Date(docDate).getTime()) / 864e5);
  if (days <= 0) return "today";
  return `${days} day${days === 1 ? "" : "s"} old`;
}

const money = (v) => Number(v).toLocaleString("en-US",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// What the row actually says. It used to be
// `${site} · ${project} — ${hint}`, which for a payment voucher (no site, no
// project) rendered "— — Approve the batch or query lines" three times over,
// telling a signatory nothing about what they were approving (owner
// 2026-08-16). Lead with the money where there is money, and drop the
// placeholders where a document has no site.
function RowText({ item }) {
  const where = [item.site_code, item.project_code]
    .filter((x) => x && x !== "—").join(" · ");
  return (
    <>
      {item.amount != null && (
        // Never hard-code the currency here. An import order is priced in the
        // supplier's currency and a payment request can be raised in USD, so
        // a printed "MVR" showed a signatory a figure fifteen times smaller
        // than the one they were authorising (owner 2026-08-30).
        <b style={{ color: "var(--sp-navy)" }}>
          {item.currency || "MVR"} {money(item.amount)}
        </b>
      )}
      {item.amount != null && (where || item.hint) && " · "}
      {where && <span>{where}</span>}
      {where && item.hint && " — "}
      {item.hint && (
        <span style={{ color: item.amount != null ? "var(--muted)"
                                                  : undefined }}>
          {item.hint}
        </span>
      )}
    </>
  );
}

export default function ApprovalsPage({ me, refresh, onOpen }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/approvals/pending").then(setData).catch((e) => setError(e.message));
  }, [refresh]);

  if (error) return <section style={card}>{error}</section>;
  if (!data) return <section style={card}>Loading…</section>;

  return (
    <>
      {data.total === 0 && (
        <section style={card}>
          <p style={{ color: "var(--green-fg)", fontSize: 14, margin: 0 }}>
            ✓ Nothing waiting on you — every document that needs your action
            has been dealt with.
          </p>
        </section>
      )}
      {data.groups.map((g) => (
        <div key={g.title}>
          <Eyebrow meta={String(g.items.length)}
                   metaTone={severityFor(g.title) === "warn" ? "alert" : null}>
            {g.title}
          </Eyebrow>
          {g.items.map((item) => (
            /* `ref` alone is not unique — two sites' payroll runs for the
               same month carry the same label — so include the row's own id */
            <ActionCard key={`${item.doc_type}-${item.run_id ?? item.ref}`}
              severity={severityFor(g.title)}
              refText={item.ref}
              text={<RowText item={item} />}
              meta={`${item.doc_date} · ${ageLine(item.doc_date)}`}
              chip={<StatusChip status={item.status} />}
              button={
                <Btn variant={severityFor(g.title) === "warn"
                              ? "navy" : "secondary"}
                     onClick={() => onOpen(item)}
                     style={{ padding: "6px 14px", fontSize: 13 }}>
                  Open {item.doc_type}
                </Btn>
              } />
          ))}
        </div>
      ))}
    </>
  );
}
