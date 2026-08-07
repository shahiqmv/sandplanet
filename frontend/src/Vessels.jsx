// Local-vessel tracking (FollowMe). Three surfaces, one data source:
//  • VesselPicker — type-ahead onto a Loading Manifest, stores name + id
//  • VesselTrack  — live position for a picked vessel (map pin + last-seen)
//  • VesselsPage  — "what's near us" browse for site + purchasing
// The backend proxies FollowMe so the API key never reaches the browser.
import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { card, ghostButton, inputStyle, td, th } from "./ui.jsx";

// "2026-08-07 09:10:33" → "how long ago", so a stale fix is obvious.
function ago(ts) {
  if (!ts) return "";
  const t = new Date(ts.replace(" ", "T") + "Z");   // stored Maldives-local ≈ UTC+5
  const mins = Math.round((Date.now() - t.getTime()) / 60000) - 5 * 60;
  if (isNaN(mins)) return ts;
  if (mins < 2) return "just now";
  if (mins < 90) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 36) return `${hrs} h ago`;
  return `${Math.round(hrs / 24)} d ago`;
}

function mapHref(v) {
  return `https://www.google.com/maps?q=${v.lat},${v.lon}`;
}

// ---- Live position panel (shared by the LM view and the browse page) ------
export function VesselTrack({ vesselId, name, compact }) {
  const [v, setV] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    setErr(null);
    try {
      setV(await api(`/vessels/${vesselId}`));
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { if (vesselId) refresh(); }, [vesselId]);   // eslint-disable-line

  if (!vesselId) return null;
  return (
    <div style={{ border: "1px solid #dbe3ea", borderRadius: 8,
                  padding: compact ? "8px 10px" : 12,
                  background: "#f7fafc", fontSize: 13 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                    flexWrap: "wrap" }}>
        <strong style={{ color: "var(--sp-navy)" }}>
          🛰️ {v?.name || name || `Vessel ${vesselId}`}</strong>
        <button onClick={refresh} disabled={loading} style={{ ...ghostButton,
          padding: "2px 10px", fontSize: 12 }}>
          {loading ? "…" : "Refresh"}</button>
      </div>
      {err && <p style={{ color: "#c0392b", margin: "6px 0 0" }}>{err}</p>}
      {v && !err && (
        v.lat != null && v.lon != null ? (
          <div style={{ marginTop: 6, lineHeight: 1.7 }}>
            <span>Near <strong>{v.port || "—"}</strong>
              {v.atoll ? ` (${v.atoll} atoll)` : ""}</span><br />
            <span>Speed {v.speed ?? "—"} kn · Course {v.course ?? "—"}° ·
              {" "}Last seen {ago(v.time) || "—"}</span><br />
            <a href={mapHref(v)} target="_blank" rel="noreferrer"
               style={{ color: "var(--sp-navy)", fontWeight: 600 }}>
              View on map ↗</a>
          </div>
        ) : (
          <p style={{ margin: "6px 0 0", color: "#5a6b78" }}>
            No live position reported for this vessel right now.</p>
        )
      )}
    </div>
  );
}

