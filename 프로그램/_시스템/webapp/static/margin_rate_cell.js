/* margin_rate_cell.js — 전체내역 「마진율」 칸 렌더 (모음전 추가분)

   왜 필요한가 (2026-07-24 라이브 실측)
   ────────────────────────────────────
   마진율 = 순마진 ÷ 판매가 다. 판매가(단가×수량)가 0 이면 분모가 0 이라 규칙상 0 이
   나오고, 화면엔 `0.0%` 로 찍힌다. 그 0.0% 는 '마진이 없다'처럼 보이지만 실제로는
   **계산을 못 한 것**이다 — 매입 36,490원짜리 11번가 주문이 판매가 0 이라 순마진
   −36,490 인데 마진율은 0.0% 로 떴고, 역마진 배지도 블랙스팟도 안 붙어 아무 표시
   없이 정상처럼 지나갔다(사장님 발견).

   그래서 판매가·정산이 **둘 다 0** 이면 숫자를 지어내지 말고 「계산불가」라고 그대로
   말한다. 원인은 대개 주문내역 쪽 금액 공란이므로 툴팁으로 어디를 볼지 알려준다.

   본문(margin_embed.html)은 원본 무수정 이식이라 로직을 넣지 않는다 — 씨앗은 이
   함수를 부르는 한 줄뿐이고, 함수가 없으면 원본 그대로 렌더한다(폴백).
*/
(function (root) {
  'use strict';
  function num(v) { var n = Number(v); return isFinite(n) ? n : 0; }

  /* r=행, isBs=블랙스팟 여부, rate=표시용 마진율, fmtPct=본문 포매터 */
  root._moumMarginRateCell = function (r, isBs, rate, fmtPct) {
    if (isBs) return '<td style="font-weight:700;">-100%</td>';
    var sale = num(r && r['판매가']);
    var settle = num(r && r['정산예상금액']);
    if (sale <= 0 && settle <= 0) {
      return '<td style="font-weight:700;color:#9a3412;background:#fff7ed" '
           + 'title="판매가·정산이 모두 0원이라 마진율을 계산할 수 없어요. '
           + '주문내역에서 이 주문의 금액이 비어 있는지 확인해 주세요.">계산불가</td>';
    }
    var pct = (typeof fmtPct === 'function') ? fmtPct(r['마진율'])
                                             : (num(r && r['마진율']).toFixed(1) + '%');
    return '<td style="font-weight:700;"' + (num(rate) < 0 ? ' class="neg"' : '') + '>'
         + pct + '</td>';
  };
})(typeof window !== 'undefined' ? window : globalThis);
