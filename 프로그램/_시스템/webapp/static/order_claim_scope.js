/* order_claim_scope.js — 주문 집계에서 「무엇을 빼고 무엇을 남기나」 **한 정의**.
 *
 * 왜 파일 하나인가
 *   PC 주문내역(orders/index.html)과 폰 주문(mobile/orders.html)이 각자 자기
 *   정규식을 들고 있으면 같은 이름의 숫자가 두 답을 낸다. 실제로 폰은
 *   `/취소완료|취소요청/` 만 뺐고(반품은 매출에 그대로 섞임), PC 는 아무것도
 *   안 뺐다. 두 화면이 이 파일 하나만 쓰게 한다.
 *
 * 사장님 확정(2026-08-06)
 *   ① 제외 = **취소·반품 클레임**. **교환은 포함**(교환은 정산이 이뤄진다).
 *   ② 매출     = 제외 후 `실결제금액 + 배송비` 합.
 *   ③ 정산예정 = 제외 후 `정산예정금(배송비포함)` 합.
 *
 * 왜 `정산예정금액` 이 아니라 `정산예정금(배송비포함)` 인가
 *   order_export._finalize_rows 규약: `정산예정금액`=상품분(배송비 뺀 값),
 *   `정산예정금(배송비포함)`=정산예정금액+고객배송비. 배송비는 배송건 첫 행에만
 *   실려 있어 그대로 합해도 중복이 없다(lemouton/orders/fulfillment.py 도 같은 열이
 *   단일 원천이라고 못 박는다).
 *
 * 🔴 취소 행을 반드시 걸러야 하는 이유
 *   취소완료는 `정산예정금액`만 0 으로 강제되고(zero_cancel) N열은 `0 + 배송비` 라
 *   **배송비가 남는다**. 안 거르면 취소된 주문의 배송비가 정산예정에 섞인다.
 *
 * 🔴 절대 제외하면 안 되는 값
 *   · 교환* (교환완료·교환요청·교환수거완료·교환보류·교환재발송) — 정산이 이뤄진다
 *   · 취소철회·반품철회 (11번가 클레임코드 4·5) — 되돌린 클레임이라 주문이 **살아 있다**
 *   판정은 **주문상태 칸만** 본다(상품명에 '반품' 글자가 있어도 안 걸리게).
 *
 * 🔴 「철회」 두 글자만 있는 값은 반대다 — 롯데온 odPrgsStepCd 22 = 취소다
 *   같은 글자가 마켓마다 뜻이 갈린다: 11번가 「취소철회」=클레임 되돌림(살아 있음),
 *   롯데온 단독 「철회」=취소(마진 모듈 lemouton/margin/sell_source.py:226 이
 *   `"철회": "취소완료"` 로 매핑 — 그 주석이 "기본값 O 로 새던 것"이라 적고 있다).
 *   그래서 남기는 조건은 「철회가 들어가면」이 아니라 **「취소/반품/교환 뒤에 붙은
 *   철회일 때」** 다. 이걸 뭉뚱그리면 롯데온 취소분이 매출·정산예정에 섞인다.
 *
 * 상태 실값 출처: lemouton/markets/order_export.py `_STATUS_KO`(190~202행) +
 *   11번가 클레임표(1480~1485행) + 롯데온 회수 단계(23~27).
 */
