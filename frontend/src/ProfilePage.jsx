import { useEffect, useRef, useState } from "react";
import { api, apiUpload } from "./api.js";
import { Btn, card, inputStyle } from "./ui.jsx";
import ImageCropper from "./ImageCropper.jsx";

// Company Profile — management maintains the ongoing-project pages that go into
// the emailed profile PDF. Marketing brand world (warm navy / amber / sand),
// distinct from the app's cooler chrome.
const NAVY = "#0E3A5C", AMBER = "#E38A2E", SAND = "#F3ECDE";
const MAX_GALLERY = 6;

function getCookie(name) {
  const m = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
  return m ? decodeURIComponent(m[2]) : null;
}

export default function ProfilePage() {
  const [data, setData] = useState(null);
  const [sel, setSel] = useState(null);     // selected entry id
  const [error, setError] = useState(null);
  const [gen, setGen] = useState(false);

  async function generate(preview) {
    setGen(true); setError(null);
    try {
      const res = await fetch(
        `/api/v1/profile/generate${preview ? "?preview=1" : ""}`,
        { method: "POST", credentials: "same-origin",
          headers: { "X-CSRFToken": getCookie("csrftoken") } });
      if (!res.ok) throw new Error("Could not generate the profile PDF.");
      const url = URL.createObjectURL(await res.blob());
      if (preview) window.open(url, "_blank");
      else {
        const a = document.createElement("a");
        a.href = url;
        a.download = "Sand_Planet_Company_Profile.pdf";
        a.click();
      }
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) { setError(e.message); }
    setGen(false);
  }

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
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <Btn variant="secondary" disabled={gen}
            onClick={() => generate(true)}>Preview</Btn>
          <Btn variant="primary" disabled={gen}
            onClick={() => generate(false)}>
            {gen ? "Generating…" : "Generate PDF"}</Btn>
        </div>
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

      <CoverPanel />
      <ManagementPanel />
      <CorporatePanel />
      <RefereesPanel />
    </div>
  );
}

// ---- cover photo ----------------------------------------------------------
// The cover used to be whichever ongoing project sorted first, so reordering
// the projects silently changed the front page (owner 2026-08-19).

