/* margin_checksum.js — 「검산식」(전체 건수 = 모든 카드 합) · 시안 20 기여도 바 리스트
   ─────────────────────────────────────────────────────────────
   사장님 확정 2026-07-25: 시안 20(기여도 가로 막대) + 막대 클릭 → 그 카드 전체내역 펼침.

   ■ 무엇을 검산하나
     분류 로직(card_counts.py)은 주문 한 건을 정확히 한 카드에만 넣는다 →
     서로 안 겹치는 모든 카드의 합 = 전체 건수(ex.total)여야 한다.
     여기서 각 카드는 _getRowsByCardFilter(type).length 로 세고(화면 카드와 같은 원천),
     전체는 _getRowsByCardFilter('all').length 로 센다. 합 ≠ 전체면 차이를 빨간색으로
     정직하게 노출한다(사장님 결정 ③ — 차이 N건 빨간 노출).

   ■ 클릭
     막대를 누르면 window._goAllWithCardFilter(type, label) → 카드 아래(#detail-section)에
     그 카드 주문을 전체내역 양식으로 펼친다(margin_all_tab.js 와 같은 진입점).

   ■ 이 파일에 두는 이유: margin_embed.html 은 원본 씨앗(seam)만 바꿔 만드는 파일이라
     본문에 로직을 넣지 않는다(margin_kkadaegi_sent.js·margin_all_tab.js 와 같은 패턴).

   ■ 실마켓(API) 미매칭 카드도 여기서 정의(window._moumUnmatchedBuyCardHTML) — 더망고엔
     있으나 실마켓서 못 불러온 매입건(analysisData.unmatched_buy). 1,024 분류 밖이므로
     검산 합에는 넣지 않는다(넣으면 합이 전체보다 커진다). */