(function (root) {
  'use strict';

  var SETTLE_FIELD = '정산예정금(배송비포함)';

  // 되돌린 클레임·교환 — 여기 걸리면 **무조건 남긴다**(아래 CLAIM_RE 보다 우선).
  //   철회는 「취소철회·반품철회」처럼 **앞 글자가 붙었을 때만** 남긴다
  //   (사이 공백 허용: '반품 철회' 실값이 margin/config.py 137행에 있다).
  //   단독 「철회」는 롯데온 취소라 여기 안 걸리고 아래 CLAIM_RE 가 잡는다.
  var KEEP_RE = /교환|(?:취소|반품)\s*철회/;
  // 취소·반품 부류. 회수*(롯데온 23~27)는 반품 진행 단계이고,
  //   단독 「철회」는 롯데온 odPrgsStepCd 22 = 취소다(위 주석의 근거).
  var CLAIM_RE = /취소|반품|철회|회수(?:지시|진행|완료|확정)/;

  function isExcluded(status) {
    var s = String(status == null ? '' : status).trim();
    if (!s) return false;              // 상태를 모르면 빼지 않는다(지어내기 금지)
    if (KEEP_RE.test(s)) return false; // 교환·철회 우선
    return CLAIM_RE.test(s);
  }

  function rowExcluded(r) {
    return isExcluded((r || {})['주문상태']);
  }

  // 숫자 읽기 — PC·폰이 쓰던 것과 같은 규칙(콤마·원 표기 제거 후 반올림).
  function num(v) {
    var n = parseFloat(String(v == null ? '' : v).replace(/[^0-9.\-]/g, ''));
    return isFinite(n) ? Math.round(n) : 0;
  }

  function isBlank(v) {
    return v == null || String(v).trim() === '';
  }

  /** 매출 = 제외 후 실결제금액 + 배송비. */
  function salesOf(rows) {
    var sum = 0;
    (rows || []).forEach(function (r) {
      if (rowExcluded(r)) return;
      sum += num(r['실결제금액']) + num(r['배송비']);
    });
    return sum;
  }

  /** 정산예정 = 제외 후 `정산예정금(배송비포함)` 합.
   *  빈칸은 건너뛰되 **몇 건을 건너뛰었는지 돌려준다**(모르는 걸 0 으로 숨기지 않는다). */
  function settleSummary(rows) {
    var sum = 0, counted = 0, blank = 0;
    (rows || []).forEach(function (r) {
      if (rowExcluded(r)) return;
      var v = (r || {})[SETTLE_FIELD];
      if (isBlank(v)) { blank++; return; }
      sum += num(v);
      counted++;
    });
    return { sum: sum, counted: counted, blank: blank };
  }

  // 카드 밑 잔글씨(사장님 확정 A안) — 화면마다 다시 쓰지 않는다.
  var CAPS = {
    sales:  ['취소·반품 제외', '교환 정산 포함', '실결제+배송비'],
    settle: ['취소·반품 제외', '교환 정산 포함', '배송비 포함'],
    amount: ['단가 총합', '제외 없음'],
    salesPhone: ['취소·반품 제외', '교환 정산 포함']   // 폰은 칸이 좁아 2줄
  };

  function capHtml(lines) {
    return '<div class="cap">' + (lines || []).join('<br>') + '</div>';
  }

  function card(label, value, caps) {
    return '<div class="kpi"><div class="l">' + label + '</div>'
         + '<div class="v">' + value + '</div>'
         + ((caps && caps.length) ? capHtml(caps) : '')
         + '</div>';
  }

  function man(n) { return (n / 10000).toFixed(0) + '<small>만</small>'; }

  /** PC 주문내역 KPI 5칸 — 주문·발송대기·주문금액·매출·정산예정.
   *  발송대기는 화면의 WAIT 정규식이 세어 넘겨준다(같은 수 두 정의 금지). */
  function kpiHtml(rows, waitN) {
    rows = rows || [];
    var amt = 0;
    rows.forEach(function (r) { amt += num(r['단가']); });   // 주문금액 = 단가 총합(제외 없음)
    var st = settleSummary(rows);
    var settleCaps = CAPS.settle.slice();
    if (st.blank) settleCaps.push('정산예정 모르는 ' + st.blank + '건 빠짐');
    return card('주문', rows.length + '<small>건</small>')
         + card('발송대기', waitN + '<small>건</small>')
         + card('주문금액', man(amt), CAPS.amount)
         + card('매출', man(salesOf(rows)), CAPS.sales)
         + card('정산예정', man(st.sum), settleCaps);
  }

  var API = {
    SETTLE_FIELD: SETTLE_FIELD,
    KEEP_RE: KEEP_RE,
    CLAIM_RE: CLAIM_RE,
    CAPS: CAPS,
    isExcluded: isExcluded,
    rowExcluded: rowExcluded,
    num: num,
    salesOf: salesOf,
    settleSummary: settleSummary,
    capHtml: capHtml,
    kpiHtml: kpiHtml
  };

  root.MOUM_ORDER_SCOPE = API;
  if (typeof module === 'object' && module.exports) { module.exports = API; }
})(typeof globalThis !== 'undefined' ? globalThis : this);
