/* Planet Desktop service worker — installability + Web Push.
   Served by Django at /sw.js with Service-Worker-Allowed:/ (scope /).

   Deliberately NOT an offline shell. Caching the SPA shell would leave
   installed windows running yesterday's build against today's server, which
   is the classic desktop-app support burden — so navigations always go to
   the network and only content-hashed build assets are cached. Nothing here
   holds secrets: it caches static files and renders push payloads.

   To retire it: replace this file's body with
   `self.addEventListener("install", () => self.registration.unregister())`
   and deploy — installed browsers pick it up on their next navigation,
   because /sw.js is served no-cache. */
const CACHE = "planet-desktop-v1";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  // Planet Mobile (/m) and the client portal each have their own scope and
  // their own worker — never answer for them.
  if (url.pathname.startsWith("/m") || url.pathname.startsWith("/portal")) return;
  // Only the build's hashed assets, and never a navigation or an API call.
  if (req.mode === "navigate" || !url.pathname.startsWith("/static/")) return;

  event.respondWith(
    caches.match(req).then((hit) => {
      const net = fetch(req)
        .then((res) => {
          if (res && res.ok && res.type === "basic") {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(() => hit);
      return hit || net;
    })
  );
});

// ---- Web Push -----------------------------------------------------------
self.addEventListener("push", (event) => {
  let data = { title: "Sand Planet", body: "", url: "/" };
  try {
    if (event.data) data = Object.assign(data, event.data.json());
  } catch (e) {
    if (event.data) data.body = event.data.text();
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "Sand Planet", {
      body: data.body || "",
      icon: "/static/desktop/icon-192.png",
      badge: "/static/desktop/icon-192.png",
      tag: data.url || "planet",
      data: { url: data.url || "/" },
    })
  );
});

// Clicking a notification focuses the window that is already open and tells
// it where to go, rather than piling up windows.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((list) => {
        for (const client of list) {
          const path = new URL(client.url).pathname;
          if (path.startsWith("/m") || path.startsWith("/portal")) continue;
          if ("focus" in client) {
            client.postMessage({ type: "navigate", url: target });
            return client.focus();
          }
        }
        if (self.clients.openWindow) return self.clients.openWindow(target);
      })
  );
});
