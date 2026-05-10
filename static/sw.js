const CACHE_VERSION = 'mas-ops-v2';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const SCOPE_PREFIX = '';

const STATIC_ASSETS = [
  `${SCOPE_PREFIX}/static/css/app.css`,
  `${SCOPE_PREFIX}/static/img/icon-192.png`,
  `${SCOPE_PREFIX}/static/img/icon-512.png`,
  `${SCOPE_PREFIX}/static/img/mas_logo.png`,
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys
          .filter((k) => !k.startsWith(CACHE_VERSION))
          .map((k) => caches.delete(k))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith(SCOPE_PREFIX)) return;

  const isStatic = url.pathname.startsWith(`${SCOPE_PREFIX}/static/`);

  if (isStatic) {
    event.respondWith(
      caches.match(req).then((cached) => {
        return cached || fetch(req).then((res) => {
          if (res.status === 200) {
            const copy = res.clone();
            caches.open(STATIC_CACHE).then((c) => c.put(req, copy));
          }
          return res;
        });
      })
    );
  } else {
    event.respondWith(
      fetch(req).catch(() => {
        return new Response(
          '<!doctype html><meta charset=utf-8><title>Offline</title>' +
          '<body style="font-family:sans-serif;background:#0e1014;color:#e8eaef;' +
          'display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;padding:1rem">' +
          '<div><h2>You\'re offline</h2>' +
          '<p style="color:#9ca0aa">MAS Ops needs an internet connection. Check your network and try again.</p>' +
          '<button onclick="location.reload()" style="background:#5b9bf2;color:#fff;border:0;padding:8px 18px;border-radius:8px;font-size:14px">Retry</button>' +
          '</div></body>',
          { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
        );
      })
    );
  }
});