function CoverPanel() {
  const [st, setSt] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef();
  const [crop, setCrop] = useState(null);
  const load = () => api("/profile/settings").then(setSt).catch(() => {});
  useEffect(() => { load(); }, []);

  // Crop it by hand rather than centring blindly: on a good cover shot the
  // subject is rarely dead centre — the pool and its decking sit in one corner
  // of the frame, and a centre crop clips the furniture off (owner 2026-08-19).
  function chosen(e) {
    const f = e.target.files[0];
    if (f) setCrop(f);
    e.target.value = "";
  }

  async function upload(blob) {
    setCrop(null);
    if (!blob) return;
    setErr(null); setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", blob, "cover.jpg");
      setSt(await apiUpload("/profile/cover", fd));
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  async function clear() {
    setErr(null);
    try { setSt(await api("/profile/cover", { method: "DELETE" })); }
    catch (e) { setErr(e.message); }
  }
  async function setFocus(v) {
    setErr(null);
    try {
      setSt(await api("/profile/settings",
                      { method: "PATCH", body: { divider_focus: v } }));
    } catch (e) { setErr(e.message); }
  }

  async function setStyle(v) {
    setErr(null);
    try {
      setSt(await api("/profile/settings",
                      { method: "PATCH", body: { cover_style: v } }));
    } catch (e) { setErr(e.message); }
  }
  if (!st) return null;

  return (
    <section style={{ ...card, marginTop: 16 }}>
      <h3 style={{ margin: "0 0 4px", color: NAVY, fontSize: 15 }}>
        Cover photo</h3>
      <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "0 0 10px" }}>
        The picture on the front page. Without one it falls back to whichever
        ongoing project is first in the list — which changes when you reorder
        them.
      </p>
      {/* Where the title sits depends on the photo: on an aerial the subject
          is low in the frame, so type at the bottom covers it. */}
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap",
                    marginBottom: 12, fontSize: 12.5 }}>
        {[["TOP", "Title in the sky", "for aerials — subject low in frame"],
          ["FULL", "Title at the foot", "when the subject is high or central"],
          ["BAND", "Photo band, title below", "the original, plainer layout"]]
          .map(([v, label, why]) => (
          <label key={v} style={{ display: "flex", gap: 6, alignItems: "start",
                                  cursor: "pointer" }}>
            <input type="radio" name="coverstyle" checked={st.cover_style === v}
                   onChange={() => setStyle(v)} style={{ marginTop: 2 }} />
            <span>
              <span style={{ fontWeight: 600 }}>{label}</span>
              <span style={{ display: "block", fontSize: 11,
                             color: "var(--muted)" }}>{why}</span>
            </span>
          </label>
        ))}
      </div>
      {err && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{err}</p>}
      {/* The section dividers show a tall narrow slice of this same photo.
          A centred slice cut through the pool and landed on empty beach
          (owner 2026-08-20). */}
      <div style={{ display: "flex", gap: 8, alignItems: "center",
                    marginBottom: 12, fontSize: 12.5 }}>
        <span style={{ color: "var(--muted)" }}>
          Section dividers show a narrow strip of this photo — take it from the:
        </span>
        {[["LEFT", "left"], ["CENTER", "middle"], ["RIGHT", "right"]]
          .map(([v, label]) => (
          <label key={v} style={{ display: "flex", gap: 4, alignItems: "center",
                                  cursor: "pointer" }}>
            <input type="radio" name="divfocus"
                   checked={(st.divider_focus || "CENTER") === v}
                   onChange={() => setFocus(v)} />
            {label}
          </label>
        ))}
      </div>
      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        <input type="file" accept="image/*" ref={fileRef}
               style={{ display: "none" }} onChange={chosen} />
        {st.cover_url ? (
          <img src={st.cover_url} alt=""
               onClick={() => fileRef.current?.click()}
               style={{ width: 120,
                        height: Math.round(120 / (st.cover_aspect || 0.707)),
                        objectFit: "cover",
                        borderRadius: 6, cursor: "pointer",
                        border: "1px solid var(--sp-border)" }} />
        ) : (
          <button onClick={() => fileRef.current?.click()}
                  style={{ width: 120, height: 160, borderRadius: 6,
                           border: "1px dashed var(--sp-border)",
                           background: "#fafbfc", cursor: "pointer",
                           color: "#8a94a0", fontSize: 12 }}>
            + Choose a cover photo</button>
        )}
        <div>
          <Btn variant="secondary" disabled={busy}
               onClick={() => fileRef.current?.click()}>
            {busy ? "Uploading…" : st.cover_url ? "Replace" : "Choose photo"}
          </Btn>
          {st.cover_url && (
            <Btn variant="secondary" style={{ marginLeft: 8 }} onClick={clear}>
              Use the first project instead</Btn>
          )}
          <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 8 }}>
            You choose the crop. The cover band is slightly wider than it is
            tall (210&times;176mm), so a landscape photo needs only its edges
            trimmed.
          </div>
        </div>
      </div>
      {crop && (
        <ImageCropper file={crop} aspect={st.cover_aspect || 210 / 297}
                      outW={2200}
                      label="Position the cover photo"
                      onCancel={() => setCrop(null)} onDone={upload} />
      )}
    </section>
  );
}

// ---- key management personnel ---------------------------------------------
// Was four hardcoded people in the renderer; adding a director meant a deploy.

