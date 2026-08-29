import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { BTN, buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Contract & time. There was no notice of any kind, no RFI register and no
// delay log, so a delay claim rested on daily reports and photographs.
//
// Each register leads with its own exposure: a reply that is overdue, an
// employer-risk delay with no notice served, an application awaiting a
// decision.

const KINDS = [["RFI", "Request for information"], ["LTR", "Letter"],
               ["INS", "Instruction"], ["NTC", "Contractual notice"]];
const PARTIES = [["CLIENT", "Client / Employer"],
                 ["CONSULTANT", "Consultant / Engineer"],
                 ["SUBCONTRACTOR", "Subcontractor"], ["SUPPLIER", "Supplier"],
                 ["AUTHORITY", "Authority"], ["OTHER", "Other"]];
const CAUSES = [
  ["WEATHER", "Weather / sea conditions"],
  ["LATE_INFORMATION", "Information late"],
  ["INSTRUCTION", "Instruction / variation"],
  ["ACCESS", "Access not given"], ["LATE_MATERIAL", "Material late"],
  ["SUBCONTRACTOR", "Subcontractor"], ["AUTHORITY", "Authority / permit"],
  ["OUR_OWN", "Our own resource or method"], ["OTHER", "Other"],
];
const RESPONSIBILITIES = [
  ["UNDECIDED", "Not yet decided"], ["EMPLOYER", "Employer risk"],
  ["NEUTRAL", "Neutral (shared)"], ["CONTRACTOR", "Our risk"],
];
const CAN_DECIDE = ["PM", "DIRECTOR", "ADMIN", "QS"];
const box = { background: "var(--sand,#f7f4ee)", padding: 14,
              borderRadius: 8, marginBottom: 14 };

function Err({ children }) {
  if (!children) return null;
  return <p style={{ color: "#a3271b", fontSize: 13 }}>{children}</p>;
}

function Stat({ value, label, alarm }) {
  return (
    <div style={{ padding: "12px 16px", background: "var(--paper)",
                  border: "1px solid var(--line)", borderRadius: 10,
                  minWidth: 120 }}>
      <div style={{ fontSize: 24, fontWeight: 700,
                    fontFamily: "var(--font-mono, monospace)",
                    color: alarm && value > 0 ? "#a3271b" : "var(--navy)" }}>
        {value}</div>
      <div style={{ fontSize: 12, color: "#5a6b78", marginTop: 2 }}>{label}</div>
    </div>
  );
}

export default function ContractPage({ me, sites }) {
  const [tab, setTab] = useState("correspondence");
  const [siteFilter, setSiteFilter] = useState("");
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState("");

  useEffect(() => {
    if (!siteFilter) { setProjects([]); setProjectId(""); return; }
    api(`/sites/${siteFilter}/projects`).then((list) => {
      setProjects(list || []);
      setProjectId(list?.length === 1 ? list[0].id : "");
    }).catch(() => setProjects([]));
  }, [siteFilter]);

  return (
    <section>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap", marginBottom: 10 }}>
        <h2 style={{ margin: 0, color: "var(--navy)" }}>Contract &amp; time</h2>
        <p style={{ margin: 0, fontSize: 13, color: "#5a6b78" }}>
          Correspondence and notices, what delayed the work, and what we have
          claimed for it.
        </p>
      </div>

      <div style={{ display: "flex", gap: 2, marginBottom: 12,
                    flexWrap: "wrap", alignItems: "flex-end",
                    borderBottom: "2px solid var(--line)" }}>
        {[["correspondence", "Correspondence & notices"],
          ["delays", "Delay events"], ["eot", "Extensions of time"]]
          .map(([key, label]) => (
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
        <div style={{ marginLeft: "auto", display: "flex", gap: 8,
                      paddingBottom: 5 }}>
          <select value={siteFilter}
                  onChange={(e) => setSiteFilter(e.target.value)}
                  style={{ ...inputStyle, width: "auto" }}>
            <option value="">All sites</option>
            {(sites || []).map((s) => (
              <option key={s.id} value={s.id}>{s.code}</option>
            ))}
          </select>
          {tab !== "correspondence" && projects.length > 0 && (
            <select value={projectId}
                    onChange={(e) => setProjectId(e.target.value)}
                    style={{ ...inputStyle, width: "auto" }}>
              <option value="">Choose a project</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.code}</option>
              ))}
            </select>
          )}
        </div>
      </div>

      {tab === "correspondence" && (
        <CorrespondenceTab me={me} sites={sites} siteFilter={siteFilter}
                           projects={projects} />
      )}
      {tab === "delays" && (
        <DelayTab me={me} projectId={projectId} siteFilter={siteFilter} />
      )}
      {tab === "eot" && <EotTab me={me} projectId={projectId} />}
    </section>
  );
}

