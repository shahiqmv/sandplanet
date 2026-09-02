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
// What staff may set. Submitted / accepted / returned are what HAPPENED to a
// document, recorded through a transmittal — not opinions to be typed in
// (owner 2026-09-01).
const HAND_STATUSES = [["REQUIRED", "Required"],
                       ["NOT_APPLICABLE", "Not applicable"]];
const STATUS_CHIP = {
  REQUIRED: ["Required", "#5a6b78", "#eef2f5"],
  SUBMITTED: ["With client", "#8a6d00", "#fff7e0"],
  ACCEPTED: ["Accepted", "#1a7f37", "#e8f5ec"],
  RETURNED: ["Returned", "#a3271b", "#fbeae8"],
  NOT_APPLICABLE: ["N/A", "#8a94a0", "#f4f6f8"],
};
// A transmittal's own states. CLOSED means every document was ANSWERED —
// not that every answer was yes.
const TRANSMITTAL_CHIP = {
  DRAFT: ["Draft", "#5a6b78", "#eef2f5"],
  ISSUED: ["With client", "#8a6d00", "#fff7e0"],
  CLOSED: ["Answered", "#1a7f37", "#e8f5ec"],
};
const RESULTS = [["APPROVED", "Approved"],
                 ["APPROVED_WITH_COMMENTS", "Approved with comments"],
                 ["REJECTED", "Rejected — resubmit"]];
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

