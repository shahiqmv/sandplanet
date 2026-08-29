import { Fragment, useCallback, useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { BTN, buttonStyle, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Materials & site testing. Cube tests, compaction and pressure tests were
// recorded nowhere — the reports were paper and only reached the app when
// somebody uploaded them into the handover pack at the end. Recorded here,
// handover pulls them like any other document.

const KINDS = [
  ["CUBE", "Concrete cube (compressive strength)"],
  ["SLUMP", "Slump / workability"], ["CORE", "Concrete core"],
  ["COMPACTION", "Compaction / field density"], ["CBR", "CBR / bearing"],
  ["SIEVE", "Sieve / grading"], ["STEEL", "Steel tensile / bend"],
  ["PRESSURE", "Pressure / leak test"], ["WATER", "Water quality"],
  ["OTHER", "Other"],
];
const STATUS_LABEL = { SAMPLED: "Awaiting results", PARTIAL: "Part results",
                       PASSED: "Passed", FAILED: "Failed",
                       CANCELLED: "Cancelled" };
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
                  minWidth: 118 }}>
      <div style={{ fontSize: 24, fontWeight: 700,
                    fontFamily: "var(--font-mono, monospace)",
                    color: alarm && value > 0 ? "#a3271b" : "var(--navy)" }}>
        {value}</div>
      <div style={{ fontSize: 12, color: "#5a6b78", marginTop: 2 }}>{label}</div>
    </div>
  );
}

