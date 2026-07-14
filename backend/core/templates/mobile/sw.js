/* Planet Mobile service worker — app-shell cache + Web Push.
   Served by Django at /m/sw.js with Service-Worker-Allowed:/m/ (scope /m/).
   No secrets here; it only caches shells/assets and renders push payloads. */
const CACHE = "planet-mobile-v1";
const SHELL = "/m/";
const PRECACHE = [
  "/m/",
  "/m/manifest.webmanifest",
  "/static/mobile/icon-192.png",
  "/static/mobile/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(PRECACHE).catch(() => null))
      .then(() => self.skipWaiting())
  );
});

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

  // API is never cached — approve/return need live state (R6 §10).
  if (url.pathname.startsWith("/api/")) return;

  // App navigations under /m: network-first, fall back to the cached shell.
  if (req.mode === "navigate" && url.pathname.startsWith("/m")) {
    event.respondWith(
      fetch(req).catch(() => caches.match(SHELL).then((r) => r || fetch(req)))
    );
    return;
  }

  // Hashed build assets + icons: cache-first, refresh in the background.
  if (
    url.pathname.startsWith("/static/") ||
    url.pathname.startsWith("/m/manifest")
  ) {
    event.respondWith(
      caches.match(req).then((hit) => {
        const net = fetch(req)
          .then((res) => {
            if (res && res.ok) {
              const copy = res.clone();
              caches.open(CACHE).then((c) => c.put(req, copy));
            }
            return res;
          })
          .catch(() => hit);
        return hit || net;
      })
    );
  }
});

// ---- Web Push -----------------------------------------------------------
self.addEventListener("push", (event) => {
  let data = { title: "Planet", body: "", url: "/m" };
  try {
    if (event.data) data = Object.assign(data, event.data.json());
  } catch (e) {
    if (event.data) data.body = event.data.text();
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "Planet", {
      body: data.body || "",
      icon: "/static/mobile/icon-192.png",
      badge: "/static/mobile/icon-192.png",
      tag: data.url || "planet",
      data: { url: data.url || "/m" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/m";
  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((list) => {
        for (const client of list) {
          if (client.url.includes("/m") && "focus" in client) {
            client.postMessage({ type: "navigate", url: target });
            return client.focus();
          }
        }
        if (self.clients.openWindow) return self.clients.openWindow(target);
      })
  );
});
