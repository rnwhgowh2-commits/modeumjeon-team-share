/* matrix_hscroll.js — 매트릭스 가로 스크롤 떠있는 바 (2026-06-22)
 *
 * 문제: 옵션 매트릭스(#price-matrix-table)는 소싱처 컬럼이 많아 가로로 넓고,
 *       래퍼(overflow-x:auto)에 가로 스크롤바가 있으나 테이블이 길어 화면 한참 아래라
 *       사용자가 도달 못 함 → 크롤 위젯에 가린 우측 컬럼을 못 본다.
 * 해결: 화면 하단에 항상 닿는 '떠있는 가로 스크롤바'를 만들어 래퍼와 양방향 동기화.
 *       래퍼의 네이티브 가로 스크롤바가 이미 화면에 보이면(짧은 테이블) 숨긴다(중복 방지).
 *
 * 매트릭스가 없는 페이지에서는 아무것도 안 함(null-safe).
 */
(function () {
  'use strict';
  var TABLE_ID = 'price-matrix-table';
  var BAR_ID = 'mtx-hscroll-bar';
  var SP_ID = 'mtx-hscroll-sp';

  function getWrap() {
    var t = document.getElementById(TABLE_ID);
    return t ? t.parentElement : null;   // overflow-x:auto 래퍼
  }

  function ensureBar() {
    var bar = document.getElementById(BAR_ID);
    if (bar) return bar;
    bar = document.createElement('div');
    bar.id = BAR_ID;
    bar.style.cssText = [
      'position:fixed', 'bottom:0', 'left:0', 'height:16px',
      'overflow-x:scroll', 'overflow-y:hidden', 'z-index:8000',
      'background:rgba(248,250,252,.96)', 'border-top:1px solid #d1d6db',
      'box-shadow:0 -2px 10px rgba(0,0,0,.08)', 'display:none'
    ].join(';');
    var sp = document.createElement('div');
    sp.id = SP_ID;
    sp.style.cssText = 'height:1px;width:1px;';
    bar.appendChild(sp);
    document.body.appendChild(bar);
    // 바 → 래퍼 동기화
    bar.addEventListener('scroll', function () {
      var wrap = getWrap();
      if (wrap && Math.abs(wrap.scrollLeft - bar.scrollLeft) > 1) wrap.scrollLeft = bar.scrollLeft;
    });
    return bar;
  }

  function bindWrap() {
    var wrap = getWrap();
    if (!wrap || wrap.__hsBound) return;
    wrap.__hsBound = true;
    // 래퍼 → 바 동기화
    wrap.addEventListener('scroll', function () {
      var bar = document.getElementById(BAR_ID);
      if (bar && bar.style.display !== 'none' && Math.abs(bar.scrollLeft - wrap.scrollLeft) > 1) {
        bar.scrollLeft = wrap.scrollLeft;
      }
    });
  }

  function update() {
    var wrap = getWrap();
    var bar = document.getElementById(BAR_ID);
    if (!wrap) { if (bar) bar.style.display = 'none'; return; }
    bar = ensureBar();

    var overflows = wrap.scrollWidth > wrap.clientWidth + 2;
    var r = wrap.getBoundingClientRect();
    var vh = window.innerHeight, vw = window.innerWidth;
    var inView = r.top < vh - 40 && r.bottom > 100;          // 매트릭스가 화면에 보이는가
    var nativeReachable = r.bottom <= vh - 2;                 // 래퍼 하단(=네이티브 스크롤바)이 화면 안인가

    if (overflows && inView && !nativeReachable) {
      var left = Math.max(0, Math.round(r.left));
      var width = Math.min(Math.round(r.width), vw - left);
      bar.style.left = left + 'px';
      bar.style.width = width + 'px';
      document.getElementById(SP_ID).style.width = wrap.scrollWidth + 'px';
      bar.style.display = 'block';
      if (Math.abs(bar.scrollLeft - wrap.scrollLeft) > 1) bar.scrollLeft = wrap.scrollLeft;
    } else {
      bar.style.display = 'none';
    }
  }

  function tick() { bindWrap(); update(); }

  function init() {
    window.addEventListener('scroll', update, true);   // 캡처: 래퍼/페이지 스크롤 모두 포착
    window.addEventListener('resize', update);
    // 매트릭스는 비동기 렌더 + 행 펼침/접힘으로 높이·폭 변함 → 관찰 + 주기 점검
    try {
      var mo = new MutationObserver(function () { tick(); });
      mo.observe(document.body, { childList: true, subtree: true });
    } catch (_) {}
    setInterval(tick, 1000);   // 위젯 도킹으로 래퍼 폭이 바뀌는 경우 등 보정
    tick();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