function Chip({ status, map }) {
  const [label, fg, bg] = (map || STATUS_CHIP)[status]
    || [status, "#5a6b78", "#eee"];
  return (
    <span style={{ background: bg, color: fg, fontSize: 11.5,
                   fontWeight: 700, padding: "2px 8px", borderRadius: 999,
                   whiteSpace: "nowrap" }}>{label}</span>
  );
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
            {c.provided} of {c.required} submitted
            {" · "}<strong>{c.accepted ?? 0} accepted</strong>
            {c.returned > 0 && (
              <strong style={{ color: "#a3271b" }}>
                {" · "}{c.returned} returned</strong>
            )}
          </div>
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
          ["transmittals", `Submissions (${(dossier.transmittals || []).length})`],
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
      {tab === "transmittals" && (
        <TransmittalTab project={project} me={me} dossier={dossier}
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
          && i.status !== "RETURNED").length;
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
                    <td style={{ ...td, width: 200 }}>
                      <div style={{ display: "flex", gap: 8,
                                    alignItems: "center" }}>
                        <Chip status={i.status} />
                        {i.revision > 0 && (
                          <span style={{ fontSize: 11.5, color: "#5a6b78" }}>
                            Rev {i.revision}</span>
                        )}
                        {/* Ours to set while the document is with us. A
                            returned one is back in our hands; a submitted or
                            accepted one is not. */}
                        {!["SUBMITTED", "ACCEPTED"].includes(i.status) && (
                          <select value={i.status}
                                  onChange={(e) => setStatus(i, e.target.value)}
                                  style={{ ...inputStyle, padding: "2px 4px",
                                           fontSize: 11.5, width: 108 }}>
                            {HAND_STATUSES.map(([v, l]) => (
                              <option key={v} value={v}>{l}</option>
                            ))}
                          </select>
                        )}
                      </div>
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

// The submission log. A document is provided when it goes to the Engineer
// under a reference, on a date, with a review period running — not when
// somebody ticks it (owner 2026-09-01).
function TransmittalTab({ project, me, dossier, onChanged, onError }) {
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(null);
  const [drafting, setDrafting] = useState(false);
  const canIssue = CAN_CLOSE.includes(me.role);

  const load = useCallback(() => {
    api(`/projects/${project.id}/handover/transmittals`)
      .then(setRows).catch(() => setRows([]));
  }, [project.id]);
  useEffect(load, [load]);

  function refresh() { load(); onChanged(); }

  return (
    <>
      <div style={{ display: "flex", gap: 10, marginBottom: 12,
                    alignItems: "center", flexWrap: "wrap" }}>
        <button onClick={() => setDrafting(true)} style={BTN.primary}>
          New transmittal</button>
        <span style={{ fontSize: 12.5, color: "#5a6b78" }}>
          Documents go to the client in numbered batches. The review clock
          starts when one is issued.
        </span>
      </div>

      {drafting && (
        <DraftTransmittal project={project} onClose={() => setDrafting(false)}
                          onSaved={(t) => { setDrafting(false); refresh();
                                            setOpen(t.id); }}
                          onError={onError} />
      )}

      {rows.length === 0 && !drafting && (
        <p style={{ fontSize: 13, color: "#5a6b78" }}>
          Nothing submitted yet. Attach documents to the pack, then send them
          to the client on a transmittal.</p>
      )}

      {rows.map((r) => (
        <div key={r.id} style={{ ...box, marginBottom: 10 }}>
          <div style={{ display: "flex", gap: 12, alignItems: "center",
                        flexWrap: "wrap" }}>
            <strong style={{ fontFamily: "var(--font-mono, monospace)",
                             color: "var(--navy)" }}>{r.ref}</strong>
            <Chip status={r.status} map={TRANSMITTAL_CHIP} />
            <span style={{ fontSize: 12.5, color: "#5a6b78" }}>
              {r.answered} of {r.lines.length} answered
              {r.issued_on && ` · issued ${r.issued_on}`}
              {r.response_due_on && ` · due ${r.response_due_on}`}
            </span>
            {r.is_overdue && (
              <strong style={{ color: "#a3271b", fontSize: 12.5 }}>
                overdue</strong>
            )}
            <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
              {r.status !== "DRAFT" && (
                <a href={`/api/v1/handover/transmittals/${r.id}/transmittal.pdf`}
                   target="_blank" rel="noreferrer"
                   style={{ ...ghostButton, fontSize: 12,
                            padding: "3px 10px", textDecoration: "none",
                            color: "var(--navy)" }}>⬇ Transmittal</a>
              )}
              <button onClick={() => setOpen(open === r.id ? null : r.id)}
                      style={{ ...ghostButton, fontSize: 12,
                               padding: "3px 10px" }}>
                {open === r.id ? "close" : "open"}</button>
            </span>
          </div>
          {open === r.id && (
            <TransmittalDetail id={r.id} canIssue={canIssue}
                               onChanged={refresh} onError={onError} />
          )}
        </div>
      ))}
    </>
  );
}

function DraftTransmittal({ project, onClose, onSaved, onError }) {
  const [cands, setCands] = useState([]);
  const [picked, setPicked] = useState([]);
  const [f, setF] = useState({ addressed_to: "", organisation: "",
                               subject: "", covering_note: "",
                               response_days: 14 });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api(`/projects/${project.id}/handover/transmittals/candidates`)
      .then(setCands).catch(() => setCands([]));
  }, [project.id]);

  function toggle(id) {
    setPicked((p) => p.includes(id) ? p.filter((x) => x !== id) : [...p, id]);
  }

  async function save() {
    setBusy(true);
    try {
      const t = await api(`/projects/${project.id}/handover/transmittals`,
                          { method: "POST",
                            body: { ...f, item_ids: picked } });
      onSaved(t);
    } catch (e) { onError(e.message); } finally { setBusy(false); }
  }

  return (
    <div style={box}>
      <h3 style={{ margin: "0 0 8px", fontSize: 14 }}>New transmittal</h3>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                    marginBottom: 10 }}>
        <input placeholder="Addressed to (name)" value={f.addressed_to}
               onChange={(e) => setF({ ...f, addressed_to: e.target.value })}
               style={{ ...inputStyle, flex: "1 1 180px" }} />
        <input placeholder="Organisation" value={f.organisation}
               onChange={(e) => setF({ ...f, organisation: e.target.value })}
               style={{ ...inputStyle, flex: "1 1 180px" }} />
        <input type="number" min="1" value={f.response_days}
               onChange={(e) => setF({ ...f, response_days: e.target.value })}
               title="Review period in days"
               style={{ ...inputStyle, width: 90 }} />
      </div>
      <input placeholder="Subject" value={f.subject}
             onChange={(e) => setF({ ...f, subject: e.target.value })}
             style={{ ...inputStyle, width: "100%", marginBottom: 10 }} />

      <p style={{ fontSize: 12.5, color: "#5a6b78", margin: "0 0 6px" }}>
        Documents ready to send. Anything already out with the client is not
        offered; a returned document comes back round as the next revision.
      </p>
      <div style={{ maxHeight: 260, overflowY: "auto", marginBottom: 10 }}>
        {cands.length === 0 && (
          <p style={{ fontSize: 13, margin: 0 }}>
            Nothing ready — attach a file or pull in an approved record
            first.</p>
        )}
        {cands.map((c) => (
          <label key={c.id}
                 style={{ display: "flex", gap: 8, alignItems: "center",
                          fontSize: 13, padding: "3px 0" }}>
            <input type="checkbox" checked={picked.includes(c.id)}
                   onChange={() => toggle(c.id)} />
            <span>{c.title}
              {c.reference && (
                <span style={{ color: "#5a6b78" }}> · {c.reference}</span>
              )}
              {c.revision > 0 && (
                <strong style={{ color: "#8a6d00" }}> · Rev {c.revision}</strong>
              )}
            </span>
          </label>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={save} disabled={busy || picked.length === 0}
                style={BTN.primary}>
          Create with {picked.length} document{picked.length === 1 ? "" : "s"}
        </button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
  );
}

function TransmittalDetail({ id, canIssue, onChanged, onError }) {
  const [t, setT] = useState(null);
  const [responding, setResponding] = useState(null);

  const load = useCallback(() => {
    api(`/handover/transmittals/${id}`).then(setT).catch(() => setT(null));
  }, [id]);
  useEffect(load, [load]);

  async function issue() {
    try {
      await api(`/handover/transmittals/${id}/issue`,
                { method: "POST", body: {} });
      load(); onChanged();
    } catch (e) { onError(e.message); }
  }

  if (!t) return null;
  return (
    <div style={{ marginTop: 10, borderTop: "1px solid var(--line)",
                  paddingTop: 10 }}>
      {t.status === "DRAFT" && canIssue && (
        <button onClick={issue} style={{ ...BTN.primary, marginBottom: 10 }}>
          Issue to the client</button>
      )}
      {t.status === "DRAFT" && !canIssue && (
        <p style={{ fontSize: 12.5, color: "#5a6b78" }}>
          A PM, QS or Director issues a transmittal to the client.</p>
      )}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>
          <th style={th}>Document</th><th style={{ ...th, width: 60 }}>Rev</th>
          <th style={{ ...th, width: 210 }}>Client response</th>
          <th style={{ ...th, width: 90 }} />
        </tr></thead>
        <tbody>
          {t.lines.map((ln) => (
            <tr key={ln.id}>
              <td style={td}>{ln.title}
                {ln.reference && (
                  <span style={{ color: "#5a6b78" }}> · {ln.reference}</span>
                )}
              </td>
              <td style={td}>{ln.revision}</td>
              <td style={{ ...td, fontSize: 12.5 }}>
                {ln.result ? (
                  <>
                    <Chip status={ln.result === "REJECTED"
                      ? "RETURNED" : "ACCEPTED"} />
                    <div style={{ color: "#5a6b78", marginTop: 2 }}>
                      {RESULTS.find(([v]) => v === ln.result)?.[1]}
                      {ln.result_on && ` · ${ln.result_on}`}
                      {ln.reviewed_by && ` · ${ln.reviewed_by}`}
                    </div>
                    {ln.comments && (
                      <div style={{ color: "#5a6b78", marginTop: 2 }}>
                        {ln.comments}</div>
                    )}
                  </>
                ) : (
                  <span style={{ color: "#5a6b78" }}>awaiting the client</span>
                )}
              </td>
              <td style={td}>
                {!ln.result && t.status !== "DRAFT" && canIssue && (
                  <button onClick={() => setResponding(
                            responding === ln.id ? null : ln.id)}
                          style={{ ...ghostButton, fontSize: 12,
                                   padding: "2px 8px" }}>
                    record</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {responding && (
        <ResponseForm lineId={responding}
                      onClose={() => setResponding(null)}
                      onSaved={() => { setResponding(null); load();
                                       onChanged(); }}
                      onError={onError} />
      )}
    </div>
  );
}

function ResponseForm({ lineId, onClose, onSaved, onError }) {
  const [f, setF] = useState({ result: "APPROVED", result_on: "",
                               reviewed_by: "", position: "",
                               reply_ref: "", comments: "" });
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      await api(`/handover/transmittal-lines/${lineId}/response`,
                { method: "POST", body: f });
      onSaved();
    } catch (e) { onError(e.message); } finally { setBusy(false); }
  }

  return (
    <div style={{ ...box, marginTop: 10 }}>
      <p style={{ fontSize: 12.5, color: "#5a6b78", margin: "0 0 8px" }}>
        What the Engineer said. Recorded on their behalf — your name is kept
        against it alongside theirs.
      </p>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                    marginBottom: 8 }}>
        <select value={f.result}
                onChange={(e) => setF({ ...f, result: e.target.value })}
                style={{ ...inputStyle, flex: "1 1 200px" }}>
          {RESULTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <input type="date" value={f.result_on}
               onChange={(e) => setF({ ...f, result_on: e.target.value })}
               style={{ ...inputStyle, width: 150 }} />
        <input placeholder="Their reply ref" value={f.reply_ref}
               onChange={(e) => setF({ ...f, reply_ref: e.target.value })}
               style={{ ...inputStyle, flex: "1 1 140px" }} />
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                    marginBottom: 8 }}>
        <input placeholder="Reviewed by (their name)" value={f.reviewed_by}
               onChange={(e) => setF({ ...f, reviewed_by: e.target.value })}
               style={{ ...inputStyle, flex: "1 1 180px" }} />
        <input placeholder="Position" value={f.position}
               onChange={(e) => setF({ ...f, position: e.target.value })}
               style={{ ...inputStyle, flex: "1 1 160px" }} />
      </div>
      <textarea placeholder="Comments" value={f.comments}
                onChange={(e) => setF({ ...f, comments: e.target.value })}
                rows={2}
                style={{ ...inputStyle, width: "100%", marginBottom: 8 }} />
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={save} disabled={busy} style={BTN.primary}>
          Record</button>
        <button onClick={onClose} style={ghostButton}>Cancel</button>
      </div>
    </div>
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
