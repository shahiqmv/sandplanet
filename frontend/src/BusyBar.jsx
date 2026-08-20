import { useEffect, useState } from "react";
import { onBusy } from "./api.js";

// A bar across the top of the window whenever the app is talking to the server,
// plus a pill naming what it is doing.
//
// Work that takes real time used to look exactly like work that had failed:
// issuing a MAR with a large enclosure ran for minutes with nothing on screen,
// so people closed the tab or moved on and killed it half-way (owner
// 2026-08-20). An abandoned write can leave a document issued with no PDF.
//
// Uploads show a true percentage — apiUpload reports bytes sent. Everything
// else shows an indeterminate sweep, because a made-up percentage that stalls
// at 90% is worse than an honest "still going".

export default function BusyBar() {
  const [jobs, setJobs] = useState([]);
  // A tiny delay stops the bar flickering on every fast request; anything that
  // finishes inside it never needed announcing.
  const [shown, setShown] = useState(false);

  useEffect(() => onBusy(setJobs), []);

  useEffect(() => {
    if (!jobs.length) { setShown(false); return undefined; }
    const t = setTimeout(() => setShown(true), 350);
    return () => clearTimeout(t);
  }, [jobs.length]);

  if (!shown || !jobs.length) return null;

  // The slowest-looking job is the one worth naming: an upload in progress
  // beats a background GET.
  const job = jobs.find((j) => j.progress != null)
           || jobs.find((j) => j.write)
           || jobs[0];
  const pct = job.progress != null ? Math.round(job.progress * 100) : null;

  return (
    <>
      <style>{`
        @keyframes sp-sweep {
          0%   { left: -35%; width: 35%; }
          50%  { left: 40%;  width: 45%; }
          100% { left: 100%; width: 35%; }
        }
      `}</style>
      <div style={{ position: "fixed", top: 0, left: 0, right: 0, height: 3,
                    background: "rgba(14,58,92,.12)", zIndex: 9999,
                    overflow: "hidden" }}>
        {pct == null ? (
          <div style={{ position: "absolute", top: 0, height: "100%",
                        background: "var(--sp-sky, #29ABE2)",
                        animation: "sp-sweep 1.1s ease-in-out infinite" }} />
        ) : (
          <div style={{ height: "100%", width: `${pct}%`,
                        background: "var(--sp-sky, #29ABE2)",
                        transition: "width .15s linear" }} />
        )}
      </div>

      {/* Centred and capped: on a phone the full sentence used to run under
          the logo and out of the header. */}
      <div style={{ position: "fixed", top: 10, left: "50%", zIndex: 9999,
                    transform: "translateX(-50%)",
                    maxWidth: "min(88vw, 380px)",
                    background: "#0E3A5C", color: "#fff",
                    borderRadius: 999, padding: "5px 14px", fontSize: 12.5,
                    lineHeight: 1.35, textAlign: "center",
                    boxShadow: "0 2px 10px rgba(0,0,0,.18)",
                    pointerEvents: "none" }}>
        <span style={{ whiteSpace: "nowrap" }}>
          {job.label}{pct != null ? ` ${pct}%` : "…"}
          {jobs.length > 1 && (
            <span style={{ opacity: .7 }}> +{jobs.length - 1}</span>
          )}
        </span>
        {job.write && (
          <span style={{ opacity: .8, display: "block", fontSize: 11.5 }}>
            Please keep this page open</span>
        )}
      </div>
    </>
  );
}