function ManagementPanel() {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState(null);
  const load = () => api("/profile/management").then(setRows).catch(() => {});
  useEffect(() => { load(); }, []);

  async function add() {
    setErr(null);
    try {
      await api("/profile/management",
                { method: "POST", body: { name: "New person", role: "" } });
      load();
    } catch (e) { setErr(e.message); }
  }
  async function save(r) {
    setErr(null);
    try {
      await api(`/profile/management/${r.id}`, { method: "PATCH", body: {
        name: r.name, role: r.role, intro: r.intro, is_active: r.is_active } });
      load();
    } catch (e) { setErr(e.message); }
  }
  async function del(id) {
    if (!window.confirm("Remove this person from the profile?")) return;
    try { await api(`/profile/management/${id}`, { method: "DELETE" }); load(); }
    catch (e) { setErr(e.message); }
  }
  async function photo(id, f) {
    if (!f) return;
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", f);
      await apiUpload(`/profile/management/${id}/photo`, fd);
      load();
    } catch (e) { setErr(e.message); }
  }
  if (!rows) return null;

  return (
    <section style={{ ...card, marginTop: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <h3 style={{ margin: 0, color: NAVY, fontSize: 15 }}>
          Key management personnel</h3>
        <span style={{ fontSize: 12, color: "var(--muted)" }}>
          {rows.filter((r) => r.is_active).length} on the profile</span>
        <Btn variant="secondary" style={{ marginLeft: "auto" }}
             onClick={add}>+ Add a person</Btn>
      </div>
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "6px 0 12px" }}>
        Six fit the page comfortably; beyond that the cards tighten up.
        Without a photo the profile shows their initials.
      </p>
      {err && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{err}</p>}
      {rows.map((r) => (
        <MgmtRow key={r.id} row={r} onSave={save} onDel={del}
                 onPhoto={photo} />
      ))}
    </section>
  );
}

