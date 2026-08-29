import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { BTN, buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";
import { ToolboxTab, TrainingTab, WorkerRecordsTab } from "./HseRecords.jsx";
import { AssessmentsTab, InspectionsTab, PermitsTab } from "./HseWork.jsx";

// Safety (HSE). The app's whole safety functionality used to be one checkbox
// on the daily report that notified nobody, so "how many incidents last
// quarter?" could only be answered by reading every report by hand.
//
// Two things drive the design. Reporting is deliberately the cheapest action
// on the page — a near miss must never feel like a bigger decision than
// keeping quiet. And the page leads with what is unfinished: open incidents
// and overdue actions, not a count of records filed.

const KINDS = [
  ["NEAR_MISS", "Near miss"],
  ["FIRST_AID", "First aid"],
  ["MEDICAL", "Medical treatment"],
  ["LOST_TIME", "Lost-time injury"],
  ["FATALITY", "Fatality"],
  ["PROPERTY", "Property / plant damage"],
  ["ENVIRONMENTAL", "Environmental"],
  ["DANGEROUS", "Dangerous occurrence"],
];
const SEVERITIES = [["LOW", "Low"], ["MEDIUM", "Medium"], ["HIGH", "High"],
                    ["CRITICAL", "Critical"]];
const INVOLVEMENT = [["INJURED", "Injured"], ["INVOLVED", "Involved"],
                     ["WITNESS", "Witness"]];
// The HSE officer on a bigger site works under a Site Engineer or Site Admin
// login, so the site team investigates and closes its own incidents
// (owner 2026-08-29). The API scopes them to their own site regardless.
const CAN_INVESTIGATE = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "DIRECTOR",
                         "ADMIN", "HO_HR"];

const SEVERITY_TONE = {
  LOW: { bg: "#eef4fb", fg: "#16527E" },
  MEDIUM: { bg: "#f9efe2", fg: "#8a5200" },
  HIGH: { bg: "#f9e8e6", fg: "#a3271b" },
  CRITICAL: { bg: "#a3271b", fg: "#fff" },
};
const STATUS_LABEL = {
  REPORTED: "Reported", INVESTIGATING: "Investigating",
  ACTIONS_OPEN: "Actions open", CLOSED: "Closed",
};

function Pill({ children, tone }) {
  return (
    <span style={{ display: "inline-block", padding: "2px 9px",
                   borderRadius: 999, fontSize: 11, fontWeight: 700,
                   letterSpacing: ".03em", whiteSpace: "nowrap",
                   background: tone?.bg || "#eef1f4",
                   color: tone?.fg || "#4a5b68" }}>{children}</span>
  );
}

function Modal({ title, children, onClose, wide }) {
  return (
    <div onClick={onClose}
         style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.35)",
                  display: "flex", alignItems: "center",
                  justifyContent: "center", zIndex: 50, padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ ...card, maxWidth: wide ? 860 : 620, width: "100%",
                    maxHeight: "88vh", overflow: "auto" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <h2 style={{ margin: 0, color: "var(--navy)", fontSize: 16 }}>
            {title}</h2>
          <button onClick={onClose}
                  style={{ ...ghostButton, marginLeft: "auto" }}>Close</button>
        </div>
        <div style={{ marginTop: 14 }}>{children}</div>
      </div>
    </div>
  );
}

function Stat({ value, label, alarm }) {
  return (
    <div style={{ padding: "12px 16px", background: "var(--paper)",
                  border: "1px solid var(--line)", borderRadius: 10,
                  minWidth: 118 }}>
      <div style={{ fontSize: 24, fontWeight: 700,
                    fontFamily: "var(--font-mono, monospace)",
                    color: alarm && value > 0 ? "#a3271b" : "var(--navy)" }}>
        {value}</div>
      <div style={{ fontSize: 12, color: "#5a6b78", marginTop: 2 }}>{label}</div>
    </div>
  );
}

