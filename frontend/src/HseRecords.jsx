import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { BTN, buttonStyle, ghostButton, inputStyle, td, th } from "./ui.jsx";

// The records an HSE officer already keeps on the bigger sites: toolbox
// talks, inductions, training and competency, PPE. Registers, not workflows —
// the officer runs the process, this holds the evidence.

const TRAINING_CATEGORIES = [
  ["PLANT", "Plant / equipment operator"],
  ["HEIGHT", "Working at height"],
  ["CONFINED", "Confined space"],
  ["LIFTING", "Lifting / rigging"],
  ["ELECTRICAL", "Electrical"],
  ["HOT_WORK", "Hot work"],
  ["FIRST_AID", "First aid"],
  ["SCAFFOLD", "Scaffolding"],
  ["DIVING", "Diving / marine"],
  ["GENERAL", "General safety"],
];

const box = { background: "var(--sand,#f7f4ee)", padding: 14,
              borderRadius: 8, marginBottom: 14 };

function Err({ children }) {
  if (!children) return null;
  return <p style={{ color: "#a3271b", fontSize: 13 }}>{children}</p>;
}

// ------------------------------------------------------------ toolbox talks
export function ToolboxTab({ me, sites, siteFilter }) {
  const [rows, setRows] = useState([]);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);

  const load = useCallback(() => {
    api(`/hse/toolbox-talks${siteFilter ? `?site=${siteFilter}` : ""}`)
      .then(setRows).catch((e) => setError(e.message));
  }, [siteFilter]);
  useEffect(load, [load]);

  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <button onClick={() => setAdding(true)} style={BTN.primary}>
          Record a toolbox talk
        </button>
      </div>
      <Err>{error}</Err>
      {adding && (
        <TalkForm sites={sites} siteFilter={siteFilter}
                  onClose={() => setAdding(false)}
                  onSaved={() => { setAdding(false); load(); }} />
      )}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={{ ...th, width: 120 }}>Ref</th>
          <th style={{ ...th, width: 130 }}>When</th>
          <th style={{ ...th, width: 60 }}>Site</th>
          <th style={th}>Topic</th>
          <th style={{ ...th, width: 90 }}>Attended</th>
          <th style={{ ...th, width: 150 }}>Given by</th>
        </tr></thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={6} style={{ ...td, color: "#8a97a1" }}>
              No talks recorded yet.</td></tr>
          )}
          {rows.map((r) => (
            <tr key={r.id} onClick={() => setOpen(open === r.id ? null : r.id)}
                style={{ cursor: "pointer" }}>
              <td style={{ ...td, fontFamily: "var(--font-mono, monospace)",
                           fontWeight: 600 }}>{r.ref}</td>
              <td style={td}>
                {new Date(r.delivered_at).toLocaleString([], {
                  dateStyle: "short", timeStyle: "short" })}</td>
              <td style={td}>{r.site_code}</td>
              <td style={td}>
                {r.topic}
                {open === r.id && r.attendees.length > 0 && (
                  <div style={{ fontSize: 12, color: "#5a6b78",
                                marginTop: 6 }}>
                    {r.attendees.map((a) => a.display_name).join(", ")}
                  </div>
                )}
              </td>
              <td style={td}>{r.attendee_count}</td>
              <td style={td}>{r.presenter_name || r.delivered_by_name}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function TalkForm({ sites, siteFilter, onClose, onSaved }) {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 16);
  const [f, setF] = useState({
    site_id: siteFilter || "", topic: "", delivered_at: local,
    duration_min: 15, location: "", key_points: "", presenter_name: "",
  });
  const [present, setPresent] = useState([]);
  const [picked, setPicked] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));

  // The attendance register is already the list of men who were there.
  useEffect(() => {
    if (!f.site_id) return setPresent([]);
    const day = f.delivered_at.slice(0, 10);
    api(`/hse/present?site=${f.site_id}&day=${day}`)
      .then((list) => { setPresent(list); setPicked(new Set(
        list.map((p) => p.employee_id))); })
      .catch(() => setPresent([]));
  }, [f.site_id, f.delivered_at.slice(0, 10)]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (id) => setPicked((s) => {
    const next = new Set(s);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  async function save() {
    if (!f.site_id) return setError("Choose the site.");
    if (!f.topic.trim()) return setError("What was the talk about?");
    setBusy(true); setError(null);
    try {
      await api("/hse/toolbox-talks", {
        method: "POST",
        body: { ...f,
                delivered_at: new Date(f.delivered_at).toISOString(),
                attendees: [...picked].map((id) => ({ employee_id: id })) },
      });
      onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
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
        <label style={{ fontSize: 13 }}>When
          <input type="datetime-local" value={f.delivered_at}
                 onChange={(e) => set("delivered_at", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Minutes
          <input type="number" min="1" value={f.duration_min}
                 onChange={(e) => set("duration_min", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Where
          <input value={f.location}
                 onChange={(e) => set("location", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Given by (if not you)
          <input value={f.presenter_name} placeholder="HSE officer's name"
                 onChange={(e) => set("presenter_name", e.target.value)}
                 style={inputStyle} />
        </label>
      </div>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>Topic
        <input value={f.topic}
               onChange={(e) => set("topic", e.target.value)}
               placeholder="Working at height — harness inspection"
               style={inputStyle} />
      </label>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        Key points
        <textarea value={f.key_points} rows={2}
                  onChange={(e) => set("key_points", e.target.value)}
                  style={{ ...inputStyle, resize: "vertical" }} />
      </label>

      <div style={{ marginTop: 12 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10,
                      flexWrap: "wrap" }}>
          <strong style={{ fontSize: 13 }}>
            Who attended ({picked.size} of {present.length})</strong>
          <span style={{ fontSize: 12, color: "#5a6b78" }}>
            everyone marked present that day, already ticked — untick anyone
            who wasn't there
          </span>
          {present.length > 0 && (
            <button onClick={() => setPicked(picked.size === present.length
              ? new Set()
              : new Set(present.map((p) => p.employee_id)))}
                    style={{ ...ghostButton, padding: "3px 10px",
                             fontSize: 12 }}>
              {picked.size === present.length ? "Untick all" : "Tick all"}
            </button>
          )}
        </div>
        {present.length === 0 ? (
          <p style={{ fontSize: 12.5, color: "#8a97a1", margin: "6px 0 0" }}>
            Nobody is marked present at that site on that date — mark the
            attendance register first, or add names by hand later.
          </p>
        ) : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6,
                        marginTop: 8, maxHeight: 200, overflowY: "auto" }}>
            {present.map((p) => (
              <label key={p.employee_id}
                     style={{ display: "flex", gap: 5, alignItems: "center",
                              fontSize: 12.5, padding: "3px 8px",
                              borderRadius: 6, cursor: "pointer",
                              background: picked.has(p.employee_id)
                                ? "#e7f2ea" : "var(--paper)",
                              border: "1px solid var(--line)" }}>
                <input type="checkbox" checked={picked.has(p.employee_id)}
                       onChange={() => toggle(p.employee_id)} />
                {p.full_name}
              </label>
            ))}
          </div>
        )}
      </div>

      <Err>{error}</Err>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Saving…" : "Record the talk"}</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}

// --------------------------------------------------------------- competency
export function TrainingTab({ siteFilter }) {
  const [rows, setRows] = useState([]);
  const [adding, setAdding] = useState(false);
  const [expiringOnly, setExpiringOnly] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api(`/hse/training${expiringOnly ? "?expiring=60" : ""}`)
      .then(setRows).catch((e) => setError(e.message));
  }, [expiringOnly]);
  useEffect(load, [load]);

  return (
    <>
      <div style={{ display: "flex", gap: 12, alignItems: "center",
                    marginBottom: 12, flexWrap: "wrap" }}>
        <button onClick={() => setAdding(true)} style={BTN.primary}>
          Record training
        </button>
        <label style={{ fontSize: 12.5, color: "#5a6b78", display: "flex",
                        gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={expiringOnly}
                 onChange={(e) => setExpiringOnly(e.target.checked)} />
          Expiring within 60 days
        </label>
      </div>
      <Err>{error}</Err>
      {adding && (
        <TrainingForm siteFilter={siteFilter}
                      onClose={() => setAdding(false)}
                      onSaved={() => { setAdding(false); load(); }} />
      )}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={{ ...th, width: 90 }}>Emp no</th>
          <th style={{ ...th, width: 180 }}>Worker</th>
          <th style={{ ...th, width: 170 }}>Category</th>
          <th style={th}>Training</th>
          <th style={{ ...th, width: 100 }}>Expires</th>
        </tr></thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={5} style={{ ...td, color: "#8a97a1" }}>
              {expiringOnly ? "Nothing expiring in the next 60 days."
                            : "No training recorded yet."}</td></tr>
          )}
          {rows.map((r) => {
            const d = r.days_to_expiry;
            const tone = d == null ? undefined
              : d < 0 ? "#a3271b" : d <= 30 ? "#8a5200" : undefined;
            return (
              <tr key={r.id}>
                <td style={{ ...td,
                             fontFamily: "var(--font-mono, monospace)" }}>
                  {r.emp_no}</td>
                <td style={td}>{r.employee_name}</td>
                <td style={td}>{r.category_display}</td>
                <td style={td}>
                  {r.title}
                  {r.issuer && (
                    <span style={{ color: "#5a6b78" }}> · {r.issuer}</span>
                  )}
                </td>
                <td style={{ ...td, color: tone,
                             fontWeight: tone ? 700 : 400 }}>
                  {r.expires_on || "—"}
                  {d != null && d < 0 && " (expired)"}
                  {d != null && d >= 0 && d <= 30 && ` (${d}d)`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}

function TrainingForm({ siteFilter, onClose, onSaved }) {
  const [f, setF] = useState({ employee_id: "", category: "PLANT",
                               title: "", issuer: "", reference: "",
                               issued_on: "", expires_on: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function save() {
    if (!f.employee_id) return setError("Choose the worker.");
    if (!f.title.trim()) return setError("What training was it?");
    setBusy(true); setError(null);
    try {
      await api("/hse/training", { method: "POST", body: f });
      onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={box}>
      <div style={{ display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))" }}>
        <WorkerPicker siteFilter={siteFilter} value={f.employee_id}
                      onPick={(id) => setF({ ...f, employee_id: id })} />
        <label style={{ fontSize: 13 }}>Category
          <select value={f.category}
                  onChange={(e) => setF({ ...f, category: e.target.value })}
                  style={inputStyle}>
            {TRAINING_CATEGORIES.map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Issued
          <input type="date" value={f.issued_on}
                 onChange={(e) => setF({ ...f, issued_on: e.target.value })}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Expires
          <input type="date" value={f.expires_on}
                 onChange={(e) => setF({ ...f, expires_on: e.target.value })}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Issued by
          <input value={f.issuer} placeholder="Training body"
                 onChange={(e) => setF({ ...f, issuer: e.target.value })}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Certificate no.
          <input value={f.reference}
                 onChange={(e) => setF({ ...f, reference: e.target.value })}
                 style={inputStyle} />
        </label>
      </div>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        What training
        <input value={f.title} placeholder="Excavator operator — 20t tracked"
               onChange={(e) => setF({ ...f, title: e.target.value })}
               style={inputStyle} />
      </label>
      <p style={{ fontSize: 12, color: "#5a6b78", margin: "8px 0 0" }}>
        With an expiry date set, the PM and HR are reminded at 60, 30 and 7
        days, and again once it lapses.
      </p>
      <Err>{error}</Err>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Saving…" : "Record"}</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}

// --------------------------------------------------- inductions + PPE
export function WorkerRecordsTab({ sites, siteFilter }) {
  const [employeeId, setEmployeeId] = useState("");
  const [inductions, setInductions] = useState([]);
  const [ppe, setPpe] = useState([]);
  const [mode, setMode] = useState(null);       // "induction" | "ppe"
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    if (!employeeId) { setInductions([]); setPpe([]); return; }
    api(`/hse/inductions?employee=${employeeId}`).then(setInductions)
      .catch(() => setInductions([]));
    api(`/hse/ppe?employee=${employeeId}`).then(setPpe)
      .catch(() => setPpe([]));
  }, [employeeId]);
  useEffect(load, [load]);

  return (
    <>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end",
                    flexWrap: "wrap", marginBottom: 14 }}>
        <div style={{ minWidth: 260 }}>
          <WorkerPicker siteFilter={siteFilter} value={employeeId}
                        label="Worker" onPick={setEmployeeId} />
        </div>
        {employeeId && (
          <>
            <button onClick={() => setMode("induction")} style={BTN.primary}>
              Record induction</button>
            <button onClick={() => setMode("ppe")} style={ghostButton}>
              Issue PPE</button>
          </>
        )}
      </div>
      <Err>{error}</Err>

      {mode && (
        <WorkerRecordForm mode={mode} employeeId={employeeId} sites={sites}
                          siteFilter={siteFilter}
                          onClose={() => setMode(null)}
                          onSaved={() => { setMode(null); load(); }}
                          onError={setError} />
      )}

      {!employeeId && (
        <p style={{ fontSize: 13, color: "#8a97a1" }}>
          Pick a worker to see what they have been inducted on and issued.</p>
      )}

      {employeeId && (
        <div style={{ display: "grid", gap: 20,
                      gridTemplateColumns: "repeat(auto-fit,minmax(320px,1fr))" }}>
          <div>
            <h3 style={{ fontSize: 14, margin: "0 0 6px" }}>Inductions</h3>
            {inductions.length === 0
              ? <p style={{ fontSize: 13, color: "#8a97a1" }}>
                  None recorded.</p>
              : (
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <tbody>
                    {inductions.map((i) => (
                      <tr key={i.id}>
                        <td style={{ ...td, width: 100 }}>{i.inducted_on}</td>
                        <td style={td}>{i.site_code}
                          {i.topics && (
                            <div style={{ fontSize: 12, color: "#5a6b78" }}>
                              {i.topics}</div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
          </div>
          <div>
            <h3 style={{ fontSize: 14, margin: "0 0 6px" }}>PPE issued</h3>
            {ppe.length === 0
              ? <p style={{ fontSize: 13, color: "#8a97a1" }}>
                  None recorded.</p>
              : (
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <tbody>
                    {ppe.map((p) => (
                      <tr key={p.id}>
                        <td style={{ ...td, width: 100 }}>{p.issued_on}</td>
                        <td style={td}>
                          {p.item}{p.qty > 1 && ` × ${p.qty}`}
                          {p.replacement && (
                            <span style={{ color: "#5a6b78" }}>
                              {" "}· replacement</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
          </div>
        </div>
      )}
    </>
  );
}

function WorkerRecordForm({ mode, employeeId, sites, siteFilter, onClose,
                            onSaved, onError }) {
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({
    site_id: siteFilter || "", inducted_on: today, topics: "",
    item: "", qty: 1, issued_on: today, replacement: false, notes: "",
  });
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));

  async function save() {
    if (!f.site_id) return onError("Choose the site.");
    setBusy(true); onError(null);
    try {
      await api(mode === "induction" ? "/hse/inductions" : "/hse/ppe", {
        method: "POST", body: { ...f, employee_id: employeeId },
      });
      onSaved();
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
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
        {mode === "induction" ? (
          <label style={{ fontSize: 13 }}>Inducted on
            <input type="date" value={f.inducted_on}
                   onChange={(e) => set("inducted_on", e.target.value)}
                   style={inputStyle} />
          </label>
        ) : (
          <>
            <label style={{ fontSize: 13 }}>Item
              <input value={f.item} placeholder="Safety harness"
                     onChange={(e) => set("item", e.target.value)}
                     style={inputStyle} />
            </label>
            <label style={{ fontSize: 13 }}>Qty
              <input type="number" min="1" value={f.qty}
                     onChange={(e) => set("qty", e.target.value)}
                     style={inputStyle} />
            </label>
            <label style={{ fontSize: 13 }}>Issued on
              <input type="date" value={f.issued_on}
                     onChange={(e) => set("issued_on", e.target.value)}
                     style={inputStyle} />
            </label>
          </>
        )}
      </div>
      {mode === "induction" ? (
        <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
          Topics covered
          <textarea value={f.topics} rows={2}
                    onChange={(e) => set("topics", e.target.value)}
                    placeholder="Site rules, PPE, emergency muster, permits"
                    style={{ ...inputStyle, resize: "vertical" }} />
        </label>
      ) : (
        <label style={{ fontSize: 13, display: "flex", gap: 8,
                        alignItems: "center", marginTop: 10 }}>
          <input type="checkbox" checked={f.replacement}
                 onChange={(e) => set("replacement", e.target.checked)} />
          Replacing something worn out or lost
        </label>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Saving…" : "Record"}</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}

// A worker picker that searches rather than rendering 600 options.
function WorkerPicker({ siteFilter, value, onPick, label = "Worker" }) {
  const [all, setAll] = useState([]);
  const [q, setQ] = useState("");

  useEffect(() => {
    api(`/employees${siteFilter ? `?site=${siteFilter}` : ""}`)
      .then((list) => setAll(Array.isArray(list) ? list
        : (list.results || []))).catch(() => setAll([]));
  }, [siteFilter]);

  const term = q.trim().toLowerCase();
  const shown = term
    ? all.filter((e) => `${e.emp_no} ${e.full_name}`.toLowerCase()
        .includes(term)).slice(0, 40)
    : all.slice(0, 40);

  return (
    <label style={{ fontSize: 13, display: "block" }}>{label}
      <input value={q} onChange={(e) => setQ(e.target.value)}
             placeholder="Search name or number"
             style={{ ...inputStyle, marginBottom: 4 }} />
      <select value={value} onChange={(e) => onPick(e.target.value)}
              style={inputStyle} size={term ? Math.min(shown.length + 1, 6) : 1}>
        <option value="">— choose —</option>
        {shown.map((e) => (
          <option key={e.id} value={e.id}>{e.emp_no} — {e.full_name}</option>
        ))}
      </select>
    </label>
  );
}
