// Client Portal API — Bearer token against /api/client. The token is the only
// client-held secret; every rule is server-enforced. Isolated from the staff
// SPA (which uses session cookies).
const BASE = "/api/client";
const TOKEN_KEY = "planet.client.token";

export const getToken = () => localStorage.getItem(TOKEN_KEY) || "";
export const setToken = (t) =>
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY);

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

// Download a file from the token-authed API (a plain <a> can't send the Bearer
// header, so fetch as a blob and trigger the download client-side).
export async function downloadFile(path, filename) {
  const res = await fetch(BASE + path,
    { headers: { Authorization: `Bearer ${getToken()}` } });
  if (!res.ok) throw new ApiError("Download failed.", res.status);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

export async function api(path, { method = "GET", body } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(BASE + path, { method, headers,
      body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch {
    throw new ApiError("You're offline — check your connection.", 0);
  }
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json")
    ? await res.json().catch(() => null) : null;
  if (!res.ok) {
    if (res.status === 401) setToken("");
    throw new ApiError((data && data.detail) || "Something went wrong.",
                       res.status);
  }
  return data;
}
