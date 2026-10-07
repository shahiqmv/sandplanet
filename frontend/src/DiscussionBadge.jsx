import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";

/* The corner badge (owner 2026-10-07): a chip in the bottom-right of every
 * page while a question waits on you — amber, red once something has sat
 * for more than two days — opening a list of what is waiting on you and
 * what you are waiting on others for. A line opens the document with the
 * discussion panel open on that question. Refreshes every minute.
 */
const POLL_MS = 60000;
const ago = (days) => days === 0 ? "today" : days === 1 ? "1 day" : `${days} days`;

export default function DiscussionBadge({ onOpen }) {
  const [d, setD] = useState(null);
  const [open, setOpen] = useState(false);
  const load = useCallback(() => api("/discussion/mine").then(setD)
    .catch(() => {}), []);
  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    const onFocus = () => load();
    window.addEventListener("focus", onFocus);
    return () => { clearInterval(t); window.removeEventListener("focus", onFocus); };
  }, [load]);
  if (!d || (d.count === 0 && d.asked_count === 0)) return null;

  const tone = d.count === 0 ? "#5a6b78" : d.oldest_days > 2 ? "#a3271b" : "#b45309";
  function go(item) {
    // the panel opens on that question when the document loads
    try {
      localStorage.setItem("planet:discussion", "open");
      localStorage.setItem("planet:discussion:focus", String(item.comment_id));
    } catch { /* private mode */ }
    setOpen(false);
    onOpen(item);
  }
  const Row = ({ it, mine }) => (
    <div onClick={() => go(it)}
         style={{ padding: "7px 10px", cursor: "pointer",
                  borderTop: "1px solid #eef2f5", fontSize: 12.5 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
        <strong style={{ fontFamily: "var(--font-mono)", color: "var(--sp-navy)" }}>
          {it.ref}</strong>
        <span style={{ color: "#5a6b78" }}>
          {mine ? `to ${it.to.join(", ")}` : it.asked_by}</span>
        <span style={{ marginLeft: "auto", fontSize: 11.5,
                       color: it.days_open > 2 ? "#a3271b" : "#8a97a1" }}>
          {ago(it.days_open)}</span>
      </div>
      <div style={{ color: "#1f2d3a", whiteSpace: "nowrap", overflow: "hidden",
                    textOverflow: "ellipsis" }}>{it.body}</div>
    </div>);

  return (
    <div style={{ position: "fixed", right: 18, bottom: 18, zIndex: 36 }}>
      {open && (
        <div style={{ position: "absolute", right: 0, bottom: 44, width: 360,
                      maxHeight: "60vh", overflowY: "auto", background: "#fff",
                      borderRadius: 10, boxShadow: "0 10px 30px rgba(15,30,45,.25)",
                      border: "1px solid var(--sp-border, #d5dde3)" }}>
          {d.count > 0 && (<>
            <div style={{ padding: "8px 10px 4px", fontSize: 11.5, fontWeight: 700,
                          color: tone, letterSpacing: ".04em" }}>
              WAITING ON YOU · {d.count}</div>
            {d.items.map((it) => <Row key={`m${it.comment_id}`} it={it} />)}
          </>)}
          {d.asked_count > 0 && (<>
            <div style={{ padding: "10px 10px 4px", fontSize: 11.5, fontWeight: 700,
                          color: "#5a6b78", letterSpacing: ".04em" }}>
              ASKED BY YOU, STILL OPEN · {d.asked_count}</div>
            {d.asked.map((it) => <Row key={`a${it.comment_id}`} it={it} mine />)}
          </>)}
        </div>)}
      <button onClick={() => setOpen((o) => !o)}
        title={d.count ? `${d.count} question${d.count === 1 ? "" : "s"} waiting on you`
          : `${d.asked_count} you asked, still open`}
        style={{ background: tone, color: "#fff", border: "none", borderRadius: 999,
                 padding: "8px 14px", fontSize: 13.5, fontWeight: 700,
                 cursor: "pointer", boxShadow: "0 4px 14px rgba(15,30,45,.3)" }}>
        💬 {d.count || d.asked_count}
      </button>
    </div>
  );
}