export default function HsePage({ me, sites, site }) {
  const [tab, setTab] = useState("incidents");
  const [stats, setStats] = useState(null);
  const [rows, setRows] = useState([]);
  const [actions, setActions] = useState([]);
  const [openOnly, setOpenOnly] = useState(true);
  const [siteFilter, setSiteFilter] = useState(site?.id || "");
  const [reporting, setReporting] = useState(false);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const canInvestigate = CAN_INVESTIGATE.includes(me.role);

  const load = useCallback(() => {
    const q = [];
    if (openOnly) q.push("status=open");
    if (siteFilter) q.push(`site=${siteFilter}`);
    api(`/hse/incidents${q.length ? `?${q.join("&")}` : ""}`)
      .then(setRows).catch((e) => setError(e.message));
    api(`/hse/actions?status=open${siteFilter ? `&site=${siteFilter}` : ""}`)
      .then(setActions).catch(() => setActions([]));
    api(`/hse/stats${siteFilter ? `?site=${siteFilter}` : ""}`)
      .then(setStats).catch(() => setStats(null));
  }, [openOnly, siteFilter]);

  useEffect(load, [load]);

  const reopenDetail = (ref) =>
    api(`/hse/incidents/${ref}`).then(setDetail).catch(() => {});

  return (
    <section>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap", marginBottom: 4 }}>
        <h2 style={{ margin: 0, color: "var(--navy)" }}>Safety</h2>
        <p style={{ margin: 0, fontSize: 13, color: "#5a6b78" }}>
          Incidents, near misses and the actions that came out of them.
        </p>
        <button onClick={() => setReporting(true)}
                style={{ ...BTN.primary, marginLeft: "auto" }}>
          Report an incident
        </button>
      </div>

      {error && (
        <p style={{ color: "#a3271b", fontSize: 13 }}>{error}</p>
      )}
      {notice && (
        <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>
      )}

      {stats && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                      margin: "14px 0 18px" }}>
          <Stat value={stats.open} label="Open incidents" alarm />
          <Stat value={stats.actions_overdue} label="Actions overdue" alarm />
          <Stat value={stats.actions_open} label="Actions open" />
          <Stat value={stats.permits_expired} label="Permits not handed back"
                alarm />
          <Stat value={stats.permits_open} label="Permits open" />
          <Stat value={stats.near_misses} label="Near misses" />
          <Stat value={stats.injuries} label="Injuries" />
          <Stat value={stats.lost_time} label="Lost-time injuries" />
          <Stat value={stats.days_lost} label="Days lost" />
        </div>
      )}

      <div style={{ display: "flex", gap: 2, marginBottom: 12,
                    flexWrap: "wrap", alignItems: "flex-end",
                    borderBottom: "2px solid var(--line)" }}>
        {[["incidents", `Incidents (${rows.length})`],
          ["actions", `Corrective actions (${actions.length})`],
          ["permits", "Permits"],
          ["inspections", "Inspections"],
          ["assessments", "Risk assessments"],
          ["toolbox", "Toolbox talks"],
          ["training", "Competency"],
          ["workers", "Worker records"]].map(
          ([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
                  style={{ background: "transparent", border: "none",
                           cursor: "pointer", padding: "7px 16px 8px",
                           fontSize: 13.5, marginBottom: -2,
                           fontFamily: "inherit",
                           color: tab === key ? "var(--navy)" : "#5a6b78",
                           fontWeight: tab === key ? 700 : 500,
                           borderBottom: tab === key
                             ? "2.5px solid var(--navy)"
                             : "2.5px solid transparent" }}>
            {label}
          </button>
        ))}
        {tab === "incidents" && (
          <label style={{ marginLeft: "auto", fontSize: 12.5,
                          color: "#5a6b78", display: "flex",
                          alignItems: "center", gap: 6, paddingBottom: 6 }}>
            <input type="checkbox" checked={openOnly}
                   onChange={(e) => setOpenOnly(e.target.checked)} />
            Unfinished only
          </label>
        )}
        {!site && (sites || []).length > 1 && (
          <select value={siteFilter} style={{ marginLeft: tab === "incidents"
            ? 10 : "auto" }}
                  onChange={(e) => setSiteFilter(e.target.value)}
                  style={{ ...inputStyle, width: "auto", marginBottom: 5,
                           marginLeft: 10 }}>
            <option value="">All sites</option>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>{s.code}</option>
            ))}
          </select>
        )}
      </div>

      {tab === "incidents" && (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={{ ...th, width: 120 }}>Ref</th>
            <th style={{ ...th, width: 96 }}>Date</th>
            <th style={{ ...th, width: 60 }}>Site</th>
            <th style={th}>What happened</th>
            <th style={{ ...th, width: 130 }}>Kind</th>
            <th style={{ ...th, width: 90 }}>Severity</th>
            <th style={{ ...th, width: 120 }}>Status</th>
          </tr></thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={7} style={{ ...td, color: "#8a97a1" }}>
                {openOnly ? "Nothing open." : "No incidents recorded."}
              </td></tr>
            )}
            {rows.map((r) => (
              <tr key={r.id} onClick={() => setDetail(r)}
                  style={{ cursor: "pointer" }}>
                <td style={{ ...td, fontWeight: 600,
                             fontFamily: "var(--font-mono, monospace)" }}>
                  {r.ref}</td>
                <td style={td}>
                  {new Date(r.occurred_at).toLocaleDateString()}</td>
                <td style={td}>{r.site_code}</td>
                <td style={td}>
                  {r.description.length > 90
                    ? `${r.description.slice(0, 90)}…` : r.description}
                  {r.open_actions > 0 && (
                    <span style={{ color: "#8a5200", fontSize: 12 }}>
                      {" "}· {r.open_actions} action(s) open</span>
                  )}
                </td>
                <td style={td}>{r.kind_display}</td>
                <td style={td}>
                  <Pill tone={SEVERITY_TONE[r.severity]}>{r.severity}</Pill>
                </td>
                <td style={td}>{STATUS_LABEL[r.status] || r.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "permits" && (
        <PermitsTab sites={sites} siteFilter={siteFilter} />
      )}

      {tab === "inspections" && (
        <InspectionsTab me={me} sites={sites} siteFilter={siteFilter} />
      )}

      {tab === "assessments" && (
        <AssessmentsTab sites={sites} siteFilter={siteFilter} />
      )}

      {tab === "toolbox" && (
        <ToolboxTab me={me} sites={sites} siteFilter={siteFilter} />
      )}

      {tab === "training" && <TrainingTab siteFilter={siteFilter} />}

      {tab === "workers" && (
        <WorkerRecordsTab sites={sites} siteFilter={siteFilter} />
      )}

      {tab === "actions" && (
        <ActionTable actions={actions} me={me} canVerify={canInvestigate}
                     onChanged={() => { load(); setNotice(null); }}
                     onError={setError} />
      )}

      {reporting && (
        <ReportForm me={me} sites={sites} site={site}
                    onClose={() => setReporting(false)}
                    onSaved={(inc) => {
                      setReporting(false);
                      setNotice(`${inc.ref} reported.`);
                      load();
                      setDetail(inc);
                    }} />
      )}

      {detail && (
        <IncidentDetail incident={detail} me={me}
                        canInvestigate={canInvestigate}
                        onClose={() => { setDetail(null); load(); }}
                        onChanged={(fresh) => { setDetail(fresh); load(); }} />
      )}
    </section>
  );
}

// ---------------------------------------------------------------- reporting
function ReportForm({ me, sites, site, onClose, onSaved }) {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 16);
  const [f, setF] = useState({
    site_id: site?.id || "", kind: "NEAR_MISS", severity: "LOW",
    occurred_at: local, location: "", description: "",
    immediate_action: "", work_stopped: false,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));

  async function save() {
    if (!f.site_id) return setError("Choose the site.");
    if (!f.description.trim()) return setError("Describe what happened.");
    setBusy(true); setError(null);
    try {
      const inc = await api("/hse/incidents", {
        method: "POST",
        body: { ...f, occurred_at: new Date(f.occurred_at).toISOString() },
      });
      onSaved(inc);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Report an incident" onClose={onClose}>
      <p style={{ fontSize: 12.5, color: "#5a6b78", margin: "0 0 14px" }}>
        Report it now with whatever you know. Kind and severity can be
        corrected during the investigation — a near miss reported late is
        worth less than one reported roughly.
      </p>
      <div style={{ display: "grid", gap: 12,
                    gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))" }}>
        {!site && (
          <label style={{ fontSize: 13 }}>Site
            <select value={f.site_id} onChange={(e) => set("site_id", e.target.value)}
                    style={inputStyle}>
              <option value="">— choose —</option>
              {(sites || []).map((s) => (
                <option key={s.id} value={s.id}>{s.code} — {s.name}</option>
              ))}
            </select>
          </label>
        )}
        <label style={{ fontSize: 13 }}>What kind
          <select value={f.kind} onChange={(e) => set("kind", e.target.value)}
                  style={inputStyle}>
            {KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Severity
          <select value={f.severity}
                  onChange={(e) => set("severity", e.target.value)}
                  style={inputStyle}>
            {SEVERITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>When
          <input type="datetime-local" value={f.occurred_at}
                 onChange={(e) => set("occurred_at", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Where
          <input value={f.location} placeholder="Villa 3, north face"
                 onChange={(e) => set("location", e.target.value)}
                 style={inputStyle} />
        </label>
      </div>
      <label style={{ fontSize: 13, display: "block", marginTop: 12 }}>
        What happened
        <textarea value={f.description} rows={4}
                  onChange={(e) => set("description", e.target.value)}
                  style={{ ...inputStyle, resize: "vertical" }} />
      </label>
      <label style={{ fontSize: 13, display: "block", marginTop: 12 }}>
        What was done straight away
        <textarea value={f.immediate_action} rows={2}
                  onChange={(e) => set("immediate_action", e.target.value)}
                  style={{ ...inputStyle, resize: "vertical" }} />
      </label>
      <label style={{ fontSize: 13, display: "flex", gap: 8,
                      alignItems: "center", marginTop: 12 }}>
        <input type="checkbox" checked={f.work_stopped}
               onChange={(e) => set("work_stopped", e.target.checked)} />
        Work was stopped / the area was closed
      </label>
      {error && <p style={{ color: "#a3271b", fontSize: 13 }}>{error}</p>}
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Reporting…" : "Report"}
        </button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </Modal>
  );
}

// ------------------------------------------------------------------ detail
function IncidentDetail({ incident, me, canInvestigate, onClose, onChanged }) {
  const [inv, setInv] = useState({
    root_cause: incident.root_cause || "",
    contributing_factors: incident.contributing_factors || "",
    lessons: incident.lessons || "",
    severity: incident.severity,
    is_reportable: incident.is_reportable,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [addingAction, setAddingAction] = useState(false);
  const closed = incident.status === "CLOSED";

  const refresh = () => api(`/hse/incidents/${incident.ref}`).then(onChanged);

  async function act(path, body) {
    setBusy(true); setError(null);
    try {
      const fresh = await api(`/hse/incidents/${incident.ref}${path}`,
                              { method: "POST", body: body || {} });
      onChanged(fresh);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function saveInvestigation() {
    setBusy(true); setError(null);
    try {
      const fresh = await api(`/hse/incidents/${incident.ref}`,
                              { method: "PATCH", body: inv });
      onChanged(fresh);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const openActions = (incident.actions || []).filter(
    (a) => !["VERIFIED", "CANCELLED"].includes(a.status));

  return (
    <Modal wide title={`${incident.ref} — ${incident.kind_display}`}
           onClose={onClose}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                    marginBottom: 12 }}>
        <Pill tone={SEVERITY_TONE[incident.severity]}>
          {incident.severity}</Pill>
        <Pill>{STATUS_LABEL[incident.status] || incident.status}</Pill>
        {incident.work_stopped && <Pill tone={SEVERITY_TONE.HIGH}>
          Work stopped</Pill>}
        {incident.is_reportable && <Pill tone={SEVERITY_TONE.HIGH}>
          Reportable</Pill>}
      </div>

      <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr",
                   gap: "6px 14px", fontSize: 13.5, margin: "0 0 16px" }}>
        <dt style={{ color: "#5a6b78" }}>When</dt>
        <dd style={{ margin: 0 }}>
          {new Date(incident.occurred_at).toLocaleString()}</dd>
        <dt style={{ color: "#5a6b78" }}>Where</dt>
        <dd style={{ margin: 0 }}>
          {incident.site_code}{incident.location && ` · ${incident.location}`}
        </dd>
        <dt style={{ color: "#5a6b78" }}>Reported by</dt>
        <dd style={{ margin: 0 }}>{incident.reported_by_name}</dd>
        <dt style={{ color: "#5a6b78" }}>What happened</dt>
        <dd style={{ margin: 0, whiteSpace: "pre-wrap" }}>
          {incident.description}</dd>
        {incident.immediate_action && (<>
          <dt style={{ color: "#5a6b78" }}>Done straight away</dt>
          <dd style={{ margin: 0, whiteSpace: "pre-wrap" }}>
            {incident.immediate_action}</dd>
        </>)}
      </dl>

      <PeopleBlock incident={incident} onChanged={onChanged} />

      {canInvestigate && !closed && (
        <>
          <h3 style={{ fontSize: 14, margin: "18px 0 6px" }}>Investigation</h3>
          {incident.status === "REPORTED" && (
            <button onClick={() => act("/investigate")} disabled={busy}
                    style={{ ...BTN.primary, marginBottom: 10 }}>
              Start the investigation
            </button>
          )}
          <label style={{ fontSize: 13, display: "block", marginBottom: 8 }}>
            Root cause — why it happened, not what happened
            <textarea value={inv.root_cause} rows={2}
                      onChange={(e) => setInv({ ...inv,
                                                root_cause: e.target.value })}
                      style={{ ...inputStyle, resize: "vertical" }} />
          </label>
          <label style={{ fontSize: 13, display: "block", marginBottom: 8 }}>
            Contributing factors
            <textarea value={inv.contributing_factors} rows={2}
                      onChange={(e) => setInv({
                        ...inv, contributing_factors: e.target.value })}
                      style={{ ...inputStyle, resize: "vertical" }} />
          </label>
          <label style={{ fontSize: 13, display: "block", marginBottom: 8 }}>
            Lessons
            <textarea value={inv.lessons} rows={2}
                      onChange={(e) => setInv({ ...inv,
                                                lessons: e.target.value })}
                      style={{ ...inputStyle, resize: "vertical" }} />
          </label>
          <label style={{ fontSize: 13, display: "flex", gap: 8,
                          alignItems: "center", marginBottom: 10 }}>
            <input type="checkbox" checked={inv.is_reportable}
                   onChange={(e) => setInv({ ...inv,
                                             is_reportable: e.target.checked })} />
            Reportable to the authorities
          </label>
          <button onClick={saveInvestigation} disabled={busy}
                  style={ghostButton}>Save investigation</button>
        </>
      )}

      {closed && incident.root_cause && (
        <>
          <h3 style={{ fontSize: 14, margin: "18px 0 6px" }}>Investigation</h3>
          <p style={{ fontSize: 13.5, whiteSpace: "pre-wrap", margin: 0 }}>
            <strong>Root cause:</strong> {incident.root_cause}</p>
          {incident.lessons && (
            <p style={{ fontSize: 13.5, whiteSpace: "pre-wrap" }}>
              <strong>Lessons:</strong> {incident.lessons}</p>
          )}
        </>
      )}

      <h3 style={{ fontSize: 14, margin: "18px 0 6px" }}>
        Corrective actions
        {openActions.length > 0 && (
          <span style={{ color: "#8a5200", fontWeight: 500 }}>
            {" "}· {openActions.length} still open</span>
        )}
      </h3>
      {(incident.actions || []).length === 0 && (
        <p style={{ fontSize: 13, color: "#8a97a1", margin: "0 0 8px" }}>
          Nothing raised yet.</p>
      )}
      {(incident.actions || []).map((a) => (
        <div key={a.id} style={{ borderLeft: "3px solid var(--line)",
                                 padding: "4px 0 4px 12px", marginBottom: 8,
                                 fontSize: 13.5 }}>
          <div>{a.description}</div>
          <div style={{ fontSize: 12, color: "#5a6b78" }}>
            {a.owner_name} · due {a.due_date} · {a.status}
            {a.days_overdue > 0 && (
              <strong style={{ color: "#a3271b" }}>
                {" "}· {a.days_overdue} days overdue</strong>
            )}
          </div>
        </div>
      ))}
      {!closed && (
        addingAction ? (
          <ActionForm incidentRef={incident.ref}
                      onClose={() => setAddingAction(false)}
                      onSaved={() => { setAddingAction(false); refresh(); }} />
        ) : (
          <button onClick={() => setAddingAction(true)} style={ghostButton}>
            Raise a corrective action
          </button>
        )
      )}

      {error && <p style={{ color: "#a3271b", fontSize: 13 }}>{error}</p>}

      {canInvestigate && !closed && (
        <div style={{ marginTop: 18, paddingTop: 14,
                      borderTop: "1px solid var(--line)" }}>
          <button onClick={() => act("/close")} disabled={busy}
                  style={BTN.navy}>Close this incident</button>
          <span style={{ fontSize: 12, color: "#5a6b78", marginLeft: 10 }}>
            Needs a root cause, and every action verified.
          </span>
        </div>
      )}
    </Modal>
  );
}

// Who was hurt, involved or watching. An injury record without the injured
// person is not a record of anything.
function PeopleBlock({ incident, onChanged }) {
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ name: "", employer: "",
                               involvement: "INJURED", injury: "",
                               body_part: "", treatment: "", days_lost: 0 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const closed = incident.status === "CLOSED";

  async function save() {
    if (!f.name.trim()) return setError("Who was it?");
    setBusy(true); setError(null);
    try {
      const fresh = await api(`/hse/incidents/${incident.ref}/people`,
                              { method: "POST", body: f });
      onChanged(fresh);
      setAdding(false);
      setF({ name: "", employer: "", involvement: "INJURED", injury: "",
             body_part: "", treatment: "", days_lost: 0 });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h3 style={{ fontSize: 14, margin: "16px 0 6px" }}>People</h3>
      {(incident.people || []).length === 0 && (
        <p style={{ fontSize: 13, color: "#8a97a1", margin: "0 0 8px" }}>
          Nobody recorded yet.</p>
      )}
      {(incident.people || []).length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <tbody>
            {incident.people.map((p) => (
              <tr key={p.id}>
                <td style={{ ...td, fontWeight: 600 }}>
                  {p.display_name}
                  {p.employer && (
                    <span style={{ fontWeight: 400, color: "#5a6b78" }}>
                      {" "}· {p.employer}</span>
                  )}
                </td>
                <td style={{ ...td, width: 90 }}>{p.involvement}</td>
                <td style={td}>
                  {p.injury || "—"}
                  {p.body_part && ` (${p.body_part})`}
                </td>
                <td style={{ ...td, width: 110 }}>
                  {p.days_lost ? `${p.days_lost} days lost` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!closed && !adding && (
        <button onClick={() => setAdding(true)}
                style={{ ...ghostButton, marginTop: 6 }}>Add a person</button>
      )}
      {adding && (
        <div style={{ background: "var(--sand,#f7f4ee)", padding: 12,
                      borderRadius: 8, marginTop: 8 }}>
          <div style={{ display: "grid", gap: 10,
                        gridTemplateColumns:
                          "repeat(auto-fit,minmax(150px,1fr))" }}>
            <label style={{ fontSize: 13 }}>Name
              <input value={f.name}
                     onChange={(e) => setF({ ...f, name: e.target.value })}
                     style={inputStyle} />
            </label>
            <label style={{ fontSize: 13 }}>Employer
              <input value={f.employer} placeholder="Us, or the subcontractor"
                     onChange={(e) => setF({ ...f, employer: e.target.value })}
                     style={inputStyle} />
            </label>
            <label style={{ fontSize: 13 }}>Involvement
              <select value={f.involvement}
                      onChange={(e) => setF({ ...f,
                                              involvement: e.target.value })}
                      style={inputStyle}>
                {INVOLVEMENT.map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </select>
            </label>
            {f.involvement === "INJURED" && (
              <>
                <label style={{ fontSize: 13 }}>Injury
                  <input value={f.injury}
                         onChange={(e) => setF({ ...f,
                                                 injury: e.target.value })}
                         style={inputStyle} />
                </label>
                <label style={{ fontSize: 13 }}>Body part
                  <input value={f.body_part}
                         onChange={(e) => setF({ ...f,
                                                 body_part: e.target.value })}
                         style={inputStyle} />
                </label>
                <label style={{ fontSize: 13 }}>Days lost
                  <input type="number" min="0" value={f.days_lost}
                         onChange={(e) => setF({ ...f,
                                                 days_lost: e.target.value })}
                         style={inputStyle} />
                </label>
              </>
            )}
          </div>
          {error && <p style={{ color: "#a3271b", fontSize: 13 }}>{error}</p>}
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button onClick={save} disabled={busy} style={buttonStyle}>
              Add</button>
            <button onClick={() => setAdding(false)} style={ghostButton}>
              Cancel</button>
          </div>
        </div>
      )}
    </>
  );
}

function ActionForm({ incidentRef, onClose, onSaved }) {
  const [people, setPeople] = useState([]);
  const [f, setF] = useState({ description: "", owner_id: "", due_date: "",
                               priority: "MEDIUM", is_preventive: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/directory").then(setPeople).catch(() => setPeople([]));
  }, []);

  async function save() {
    setBusy(true); setError(null);
    try {
      await api(`/hse/incidents/${incidentRef}/actions`,
                { method: "POST", body: f });
      onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ background: "var(--sand,#f7f4ee)", padding: 12,
                  borderRadius: 8, marginTop: 8 }}>
      <label style={{ fontSize: 13, display: "block" }}>What must change
        <textarea value={f.description} rows={2}
                  onChange={(e) => setF({ ...f, description: e.target.value })}
                  style={{ ...inputStyle, resize: "vertical" }} />
      </label>
      <div style={{ display: "grid", gap: 10, marginTop: 8,
                    gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))" }}>
        <label style={{ fontSize: 13 }}>Owner
          <select value={f.owner_id}
                  onChange={(e) => setF({ ...f, owner_id: e.target.value })}
                  style={inputStyle}>
            <option value="">— choose —</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>{p.full_name}</option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Due
          <input type="date" value={f.due_date}
                 onChange={(e) => setF({ ...f, due_date: e.target.value })}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Priority
          <select value={f.priority}
                  onChange={(e) => setF({ ...f, priority: e.target.value })}
                  style={inputStyle}>
            <option value="LOW">Low</option>
            <option value="MEDIUM">Medium</option>
            <option value="HIGH">High</option>
          </select>
        </label>
      </div>
      <label style={{ fontSize: 13, display: "flex", gap: 8,
                      alignItems: "center", marginTop: 8 }}>
        <input type="checkbox" checked={f.is_preventive}
               onChange={(e) => setF({ ...f,
                                       is_preventive: e.target.checked })} />
        Stops it happening again (rather than fixing this instance)
      </label>
      {error && <p style={{ color: "#a3271b", fontSize: 13 }}>{error}</p>}
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>Raise</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------- actions
function ActionTable({ actions, me, canVerify, onChanged, onError }) {
  const [busy, setBusy] = useState(null);

  async function run(id, path, body) {
    setBusy(id);
    try {
      await api(`/hse/actions/${id}/${path}`,
                { method: "POST", body: body || {} });
      onChanged();
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(null);
    }
  }

  if (actions.length === 0) {
    return <p style={{ fontSize: 13, color: "#8a97a1" }}>
      Nothing open. Every action raised has been verified closed.</p>;
  }

  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead><tr>
        <th style={{ ...th, width: 110 }}>From</th>
        <th style={th}>What must change</th>
        <th style={{ ...th, width: 150 }}>Owner</th>
        <th style={{ ...th, width: 100 }}>Due</th>
        <th style={{ ...th, width: 120 }}>Status</th>
        <th style={{ ...th, width: 150 }} />
      </tr></thead>
      <tbody>
        {actions.map((a) => (
          <tr key={a.id}>
            <td style={{ ...td, fontFamily: "var(--font-mono, monospace)",
                         fontSize: 12.5 }}>{a.source_ref}</td>
            <td style={td}>
              {a.description}
              {a.is_preventive && (
                <span style={{ fontSize: 11.5, color: "#5a6b78" }}>
                  {" "}· preventive</span>
              )}
            </td>
            <td style={td}>{a.owner_name}</td>
            <td style={{ ...td,
                         color: a.days_overdue > 0 ? "#a3271b" : undefined,
                         fontWeight: a.days_overdue > 0 ? 700 : 400 }}>
              {a.due_date}
              {a.days_overdue > 0 && ` (+${a.days_overdue})`}
            </td>
            <td style={td}>{a.status.replace(/_/g, " ")}</td>
            <td style={td}>
              {a.status !== "DONE" && a.owner === me.id && (
                <button disabled={busy === a.id} style={ghostButton}
                        onClick={() => run(a.id, "complete",
                          { note: window.prompt("What was done?") || "" })}>
                  Mark done
                </button>
              )}
              {a.status === "DONE" && canVerify && (
                <button disabled={busy === a.id} style={BTN.navy}
                        onClick={() => run(a.id, "verify")}>
                  Verify
                </button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
