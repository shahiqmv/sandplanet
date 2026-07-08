import { useEffect, useState } from "react";
import { api } from "./api.js";
import { StatusChip, card, td, th } from "./ui.jsx";

// Per-role "waiting on you" queue (owner, 2026-07-08) — the landing page
// for approver roles so nothing sits unnoticed: PM approvals/verifications,
// Director awards, Purchasing actions, Finance payments.

export default function ApprovalsPage({ me, refresh, onOpen }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/approvals/pending").then(setData).catch((e) => setError(e.message));
  }, [refresh]);

  if (error) return <section style={card}>{error}</section>;
  if (!data) return <section style={card}>Loading…</section>;

  return (
    <section style={card}>
      <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
        Waiting on you
        {data.total > 0 && (
          <span style={{ background: "#c0392b", color: "#fff",
                         borderRadius: 12, padding: "2px 10px", fontSize: 13,
                         marginLeft: 10 }}>{data.total}</span>
        )}
      </h2>
      {data.total === 0 && (
        <p style={{ color: "#1a7f37", fontSize: 14 }}>
          ✓ Nothing pending — every document that needs your action has been
          dealt with.
        </p>
      )}
      {data.groups.map((g) => (
        <div key={g.title} style={{ marginBottom: 18 }}>
          <h3 style={{ fontSize: 14, color: "var(--sp-navy)",
                       margin: "0 0 6px" }}>
            {g.title} <span style={{ color: "#5a6b78", fontWeight: 400 }}>
              · {g.items.length}</span>
          </h3>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={th}>Ref</th><th style={th}>Site</th>
                <th style={th}>Project</th><th style={th}>Date</th>
                <th style={th}>Status</th><th style={th}>Action needed</th>
              </tr>
            </thead>
            <tbody>
              {g.items.map((item) => (
                <tr key={item.ref}>
                  <td style={{ ...td, width: 130 }}>
                    <a href="#" onClick={(e) => { e.preventDefault();
                                                  onOpen(item); }}
                       style={{ color: "var(--sp-navy)", fontWeight: 600 }}>
                      {item.ref}
                    </a>
                  </td>
                  <td style={td}>{item.site_code}</td>
                  <td style={td}>{item.project_code || "—"}</td>
                  <td style={td}>{item.doc_date}</td>
                  <td style={td}><StatusChip status={item.status} /></td>
                  <td style={{ ...td, color: "#5a6b78", fontSize: 12 }}>
                    {item.hint}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </section>
  );
}
