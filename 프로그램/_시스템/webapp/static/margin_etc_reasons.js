/* margin_etc_reasons.js — 「기타」 카드에 '왜 기타인지' 보여주기
   ─────────────────────────────────────────────────────────────
   기타는 "어느 카드 조건에도 안 걸린 나머지"다. 숫자만 보여주면 왜 그런지 알 수 없어
   매번 사람이 파봐야 한다(2026-07-24: 55건 전부 롯데온 '출고지시' 였는데, 분류표에
   그 상태가 없어서 떨어진 것이었다 — 데이터가 아니라 규칙 문제였다).

   그래서 (판매처 · 판매처 주문상태) 로 묶어 많은 순서로 보여준다. 다음에 모르는 상태가
   생기면 카드만 봐도 바로 드러난다.

   별도 파일인 이유: margin_embed.html 은 원본에서 씨앗(seam)만 바꿔 생성하는 파일이라
   본문에 로직을 넣지 않는다(margin_kkadaegi_sent.js 와 같은 패턴). */
(function () {
  'use strict';

  var TOP = 3;   /* 너무 많으면 카드가 길어진다 — 상위 3개 + 나머지 묶음 */

  function reasonOf(r) {
    var mk = String((r && r['마켓']) || '').trim();
    var sm = String((r && (r['샵마인_주문상태'] || r['샵마인_샵마인주문상태'])) || '').trim();
    var mg = String((r && r['더망고주문상태 (사용자 연동)']) || '').trim();
    /* 판매처 상태가 비어 있으면 더망고 상태로 묶는다 — '빈칸'만 잔뜩 뜨는 걸 막는다. */
    var what = sm || (mg ? '더망고 ' + mg : '상태 없음');
    return (mk ? mk + ' · ' : '') + what;
  }

  function groups() {
    if (typeof _getRowsByCardFilter !== 'function') return [];
    var rows = _getRowsByCardFilter('etc') || [];
    var c = {};
    rows.forEach(function (r) { var k = reasonOf(r); c[k] = (c[k] || 0) + 1; });
    return Object.keys(c).map(function (k) { return { label: k, n: c[k] }; })
                  .sort(function (a, b) { return b.n - a.n; });
  }

  /* 카드 아래 붙일 사유 목록. 기타가 0이면 아무것도 안 붙인다. */
  function reasonsHTML() {
    var g = groups();
    if (!g.length) return '';
    var shown = g.slice(0, TOP);
    var rest = g.slice(TOP).reduce(function (a, x) { return a + x.n; }, 0);
    var h = '<div style="margin-top:8px;padding-top:8px;border-top:1px dashed #e5e7eb;'
          + 'font-size:11.5px;color:#6b7280;line-height:1.6;text-align:left">';
    shown.forEach(function (x) {
      h += '<div style="display:flex;justify-content:space-between;gap:6px">'
        +  '<span style="word-break:keep-all">' + esc(x.label) + '</span>'
        +  '<span style="font-weight:700;color:#374151;font-variant-numeric:tabular-nums">'
        +  fmt(x.n) + '</span></div>';
    });
    if (rest) {
      h += '<div style="display:flex;justify-content:space-between;gap:6px">'
        +  '<span>그 밖에</span>'
        +  '<span style="font-weight:700;color:#374151;font-variant-numeric:tabular-nums">'
        +  fmt(rest) + '</span></div>';
    }
    return h + '</div>';
  }

  /* 기타 카드 한 장 — 원본 _summaryCardHTML 결과에 사유 목록만 끼운다(카드 모양 무변경). */
  function cardHTML(count) {
    var html = _summaryCardHTML('etc', count, '기타', 'gray');
    var reasons = reasonsHTML();
    var anchor = '<button onclick="event.stopPropagation();showCardBreakdown';
    return reasons ? html.replace(anchor, reasons + anchor) : html;
  }

  window._etcReasonGroups = groups;
  window._etcCardHTML = cardHTML;
})();
