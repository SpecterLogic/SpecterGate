// Network-only PWA: never persist administrator pages, API data or subscriptions.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  if (event.request.mode === 'navigate' && new URL(event.request.url).origin === self.location.origin) {
    event.respondWith(fetch(event.request).catch(() => new Response(
      '<!doctype html><meta charset="utf-8"><title>SpecterGate</title><body style="background:#080e16;color:white;font:20px sans-serif;padding:40px"><h1>SpecterGate</h1><p>Connect to the network to open your panel.</p></body>',
      {status:503,headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'}})));
  }
});
