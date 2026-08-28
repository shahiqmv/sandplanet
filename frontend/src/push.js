// Desktop web push — permission, subscription, and the server registration
// that ties this browser to the signed-in user. Mirrors src/mobile/push.js
// against the desktop API; failures are always non-fatal, because the in-app
// bell remains the source of truth either way.
import { api } from "./api.js";

export function pushSupported() {
  return (
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

export function pushPermission() {
  return pushSupported() ? Notification.permission : "unsupported";
}

// True when the app is running in its own installed window rather than a
// browser tab — used to tell people whether "Install" is still worth offering.
export function isInstalled() {
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    window.navigator.standalone === true
  );
}

function urlB64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function readyRegistration() {
  if (!("serviceWorker" in navigator)) return null;
  return navigator.serviceWorker.ready;
}

// A live subscription is the reliable "notifications are on" signal —
// Notification.permission alone can read granted with nothing registered.
export async function isSubscribed() {
  try {
    const reg = await readyRegistration();
    if (!reg) return false;
    return !!(await reg.pushManager.getSubscription());
  } catch {
    return false;
  }
}

// Ask permission, subscribe with the server's VAPID key, register with the
// backend. Returns { ok, reason } — never throws.
export async function enablePush() {
  if (!pushSupported()) return { ok: false, reason: "unsupported" };
  const { public_key, enabled } = await api("/push/key").catch(() => ({}));
  if (!enabled || !public_key) return { ok: false, reason: "server-off" };

  const perm = await Notification.requestPermission();
  if (perm !== "granted") return { ok: false, reason: perm };

  const reg = await readyRegistration();
  if (!reg) return { ok: false, reason: "no-sw" };
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    try {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlB64ToUint8Array(public_key),
      });
    } catch {
      return { ok: false, reason: "subscribe-failed" };
    }
  }
  const json = sub.toJSON();
  try {
    await api("/push/subscribe", {
      method: "POST",
      body: { endpoint: sub.endpoint, keys: json.keys },
    });
  } catch {
    return { ok: false, reason: "server-error" };
  }
  return { ok: true };
}

export async function disablePush() {
  const reg = await readyRegistration();
  if (!reg) return;
  const sub = await reg.pushManager.getSubscription();
  if (!sub) return;
  await api("/push/unsubscribe", {
    method: "POST", body: { endpoint: sub.endpoint },
  }).catch(() => {});
  await sub.unsubscribe().catch(() => {});
}
