import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Eyebrow, IssuedStamp, RefStamp, StampTile, StatusChip,
         buttonStyle, card, ghostButton, td, th } from "./ui.jsx";

const CAN_CREATE_DPR = ["SITE_ENGINEER", "SITE_ADMIN", "PM", "ADMIN"];
const CAN_CREATE_MR = ["SITE_ADMIN", "PM", "ADMIN"];

export default function SiteDashboard({ site, me, project, onNewDpr, onNewMr,
                                        onNewQa, onAttendance, onDma,
                                        onManpower, onNewPyr, onPyrRegister,
                                        onPettyCash, onStock,
                                        onCreateGrn, onOpenDoc, refresh }) {
  const [dash, setDash] = useState(null);
  const [register, setRegister] = useState(null);
  const [mrs, setMrs] = useState([]);
  const [qaDocs, setQaDocs] = useState([]);
  const [incomingLms, setIncomingLms] = useState([]);
  const [pyrs, setPyrs] = useState([]);
  const [stock, setStock] = useState(null);

  const projectParam = project ? `&project=${project.id}` : "";

  const load = useCallback(() => {
    api(`/dashboards/site/${site.id}`).then(setDash);
    api(`/registers/dpr-tws?site=${site.id}${projectParam}`)
      .then(setRegister);
    api(`/documents/list?site=${site.id}&doc_type=MR`).then(setMrs);
    api(`/documents/list?site=${site.id}&doc_type=PYR`).then(setPyrs)
      .catch(() => setPyrs([]));
    Promise.all([
      api(`/documents/list?site=${site.id}&doc_type=IR${projectParam}`),
      api(`/documents/list?site=${site.id}&doc_type=MAR${projectParam}`),
    ]).then(([irs, mars]) => setQaDocs(
      [...irs, ...mars].sort((a, b) => b.created_at.localeCompare(a.created_at))
    ));
    api(`/documents/list?site=${site.id}&doc_type=LM&status=DEPARTED`)
      .then(setIncomingLms);
    api(`/stock/${site.id}`).then(setStock).catch(() => setStock(null));
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
        <StampTile title="Manpower Allocation"
          done={dash?.dma_today?.status === "ISSUED"}
          doneStamp={dash?.dma_today && (
            <a href="#" onClick={(e) => { e.preventDefault(); onDma(); }}
               style={{ textDecoration: "none" }}>
              <IssuedStamp refText={dash.dma_today.ref} />
            </a>
          )}
          dueText={dash?.dma_today
            ? "Drafted — PM issues the allocation"
            : "Allocate the crew from yesterday's TWS"}
          action={["SITE_ENGINEER", "PM", "ADMIN"].includes(me.role) && (
            <Btn variant="primary" onClick={onDma}>
              {dash?.dma_today ? "Open allocation" : "Allocate manpower"}
            </Btn>
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
          {["SITE_ADMIN", "SITE_ENGINEER", "PM", "ADMIN"].includes(me.role) && (
            <button onClick={onNewPyr} style={buttonStyle}>+ Payment</button>
          )}
          {["SITE_ADMIN", "PM", "FINANCE", "ADMIN"].includes(me.role) && (
            <button onClick={onPettyCash} style={buttonStyle}>💰 Petty Cash</button>
          )}
          {["SITE_ADMIN", "SITE_ENGINEER", "PM", "ADMIN"].includes(me.role) && (
            <button onClick={onStock} style={buttonStyle}>📦 Stock</button>
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

      {dash?.manpower && dash.manpower.roster_total > 0 && (
        <section style={card}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10,
                        flexWrap: "wrap" }}>
            <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 15 }}>
              👷 Manpower today
            </h2>
            <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
              {dash.manpower.roster_total} on roster
              {dash.manpower.attendance_entered ? (
                <> · <b style={{ color: "var(--green-fg)" }}>
                  {dash.manpower.present} present</b>
                {dash.manpower.absent > 0 && (
                  <> · <b style={{ color: "var(--red-fg)" }}>
                    {dash.manpower.absent} absent/leave</b></>
                )}
                {dash.manpower.allocated != null && (
                  <> · {dash.manpower.allocated} allocated to tasks
                  {dash.manpower.idle > 0 && (
                    <> · <b style={{ color: "var(--amber-fg)" }}>
                      {dash.manpower.idle} idle</b></>
                  )}</>
                )}</>
              ) : " · attendance not entered yet today"}
            </span>
            <a href="#" onClick={(e) => { e.preventDefault(); onManpower(); }}
               style={{ marginLeft: "auto", fontSize: 12.5,
                        color: "var(--navy)" }}>
              Full breakdown →
            </a>
          </div>
          {dash.manpower.dpr_mismatch && (
            <p style={{ fontSize: 12, color: "var(--amber-fg)",
                        margin: "6px 0 0" }}>
              ⚠ Today's DPR reports {dash.manpower.dpr_total} manpower but
              attendance shows {dash.manpower.present} present — worth a
              check before the client asks.
            </p>
          )}
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap",
                        marginTop: 10 }}>
            {dash.manpower.top.map((c) => (
              <div key={c.name} style={{ flex: 1, minWidth: 140 }}>
                <div style={{ fontSize: 12, marginBottom: 2 }}>
                  {c.name}{" "}
                  <span style={{ fontFamily: "var(--font-mono)",
                                 color: "var(--muted)" }}>
                    {dash.manpower.attendance_entered
                      ? `${c.present}/${c.roster}` : c.roster}
                  </span>
                </div>
                <div style={{ background: "var(--row-line)", borderRadius: 4,
                              height: 9 }}>
                  <div style={{ height: 9, borderRadius: 4,
                                width: `${100 * (dash.manpower
                                  .attendance_entered ? c.present : c.roster)
                                  / Math.max(c.roster, 1)}%`,
                                background: "var(--sky)" }} />
                </div>
              </div>
            ))}
            {dash.manpower.others_roster > 0 && (
              <div style={{ fontSize: 12, color: "var(--faint)",
                            alignSelf: "end" }}>
                +{dash.manpower.others_roster} in other categories
              </div>
            )}
          </div>
        </section>
      )}

      {/* Receiving goods is a site responsibility — the boats/GRN section
          is always visible, never lost behind an empty list (owner,
          2026-07-08). The GRN prefills its lines from the manifest. */}
      <section style={{ ...card,
                        background: incomingLms.length ? "#fff8e6"
                                                       : "var(--paper)" }}>
        <h2 style={{ marginTop: 0, color: "var(--navy)", fontSize: 15 }}>
          🚤 Incoming boats &amp; goods receiving
        </h2>
        {incomingLms.map((lm) => (
          <div key={lm.ref} style={{ display: "flex", gap: 12,
                                     alignItems: "center", padding: "4px 0",
                                     flexWrap: "wrap" }}>
            <a href="#" onClick={(e) => { e.preventDefault();
                                          onOpenDoc(lm.ref); }}
               style={{ textDecoration: "none" }}>
              <RefStamp>{lm.ref}</RefStamp>
            </a>
            <span style={{ fontSize: 13, color: "var(--muted)" }}>
              {lm.payload?.vessel} · expected {lm.payload?.expected_arrival}
            </span>
            {canMr && (
              <Btn variant="navy" onClick={() => onCreateGrn(lm.ref)}
                   style={{ marginLeft: "auto", padding: "4px 12px",
                            fontSize: 13 }}>
                Receive → New GRN
              </Btn>
            )}
          </div>
        ))}
        {incomingLms.length === 0 && (
          <p style={{ fontSize: 13, color: "var(--muted)", margin: 0 }}>
            No manifests in transit right now. When Head Office despatches a
            boat, it appears here — receiving it creates the GRN with the
            manifest's lines pre-filled.
          </p>
        )}
      </section>

      {(dash?.materials_in_transit_count > 0 ||
        dash?.pending_materials_count > 0) && (
        <section style={card}>
          <h2 style={{ marginTop: 0, color: "var(--navy)", fontSize: 15 }}>
            📦 Materials yet to reach the site
          </h2>
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 240 }}>
              <div style={{ fontSize: 12.5, fontWeight: 700,
                            color: "var(--navy)", marginBottom: 4 }}>
                On the water · {dash.materials_in_transit_count}
              </div>
              {dash.materials_in_transit.map((m, i) => (
                <div key={i} style={{ fontSize: 12.5, padding: "2px 0",
                                      borderTop: "1px solid var(--row-line)",
                                      display: "flex", gap: 8 }}>
                  <span style={{ flex: 1 }}>{m.description}</span>
                  <span style={{ fontFamily: "var(--font-mono)",
                                 color: "var(--muted)" }}>
                    {m.qty} {m.unit}</span>
                </div>
              ))}
              {dash.materials_in_transit_count >
                dash.materials_in_transit.length && (
                <div style={{ fontSize: 11.5, color: "var(--faint)" }}>
                  … and {dash.materials_in_transit_count
                         - dash.materials_in_transit.length} more lines
                </div>
              )}
              {dash.materials_in_transit_count === 0 && (
                <div style={{ fontSize: 12, color: "var(--faint)" }}>
                  nothing in transit</div>
              )}
            </div>
            <div style={{ flex: 1, minWidth: 240 }}>
              <div style={{ fontSize: 12.5, fontWeight: 700,
                            color: "var(--amber-fg)", marginBottom: 4 }}>
                Pending with Head Office · {dash.pending_materials_count}
              </div>
              {dash.pending_materials.map((m, i) => (
                <div key={i} style={{ fontSize: 12.5, padding: "2px 0",
                                      borderTop: "1px solid var(--row-line)",
                                      display: "flex", gap: 8 }}>
                  <span style={{ flex: 1 }}>{m.description}</span>
                  <span style={{ fontFamily: "var(--font-mono)",
                                 color: "var(--muted)" }}>
                    {m.qty} {m.unit}</span>
                </div>
              ))}
              {dash.pending_materials_count >
                dash.pending_materials.length && (
                <div style={{ fontSize: 11.5, color: "var(--faint)" }}>
                  … and {dash.pending_materials_count
                         - dash.pending_materials.length} more lines
                </div>
              )}
              {dash.pending_materials_count === 0 && (
                <div style={{ fontSize: 12, color: "var(--faint)" }}>
                  nothing outstanding</div>
              )}
            </div>
          </div>
        </section>
      )}

      {stock?.balances?.length > 0 && (() => {
        const low = stock.balances.filter((b) => Number(b.on_hand) <= 0);
        return (
          <section style={card}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10,
                          flexWrap: "wrap" }}>
              <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 15 }}>
                📦 Site stock</h2>
              <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
                {stock.balances.length} item
                {stock.balances.length === 1 ? "" : "s"} on hand</span>
              <button onClick={onStock}
                      style={{ ...ghostButton, marginLeft: "auto",
                               padding: "2px 12px", fontSize: 12 }}>
                View stock →</button>
            </div>
            {low.length > 0 ? (
              <div style={{ marginTop: 8 }}>
                <div style={{ fontSize: 12.5, fontWeight: 700,
                              color: "var(--red-fg)", marginBottom: 4 }}>
                  ⚠ {low.length} item{low.length === 1 ? "" : "s"} at or below
                  zero — reconcile or replenish
                </div>
                {low.slice(0, 6).map((b) => (
                  <div key={b.item_id}
                       style={{ fontSize: 12.5, padding: "2px 0",
                                borderTop: "1px solid var(--row-line)",
                                display: "flex", gap: 8 }}>
                    <span style={{ flex: 1 }}>{b.description}</span>
                    <span style={{ fontFamily: "var(--font-mono)",
                                   color: Number(b.on_hand) < 0
                                     ? "var(--red-fg)" : "var(--muted)" }}>
                      {b.on_hand} {b.unit}</span>
                  </div>
                ))}
                {low.length > 6 && (
                  <div style={{ fontSize: 11.5, color: "var(--faint)" }}>
                    … and {low.length - 6} more</div>
                )}
              </div>
            ) : (
              <div style={{ fontSize: 12, color: "var(--faint)", marginTop: 6 }}>
                All balances positive.</div>
            )}
          </section>
        );
      })()}

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

      {(pyrs.length > 0 ||
        ["SITE_ADMIN", "SITE_ENGINEER", "PM", "ADMIN"].includes(me.role)) && (
        <PyrRegister pyrs={pyrs} onOpenDoc={onOpenDoc}
                     onOpenRegister={onPyrRegister} />
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


// Payment Requests register + pending payments for the site (§5.9, §7.4).
// "Pending" = approved and on its way to payment (owner): a payment
// becomes pending once the site PM approves it — drafts and requests
// still awaiting PM review are not counted.
const PYR_PENDING = ["PM_APPROVED", "DIRECTOR_APPROVED", "AUTHORISED"];
const money = (v) => v == null ? "—"
  : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2 });

