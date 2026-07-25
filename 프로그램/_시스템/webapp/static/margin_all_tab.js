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

  /* 전체내역 탭 = 카드 상세와 완전 같은 뿌리 (사장님 확정 2026-07-25).
     탭 디스패치(map.all)가 씨앗으로 window._moumRenderAll 을 우선 쓴다. 여기서 'all' 카드
     행을 buildDetailTable 로 렌더 — 카드 상세와 같은 24열+체크박스+간단메모+인라인 편집.
     데이터(analysisData)가 공유라, 카드 상세든 이 탭이든 한쪽에서 단가/정산/매입을 고치면
     editCell 이 공유 행을 갱신해 양쪽에 반영된다(재렌더/탭 전환 시 자동 동기화).
     ★buildDetailTable 은 #detail-section 에 그린다 → 이 탭 안에 그 컨테이너를 만들어 채운다.
       탭 콘텐츠는 한 번에 하나만 렌더되므로 블랙스팟 탭의 #detail-section 과 겹치지 않는다. */
  window._moumRenderAll = function (d) {
    var all;
    if (window.__allMarginFilter === 'unfulfilled' && typeof window._getUnfulfilledRows === 'function') {
      all = window._getUnfulfilledRows();
    } else if (typeof window._getRowsByCardFilter === 'function' && d && d.summary) {
      all = window._getRowsByCardFilter('all');
    } else {
      all = (d && d.matched) || [];
    }
    setTimeout(function () {
      if (typeof window.buildDetailTable !== 'function') return;
      if (window.state) {
        window.state.currentDetailCode = '__CARD_ALL__';
        window.state.currentDetailCardCtx = 'all';
        window.state.currentDetailSubFilter = null;
      }
      window.buildDetailTable('__CARD_ALL__', all, 'all');
    }, 0);
    return '<div id="detail-section"></div>';
  };

  /* 카드 「📋 …보기」 버튼(본문 씨앗)이 부르는 진입점.
     예전엔 전체내역 탭으로 점프했지만, 이제 카드 아래 인라인 펼침. */
  function go(type, label, sub) {
    inlineCard(type, sub);
  }

  window._goAllWithCardFilter = go;

  /* 사이드 패널 내용 — 사장님 요청 2026-07-25: 「상세내역 보기」·「전체내역에서 보기」
     버튼은 이제 의미 없다(카드 누르면 아래에 바로 상세가 뜬다). 버튼 없이 선택 카드
     건수만 보여준다. 원본 _renderBsSidePanelContent 를 통째로 대체. */
  function bsSidePanelNoButtons() {
    var type = (window.state && window.state.selectedCardType) || null;
    if (!type) {
      return '<div style="font-size:13px;color:#9ca3af;font-weight:500;margin-bottom:8px">💡 카드 선택</div>'
           + '<div style="font-size:14px;color:#d1d5db;line-height:1.5">왼쪽 카드를 클릭하면<br>아래에 상세내역이 바로 나타납니다</div>';
    }
    var label = (window.state && window.state.selectedCardLabel) || type;
    var rows = (typeof window._getRowsByCardFilter === 'function') ? window._getRowsByCardFilter(type) : [];
    var n = rows.length;
    var fmt = (typeof window.fmt === 'function') ? window.fmt : function (x) { return x; };
    var esc = (typeof window.esc === 'function') ? window.esc : function (x) { return x; };
    return '<div style="font-size:12px;color:#9ca3af;font-weight:500;margin-bottom:6px">선택된 카드</div>'
         + '<div style="font-size:16px;font-weight:700;color:#fff;display:flex;align-items:baseline;gap:8px">'
         +   '<span style="font-size:32px;font-weight:800;color:#f59e0b;letter-spacing:-0.02em">' + fmt(n) + '</span>'
         +   '<span style="font-size:13px;color:#d1d5db">' + esc(label) + '</span>'
         + '</div>'
         + '<div style="margin-top:10px;font-size:12px;color:#9ca3af;line-height:1.5">아래에 상세내역이 표시됩니다.</div>';
  }

  /* 인라인 정의(_jumpAllByCard·_selectBsCard) 이후에 덮어써야 하므로 DOM 준비 후 실행. */
  function wireInline() {
    /* 사이드 패널 「전체내역에서 보기 →」 도 인라인 펼침으로. */
    window._jumpAllByCard = function (type) { inlineCard(type); };

    /* 사이드 패널 버튼 제거 (상세내역 보기·전체내역에서 보기 → 의미 없어짐). */
    if (typeof window._renderBsSidePanelContent === 'function') {
      window._renderBsSidePanelContent = bsSidePanelNoButtons;
    }

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