export default function TestingTab({ me, sites, siteFilter }) {
  const [rows, setRows] = useState([]);
  const [stats, setStats] = useState(null);
  const [filter, setFilter] = useState("");
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    const q = [];
    if (siteFilter) q.push(`site=${siteFilter}`);
    if (filter === "awaiting") q.push("status=awaiting");
    if (filter === "failed") q.push("status=FAILED");
    if (filter === "overdue") q.push("overdue=1");
    api(`/quality/tests${q.length ? `?${q.join("&")}` : ""}`)
      .then(setRows).catch((e) => setError(e.message));
    api("/quality/tests/stats").then(setStats).catch(() => setStats(null));
  }, [siteFilter, filter]);
  useEffect(load, [load]);

  async function raiseNcr(ref) {
    if (!window.confirm("Raise a non-conformance for this failed test?")) return;
    try {
      await api(`/quality/tests/${ref}/ncr`, { method: "POST", body: {} });
      load();
    } catch (e) { setError(e.message); }
  }

  return (
    <>
      {stats && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                      marginBottom: 16 }}>
          <Stat value={stats.awaiting} label="Awaiting results" />
          <Stat value={stats.overdue} label="Results overdue" alarm />
          <Stat value={stats.failed} label="Failed" alarm />
          <Stat value={stats.passed} label="Passed" />
          <Stat value={stats.total} label="Samples taken" />
        </div>
      )}
      {stats?.overdue > 0 && (
        <p style={{ fontSize: 13, color: "#a3271b", fontWeight: 600,
                    margin: "0 0 10px" }}>
          {stats.overdue} sample(s) are past the age their result was due —
          either a certificate never came back, or a failure nobody chased.
        </p>
      )}

      <div style={{ display: "flex", gap: 12, alignItems: "center",
                    marginBottom: 12, flexWrap: "wrap" }}>
        <button onClick={() => setAdding(true)} style={BTN.primary}>
          Record a sample</button>
        <select value={filter} onChange={(e) => setFilter(e.target.value)}
                style={{ ...inputStyle, width: "auto" }}>
          <option value="">All tests</option>
          <option value="awaiting">Awaiting results</option>
          <option value="overdue">Results overdue</option>
          <option value="failed">Failed</option>
        </select>
      </div>
      <Err>{error}</Err>
      {adding && (
        <TestForm sites={sites} siteFilter={siteFilter}
                  onClose={() => setAdding(false)}
                  onSaved={() => { setAdding(false); load(); }} />
      )}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={{ ...th, width: 120 }}>Ref</th>
          <th style={{ ...th, width: 150 }}>Test</th>
          <th style={th}>Element / pour</th>
          <th style={{ ...th, width: 100 }}>Sampled</th>
          <th style={{ ...th, width: 130 }}>Result due</th>
          <th style={{ ...th, width: 140 }}>Status</th>
        </tr></thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={6} style={{ ...td, color: "#8a97a1" }}>
              No tests recorded.</td></tr>
          )}
          {rows.map((r) => (
            <Fragment key={r.id}>
              <tr onClick={() => setOpen(open === r.id ? null : r.id)}
                  style={{ cursor: "pointer" }}>
                <td style={{ ...td, fontFamily: "var(--font-mono, monospace)",
                             fontWeight: 600 }}>{r.ref}</td>
                <td style={td}>{r.kind_display}</td>
                <td style={td}>
                  {r.element}
                  <div style={{ fontSize: 12, color: "#5a6b78" }}>
                    {[r.pour_ref, r.grade, r.quantity].filter(Boolean)
                      .join(" · ")}
                  </div>
                </td>
                <td style={td}>{r.sampled_on}</td>
                <td style={{ ...td, color: r.is_overdue ? "#a3271b" : undefined,
                             fontWeight: r.is_overdue ? 700 : 400 }}>
                  {r.result_due_on || "—"}
                  {r.is_overdue && " · overdue"}
                </td>
                <td style={{ ...td,
                             color: r.status === "FAILED" ? "#a3271b"
                               : r.status === "PASSED" ? "#166f30" : undefined,
                             fontWeight: r.status === "FAILED" ? 700 : 400 }}>
                  {STATUS_LABEL[r.status] || r.status}
                  {r.ncr_ref && (
                    <div style={{ fontSize: 12 }}>{r.ncr_ref}</div>
                  )}
                </td>
              </tr>
              {open === r.id && (
                <tr>
                  <td colSpan={6} style={{ ...td,
                                           background: "var(--sand,#f7f4ee)" }}>
                    <ResultBlock test={r} onChanged={load}
                                 onError={setError}
                                 onRaiseNcr={() => raiseNcr(r.ref)} />
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

function ResultBlock({ test, onChanged, onError, onRaiseNcr }) {
  const [adding, setAdding] = useState(false);

  return (
    <>
      <div style={{ fontSize: 12.5, color: "#5a6b78", marginBottom: 6 }}>
        {test.spec_reference && <>Spec: {test.spec_reference} · </>}
        {test.required_value && (
          <>Required <strong>{test.required_value} {test.unit}</strong> · </>
        )}
        {test.lab_name}
        {test.witnessed_by && <> · witnessed by {test.witnessed_by}</>}
      </div>
      {test.results.length === 0 ? (
        <p style={{ fontSize: 13, margin: "0 0 8px" }}>No results yet.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse",
                        marginBottom: 8 }}>
          <thead><tr>
            <th style={{ ...th, width: 70 }}>Age</th>
            <th style={{ ...th, width: 110 }}>Tested</th>
            <th style={{ ...th, width: 110 }}>Specimen</th>
            <th style={{ ...th, width: 110 }}>Result</th>
            <th style={{ ...th, width: 90 }}>Outcome</th>
            <th style={th}>Report</th>
          </tr></thead>
          <tbody>
            {test.results.map((res) => (
              <tr key={res.id}>
                <td style={td}>{res.age_days ? `${res.age_days} d` : "—"}</td>
                <td style={td}>{res.tested_on || "—"}</td>
                <td style={td}>{res.specimen_ref || "—"}</td>
                <td style={td}>
                  {res.value != null ? `${res.value} ${res.unit || ""}` : "—"}
                </td>
                <td style={{ ...td, fontWeight: 700,
                             color: res.outcome === "FAIL" ? "#a3271b"
                               : res.outcome === "PASS" ? "#166f30"
                               : "#8a5200" }}>
                  {res.outcome}</td>
                <td style={td}>
                  {res.report_ref}
                  {res.certificate_url && (
                    <>
                      {res.report_ref ? " · " : ""}
                      <a href={res.certificate_url} target="_blank"
                         rel="noreferrer">certificate</a>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {!adding && (
          <button onClick={(e) => { e.stopPropagation(); setAdding(true); }}
                  style={ghostButton}>Record a result</button>
        )}
        {test.status === "FAILED" && !test.ncr_ref && (
          <button onClick={(e) => { e.stopPropagation(); onRaiseNcr(); }}
                  style={BTN.navy}>Raise a non-conformance</button>
        )}
      </div>
      {adding && (
        <ResultForm test={test} onClose={() => setAdding(false)}
                    onSaved={() => { setAdding(false); onChanged(); }}
                    onError={onError} />
      )}
    </>
  );
}

function ResultForm({ test, onClose, onSaved, onError }) {
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({
    age_days: test.kind === "CUBE" ? 28 : "", tested_on: today,
    specimen_ref: "", value: "", unit: test.unit || "", report_ref: "",
    remarks: "",
  });
  const [cert, setCert] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));

  async function save() {
    setBusy(true); onError(null);
    try {
      const fd = new FormData();
      Object.entries(f).forEach(([k, v]) => fd.append(k, v ?? ""));
      if (cert) fd.append("certificate", cert);
      await apiUpload(`/quality/tests/${test.ref}/results`, fd);
      onSaved();
    } catch (e) { onError(e.message); } finally { setBusy(false); }
  }

  return (
    <div style={{ ...box, marginTop: 10 }} onClick={(e) => e.stopPropagation()}>
      <div style={{ display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))" }}>
        <label style={{ fontSize: 13 }}>Age (days)
          <input type="number" min="0" value={f.age_days}
                 onChange={(e) => set("age_days", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Tested on
          <input type="date" value={f.tested_on}
                 onChange={(e) => set("tested_on", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Specimen
          <input value={f.specimen_ref} placeholder="Cube 3"
                 onChange={(e) => set("specimen_ref", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Result
          <input value={f.value} placeholder="34.5"
                 onChange={(e) => set("value", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Unit
          <input value={f.unit} placeholder="N/mm2"
                 onChange={(e) => set("unit", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Lab report no.
          <input value={f.report_ref}
                 onChange={(e) => set("report_ref", e.target.value)}
                 style={inputStyle} />
        </label>
      </div>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        Certificate
        <input type="file" onChange={(e) => setCert(e.target.files[0])}
               style={{ ...inputStyle, padding: 6 }} />
      </label>
      {test.required_value && (
        <p style={{ fontSize: 12, color: "#5a6b78", margin: "8px 0 0" }}>
          Pass or fail is decided against the specified
          {" "}{test.required_value} {test.unit} — no need to say which.
        </p>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Saving…" : "Record"}</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}

function TestForm({ sites, siteFilter, onClose, onSaved }) {
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({
    site_id: siteFilter || "", project_id: "", kind: "CUBE", element: "",
    location: "", pour_ref: "", grade: "", quantity: "",
    sampled_on: today, required_value: "", unit: "N/mm2",
    spec_reference: "", acceptance_criteria: "", lab_name: "",
    witnessed_by: "",
  });
  const [projects, setProjects] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));

  useEffect(() => {
    if (!f.site_id) return setProjects([]);
    api(`/sites/${f.site_id}/projects`).then((list) => {
      setProjects(list || []);
      if (list?.length === 1) set("project_id", list[0].id);
    }).catch(() => setProjects([]));
  }, [f.site_id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save() {
    if (!f.site_id) return setError("Choose the site.");
    if (!f.element.trim()) return setError("What was sampled?");
    setBusy(true); setError(null);
    try {
      await api("/quality/tests", { method: "POST", body: f });
      onSaved();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <div style={box}>
      <div style={{ display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))" }}>
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
        <label style={{ fontSize: 13 }}>Test
          <select value={f.kind} onChange={(e) => set("kind", e.target.value)}
                  style={inputStyle}>
            {KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Sampled on
          <input type="date" value={f.sampled_on}
                 onChange={(e) => set("sampled_on", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Pour / batch ref
          <input value={f.pour_ref} placeholder="POUR-014"
                 onChange={(e) => set("pour_ref", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Grade / mix
          <input value={f.grade} placeholder="C30/20"
                 onChange={(e) => set("grade", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Quantity represented
          <input value={f.quantity} placeholder="18 m3"
                 onChange={(e) => set("quantity", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Required value
          <input value={f.required_value} placeholder="30"
                 onChange={(e) => set("required_value", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Unit
          <input value={f.unit}
                 onChange={(e) => set("unit", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Lab
          <input value={f.lab_name}
                 onChange={(e) => set("lab_name", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Witnessed by
          <input value={f.witnessed_by} placeholder="Consultant"
                 onChange={(e) => set("witnessed_by", e.target.value)}
                 style={inputStyle} />
        </label>
      </div>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        Element sampled
        <input value={f.element}
               placeholder="Villa 3 ground floor slab"
               onChange={(e) => set("element", e.target.value)}
               style={inputStyle} />
      </label>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        Specification reference
        <input value={f.spec_reference} placeholder="SPEC 03300 cl.4.2"
               onChange={(e) => set("spec_reference", e.target.value)}
               style={inputStyle} />
      </label>
      <p style={{ fontSize: 12, color: "#5a6b78", margin: "8px 0 0" }}>
        A cube is expected to have its 28-day result; the register flags any
        sample whose result never came back. Passed tests can be pulled
        straight into the project's handover pack.
      </p>
      <Err>{error}</Err>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Saving…" : "Record the sample"}</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}
