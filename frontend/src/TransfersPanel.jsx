import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Site-to-site movement of materials and tools (MTN). Raised by the site
// team, released by the sending site's PM, then counted in at the far end —
// the stock is on neither ledger while it is on the boat (owner 2026-08-16).

const qty = (v) => v == null ? "—"
  : Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 });

const CAN_RAISE = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "ADMIN"];

const TONE = {
  DRAFT: "#8a6d00", APPROVED: "#2f6f9f", DESPATCHED: "#b35900",
  RECEIVED: "#1a7f37", CANCELLED: "#8a94a0",
};

export default function TransfersPanel({ site, me, sites, onStockMoved }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [raising, setRaising] = useState(false);
  const [receiving, setReceiving] = useState(null);   // transfer being counted
  const [counts, setCounts] = useState({});
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api(`/transfers?site=${site.id}`)
    .then((d) => setRows(d.transfers)).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [site.id]);

  async function act(tr, action, body = {}) {
    setBusy(true);
    try {
      await api(`/transfers/${tr.id}`, { method: "POST",
                                         body: { action, ...body } });
      setReceiving(null); setCounts({}); setNote("");
      await load();
      setError(null);
      // Despatching and receiving both move the ledger sitting above this
      // panel — leaving it showing the old on-hand would have the storeman
      // doubting the transfer went through.
      if (["despatch", "receive"].includes(action) && onStockMoved) {
        onStockMoved();
      }
    } catch (e) { setError(e.message); }
    setBusy(false);
  }

  if (!rows) return <section style={card}>Loading transfers…</section>;

  const outgoing = rows.filter((t) => t.from_site_id === site.id);
  const incoming = rows.filter((t) => t.to_site_id === site.id);

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap" }}>
        <h3 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 16 }}>
          Transfers
        </h3>
        <span style={{ fontSize: 12.5, color: "var(--muted)", flex: 1 }}>
          Materials and tools moving to or from {site.code}.
        </span>
        {CAN_RAISE.includes(me.role) && !raising && (
          <Btn onClick={() => setRaising(true)}>+ Send to another site</Btn>
        )}
      </div>
      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      {raising && (
        <RaiseForm site={site} sites={sites}
                   onCancel={() => setRaising(false)}
                   onDone={() => { setRaising(false); load(); }} />
      )}

      {incoming.length > 0 && (
        <>
          <h4 style={sub}>Coming to {site.code}</h4>
          <Table rows={incoming} site={site} me={me} busy={busy}
                 onAct={act} onReceive={(t) => {
                   setReceiving(t);
                   setCounts(Object.fromEntries(
                     t.lines.map((l) => [l.id, String(l.qty)])));
                 }} />
        </>
      )}
      {outgoing.length > 0 && (
        <>
          <h4 style={sub}>Leaving {site.code}</h4>
          <Table rows={outgoing} site={site} me={me} busy={busy}
                 onAct={act} onReceive={null} />
        </>
      )}
      {!rows.length && (
        <p style={{ fontSize: 13, color: "var(--muted)" }}>
          Nothing has been transferred to or from this site yet.
        </p>
      )}

      {receiving && (
        <ReceiveSheet tr={receiving} counts={counts} setCounts={setCounts}
                      note={note} setNote={setNote} busy={busy}
                      onCancel={() => setReceiving(null)}
                      onConfirm={() => act(receiving, "receive",
                                           { counts, note })} />
      )}
    </section>
  );
}

const sub = { margin: "16px 0 6px", fontSize: 12.5, fontWeight: 700,
              color: "#6b7a86", textTransform: "uppercase",
              letterSpacing: .4 };