// ---------------------------------------------------------- correspondence
function CorrespondenceTab({ me, sites, siteFilter, projects }) {
  const [rows, setRows] = useState([]);
  const [outstandingOnly, setOutstandingOnly] = useState(true);
  const [kind, setKind] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    const q = [];
    if (outstandingOnly) q.push("status=outstanding");
    if (siteFilter) q.push(`site=${siteFilter}`);
    if (kind) q.push(`kind=${kind}`);
    api(`/contract/correspondence${q.length ? `?${q.join("&")}` : ""}`)
      .then(setRows).catch((e) => setError(e.message));
  }, [outstandingOnly, siteFilter, kind]);
  useEffect(load, [load]);

  async function respond(ref) {
    const summary = window.prompt("What was the answer?");
    if (summary === null) return;
    try {
      await api(`/contract/correspondence/${ref}/respond`,
                { method: "POST", body: { response_summary: summary } });
      load();
    } catch (e) { setError(e.message); }
  }

  const late = rows.filter((r) => r.days_outstanding > 0);

  return (
    <>
      <div style={{ display: "flex", gap: 12, alignItems: "center",
                    marginBottom: 12, flexWrap: "wrap" }}>
        <button onClick={() => setAdding(true)} style={BTN.primary}>
          Log correspondence</button>
        <label style={{ fontSize: 12.5, color: "#5a6b78", display: "flex",
                        gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={outstandingOnly}
                 onChange={(e) => setOutstandingOnly(e.target.checked)} />
          Awaiting a reply
        </label>
        <select value={kind} onChange={(e) => setKind(e.target.value)}
                style={{ ...inputStyle, width: "auto" }}>
          <option value="">All kinds</option>
          {KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </div>
      <Err>{error}</Err>
      {late.length > 0 && (
        <p style={{ fontSize: 13, color: "#a3271b", fontWeight: 600,
                    margin: "0 0 10px" }}>
          {late.length} overdue. An unanswered RFI is the commonest root of a
          delay claim.
        </p>
      )}
      {adding && (
        <CorrespondenceForm sites={sites} siteFilter={siteFilter}
                            projects={projects}
                            onClose={() => setAdding(false)}
                            onSaved={() => { setAdding(false); load(); }} />
      )}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={{ ...th, width: 120 }}>Ref</th>
          <th style={{ ...th, width: 60 }}>Dir</th>
          <th style={th}>Subject</th>
          <th style={{ ...th, width: 130 }}>Party</th>
          <th style={{ ...th, width: 105 }}>Reply due</th>
          <th style={{ ...th, width: 110 }} />
        </tr></thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={6} style={{ ...td, color: "#8a97a1" }}>
              {outstandingOnly ? "Nothing awaiting a reply."
                               : "Nothing logged."}</td></tr>
          )}
          {rows.map((r) => (
            <tr key={r.id}>
              <td style={{ ...td, fontFamily: "var(--font-mono, monospace)",
                           fontWeight: 600 }}>
                {r.ref}
                {r.served_late && (
                  <div style={{ fontSize: 11, color: "#a3271b",
                                fontWeight: 700 }}>served late</div>
                )}
              </td>
              <td style={td}>{r.direction === "OUT" ? "→ out" : "← in"}</td>
              <td style={td}>
                {r.subject}
                {r.clause && (
                  <span style={{ color: "#5a6b78" }}> · cl. {r.clause}</span>
                )}
              </td>
              <td style={td}>{r.party_name || r.party}</td>
              <td style={{ ...td,
                           color: r.days_outstanding > 0 ? "#a3271b" : undefined,
                           fontWeight: r.days_outstanding > 0 ? 700 : 400 }}>
                {r.response_due || "—"}
                {r.days_outstanding > 0 && ` (+${r.days_outstanding})`}
              </td>
              <td style={td}>
                {!r.responded_on && r.response_required && (
                  <button onClick={() => respond(r.ref)} style={ghostButton}>
                    Answered</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function CorrespondenceForm({ sites, siteFilter, projects, onClose, onSaved }) {
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ site_id: siteFilter || "", project_id: "",
                               kind: "RFI", direction: "OUT",
                               party: "CONSULTANT", party_name: "",
                               their_ref: "", subject: "", body: "",
                               dated_on: today, response_required: true,
                               clause: "", aware_on: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));

  async function save() {
    if (!f.site_id) return setError("Choose the site.");
    if (!f.subject.trim()) return setError("What is it about?");
    setBusy(true); setError(null);
    try {
      await api("/contract/correspondence", { method: "POST", body: f });
      onSaved();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <div style={box}>
      <div style={{ display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))" }}>
        <label style={{ fontSize: 13 }}>Site
          <select value={f.site_id}
                  onChange={(e) => set("site_id", e.target.value)}
                  style={inputStyle}>
            <option value="">— choose —</option>
            {(sites || []).map((s) => (
              <option key={s.id} value={s.id}>{s.code}</option>
            ))}
          </select>
        </label>
        {projects.length > 0 && (
          <label style={{ fontSize: 13 }}>Project
            <select value={f.project_id}
                    onChange={(e) => set("project_id", e.target.value)}
                    style={inputStyle}>
              <option value="">— site-wide —</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.code}</option>
              ))}
            </select>
          </label>
        )}
        <label style={{ fontSize: 13 }}>Kind
          <select value={f.kind} onChange={(e) => set("kind", e.target.value)}
                  style={inputStyle}>
            {KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Direction
          <select value={f.direction}
                  onChange={(e) => set("direction", e.target.value)}
                  style={inputStyle}>
            <option value="OUT">Sent by us</option>
            <option value="IN">Received</option>
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Party
          <select value={f.party} onChange={(e) => set("party", e.target.value)}
                  style={inputStyle}>
            {PARTIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Their reference
          <input value={f.their_ref}
                 onChange={(e) => set("their_ref", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Dated
          <input type="date" value={f.dated_on}
                 onChange={(e) => set("dated_on", e.target.value)}
                 style={inputStyle} />
        </label>
        {f.kind === "NTC" && (
          <>
            <label style={{ fontSize: 13 }}>Clause
              <input value={f.clause} placeholder="20.1"
                     onChange={(e) => set("clause", e.target.value)}
                     style={inputStyle} />
            </label>
            <label style={{ fontSize: 13 }}>We became aware
              <input type="date" value={f.aware_on}
                     onChange={(e) => set("aware_on", e.target.value)}
                     style={inputStyle} />
            </label>
          </>
        )}
      </div>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        Subject
        <input value={f.subject}
               onChange={(e) => set("subject", e.target.value)}
               style={inputStyle} />
      </label>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        Detail
        <textarea value={f.body} rows={3}
                  onChange={(e) => set("body", e.target.value)}
                  style={{ ...inputStyle, resize: "vertical" }} />
      </label>
      <label style={{ fontSize: 13, display: "flex", gap: 8,
                      alignItems: "center", marginTop: 10 }}>
        <input type="checkbox" checked={f.response_required}
               onChange={(e) => set("response_required", e.target.checked)} />
        A reply is owed
      </label>
      {f.kind === "NTC" && f.aware_on && (
        <p style={{ fontSize: 12, color: "#5a6b78", margin: "6px 0 0" }}>
          The time bar is counted from the aware date using the project's
          notice period. If none is set on the project, no deadline is
          recorded rather than one being invented.
        </p>
      )}
      <Err>{error}</Err>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Saving…" : "Log"}</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------ delay events
function DelayTab({ me, projectId }) {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);
  const canDecide = CAN_DECIDE.includes(me.role);

  const load = useCallback(() => {
    if (!projectId) { setRows([]); setSummary(null); return; }
    api(`/contract/delays?project=${projectId}`).then(setRows)
      .catch((e) => setError(e.message));
    api(`/projects/${projectId}/entitlement`).then(setSummary)
      .catch(() => setSummary(null));
  }, [projectId]);
  useEffect(load, [load]);

  async function decide(ref) {
    const value = window.prompt(
      "Whose risk is this delay?\n\n"
      + "EMPLOYER — may buy time and money\n"
      + "NEUTRAL — typically buys time only\n"
      + "CONTRACTOR — buys neither\n\n"
      + "Type EMPLOYER, NEUTRAL or CONTRACTOR");
    if (!value) return;
    try {
      await api(`/contract/delays/${ref}`, {
        method: "PATCH",
        body: { responsibility: value.trim().toUpperCase() } });
      load();
    } catch (e) { setError(e.message); }
  }

  if (!projectId) {
    return <p style={{ fontSize: 13, color: "#8a97a1" }}>
      Choose a site and project above.</p>;
  }

  return (
    <>
      {summary && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                      marginBottom: 16 }}>
          <Stat value={summary.days_by_responsibility.EMPLOYER}
                label="Days — employer risk" />
          <Stat value={summary.days_by_responsibility.NEUTRAL}
                label="Days — neutral" />
          <Stat value={summary.days_by_responsibility.CONTRACTOR}
                label="Days — our risk" />
          <Stat value={summary.days_by_responsibility.UNDECIDED}
                label="Days — undecided" alarm />
          <Stat value={summary.employer_risk_without_notice}
                label="Employer risk, no notice served" alarm />
          <Stat value={summary.open_events} label="Still running" />
        </div>
      )}
      {summary?.employer_risk_without_notice > 0 && (
        <p style={{ fontSize: 13, color: "#a3271b", fontWeight: 600,
                    margin: "0 0 10px" }}>
          An employer-risk delay with no notice served is an entitlement at
          risk of being time-barred.
        </p>
      )}
      <div style={{ marginBottom: 12 }}>
        <button onClick={() => setAdding(true)} style={BTN.primary}>
          Log a delay event</button>
      </div>
      <Err>{error}</Err>
      {adding && (
        <DelayForm projectId={projectId} onClose={() => setAdding(false)}
                   onSaved={() => { setAdding(false); load(); }} />
      )}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={{ ...th, width: 120 }}>Ref</th>
          <th style={th}>What happened</th>
          <th style={{ ...th, width: 150 }}>Cause</th>
          <th style={{ ...th, width: 90 }}>Days</th>
          <th style={{ ...th, width: 140 }}>Whose risk</th>
          <th style={{ ...th, width: 110 }}>Notice</th>
        </tr></thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={6} style={{ ...td, color: "#8a97a1" }}>
              None logged.</td></tr>
          )}
          {rows.map((r) => (
            <tr key={r.id}>
              <td style={{ ...td, fontFamily: "var(--font-mono, monospace)",
                           fontWeight: 600 }}>{r.ref}</td>
              <td style={td}>
                {r.title}
                {r.activity_names.length > 0 && (
                  <div style={{ fontSize: 12, color: "#5a6b78" }}>
                    hit: {r.activity_names.join(", ")}</div>
                )}
              </td>
              <td style={td}>{r.cause_display}</td>
              <td style={td}>
                {r.days_lost ?? r.duration}
                {!r.ended_on && (
                  <span style={{ color: "#8a5200" }}> · running</span>
                )}
              </td>
              <td style={td}>
                {r.responsibility === "UNDECIDED" ? (
                  canDecide ? (
                    <button onClick={() => decide(r.ref)}
                            style={{ ...ghostButton, fontSize: 12,
                                     padding: "3px 10px" }}>Decide</button>
                  ) : <span style={{ color: "#8a5200" }}>undecided</span>
                ) : r.responsibility_display}
              </td>
              <td style={{ ...td,
                           color: (!r.notice_ref
                                   && r.responsibility === "EMPLOYER")
                             ? "#a3271b" : undefined }}>
                {r.notice_ref || (r.responsibility === "EMPLOYER"
                  ? "none served" : "—")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function DelayForm({ projectId, onClose, onSaved }) {
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ title: "", cause: "LATE_INFORMATION",
                               started_on: today, ended_on: "",
                               description: "", mitigation: "" });
  const [activities, setActivities] = useState([]);
  const [picked, setPicked] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));

  useEffect(() => {
    api(`/projects/${projectId}/programme`).then(setActivities)
      .catch(() => setActivities([]));
  }, [projectId]);

  async function save() {
    if (!f.title.trim()) return setError("What happened?");
    setBusy(true); setError(null);
    try {
      await api("/contract/delays", {
        method: "POST",
        body: { ...f, project_id: projectId, activity_ids: picked },
      });
      onSaved();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <div style={box}>
      <div style={{ display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))" }}>
        <label style={{ fontSize: 13 }}>Cause
          <select value={f.cause} onChange={(e) => set("cause", e.target.value)}
                  style={inputStyle}>
            {CAUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Started
          <input type="date" value={f.started_on}
                 onChange={(e) => set("started_on", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Ended (blank = still running)
          <input type="date" value={f.ended_on}
                 onChange={(e) => set("ended_on", e.target.value)}
                 style={inputStyle} />
        </label>
      </div>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        What happened
        <input value={f.title}
               placeholder="Ceiling detail not issued — RFI unanswered"
               onChange={(e) => set("title", e.target.value)}
               style={inputStyle} />
      </label>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        Mitigation — what we did about it
        <textarea value={f.mitigation} rows={2}
                  onChange={(e) => set("mitigation", e.target.value)}
                  style={{ ...inputStyle, resize: "vertical" }} />
      </label>
      {activities.length > 0 && (
        <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
          Which activities it hit
          <select multiple value={picked.map(String)}
                  onChange={(e) => setPicked(
                    [...e.target.selectedOptions].map((o) => +o.value))}
                  style={{ ...inputStyle, height: 120 }}>
            {activities.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </label>
      )}
      <Err>{error}</Err>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Saving…" : "Log"}</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------- EOT
function EotTab({ me, projectId }) {
  const [rows, setRows] = useState([]);
  const [events, setEvents] = useState([]);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);
  const canDecide = CAN_DECIDE.includes(me.role);

  const load = useCallback(() => {
    if (!projectId) { setRows([]); return; }
    api(`/contract/eots?project=${projectId}`).then(setRows)
      .catch((e) => setError(e.message));
    api(`/contract/delays?project=${projectId}`).then(setEvents)
      .catch(() => setEvents([]));
  }, [projectId]);
  useEffect(load, [load]);

  async function act(ref, path, body) {
    try {
      await api(`/contract/eots/${ref}/${path}`,
                { method: "POST", body: body || {} });
      load();
    } catch (e) { setError(e.message); }
  }

  function decide(ref, claimed) {
    const days = window.prompt(
      `How many days were awarded? (0 to reject, up to ${claimed})`);
    if (days === null) return;
    const note = window.prompt("The employer's reasoning?") || "";
    act(ref, "decide", { days_awarded: days, decision_note: note });
  }

  if (!projectId) {
    return <p style={{ fontSize: 13, color: "#8a97a1" }}>
      Choose a site and project above.</p>;
  }

  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <button onClick={() => setAdding(true)} style={BTN.primary}
                disabled={events.length === 0}>
          Prepare an application</button>
        {events.length === 0 && (
          <span style={{ fontSize: 12.5, color: "#5a6b78", marginLeft: 10 }}>
            Log the delay events first — an application is built from them,
            not typed from memory.
          </span>
        )}
      </div>
      <Err>{error}</Err>
      {adding && (
        <EotForm projectId={projectId} events={events}
                 onClose={() => setAdding(false)}
                 onSaved={() => { setAdding(false); load(); }} />
      )}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={{ ...th, width: 120 }}>Ref</th>
          <th style={th}>Grounds</th>
          <th style={{ ...th, width: 90 }}>Claimed</th>
          <th style={{ ...th, width: 90 }}>Awarded</th>
          <th style={{ ...th, width: 140 }}>Status</th>
          <th style={{ ...th, width: 130 }} />
        </tr></thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={6} style={{ ...td, color: "#8a97a1" }}>
              No applications.</td></tr>
          )}
          {rows.map((r) => (
            <tr key={r.id}>
              <td style={{ ...td, fontFamily: "var(--font-mono, monospace)",
                           fontWeight: 600 }}>{r.ref}</td>
              <td style={td}>
                {r.grounds || "—"}
                <div style={{ fontSize: 12, color: "#5a6b78" }}>
                  from {r.event_refs.join(", ")}</div>
                {r.baseline_label && (
                  <div style={{ fontSize: 12, color: "#166f30" }}>
                    programme re-baselined: {r.baseline_label}</div>
                )}
              </td>
              <td style={td}>{r.days_claimed}</td>
              <td style={td}>{r.days_awarded ?? "—"}</td>
              <td style={td}>{r.status.replace(/_/g, " ")}</td>
              <td style={td}>
                {r.status === "DRAFT" && (
                  <button onClick={() => act(r.ref, "submit")}
                          style={ghostButton}>Submit</button>
                )}
                {r.status === "SUBMITTED" && canDecide && (
                  <button onClick={() => decide(r.ref, r.days_claimed)}
                          style={BTN.navy}>Record decision</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ fontSize: 12, color: "#5a6b78", marginTop: 10 }}>
        Awarding days re-baselines the programme, so slippage afterwards is
        measured against the extended plan.
      </p>
    </>
  );
}

function EotForm({ projectId, events, onClose, onSaved }) {
  const [picked, setPicked] = useState([]);
  const [grounds, setGrounds] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const claimed = events.filter((e) => picked.includes(e.id))
    .reduce((a, e) => a + (e.days_lost ?? e.duration), 0);

  async function save() {
    if (!picked.length) return setError("Choose the delay events.");
    setBusy(true); setError(null);
    try {
      await api("/contract/eots", {
        method: "POST",
        body: { project_id: projectId, delay_event_ids: picked, grounds },
      });
      onSaved();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <div style={box}>
      <p style={{ fontSize: 13, margin: "0 0 8px" }}>
        Which delay events is this claiming for?</p>
      <div style={{ display: "flex", flexDirection: "column", gap: 4,
                    maxHeight: 200, overflowY: "auto" }}>
        {events.map((e) => (
          <label key={e.id} style={{ fontSize: 13, display: "flex", gap: 8,
                                     alignItems: "baseline" }}>
            <input type="checkbox" checked={picked.includes(e.id)}
                   onChange={() => setPicked((p) => p.includes(e.id)
                     ? p.filter((x) => x !== e.id) : [...p, e.id])} />
            <span>
              <strong>{e.ref}</strong> {e.title}
              <span style={{ color: "#5a6b78" }}>
                {" "}· {e.days_lost ?? e.duration} days
                {e.responsibility !== "EMPLOYER" && (
                  <em> · {e.responsibility_display}</em>
                )}
              </span>
            </span>
          </label>
        ))}
      </div>
      <p style={{ fontSize: 13, margin: "10px 0 0" }}>
        Claiming <strong>{claimed}</strong> days</p>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        Grounds
        <textarea value={grounds} rows={3}
                  onChange={(e) => setGrounds(e.target.value)}
                  style={{ ...inputStyle, resize: "vertical" }} />
      </label>
      <Err>{error}</Err>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Saving…" : "Prepare"}</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}
