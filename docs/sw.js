const CACHE_ADI   = 'bist-agent-v1';
const CACHE_STATIK = [
  './demo.html',
  './index.html',
  './manifest.json',
  'https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;600;700;900&display=swap',
  'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js',
];

// ── Kurulum: statik dosyaları önbelleğe al ────────────────
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_ADI).then((cache) => {
      return cache.addAll(CACHE_STATIK).catch((err) => {
        console.log('[SW] Cache hatası:', err);
      });
    })
  );
  self.skipWaiting();
});

// ── Aktivasyon: eski cache'leri temizle ───────────────────
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_ADI).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ── Fetch: önce cache, sonra network ─────────────────────
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // API isteklerini cache'leme — her zaman canlı ver
  if (url.hostname.includes('railway.app') ||
      url.hostname.includes('yahoo') ||
      url.pathname.includes('/api/')) {
    e.respondWith(
      fetch(e.request).catch(() => {
        return new Response(
          JSON.stringify({ hata: 'İnternet bağlantısı yok', offline: true }),
          { headers: { 'Content-Type': 'application/json' } }
        );
      })
    );
    return;
  }

  // Statik dosyalar: cache first
  e.respondWith(
    caches.match(e.request).then((cached) => {
      if (cached) return cached;
      return fetch(e.request).then((response) => {
        // Başarılı yanıtı cache'e ekle
        if (response && response.status === 200 && response.type === 'basic') {
          const klon = response.clone();
          caches.open(CACHE_ADI).then((cache) => cache.put(e.request, klon));
        }
        return response;
      }).catch(() => {
        // Offline fallback
        if (e.request.destination === 'document') {
          return caches.match('./demo.html');
        }
      });
    })
  );
});

// ── Push Notification ─────────────────────────────────────
self.addEventListener('push', (e) => {
  const data = e.data ? e.data.json() : {};
  const baslik = data.baslik || '🔔 BIST Agent Alarmı';
  const secenekler = {
    body:    data.mesaj || 'Yeni bir alarm tetiklendi',
    icon:    './manifest.json',
    badge:   './manifest.json',
    tag:     data.ticker || 'bist-alarm',
    renotify: true,
    vibrate: [200, 100, 200],
    data:    { url: data.url || './demo.html', ticker: data.ticker },
    actions: [
      { action: 'karar', title: '🎯 Karar Al' },
      { action: 'kapat', title: 'Kapat' },
    ],
  };
  e.waitUntil(self.registration.showNotification(baslik, secenekler));
});

// ── Bildirime tıklama ─────────────────────────────────────
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  if (e.action === 'kapat') return;

  const hedefUrl = e.notification.data?.url || './demo.html';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      // Açık pencere varsa fokusla
      for (const client of list) {
        if (client.url.includes('demo.html') && 'focus' in client) {
          return client.focus();
        }
      }
      // Yoksa yeni pencere aç
      return clients.openWindow(hedefUrl);
    })
  );
});

// ── Background sync (offline alarm kuyruğu) ──────────────
self.addEventListener('sync', (e) => {
  if (e.tag === 'alarm-sync') {
    e.waitUntil(
      fetch('./api/alarmlar/kontrol').catch(() => {})
    );
  }
});
