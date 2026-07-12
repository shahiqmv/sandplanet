import { useEffect, useState } from "react";
import { api } from "./api.js";
import { RefStamp, card, td, th } from "./ui.jsx";

// Project cost control (§6C.4): contract value vs committed / incurred /
// paid, per site and by cost head, % consumed vs % elapsed, drillable to
// the source postings. Cost figures are commercially sensitive (§6C.5).

const money = (v) => v == null ? "—"
  : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2 });
const pct = (v) => v == null ? "—" : `${v}%`;

export default function CostControlPage({ onOpenDoc, me }) {
  const [pf, setPf] = useState(null);
  const [openSite, setOpenSite] = useState(null);
  const [detail, setDetail] = useState(null);
  const [drill, setDrill] = useState(null);   // {head, state, rows}
  const [rate, setRate] = useState(null);
  const [error, setError] = useState(null);

  const canSetRate = ["ADMIN", "FINANCE", "QS"].includes(me?.role);

  function loadRate() {
    api("/fx/usd-rate").then(setRate).catch(() => {});
  }
  useEffect(() => {
    api("/cost/portfolio").then(setPf).catch((e) => setError(e.message));
    loadRate();
  }, []);

  async function editRate() {
    const v = window.prompt("MVR per 1 USD (rate used to convert site costs "
      + "to USD):", rate ? String(rate.rate) : "15.42");
    if (v === null) return;
    try {
      await api("/fx/usd-rate", { method: "PUT", body: { rate: Number(v) } });
      loadRate();
      api("/cost/portfolio").then(setPf);   // refresh figures at the new rate
      if (openSite) api(`/cost/site/${openSite}`).then(setDetail);
    } catch (e) { setError(e.message); }
  }

  const openDetail = (siteId) => {
    if (openSite === siteId) { setOpenSite(null); setDetail(null); return; }
    setOpenSite(siteId); setDetail(null); setDrill(null);
    api(`/cost/site/${siteId}`).then(setDetail).catch((e) =>
      setError(e.message));
  };

  const openDrill = (siteId, head, state) => {
    setDrill({ head, state, rows: null });
    api(`/cost/site/${siteId}/postings?head=${encodeURIComponent(head)}`
        + `&state=${state}`)
      .then((rows) => setDrill({ head, state, rows }))
      .catch((e) => setError(e.message));
  };

  if (error) return <section style={card}><p style={{ color:
    "var(--red-fg)" }}>{error}</p></section>;
  if (!pf) return <section style={card}><p>Loading…</p></section>;

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 18 }}>
          Project cost control</h2>
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
          all figures in USD
          {rate && ` · MVR costs @ ${rate.rate}/USD`}
          {canSetRate && (
            <button onClick={editRate}
                    style={{ background: "none", border: "none",
                             color: "var(--navy)", cursor: "pointer",
                             textDecoration: "underline", fontSize: 12.5,
                             marginLeft: 6, padding: 0 }}>
              change rate</button>
          )}
        </span>
      </div>

      <div style={card}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={th}>Site</th>
            <th style={{ ...th, textAlign: "right" }}>Contract</th>
            <th style={{ ...th, textAlign: "right" }}>Committed</th>
            <th style={{ ...th, textAlign: "right" }}>Incurred</th>
            <th style={{ ...th, textAlign: "right" }}>Paid</th>
            <th style={th}>Consumed vs elapsed</th>
          </tr></thead>
          <tbody>
            {pf.sites.map((s) => (
              <tr key={s.site_id} onClick={() => openDetail(s.site_id)}
                  style={{ cursor: "pointer",
                           background: openSite === s.site_id
                             ? "var(--sand)" : undefined }}>
                <td style={td}><strong>{s.site_code}</strong>
                  <span style={{ color: "var(--muted)", marginLeft: 6,
                                 fontSize: 12 }}>{s.site_name}</span></td>
                <td style={num}>{money(s.contract_value)}</td>
                <td style={num}>{money(s.committed)}</td>
                <td style={num}>{money(s.incurred)}</td>
                <td style={num}>{money(s.paid)}</td>
                <td style={td}>
                  <span style={{ color: s.outpacing ? "var(--red-fg)"
                                 : "var(--navy)" }}>
                    {pct(s.pct_consumed)}</span>
                  <span style={{ color: "var(--muted)" }}> vs {pct(
                    s.pct_elapsed)}</span>
                  {s.outpacing && (
                    <span style={{ marginLeft: 6, background: "var(--red-bg)",
                                   color: "var(--red-fg)", fontSize: 11,
                                   padding: "1px 6px", borderRadius: 5 }}>
                      outpacing</span>
                  )}
                </td>
              </tr>
            ))}
            {pf.sites.length === 0 && (
              <tr><td style={td} colSpan={6}>No cost recorded yet.</td></tr>
            )}
          </tbody>
          {pf.sites.length > 0 && (
            <tfoot><tr style={{ borderTop: "2px solid var(--navy)" }}>
              <td style={{ ...td, fontWeight: 700 }}>Portfolio</td>
              <td style={numB}>{money(pf.totals.contract)}</td>
              <td style={numB}>{money(pf.totals.committed)}</td>
              <td style={numB}>{money(pf.totals.incurred)}</td>
              <td style={numB}>{money(pf.totals.paid)}</td>
              <td style={td}></td>
            </tr></tfoot>
          )}
        </table>
      </div>

      {detail && (
        <div style={card}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 16,
                        flexWrap: "wrap" }}>
            <h3 style={{ margin: 0, fontSize: 15, color: "var(--navy)" }}>
              {detail.site_code} — {detail.site_name}</h3>
            <span style={{ fontSize: 13, color: "var(--muted)" }}>
              Contract USD {money(detail.contract_value)}
              {detail.remaining != null &&
                ` · remaining USD ${money(detail.remaining)}`}</span>
            <span style={{ marginLeft: "auto", fontSize: 13 }}>
              consumed <strong>{pct(detail.pct_consumed)}</strong>
              {" "}vs elapsed {pct(detail.pct_elapsed)}</span>
          </div>

          <div style={{ display: "flex", gap: 20, margin: "10px 0",
                        flexWrap: "wrap" }}>
            {[["Committed", detail.committed],
              ["Incurred", detail.incurred],
              ["Paid", detail.paid]].map(([k, v]) => (
              <div key={k}>
                <div style={{ fontSize: 12, color: "var(--muted)" }}>{k}</div>
                <div style={{ fontSize: 18, fontFamily: "var(--font-mono)",
                              color: "var(--navy)" }}>USD {money(v)}</div>
              </div>
            ))}
          </div>

          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>Cost head</th>
              <th style={{ ...th, textAlign: "right" }}>Committed</th>
              <th style={{ ...th, textAlign: "right" }}>Incurred</th>
              <th style={{ ...th, textAlign: "right" }}>Paid</th>
            </tr></thead>
            <tbody>
              {detail.by_cost_head.map((h) => (
                <tr key={h.cost_head}>
                  <td style={td}>{h.cost_head}</td>
                  {["committed", "incurred", "paid"].map((s) => (
                    <td key={s} style={num}>
                      {Number(h[s]) !== 0 ? (
                        <a href="#" onClick={(e) => { e.preventDefault();
                          openDrill(detail.site_id, h.cost_head,
                                    s.toUpperCase()); }}
                           style={{ textDecoration: "none" }}>
                          {money(h[s])}</a>
                      ) : money(h[s])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ fontSize: 11, color: "var(--muted)", marginTop: 6 }}>
            Click any figure to see the source documents behind it.</p>

          {drill && (
            <div style={{ border: "1px solid var(--line)", borderRadius: 8,
                          padding: 10, marginTop: 8 }}>
              <div style={{ fontSize: 13, fontWeight: 600,
                            color: "var(--navy)" }}>
                {drill.head} · {drill.state}</div>
              {!drill.rows ? <p style={{ fontSize: 12 }}>Loading…</p> : (
                <table style={{ width: "100%", borderCollapse: "collapse",
                                marginTop: 4 }}>
                  <tbody>
                    {drill.rows.map((r) => (
                      <tr key={r.id}>
                        <td style={{ ...td, width: 120 }}>
                          {r.ref && onOpenDoc && !r.ref.includes(" ") ? (
                            <a href="#" onClick={(e) => { e.preventDefault();
                              onOpenDoc(r.ref); }}
                               style={{ textDecoration: "none" }}>
                              <RefStamp small>{r.ref}</RefStamp></a>
                          ) : <span style={{ fontSize: 12 }}>{r.ref}</span>}
                        </td>
                        <td style={{ ...td, fontSize: 12,
                                     color: "var(--muted)" }}>
                          {r.source}{r.is_reversal ? " · reversal" : ""}</td>
                        <td style={td}>{r.posted_on}</td>
                        <td style={num}>{money(r.amount)}
                          {r.currency_original === "MVR" && (
                            <div style={{ fontSize: 10, color: "var(--muted)" }}>
                              MVR {money(r.amount_original)}</div>
                          )}
                        </td>
                      </tr>
                    ))}
                    {drill.rows.length === 0 && (
                      <tr><td style={td} colSpan={4}>No postings.</td></tr>
                    )}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

const num = { ...td, textAlign: "right", fontFamily: "var(--font-mono)" };
const numB = { ...num, fontWeight: 700 };
