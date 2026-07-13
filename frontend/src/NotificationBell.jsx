import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

// Header bell: polls for approval/attention notifications, shows an unread
// badge, and opens the underlying document when a notification is clicked.
export default function NotificationBell({ onOpen }) {
  const [data, setData] = useState({ unread: 0, items: [] });
  const [open, setOpen] = useState(false);
  const box = useRef(null);

  const load = () => api("/notifications").then(setData).catch(() => {});
  useEffect(() => {
    load();
    const t = setInterval(load, 45000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    const h = (e) => {
      if (box.current && !box.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  async function markAll() {
    await api("/notifications/read", { method: "POST", body: {} });
    load();
  }
  async function openItem(n) {
    api("/notifications/read", { method: "POST", body: { ids: [n.id] } })
      .then(load);
    setOpen(false);
    if (n.doc_ref) onOpen(n.doc_ref, n.doc_type);
  }

  const linkBtn = {
    background: "transparent", border: "none", color: "var(--sp-navy)",
    cursor: "pointer", fontSize: 12, textDecoration: "underline",
  };

  return (
    <div ref={box} style={{ position: "relative", marginLeft: "auto" }}>
      <button onClick={() => { setOpen((o) => !o); load(); }}
        title="Notifications"
        style={{ background: "transparent", border: "none", cursor: "pointer",
                 fontSize: 18, position: "relative", lineHeight: 1,
                 padding: "2px 4px" }}>
        <span role="img" aria-label="notifications">🔔</span>
        {data.unread > 0 && (
          <span style={{ position: "absolute", top: -5, right: -6,
                         background: "#c0392b", color: "#fff", borderRadius: 10,
                         padding: "0 5px", fontSize: 10.5, fontWeight: 700 }}>
            {data.unread}
          </span>
        )}
      </button>
      {open && (
        <div style={{ position: "absolute", right: 0, top: 32, width: 340,
                      maxHeight: 440, overflowY: "auto", background: "#fff",
                      color: "var(--sp-navy)", borderRadius: 10,
                      boxShadow: "0 8px 28px rgba(0,0,0,.28)", zIndex: 200,
                      padding: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "center", padding: "2px 8px 6px" }}>
            <strong style={{ fontSize: 13 }}>Notifications</strong>
            {data.unread > 0 && (
              <button onClick={markAll} style={linkBtn}>Mark all read</button>
            )}
          </div>
          {data.items.length === 0 && (
            <p style={{ fontSize: 13, color: "#8a97a1", padding: 8, margin: 0 }}>
              Nothing needs you right now.</p>
          )}
          {data.items.map((n) => (
            <div key={n.id} onClick={() => openItem(n)}
              style={{ cursor: "pointer", padding: "8px 10px", borderRadius: 8,
                       background: n.read_at ? "transparent" : "#eef4fb",
                       marginBottom: 3 }}>
              <div style={{ fontSize: 13,
                            fontWeight: n.read_at ? 500 : 700 }}>{n.title}</div>
              <div style={{ fontSize: 11.5, color: "#5a6b78" }}>
                {n.body}{n.body ? " · " : ""}
                {new Date(n.created_at).toLocaleString()}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
