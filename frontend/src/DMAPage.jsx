import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { StatusChip, buttonStyle, card, ghostButton, inputStyle, td, th }
  from "./ui.jsx";

// Daily Manpower Allocation (R5): the PM's early-morning task board, built
// off the TWSs issued the previous evening plus general tasks (cleaning,
// unloading, housekeeping). One per site per day; internal only.

const EMPTY_TASK = { task: "", project: "", location: "", unit_id: "",
                     category: "",
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
  // The project is picked, never typed — a typo made a project nobody could
  // report on — and a project that tracks units offers them as the location
  // (owner 2026-09-03).
  const [projects, setProjects] = useState([]);
  const [units, setUnits] = useState([]);
  const [mp, setMp] = useState(null);  // roster/attendance per category
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Categories come strictly from the manpower list (owner, R9
    // addendum) — preferring the ones actually on THIS site's roster —
    // and attendance supplies who is available to allocate.
    api(`/sites/${site.id}/projects?status=ACTIVE`)
      .then(setProjects).catch(() => setProjects([]));
    api(`/sites/${site.id}/units`).then(setUnits).catch(() => setUnits([]));
    Promise.all([
      api("/manpower-categories").catch(() => []),
      api(`/sites/${site.id}/manpower`).catch(() => null),
    ]).then(([list, manpower]) => {
      setMp(manpower);
      const roster = (manpower?.categories || []).filter(
        (c) => c.id && c.roster > 0);
      if (roster.length) {
        setCategories(roster.map((c) => ({ id: c.id, name: c.name })));
      } else {
        const dpr = list.filter((c) => c.list_type === "DPR" && c.is_active);
        setCategories(dpr.length ? dpr : list);
      }
    });
  }, [site.id]);

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
    ["SITE_ENGINEER", "PM", "DIRECTOR", "ADMIN"].includes(me.role));
  const canIssue = doc && doc.status === "DRAFT" &&
    ["PM", "ADMIN"].includes(me.role);

  function setTask(i, field, value) {
    setTasks(tasks.map((t, j) => (j === i ? { ...t, [field]: value } : t)));
  }
  // Same task, another manpower category: insert a fresh line right below,
  // pre-filled with this task/project/location so nothing is retyped. A crew
  // can also be reused across tasks, so allocation is never capped by headcount.
  function addCategoryLine(i) {
    const s = tasks[i];
    setTasks([...tasks.slice(0, i + 1),
              { ...EMPTY_TASK, task: s.task, project: s.project,
                location: s.location, unit_id: s.unit_id || "" },
              ...tasks.slice(i + 1)]);
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

  // Total worker-assignments across tasks. A crew reused on several tasks is
  // counted once per task, so this is an ALLOCATION count, not the headcount on
  // site — the real "manpower at work" comes from attendance (below).
  let grandTotal = 0;
  for (const t of tasks) grandTotal += parseInt(t.workers, 10) || 0;
  // Attendance is shown for reference (present per category), but it does NOT
  // cap allocation — the same crew can cover several tasks in a day, so the
  // sheet total legitimately exceeds headcount. No "unallocated"/over warnings.
  const attendanceIn = !!mp?.attendance_entered;
  const presentByCat = {};
  for (const c of mp?.categories || []) presentByCat[c.name] = c.present;
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

      {mp && (
        <p style={{ fontSize: 12.5, color: "#5a6b78", margin: "0 0 10px" }}>
          {attendanceIn ? (
            <>
              <b style={{ color: "#1a7f37" }}>{mp.present} present</b> today
              (attendance) · {grandTotal} allocated across tasks
            </>
          ) : "Attendance has not been entered for today yet — present "
            + "counts will appear here once it is."}
        </p>
      )}
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
                      <select value={t.project || ""}
                              onChange={(e) => setTasks(tasks.map((x, j) =>
                                j === i ? { ...x, project: e.target.value,
                                            unit_id: "" } : x))}
                              title="Leave general for site-wide tasks"
                              style={{ ...inputStyle, width: 120,
                                       background: t.project && !projects.some(
                                         (pr) => pr.code === t.project)
                                         ? "#fff8e6" : "#fff" }}>
                        <option value="">— general —</option>
                        {projects.map((pr) => (
                          <option key={pr.code} value={pr.code}>{pr.code}</option>
                        ))}
                        {t.project && !projects.some((pr) =>
                            pr.code === t.project) && (
                          <option value={t.project}>
                            {t.project} (not on this site)</option>
                        )}
                      </select>
                    </td>
                    <td style={td}>
                      {(() => {
                        const mine = units.filter(
                          (u) => u.project_code === t.project);
                        if (!t.project || !mine.length) {
                          return (
                            <input value={t.location}
                                   onChange={(e) => setTask(i, "location",
                                                            e.target.value)}
                                   style={{ ...inputStyle, width: 120 }} />
                          );
                        }
                        // A unit-tracking project: the villa/pool is the
                        // location. "Other" keeps the free text for the
                        // jetty, the batching plant, the store.
                        const other = t.unit_id === "" && t.location;
                        return (
                          <span style={{ display: "inline-flex", gap: 4 }}>
                            <select value={other ? "__other" : (t.unit_id || "")}
                                    onChange={(e) => {
                                      const v = e.target.value;
                                      if (v === "__other") {
                                        setTasks(tasks.map((x, j) => j === i
                                          ? { ...x, unit_id: "", location: x.location || " " }
                                          : x));
                                        return;
                                      }
                                      const u = mine.find(
                                        (m) => String(m.id) === v);
                                      setTasks(tasks.map((x, j) => j === i
                                        ? { ...x, unit_id: v,
                                            location: u ? (u.name
                                              ? `${u.ref} · ${u.name}` : u.ref)
                                              : "" }
                                        : x));
                                    }}
                                    style={{ ...inputStyle, width: 150 }}>
                              <option value="">— unit —</option>
                              {mine.map((u) => (
                                <option key={u.id} value={u.id}>
                                  {u.ref}{u.name ? ` · ${u.name}` : ""}
                                </option>
                              ))}
                              <option value="__other">other location…</option>
                            </select>
                            {other && (
                              <input value={t.location.trim()}
                                     placeholder="where"
                                     onChange={(e) => setTask(i, "location",
                                                              e.target.value)}
                                     style={{ ...inputStyle, width: 110 }} />
                            )}
                          </span>
                        );
                      })()}
                    </td>
                    <td style={td}>
                      {/* Strictly the site's manpower categories (owner) —
                          a legacy/TWS value not in the list stays visible
                          but flagged until corrected */}
                      <select value={t.category}
                              onChange={(e) => setTask(i, "category",
                                                       e.target.value)}
                              style={{ ...inputStyle, width: 150,
                                       background: t.category &&
                                         !categories.some((c) =>
                                           c.name === t.category)
                                         ? "#fff8e6" : "#fff" }}>
                        <option value="">— category —</option>
                        {categories.map((c) => (
                          <option key={c.id} value={c.name}>
                            {c.name}
                            {attendanceIn && presentByCat[c.name] != null
                              ? ` (${presentByCat[c.name]} present)` : ""}
                          </option>
                        ))}
                        {t.category && !categories.some((c) =>
                            c.name === t.category) && (
                          <option value={t.category}>
                            {t.category} (not in category list)
                          </option>
                        )}
                      </select>
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
                    <td style={{ ...td, whiteSpace: "nowrap" }}>
                      <button onClick={() => addCategoryLine(i)}
                              title="Add another manpower category for this task"
                              style={{ ...ghostButton, padding: "2px 8px",
                                       marginRight: 4 }}>
                        ＋ cat
                      </button>
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
      {editable && (
        <button onClick={() => setTasks([...tasks, { ...EMPTY_TASK }])}
                style={{ ...ghostButton, marginTop: 8, fontSize: 13 }}>
          + Add task row
        </button>
      )}

      {attendanceIn && mp.present > 0 && (
        <div style={{ marginTop: 16, maxWidth: 420 }}>
          <h3 style={{ margin: "0 0 2px", fontSize: 14,
                       color: "var(--sp-navy)" }}>
            Manpower at work
          </h3>
          <p style={{ margin: "0 0 6px", fontSize: 11.5, color: "#5a6b78" }}>
            From today's attendance — the crew actually on site. Task
            allocation above may put the same crew on more than one job.
          </p>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>Category</th>
              <th style={{ ...th, textAlign: "right" }}>On site</th>
            </tr></thead>
            <tbody>
              {[...(mp.categories || [])].filter((c) => c.present > 0)
                .sort((a, b) => b.present - a.present).map((c) => (
                  <tr key={c.name}>
                    <td style={td}>{c.name}</td>
                    <td style={{ ...td, textAlign: "right" }}>{c.present}</td>
                  </tr>
                ))}
              <tr style={{ fontWeight: 700 }}>
                <td style={td}>Total</td>
                <td style={{ ...td, textAlign: "right" }}>{mp.present}</td>
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
        {/* A sheet per project for the client team that runs it — the
            general rows ride along on every one. Offered on a locked sheet
            too: that is when the client wants it (owner 2026-09-03). */}
        {doc && [...new Set(tasks.map((t) => t.project).filter(Boolean))]
          .map((code) => (
            <a key={code} target="_blank" rel="noreferrer"
               href={`/api/v1/dma/${doc.ref}/report.pdf?project=${encodeURIComponent(code)}`}
               title={`${code} rows plus the general rows`}
               style={{ ...ghostButton, textDecoration: "none",
                        display: "inline-block" }}>
              ⬇ {code} sheet</a>
          ))}
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
