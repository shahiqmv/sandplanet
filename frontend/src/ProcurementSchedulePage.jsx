import { Fragment, useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { MovementsTable } from "./ImportOrders.jsx";
import { shrinkPhoto } from "./imageResize.js";
import { Btn, Chip, RefStamp, card, inputStyle } from "./ui.jsx";

const STATUS_TONE = {
  DRAFT: "info", SUBMITTED: "warn", CONFIRMED: "warn", SIGNED_OFF: "ok",
  CANCELLED: "alert",
};
// Whose turn it is at each stage — spelled out so a submitted schedule never
// looks stuck (two-step control: Purchasing confirms, then the Director signs).
const WHOSE_TURN = {
  DRAFT: "Being planned by the PM",
  SUBMITTED: "Awaiting Purchasing confirmation",
  CONFIRMED: "Awaiting Director sign-off",
};
const STATE_TONE = {
  PROPOSED: "info", CONFIRMED: "warn", SIGNED_OFF: "ok", CANCELLED: "alert",
};
const SUPPLY = [["CONTRACTOR", "Contractor"], ["CLIENT", "Client"]];
// The commercial/project team proposes lines; Purchasing + PD are the gates.
const PROPOSE = ["QS", "PM", "SITE_ENGINEER", "SITE_ADMIN", "DIRECTOR", "ADMIN"];
const money = (v, c) => v == null ? "—"
  : `${c || ""} ${Number(v).toLocaleString("en-US",
      { minimumFractionDigits: 2 })}`.trim();
const fmt = (s) => s ? new Date(s).toLocaleDateString("en-GB",
  { day: "2-digit", month: "short", year: "numeric" }) : "—";

// Derived pipeline — the schedule watches execution. Six stages in flow order.
const STAGE_ABBR = { tds: "TDS", order: "ORD", production: "PRD",
  shipment: "SHP", delivery: "DEL", eta: "ETA" };
const STAGE_COLOR = { done: "var(--green-fg)", pending: "var(--amber-fg)",
  warn: "var(--red-fg)", none: "#c9d6df", na: "#e2e8ee" };
// Which stages are backed by a linkable execution document.
const LINK_SLOTS = [
  ["mar", "TDS / MAR", "mar_ref"],
  ["ipr", "Order (IPR)", "ipr_ref"],
  ["grn", "Delivery (GRN)", "grn_ref"],
];
const PRODUCTION = [["PENDING", "Pending"], ["IN_PRODUCTION", "In production"],
  ["COMPLETED", "Completed"]];

const RISK_TONE = { LATE: "alert", AT_RISK: "warn", ON_TRACK: "ok",
  DELIVERED: "info" };
const RISK_LABEL = { LATE: "Late", AT_RISK: "At risk", ON_TRACK: "On track",
  DELIVERED: "Delivered" };

// Live shipment tracking (from the linked IPR's shipment) shown inline on a
// planner line — see [[shipsgo-tracking]].
const TRACK_HEALTH = { UNTRACKED: "Not trackable", STALE: "No recent movement",
  FAILED: "Tracking failed", PENDING_REGISTRATION: "Registering…",
  ACTIVE: "Tracking", ARRIVED: "Arrived", MANUAL: "Manual" };
const TRACK_BAD = ["UNTRACKED", "STALE", "FAILED"];

function TrackingLine({ t }) {
  // The timeline opens in OUR modal, not a jump to the provider's site
  // (owner 2026-08-26); the live map stays available inside it.
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  if (!t) return null;
  const bad = TRACK_BAD.includes(t.health);
  const show = () => {
    setOpen(true);
    api(`/tracking/shipments/${t.shipment_id}/movements`)
      .then(setDetail).catch(() => setDetail({ movements: [] }));
  };
  return (
    <div style={{ fontSize: 9.5, marginTop: 3,
      color: bad ? "var(--amber-fg)" : "var(--muted)" }}>
      <a href="#" onClick={(e) => { e.preventDefault(); show(); }}
         style={{ color: "inherit", textDecoration: "none" }}
         title="Open the movement timeline">
        🚢 {t.live_status || TRACK_HEALTH[t.health] || "—"}
        {t.current_eta ? ` · ETA ${fmt(t.current_eta)}` : ""}
        <span style={{ color: "var(--sky)" }}> · timeline ▸</span>
      </a>
      {open && (
        <div onClick={() => setOpen(false)}
             style={{ position: "fixed", inset: 0,
                      background: "rgba(0,0,0,.4)", display: "flex",
                      alignItems: "center", justifyContent: "center",
                      zIndex: 70, padding: 16 }}>
          <div onClick={(e) => e.stopPropagation()}
               style={{ ...card, maxWidth: 620, width: "94vw",
                        maxHeight: "80vh", overflowY: "auto", margin: 0,
                        fontSize: 13, color: "var(--ink, #1c2b36)" }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
              <strong>Shipment tracking
                {t.ipr_ref ? ` — ${t.ipr_ref}` : ""}</strong>
              <span style={{ color: "#5a6b78", fontSize: 12 }}>
                {detail?.status || t.live_status || ""}
                {t.current_eta ? ` · ETA ${fmt(t.current_eta)}` : ""}</span>
              <span style={{ marginLeft: "auto", display: "flex", gap: 10 }}>
                {(detail?.map_url || t.map_url) && (
                  <a href={detail?.map_url || t.map_url} target="_blank"
                     rel="noreferrer" style={{ fontSize: 12 }}>
                    📍 Live position ↗</a>)}
                <a href="#" onClick={(e) => { e.preventDefault();
                                              setOpen(false); }}
                   style={{ fontSize: 12 }}>Close</a>
              </span>
            </div>
            {detail == null
              ? <p style={{ color: "#5a6b78", fontSize: 12 }}>Loading…</p>
              : detail.movements?.length
                ? <MovementsTable movements={detail.movements} />
                : <p style={{ color: "#5a6b78", fontSize: 12 }}>
                    No movements reported yet.</p>}
          </div>
        </div>
      )}
    </div>
  );
}

function ValueCell({ ln }) {
  return (
    <div>
      <div>{money(ln.estimated_value, ln.currency)}</div>
      {ln.committed && <div style={{ fontSize: 10.5, color: "var(--muted)" }}>
        ordered {money(ln.committed.value, ln.committed.currency)}</div>}
      {ln.variance != null && ln.variance !== 0 && (
        <div style={{ fontSize: 10.5, fontWeight: 600,
          color: ln.variance > 0 ? "var(--red-fg)" : "var(--green-fg)" }}>
          {ln.variance > 0 ? "over" : "under"}{" "}
          {money(Math.abs(ln.variance), "")}</div>)}
    </div>
  );
}

// The last day an order can go out and still make the required date. The PM
// SETS this — the app cannot know how long a mattress takes out of China in
// December against a panel board in a normal month, and product type, season,
// a war on the lane and the state of the port all move it. A date computed
// from figures the software invented would be worse than none, because it
// reads as authoritative (owner 2026-08-29).
function OrderByCell({ ln }) {
  if (ln.ipr_ref) {
    return (
      <span title="Ordered" style={{ color: "var(--muted)" }}>
        {ln.risk?.projected ? fmt(ln.risk.projected) : "ordered"}
      </span>
    );
  }
  if (!ln.order_by) {
    return (
      <span style={{ color: "var(--muted)" }}
            title="Not set — a PM decides this date; the app does not guess it">
        not set</span>
    );
  }
  const late = ln.risk?.order_overdue_days || 0;
  return (
    <span style={{ fontWeight: late ? 700 : 500,
                   color: late ? "#a3271b" : undefined }}>
      {fmt(ln.order_by)}
      {late > 0 && (
        <div style={{ fontSize: 11, fontWeight: 700 }}>
          {late}d overdue to order</div>
      )}
    </span>
  );
}

// Offered only when the PM has stated all three legs themselves. Filling the
// field from a country-table guess would dress a guess as a deadline.
// Country and the three legs, plus the date to order by. Shared by both
// halves of the editor: the PM plans them from the consultant's spec, and
// Purchasing refines them when a supplier quotes a real lead time. They used
// to sit only behind the commercial gate, which meant nobody could enter them
// on a draft schedule at all (owner 2026-08-30).
function LeadTimeFields({ f, set, setF }) {
  return (
    <>
        <L k="Source country"><input style={inputStyle}
          value={f.source_country || ""} onChange={set("source_country")} /></L>
        <L k="Manufacturing (days)"><input type="number" style={inputStyle}
          value={f.lead_time_days ?? ""} onChange={set("lead_time_days")} /></L>
        <L k="Shipping (days)"><input type="number" style={inputStyle}
          placeholder="by country if blank"
          value={f.shipping_days ?? ""} onChange={set("shipping_days")} /></L>
        <L k="Customs clearance (days)"><input type="number"
          style={inputStyle}
          value={f.clearance_days ?? ""}
          onChange={set("clearance_days")} /></L>
        <L k="Order by" wide>
          <div style={{ display: "flex", gap: 8, alignItems: "center",
                        flexWrap: "wrap" }}>
            <input type="date" style={{ ...inputStyle, width: "auto" }}
              value={f.order_by_date || ""}
              onChange={set("order_by_date")} />
            <SuggestOrderBy f={f} onUse={(d) =>
              setF((p) => ({ ...p, order_by_date: d }))} />
          </div>
          <div style={{ fontSize: 11.5, color: "var(--muted)",
                        marginTop: 3 }}>
            Your call. Production, sailing and clearing all move with the
            product, the season and whatever the lanes are doing — the app
            does not guess this.
          </div>
        </L>
    </>
  );
}

function SuggestOrderBy({ f, onUse }) {
  const legs = [f.lead_time_days, f.shipping_days, f.clearance_days];
  const ready = f.required_date && legs.every(
    (v) => v !== "" && v !== null && v !== undefined && !Number.isNaN(+v));
  if (!ready) {
    return (
      <span style={{ fontSize: 11.5, color: "var(--muted)" }}>
        enter the three legs and a required date to work it out
      </span>
    );
  }
  const total = legs.reduce((a, v) => a + Number(v), 0) + 5;   // site buffer
  const d = new Date(f.required_date);
  d.setDate(d.getDate() - total);
  const iso = d.toISOString().slice(0, 10);
  return (
    <Btn variant="ghost" onClick={() => onUse(iso)}
         title={`${legs[0]}d make + ${legs[1]}d ship + ${legs[2]}d clear `
                + "+ 5d to site, back from the required date"}>
      Work it out ({iso})
    </Btn>
  );
}

function RiskCell({ risk }) {
  if (!risk || risk.level === "NONE")
    return <span style={{ color: "var(--muted)" }}>—</span>;
  return (
    <span title={risk.reason + (risk.projected
      ? ` · projected ${fmt(risk.projected)}` : "")}>
      <Chip tone={RISK_TONE[risk.level] || "info"}>
        {RISK_LABEL[risk.level]}
        {risk.unordered && risk.level === "LATE" ? " ⚠" : ""}</Chip>
    </span>
  );
}

// "3 late · 5 at risk" header summary, red-first.
function RiskSummary({ counts }) {
  const late = counts?.LATE || 0, risk = counts?.AT_RISK || 0;
  if (!late && !risk) return null;
  return (
    <span style={{ display: "inline-flex", gap: 6 }}>
      {late > 0 && <Chip tone="alert">{late} late</Chip>}
      {risk > 0 && <Chip tone="warn">{risk} at risk</Chip>}
    </span>
  );
}

// The client live-link control: create/copy/regenerate/revoke the shareable,
// login-free URL the employer bookmarks for the always-current plan.
function ClientLink({ share, busy, onCreate, onRevoke }) {
  const [copied, setCopied] = useState(false);
  const url = share.path ? window.location.origin + share.path : "";
  const copy = () => {
    navigator.clipboard?.writeText(url).then(
      () => { setCopied(true); setTimeout(() => setCopied(false), 1800); },
      () => window.prompt("Client link:", url));
  };
  if (!share.path) {
    return <button style={linkBtn} disabled={busy} onClick={onCreate}
      title="Create a read-only live link to share with the client">
      🔗 Create client link</button>;
  }
  return (
    <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
      <button style={linkBtn} disabled={busy} onClick={copy}
        title={url}>🔗 {copied ? "Copied!" : "Copy client link"}</button>
      <button style={linkBtn} disabled={busy} onClick={onCreate}
        title="Issue a new link (revokes the current one)">Regenerate</button>
      <button style={{ ...linkBtn, color: "var(--red-fg)" }} disabled={busy}
        onClick={() => { if (window.confirm("Revoke the client link? The "
          + "current URL will stop working.")) onRevoke(); }}>Revoke</button>
    </span>
  );
}

function PipelineStrip({ stages }) {
  return (
    <div style={{ display: "flex", gap: 3 }}>
      {(stages || []).map((s) => (
        <span key={s.key} title={`${s.label}: ${s.detail}`
            + (s.ref ? ` (${s.ref})` : "")}
          style={{ display: "flex", flexDirection: "column",
            alignItems: "center", gap: 2, minWidth: 26 }}>
          <span style={{ width: 9, height: 9, borderRadius: 999,
            background: STAGE_COLOR[s.state] || "#c9d6df",
            border: s.state === "none" || s.state === "na"
              ? "1px solid #c9d6df" : "none" }} />
          <span style={{ fontSize: 8.5, color: "var(--muted)",
            letterSpacing: "0.02em" }}>{STAGE_ABBR[s.key]}</span>
        </span>
      ))}
    </div>
  );
}

// One line row in the schedule table. `member` = a line shown expanded under a
// bundle summary (indented, serial hidden).
// The line's reference thumbnail — read-only in the list (click to enlarge).
// It's added / replaced on the line's Edit form, not here.
function RefImage({ ln }) {
  const img = ln.reference_image;
  if (!img) return null;
  return (
    <a href={img} target="_blank" rel="noreferrer" title="Reference image"
      style={{ flexShrink: 0 }}>
      <img src={img} alt="" style={{ width: 42, height: 42, objectFit: "cover",
        borderRadius: 4, border: "1px solid var(--line)", display: "block" }} />
    </a>
  );
}

function LineRow({ ln, c, member, sel, on }) {
  return (
    <tr style={{ borderTop: member ? "1px dashed var(--line)"
      : "1px solid var(--line)",
      background: member ? "var(--sky-soft)" : undefined }}>
      <td style={{ ...cell, paddingLeft: member ? 26 : 10 }}>
        {member ? "" : ln.s_no}</td>
      <td style={cell}>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
          <RefImage ln={ln} />
          <div>{ln.description}
            {ln.specification && <div style={{ color: "var(--muted)",
              fontSize: 11 }}>{ln.specification}</div>}
            {/* The team writes the live story of a line here ("containers
                booked, ETA Tuticorin") and the client's page shows it — so
                the planner shows it too (owner 2026-09-03). */}
            {ln.remarks && <div style={{ color: "var(--muted)", fontSize: 10.5,
              fontStyle: "italic", marginTop: 2, maxWidth: 260 }}>
              <span style={{ fontStyle: "normal", fontWeight: 600 }}>
                Remark </span>{ln.remarks}</div>}
            {ln.client_stale && <div style={{ color: "var(--amber-fg)",
              fontSize: 10.5 }}>⚠ client update overdue</div>}</div>
        </div></td>
      <td style={cell}>{ln.make_brand || "—"}</td>
      <td style={cell}>{ln.quantity != null
        ? `${Number(ln.quantity)}${ln.uom ? " " + ln.uom : ""}`
        : (ln.uom || "—")}</td>
      <td style={cell}>{ln.category || ln.trade || "—"}</td>
      <td style={cell}>{ln.supply_by === "CLIENT"
        ? <Chip tone="warn">{c.site_code}</Chip> : "Sand Planet"}</td>
      <td style={cell}>{fmt(ln.required_date)}</td>
      <td style={cell}>{ln.ipr_supplier || ln.planned_supplier || "—"}</td>
      <td style={cell}>{ln.ipr_country || ln.source_country || "—"}</td>
      <td style={cell}><OrderByCell ln={ln} /></td>
      {c.show_values && <td style={cell}><ValueCell ln={ln} /></td>}
      <td style={cell}><PipelineStrip stages={ln.pipeline} /></td>
      <td style={cell}><RiskCell risk={ln.risk} /></td>
      <td style={cell}>
        {ln.stage ? <Chip tone={ln.stage.tone}>{ln.stage.label}</Chip>
          : <Chip tone={STATE_TONE[ln.state]}>
              {ln.state.replace(/_/g, " ")}</Chip>}
        {ln.stage && <div style={{ fontSize: 9.5, color: "var(--muted)",
          marginTop: 2 }}>{ln.state.replace(/_/g, " ").toLowerCase()}</div>}
        {ln.amended && <div style={{ fontSize: 9.5, color: "#b35900",
          marginTop: 2 }} title="Edited after sign-off — goes round for re-confirmation and re-sign">
          amended</div>}
        {/* The order ref, right on the row — click for the status card
            (site roles) or the full order (HO) (owner 2026-08-27). */}
        {ln.ipr_ref && (
          <div style={{ marginTop: 3 }}>
            <a href="#" title="Open the order's status"
               onClick={(e) => { e.preventDefault();
                                 on.openRef?.(ln.ipr_ref); }}
               style={{ textDecoration: "none" }}>
              <RefStamp small>{ln.ipr_ref}</RefStamp></a>
          </div>
        )}
        <TrackingLine t={ln.tracking} />
      </td>
      <td style={{ ...cell, whiteSpace: "nowrap" }}>
        {(c.can_edit_plan || c.can_confirm) &&
          <button style={linkBtn} onClick={() => on.edit(ln.id)}>Edit</button>}
        {c.can_link && <button style={{ ...linkBtn, marginLeft: 8,
          color: "var(--sky)" }}
          onClick={() => on.track(sel.track === ln.id ? null : ln.id)}>
          Track</button>}
        {c.show_values && (c.can_quote || ln.quotes?.length > 0) &&
          <button style={{ ...linkBtn, marginLeft: 8, color: "var(--sky)" }}
            onClick={() => on.quotes(sel.quotes === ln.id ? null : ln.id)}>
            Quotes{ln.quotes?.length ? ` · ${ln.quotes.length}` : ""}
            {ln.quotes?.some((q) => q.is_awarded) || ln.award_is_new_supplier
              ? " ✓" : ""}</button>}
        {c.can_split && ln.supply_by === "CONTRACTOR" && ln.quantity != null &&
          <button style={{ ...linkBtn, marginLeft: 8, color: "var(--sky)" }}
            title="Split this order across more than one IPR"
            onClick={() => on.split(ln.id)}>Split</button>}
        {/* A line no document will ever close: material received before the
            import module existed, or a local purchase with no GRN. Without
            this it stays "Produced" and flags Late forever. */}
        {c.can_link && !ln.grn_ref && ln.supply_by === "CONTRACTOR" && (
          ln.delivered_on ? (
            <button style={{ ...linkBtn, marginLeft: 8,
                             color: "var(--muted)" }}
              title={`Received ${ln.delivered_on}`
                + (ln.delivered_note ? ` — ${ln.delivered_note}` : "")}
              onClick={() => on.delivered(ln.id, null)}>Reopen</button>
          ) : (
            <button style={{ ...linkBtn, marginLeft: 8, color: "var(--sky)" }}
              title="Mark received without a goods receipt"
              onClick={() => on.delivered(ln.id)}>Received</button>
          ))}
      </td>
    </tr>
  );
}

// The collapsed summary row for a bundle of same-material, same-supplier lines
// (e.g. "Deck & Fence Timber" in six sizes). Click to expand the members.
function BundleRow({ group, c, open, onToggle }) {
  const s = group.summary;
  const qty = s.quantity != null
    ? `${Number(s.quantity)}${s.uom ? " " + s.uom : ""}`
    : `${s.count} items`;
  return (
    <tr style={{ borderTop: "1px solid var(--line)",
      background: "var(--sky-soft)", cursor: "pointer" }} onClick={onToggle}>
      <td style={{ ...cell, color: "var(--muted)" }}>{open ? "▾" : "▸"}</td>
      <td style={cell}>
        <span style={{ fontWeight: 600 }}>{s.bundle}</span>
        <span style={{ color: "var(--muted)", fontSize: 11 }}>
          {" "}· {s.count} items</span>
        {s.make_brand && s.make_brand !== "Multiple" &&
          <div style={{ color: "var(--muted)", fontSize: 11 }}>
            {s.make_brand}</div>}
      </td>
      <td style={cell}>{s.make_brand || "—"}</td>
      <td style={cell}>{qty}</td>
      <td style={cell}>{s.category || "—"}</td>
      <td style={cell}>{s.supply_by === "CLIENT"
        ? <Chip tone="warn">{c.site_code}</Chip> : "Sand Planet"}</td>
      <td style={cell}>{fmt(s.required_date)}</td>
      <td style={cell}>{s.supplier || <span style={{
        color: "var(--muted)" }}>TBD</span>}</td>
      <td style={cell}>{s.source_country || "—"}</td>
      <td style={cell}>—</td>
      {c.show_values && <td style={cell}>{money(s.estimated_value, "USD")}
        {s.committed_value != null && <div style={{ fontSize: 10.5,
          color: "var(--muted)" }}>ordered {money(s.committed_value, "USD")}</div>}
      </td>}
      <td style={cell}><PipelineStrip stages={s.pipeline} /></td>
      <td style={cell}><RiskCell risk={s.risk} /></td>
      <td style={cell}><Chip tone={STATE_TONE[s.state]}>
        {s.state.replace(/_/g, " ")}</Chip></td>
      <td style={{ ...cell, color: "var(--sky)", whiteSpace: "nowrap" }}>
        {open ? "Hide" : "Expand"}</td>
    </tr>
  );
}

// Per-project procurement schedule: PM proposes lines, Purchasing confirms the
// commercial fields, the Director signs off the baseline.
export default function ProcurementSchedulePage({ me, sites, onOpenDoc }) {
  const [list, setList] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [view, setView] = useState("list");   // list | new
  const [error, setError] = useState(null);

  const load = () => api("/procurement-schedules").then(setList)
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  if (openId)
    return <ScheduleDetail id={openId} me={me} onOpenDoc={onOpenDoc}
             onBack={() => { setOpenId(null); load(); }}
             onDeleted={() => { setOpenId(null); load(); }} />;
  if (view === "new")
    return <NewSchedule sites={sites} onCancel={() => setView("list")}
             onDone={(d) => { setView("list"); setOpenId(d.id); load(); }} />;

  const canOpen = PROPOSE.includes(me.role);
  return (
    <div style={{ maxWidth: 980 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12,
        marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Procurement Schedule</h2>
        {canOpen && <Btn variant="primary"
          onClick={() => setView("new")}>+ Open a project schedule</Btn>}
      </div>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      {list === null ? <div style={card}>Loading…</div>
       : !list.length ? <div style={card}>No schedules yet.</div> : (
        <div style={{ ...card, padding: 0, overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
            fontSize: 13 }}>
            <thead><tr style={{ textAlign: "left", color: "var(--muted)" }}>
              {["Ref", "Project", "Site", "Status", "Lines", "Risk"].map((h) =>
                <th key={h} style={{ padding: "8px 12px" }}>{h}</th>)}
            </tr></thead>
            <tbody>
              {list.map((s) => (
                <tr key={s.id} style={{ borderTop: "1px solid var(--line)",
                  cursor: "pointer" }} onClick={() => setOpenId(s.id)}>
                  <td style={{ padding: "8px 12px", fontFamily:
                    "var(--font-mono)" }}>{s.ref}</td>
                  <td style={{ padding: "8px 12px" }}>{s.project_code} —{" "}
                    {s.project_title}</td>
                  <td style={{ padding: "8px 12px" }}>{s.site_code}</td>
                  <td style={{ padding: "8px 12px" }}>
                    <Chip tone={STATUS_TONE[s.status]}>
                      {s.status.replace(/_/g, " ")}</Chip>
                    {WHOSE_TURN[s.status] && <div style={{ fontSize: 11,
                      color: "var(--muted)", marginTop: 2 }}>
                      {WHOSE_TURN[s.status]}</div>}</td>
                  <td style={{ padding: "8px 12px", color: "var(--muted)" }}>
                    {Object.entries(s.line_counts || {})
                      .map(([k, v]) => `${v} ${k.toLowerCase()}`).join(" · ")
                      || "—"}</td>
                  <td style={{ padding: "8px 12px" }}>
                    <RiskSummary counts={s.risk_counts} />
                    {!(s.risk_counts?.LATE || s.risk_counts?.AT_RISK) &&
                      <span style={{ color: "var(--muted)" }}>—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// The schedule as a tab inside a project (next to Commercials). Opens the
// project's schedule, offering to start one if it doesn't exist yet.
export function ProjectScheduleTab({ project, me, onOpenDoc }) {
  const [id, setId] = useState(null);
  const [state, setState] = useState("loading");   // loading|none|ready|error
  const [error, setError] = useState(null);

  function load() {
    setState("loading");
    api(`/projects/${project.id}/procurement-schedule`)
      .then((d) => { setId(d.id); setState("ready"); })
      .catch((e) => { if (e.status === 404) setState("none");
        else { setError(e.message); setState("error"); } });
  }
  useEffect(() => { load(); }, [project.id]);   // eslint-disable-line

  async function start() {
    try {
      const d = await api(`/projects/${project.id}/procurement-schedule`,
        { method: "POST" });
      setId(d.id); setState("ready");
    } catch (e) { setError(e.message); }
  }

  if (state === "loading") return <div style={card}>Loading…</div>;
  if (state === "error") return <div style={card}>{error}</div>;
  if (state === "none") return (
    <div style={card}>
      <p style={{ marginTop: 0 }}>No procurement schedule for this project yet.</p>
      {PROPOSE.includes(me.role) && <Btn variant="primary" onClick={start}>
        Start the procurement schedule</Btn>}
    </div>
  );
  return <ScheduleDetail id={id} me={me} onBack={null} onOpenDoc={onOpenDoc}
    onDeleted={() => { setId(null); setState("none"); }} />;
}

function NewSchedule({ sites, onCancel, onDone }) {
  const [siteId, setSiteId] = useState(sites?.[0]?.id || "");
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!siteId) { setProjects([]); return; }
    api(`/sites/${siteId}/projects`).then((l) => { setProjects(l);
      setProjectId(l?.[0]?.id || ""); }).catch(() => setProjects([]));
  }, [siteId]);

  async function open() {
    if (!projectId) { setError("Pick a project."); return; }
    setBusy(true); setError(null);
    try {
      const d = await api(`/projects/${projectId}/procurement-schedule`,
        { method: "POST" });
      onDone(d);
    } catch (e) { setError(e.message); setBusy(false); }
  }
  return (
    <div style={{ ...card, maxWidth: 560 }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Open a project schedule</h2>
        <button onClick={onCancel} style={{ border: "none",
          background: "none", cursor: "pointer", color: "var(--navy)" }}>
          Cancel</button>
      </div>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      <label style={fld}>Site
        <select style={inputStyle} value={siteId}
          onChange={(e) => setSiteId(e.target.value)}>
          {(sites || []).map((s) => <option key={s.id} value={s.id}>
            {s.code} — {s.name}</option>)}
        </select></label>
      <label style={{ ...fld, marginTop: 8 }}>Project
        <select style={inputStyle} value={projectId}
          onChange={(e) => setProjectId(e.target.value)}>
          <option value="">Select…</option>
          {projects.map((p) => <option key={p.id} value={p.id}>
            {p.code} — {p.title}</option>)}
        </select></label>
      <div style={{ marginTop: 12 }}>
        <Btn variant="primary" disabled={busy} onClick={open}>
          Open schedule</Btn>
      </div>
    </div>
  );
}

// Pops a line's Edit/Track/Quotes/Split form over the table, centred, instead
// of pushing it below every section (owner 2026-08-08 — the table is long, so
// an inline form far down was easy to lose). Backdrop or Esc closes it.
function Modal({ onClose, children }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose?.(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 1000,
      background: "rgba(20,30,40,.45)", display: "flex",
      alignItems: "flex-start", justifyContent: "center",
      padding: "40px 16px", overflowY: "auto" }}>
      <div onClick={(e) => e.stopPropagation()}
        style={{ width: "100%", maxWidth: 820, margin: "auto" }}>
        {children}
      </div>
    </div>
  );
}

function ScheduleDetail({ id, me, onBack, onDeleted, onOpenDoc }) {
  const [briefRef, setBriefRef] = useState(null);
  // Everyone gets the status card on the planner (owner 2026-08-27) — the
  // full order page is a jump too far mid-schedule; HO reaches it from the
  // International Orders list when they need to act.
  const openRef = (ref) =>
    String(ref).startsWith("IPR-")
      ? setBriefRef(ref)
      : onOpenDoc && onOpenDoc(ref);
  const [c, setC] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [editId, setEditId] = useState(null);
  const [trackId, setTrackId] = useState(null);
  const [quotesId, setQuotesId] = useState(null);
  const [splitId, setSplitId] = useState(null);
  const [openB, setOpenB] = useState({});   // expanded bundle keys

  const load = () => api(`/procurement-schedules/${id}`).then(setC)
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, [id]);

  // Close a line that no document will close — material received before the
  // import module existed, or a local purchase with no GRN. A note is
  // required: this is the one stage with nothing behind it, so it should say
  // on what basis it was asserted.
  async function markDelivered(lineId, reopen) {
    if (reopen === null) {
      if (!window.confirm("Reopen this line? It stops counting as received."))
        return;
      await api(`/procurement-schedule-lines/${lineId}/delivered`,
                { method: "POST", body: { on: null } }).then(load)
        .catch((e) => setError(e.message));
      return;
    }
    const on = window.prompt("Date received (YYYY-MM-DD):",
                             new Date().toISOString().slice(0, 10));
    if (!on) return;
    const note = window.prompt("How was it received? There is no goods "
                               + "receipt behind this, so the note is the "
                               + "record.");
    if (!note) return;
    api(`/procurement-schedule-lines/${lineId}/delivered`,
        { method: "POST", body: { on, note } }).then(load)
      .catch((e) => setError(e.message));
  }

  async function run(fn) {
    setBusy(true); setError(null);
    try { await fn(); await load(); } catch (e) { setError(e.message); }
    setBusy(false);
  }
  const act = (action) => run(async () => {
    let note = "";
    if (action === "return") {
      note = window.prompt("Reason to return to the PM:") || "";
      if (!note.trim()) throw new Error("A reason is required.");
    }
    await api(`/procurement-schedules/${id}/action`,
      { method: "POST", body: { action, note } });
  });
  const submit = () => run(() =>
    api(`/procurement-schedules/${id}/submit`, { method: "POST" }));
  const reopen = () => {
    if (!window.confirm(
      "Reopen this signed-off schedule for changes? It returns to draft so " +
      "the team can edit lines, then goes back through confirm + sign-off.")) {
      return;
    }
    run(() => api(`/procurement-schedules/${id}/reopen`, { method: "POST" }));
  };
  const share = () => run(() =>
    api(`/procurement-schedules/${id}/share`, { method: "POST" }));
  const revokeShare = () => run(() =>
    api(`/procurement-schedules/${id}/share`, { method: "DELETE" }));
  // Admin removes a draft opened in error (e.g. a PM created it on the wrong
  // project). Don't run load() afterwards — the schedule is gone.
  const del = async () => {
    if (!window.confirm(`Delete draft schedule ${c.ref}? This permanently `
      + "removes the plan and all its lines. This cannot be undone.")) return;
    setBusy(true); setError(null);
    try {
      await api(`/procurement-schedules/${id}`, { method: "DELETE" });
      (onDeleted || onBack)?.();
    } catch (e) { setError(e.message); setBusy(false); }
  };

  if (error && !c) return <div style={card}>{error}
    <div><button style={linkBtn} onClick={onBack}>← Back</button></div></div>;
  if (!c) return <div style={card}>Loading…</div>;

  // Always show the ungrouped bucket when it has lines — even alongside real
  // sections — so lines added before a section was created never vanish.
  const hasUngrouped = (c.groups?.["0"] || []).length > 0;
  const secList = [
    ...c.sections,
    ...(hasUngrouped || !c.sections.length
      ? [{ id: "none", code: "", title: "Ungrouped" }] : []),
  ];

  return (
    <div>
      {onBack && <button style={linkBtn} onClick={onBack}>
        ← All schedules</button>}
      <div style={{ ...card, marginTop: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10,
          flexWrap: "wrap" }}>
          <h2 style={{ margin: 0, fontFamily: "var(--font-mono)" }}>{c.ref}</h2>
          <Chip tone={STATUS_TONE[c.status]}>{c.status.replace(/_/g, " ")}</Chip>
          {WHOSE_TURN[c.status] && <span style={{ fontSize: 12.5,
            color: "var(--muted)", fontStyle: "italic" }}>
            · {WHOSE_TURN[c.status]}</span>}
          <span style={{ color: "var(--muted)" }}>{c.project_code} —{" "}
            {c.project_title} · {c.site_code}</span>
          {c.baseline_signed_at && <span style={{ fontSize: 12,
            color: "var(--muted)" }}>baseline {fmt(c.baseline_signed_at)} ·{" "}
            {c.baseline_signed_by}</span>}
          <RiskSummary counts={c.risk_counts} />
        </div>
        {c.show_values && c.totals && (
          <div style={{ marginTop: 8, fontSize: 13 }}>
            <span style={{ color: "var(--muted)" }}>Estimated </span>
            <b>{money(c.totals.estimated, "USD")}</b>
            {Number(c.totals.committed) > 0 && <>
              <span style={{ color: "var(--muted)" }}> · Ordered </span>
              <b>{money(c.totals.committed, "USD")}</b></>}
          </div>)}
        {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
        {/* workflow bar */}
        <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
          {c.can_edit_plan && <Btn variant="secondary" disabled={busy}
            onClick={() => setAdding(true)}>+ Add line</Btn>}
          {c.can_edit_plan && <Btn variant="secondary" disabled={busy}
            title="The BOM is the planner's source document — adds any BOM items not already on the plan"
            onClick={() => run(() => api(
              `/procurement-schedules/${id}/seed-bom`, { method: "POST" }))}>
            ⤵ Seed from BOM</Btn>}
          {c.can_submit &&
            <Btn variant="primary" disabled={busy}
              onClick={submit}>Submit to Purchasing</Btn>}
          {c.can_confirm && <>
            <Btn variant="primary" disabled={busy}
              onClick={() => act("confirm")}
              title="Purchasing confirms the commercial fields, then it goes to the Director to sign off">
              Confirm commercials &amp; send to Director</Btn>
            <Btn variant="ghost" disabled={busy}
              onClick={() => act("return")}>Return to PM</Btn></>}
          {c.can_sign_off && <>
            <Btn variant="primary" disabled={busy}
              onClick={() => act("sign_off")}>Sign off baseline</Btn>
            <Btn variant="ghost" disabled={busy}
              onClick={() => act("return")}>Return to PM</Btn></>}
          {c.can_reopen &&
            <Btn variant="secondary" disabled={busy} onClick={reopen}
              title="Reopen the signed-off schedule so the team can edit lines">
              Reopen for changes</Btn>}
          {me.role === "ADMIN" && c.status === "DRAFT" && (
            <Btn variant="ghost" disabled={busy} onClick={del}
              title={"Delete this draft schedule (e.g. opened on the wrong "
                + "project). Removes the plan and all its lines."}>
              🗑 Delete draft</Btn>)}
          <a href={`/api/v1/procurement-schedules/${c.id}/export`}
            style={{ ...linkBtn, marginLeft: "auto", textDecoration: "none" }}
            title="Download the client procurement plan (Excel) — bundled
 variants grouped">
            ⬇ Export client plan</a>
          <a href={`/api/v1/procurement-schedules/${c.id}/export?expand=1`}
            style={{ ...linkBtn, textDecoration: "none", fontWeight: 400 }}
            title="Same plan with every bundled variant on its own row">
            all variants</a>
          {c.share?.can_share && <ClientLink share={c.share} busy={busy}
            onCreate={share} onRevoke={revokeShare} />}
        </div>
      </div>

      {adding && <Modal onClose={() => setAdding(false)}>
        <LineForm mode="plan" c={c} me={me}
          onCancel={() => setAdding(false)}
          onSaved={() => { setAdding(false); load(); }} />
      </Modal>}

      {secList.map((sec) => {
        const gkey = String(sec.id === "none" ? 0 : sec.id);
        const grows = c.groups?.[gkey] || [];
        if (!grows.length && sec.id !== "none") return null;
        const on = { openRef,
                     edit: setEditId, track: setTrackId, quotes: setQuotesId,
          split: setSplitId, delivered: markDelivered };
        const sel = { track: trackId, quotes: quotesId };
        return (
          <div key={sec.id} style={{ ...card, marginTop: 10, padding: 0,
            overflowX: "auto" }}>
            {(sec.code || sec.id === "none") && (
              <div style={{ padding: "8px 12px", fontWeight: 600,
                background: "var(--sky-soft)" }}>
                {sec.code ? `${sec.code} — ${sec.title}` : sec.title}
              </div>)}
            <table style={{ width: "100%", borderCollapse: "collapse",
              fontSize: 12.5 }}>
              <thead><tr style={{ textAlign: "left", color: "var(--muted)" }}>
                {["#", "Description", "Make", "Qty", "Category", "Supply",
                  "Required", "Supplier", "Country", "Order by",
                  ...(c.show_values ? ["Est. value"] : []),
                  "Pipeline", "Risk", "State", ""].map((h, i) =>
                  <th key={i} style={{ padding: "6px 10px",
                    whiteSpace: "nowrap" }}>{h}</th>)}
              </tr></thead>
              <tbody>
                {grows.map((row) => row.kind === "bundle" ? (
                  <Fragment key={`b${row.key}`}>
                    <BundleRow group={row} c={c} open={!!openB[row.key]}
                      onToggle={() => setOpenB((o) =>
                        ({ ...o, [row.key]: !o[row.key] }))} />
                    {openB[row.key] && row.members.map((ln) => (
                      <LineRow key={ln.id} ln={ln} c={c} member sel={sel}
                        on={on} />
                    ))}
                  </Fragment>
                ) : (
                  <LineRow key={row.line.id} ln={row.line} c={c} sel={sel}
                    on={on} />
                ))}
                {!grows.length && <tr><td style={{ ...cell,
                  color: "var(--muted)" }} colSpan={c.show_values ? 15 : 14}>
                  No lines.</td></tr>}
                {c.show_values && grows.length > 0 && (
                  <tr style={{ borderTop: "2px solid var(--line)",
                    fontWeight: 600 }}>
                    <td style={{ ...cell, textAlign: "right" }} colSpan={10}>
                      Section total</td>
                    <td style={cell}>{money(
                      c.totals?.sections?.[sec.id === "none" ? 0 : sec.id],
                      "USD")}</td>
                    <td colSpan={4}></td>
                  </tr>)}
              </tbody>
            </table>
          </div>
        );
      })}

      {editId && <Modal onClose={() => setEditId(null)}>
        <LineForm mode={c.can_confirm ? "commercial" : "plan"} c={c}
          me={me} line={c.lines.find((l) => l.id === editId)}
          onCancel={() => setEditId(null)}
          onSaved={() => { setEditId(null); load(); }} />
      </Modal>}

      {trackId && <Modal onClose={() => setTrackId(null)}>
        <LinkPanel line={c.lines.find((l) => l.id === trackId)}
          onClose={() => setTrackId(null)} onSaved={setC}
          onOpenDoc={openRef} />
      </Modal>}
      {briefRef && <IprBrief refIpr={briefRef}
        onClose={() => setBriefRef(null)} />}

      {quotesId && <Modal onClose={() => setQuotesId(null)}>
        <QuotesPanel line={c.lines.find((l) => l.id === quotesId)}
          canAward={c.can_award} onClose={() => setQuotesId(null)}
          onSaved={setC} onOpenDoc={onOpenDoc} />
      </Modal>}

      {splitId && <Modal onClose={() => setSplitId(null)}>
        <SplitPanel line={c.lines.find((l) => l.id === splitId)}
          onClose={() => setSplitId(null)} onSaved={setC} />
      </Modal>}
    </div>
  );
}

// Split a line's order across several IPRs: divide its quantity into sibling
// sub-lines (sharing a bundle so they roll up into one expandable row). Each
// sub-line then links its own IPR / shipment / GRN.
function SplitPanel({ line, onClose, onSaved }) {
  const total = Number(line.quantity);
  const [parts, setParts] = useState(() => {
    const half = Math.round((total / 2) * 100) / 100;
    return [String(half), String(Math.round((total - half) * 100) / 100)];
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const sum = parts.reduce((a, p) => a + (parseFloat(p) || 0), 0);
  const ok = parts.length >= 2 && parts.every((p) => parseFloat(p) > 0)
    && Math.abs(sum - total) < 0.005;

  const setPart = (i, v) =>
    setParts(parts.map((p, j) => (j === i ? v : p)));
  const addPart = () => setParts([...parts, ""]);
  const rmPart = (i) => setParts(parts.filter((_, j) => j !== i));

  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const d = await api(
        `/procurement-schedule-lines/${line.id}/split`,
        { method: "POST", body: { quantities: parts } });
      onSaved(d); onClose();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <div style={{ ...card, marginTop: 10, border: "1px solid var(--sky)" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center" }}>
        <div style={{ fontWeight: 600 }}>Split order — #{line.s_no}{" "}
          <span style={{ color: "var(--muted)", fontWeight: 400 }}>
            {line.description}</span></div>
        <button style={linkBtn} onClick={onClose}>Close</button>
      </div>
      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
        Divide the {total}{line.uom ? " " + line.uom : ""} into separate
        sub-lines — one per IPR. They collapse into one expandable row and each
        tracks its own order / shipment / delivery.</div>
      <div style={{ marginTop: 12 }}>
        {parts.map((p, i) => (
          <div key={i} style={{ display: "flex", gap: 8, alignItems: "center",
            marginBottom: 6 }}>
            <span style={{ width: 62, color: "var(--muted)", fontSize: 12 }}>
              {i === 0 ? "This line" : `Split ${i}`}</span>
            <input style={{ ...inputStyle, width: 120 }} inputMode="decimal"
              value={p} onChange={(e) => setPart(i, e.target.value)} />
            <span style={{ color: "var(--muted)", fontSize: 12 }}>
              {line.uom}</span>
            {parts.length > 2 && (
              <button style={{ border: "none", background: "none",
                cursor: "pointer", color: "var(--red-fg)", fontSize: 16 }}
                onClick={() => rmPart(i)} title="Remove">×</button>)}
          </div>
        ))}
        <button style={{ ...linkBtn, color: "var(--navy)" }}
          onClick={addPart}>+ Add a split</button>
      </div>
      <div style={{ marginTop: 8, fontSize: 12,
        color: ok ? "var(--muted)" : "var(--red-fg)" }}>
        Total {sum || 0} of {total}{line.uom ? " " + line.uom : ""}
        {ok ? " ✓" : " — must add up to the line quantity"}</div>
      {err && <div style={{ color: "var(--red-fg)", fontSize: 12,
        marginTop: 6 }}>{err}</div>}
      <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
        <Btn variant="primary" disabled={!ok || busy} onClick={submit}>
          {busy ? "Splitting…" : "Split line"}</Btn>
        <Btn onClick={onClose}>Cancel</Btn>
      </div>
    </div>
  );
}

// Track panel: link the execution documents that fulfil a line (MAR/IPR/GRN)
// and set the manual production flag. The pipeline above is derived from these.
// The IPR as the site team sees it (owner 2026-08-27): status, payment
// position in words, shipments with live tracking — no import prices
// (§6C.5). HO users open the full order instead.
function IprBrief({ refIpr, onClose }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    api(`/ipr/${refIpr}/brief`).then(setD).catch((e) => setErr(e.message));
  }, [refIpr]);
  const line = { fontSize: 13, margin: "2px 0" };
  return (
    <Modal onClose={onClose}>
      <div style={{ ...card, minWidth: 320, maxWidth: 560,
                    margin: "0 auto" }}>
        {err && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{err}</p>}
        {!d && !err && <p style={{ fontSize: 13 }}>Loading…</p>}
        {d && (
          <>
            <div style={{ display: "flex", gap: 10, alignItems: "baseline",
                          flexWrap: "wrap" }}>
              <strong style={{ fontSize: 16, color: "var(--navy)" }}>
                {d.ref}</strong>
              <Chip tone={{ AUTHORISED: "ok", APPROVED: "ok",
                            SUBMITTED: "info", DRAFT: "warn" }[d.status]
                          || "info"}>{d.status}</Chip>
              <span style={{ marginLeft: "auto", fontSize: 12,
                             color: "var(--muted)" }}>{d.doc_date}</span>
            </div>
            <p style={{ ...line, color: "var(--muted)" }}>
              {d.supplier}{d.supplier_country ? ` · ${d.supplier_country}` : ""}
              {d.incoterm ? ` · ${d.incoterm}` : ""}
              {" · for "}{(d.projects || []).join(", ") || "—"}
            </p>
            <p style={line}><b>Payment:</b> {d.payment_word}</p>
            {(d.milestones || []).length > 0 && (
              <div style={{ fontSize: 12.5, color: "var(--muted)",
                            marginBottom: 6 }}>
                {d.milestones.map((m, i) => (
                  <div key={i}>· {m.label} ({m.trigger}) —{" "}
                    <span style={{ fontWeight: 600,
                      color: m.status === "PAID" ? "var(--ok-fg, #1a7f37)"
                        : m.status === "DUE" ? "#b35900"
                        : "var(--muted)" }}>{m.status}</span></div>
                ))}
              </div>
            )}
            <p style={{ ...line, marginTop: 6 }}><b>Shipping:</b>
              {(d.shipments || []).length === 0 && " no shipment booked yet"}
            </p>
            {(d.shipments || []).map((sh) => (
              <div key={sh.seq} style={{ border: "1px solid var(--line)",
                borderRadius: 8, padding: "6px 10px", marginBottom: 6,
                fontSize: 12.5 }}>
                <b>{sh.mode === "AIR" ? "✈" : "🚢"} Shipment {sh.seq}</b>
                {" — "}{sh.status_display}
                {sh.live ? ` · live: ${sh.live.replace(/_/g, " ")
                  .toLowerCase()}` : ""}
                {sh.eta ? ` · ETA ${sh.eta}` : ""}
                {sh.vessel_flight ? ` · ${sh.vessel_flight}` : ""}
                {sh.last_move && (
                  <div style={{ color: "var(--muted)" }}>
                    last: {sh.last_move.label}
                    {sh.last_move.location ? ` — ${sh.last_move.location}`
                                           : ""} · {sh.last_move.date}</div>
                )}
              </div>
            ))}
          </>
        )}
      </div>
    </Modal>
  );
}


function LinkPanel({ line, onClose, onSaved, onOpenDoc }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [openSlot, setOpenSlot] = useState(null);   // slot showing suggestions
  const [cands, setCands] = useState([]);
  const [ref, setRef] = useState("");
  const [note, setNote] = useState(line?.client_update_note || "");
  if (!line) return null;
  const isClient = line.supply_by === "CLIENT";

  async function run(fn) {
    setBusy(true); setErr(null);
    try { const d = await fn(); if (d) onSaved(d); }
    catch (e) { setErr(e.message); }
    setBusy(false);
  }
  const link = (slot, r) => run(() =>
    api(`/procurement-schedule-lines/${line.id}/link`,
      { method: "POST", body: { slot, ref: r } })
      .then((d) => { setOpenSlot(null); setRef(""); return d; }));
  const unlink = (slot) => run(() =>
    api(`/procurement-schedule-lines/${line.id}/link`,
      { method: "DELETE", body: { slot } }));
  const setProduction = (status) => run(() =>
    api(`/procurement-schedule-lines/${line.id}/production`,
      { method: "POST", body: { status } }));
  const clientUpdate = (delivered) => run(() =>
    api(`/procurement-schedule-lines/${line.id}/client-update`,
      { method: "POST", body: { note, delivered } }));
  // The ETA is the team's date — nothing computes it (owner 2026-09-03).
  const setEta = (eta_date) => run(() =>
    api(`/procurement-schedule-lines/${line.id}/eta`,
      { method: "POST", body: { eta_date } }));
  async function suggest(slot) {
    if (openSlot === slot) { setOpenSlot(null); return; }
    setOpenSlot(slot); setCands([]); setRef("");
    try {
      const l = await api(
        `/procurement-schedule-lines/${line.id}/candidates?slot=${slot}`);
      setCands(l);
    } catch { setCands([]); }
  }

  const prodStage = (line.pipeline || []).find((s) => s.key === "production");
  return (
    <div style={{ ...card, marginTop: 10, border: "1px solid var(--sky)" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center" }}>
        <div style={{ fontWeight: 600 }}>Track — #{line.s_no}{" "}
          {line.description}</div>
        <button style={linkBtn} onClick={onClose}>Close</button>
      </div>
      {err && <p style={{ color: "var(--red-fg)" }}>{err}</p>}

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
        marginTop: 10 }}>
        {isClient && (
          <div style={{ flex: 1, minWidth: 260,
            border: "1px solid var(--line)", borderRadius: 8, padding: 10 }}>
            <div style={{ fontSize: 12, color: "var(--muted)",
              marginBottom: 6, display: "flex", gap: 8 }}>
              Client update
              {line.client_stale && <Chip tone="warn">chase overdue</Chip>}
              {line.client_delivered_on &&
                <Chip tone="ok">delivered {fmt(line.client_delivered_on)}</Chip>}
            </div>
            {line.client_last_update && <div style={{ fontSize: 11.5,
              color: "var(--muted)", marginBottom: 6 }}>
              Last update {fmt(line.client_last_update)}</div>}
            <input style={{ ...inputStyle, fontSize: 12 }} value={note}
              placeholder="Where is the client's supply?"
              onChange={(e) => setNote(e.target.value)} />
            <div style={{ display: "flex", gap: 6, marginTop: 6,
              flexWrap: "wrap" }}>
              <Btn variant="secondary" disabled={busy}
                style={{ padding: "4px 12px" }}
                onClick={() => clientUpdate(null)}>Record update</Btn>
              {line.client_delivered_on
                ? <Btn variant="ghost" disabled={busy}
                    style={{ padding: "4px 12px" }}
                    onClick={() => clientUpdate(false)}>Un-deliver</Btn>
                : <Btn variant="primary" disabled={busy}
                    style={{ padding: "4px 12px" }}
                    onClick={() => clientUpdate(true)}>Mark delivered</Btn>}
            </div>
          </div>
        )}
        {!isClient && LINK_SLOTS.map(([slot, label, refKey]) => (
          <div key={slot} style={{ flex: 1, minWidth: 240,
            border: "1px solid var(--line)", borderRadius: 8, padding: 10 }}>
            <div style={{ fontSize: 12, color: "var(--muted)",
              marginBottom: 6 }}>{label}</div>
            {line[refKey] ? (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {onOpenDoc ? (
                  <a href="#" onClick={(e) => { e.preventDefault();
                      onOpenDoc(line[refKey]); }}
                    style={{ textDecoration: "none" }}
                    title="Open the document">
                    <RefStamp small>{line[refKey]}</RefStamp></a>
                ) : <RefStamp small>{line[refKey]}</RefStamp>}
                <button style={linkBtn} disabled={busy}
                  onClick={() => unlink(slot)}>Unlink</button>
              </div>
            ) : (
              <>
                <div style={{ display: "flex", gap: 6 }}>
                  <input style={{ ...inputStyle, fontSize: 12 }}
                    placeholder={`${slot.toUpperCase()} ref…`}
                    value={openSlot === slot ? ref : ""}
                    onFocus={() => setOpenSlot(slot)}
                    onChange={(e) => setRef(e.target.value)} />
                  <Btn variant="secondary" disabled={busy || !ref.trim()}
                    style={{ padding: "4px 12px" }}
                    onClick={() => link(slot, ref)}>Link</Btn>
                </div>
                <button style={{ ...linkBtn, fontSize: 11.5, marginTop: 6,
                  color: "var(--sky)" }} onClick={() => suggest(slot)}>
                  {openSlot === slot ? "Hide" : "Suggest matches"}</button>
                {openSlot === slot && <div style={{ marginTop: 6 }}>
                  {!cands.length ? <span style={{ fontSize: 11.5,
                    color: "var(--muted)" }}>No matching documents.</span>
                   : cands.map((c) => (
                    <div key={c.doc_id} style={{ display: "flex", gap: 8,
                      alignItems: "center", padding: "3px 0" }}>
                      <button style={{ ...linkBtn, fontSize: 12 }}
                        disabled={busy} onClick={() => link(slot, c.ref)}>
                        {c.ref}</button>
                      <Chip tone="info">{(c.status || "")
                        .replace(/_/g, " ")}</Chip>
                      {c.note && <span style={{ fontSize: 10.5,
                        color: "var(--green-fg)" }}>{c.note}</span>}
                    </div>
                  ))}
                </div>}
              </>
            )}
          </div>
        ))}

        <div style={{ flex: 1, minWidth: 240,
          border: "1px solid var(--line)", borderRadius: 8, padding: 10 }}>
          <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>
            Production (made-to-order)</div>
          <select style={{ ...inputStyle, fontSize: 12 }} disabled={busy}
            value={prodStage ? line.production_status || "PENDING" : "PENDING"}
            onChange={(e) => setProduction(e.target.value)}>
            {PRODUCTION.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>

        {!isClient && (
          <div style={{ flex: 1, minWidth: 240,
            border: "1px solid var(--line)", borderRadius: 8, padding: 10 }}>
            <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>
              ETA to site (shown to the client)</div>
            <input type="date" style={{ ...inputStyle, fontSize: 12 }}
              disabled={busy} value={line.eta_date || ""}
              onChange={(e) => setEta(e.target.value)} />
            <div style={{ fontSize: 10.5, color: "var(--muted)", marginTop: 4 }}>
              {line.tracking?.current_eta
                ? `Forwarder's ETA ${fmt(line.tracking.current_eta)} — used (+5d) until you enter a date`
                : "Your date; the app does not guess it"}
              {line.required_date ? ` · required ${fmt(line.required_date)}` : ""}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Quotes panel: BOQ supplier quotes on a line (QS/PM capture) + the IPR award
// decision (Purchasing + PD). Values-gated — only shown when show_values.
const BLANK_QUOTE = { supplier_name: "", quoted_value: "", currency: "USD",
  country: "", lead_time_days: "", contact: "", valid_until: "", remarks: "",
  is_recommended: false };

function QuotesPanel({ line, canAward, onClose, onSaved, onOpenDoc }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState(BLANK_QUOTE);
  const [file, setFile] = useState(null);
  const [raisedRef, setRaisedRef] = useState("");
  if (!line) return null;
  const quotes = line.quotes || [];
  const awarded = quotes.some((q) => q.is_awarded);
  const set = (k) => (e) => setF((p) => ({ ...p,
    [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  async function run(fn) {
    setBusy(true); setErr(null);
    try { const d = await fn(); if (d) onSaved(d); }
    catch (e) { setErr(e.message); }
    setBusy(false);
  }
  async function addQuote() {
    if (!f.supplier_name.trim()) { setErr("Supplier name is required."); return; }
    const fd = new FormData();
    Object.entries(f).forEach(([k, v]) => fd.append(k, v));
    if (file) fd.append("quote_file", file);
    await run(async () => {
      const d = await apiUpload(
        `/procurement-schedule-lines/${line.id}/quotes`, fd);
      setAdding(false); setFile(null); setF(BLANK_QUOTE);
      return d;
    });
  }
  const del = (qid) => run(() =>
    api(`/procurement-schedule-quotes/${qid}`, { method: "DELETE" }));
  const recommend = (qid) => run(() => apiUpload(
    `/procurement-schedule-quotes/${qid}`,
    (() => { const fd = new FormData();
      fd.append("is_recommended", "true"); return fd; })(), "PATCH"));
  const award = (body) => run(() =>
    api(`/procurement-schedule-lines/${line.id}/award`,
      { method: "POST", body }));
  function awardNew() {
    const note = window.prompt(
      "Reason for going with a new supplier (not among the quotes):") || "";
    if (note.trim()) award({ action: "new", note });
  }
  const raiseIpr = () => run(async () => {
    const d = await api(`/procurement-schedule-lines/${line.id}/raise-ipr`,
      { method: "POST" });
    setRaisedRef(d.raised_ipr || "");
    return d;
  });

  return (
    <div style={{ ...card, marginTop: 10, border: "1px solid var(--sky)" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center" }}>
        <div style={{ fontWeight: 600 }}>BOQ quotes — #{line.s_no}{" "}
          {line.description}</div>
        <button style={linkBtn} onClick={onClose}>Close</button>
      </div>
      {err && <p style={{ color: "var(--red-fg)" }}>{err}</p>}

      {line.award_is_new_supplier && (
        <div style={{ marginTop: 8 }}>
          <Chip tone="ok">Awarded: new supplier</Chip>
          {line.award_note && <span style={{ fontSize: 12,
            color: "var(--muted)", marginLeft: 8 }}>{line.award_note}</span>}
          {canAward && <button style={{ ...linkBtn, marginLeft: 8 }}
            onClick={() => award({ action: "clear" })}>clear</button>}
        </div>)}

      <div style={{ marginTop: 8, display: "flex", flexDirection: "column",
        gap: 6 }}>
        {!quotes.length && <span style={{ fontSize: 12.5,
          color: "var(--muted)" }}>No quotes captured yet.</span>}
        {quotes.map((q) => (
          <div key={q.id} style={{ display: "flex", gap: 10,
            alignItems: "center", flexWrap: "wrap", padding: "6px 8px",
            border: "1px solid var(--line)", borderRadius: 8,
            background: q.is_awarded ? "var(--green-bg)" : "var(--paper)" }}>
            <div style={{ minWidth: 150, fontWeight: 600 }}>{q.supplier_name}
              {q.country && <span style={{ fontWeight: 400, fontSize: 11,
                color: "var(--muted)" }}> · {q.country}</span>}</div>
            <div style={{ minWidth: 90 }}>{money(q.quoted_value, q.currency)}</div>
            <div style={{ fontSize: 12, color: "var(--muted)" }}>
              {q.lead_time_days != null ? `${q.lead_time_days}d` : "—"}
              {q.valid_until ? ` · valid ${fmt(q.valid_until)}` : ""}</div>
            {q.is_recommended && <Chip tone="info">recommended</Chip>}
            {q.is_awarded && <Chip tone="ok">awarded</Chip>}
            {q.file_url && <a href={q.file_url} target="_blank"
              rel="noreferrer"
              style={{ fontSize: 12, color: "var(--navy)" }}>quote ↗</a>}
            <span style={{ flex: 1 }} />
            {!q.is_recommended && <button style={linkBtn} disabled={busy}
              onClick={() => recommend(q.id)}>recommend</button>}
            {canAward && !q.is_awarded && <button style={{ ...linkBtn,
              color: "var(--sky)" }} disabled={busy}
              onClick={() => award({ action: "quote", quote_id: q.id })}>
              award</button>}
            {canAward && q.is_awarded && <button style={linkBtn} disabled={busy}
              onClick={() => award({ action: "clear" })}>clear</button>}
            {!q.is_awarded && <button style={{ ...linkBtn,
              color: "var(--red-fg)" }} disabled={busy}
              onClick={() => del(q.id)}>remove</button>}
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: 12, marginTop: 10, flexWrap: "wrap" }}>
        {!adding && <Btn variant="secondary" disabled={busy}
          onClick={() => setAdding(true)}>+ Add quote</Btn>}
        {canAward && quotes.length > 0 && !line.award_is_new_supplier &&
          <Btn variant="ghost" disabled={busy} onClick={awardNew}>
            Go with a new supplier…</Btn>}
        {canAward && awarded && !line.ipr_id &&
          <Btn variant="primary" disabled={busy} onClick={raiseIpr}>
            Raise IPR from award</Btn>}
        {line.ipr_ref && <span style={{ fontSize: 12.5, alignSelf: "center",
          color: "var(--green-fg)" }}>IPR{" "}
          {onOpenDoc
            ? <a href="#" onClick={(e) => { e.preventDefault();
                onOpenDoc(line.ipr_ref); }}
                style={{ color: "var(--navy)", fontWeight: 600 }}>
                {line.ipr_ref}</a>
            : line.ipr_ref} linked</span>}
      </div>
      {raisedRef && !line.ipr_ref && <p style={{ fontSize: 12.5,
        color: "var(--green-fg)", marginTop: 6 }}>Draft {raisedRef} raised and
        linked — complete the supplier, rate and cost head.{" "}
        {onOpenDoc && <a href="#" onClick={(e) => { e.preventDefault();
            onOpenDoc(raisedRef); }}
          style={{ color: "var(--navy)", fontWeight: 600 }}>
          Open {raisedRef} →</a>}
        </p>}

      {adding && (
        <div style={{ ...grid, marginTop: 10, border: "1px solid var(--line)",
          borderRadius: 8, padding: 10 }}>
          <L k="Supplier name *"><input style={inputStyle}
            value={f.supplier_name} onChange={set("supplier_name")} /></L>
          <L k="Country"><input style={inputStyle} value={f.country}
            onChange={set("country")} /></L>
          <L k="Contact"><input style={inputStyle} value={f.contact}
            onChange={set("contact")} /></L>
          <L k="Quoted value"><input type="number" style={inputStyle}
            value={f.quoted_value} onChange={set("quoted_value")} /></L>
          <L k="Currency"><input style={inputStyle} value={f.currency}
            onChange={set("currency")} /></L>
          <L k="Lead time (days)"><input type="number" style={inputStyle}
            value={f.lead_time_days} onChange={set("lead_time_days")} /></L>
          <L k="Quote valid until"><input type="date" style={inputStyle}
            value={f.valid_until} onChange={set("valid_until")} /></L>
          <L k="Quote file"><input type="file" style={{ fontSize: 12 }}
            onChange={(e) => setFile(e.target.files?.[0] || null)} /></L>
          <L k="Remarks" wide><input style={inputStyle} value={f.remarks}
            onChange={set("remarks")} /></L>
          <label style={{ ...fld, alignSelf: "end" }}>
            <span><input type="checkbox" checked={f.is_recommended}
              onChange={set("is_recommended")} /> Recommended</span></label>
          <div style={{ gridColumn: "1 / -1", display: "flex", gap: 8 }}>
            <Btn variant="primary" disabled={busy} onClick={addQuote}>
              Save quote</Btn>
            <Btn variant="ghost" disabled={busy}
              onClick={() => { setAdding(false); setFile(null);
                setF(BLANK_QUOTE); }}>Cancel</Btn>
          </div>
        </div>)}
    </div>
  );
}

const UOMS = ["nos", "set", "lot", "pcs", "pair", "box", "m", "m²", "m³",
  "ft", "sqft", "kg", "ton", "litre", "bag", "drum", "roll", "sheet", "bundle"];

function LineForm({ mode, c, me, line, onCancel, onSaved }) {
  const isNew = !line;
  const [f, setF] = useState(() => line ? { ...line,
    section_code: line.section_code, section_title: line.section_title }
    : { supply_by: "CONTRACTOR", section_code: "", section_title: "",
        description: "", item_id: null, make_brand: "", specification: "",
        category: "", quantity: "", uom: "", required_date: "",
        tds_required: false });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [items, setItems] = useState([]);
  const [cats, setCats] = useState([]);
  const [imgFile, setImgFile] = useState(null);     // reference image to upload
  const [removeImg, setRemoveImg] = useState(false); // clear existing on save
  const set = (k) => (e) => setF({ ...f,
    [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const patch = (o) => setF((prev) => ({ ...prev, ...o }));

  useEffect(() => {
    api("/items").then(setItems).catch(() => setItems([]));
    api("/item-categories").then(setCats).catch(() => setCats([]));
  }, []);

  const supplyLabel = { CONTRACTOR: "Sand Planet", CLIENT: c.site_code };
  const canCreateItem = ["HO_PURCHASING", "ADMIN", "SITE_ADMIN",
    "SITE_ENGINEER", "PM", "QS", "DIRECTOR"].includes(me?.role);
  const noItemMatch = canCreateItem && (f.description || "").trim() &&
    !f.item_id && !items.some((it) =>
      it.description.toLowerCase() === f.description.trim().toLowerCase());

  function pickDescription(v) {
    const match = items.find((it) =>
      it.description.toLowerCase() === v.trim().toLowerCase());
    if (match) patch({ description: match.description, item_id: match.id,
      uom: match.unit || f.uom, category: match.category || f.category });
    else patch({ description: v, item_id: null });
  }
  async function addToCatalog() {
    const description = (f.description || "").trim();
    const unit = window.prompt(`Add "${description}" to the item catalog.\n`
      + "Unit (nos, set, m, kg…):", f.uom || "");
    if (unit === null) return;
    try {
      const item = await api("/items", { method: "POST",
        body: { description, unit: unit.trim(), category: f.category || "" } });
      setItems((l) => [...l, item]);
      patch({ item_id: item.id, uom: item.unit });
    } catch (e) { window.alert(e.message); }
  }

  async function save() {
    setBusy(true); setErr(null);
    try {
      let lineId = line?.id;
      if (isNew) {
        const known = new Set((c.lines || []).map((l) => l.id));
        const d = await api(`/procurement-schedules/${c.id}/lines`,
          { method: "POST", body: f });
        lineId = ((d.lines || []).find((l) => !known.has(l.id)) || {}).id;
      } else {
        await api(`/procurement-schedule-lines/${line.id}`,
          { method: "PATCH", body: f });
      }
      if (lineId && imgFile) {
        const fd = new FormData();
        fd.append("image", await shrinkPhoto(imgFile));
        await apiUpload(`/procurement-schedule-lines/${lineId}/image`, fd);
      } else if (lineId && removeImg && line?.reference_image) {
        await api(`/procurement-schedule-lines/${lineId}/image`,
          { method: "DELETE" });
      }
      onSaved();
    } catch (e) { setErr(e.message); setBusy(false); }
  }
  async function del() {
    if (!window.confirm("Remove this line?")) return;
    setBusy(true);
    try { await api(`/procurement-schedule-lines/${line.id}`,
      { method: "DELETE" }); onSaved(); }
    catch (e) { setErr(e.message); setBusy(false); }
  }

  const commercial = mode === "commercial";
  return (
    <div style={{ ...card, marginTop: 10, border: "1px solid var(--sky)" }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>
        {isNew ? "New line" : commercial ? "Confirm commercial fields"
          : "Edit line"}</div>
      {err && <p style={{ color: "var(--red-fg)" }}>{err}</p>}
      {!commercial ? (
        <div style={grid}>
          <L k="Section code"><input style={inputStyle} value={f.section_code}
            onChange={set("section_code")} placeholder="A" /></L>
          <L k="Section title"><input style={inputStyle}
            value={f.section_title} onChange={set("section_title")}
            placeholder="Villa Upgrades" /></L>
          <L k="Supply"><select style={inputStyle} value={f.supply_by}
            onChange={set("supply_by")}>{SUPPLY.map(([v]) =>
              <option key={v} value={v}>{supplyLabel[v]}</option>)}</select></L>
          <L k="Description *" wide>
            <input style={inputStyle} list="psc-items" value={f.description}
              placeholder="Search the item catalog…"
              onChange={(e) => pickDescription(e.target.value)} />
            <datalist id="psc-items">
              {items.map((it) => <option key={it.id} value={it.description}
                label={it.code} />)}
            </datalist>
            {f.item_id && <span style={{ fontSize: 11,
              color: "var(--green-fg)" }}>✓ linked to catalog</span>}
            {noItemMatch && <button type="button" onClick={addToCatalog}
              style={{ ...linkBtn, fontSize: 11.5, color: "var(--sky)" }}>
              + Add "{f.description.trim().slice(0, 28)}" to the catalog</button>}
          </L>
          <L k="Make / brand"><input style={inputStyle} value={f.make_brand}
            onChange={set("make_brand")} /></L>
          <L k="Reference image">
            {imgFile ? (
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <img src={URL.createObjectURL(imgFile)} alt="" style={{
                  width: 44, height: 44, objectFit: "cover", borderRadius: 4,
                  border: "1px solid var(--line)" }} />
                <button type="button" onClick={() => setImgFile(null)}
                  style={{ ...linkBtn, color: "var(--red-fg)", fontSize: 12 }}>
                  Clear</button>
              </div>
            ) : (f.reference_image && !removeImg) ? (
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <img src={f.reference_image} alt="" style={{ width: 44,
                  height: 44, objectFit: "cover", borderRadius: 4,
                  border: "1px solid var(--line)" }} />
                <label style={{ ...linkBtn, color: "var(--sky)", fontSize: 12 }}>
                  Replace<input type="file" accept="image/*"
                    style={{ display: "none" }}
                    onChange={(e) => setImgFile(e.target.files?.[0] || null)} />
                </label>
                <button type="button" onClick={() => setRemoveImg(true)}
                  style={{ ...linkBtn, color: "var(--red-fg)", fontSize: 12 }}>
                  Remove</button>
              </div>
            ) : (
              <input type="file" accept="image/*"
                style={{ ...inputStyle, padding: 4 }}
                onChange={(e) => { setImgFile(e.target.files?.[0] || null);
                  setRemoveImg(false); }} />
            )}
          </L>
          <L k="Bundle / group">
            <input style={inputStyle} list="psc-bundles" value={f.bundle || ""}
              onChange={set("bundle")} placeholder="e.g. Deck & Fence Timber" />
            <datalist id="psc-bundles">
              {[...new Set((c.lines || []).map((l) => (l.bundle || "").trim())
                .filter(Boolean))].map((b) =>
                <option key={b} value={b} />)}
            </datalist>
            <span style={{ fontSize: 10.5, color: "var(--muted)" }}>
              Variants sharing a bundle + supplier collapse into one row.</span>
          </L>
          <L k="Quantity"><input type="number" style={inputStyle}
            value={f.quantity ?? ""} onChange={set("quantity")} /></L>
          <L k="Unit (UOM)">
            <input style={inputStyle} list="psc-uoms" value={f.uom || ""}
              onChange={set("uom")} placeholder="nos / m² / set" />
            <datalist id="psc-uoms">
              {UOMS.map((u) => <option key={u} value={u} />)}</datalist></L>
          <L k="Trade / category">
            <select style={inputStyle} value={f.category || ""}
              onChange={set("category")}>
              <option value="">—</option>
              {f.category && !cats.some((x) => x.name === f.category) &&
                <option value={f.category}>{f.category}</option>}
              {cats.map((x) => <option key={x.id} value={x.name}>
                {x.name}</option>)}
            </select></L>
          <L k="Required on site"><input type="date" style={inputStyle}
            value={f.required_date || ""} onChange={set("required_date")} /></L>
          <LeadTimeFields f={f} set={set} setF={setF} />
          <L k="Specification" wide><input style={inputStyle}
            value={f.specification} onChange={set("specification")} /></L>
          <L k="Remarks" wide><input style={inputStyle} value={f.remarks || ""}
            onChange={set("remarks")} /></L>
          <label style={{ ...fld, alignSelf: "end" }}>
            <span><input type="checkbox" checked={!!f.tds_required}
              onChange={set("tds_required")} /> TDS / MAR required</span></label>
        </div>
      ) : (
        <div style={grid}>
          <L k="Planned supplier" wide><input style={inputStyle}
            value={f.planned_supplier || ""}
            onChange={set("planned_supplier")} /></L>
          <L k="Estimated value"><input type="number" style={inputStyle}
            value={f.estimated_value ?? ""}
            onChange={set("estimated_value")} /></L>
          <L k="Currency"><input style={inputStyle} value={f.currency || "USD"}
            onChange={set("currency")} /></L>
          {/* Purchasing sees these too: the PM plans them from the spec, and
              a supplier's quote is where the real lead time turns up. */}
          <LeadTimeFields f={f} set={set} setF={setF} />
        </div>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <Btn variant="primary" disabled={busy} onClick={save}>Save</Btn>
        <Btn variant="ghost" disabled={busy} onClick={onCancel}>Cancel</Btn>
        {!isNew && !commercial && line.state === "PROPOSED" &&
          <Btn variant="danger" disabled={busy} onClick={del}>Delete</Btn>}
      </div>
    </div>
  );
}

const fld = { display: "flex", flexDirection: "column", gap: 3, fontSize: 12,
  color: "var(--muted)" };
const grid = { display: "grid", gap: 8, gridTemplateColumns: "repeat(3, 1fr)" };
const cell = { padding: "6px 10px", verticalAlign: "top" };
const linkBtn = { border: "none", background: "none", cursor: "pointer",
  color: "var(--navy)", fontSize: 13, padding: 0 };
function L({ k, wide, children }) {
  return <label style={{ ...fld, gridColumn: wide ? "span 2" : "auto" }}>
    {k}{children}</label>;
}
