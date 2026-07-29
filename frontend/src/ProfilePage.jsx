import { useEffect, useRef, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, card, inputStyle } from "./ui.jsx";
import ImageCropper from "./ImageCropper.jsx";

// Company Profile — management maintains the ongoing-project pages that go into
// the emailed profile PDF. Marketing brand world (warm navy / amber / sand),
// distinct from the app's cooler chrome.
const NAVY = "#0E3A5C", AMBER = "#E38A2E", SAND = "#F3ECDE";
const MAX_GALLERY = 6;

export default function ProfilePage() {
  const [data, setData] = useState(null);
  const [sel, setSel] = useState(null);     // selected entry id
  const [error, setError] = useState(null);

  const load = () => api("/profile/entries").then((d) => {
    setData(d);
    setSel((s) => s || d.ongoing[0]?.id || null);
  }).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);   // eslint-disable-line

  async function addEntry() {
    try {
      const e = await api("/profile/entries", { method: "POST",
        body: { project_name: "New project" } });
      await load();
      setSel(e.id);
    } catch (e) { setError(e.message); }
  }

  if (error && !data) return <div style={card}>{error}</div>;
  if (!data) return <div style={card}>Loading…</div>;

  const entry = [...data.ongoing, ...data.completed].find((e) => e.id === sel);

  return (
    <div style={{ maxWidth: 1180 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
        marginBottom: 12 }}>
        <h2 style={{ margin: 0, color: NAVY }}>Company Profile</h2>
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
          Ongoing projects for the emailed profile · {data.ongoing.length} live</span>
      </div>
      {error && <p style={{ color: "var(--red-fg)" }}>{error}</p>}

      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        <OngoingList data={data} sel={sel} setSel={setSel}
          onAdd={addEntry} onReorder={load} />
        {entry
          ? <Editor key={entry.id} entry={entry} onSaved={load}
              onDeleted={() => { setSel(null); load(); }} />
          : <div style={{ ...card, flex: 1 }}>
              Select a project, or add one.</div>}
      </div>
    </div>
  );
}

// ---- left column: drag-reorderable ongoing list + completed ---------------

