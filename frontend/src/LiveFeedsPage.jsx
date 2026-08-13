import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Btn, Chip, card, inputStyle, td, th } from "./ui.jsx";
import WhepPlayer from "./WhepPlayer.jsx";

/* Live site cameras (owner 2026-08-12).
 *
 * Cameras sit behind carrier NAT on the sites, so a small box at each site
 * publishes to our relay and everything here reads back off it. A camera is
 * "online" only while its site box is actually publishing — offline usually
 * means the box or the uplink is down, not the camera.
 */
export default function LiveFeedsPage({ me }) {
  const [d, setD] = useState(null);
  const [sites, setSites] = useState([]);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);        // camera id being watched
  const [adding, setAdding] = useState(false);

  function load() {
    api("/cameras")
      .then(setD)
      .catch((e) => setError(e.message));
  }
  useEffect(() => {
    load();
    api("/sites")
      .then((r) => setSites(Array.isArray(r) ? r : r.results || []))
      .catch(() => {});
  }, []);

  // Online/offline comes from the relay, so refresh it while the page is up.
  useEffect(() => {
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  if (error) return <p style={{ color: "#b00" }}>{error}</p>;
  if (!d) return <p>Loading…</p>;

  const cams = d.cameras || [];
  const bySite = {};
  cams.forEach((c) => {
    (bySite[c.site_code] = bySite[c.site_code] || []).push(c);
  });

  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    marginBottom: 14 }}>
        <h2 style={{ margin: 0 }}>Live Feeds</h2>
        <span style={{ color: "#667", fontSize: 13 }}>
          {cams.filter((c) => c.online).length} of {cams.length} online
        </span>
        <div style={{ flex: 1 }} />
        {d.can_manage && (
          <Btn variant="secondary" onClick={() => setAdding(!adding)}>
            {adding ? "Cancel" : "+ Add camera"}
          </Btn>
        )}
      </div>

      {!d.relay_configured && (
        <div style={{ ...card, borderLeft: "4px solid #e0a800", marginBottom: 16 }}>
          <strong>No relay configured.</strong>
          <p style={{ margin: "6px 0 0", color: "#555" }}>
            Cameras can be registered, but nothing can be watched until
            CAMERA_RELAY_URL is set on the server.
          </p>
        </div>
      )}

      {adding && <AddCamera sites={sites} onDone={() => { setAdding(false); load(); }} />}

      {cams.length === 0 && (
        <div style={card}>
          <p style={{ margin: 0, color: "#667" }}>
            No cameras registered yet.
          </p>
        </div>
      )}

      {Object.entries(bySite).map(([code, list]) => (
        <div key={code} style={{ marginBottom: 22 }}>
          <h3 style={{ margin: "0 0 8px", fontSize: 15 }}>{code}</h3>
          <div style={{ display: "grid", gap: 14,
                        gridTemplateColumns: "repeat(auto-fill,minmax(330px,1fr))" }}>
            {list.map((c) => (
              <CameraCard key={c.id} cam={c} canManage={d.can_manage}
                          isOpen={open === c.id}
                          onOpen={() => setOpen(open === c.id ? null : c.id)}
                          onChanged={load} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function CameraCard({ cam, canManage, isOpen, onOpen, onChanged }) {
  const [busy, setBusy] = useState(false);

  async function patch(body) {
    setBusy(true);
    try {
      await api(`/cameras/${cam.id}`, { method: "PATCH", body });
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(
      `Remove camera "${cam.name}"? The site box will stop being able to `
      + "publish to it.")) return;
    await api(`/cameras/${cam.id}`, { method: "DELETE" });
    onChanged();
  }

  return (
    <div style={{ ...card, padding: 0, overflow: "hidden" }}>
      <div style={{ padding: "10px 12px", display: "flex", gap: 8,
                    alignItems: "center" }}>
        <strong style={{ flex: 1 }}>{cam.name}</strong>
        {/* A pull camera sits idle until someone watches it, so "not ready"
            means nobody is looking — not that it is down. */}
        <Chip tone={cam.online ? "success"
                    : cam.mode === "PULL" ? "info" : "muted"}>
          {cam.online ? "Live now"
           : cam.mode === "PULL" ? "On demand" : "Offline"}
        </Chip>
      </div>
      {cam.location_note && (
        <div style={{ padding: "0 12px 8px", color: "#667", fontSize: 12 }}>
          {cam.location_note}
        </div>
      )}

      {isOpen && (cam.online || cam.mode === "PULL") && (
        <WhepPlayer getTicket={() =>
          api(`/cameras/${cam.id}/ticket`, { method: "POST" })} />
      )}

      <div style={{ padding: "8px 12px", display: "flex", gap: 8,
                    alignItems: "center", borderTop: "1px solid #eef0f4" }}>
        <Btn variant="secondary"
             disabled={!cam.online && cam.mode !== "PULL"} onClick={onOpen}>
          {isOpen ? "Close" : "Watch"}
        </Btn>
        <div style={{ flex: 1 }} />
        {canManage && (
          <>
            <label style={{ fontSize: 12, color: "#556", display: "flex",
                            gap: 5, alignItems: "center" }}
                   title="Show this camera to the site's client in their portal">
              <input type="checkbox" checked={cam.client_visible}
                     disabled={busy}
                     onChange={() => patch({ client_visible: !cam.client_visible })} />
              Client
            </label>
            <Btn variant="secondary" onClick={remove}>Remove</Btn>
          </>
        )}
      </div>

      {canManage && cam.stream_key && (
        <div style={{ padding: "8px 12px", background: "#f7f8fa",
                      fontSize: 11, color: "#667", wordBreak: "break-all" }}>
          <div>Publish path: <code>{cam.path}</code></div>
          <div>Stream key: <code>{cam.stream_key}</code></div>
        </div>
      )}
    </div>
  );
}

function AddCamera({ sites, onDone }) {
  const [f, setF] = useState({ site: "", name: "", path: "",
                               location_note: "", source_url: "" });
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  async function save() {
    setErr(null);
    try {
      await api("/cameras", { method: "POST", body: f });
      onDone();
    } catch (e) {
      setErr(e.message);
    }
  }

  return (
    <div style={{ ...card, marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>Register a camera</h3>
      <div style={{ display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fit,minmax(190px,1fr))" }}>
        <select style={inputStyle} value={f.site} onChange={set("site")}>
          <option value="">Site…</option>
          {sites.map((s) => (
            <option key={s.id} value={s.id}>{s.code} — {s.name}</option>
          ))}
        </select>
        <input style={inputStyle} placeholder="Name (e.g. Main gate)"
               value={f.name} onChange={set("name")} />
        <input style={inputStyle} placeholder="Stream path (e.g. vkr-gate)"
               value={f.path} onChange={set("path")} />
        <input style={inputStyle} placeholder="Where it points (optional)"
               value={f.location_note} onChange={set("location_note")} />
      </div>
      <input style={{ ...inputStyle, marginTop: 10, width: "100%" }}
             placeholder="Pull URL (optional) — rtsp://user:pass@site-ip:8554/Preview_02_main"
             value={f.source_url} onChange={set("source_url")} />
      {err && <p style={{ color: "#b00", marginBottom: 0 }}>{err}</p>}
      <p style={{ color: "#667", fontSize: 12 }}>
        Two ways in. Leave the pull URL blank and something at the site
        publishes to us using the generated path and key. Fill it in — when the
        site has a routable address and forwards the camera’s port to us — and
        the relay fetches the stream itself, with nothing running at the site
        and no bandwidth used unless somebody is watching. Either way the
        camera stays internal until you tick “Client”.
      </p>
      <Btn onClick={save}>Save</Btn>
    </div>
  );
}
