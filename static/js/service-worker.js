/*
 * ShowWise service worker (served at /sw.js so it covers the whole site).
 *
 * Why it exists: venues have bad wifi. With this, the pages people use at an event still
 * open with no connection, showing the copy saved the last time they loaded.
 *
 *   - Pages:   network first. A page that loads is saved (only the event-day pages in KEEP);
 *              with no connection the saved copy is shown, else a small "no connection" page.
 *   - Static:  CSS, scripts, icons and the scanner libraries are kept and refreshed in the background.
 *   - Data:    API calls and anything that isn't a GET are never touched. Scans made offline
 *              are queued by the page itself (localStorage) and sent when the connection returns.
 *   - Privacy: saved pages are wiped when someone logs out, so the next person on a shared
 *              phone can't open them.
 *
 * Bump VERSION to throw away everything that was saved.
 */
const VERSION = 'v1';
const STATIC = `showwise-static-${VERSION}`;
const PAGES = `showwise-pages-${VERSION}`;
const OFFLINE_URL = '/offline';

// Pages worth having with no connection
const KEEP = [/^\/dashboard$/, /^\/equipment\/checkout$/, /^\/picklist$/, /^\/equipment$/, /^\/events\/\d+$/];
const STATIC_HOSTS = ['cdnjs.cloudflare.com', 'cdn.jsdelivr.net'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(PAGES).then((c) => c.add(OFFLINE_URL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((n) => n.startsWith('showwise-') && n !== STATIC && n !== PAGES).map((n) => caches.delete(n)));
    await self.clients.claim();
  })());
});

async function forgetPages() {
  await caches.delete(PAGES);
  const c = await caches.open(PAGES);
  try { await c.add(OFFLINE_URL); } catch (e) { /* offline: it comes back on the next install */ }
}

const isHtml = (res) => (res.headers.get('content-type') || '').includes('text/html');

async function savePage(request, response) {
  const url = new URL(request.url);
  // Not saved: errors, anything that bounced to the login page, pages not on the list
  if (!response.ok || response.redirected || !isHtml(response) || !KEEP.some((re) => re.test(url.pathname))) return;
  const cache = await caches.open(PAGES);
  await cache.put(url.pathname + url.search, response.clone());
}

async function page(request) {
  try {
    const response = await fetch(request);
    savePage(request, response).catch(() => {});
    return response;
  } catch (err) {
    const url = new URL(request.url);
    const cache = await caches.open(PAGES);
    return (await cache.match(url.pathname + url.search))
        || (await cache.match(url.pathname, { ignoreSearch: true }))
        || (await cache.match(OFFLINE_URL))
        || new Response('No connection', { status: 503, headers: { 'Content-Type': 'text/plain' } });
  }
}

async function staticFile(request) {
  const cache = await caches.open(STATIC);
  const hit = await cache.match(request);
  const refresh = fetch(request).then((res) => {
    if (res.ok || res.type === 'opaque') cache.put(request, res.clone()).catch(() => {});
    return res;
  });
  if (hit) { refresh.catch(() => {}); return hit; }
  return refresh;
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  const sameOrigin = url.origin === self.location.origin;

  if (request.mode === 'navigate' && sameOrigin) {
    if (/^\/(logout|__dev\/logout)\b/.test(url.pathname)) { event.waitUntil(forgetPages()); return; }
    if (/^\/(login|signup|password|sw\.js)/.test(url.pathname)) return;
    event.respondWith(page(request));
    return;
  }
  if ((sameOrigin && url.pathname.startsWith('/static/')) || STATIC_HOSTS.includes(url.hostname)) {
    event.respondWith(staticFile(request));
  }
});

// The page can ask for the event-day pages and scanner files to be saved ahead of time,
// so they open offline even if nobody visited them on this phone yet.
self.addEventListener('message', (event) => {
  const msg = event.data || {};
  if (msg.type === 'forget') event.waitUntil(forgetPages());
  if (msg.type === 'warm') {
    event.waitUntil((async () => {
      for (const path of msg.pages || []) {
        try {
          const res = await fetch(path, { credentials: 'same-origin' });
          await savePage(new Request(new URL(path, self.location.origin)), res);
        } catch (e) { /* offline or signed out: nothing to save */ }
      }
      const cache = await caches.open(STATIC);
      for (const src of msg.files || []) {
        try {
          const external = new URL(src, self.location.origin).origin !== self.location.origin;
          const req = new Request(src, external ? { mode: 'no-cors' } : {});
          if (!(await cache.match(req))) await cache.put(req, await fetch(req));
        } catch (e) { /* try again next time */ }
      }
    })());
  }
});
