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
    </div>
  );
}
