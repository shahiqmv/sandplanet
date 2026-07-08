import { useEffect, useState } from "react";
import { api } from "./api.js";
import { ActionCard, Chip, Eyebrow, IssuedStamp, StampTile, Stat, card }
  from "./ui.jsx";

// HR / Payroll dashboard (spec §7.4): month-lock board first (payroll
// export is enabled only when every site is locked), then alerts, then
// workforce summaries.

export default function HRDashboard({ refresh, onOpenPayroll }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/dashboards/hr").then(setData).catch((e) => setError(e.message));
  }, [refresh]);

  if (error) return <section style={card}>{error}</section>;
  if (!data) return <section style={card}>Loading…</section>;

  const daysTo = (d) =>
    Math.floor((new Date(d).getTime() - Date.now()) / 864e5);

  return (
    <>
      <Eyebrow meta={data.all_locked
                 ? "all sites locked — payroll export ready"
                 : `${data.lock_board.filter((b) => b.status !== "LOCKED")
                     .length} site(s) still open`}
               metaTone={data.all_locked ? null : "alert"}>
        Month lock — {data.month}
      </Eyebrow>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                    marginBottom: 14 }}>
        {data.lock_board.map((b) => (
          <StampTile key={b.code} title={`${b.code} — ${b.name}`}
            done={b.status === "LOCKED"}
            doneStamp={<IssuedStamp refText={b.code} label="LOCKED 🔒" />}
            dueText="PM sign-off pending" />
        ))}
        {data.lock_board.length === 0 && (
          <section style={card}>No active sites.</section>
        )}
      </div>

      {(data.permit_expiries.length > 0 ||
        data.reallocation_alerts.length > 0) && (
        <>
          <Eyebrow meta={String(data.permit_expiries.length
                                + data.reallocation_alerts.length)}
                   metaTone="alert">
            Alerts
          </Eyebrow>
          {data.permit_expiries.map((e) => {
            const days = daysTo(e.work_permit_expiry);
            return (
              <ActionCard key={e.emp_no}
                severity={days <= 14 ? "alert" : "warn"}
                refText={e.emp_no}
                text={`${e.full_name} — work permit expires `
                      + `${e.work_permit_expiry}`}
                meta={days < 0 ? `expired ${-days} days ago`
                               : `${days} days left`}
                chip={<Chip tone={days <= 14 ? "alert" : "warn"}>
                        PERMIT</Chip>} />
            );
          })}
          {data.reallocation_alerts.map((a) => (
            <ActionCard key={a.employee__emp_no} severity="warn"
              refText={a.employee__emp_no}
              text={`${a.employee__full_name} is allocated to closed site `
                    + `${a.site__code} — reallocate or deactivate`}
              chip={<Chip tone="warn">REALLOCATE</Chip>} />
          ))}
        </>
      )}

      <Eyebrow>Workforce</Eyebrow>
      <section style={{ ...card, display: "flex", gap: 18,
                        flexWrap: "wrap" }}>
        <Stat label="At work today" value={data.workforce_today}
              tone="info" context="from today's attendance entries" />
        <Stat label="OT awaiting PM approval" value={data.ot_pending_approval}
              tone={data.ot_pending_approval ? "warn" : "ok"}
              context={data.ot_pending_approval
                ? "unapproved OT never reaches payroll" : "all approved"} />
        <Stat label="Active employees" value={data.active_employees}
              tone="info" context="company-wide roster" />
      </section>
    </>
  );
}
