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
            <ActionCard key={item.ref}
              severity={severityFor(g.title)}
              refText={item.ref}
              text={`${item.site_code}${item.project_code
                ? ` · ${item.project_code}` : ""} — ${item.hint}`}
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
