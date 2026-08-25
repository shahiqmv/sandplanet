import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Crew allocation (owner 2026-08-25): pick a shift, tick the men, move them.
// The same flow IS the change-shift mechanism — moving a ticked man simply
// closes his old assignment the day before and opens the new one, exactly
// like the per-row select on the day grid.
export default function ShiftAllocation({ site, canEnter }) {
  const [day, setDay] = useState(() => new Date().toISOString().slice(0, 10));
  const [data, setData] = useState(null);
  const [target, setTarget] = useState("");     // shift id, or "" = site hours
  const [ticked, setTicked] = useState(() => new Set());
  const [search, setSearch] = useState("");
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api(`/attendance?site=${site.id}&date=${day}`)
      .then((d) => { setData(d); setTicked(new Set()); })
      .catch((e) => setError(e.message));
  }, [site.id, day]);
  useEffect(load, [load]);

  const shifts = data?.shifts || [];
  const crews = useMemo(() => {
    const counts = { "": 0 };
    shifts.forEach((s) => { counts[s.id] = 0; });
    (data?.rows || []).forEach((r) => {
      counts[r.shift_id ?? ""] = (counts[r.shift_id ?? ""] || 0) + 1;
    });
    return counts;
  }, [data, shifts]);

  const targetShift = shifts.find((s) => String(s.id) === String(target));
  const targetLabel = targetShift
    ? `${targetShift.name} ${targetShift.start}–${targetShift.end}`
    : "site hours";

  const rows = (data?.rows || []).filter((r) => {
    const q = search.trim().toLowerCase();
    return !q || r.full_name.toLowerCase().includes(q)
      || String(r.emp_no).toLowerCase().includes(q);
  });
  const onTarget = (r) => String(r.shift_id ?? "") === String(target);
  const eligible = rows.filter((r) => !onTarget(r));

  const toggle = (id) => {
    const next = new Set(ticked);
    if (next.has(id)) next.delete(id); else next.add(id);
    setTicked(next);
  };

  async function move() {
    setBusy(true); setError(null); setNotice(null);
    try {
      const r = await api("/attendance/shift-assign", { method: "POST",
        body: { site: site.id, date: day,
                employee_ids: [...ticked], shift_id: target || null } });
      setNotice(`Moved ${r.assigned} worker(s) to ${targetLabel} `
                + `from ${day}.`);
      load();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  if (!data) return <p style={{ fontSize: 13 }}>{error || "Loading…"}</p>;
  if (shifts.length === 0) {
    return (
      <p style={{ color: "#5a6b78", fontSize: 13, marginTop: 12 }}>
        This site has no shifts defined yet — the PM defines them from the
        site dashboard's <strong>Shifts</strong> button (or Admin on the
        Sites page). Then crews are allocated here.
      </p>
    );
  }

  const chip = (label, count, value) => (
    <button key={value} onClick={() => { setTarget(value);
                                         setTicked(new Set()); }}
            style={{
              ...(String(target) === String(value)
                ? buttonStyle : ghostButton),
              padding: "6px 14px", fontSize: 13 }}>
      {label} · {count}
    </button>
  );

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center",
                    flexWrap: "wrap" }}>
        <span style={{ fontSize: 13, color: "#5a6b78" }}>Move workers to:</span>
        {chip("Site hours", crews[""] || 0, "")}
        {shifts.map((s) => chip(
          `${s.name} ${s.start}–${s.end}${s.overnight ? " +1d" : ""}`,
          crews[s.id] || 0, s.id))}
        <span style={{ marginLeft: "auto", display: "flex", gap: 8,
                       alignItems: "center" }}>
          <label style={{ fontSize: 12.5, color: "#5a6b78" }}>
            effective from{" "}
            <input type="date" value={day}
                   onChange={(e) => setDay(e.target.value)}
                   style={{ ...inputStyle, width: 145 }} />
          </label>
        </span>
      </div>

      <div style={{ display: "flex", gap: 10, alignItems: "center",
                    margin: "12px 0 6px", flexWrap: "wrap" }}>
        <input placeholder="Search name or emp no…" value={search}
               onChange={(e) => setSearch(e.target.value)}
               style={{ ...inputStyle, width: 220 }} />
        {canEnter && (
          <>
            <button style={{ ...ghostButton, padding: "4px 10px",
                             fontSize: 12 }}
                    onClick={() => setTicked(new Set(
                      eligible.map((r) => r.employee_id)))}>
              Tick all shown</button>
            <button style={{ ...ghostButton, padding: "4px 10px",
                             fontSize: 12 }}
                    onClick={() => setTicked(new Set())}>Clear</button>
            <button onClick={move} disabled={busy || ticked.size === 0}
                    style={buttonStyle}>
              {busy ? "Moving…"
                : `Move ${ticked.size || ""} to ${targetLabel}`}</button>
          </>
        )}
      </div>
      {notice && <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>}
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <table style={{ width: "100%", borderCollapse: "collapse",
                      fontSize: 13 }}>
        <thead><tr>
          {canEnter && <th style={{ ...th, width: 34 }} />}
          <th style={{ ...th, width: 90 }}>Emp No</th>
          <th style={th}>Name</th>
          <th style={{ ...th, width: 150 }}>Category</th>
          <th style={{ ...th, width: 170 }}>Current shift</th>
        </tr></thead>
        <tbody>
          {rows.map((r) => {
            const already = onTarget(r);
            return (
              <tr key={r.employee_id}
                  onClick={() => canEnter && !already && toggle(r.employee_id)}
                  style={{ cursor: canEnter && !already ? "pointer"
                                                        : "default",
                           opacity: already ? 0.45 : 1,
                           background: ticked.has(r.employee_id)
                             ? "#eef6fd" : "transparent" }}>
                {canEnter && (
                  <td style={{ ...td, textAlign: "center" }}>
                    <input type="checkbox" readOnly disabled={already}
                           checked={ticked.has(r.employee_id)} />
                  </td>
                )}
                <td style={{ ...td, fontWeight: 600,
                             color: "var(--sp-navy)" }}>{r.emp_no}</td>
                <td style={td}>{r.full_name}</td>
                <td style={td}>{r.category}</td>
                <td style={td}>
                  {already
                    ? <em style={{ color: "#5a6b78" }}>already on
                        {" "}{targetShift ? targetShift.name : "site hours"}
                      </em>
                    : (r.shift_name || "site hours")}
                </td>
              </tr>
            );
          })}
          {rows.length === 0 && (
            <tr><td colSpan={5} style={{ ...td, color: "#5a6b78" }}>
              No workers match.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
