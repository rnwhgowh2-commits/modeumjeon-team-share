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

  /* 헤더(첫 행) 고정 — 아래로 스크롤해도 열 이름이 계속 보이게 (사장님 요청 2026-07-30).
     표는 `.table-wrap`(max-height:70vh) 안에서 세로로 스크롤되므로 `position:sticky;top:0` 이면 된다.
     막고 있던 것 둘:
       ① 씨앗이 헤더 칸에 **인라인으로** `position:relative`(고정 열만 sticky)·`z-index:1` 을 박아둠
          → 인라인이 더 세서 CSS 로 이기려면 !important 가 필요하다.
       ② 헤더 칸에 **배경색이 없다**(투명 → 카드 흰색이 비침). 그대로 고정하면 행이 헤더를 뚫고 지나간다.
          지금 보이는 색 그대로 유지 — 일반 칸 #fff · 왼쪽 고정 열 #f8f9fb(기존값).
     z-index: 일반 헤더 4 > 본문 고정열 칸 2, 헤더 고정열 6 > 4 (왼쪽 위 모서리가 항상 위).
     밑줄은 border-collapse:collapse 라 스크롤 시 사라져서 ::after 로 다시 그린다(기존 1.5px #E5E8EB 동일). */
  (function stickyHead() {
    if (document.getElementById('moum-sticky-head')) return;
    var st = document.createElement('style');
    st.id = 'moum-sticky-head';
    st.textContent =
      '#detail-table thead th{position:sticky !important;top:0;z-index:4 !important;background:#fff}' +
      '#detail-table thead th.sticky-col{background:#f8f9fb;z-index:6 !important}' +
      '#detail-table thead th::after{content:"";position:absolute;left:0;right:0;bottom:0;' +
      'height:1.5px;background:#E5E8EB;pointer-events:none}';
    (document.head || document.documentElement).appendChild(st);
  })();

  function inlineCard(type, sub) {
    /* 🔴 까대기 소분류(done/sent/none)는 _showCardAllRows 가 안 거른다(그 함수는
       rtn/ex/normal/etc 만 처리). 그대로 넘기면 소분류를 눌러도 까대기 전체가 나온다.
       (사장님 신고 2026-07-25). 여기서 _kkadaegiSentSubFilter 로 직접 걸러 buildDetailTable
       에 넘긴다 — 카드 상세와 같은 렌더러·같은 #detail-section. */
    if (type === 'kkadaegi_sent' && sub
        && typeof window._kkadaegiSentSubFilter === 'function'
        && typeof window._getRowsByCardFilter === 'function'
        && typeof window.buildDetailTable === 'function') {
      var rows = (window._getRowsByCardFilter('kkadaegi_sent') || [])
        .filter(function (r) { return window._kkadaegiSentSubFilter(r, sub); });
      if (window.state) {
        window.state.currentDetailCode = '__CARD_ALL__';
        window.state.currentDetailCardCtx = 'kkadaegi_sent';
        window.state.currentDetailSubFilter = sub;
      }
      window.buildDetailTable('__CARD_ALL__', rows, 'kkadaegi_sent');
      setTimeout(function () {
        var ds = document.getElementById('detail-section');
        if (ds) window.scrollTo(0, Math.max(0, ds.getBoundingClientRect().top + window.scrollY - 80));
      }, 200);
      return true;
    }
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
  /* 전체내역 탭의 「기준 행」 단일 원천 — 최초 렌더(_moumRenderAll)와 정렬 재렌더
     (_getDetailRowsSorted)가 반드시 같은 소스를 써야 한다. 예전엔 최초=_getRowsByCardFilter('all')
     인데 정렬 재렌더는 state.tab1Data(classified)를 써서 소스가 달라졌고, buildDetailTable 이
     행 데이터에서 usedCols(표시 열)를 매번 다시 뽑기 때문에 정렬만 눌러도 「양식(열 구성)」이
     바뀌었다(사장님 신고 2026-07-25 ④). 여기로 통일해 열이 고정되게 한다.
     · __allMarginFilter (드롭다운/이상마진 점프) = ''·normal·abnormal·unfulfilled 모두 반영
       → 이상마진 클릭 시 실제로 이상마진만 걸러진다(③). 기준은 구 filterAll 과 동일.
     · __cardFilterForAll (블랙스팟 카드 필터)도 반영. */
  function _moumAllBaseRows(d) {
    var flt = window.__allMarginFilter || '';
    var rows;
    if (flt === 'unfulfilled' && typeof window._getUnfulfilledRows === 'function') {
      rows = window._getUnfulfilledRows();
    } else if (typeof window._getRowsByCardFilter === 'function') {
      rows = window._getRowsByCardFilter('all');
    } else {
      rows = (d && d.matched) || (window.analysisData && window.analysisData.matched) || [];
    }
    if (flt === 'abnormal' || flt === 'normal') {
      rows = rows.filter(function (r) {
        var mr = Number(r['마진율']) || 0, ma = Number(r['순마진']) || 0;
        var isHigh = (typeof isHighMargin === 'function') ? isHighMargin(mr, ma) : false;
        var isNeg = ((typeof MR !== 'undefined' && MR) ? MR.rowMargin(r) : ma) < 0;
        var isUnf = r['_주문미이행'] && !r['_매입흔적'];
        if (flt === 'abnormal') return !(r._excluded || r['이상가'] || isUnf || (!isNeg && !isHigh));
        return !(isUnf || isNeg || isHigh);   /* normal */
      });
    }
    var cf = window.__cardFilterForAll;
    if (cf && flt !== 'unfulfilled' && typeof window._getRowsByCardFilter === 'function') {
      var set = new Set(window._getRowsByCardFilter(cf));
      rows = rows.filter(function (r) { return set.has(r); });
    }
    return rows;
  }
  window._moumAllBaseRows = _moumAllBaseRows;

  window._moumRenderAll = function (d) {
    var all = _moumAllBaseRows(d);
    setTimeout(function () {
      if (typeof window.buildDetailTable !== 'function') return;
      /* 🔴 열 필터(▼) 목록이 통째로 비던 버그 — 필터는 state.tab1Data 를 보는데 그건
         _syncBlackspotState() 가 채운다. 그 함수는 renderBlackspot 안에서만 불려서,
         블랙스팟 탭을 한 번도 안 열고 전체내역 탭으로 오면 tab1Data 가 비어 있었다
         (사장님 화면 실측 2026-07-30: 「필터 — 판매처_주문상태」 목록 0개).
         → 전체내역 탭도 같은 상태를 채우고 시작한다. */
      if (typeof window._syncBlackspotState === 'function') {
        try { window._syncBlackspotState(); } catch (e) { /* 표는 그려야 한다 */ }
      }
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
      return '<div style="font-size:13px;color:#9ca3af;font-weight:500;margin-bottom:8px">카드 선택</div>'
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

    /* 정렬해도 보던 자리 그대로 (사장님 신고 2026-07-30).
       표를 오른쪽으로 밀어놓고 열 이름을 눌러 정렬하면 표가 맨 왼쪽으로 튕겨 돌아왔다.
       원인 둘:
         ① sortDetailColumn 은 `section.innerHTML = h` 로 표를 통째 다시 그리는데,
            가로 스크롤을 가진 `.table-wrap` 이 새로 만들어져 scrollLeft 이 0 이 된다.
            (원본은 window 세로 위치만 보존한다 — 표 내부 스크롤은 안 봄)
         ② 그 복원 코드가 `window.scrollTo(0, scrollY)` 라 **페이지 가로 위치까지 0 으로** 민다.
       → 원본은 손대지 않고 감싸서, 정렬 전 위치(표 가로·세로 + 페이지 가로·세로)를 기억했다가
         다시 그린 뒤 되돌린다. 정렬 방향만 바뀌고 화면은 그대로다.
       ★rAF 복원은 원본의 rAF 보다 **나중에** 등록되므로 원본의 scrollTo 를 덮어쓴다(순서 보장). */
    var _origSort = window.sortDetailColumn;
    if (typeof _origSort === 'function' && !_origSort.__moumKeepScroll) {
      var patchedSort = function (col) {
        var wrap = document.querySelector('#detail-section .table-wrap');
        var sl = wrap ? wrap.scrollLeft : 0;
        var st = wrap ? wrap.scrollTop : 0;
        var wx = window.scrollX || window.pageXOffset || 0;
        var wy = window.scrollY || window.pageYOffset || 0;
        var ret = _origSort.apply(this, arguments);
        var restore = function () {
          var w2 = document.querySelector('#detail-section .table-wrap');
          if (w2) { w2.scrollLeft = sl; w2.scrollTop = st; }
          window.scrollTo(wx, wy);
        };
        restore();                       /* 즉시 — 다시 그린 직후라 깜빡임이 안 보인다 */
        requestAnimationFrame(restore);  /* 레이아웃 확정 후 한 번 더(원본 rAF 뒤에 실행) */
        return ret;
      };
      patchedSort.__moumKeepScroll = true;
      window.sortDetailColumn = patchedSort;
    }

    /* ③ 이상마진 클릭 → 전체내역에서 이상마진만 (사장님 신고 2026-07-25).
       원본 gotoAbnormalAll 은 죽은 filterAll/renderAll 기계에 의존해 필터가 안 걸렸다
       (전체내역 탭은 _moumRenderAll 로 대체됨). _jumpToUnfulfilled 와 같은 방식으로 고친다:
       __allMarginFilter='abnormal' 을 세우고 preserveFilter 로 탭 전환 → _moumAllBaseRows 가
       이상마진만 거른다. filterAll(no-op) 의존을 끊고, 리셋(null)도 하지 않는다(정렬해도 유지). */
    window.gotoAbnormalAll = function () {
      window.__allMarginFilter = 'abnormal';
      window.__cardFilterForAll = null;
      window.__allColFilters = {};
      if (window.state) { window.state.detailColFilters = {}; window.state.detailSort = null; }
      var tabs = document.querySelectorAll('[onclick*="switchTab"]');
      var t = Array.prototype.slice.call(tabs).filter(function (el) { return el.textContent.trim() === '전체내역'; })[0];
      if (t && typeof switchTab === 'function') switchTab(t, true);
      if (typeof renderCurrentTab === 'function') renderCurrentTab();
    };

    /* ④ 정렬 시 「양식(열)」이 바뀌던 버그 (사장님 신고 2026-07-25).
       원본 _getDetailRowsSorted 는 전체내역(ctxCard='all', __CARD_ALL__)일 때 state.tab1Data
       를 소스로 써서 최초 렌더(_moumAllBaseRows)와 행 소스가 달랐다 → buildDetailTable 의
       usedCols 재계산으로 열이 변함. 전체내역 컨텍스트만 _moumAllBaseRows 로 바꾸고, 검색·별표·
       컬럼필터·정렬 꼬리는 원본과 동일하게 적용. 그 외 컨텍스트는 원본에 위임(카드 상세 정렬 유지). */
    var _origGDRS = window._getDetailRowsSorted;
    if (typeof _origGDRS === 'function' && !_origGDRS.__moumAllFix) {
      var patched = function () {
        var st = window.state || {};
        var ctx = st.currentDetailCardCtx || st.currentCardType || st.activeCardFilter || null;
        var isAllCtx = (st.currentDetailCode === '__CARD_ALL__') && (ctx === 'all' || !ctx);
        if (!isAllCtx || typeof _moumAllBaseRows !== 'function') {
          return _origGDRS.apply(this, arguments);
        }
        var rows = _moumAllBaseRows();
        /* 검색 필터 (원본과 동일 — searchInput1) */
        var si = document.getElementById('searchInput1');
        var q = si ? si.value.toLowerCase().trim() : '';
        if (q) {
          rows = rows.filter(function (r) {
            return Object.values(r).some(function (v) { return v != null && String(v).toLowerCase().indexOf(q) >= 0; });
          });
        }
        /* 별표만 보기 */
        if (st.memoStarFilterOn && window.__memoStars) {
          rows = rows.filter(function (r) {
            var rid = (r['마켓주문번호'] || '') + '::' + (r['옵션1'] || '');
            return window.__memoStars.has(rid);
          });
        }
        /* 컬럼별 값 필터 */
        var colFilters = st.detailColFilters || {};
        var activeCols = Object.keys(colFilters).filter(function (c) { return colFilters[c]; });
        if (activeCols.length > 0) {
          rows = rows.filter(function (r) {
            return activeCols.every(function (c) {
              var allowed = colFilters[c];
              var key = window._moumColFilterKey ? window._moumColFilterKey(r, c) : ((r[c] == null || r[c] === '') ? '(빈값)' : String(r[c]));
              return allowed.has(key);
            });
          });
        }
        /* 정렬 */
        if (st.detailSort && st.detailSort.col) {
          var sc = st.detailSort.col, sa = st.detailSort.asc;
          rows = rows.slice().sort(function (a, b) {
            var va = a[sc], vb = b[sc];
            if (va == null) va = ''; if (vb == null) vb = '';
            if (typeof va === 'number' && typeof vb === 'number') return sa ? va - vb : vb - va;
            return sa ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
          });
        }
        return rows;
      };
      patched.__moumAllFix = true;
      window._getDetailRowsSorted = patched;
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wireInline);
  } else {
    wireInline();
  }
})();
