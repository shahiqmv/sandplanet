import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { StatusChip, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

// Daily Manpower Allocation (R5): the PM's early-morning task board, built
// off the TWSs issued the previous evening plus general tasks (cleaning,
// unloading, housekeeping). One per site per day; internal only.

const EMPTY_TASK = { task: "", project: "", location: "", category: "",
                     workers: "", remarks: "" };
const today = () => new Date().toISOString().slice(0, 10);

export default function DMAPage({ site, me, onClose }) {
  const [date, setDate] = useState(today());
  const [doc, setDoc] = useState(null);          // existing DMA for the date
  const [tasks, setTasks] = useState([{ ...EMPTY_TASK }]);
  const [notes, setNotes] = useState("");
  const [hours, setHours] = useState("");
  const [twsRefs, setTwsRefs] = useState([]);
  const [categories, setCategories] = useState([]);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/manpower-categories").then((list) => {
      const dpr = list.filter((c) => c.list_type === "DPR");
      setCategories(dpr.length ? dpr : list);
    }).catch(() => {});
  }, []);

  const load = useCallback(() => {
    setError(null);
    setNotice(null);
    api(`/documents/list?site=${site.id}&doc_type=DMA`).then((list) => {
      const found = list.find((d) => d.doc_date === date && !d.is_void);
      setDoc(found || null);
      const p = found?.payload || {};
      setTasks(p.tasks?.length ? p.tasks : [{ ...EMPTY_TASK }]);
      setNotes(p.notes || "");
      setHours(p.working_hours || "");
      setTwsRefs(p.tws_refs || []);
    }).catch((e) => setError(e.message));
  }, [site.id, date]);

  useEffect(load, [load]);

  const editable = !doc || (doc.status === "DRAFT" &&
    ["SITE_ENGINEER", "PM", "ADMIN"].includes(me.role));
  const canIssue = doc && doc.status === "DRAFT" &&
    ["PM", "ADMIN"].includes(me.role);

  function setTask(i, field, value) {
    setTasks(tasks.map((t, j) => (j === i ? { ...t, [field]: value } : t)));
  }

  async function loadFromTws() {
    setError(null);
    try {
      const r = await api(`/dma-prefill?site=${site.id}&date=${date}`);
      if (!r.tasks.length) {
        setNotice(`No issued TWS found scheduling work for ${date}.`);
        return;
      }
      const existing = tasks.filter((t) => t.task.trim());
      setTasks([...existing, ...r.tasks]);
      setTwsRefs(r.tws_refs);
      setNotice(`${r.tasks.length} task(s) loaded from ${r.tws_refs.join(", ")}.`);
    } catch (e) {
      setError(e.message);
    }
  }

  function payload() {
    return {
      tasks: tasks.filter((t) => t.task.trim()),
      notes, working_hours: hours, tws_refs: twsRefs,
    };
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      if (doc) {
        const updated = await api(`/documents/${doc.ref}`, {
          method: "PATCH", body: { payload: payload() } });
        setDoc(updated);
        setNotice(`${updated.ref} saved.`);
      } else {
        const created = await api("/documents", { method: "POST", body: {
          doc_type: "DMA", site_id: site.id, doc_date: date,
          payload: payload() } });
        setDoc(created);
        setNotice(`${created.ref} created (draft).`);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function issue() {
    setBusy(true);
    setError(null);
    try {
      await api(`/documents/${doc.ref}`, { method: "PATCH",
                body: { payload: payload() } });
      const issued = await api(`/documents/${doc.ref}/actions/issue`,
                               { method: "POST" });
      setDoc(issued);
      setNotice(`${issued.ref} issued — allocation is now locked.`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  // Category totals — mirrors the PDF's "Manpower at Work" table
  const totals = {};
  let grandTotal = 0;
  for (const t of tasks) {
    const n = parseInt(t.workers, 10) || 0;
    if (!n) continue;
    const key = (t.category || "Unassigned").trim() || "Unassigned";
    totals[key] = (totals[key] || 0) + n;
    grandTotal += n;
  }
  const pdf = doc?.attachments?.filter((a) => a.kind === "GENERATED_PDF")
    .slice(-1)[0];

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)", fontSize: 17 }}>
          ☀ Daily Manpower Allocation — {site.code}
        </h2>
        {doc && <><b>{doc.ref}</b> <StatusChip status={doc.status} /></>}
        {pdf && (
          <a href={pdf.url} target="_blank" rel="noreferrer"
             style={{ fontSize: 13 }}>📄 PDF</a>
        )}
        <button onClick={onClose} style={{ ...ghostButton,
                                           marginLeft: "auto" }}>
          ← Back
        </button>
      </div>

      <div style={{ display: "flex", gap: 12, alignItems: "center",
                    margin: "14px 0", flexWrap: "wrap" }}>
        <label style={{ fontSize: 13 }}>Allocation for{" "}
          <input type="date" value={date}
                 onChange={(e) => setDate(e.target.value)}
                 style={{ ...inputStyle, width: 150 }} />
        </label>
        <label style={{ fontSize: 13 }}>Working hours{" "}
          <input value={hours} placeholder="e.g. 08:00 – 18:00"
                 disabled={!editable}
                 onChange={(e) => setHours(e.target.value)}
                 style={{ ...inputStyle, width: 150 }} />
        </label>
        {editable && (
          <button onClick={loadFromTws} style={{ ...ghostButton,
                                                 fontSize: 13 }}>
            ⤵ Load tasks from TWS
          </button>
        )}
        {twsRefs.length > 0 && (
          <span style={{ fontSize: 12, color: "#5a6b78" }}>
            Based on {twsRefs.join(", ")}
          </span>
        )}
      </div>

      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}
      {notice && <p style={{ color: "#1a7f37", fontSize: 13 }}>{notice}</p>}

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={th}>#</th><th style={th}>Task</th>
              <th style={th}>Project</th><th style={th}>Location/Area</th>
              <th style={th}>Category</th><th style={th}>Workers</th>
              <th style={th}>Remarks</th>
              {editable && <th style={th} />}
            </tr>
          </thead>
          <tbody>
            {tasks.map((t, i) => (
              <tr key={i}>
                <td style={{ ...td, width: 24, color: "#5a6b78" }}>{i + 1}</td>
                {editable ? (
                  <>
                    <td style={td}>
                      <input value={t.task}
                             placeholder="Task (TWS scope or general)"
                             onChange={(e) => setTask(i, "task",
                                                      e.target.value)}
                             style={{ ...inputStyle, minWidth: 220 }} />
                    </td>
                    <td style={td}>
                      <input value={t.project} placeholder="— general —"
                             title="Project code; leave blank for general tasks"
                             onChange={(e) => setTask(i, "project",
                                                      e.target.value)}
                             style={{ ...inputStyle, width: 100 }} />
                    </td>
                    <td style={td}>
                      <input value={t.location}
                             onChange={(e) => setTask(i, "location",
                                                      e.target.value)}
                             style={{ ...inputStyle, width: 120 }} />
                    </td>
                    <td style={td}>
                      <input value={t.category} list="dma-categories"
                             onChange={(e) => setTask(i, "category",
                                                      e.target.value)}
                             style={{ ...inputStyle, width: 130 }} />
                    </td>
                    <td style={td}>
                      <input type="number" min="0" value={t.workers}
                             onChange={(e) => setTask(i, "workers",
                                                      e.target.value)}
                             style={{ ...inputStyle, width: 70 }} />
                    </td>
                    <td style={td}>
                      <input value={t.remarks}
                             onChange={(e) => setTask(i, "remarks",
                                                      e.target.value)}
                             style={{ ...inputStyle, width: 140 }} />
                    </td>
                    <td style={td}>
                      <button onClick={() => setTasks(
                                tasks.filter((_, j) => j !== i))}
                              title="Remove row"
                              style={{ ...ghostButton, padding: "2px 8px" }}>
                        ×
                      </button>
                    </td>
                  </>
                ) : (
                  <>
                    <td style={td}>{t.task}</td>
                    <td style={td}>{t.project || "General"}</td>
                    <td style={td}>{t.location}</td>
                    <td style={td}>{t.category}</td>
                    <td style={{ ...td, textAlign: "center" }}>{t.workers}</td>
                    <td style={td}>{t.remarks}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <datalist id="dma-categories">
        {categories.map((c) => <option key={c.id} value={c.name} />)}
      </datalist>

      {editable && (
        <button onClick={() => setTasks([...tasks, { ...EMPTY_TASK }])}
                style={{ ...ghostButton, marginTop: 8, fontSize: 13 }}>
          + Add task row
        </button>
      )}

      {grandTotal > 0 && (
        <div style={{ marginTop: 16, maxWidth: 340 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 14,
                       color: "var(--sp-navy)" }}>
            Manpower at work
          </h3>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {Object.entries(totals).sort().map(([cat, n]) => (
                <tr key={cat}>
                  <td style={td}>{cat}</td>
                  <td style={{ ...td, textAlign: "right" }}>{n}</td>
                </tr>
              ))}
              <tr style={{ fontWeight: 700 }}>
                <td style={td}>Total</td>
                <td style={{ ...td, textAlign: "right" }}>{grandTotal}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {editable && (
        <div style={{ marginTop: 16 }}>
          <label style={{ display: "block", fontSize: 13, marginBottom: 4 }}>
            Notes / instructions</label>
          <textarea value={notes} rows={2}
                    onChange={(e) => setNotes(e.target.value)}
                    style={{ ...inputStyle, width: "100%" }} />
        </div>
      )}
      {!editable && notes && (
        <p style={{ fontSize: 13 }}><b>Notes:</b> {notes}</p>
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        {editable && (
          <button onClick={save} disabled={busy} style={buttonStyle}>
            {doc ? "Save" : "Create draft"}
          </button>
        )}
        {canIssue && (
          <button onClick={issue} disabled={busy}
                  style={{ ...buttonStyle, background: "#1a7f37" }}>
            Issue (locks allocation)
          </button>
        )}
        {doc && doc.status === "DRAFT" && !canIssue && editable && (
          <span style={{ fontSize: 12, color: "#5a6b78",
                         alignSelf: "center" }}>
            Only the PM issues the morning allocation.
          </span>
        )}
      </div>
    </section>
  );
}
