import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { StatusChip, buttonStyle, card, td, th } from "./ui.jsx";

const CAN_CREATE_DPR = ["SITE_ENGINEER", "SITE_ADMIN", "PM", "ADMIN"];

export default function SiteDashboard({ site, me, onNewDpr, onOpenDoc, refresh }) {
  const [dash, setDash] = useState(null);
  const [register, setRegister] = useState(null);

  const load = useCallback(() => {
    api(`/dashboards/site/${site.id}`).then(setDash);
    api(`/registers/dpr-tws?site=${site.id}`).then(setRegister);
  }, [site.id]);

  useEffect(load, [load, refresh]);

  const canCreate = CAN_CREATE_DPR.includes(me.role);
  const gaps = register?.rows.filter((r) => r.gap).length || 0;

  return (
    <>
      <section style={{ ...card, display: "flex", gap: 24, alignItems: "center",
                        flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          {dash?.dpr_today ? (
            <span style={{ fontSize: 14 }}>
              DPR today:{" "}
              <a href="#" onClick={(e) => { e.preventDefault();
                                            onOpenDoc(dash.dpr_today.ref); }}
                 style={{ color: "var(--sp-navy)", fontWeight: 600 }}>
                {dash.dpr_today.ref}
              </a>{" "}
              <StatusChip status={dash.dpr_today.status} />
            </span>
          ) : (
            <span style={{ color: "#b35900", fontSize: 14, fontWeight: 600 }}>
              ⚠ No DPR issued today
            </span>
          )}
          <div style={{ fontSize: 12, color: "#5a6b78", marginTop: 4 }}>
            {dash ? `${dash.unverified_dprs} awaiting PM verification · ` : ""}
            {gaps} gap day{gaps === 1 ? "" : "s"} in the last two weeks
          </div>
        </div>
        {canCreate && (
          <button onClick={onNewDpr} style={buttonStyle}>+ New DPR</button>
        )}
      </section>

      <section style={card}>
        <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          DPR &amp; TWS Register — last 14 days
        </h2>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={th}>Date</th><th style={th}>Day</th>
                <th style={th}>DPR Ref</th><th style={th}>Status</th>
                <th style={th}>TWS Ref</th>
              </tr>
            </thead>
            <tbody>
              {register?.rows.slice().reverse().map((row) => (
                <tr key={row.date}
                    style={row.gap ? { background: "#fdeceb" }
                          : row.due_today ? { background: "#fff8e6" } : {}}>
                  <td style={td}>{row.date}</td>
                  <td style={td}>{row.day}</td>
                  <td style={td}>
                    {row.dpr_ref ? (
                      <a href="#" onClick={(e) => { e.preventDefault();
                                                    onOpenDoc(row.dpr_ref); }}
                         style={{ color: "var(--sp-navy)", fontWeight: 600 }}>
                        {row.dpr_ref}
                      </a>
                    ) : row.gap ? (
                      <span style={{ color: "#c0392b", fontWeight: 600 }}>
                        — missing —
                      </span>
                    ) : row.due_today ? (
                      <span style={{ color: "#b35900" }}>due today</span>
                    ) : "—"}
                  </td>
                  <td style={td}><StatusChip status={row.dpr_status} /></td>
                  <td style={td}>{row.tws_ref || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
