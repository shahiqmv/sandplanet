import { useCallback, useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { BTN, buttonStyle, ghostButton, inputStyle, td, th } from "./ui.jsx";

// Handover. The pack is opened WITH the project rather than at the end of it,
// and records the app already holds — approved inspection requests, approved
// submittals, test plans — are offered as candidates as they are produced.
// Handover then gets assembled by construction instead of reconstructed from
// memory in the last fortnight, which is when it is always reconstructed
// badly.

const SECTIONS = [
  ["AS_BUILT", "As-built drawings"],
  ["INSPECTION", "Inspection requests & checklists"],
  ["TEST", "Test & commissioning records"],
  ["SUBMITTAL", "Approved material submittals"],
  ["OM_MANUAL", "O&M manuals"],
  ["WARRANTY", "Warranties & guarantees"],
  ["CERTIFICATE", "Statutory & authority certificates"],
  ["TRAINING", "Client training records"],
  ["SPARES", "Spares & attic stock"],
  ["OTHER", "Other"],
];
const DISCIPLINES = [["GENERAL", "General"], ["CIVIL", "Civil / structural"],
                     ["MEP", "MEP"], ["FINISHES", "Finishes"],
                     ["EXTERNAL", "External works"]];
const STATUSES = [["REQUIRED", "Required"], ["PROVIDED", "Provided"],
                  ["ACCEPTED", "Accepted by client"],
                  ["REJECTED", "Returned"],
                  ["NOT_APPLICABLE", "Not applicable"]];
const SNAG_STATUSES = [["OPEN", "Open"], ["IN_PROGRESS", "In progress"],
                       ["FIXED", "Fixed — awaiting check"],
                       ["CLOSED", "Closed"],
                       ["REJECTED", "Not a defect"]];
const CAN_CLOSE = ["PM", "DIRECTOR", "ADMIN", "QS"];
const box = { background: "var(--sand,#f7f4ee)", padding: 14,
              borderRadius: 8, marginBottom: 14 };

function Err({ children }) {
  if (!children) return null;
  return <p style={{ color: "#a3271b", fontSize: 13 }}>{children}</p>;
}

function Bar({ pct }) {
  return (
    <div style={{ background: "#e3e9ee", borderRadius: 999, height: 8,
                  overflow: "hidden", minWidth: 80 }}>
      <div style={{ width: `${pct}%`, height: "100%",
                    background: pct >= 100 ? "#1a7f37" : "var(--sky)" }} />
    </div>
  );
}

export default function HandoverTab({ project, me }) {
  const [dossier, setDossier] = useState(null);
  const [missing, setMissing] = useState(false);
  const [tab, setTab] = useState("pack");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api(`/projects/${project.id}/handover`)
      .then((d) => { setDossier(d); setMissing(false); })
      .catch((e) => {
        if (String(e.message).includes("no-dossier")) setMissing(true);
        else setError(e.message);
      });
  }, [project.id]);
  useEffect(load, [load]);

  async function open() {
    setBusy(true);
    try {
      setDossier(await api(`/projects/${project.id}/handover`,
                           { method: "POST", body: {} }));
      setMissing(false);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  if (missing) {
    return (
      <section>
        <p style={{ fontSize: 13.5, maxWidth: "62ch" }}>
          No handover pack yet. Opening one now creates the standard checklist
          — as-builts, inspection requests by discipline, cube tests, MEP
          commissioning, O&amp;M manuals, warranties, certificates — and lets
          approved records be pulled in as they are produced, instead of
          hunting for them in the last fortnight.
        </p>
        <Err>{error}</Err>
        <button onClick={open} disabled={busy} style={BTN.primary}>
          {busy ? "Opening…" : "Open the handover pack"}</button>
      </section>
    );
  }
  if (!dossier) return <p style={{ fontSize: 13 }}>Loading…</p>;

  const c = dossier.completeness;
  return (
    <section>
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap",
                    alignItems: "center", marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 26, fontWeight: 700,
                        fontFamily: "var(--font-mono, monospace)",
                        color: "var(--navy)" }}>{c.pct}%</div>
          <div style={{ fontSize: 12, color: "#5a6b78" }}>
            {c.provided} of {c.required} provided</div>
        </div>
        <div style={{ flex: "1 1 220px", maxWidth: 320 }}>
          <Bar pct={c.pct} /></div>
        <div style={{ fontSize: 13, color: "#5a6b78" }}>
          {dossier.taking_over_on ? (
            <>Taken over <strong>{dossier.taking_over_on}</strong>
              {dossier.dlp_ends && (
                <> · defects liability ends <strong>{dossier.dlp_ends}</strong></>
              )}
            </>
          ) : "Not yet taken over"}
          <div>
            {dossier.snags.open} snag(s) open
            {dossier.snags.overdue > 0 && (
              <strong style={{ color: "#a3271b" }}>
                {" "}· {dossier.snags.overdue} overdue</strong>
            )}
          </div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 2, marginBottom: 12,
                    flexWrap: "wrap", alignItems: "flex-end",
                    borderBottom: "2px solid var(--line)" }}>
        {[["pack", `Pack (${c.required})`],
          ["snags", `Snags (${dossier.snags.open})`],
          ["milestones", "Taking over"]].map(([key, label]) => (
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
      </div>

      <Err>{error}</Err>
      {tab === "pack" && (
        <PackTab project={project} me={me} dossier={dossier}
                 onChanged={load} onError={setError} />
      )}
      {tab === "snags" && (
        <SnagTab project={project} me={me} onChanged={load}
                 onError={setError} />
      )}
      {tab === "milestones" && (
        <MilestoneTab project={project} me={me} dossier={dossier}
                      onChanged={load} onError={setError} />
      )}
    </section>
  );
}

function PackTab({ project, me, dossier, onChanged, onError }) {
  const [candidates, setCandidates] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [showCandidates, setShowCandidates] = useState(false);

  const loadCandidates = useCallback(() => {
    api(`/projects/${project.id}/handover/candidates`).then(setCandidates)
      .catch(() => setCandidates([]));
  }, [project.id]);
  useEffect(loadCandidates, [loadCandidates]);

  async function pull(c) {
    try {
      await api(`/projects/${project.id}/handover/items`,
                { method: "POST", body: { document_id: c.document_id,
                                          section: c.suggested_section } });
      loadCandidates();
      onChanged();
    } catch (e) { onError(e.message); }
  }

  async function setStatus(item, status) {
    try {
      await api(`/handover/items/${item.id}`,
                { method: "PATCH", body: { status } });
      onChanged();
    } catch (e) { onError(e.message); }
  }

  const bySection = {};
  for (const item of dossier.items) {
    (bySection[item.section] = bySection[item.section] || []).push(item);
  }

  return (
    <>
      <div style={{ display: "flex", gap: 10, marginBottom: 12,
                    flexWrap: "wrap" }}>
        <button onClick={() => setUploading(true)} style={BTN.primary}>
          Attach a document</button>
        <button onClick={() => setShowCandidates(!showCandidates)}
                style={ghostButton}>
          {candidates.length} record{candidates.length === 1 ? "" : "s"} ready
          to pull in
        </button>
      </div>

      {showCandidates && (
        <div style={box}>
          <p style={{ fontSize: 12.5, color: "#5a6b78", margin: "0 0 8px" }}>
            Approved on this project already. Pulling one in links it — the
            pack points at the record rather than holding a second copy.
          </p>
          {candidates.length === 0 && (
            <p style={{ fontSize: 13, margin: 0 }}>
              Nothing new. Approved inspection requests and submittals appear
              here as they are produced.</p>
          )}
          {candidates.map((c) => (
            <div key={c.document_id}
                 style={{ display: "flex", gap: 10, alignItems: "center",
                          padding: "4px 0", fontSize: 13 }}>
              <strong style={{ fontFamily: "var(--font-mono, monospace)",
                               minWidth: 130 }}>{c.ref}</strong>
              <span style={{ color: "#5a6b78", minWidth: 200 }}>
                {c.status.replace(/_/g, " ")} · {c.doc_date}</span>
              <button onClick={() => pull(c)}
                      style={{ ...ghostButton, fontSize: 12,
                               padding: "3px 10px" }}>
                Add to {c.suggested_section.replace(/_/g, " ").toLowerCase()}
              </button>
            </div>
          ))}
        </div>
      )}

      {uploading && (
        <UploadForm project={project} onClose={() => setUploading(false)}
                    onSaved={() => { setUploading(false); onChanged(); }}
                    onError={onError} />
      )}

      {SECTIONS.filter(([key]) => bySection[key]).map(([key, label]) => {
        const items = bySection[key];
        const done = items.filter((i) => i.status !== "REQUIRED"
          && i.status !== "REJECTED").length;
        return (
          <div key={key} style={{ marginBottom: 18 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10,
                          marginBottom: 4 }}>
              <h3 style={{ fontSize: 14, margin: 0 }}>{label}</h3>
              <span style={{ fontSize: 12, color: "#5a6b78" }}>
                {done} of {items.length}</span>
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <tbody>
                {items.map((i) => (
                  <tr key={i.id}>
                    <td style={{ ...td, width: 90, fontSize: 12,
                                 color: "#5a6b78" }}>{i.discipline}</td>
                    <td style={td}>
                      {i.title}
                      {i.reference && (
                        <span style={{ color: "#5a6b78" }}>
                          {" "}· {i.reference}</span>
                      )}
                      {i.document_ref && (
                        <span style={{ fontFamily:
                                       "var(--font-mono, monospace)",
                                       fontSize: 12, color: "#16527E" }}>
                          {" "}· {i.document_ref}</span>
                      )}
                      {i.file_url && (
                        <>
                          {" · "}
                          <a href={i.file_url} target="_blank"
                             rel="noreferrer"
                             style={{ fontSize: 12 }}>file</a>
                        </>
                      )}
                    </td>
                    <td style={{ ...td, width: 190 }}>
                      <select value={i.status}
                              onChange={(e) => setStatus(i, e.target.value)}
                              style={{ ...inputStyle, padding: "3px 6px",
                                       fontSize: 12.5 }}>
                        {STATUSES.map(([v, l]) => (
                          <option key={v} value={v}
                                  disabled={v === "ACCEPTED"
                                    && !CAN_CLOSE.includes(me.role)}>
                            {l}</option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </>
  );
}

function UploadForm({ project, onClose, onSaved, onError }) {
  const [f, setF] = useState({ title: "", section: "TEST",
                               discipline: "CIVIL", reference: "" });
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));

  async function save() {
    if (!f.title.trim()) return onError("What is this document?");
    if (!file) return onError("Choose a file.");
    setBusy(true); onError(null);
    try {
      const fd = new FormData();
      Object.entries(f).forEach(([k, v]) => fd.append(k, v));
      fd.append("file", file);
      await apiUpload(`/projects/${project.id}/handover/upload`, fd);
      onSaved();
    } catch (e) { onError(e.message); } finally { setBusy(false); }
  }

  return (
    <div style={box}>
      <p style={{ fontSize: 12.5, color: "#5a6b78", margin: "0 0 10px" }}>
        For the parts of the pack that arrive as paper — cube test reports,
        as-built drawings, O&amp;M manuals, warranties, authority
        certificates.
      </p>
      <div style={{ display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))" }}>
        <label style={{ fontSize: 13 }}>Section
          <select value={f.section}
                  onChange={(e) => set("section", e.target.value)}
                  style={inputStyle}>
            {SECTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Discipline
          <select value={f.discipline}
                  onChange={(e) => set("discipline", e.target.value)}
                  style={inputStyle}>
            {DISCIPLINES.map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Reference
          <input value={f.reference} placeholder="LAB-2291 / DWG-A-201 Rev C"
                 onChange={(e) => set("reference", e.target.value)}
                 style={inputStyle} />
        </label>
      </div>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        What it is
        <input value={f.title}
               placeholder="Cube test report — 28 day, pour 14"
               onChange={(e) => set("title", e.target.value)}
               style={inputStyle} />
      </label>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        File
        <input type="file" onChange={(e) => setFile(e.target.files[0])}
               style={{ ...inputStyle, padding: 6 }} />
      </label>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Attaching…" : "Attach"}</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}

function SnagTab({ project, me, onChanged, onError }) {
  const [rows, setRows] = useState([]);
  const [adding, setAdding] = useState(false);
  const [openOnly, setOpenOnly] = useState(true);

  const load = useCallback(() => {
    api(`/projects/${project.id}/handover/snags${
      openOnly ? "?status=open" : ""}`)
      .then(setRows).catch((e) => onError(e.message));
  }, [project.id, openOnly]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(load, [load]);

  async function setStatus(snag, status) {
    try {
      await api(`/handover/snags/${snag.id}`,
                { method: "PATCH", body: { status } });
      load();
      onChanged();
    } catch (e) { onError(e.message); }
  }

  return (
    <>
      <div style={{ display: "flex", gap: 12, alignItems: "center",
                    marginBottom: 12, flexWrap: "wrap" }}>
        <button onClick={() => setAdding(true)} style={BTN.primary}>
          Raise a snag</button>
        <label style={{ fontSize: 12.5, color: "#5a6b78", display: "flex",
                        gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={openOnly}
                 onChange={(e) => setOpenOnly(e.target.checked)} />
          Open only
        </label>
      </div>
      {adding && (
        <SnagForm project={project} onClose={() => setAdding(false)}
                  onSaved={() => { setAdding(false); load(); onChanged(); }}
                  onError={onError} />
      )}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={{ ...th, width: 100 }}>Ref</th>
          <th style={{ ...th, width: 160 }}>Where</th>
          <th style={th}>Defect</th>
          <th style={{ ...th, width: 100 }}>Due</th>
          <th style={{ ...th, width: 180 }}>Status</th>
        </tr></thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={5} style={{ ...td, color: "#8a97a1" }}>
              {openOnly ? "Nothing open." : "No snags."}</td></tr>
          )}
          {rows.map((s) => (
            <tr key={s.id}>
              <td style={{ ...td, fontFamily: "var(--font-mono, monospace)" }}>
                {s.ref_no}
                {s.in_dlp && (
                  <div style={{ fontSize: 11, color: "#8a5200" }}>DLP</div>
                )}
              </td>
              <td style={td}>{s.location}</td>
              <td style={td}>
                {s.description}
                <div style={{ fontSize: 12, color: "#5a6b78" }}>
                  {s.discipline}
                  {s.owner_name && ` · ${s.owner_name}`}
                  {s.owner_note && ` · ${s.owner_note}`}
                </div>
              </td>
              <td style={td}>{s.due_date || "—"}</td>
              <td style={td}>
                <select value={s.status}
                        onChange={(e) => setStatus(s, e.target.value)}
                        style={{ ...inputStyle, padding: "3px 6px",
                                 fontSize: 12.5 }}>
                  {SNAG_STATUSES.map(([v, l]) => (
                    <option key={v} value={v}
                            disabled={v === "CLOSED"
                              && !CAN_CLOSE.includes(me.role)}>{l}</option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function SnagForm({ project, onClose, onSaved, onError }) {
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ location: "", discipline: "FINISHES",
                               description: "", raised_on: today,
                               due_date: "", owner_note: "" });
  const [photo, setPhoto] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));

  async function save() {
    if (!f.location.trim()) return onError("Where is it?");
    if (!f.description.trim()) return onError("What is the defect?");
    setBusy(true); onError(null);
    try {
      const fd = new FormData();
      Object.entries(f).forEach(([k, v]) => fd.append(k, v));
      if (photo) fd.append("photo", photo);
      await apiUpload(`/projects/${project.id}/handover/snags`, fd);
      onSaved();
    } catch (e) { onError(e.message); } finally { setBusy(false); }
  }

  return (
    <div style={box}>
      <div style={{ display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))" }}>
        <label style={{ fontSize: 13 }}>Where
          <input value={f.location} placeholder="Villa 3 bathroom"
                 onChange={(e) => set("location", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Discipline
          <select value={f.discipline}
                  onChange={(e) => set("discipline", e.target.value)}
                  style={inputStyle}>
            {DISCIPLINES.map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Due
          <input type="date" value={f.due_date}
                 onChange={(e) => set("due_date", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Who fixes it
          <input value={f.owner_note} placeholder="Our foreman / ABC Sub"
                 onChange={(e) => set("owner_note", e.target.value)}
                 style={inputStyle} />
        </label>
      </div>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        The defect
        <textarea value={f.description} rows={2}
                  onChange={(e) => set("description", e.target.value)}
                  style={{ ...inputStyle, resize: "vertical" }} />
      </label>
      <label style={{ fontSize: 13, display: "block", marginTop: 10 }}>
        Photo
        <input type="file" accept="image/*"
               onChange={(e) => setPhoto(e.target.files[0])}
               style={{ ...inputStyle, padding: 6 }} />
      </label>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={save} disabled={busy} style={buttonStyle}>
          {busy ? "Saving…" : "Raise"}</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}

function MilestoneTab({ project, me, dossier, onChanged, onError }) {
  const [f, setF] = useState({
    target_date: dossier.target_date || "",
    taking_over_on: dossier.taking_over_on || "",
    taking_over_ref: dossier.taking_over_ref || "",
    making_good_on: dossier.making_good_on || "",
    making_good_ref: dossier.making_good_ref || "",
  });
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  const canClose = CAN_CLOSE.includes(me.role);

  async function save() {
    setBusy(true); onError(null);
    try {
      await api(`/projects/${project.id}/handover/milestones`,
                { method: "POST", body: f });
      onChanged();
    } catch (e) { onError(e.message); } finally { setBusy(false); }
  }

  return (
    <div style={{ maxWidth: 620 }}>
      <p style={{ fontSize: 13, color: "#5a6b78" }}>
        Recording taking-over starts the defects-liability clock
        {project.defects_liability_months
          ? ` (${project.defects_liability_months} months on this contract)`
          : " — no period is set on this project's contract terms"}.
      </p>
      <div style={{ display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))" }}>
        <label style={{ fontSize: 13 }}>Target handover
          <input type="date" value={f.target_date}
                 onChange={(e) => set("target_date", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Taken over on
          <input type="date" value={f.taking_over_on} disabled={!canClose}
                 onChange={(e) => set("taking_over_on", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Certificate ref
          <input value={f.taking_over_ref} disabled={!canClose}
                 onChange={(e) => set("taking_over_ref", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Making good on
          <input type="date" value={f.making_good_on} disabled={!canClose}
                 onChange={(e) => set("making_good_on", e.target.value)}
                 style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Making good ref
          <input value={f.making_good_ref} disabled={!canClose}
                 onChange={(e) => set("making_good_ref", e.target.value)}
                 style={inputStyle} />
        </label>
      </div>
      {dossier.dlp_ends && (
        <p style={{ fontSize: 13.5, marginTop: 12 }}>
          Defects liability ends <strong>{dossier.dlp_ends}</strong>.</p>
      )}
      {canClose && (
        <button onClick={save} disabled={busy}
                style={{ ...buttonStyle, marginTop: 12 }}>
          {busy ? "Saving…" : "Save"}</button>
      )}
    </div>
  );
}
