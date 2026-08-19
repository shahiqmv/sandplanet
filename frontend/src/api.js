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

export async function apiUpload(path, formData, method = "POST") {
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers: { "X-CSRFToken": getCookie("csrftoken") },
    credentials: "same-origin",
    body: formData,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(readError(data, res.status));
    err.data = data;
    err.status = res.status;
    throw err;
  }
  return data;
}

export async function api(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRFToken"] = getCookie("csrftoken");
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers,
    credentials: "same-origin",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
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
  const res = await fetch(`/api/v1${path}`, { credentials: "same-origin" });
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
