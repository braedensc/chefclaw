// chefclaw service worker (V2-C) — minimal, dependency-free, and hand-written so
// the cache policy is auditable in one screen.
//
// THE INVARIANT: never touch /api/*. Sessions/auth and owner-scoped recipe
// images live under /api, and must ALWAYS hit the network and NEVER be cached —
// the fetch handler returns early for any /api request (and any non-GET or
// cross-origin request), leaving it to the network untouched.
//
// Lifecycle is deliberately standard (no skipWaiting / clients.claim): the page
// that registers the SW is never controlled on its first load, so the app —
// and the Playwright suites, which register nothing (see main.tsx) — behave
// exactly as before on a first visit. Offline support kicks in next visit.

const SHELL = 'chefclaw-shell-v1';
const ASSETS = 'chefclaw-assets-v1';
const KEEP = new Set([SHELL, ASSETS]);

// The app shell + icons — enough to open the SPA offline. Hashed JS/CSS are
// added to ASSETS lazily as they're first fetched (their names change per build,
// so there's nothing static to precache).
const SHELL_URLS = [
  '/',
  '/manifest.json',
  '/favicon.svg',
  '/pwa-icon-192.png',
  '/pwa-icon-512.png',
  '/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL).then((cache) => cache.addAll(SHELL_URLS)));
});

self.addEventListener('activate', (event) => {
  // Drop caches left by an older SW version.
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((key) => !KEEP.has(key)).map((key) => caches.delete(key)),
        ),
      ),
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Only same-origin GETs are ever cache-eligible. POST/PUT/etc., cross-origin,
  // and — CRUCIALLY — every /api/* request fall straight through to the network.
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) return;

  // App-shell navigations: network-first so an online user always gets the
  // freshest SPA; fall back to the cached shell when offline so it still opens.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          void caches.open(SHELL).then((cache) => cache.put('/', copy));
          return response;
        })
        .catch(() => caches.match('/', { ignoreSearch: true })),
    );
    return;
  }

  // Static assets (Vite content-hashed bundles, fonts, icons): cache-first, then
  // populate the runtime cache. Content-hashed names make cache-first safe — a
  // changed file is a new URL, so stale bytes can't be served.
  event.respondWith(
    caches.match(request).then(
      (hit) =>
        hit ??
        fetch(request).then((response) => {
          if (response.ok && response.type === 'basic') {
            const copy = response.clone();
            void caches.open(ASSETS).then((cache) => cache.put(request, copy));
          }
          return response;
        }),
    ),
  );
});
