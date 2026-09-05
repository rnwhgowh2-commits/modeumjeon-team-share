/* margin_status_history.js — 전체내역 「[판매처] 주문상태」 칸에 정산여부 배지 + 이력 호버
   (모음전 신규, 2026-09-05 사장님 지시)

   왜 필요한가:
   ────────────────────────────────────────────────────────────
   클레임(취소요청·반품요청·교환요청 등)으로 들어온 주문상태가 그 뒤 실제로 어떻게
   끝났는지(철회·정산완료)를 화면이 안 보여줘서, 이미 끝난 정상거래가 "손실 진행중"
   으로 잘못 보였다. 서버(lemouton.margin.settle_status)가 매 분석마다 계산해 matched
   행에 실어 준 두 필드를 그대로 그린다 — 여기서 새로 판정하지 않는다(단일 원천):
     · r['정산여부']       — 'O'(마켓이 실제로 입금했다고 알려준 것만) /
                              '진행중'(반품·교환·취소가 마켓에서도 아직 안 끝남) /
                              '확인불가'(그 채널이 없거나 아직 안 옴 — 폴백 아님, 사실)
     · r['_주문상태이력']  — [{status, at}, ...] 시간순. 예:
                              [{"status":"취소요청","at":"2026-08-30"},
                               {"status":"배송완료","at":"2026-09-03"}]

   🔴 툴팁은 position:fixed + JS 위치계산 — 전체내역 표는 가로 스크롤(overflow) 래퍼가
     있어 position:absolute 는 표 경계에서 잘린다(margin_settle_cell.js 와 같은 이유).
   본문(margin_embed.html)은 씨앗 빌드라 직접 편집 금지 — build_margin_embed.py SEAM 이
     이 함수를 호출한다(없으면 원본 그대로 폴백 — window._ssVerdictCellHtml 미정의 시 no-op).
*/
(function (root) {
  'use strict';

  var doc = (typeof document !== 'undefined') ? document : null;
  if (doc && !doc.getElementById('ss-hist-style')) {
    var st = doc.createElement('style');
    st.id = 'ss-hist-style';
    st.textContent = [
      '.ss-verdict-badge{display:inline-block;padding:1px 6px;border-radius:3px;color:#fff;font-size:10px;font-weight:600;margin-left:3px;white-space:nowrap}',
      '.ss-hist-anchor{cursor:help;font-size:11px;color:#6b7280;margin-left:2px}',
      '.ss-hist-pop{display:none;position:fixed;z-index:99999;background:#fff;border:1px solid #d1d6db;border-radius:10px;max-height:60vh;overflow-y:auto;box-shadow:0 10px 26px rgba(0,0,0,.2);cursor:default;text-align:left;padding:8px 10px;font-size:12px;min-width:180px}',
      '.ss-hist-pop .hd{font-weight:600;margin-bottom:4px;color:#374151}'
    ].join('\n');
    doc.head.appendChild(st);
  }

  var VERDICT_STYLE = {
    'O':      { bg: '#10b981', label: '정산O' },
    '진행중': { bg: '#F59E0B', label: '진행중' },
    '확인불가': { bg: '#6b7280', label: '확인불가' }
  };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /* 표 렌더가 호출 — 배지(+이력이 2건 이상이면 호버 아이콘) HTML 조각을 돌려준다. */
  root._ssVerdictCellHtml = function (r) {
    var v = r && r['정산여부'];
    if (!v) return '';
    var st2 = VERDICT_STYLE[v] || { bg: '#6b7280', label: v };
    var hist = (r && r['_주문상태이력']) || [];
    var badge = ' <span class="ss-verdict-badge" style="background:' + st2.bg + '">' + esc(st2.label) + '</span>';
    if (hist.length <= 1) return badge;   // 이력이 한 건뿐이면 호버로 보여줄 게 없다
    var histJson = JSON.stringify(hist).replace(/"/g, '&quot;');
    return ' <span class="ss-hist-anchor" data-ss-hist=\'' + histJson + '\' '
      + 'onmouseenter="_ssHistShow(event,this)" onmouseleave="_ssHistHide()" '
      + 'title="주문상태 이력 보기">🕒</span>' + badge;  /* 🕒 */
  };

  if (!doc) return;
  var pop, hideTimer;
  function ensurePop() {
    if (pop) return pop;
    pop = doc.createElement('div');
    pop.className = 'ss-hist-pop';
    pop.addEventListener('mouseenter', function () { clearTimeout(hideTimer); });
    pop.addEventListener('mouseleave', function () { scheduleHide(); });
    doc.body.appendChild(pop);
    return pop;
  }
  function scheduleHide() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(function () { if (pop) pop.style.display = 'none'; }, 250);
  }
  root._ssHistShow = function (ev, anchor) {
    clearTimeout(hideTimer);
    var hist;
    try { hist = JSON.parse(anchor.getAttribute('data-ss-hist') || '[]'); } catch (e) { hist = []; }
    var p = ensurePop();
    p.innerHTML = '<div class="hd">주문상태 이력</div>' + hist.map(function (e, idx) {
      var arrow = idx > 0 ? '<span style="color:#9ca3af"> → </span>' : '';  /* → */
      var at = e.at ? '<span style="color:#9ca3af;font-size:11px">(' + esc(e.at) + ')</span>' : '';
      return arrow + '<span>' + esc(e.status || '') + '</span> ' + at;
    }).join('<br>');
    p.style.display = 'block';
    var r = anchor.getBoundingClientRect(), w = p.offsetWidth, h2 = p.offsetHeight;
    var left = Math.max(8, Math.min(r.right - w, root.innerWidth - w - 8));
    var top = r.bottom + 7;
    if (top + h2 > root.innerHeight - 8) top = r.top - h2 - 7;
    p.style.left = left + 'px';
    p.style.top = Math.max(8, top) + 'px';
  };
  root._ssHistHide = scheduleHide;
  root.addEventListener('scroll', function () { if (pop) pop.style.display = 'none'; }, { passive: true });
})(typeof window !== 'undefined' ? window : this);
