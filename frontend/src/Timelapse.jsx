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

function Upload({ sites, reels, lastWeek, onDone, onCancel }) {
  const [siteId, setSiteId] = useState(sites.length === 1 ? sites[0].id : "");
  const [label, setLabel] = useState("");
  const [from, setFrom] = useState(iso(lastWeek?.from));
  const [to, setTo] = useState(iso(lastWeek?.to));
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const known = reels.filter((r) => String(r.site_id) === String(siteId))
    .map((r) => r.camera_label);

  async function send() {
    if (!siteId || !label.trim() || !file) {
      setError("Choose the site, name the camera and attach the video.");
      return;
    }
    setBusy(true); setError(null);
    try {
      const fd = new FormData();
      fd.append("site_id", siteId);
      fd.append("camera_label", label.trim());
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
        <label style={{ fontSize: 12.5 }}>Site
          <select style={inputStyle} value={siteId}
            onChange={(e) => { setSiteId(e.target.value); setLabel(""); }}>
            <option value="">Choose…</option>
            {sites.map((s) => <option key={s.id} value={s.id}>{s.code} — {s.name}</option>)}
          </select></label>
        <label style={{ fontSize: 12.5 }}>Camera
          <input style={inputStyle} value={label} list="tl-cams"
            placeholder="e.g. Brinno — north side"
            onChange={(e) => setLabel(e.target.value)} />
          <datalist id="tl-cams">{known.map((k) => <option key={k} value={k} />)}</datalist>
        </label>
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
      {error && <p style={{ color: "#b00", fontSize: 13 }}>{error}</p>}
      <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
        <Btn variant="primary" disabled={busy} onClick={send}>
          {busy ? "Uploading…" : "Upload"}</Btn>
        <Btn variant="ghost" onClick={onCancel}>Cancel</Btn>
      </div>
    </div>
  );
}

export default function TimelapseSection({ sites }) {
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
      {uploading && <Upload sites={sites} reels={reels} lastWeek={d.last_week}
        onCancel={() => setUploading(false)}
        onDone={() => { setUploading(false); load(); }} />}

      {reels.length === 0 && !uploading && (
        <div style={card}><p style={{ margin: 0, color: "#667" }}>
          No time-lapse yet. Upload the first week's video from the camera's
          card.</p></div>)}

      <div style={{ display: "grid", gap: 14,
                    gridTemplateColumns: "repeat(auto-fill,minmax(360px,1fr))" }}>
        {reels.map((r) => (
          <div key={r.id} style={card}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8,
                          flexWrap: "wrap" }}>
              <strong>{r.site_code} · {r.camera_label}</strong>
              {r.client_visible
                ? <Chip tone="ok">on client portal</Chip>
                : <Chip tone="info">internal</Chip>}
              {r.waiting > 0 && <Chip tone="warn">
                {r.waiting} week{r.waiting > 1 ? "s" : ""} being joined</Chip>}
            </div>
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
