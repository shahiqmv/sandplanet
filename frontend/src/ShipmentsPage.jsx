import { useEffect, useState } from "react";
import { api } from "./api.js";
import { StatusChip, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

// Shipments as their own register (owner 2026-08-28): freight doesn't
// respect order boundaries — a supplier clubs several of our orders, or the
// forwarder consolidates several suppliers into one container. Cargo is
// picked across orders; each IPR still shows the shipment it rides.
const STAGES = ["BOOKED", "SHIPPED", "IN_TRANSIT", "ARRIVED",
                "UNDER_CLEARING", "CLEARED"];

export default function ShipmentsPage({ me, onOpenIpr, onOpenShipment }) {
  const [data, setData] = useState(null);
  const [booking, setBooking] = useState(false);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");

  const load = () => api("/shipments").then(setData)
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const canBook = ["HO_PURCHASING", "ADMIN"].includes(me.role);
  if (booking) return <BookShipment onCancel={() => setBooking(false)}
    onBooked={() => { setBooking(false); load(); }} />;
  if (!data) return <section style={card}>{error || "Loading…"}</section>;

  const rows = data.rows.filter((r) => {
    const n = q.trim().toLowerCase();
    return !n || r.ref.toLowerCase().includes(n)
      || (r.container_awb || "").toLowerCase().includes(n)
      || (r.bl_no || "").toLowerCase().includes(n)
      || r.orders.some((o) => o.ref.toLowerCase().includes(n)
                           || o.supplier.toLowerCase().includes(n));
  });

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          🚢 Shipments</h2>
        {canBook && (
          <button onClick={() => setBooking(true)} style={buttonStyle}>
            + Book shipment</button>
        )}
        <span style={{ fontSize: 12.5, color: "#5a6b78" }}>
          {data.consolidated} consolidated (carrying more than one order)
        </span>
        <input placeholder="Search ref / order / supplier / container…"
               value={q} onChange={(e) => setQ(e.target.value)}
               style={{ ...inputStyle, width: 260, marginLeft: "auto" }} />
      </div>
      <div style={{ display: "flex", gap: 8, margin: "12px 0",
                    flexWrap: "wrap" }}>
        {STAGES.map((s) => (
          <div key={s} style={{ border: "1px solid #dde5ea", borderRadius: 8,
            padding: "6px 14px", background: "#fafcfd", minWidth: 96 }}>
            <div style={{ fontSize: 19, fontWeight: 700,
                          color: "var(--sp-navy)" }}>
              {data.counts[s] || 0}</div>
            <div style={{ fontSize: 10.5, color: "#5a6b78" }}>
              {s.replace(/_/g, " ").toLowerCase()}</div>
          </div>
        ))}
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse",
                      fontSize: 13 }}>
        <thead><tr>
          <th style={th}>Shipment</th><th style={th}>Carrying</th>
          <th style={th}>Mode</th><th style={th}>Key</th>
          <th style={th}>ETA</th><th style={th}>Status</th>
          <th style={th}>Docs</th><th style={th}>IRN</th>
        </tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} onClick={() => onOpenShipment?.(r)}
                style={{ cursor: onOpenShipment ? "pointer" : "default" }}>
              <td style={{ ...td, fontWeight: 600, color: "var(--sp-navy)",
                           whiteSpace: "nowrap" }}>{r.ref}</td>
              <td style={td}>
                {r.orders.map((o, i) => (
                  <span key={o.ref}>
                    {i > 0 && " · "}
                    <a href="#" onClick={(e) => { e.preventDefault();
                                                  e.stopPropagation();
                                                  onOpenIpr?.(o.ref); }}
                       style={{ color: "var(--sp-navy)" }}>{o.ref}</a>
                  </span>
                ))}
                <div style={{ fontSize: 11, color: "#5a6b78" }}>
                  {[...new Set(r.orders.map((o) => o.supplier))].join(" · ")}
                  {r.orders.length > 1 && (
                    <b style={{ color: "#8a6d00" }}> · consolidated</b>)}
                </div>
              </td>
              <td style={td}>{r.mode}</td>
              <td style={{ ...td, fontSize: 12 }}>
                {r.container_awb || r.bl_no || "—"}
                {r.vessel_flight && (
                  <div style={{ fontSize: 11, color: "#5a6b78" }}>
                    {r.vessel_flight}</div>)}
              </td>
              <td style={td}>{r.eta || "—"}</td>
              <td style={td}>
                <StatusChip status={r.status} />
                {r.live_status && (
                  <div style={{ fontSize: 10.5, color: "#5a6b78" }}>
                    live: {r.live_status.replace(/_/g, " ").toLowerCase()}
                  </div>)}
              </td>
              <td style={td}>{r.documents}
                {r.shared_with_agent_at && (
                  <div style={{ fontSize: 10.5, color: "#1a7f37" }}>
                    ✓ shared</div>)}
              </td>
              <td style={td}>{r.irn || "—"}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={8} style={{ ...td, textAlign: "center",
                                         color: "#5a6b78" }}>
              {q ? "Nothing matches." : "No shipments booked yet."}</td></tr>
          )}
        </tbody>
      </table>
      </div>
    </section>
  );
}

