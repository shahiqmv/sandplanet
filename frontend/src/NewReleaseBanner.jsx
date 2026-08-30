import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";

// "There is a new version — reload."
//
// The installed desktop app has no address bar and no refresh button, and
// people leave it open for days, so a release could sit unused indefinitely
// (owner 2026-08-30). The service worker never caches a navigation, so a
// reload is all that is needed; the only missing piece was telling anyone.
//
// Deliberately quiet: it checks on a slow timer and when the window regains
// focus, and it appears once per release. Dismissing it holds it back until
// the NEXT release, because a bar that returns every ten minutes is a bar
// people learn to click past without reading.

const POLL_MS = 10 * 60 * 1000;          // ten minutes
const DISMISSED_KEY = "planet.release.dismissed";

export default function NewReleaseBanner() {
  const booted = useRef(null);           // the build this tab started on
  const [fresh, setFresh] = useState(null);
  const [dismissed, setDismissed] = useState("");
  const [showNotes, setShowNotes] = useState(false);

  useEffect(() => {
    try {
      setDismissed(localStorage.getItem(DISMISSED_KEY) || "");
    } catch {
      /* private windows and blocked site data — the banner still works */
    }
  }, []);

  const check = useCallback(async () => {
    try {
      const { build } = await api("/version");
      if (!build) return;
      if (booted.current === null) { booted.current = build; return; }
      if (build !== booted.current) setFresh(build);
    } catch {
      /* offline or mid-deploy — try again on the next tick */
    }
  }, []);

  useEffect(() => {
    check();
    const t = setInterval(check, POLL_MS);
    // Coming back to the window is the moment a stale tab is most likely to
    // be used, and the cheapest time to notice.
    const onFocus = () => check();
    window.addEventListener("focus", onFocus);
    return () => { clearInterval(t); window.removeEventListener("focus", onFocus); };
  }, [check]);

  if (!fresh || fresh === dismissed) return null;

  return (
    <div role="status"
         style={{ display: "flex", alignItems: "center", gap: 12,
                  flexWrap: "wrap", padding: "9px 16px",
                  background: "var(--sky, #1B7FB8)", color: "#fff",
                  fontSize: 13.5 }}>
      <strong>A new version of Planet is available.</strong>
      <span style={{ opacity: .9 }}>
        Reload to pick it up — nothing you have open will be lost.
      </span>
      <button onClick={() => setShowNotes(true)}
              style={{ background: "transparent", border: "none",
                       color: "#fff", textDecoration: "underline",
                       cursor: "pointer", fontSize: 13,
                       fontFamily: "inherit", padding: 0 }}>
        What changed?</button>
      <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
        <button onClick={() => window.location.reload()}
                style={{ background: "#fff", color: "var(--navy, #14507C)",
                         border: "none", borderRadius: 6, cursor: "pointer",
                         padding: "5px 14px", fontSize: 13, fontWeight: 700,
                         fontFamily: "inherit" }}>
          Reload now</button>
        <button onClick={() => {
                  setDismissed(fresh);
                  try { localStorage.setItem(DISMISSED_KEY, fresh); } catch {}
                }}
                style={{ background: "transparent", color: "#fff",
                         border: "1px solid rgba(255,255,255,.55)",
                         borderRadius: 6, cursor: "pointer",
                         padding: "5px 12px", fontSize: 13,
                         fontFamily: "inherit" }}>
          Later</button>
      </span>
      {showNotes && <ReleaseNotes onClose={() => setShowNotes(false)} />}
    </div>
  );
}

// What actually changed. The banner says a release exists; this says why
// anyone should care (owner 2026-08-30).
export function ReleaseNotes({ onClose }) {
  const [rows, setRows] = useState(null);

  useEffect(() => {
    api("/releases").then(setRows).catch(() => setRows([]));
  }, []);

  return (
    <div onClick={onClose}
         style={{ position: "fixed", inset: 0, zIndex: 320, padding: 20,
                  background: "rgba(16,28,38,.42)", display: "flex",
                  alignItems: "flex-start", justifyContent: "center",
                  overflowY: "auto" }}>
      <div onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true"
           style={{ background: "var(--paper, #fff)", color: "var(--ink,#16232E)",
                    borderRadius: 12, width: "100%", maxWidth: 620,
                    margin: "32px 0", padding: 22,
                    boxShadow: "0 18px 60px rgba(16,28,38,.28)" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <h2 style={{ margin: 0, fontSize: 18, color: "var(--navy)" }}>
            What&rsquo;s new</h2>
          <button onClick={onClose}
                  style={{ marginLeft: "auto", background: "transparent",
                           border: "1px solid #BFD6E6", borderRadius: 8,
                           padding: "5px 13px", cursor: "pointer",
                           fontSize: 13, color: "var(--navy)",
                           fontFamily: "inherit" }}>Close</button>
        </div>
        {rows === null && (
          <p style={{ fontSize: 13.5, color: "#5a6b78" }}>Loading…</p>
        )}
        {rows?.length === 0 && (
          <p style={{ fontSize: 13.5, color: "#5a6b78" }}>
            Nothing recorded yet. Releases worth reading about appear here.
          </p>
        )}
        {(rows || []).map((n) => (
          <div key={n.id} style={{ borderTop: "1px solid var(--line,#e2e8f0)",
                                   padding: "14px 0 2px" }}>
            <div style={{ display: "flex", gap: 10, alignItems: "baseline",
                          flexWrap: "wrap" }}>
              <strong style={{ fontSize: 14.5 }}>{n.title}</strong>
              {n.area && (
                <span style={{ fontSize: 11, fontWeight: 700,
                               padding: "2px 8px", borderRadius: 999,
                               background: "#eef4fb", color: "#16527E" }}>
                  {n.area}</span>
              )}
              <span style={{ marginLeft: "auto", fontSize: 12,
                             color: "#5a6b78" }}>{n.released_on}</span>
            </div>
            {n.body && (
              <p style={{ margin: "5px 0 0", fontSize: 13.5,
                          whiteSpace: "pre-wrap" }}>{n.body}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
