function getCookie(name) {
  const match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
  return match ? decodeURIComponent(match[2]) : null;
}

function prettyField(key) {
  if (key === "non_field_errors" || key === "detail") return "";
  return key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

// Turn any API error body into a message a person can act on. Handles
// {detail: "..."}, DRF field errors {field: ["msg", ...]}, plain strings,
// and nested shapes — so users see "Code: no more than 6 characters" instead
// of "Request failed (400)".
function readError(data, status) {
  if (data == null) return `Request failed (${status})`;
  if (typeof data === "string") return data;
  if (typeof data.detail === "string") return data.detail;
  const parts = [];
  const walk = (val, label) => {
    if (val == null) return;
    if (typeof val === "string") {
      parts.push(label ? `${label}: ${val}` : val);
    } else if (Array.isArray(val)) {
      val.forEach((v) => walk(v, label));
    } else if (typeof val === "object") {
      Object.entries(val).forEach(([k, v]) => walk(v, prettyField(k) || label));
    }
  };
  walk(data, "");
  return parts.filter(Boolean).join(" · ") || `Request failed (${status})`;
}

// ---- "something is happening" -----------------------------------------------
// Every request in the app goes through api / apiUpload / apiDownload, so
// tracking them here covers the whole app at once.
//
// This exists because work that takes real time looked identical to work that
// had failed: issuing a MAR with a large enclosure ran for minutes with nothing
// on screen, and people closed the tab or navigated away mid-request, killing
// it (owner 2026-08-20). A write that is abandoned half-way can leave a
// document issued with no PDF, which is exactly what happened.

let _seq = 0;
const _inflight = new Map();          // id -> {label, write, progress}
const _listeners = new Set();

function _emit() {
  const jobs = [..._inflight.values()];
  _listeners.forEach((fn) => fn(jobs));
}

/** Subscribe to in-flight requests. Returns an unsubscribe function. */
export function onBusy(fn) {
  _listeners.add(fn);
  fn([..._inflight.values()]);
  return () => _listeners.delete(fn);
}

function _start(label, write) {
  const id = ++_seq;
  _inflight.set(id, { id, label, write, progress: null });
  _emit();
  return id;
}

function _progress(id, fraction) {
  const job = _inflight.get(id);
  if (!job) return;
  job.progress = fraction;
  _emit();
}

function _end(id) {
  _inflight.delete(id);
  _emit();
}

// Losing a GET costs nothing; losing a write can leave a half-finished
// document. Only writes are worth interrupting someone over.
window.addEventListener("beforeunload", (e) => {
  if (![..._inflight.values()].some((j) => j.write)) return;
  e.preventDefault();
  e.returnValue = "";                 // browsers show their own wording
  return "";
});

function _label(method, path) {
  if (method === "GET") return "Loading";
  if (method === "DELETE") return "Removing";
  if (path.includes("/actions/issue")) return "Issuing — this can take a minute";
  if (path.includes("/actions/")) return "Submitting";
  return "Saving";
}


export function apiUpload(path, formData, method = "POST") {
  // XMLHttpRequest, not fetch: fetch cannot report how much of a body has been
  // sent, and a 15MB enclosure over a site connection needs a real percentage
  // rather than a spinner that might mean anything (owner 2026-08-20).
  return new Promise((resolve, reject) => {
    const id = _start("Uploading", true);
    const xhr = new XMLHttpRequest();
    xhr.open(method, `/api/v1${path}`, true);
    xhr.withCredentials = true;
    xhr.setRequestHeader("X-CSRFToken", getCookie("csrftoken"));

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) _progress(id, e.loaded / e.total);
    };
    // Once the bytes are up, the server still has work to do — rendering a
    // PDF, merging enclosures. Switch the message rather than sitting at 100%.
    xhr.upload.onload = () => {
      const job = _inflight.get(id);
      if (job) { job.label = "Processing"; job.progress = null; _emit(); }
    };
    xhr.onload = () => {
      _end(id);
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(data);
      const err = new Error(readError(data, xhr.status));
      err.data = data;
      err.status = xhr.status;
      reject(err);
    };
    xhr.onerror = () => {
      _end(id);
      reject(new Error("The upload did not reach the server — check the "
                       + "connection and try again."));
    };
    xhr.onabort = () => { _end(id); reject(new Error("Upload cancelled.")); };
    xhr.send(formData);
  });
}

export async function api(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRFToken"] = getCookie("csrftoken");
  const id = _start(_label(method, path), method !== "GET");
  let res;
  try {
    res = await fetch(`/api/v1${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } finally {
    _end(id);
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(readError(data, res.status));
    err.data = data;
    err.status = res.status;
    throw err;
  }
  return data;
}


// Download a binary response (the ESC/POS slip job) and hand it to the browser
// as a file, WITHOUT navigating.
//
// A plain <a href> could not do this job: on any error the browser left the app
// and displayed raw JSON, and on success it downloaded in silence, so the
// button looked broken either way (owner 2026-08-19). Returns a short summary
// to show the user; throws a readable Error otherwise.
export async function apiDownload(path) {
  const id = _start("Preparing the download", false);
  let res;
  try {
    res = await fetch(`/api/v1${path}`, { credentials: "same-origin" });
  } finally {
    _end(id);
  }
  if (!res.ok) {
    let data = null;
    try { data = await res.json(); } catch { /* not JSON — fall through */ }
    throw new Error(readError(data, res.status));
  }
  const blob = await res.blob();
  // Prefer the server's filename; it names the site and period.
  const disp = res.headers.get("content-disposition") || "";
  const match = disp.match(/filename="?([^"]+)"?/);
  const name = match ? match[1] : path.split("/").pop();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke late: Safari aborts the save if the URL dies too soon.
  setTimeout(() => URL.revokeObjectURL(url), 30000);
  return { name, bytes: blob.size,
           count: Number(res.headers.get("x-slip-count")) || null };
}