// Cargo picker across orders — the heart of consolidation.
function BookShipment({ onCancel, onBooked }) {
  const [opts, setOpts] = useState(null);
  const [qty, setQty] = useState({});          // line id -> qty
  const [f, setF] = useState({ mode: "SEA", carrier_scac: "", bl_no: "",
    container_awb: "", vessel_flight: "", etd: "", eta: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/shipments/cargo-options").then(setOpts)
      .catch((e) => setError(e.message));
  }, []);

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const rows = Object.entries(qty)
    .filter(([, v]) => parseFloat(v) > 0)
    .map(([id, v]) => ({ ipr_line_id: Number(id), qty: v }));
  const ordersPicked = new Set(
    (opts || []).filter((o) => o.lines.some((l) => parseFloat(qty[l.id]) > 0))
      .map((o) => o.ipr_ref));

  async function book() {
    setBusy(true); setError(null);
    try {
      await api("/shipments", { method: "POST", body: { ...f, rows } });
      onBooked();
    } catch (e) { setError(e.message); setBusy(false); }
  }

  if (!opts) return <section style={card}>{error || "Loading…"}</section>;

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          Book a shipment</h2>
        <button onClick={onCancel}
                style={{ ...ghostButton, marginLeft: "auto" }}>Cancel</button>
      </div>
      <p style={{ fontSize: 12.5, color: "#5a6b78", margin: "6px 0 12px" }}>
        Tick cargo from as many orders as travel together — one supplier
        clubbing orders, or the forwarder consolidating several suppliers
        into one container. Clearing charges apportion by goods value.
      </p>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                    marginBottom: 12 }}>
        <label style={{ fontSize: 12 }}>Mode
          <select value={f.mode} onChange={set("mode")}
                  style={{ ...inputStyle, width: 90 }}>
            <option>SEA</option><option>AIR</option></select></label>
        <label style={{ fontSize: 12 }}>Carrier SCAC
          <input value={f.carrier_scac} onChange={set("carrier_scac")}
                 style={{ ...inputStyle, width: 110 }} /></label>
        <label style={{ fontSize: 12 }}>Container / AWB
          <input value={f.container_awb} onChange={set("container_awb")}
                 style={{ ...inputStyle, width: 160 }} /></label>
        <label style={{ fontSize: 12 }}>B/L no.
          <input value={f.bl_no} onChange={set("bl_no")}
                 style={{ ...inputStyle, width: 150 }} /></label>
        <label style={{ fontSize: 12 }}>Vessel / flight
          <input value={f.vessel_flight} onChange={set("vessel_flight")}
                 style={{ ...inputStyle, width: 150 }} /></label>
        <label style={{ fontSize: 12 }}>ETD
          <input type="date" value={f.etd} onChange={set("etd")}
                 style={{ ...inputStyle, width: 145 }} /></label>
        <label style={{ fontSize: 12 }}>ETA
          <input type="date" value={f.eta} onChange={set("eta")}
                 style={{ ...inputStyle, width: 145 }} /></label>
      </div>

      {opts.length === 0 && (
        <p style={{ fontSize: 13, color: "#5a6b78" }}>
          No authorised order has cargo left to ship.</p>
      )}
      {opts.map((o) => (
        <div key={o.ipr_ref} style={{ border: "1px solid #dde5ea",
          borderRadius: 8, padding: 10, marginBottom: 10,
          background: ordersPicked.has(o.ipr_ref) ? "#f2f8f4" : undefined }}>
          <div style={{ fontWeight: 600, color: "var(--sp-navy)" }}>
            {o.ipr_ref}
            <span style={{ fontWeight: 400, color: "#5a6b78", fontSize: 12.5 }}>
              {" "}· {o.supplier}{o.country ? ` · ${o.country}` : ""}
              {o.incoterm ? ` · ${o.incoterm}` : ""}</span>
          </div>
          <table style={{ borderCollapse: "collapse", fontSize: 12.5,
                          marginTop: 6, width: "100%" }}>
            <tbody>
              {o.lines.map((l) => (
                <tr key={l.id}>
                  <td style={{ ...td, padding: "3px 6px" }}>{l.line_no}</td>
                  <td style={{ ...td, padding: "3px 6px" }}>{l.description}</td>
                  <td style={{ ...td, padding: "3px 6px", color: "#5a6b78",
                               whiteSpace: "nowrap" }}>
                    {l.remaining} {l.unit} left</td>
                  <td style={{ ...td, padding: "3px 6px", width: 150 }}>
                    <input type="number" min="0" max={l.remaining}
                           placeholder="qty on this shipment"
                           value={qty[l.id] || ""}
                           onChange={(e) => setQty({ ...qty,
                             [l.id]: e.target.value })}
                           style={{ ...inputStyle, width: 140 }} />
                  </td>
                  <td style={{ ...td, padding: "3px 6px" }}>
                    <button style={{ ...ghostButton, padding: "1px 8px",
                                     fontSize: 11 }}
                            onClick={() => setQty({ ...qty,
                              [l.id]: String(l.remaining) })}>all</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      <div style={{ display: "flex", gap: 10, alignItems: "center",
                    marginTop: 8 }}>
        <button onClick={book} disabled={busy || rows.length === 0}
                style={buttonStyle}>
          {busy ? "Booking…" : `Book shipment (${rows.length} line(s) from `
            + `${ordersPicked.size} order(s))`}</button>
        {ordersPicked.size > 1 && (
          <span style={{ fontSize: 12, color: "#8a6d00" }}>
            Consolidated — charges will apportion by goods value.</span>
        )}
      </div>
    </section>
  );
}
