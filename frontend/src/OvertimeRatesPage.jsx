import { useEffect, useState } from "react";
import { api } from "./api.js";
import { buttonStyle, card, inputStyle, td, th } from "./ui.jsx";

// Overtime rate master (owner: managed, not hardcoded). One flat rate per
// hour per job category, in MVR and/or USD, with an "applies by default"
// toggle that seeds each worker's OT entitlement. HR/Admin.

export default function OvertimeRatesPage({ me }) {
  const [rows, setRows] = useState([]);
  const [edits, setEdits] = useState({});   // key `${catId}:${cur}` -> {rate, def}
  const [error, setError] = useState(null);
  const [savedFor, setSavedFor] = useState(null);

  const canEdit = ["HO_HR", "ADMIN"].includes(me.role);

  function load() {
    api("/overtime-rates").then((data) => {
      setRows(data);
      const e = {};
      for (const r of data) {
        for (const cur of ["MVR", "USD"]) {
          const v = r.rates[cur];
          e[`${r.category_id}:${cur}`] = {
            rate: v?.rate_per_hour != null ? String(v.rate_per_hour) : "",
            def: v ? v.applies_by_default : true,
          };
        }
      }
      setEdits(e);
    }).catch((ex) => setError(ex.message));
  }
  useEffect(load, []);

  const set = (key, patch) =>
    setEdits((e) => ({ ...e, [key]: { ...e[key], ...patch } }));

  async function save(catId, cur) {
    const key = `${catId}:${cur}`;
    const { rate, def } = edits[key];
    if (rate === "" || rate == null) return;
    setError(null);
    try {
      await api("/overtime-rates", { method: "POST",
        body: { category_id: catId, currency: cur,
                rate_per_hour: rate, applies_by_default: def } });
      setSavedFor(key);
      setTimeout(() => setSavedFor(null), 1500);
      load();
    } catch (ex) { setError(ex.message); }
  }

  const groups = [["STAFF", "Staff"], ["LABOUR", "Trades / Labour"]];

  return (
    <section style={card}>
      <h2 style={{ marginTop: 0, color: "var(--sp-navy)", fontSize: 17 }}>
        Overtime Rates
      </h2>
      <p style={{ color: "#5a6b78", fontSize: 12.5, margin: "0 0 12px" }}>
        Flat overtime rate per hour, by category and currency. “Applies by
        default” decides whether workers in that category get overtime unless
        turned off on their profile.
      </p>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead><tr>
          <th style={th}>Category</th>
          <th style={{ ...th, textAlign: "right" }}>MVR / hr</th>
          <th style={{ ...th, textAlign: "center" }}>Default</th>
          <th style={{ ...th, textAlign: "right" }}>USD / hr</th>
          <th style={{ ...th, textAlign: "center" }}>Default</th>
          {canEdit && <th style={th} />}
        </tr></thead>
        <tbody>
          {groups.map(([grp, label]) => {
            const list = rows.filter((r) => r.grp === grp);
            if (!list.length) return null;
            return (
              <>
                <tr key={grp}><td colSpan={canEdit ? 6 : 5}
                    style={{ ...td, fontWeight: 700, color: "var(--sp-navy)",
                             background: "var(--sp-tint, #f5f8fb)" }}>
                  {label}</td></tr>
                {list.map((r) => {
                  const mk = `${r.category_id}:MVR`;
                  const uk = `${r.category_id}:USD`;
                  const m = edits[mk] || {}; const u = edits[uk] || {};
                  return (
                    <tr key={r.category_id}>
                      <td style={td}>{r.category_name}</td>
                      <td style={{ ...td, textAlign: "right" }}>
                        <input type="number" step="0.01" value={m.rate ?? ""}
                               disabled={!canEdit}
                               onChange={(e) => set(mk, { rate: e.target.value })}
                               style={{ ...inputStyle, width: 80,
                                        textAlign: "right" }} />
                      </td>
                      <td style={{ ...td, textAlign: "center" }}>
                        <input type="checkbox" checked={!!m.def}
                               disabled={!canEdit}
                               onChange={(e) => set(mk, { def: e.target.checked })} />
                      </td>
                      <td style={{ ...td, textAlign: "right" }}>
                        <input type="number" step="0.01" value={u.rate ?? ""}
                               disabled={!canEdit}
                               onChange={(e) => set(uk, { rate: e.target.value })}
                               style={{ ...inputStyle, width: 80,
                                        textAlign: "right" }} />
                      </td>
                      <td style={{ ...td, textAlign: "center" }}>
                        <input type="checkbox" checked={!!u.def}
                               disabled={!canEdit}
                               onChange={(e) => set(uk, { def: e.target.checked })} />
                      </td>
                      {canEdit && (
                        <td style={{ ...td, whiteSpace: "nowrap" }}>
                          <button onClick={() => { save(r.category_id, "MVR");
                                                   save(r.category_id, "USD"); }}
                                  style={{ ...buttonStyle, padding: "3px 12px",
                                           fontSize: 12 }}>Save</button>
                          {(savedFor === mk || savedFor === uk) && (
                            <span style={{ color: "#1a7f37", fontSize: 12,
                                           marginLeft: 6 }}>✓</span>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
