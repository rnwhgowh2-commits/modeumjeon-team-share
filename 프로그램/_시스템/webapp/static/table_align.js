/* ═══════════════════════════════════════════════════════════════════
   table_align.js — 표 머리글이 값 정렬을 따라가게 (2026-08-03)
   ───────────────────────────────────────────────────────────────────
   왜 자바스크립트가 필요한가
     “머리글은 왼쪽, 값은 오른쪽” 이 어긋나는 진짜 이유는
     **머리글 칸에 아무 표시가 없어서** 다. CSS 만으로는 어느 칸이 숫자 칸인지
     알 수 없다 — 그건 화면에 그려진 내용을 봐야 안다.
     게다가 표 상당수가 자바스크립트로 그려진다(마진계산기 aggTable 등).
     템플릿 135개를 하나씩 고치면 **반드시 빠지는 곳이 생기므로**,
     길목 한 곳에서 렌더된 표를 훑는다.

   무엇을 하나
     칸(열)마다 내용 길이를 재서
       · 가장 긴 내용이 14자 이하  → 짧은 칸  → 가운데 (table_align.css)
       · 그보다 길면              → 긴 글 칸 → 왼쪽  (`.칸-글`)
     그리고 표에 `.정렬동기화` 를 붙인다 — 이게 붙어야 CSS 가 걸린다.

   빼고 싶은 표
     <table data-align-keep> → 손대지 않는다.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var 긴글기준 = 14;          /* 글자 수 — 이보다 길면 왼쪽 */
  var 큰표기준 = 4000;        /* 칸이 이보다 많으면 건너뛴다(매트릭스처럼 큰 표) */

  function 글자수(el) {
    var t = (el.textContent || '').trim();
    /* 줄바꿈이 있으면 가장 긴 줄로 센다 */
    if (t.indexOf('\n') >= 0) {
      return t.split('\n').reduce(function (m, s) { return Math.max(m, s.trim().length); }, 0);
    }
    return t.length;
  }

  function 한표(table) {
    if (table.hasAttribute('data-align-keep')) return;

    var body = table.tBodies && table.tBodies[0];
    if (!body || !body.rows.length) return;

    /* 이미 같은 모양으로 처리했으면 다시 안 한다 (렌더 때마다 훑지 않도록) */
    var 지문 = body.rows.length + 'x' + (body.rows[0] ? body.rows[0].cells.length : 0);
    if (table.dataset.정렬지문 === 지문) return;

    var 칸수 = 0;
    for (var i = 0; i < body.rows.length; i++) 칸수 += body.rows[i].cells.length;
    if (칸수 > 큰표기준) return;

    /* ── 칸(열)마다 가장 긴 내용 재기 ── */
    var 최장 = [];
    for (var r = 0; r < body.rows.length; r++) {
      var cells = body.rows[r].cells;
      /* colspan 으로 가로지르는 줄(소계·펼침 줄)은 칸 번호가 어긋나므로 뺀다 */
      var 가로지름 = false;
      for (var c = 0; c < cells.length; c++) {
        if (cells[c].colSpan > 1) { 가로지름 = true; break; }
      }
      if (가로지름) continue;
      for (var c2 = 0; c2 < cells.length; c2++) {
        var n = 글자수(cells[c2]);
        if (최장[c2] === undefined || n > 최장[c2]) 최장[c2] = n;
      }
    }
    if (!최장.length) return;

    /* ── 요소에 직접 박아 둔 정렬 지우기 ─────────────────────────────
       🔴 [2026-08-03] 남은 어긋남 17곳의 진짜 원인이 이것이었다.
          머리글에 style="text-align:left" 처럼 **요소에 직접** 적어 둔 곳이 있는데,
          그렇게 박아 둔 값은 어떤 CSS 규칙보다도 세서 공통 규칙이 통째로 진다
          (라이브 실측: 소싱처 계정 화면의 머리글 4칸 — 값은 가운데인데 머리글만 왼쪽).
       ★ 정렬만 지운다. 칸 너비·색·여백 같은 나머지는 그대로 둔다. */
    function 박힌정렬지우기(cell) {
      if (cell && cell.style && cell.style.textAlign) cell.style.textAlign = '';
    }
    for (var rr = 0; rr < body.rows.length; rr++) {
      var cs = body.rows[rr].cells;
      for (var cc = 0; cc < cs.length; cc++) 박힌정렬지우기(cs[cc]);
    }
    if (table.tHead) {
      for (var hh = 0; hh < table.tHead.rows.length; hh++) {
        var hs = table.tHead.rows[hh].cells;
        for (var hc = 0; hc < hs.length; hc++) 박힌정렬지우기(hs[hc]);
      }
    }

    /* ── 긴 글 칸에 표시 붙이기 (머리글·값 같이) ── */
    var heads = table.tHead ? table.tHead.rows : [];
    for (var k = 0; k < 최장.length; k++) {
      var 긴글 = 최장[k] > 긴글기준;
      for (var r2 = 0; r2 < body.rows.length; r2++) {
        var cell = body.rows[r2].cells[k];
        if (cell && cell.colSpan === 1) cell.classList.toggle('칸-글', 긴글);
      }
      for (var h = 0; h < heads.length; h++) {
        var th = heads[h].cells[k];
        if (th && th.colSpan === 1) th.classList.toggle('칸-글', 긴글);
      }
    }

    /* ── 머리글의 좌우 여백을 값 칸에 맞추기 ──────────────────────────
       🔴 [2026-08-03] 라이브에서 잡힌 마지막 어긋남.
          정렬이 둘 다 같아도 **좌우 여백이 다르면** 글자 시작점이 어긋난다
          (자동화 설정 「소싱처」 칸: 머리글 8px 12px · 값 4px 8px → 5px 밀림).
       ★ 표마다 촘촘한 정도가 다르므로 **한 값으로 못 박지 않고**,
         그 표의 값 칸이 쓰는 여백을 머리글에 그대로 옮긴다. */
    if (table.tHead && body.rows[0]) {
      for (var k2 = 0; k2 < 최장.length; k2++) {
        var 본 = body.rows[0].cells[k2];
        if (!본 || 본.colSpan > 1) continue;
        /* 이름을 값칸모양 으로 — 위쪽 루프의 cs(칸 목록)와 겹치지 않게 */
        var 값칸모양 = window.getComputedStyle(본);
        for (var h2 = 0; h2 < table.tHead.rows.length; h2++) {
          var th2 = table.tHead.rows[h2].cells[k2];
          if (!th2 || th2.colSpan > 1) continue;
          th2.style.paddingLeft = 값칸모양.paddingLeft;
          th2.style.paddingRight = 값칸모양.paddingRight;
        }
      }
    }

    table.dataset.정렬지문 = 지문;
    table.classList.add('정렬동기화');
  }

  function 훑기(뿌리) {
    var tables = (뿌리 || document).querySelectorAll('table');
    for (var i = 0; i < tables.length; i++) {
      try { 한표(tables[i]); } catch (e) { /* 한 표가 실패해도 나머지는 계속 */ }
    }
  }

  /* ── 처음 한 번 ── */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { 훑기(document); });
  } else {
    훑기(document);
  }

  /* ── 나중에 그려지는 표도 (자바스크립트로 만드는 표가 많다) ──
     너무 자주 돌지 않게 묶어서 처리한다. */
  var 예약 = null;
  var 관찰 = new MutationObserver(function (기록들) {
    for (var i = 0; i < 기록들.length; i++) {
      if (기록들[i].addedNodes && 기록들[i].addedNodes.length) {
        if (예약) return;
        예약 = setTimeout(function () { 예약 = null; 훑기(document); }, 150);
        return;
      }
    }
  });
  관찰.observe(document.documentElement, { childList: true, subtree: true });

  /* 화면 쪽에서 직접 부를 수 있게 (표를 새로 그린 직후 등) */
  window.표정렬맞추기 = 훑기;
})();
