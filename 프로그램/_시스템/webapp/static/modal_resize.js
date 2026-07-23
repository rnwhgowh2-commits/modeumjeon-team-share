/* 팝업창 크기 드래그 조절 — 전역 유틸 (modal_resize.css 와 한 쌍)
 *
 * 무엇: 프로그램 안 모든 팝업(모달·팝오버·드로어)의 가장자리를 잡아끌어 크기를 바꾼다.
 * 어떻게: 팝업마다 코드를 고치지 않고, 화면에 뜬 팝업을 런타임에 찾아 손잡이를 붙인다.
 * 기억: 바꾼 크기는 브라우저에 저장돼 다음에 열 때 그대로 뜬다. 우하단 손잡이 더블클릭 = 원래 크기로.
 *
 * 제외하려면 팝업 요소에 data-noresize 를 넣으면 된다.
 * 강제로 포함하려면 data-resizable-modal 을 넣으면 된다(이름 규칙과 무관하게 잡힘).
 */
(function () {
  'use strict';
  if (window.__mrzLoaded) return;
  window.__mrzLoaded = true;

  var STORE_KEY = 'mrz.size.v1';
  var MIN_W = 280, MIN_H = 160;
  var SEL = [
    '[data-resizable-modal]', '[role="dialog"]', 'dialog',
    '[class*="modal"]', '[class*="Modal"]',
    '[class*="popup"]', '[class*="Popup"]',
    '[class*="pop"]', '[class*="drawer"]', '[class*="sheet"]', '[class*="dialog"]'
  ].join(',');
  // 이미 자체 크기조절·드래그를 가진 것들 + 팝업이 아닌 것들
  var DENY = /(toast|snack|tooltip|tip$|crawl-?log|crawllog|widget|sidebar|header|footer|dropdown|autocomplete|suggest)/i;

  /* ---------- 저장/복원 ---------- */
  function store() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY) || '{}'); } catch (e) { return {}; }
  }
  function saveSize(key, w, h) {
    if (!key) return;
    try { var s = store(); s[key] = { w: Math.round(w), h: Math.round(h) }; localStorage.setItem(STORE_KEY, JSON.stringify(s)); } catch (e) {}
  }
  function clearSize(key) {
    if (!key) return;
    try { var s = store(); delete s[key]; localStorage.setItem(STORE_KEY, JSON.stringify(s)); } catch (e) {}
  }
  function keyOf(el) {
    var cls = (el.className && typeof el.className === 'string' ? el.className : '')
      .split(/\s+/).filter(function (c) { return c && c.indexOf('mrz') !== 0; }).sort().join('.');
    var k = (el.id ? '#' + el.id : '') + (cls ? '.' + cls : '');
    return k || null;
  }

  /* ---------- 후보 판별 ---------- */
  function visibleBox(el) {
    var cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || el.hidden) return false;
    var r = el.getBoundingClientRect();
    if (r.width < MIN_W || r.height < MIN_H) return false;
    // 화면을 거의 다 덮으면 딤(배경 가림막)이므로 제외 — 크기 조절 대상은 그 안의 패널
    if (r.width >= innerWidth * 0.99 && r.height >= innerHeight * 0.99) return false;
    return true;
  }
  function isCandidate(el) {
    if (!el || el.nodeType !== 1 || el.__mrz) return false;
    if (el.hasAttribute('data-noresize') || el.closest('[data-noresize]')) return false;
    if (el.hasAttribute('data-resizable-modal')) return visibleBox(el);
    var name = (el.id || '') + ' ' + (typeof el.className === 'string' ? el.className : '');
    if (DENY.test(name)) return false;
    var cs = getComputedStyle(el);
    if (cs.position !== 'fixed' && cs.position !== 'absolute') return false;
    return visibleBox(el);
  }

  /* ---------- 고정(pin) — 가운데정렬(transform)을 실제 좌표로 확정 ---------- */
  function pin(el) {
    if (el.__mrzPinned) return;
    var r = el.getBoundingClientRect();
    el.style.position = 'fixed';
    el.style.margin = '0';
    el.style.transform = 'none';
    el.style.left = r.left + 'px';
    el.style.top = r.top + 'px';
    el.style.right = 'auto';
    el.style.bottom = 'auto';
    el.style.width = r.width + 'px';
    el.style.height = r.height + 'px';
    el.style.maxWidth = 'none';
    el.style.maxHeight = 'none';
    el.__mrzPinned = true;
  }

  /* ---------- 손잡이 붙이기 ---------- */
  var DIRS = ['e', 'w', 's', 'se', 'sw'];
  function attach(el) {
    el.__mrz = true;
    var cs = getComputedStyle(el);
    if (cs.position === 'static') el.style.position = 'relative';

    DIRS.forEach(function (d) {
      var h = document.createElement('div');
      h.className = 'mrz-h mrz-h-' + d;
      h.setAttribute('data-mrz-dir', d);
      h.title = '드래그해서 팝업 크기 조절';
      h.addEventListener('pointerdown', function (e) { startDrag(e, el, d, h); });
      if (d === 'se') {
        h.addEventListener('dblclick', function (e) {
          e.preventDefault(); e.stopPropagation();
          reset(el);
        });
      }
      el.appendChild(h);
    });
    fixScrollbarGap(el);
    restore(el);
  }

  // 팝업 자체가 세로 스크롤될 때 오른쪽 손잡이가 스크롤바를 덮지 않도록 밀어준다
  function fixScrollbarGap(el) {
    var gap = el.offsetWidth - el.clientWidth;
    var e = el.querySelector(':scope > .mrz-h-e');
    if (e) e.style.right = (gap > 0 ? gap : 0) + 'px';
  }

  function restore(el) {
    var s = store()[keyOf(el)];
    if (!s) return;
    el.style.width = Math.min(s.w, innerWidth) + 'px';
    el.style.height = Math.min(s.h, innerHeight) + 'px';
    el.style.maxWidth = 'none';
    el.style.maxHeight = 'none';
    el.__mrzRestored = true;
  }

  function reset(el) {
    clearSize(keyOf(el));
    ['position', 'margin', 'transform', 'left', 'top', 'right', 'bottom', 'width', 'height', 'maxWidth', 'maxHeight']
      .forEach(function (p) { el.style[p] = ''; });
    el.__mrzPinned = false;
    el.__mrzRestored = false;
    fixScrollbarGap(el);
  }

  /* ---------- 드래그 ---------- */
  function startDrag(e, el, dir, handle) {
    if (e.button !== 0) return;
    e.preventDefault(); e.stopPropagation();
    pin(el);
    var r = el.getBoundingClientRect();
    var x0 = e.clientX, y0 = e.clientY;
    var w0 = r.width, h0 = r.height, l0 = r.left, t0 = r.top;
    document.body.classList.add('mrz-dragging');
    try { handle.setPointerCapture(e.pointerId); } catch (err) {}

    function move(ev) {
      var dx = ev.clientX - x0, dy = ev.clientY - y0;
      var w = w0, h = h0, l = l0;
      if (dir.indexOf('e') >= 0) w = w0 + dx;
      if (dir.indexOf('w') >= 0) { w = w0 - dx; l = l0 + dx; }
      if (dir.indexOf('s') >= 0) h = h0 + dy;
      // 최소치 + 화면 밖 방지
      if (w < MIN_W) { if (dir.indexOf('w') >= 0) l = l0 + (w0 - MIN_W); w = MIN_W; }
      if (h < MIN_H) h = MIN_H;
      if (l < 0) { w += l; l = 0; }
      if (l + w > innerWidth) w = innerWidth - l;
      if (t0 + h > innerHeight) h = innerHeight - t0;
      el.style.width = w + 'px';
      el.style.height = h + 'px';
      el.style.left = l + 'px';
    }
    function up() {
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', up);
      handle.removeEventListener('pointercancel', up);
      document.body.classList.remove('mrz-dragging');
      var rr = el.getBoundingClientRect();
      saveSize(keyOf(el), rr.width, rr.height);
      fixScrollbarGap(el);
    }
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up);
    handle.addEventListener('pointercancel', up);
  }

  /* ---------- 스캔 ---------- */
  var timer = null;
  function scan() {
    var list;
    try { list = document.querySelectorAll(SEL); } catch (e) { return; }
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      if (el.__mrz) { if (!el.__mrzRestored && visibleBox(el)) restore(el); continue; }
      if (isCandidate(el)) attach(el);
    }
  }
  function schedule() {
    if (timer) return;
    timer = setTimeout(function () { timer = null; scan(); }, 120);
  }

  function boot() {
    scan();
    new MutationObserver(schedule).observe(document.body, {
      childList: true, subtree: true,
      attributes: true, attributeFilter: ['hidden', 'class', 'style', 'open']
    });
    document.addEventListener('click', schedule, true);
    window.addEventListener('resize', schedule);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  window.MoumModalResize = { scan: scan, reset: reset };
})();
