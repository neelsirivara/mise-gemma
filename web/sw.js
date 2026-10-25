// Offline shell for the installed web app. The UI loads from cache; every /api call
// goes to the Mise hub (the laptop) and is never cached. On-phone mode also needs the
// Gemma runtime from the CDN (cached here, cache-first) and the model (its own cache,
// "mise-model-v1", written by web/lib/phone/llm.js and never touched here).
const CACHE = "mise-shell-v2";
const RUNTIME = "mise-runtime-v1";
const CDN = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-genai@";
const SHELL = ["./", "app.js", "style.css", "manifest.webmanifest", "icons/icon-192.png", "icons/apple-touch-icon.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k.startsWith("mise-shell-") && k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method === "GET" && e.request.url.startsWith(CDN)) {
    // versioned URLs never change: cache first, so on-phone mode starts with no network
    e.respondWith(caches.open(RUNTIME).then(async (c) => (await c.match(e.request)) || fetch(e.request).then((r) => {
      if (r.ok) c.put(e.request, r.clone());
      return r;
    })));
    return;
  }
  if (e.request.method !== "GET" || url.pathname.includes("/api/") || url.origin !== location.origin) return;
  // network first so a fresh deploy wins, cache when offline
  e.respondWith(
    fetch(e.request)
      .then((r) => { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return r; })
      .catch(() => caches.match(e.request, { ignoreSearch: true }))
  );
});
