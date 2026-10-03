// Photo evidence on a safety record — an incident or a toolbox talk — and the
// button that prints the record as a report (owner 2026-10-03).
import { useRef, useState } from "react";
import { api, apiDownload, apiUpload } from "./api.js";
import { BTN, ghostButton, inputStyle } from "./ui.jsx";

// `base` is the record's API path: /hse/incidents/INC-… or /hse/toolbox-talks/TBT-…
export function ReportButton({ base, label = "Report (PDF)" }) {
  const [error, setError] = useState(null);
  return (
    <>
      <button style={{ ...ghostButton, padding: "5px 12px", fontSize: 13 }}
              onClick={(e) => { e.stopPropagation(); setError(null);
                                apiDownload(`${base}/report.pdf`).catch((x) => setError(x.message)); }}>
        ⬇ {label}
      </button>
      {error && <span style={{ color: "#b3261e", fontSize: 12, marginLeft: 8 }}>{error}</span>}
    </>
  );
}

// A file picker that takes several photos, from the camera on a phone.
export function PhotoPicker({ files, setFiles, label }) {
  const ref = useRef(null);
  return (
    <div style={{ marginTop: 12 }}>
      <strong style={{ fontSize: 13 }}>{label}</strong>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 6 }}>
        <input ref={ref} type="file" accept="image/*" multiple style={{ fontSize: 12.5 }}
               onChange={(e) => setFiles([...files, ...Array.from(e.target.files || [])])} />
        {files.length > 0 && (
          <span style={{ fontSize: 12.5, color: "#5a6b78" }}>
            {files.length} photo{files.length === 1 ? "" : "s"} chosen ·{" "}
            <button style={{ border: 0, background: "none", color: "#16527E", cursor: "pointer", padding: 0, font: "inherit" }}
                    onClick={() => { setFiles([]); if (ref.current) ref.current.value = ""; }}>clear</button>
          </span>)}
      </div>
    </div>
  );
}

export async function uploadPhotos(base, files, caption = "") {
  const fd = new FormData();
  files.forEach((f) => fd.append("photos", f));
  if (caption) fd.append("caption", caption);
  return apiUpload(`${base}/photos`, fd, "POST");
}

export default function HsePhotos({ base, photos, canAdd, canRemove, onChanged, emptyNote }) {
  const [files, setFiles] = useState([]);
  const [caption, setCaption] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function add() {
    setBusy(true); setError(null);
    try { const r = await uploadPhotos(base, files, caption); setFiles([]); setCaption(""); onChanged(r.photos); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function remove(p) {
    if (!window.confirm("Remove this photo?")) return;
    setError(null);
    try { const r = await api(`${base}/photos/${p.id}`, { method: "DELETE" }); onChanged(r.photos); }
    catch (e) { setError(e.message); }
  }

  return (
    <div style={{ margin: "14px 0" }}>
      <h3 style={{ fontSize: 14, margin: "0 0 6px" }}>Photos{photos.length ? ` (${photos.length})` : ""}</h3>
      {photos.length === 0 && (
        <p style={{ fontSize: 13, color: "#b3261e", margin: "0 0 8px" }}>{emptyNote || "No photo yet."}</p>)}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {photos.map((p) => (
          <figure key={p.id} style={{ margin: 0, width: 150 }}>
            <a href={p.url} target="_blank" rel="noreferrer">
              <img src={p.url} alt={p.caption || p.file_name}
                   style={{ width: 150, height: 110, objectFit: "cover", borderRadius: 6, border: "1px solid #d5dde3" }} />
            </a>
            <figcaption style={{ fontSize: 11.5, color: "#5a6b78", lineHeight: 1.3 }}>
              {p.caption || <span style={{ opacity: .6 }}>{p.by}</span>}
              {canRemove && <button title="Remove this photo" onClick={() => remove(p)}
                style={{ border: 0, background: "none", color: "#b3261e", cursor: "pointer", marginLeft: 4 }}>✕</button>}
            </figcaption>
          </figure>))}
      </div>
      {canAdd && (
        <div style={{ marginTop: 8 }}>
          <PhotoPicker files={files} setFiles={setFiles} label="Add photos" />
          {files.length > 0 && (
            <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
              <input value={caption} placeholder="What the photo shows (optional)" onChange={(e) => setCaption(e.target.value)}
                     style={{ ...inputStyle, maxWidth: 320 }} />
              <button onClick={add} disabled={busy} style={BTN.primary}>{busy ? "Uploading…" : `Upload ${files.length}`}</button>
            </div>)}
        </div>)}
      {error && <p style={{ color: "#b3261e", fontSize: 13 }}>{error}</p>}
    </div>
  );
}
