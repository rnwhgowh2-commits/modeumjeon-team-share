/**
 * Service Worker — 모음전 PWA
 *
 * 캐시 전략:
 *  - 정적 자원 (CSS/JS/icons): Cache First (1주 캐시)
 *  - HTML / API: Network First (오프라인 시 캐시 폴백)
 *  - manifest / sw.js 자체: Network Only (캐시 X)
 */
const CACHE_VERSION = 'modeumjeon-v1-2026-05-17';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;

// 핵심 정적 자원 (앱 셸)
const STATIC_ASSETS = [
  '/static/toss.css',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
];

// ─── 설치 ───
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => {
      console.log('[SW] 캐시 등록:', STATIC_ASSETS.length, '개');
      return cache.addAll(STATIC_ASSETS.map((url) => new Request(url, { cache: 'reload' })));
    }).then(() => self.skipWaiting())
  );
});

// ─── 활성화 + 옛 캐시 정리 ───
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => !k.startsWith(CACHE_VERSION))
          .map((k) => {
            console.log('[SW] 옛 캐시 삭제:', k);
            return caches.delete(k);
          })
      )
    ).then(() => self.clients.claim())
  );
});

// ─── 요청 가로채기 ───
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // POST / PUT / DELETE 는 항상 네트워크
  if (request.method !== 'GET') return;

  // sw.js / manifest 는 네트워크 only (업데이트 보장)
  if (url.pathname === '/static/sw.js' || url.pathname === '/static/manifest.json') {
    return;
  }

  // 정적 자원 → Cache First
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // API 호출 → Network First (오프라인 시 캐시)
  if (url.pathname.startsWith('/mobile/api/') || url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(request));
    return;
  }

  // 모바일 HTML 페이지 → Network First
  if (url.pathname.startsWith('/mobile')) {
    event.respondWith(networkFirst(request));
    return;
  }

  // 그 외 (데스크탑 페이지 등) — Service Worker 가로채지 X
});

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const fresh = await fetch(request);
    const cache = await caches.open(STATIC_CACHE);
    cache.put(request, fresh.clone());
    return fresh;
  } catch (e) {
    return new Response('Offline', { status: 503 });
  }
}

async function networkFirst(request) {
  try {
    const fresh = await fetch(request);
    const cache = await caches.open(RUNTIME_CACHE);
    cache.put(request, fresh.clone());
    return fresh;
  } catch (e) {
    const cached = await caches.match(request);
    if (cached) return cached;
    // 오프라인 폴백 페이지 (옵션)
    if (request.mode === 'navigate') {
      return new Response(
        '<html><head><title>오프라인</title><meta charset="utf-8"></head><body style="font-family:Pretendard,sans-serif;text-align:center;padding:60px 24px;color:#4E5968"><h1 style="color:#3182F6">📡 오프라인</h1><p>인터넷 연결을 확인하세요.</p></body></html>',
        { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
      );
    }
    throw e;
  }
}

// ─── 푸시 알림 (Day 5+ 활용) ───
self.addEventListener('push', (event) => {
  if (!event.data) return;
  const data = event.data.json();
  event.waitUntil(
    self.registration.showNotification(data.title || '모음전', {
      body: data.body,
      icon: '/static/icons/icon-192.png',
      badge: '/static/icons/icon-192.png',
      data: data.url,
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data || '/mobile'));
});
