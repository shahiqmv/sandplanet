import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";

const SITE_MANAGE = ["SITE_ADMIN", "SITE_ENGINEER", "ADMIN"];
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
  const [view, setView] = useState(null);   // 'add' | 'roster'
  const [error, setError] = useState(null);
  const canManage = SITE_MANAGE.includes(me.role);

  function load() {
    api(`/worker-batches?site_id=${site.id}`).then(setBatches)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [site.id]);

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
const BLANK = { full_name: "", passport_no: "", nationality: "",
  job_category_id: "", basic_pay: "", currency: "MVR",
  employment_type: "PERMANENT", work_permit_no: "", work_permit_expiry: "" };

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
      const workers = rows.filter((r) => r.full_name.trim())
        .map((r) => { const w = { ...r };
          if (!w.job_category_id) delete w.job_category_id; return w; });
      await api(`/sites/${site.id}/worker-batches`,
                { method: "POST", body: { kind: "ADD", workers } });
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
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}
      {rows.map((r, i) => (
        <div key={i} style={{ border: "1px solid #e2e8f0", borderRadius: 8,
                              padding: 8, marginBottom: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                        marginBottom: 4 }}>
            <b style={{ fontSize: 12, color: "var(--muted)" }}>
              Worker {i + 1}</b>
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
    api("/sites").then((s) => setSites(s.filter((x) => x.id !== site.id)))
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
            <select style={{ ...inputStyle, width: 130 }} value={dest}
                    onChange={(e) => setDest(e.target.value)}>
              <option value="">Site…</option>
              {sites.map((s) => (
                <option key={s.id} value={s.id}>{s.code}</option>))}
            </select>
            <Btn variant="secondary" disabled={busy}
                 onClick={() => submit("TRANSFER")}>Transfer selected</Btn>
          </div>
        </>
      )}
    </div>
  );
}
