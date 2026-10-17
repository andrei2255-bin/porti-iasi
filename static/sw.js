/* Service worker: ține aplicația disponibilă și când semnalul e slab. Datele (/api) vin mereu de la server. */
const CACHE = 'portile-v1';
const FISIERE = ['/app', '/static/icon.svg', '/static/icon-192.png', '/manifest.webmanifest'];
self.addEventListener('install', e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(FISIERE)).then(() => self.skipWaiting())));
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.pathname.startsWith('/api/')) return;
  e.respondWith(fetch(e.request).then(r => { const copie = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copie)); return r; })
    .catch(() => caches.match(e.request)));
});
