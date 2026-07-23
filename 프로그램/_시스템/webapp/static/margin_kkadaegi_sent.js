/* margin_kkadaegi_sent.js — 「까대기 송장번호 전송 완료」 카드
   ─────────────────────────────────────────────────────────────
   사장님 정의(2026-07-23):
     · 대상 = 더망고 주문상태 「현지배송완료」  (까대기 주문 후 송장을 뽑아 마켓까지 전송한 건)
       ※ 「해외현지배송중」(주문만 넣은 상태)은 기존 「까대기」 카드 그대로 — 섞지 않는다.
     · 카드 안 양분 = 국내송장번호가 있으면 「송장 입력 완료」, 없으면 「송장 미입력」
     · 색·좌우 = 입력 완료 초록(왼쪽) · 미입력 빨강(오른쪽)

   이 파일에 두는 이유: margin_embed.html 은 원본에서 씨앗(seam)만 바꿔 생성하는 파일이라
   (tools/build_margin_embed.py + 동치 가드 테스트) 본문에 로직을 넣지 않는다.
   margin_ext_check.js · margin_refresh_orders.js 와 같은 패턴. */
(function () {
  'use strict';

  /* 국내송장번호가 '있다'고 볼 수 있는 값만 참 — 공백·nan·0 은 없는 것으로 본다.
     (더망고 엑셀은 빈 칸을 여러 모습으로 준다. 하나라도 놓치면 미입력이 입력으로 둔갑한다.) */
  function hasInvoice(r) {
    var v = String((r && r['국내송장번호']) || '').trim();
    return !!v && ['nan', 'none', '0', '0.0', 'null'].indexOf(v.toLowerCase()) < 0;
  }

  /* 카드 안 두 칸 수치. _splitRtnEx 와 같은 모양({rtn, ex, total})으로 돌려준다 —
     원본 막대 함수가 그 모양을 받기 때문. ex=입력 완료(초록), rtn=미입력(빨강). */
  function splitSentInvoice(cardType) {
    if (typeof _getRowsByCardFilter !== 'function') return null;
    var rows = _getRowsByCardFilter(cardType || 'kkadaegi_sent');
    var sent = 0, none = 0;
    rows.forEach(function (r) { if (hasInvoice(r)) sent++; else none++; });
    return { rtn: none, ex: sent, total: rows.length };
  }

  /* 원본 반품/교환 막대를 그대로 쓰되 라벨·좌우만 바꾼다.
     ★'교환 (정산O)' 를 먼저 통째로 바꿔야 '(정산O)' 꼬리표가 안 남는다.
       단어만 바꾸면 '송장 입력 완료 (정산O)' 가 되어 뜻이 틀린다(시안에서 실행으로 확인).
     ★원본은 빨강이 왼쪽이라 두 칸의 순서를 맞바꾼다. 구조가 예상과 다르면 손대지 않는다. */
  function sentBar(split) {
    if (!split || !split.total) return '';
    var html = _renderRtnExBar(split, 'kkadaegi_sent')
      .replace('교환 (정산O)', '송장 입력 완료')
      .replace('클릭 → 교환 행만 보기 (정산 받는 건)', '클릭 → 송장 입력 완료 행만 보기')
      .replace('클릭 → 반품/취소 행만 보기', '클릭 → 송장 미입력 행만 보기')
      .replace(/반품\/취소/g, '송장 미입력');
    var PILL = /<div onclick="event\.stopPropagation\(\);_showCardAllRows[\s\S]*?<\/div>[\s\S]*?<\/div>[\s\S]*?<\/div>/g;
    var pills = html.match(PILL);
    if (!pills || pills.length !== 2) return html;
    var i = 0;
    return html.replace(PILL, function () { return pills[1 - (i++)]; });
  }

  /* 카드 한 장 HTML — 원본 _summaryCardHTML 결과에 두 칸 막대만 끼운다(카드 모양 무변경). */
  function cardHTML(count) {
    var html = _summaryCardHTML('kkadaegi_sent', count, '까대기 송장번호 전송 완료', 'teal');
    var bar = sentBar(splitSentInvoice('kkadaegi_sent'));
    var anchor = '<button onclick="event.stopPropagation();showCardBreakdown';
    return bar ? html.replace(anchor, bar + anchor) : html;
  }

  window._hasKkadaegiInvoice = hasInvoice;
  window._splitSentInvoice = splitSentInvoice;
  window._kkadaegiSentCardHTML = cardHTML;
})();
