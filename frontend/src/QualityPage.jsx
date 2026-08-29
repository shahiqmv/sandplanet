import { Fragment, useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { BTN, buttonStyle, card, ghostButton, inputStyle, td, th } from "./ui.jsx";
import TestingTab from "./TestingTab.jsx";

// Quality. Non-conformance had nowhere to live and suppliers were never
// rated, so a supplier who kept causing failures carried no record of it.
//
// Corrective actions raised here go to the same register the safety module
// writes to — one open-actions list, whatever raised the item.

const CATEGORIES = [
  ["WORKMANSHIP", "Workmanship"], ["MATERIAL", "Material"],
  ["DOCUMENTATION", "Documentation"], ["PROCESS", "Process"],
  ["SUPPLIER", "Supplier / subcontractor"],
];
const SEVERITIES = [["MINOR", "Minor"], ["MAJOR", "Major"],
                    ["CRITICAL", "Critical"]];
const DISPOSITIONS = [
  ["REWORK", "Rework to specification"], ["REPAIR", "Repair"],
  ["USE_AS_IS", "Use as is (concession)"],
  ["REGRADE", "Re-grade / re-use elsewhere"], ["REJECT", "Reject / remove"],
];
const POINT_TYPES = [
  ["HOLD", "Hold — work stops until signed"],
  ["WITNESS", "Witness — invited to attend"],
  ["REVIEW", "Review — records reviewed after"],
  ["MONITOR", "Monitor — surveillance only"],
];
const PARTIES = [["US", "Us"], ["CONSULTANT", "Consultant"],
                 ["CLIENT", "Client"], ["THIRD_PARTY", "Third party"]];
const CAN_DISPOSE = ["PM", "DIRECTOR", "ADMIN", "QS"];

const SEV_TONE = {
  MINOR: { bg: "#eef4fb", fg: "#16527E" },
  MAJOR: { bg: "#f9efe2", fg: "#8a5200" },
  CRITICAL: { bg: "#a3271b", fg: "#fff" },
};
const BAND_TONE = {
  PREFERRED: { bg: "#e7f2ea", fg: "#166f30" },
  APPROVED: { bg: "#eef4fb", fg: "#16527E" },
  CONDITIONAL: { bg: "#f9efe2", fg: "#8a5200" },
  UNACCEPTABLE: { bg: "#f9e8e6", fg: "#a3271b" },
};
const box = { background: "var(--sand,#f7f4ee)", padding: 14,
              borderRadius: 8, marginBottom: 14 };

function Pill({ children, tone }) {
  return (
    <span style={{ display: "inline-block", padding: "2px 9px",
                   borderRadius: 999, fontSize: 11, fontWeight: 700,
                   whiteSpace: "nowrap", background: tone?.bg || "#eef1f4",
                   color: tone?.fg || "#4a5b68" }}>{children}</span>
  );
}

function Err({ children }) {
  if (!children) return null;
  return <p style={{ color: "#a3271b", fontSize: 13 }}>{children}</p>;
}

function Modal({ title, children, onClose }) {
  return (
    <div onClick={onClose}
         style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.35)",
                  display: "flex", alignItems: "center",
                  justifyContent: "center", zIndex: 50, padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ ...card, maxWidth: 780, width: "100%", maxHeight: "88vh",
                    overflow: "auto" }}>
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

