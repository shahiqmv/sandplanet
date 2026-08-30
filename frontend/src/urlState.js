// The app kept every navigation decision in React state, so the address bar
// never moved: refresh dumped you on the dashboard, Back left the app, and
// nothing could be opened in a second tab (owner 2026-08-28). This encodes
// the current view into the URL hash and reads it back.
//
// Only views that can be REBUILT from an id or a ref are encoded. Half-filled
// forms (a DPR being typed, a new PYR) are deliberately not: resurrecting a
// draft from a URL would promise more than it can keep, so a refresh there
// lands on the page behind the form.
const REF_MODES = ["ipr-view", "irn-view", "line-view", "qa-view",
                   "shipment-view", "pr-match"];
const SITE_MODES = ["attendance", "dma", "workforce", "stock", "tools",
                    "units", "manpower", "petty-cash", "testing",
                    "submittals"];

export function encodeView({ hoPage, siteId, docView }) {
  if (docView) {
    const m = docView.mode;
    if (m === "project" && docView.projectId) {
      return `#/project/${docView.projectId}`;
    }
    if (REF_MODES.includes(m) && docView.doc?.ref) {
      const extra = docView.shipmentId ? `?s=${docView.shipmentId}` : "";
      return `#/doc/${m}/${encodeURIComponent(docView.doc.ref)}${extra}`;
    }
    if (SITE_MODES.includes(m) && siteId) {
      return `#/site/${siteId}/${m}`;
    }
    if (m === "vessels") return "#/vessels";
    // Your own record. A mode with no route here is silently
    // reset by the hash listener on the next tick.
    if (m === "my-record") return "#/me";
    // a form or another transient view — keep the page behind it
  }
  if (siteId) return `#/site/${siteId}`;
  return `#/ho/${hoPage || "sites"}`;
}

export function decodeView(hash) {
  const raw = (hash || "").replace(/^#\/?/, "");
  if (!raw) return null;
  const [path, query] = raw.split("?");
  const parts = path.split("/").filter(Boolean);
  const params = new URLSearchParams(query || "");
  if (parts[0] === "ho" && parts[1]) return { hoPage: parts[1] };
  // #/open/<ref> — a landing route, never written by encodeView. A desktop
  // push notification knows the document ref but not which view renders it,
  // so it hands the ref to the app, which resolves it and rewrites the URL
  // to the canonical #/doc/... form (owner 2026-08-28).
  if (parts[0] === "open" && parts[1]) {
    return { openRef: decodeURIComponent(parts[1]) };
  }
  if (parts[0] === "vessels") return { docView: { mode: "vessels" } };
  if (parts[0] === "me") return { docView: { mode: "my-record" } };
  if (parts[0] === "project" && parts[1]) {
    return { docView: { mode: "project", projectId: Number(parts[1]) } };
  }
  if (parts[0] === "doc" && parts[1] && parts[2]) {
    const dv = { mode: parts[1], doc: { ref: decodeURIComponent(parts[2]) } };
    if (params.get("s")) dv.shipmentId = Number(params.get("s"));
    return { docView: dv };
  }
  if (parts[0] === "site" && parts[1]) {
    const out = { siteId: Number(parts[1]) };
    if (parts[2] && SITE_MODES.includes(parts[2])) {
      out.docView = { mode: parts[2] };
    }
    return out;
  }
  return null;
}
