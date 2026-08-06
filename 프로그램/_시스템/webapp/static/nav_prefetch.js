/* ════════════════════════════════════════════════════════════════════
 * nav_prefetch.js — 탭·메뉴를 누르기 "전에" 다음 화면을 미리 받아 둔다.
 *
 * 왜 만들었나 (2026-08-06 라이브 실측):
 *   화면을 하나 여는 데 서버가 답하는 시간(TTFB) 만 400ms 였다. 사용자가 탭을 누르면
 *   그 400ms 동안은 아무 일도 안 일어난 것처럼 보인다 — "클릭하면 느려"의 정체다.
 *
 * 무엇을 하나:
 *   메뉴·탭 링크에 **마우스를 올리는 순간**(누르기 전) 그 주소의 HTML 을 미리 받아 둔다.
 *   사람이 링크를 보고 누르기까지는 보통 200~300ms 가 걸리므로, 실제로 누를 때쯤엔
 *   화면이 이미 도착해 있다 → 누르자마자 뜬다.
 *
 * 안 건드리는 것 (부작용 방지):
 *   · 바깥 사이트 주소, 다운로드, 새 창(target), #앵커, mailto/tel
 *   · 값을 바꾸는 주소(POST 를 부르는 버튼은 <a> 가 아니므로 애초에 해당 없음)
 *   · data-no-prefetch 가 붙은 링크 — 눌러야만 동작해야 하는 링크의 탈출구
 *   · 데이터 절약 모드(saveData)·느린 회선(2g) — 남의 데이터를 함부로 쓰지 않는다
 *
 * 미리 받기는 GET 이고 화면을 바꾸지 않는다. 같은 주소는 한 번만 받는다.
 * ════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var conn = navigator.connection || {};
  if (conn.saveData) return;                                   // 데이터 절약 모드 존중
  if (/(^|-)2g$/.test(conn.effectiveType || '')) return;       // 느린 회선에선 안 함

  var done = new Set();       // 이미 미리 받은 주소
  var timer = null;
  var ready = false;          // 지금 화면이 다 뜬 뒤에만 시작한다

  // 🔴 이 두 숫자는 "서버 부담"을 정하는 값이다 — 미리받기는 서버에 진짜 요청을 보낸다.
  //   워커가 2개뿐이라, 마우스가 메뉴 위를 쓸고 지나갈 때마다 화면을 통째로 그리면
  //   빠르게 하려다 도리어 느려진다. 그래서 "일부러 머문 링크"만, 화면당 몇 개만 받는다.
  var HOVER_DELAY = 140;      // 스쳐 지나가는 마우스는 무시 (프로젝트 호버 관례와 같은 값)
  var MAX = 4;                // 한 화면에서 미리 받을 상한

  function 미리받아도_되는_링크인가(a) {
    if (!a || a.tagName !== 'A') return false;
    if (a.target && a.target !== '_self') return false;
    if (a.hasAttribute('download')) return false;
    if (a.dataset.noPrefetch !== undefined) return false;

    var href = a.getAttribute('href') || '';
    if (!href || href[0] === '#') return false;
    if (/^(mailto|tel|javascript|blob|data):/i.test(href)) return false;

    var url;
    try { url = new URL(a.href, location.href); } catch (e) { return false; }
    if (url.origin !== location.origin) return false;          // 우리 사이트만
    if (url.pathname === location.pathname && url.search === location.search) return false;
    if (url.pathname.startsWith('/static/')) return false;     // 이미 캐시됨
    return true;
  }

  function 미리받기(url) {
    if (!ready) return;       // 지금 화면이 아직 뜨는 중이면 그쪽을 방해하지 않는다
    if (done.size >= MAX || done.has(url)) return;
    done.add(url);
    var link = document.createElement('link');
    link.rel = 'prefetch';
    link.as = 'document';
    link.href = url;
    document.head.appendChild(link);
  }

  function 후보(e) {
    var a = e.target && e.target.closest ? e.target.closest('a') : null;
    return 미리받아도_되는_링크인가(a) ? a.href : null;
  }

  if (document.readyState === 'complete') ready = true;
  else window.addEventListener('load', function () { ready = true; }, { once: true });

  document.addEventListener('mouseover', function (e) {
    var url = 후보(e);
    if (!url) return;
    clearTimeout(timer);
    timer = setTimeout(function () { 미리받기(url); }, HOVER_DELAY);
  }, { passive: true, capture: true });

  document.addEventListener('mouseout', function () { clearTimeout(timer); },
                            { passive: true, capture: true });

  // 손가락으로 쓰는 화면 — 누르기 시작하는 순간(손 떼기 전) 받기 시작한다
  document.addEventListener('touchstart', function (e) {
    var url = 후보(e);
    if (url) 미리받기(url);
  }, { passive: true, capture: true });
})();