export default function QualityPage({ me, sites, site }) {
  const [tab, setTab] = useState("ncrs");
  const [siteFilter, setSiteFilter] = useState(site?.id || "");

  return (
    <section>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap", marginBottom: 10 }}>
        <h2 style={{ margin: 0, color: "var(--navy)" }}>Quality</h2>
        <p style={{ margin: 0, fontSize: 13, color: "#5a6b78" }}>
          Non-conformance, inspection and test plans, and how our suppliers
          are performing.
        </p>
      </div>

      <div style={{ display: "flex", gap: 2, marginBottom: 12,
                    flexWrap: "wrap", alignItems: "flex-end",
                    borderBottom: "2px solid var(--line)" }}>
        {[["ncrs", "Non-conformance"], ["testing", "Testing"],
          ["itps", "Inspection & test plans"],
          ["suppliers", "Supplier performance"]].map(([key, label]) => (
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
        {!site && (sites || []).length > 1 && tab !== "suppliers" && (
          <select value={siteFilter}
                  onChange={(e) => setSiteFilter(e.target.value)}
                  style={{ ...inputStyle, width: "auto", marginLeft: "auto",
                           marginBottom: 5 }}>
            <option value="">All sites</option>
            {sites.map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}
          </select>
        )}
      </div>

      {tab === "ncrs" && (
        <NcrTab me={me} sites={sites} siteFilter={siteFilter} />
      )}
      {tab === "testing" && (
        <TestingTab me={me} sites={sites} siteFilter={siteFilter} />
      )}
      {tab === "itps" && <ItpTab sites={sites} siteFilter={siteFilter} />}
      {tab === "suppliers" && <SupplierTab me={me} />}
    </section>
  );
}

// ------------------------------------------------------------------- NCRs
function NcrTab({ me, sites, siteFilter }) {
  const [rows, setRows] = useState([]);
  const [openOnly, setOpenOnly] = useState(true);
  const [adding, setAdding] = useState(false);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    const q = [];
    if (openOnly) q.push("status=open");
    if (siteFilter) q.push(`site=${siteFilter}`);
    api(`/quality/ncrs${q.length ? `?${q.join("&")}` : ""}`)
      .then(setRows).catch((e) => setError(e.message));
  }, [openOnly, siteFilter]);
  useEffect(load, [load]);

  return (
    <>
      <div style={{ display: "flex", gap: 12, alignItems: "center",
                    marginBottom: 12, flexWrap: "wrap" }}>
        <button onClick={() => setAdding(true)} style={BTN.primary}>
          Raise a non-conformance</button>
        <label style={{ fontSize: 12.5, color: "#5a6b78", display: "flex",
                        gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={openOnly}
                 onChange={(e) => setOpenOnly(e.target.checked)} />
          Open only
        </label>
      </div>
      <Err>{error}</Err>
      {adding && (
        <NcrForm sites={sites} siteFilter={siteFilter}
                 onClose={() => setAdding(false)}
                 onSaved={(n) => { setAdding(false); load(); setDetail(n); }} />
      )}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={{ ...th, width: 120 }}>Ref</th>
          <th style={{ ...th, width: 95 }}>Raised</th>
          <th style={th}>What is wrong</th>
          <th style={{ ...th, width: 130 }}>Category</th>
          <th style={{ ...th, width: 85 }}>Severity</th>
          <th style={{ ...th, width: 150 }}>Disposition</th>
        </tr></thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={6} style={{ ...td, color: "#8a97a1" }}>
              {openOnly ? "Nothing open." : "None recorded."}</td></tr>
          )}
          {rows.map((r) => (
            <tr key={r.id} onClick={() => setDetail(r)}
                style={{ cursor: "pointer" }}>
              <td style={{ ...td, fontFamily: "var(--font-mono, monospace)",
                           fontWeight: 600 }}>{r.ref}</td>
              <td style={td}>{r.raised_on}</td>
              <td style={td}>
                {r.description.length > 80
                  ? `${r.description.slice(0, 80)}…` : r.description}
                {r.open_actions > 0 && (
                  <span style={{ color: "#8a5200", fontSize: 12 }}>
                    {" "}· {r.open_actions} action(s) open</span>
                )}
              </td>
              <td style={td}>{r.category_display}</td>
              <td style={td}>
                <Pill tone={SEV_TONE[r.severity]}>{r.severity}</Pill></td>
              <td style={td}>
                {r.disposition_display || (
                  <span style={{ color: "#8a5200" }}>not yet decided</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {detail && (
        <NcrDetail ncr={detail} me={me}
                   onClose={() => { setDetail(null); load(); }}
                   onChanged={(fresh) => { setDetail(fresh); load(); }} />
      )}
    </>
  );
}

function NcrForm({ sites, siteFilter, onClose, onSaved }) {
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ site_id: siteFilter || "",
                               category: "WORKMANSHIP", severity: "MINOR",
                               raised_on: today, location: "",
                               description: "", requirement: "",
                               supplier_id: "" });
  const [suppliers, setSuppliers] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));

  useEffect(() => {
    api("/suppliers").then((d) => setSuppliers(d.results || d || []))
      .catch(() => setSuppliers([]));
  }, []);

  async function save() {
    if (!f.site_id) return setError("Choose the site.");
    if (!f.description.trim()) return setError("Describe what is wrong.");
    if (!f.requirement.trim()) {
      return setError("Say what this fails to meet — the clause, drawing or "
        + "standard.");
    }
    setBusy(true); setError(null);
    try {
      onSaved(await api("/quality/ncrs", { method: "POST", body: f }));
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
        <label style={{ fontSize: 13 }}>Category
          <select value={f.category}
                  onChange={(e) => set("category", e.target.value)}
                  style={inputStyle}>
            {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Severity
          <select value={f.severity}
                  onChange={(e) => set("severity", e.target.value)}
                  style={inputStyle}>
            {SEVERITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Raised on
          <input type="date" value={f.raised_on}
                 onChange={(e) => set("raised_on", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Where
          <input value={f.location} placeholder="Villa 3, west wall"
                 onChange={(e) => set("location", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Supplier (if theirs)
          <select value={f.supplier_id}
                  onChange={(e) => set("supplier_id", e.target.value)}
                  style={inputStyle}>
            <option value="">— none —</option>
            {suppliers.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </label>
      </div>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        What is wrong
        <textarea value={f.description} rows={3}
                  onChange={(e) => set("description", e.target.value)}
                  style={{ ...inputStyle, resize: "vertical" }} />
      </label>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        What it fails to meet
        <input value={f.requirement}
               placeholder="SPEC 04200 cl.3.2 — max 5mm in 2.4m"
               onChange={(e) => set("requirement", e.target.value)}
               style={inputStyle} />
        <span style={{ fontSize: 12, color: "#5a6b78" }}>
          The clause, drawing or standard. Without it there is nothing to
          argue from.
        </span>
      </label>
      <Err>{error}</Err>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Raising…" : "Raise"}</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}

function NcrDetail({ ncr, me, onClose, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [disp, setDisp] = useState({ disposition: ncr.disposition || "REWORK",
                                     disposition_note: "" });
  const [addingAction, setAddingAction] = useState(false);
  const canDispose = CAN_DISPOSE.includes(me.role);
  const closed = ncr.status === "CLOSED";

  const refresh = () =>
    api(`/quality/ncrs/${ncr.ref}`).then(onChanged).catch(() => {});

  async function post(path, body) {
    setBusy(true); setError(null);
    try {
      onChanged(await api(`/quality/ncrs/${ncr.ref}${path}`,
                          { method: "POST", body: body || {} }));
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal title={`${ncr.ref} — ${ncr.category_display}`} onClose={onClose}>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <Pill tone={SEV_TONE[ncr.severity]}>{ncr.severity}</Pill>
        <Pill>{ncr.status.replace(/_/g, " ")}</Pill>
      </div>
      <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr",
                   gap: "6px 14px", fontSize: 13.5, margin: "0 0 16px" }}>
        <dt style={{ color: "#5a6b78" }}>Raised</dt>
        <dd style={{ margin: 0 }}>{ncr.raised_on} · {ncr.raised_by_name}</dd>
        <dt style={{ color: "#5a6b78" }}>Where</dt>
        <dd style={{ margin: 0 }}>
          {ncr.site_code}{ncr.location && ` · ${ncr.location}`}</dd>
        <dt style={{ color: "#5a6b78" }}>What is wrong</dt>
        <dd style={{ margin: 0, whiteSpace: "pre-wrap" }}>{ncr.description}</dd>
        <dt style={{ color: "#5a6b78" }}>Fails to meet</dt>
        <dd style={{ margin: 0 }}>{ncr.requirement}</dd>
        {ncr.supplier_name && (<>
          <dt style={{ color: "#5a6b78" }}>Supplier</dt>
          <dd style={{ margin: 0 }}>{ncr.supplier_name}</dd>
        </>)}
      </dl>

      <h3 style={{ fontSize: 14, margin: "16px 0 6px" }}>
        What happens to the work</h3>
      {ncr.disposition ? (
        <p style={{ fontSize: 13.5, margin: 0 }}>
          <strong>{ncr.disposition_display}</strong>
          {ncr.disposition_note && ` — ${ncr.disposition_note}`}
          <span style={{ color: "#5a6b78" }}>
            {" "}· decided by {ncr.disposition_by_name}</span>
        </p>
      ) : (
        <p style={{ fontSize: 13, color: "#8a5200", margin: 0 }}>
          Not decided yet. Nothing closes until it is.</p>
      )}
      {canDispose && !closed && (
        <div style={{ ...box, marginTop: 10 }}>
          <div style={{ display: "grid", gap: 10,
                        gridTemplateColumns: "1fr 2fr" }}>
            <label style={{ fontSize: 13 }}>Decision
              <select value={disp.disposition}
                      onChange={(e) => setDisp({ ...disp,
                                                 disposition: e.target.value })}
                      style={inputStyle}>
                {DISPOSITIONS.map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </select>
            </label>
            <label style={{ fontSize: 13 }}>Reason
              <input value={disp.disposition_note}
                     placeholder={disp.disposition === "USE_AS_IS"
                       ? "Required — why is this acceptable?" : "Optional"}
                     onChange={(e) => setDisp({ ...disp,
                       disposition_note: e.target.value })}
                     style={inputStyle} />
            </label>
          </div>
          <button onClick={() => post("/disposition", disp)} disabled={busy}
                  style={{ ...buttonStyle, marginTop: 10 }}>
            Record the decision</button>
        </div>
      )}

      <h3 style={{ fontSize: 14, margin: "18px 0 6px" }}>Corrective actions</h3>
      {(ncr.actions || []).length === 0 && (
        <p style={{ fontSize: 13, color: "#8a97a1", margin: "0 0 8px" }}>
          None raised yet.</p>
      )}
      {(ncr.actions || []).map((a) => (
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
      {!closed && (addingAction ? (
        <NcrActionForm ncrRef={ncr.ref}
                       onClose={() => setAddingAction(false)}
                       onSaved={() => { setAddingAction(false); refresh(); }} />
      ) : (
        <button onClick={() => setAddingAction(true)} style={ghostButton}>
          Raise a corrective action</button>
      ))}
      <p style={{ fontSize: 12, color: "#5a6b78", marginTop: 8 }}>
        These join the same open-actions list as safety — Safety → Corrective
        actions.
      </p>

      <Err>{error}</Err>
      {canDispose && !closed && (
        <div style={{ marginTop: 18, paddingTop: 14,
                      borderTop: "1px solid var(--line)" }}>
          <button onClick={() => post("/close", {
            note: window.prompt("How was it verified?") || "" })}
                  disabled={busy} style={BTN.navy}>Close this NCR</button>
          <span style={{ fontSize: 12, color: "#5a6b78", marginLeft: 10 }}>
            Needs a decision, and every action verified.
          </span>
        </div>
      )}
    </Modal>
  );
}

function NcrActionForm({ ncrRef, onClose, onSaved }) {
  const [people, setPeople] = useState([]);
  const [f, setF] = useState({ description: "", owner_id: "", due_date: "",
                               priority: "MEDIUM" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/directory").then(setPeople).catch(() => setPeople([]));
  }, []);

  async function save() {
    setBusy(true); setError(null);
    try {
      await api(`/quality/ncrs/${ncrRef}/actions`,
                { method: "POST", body: f });
      onSaved();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <div style={box}>
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
      </div>
      <Err>{error}</Err>
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>Raise</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}

// -------------------------------------------------------------------- ITPs
function ItpTab({ sites, siteFilter }) {
  const [rows, setRows] = useState([]);
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api(`/quality/itps?status=current${
      siteFilter ? `&site=${siteFilter}` : ""}`)
      .then(setRows).catch((e) => setError(e.message));
  }, [siteFilter]);
  useEffect(load, [load]);

  async function sign(itemId) {
    const result = window.confirm("Pass this point?\n\nOK = pass, "
      + "Cancel = record a failure") ? "PASS" : "FAIL";
    const location = window.prompt("Where? (villa / grid / element)") || "";
    try {
      await api(`/quality/itp-items/${itemId}/record`,
                { method: "POST", body: { result, location } });
      load();
    } catch (e) { setError(e.message); }
  }

  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <button onClick={() => setAdding(true)} style={BTN.primary}>
          New inspection & test plan</button>
      </div>
      <Err>{error}</Err>
      {adding && (
        <ItpForm sites={sites} siteFilter={siteFilter}
                 onClose={() => setAdding(false)}
                 onSaved={() => { setAdding(false); load(); }} />
      )}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={{ ...th, width: 120 }}>Ref</th>
          <th style={th}>Plan</th>
          <th style={{ ...th, width: 110 }}>Points</th>
          <th style={{ ...th, width: 160 }}>Hold points open</th>
        </tr></thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={4} style={{ ...td, color: "#8a97a1" }}>
              No plans recorded.</td></tr>
          )}
          {rows.map((r) => (
            <Fragment key={r.id}>
              <tr onClick={() => setOpen(open === r.id ? null : r.id)}
                  style={{ cursor: "pointer" }}>
                <td style={{ ...td, fontFamily: "var(--font-mono, monospace)",
                             fontWeight: 600 }}>{r.ref}</td>
                <td style={td}>
                  {r.title}
                  {r.discipline && (
                    <span style={{ color: "#5a6b78" }}> · {r.discipline}</span>
                  )}
                </td>
                <td style={td}>
                  {r.progress.recorded} of {r.progress.items}
                  {r.progress.failed > 0 && (
                    <strong style={{ color: "#a3271b" }}>
                      {" "}· {r.progress.failed} failed</strong>
                  )}
                </td>
                <td style={{ ...td,
                             color: r.progress.holds_outstanding
                               ? "#a3271b" : "#166f30",
                             fontWeight: 700 }}>
                  {r.progress.holds_outstanding || "none"}
                </td>
              </tr>
              {open === r.id && (
                <tr>
                  <td colSpan={4} style={{ ...td,
                                           background: "var(--sand,#f7f4ee)" }}>
                    <table style={{ width: "100%",
                                    borderCollapse: "collapse" }}>
                      <thead><tr>
                        <th style={th}>Activity</th>
                        <th style={{ ...th, width: 200 }}>Point</th>
                        <th style={{ ...th, width: 130 }}>By</th>
                        <th style={th}>Acceptance</th>
                        <th style={{ ...th, width: 190 }}>Records</th>
                      </tr></thead>
                      <tbody>
                        {r.items.map((it) => (
                          <tr key={it.id}>
                            <td style={td}>
                              {it.activity}
                              {it.reference && (
                                <div style={{ fontSize: 12,
                                              color: "#5a6b78" }}>
                                  {it.reference}</div>
                              )}
                            </td>
                            <td style={td}>
                              <Pill tone={it.point_type === "HOLD"
                                ? SEV_TONE.CRITICAL : undefined}>
                                {it.point_type}</Pill>
                            </td>
                            <td style={td}>{it.responsible}</td>
                            <td style={td}>{it.acceptance_criteria}</td>
                            <td style={td}>
                              {it.records.map((rec) => (
                                <div key={rec.id} style={{ fontSize: 12 }}>
                                  {rec.result === "PASS" ? "✓" : "✗"}{" "}
                                  {rec.inspected_on}
                                  {rec.location && ` · ${rec.location}`}
                                </div>
                              ))}
                              <button onClick={(e) => { e.stopPropagation();
                                                        sign(it.id); }}
                                      style={{ ...ghostButton, fontSize: 12,
                                               padding: "2px 8px",
                                               marginTop: 4 }}>
                                Record</button>
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

const EMPTY_POINT = { activity: "", reference: "", acceptance_criteria: "",
                      point_type: "REVIEW", responsible: "US",
                      frequency: "", record_required: "" };

function ItpForm({ sites, siteFilter, onClose, onSaved }) {
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ site_id: siteFilter || "", title: "",
                               discipline: "", prepared_on: today,
                               notes: "" });
  const [items, setItems] = useState([{ ...EMPTY_POINT }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  const setItem = (i, patch) => setItems((xs) =>
    xs.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  async function save() {
    if (!f.site_id) return setError("Choose the site.");
    if (!f.title.trim()) return setError("What is this plan for?");
    const clean = items.filter((x) => x.activity.trim());
    if (!clean.length) return setError("Add at least one inspection point.");
    setBusy(true); setError(null);
    try {
      await api("/quality/itps", { method: "POST",
                                   body: { ...f, items: clean } });
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
        <label style={{ fontSize: 13 }}>Title
          <input value={f.title} placeholder="Concrete works"
                 onChange={(e) => set("title", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Discipline
          <input value={f.discipline} placeholder="Civil"
                 onChange={(e) => set("discipline", e.target.value)}
                 style={inputStyle} />
        </label>
      </div>

      <p style={{ fontSize: 12.5, color: "#5a6b78", margin: "14px 0 6px" }}>
        A <strong>hold point</strong> stops the work until it is signed off. A
        witness point invites attendance but does not stop anything — that
        distinction is what makes the plan worth having.
      </p>
      {items.map((x, i) => (
        <div key={i} style={{ borderTop: "1px solid var(--line)",
                              paddingTop: 10, marginTop: 10 }}>
          <div style={{ display: "grid", gap: 8,
                        gridTemplateColumns:
                          "repeat(auto-fit,minmax(150px,1fr))" }}>
            <label style={{ fontSize: 12.5 }}>Activity
              <input value={x.activity}
                     onChange={(e) => setItem(i, { activity: e.target.value })}
                     style={inputStyle} />
            </label>
            <label style={{ fontSize: 12.5 }}>Point type
              <select value={x.point_type}
                      onChange={(e) => setItem(i, {
                        point_type: e.target.value })}
                      style={inputStyle}>
                {POINT_TYPES.map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </select>
            </label>
            <label style={{ fontSize: 12.5 }}>Carried out by
              <select value={x.responsible}
                      onChange={(e) => setItem(i, {
                        responsible: e.target.value })}
                      style={inputStyle}>
                {PARTIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <label style={{ fontSize: 12.5 }}>Reference
              <input value={x.reference} placeholder="SPEC 03200 cl.3.4"
                     onChange={(e) => setItem(i, { reference: e.target.value })}
                     style={inputStyle} />
            </label>
            <label style={{ fontSize: 12.5 }}>Frequency
              <input value={x.frequency} placeholder="Every pour"
                     onChange={(e) => setItem(i, { frequency: e.target.value })}
                     style={inputStyle} />
            </label>
          </div>
          <label style={{ fontSize: 12.5, display: "block", marginTop: 8 }}>
            Acceptance criteria
            <input value={x.acceptance_criteria}
                   onChange={(e) => setItem(i, {
                     acceptance_criteria: e.target.value })}
                   style={inputStyle} />
          </label>
          {items.length > 1 && (
            <button onClick={() => setItems((xs) =>
              xs.filter((_, j) => j !== i))}
                    style={{ ...ghostButton, marginTop: 8, fontSize: 12,
                             padding: "3px 10px" }}>Remove</button>
          )}
        </div>
      ))}
      <button onClick={() => setItems([...items, { ...EMPTY_POINT }])}
              style={{ ...ghostButton, marginTop: 10 }}>Add a point</button>
      <Err>{error}</Err>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Saving…" : "Record"}</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}

// --------------------------------------------------------------- suppliers
function SupplierTab({ me }) {
  const [rows, setRows] = useState([]);
  const [rating, setRating] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api("/quality/supplier-scorecards").then(setRows)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const canRate = ["PM", "DIRECTOR", "ADMIN", "QS", "HO_PURCHASING"]
    .includes(me.role);

  return (
    <>
      <Err>{error}</Err>
      <p style={{ fontSize: 12.5, color: "#5a6b78", margin: "0 0 12px" }}>
        The non-conformance counts are counted by the system, so a rating has
        evidence beside it rather than only an opinion.
      </p>
      {rating && (
        <EvaluationForm supplier={rating} onClose={() => setRating(null)}
                        onSaved={() => { setRating(null); load(); }} />
      )}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={th}>Supplier</th>
          <th style={{ ...th, width: 90 }}>Score</th>
          <th style={{ ...th, width: 130 }}>Rating</th>
          <th style={{ ...th, width: 110 }}>NCRs 12m</th>
          <th style={{ ...th, width: 100 }}>Open</th>
          <th style={{ ...th, width: 110 }} />
        </tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.supplier_id}>
              <td style={td}>{r.name}</td>
              <td style={td}>{r.latest_score || "—"}</td>
              <td style={td}>
                {r.band ? <Pill tone={BAND_TONE[r.band]}>{r.band}</Pill>
                        : <span style={{ color: "#8a97a1" }}>not rated</span>}
              </td>
              <td style={{ ...td,
                           color: r.ncrs_12m > 0 ? "#8a5200" : undefined }}>
                {r.ncrs_12m}</td>
              <td style={{ ...td,
                           color: r.ncrs_open > 0 ? "#a3271b" : undefined,
                           fontWeight: r.ncrs_open > 0 ? 700 : 400 }}>
                {r.ncrs_open}</td>
              <td style={td}>
                {canRate && (
                  <button onClick={() => setRating(r)} style={ghostButton}>
                    Rate</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function EvaluationForm({ supplier, onClose, onSaved }) {
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth() - 3, 1);
  const [f, setF] = useState({
    period_start: start.toISOString().slice(0, 10),
    period_end: today.toISOString().slice(0, 10),
    quality: 3, delivery: 3, price: 3, responsiveness: 3, documentation: 3,
    notes: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));

  async function save() {
    setBusy(true); setError(null);
    try {
      await api("/quality/supplier-evaluations", {
        method: "POST", body: { ...f, supplier_id: supplier.supplier_id },
      });
      onSaved();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  const avg = (["quality", "delivery", "price", "responsiveness",
                "documentation"].reduce((a, k) => a + Number(f[k]), 0) / 5)
    .toFixed(2);

  return (
    <div style={box}>
      <strong style={{ fontSize: 14 }}>Rating {supplier.name}</strong>
      <div style={{ display: "grid", gap: 10, marginTop: 10,
                    gridTemplateColumns: "repeat(auto-fit,minmax(140px,1fr))" }}>
        <label style={{ fontSize: 13 }}>Period from
          <input type="date" value={f.period_start}
                 onChange={(e) => set("period_start", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>to
          <input type="date" value={f.period_end}
                 onChange={(e) => set("period_end", e.target.value)}
                 style={inputStyle} />
        </label>
        {[["quality", "Quality"], ["delivery", "Delivery"],
          ["price", "Price"], ["responsiveness", "Responsiveness"],
          ["documentation", "Documentation"]].map(([k, l]) => (
          <label key={k} style={{ fontSize: 13 }}>{l}
            <select value={f[k]} onChange={(e) => set(k, +e.target.value)}
                    style={inputStyle}>
              {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        ))}
      </div>
      <p style={{ fontSize: 13, margin: "10px 0 0" }}>
        Average <strong>{avg}</strong></p>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>Notes
        <textarea value={f.notes} rows={2}
                  onChange={(e) => set("notes", e.target.value)}
                  style={{ ...inputStyle, resize: "vertical" }} />
      </label>
      <Err>{error}</Err>
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>Save</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}
