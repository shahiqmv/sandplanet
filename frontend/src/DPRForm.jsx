import { useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { SectionTitle, buttonStyle, card, ghostButton, inputStyle } from "./ui.jsx";

const WEATHER = ["Sunny", "Cloudy", "Rainy"];

// Site-wide DPR (R8): every work row is tagged with its project (or
// General) and may link to that project's programme activity
const emptyWork = { project: "", activity_id: "", activity: "", trade: "",
                    location: "", progress_today: "", progress_todate: "",
                    remarks: "" };
const emptyMachine = { item: "", nos: "", remarks: "" };
const emptyMaterial = {
  material: "", unit: "", opening: "", received: "", consumed: "", remarks: "",
};

function RowTable({ headers, rows, setRows, empty, render }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h} style={{ textAlign: "left", fontSize: 12,
                                   color: "var(--sp-navy)", padding: 4 }}>
                {h}
              </th>
            ))}
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {render(row, (patch) =>
                setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
              )}
              <td style={{ width: 30 }}>
                <button
                  type="button"
                  onClick={() => setRows(rows.filter((_, j) => j !== i))}
                  style={{ ...ghostButton, padding: "2px 8px", color: "#c0392b" }}
                >
                  ×
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" onClick={() => setRows([...rows, { ...empty }])}
              style={{ ...ghostButton, padding: "4px 12px", marginTop: 6 }}>
        + Add row
      </button>
    </div>
  );
}

function cell(value, onChange, width, type = "text") {
  return (
    <td style={{ padding: 3 }}>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)}
             style={{ ...inputStyle, width: width || "100%" }} />
    </td>
  );
}

