/* margin_all_tab.js — 카드 클릭 → 「카드 아래에」 그 카드 주문을 전체내역 양식으로 펼침
   ─────────────────────────────────────────────────────────────
   사장님 확정 2026-07-25 (재수정): 카드를 누르면 **전체내역 탭으로 이동하지 말고**,
   카드 바로 아래(#detail-section)에 그 카드에 속한 주문을 전체내역 24열 양식으로 펼친다.

   이미 소분류 칸(파랑·초록·빨강)이 쓰던 `_showCardAllRows(type, sub)` 가 그 일을 한다
   (buildDetailTable → #detail-section, 카드 바로 아래). 카드 본체·「보기」 버튼·사이드
   패널 버튼이 예전엔 탭 이동(_goAllWithCardFilter/_jumpAllByCard)이었는데, 전부 이 인라인
   펼침으로 돌린다. 표를 다시 그리지 않고 렌더러 하나(buildDetailTable)만 쓰므로 양식이
   전체내역과 항상 같다.

   ★ 로드 순서: 이 정적 파일은 인라인 <script>(margin_embed 본문)보다 **먼저** 실행된다.
     그래서 _showCardAllRows·_jumpAllByCard·_selectBsCard 는 이 시점엔 아직 없다 →
     · go() 는 **클릭 시점**에 window._showCardAllRows 를 참조(그때는 정의돼 있다).
     · _jumpAllByCard·_selectBsCard 덮어쓰기는 DOMContentLoaded 에서(인라인 정의 후) 한다. */
(function () {
  'use strict';

  function inlineCard(type, sub) {
    if (typeof window._showCardAllRows === 'function') {
      window._showCardAllRows(type, sub || undefined);
      return true;
    }
    return false;
  }

  /* 카드 「📋 …보기」 버튼(본문 씨앗)이 부르는 진입점.
     예전엔 전체내역 탭으로 점프했지만, 이제 카드 아래 인라인 펼침. */
  function go(type, label, sub) {
    inlineCard(type, sub);
  }

  window._goAllWithCardFilter = go;

  /* 인라인 정의(_jumpAllByCard·_selectBsCard) 이후에 덮어써야 하므로 DOM 준비 후 실행. */
  function wireInline() {
    /* 사이드 패널 「전체내역에서 보기 →」 도 인라인 펼침으로. */
    window._jumpAllByCard = function (type) { inlineCard(type); };

    /* 카드 본체 클릭 — 원래 선택(사이드 패널 갱신)은 그대로 두고, 아래 인라인 펼침을 더한다.
       원본 _selectBsCard 는 인라인 스크립트에서 정의된다(프리즈 대상) → 손대지 않고 감싼다. */
    var origSelect = window._selectBsCard;
    if (typeof origSelect === 'function' && !origSelect.__moumWrapped) {
      var wrapped = function (type, label) {
        try { origSelect(type, label); } catch (e) { /* 선택 실패해도 펼침은 시도 */ }
        inlineCard(type);
      };
      wrapped.__moumWrapped = true;
      window._selectBsCard = wrapped;
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wireInline);
  } else {
    wireInline();
  }
})();
