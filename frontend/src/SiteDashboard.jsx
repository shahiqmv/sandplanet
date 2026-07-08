import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Eyebrow, IssuedStamp, RefStamp, StampTile, StatusChip,
         buttonStyle, card, td, th } from "./ui.jsx";

const CAN_CREATE_DPR = ["SITE_ENGINEER", "SITE_ADMIN", "PM", "ADMIN"];
const CAN_CREATE_MR = ["SITE_ADMIN", "PM", "ADMIN"];

export default function SiteDashboard({ site, me, project, onNewDpr, onNewMr,
                                        onNewQa, onAttendance, onDma,
                                        onCreateGrn, onOpenDoc, refresh }) {
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
  // Today's obligations come first (design brief: dashboard order is
  // priority order) — DPR + TWS as stamp tiles
  const todayRow = register?.rows.find((r) => r.due_today) ||
    register?.rows[register.rows.length - 1];
  const dprIssued = dash?.dpr_today &&
    ["ISSUED", "VERIFIED"].includes(dash.dpr_today.status);
  const twsRef = todayRow?.tws_ref;

  return (
    <>
      <Eyebrow meta={gaps > 0 ? `${gaps} gap day${gaps === 1 ? "" : "s"} in `
                                + "the last two weeks" : null}
               metaTone="alert">
        Today's obligations
      </Eyebrow>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                    marginBottom: 14 }}>
        <StampTile title="Daily Progress Report"
          done={!!dash?.dpr_today}
          doneStamp={dash?.dpr_today && (
            <a href="#" onClick={(e) => { e.preventDefault();
                                          onOpenDoc(dash.dpr_today.ref); }}
               style={{ textDecoration: "none" }}>
              <IssuedStamp refText={dash.dpr_today.ref}
                label={dash.dpr_today.status === "VERIFIED" ? "VERIFIED"
                       : dprIssued ? "ISSUED" : "DRAFT"} />
            </a>
          )}
          dueText="Due by end of working day"
          action={canCreate && (
            <Btn variant="primary" onClick={onNewDpr}>Prepare DPR</Btn>
          )} />
        <StampTile title="Tomorrow Work Schedule"
          done={!!twsRef}
          doneStamp={twsRef && (
            <a href="#" onClick={(e) => { e.preventDefault();
                                          onOpenDoc(twsRef); }}
               style={{ textDecoration: "none" }}>
              <IssuedStamp refText={twsRef} />
            </a>
          )}
          dueText="Issue with today's DPR"
          action={canCreate && (
            <Btn variant="primary" onClick={() => onNewQa("TWS")}>
              Prepare TWS</Btn>
          )} />
      </div>

      <section style={{ ...card, display: "flex", gap: 24, alignItems: "center",
                        flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 200, fontSize: 12,
                      color: "var(--muted)" }}>
          {dash ? `${dash.unverified_dprs} DPR${dash.unverified_dprs === 1
                    ? "" : "s"} awaiting PM verification` : ""}
        </div>
        <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
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
          {["SITE_ENGINEER", "PM", "ADMIN"].includes(me.role) && (
            <button onClick={onDma}
                    style={{ ...buttonStyle, background: "#b35900" }}>
              ☀ Manpower
            </button>
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
