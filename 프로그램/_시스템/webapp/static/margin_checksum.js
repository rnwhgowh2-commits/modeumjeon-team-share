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

  /* 매입흔적(전체) 中 실마켓서 못 찾은 미매칭 행 = 데이터출처 '더망고만'.
     (총 = 매칭 + 미매칭 이 항상 성립하도록 매칭은 나머지로 계산한다.) */
  function _mangoOnlyRows() {
    if (typeof window._getRowsByCardFilter !== 'function') return [];
    var all = window._getRowsByCardFilter('all') || [];
    return all.filter(function (r) {
      return String((r && r['데이터출처']) || '').indexOf('더망고만') === 0;
    });
  }

  /* 검산 요약(가로 3분할) — 사장님 확정 2026-07-25(v3 시안 1).
     최상단(가로탭 아래·이상마진 위)에 총 / 매칭(%) / 미매칭 + 바로가기. 폰트 200%.
     복잡한 11개 막대 대신 단순 3분할(사장님 지시). ex 인자는 안 씀(직접 센다). */
  window._moumChecksumHTML = function (ex) {
    if (typeof window._getRowsByCardFilter !== 'function') return '';
    var all = window._getRowsByCardFilter('all') || [];
    var total = all.length;
    if (!total) return '';                 // 데이터 없으면 숨김
    var unm = _mangoOnlyRows().length;     // 미매칭 = 매입 O · 실마켓 X
    var match = total - unm;               // 매칭 = 나머지 (총=매칭+미매칭 보장)
    var pctv = match / total * 100;
    var pct = (pctv % 1 === 0) ? pctv.toFixed(0) : pctv.toFixed(1);

    var goBtn = '<button onclick="if(window._goAllWithCardFilter)window._goAllWithCardFilter(\'moum_mango_only\',\'미매칭 (실마켓서 못 찾음)\')" '
      + 'style="margin-top:14px;display:inline-flex;align-items:center;gap:8px;background:#B45309;color:#fff;border:0;border-radius:10px;padding:12px 22px;font-size:20px;font-weight:800;cursor:pointer;font-family:inherit;white-space:nowrap">미매칭 건 보기 →</button>';

    return ''
      + '<div style="margin:0 0 14px 0;background:#fff;border:1px solid #E5E8EB;border-top:5px solid #22C55E;border-radius:16px;box-shadow:0 8px 24px rgba(16,24,40,.10);padding:26px 32px">'
      +   '<div style="display:grid;grid-template-columns:1fr 1fr 1.15fr;align-items:center">'
      +     '<div style="text-align:center;padding:6px 20px">'
      +       '<div style="font-size:24px;color:#6b7684;font-weight:700;margin-bottom:6px">총 건수</div>'
      +       '<div style="font-size:56px;font-weight:800;letter-spacing:-2px;font-variant-numeric:tabular-nums;font-feature-settings:\'tnum\'">' + _fmt(total) + '<span style="font-size:26px;color:#8B95A1;font-weight:700;margin-left:4px">건</span></div></div>'
      +     '<div style="text-align:center;padding:6px 20px;border-left:2px solid #E5E8EB;border-right:2px solid #E5E8EB">'
      +       '<div style="font-size:24px;color:#6b7684;font-weight:700;margin-bottom:6px">매칭 수</div>'
      +       '<div style="font-size:56px;font-weight:800;letter-spacing:-2px;color:#1AB053;font-variant-numeric:tabular-nums;font-feature-settings:\'tnum\'">' + _fmt(match) + '<span style="font-size:26px;color:#1AB053;opacity:.7;font-weight:700;margin-left:6px">건 · ' + pct + '%</span></div></div>'
      +     '<div style="text-align:center;padding:6px 20px">'
      +       '<div style="font-size:24px;color:#6b7684;font-weight:700;margin-bottom:6px">미매칭 수</div>'
      +       '<div style="font-size:56px;font-weight:800;letter-spacing:-2px;color:#D97706;font-variant-numeric:tabular-nums;font-feature-settings:\'tnum\'">' + _fmt(unm) + '<span style="font-size:26px;color:#D97706;opacity:.8;font-weight:700;margin-left:4px">건</span></div>'
      +       goBtn + '</div>'
      +   '</div>'
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

  /* ② '매입 흔적만'(데이터검증 배너 1-2) 카드 클릭 시 펼칠 행.
     ★배너 traceOnly 카운트(margin_embed.html renderDataVerifyBanner)와 100% 같은 기준이어야
       숫자와 목록이 일치한다 → 기간필터 안 쓴 analysisData.matched **전체** + _hasV 동치 복제.
       조건: 사이트주문번호 없음 AND NOT(주문미이행 only). */
  function _traceHasV(v) {
    var s = String(v || '').trim();
    return s && ['nan', '0', '0.0', 'None'].indexOf(s) < 0;
  }
  function _traceOnlyRows() {
    var src = (window.analysisData && window.analysisData.matched) || [];
    return src.filter(function (r) {
      return !_traceHasV(r['사이트주문번호']) && !(r['_주문미이행'] && !r['_매입흔적']);
    });
  }
  /* 카드 클릭 핸들러 — _showCardAllRows('trace_only') 가 #detail-section(카드 바로 아래)에
     buildDetailTable 로 펼치고 스크롤까지 한다(다른 블랙스팟 카드와 동일 UX). */
  window._moumTraceOnlyClick = function () {
    if (typeof window._showCardAllRows === 'function') window._showCardAllRows('trace_only');
  };

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
      if (type === 'moum_mango_only') return _mangoOnlyRows();  /* 검산 요약 '미매칭 건 보기' */
      if (type === 'trace_only') return _traceOnlyRows();        /* ② 블랙스팟 '매입 흔적만' 카드 클릭 내역 */
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

/* ── 1-3 「블랙스팟 의심」 박스 클릭 → 그 건 상세 (사장님 요청 2026-07-30) ──
   무엇인가: 더망고에 매입 흔적(사이트주문번호)이 있는데 실마켓(API)에서 못 찾은 건.
   배너의 1-3 숫자(unmWithSite)와 **같은 기준**으로 골라야 숫자와 목록이 어긋나지 않는다
   → analysisData.unmatched_buy 中 사이트주문번호가 있는 행. */
(function () {
  'use strict';

  function _hasV(v) {
    var s = String(v == null ? '' : v).trim();
    return !!s && s !== 'nan' && s !== 'None' && s !== '-';
  }

  function suspectRows() {
    return ((window.analysisData && window.analysisData.unmatched_buy) || [])
      .filter(function (r) { return _hasV(r && r['사이트주문번호']); });
  }

  window._moumSuspectClick = function () {
    var rows = suspectRows();
    if (!rows.length) {
      alert('블랙스팟 의심 건이 없습니다.');
      return;
    }
    /* 전체내역과 같은 렌더러로 펼친다(카드 상세와 동일 양식) */
    if (typeof window.buildDetailTable === 'function') {
      if (window.state) {
        window.state.currentDetailCode = '__CARD_ALL__';
        window.state.currentDetailCardCtx = 'blackspot_suspect';
        window.state.currentDetailSubFilter = null;
      }
      window.buildDetailTable('__CARD_ALL__', rows, 'blackspot_suspect');
      setTimeout(function () {
        var ds = document.getElementById('detail-section');
        if (ds) window.scrollTo(0, Math.max(0, ds.getBoundingClientRect().top + window.scrollY - 80));
      }, 200);
      return;
    }
    if (typeof window._goAllWithCardFilter === 'function') {
      window._goAllWithCardFilter('blackspot_suspect', '블랙스팟 의심');
    }
  };

  /* _getRowsByCardFilter 도 이 타입을 알게 감싼다(다른 진입점에서 불려도 같은 행). */
  function _wrap() {
    var orig = window._getRowsByCardFilter;
    if (typeof orig !== 'function' || orig.__moumSuspect) return;
    var wrapped = function (type) {
      if (type === 'blackspot_suspect') return suspectRows();
      return orig.apply(this, arguments);
    };
    wrapped.__moumSuspect = true;
    window._getRowsByCardFilter = wrapped;
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _wrap);
  } else {
    _wrap();
  }
})();
