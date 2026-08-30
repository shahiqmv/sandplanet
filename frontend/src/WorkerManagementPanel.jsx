import { useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { shrinkPhoto } from "./imageResize.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";

// Worker photo: thumbnail + add/replace via the phone camera or camera
// roll (owner 2026-08-26 — photo identity, adopted from the SFR
// spreadsheet). accept="image/*" gives the Take Photo / Photo Library
// choice on mobile; shrinkPhoto keeps uploads small.
function WorkerPhoto({ worker, canManage, onSaved }) {
  const [busy, setBusy] = useState(false);
  const pick = async (file) => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("photo", await shrinkPhoto(file));
      await apiUpload(`/workers/${worker.id}/photo`, fd);
      onSaved?.();
    } catch { /* row reloads regardless */ }
    finally { setBusy(false); }
  };
  const img = worker.photo_url
    ? <img src={worker.photo_url} alt=""
           style={{ width: 40, height: 48, objectFit: "cover",
                    borderRadius: 5, border: "1px solid #dde5ea",
                    display: "block" }} />
    : <div style={{ width: 40, height: 48, borderRadius: 5,
                    border: "1px dashed #c8b98a", background: "#fdf6ec",
                    display: "grid", placeItems: "center", fontSize: 15,
                    color: "#8a6d00" }}>👤</div>;
  if (!canManage) return img;
  return (
    <label title={worker.photo_url ? "Replace photo" : "Add photo — camera or camera roll"}
           style={{ cursor: "pointer", opacity: busy ? 0.5 : 1,
                    display: "inline-block" }}>
      {img}
      <span style={{ fontSize: 9.5, color: "var(--sky, #1a6091)",
                     display: "block", textAlign: "center" }}>
        {busy ? "…" : worker.photo_url ? "replace" : "add"}</span>
      <input type="file" accept="image/*" style={{ display: "none" }}
             onChange={(e) => { pick(e.target.files[0]);
                                e.target.value = ""; }} />
    </label>
  );
}

const SITE_MANAGE = ["SITE_ADMIN", "SITE_ENGINEER", "PM", "DIRECTOR", "ADMIN"];
const KIND_LABEL = { ADD: "New hires", REMOVE: "Removals", TRANSFER: "Transfers" };
const STATUS_TONE = {
  SUBMITTED: "warn", PM_APPROVED: "warn", APPROVED: "ok",
  RETURNED: "alert", REJECTED: "alert", CANCELLED: "info",
};
const money = (v) => v == null ? "—"
  : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2 });

