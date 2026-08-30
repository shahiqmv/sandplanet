import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, card, inputStyle, td, th } from "./ui.jsx";

const money = (v) => Number(v || 0).toLocaleString("en-US",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// Final settlement for a demobilised batch: the men whose contract ends when
// they leave the site, who cannot wait for a month-end run they will not be
// here for (owner 2026-08-30).
export default function SettlementPanel({ sites, onCreated, onClose }) {
  const [siteId, setSiteId] = useState("");
  const [lastDay, setLastDay] = useState("");
  const [reason, setReason] = useState("Demobilised — contract ended");
  const [people, setPeople] = useState([]);
  const [picked, setPicked] = useState([]);
  const [preview, setPreview] = useState(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setPicked([]); setPreview(null);
    if (!siteId) { setPeople([]); return; }
    api(`/payroll/settlements/candidates?site=${siteId}`)
      .then(setPeople).catch((e) => setError(e.message));
  }, [siteId]);

  const toggle = (id) => {
    setPreview(null);
    setPicked((cur) => cur.includes(id) ? cur.filter((x) => x !== id)
                                        : [...cur, id]);
  };

  const body = useCallback(() => ({
    site_id: siteId, employee_ids: picked, last_working_day: lastDay,
    reason,
  }), [siteId, picked, lastDay, reason]);

  async function runPreview() {
    setBusy(true); setError(null);
    try { setPreview(await api("/payroll/settlements/preview",
                               { method: "POST", body: body() })); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function create() {
    setBusy(true); setError(null);
    try {
      const run = await api("/payroll/settlements",
                            { method: "POST", body: body() });
      onCreated?.(run);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  // Group by the day this site's roster let them go. A batch demobilised
  // together shares that date, which is what makes "those twenty" findable
  // in a roster of a hundred.
  const needle = q.trim().toLowerCase();
  const groups = [];
  for (const p of people) {
    if (needle && !`${p.emp_no} ${p.full_name}`.toLowerCase()
        .includes(needle)) continue;
    const key = p.removed_on || "active";
    let g = groups.find((x) => x.key === key);
    if (!g) {
      g = { key, rows: [],
            label: p.removed_on
              ? `Left the site ${new Date(p.removed_on)
                  .toLocaleDateString(undefined, { day: "numeric",
                    month: "short", year: "numeric" })}`
              : "Still on the roster" };
      groups.push(g);
    }
    g.rows.push(p);
  }

  const selectGroup = (g) => {
    setPreview(null);
    const ids = g.rows.map((r) => r.id);
    const all = ids.every((id) => picked.includes(id));
    setPicked((cur) => all ? cur.filter((id) => !ids.includes(id))
                           : [...new Set([...cur, ...ids])]);
  };

  // What the system already thinks — shown, never prefilled. At VKR the
  // recorded date is the day someone got round to the paperwork, five days
  // after the men actually stopped, and prefilling it would launder that
  // mistake into the pay run.
  const pickedDates = [...new Set(people.filter((p) => picked.includes(p.id))
    .map((p) => p.removed_on).filter(Boolean))];

  const ready = siteId && lastDay && picked.length > 0;

  return (
    <section style={{ ...card, border: "1px solid var(--sp-sky, #1B7FB8)" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap" }}>
        <h3 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 16 }}>
          Final settlement
        </h3>
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
          Pay a demobilised batch everything still owed, up to their last
          working day
        </span>
        <button onClick={onClose}
                style={{ marginLeft: "auto", background: "transparent",
                         border: "1px solid #BFD6E6", borderRadius: 8,
                         padding: "5px 13px", cursor: "pointer",
                         fontFamily: "inherit", color: "var(--navy)" }}>
          Close
        </button>
      </div>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                    margin: "14px 0" }}>
        <label style={fld}>Site
          <select value={siteId} onChange={(e) => setSiteId(e.target.value)}
                  style={{ ...inputStyle, width: 200 }}>
            <option value="">— select —</option>
            {sites.filter((s) => !s.is_head_office).map((s) => (
              <option key={s.id} value={s.id}>{s.code} — {s.name}</option>
            ))}
          </select>
        </label>
        <label style={fld}>Last working day
          <input type="date" value={lastDay}
                 onChange={(e) => { setLastDay(e.target.value);
                                    setPreview(null); }}
                 style={{ ...inputStyle, width: 170 }} />
        </label>
        <label style={{ ...fld, flex: 1, minWidth: 220 }}>Reason
          <input value={reason} onChange={(e) => setReason(e.target.value)}
                 style={inputStyle} />
        </label>
      </div>

      <p style={{ fontSize: 12, color: "var(--muted)", margin: "0 0 8px" }}>
        The last working day caps every man&rsquo;s pay, whatever the register
        says after it — that is what corrects a demobilisation recorded late.
        {pickedDates.length === 1 && (
          <> The system has them leaving{" "}
            <b>{new Date(pickedDates[0]).toLocaleDateString(undefined,
              { day: "numeric", month: "short", year: "numeric" })}</b>
            {" "}— that is the day the removal was filed, which is often
            later than the day they stopped.</>
        )}
      </p>

      {people.length > 0 && (
        <>
          <div style={{ display: "flex", gap: 8, alignItems: "center",
                        marginBottom: 8, flexWrap: "wrap" }}>
            <input value={q} onChange={(e) => setQ(e.target.value)}
                   placeholder="Find a worker by name or number…"
                   style={{ ...inputStyle, width: 260 }} />
            <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
              {picked.length} selected of {people.length}
            </span>
            {picked.length > 0 && (
              <Btn variant="ghost"
                   style={{ fontSize: 12, padding: "3px 10px" }}
                   onClick={() => { setPicked([]); setPreview(null); }}>
                Clear</Btn>
            )}
          </div>
          <div style={{ maxHeight: 300, overflowY: "auto",
                        border: "1px solid var(--line)", borderRadius: 8,
                        padding: 8, marginBottom: 12 }}>
            {groups.map((g) => (
              <div key={g.key} style={{ marginBottom: 10 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center",
                              flexWrap: "wrap", padding: "4px 2px",
                              borderBottom: "1px solid var(--line)",
                              marginBottom: 4 }}>
                  <b style={{ fontSize: 12.5, color: "var(--sp-navy)" }}>
                    {g.label}
                  </b>
                  <span style={{ fontSize: 12, color: "var(--muted)" }}>
                    {g.rows.length} worker{g.rows.length === 1 ? "" : "s"}
                  </span>
                  <Btn variant="ghost"
                       style={{ fontSize: 11.5, padding: "2px 9px",
                                marginLeft: "auto" }}
                       onClick={() => selectGroup(g)}>
                    {g.rows.every((r) => picked.includes(r.id))
                      ? "Deselect" : `Select these ${g.rows.length}`}
                  </Btn>
                </div>
                {g.rows.map((p) => (
                  <label key={p.id}
                         style={{ display: "flex", gap: 8, fontSize: 13,
                                  padding: "3px 4px", cursor: "pointer" }}>
                    <input type="checkbox" checked={picked.includes(p.id)}
                           onChange={() => toggle(p.id)} />
                    <span style={{ width: 92 }}>{p.emp_no}</span>
                    <span style={{ flex: 1 }}>{p.full_name}</span>
                  </label>
                ))}
              </div>
            ))}
            {groups.length === 0 && (
              <p style={{ fontSize: 13, color: "var(--muted)", margin: 4 }}>
                Nobody matches “{q}”.</p>
            )}
          </div>
        </>
      )}

      {error && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{error}</p>}

      <div style={{ display: "flex", gap: 8 }}>
        <Btn variant="secondary" disabled={!ready || busy}
             onClick={runPreview}>
          Work out what they are owed</Btn>
        {preview && (
          <Btn variant="primary" disabled={busy} onClick={create}>
            Raise the settlement run</Btn>
        )}
      </div>

      {preview && (
        <>
          {preview.conflict_count > 0 && (
            // Two records disagreeing about when men stopped working is not
            // ours to resolve quietly — the money turns on it.
            <div style={{ marginTop: 14, padding: "10px 14px",
                          borderRadius: 8, background: "var(--amber-bg, #FDF1E3)",
                          border: "1px solid var(--amber-fg, #B35900)" }}>
              <b style={{ color: "var(--amber-fg, #B35900)", fontSize: 13 }}>
                {preview.conflict_count} of these men are marked present after{" "}
                {preview.last_working_day}
              </b>
              <p style={{ margin: "4px 0 0", fontSize: 12.5 }}>
                The register and the last working day disagree. Those days are
                NOT being paid. If the register is right, correct the last
                working day instead.
              </p>
            </div>
          )}
          <table style={{ width: "100%", borderCollapse: "collapse",
                          marginTop: 14, fontSize: 13 }}>
            <thead><tr>
              <th style={th}>Worker</th>
              <th style={th}>Periods</th>
              <th style={{ ...th, textAlign: "right" }}>Gross</th>
              <th style={{ ...th, textAlign: "right" }}>Recovered</th>
              <th style={{ ...th, textAlign: "right" }}>Net</th>
              <th style={th}>Marked after</th>
            </tr></thead>
            <tbody>
              {preview.rows.map((r) => (
                <tr key={r.employee_id}>
                  <td style={td}>{r.emp_no} · {r.full_name}</td>
                  <td style={{ ...td, fontSize: 12 }}>
                    {r.months.length === 0 ? "—" : r.months.map((m) =>
                      `${m.year}-${String(m.month).padStart(2, "0")}` +
                      ` (${m.days}d)`).join(", ")}
                  </td>
                  <td style={num}>{money(r.gross)}</td>
                  <td style={num}>
                    {+r.advance + +r.loan > 0
                      ? money(+r.advance + +r.loan) : "—"}
                  </td>
                  <td style={{ ...num, fontWeight: 700 }}>{money(r.net)}</td>
                  <td style={{ ...td, fontSize: 12,
                               color: "var(--amber-fg, #B35900)" }}>
                    {r.conflicts.length
                      ? `${r.conflicts.length} day${
                          r.conflicts.length === 1 ? "" : "s"}` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot><tr>
              <td style={{ ...td, fontWeight: 700 }} colSpan={4}>
                {preview.rows.length} workers</td>
              <td style={{ ...num, fontWeight: 700 }}>
                {money(preview.total_net)}</td>
              <td style={td} />
            </tr></tfoot>
          </table>
        </>
      )}
    </section>
  );
}

const fld = { display: "flex", flexDirection: "column", gap: 3, fontSize: 12,
  color: "var(--muted)" };
const num = { ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" };
