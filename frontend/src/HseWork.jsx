import { Fragment, useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { BTN, buttonStyle, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Permits to work, risk assessments and safety inspections — the records
// about the WORK, as opposed to the records about the people. Each leads with
// its own exception: a permit never handed back, a hazard still rated high
// after controls, a checklist item that failed.

const PERMIT_KINDS = [
  ["HOT_WORK", "Hot work"], ["CONFINED", "Confined space"],
  ["HEIGHT", "Working at height"], ["LIFTING", "Lifting operation"],
  ["EXCAVATION", "Excavation"], ["ELECTRICAL", "Electrical / isolation"],
  ["DIVING", "Diving / marine"], ["OTHER", "Other"],
];

const BAND_TONE = {
  LOW: { bg: "#e7f2ea", fg: "#166f30" },
  MEDIUM: { bg: "#f9efe2", fg: "#8a5200" },
  HIGH: { bg: "#f9e8e6", fg: "#a3271b" },
  CRITICAL: { bg: "#a3271b", fg: "#fff" },
};

const box = { background: "var(--sand,#f7f4ee)", padding: 14,
              borderRadius: 8, marginBottom: 14 };

function Band({ value }) {
  if (!value) return <span style={{ color: "#8a97a1" }}>—</span>;
  const tone = BAND_TONE[value] || {};
  return (
    <span style={{ display: "inline-block", padding: "2px 8px",
                   borderRadius: 999, fontSize: 11, fontWeight: 700,
                   background: tone.bg, color: tone.fg }}>{value}</span>
  );
}

function Err({ children }) {
  if (!children) return null;
  return <p style={{ color: "#a3271b", fontSize: 13 }}>{children}</p>;
}

function localNow(offsetHours = 0) {
  const d = new Date(Date.now() + offsetHours * 3600000);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 16);
}

// ------------------------------------------------------------------ permits
export function PermitsTab({ sites, siteFilter }) {
  const [rows, setRows] = useState([]);
  const [adding, setAdding] = useState(false);
  const [openOnly, setOpenOnly] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    const q = [];
    if (openOnly) q.push("status=open");
    if (siteFilter) q.push(`site=${siteFilter}`);
    api(`/hse/permits${q.length ? `?${q.join("&")}` : ""}`)
      .then(setRows).catch((e) => setError(e.message));
  }, [openOnly, siteFilter]);
  useEffect(load, [load]);

  async function close(ref) {
    const note = window.prompt("Handing the permit back — anything to note?");
    if (note === null) return;
    try {
      await api(`/hse/permits/${ref}/close`, { method: "POST",
                                               body: { note } });
      load();
    } catch (e) { setError(e.message); }
  }

  const expired = rows.filter((r) => r.is_expired);

  return (
    <>
      <div style={{ display: "flex", gap: 12, alignItems: "center",
                    marginBottom: 12, flexWrap: "wrap" }}>
        <button onClick={() => setAdding(true)} style={BTN.primary}>
          Issue a permit</button>
        <label style={{ fontSize: 12.5, color: "#5a6b78", display: "flex",
                        gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={openOnly}
                 onChange={(e) => setOpenOnly(e.target.checked)} />
          Open only
        </label>
      </div>
      <Err>{error}</Err>
      {expired.length > 0 && (
        <p style={{ fontSize: 13, color: "#a3271b", fontWeight: 600,
                    margin: "0 0 10px" }}>
          {expired.length} permit{expired.length > 1 ? "s are" : " is"} past
          the end time and has not been handed back.
        </p>
      )}
      {adding && (
        <PermitForm sites={sites} siteFilter={siteFilter}
                    onClose={() => setAdding(false)}
                    onSaved={() => { setAdding(false); load(); }} />
      )}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={{ ...th, width: 120 }}>Ref</th>
          <th style={{ ...th, width: 150 }}>Kind</th>
          <th style={th}>Where / what</th>
          <th style={{ ...th, width: 160 }}>Valid until</th>
          <th style={{ ...th, width: 110 }}>Status</th>
          <th style={{ ...th, width: 110 }} />
        </tr></thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={6} style={{ ...td, color: "#8a97a1" }}>
              {openOnly ? "No permits open." : "No permits recorded."}
            </td></tr>
          )}
          {rows.map((r) => (
            <tr key={r.id}>
              <td style={{ ...td, fontFamily: "var(--font-mono, monospace)",
                           fontWeight: 600 }}>{r.ref}</td>
              <td style={td}>{r.kind_display}</td>
              <td style={td}>
                <strong>{r.location}</strong>
                {r.description && (
                  <div style={{ fontSize: 12, color: "#5a6b78" }}>
                    {r.description}</div>
                )}
              </td>
              <td style={{ ...td,
                           color: r.is_expired ? "#a3271b" : undefined,
                           fontWeight: r.is_expired ? 700 : 400 }}>
                {new Date(r.valid_to).toLocaleString([], {
                  dateStyle: "short", timeStyle: "short" })}
              </td>
              <td style={td}>
                {r.is_expired ? "Not handed back" : r.status}
              </td>
              <td style={td}>
                {r.status === "ISSUED" && (
                  <button onClick={() => close(r.ref)} style={ghostButton}>
                    Hand back</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function PermitForm({ sites, siteFilter, onClose, onSaved }) {
  const [f, setF] = useState({
    site_id: siteFilter || "", kind: "HOT_WORK", location: "",
    description: "", valid_from: localNow(), valid_to: localNow(8),
    precautions: "", accepted_by_name: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));

  async function save() {
    if (!f.site_id) return setError("Choose the site.");
    if (!f.location.trim()) return setError("Where is the work?");
    setBusy(true); setError(null);
    try {
      await api("/hse/permits", {
        method: "POST",
        body: { ...f,
                valid_from: new Date(f.valid_from).toISOString(),
                valid_to: new Date(f.valid_to).toISOString() },
      });
      onSaved();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <div style={box}>
      <div style={{ display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))" }}>
        {!siteFilter && (
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
        )}
        <label style={{ fontSize: 13 }}>Kind
          <select value={f.kind} onChange={(e) => set("kind", e.target.value)}
                  style={inputStyle}>
            {PERMIT_KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Valid from
          <input type="datetime-local" value={f.valid_from}
                 onChange={(e) => set("valid_from", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Valid to
          <input type="datetime-local" value={f.valid_to}
                 onChange={(e) => set("valid_to", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Accepted by
          <input value={f.accepted_by_name} placeholder="Supervisor's name"
                 onChange={(e) => set("accepted_by_name", e.target.value)}
                 style={inputStyle} />
        </label>
      </div>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        Where
        <input value={f.location} placeholder="Plant room, Villa 3"
               onChange={(e) => set("location", e.target.value)}
               style={inputStyle} />
      </label>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        What work
        <input value={f.description}
               onChange={(e) => set("description", e.target.value)}
               style={inputStyle} />
      </label>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        Precautions
        <textarea value={f.precautions} rows={3}
                  placeholder="Fire watch, extinguisher on hand, gas test before entry…"
                  onChange={(e) => set("precautions", e.target.value)}
                  style={{ ...inputStyle, resize: "vertical" }} />
      </label>
      <Err>{error}</Err>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Issuing…" : "Issue"}</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}

// --------------------------------------------------------- risk assessments
export function AssessmentsTab({ sites, siteFilter }) {
  const [rows, setRows] = useState([]);
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api(`/hse/risk-assessments?status=current${
      siteFilter ? `&site=${siteFilter}` : ""}`)
      .then(setRows).catch((e) => setError(e.message));
  }, [siteFilter]);
  useEffect(load, [load]);

  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <button onClick={() => setAdding(true)} style={BTN.primary}>
          New risk assessment</button>
      </div>
      <Err>{error}</Err>
      {adding && (
        <AssessmentForm sites={sites} siteFilter={siteFilter}
                        onClose={() => setAdding(false)}
                        onSaved={() => { setAdding(false); load(); }} />
      )}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={{ ...th, width: 120 }}>Ref</th>
          <th style={th}>Activity</th>
          <th style={{ ...th, width: 90 }}>Hazards</th>
          <th style={{ ...th, width: 110 }}>Highest risk</th>
          <th style={{ ...th, width: 100 }}>Review by</th>
        </tr></thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={5} style={{ ...td, color: "#8a97a1" }}>
              No assessments recorded.</td></tr>
          )}
          {rows.map((r) => (
            <Fragment key={r.id}>
              <tr onClick={() => setOpen(open === r.id ? null : r.id)}
                  style={{ cursor: "pointer" }}>
                <td style={{ ...td, fontFamily: "var(--font-mono, monospace)",
                             fontWeight: 600 }}>{r.ref}</td>
                <td style={td}>
                  {r.activity}
                  {r.supersedes_ref && (
                    <span style={{ fontSize: 12, color: "#5a6b78" }}>
                      {" "}· replaces {r.supersedes_ref}</span>
                  )}
                </td>
                <td style={td}>{r.hazards.length}</td>
                <td style={td}><Band value={r.highest_band} /></td>
                <td style={td}>{r.review_on || "—"}</td>
              </tr>
              {open === r.id && (
                <tr>
                  <td colSpan={5} style={{ ...td, background: "var(--sand,#f7f4ee)" }}>
                    <table style={{ width: "100%",
                                    borderCollapse: "collapse" }}>
                      <thead><tr>
                        <th style={th}>Hazard</th>
                        <th style={{ ...th, width: 130 }}>Who</th>
                        <th style={th}>Controls</th>
                        <th style={{ ...th, width: 80 }}>Risk</th>
                        <th style={th}>Further controls</th>
                        <th style={{ ...th, width: 90 }}>Residual</th>
                      </tr></thead>
                      <tbody>
                        {r.hazards.map((h) => (
                          <tr key={h.id}>
                            <td style={td}>{h.hazard}</td>
                            <td style={td}>{h.who_at_risk}</td>
                            <td style={td}>{h.existing_controls}</td>
                            <td style={td}>
                              {h.rating} <Band value={h.band} /></td>
                            <td style={td}>{h.further_controls}</td>
                            <td style={td}>
                              {h.residual_rating != null && (
                                <>{h.residual_rating}{" "}
                                  <Band value={h.residual_band} /></>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </>
  );
}

const EMPTY_HAZARD = { hazard: "", who_at_risk: "", existing_controls: "",
                       likelihood: 3, severity: 3, further_controls: "",
                       residual_likelihood: 1, residual_severity: 3 };

function AssessmentForm({ sites, siteFilter, onClose, onSaved }) {
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ site_id: siteFilter || "", activity: "",
                               assessed_on: today, review_on: "",
                               assessor_name: "", notes: "" });
  const [hazards, setHazards] = useState([{ ...EMPTY_HAZARD }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  const setH = (i, patch) => setHazards((hs) =>
    hs.map((h, j) => (j === i ? { ...h, ...patch } : h)));

  async function save() {
    if (!f.site_id) return setError("Choose the site.");
    if (!f.activity.trim()) return setError("What activity is this for?");
    const clean = hazards.filter((h) => h.hazard.trim());
    if (!clean.length) return setError("Add at least one hazard.");
    setBusy(true); setError(null);
    try {
      await api("/hse/risk-assessments", { method: "POST",
                                           body: { ...f, hazards: clean } });
      onSaved();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <div style={box}>
      <div style={{ display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))" }}>
        {!siteFilter && (
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
        )}
        <label style={{ fontSize: 13 }}>Assessed on
          <input type="date" value={f.assessed_on}
                 onChange={(e) => set("assessed_on", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Review by
          <input type="date" value={f.review_on}
                 onChange={(e) => set("review_on", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Assessed by
          <input value={f.assessor_name} placeholder="HSE officer's name"
                 onChange={(e) => set("assessor_name", e.target.value)}
                 style={inputStyle} />
        </label>
      </div>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        Activity
        <input value={f.activity} placeholder="Roof sheeting — Villa 3"
               onChange={(e) => set("activity", e.target.value)}
               style={inputStyle} />
      </label>

      <p style={{ fontSize: 12.5, color: "#5a6b78", margin: "14px 0 6px" }}>
        Risk is likelihood × severity on a 1–5 scale. Residual is the same
        judgement <em>after</em> the further controls are in place.
      </p>
      {hazards.map((h, i) => (
        <div key={i} style={{ borderTop: "1px solid var(--line)",
                              paddingTop: 10, marginTop: 10 }}>
          <div style={{ display: "grid", gap: 8,
                        gridTemplateColumns:
                          "repeat(auto-fit,minmax(150px,1fr))" }}>
            <label style={{ fontSize: 12.5 }}>Hazard
              <input value={h.hazard}
                     onChange={(e) => setH(i, { hazard: e.target.value })}
                     style={inputStyle} />
            </label>
            <label style={{ fontSize: 12.5 }}>Who is at risk
              <input value={h.who_at_risk}
                     onChange={(e) => setH(i, { who_at_risk: e.target.value })}
                     style={inputStyle} />
            </label>
            <label style={{ fontSize: 12.5 }}>Existing controls
              <input value={h.existing_controls}
                     onChange={(e) => setH(i, {
                       existing_controls: e.target.value })}
                     style={inputStyle} />
            </label>
          </div>
          <div style={{ display: "grid", gap: 8, marginTop: 8,
                        gridTemplateColumns:
                          "repeat(auto-fit,minmax(110px,1fr))" }}>
            {[["likelihood", "Likelihood"], ["severity", "Severity"],
              ["residual_likelihood", "Residual likelihood"],
              ["residual_severity", "Residual severity"]].map(([k, l]) => (
              <label key={k} style={{ fontSize: 12.5 }}>{l}
                <select value={h[k]}
                        onChange={(e) => setH(i, { [k]: +e.target.value })}
                        style={inputStyle}>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              </label>
            ))}
            <div style={{ fontSize: 12.5, alignSelf: "end",
                          paddingBottom: 8 }}>
              Risk <strong>{h.likelihood * h.severity}</strong>
              {" → "}
              <strong>{h.residual_likelihood * h.residual_severity}</strong>
            </div>
          </div>
          <label style={{ fontSize: 12.5, display: "block", marginTop: 8 }}>
            Further controls
            <input value={h.further_controls}
                   onChange={(e) => setH(i, {
                     further_controls: e.target.value })}
                   style={inputStyle} />
          </label>
          {hazards.length > 1 && (
            <button onClick={() => setHazards((hs) =>
              hs.filter((_, j) => j !== i))}
                    style={{ ...ghostButton, marginTop: 8, fontSize: 12,
                             padding: "3px 10px" }}>Remove</button>
          )}
        </div>
      ))}
      <button onClick={() => setHazards([...hazards, { ...EMPTY_HAZARD }])}
              style={{ ...ghostButton, marginTop: 10 }}>Add a hazard</button>

      <Err>{error}</Err>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Saving…" : "Record"}</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}

// -------------------------------------------------------------- inspections
export function InspectionsTab({ me, sites, siteFilter }) {
  const [rows, setRows] = useState([]);
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api(`/hse/inspections${siteFilter ? `?site=${siteFilter}` : ""}`)
      .then(setRows).catch((e) => setError(e.message));
  }, [siteFilter]);
  useEffect(load, [load]);

  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <button onClick={() => setAdding(true)} style={BTN.primary}>
          Record an inspection</button>
      </div>
      <Err>{error}</Err>
      {adding && (
        <InspectionForm sites={sites} siteFilter={siteFilter}
                        onClose={() => setAdding(false)}
                        onSaved={() => { setAdding(false); load(); }} />
      )}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={{ ...th, width: 120 }}>Ref</th>
          <th style={{ ...th, width: 100 }}>Date</th>
          <th style={th}>Area</th>
          <th style={{ ...th, width: 150 }}>Checklist</th>
          <th style={{ ...th, width: 90 }}>Actions</th>
        </tr></thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={5} style={{ ...td, color: "#8a97a1" }}>
              No inspections recorded.</td></tr>
          )}
          {rows.map((r) => (
            <tr key={r.id} onClick={() => setOpen(open === r.id ? null : r.id)}
                style={{ cursor: "pointer" }}>
              <td style={{ ...td, fontFamily: "var(--font-mono, monospace)",
                           fontWeight: 600 }}>{r.ref}</td>
              <td style={td}>{r.inspected_on}</td>
              <td style={td}>
                {r.area}
                {open === r.id && (
                  <div style={{ fontSize: 12, color: "#5a6b78",
                                marginTop: 6 }}>
                    {(r.checklist || []).map((c, i) => (
                      <div key={i}>
                        {c.result === "NOT_OK" ? "✗" : c.result === "NA"
                          ? "–" : "✓"} {c.item}
                        {c.note && ` — ${c.note}`}
                      </div>
                    ))}
                    {r.summary && <div style={{ marginTop: 6 }}>{r.summary}</div>}
                  </div>
                )}
              </td>
              <td style={td}>
                {r.counts.not_ok > 0 && (
                  <strong style={{ color: "#a3271b" }}>
                    {r.counts.not_ok} failed</strong>
                )}
                {r.counts.not_ok > 0 && " · "}
                {r.counts.ok} ok
              </td>
              <td style={td}>{(r.actions || []).length}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function InspectionForm({ sites, siteFilter, onClose, onSaved }) {
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ site_id: siteFilter || "", area: "",
                               inspected_on: today, inspector_name: "",
                               summary: "" });
  const [items, setItems] = useState([{ item: "", result: "OK", note: "" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  const setItem = (i, patch) => setItems((xs) =>
    xs.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  async function save() {
    if (!f.site_id) return setError("Choose the site.");
    if (!f.area.trim()) return setError("What area was inspected?");
    setBusy(true); setError(null);
    try {
      await api("/hse/inspections", {
        method: "POST",
        body: { ...f, checklist: items.filter((x) => x.item.trim()) },
      });
      onSaved();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <div style={box}>
      <div style={{ display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))" }}>
        {!siteFilter && (
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
        )}
        <label style={{ fontSize: 13 }}>Date
          <input type="date" value={f.inspected_on}
                 onChange={(e) => set("inspected_on", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Area
          <input value={f.area} placeholder="Villa 3 scaffold"
                 onChange={(e) => set("area", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Inspected by
          <input value={f.inspector_name} placeholder="HSE officer's name"
                 onChange={(e) => set("inspector_name", e.target.value)}
                 style={inputStyle} />
        </label>
      </div>

      <p style={{ fontSize: 12.5, color: "#5a6b78", margin: "12px 0 4px" }}>
        What was checked. Anything marked failed can be turned into a
        corrective action afterwards.
      </p>
      {items.map((x, i) => (
        <div key={i} style={{ display: "grid", gap: 8, marginBottom: 6,
                              gridTemplateColumns: "2fr 110px 2fr auto" }}>
          <input value={x.item} placeholder="Guard rails in place"
                 onChange={(e) => setItem(i, { item: e.target.value })}
                 style={inputStyle} />
          <select value={x.result}
                  onChange={(e) => setItem(i, { result: e.target.value })}
                  style={inputStyle}>
            <option value="OK">OK</option>
            <option value="NOT_OK">Failed</option>
            <option value="NA">N/A</option>
          </select>
          <input value={x.note} placeholder="Note"
                 onChange={(e) => setItem(i, { note: e.target.value })}
                 style={inputStyle} />
          {items.length > 1 && (
            <button onClick={() => setItems((xs) =>
              xs.filter((_, j) => j !== i))}
                    style={{ ...ghostButton, padding: "3px 10px",
                             fontSize: 12 }}>×</button>
          )}
        </div>
      ))}
      <button onClick={() => setItems([...items,
                                       { item: "", result: "OK", note: "" }])}
              style={ghostButton}>Add a check</button>

      <label style={{ fontSize: 13, display: "block", marginTop: 12 }}>
        Summary
        <textarea value={f.summary} rows={2}
                  onChange={(e) => set("summary", e.target.value)}
                  style={{ ...inputStyle, resize: "vertical" }} />
      </label>
      <Err>{error}</Err>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Saving…" : "Record"}</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}
