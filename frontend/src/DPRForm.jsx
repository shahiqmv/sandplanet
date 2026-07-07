import { useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { SectionTitle, buttonStyle, card, ghostButton, inputStyle } from "./ui.jsx";

const WEATHER = ["Sunny", "Cloudy", "Rainy"];

const emptyWork = { activity: "", location: "", progress_pct: "", remarks: "" };
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

export default function DPRForm({ site, existing, onSaved, onCancel }) {
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
  const [workDone, setWorkDone] = useState(p.work_done?.length ? p.work_done
                                                              : [{ ...emptyWork }]);
  const [machinery, setMachinery] = useState(p.machinery || []);
  const [materials, setMaterials] = useState(p.materials || []);
  const [manpower, setManpower] = useState(p.manpower || {});
  const [matters, setMatters] = useState(p.matters_affecting || "");
  const [visitors, setVisitors] = useState(p.visitors_instructions || "");
  const [incident, setIncident] = useState(p.safety?.incident || false);
  const [incidentDetails, setIncidentDetails] = useState(p.safety?.details || "");
  const [categories, setCategories] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [doc, setDoc] = useState(existing || null);
  const [caption, setCaption] = useState("");
  const [file, setFile] = useState(null);

  useEffect(() => {
    api("/manpower-categories").then((all) =>
      setCategories(all.filter((c) => c.list_type === "DPR" && c.is_active))
    );
  }, []);

  const rainy = weatherAm === "Rainy" || weatherPm === "Rainy";
  const manpowerTotal = Object.values(manpower)
    .reduce((a, b) => a + (parseInt(b, 10) || 0), 0);

  function payload() {
    return {
      working_hours: workingHours,
      weather_am: weatherAm,
      weather_pm: weatherPm,
      rain_from: rainy ? rainFrom : "",
      rain_to: rainy ? rainTo : "",
      work_time_lost: timeLost,
      work_done: workDone.filter((r) => r.activity),
      manpower,
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

  async function issue() {
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

      <SectionTitle>1. Work Done Today</SectionTitle>
      <RowTable
        headers={["Activity", "Location/Area/Villa", "Progress %", "Remarks"]}
        rows={workDone} setRows={setWorkDone} empty={emptyWork}
        render={(row, set) => (
          <>
            {cell(row.activity, (v) => set({ activity: v }))}
            {cell(row.location, (v) => set({ location: v }), 140)}
            {cell(row.progress_pct, (v) => set({ progress_pct: v }), 70)}
            {cell(row.remarks, (v) => set({ remarks: v }), 140)}
          </>
        )}
      />

      <SectionTitle>2. Manpower — total {manpowerTotal}</SectionTitle>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        {[["Staff", staff], ["Trades / Labour", labour]].map(([label, list]) => (
          <div key={label}>
            <strong style={{ fontSize: 13, color: "var(--sp-navy)" }}>{label}</strong>
            {list.map((c) => (
              <div key={c.id} style={{ display: "flex", justifyContent:
                   "space-between", alignItems: "center", padding: "2px 0" }}>
                <span style={{ fontSize: 13 }}>{c.name}</span>
                <input type="number" min="0"
                       value={manpower[c.id] ?? ""}
                       onChange={(e) => setManpower({ ...manpower,
                                                      [c.id]: e.target.value })}
                       style={{ ...inputStyle, width: 70 }} />
              </div>
            ))}
          </div>
        ))}
      </div>

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
        Progress Photos — {captioned} of 4 required captioned photos
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
        <button onClick={issue} disabled={busy || captioned < 4} style={buttonStyle}
                title={captioned < 4 ? "Needs 4 captioned photos" : ""}>
          Issue to client
        </button>
      </div>
    </section>
  );
}
