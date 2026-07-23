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

  /* 판매처가 '다 갔다'고 알려준 상태 — 라이브 저장분 실측(2026-07-23) 4가지.
     ★'수취확인후주문취소' 처럼 취소가 붙은 값은 제외한다(‘수취’ 만 보면 취소건이 섞인다). */
  var DONE_STATES = ['배송완료', '구매확정', '수취완료', '구매결정'];

  function isDelivered(r) {
    var s = String((r && (r['샵마인_주문상태'] || r['샵마인_샵마인주문상태'])) || '');
    if (!s || s.indexOf('취소') >= 0 || s.indexOf('반품') >= 0 || s.indexOf('교환') >= 0) return false;
    for (var i = 0; i < DONE_STATES.length; i++) {
      if (s.indexOf(DONE_STATES[i]) >= 0) return true;
    }
    return false;
  }

  /* 카드 안 세 칸 수치. 칸끼리 겹치지 않는다 — 배송완료면 송장이 있어도 그쪽으로 간다.
     세 칸 합 = 카드 숫자(사장님 확정 V1). */
  function splitSentInvoice(cardType) {
    if (typeof _getRowsByCardFilter !== 'function') return null;
    var rows = _getRowsByCardFilter(cardType || 'kkadaegi_sent');
    var done = 0, sent = 0, none = 0;
    rows.forEach(function (r) {
      if (isDelivered(r)) done++;
      else if (hasInvoice(r)) sent++;
      else none++;
    });
    return { done: done, sent: sent, none: none, total: rows.length };
  }

  /* 칸(pill) 스타일 — 원본 `_renderRtnExBar` 안의 pillStyle 과 **같은 문자열**.
     그 함수 안의 지역 함수라 밖에서 못 부른다. 값이 갈리면 카드마다 칸 모양이 달라지므로,
     원본이 바뀌면 여기도 같이 바꾼다(시안도 이 문자열을 원본에서 잘라 검증했다). */
  function pillStyle(color, bgIdle, borderIdle) {
    return 'display:flex;flex-direction:column;align-items:center;padding:12px 8px;'
         + 'border:2px solid ' + borderIdle + ';background:' + bgIdle + ';color:' + color + ';'
         + 'border-radius:10px;cursor:pointer;transition:all 0.15s;user-select:none;text-align:center';
  }

  /* V1 순서 = 가장 진행된 것부터 (사장님 확정) */
  function cells(split) {
    return [
      { key: 'done', label: '구매확정/배송완료', n: split.done,
        fg: '#1D4ED8', bg: '#eff6ff', bd: '#bfdbfe' },
      { key: 'sent', label: '송장 입력 완료', n: split.sent,
        fg: '#16A34A', bg: '#f0fdf4', bd: '#bbf7d0' },
      { key: 'none', label: '송장 미입력', n: split.none,
        fg: '#DC2626', bg: '#fff5f5', bd: '#fecaca' },
    ];
  }

  function sentBar(split) {
    if (!split || !split.total) return '';
    var h = '<div style="margin-top:10px;padding-top:10px;border-top:1px dashed #e5e7eb">'
          + '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px">';
    cells(split).forEach(function (c) {
      h += '<div onclick="event.stopPropagation();_showKkadaegiSentRows(\'' + c.key + '\')" '
        +  'style="' + pillStyle(c.fg, c.bg, c.bd) + '" title="클릭 → ' + c.label + ' 행만 보기">'
        +  '<div style="font-size:20px;font-weight:800;line-height:1;font-variant-numeric:tabular-nums">'
        +  fmt(c.n) + '</div>'
        +  '<div style="font-size:10.5px;font-weight:600;margin-top:4px;word-break:keep-all">'
        +  c.label + '</div></div>';
    });
    return h + '</div></div>';
  }

  /* 칸 클릭 → 그 칸의 주문만. 원본 _showCardAllRows 는 반품/교환 2분류 전용이라 따로 둔다. */
  function showRows(which) {
    if (typeof _getRowsByCardFilter !== 'function') return;
    var rows = _getRowsByCardFilter('kkadaegi_sent').filter(function (r) {
      if (which === 'done') return isDelivered(r);
      if (which === 'sent') return !isDelivered(r) && hasInvoice(r);
      return !isDelivered(r) && !hasInvoice(r);
    });
    if (typeof _renderDetailRows === 'function') { _renderDetailRows(rows); return; }
    if (typeof filterByCard === 'function') filterByCard('kkadaegi_sent');
  }

  /* 카드 한 장 HTML — 원본 _summaryCardHTML 결과에 세 칸 막대만 끼운다(카드 모양 무변경). */
  function cardHTML(count) {
    var html = _summaryCardHTML('kkadaegi_sent', count, '까대기 송장번호 전송 완료', 'teal');
    var bar = sentBar(splitSentInvoice('kkadaegi_sent'));
    var anchor = '<button onclick="event.stopPropagation();showCardBreakdown';
    return bar ? html.replace(anchor, bar + anchor) : html;
  }

  window._hasKkadaegiInvoice = hasInvoice;
  window._isKkadaegiDelivered = isDelivered;
  window._splitSentInvoice = splitSentInvoice;
  window._showKkadaegiSentRows = showRows;
  window._kkadaegiSentCardHTML = cardHTML;
})();
