import { useEffect, useState } from "react";
import { api } from "./api.js";
import { CaseDetail } from "./OnboardingPage.jsx";
import { Chip, Stat, card, inputStyle, td, th } from "./ui.jsx";

// The business-visa schedule (owner 2026-08-09): everyone in the country on a
// BV with the expiry clock front and centre, separate from the onboarding
// case list. Rows open the full onboarding case.
const LEVEL = {
  EXPIRED: ["alert", "Expired"],
  T3: ["alert", "≤ 3 days"],
  T7: ["warn", "≤ 7 days"],
  T14: ["warn", "≤ 14 days"],
  OK: ["ok", "OK"],
};
const PURPOSE = { RECRUITMENT: "Recruitment", SUBCONTRACT: "Subcontract" };

const fmt = (d) => d ? new Date(d).toLocaleDateString("en-GB",
  { day: "2-digit", month: "short", year: "numeric" }) : "—";

export default function BvRegisterPage({ me }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState(null);
  const [showClosed, setShowClosed] = useState(false);

  const load = () => api("/onboarding/bv-register").then(setData)
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  if (openId) return <CaseDetail id={openId} me={me}
    onBack={() => { setOpenId(null); load(); }} />;
  if (error) return <p style={{ color: "var(--red-fg)" }}>{error}</p>;
  if (!data) return <div style={card}>Loading…</div>;

  const match = (r) => !q.trim()
    || [r.name, r.ref, r.passport_no, r.site, r.subcontractor]
      .join(" ").toLowerCase().includes(q.trim().toLowerCase());

  const Rows = ({ list, showDays }) => list.filter(match).map((r) => {
    const [tone, label] = LEVEL[r.level] || [];
    return (
      <tr key={r.case_id} style={{ cursor: "pointer" }}
        onClick={() => setOpenId(r.case_id)}>
        <td style={{ ...td, fontFamily: "var(--font-mono)" }}>{r.ref}</td>
        <td style={td}><b>{r.name}</b>
          <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
            {r.nationality || "—"} · {r.passport_no || "no passport"}</div></td>
        <td style={td}>{r.site || "—"}
          <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
            {r.position || ""}</div></td>
        <td style={td}>{PURPOSE[r.purpose] || "—"}
          {r.subcontractor && <div style={{ fontSize: 11.5,
            color: "var(--muted)" }}>{r.subcontractor}</div>}</td>
        <td style={td}>{fmt(r.approved_on)}</td>
        <td style={td}>{fmt(r.arrived)}</td>
        <td style={td}>{fmt(r.expiry)}
          {r.renewals > 0 && <div style={{ fontSize: 11,
            color: "var(--muted)" }}>{r.renewals}/2 extensions</div>}</td>
        {showDays ? (
          <td style={td}>
            {r.level && <Chip tone={tone}>
              {r.level === "OK" ? `${r.days_left}d left`
                : r.level === "EXPIRED"
                  ? `${label} ${-r.days_left}d ago`
                  : `${r.days_left}d — ${label}`}</Chip>}
          </td>
        ) : (
          <td style={td}>
            {/* A visa runs from the day it is approved, so a man who has not
                flown yet can already be inside his window. The stage alone
                used to be all this column said. */}
            {r.expiry_missing ? <Chip tone="alert">Visa dates missing</Chip>
              : r.level ? <Chip tone={tone}>
                  {r.level === "OK" ? `${r.days_left}d left`
                    : r.level === "EXPIRED"
                      ? `${label} ${-r.days_left}d ago`
                      : `${r.days_left}d — ${label}`}</Chip>
              : r.converted ? <Chip tone="ok">Converted to WP</Chip>
              : <Chip tone="info">
                  {(r.stage || r.doc_status).replace(/_/g, " ")}</Chip>}
            <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
              {(r.stage || r.doc_status).replace(/_/g, " ")}</div>
          </td>
        )}
      </tr>
    );
  });

  const head = (cols) => (
    <thead><tr>{cols.map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12,
        flexWrap: "wrap", marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Business Visa register</h2>
        <input style={{ ...inputStyle, width: 240, marginLeft: "auto" }}
          placeholder="Search name / ref / passport…"
          value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      <div style={{ ...card, display: "flex", gap: 20, flexWrap: "wrap" }}>
        <Stat value={data.counts.in_country} label="In country on BV"
          context="visa clock running" tone="info" />
        <Stat value={data.counts.expiring} label="Expiring ≤ 14 days"
          context={data.counts.expiring
            ? "extend or convert now — arrived or not" : "none"}
          tone={data.counts.expiring ? "warn" : "ok"} />
        <Stat value={data.counts.expired} label="Expired"
          context={data.counts.expired ? "overstaying — act today" : "none"}
          tone={data.counts.expired ? "alert" : "ok"} />
        <Stat value={data.counts.pipeline} label="In process"
          context="not arrived yet" tone="info" />
        {data.counts.awaiting_expiry > 0 && (
          <Stat value={data.counts.awaiting_expiry} label="Visa dates missing"
            context="approved — record the dates" tone="alert" />)}
      </div>

      <div style={{ ...card, padding: 0, overflowX: "auto" }}>
        <div style={{ padding: "12px 14px 0", fontWeight: 600 }}>
          In country — by expiry</div>
        <table style={{ width: "100%", borderCollapse: "collapse",
          fontSize: 13 }}>
          {head(["Ref", "Candidate", "Site", "Purpose", "Approved",
                 "Arrived", "Visa expiry", "Countdown"])}
          <tbody>
            <Rows list={data.in_country} showDays />
            {!data.in_country.length && <tr><td style={td} colSpan={8}>
              Nobody is in the country on a business visa.</td></tr>}
          </tbody>
        </table>
      </div>

      {data.pipeline.length > 0 && (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <div style={{ padding: "12px 14px 0", fontWeight: 600 }}>
            In process — not arrived
            <span style={{ fontWeight: 400, fontSize: 12,
                           color: "var(--muted)" }}>
              {" "}· an approved visa is already counting down</span></div>
          <table style={{ width: "100%", borderCollapse: "collapse",
            fontSize: 13 }}>
            {head(["Ref", "Candidate", "Site", "Purpose", "Approved",
                   "Arrived", "Visa expiry", "Visa clock"])}
            <tbody><Rows list={data.pipeline} /></tbody>
          </table>
        </div>
      )}

      <div style={{ margin: "8px 0" }}>
        <button onClick={() => setShowClosed(!showClosed)}
          style={{ background: "none", border: "none", cursor: "pointer",
            color: "var(--navy)", fontSize: 13, fontWeight: 600, padding: 0 }}>
          {showClosed ? "▾" : "▸"} Closed — converted or departed
          {" "}({data.closed.length})</button>
      </div>
      {showClosed && data.closed.length > 0 && (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
            fontSize: 13 }}>
            {head(["Ref", "Candidate", "Site", "Purpose", "Approved",
                   "Arrived", "Visa expiry", "Outcome"])}
            <tbody><Rows list={data.closed} /></tbody>
          </table>
        </div>
      )}
    </div>
  );
}