// Site worker management (site-worker-management tool): SA/SE submit BATCHES of
// add / remove / transfer for a site's DIRECT workforce; the PM approves (and
// the Director activates new hires) a whole batch at once.
export default function WorkerManagementPanel({ site, me }) {
  const [batches, setBatches] = useState(null);
  const [roster, setRoster] = useState(null);
  const [revisions, setRevisions] = useState(null);
  const [view, setView] = useState(null);   // 'add' | 'roster'
  const [revising, setRevising] = useState(null);  // worker being revised
  const [error, setError] = useState(null);
  const canManage = SITE_MANAGE.includes(me.role);

  function load() {
    api(`/worker-batches?site_id=${site.id}`).then(setBatches)
      .catch((e) => setError(e.message));
    api(`/sites/${site.id}/direct-workers`).then(setRoster).catch(() => {});
    api(`/salary-revisions?site_id=${site.id}`).then(setRevisions)
      .catch(() => {});
  }
  useEffect(load, [site.id]);

  const openRev = (revisions || []).filter((r) => r.is_open);
  const openRevIds = new Set(openRev.map((r) => r.employee_id));

  const open = (batches || []).filter((b) =>
    ["SUBMITTED", "PM_APPROVED", "RETURNED"].includes(b.status));
  const recent = (batches || []).filter((b) =>
    ["APPROVED", "REJECTED", "CANCELLED"].includes(b.status)).slice(0, 5);

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 4 }}>
        <h3 style={{ margin: 0, color: "var(--navy)" }}>
          Direct workers</h3>
        {canManage && (
          <div style={{ display: "flex", gap: 8 }}>
            <Btn variant="navy" onClick={() => setView("add")}>
              + New hires</Btn>
            <Btn variant="secondary" onClick={() => setView("roster")}>
              Remove / transfer</Btn>
          </div>
        )}
      </div>
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "0 0 8px" }}>
        Submitted as batches: new hires need PM then Director approval; removals
        & transfers need PM approval. Approve the whole batch at once.</p>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}

      {view === "add" && (
        <HiresForm site={site} onCancel={() => setView(null)}
                   onDone={() => { setView(null); load(); }} />
      )}
      {view === "roster" && (
        <RosterPicker site={site} onCancel={() => setView(null)}
                      onDone={() => { setView(null); load(); }} />
      )}
      {revising && (
        <ReviseForm site={site} worker={revising}
                    onCancel={() => setRevising(null)}
                    onDone={() => { setRevising(null); load(); }} />
      )}

      {openRev.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <h4 style={{ margin: "10px 0 6px", color: "var(--navy)" }}>
            Salary revisions — awaiting approval</h4>
          {openRev.map((r) => (
            <RevisionCard key={r.id} rev={r} me={me} onChanged={load} />
          ))}
        </div>
      )}

      {batches === null ? <p style={{ color: "var(--muted)" }}>Loading…</p> : (
        <>
          {open.length === 0 && (
            <p style={{ fontSize: 12.5, color: "var(--muted)" }}>
              No batches awaiting action.</p>
          )}
          {open.map((b) => (
            <BatchCard key={b.id} batch={b} me={me} onChanged={load} />
          ))}
          {recent.length > 0 && (
            <details style={{ marginTop: 8 }}>
              <summary style={{ cursor: "pointer", fontSize: 12.5,
                                color: "var(--muted)" }}>Recent decisions</summary>
              {recent.map((b) => (
                <div key={b.id} style={{ fontSize: 12.5, padding: "3px 0",
                                         color: "var(--muted)" }}>
                  {KIND_LABEL[b.kind]} ×{b.worker_count} ·{" "}
                  <Chip tone={STATUS_TONE[b.status]}>{b.status_label}</Chip>
                </div>
              ))}
            </details>
          )}
        </>
      )}

      <h4 style={{ margin: "16px 0 6px", color: "var(--navy)" }}>
        On site — {(roster || []).length} worker(s)</h4>
      {roster === null ? <p style={{ color: "var(--muted)" }}>Loading…</p>
       : roster.length === 0 ? (
        <p style={{ fontSize: 12.5, color: "var(--muted)" }}>
          No active direct workers here.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={{ ...th, width: 52 }}>Photo</th>
              <th style={th}>Emp No</th><th style={th}>Name</th>
              <th style={th}>Category</th><th style={th}>Nationality</th>
              <th style={th}>Joined</th>
              <th style={{ ...th, textAlign: "right" }}>Salary</th>
              {canManage && <th style={th}></th>}
            </tr></thead>
            <tbody>
              {roster.map((w) => (
                <tr key={w.id}>
                  <td style={{ ...td, padding: "4px 6px" }}>
                    <WorkerPhoto worker={w} canManage={canManage}
                                 onSaved={load} /></td>
                  <td style={td}>{w.emp_no}</td>
                  <td style={td}>{w.full_name}</td>
                  <td style={td}>{w.job_title || "—"}</td>
                  <td style={td}>{w.nationality || "—"}</td>
                  <td style={td}>
                    {canManage
                      ? <JoinDateCell worker={w} onSaved={load} />
                      : (w.join_date || "—")}
                  </td>
                  <td style={{ ...td, textAlign: "right",
                               fontFamily: "var(--font-mono)" }}>
                    {w.pay_hidden ? <span style={{ color: "var(--muted)" }}
                      title="Senior-staff pay is hidden">—</span>
                      : w.basic_pay == null ? "—"
                      : `${w.currency} ${money(w.basic_pay)}`}</td>
                  {canManage && (
                    <td style={{ ...td, textAlign: "right" }}>
                      {w.pay_hidden ? null : openRevIds.has(w.id)
                        ? <span style={{ fontSize: 11, color: "var(--muted)" }}>
                            revision pending</span>
                        : <a href="#" onClick={(e) => { e.preventDefault();
                            setRevising(w); }} style={{ fontSize: 12 }}>
                            Revise salary</a>}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function BatchCard({ batch, me, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [openList, setOpenList] = useState(false);
  const isPM = ["PM", "ADMIN"].includes(me.role);
  const isDir = ["DIRECTOR", "ADMIN"].includes(me.role);
  const isSite = SITE_MANAGE.includes(me.role);
  const s = batch.status;

  async function act(action, needNote) {
    let note = "";
    if (needNote) {
      note = window.prompt("Reason for returning to the site:") || "";
      if (!note.trim()) return;
    }
    setBusy(true); setError(null);
    try {
      await api(`/worker-batches/${batch.id}/action`,
                { method: "POST", body: { action, note } });
      onChanged();
    } catch (e) { setError(e.message); setBusy(false); }
  }

  const acts = [];
  if (batch.kind === "ADD" && s === "SUBMITTED" && isPM)
    acts.push(["approve", "Approve (PM)", "navy", false]);
  if (batch.kind === "ADD" && s === "PM_APPROVED" && isDir)
    acts.push(["approve", "Activate (Director)", "navy", false]);
  if (batch.kind !== "ADD" && s === "SUBMITTED" && isPM)
    acts.push(["approve", "Approve (PM)", "navy", false]);
  if (["SUBMITTED", "PM_APPROVED"].includes(s) && (isPM || isDir))
    acts.push(["return", "Return", "secondary", true]);
  if (s === "RETURNED" && isSite)
    acts.push(["resubmit", "Resubmit", "navy", false]);
  if (["SUBMITTED", "PM_APPROVED", "RETURNED"].includes(s) && isSite)
    acts.push(["cancel", "Cancel", "ghost", false]);

  return (
    <div style={{ border: "1px solid #e2e8f0", borderRadius: 8,
                  padding: "8px 10px", marginBottom: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                    flexWrap: "wrap" }}>
        <b style={{ color: "var(--navy)" }}>
          {KIND_LABEL[batch.kind]} · {batch.worker_count} worker(s)</b>
        <Chip tone={STATUS_TONE[s]}>{batch.status_label}</Chip>
        {batch.kind === "TRANSFER" && (
          <span style={{ color: "var(--muted)" }}>→ {batch.to_site_code}</span>
        )}
        <a href="#" onClick={(e) => { e.preventDefault();
                                      setOpenList(!openList); }}
           style={{ fontSize: 12, marginLeft: "auto" }}>
          {openList ? "hide" : "show"} workers</a>
      </div>
      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
        by {batch.requested_by}
        {batch.reason ? ` · "${batch.reason}"` : ""}
        {batch.decision_note ? ` · returned: ${batch.decision_note}` : ""}
      </div>
      {openList && (
        <table style={{ width: "100%", borderCollapse: "collapse",
                        marginTop: 6 }}>
          <tbody>
            {batch.workers.map((w) => (
              <tr key={w.id}>
                <td style={{ ...td, padding: "3px 6px" }}>{w.full_name}</td>
                <td style={{ ...td, padding: "3px 6px",
                             color: "var(--muted)" }}>{w.job_title || "—"}</td>
                <td style={{ ...td, padding: "3px 6px",
                             color: "var(--muted)" }}>{w.nationality}</td>
                {batch.kind === "ADD" && (
                  <td style={{ ...td, padding: "3px 6px", textAlign: "right",
                               fontFamily: "var(--font-mono)" }}>
                    {w.currency} {money(w.basic_pay)}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {error && <p style={{ color: "var(--red-fg)", margin: "4px 0" }}>
        {error}</p>}
      {acts.length > 0 && (
        <div style={{ display: "flex", gap: 6, marginTop: 6,
                      flexWrap: "wrap" }}>
          {acts.map(([action, label, variant, needNote]) => (
            <Btn key={label} variant={variant} disabled={busy}
                 onClick={() => act(action, needNote)}>{label}</Btn>
          ))}
        </div>
      )}
    </div>
  );
}

const lbl = { display: "flex", flexDirection: "column", gap: 3, fontSize: 11.5,
              color: "var(--muted)" };

// A site team member proposes a category/salary change for one worker. If the
// PM raises it, it skips to the Director; a Site Admin/Engineer's goes to the
// PM first. The new pay applies to the whole month once approved.
function ReviseForm({ site, worker, onCancel, onDone }) {
  const [cats, setCats] = useState([]);
  const [toCat, setToCat] = useState("");
  const [toPay, setToPay] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/manpower-categories")
      .then((all) => setCats(all.filter((c) => c.list_type === "DPR")))
      .catch(() => setCats([]));
  }, []);

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api("/salary-revisions", { method: "POST", body: {
        site_id: site.id, employee_id: worker.id,
        to_category_id: toCat || null, to_basic_pay: toPay, reason } });
      onDone();
    } catch (err) { setError(err.message); setBusy(false); }
  }

  return (
    <form onSubmit={submit} style={{ ...card, background: "var(--paper)",
                                     marginBottom: 12 }}>
      <h4 style={{ margin: "0 0 4px", color: "var(--navy)" }}>
        Revise salary — {worker.full_name}</h4>
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "0 0 8px" }}>
        Currently {worker.job_title || "—"} ·{" "}
        {worker.currency} {money(worker.basic_pay)}. The change is subject to
        Director approval and applies to the whole current month.</p>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      <div style={{ display: "grid", gap: 6,
                    gridTemplateColumns: "repeat(3, 1fr)" }}>
        <label style={lbl}>New category
          <select style={inputStyle} value={toCat}
                  onChange={(e) => setToCat(e.target.value)}>
            <option value="">(keep {worker.job_title || "—"})</option>
            {cats.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>))}
          </select></label>
        <label style={lbl}>Revised salary ({worker.currency})
          <input style={inputStyle} value={toPay} inputMode="decimal"
                 onChange={(e) => setToPay(e.target.value)} /></label>
      </div>
      <label style={{ ...lbl, marginTop: 6 }}>Reason (performance note)
        <textarea style={{ ...inputStyle, minHeight: 44 }} value={reason}
                  onChange={(e) => setReason(e.target.value)} /></label>
      <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
        <Btn variant="navy" disabled={busy}>Submit for approval</Btn>
        <Btn type="button" variant="ghost" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}

function RevisionCard({ rev, me, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const isPM = ["PM", "ADMIN"].includes(me.role);
  const isDir = ["DIRECTOR", "ADMIN"].includes(me.role);
  const isSite = SITE_MANAGE.includes(me.role);
  const s = rev.status;

  async function act(action, needNote) {
    let note = "";
    if (needNote) {
      note = window.prompt("Reason:") || "";
      if (!note.trim()) return;
    }
    setBusy(true); setError(null);
    try {
      await api(`/salary-revisions/${rev.id}/action`,
                { method: "POST", body: { action, note } });
      onChanged();
    } catch (e) { setError(e.message); setBusy(false); }
  }

  const acts = [];
  if (s === "SUBMITTED" && isPM) acts.push(["approve", "Approve (PM)", "navy", false]);
  if (s === "PM_APPROVED" && isDir) acts.push(["approve", "Approve (Director)", "navy", false]);
  if (isDir) acts.push(["reject", "Reject", "danger", true]);
  if (isPM || isDir) acts.push(["return", "Return", "secondary", true]);
  if (isSite) acts.push(["cancel", "Cancel", "ghost", false]);

  const cat = rev.from_category !== rev.to_category
    ? `${rev.from_category || "—"} → ${rev.to_category || "—"}` : rev.to_category;
  return (
    <div style={{ border: "1px solid #e2e8f0", borderRadius: 8,
                  padding: "8px 10px", marginBottom: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                    flexWrap: "wrap" }}>
        <b style={{ color: "var(--navy)" }}>{rev.employee}</b>
        <Chip tone={STATUS_TONE[s]}>{rev.status_label}</Chip>
        {rev.pay_hidden ? (
          <span style={{ fontSize: 12.5, color: "var(--muted)" }}
                title="Management pay is not shown on site">
            management pay — HR only</span>
        ) : (
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12.5 }}>
            {rev.currency} {money(rev.from_basic_pay)} →{" "}
            <b>{money(rev.to_basic_pay)}</b></span>
        )}
      </div>
      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
        {cat ? `${cat} · ` : ""}by {rev.requested_by}
        {rev.reason ? ` · "${rev.reason}"` : ""}
        {rev.decision_note ? ` · note: ${rev.decision_note}` : ""}
      </div>
      {error && <p style={{ color: "var(--red-fg)", margin: "4px 0" }}>{error}</p>}
      {acts.length > 0 && (
        <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
          {acts.map(([action, label, variant, needNote]) => (
            <Btn key={label} variant={variant} disabled={busy}
                 onClick={() => act(action, needNote)}>{label}</Btn>
          ))}
        </div>
      )}
    </div>
  );
}
// Site hires are CONTRACT workers only (owner 2026-08-11) — a PERMANENT
// worker goes on the company work permit and is created by HR / onboarding,
// never from the site batch. The server enforces this too.
const BLANK = { full_name: "", passport_no: "", nationality: "",
  job_category_id: "", basic_pay: "", currency: "MVR",
  employment_type: "CONTRACT", work_permit_no: "", work_permit_expiry: "",
  // Held on the row and uploaded once the batch has created the worker: the
  // photo is taken with the man standing there on his first day, not after
  // an approval that may be days away (owner 2026-08-30).
  photo: null };

// Take the man's photograph while he is standing there. The only way to add
// one used to be from the workforce list after the hire was approved, or
// through an onboarding case — so for a site hire it was days late, and
// usually never (owner 2026-08-30).
function HirePhoto({ file, onPick }) {
  const [preview, setPreview] = useState(null);
  useEffect(() => {
    if (!file) { setPreview(null); return undefined; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  return (
    <label title="Photo — camera or camera roll"
           style={{ display: "flex", alignItems: "center", gap: 6,
                    cursor: "pointer", fontSize: 12 }}>
      {preview ? (
        <img src={preview} alt="" style={{ width: 30, height: 30,
                                           borderRadius: "50%",
                                           objectFit: "cover" }} />
      ) : (
        <span style={{ width: 30, height: 30, borderRadius: "50%",
                       background: "#e8eef3", display: "inline-flex",
                       alignItems: "center", justifyContent: "center",
                       color: "#8a97a3", fontSize: 14 }}>👤</span>
      )}
      <span style={{ color: "var(--navy)", textDecoration: "underline" }}>
        {file ? "change" : "add photo"}</span>
      <input type="file" accept="image/*" capture="environment"
             style={{ display: "none" }}
             onChange={(e) => onPick(e.target.files[0] || null)} />
    </label>
  );
}

function HiresForm({ site, onCancel, onDone }) {
  const [rows, setRows] = useState([{ ...BLANK }]);
  const [cats, setCats] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (i, k) => (e) => {
    const next = rows.slice();
    next[i] = { ...next[i], [k]: e.target.value };
    setRows(next);
  };

  useEffect(() => {
    api("/manpower-categories")
      .then((all) => setCats(all.filter((c) => c.list_type === "DPR")))
      .catch(() => setCats([]));
  }, []);

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const kept = rows.filter((r) => r.full_name.trim());
      const workers = kept.map((r) => { const w = { ...r };
        delete w.photo;
        if (!w.job_category_id) delete w.job_category_id; return w; });
      const batch = await api(`/sites/${site.id}/worker-batches`,
                              { method: "POST",
                                body: { kind: "ADD", workers } });
      // The batch creates the worker records, so the photos go up against
      // the ids it hands back — matched on passport number rather than
      // position, so a reordered response cannot put a face on the wrong man.
      const created = batch?.workers || [];
      for (const r of kept) {
        if (!r.photo) continue;
        const match = created.find(
          (w) => (w.passport_no || "").trim().toUpperCase()
                 === (r.passport_no || "").trim().toUpperCase());
        if (!match) continue;
        try {
          const fd = new FormData();
          fd.append("photo", await shrinkPhoto(r.photo));
          await apiUpload(`/workers/${match.id}/photo`, fd);
        } catch {
          // A failed photo must not lose the hire — it can be added from the
          // workforce list afterwards.
        }
      }
      onDone();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  const star = (t) => (
    <span>{t} <span style={{ color: "var(--red-fg)" }}>*</span></span>);
  return (
    <form onSubmit={submit} style={{ ...card, background: "var(--paper)",
                                     marginBottom: 12 }}>
      <h4 style={{ margin: "0 0 8px", color: "var(--navy)" }}>
        New hires — submit as one batch</h4>
      <p style={{ margin: "0 0 8px", fontSize: 12, color: "#8a6d00" }}>
        Site hires are <b>Contract</b> workers. A permanent worker (company
        work permit) is created by HR through Onboarding — not here.</p>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      {rows.map((r, i) => (
        <div key={i} style={{ border: "1px solid #e2e8f0", borderRadius: 8,
                              padding: 8, marginBottom: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                        marginBottom: 4 }}>
            <b style={{ fontSize: 12, color: "var(--muted)" }}>
              Worker {i + 1}</b>
            <HirePhoto file={r.photo}
                       onPick={(file) => {
                         const next = rows.slice();
                         next[i] = { ...next[i], photo: file };
                         setRows(next);
                       }} />
            {rows.length > 1 && (
              <a href="#" onClick={(e) => { e.preventDefault();
                setRows(rows.filter((_, j) => j !== i)); }}
                 style={{ fontSize: 12, color: "var(--red-fg)" }}>remove</a>
            )}
          </div>
          <div style={{ display: "grid", gap: 6,
                        gridTemplateColumns: "repeat(4, 1fr)" }}>
            <label style={lbl}>{star("Full name")}
              <input style={inputStyle} value={r.full_name}
                     onChange={set(i, "full_name")} /></label>
            <label style={lbl}>{star("Passport no.")}
              <input style={inputStyle} value={r.passport_no}
                     onChange={set(i, "passport_no")} /></label>
            <label style={lbl}>{star("Nationality")}
              <input style={inputStyle} value={r.nationality}
                     onChange={set(i, "nationality")} /></label>
            <label style={lbl}>{star("Trade")}
              <select style={inputStyle} value={r.job_category_id}
                      onChange={set(i, "job_category_id")}>
                <option value="">—</option>
                {cats.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>))}
              </select></label>
            <label style={lbl}>{star("Basic pay")}
              <input style={inputStyle} value={r.basic_pay} inputMode="decimal"
                     onChange={set(i, "basic_pay")} /></label>
            <label style={lbl}>Currency
              <select style={inputStyle} value={r.currency}
                      onChange={set(i, "currency")}>
                <option>MVR</option><option>USD</option></select></label>
            <label style={lbl}>Work-permit ID
              <input style={inputStyle} value={r.work_permit_no}
                     onChange={set(i, "work_permit_no")} /></label>
            <label style={lbl}>WP expiry
              <input type="date" style={inputStyle} value={r.work_permit_expiry}
                     onChange={set(i, "work_permit_expiry")} /></label>
          </div>
        </div>
      ))}
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <Btn type="button" variant="ghost"
             onClick={() => setRows([...rows, { ...BLANK }])}>
          + Add another worker</Btn>
      </div>
      <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
        <Btn variant="navy" disabled={busy}>Submit batch for approval</Btn>
        <Btn type="button" variant="ghost" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}

function RosterPicker({ site, onCancel, onDone }) {
  const [roster, setRoster] = useState(null);
  const [sites, setSites] = useState([]);
  const [sel, setSel] = useState(() => new Set());
  const [dest, setDest] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api(`/sites/${site.id}/direct-workers`).then(setRoster)
      .catch((e) => setError(e.message));
    // NOT /sites — that returns only the sites the user is allocated to, so a
    // PM could send men to the other sites he runs and nobody else, and a Site
    // Admin had no destination at all (owner 2026-08-20).
    api(`/sites/${site.id}/transfer-destinations`).then(setSites)
      .catch(() => setSites([]));
  }, [site.id]);

  const toggle = (id) => {
    const n = new Set(sel);
    n.has(id) ? n.delete(id) : n.add(id);
    setSel(n);
  };

  async function submit(kind) {
    const ids = [...sel];
    if (!ids.length) { setError("Select at least one worker."); return; }
    const body = { kind, employee_ids: ids };
    if (kind === "REMOVE") {
      body.reason = window.prompt("Reason for removing these workers:") || "";
    } else {
      if (!dest) { setError("Choose a destination site."); return; }
      body.to_site_id = dest;
    }
    setBusy(true); setError(null);
    try {
      await api(`/sites/${site.id}/worker-batches`, { method: "POST", body });
      onDone();
    } catch (e) { setError(e.message); setBusy(false); }
  }

  return (
    <div style={{ ...card, background: "var(--paper)", marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <h4 style={{ margin: "0 0 8px", color: "var(--navy)" }}>
          Remove or transfer workers</h4>
        <Btn variant="ghost" onClick={onCancel}>Close</Btn>
      </div>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      {roster === null ? <p style={{ color: "var(--muted)" }}>Loading…</p>
       : roster.length === 0 ? (
        <p style={{ color: "var(--muted)" }}>No active direct workers here.</p>
      ) : (
        <>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={{ ...th, width: 30 }}></th>
              <th style={th}>Emp No</th><th style={th}>Name</th>
              <th style={th}>Trade</th><th style={th}>Nationality</th>
            </tr></thead>
            <tbody>
              {roster.map((e) => (
                <tr key={e.id} style={e.busy ? { opacity: 0.5 } : {}}>
                  <td style={td}>
                    <input type="checkbox" disabled={e.busy}
                           checked={sel.has(e.id)}
                           onChange={() => toggle(e.id)} /></td>
                  <td style={td}>{e.emp_no}</td>
                  <td style={td}>{e.full_name}
                    {e.busy && <span style={{ fontSize: 11,
                      color: "var(--muted)" }}> · in a batch</span>}</td>
                  <td style={td}>{e.job_title || "—"}</td>
                  <td style={td}>{e.nationality}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ display: "flex", gap: 8, marginTop: 10,
                        alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
              {sel.size} selected</span>
            <Btn variant="danger" disabled={busy}
                 onClick={() => submit("REMOVE")}>Remove selected</Btn>
            <span style={{ marginLeft: 8 }}>Transfer to</span>
            <select style={{ ...inputStyle, width: 190 }} value={dest}
                    onChange={(e) => setDest(e.target.value)}>
              <option value="">Site…</option>
              {sites.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.code} — {s.name}
                  {s.status === "AWARDED" ? " (mobilising)" : ""}</option>))}
            </select>
            <Btn variant="secondary" disabled={busy}
                 onClick={() => submit("TRANSFER")}>Transfer selected</Btn>
          </div>
        </>
      )}
    </div>
  );
}

/* The start date drives pro-rata pay for a part month, so the site that knows
   when someone actually walked on has to be able to correct it — the hire flow
   can only stamp the day the batch was approved (owner 2026-08-13). */
function JoinDateCell({ worker, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(worker.join_date || "");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    setErr(null);
    try {
      await api(`/workers/${worker.id}/join-date`, {
        method: "PATCH", body: { join_date: value },
      });
      setEditing(false);
      onSaved();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (!editing) {
    return (
      <a href="#" title="Set the date this worker started"
         onClick={(e) => { e.preventDefault(); setEditing(true); }}
         style={{ fontSize: 12.5,
                  color: worker.join_date ? "inherit" : "#b06000" }}>
        {worker.join_date || "set date"}
      </a>
    );
  }
  return (
    <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
      <input type="date" value={value} disabled={busy}
             onChange={(e) => setValue(e.target.value)}
             style={{ ...inputStyle, padding: "2px 6px", fontSize: 12,
                      width: 140 }} />
      <Btn onClick={save} disabled={busy}
           style={{ padding: "2px 8px", fontSize: 12 }}>Save</Btn>
      <a href="#" onClick={(e) => { e.preventDefault(); setEditing(false);
                                    setErr(null); }}
         style={{ fontSize: 12 }}>cancel</a>
      {err && <span style={{ color: "#b00", fontSize: 11 }}>{err}</span>}
    </span>
  );
}
