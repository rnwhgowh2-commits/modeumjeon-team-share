/* margin_route_cell.js — 전체내역 「판매경로」 칸 렌더 (모음전 추가분)

   왜 필요한가 (2026-07-25 샵마인 대조에서 발견)
   ────────────────────────────────────────────
   롯데온 판매경로는 제휴 / 롯데ON / 미확인 3상태다. 제휴면 상품가 2% 수수료가 정산에서
   더 빠진다. 그런데 원본 렌더는 '제휴'가 아닌 값을 전부 같은 파란 칸(롯데ON 색)으로
   그렸다 — '미확인'인데도 롯데ON 처럼 보여, 2% 를 안 뗀 정산이 **맞는 값처럼** 읽혔다.

   그래서 '미확인'은 회색으로 따로 뗀다(확정된 롯데ON 과 눈으로 갈리게). 라벨은 낱말
   하나 '미확인'(사장님 확정 2026-07-25). 툴팁은 제휴면 2% 부과, 미확인이면 '아직
   판별 못 함 — 제휴면 2%가 더 빠진다'로 왜 조심해야 하는지 알린다.

   본문(margin_embed.html)은 원본 무수정 이식이라 로직을 넣지 않는다 — 씨앗은 이 함수를
   부르는 한 줄뿐이고, 함수가 없으면 원본 그대로 렌더한다(폴백). margin_rate_cell.js 와
   동일 패턴.
*/
(function (root) {
  'use strict';

  /* r=행, esc=본문 HTML 이스케이프 함수 */
  root._moumRouteCell = function (r, esc) {
    var ch = String((r && r['판매경로']) || '');
    if (!ch) return '<td style="text-align:center;color:#c9cdd2">—</td>';

    var isAff = ch.indexOf('제휴') >= 0;                 // '제휴'
    var unknown = (ch === '미확인' || ch === '확인 불가');  // '미확인'/옛 '확인 불가'

    var st, lbl, tip;
    if (isAff) {
      st = 'background:#FFF0F0;color:#c92a2a';
      lbl = '제휴 2%';                                   // '제휴 2%'
      tip = ch + ' — 상품가 2% 제휴수수료 부과';
    } else if (unknown) {
      st = 'background:#F1EFE8;color:#5F5E5A';                    // 회색 — 확정 아님을 눈에 띄게
      lbl = '미확인';                                // '미확인'
      tip = '아직 판별 못 했어요 — 제휴면 정산에서 2%가 더 빠집니다.';
    } else {
      st = 'background:#EAF2FF;color:#1d4ed8';
      lbl = ch;                                                  // '롯데ON'
      tip = ch + ' — 제휴수수료 없음';
    }
    return '<td style="text-align:center"><span style="' + st
         + ';padding:1px 7px;border-radius:10px;font-size:11px;font-weight:700" title="'
         + esc(tip) + '">' + esc(lbl) + '</span></td>';
  };
})(typeof window !== 'undefined' ? window : globalThis);
