// Offline shell for the installed web app. The UI loads from cache; every /api call
// goes to the Mise hub (the laptop) and is never cached. On-phone mode also needs the
// Gemma runtime from the CDN (cached here, cache-first) and the model (its own cache,
// "mise-model-v1", written by web/lib/phone/llm.js and never touched here).
const CACHE = "mise-shell-v3";
const RUNTIME = "mise-runtime-v1";
const CDN = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-genai@";
// everything the app needs to open and cook with no network (on-phone mode): pages, code, Mum, fonts, starters
const SHELL = ["mise/index.html", "mise/mise.css", "mise/manifest.webmanifest", "mise/leaf-shadow.svg",
  ...["main", "ui", "mum", "scenes"].map((f) => `mise/js/${f}.js`),
  ...["capture", "home", "pantry", "recipe", "cook", "feedback", "phone"].map((f) => `mise/js/views/${f}.js`),
  ...["api", "voice", "camera"].map((f) => `lib/${f}.js`),
  ...["hub", "llm", "book", "chef", "cook", "companion", "json"].map((f) => `lib/phone/${f}.js`),
  ...["indian", "italian", "japanese", "chinese", "mexican", "american"].map((m) => `mise/mums/${m}.png`),
  ...["caprese_salad", "carbonara", "guacamole", "shakshuka"].map((r) => `mise/starters/${r}.json`),
  "fonts/fonts.css", "fonts/AtkinsonHyperlegible-normal-400.woff2", "fonts/AtkinsonHyperlegible-normal-700.woff2",
  "fonts/AtkinsonHyperlegible-italic-400.woff2", "fonts/BricolageGrotesque-normal-500_800.woff2", "fonts/Nunito-normal-600_900.woff2",
  "icons/icon-192.png", "icons/apple-touch-icon.png", "icons/mise-logo.svg", "icons/mise-mark.svg", "icons/favicon.png"];

self.addEventListener("install", (e) => {
  // one by one: a single missing file must not stop the rest from being saved
  e.waitUntil(caches.open(CACHE).then((c) => Promise.all(SHELL.map((u) => c.add(u).catch(() => {})))).then(() => self.skipWaiting()));
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
      .catch(async () => (await caches.match(e.request, { ignoreSearch: true }))
        // offline and opening the app itself ("/" on the hosted page, "/mise/" on the laptop): the saved page
        || (e.request.mode === "navigate" ? caches.match("mise/index.html") : undefined))
  );
});
