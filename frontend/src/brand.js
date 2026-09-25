// The brand layer (MARINE_BUILD_BRIEF.md §2): name, colours, marks, feature
// switches and the sister-app switcher, loaded once before sign-in from
// /api/v1/brand and applied as CSS variables. Sand Planet's values are the
// defaults in index.css, so a slow or failed load changes nothing.
//
// The same build serves a sister instance under a path prefix (phase 2:
// app.sandplanet.mv/marine/); every request and cookie name derives from
// that prefix here, in one place.
export const PREFIX = (() => {
  const m = /^\/(marine)(?=\/|$)/.exec(window.location.pathname);
  return m ? `/${m[1]}` : "";
})();
export const API_BASE = `${PREFIX}/api/v1`;
export const CSRF_COOKIE = PREFIX ? `${PREFIX.slice(1)}_csrftoken` : "csrftoken";

const VARS = {
  primary: ["--navy"], primary_deep: ["--navy-deep"], accent: ["--sky"], soft: ["--sky-soft"],
};

let _brand = null;
const _listeners = new Set();

export function getBrand() { return _brand; }
export function onBrand(fn) { _listeners.add(fn); if (_brand) fn(_brand); return () => _listeners.delete(fn); }

export function applyBrand(b) {
  _brand = b;
  const root = document.documentElement.style;
  Object.entries(VARS).forEach(([token, names]) => {
    const v = b?.colours?.[token];
    if (v) names.forEach((n) => root.setProperty(n, v));
  });
  if (b?.name) document.title = document.title.replace(/^Sand Planet/i, b.name.replace(/\b\w+/g, (w) => w[0] + w.slice(1).toLowerCase()));
  _listeners.forEach((fn) => fn(b));
}

export async function loadBrand() {
  try {
    const res = await fetch(`${API_BASE}/brand`, { credentials: "include" });
    if (!res.ok) return null;
    const b = await res.json();
    applyBrand(b);
    return b;
  } catch {
    return null;
  }
}

/** "SAND PLANET" → ["SAND", "PLANET"]-style split for the two-tone wordmark. */
export function nameParts(name) {
  const parts = (name || "SAND PLANET").trim().split(/\s+/);
  return [parts[0] || "", parts.slice(1).join(" ")];
}
