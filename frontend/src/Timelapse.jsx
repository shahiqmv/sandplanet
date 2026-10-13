import { useCallback, useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";

// Site time-lapse (owner 2026-10-13). The Brinno cameras record to an SD
// card; each week someone uploads that week's video here. A background job
// converts it and joins it onto the camera's one continuous video — the
// thing people watch. "Per week videos will be messy", so the weekly
// uploads sit behind a toggle as the record of what went in.

function fmt(d) {
  if (!d) return "";
  const x = new Date(d);
  return Number.isNaN(x.getTime()) ? String(d)
    : x.toLocaleDateString("en-GB", { day: "2-digit", month: "short",
                                       year: "numeric" });
}
function mins(s) {
  if (s == null) return "";
  const n = Math.round(Number(s));
  return n >= 60 ? `${Math.floor(n / 60)} min ${n % 60} s` : `${n} s`;
}
const iso = (d) => (d ? new Date(d).toISOString().slice(0, 10) : "");

function SiteField({ d, siteId, setSiteId }) {
  const sites = d.sites || [];
  if (d.site_locked) {
    const s = sites[0];
    return (
      <label style={{ fontSize: 12.5 }}>Site
        <div style={{ ...inputStyle, background: "#f3f5f8", color: "#334" }}>
          {s ? `${s.code} — ${s.name}` : "—"}</div></label>);
  }
  return (
    <label style={{ fontSize: 12.5 }}>Site
      <select style={inputStyle} value={siteId}
        onChange={(e) => setSiteId(e.target.value)}>
        <option value="">Choose…</option>
        {sites.map((s) => <option key={s.id} value={s.id}>{s.code} — {s.name}</option>)}
      </select></label>);
}

const camText = (c) => [c.project_code || "whole site", c.location]
  .filter(Boolean).join(" · ");

function Upload({ d, onDone, onCancel }) {
  const [siteId, setSiteId] = useState(d.default_site_id || "");
  const [camId, setCamId] = useState("");
  const [from, setFrom] = useState(iso(d.last_week?.from));
  const [to, setTo] = useState(iso(d.last_week?.to));
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const cams = (d.cameras || []).filter(
    (c) => c.is_active && String(c.site_id) === String(siteId));
  const cam = cams.find((c) => String(c.id) === String(camId));
  // one camera on the site — nothing to choose
  useEffect(() => {
    setCamId(cams.length === 1 ? String(cams[0].id) : "");
  }, [siteId, cams.length]); // eslint-disable-line react-hooks/exhaustive-deps

  async function send() {
    if (!cam || !file) {
      setError("Pick the camera and attach the video.");
      return;
    }
    setBusy(true); setError(null);
    try {
      const fd = new FormData();
      fd.append("camera_id", cam.id);
      fd.append("week_from", from);
      fd.append("week_to", to);
      fd.append("file", file);
      await apiUpload("/timelapses", fd, "POST");
      onDone();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div style={{ ...card, marginBottom: 14 }}>
      <h3 style={{ marginTop: 0, fontSize: 15 }}>Upload this week's time-lapse</h3>
      <p style={{ fontSize: 12.5, color: "#667", marginTop: 0 }}>
        Copy the video off the camera's card and upload it as it is — the AVI
        file is fine. It is joined onto the camera's video within about ten
        minutes.</p>
      <div style={{ display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fill,minmax(200px,1fr))" }}>
        <SiteField d={d} siteId={siteId} setSiteId={setSiteId} />
        <label style={{ fontSize: 12.5, gridColumn: "1 / -1" }}>Camera
          <select style={inputStyle} value={camId} disabled={!siteId}
            onChange={(e) => setCamId(e.target.value)}>
            <option value="">{siteId ? "Choose…" : "Choose the site first"}</option>
            {cams.map((c) => <option key={c.id} value={c.id}>
              {c.name} — {camText(c)}</option>)}
          </select></label>
        <label style={{ fontSize: 12.5 }}>Week from
          <input type="date" style={inputStyle} value={from}
            onChange={(e) => setFrom(e.target.value)} /></label>
        <label style={{ fontSize: 12.5 }}>to
          <input type="date" style={inputStyle} value={to}
            onChange={(e) => setTo(e.target.value)} /></label>
        <label style={{ fontSize: 12.5, gridColumn: "1 / -1" }}>Video
          <input type="file" accept="video/*,.avi" style={{ display: "block", marginTop: 4 }}
            onChange={(e) => setFile(e.target.files?.[0] || null)} /></label>
      </div>
      {siteId && cams.length === 0 && (
        <p style={{ fontSize: 13, color: "#8a5200" }}>
          No time-lapse camera is registered for this site yet. The PM
          registers it under Cameras below — its project and where it is
          mounted — and it then appears here.</p>)}
      {cam && (
        <p style={{ fontSize: 12.5, color: "#556", margin: "8px 0 0" }}>
          {cam.project_code ? `${cam.project_code} — ${cam.project_title}`
                            : "Whole site"} · {cam.location}</p>)}
      {error && <p style={{ color: "#b00", fontSize: 13 }}>{error}</p>}
      <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
        <Btn variant="primary" disabled={busy || !cam} onClick={send}>
          {busy ? "Uploading…" : "Upload"}</Btn>
        <Btn variant="ghost" onClick={onCancel}>Cancel</Btn>
      </div>
    </div>
  );
}

// The camera register — like the live cameras: which site, which project,
// where it is mounted. Uploads pick from it.
function CameraForm({ d, cam, onDone, onCancel }) {
  const [siteId, setSiteId] = useState(cam ? cam.site_id : d.default_site_id || "");
  const [name, setName] = useState(cam?.name || "");
  const [project, setProject] = useState(
    cam ? (cam.project_id ? String(cam.project_id) : "site") : "");
  const [location, setLocation] = useState(cam?.location || "");
  const [error, setError] = useState(null);
  const site = (d.sites || []).find((s) => String(s.id) === String(siteId));
  const projects = site?.projects || [];

  async function save() {
    if (!siteId || !name.trim() || !project || !location.trim()) {
      setError("Give the site, a name, the project and where it is mounted.");
      return;
    }
    const body = { name, location,
                   project_id: project === "site" ? null : project };
    try {
      if (cam) await api(`/timelapse-cameras/${cam.id}`, { method: "PATCH", body });
      else await api("/timelapse-cameras", { method: "POST",
                                             body: { ...body, site_id: siteId } });
      onDone();
    } catch (e) { setError(e.message); }
  }

  return (
    <div style={{ ...card, margin: "8px 0 12px" }}>
      <h3 style={{ marginTop: 0, fontSize: 15 }}>
        {cam ? `Edit ${cam.name}` : "Register a time-lapse camera"}</h3>
      <div style={{ display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fill,minmax(200px,1fr))" }}>
        {cam ? (
          <label style={{ fontSize: 12.5 }}>Site
            <div style={{ ...inputStyle, background: "#f3f5f8" }}>{cam.site_code}</div></label>
        ) : (
          <SiteField d={d} siteId={siteId}
            setSiteId={(v) => { setSiteId(v); setProject(""); }} />)}
        <label style={{ fontSize: 12.5 }}>Name
          <input style={inputStyle} value={name} placeholder="e.g. Brinno 1"
            onChange={(e) => setName(e.target.value)} /></label>
        <label style={{ fontSize: 12.5 }}>Project it watches
          <select style={inputStyle} value={project} disabled={!site}
            onChange={(e) => setProject(e.target.value)}>
            <option value="">Choose…</option>
            {projects.map((p) => <option key={p.id} value={p.id}>
              {p.code} — {p.title}</option>)}
            <option value="site">Whole site (several projects)</option>
          </select></label>
        <label style={{ fontSize: 12.5, gridColumn: "1 / -1" }}>Where it is mounted and what it looks at
          <input style={inputStyle} value={location}
            placeholder="e.g. Jetty head pole, facing villas 20–30"
            onChange={(e) => setLocation(e.target.value)} /></label>
      </div>
      {error && <p style={{ color: "#b00", fontSize: 13 }}>{error}</p>}
      <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
        <Btn variant="primary" onClick={save}>Save</Btn>
        <Btn variant="ghost" onClick={onCancel}>Cancel</Btn>
      </div>
    </div>
  );
}

function CameraRegister({ d, reload, setError }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);        // camera or "new"
  const cams = d.cameras || [];

  async function patch(c, body) {
    try { await api(`/timelapse-cameras/${c.id}`, { method: "PATCH", body }); reload(); }
    catch (e) { setError(e.message); }
  }
  async function remove(c) {
    if (!window.confirm(`Remove ${c.name} from the register?`)) return;
    try { await api(`/timelapse-cameras/${c.id}`, { method: "DELETE" }); reload(); }
    catch (e) { setError(e.message); }
  }

  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <button onClick={() => setOpen((v) => !v)}
          style={{ border: "none", background: "none", cursor: "pointer",
                   color: "var(--navy, #1f3a52)", fontSize: 13, padding: 0 }}>
          {open ? "▾" : "▸"} Cameras ({cams.filter((c) => c.is_active).length})</button>
        {d.can_manage_cameras && (
          <Btn variant="secondary" onClick={() => { setOpen(true); setEditing("new"); }}>
            + Register camera</Btn>)}
      </div>
      {editing && <CameraForm d={d} cam={editing === "new" ? null : editing}
        onCancel={() => setEditing(null)}
        onDone={() => { setEditing(null); reload(); }} />}
      {open && (cams.length === 0 ? (
        <p style={{ fontSize: 13, color: "#667" }}>No time-lapse camera registered yet.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13, marginTop: 6 }}>
            <thead><tr>
              <th style={th}>Camera</th><th style={th}>Project</th>
              <th style={th}>Mounted at</th><th style={th}>Weeks</th>
              <th style={th}></th></tr></thead>
            <tbody>
              {cams.map((c) => (
                <tr key={c.id} style={{ opacity: c.is_active ? 1 : 0.55 }}>
                  <td style={td}><strong>{c.site_code} · {c.name}</strong>
                    {!c.is_active && <> <Chip tone="muted">retired</Chip></>}</td>
                  <td style={td}>{c.project_code
                    ? <>{c.project_code}<div style={{ color: "#889", fontSize: 11.5 }}>
                        {c.project_title}</div></>
                    : "Whole site"}</td>
                  <td style={td}>{c.location}</td>
                  <td style={td}>{c.uploads}</td>
                  <td style={{ ...td, whiteSpace: "nowrap" }}>
                    {d.can_manage_cameras && (<>
                      <Btn variant="ghost" onClick={() => setEditing(c)}>Edit</Btn>
                      <Btn variant="ghost" onClick={() => patch(c, { is_active: !c.is_active })}>
                        {c.is_active ? "Retire" : "Bring back"}</Btn>
                      {c.uploads === 0 && (
                        <Btn variant="ghost" onClick={() => remove(c)}>Remove</Btn>)}
                    </>)}
                  </td>
                </tr>))}
            </tbody>
          </table>
        </div>))}
    </div>
  );
}

