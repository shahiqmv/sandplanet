function getCookie(name) {
  const match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
  return match ? decodeURIComponent(match[2]) : null;
}

export async function apiUpload(path, formData, method = "POST") {
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers: { "X-CSRFToken": getCookie("csrftoken") },
    credentials: "same-origin",
    body: formData,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(data?.detail || `Upload failed (${res.status})`);
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
    throw new Error(data?.detail || `Request failed (${res.status})`);
  }
  return data;
}