(function () {
  'use strict';

  /* 서로 안 겹치는 분류 카드 전체 (합 = 전체 건수). 라벨·색은 화면 카드와 맞춘다.
     status_mismatch 라벨은 '샵마인'→'실마켓' 개명 반영. */
  var CARDS = [
    { t: 'normal',             l: '정상/완료',                 c: '#22C55E' },
    { t: 'kkadaegi_sent',      l: '까대기 송장전송 완료',       c: '#0D9488' },
    { t: 'kkadaegi',           l: '까대기',                     c: '#14B8A6' },
    { t: 'pending',            l: '발송 대기',                  c: '#3B82F6' },
    { t: 'inprogress',         l: '반품/교환/취소 진행중',       c: '#A855F7' },
    { t: 'completed_memo_yes', l: '반품/교환/취소 완료(메모O)',  c: '#94A3B8' },
    { t: 'completed_memo_no',  l: '반품/교환/취소 완료(메모X)',  c: '#F59E0B' },
    { t: 'tracking_failed',    l: '송장 재전송 실패',           c: '#06B6D4' },
    { t: 'mango_check',        l: '더망고 상태 점검',           c: '#F59E0B' },
    { t: 'status_mismatch',    l: '상태 불일치 (실마켓↔더망고)', c: '#8B5CF6' },
    { t: 'immediate',          l: '즉시 확인',                  c: '#F43F5E' },
    { t: 'sourcing',           l: '소싱처 확인',                c: '#FB923C' },
    { t: 'market',             l: '마켓 확인',                  c: '#FBBF24' },
    { t: 'confirmed_blackspot',l: '확인된 블랙스팟',            c: '#EF4444' },
    { t: 'memo_settled',       l: '입금/철회 완료',             c: '#64748B' },
    { t: 'etc',                l: '기타',                       c: '#94A3B8' }
  ];

  function _count(type) {
    if (typeof window._getRowsByCardFilter !== 'function') return null;
    try { return window._getRowsByCardFilter(type).length; } catch (e) { return 0; }
  }
  function _fmt(n) {
    var f = (typeof window.fmt === 'function') ? window.fmt : null;
    if (f) return f(n);
    return Number(n).toLocaleString('ko-KR');
  }
  function _esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /* 검산식 본체 — ex 는 참고용(폴백). 실제 수치는 _getRowsByCardFilter 로 직접 센다. */
  window._moumChecksumHTML = function (ex) {
    if (typeof window._getRowsByCardFilter !== 'function') return '';
    var total = _count('all');
    if (!total) return '';  // 데이터 없으면 검산 숨김

    var items = CARDS.map(function (c) {
      return { t: c.t, l: c.l, c: c.c, v: _count(c.t) || 0 };
    });
    var sum = items.reduce(function (a, b) { return a + b.v; }, 0);
    var diff = total - sum;
    var nz = items.filter(function (i) { return i.v > 0; })
                  .sort(function (a, b) { return b.v - a.v; });
    var maxv = Math.max.apply(null, nz.map(function (i) { return i.v; }).concat([1]));

    var diffChip = (diff === 0)
      ? '<span style="display:inline-flex;align-items:center;gap:5px;background:#EAF7EF;color:#1AB053;border:1px solid #BEE9CE;border-radius:999px;padding:3px 12px;font-size:13px;font-weight:800">✔ 차이 0 · 전부 분류됨</span>'
      : '<span style="display:inline-flex;align-items:center;gap:5px;background:#FFF3F3;color:#dc2626;border:1px solid #FFD5D5;border-radius:999px;padding:3px 12px;font-size:13px;font-weight:800">⚠ 차이 ' + _fmt(Math.abs(diff)) + '건 · 확인 필요</span>';

    var rows = nz.map(function (i) {
      var pct = i.v / maxv * 100;
      return ''
        + '<div onclick="if(window._goAllWithCardFilter)window._goAllWithCardFilter(\'' + i.t + '\',\'' + _esc(i.l).replace(/'/g, '') + '\')" '
        +   'title="눌러서 이 카드의 전체내역 보기" '
        +   'style="display:flex;align-items:center;gap:10px;padding:5px 8px;border-radius:8px;cursor:pointer;transition:background .12s" '
        +   'onmouseover="this.style.background=\'#F2F4F6\'" onmouseout="this.style.background=\'transparent\'">'
        +   '<span style="width:172px;flex:none;color:#333D4B;font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + _esc(i.l) + '</span>'
        +   '<span style="flex:1;height:12px;background:#EEF1F4;border-radius:6px;overflow:hidden">'
        +     '<i style="display:block;height:100%;width:' + pct + '%;background:' + i.c + ';border-radius:6px"></i>'
        +   '</span>'
        +   '<span style="width:56px;flex:none;text-align:right;font-weight:700;font-variant-numeric:tabular-nums;font-feature-settings:\'tnum\'">' + _fmt(i.v) + '</span>'
        + '</div>';
    }).join('');

    var zeros = items.length - nz.length;
    var zeroLine = zeros > 0
      ? '<div style="display:flex;align-items:center;gap:10px;padding:3px 8px;color:#8B95A1;font-size:12px">'
        + '<span style="width:172px;flex:none">0건 ' + zeros + '종 (즉시·소싱·마켓 등)</span>'
        + '<span style="flex:1"></span>'
        + '<span style="width:56px;flex:none;text-align:right;font-variant-numeric:tabular-nums">0</span></div>'
      : '';

    return ''
      + '<div style="background:#fff;border:1px solid #E5E8EB;border-radius:14px;padding:16px 20px;margin:2px 0 12px 0">'
      +   '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">'
      +     '<span style="font-size:15px;font-weight:800;color:#191F28">🧮 분류 검산 — 전체 <span style="font-variant-numeric:tabular-nums">' + _fmt(total) + '</span>건이 모든 카드 합과 맞는지</span>'
      +     diffChip
      +   '</div>'
      +   '<div>' + rows + zeroLine + '</div>'
      +   '<div style="display:flex;align-items:center;justify-content:space-between;border-top:2px solid #191F28;margin-top:8px;padding-top:9px">'
      +     '<span style="font-weight:800;color:#191F28">카드 합계 / 전체 건수</span>'
      +     '<span style="font-weight:800;font-variant-numeric:tabular-nums;color:' + (diff ? '#dc2626' : '#1AB053') + '">' + _fmt(sum) + ' / ' + _fmt(total) + '</span>'
      +   '</div>'
      +   (diff ? '<div style="margin-top:8px;background:#FFF3F3;border:1px solid #FFD5D5;border-radius:8px;padding:8px 12px;color:#dc2626;font-size:12.5px;line-height:1.6">⚠️ 카드 어디에도 안 들어간 주문이 <b>' + _fmt(Math.abs(diff)) + '건</b> 있습니다. 분류 규칙에 빠진 상태가 있는지 확인이 필요합니다.</div>' : '')
      + '</div>';
  };

  /* ── 실마켓(API) 미매칭 카드 (사장님 요청 #1) ──
     더망고엔 있으나 실마켓(판매처 API)에서 못 불러온 매입건 = analysisData.unmatched_buy.
     화면 카드 부품(_summaryCardHTML)을 그대로 써서 모양을 맞춘다. 클릭 시 그 행들을
     전체내역 양식으로 펼치려고, _getRowsByCardFilter 를 감싸 'unmatched_buy' 를 처리한다. */
  function _unmatchedBuyRows() {
    return (window.analysisData && window.analysisData.unmatched_buy) || [];
  }

  window._moumUnmatchedBuyCardHTML = function () {
    var n = _unmatchedBuyRows().length;
    if (typeof window._summaryCardHTML === 'function') {
      // (type, count, label, color) — type 은 아래에서 감싼 _getRowsByCardFilter 가 처리
      return window._summaryCardHTML('unmatched_buy', n, '실마켓(API) 미매칭', 'red');
    }
    // 폴백 — _summaryCardHTML 이 없으면 최소 카드
    return '<div style="background:#fff;border:1px solid #FECACA;border-radius:12px;padding:14px;text-align:center">'
      + '<div style="font-size:26px;font-weight:800;color:#dc2626;font-variant-numeric:tabular-nums">' + _fmt(n) + '</div>'
      + '<div style="font-size:12px;color:#6b7280">실마켓(API) 미매칭</div></div>';
  };

  /* ── 프로그램(API) 미매칭 카드 (사장님 요청 2026-07-25) ──
     실마켓(판매처 API)엔 매출이 있으나 우리 프로그램(더망고 매입)에서 못 찾은 건 =
     analysisData.unmatched_sell. 실마켓(API) 미매칭(unmatched_buy)의 **거울** 카드다:
       · 실마켓(API) 미매칭 = 더망고 매입 O · 실마켓 매출 X  (실마켓서 못 찾음)
       · 프로그램(API) 미매칭 = 실마켓 매출 O · 더망고 매입 X (우리 프로그램서 못 찾음)
     → 마켓엔 팔렸는데 매입 기록이 없는 건(누락 매입·블랙스팟 후보)이라 눈에 띄게 표시. */
  function _unmatchedSellRows() {
    return (window.analysisData && window.analysisData.unmatched_sell) || [];
  }

  window._moumUnmatchedSellCardHTML = function () {
    var n = _unmatchedSellRows().length;
    if (typeof window._summaryCardHTML === 'function') {
      return window._summaryCardHTML('unmatched_sell', n, '프로그램(API) 미매칭', 'orange');
    }
    return '<div style="background:#fff;border:1px solid #FED7AA;border-radius:12px;padding:14px;text-align:center">'
      + '<div style="font-size:26px;font-weight:800;color:#C2410C;font-variant-numeric:tabular-nums">' + _fmt(n) + '</div>'
      + '<div style="font-size:12px;color:#6b7280">프로그램(API) 미매칭</div></div>';
  };

  /* _getRowsByCardFilter 를 감싸 'unmatched_buy'·'unmatched_sell' 을 지원(원본 함수는 인라인
     정의 → DOM 준비 후 감싼다). 다른 type 은 원본 그대로 위임. */
  function _wrapFilter() {
    var orig = window._getRowsByCardFilter;
    if (typeof orig !== 'function' || orig.__moumUB) return;
    var wrapped = function (type) {
      if (type === 'unmatched_buy') return _unmatchedBuyRows();
      if (type === 'unmatched_sell') return _unmatchedSellRows();
      return orig.apply(this, arguments);
    };
    wrapped.__moumUB = true;
    window._getRowsByCardFilter = wrapped;
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _wrapFilter);
  } else {
    _wrapFilter();
  }
})();
