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
 * 사장님 확정(2026-08-06 2차) — 주문금액·마켓 할인
 *   ④ 주문금액 = **표의 `주문금액` 열을 그대로** 더한다(제외 없음).
 *   ⑤ 「마켓 할인」 카드를 주문금액과 매출 **사이**에 넣는다
 *      = 제외 후 `단가×수량 − 실결제금액`.
 *
 * 🔴 옛 주문금액이 왜 틀렸나 — 같은 이름, 두 정의
 *   옛 계산은 `단가`(상품 **개당가**) 만 더했다. 수량도 배송비도 안 들어가서,
 *   표의 `주문금액` 열(order_export._finalize_rows: 단가×수량 + 배송비)과 이름은
 *   같은데 값이 달랐다. 표 합계와 카드가 어긋나는 게 정상처럼 굳어 있었다.
 *
 * 🔴 「주문금액 − 매출」의 정체는 마켓 할인이다
 *   라이브 실측(2026-08-06 오늘·48건): 정가 4,506,140 → 실결제 4,186,470.
 *   롯데온은 26건 **전부** 제휴할인이 붙어 있었다(스스 4/6·11번가 4/4·쿠팡 0/12).
 *   차이가 22만인데 화면에 아무 설명이 없어 「오류 아니냐」가 반복됐다.
 *
 * 🔴 모르는 값을 0 으로 삼키지 않는다
 *   `단가`·`실결제금액`이 빈칸인 행은 흔하다(11번가 구매확정 목록엔 단가가 없다).
 *   0 으로 더하면 주문금액이 조용히 줄고 **할인이 늘어난 것처럼** 보인다.
 *   정산예정과 똑같이 「모르는 N건 빠짐」을 잔글씨 마지막 줄로 말한다.
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
  var AMOUNT_FIELD = '주문금액';     // 표의 그 열(= 단가×수량 + 배송비). 카드와 표는 한 값이다.

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

  /** 주문금액 = 표의 `주문금액` 열 합(제외 없음).
   *  🔴 `단가`를 다시 곱하지 않는다 — 그 셈은 `_finalize_rows` 가 이미 했고,
   *     배송비는 **배송건 첫 행에만** 실려 있어 여기서 다시 더하면 중복된다. */
  function amountSummary(rows) {
    var sum = 0, counted = 0, blank = 0;
    (rows || []).forEach(function (r) {
      var v = (r || {})[AMOUNT_FIELD];
      if (isBlank(v)) { blank++; return; }
      sum += num(v);
      counted++;
    });
    return { sum: sum, counted: counted, blank: blank };
  }

  /** 마켓 할인 = 제외 후 (단가×수량 − 실결제금액). 전 마켓 한 가지 셈이다.
   *  모수는 **매출과 같다**(취소·반품 제외) — 그래야 주문금액 − 할인 = 매출로 읽힌다.
   *  배송비는 양쪽에 똑같이 들어가 상쇄되므로 여기선 안 본다.
   *
   *  🔴 `_cp_seller_dc` 를 여기서 **또 더하면 두 번 센다**
   *     2026-08-06 사장님 확정으로 쿠팡 `실결제금액`이 판매자부담쿠폰을 **이미 뺀**
   *     값이 됐다(order_export 의 `_paid_raw - _sdc`). 그 전에는 쿠팡만 실결제가
   *     할인 차감 **전**이라 여기서 따로 더해 줬는데, 그 줄을 지우지 않으면
   *     쿠팡 할인이 정확히 두 배로 잡힌다. 지웠다 — 되살리지 말 것.
   *  🔴 이제 쿠팡도 매출에서 쿠폰이 빠지므로 주문금액 − 할인 = 매출 이 전 마켓 성립한다. */
  function discountSummary(rows) {
    var sum = 0, counted = 0, blank = 0;
    (rows || []).forEach(function (r) {
      if (rowExcluded(r)) return;
      var u = (r || {})['단가'], p = (r || {})['실결제금액'];
      if (isBlank(u) || isBlank(p)) { blank++; return; }   // 둘 중 하나만 없어도 못 센다
      var q = parseInt((r || {})['수량'], 10);
      if (!isFinite(q) || q < 1) q = 1;
      sum += num(u) * q - num(p);
      counted++;
    });
    return { sum: sum, counted: counted, blank: blank };
  }

  // 카드 밑 잔글씨(사장님 확정 A안) — 화면마다 다시 쓰지 않는다.
  var CAPS = {
    sales:  ['취소·반품 제외', '교환 정산 포함', '실결제+배송비'],
    settle: ['취소·반품 제외', '교환 정산 포함', '배송비 포함'],
    amount: ['단가×수량+배송비', '제외 없음'],
    discount: ['취소·반품 제외', '정가−실결제'],
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

  /** 할인은 「빼는 값」이라 부호를 보여준다. 0 이면 「−0만」이 되지 않게 그냥 둔다.
   *  음수(옵션추가금이 실결제에 실린 경우)는 숨기지 않고 +로 드러낸다. */
  function signedMan(n) {
    if (n > 0) return '−' + man(n);
    if (n < 0) return '+' + man(-n);
    return man(0);
  }

  function withBlank(caps, blank, 말) {
    var out = caps.slice();
    if (blank) out.push(말 + ' 모르는 ' + blank + '건 빠짐');
    return out;
  }

  /** 마켓 할인 잔글씨. 옛 판에는 「쿠팡 쿠폰 N원 포함(매출엔 안 빠짐)」 줄이 있었다 —
   *  쿠팡 실결제가 할인 차감 전이라 항등식이 깨졌기 때문이다. 2026-08-06 확정으로
   *  쿠팡 매출에서도 쿠폰이 빠져 전 마켓 항등식이 성립하므로 그 예외 안내는 없앴다
   *  (남겨 두면 거짓말이 된다). PC·폰이 이 한 함수를 같이 쓴다. */
  function discountCaps(dc) {
    return withBlank(CAPS.discount, dc.blank, '실결제');
  }

  /** PC 주문내역 KPI 6칸 — 주문·발송대기·주문금액·마켓 할인·매출·정산예정.
   *  🔴 마켓 할인은 주문금액과 매출 **사이**에 둔다 — 세 숫자를 왼쪽에서 오른쪽으로
   *     이어 읽으면 「정가 → 할인 → 실제 매출」이 한 줄로 설명된다.
   *  발송대기는 화면의 WAIT 정규식이 세어 넘겨준다(같은 수 두 정의 금지). */
  function kpiHtml(rows, waitN) {
    rows = rows || [];
    var am = amountSummary(rows);
    var dc = discountSummary(rows);
    var st = settleSummary(rows);
    return card('주문', rows.length + '<small>건</small>')
         + card('발송대기', waitN + '<small>건</small>')
         + card('주문금액', man(am.sum), withBlank(CAPS.amount, am.blank, '주문금액'))
         + card('마켓 할인', signedMan(dc.sum), discountCaps(dc))
         + card('매출', man(salesOf(rows)), CAPS.sales)
         + card('정산예정', man(st.sum), withBlank(CAPS.settle, st.blank, '정산예정'));
  }

  var API = {
    SETTLE_FIELD: SETTLE_FIELD,
    AMOUNT_FIELD: AMOUNT_FIELD,
    amountSummary: amountSummary,
    discountSummary: discountSummary,
    discountCaps: discountCaps,
    signedMan: signedMan,
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
