// Planet Mobile API client — Bearer device token against /api/mobile/v1/.
// The token is the only client-held secret; every rule is server-enforced.
const BASE = "/api/mobile/v1";
const TOKEN_KEY = "planet.mobile.token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}
export function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data || {};
  }
}

async function req(method, path, body) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new ApiError("You're offline — check your connection.", 0);
  }
  let data = null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    data = await res.json().catch(() => null);
  }
  if (res.status === 401) {
    setToken("");
    throw new ApiError((data && data.detail) || "Session expired.", 401, data);
  }
  if (!res.ok) {
    const msg = (data && data.detail) || `Request failed (${res.status}).`;
    throw new ApiError(msg, res.status, data);
  }
  return data;
}

export const api = {
  login: (username, password) =>
    req("POST", "/auth/login", { username, password }),
  logout: () => req("POST", "/auth/logout", {}),
  me: () => req("GET", "/me"),
  queue: () => req("GET", "/queue"),
  actioned: (days = 30) => req("GET", `/actioned?days=${days}`),
  document: (ref) => req("GET", `/documents/${encodeURIComponent(ref)}`),
  approve: (ref, comment) =>
    req("POST", `/documents/${encodeURIComponent(ref)}/approve`, { comment }),
  return: (ref, comment) =>
    req("POST", `/documents/${encodeURIComponent(ref)}/return`, { comment }),
  requests: () => req("GET", "/requests"),
  timeline: (ref) => req("GET", `/requests/${encodeURIComponent(ref)}/timeline`),
  alerts: () => req("GET", "/alerts"),
  alertsRead: (ids) => req("POST", "/alerts/read", ids ? { ids } : {}),
  vapidKey: () => req("GET", "/push/vapid-key"),
  pushSubscribe: (sub) => req("POST", "/push/subscribe", sub),
  pushUnsubscribe: (endpoint) =>
    req("POST", "/push/unsubscribe", { endpoint }),
};
