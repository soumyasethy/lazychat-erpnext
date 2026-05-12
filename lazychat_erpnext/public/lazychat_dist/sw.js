/* lazychat chat-ui service worker — opt-in app-shell cache.
 *
 * Activation
 * ----------
 * This SW is shipped to dist/sw.js and served alongside index.html, so its
 * natural max scope is `/assets/lazychat_erpnext/lazychat_dist/`.
 * Registration is opt-in (see src/main.tsx) — flip it on per deployment by
 * appending `&sw=on` to the iframe URL or by setting
 *   localStorage.setItem('lazychat_sw', 'on')
 * and refreshing.
 *
 * Caching strategy
 * ----------------
 *  - hashed assets under ./assets/  : cache-first, immutable (Vite's content
 *    hash is the cache key — old hashes age out via cleanup on activate).
 *  - index.html                     : stale-while-revalidate (serve cached
 *    instantly for snappy boot, refresh in background for the next visit).
 *  - everything else                : network only (don't intercept tool
 *    calls / postMessage proxies / sourcemaps).
 *
 * Versioning
 * ----------
 * Bump `CACHE_VERSION` whenever the strategy changes; the activate handler
 * deletes any cache that doesn't match the current name.
 */
const CACHE_VERSION = 'lazychat-v1';
const ASSET_CACHE = `${CACHE_VERSION}-assets`;
const HTML_CACHE = `${CACHE_VERSION}-html`;

self.addEventListener('install', (event) => {
  // Take over the next request cycle without waiting for tabs to close.
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((k) => k !== ASSET_CACHE && k !== HTML_CACHE)
          .map((k) => caches.delete(k)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  // Confine ourselves to the SPA scope — never intercept Frappe API calls or
  // anything outside the dist/ directory, even though the SW's max scope is
  // the dist root.
  const myScope = self.registration.scope;
  if (!req.url.startsWith(myScope)) return;

  // 1) Hashed assets: cache-first, fall back to network on cache miss.
  if (/\/assets\/.+-[A-Za-z0-9_-]{6,}\./.test(url.pathname)) {
    event.respondWith(cacheFirst(req, ASSET_CACHE));
    return;
  }

  // 2) Entry HTML: stale-while-revalidate.
  if (url.pathname.endsWith('/index.html') || url.pathname === myScope.replace(self.location.origin, '')) {
    event.respondWith(staleWhileRevalidate(req, HTML_CACHE));
    return;
  }

  // 3) Anything else (sourcemaps in dev, the SW itself, mascot.png, etc):
  // straight network passthrough.
});

async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req, { ignoreVary: true });
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) cache.put(req, res.clone());
  return res;
}

async function staleWhileRevalidate(req, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req, { ignoreVary: true });
  const network = fetch(req)
    .then((res) => {
      if (res.ok) cache.put(req, res.clone());
      return res;
    })
    .catch(() => hit); // offline → fall back to cache
  return hit || network;
}
