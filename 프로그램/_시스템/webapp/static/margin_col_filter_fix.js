/* margin_col_filter_fix.js — 전체내역 컬럼 필터 통일
   ─────────────────────────────────────────────────────────────
   사장님 신고 2026-08-20: 전체내역탭 헤더 필터를 걸어도 안 걸러지는 칼럼이 있고,
   빈 셀도 "(빈값)"으로 안 걸린다.

   원인 둘 다 openColFilter/_getDetailRowsSorted(margin_embed.html)와 그 전체내역용
   패치본(margin_all_tab.js)이 공유하는 값-키 산출 로직에 있었다:

   1) '제외'·'비대량등록' 칼럼 — 체크박스는 r._excluded/r._manual_reg 를 보고 그리는데,
      필터는 r['제외']/r['비대량등록'] 을 읽는다. 그 두 필드엔 아무도 값을 넣지 않아
      항상 undefined → 옵션이 "(빈값)" 단 하나뿐이라 체크/해제해도 아무것도 안 갈린다.
   2) "(빈값)" 판정이 null/undefined/'' 만 잡는다. 상류에서 문자열화된 "nan"/"None"
      (그리고 공백만 있는 값)은 별도 옵션으로 갈라져 나와, "(빈값)"만 체크해도
      그 행들은 필터를 통과하지 못한다.

   컬럼 필터가 값을 읽는 모든 지점(margin_embed.html 3곳 + margin_all_tab.js 패치본
   1곳)이 이 한 함수로 키를 산출하도록 통일한다 — 정의가 갈라지면 또 조용히 어긋난다. */
(function () {
  'use strict';
  var BLANKISH = { 'nan': 1, 'none': 1, 'na': 1, 'nat': 1, 'null': 1, 'undefined': 1 };
  function colFilterKey(r, col) {
    var val = (col === '제외') ? (r && r._excluded ? '예' : '아니오')
            : (col === '비대량등록') ? (r && r._manual_reg ? '예' : '아니오')
            : (r ? r[col] : null);
    if (val == null) return '(빈값)';
    var s = String(val).trim();
    if (s === '' || BLANKISH[s.toLowerCase()]) return '(빈값)';
    return s;
  }
  window._moumColFilterKey = colFilterKey;
})();
