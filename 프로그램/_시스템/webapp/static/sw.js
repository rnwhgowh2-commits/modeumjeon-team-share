/**
 * Service Worker — 모음전 PWA
 *
 * 🔴 캐시 정책 (설계서 2026-08-03 §4.7 · 사장님 확정 A안)
 *   - 앱 껍데기(/static/*) 만 저장한다 → 앱이 빨리 뜬다.
 *   - 가격·재고·주문·정산 등 **모든 데이터는 저장하지 않는다.**
 *     인터넷이 끊기면 낡은 값을 보여주는 대신 "연결이 안 됩니다"라고 말한다.
 *
 *   왜: 폰은 지하철·엘리베이터·지하 창고에서 수시로 끊긴다. 예전 정책(Network First +
 *   캐시 폴백)은 어제 매입가·재고를 **티 없이** 화면에 띄웠다. 그 숫자로 판매가를 정하면
 *   그대로 금전 손실이다. 이 프로젝트 규칙 1번이 "가격·재고 오류 = 금전 손실".
 */
const CACHE_VERSION = 'modeumjeon-v2-2026-08-04';
const STATIC_CACHE = `${CACHE_VERSION}-static`;

// 앱 셸 — 이것만 저장한다
const STATIC_ASSETS = [
  '/static/toss.css',
  '/static/mobile_shell.css',
  '/static/mobile_shell.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
];

// ─── 설치 ───
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) =>
      // 하나가 없어도 설치가 통째로 실패하지 않게 개별 처리
      Promise.all(STATIC_ASSETS.map((url) =>
        cache.add(new Request(url, { cache: 'reload' })).catch((e) => {
          console.warn('[SW] 캐시 건너뜀:', url, e);
        })
      ))
    ).then(() => self.skipWaiting())
  );
});

// ─── 활성화 + 옛 캐시 정리 ───
// 이전 버전이 남긴 런타임 캐시(낡은 가격·재고)를 여기서 통째로 지운다.
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

const OFFLINE_HTML =
  '<html><head><title>연결 안 됨</title><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width,initial-scale=1"></head>' +
  '<body style="font-family:Pretendard,-apple-system,sans-serif;text-align:center;padding:64px 24px;color:#4E5968">' +
  '<div style="font-size:44px"></div>' +
  '<h1 style="font-size:19px;color:#191F28;margin:14px 0 8px">연결이 안 됩니다</h1>' +
  '<p style="font-size:14px;line-height:1.7;margin:0">가격·재고는 <b>낡은 값을 보여드리지 않습니다.</b><br>연결되면 바로 나옵니다.</p>' +
  '<button onclick="location.reload()" style="margin-top:22px;padding:12px 26px;border:0;border-radius:10px;background:#3182F6;color:#fff;font-size:15px;font-weight:700">다시 시도</button>' +
  '</body></html>';

// ─── 요청 가로채기 ───
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method !== 'GET') return;                       // 쓰기는 항상 네트워크
  if (url.origin !== self.location.origin) return;            // 남의 도메인은 안 건드림

  // sw.js / manifest 는 네트워크 only (업데이트 보장)
  if (url.pathname === '/static/sw.js' || url.pathname === '/static/manifest.json') return;

  // 앱 껍데기 → 저장본 우선 (여기가 유일하게 저장하는 곳)
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(shellFirst(request));
    return;
  }

  // 그 외 전부(HTML·API·데이터) → 네트워크만. 저장하지 않는다.
  event.respondWith(networkOnly(request));
});

async function shellFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const fresh = await fetch(request);
    if (fresh && fresh.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, fresh.clone());
    }
    return fresh;
  } catch (e) {
    return new Response('offline', { status: 503 });
  }
}

async function networkOnly(request) {
  try {
    return await fetch(request);
  } catch (e) {
    if (request.mode === 'navigate') {
      return new Response(OFFLINE_HTML, {
        status: 503,
        headers: { 'Content-Type': 'text/html; charset=utf-8' },
      });
    }
    return new Response(JSON.stringify({ ok: false, offline: true, error: '연결이 안 됩니다' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
    });
  }
}

// ─── 푸시 알림 (선택 단계에서 사용) ───
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
