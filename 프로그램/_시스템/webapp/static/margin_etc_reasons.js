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
    /* ★끼워 넣는 기준점 — 버튼 문구·핸들러가 바뀌어도 깨지지 않게 **가장 짧은 공통부분**만
       잡는다. 2026-07-24 사고: 「세부보기」→「전체내역에서 보기」로 핸들러를 바꿨더니
       'showCardBreakdown' 까지 포함한 기준점이 안 맞아 카드 안 칸이 통째로 사라졌다
       (사장님이 화면에서 발견). 못 찾으면 카드 끝에 붙여 **절대 사라지지 않게** 한다. */
    var anchor = '<button onclick="event.stopPropagation();';
    if (!reasons) return html;
    return html.indexOf(anchor) >= 0 ? html.replace(anchor, reasons + anchor)
                                     : html.replace('</div>', reasons + '</div>');
  }

  /* ── 「정상/완료」 카드에 역마진 경고 ────────────────────────────────────
     🔴 2026-07-24: 마진율 −101% 인 주문이 「정상/완료」에 조용히 앉아 있었다.
        카드는 **주문 상태만** 보기 때문에, 배송만 끝났으면 아무리 손해여도 정상이다.
        (그 건은 판매 36,700 · 매입 70,345 로 실제 매입가가 판매가의 1.92배였다.
         분류 오류가 아니라 데이터가 그랬던 것 — 그래서 '고치는' 게 아니라 '보이게' 한다.)
     손실 판정은 margin_rules.js(MR) 단일 원천을 그대로 쓴다 — 여기서 다시 만들지 않는다. */
  function lossRows(cardType) {
    if (typeof _getRowsByCardFilter !== 'function' || typeof MR === 'undefined') return [];
    return (_getRowsByCardFilter(cardType) || []).filter(function (r) {
      return MR.rowMargin(r) < 0;
    });
  }

  function lossNoteHTML(cardType) {
    var rows = lossRows(cardType);
    if (!rows.length) return '';
    var worst = rows.reduce(function (a, b) {
      return (Number(a['마진율']) || 0) <= (Number(b['마진율']) || 0) ? a : b;
    });
    return '<div style="margin-top:8px;padding:6px 8px;border-radius:6px;'
      + 'background:#fff5f5;border:1px solid #fecaca;color:#DC2626;'
      + 'font-size:11.5px;font-weight:600;line-height:1.5;text-align:left">'
      + '⚠️ 이 안에 <b>손해 본 주문 ' + fmt(rows.length) + '건</b>'
      + '<div style="font-weight:500;color:#991b1b;margin-top:2px">'
      + '가장 나쁜 건 ' + fmt(Number(worst['마진율']) || 0) + '%</div></div>';
  }

  function normalCardHTML(count) {
    var html = _summaryCardHTML('normal', count, '정상/완료', 'green');
    var note = lossNoteHTML('normal');
    /* ★끼워 넣는 기준점 — 버튼 문구·핸들러가 바뀌어도 깨지지 않게 **가장 짧은 공통부분**만
       잡는다. 2026-07-24 사고: 「세부보기」→「전체내역에서 보기」로 핸들러를 바꿨더니
       'showCardBreakdown' 까지 포함한 기준점이 안 맞아 카드 안 칸이 통째로 사라졌다
       (사장님이 화면에서 발견). 못 찾으면 카드 끝에 붙여 **절대 사라지지 않게** 한다. */
    var anchor = '<button onclick="event.stopPropagation();';
    if (!note) return html;
    return html.indexOf(anchor) >= 0 ? html.replace(anchor, note + anchor)
                                     : html.replace('</div>', note + '</div>');
  }

  window._etcReasonGroups = groups;
  window._etcCardHTML = cardHTML;
  window._cardLossRows = lossRows;
  window._normalCardHTML = normalCardHTML;
})();
