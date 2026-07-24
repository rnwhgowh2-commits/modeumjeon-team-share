/* margin_all_tab.js — 카드 → 「전체내역」 한 곳으로 통일 (사장님 확정 2026-07-24)
   ─────────────────────────────────────────────────────────────
   그동안 카드를 누르면 ①카드 아래 상세내역 ②전체내역 탭 두 갈래로 갈렸다.
   앞으로는 **전체내역 하나**만 쓴다. 카드(또는 카드 안 소분류 칸)를 누르면
   전체내역 탭으로 가고 **그 카드 건만** 남긴다.

   ★거르는 층 — 표를 다시 그리지 않고 **그려진 행을 숨긴다**.
     전체내역 표는 만드는 경로가 여러 갈래라(그룹별 보기·별표만 보기·검색 등)
     렌더러를 고치면 그 갈래마다 또 새는 곳이 생긴다. 행에 이미 `data-row-idx`
     가 붙어 있으므로, 남길 _idx 집합만 알면 어느 경로로 그려졌든 똑같이 걸러진다.

   ★건수는 화면에 그대로 적는다 — "몇 건이 걸러졌는지" 를 사장님이 눈으로 확인할 수 있어야
     한다(카드 숫자와 표 줄 수가 다르면 바로 드러나야 한다). */
(function () {
  'use strict';

  var CHIP_ID = 'mAllCardChip';

  function keepSet(type, sub) {
    if (typeof _getRowsByCardFilter !== 'function') return null;
    var rows = _getRowsByCardFilter(type) || [];
    if (sub && typeof window._kkadaegiSentSubFilter === 'function') {
      rows = rows.filter(function (r) { return window._kkadaegiSentSubFilter(r, sub); });
    }
    var s = {};
    rows.forEach(function (r) { if (r && r._idx != null) s[String(r._idx)] = 1; });
    return { set: s, n: rows.length };
  }

  function apply() {
    var f = window._allTabCardFilter;
    var trs = document.querySelectorAll('tr[data-row-idx]');
    if (!f) {
      trs.forEach(function (tr) { tr.style.display = ''; });
      var old = document.getElementById(CHIP_ID);
      if (old) old.remove();
      return;
    }
    var shown = 0;
    trs.forEach(function (tr) {
      var ok = !!f.set[String(tr.getAttribute('data-row-idx'))];
      tr.style.display = ok ? '' : 'none';
      if (ok) shown++;
    });
    chip(f, shown);
  }

  function chip(f, shown) {
    var host = document.querySelector('#tab-all') || document.querySelector('.tab-pane.active')
            || document.body;
    var el = document.getElementById(CHIP_ID);
    if (!el) {
      el = document.createElement('div');
      el.id = CHIP_ID;
      el.style.cssText = 'margin:10px 0;padding:8px 12px;border-radius:8px;'
        + 'background:#eff6ff;border:1px solid #bfdbfe;color:#1D4ED8;font-size:13px;'
        + 'font-weight:600;display:flex;align-items:center;gap:10px';
      host.insertBefore(el, host.firstChild);
    }
    el.innerHTML = '🔎 <b>' + esc(f.label) + '</b> 만 보는 중'
      + ' <span style="font-weight:500;color:#1e40af">카드 ' + fmt(f.n)
      + '건 · 표에 보이는 줄 ' + fmt(shown) + '건</span>'
      + (f.n !== shown
          ? '<span style="color:#DC2626;font-weight:700">⚠️ 숫자가 다릅니다</span>' : '')
      + '<button onclick="window._clearAllTabCardFilter()" style="margin-left:auto;'
      + 'padding:3px 10px;border:1px solid #93c5fd;background:#fff;color:#1D4ED8;'
      + 'border-radius:6px;cursor:pointer;font-size:12px">✕ 전체 보기</button>';
  }

  function go(type, label, sub) {
    var k = keepSet(type, sub);
    if (!k) return;
    window._allTabCardFilter = { type: type, label: label || type, sub: sub || '',
                                 set: k.set, n: k.n };
    /* 전체내역 탭으로 이동 — 탭 버튼을 실제로 눌러 원본 렌더 경로를 그대로 탄다. */
    var btn = document.querySelector('.tab-btn[data-tab="all"]');
    if (btn) btn.click();
    setTimeout(apply, 0);
    setTimeout(apply, 250);   /* 표가 늦게 그려지는 경로 대비 */
  }

  function clear() {
    window._allTabCardFilter = null;
    apply();
  }

  window._goAllWithCardFilter = go;
  window._clearAllTabCardFilter = clear;
  window._applyAllTabCardFilter = apply;
})();