export default function TimelapseSection() {
  const [d, setD] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [showWeeks, setShowWeeks] = useState(false);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    api("/timelapses").then(setD).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { load(); }, [load]);

  async function publish(reel, on) {
    try { await api(`/timelapse-reels/${reel.id}`, { method: "PATCH",
                                                      body: { client_visible: on } });
          load(); }
    catch (e) { setError(e.message); }
  }
  async function removeWeek(u) {
    if (!window.confirm(`Remove the ${fmt(u.week_from)} week? The camera's video is rebuilt without it.`)) return;
    try { await api(`/timelapses/${u.id}`, { method: "DELETE" }); load(); }
    catch (e) { setError(e.message); }
  }

  if (!d) return null;
  const reels = d.reels || [];
  return (
    <div style={{ marginTop: 28 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    marginBottom: 10 }}>
        <h2 style={{ margin: 0 }}>Time-lapse</h2>
        <span style={{ color: "#667", fontSize: 13 }}>
          one continuous video per camera, a week added at a time</span>
        <div style={{ flex: 1 }} />
        {d.can_upload && !uploading && (
          <Btn variant="primary" onClick={() => setUploading(true)}>
            ⬆ Upload this week</Btn>)}
      </div>
      {error && <p style={{ color: "#b00", fontSize: 13 }}>{error}</p>}
      {d.behind?.length > 0 && (
        <p style={{ fontSize: 12.5, color: "#8a5200", margin: "0 0 10px" }}>
          Last week ({fmt(d.last_week.from)} – {fmt(d.last_week.to)}) is not in
          yet for: {d.behind.join(", ")}</p>)}
      {uploading && <Upload d={d}
        onCancel={() => setUploading(false)}
        onDone={() => { setUploading(false); load(); }} />}

      {reels.length === 0 && !uploading && (
        <div style={card}><p style={{ margin: 0, color: "#667" }}>
          No time-lapse yet. Register the camera under Cameras, then upload
          the first week's video from its card.</p></div>)}

      <div style={{ display: "grid", gap: 14,
                    gridTemplateColumns: "repeat(auto-fill,minmax(360px,1fr))" }}>
        {reels.map((r) => (
          <div key={r.id} style={card}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8,
                          flexWrap: "wrap" }}>
              <strong>{r.site_code} · {r.camera_label}</strong>
              {!r.camera_active && <Chip tone="muted">retired</Chip>}
              {r.client_visible
                ? <Chip tone="ok">on client portal</Chip>
                : <Chip tone="info">internal</Chip>}
              {r.waiting > 0 && <Chip tone="warn">
                {r.waiting} week{r.waiting > 1 ? "s" : ""} being joined</Chip>}
            </div>
            <div style={{ fontSize: 12.5, color: "#556", marginTop: 3 }}>
              {r.project_code ? `${r.project_code} — ${r.project_title}` : "Whole site"}
              {r.location && ` · ${r.location}`}</div>
            {r.play_url ? (
              <video src={r.play_url} controls preload="metadata"
                style={{ width: "100%", marginTop: 8, borderRadius: 6,
                         background: "#000" }} />
            ) : (
              <p style={{ fontSize: 13, color: "#667" }}>
                The first week is being prepared — it appears here within
                about ten minutes.</p>
            )}
            {r.weeks > 0 && (
              <div style={{ fontSize: 12.5, color: "#667", marginTop: 6 }}>
                {fmt(r.covers_from)} – {fmt(r.covers_to)} · {r.weeks} week
                {r.weeks > 1 ? "s" : ""} · {mins(r.duration_s)}
              </div>)}
            {d.can_publish && r.play_url && (
              <div style={{ marginTop: 8 }}>
                <Btn variant="secondary" onClick={() => publish(r, !r.client_visible)}>
                  {r.client_visible ? "Take off the client portal"
                                    : "Show on the client portal"}</Btn>
              </div>)}
          </div>
        ))}
      </div>

      <CameraRegister d={d} reload={load} setError={setError} />

      {(d.uploads || []).length > 0 && (
        <div style={{ marginTop: 14 }}>
          <button onClick={() => setShowWeeks((v) => !v)}
            style={{ border: "none", background: "none", cursor: "pointer",
                     color: "var(--navy, #1f3a52)", fontSize: 13, padding: 0 }}>
            {showWeeks ? "▾" : "▸"} Weekly uploads ({d.uploads.length})</button>
          {showWeeks && (
            <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 13, marginTop: 6 }}>
              <thead><tr>
                <th style={th}>Week</th><th style={th}>Camera</th>
                <th style={th}>Status</th><th style={th}>Uploaded by</th>
                <th style={th}></th></tr></thead>
              <tbody>
                {d.uploads.map((u) => (
                  <tr key={u.id}>
                    <td style={td}>{fmt(u.week_from)} – {fmt(u.week_to)}</td>
                    <td style={td}>{u.site_code} · {u.camera_label}</td>
                    <td style={td}>{u.status_label}
                      {u.error && <div style={{ color: "#b00", fontSize: 11.5 }}>{u.error}</div>}</td>
                    <td style={td}>{u.uploaded_by}
                      <div style={{ color: "#889", fontSize: 11.5 }}>{fmt(u.created_at)}</div></td>
                    <td style={td}>
                      <button onClick={() => removeWeek(u)} title="Remove this week"
                        style={{ border: "none", background: "none",
                                 cursor: "pointer", color: "#b00" }}>✕</button></td>
                  </tr>))}
              </tbody>
            </table>)}
        </div>)}
    </div>
  );
}
