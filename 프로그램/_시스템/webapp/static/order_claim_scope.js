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

  /** 마켓 할인을 **잴 수 없는** 마켓 — 0 이 아니라 「확인 불가」로 적을 곳.
   *  정합성 3대 원칙: 확인 못 하면 「확인 불가」, 추정·폴백 금지.
   *
   *  🔴 2026-08-12 현재 **비어 있다**(= 확인 불가 마켓 없음). 옛 판에는 옥션·G마켓이
   *    들어 있었는데, 그건 `OrderAmount`·`AcntMoney` 두 필드만 보고 「구조적으로 못
   *    가른다」고 낸 **오판**이었다. 같은 주문조회 응답 안에 갈래가 그대로 있다:
   *      · 옥션 2567864872  SellerDiscountPrice 0 · DirectDiscountPrice 8,980
   *      · G마켓 22행 중 18행  셀러 합 0 · 마켓 합 47,640
   *    `_finalize_rows` 의 `force_orig` 도 이제 판매자할인만 빼므로(사이트할인은 마켓
   *    돈이라 안 뺀다), 「정가−실결제」가 곧 우리 부담이 된다.
   *    이름은 남긴다 — 갈래를 못 주는 마켓이 생기면 여기에 넣으면 그대로 작동한다. */
  var ESM_UNKNOWN = {};

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

  /** 한 행의 매출 = 정가 + 배송비 − **판매자부담** 할인 (사장님 확정 2026-08-13).
   *  🔴 마켓(사이트)이 부담한 할인은 마켓이 대신 내주고 우리는 정가대로 정산받으므로
   *    빼지 않는다. 예전엔 `실결제금액`을 그대로 매출로 썼는데, 스스·롯데온·11번가는
   *    실결제에 **마켓 부담분까지** 빠져 있어 우리 매출이 실제보다 작았다
   *    (라이브 30일 실측 2026-08-13: 롯데온 3,205,562원·스스 24,000원 과소).
   *  🔴 값은 주문내역 서버(order_export)가 `_매출기준액` 한 칸으로 **한 번만** 만든다.
   *    화면이 다시 계산하면 마진계산기·엑셀과 조용히 갈린다.
   *  없거나 0(판매자할인 모름·취소·옛 저장분)이면 옛 기준(실결제+배송비)으로 폴백한다. */
  function saleBasisOf(r) {
    r = r || {};
    var s = num(r['_매출기준액']);
    if (s > 0) return s;
    return num(r['실결제금액']) + num(r['배송비']);
  }

  /** 매출 = 제외 후 행별 매출 기준액 합. */
  function salesOf(rows) {
    var sum = 0;
    (rows || []).forEach(function (r) {
      if (rowExcluded(r)) return;
      sum += saleBasisOf(r);
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
      // 🔴 2026-08-08 사장님 확정 — 여기도 취소·반품을 뺀다.
      //   전엔 주문금액만 「제외 없음」이라 세 숫자가 안 이어졌다
      //   (실측 3,658 − 207 ≠ 2,485 — 차이의 대부분이 취소·반품이었다).
      //   매출·할인과 같은 모수여야 「정가 → 할인 → 매출」로 읽힌다.
      if (rowExcluded(r)) return;
      var v = (r || {})[AMOUNT_FIELD];
      if (isBlank(v)) { blank++; return; }
      sum += num(v);
      counted++;
    });
    return { sum: sum, counted: counted, blank: blank };
  }

  /** 판매처별 마켓 할인 — 호버 창이 쓸 자료.
   *  · markets = [{market, sum, count, top:[{name, amount, orderNo}…]}] 할인 많은 순
   *  · esmUnknown = 옥션·G마켓 건수(금액 표에 안 섞는다 — 0 으로 보이면 「할인 없음」 오독)
   *  · blank = 정가·실결제를 모르는 건수 */
  function discountByMarket(rows) {
    var by = {}, esmUnknown = 0, blank = 0, total = 0;
    (rows || []).forEach(function (r) {
      r = r || {};
      if (rowExcluded(r)) return;
      var mk = r['판매처'] || '(모름)';
      if (ESM_UNKNOWN[mk]) { esmUnknown++; return; }
      var g = 정가(r), p = r['실결제금액'];
      if (g === null || isBlank(p)) { blank++; return; }
      var d = g - num(p);
      var b = by[mk] || (by[mk] = { market: mk, sum: 0, count: 0, top: [],
                                    seller: 0, mkt: 0, mktOut: 0, known: 0, kinds: {} });
      b.sum += d; b.count++; total += d;
      // ── 「누가 깎아 줬나」 — 마켓이 갈라 주는 곳만 센다(안 주면 안 세고 건수로 남긴다) ──
      //  스스: 총(_dc_total) − 셀러(_dc_seller) = 마켓. 나머지 마켓은 둘 다 실값으로 온다.
      // 🔴 부담율은 **화면에 뜬 그 금액(d)** 을 100 으로 놓고 잰다(2026-08-12 정정).
      //   마켓마다 `실결제금액`의 뜻이 달라 카드 금액에 담긴 것이 다르기 때문:
      //     · 스스·11번가·롯데온 — 실결제가 모든 할인 반영 → d = 셀러+마켓
      //     · 쿠팡             — 실결제가 셀러 쿠폰만 반영 → d = 셀러분만
      //   옛 식 `셀러/(셀러+마켓)` 은 카드에 없는 마켓분을 분모에 넣어, 쿠팡이
      //   **「우리 부담 0%」**로 떴다(라이브 실측 — 그 100원은 전액 우리 돈이다).
      //   우리 몫은 d 를 넘을 수 없으므로 잘라 쓴다.
      var s = r['_dc_seller'], mk2 = r['_dc_market'];
      if (!isBlank(s)) {
        var sv = Math.max(0, Math.min(num(s), d));
        var mvIn = Math.max(0, d - sv);          // 카드 금액 안에 든 마켓 몫
        b.seller += sv; b.mkt += mvIn; b.known++;
        // 🔴 마켓이 **카드 밖에서** 부담한 몫 — 우리 매출과 무관해 카드 금액엔 없다.
        //   비율만 쓰면 「옥션이 8,980원 깎아줬다」는 사실이 화면에서 사라진다.
        if (!isBlank(mk2)) b.mktOut += Math.max(0, num(mk2) - mvIn);
      }
      var kk = r['_dc_kinds'];
      if (kk) {
        for (var kn in kk) {
          if (!Object.prototype.hasOwnProperty.call(kk, kn) || isBlank(kk[kn])) continue;
          if (num(kk[kn]) > 0) b.kinds[kn] = (b.kinds[kn] || 0) + num(kk[kn]);
        }
      }
      if (d > 0) {
        b.top.push({ name: String(r['상품명'] || ''), amount: d,
                     orderNo: String(r['오픈마켓주문번호'] || '') });
      }
    });
    var out = [];
    for (var k in by) {
      if (!Object.prototype.hasOwnProperty.call(by, k)) continue;
      by[k].top.sort(function (a, b2) { return b2.amount - a.amount; });
      by[k].top = by[k].top.slice(0, 3);
      // 셀러 부담율 = 셀러 / (셀러+마켓). 🔴 갈래를 아는 행이 하나도 없으면 **null**
      //   — 0% 로 적으면 「마켓이 다 내줬다」는 거짓말이 된다.
      var b3 = by[k], tot2 = b3.seller + b3.mkt;
      b3.sellerRate = (b3.known && tot2 > 0) ? Math.round(b3.seller / tot2 * 100) : null;
      // 🔴 얼마나 근거가 있는 비율인지 같이 돌려준다(2026-08-12).
      //   11번가는 109행 중 19행만 갈래 값이 온다 — 아는 행만으로 낸 비율을 화면이
      //   **전체인 양** 보여줘 할인 569,904원 중 466,989원이 근거 없는 몫이 됐다.
      b3.knownSum = tot2;
      b3.kindList = Object.keys(b3.kinds)
        .map(function (n) { return { name: n, amount: b3.kinds[n] }; })
        .sort(function (x, y) { return y.amount - x.amount; });
      // 할인도 0 이고 마켓이 따로 낸 것도 없으면 표에 안 싣는다(빈 줄 = 잡음).
      //   단 마켓이 따로 부담한 게 있으면 금액이 0 이어도 남긴다 — 그게 볼거리다.
      if (b3.sum !== 0 || b3.mktOut > 0) out.push(b3);
    }
    out.sort(function (a, b2) { return b2.sum - a.sum; });
    return { markets: out, total: total, esmUnknown: esmUnknown, blank: blank };
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
   *  🔴 2026-08-13 정정 — 이 카드의 「할인」은 **고객이 받은 할인 총액**(판매자+마켓)이다.
   *     매출 정의가 「정가 − 판매자부담」으로 바뀌었으므로 `주문금액 − 할인 = 매출` 은
   *     더 이상 성립하지 않는다. 성립하는 관계는 `주문금액 − 판매자부담 = 매출` 이고,
   *     그 갈래(우리 부담 vs 마켓 부담)는 아래 호버 창이 이미 갈라 보여 준다. */
  /** 할인을 재는 「정가」 = 총주문금액(단가×수량 + **옵션추가금**).
   *  🔴 2026-08-12 — 옛 코드는 `단가×수량` 만 봐서 옵션가를 통째로 빼먹었다.
   *     실결제엔 옵션가가 들어 있으므로 할인이 **음수**로 나왔다(라이브 스스 81행 중 16행).
   *     총주문금액이 없으면(옛 저장분) 단가×수량+옵션추가금으로 직접 만든다.
   *     그마저 못 만들면 null — 지어내지 않고 「모르는 건수」로 센다. */
  function 정가(r) {
    r = r || {};
    if (!isBlank(r['총주문금액'])) return num(r['총주문금액']);
    if (isBlank(r['단가'])) return null;
    var q = parseInt(r['수량'], 10);
    if (!isFinite(q) || q < 1) q = 1;
    return num(r['단가']) * q + (isBlank(r['옵션추가금']) ? 0 : num(r['옵션추가금']));
  }

  function discountSummary(rows) {
    var sum = 0, counted = 0, blank = 0, esmUnknown = 0;
    (rows || []).forEach(function (r) {
      if (rowExcluded(r)) return;
      if (ESM_UNKNOWN[(r || {})['판매처']]) { esmUnknown++; return; }
      var g = 정가(r), p = (r || {})['실결제금액'];
      if (g === null || isBlank(p)) { blank++; return; }   // 둘 중 하나만 없어도 못 센다
      sum += g - num(p);
      counted++;
    });
    return { sum: sum, counted: counted, blank: blank, esmUnknown: esmUnknown };
  }

  // 카드 밑 잔글씨(사장님 확정 A안) — 화면마다 다시 쓰지 않는다.
  var CAPS = {
    sales:  ['취소·반품 제외', '교환 정산 포함', '실결제+배송비'],
    settle: ['취소·반품 제외', '교환 정산 포함', '배송비 포함'],
    amount: ['단가×수량+옵션+배송비', '취소·반품 제외'],
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

  /** 판매처 한 줄의 「누가 냈나」 문구 — PC·폰이 **같은 함수**를 쓴다.
   *  갈래를 모르는 몫이 있으면 그 금액을 반드시 밝힌다(부분을 전체로 읽히지 않게). */
  function comma(n) {
    return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }

  function burdenLine(m) {
    if (!m) return '';
    var rest = Math.max(0, (m.sum || 0) - (m.knownSum || 0));
    // 🔴 「우리가 낸 게 0원」과 「누가 냈는지 모른다」는 완전히 다른 말이다(2026-08-12).
    //   옥션은 SellerDiscountPrice=0 · DirectDiscountPrice=8,980 이 실제로 온다 —
    //   갈래를 아는데 「확인 불가」로 뭉개면 아는 사실을 화면이 모른다고 거짓말한다.
    var head = (m.sellerRate == null)
      ? (m.known ? '우리 부담 없음(전액 마켓 부담)' : '누가 냈는지 확인 불가')
      : '우리 부담 ' + m.sellerRate + '% · 마켓 부담 ' + (100 - m.sellerRate) + '%';
    if (rest > 0 && m.sellerRate != null) {
      head += ' (' + comma(m.knownSum) + '원만 확인 · ' + comma(rest) + '원은 확인 불가)';
    }
    if (m.mktOut > 0) {
      head += ' · 마켓이 따로 ' + comma(m.mktOut) + '원 부담(우리 매출과 무관)';
    }
    return head;
  }

  /** 마켓 할인 잔글씨. 옛 판에는 「쿠팡 쿠폰 N원 포함(매출엔 안 빠짐)」 줄이 있었다 —
   *  쿠팡 실결제가 할인 차감 전이라 항등식이 깨졌기 때문이다. 2026-08-06 확정으로
   *  쿠팡 매출에서도 쿠폰이 빠져 전 마켓 항등식이 성립하므로 그 예외 안내는 없앴다
   *  (남겨 두면 거짓말이 된다). PC·폰이 이 한 함수를 같이 쓴다. */
  function discountCaps(dc) {
    var out = withBlank(CAPS.discount, dc.blank, '실결제');
    // 「0 이라 안 보이는 것」과 「못 재서 안 보이는 것」을 화면이 갈라 말한다.
    if (dc.esmUnknown) out.push('옥션·G마켓 ' + dc.esmUnknown + '건은 할인 확인 불가');
    return out;
  }

  /** PC 주문내역 KPI 6칸 — 주문·발송대기·주문금액·마켓 할인·매출·정산예정.
   *  🔴 마켓 할인은 주문금액과 매출 **사이**에 둔다 — 세 숫자를 왼쪽에서 오른쪽으로
   *     이어 읽으면 「정가 → 할인 → 실제 매출」이 한 줄로 설명된다.
   *  발송대기는 화면의 WAIT 정규식이 세어 넘겨준다(같은 수 두 정의 금지). */
  /** 매출 카드 밑에 붙는 한 줄 — 할인이 **이미 빠졌음**을 말하는 자리.
   *  🔴 옆 칸에 「−207만」으로 세웠더니 **또 빼는 돈**으로 읽혔다(2026-08-08 사장님 지적).
   *     매출은 이미 할인이 빠진 값이라, 「반영됨」이라고 말해야 두 번 빼지 않는다.
   *  `data-pop` 이 호버 창의 앵커다(마켓별 내역은 화면이 그린다). */
  function discountHint(dc) {
    if (!dc || (!dc.sum && !dc.esmUnknown)) return '';
    return '<b class="hi" data-pop="disc">마켓 할인 ' + man(dc.sum).replace('<small>', '<small>')
         + ' 반영됨<span class="q">?</span></b>';
  }

  function kpiHtml(rows, waitN) {
    rows = rows || [];
    var am = amountSummary(rows);
    var dc = discountSummary(rows);
    var st = settleSummary(rows);
    var salesCaps = CAPS.sales.concat([discountHint(dc)]).filter(Boolean);
    return card('주문', rows.length + '<small>건</small>')
         + card('발송대기', waitN + '<small>건</small>')
         + card('주문금액', man(am.sum), withBlank(CAPS.amount, am.blank, '주문금액'))
         + card('매출', man(salesOf(rows)), salesCaps)
         + card('정산예정', man(st.sum), withBlank(CAPS.settle, st.blank, '정산예정'));
  }

  var API = {
    SETTLE_FIELD: SETTLE_FIELD,
    AMOUNT_FIELD: AMOUNT_FIELD,
    amountSummary: amountSummary,
    saleBasisOf: saleBasisOf,
    discountSummary: discountSummary,
    discountByMarket: discountByMarket,
    discountCaps: discountCaps,
    burdenLine: burdenLine,
    discountHint: discountHint,
    ESM_UNKNOWN: ESM_UNKNOWN,
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
