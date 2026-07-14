// Web Push subscription lifecycle. Best-effort: push failures fall back to the
// in-app Alerts feed, so nothing here throws to the UI beyond a returned flag.
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

// Ask permission, subscribe with the server's VAPID key, register with backend.
// Returns { ok, reason }.
export async function enablePush() {
  if (!pushSupported()) return { ok: false, reason: "unsupported" };
  const { public_key, enabled } = await api.vapidKey().catch(() => ({}));
  if (!enabled || !public_key) return { ok: false, reason: "server-off" };

  const perm = await Notification.requestPermission();
  if (perm !== "granted") return { ok: false, reason: "denied" };

  const reg = await readyRegistration();
  if (!reg) return { ok: false, reason: "no-sw" };
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlB64ToUint8Array(public_key),
    });
  }
  const json = sub.toJSON();
  await api.pushSubscribe({ endpoint: sub.endpoint, keys: json.keys });
  return { ok: true };
}

export async function disablePush() {
  const reg = await readyRegistration();
  if (!reg) return;
  const sub = await reg.pushManager.getSubscription();
  if (sub) {
    await api.pushUnsubscribe(sub.endpoint).catch(() => {});
    await sub.unsubscribe().catch(() => {});
  }
}