function OngoingList({ data, sel, setSel, onAdd, onReorder }) {
  const [order, setOrder] = useState(data.ongoing.map((e) => e.id));
  const dragId = useRef(null);
  useEffect(() => { setOrder(data.ongoing.map((e) => e.id)); },
    [data.ongoing.map((e) => e.id).join(",")]);   // eslint-disable-line

  const byId = Object.fromEntries(data.ongoing.map((e) => [e.id, e]));

  function drop(targetId) {
    const from = dragId.current;
    if (!from || from === targetId) return;
    const next = order.filter((i) => i !== from);
    next.splice(next.indexOf(targetId), 0, from);
    setOrder(next);
    api("/profile/entries/reorder", { method: "POST", body: { order: next } })
      .then(onReorder).catch(() => {});
  }

  return (
    <div style={{ width: 300, flexShrink: 0 }}>
      <div style={{ ...card, padding: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between",
          alignItems: "center", marginBottom: 8 }}>
          <b style={{ fontSize: 13, color: NAVY }}>Ongoing</b>
          <Btn variant="primary" style={{ padding: "4px 10px" }}
            onClick={onAdd}>+ Add</Btn>
        </div>
        {order.map((id) => {
          const e = byId[id];
          if (!e) return null;
          return (
            <div key={id} draggable
              onDragStart={() => { dragId.current = id; }}
              onDragOver={(ev) => ev.preventDefault()}
              onDrop={() => drop(id)}
              onClick={() => setSel(id)}
              style={{ display: "flex", gap: 8, alignItems: "center",
                padding: "7px 8px", borderRadius: 8, cursor: "pointer",
                marginBottom: 4,
                background: sel === id ? SAND : "transparent",
                border: sel === id ? `1px solid ${AMBER}`
                  : "1px solid transparent" }}>
              <span style={{ color: "var(--muted)", cursor: "grab" }}>⋮⋮</span>
              {e.featured_url
                ? <img src={e.featured_url} alt="" style={{ width: 34,
                    height: 34, borderRadius: 6, objectFit: "cover" }} />
                : <div style={{ width: 34, height: 34, borderRadius: 6,
                    background: "#dce6ee" }} />}
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: NAVY,
                  whiteSpace: "nowrap", overflow: "hidden",
                  textOverflow: "ellipsis" }}>{e.project_name}</div>
                <div style={{ fontSize: 11, color: "var(--muted)" }}>
                  {e.client_display || "—"}</div>
              </div>
            </div>
          );
        })}
        {!order.length && <p style={{ fontSize: 12, color: "var(--muted)",
          padding: "4px 8px" }}>No ongoing projects yet.</p>}
      </div>

      {data.completed.length > 0 && (
        <div style={{ ...card, padding: 10 }}>
          <b style={{ fontSize: 13, color: NAVY }}>Completed (references)</b>
          {data.completed.map((e) => (
            <div key={e.id} onClick={() => setSel(e.id)}
              style={{ fontSize: 12.5, padding: "5px 8px", cursor: "pointer",
                color: "var(--muted)" }}>
              🔒 {e.project_name}</div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- right column: entry editor + live preview ----------------------------

const FIELDS = [
  ["project_name", "Project name", "Soneva Jani — North Jetty Villas"],
  ["client_display", "Client stamp (on the photo)", "SONEVA JANI"],
  ["start_value", "Commenced", "April 2026"],
];

function Editor({ entry, onSaved, onDeleted }) {
  const [f, setF] = useState({ ...entry });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [crop, setCrop] = useState(null);   // {file, aspect, outW, kind}
  const fileRef = useRef(null);
  const pending = useRef("featured");
  const locked = entry.locked;

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  async function save() {
    setBusy(true); setErr(null);
    try {
      await api(`/profile/entries/${entry.id}`, { method: "PATCH", body: {
        project_name: f.project_name, client_display: f.client_display,
        summary: f.summary, start_value: f.start_value } });
      onSaved();
    } catch (e) { setErr(e.message); }
    setBusy(false);
  }
  async function del() {
    if (!window.confirm(`Remove "${entry.project_name}"?`)) return;
    try { await api(`/profile/entries/${entry.id}`, { method: "DELETE" });
      onDeleted(); } catch (e) { setErr(e.message); }
  }

  function pick(kind) {
    pending.current = kind;
    fileRef.current.value = "";
    fileRef.current.click();
  }
  function chosen(e) {
    const file = e.target.files[0];
    if (!file) return;
    const kind = pending.current;
    setCrop(kind === "featured"
      ? { file, aspect: 1, outW: 1300, kind }
      : { file, aspect: 1.5, outW: 1000, kind });
  }
  async function cropped(blob) {
    const kind = crop.kind;
    setCrop(null); setBusy(true); setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", blob, "crop.jpg");
      const url = kind === "featured"
        ? `/profile/entries/${entry.id}/featured`
        : `/profile/entries/${entry.id}/gallery`;
      await apiUpload(url, fd);
      onSaved();
    } catch (e) { setErr(e.message); }
    setBusy(false);
  }
  async function delGallery(gid) {
    try { await api(`/profile/gallery/${gid}`, { method: "DELETE" });
      onSaved(); } catch (e) { setErr(e.message); }
  }

  return (
    <div style={{ flex: 1, display: "flex", gap: 16, alignItems: "flex-start" }}>
      <div style={{ ...card, flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <b style={{ color: NAVY }}>{locked ? "Completed (locked)" : "Edit project"}</b>
          {!locked && <button onClick={del} style={{ border: "none",
            background: "none", color: "var(--red-fg)", cursor: "pointer",
            fontSize: 12.5 }}>Remove</button>}
        </div>
        {err && <p style={{ color: "var(--red-fg)" }}>{err}</p>}
        {locked && <p style={{ fontSize: 12, color: "var(--muted)" }}>
          This project is a frozen reference. Reopen it (admin) to edit.</p>}

        <fieldset disabled={locked} style={{ border: "none", padding: 0,
          margin: 0 }}>
          {FIELDS.map(([k, label, ph]) => (
            <label key={k} style={fld}>{label}
              <input style={inputStyle} value={f[k] || ""} placeholder={ph}
                onChange={set(k)} /></label>
          ))}
          <label style={fld}>Summary (2–4 sentences)
            <textarea style={{ ...inputStyle, minHeight: 84,
              resize: "vertical" }} value={f.summary || ""}
              placeholder="What the project is and what Sand Planet delivered."
              onChange={set("summary")} /></label>

          {/* featured */}
          <div style={{ marginTop: 10 }}>
            <div style={lab}>Featured photo (square)</div>
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              {entry.featured_url
                ? <img src={entry.featured_url} alt="" style={{ width: 84,
                    height: 84, borderRadius: 8, objectFit: "cover" }} />
                : <div style={{ width: 84, height: 84, borderRadius: 8,
                    background: "#e6eef4", display: "grid",
                    placeItems: "center", color: "var(--muted)",
                    fontSize: 11 }}>none</div>}
              {!locked && <Btn variant="secondary"
                onClick={() => pick("featured")}>
                {entry.featured_url ? "Replace" : "Add"} featured</Btn>}
            </div>
          </div>

          {/* gallery */}
          <div style={{ marginTop: 12 }}>
            <div style={lab}>Gallery (up to {MAX_GALLERY}, 3:2)</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {entry.gallery.map((g) => (
                <div key={g.id} style={{ position: "relative" }}>
                  <img src={g.url} alt="" style={{ width: 96, height: 64,
                    borderRadius: 6, objectFit: "cover" }} />
                  {!locked && <button onClick={() => delGallery(g.id)}
                    title="Remove" style={delBtn}>×</button>}
                </div>
              ))}
              {!locked && entry.gallery.length < MAX_GALLERY && (
                <button onClick={() => pick("gallery")} style={{ width: 96,
                  height: 64, borderRadius: 6, border: "1px dashed #b8c9d6",
                  background: "#f4f9fd", cursor: "pointer", color: NAVY,
                  fontSize: 20 }}>+</button>)}
            </div>
          </div>
        </fieldset>

        {!locked && <div style={{ marginTop: 14 }}>
          <Btn variant="primary" disabled={busy} onClick={save}>
            {busy ? "Saving…" : "Save"}</Btn></div>}

        <input ref={fileRef} type="file" accept="image/*" hidden
          onChange={chosen} />
      </div>

      <ProjectPreview f={f} entry={entry} />

      {crop && <ImageCropper file={crop.file} aspect={crop.aspect}
        outW={crop.outW} label={crop.kind === "featured"
          ? "the featured photo" : "the gallery photo"}
        onCancel={() => setCrop(null)} onDone={cropped} />}
    </div>
  );
}

// A live miniature of the rendered profile page (brand world of the PDF).
function ProjectPreview({ f, entry }) {
  const ncol = entry.gallery.length >= 3 ? 3
    : Math.max(1, entry.gallery.length);
  return (
    <div style={{ width: 340, flexShrink: 0 }}>
      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6,
        textTransform: "uppercase", letterSpacing: ".06em" }}>Page preview</div>
      <div style={{ background: "#fff", borderRadius: 8, overflow: "hidden",
        border: "1px solid var(--line)", boxShadow: "0 2px 8px rgba(16,52,79,.1)",
        fontFamily: "Georgia, serif" }}>
        <div style={{ position: "relative", height: 190, background: NAVY }}>
          {entry.featured_url && <img src={entry.featured_url} alt=""
            style={{ width: "100%", height: "100%", objectFit: "cover",
              opacity: .82 }} />}
          <div style={{ position: "absolute", inset: 0,
            background: "linear-gradient(180deg,rgba(14,58,92,.1),rgba(14,58,92,.75))" }} />
          <div style={{ position: "absolute", left: 16, bottom: 12,
            right: 16, color: "#fff" }}>
            <span style={{ background: AMBER, color: "#fff", fontSize: 10,
              fontWeight: 700, padding: "2px 8px", letterSpacing: ".08em",
              borderRadius: 2 }}>{f.client_display || "CLIENT"}</span>
            <div style={{ fontSize: 18, fontWeight: 700, marginTop: 6,
              lineHeight: 1.15 }}>{f.project_name || "Project name"}</div>
            <div style={{ fontSize: 11, opacity: .9, marginTop: 3 }}>
              ● {f.start_label || "Commenced"} {f.start_value || "—"}</div>
          </div>
        </div>
        <div style={{ padding: "12px 16px 16px" }}>
          <div style={{ fontSize: 11.5, color: "#2a3b48", lineHeight: 1.5,
            borderLeft: `3px solid ${AMBER}`, paddingLeft: 10 }}>
            {f.summary || "The project summary appears here — two to four "
              + "marketing sentences describing the scope and delivery."}</div>
          {entry.gallery.length > 0 && (
            <div style={{ display: "grid", gap: 4, marginTop: 10,
              gridTemplateColumns: `repeat(${ncol},1fr)` }}>
              {entry.gallery.map((g) => (
                <img key={g.id} src={g.url} alt="" style={{ width: "100%",
                  aspectRatio: "3/2", objectFit: "cover", borderRadius: 3 }} />
              ))}
            </div>)}
        </div>
      </div>
    </div>
  );
}

const fld = { display: "flex", flexDirection: "column", gap: 3, fontSize: 12,
  color: "var(--muted)", marginTop: 8 };
const lab = { fontSize: 12, color: "var(--muted)", marginBottom: 4 };
const delBtn = { position: "absolute", top: -6, right: -6, width: 18,
  height: 18, borderRadius: "50%", border: "none", background: "#b02418",
  color: "#fff", cursor: "pointer", fontSize: 12, lineHeight: "18px",
  padding: 0 };
