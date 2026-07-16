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