// ---- Type-ahead picker for the Loading Manifest ---------------------------
// Stores the display name in `vessel` and the tracker id in `vessel_id`; a
// vessel with no tracker can still be typed by hand (id stays empty).
export function VesselPicker({ name, vesselId, onPick }) {
  const [q, setQ] = useState(name || "");
  const [opts, setOpts] = useState([]);
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState(null);
  const timer = useRef(null);

  useEffect(() => { setQ(name || ""); }, [name]);

  function search(text) {
    clearTimeout(timer.current);
    if (!text || text.trim().length < 2) { setOpts([]); return; }
    timer.current = setTimeout(async () => {
      try {
        const d = await api(`/vessels?q=${encodeURIComponent(text.trim())}`);
        setOpts(d.vessels || []);
        setOpen(true);
        setErr(null);
      } catch (e) {
        setErr(e.message);
        setOpts([]);
      }
    }, 250);
  }

  return (
    <label style={{ fontSize: 13, position: "relative" }}>Vessel / Boat
      <input value={q} placeholder="Type to search tracked vessels…"
        onChange={(e) => {
          setQ(e.target.value);
          // free typing clears any linked id until they pick from the list
          onPick({ vessel: e.target.value, vessel_id: "" });
          search(e.target.value);
        }}
        onFocus={() => opts.length && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        style={inputStyle} />
      {vesselId && (
        <span style={{ fontSize: 11, color: "#2e7d32" }}>
          ✓ linked to tracker — the site can track this vessel live</span>
      )}
      {err && <span style={{ fontSize: 11, color: "#c0392b" }}>{err}</span>}
      {open && opts.length > 0 && (
        <div style={{ position: "absolute", top: "100%", left: 0, right: 0,
                      zIndex: 20, background: "#fff", border: "1px solid #cbd5df",
                      borderRadius: 8, maxHeight: 240, overflowY: "auto",
                      boxShadow: "0 8px 24px rgba(0,0,0,.12)" }}>
          {opts.slice(0, 40).map((o) => (
            <div key={o.id} onMouseDown={() => {
              setQ(o.name);
              onPick({ vessel: o.name, vessel_id: o.id });
              setOpen(false);
            }} style={{ padding: "7px 10px", cursor: "pointer",
                        borderBottom: "1px solid #eef2f5", fontSize: 13 }}>
              <strong>{o.name}</strong>
              <span style={{ color: "#5a6b78" }}>
                {o.type ? ` · ${o.type}` : ""}{o.port ? ` · ${o.port}` : ""}</span>
            </div>
          ))}
        </div>
      )}
    </label>
  );
}

// ---- Browse: "what supply vessels are near us" ----------------------------
// A full page opened from a dashboard button (kept off the dashboards
// themselves so they don't grow). `onClose` returns to wherever it opened from.
export function VesselsPage({ onClose, defaultAtoll = "" }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [atoll, setAtoll] = useState(defaultAtoll);
  const [supply, setSupply] = useState(true);
  const [openId, setOpenId] = useState(null);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const p = new URLSearchParams();
      if (q.trim()) p.set("q", q.trim());
      if (atoll) p.set("atoll", atoll);
      if (supply) p.set("supply", "1");
      setData(await api(`/vessels?${p.toString()}`));
    } catch (e) {
      setErr(e.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, [atoll, supply]);  // eslint-disable-line

  const vessels = data?.vessels || [];
  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10,
                    flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
          🛥️ Vessels nearby</h2>
        {onClose && (
          <button onClick={onClose}
                  style={{ ...ghostButton, marginLeft: "auto" }}>
            Close</button>
        )}
      </div>
      <p style={{ fontSize: 13, color: "#5a6b78", margin: "6px 0 14px" }}>
        Live positions of local vessels (FollowMe). Filter by atoll to see
        what's near a site, or search a boat by name.
      </p>
      <>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                    alignItems: "flex-end", marginBottom: 14 }}>
        <label style={{ fontSize: 13 }}>Search
          <input value={q} onChange={(e) => setQ(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && load()}
                 placeholder="Vessel name…" style={{ ...inputStyle, width: 200 }} />
        </label>
        <label style={{ fontSize: 13 }}>Atoll
          <select value={atoll} onChange={(e) => setAtoll(e.target.value)}
                  style={{ ...inputStyle, width: 120 }}>
            <option value="">All atolls</option>
            {(data?.atolls || []).map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: 13, display: "flex", alignItems: "center",
                        gap: 6, paddingBottom: 8 }}>
          <input type="checkbox" checked={supply}
                 onChange={(e) => setSupply(e.target.checked)} />
          Supply / cargo only
        </label>
        <button onClick={load} style={{ ...ghostButton, padding: "7px 16px" }}>
          Search</button>
      </div>

      {err && <p style={{ color: "#c0392b", fontSize: 13 }}>{err}</p>}
      {loading && <p style={{ fontSize: 13, color: "#5a6b78" }}>Loading vessels…</p>}
      {!loading && !err && (
        <>
          <p style={{ fontSize: 12, color: "#5a6b78", margin: "0 0 8px" }}>
            {data.total} vessel(s){atoll ? ` in ${atoll} atoll` : ""}
            {data.total > vessels.length ? ` — showing ${vessels.length}` : ""}.
          </p>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 13 }}>
              <thead><tr>
                <th style={th}>Vessel</th><th style={th}>Type</th>
                <th style={th}>Near</th><th style={th}>Last seen</th>
                <th style={th}></th>
              </tr></thead>
              <tbody>
                {vessels.map((v) => (
                  <>
                    <tr key={v.id}>
                      <td style={td}><strong>{v.name}</strong></td>
                      <td style={td}>{v.type || "—"}</td>
                      <td style={td}>{v.port || "—"}</td>
                      <td style={td}>{ago(v.time) || "—"}</td>
                      <td style={td}>
                        <button onClick={() => setOpenId(
                                  openId === v.id ? null : v.id)}
                                style={{ ...ghostButton, padding: "2px 12px",
                                         fontSize: 12 }}>
                          {openId === v.id ? "Hide" : "Track"}</button>
                      </td>
                    </tr>
                    {openId === v.id && (
                      <tr key={v.id + "-t"}>
                        <td colSpan={5} style={{ ...td, background: "#f7fafc" }}>
                          <VesselTrack vesselId={v.id} name={v.name} compact />
                        </td>
                      </tr>
                    )}
                  </>
                ))}
                {vessels.length === 0 && (
                  <tr><td colSpan={5} style={{ ...td, color: "#5a6b78" }}>
                    No vessels match.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
      </>
    </section>
  );
}