export default function DPRForm({ site, projects = [], existing, onSaved,
                                  onCancel }) {
  const p = existing?.payload || {};
  const [docDate, setDocDate] = useState(
    existing?.doc_date || new Date().toISOString().slice(0, 10)
  );
  const [workingHours, setWorkingHours] = useState(
    p.working_hours ||
      `${site.working_hours_from.slice(0, 5)} – ${site.working_hours_to.slice(0, 5)}`
  );
  const [weatherAm, setWeatherAm] = useState(p.weather_am || "Sunny");
  const [weatherPm, setWeatherPm] = useState(p.weather_pm || "Sunny");
  const [rainFrom, setRainFrom] = useState(p.rain_from || "");
  const [rainTo, setRainTo] = useState(p.rain_to || "");
  const [timeLost, setTimeLost] = useState(p.work_time_lost || "");
  const [timeLostCause, setTimeLostCause] = useState(p.time_lost_cause || "");
  const [timeLostReason, setTimeLostReason] = useState(
    p.time_lost_reason || "");
  const [workDone, setWorkDone] = useState(p.work_done?.length ? p.work_done
                                                              : [{ ...emptyWork }]);
  const [machinery, setMachinery] = useState(p.machinery || []);
  const [materials, setMaterials] = useState(p.materials || []);
  // Manpower entry is dynamic rows (owner, R9): pick a category, put a
  // count — no more fixed 17-category grid. Stored shape is unchanged
  // (category id → count), so old DPRs and the PDF are unaffected.
  const [mpRows, setMpRows] = useState(() => {
    const rows = Object.entries(p.manpower || {})
      .filter(([, v]) => parseInt(v, 10) > 0)
      .map(([id, count]) => ({ category_id: id, count }));
    return rows.length ? rows : [{ category_id: "", count: "" }];
  });
  const [mpNotice, setMpNotice] = useState(null);
  const [matters, setMatters] = useState(p.matters_affecting || "");
  const [visitors, setVisitors] = useState(p.visitors_instructions || "");
  const [incident, setIncident] = useState(p.safety?.incident || false);
  const [incidentDetails, setIncidentDetails] = useState(p.safety?.details || "");
  const [categories, setCategories] = useState([]);
  const [programmes, setProgrammes] = useState({});  // project code → acts
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [doc, setDoc] = useState(existing || null);
  const [caption, setCaption] = useState("");
  const [file, setFile] = useState(null);

  const activeProjects = projects.filter((pr) => pr.status === "ACTIVE");

  useEffect(() => {
    api("/manpower-categories").then((all) =>
      setCategories(all.filter((c) => c.list_type === "DPR" && c.is_active))
    );
    Promise.all(activeProjects.map((pr) =>
      api(`/projects/${pr.id}/programme`).then((rows) => [
        pr.code, rows.filter((a) => !a.is_milestone && a.indent > 0),
      ]).catch(() => [pr.code, []])
    )).then((pairs) => setProgrammes(Object.fromEntries(pairs)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects.map((pr) => pr.id).join(",")]);

  const rainy = weatherAm === "Rainy" || weatherPm === "Rainy";
  const manpowerTotal = mpRows
    .reduce((a, r) => a + (parseInt(r.count, 10) || 0), 0);

  function manpowerMap() {
    return Object.fromEntries(mpRows
      .filter((r) => r.category_id && parseInt(r.count, 10) > 0)
      .map((r) => [r.category_id, r.count]));
  }

  const [matNotice, setMatNotice] = useState(null);
  async function loadMajorMaterials() {
    setMatNotice(null);
    try {
      const { materials: major } = await api(
        `/stock/${site.id}/major?date=${docDate}`);
      if (!major.length) {
        setMatNotice("No items are flagged as major materials yet — set the "
                     + "★ flag on the Item Master.");
        return;
      }
      const have = new Set(materials.map((r) =>
        (r.material || "").trim().toLowerCase()));
      const added = major
        .filter((m) => !have.has(m.description.trim().toLowerCase()))
        .map((m) => ({ item_id: m.item_id, material: m.description,
                       unit: m.unit, opening: String(m.on_hand),
                       received: m.received_today
                         ? String(m.received_today) : "",
                       consumed: "", remarks: "" }));
      setMaterials([...materials.filter((r) => r.material), ...added]);
      setMatNotice(`Loaded ${added.length} major material(s). Opening = current `
                   + `stock; today's GRN receipts prefilled. Enter Consumed to `
                   + `draw it down — issuing the DPR posts that to stock.`);
    } catch (e) {
      setMatNotice(e.message);
    }
  }

  async function prefillFromAttendance() {
    setMpNotice(null);
    try {
      const data = await api(`/sites/${site.id}/manpower`);
      if (!data.attendance_entered) {
        setMpNotice("Attendance has not been entered for today yet — "
                    + "record it first, then prefill.");
        return;
      }
      const rows = data.categories
        .filter((c) => c.id && c.present > 0)
        .map((c) => ({ category_id: String(c.id), count: c.present }));
      setMpRows(rows.length ? rows : [{ category_id: "", count: "" }]);
      setMpNotice(`Loaded from attendance: ${data.present} present across `
                  + `${rows.length} categor${rows.length === 1 ? "y" : "ies"}`
                  + ` — adjust if needed.`);
    } catch (e) {
      setMpNotice(e.message);
    }
  }

  function payload() {
    return {
      working_hours: workingHours,
      weather_am: weatherAm,
      weather_pm: weatherPm,
      rain_from: rainy ? rainFrom : "",
      rain_to: rainy ? rainTo : "",
      work_time_lost: timeLost,
      time_lost_cause: timeLost ? timeLostCause : "",
      time_lost_reason: timeLost ? timeLostReason : "",
      work_done: workDone.filter((r) => r.activity),
      manpower: manpowerMap(),
      machinery: machinery.filter((r) => r.item),
      materials: materials
        .filter((r) => r.material)
        .map((r) => ({
          ...r,
          balance:
            (parseFloat(r.opening) || 0) + (parseFloat(r.received) || 0) -
            (parseFloat(r.consumed) || 0),
        })),
      matters_affecting: matters,
      visitors_instructions: visitors,
      safety: { incident, details: incident ? incidentDetails : "" },
    };
  }

  async function saveDraft() {
    setBusy(true);
    setError(null);
    try {
      let saved;
      if (doc) {
        saved = await api(`/documents/${doc.ref}`, {
          method: "PATCH",
          body: { payload: payload(), doc_date: docDate },
        });
      } else {
        saved = await api("/documents", {
          method: "POST",
          body: { doc_type: "DPR", site_id: site.id, doc_date: docDate,
                  payload: payload() },
        });
      }
      setDoc(saved);
      return saved;
    } catch (e) {
      setError(e.message);
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function uploadPhoto() {
    if (!file || !doc) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("kind", "PHOTO");
    fd.append("caption", caption);
    try {
      await apiUpload(`/documents/${doc.ref}/attachments`, fd);
      const fresh = await api(`/documents/${doc.ref}`);
      setDoc(fresh);
      setCaption("");
      setFile(null);
      document.getElementById("dpr-photo-input").value = "";
    } catch (e) {
      setError(e.message);
    }
  }

  function offProgrammeMissingRemark() {
    return workDone.some((r) => {
      const acts = programmes[r.project] || [];
      return r.activity && r.project && acts.length > 0 && !r.activity_id &&
             !String(r.remarks || "").trim();
    });
  }

  async function issue() {
    if (offProgrammeMissingRemark()) {
      setError("An activity not in its project's programme needs a remark "
               + "explaining it before the DPR can be issued.");
      return;
    }
    const saved = await saveDraft();
    if (!saved) return;
    setBusy(true);
    try {
      await api(`/documents/${saved.ref}/actions/issue`, { method: "POST" });
      onSaved(saved.ref);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const photos = (doc?.attachments || []).filter((a) => a.kind === "PHOTO");
  const captioned = photos.filter((a) => a.caption).length;

  const staff = categories.filter((c) => c.grp === "STAFF");
  const labour = categories.filter((c) => c.grp === "LABOUR");

  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <h2 style={{ margin: 0, color: "var(--sp-navy)" }}>
          {doc ? `${doc.ref} (draft)` : "New Daily Progress Report"}
        </h2>
        <button onClick={onCancel} style={ghostButton}>Close</button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12,
                    marginTop: 16 }}>
        <label style={{ fontSize: 13 }}>Date
          <input type="date" value={docDate} disabled={!!doc}
                 onChange={(e) => setDocDate(e.target.value)} style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Working hours
          <input value={workingHours}
                 onChange={(e) => setWorkingHours(e.target.value)} style={inputStyle} />
        </label>
        <label style={{ fontSize: 13 }}>Work time lost (hrs)
          <input value={timeLost} onChange={(e) => setTimeLost(e.target.value)}
                 style={inputStyle} />
        </label>
        {timeLost && (
          <label style={{ fontSize: 13 }}>Time lost — cause
            <select value={timeLostCause}
                    onChange={(e) => setTimeLostCause(e.target.value)}
                    style={inputStyle}>
              <option value="">— select —</option>
              <option value="Rain / weather">Rain / weather</option>
              <option value="Client / consultant instruction">
                Client / consultant instruction</option>
              <option value="Power / utility outage">Power / utility outage</option>
              <option value="Material shortage">Material shortage</option>
              <option value="Other">Other</option>
            </select>
          </label>
        )}
        {timeLost && (
          <label style={{ fontSize: 13 }}>Time lost — details
            <input value={timeLostReason}
                   onChange={(e) => setTimeLostReason(e.target.value)}
                   placeholder="e.g. resort asked to suspend 10:00–12:00 for guest arrival"
                   style={inputStyle} />
          </label>
        )}
        <label style={{ fontSize: 13 }}>Weather AM
          <select value={weatherAm} onChange={(e) => setWeatherAm(e.target.value)}
                  style={inputStyle}>
            {WEATHER.map((w) => <option key={w}>{w}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>Weather PM
          <select value={weatherPm} onChange={(e) => setWeatherPm(e.target.value)}
                  style={inputStyle}>
            {WEATHER.map((w) => <option key={w}>{w}</option>)}
          </select>
        </label>
        {rainy && (
          <label style={{ fontSize: 13 }}>Rained from / to
            <div style={{ display: "flex", gap: 6 }}>
              <input type="time" value={rainFrom}
                     onChange={(e) => setRainFrom(e.target.value)} style={inputStyle} />
              <input type="time" value={rainTo}
                     onChange={(e) => setRainTo(e.target.value)} style={inputStyle} />
            </div>
          </label>
        )}
      </div>

      <SectionTitle>
        1. Work Done Today
        {activeProjects.length > 0 &&
          " — tag each row with its project and programme activity"}
      </SectionTitle>
      <RowTable
        headers={["Project", "Activity / Milestone", "Trade",
                  "Location/Area/Villa", "Today %", "To-date %", "Remarks"]}
        rows={workDone} setRows={setWorkDone} empty={emptyWork}
        render={(row, set) => {
          const acts = programmes[row.project] || [];
          // Off-programme = a project is chosen but the row isn't linked to
          // one of its programme activities. The owner wants this flagged with
          // a caution and an explanatory remark made mandatory.
          const offProgramme = row.project && acts.length > 0 &&
                               !row.activity_id;
          return (
          <>
            <td style={{ padding: 3, verticalAlign: "top" }}>
              <select value={row.project || ""}
                      onChange={(e) => set({ project: e.target.value,
                                             activity_id: "", trade: "" })}
                      style={{ ...inputStyle, width: 110 }}>
                <option value="">General</option>
                {activeProjects.map((pr) => (
                  <option key={pr.id} value={pr.code}>{pr.code}</option>
                ))}
              </select>
            </td>
            <td style={{ padding: 3, minWidth: 200, verticalAlign: "top" }}>
              {acts.length > 0 ? (
                <>
                  <select value={row.activity_id || ""}
                          onChange={(e) => {
                            const act = acts.find(
                              (a) => String(a.id) === e.target.value);
                            set({ activity_id: act ? act.id : "",
                                  activity: act ? act.name : row.activity,
                                  trade: act ? (act.trade || row.trade)
                                             : row.trade,
                                  progress_todate: act && !row.progress_todate
                                    ? act.progress : row.progress_todate });
                          }}
                          style={{ ...inputStyle,
                                   background: row.activity_id
                                     ? "#effaf1" : "#fff8e6" }}>
                    <option value="">— other / not in programme —</option>
                    {acts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name} ({Number(a.progress)}%)
                      </option>
                    ))}
                  </select>
                  {!row.activity_id && (
                    <input value={row.activity} placeholder="Describe the work"
                           onChange={(e) => set({ activity: e.target.value })}
                           style={{ ...inputStyle, marginTop: 4 }} />
                  )}
                  {offProgramme && (
                    <p style={{ margin: "4px 0 0", fontSize: 11,
                                color: "#b35900" }}>
                      ⚠ Not in {row.project}'s programme — add a remark
                      explaining this work.
                    </p>
                  )}
                </>
              ) : (
                <input value={row.activity} placeholder="Activity"
                       onChange={(e) => set({ activity: e.target.value })}
                       style={inputStyle} />
              )}
            </td>
            {cell(row.trade, (v) => set({ trade: v }), 90)}
            {cell(row.location, (v) => set({ location: v }), 120)}
            {cell(row.progress_today, (v) => set({ progress_today: v }), 65,
                  "number")}
            {cell(row.progress_todate, (v) => set({ progress_todate: v }), 65,
                  "number")}
            <td style={{ padding: 3, verticalAlign: "top" }}>
              <input value={row.remarks}
                     onChange={(e) => set({ remarks: e.target.value })}
                     placeholder={offProgramme ? "Required — why off-programme"
                                               : ""}
                     style={{ ...inputStyle, width: 110,
                              border: offProgramme && !row.remarks
                                ? "1.5px solid #d98324" : inputStyle.border }} />
            </td>
          </>
          );
        }}
      />

      <SectionTitle>2. Manpower — total {manpowerTotal}</SectionTitle>
      <div style={{ display: "flex", gap: 8, alignItems: "center",
                    marginBottom: 8 }}>
        <button type="button" onClick={prefillFromAttendance}
                style={{ ...ghostButton, padding: "4px 12px", fontSize: 13 }}>
          ⤵ Prefill from today's attendance
        </button>
        {mpNotice && (
          <span style={{ fontSize: 12, color: mpNotice.startsWith("Loaded")
                           ? "#1a7f37" : "#b35900" }}>{mpNotice}</span>
        )}
      </div>
      {mpRows.map((row, i) => {
        const used = mpRows.map((r) => r.category_id);
        return (
          <div key={i} style={{ display: "flex", gap: 8, alignItems: "center",
                                marginBottom: 6 }}>
            <select value={row.category_id}
                    onChange={(e) => setMpRows(mpRows.map((r, j) =>
                      j === i ? { ...r, category_id: e.target.value } : r))}
                    style={{ ...inputStyle, width: 280 }}>
              <option value="">— category —</option>
              {[["Staff", staff], ["Trades / Labour", labour]].map(
                ([label, list]) => (
                <optgroup key={label} label={label}>
                  {list.map((c) => (
                    <option key={c.id} value={String(c.id)}
                            disabled={used.includes(String(c.id)) &&
                                      String(c.id) !== row.category_id}>
                      {c.name}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            <input type="number" min="0" value={row.count}
                   placeholder="count"
                   onChange={(e) => setMpRows(mpRows.map((r, j) =>
                     j === i ? { ...r, count: e.target.value } : r))}
                   style={{ ...inputStyle, width: 90 }} />
            <button type="button"
                    onClick={() => setMpRows(mpRows.filter((_, j) => j !== i))}
                    style={{ ...ghostButton, padding: "2px 8px",
                             color: "#c0392b" }}>×</button>
          </div>
        );
      })}
      <button type="button"
              onClick={() => setMpRows([...mpRows,
                                        { category_id: "", count: "" }])}
              style={{ ...ghostButton, padding: "4px 12px" }}>
        + Add category
      </button>

      <SectionTitle>3. Machinery &amp; Equipment in Use</SectionTitle>
      <RowTable
        headers={["Item", "Nos", "Remarks (working/idle/breakdown)"]}
        rows={machinery} setRows={setMachinery} empty={emptyMachine}
        render={(row, set) => (
          <>
            {cell(row.item, (v) => set({ item: v }))}
            {cell(row.nos, (v) => set({ nos: v }), 70)}
            {cell(row.remarks, (v) => set({ remarks: v }), 180)}
          </>
        )}
      />

      <SectionTitle>4. Key Materials at Site</SectionTitle>
      <div style={{ display: "flex", gap: 8, alignItems: "center",
                    marginBottom: 8 }}>
        <button type="button" onClick={loadMajorMaterials}
                style={{ ...ghostButton, padding: "4px 12px", fontSize: 13 }}>
          ⤵ Load major materials from stock
        </button>
        {matNotice && (
          <span style={{ fontSize: 12, color: matNotice.startsWith("Loaded")
                           ? "#1a7f37" : "#b35900" }}>{matNotice}</span>
        )}
      </div>
      <RowTable
        headers={["Material", "Unit", "Opening", "Received", "Consumed", "Remarks"]}
        rows={materials} setRows={setMaterials} empty={emptyMaterial}
        render={(row, set) => (
          <>
            {cell(row.material, (v) => set({ material: v }))}
            {cell(row.unit, (v) => set({ unit: v }), 60)}
            {cell(row.opening, (v) => set({ opening: v }), 70, "number")}
            {cell(row.received, (v) => set({ received: v }), 70, "number")}
            {cell(row.consumed, (v) => set({ consumed: v }), 70, "number")}
            {cell(row.remarks, (v) => set({ remarks: v }), 120)}
          </>
        )}
      />

      <SectionTitle>5. Matters Affecting Progress</SectionTitle>
      <textarea value={matters} onChange={(e) => setMatters(e.target.value)}
                rows={3} style={{ ...inputStyle, resize: "vertical" }} />

      <SectionTitle>6. Visitors / Special Events / Instructions</SectionTitle>
      <textarea value={visitors} onChange={(e) => setVisitors(e.target.value)}
                rows={3} style={{ ...inputStyle, resize: "vertical" }} />

      <SectionTitle>7. Safety</SectionTitle>
      <label style={{ fontSize: 14 }}>
        <input type="checkbox" checked={incident}
               onChange={(e) => setIncident(e.target.checked)} />{" "}
        Accident / incident today
      </label>
      {incident && (
        <textarea value={incidentDetails} placeholder="Details / action taken (required)"
                  onChange={(e) => setIncidentDetails(e.target.value)} rows={2}
                  style={{ ...inputStyle, resize: "vertical", marginTop: 8 }} />
      )}

      <SectionTitle>
        Progress Photos — {photos.length} attached
        {photos.length > 0 && ` (${captioned} captioned)`}
      </SectionTitle>
      {!doc && (
        <p style={{ fontSize: 13, color: "#5a6b78" }}>
          Save the draft first, then attach photos.
        </p>
      )}
      {doc && (
        <>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input id="dpr-photo-input" type="file" accept="image/*"
                   onChange={(e) => setFile(e.target.files[0])} />
            <input placeholder="Caption (location / activity)" value={caption}
                   onChange={(e) => setCaption(e.target.value)}
                   style={{ ...inputStyle, width: 260 }} />
            <button type="button" onClick={uploadPhoto}
                    disabled={!file || !caption} style={buttonStyle}>
              Upload
            </button>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 12 }}>
            {photos.map((ph) => (
              <figure key={ph.id} style={{ margin: 0, width: 150 }}>
                <img src={ph.url} alt={ph.caption}
                     style={{ width: "100%", borderRadius: 6,
                              border: "1px solid var(--sp-border)" }} />
                <figcaption style={{ fontSize: 11, color: "#5a6b78" }}>
                  {ph.caption || "(no caption)"}
                </figcaption>
              </figure>
            ))}
          </div>
        </>
      )}

      {error && <p style={{ color: "#c0392b", fontSize: 13 }}>{error}</p>}

      <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
        <button onClick={saveDraft} disabled={busy} style={ghostButton}>
          Save draft
        </button>
        <button onClick={issue} disabled={busy} style={buttonStyle}>
          Issue to client
        </button>
      </div>
    </section>
  );
}