// Dashboard card: PENDING payments only (owner). The full list lives on
// the Payment register page, reached by the link.
function PyrRegister({ pyrs, onOpenDoc, onOpenRegister }) {
  const pending = pyrs.filter((p) => PYR_PENDING.includes(p.status));
  const pendingTotal = pending.reduce(
    (a, p) => a + Number(p.payment_request?.amount_requested || 0), 0);
  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10,
                    flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 15 }}>
          💳 Pending Payments
        </h2>
        {pending.length > 0 && (
          <span style={{ fontSize: 12.5, color: "var(--amber-fg)" }}>
            {pending.length} awaiting approval / payment · MVR
            {" "}{money(pendingTotal)}
          </span>
        )}
        <a href="#" onClick={(e) => { e.preventDefault(); onOpenRegister(); }}
           style={{ marginLeft: "auto", fontSize: 12.5,
                    color: "var(--navy)" }}>
          Payment register →</a>
      </div>
      {pending.length === 0 ? (
        <p style={{ fontSize: 13, color: "var(--muted)", margin: "8px 0 0" }}>
          No payments pending. {pyrs.length > 0
            ? "See the payment register for the full history."
            : "Raise one for boat hire, a subcontractor, permits or other "
              + "non-purchase spend."}
        </p>
      ) : (
        <div style={{ overflowX: "auto", marginTop: 8 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>Ref</th><th style={th}>Date</th>
              <th style={th}>Cost head</th><th style={th}>Payee</th>
              <th style={{ ...th, textAlign: "right" }}>Requested</th>
              <th style={th}>Status</th>
            </tr></thead>
            <tbody>
              {pending.slice(0, 12).map((p) => {
                const pr = p.payment_request || {};
                return (
                  <tr key={p.ref}>
                    <td style={{ ...td, width: 120 }}>
                      <a href="#" onClick={(e) => { e.preventDefault();
                                                    onOpenDoc(p.ref); }}
                         style={{ textDecoration: "none" }}>
                        <RefStamp small>{p.ref}</RefStamp></a>
                    </td>
                    <td style={td}>{p.doc_date}</td>
                    <td style={td}>{pr.cost_head}</td>
                    <td style={td}>{pr.payee}</td>
                    <td style={{ ...td, textAlign: "right",
                                 fontFamily: "var(--font-mono)" }}>
                      {money(pr.amount_requested)}</td>
                    <td style={td}>
                      <StatusChip status={p.status} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