function MgmtRow({ row, onSave, onDel, onPhoto }) {
  const [r, setR] = useState(row);
  const fileRef = useRef();
  const dirty = JSON.stringify(r) !== JSON.stringify(row);
  const set = (k) => (e) => setR({ ...r, [k]: e.target.value });
  return (
    <div style={{ display: "flex", gap: 12, padding: "10px 0",
                  borderTop: "1px solid var(--sp-border)",
                  alignItems: "flex-start" }}>
      <input type="file" accept="image/*" ref={fileRef}
             style={{ display: "none" }}
             onChange={(e) => onPhoto(row.id, e.target.files[0])} />
      {r.photo_url ? (
        <img src={r.photo_url} alt="" onClick={() => fileRef.current?.click()}
             style={{ width: 54, height: 54, borderRadius: "50%",
                      objectFit: "cover", cursor: "pointer" }} />
      ) : (
        <button onClick={() => fileRef.current?.click()} title="Add a photo"
                style={{ width: 54, height: 54, borderRadius: "50%",
                         border: "1px dashed var(--sp-border)",
                         background: "#fafbfc", cursor: "pointer",
                         color: "#8a94a0", fontSize: 11 }}>photo</button>
      )}
      <div style={{ flex: 1, display: "grid", gap: 6 }}>
        <div style={{ display: "flex", gap: 6 }}>
          <input value={r.name} onChange={set("name")} placeholder="Full name"
                 style={{ ...inputStyle, flex: 1, fontWeight: 600 }} />
          <input value={r.role} onChange={set("role")}
                 placeholder="Role, e.g. Director of Projects"
                 style={{ ...inputStyle, flex: 1 }} />
        </div>
        <textarea value={r.intro} onChange={set("intro")} rows={2}
                  placeholder="A sentence or two for the profile"
                  style={{ ...inputStyle, width: "100%", resize: "vertical" }} />
      </div>
      <div style={{ display: "grid", gap: 6, minWidth: 90 }}>
        <Btn variant={dirty ? "primary" : "secondary"} disabled={!dirty}
             onClick={() => onSave(r)}>Save</Btn>
        <label style={{ fontSize: 11.5, display: "flex", gap: 5,
                        alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={r.is_active}
                 onChange={(e) => setR({ ...r, is_active: e.target.checked })} />
          Show
        </label>
        <button onClick={() => onDel(row.id)}
                style={{ background: "none", border: "none", cursor: "pointer",
                         color: "var(--red-fg)", fontSize: 11.5,
                         padding: 0 }}>Remove</button>
      </div>
    </div>
  );
}

// ---- corporate information -------------------------------------------------
// The "company at a glance" table. Total staff especially moves.

function CorporatePanel() {
  const [rows, setRows] = useState(null);
  const [st, setSt] = useState(null);
  const [err, setErr] = useState(null);
  const load = () => {
    api("/profile/corporate").then(setRows).catch(() => {});
    api("/profile/settings").then(setSt).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  async function add() {
    try {
      await api("/profile/corporate",
                { method: "POST", body: { label: "New row", value: "" } });
      load();
    } catch (e) { setErr(e.message); }
  }
  async function save(r) {
    try {
      await api(`/profile/corporate/${r.id}`, { method: "PATCH",
        body: { label: r.label, value: r.value, is_active: r.is_active } });
      load();
    } catch (e) { setErr(e.message); }
  }
  async function del(id) {
    if (!window.confirm("Remove this row?")) return;
    try { await api(`/profile/corporate/${id}`, { method: "DELETE" }); load(); }
    catch (e) { setErr(e.message); }
  }
  async function saveText(next) {
    try { setSt(await api("/profile/settings",
                          { method: "PATCH", body: next })); }
    catch (e) { setErr(e.message); }
  }
  if (!rows || !st) return null;

  return (
    <section style={{ ...card, marginTop: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <h3 style={{ margin: 0, color: NAVY, fontSize: 15 }}>
          Corporate information</h3>
        <Btn variant="secondary" style={{ marginLeft: "auto" }}
             onClick={add}>+ Add a row</Btn>
      </div>
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "6px 0 12px" }}>
        The "company at a glance" table. Use &lt;br&gt; in a value to break the
        line — that is how the senior-management row lists four people.
      </p>
      {err && <p style={{ color: "var(--red-fg)", fontSize: 13 }}>{err}</p>}
      {rows.map((r) => (
        <CorpRow key={r.id} row={r} onSave={save} onDel={del} />
      ))}
      <VisionMission st={st} onSave={saveText} />
    </section>
  );
}

function CorpRow({ row, onSave, onDel }) {
  const [r, setR] = useState(row);
  const dirty = JSON.stringify(r) !== JSON.stringify(row);
  return (
    <div style={{ display: "flex", gap: 8, padding: "7px 0",
                  borderTop: "1px solid var(--sp-border)",
                  alignItems: "flex-start" }}>
      <input value={r.label} onChange={(e) => setR({ ...r, label: e.target.value })}
             style={{ ...inputStyle, width: 190, fontWeight: 600 }} />
      <textarea value={r.value} rows={1}
                onChange={(e) => setR({ ...r, value: e.target.value })}
                style={{ ...inputStyle, flex: 1, resize: "vertical" }} />
      <Btn variant={dirty ? "primary" : "secondary"} disabled={!dirty}
           onClick={() => onSave(r)}>Save</Btn>
      <button onClick={() => onDel(row.id)}
              style={{ background: "none", border: "none", cursor: "pointer",
                       color: "var(--red-fg)", fontSize: 11.5 }}>×</button>
    </div>
  );
}

function VisionMission({ st, onSave }) {
  const [v, setV] = useState(st.vision);
  const [m, setM] = useState(st.mission);
  const dirty = v !== st.vision || m !== st.mission;
  return (
    <div style={{ marginTop: 14, borderTop: "1px solid var(--sp-border)",
                  paddingTop: 12 }}>
      <div style={{ display: "flex", gap: 12 }}>
        <label style={{ flex: 1, fontSize: 12, fontWeight: 700, color: NAVY }}>
          Our Vision
          <textarea value={v} rows={4} onChange={(e) => setV(e.target.value)}
                    style={{ ...inputStyle, width: "100%", marginTop: 4,
                             fontWeight: 400, resize: "vertical" }} />
        </label>
        <label style={{ flex: 1, fontSize: 12, fontWeight: 700, color: NAVY }}>
          Our Mission
          <textarea value={m} rows={4} onChange={(e) => setM(e.target.value)}
                    style={{ ...inputStyle, width: "100%", marginTop: 4,
                             fontWeight: 400, resize: "vertical" }} />
        </label>
      </div>
      <Btn variant={dirty ? "primary" : "secondary"} disabled={!dirty}
           style={{ marginTop: 8 }}
           onClick={() => onSave({ vision: v, mission: m })}>
        Save vision &amp; mission</Btn>
    </div>
  );
}

// ---- referees: the "Trusted by the industry" page, editable ---------------
function RefereesPanel() {
  const [refs, setRefs] = useState(null);
  const [err, setErr] = useState(null);
  const load = () => api("/profile/referees").then(setRefs)
    .catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);   // eslint-disable-line

  async function add() {
    try {
      await api("/profile/referees", { method: "POST",
        body: { name: "New referee" } });
      load();
    } catch (e) { setErr(e.message); }
  }
  async function save(r) {
    try {
      await api(`/profile/referees/${r.id}`, { method: "PATCH",
        body: { name: r.name, role: r.role, org: r.org, email: r.email } });
    } catch (e) { setErr(e.message); }
  }
  async function del(id) {
    if (!window.confirm("Remove this referee?")) return;
    try { await api(`/profile/referees/${id}`, { method: "DELETE" }); load(); }
    catch (e) { setErr(e.message); }
  }
  if (!refs) return null;
  const cell = { ...inputStyle, fontSize: 12.5 };
  const upd = (i, k, v) => setRefs(refs.map((x, j) =>
    (j === i ? { ...x, [k]: v } : x)));

  return (
    <div style={{ ...card, marginTop: 16, maxWidth: 900 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
        marginBottom: 10 }}>
        <b style={{ color: NAVY }}>Referees</b>
        <span style={{ fontSize: 12, color: "var(--muted)" }}>
          the “Trusted by the industry” page</span>
        <Btn variant="secondary" style={{ marginLeft: "auto",
          padding: "4px 10px" }} onClick={add}>+ Add referee</Btn>
      </div>
      {err && <p style={{ color: "var(--red-fg)", fontSize: 12 }}>{err}</p>}
      <div style={{ display: "grid", gap: 6 }}>
        {refs.map((r, i) => (
          <div key={r.id} style={{ display: "grid", gap: 6,
            gridTemplateColumns: "1fr 1.2fr 1.2fr 1.2fr auto auto" }}>
            <input style={cell} value={r.name} placeholder="Name"
              onChange={(e) => upd(i, "name", e.target.value)} />
            <input style={cell} value={r.role} placeholder="Role"
              onChange={(e) => upd(i, "role", e.target.value)} />
            <input style={cell} value={r.org} placeholder="Organisation"
              onChange={(e) => upd(i, "org", e.target.value)} />
            <input style={cell} value={r.email || ""} placeholder="Email"
              onChange={(e) => upd(i, "email", e.target.value)} />
            <Btn variant="secondary" style={{ padding: "4px 10px" }}
              onClick={() => save(r)}>Save</Btn>
            <Btn variant="danger" style={{ padding: "4px 10px" }}
              onClick={() => del(r.id)}>✕</Btn>
          </div>
        ))}
        {!refs.length && <p style={{ color: "var(--muted)", fontSize: 12.5 }}>
          No referees yet — add one.</p>}
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
  async function complete() {
    const when = window.prompt(
      "Completion date (YYYY-MM-DD). This moves the project into Project "
      + "References and freezes the page.",
      new Date().toISOString().slice(0, 10));
    if (when === null) return;
    setErr(null);
    try {
      await api(`/profile/entries/${entry.id}/complete`,
                { method: "POST", body: { completed_at: when } });
      onSaved();
    } catch (e) { setErr(e.message); }
  }

  async function reopen() {
    setErr(null);
    try {
      await api(`/profile/entries/${entry.id}/reopen`, { method: "POST" });
      onSaved();
    } catch (e) { setErr(e.message); }
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
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            {/* Finishing a project had no button at all — the model could
                retire one but nothing set it (owner 2026-08-20). */}
            {!locked && (
              <button onClick={complete} style={{ border: "none",
                background: "none", color: NAVY, cursor: "pointer",
                fontSize: 12.5, fontWeight: 600 }}>
                ✓ Mark completed</button>
            )}
            {locked && (
              <button onClick={reopen} style={{ border: "none",
                background: "none", color: NAVY, cursor: "pointer",
                fontSize: 12.5, fontWeight: 600 }}>
                ↩ Reopen to edit</button>
            )}
            {!locked && <button onClick={del} style={{ border: "none",
              background: "none", color: "var(--red-fg)", cursor: "pointer",
              fontSize: 12.5 }}>Remove</button>}
          </div>
        </div>
        {err && <p style={{ color: "var(--red-fg)" }}>{err}</p>}
        {locked && <p style={{ fontSize: 12, color: "var(--muted)" }}>
          Completed {entry.completed_at || ""} — this is a frozen reference, so
          the page cannot drift after the fact. Reopen it to edit.</p>}

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
