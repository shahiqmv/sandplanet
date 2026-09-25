// The vertical navigation rail (owner 2026-09-25): the same groups and
// pages as the top bar, down the left, with the active group open so its
// pages are one click away. Two widths — the full rail with labels, and a
// 52px icon rail that expands over the page on hover. Wide working pages
// (payroll, attendance, the register) collapse it on their own unless the
// user pinned it open. Below 900px the phone drawer takes over.
import { useEffect, useState } from "react";
import { Icon } from "./ui.jsx";

const GROUP_ICON = {
  approvals: "clipboard", sitesGrp: "anchor", procurement: "box", fleet: "truck",
  meetingsGrp: "clock", finance: "wallet", people: "users", adminGrp: "globe",
};

export const RAIL_KEY = "planet:rail";   // "open" | "icons" — the user's own choice

export function readRail() {
  try { return localStorage.getItem(RAIL_KEY) || "open"; } catch { return "open"; }
}

export default function SideNav({ groups, activeKey, hoPage, isCurrent, pendingCount,
                                  onGo, wide }) {
  const [pref, setPref] = useState(readRail);
  const [expanded, setExpanded] = useState(() => new Set());
  // Which groups show their pages: the active one always, plus any the
  // user opened this session.
  const open = (g) => g.key === activeKey || expanded.has(g.key);
  const toggle = (g) => setExpanded((s) => {
    const n = new Set(s);
    if (n.has(g.key)) n.delete(g.key); else n.add(g.key);
    return n;
  });
  const collapsed = pref === "icons" || (wide && pref !== "pinned");
  function setRail(v) {
    setPref(v);
    try { localStorage.setItem(RAIL_KEY, v); } catch { /* private mode */ }
  }
  useEffect(() => { setExpanded(new Set()); }, [activeKey]);

  return (
    <aside className={"sidenav" + (collapsed ? " collapsed" : "")} aria-label="Main navigation">
      <div className="rail">
        {groups.map((g) => {
          const isActive = g.key === activeKey && isCurrent;
          const single = g.subs.length === 1;
          return (
            <div key={g.key} className={"rail-group" + (isActive ? " active" : "")}>
              <a href={`#/ho/${g.subs[0][0]}`}
                 className={"rail-head" + (isActive ? " on" : "")}
                 title={g.label}
                 onClick={(e) => {
                   if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
                   e.preventDefault();
                   if (single || !open(g)) onGo(g.subs[0][0]);
                   if (!single) toggle(g);
                 }}>
                <Icon name={GROUP_ICON[g.key] || "grid"} size={17} style={{ marginRight: 0 }} />
                <span className="rail-label">{g.label}</span>
                {g.key === "approvals" && pendingCount > 0 && (
                  <span className="nav-badge rail-badge">{pendingCount}</span>
                )}
                {!single && <span className="rail-chev" aria-hidden="true">{open(g) ? "▾" : "▸"}</span>}
              </a>
              {!single && open(g) && (
                <div className="rail-subs">
                  {g.subs.map(([key, label]) => (
                    <a key={key} href={`#/ho/${key}`}
                       className={"rail-item" + (hoPage === key && isCurrent ? " on" : "")}
                       onClick={(e) => {
                         if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
                         e.preventDefault();
                         onGo(key);
                       }}>
                      {label}
                    </a>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        <div className="rail-foot">
          {collapsed ? (
            <button className="rail-head" title={wide ? "This page is wide — the rail keeps out of its way. Pin it open anyway." : "Show labels"}
                    onClick={() => setRail(wide ? "pinned" : "open")}>
              <span className="rail-ico" aria-hidden="true">»</span>
              <span className="rail-label">{wide ? "Pin open" : "Show labels"}</span>
            </button>
          ) : (
            <button className="rail-head" title="Collapse to icons" onClick={() => setRail("icons")}>
              <span className="rail-ico" aria-hidden="true">«</span>
              <span className="rail-label">Collapse</span>
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}
