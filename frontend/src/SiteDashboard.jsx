import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { StatusChip, buttonStyle, card, td, th } from "./ui.jsx";

const CAN_CREATE_DPR = ["SITE_ENGINEER", "SITE_ADMIN", "PM", "ADMIN"];
const CAN_CREATE_MR = ["SITE_ADMIN", "PM", "ADMIN"];

export default function SiteDashboard({ site, me, project, onNewDpr, onNewMr,
                                        onNewQa, onAttendance, onCreateGrn,
                                        onOpenDoc, refresh }) {
  const [dash, setDash] = useState(null);
  const [register, setRegister] = useState(null);
  const [mrs, setMrs] = useState([]);
  const [qaDocs, setQaDocs] = useState([]);
  const [incomingLms, setIncomingLms] = useState([]);

  const projectParam = project ? `&project=${project.id}` : "";

  const load = useCallback(() => {
    api(`/dashboards/site/${site.id}`).then(setDash);
    api(`/registers/dpr-tws?site=${site.id}${projectParam}`)
      .then(setRegister);
    api(`/documents/list?site=${site.id}&doc_type=MR`).then(setMrs);
    Promise.all([
      api(`/documents/list?site=${site.id}&doc_type=IR${projectParam}`),
      api(`/documents/list?site=${site.id}&doc_type=MAR${projectParam}`),
    ]).then(([irs, mars]) => setQaDocs(
      [...irs, ...mars].sort((a, b) => b.created_at.localeCompare(a.created_at))
    ));
    api(`/documents/list?site=${site.id}&doc_type=LM&status=DEPARTED`)
      .then(setIncomingLms);
  }, [site.id, projectParam]);

  useEffect(load, [load, refresh]);

  const canCreate = CAN_CREATE_DPR.includes(me.role);
  const canMr = CAN_CREATE_MR.includes(me.role);
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
        <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {canCreate && (
            <>
              <button onClick={onNewDpr} style={buttonStyle}>+ DPR</button>
              <button onClick={() => onNewQa("TWS")} style={buttonStyle}>
                + TWS</button>
            </>
          )}
          {["SITE_ENGINEER", "PM", "ADMIN"].includes(me.role) && (
            <>
              <button onClick={() => onNewQa("IR")} style={buttonStyle}>
                + IR</button>
              <button onClick={() => onNewQa("MAR")} style={buttonStyle}>
                + MAR</button>
            </>
          )}
          {canMr && (
            <button onClick={onNewMr} style={buttonStyle}>+ MR</button>
          )}
          {["SITE_ADMIN", "SITE_ENGINEER", "PM", "FINANCE", "HO_HR", "ADMIN"]
            .includes(me.role) && (
            <button onClick={onAttendance}
                    style={{ ...buttonStyle, background: "#1a7f37" }}>
              🕐 Attendance
            </button>
          )}
        </span>
      </section>

      {qaDocs.length > 0 && (
        <section style={card}>
          <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 15 }}>
            Inspections &amp; Material Approvals
          </h2>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {qaDocs.slice(0, 8).map((d) => (
                <tr key={d.ref}>
                  <td style={{ ...td, width: 130 }}>
                    <a href="#" onClick={(e) => { e.preventDefault();
                                                  onOpenDoc(d.ref); }}
                       style={{ color: "var(--sp-navy)", fontWeight: 600 }}>
                      {d.ref}
                    </a>
                  </td>
                  <td style={td}>{d.doc_date}</td>
                  <td style={td}>
                    {d.payload?.discipline || d.payload?.material_description
                      ?.slice(0, 50) || ""}
                  </td>
                  <td style={{ ...td, textAlign: "right" }}>
                    <StatusChip status={d.is_void ? "VOID" : d.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {incomingLms.length > 0 && (
        <section style={{ ...card, background: "#fff8e6" }}>
          <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 15 }}>
            🚤 Incoming boats — manifests in transit
          </h2>
          {incomingLms.map((lm) => (
            <div key={lm.ref} style={{ display: "flex", gap: 12,
                                       alignItems: "center", padding: "4px 0" }}>
              <a href="#" onClick={(e) => { e.preventDefault();
                                            onOpenDoc(lm.ref); }}
                 style={{ color: "var(--sp-navy)", fontWeight: 600 }}>
                {lm.ref}
              </a>
              <span style={{ fontSize: 13, color: "#5a6b78" }}>
                {lm.payload?.vessel} · expected {lm.payload?.expected_arrival}
              </span>
              {canMr && (
                <button onClick={() => onCreateGrn(lm.ref)}
                        style={{ ...buttonStyle, marginLeft: "auto",
                                 padding: "4px 12px", fontSize: 13 }}>
                  Receive → New GRN
                </button>
              )}
            </div>
          ))}
        </section>
      )}

      {mrs.length > 0 && (
        <section style={card}>
          <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 15 }}>
            Material Requisitions
          </h2>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {mrs.slice(0, 8).map((mr) => (
                <tr key={mr.ref}>
                  <td style={{ ...td, width: 130 }}>
                    <a href="#" onClick={(e) => { e.preventDefault();
                                                  onOpenDoc(mr.ref); }}
                       style={{ color: "var(--sp-navy)", fontWeight: 600 }}>
                      {mr.ref}
                    </a>
                  </td>
                  <td style={td}>{mr.doc_date}</td>
                  <td style={td}>{mr.payload?.planned_loading}</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    <StatusChip status={mr.is_void ? "VOID" : mr.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section style={card}>
        <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          DPR &amp; TWS Register — last 14 days
          {project && (
            <span style={{ color: "#5a6b78", fontWeight: 400 }}>
              {" "}· {project.code}</span>
          )}
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
