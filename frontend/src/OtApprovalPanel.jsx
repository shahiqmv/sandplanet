import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, ghostButton, inputStyle, td, th } from "./ui.jsx";

// The PM's OT approval table. It used to be one button — "Approve all
// requested OT" — over the whole day: 170 to 200 rows at a click, 455 times
// in a month, and the PM only ever saw hours. Here every request carries
// its rate and cost, the day's total, and what the month has already cost;
// approval is per man, or for rows the PM has ticked after reading them
// (owner 2026-09-03).
const money = (v) => Number(v || 0).toLocaleString("en-US",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const hrs = (v) => Number(v || 0).toLocaleString("en-US",
  { maximumFractionDigits: 2 });

export default function OtApprovalPanel({ site, day, locked, onChanged,
                                          onError, onNotice }) {
  const [data, setData] = useState(null);
  const [edits, setEdits] = useState({});     // attendance_id -> hours
  const [ticked, setTicked] = useState([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api(`/attendance/ot-review?site=${site.id}&date=${day}`)
      .then((d) => { setData(d); setEdits({}); setTicked([]); })
      .catch((e) => onError(e.message));
  }, [site.id, day, onError]);
  useEffect(load, [load]);

  if (!data) return <p style={{ color: "#5a6b78", fontSize: 13 }}>Loading…</p>;
  const rows = data.rows || [];
  if (!rows.length) return (
    <p style={{ color: "#5a6b78", fontSize: 13 }}>
      No overtime requested on {day}.</p>
  );
  const pending = rows.filter((r) => r.pending);
  const hoursFor = (r) => edits[r.attendance_id] ?? r.ot_requested;

  async function approve(list) {
    if (!list.length) return;
    const body = list.map((r) => ({ id: r.attendance_id,
                                    hours: hoursFor(r) }));
    const cost = list.reduce((t, r) =>
      t + Number(hoursFor(r)) * Number(r.ot_rate), 0);
    const ccy = list[0].currency;
    if (list.length > 1 && !window.confirm(
        `Approve OT for ${list.length} men — ` +
        `${hrs(list.reduce((t, r) => t + Number(hoursFor(r)), 0))} h, ` +
        `${ccy} ${money(cost)}?`)) return;
    setBusy(true); onError(null);
    try {
      const res = await api("/attendance/ot-approve",
                            { method: "POST", body: { rows: body } });
      onNotice?.(`Approved OT on ${res.approved} row(s) — ${ccy} ` +
                 `${money(res.total_cost)}.`);
      load(); onChanged();
    } catch (e) { onError(e.message); } finally { setBusy(false); }
  }

  return (
    <section style={{ marginTop: 8 }}>
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap",
                    alignItems: "baseline", marginBottom: 10 }}>
        <h3 style={{ margin: 0, fontSize: 15, color: "var(--sp-navy)" }}>
          OT approval — {day}</h3>
        {(data.totals || []).map((t) => (
          <span key={t.currency} style={{ fontSize: 13, color: "#5a6b78" }}>
            Requested <b>{hrs(t.requested_hours)} h</b> ·{" "}
            <b>{t.currency} {money(t.requested_cost)}</b>
            {" "}· approved {hrs(t.approved_hours)} h ·{" "}
            {t.currency} {money(t.approved_cost)}
            {t.pending_rows > 0 && (
              <b style={{ color: "#8a6d00" }}> · {t.pending_rows} awaiting</b>
            )}
          </span>
        ))}
        {(data.month_to_date || []).map((m) => (
          <span key={m.currency} style={{ fontSize: 13, color: "#5a6b78" }}>
            Month to date approved: <b>{hrs(m.hours)} h · {m.currency}{" "}
            {money(m.cost)}</b>
          </span>
        ))}
      </div>
      <p style={{ fontSize: 12, color: "#5a6b78", margin: "0 0 8px" }}>
        Approve each man's hours against what they cost. Rows above{" "}
        {hrs(data.flag_hours)} h are highlighted. Set hours to 0 to refuse.
      </p>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={th}>
              <input type="checkbox"
                     checked={pending.length > 0
                       && ticked.length === pending.length}
                     disabled={locked || !pending.length}
                     title="Tick every awaiting row — you still confirm the total"
                     onChange={(e) => setTicked(e.target.checked
                       ? pending.map((r) => r.attendance_id) : [])} />
            </th>
            <th style={th}>Worker</th><th style={th}>Category</th>
            <th style={th}>In – out</th>
            <th style={{ ...th, textAlign: "right" }}>Requested</th>
            <th style={{ ...th, textAlign: "right" }}>Rate</th>
            <th style={{ ...th, textAlign: "right" }}>Cost</th>
            <th style={th}>Approve</th>
            <th style={th}>Status</th>
          </tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.attendance_id}
                  style={{ background: r.flag ? "#fff7e0" : undefined }}>
                <td style={td}>
                  {r.pending && (
                    <input type="checkbox" disabled={locked}
                           checked={ticked.includes(r.attendance_id)}
                           onChange={(e) => setTicked(e.target.checked
                             ? [...ticked, r.attendance_id]
                             : ticked.filter((x) => x !== r.attendance_id))} />
                  )}
                </td>
                <td style={td}>
                  <b style={{ color: "var(--sp-navy)" }}>{r.emp_no}</b>{" "}
                  {r.full_name}
                </td>
                <td style={{ ...td, fontSize: 12 }}>{r.category}</td>
                <td style={{ ...td, fontSize: 12, whiteSpace: "nowrap" }}>
                  {String(r.check_in || "").slice(0, 5)} –{" "}
                  {String(r.check_out || "").slice(0, 5)}
                </td>
                <td style={{ ...td, textAlign: "right",
                             fontWeight: r.flag ? 700 : 400 }}>
                  {hrs(r.ot_requested)} h</td>
                <td style={{ ...td, textAlign: "right", fontSize: 12,
                             color: r.no_rate ? "#a3271b" : "#5a6b78" }}>
                  {r.no_rate ? "no OT rate" : `${r.currency} ${money(r.ot_rate)}`}
                </td>
                <td style={{ ...td, textAlign: "right",
                             fontVariantNumeric: "tabular-nums" }}>
                  {r.currency} {money(Number(hoursFor(r)) * Number(r.ot_rate))}
                </td>
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  {r.pending && !locked ? (
                    <>
                      <input type="number" min="0" step="0.5"
                             value={hoursFor(r)}
                             onChange={(e) => setEdits({ ...edits,
                               [r.attendance_id]: e.target.value })}
                             style={{ ...inputStyle, width: 64,
                                      padding: "3px 6px" }} />
                      <button onClick={() => approve([r])} disabled={busy}
                              style={{ ...buttonStyle, padding: "3px 10px",
                                       marginLeft: 6, fontSize: 12 }}>
                        Approve</button>
                      <button onClick={() => { setEdits({ ...edits,
                                [r.attendance_id]: 0 });
                                approve([{ ...r, ot_requested: 0 }]); }}
                              disabled={busy} title="Approve none of it"
                              style={{ ...ghostButton, padding: "3px 8px",
                                       marginLeft: 4, fontSize: 12,
                                       color: "#a3271b" }}>
                        0</button>
                    </>
                  ) : null}
                </td>
                <td style={{ ...td, fontSize: 12 }}>
                  {r.pending
                    ? <span style={{ color: "#8a6d00" }}>awaiting</span>
                    : <span style={{ color: "#1a7f37" }}>
                        approved {hrs(r.ot_approved)} h</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {ticked.length > 0 && !locked && (
        <div style={{ marginTop: 10 }}>
          <button disabled={busy} style={buttonStyle}
                  onClick={() => approve(
                    pending.filter((r) => ticked.includes(r.attendance_id)))}>
            Approve {ticked.length} ticked row(s) —{" "}
            {pending[0]?.currency}{" "}
            {money(pending.filter((r) => ticked.includes(r.attendance_id))
              .reduce((t, r) => t + Number(hoursFor(r)) * Number(r.ot_rate), 0))}
          </button>
        </div>
      )}
    </section>
  );
}
