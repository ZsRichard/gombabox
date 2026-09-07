const CACHE_NAME = 'gombabox-shell-v4';
const APP_SHELL = [
  '/',
  '/manifest.webmanifest',
  '/static/css/styles.css?v=4',
  '/static/js/dashboard.js?v=4',
  '/static/icons/icon.svg',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/icon-maskable-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') {
    return;
  }

  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) {
    return;
  }

  // Network-first for API and captures (prefer live), with offline fallback
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/captures/')) {
    event.respondWith(
      fetch(event.request).catch(() => {
        if (url.pathname.startsWith('/api/')) {
          return new Response(JSON.stringify({ error: 'offline' }), {
            headers: { 'Content-Type': 'application/json' },
            status: 503,
            statusText: 'Offline'
          });
        }

        return caches.match('/static/icons/icon.svg').then((cachedIcon) => cachedIcon || fetch('/static/icons/icon.svg'));
      })
    );
    return;
  }

  // For the main HTML and the dashboard JS prefer network-first so users get the latest UI
  const networkFirstPaths = ['/', '/index.html', '/static/js/dashboard.js'];
  if (networkFirstPaths.includes(url.pathname)) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const cloned = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, cloned));
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Default: cache-first for other static assets
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) {
        return cached;
      }

      return fetch(event.request).then((response) => {
        const cloned = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, cloned));
        return response;
      });
    })
  );
});
