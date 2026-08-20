/* matrix_hscroll.js — 매트릭스 가로 스크롤 떠있는 바 (2026-06-22, v3 안정/성능판)
 *
 * 문제: 옵션 매트릭스(#price-matrix-table)는 소싱처 컬럼이 많아 가로로 넓고,
 *       래퍼(overflow-x:auto)의 가로 스크롤바가 테이블이 길어 화면 한참 아래라 도달 못 함
 *       → 크롤 위젯에 가린 우측 컬럼을 못 본다.
 * 해결: 화면 하단 고정 '떠있는 가로 스크롤바'를 만들어 래퍼와 동기화.
 *
 * v3 성능/안정 개선(사용자 피드백: 천천히 스크롤 시 가끔 안 됨/끊김):
 *   · 스크롤 동기화(scrollLeft)와 위치 갱신(표시/left/width/스페이서)을 분리.
 *     - 스크롤 핸들러는 scrollLeft 한 줄만(레이아웃 계산 없음) → 가볍고 즉각.
 *     - 위치 갱신은 페이지 스크롤·리사이즈·주기(1.2s)에만(가로 스크롤 중엔 안 건드림).
 *   · syncing 락으로 바↔래퍼 피드백 루프 차단.
 *   · 스페이서 폭은 바뀔 때만 다시 설정(매 프레임 재설정이 스크롤 위치를 리셋하던 문제 제거).
 *   · 가로 스크롤(래퍼/바)에는 capture 리스너 안 검 → 불필요한 재계산 제거.
 *
 * 매트릭스 없는 페이지 null-safe.
 */
(function () {
  'use strict';
  var TABLE_ID = 'price-matrix-table';
  var BAR_ID = 'mtx-hscroll-bar';
  var SP_ID = 'mtx-hscroll-sp';
  var lastSpW = -1;        // 마지막으로 설정한 스페이서 폭(바뀔 때만 갱신)

  function getWrap() {
    var t = document.getElementById(TABLE_ID);
    return t ? t.parentElement : null;   // overflow-x:auto 래퍼
  }

  // 피드백 루프는 '값이 이미 같으면 scroll 이벤트가 안 뜬다'는 성질로 자연 종료시킨다.
  //   (rAF 락 방식은 백그라운드 탭에서 rAF 가 멈춰 락이 안 풀리는 버그 → 천천히 스크롤 시 끊김)
  //   라운딩 비교로 소수점 튕김도 방지.
  function syncTo(target, value) {
    if (Math.round(target.scrollLeft) !== Math.round(value)) target.scrollLeft = value;
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
    // 바 → 래퍼 (스크롤 위치만, 레이아웃 계산 없음)
    bar.addEventListener('scroll', function () {
      var wrap = getWrap();
      if (wrap) syncTo(wrap, bar.scrollLeft);
    });
    return bar;
  }

  function bindWrap(wrap) {
    if (!wrap || wrap.__hsBound) return;
    wrap.__hsBound = true;
    // 래퍼 → 바 (스크롤 위치만)
    wrap.addEventListener('scroll', function () {
      var bar = document.getElementById(BAR_ID);
      if (!bar || bar.style.display === 'none') return;
      syncTo(bar, wrap.scrollLeft);
    });
  }

  // 표시 여부 + 위치 + 스페이서 폭만 갱신(스크롤 위치는 가능한 한 건드리지 않음)
  function reposition() {
    var wrap = getWrap();
    var bar = document.getElementById(BAR_ID);
    if (!wrap) { if (bar) bar.style.display = 'none'; return; }
    bar = ensureBar();
    bindWrap(wrap);

    var overflows = wrap.scrollWidth > wrap.clientWidth + 2;
    var r = wrap.getBoundingClientRect();
    var vh = window.innerHeight, vw = window.innerWidth;
    var inView = r.top < vh - 40 && r.bottom > 100;       // 매트릭스가 화면에 보이는가
    var nativeReachable = r.bottom <= vh - 2;             // 래퍼 네이티브 스크롤바가 화면 안인가

    if (!(overflows && inView && !nativeReachable)) {
      if (bar.style.display !== 'none') bar.style.display = 'none';
      lastSpW = -1;                                       // 다음 표시 때 스페이서 재설정 강제
      return;
    }

    var left = Math.max(0, Math.round(r.left));
    var width = Math.min(Math.round(r.width), vw - left);
    if (bar.style.left !== left + 'px') bar.style.left = left + 'px';
    if (bar.style.width !== width + 'px') bar.style.width = width + 'px';
    if (lastSpW !== wrap.scrollWidth) {                   // 폭 바뀔 때만(스크롤 리셋 방지)
      lastSpW = wrap.scrollWidth;
      document.getElementById(SP_ID).style.width = wrap.scrollWidth + 'px';
    }
    if (bar.style.display !== 'block') bar.style.display = 'block';
    syncTo(bar, wrap.scrollLeft);   // 표시/리사이즈 직후 위치 맞춤(값 같으면 no-op)
  }

  var rafLock = 0;
  function schedule() {
    if (rafLock) return;
    rafLock = requestAnimationFrame(function () { rafLock = 0; reposition(); });
  }

  function init() {
    // 페이지 세로 스크롤·리사이즈 시에만 위치 재계산(가로 스크롤 동기화는 위 핸들러가 처리)
    window.addEventListener('scroll', schedule);   // 비-capture: 페이지 스크롤만
    window.addEventListener('resize', schedule);
    setInterval(reposition, 1200);                 // 비동기 렌더·행 펼침·위젯 도킹 폭변화 보정(가벼움)
    reposition();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