function Table({ rows, site, me, busy, onAct, onReceive }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse",
                      fontSize: 12.5 }}>
        <thead><tr>
          <th style={th}>Ref</th><th style={th}>Route</th>
          <th style={th}>Contents</th><th style={th}>Status</th>
          <th style={th}></th>
        </tr></thead>
        <tbody>
          {rows.map((t) => {
            const isFrom = t.from_site_id === site.id;
            const short = t.lines.some((l) => Number(l.shortage) > 0);
            return (
              <tr key={t.id} style={{ borderTop: "1px solid var(--sp-border)" }}>
                <td style={{ ...td, fontWeight: 600, whiteSpace: "nowrap" }}>
                  {t.ref}
                  <div style={{ fontSize: 11, color: "var(--muted)",
                                fontWeight: 400 }}>{t.doc_date}</div>
                </td>
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  {t.from_site} → {t.to_site}
                  {t.to_project && <div style={{ fontSize: 11,
                                                 color: "var(--muted)" }}>
                    {t.to_project}</div>}
                </td>
                <td style={td}>
                  {t.lines.map((l) => (
                    <div key={l.id}>
                      {l.description}
                      {l.tool_id ? (l.serial_no ? ` · ${l.serial_no}` : "")
                        : ` — ${qty(l.qty)} ${l.unit || ""}`}
                      {Number(l.shortage) > 0 && (
                        <b style={{ color: "#c0392b" }}>
                          {"  "}({qty(l.shortage)} short)</b>
                      )}
                    </div>
                  ))}
                  {t.receipt_note && (
                    <div style={{ fontSize: 11, color: "var(--muted)" }}>
                      “{t.receipt_note}”</div>
                  )}
                </td>
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  <b style={{ color: TONE[t.status] || "#333" }}>
                    {t.status_label}</b>
                  {short && t.status === "RECEIVED" && (
                    <div style={{ fontSize: 11, color: "#c0392b" }}>
                      short on arrival</div>
                  )}
                  {t.received_by && (
                    <div style={{ fontSize: 11, color: "var(--muted)" }}>
                      by {t.received_by}</div>
                  )}
                </td>
                <td style={{ ...td, whiteSpace: "nowrap", textAlign: "right" }}>
                  {isFrom && t.status === "DRAFT"
                    && ["PM", "ADMIN"].includes(me.role) && (
                    <Btn disabled={busy}
                         onClick={() => onAct(t, "approve")}>Approve</Btn>
                  )}
                  {isFrom && t.status === "APPROVED" && (
                    <Btn disabled={busy}
                         onClick={() => onAct(t, "despatch")}>Despatch</Btn>
                  )}
                  {isFrom && ["DRAFT", "APPROVED"].includes(t.status) && (
                    <button style={ghostButton} disabled={busy}
                      onClick={() => {
                        const why = window.prompt("Cancel this transfer — why?");
                        if (why) onAct(t, "cancel", { reason: why });
                      }}>Cancel</button>
                  )}
                  {!isFrom && t.status === "DESPATCHED" && onReceive && (
                    <Btn disabled={busy} onClick={() => onReceive(t)}>
                      Count it in</Btn>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RaiseForm({ site, sites, onCancel, onDone }) {
  const [avail, setAvail] = useState(null);
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const [picked, setPicked] = useState({});     // item id -> qty
  const [tools, setTools] = useState({});       // tool id -> bool
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api(`/sites/${site.id}/transferable`).then(setAvail)
      .catch((e) => setError(e.message));
  }, [site.id]);

  async function submit() {
    const lines = [
      ...Object.entries(picked).filter(([, q]) => Number(q) > 0)
        .map(([id, q]) => ({ item_id: Number(id), qty: q })),
      ...Object.entries(tools).filter(([, on]) => on)
        .map(([id]) => ({ tool_id: Number(id) })),
    ];
    if (!to) { setError("Choose the site it is going to."); return; }
    if (!lines.length) { setError("Pick something to send."); return; }
    setBusy(true);
    try {
      await api("/transfers", { method: "POST", body: {
        from_site_id: site.id, to_site_id: Number(to), reason, lines } });
      onDone();
    } catch (e) { setError(e.message); setBusy(false); }
  }

  if (!avail) return <p style={{ fontSize: 13 }}>Loading what's on site…</p>;

  return (
    <div style={{ border: "1px solid var(--sp-border)", borderRadius: 8,
                  padding: 12, marginTop: 12, background: "#fbfcfd" }}>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                    alignItems: "flex-end" }}>
        <label style={{ fontSize: 12.5 }}>
          Send to
          <select value={to} onChange={(e) => setTo(e.target.value)}
                  style={{ ...inputStyle, width: 200, marginTop: 3 }}>
            <option value="">— choose a site —</option>
            {sites.filter((s) => s.id !== site.id).map((s) => (
              <option key={s.id} value={s.id}>{s.code} · {s.name}</option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: 12.5, flex: 1, minWidth: 220 }}>
          Why
          <input value={reason} onChange={(e) => setReason(e.target.value)}
                 placeholder="e.g. project split — outfall works"
                 style={{ ...inputStyle, marginTop: 3, width: "100%" }} />
        </label>
      </div>

      <h4 style={sub}>Materials on hand</h4>
      <div style={{ maxHeight: 220, overflowY: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 12.5 }}>
          <thead><tr>
            <th style={th}>Item</th><th style={{ ...th, textAlign: "right" }}>
              On hand</th><th style={{ ...th, textAlign: "right" }}>Send</th>
          </tr></thead>
          <tbody>
            {avail.items.map((it) => (
              <tr key={it.item_id}
                  style={{ borderTop: "1px solid var(--sp-border)" }}>
                <td style={td}>{it.code} · {it.description}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  {qty(it.on_hand)} {it.unit}</td>
                <td style={{ ...td, textAlign: "right" }}>
                  <input type="number" min="0" max={it.on_hand} step="any"
                    value={picked[it.item_id] || ""}
                    onChange={(e) => setPicked({ ...picked,
                                                 [it.item_id]: e.target.value })}
                    style={{ ...inputStyle, width: 90, textAlign: "right" }} />
                </td>
              </tr>
            ))}
            {!avail.items.length && (
              <tr><td style={td} colSpan={3}>No stock on hand.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {avail.tools.length > 0 && (
        <>
          <h4 style={sub}>Tools</h4>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {avail.tools.map((t) => (
              <label key={t.id} style={{ fontSize: 12.5, border:
                        "1px solid var(--sp-border)", borderRadius: 6,
                        padding: "5px 9px", cursor: "pointer" }}>
                <input type="checkbox" checked={!!tools[t.id]}
                  onChange={(e) => setTools({ ...tools,
                                              [t.id]: e.target.checked })}
                  style={{ marginRight: 6 }} />
                {t.name}{t.serial_no ? ` · ${t.serial_no}` : ""}
                {t.state !== "IN_USE" && (
                  <span style={{ color: "#b35900" }}> ({t.state.toLowerCase()
                    .replace("_", " ")})</span>
                )}
              </label>
            ))}
          </div>
        </>
      )}

      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Btn disabled={busy} onClick={submit}>Raise transfer</Btn>
        <button style={ghostButton} onClick={onCancel}>Cancel</button>
      </div>
      <p style={{ fontSize: 11.5, color: "var(--muted)", margin: "8px 0 0" }}>
        Nothing leaves the ledger until {site.code}'s PM approves it and the
        store despatches it.
      </p>
    </div>
  );
}

function ReceiveSheet({ tr, counts, setCounts, note, setNote, busy,
                        onCancel, onConfirm }) {
  return (
    <div style={{ border: "1px solid var(--sp-border)", borderRadius: 8,
                  padding: 12, marginTop: 12, background: "#fbfcfd" }}>
      <h4 style={{ margin: "0 0 4px", fontSize: 14, color: "var(--sp-navy)" }}>
        Counting in {tr.ref} from {tr.from_site}
      </h4>
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "0 0 10px" }}>
        Enter what actually arrived. Anything short stays on the record for
        both sites to settle — it is not written off here.
      </p>
      <table style={{ width: "100%", borderCollapse: "collapse",
                      fontSize: 12.5 }}>
        <thead><tr>
          <th style={th}>Item</th>
          <th style={{ ...th, textAlign: "right" }}>Sent</th>
          <th style={{ ...th, textAlign: "right" }}>Received</th>
        </tr></thead>
        <tbody>
          {tr.lines.map((l) => (
            <tr key={l.id} style={{ borderTop: "1px solid var(--sp-border)" }}>
              <td style={td}>
                {l.description}
                {l.tool_id && l.serial_no ? ` · ${l.serial_no}` : ""}
              </td>
              <td style={{ ...td, textAlign: "right" }}>
                {qty(l.qty)} {l.unit || ""}</td>
              <td style={{ ...td, textAlign: "right" }}>
                <input type="number" min="0" max={l.qty} step="any"
                  value={counts[l.id] ?? ""}
                  onChange={(e) => setCounts({ ...counts,
                                               [l.id]: e.target.value })}
                  style={{ ...inputStyle, width: 90, textAlign: "right" }} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <label style={{ display: "block", fontSize: 12.5, marginTop: 10 }}>
        Note (if anything is short or damaged)
        <input value={note} onChange={(e) => setNote(e.target.value)}
               placeholder="e.g. two bags burst in transit"
               style={{ ...inputStyle, width: "100%", marginTop: 3 }} />
      </label>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Btn disabled={busy} onClick={onConfirm}>Confirm receipt</Btn>
        <button style={ghostButton} onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
