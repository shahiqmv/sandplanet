import { useCallback, useEffect, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";

// Site time-lapse (owner 2026-10-13). The Brinno cameras record to an SD
// card; each week someone uploads that week's video — or its daily clips —
// here. A background job
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

const MAX_BYTES = 4 * 1024 ** 3;     // the server's limit, checked before sending
const gb = (b) => (b >= 1024 ** 3 ? `${(b / 1024 ** 3).toFixed(2)} GB`
  : `${Math.max(1, Math.round(b / 1024 ** 2))} MB`);

const camText = (c) => [c.project_code || "whole site", c.location]
  .filter(Boolean).join(" · ");

// The day a clip covers, from when the camera finished writing it — a
// daily clip's file is dated the day it was recorded (copying off the card
// keeps that date). Shown for checking, never trusted blind.
const fileDay = (f) => {
  const t = new Date(f.lastModified || Date.now());
  const p = (n) => String(n).padStart(2, "0");
  return `${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())}`;
};

// Who this file is, however it was renamed: its size and three samples, so a
// 2 GB clip is known in a moment without reading all of it. The server refuses
// a fingerprint it has already saved (owner 2026-11-02). Blank where the browser
// cannot hash (plain http); name and dates are then all the server has to go on.
async function fingerprint(file) {
  if (!window.crypto?.subtle) return "";
  const n = 4 * 1024 * 1024;
  const mid = Math.max(0, Math.floor(file.size / 2) - n / 2);
  const parts = [file.slice(0, n), file.slice(mid, mid + n),
                 file.slice(Math.max(0, file.size - n))];
  const bytes = await new Blob([String(file.size), ...parts]).arrayBuffer();
  const hash = await window.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Upload what is on the card: one video for the week, or one clip a day —
// some cameras save a clip every 24 hours, seven a week (owner 2026-11-01).
// Several files each become their own upload for their own day, sent one
// after another, and the camera's video joins them in date order.
function Upload({ d, onDone, onCancel }) {
  const [siteId, setSiteId] = useState(d.default_site_id || "");
  const [camId, setCamId] = useState("");
  const [from, setFrom] = useState(iso(d.last_week?.from));
  const [to, setTo] = useState(iso(d.last_week?.to));
  // [{file, day, state: "" | "sending" | "done" | "failed" | "repeat", error}]
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const cams = (d.cameras || []).filter(
    (c) => c.is_active && String(c.site_id) === String(siteId));
  const cam = cams.find((c) => String(c.id) === String(camId));
  // one camera on the site — nothing to choose
  useEffect(() => {
    setCamId(cams.length === 1 ? String(cams[0].id) : "");
  }, [siteId, cams.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const [progress, setProgress] = useState(null);   // {i, of, part} while sending
  // tells this page's own retry from a second page sending the same clip
  const [pageId] = useState(() => Math.random().toString(36).slice(2));
  const daily = items.length > 1;
  const tooBig = items.filter((it) => it.file.size > MAX_BYTES);
  const today = new Date().toISOString().slice(0, 10);

  function pick(list) {
    const files = Array.from(list || []);
    setError(null);
    setItems(files.map((f) => ({ file: f, day: fileDay(f), state: "",
                                  error: "" }))
      .sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1
        : a.file.name.localeCompare(b.file.name))));
  }
  const setDay = (i, day) => setItems((xs) => xs.map((x, j) =>
    (j === i ? { ...x, day } : x)));
  const mark = (i, patch) => setItems((xs) => xs.map((x, j) =>
    (j === i ? { ...x, ...patch } : x)));

  // A video runs to gigabytes: it goes up in 8 MB pieces, each its own short
  // request and retried on its own, so a dropped island link costs one piece
  // rather than the whole upload (owner 2026-10-27, SJR's 2 GB).
  async function sendOne(file, wf, wt, onPart) {
    const start = await api("/timelapses/uploads", { method: "POST", body: {
      camera_id: cam.id, week_from: wf, week_to: wt,
      file_name: file.name, size: file.size,
      fingerprint: await fingerprint(file), client: pageId } });
    const size = start.chunk_size;
    const n = Math.max(1, Math.ceil(file.size / size));
    for (let i = 0; i < n; i += 1) {
      const fd = new FormData();
      fd.append("index", String(i));
      fd.append("chunk", file.slice(i * size, Math.min(file.size, (i + 1) * size)), "chunk");
      for (let attempt = 1; ; attempt += 1) {
        try {
          await apiUpload(`/timelapses/uploads/${start.token}/chunk`, fd, "POST", { quiet: true });
          break;
        } catch (e) {
          if (attempt >= 5 || (e.status && e.status < 500)) throw e;
          await new Promise((r) => setTimeout(r, 2000 * attempt));   // the link came back?
        }
      }
      onPart((i + 1) / n);
    }
    await api(`/timelapses/uploads/${start.token}/finish`, { method: "POST", body: {} });
  }

  async function send() {
    if (!cam || !items.length) {
      setError("Pick the camera and attach the video.");
      return;
    }
    if (tooBig.length) return;
    if (daily && items.some((it) => !it.day || it.day > today)) {
      setError("Give every clip the day it covers — none can be in the future.");
      return;
    }
    setBusy(true); setError(null);
    let failed = 0;
    const repeats = [];
    // in date order, so clips of the same day join in the order picked
    for (let i = 0; i < items.length; i += 1) {
      const it = items[i];
      if (it.state === "done" || it.state === "repeat") continue;
      mark(i, { state: "sending", error: "" });
      setProgress({ i: i + 1, of: items.length, part: 0 });
      try {
        await sendOne(it.file, daily ? it.day : from, daily ? it.day : to,
          (part) => setProgress({ i: i + 1, of: items.length, part }));
        mark(i, { state: "done" });
      } catch (e) {
        // already here: nothing to retry, and the reason must stay on screen
        if (e.status === 409) {
          repeats.push(e.message);
          mark(i, { state: "repeat", error: e.message });
          continue;
        }
        failed += 1;
        mark(i, { state: "failed", error: e.message });
        if (!daily) setError(e.message);
      }
    }
    setBusy(false); setProgress(null);
    if (repeats.length) setError(repeats.join(" "));
    else if (!failed) onDone();
    else if (daily) {
      setError(`${failed} of ${items.length} clips did not go up — press `
        + "Upload again to send just those; the rest are saved.");
    }
  }

  const label = () => {
    if (!busy) {
      const left = items.filter((it) => it.state !== "done"
        && it.state !== "repeat").length;
      return daily && left < items.length ? `Upload the ${left} left`
        : daily ? `Upload ${items.length} clips` : "Upload";
    }
    if (!progress || progress.part >= 1) return "Saving…";
    const pct = `${Math.floor(progress.part * 100)}%`;
    return daily ? `Clip ${progress.i} of ${progress.of} · ${pct}`
      : `Uploading ${pct} of ${gb(items[0].file.size)}`;
  };

  return (
    <div style={{ ...card, marginBottom: 14 }}>
      <h3 style={{ marginTop: 0, fontSize: 15 }}>Upload time-lapse from the camera's card</h3>
      <p style={{ fontSize: 12.5, color: "#667", marginTop: 0 }}>
        Copy the video off the card and upload it as it is — the AVI or MP4,
        up to 4 GB a file. A camera that saves one clip a day: pick all of
        the week's clips together, and each goes in for its own day. Keep
        this page open while it sends; it is joined onto the camera's video
        within about ten minutes.</p>
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
        <label style={{ fontSize: 12.5, gridColumn: "1 / -1" }}>Video — one file,
          or every clip of the week
          <input type="file" accept="video/*,.avi" multiple disabled={busy}
            style={{ display: "block", marginTop: 4 }}
            onChange={(e) => pick(e.target.files)} />
          {items.length === 1 && (
            <span style={{ fontSize: 12, color: tooBig.length ? "#b00" : "#667" }}>
              {gb(items[0].file.size)}{tooBig.length ? " — over the 4 GB limit: split the week on the card and upload it in two" : ""}</span>)}
        </label>
        {!daily && (<>
          <label style={{ fontSize: 12.5 }}>Covers from
            <input type="date" style={inputStyle} value={from}
              onChange={(e) => setFrom(e.target.value)} /></label>
          <label style={{ fontSize: 12.5 }}>to
            <input type="date" style={inputStyle} value={to}
              onChange={(e) => setTo(e.target.value)} /></label>
        </>)}
      </div>
      {daily && (
        <div style={{ marginTop: 10, overflowX: "auto" }}>
          <p style={{ fontSize: 12.5, color: "#556", margin: "0 0 6px" }}>
            {items.length} clips — each dated by when the camera saved it.
            Check the days; change any that are wrong.</p>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead><tr><th style={th}>Clip</th><th style={th}>Size</th>
              <th style={th}>Day it covers</th><th style={th}></th></tr></thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={`${it.file.name}-${i}`}>
                  <td style={td}>{it.file.name}</td>
                  <td style={{ ...td, color: it.file.size > MAX_BYTES ? "#b00" : undefined }}>
                    {gb(it.file.size)}{it.file.size > MAX_BYTES ? " — over 4 GB" : ""}</td>
                  <td style={td}>
                    <input type="date" style={{ ...inputStyle, width: 150 }}
                      value={it.day} max={today}
                      disabled={busy || it.state === "done"}
                      onChange={(e) => setDay(i, e.target.value)} /></td>
                  <td style={{ ...td, fontSize: 12, whiteSpace: "nowrap" }}>
                    {it.state === "done" && <span style={{ color: "#1d7a3a" }}>✓ saved</span>}
                    {it.state === "sending" && <span style={{ color: "#556" }}>sending…</span>}
                    {it.state === "repeat" && (
                      <span style={{ color: "#8a6d00" }} title={it.error}>not sent — a repeat</span>)}
                    {it.state === "failed" && (
                      <span style={{ color: "#b00" }} title={it.error}>did not go up</span>)}
                  </td>
                </tr>))}
            </tbody>
          </table>
        </div>)}
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
        <Btn variant="primary" disabled={busy || !cam || !items.length
          || tooBig.length > 0} onClick={send}>{label()}</Btn>
        <Btn variant="ghost" disabled={busy} onClick={() => {
          if (items.some((it) => it.state === "done")) onDone(); else onCancel();
        }}>{items.some((it) => it.state === "done") ? "Close" : "Cancel"}</Btn>
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
  // The public link, for a client whose portal is not live yet.
  async function shareLink(reel, on) {
    if (!on && !window.confirm("Stop this link? Anyone who has it can no longer "
        + "open the video, and a new link would be a different address.")) return;
    try { await api(`/timelapse-reels/${reel.id}/share`, { method: "POST",
                                                           body: { on } });
          load(); }
    catch (e) { setError(e.message); }
  }
  async function removeWeek(u) {
    if (!window.confirm(`Remove the upload for ${fmt(u.week_from)}${u.week_to !== u.week_from ? ` – ${fmt(u.week_to)}` : ""}? The camera's video is rebuilt without it.`)) return;
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
          one continuous video per camera, each upload joined on in date order</span>
        <div style={{ flex: 1 }} />
        {d.can_upload && !uploading && (
          <Btn variant="primary" onClick={() => setUploading(true)}>
            ⬆ Upload time-lapse</Btn>)}
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
          the first video from its card.</p></div>)}

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
                {r.waiting} upload{r.waiting > 1 ? "s" : ""} being joined</Chip>}
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
                The first upload is being prepared — it appears here within
                about ten minutes.</p>
            )}
            {r.weeks > 0 && (
              <div style={{ fontSize: 12.5, color: "#667", marginTop: 6 }}>
                {fmt(r.covers_from)} – {fmt(r.covers_to)} · {r.weeks} upload
                {r.weeks > 1 ? "s" : ""} · {mins(r.duration_s)}
              </div>)}
            {d.can_publish && r.play_url && (
              <div style={{ marginTop: 8 }}>
                <Btn variant="secondary" onClick={() => publish(r, !r.client_visible)}>
                  {r.client_visible ? "Take off the client portal"
                                    : "Show on the client portal"}</Btn>{" "}
                {!r.share_url && (
                  <Btn variant="secondary" onClick={() => shareLink(r, true)}>
                    Create a share link</Btn>)}
                {r.share_url && (
                  <div style={{ marginTop: 8, fontSize: 12.5 }}>
                    <div style={{ color: "#667", marginBottom: 4 }}>
                      Anyone with this link can watch this video, with no sign-in.
                      It always shows the latest video.</div>
                    <input readOnly value={r.share_url} aria-label="Share link"
                      onFocus={(e) => e.target.select()}
                      style={{ width: "100%", padding: "4px 8px", fontSize: 12.5,
                               marginBottom: 6, boxSizing: "border-box" }} />
                    <Btn variant="secondary" onClick={() =>
                      navigator.clipboard?.writeText(r.share_url)}>Copy link</Btn>{" "}
                    <Btn variant="ghost" onClick={() => shareLink(r, false)}>
                      Stop sharing</Btn>
                  </div>)}
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
            {showWeeks ? "▾" : "▸"} Uploads ({d.uploads.length})</button>
          {showWeeks && (
            <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 13, marginTop: 6 }}>
              <thead><tr>
                <th style={th}>Covers</th><th style={th}>Camera</th>
                <th style={th}>Status</th><th style={th}>Uploaded by</th>
                <th style={th}></th></tr></thead>
              <tbody>
                {d.uploads.map((u) => (
                  <tr key={u.id}>
                    <td style={td}>{fmt(u.week_from)}
                      {u.week_to !== u.week_from && ` – ${fmt(u.week_to)}`}</td>
                    <td style={td}>{u.site_code} · {u.camera_label}</td>
                    <td style={td}>{u.status_label}
                      {u.error && <div style={{ color: "#b00", fontSize: 11.5 }}>{u.error}</div>}</td>
                    <td style={td}>{u.uploaded_by}
                      <div style={{ color: "#889", fontSize: 11.5 }}>{fmt(u.created_at)}</div></td>
                    <td style={td}>
                      <button onClick={() => removeWeek(u)} title="Remove this upload"
                        style={{ border: "none", background: "none",
                                 cursor: "pointer", color: "#b00" }}>✕</button></td>
                  </tr>))}
              </tbody>
            </table>)}
        </div>)}
    </div>
  );
}
