/* card_chain_harness.js — runs the ⚫블랙스팟 client card chain under node.
 *
 * WHY THIS EXISTS
 *   The blackspot-tab card numbers (전체현황/즉시확인/까대기/…) are computed entirely
 *   client-side by _getRowsByCardFilter* + keyword helpers in
 *   webapp/templates/orders/margin_embed.html. This harness holds BYTE-IDENTICAL
 *   copies of those functions (sliced from the page) so a python test can feed them a
 *   real analysisData and assert the exact counts.
 *
 * DRIFT PROTECTION
 *   Every block between `/* VERBATIM_BEGIN *​/` and `/* VERBATIM_END *​/` is asserted,
 *   by test_blackspot_card_numbers_golden.py, to still be a verbatim substring of the
 *   CURRENT margin_embed.html. If anyone edits one of these functions on the page, the
 *   guard fails loud and points at the drifted slice. (We use substring-containment
 *   rather than runtime brace-extraction because functions like _hasUnknownKoreanInMemo
 *   embed regex literals with literal braces `\{ \}`, which a naive brace counter would
 *   miscount — a real JS tokenizer would be needed and would itself risk false failures.)
 *
 * NON-VERBATIM GLUE (intentionally NOT guarded, documented inline):
 *   - global stubs (window/analysisData/userSettings/_excludedSet/date filters)
 *   - getFilteredData(): reduced to its `.matched`-producing slice. The card chain reads
 *     ONLY fd.matched; the page's full getFilteredData additionally recomputes summary via
 *     the MR module (irrelevant to counts). The `.matched` construction lines ARE guarded.
 *   - _getUnfulfilledUnmatchedRows(): trimmed to the count-relevant loop (field payload
 *     omitted — 주문미이행 needs only the row COUNT).
 *   - the report block at the bottom (prints one JSON object to stdout).
 *
 * USAGE:  node card_chain_harness.js <analysisData.json> <path/to/margin_rules.js>
 */
'use strict';
const fs = require('fs');

// ── globals the page provides (glue) ──────────────────────────────────────
global.window = global;                        // bare `window.*` + bare identifiers
const MR = require(process.argv[3]);           // margin_rules.js (also sets global.MR via root)
global.MR = MR;
global.dateFilterFrom = null;                  // fresh page: no date filter
global.dateFilterTo = null;
global._excludedSet = new Set();               // window._excludedSet (no manual exclusions)
global._editedCount = 0;
global.window.userSettings = {highMarginRate:40, highMarginAmount:5000, saleEff1:1000, marginEff1:100};

const analysisData = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
global.analysisData = analysisData;            // bare `analysisData` + window.analysisData

/* VERBATIM_BEGIN */
var KNOWN_MEMO_TOKENS = [
  '반품','교환','취소','환불','회수',
  '철회','완료','진행','접수','신청','요청','승인','거부',
  '입금','확인','검토','점검',
  '블랙스팟',
  '정산','예정','대기',
  '배송','발송','수취','구매','준비','확정',
  '주문','시도','됨','보냄','없음','있음','중',
  '재','미'
];
/* VERBATIM_END */

/* VERBATIM_BEGIN */
function _getCardKeywords() {
  var s = (window.analysisData && window.analysisData.summary && window.analysisData.summary._card_keywords) || null;
  if (s && typeof s === 'object') return s;
  /* analysisData 없을 때만 (분석 전 초기 상태) default */
  return {
    confirmed_blackspot: {memo: ['블랙'], mg: ['오류입고']},
    memo_settled:        {memo: ['입금','철회']},
    completed_memo_yes:  {memo: ['반품완료','취소완료','교환완료','교환']},
    normal:              {memo: ['정산완료']},
    kkadaegi:            {mg: ['해외현지배송중']},
    kkadaegi_sent:       {mg: ['현지배송완료']},  /* [모음전] 까대기 송장번호 전송 완료 */
    tracking_failed:     {mg: ['송장전송실패'], mk_sync: ['송장전송실패']},
    pending:             {mg: ['배송대기중']},
  };
}
function _kw(card, field) {
  var c = _getCardKeywords()[card];
  return (c && Array.isArray(c[field])) ? c[field] : [];
}
function _matchesAny(text, keywords) {
  if (!keywords || !keywords.length) return false;
  for (var i = 0; i < keywords.length; i++) {
    if (text.indexOf(keywords[i]) >= 0) return true;
  }
  return false;
}
/* VERBATIM_END */

/* VERBATIM_BEGIN */
function _hasUnknownKoreanInMemo(memoText, recipientName) {
  if (!memoText) return false;
  var s = String(memoText);
  s = s.replace(/https?:\/\/\S+/g, '');
  s = s.replace(/\d{2,4}[.\/\-]\d{1,2}[.\/\-]\d{1,2}/g, '');
  s = s.replace(/\d{1,2}:\d{2}(:\d{2})?/g, '');
  s = s.replace(/[a-zA-Z0-9_]+/g, '');
  s = s.replace(/[/\(\)\[\]\{\},\.\-\:\;@#%&*+=?!~'"]+/g, ' ');
  if (recipientName) s = s.split(String(recipientName)).join('');
  for (var i = 0; i < KNOWN_MEMO_TOKENS.length; i++) {
    s = s.split(KNOWN_MEMO_TOKENS[i]).join('');
  }
  // ★ 동적 학습된 사람 이름 (backend 가 _memo_dynamic_names 로 전달) 도 정상 토큰
  var dyn = (window.analysisData && window.analysisData.summary && window.analysisData.summary._memo_dynamic_names) || [];
  for (var j = 0; j < dyn.length; j++) {
    s = s.split(dyn[j]).join('');
  }
  return /[가-힣]{2,}/.test(s);
}
/* VERBATIM_END */

/* VERBATIM_BEGIN */
function _isExchangeRow(r, cardType) {
  if (!r) return false;
  cardType = cardType || 'completed_memo_yes';
  var combined = String(r['간단메모']||'') + ' '
               + String(r['더망고주문상태 (사용자 연동)']||'') + ' '
               + String(r['샵마인_주문상태']||'') + ' '
               + String(r['샵마인_샵마인주문상태']||'');
  /* 더망고 복합 라벨 ('반품/교환/취소') 통째 제거 — 단독 키워드만 검사 */
  var clean = combined.replace(/반품\/교환\/취소/g, '').replace(/반품·교환·취소/g, '');
  var subEx  = _kw(cardType, 'sub_ex');
  var subRtn = _kw(cardType, 'sub_rtn');
  /* ⚠️ 사용자가 비우면 그대로 빈 list — 매칭 X (의도 존중) */
  /* 교환 키워드 우선 (정산 받음) */
  for (var i = 0; i < subEx.length; i++) {
    if (clean.indexOf(subEx[i]) >= 0) return true;
  }
  /* 반품/취소 키워드 명시 매칭 */
  for (var j = 0; j < subRtn.length; j++) {
    if (clean.indexOf(subRtn[j]) >= 0) return false;
  }
  /* 기본: 반품/취소로 안전 분류 */
  return false;
}
function _splitRtnEx(cardType) {
  if (typeof _getRowsByCardFilter !== 'function') return null;
  var rows = _getRowsByCardFilter(cardType);
  var rtn = 0, ex = 0;
  rows.forEach(function(r){
    if (_isExchangeRow(r, cardType)) ex++;
    else rtn++;
  });
  return {rtn: rtn, ex: ex, total: rows.length};
}
/* VERBATIM_END */

/* VERBATIM_BEGIN */
function _isTrackingNormalRow(r) {
  if (!r) return false;
  var combined = String(r['더망고주문상태 (사용자 연동)']||'') + ' '
               + String(r['샵마인_주문상태']||'') + ' '
               + String(r['샵마인_샵마인주문상태']||'')
               + ' ' + String(r['간단메모']||'');
  /* '반품/교환/취소 완료' 같은 복합 라벨 통째 제거 — 단독 키워드만 */
  var clean = combined.replace(/반품\/교환\/취소/g, '').replace(/반품·교환·취소/g, '');
  var subN = _kw('tracking_failed', 'sub_normal');
  /* ⚠️ 사용자가 비우면 빈 list — 매칭 X (의도 존중) */
  for (var i = 0; i < subN.length; i++) {
    if (clean.indexOf(subN[i]) >= 0) return true;
  }
  return false;
}
function _splitTrackingNormalEtc(cardType) {
  if (typeof _getRowsByCardFilter !== 'function') return null;
  var rows = _getRowsByCardFilter(cardType);
  var nrm = 0, etc = 0;
  rows.forEach(function(r){
    if (_isTrackingNormalRow(r)) nrm++; else etc++;
  });
  return {normal: nrm, etc: etc, total: rows.length};
}
/* VERBATIM_END */

/* VERBATIM_BEGIN */
function _getSuspVirtualRows() {
  if (!analysisData) return [];
  if (analysisData._suspRowsCache) return analysisData._suspRowsCache;
  function _hasV3(v){ var s_ = String(v||'').trim(); return s_ && ['nan','0','0.0','None'].indexOf(s_) < 0; }
  var unmBuy = analysisData.unmatched_buy || [];
  var base = (analysisData.matched || []).length;  /* 가상 행 _idx 시작점 (matched 인덱스 다음) */
  var out = [];
  unmBuy.forEach(function(b){
    if (!_hasV3(b['사이트주문번호'])) return;
    /* 정산 0원 / 구매가 양수 → 마진율 -100% (역마진 = 이상마진 자동 분류) */
    var bp = parseFloat(String(b['구매가격'] || 0).replace(/,/g, '')) || 0;
    /* ★ 일별/월별/브랜드별/금액대별 그룹핑 키 — matched 행과 동일 파생 필드 (누락 방지) */
    var _od  = String(b['주문일'] || '').trim();
    var _ymd = _od.slice(0, 10);   /* 2026-05-19 */
    var _ym  = _od.slice(0, 7);    /* 2026-05 */
    out.push({
      '주문일':           b['주문일'] || '',
      '일자':             _ymd,
      '월':               _ym,
      '브랜드':           '기타',
      '금액대':           '기타',
      '마켓':             b['마켓명'] || '',
      '상품명':           b['상품명'] || '',
      '옵션_매출':        b['옵션'] || '',
      '옵션_매입':        b['옵션'] || '',
      '단가':             0,
      '판매가':           0,
      '실결제금액':       0,
      '정산예상금액':     0,
      '구매가격':         bp,
      '순마진':           -bp,        /* 손실 = -구매가 */
      '마진율':           bp > 0 ? -100 : 0,  /* 역마진 -100% */
      '수량_매출':        1,
      '수령인':           b['수령인'] || '',
      '상품코드':         '',
      '매칭타입':         '⚠️ 미매칭',
      '마켓주문번호':     b['마켓주문번호'] || '',
      '간단메모':         b['간단메모'] || '',
      '사이트주문번호':   b['사이트주문번호'] || '',
      '국내송장번호':     b['국내송장번호'] || '',
      '더망고주문상태 (사용자 연동)': b['더망고주문상태 (사용자 연동)'] || '',
      '마켓주문상태 (오픈 마켓 연동)': '',
      '수령인명':         b['수령인'] || '',
      '마켓상품명':       b['상품명'] || '',
      '샵마인_주문상태':  '⚠️ 샵마인 미동기화',
      '샵마인_샵마인주문상태': '',
      '대분류':           '4_매입X(블랙스팟의심)',
      '상세분류':         '1-3_블랙스팟의심',
      '확인사항':         '[문제] 매입 진행했으나 샵마인 미동기화 → 정산 확인 필요',
      '소싱처확인필요':   true,
      '마켓확인필요':     true,
      '데이터출처':       '더망고만',
      '_idx':             base + out.length,  /* ★ 전체 제외·행 체크박스용 고유 인덱스 */
      '_블랙스팟의심':    true,
    });
  });
  analysisData._suspRowsCache = out;
  return out;
}
/* VERBATIM_END */

/* NON-VERBATIM GLUE — trimmed to the count-relevant loop (주문미이행 needs COUNT only).
   Mirrors margin_embed.html:7985-8043 filter logic (unmatched_buy WITHOUT site order no). */
function _getUnfulfilledUnmatchedRows() {
  if (!analysisData) return [];
  function _hasV4(v){ var s_ = String(v||'').trim(); return s_ && ['nan','0','0.0','None'].indexOf(s_) < 0; }
  var unmBuy = analysisData.unmatched_buy || [];
  var out = [];
  unmBuy.forEach(function(b){
    if (_hasV4(b['사이트주문번호'])) return;   // 사이트번호 있음 → 블랙스팟 의심 (미이행 아님)
    out.push({'_주문미이행': true, '_매입흔적': false});
  });
  return out;
}
function _getUnfulfilledRows() {
  var m = (analysisData && analysisData.matched) || [];
  var matchedUnful = m.filter(function(r){ return r['_주문미이행'] && !r['_매입흔적']; });
  return matchedUnful.concat(_getUnfulfilledUnmatchedRows());
}

/* NON-VERBATIM GLUE — getFilteredData reduced to its `.matched` producer.
   The `.matched` construction below is guarded verbatim (margin_embed.html:1410-1420);
   the surrounding wrapper returns only {matched} because the card chain reads nothing else. */
function getFilteredData() {
  if (!analysisData) return null;
  var hasDateF = !!(dateFilterFrom || dateFilterTo);
  /* VERBATIM_BEGIN */
  var _susp = (typeof _getSuspVirtualRows === 'function') ? _getSuspVirtualRows() : [];
  var filtered = (analysisData.matched || []).filter(function(r) {
    if (hasDateF) {
      var d = parseDate26(r['주문일']);
      if (d) {
        if (dateFilterFrom && d < dateFilterFrom) return false;
        if (dateFilterTo   && d > dateFilterTo)   return false;
      }
    }
    return true;
  }).concat(_susp);
  /* VERBATIM_END */
  return { matched: filtered };
}

/* VERBATIM_BEGIN */
function _getRowsByCardFilter(type) {
  /* ★ 방안 A — matched 기반 (backend 와 100% 일치)
     ★ 사용자 명시 — 기간 필터 적용된 matched 사용 (모든 탭 일관성) */
  if (!analysisData || !analysisData.matched) return [];
  var fd = (typeof getFilteredData === 'function') ? getFilteredData() : null;
  var sourceMatched = (fd && fd.matched) || analysisData.matched;
  if (type === 'purchase_trace_only') {
    return sourceMatched.filter(function(r){
      return r['_주문미이행'] && r['_매입흔적'];
    });
  }
  var data = sourceMatched.filter(function(r){
    return !(r['_주문미이행'] && !r['_매입흔적']);
  });
  var rows = _getRowsByCardFilter_internal(data, type);

  /* ★ V4 — 1-3 블랙스팟 의심 흡수: unmatched_buy 中 사이트번호 있는 행을
     'all' 과 'mango_check' 카드에 가상 행으로 추가 (상세보기/세부보기 일관) */
  /* ★ V4 — 가상 행 16건은 getFilteredData().matched 에 이미 포함됨 (filtered.concat).
     별도 concat 제거 — 이중 카운트(16→32) 방지 */
  return rows;
}
/* VERBATIM_END */

/* VERBATIM_BEGIN */
function _getRowsByCardFilter_internal(data, type) {
  if (!type || type === 'all') {
    /* ★ 'all' 도 _force_card 가 있으면 그 카드로 강제 이동 — all 은 전체이므로 그냥 반환 */
    return data;
  }
  // ★ 백엔드 _compute_card_counts 와 100% 동일 로직 (단일 진실 원천)
  //   if/elif 우선순위 분류 — 각 행은 정확히 하나의 카드에만 속함 (margin 만 중첩)
  //   ★ 사용자 명시 — 이슈 엑셀 _force_card 가 있으면 그 카드로 강제 이동
  var PROGRESS_PATTERNS = ['회수지시','철회','진행중','취소진행','반품진행','교환진행','출고중지','반품접수','반품요청','교환신청','교환요청'];
  var DONE_RTN_PATTERNS = ['반품완료','취소완료','환불승인','회수완료','취소된거래','취소거부'];
  var DONE_NORMAL_PATTERNS = ['배송완료','수취완료','구매확정','정산완료','정산예정','발송완료','확정'];
  function smCat(s) {
    s = String(s || '').trim();
    if (!s) return 'normal';
    for (var i=0; i<PROGRESS_PATTERNS.length; i++) if (s.indexOf(PROGRESS_PATTERNS[i]) >= 0) return 'in_progress';
    for (var i=0; i<DONE_RTN_PATTERNS.length; i++) if (s.indexOf(DONE_RTN_PATTERNS[i]) >= 0) return 'done_rtn';
    for (var i=0; i<DONE_NORMAL_PATTERNS.length; i++) if (s.indexOf(DONE_NORMAL_PATTERNS[i]) >= 0) return 'done_normal';
    return 'normal';
  }
  /* 메모O 키워드 (사용자가 직접 처리 확인) */
  /* ⚠️ 정확한 종결 phrase 만 — 단독 '완료' 매칭 X (정산완료/배송완료 등 잘못 분류 방지) */
  var MEMO_DONE_KEYWORDS = ['반품완료','교환완료','취소완료','환불완료','환불승인','회수완료'];
  /* 메모 정산 종결 토큰 — 부분 매칭 ('입금', '철회' 포함) */
  var MEMO_SETTLED_TOKENS = ['입금','철회'];
  /* 더망고 일반 진행중 (반품/취소 흐름 아닌 정상 진행) */
  var MG_NORMAL_PROGRESS = ['국내배송중','배송준비중','배송대기중','배송지시','결제완료','신규주문','발송대기','상품준비'];
  return data.filter(function(r){
    /* ★ V4 — 가상 행 (1-3 블랙스팟 의심) 은 mango_check 카드 전용
       (메모·배송상태 키워드 분류로 immediate/pending 등에 흩어지는 것 방지) */
    if (r['_블랙스팟의심']) {
      return type === 'mango_check';
    }
    /* ★ 이슈 엑셀 _force_card 강제 이동 (다른 분류 무시) */
    if (r._force_card) {
      return r._force_card === type;
    }
    var detailCode = r['상세분류'] || '';
    var code = detailCode.split('_')[0];
    var needS = !!r['소싱처확인필요'];
    var needM = !!r['마켓확인필요'];
    var isMargin = (code === '1-2' || code === '1-3');
    var isNormalCode = (
      code === '1-1' || code === '3-1' || code === '3-2' || code === '4-1' ||
      code === '5-1' || code === '5-2' || code === '5-3' || detailCode.indexOf('정상') >= 0
    );
    var isPendingCode = (code === '1-11' || code === '2-9' || code === '3-9' || code === '4-9');
    var isKkadaegiCode = (code === '1-12' || code === '2-10' || code === '3-10' || code === '4-10');
    var sm = r['샵마인_주문상태'] || r['샵마인_샵마인주문상태'] || '';
    var smC = smCat(sm);
    var mg = String(r['더망고주문상태 (사용자 연동)'] || '');
    var mkSync = String(r['마켓주문상태 (오픈 마켓 연동)'] || '');
    var trackingFailed = (mkSync.indexOf('송장전송실패') >= 0) || (mg.indexOf('송장전송실패') >= 0);
    var mgInProgress = mg.indexOf('진행중') >= 0;
    var mgCompletedRtn = mg.indexOf('완료') >= 0 && (mg.indexOf('반품') >= 0 || mg.indexOf('교환') >= 0 || mg.indexOf('취소') >= 0);
    var mgNormalProgress = MG_NORMAL_PROGRESS.some(function(k){ return mg.indexOf(k) >= 0; });
    // 사이트주문번호 ↔ 송장 미스매치
    function _has(v) { var s_ = String(v||'').trim(); return s_ && ['nan','0','0.0','None'].indexOf(s_) < 0; }
    var hasSiteNo  = _has(r['사이트주문번호']);
    var hasTrackNo = _has(r['국내송장번호']);
    var siteTrackMismatch = (hasSiteNo && !hasTrackNo) || (!hasSiteNo && hasTrackNo);

    var memo = String(r['간단메모'] || '');
    /* ★ 사용자 편집 가능 키워드 (card_keywords.json — _getCardKeywords()) */
    var hasBlackspotMemo = _matchesAny(memo, _kw('confirmed_blackspot', 'memo'));
    var isMgBlackspot    = _matchesAny(mg, _kw('confirmed_blackspot', 'mg'));
    var hasSettledMemo   = _matchesAny(memo, _kw('memo_settled', 'memo'));
    var memoCompact1     = memo.replace(/\s+/g, '');
    var hasDoneMemo      = _matchesAny(memoCompact1, _kw('completed_memo_yes', 'memo'));
    var hasNormalMemo    = _matchesAny(memo, _kw('normal', 'memo'));
    var isMgKkadaegi     = _matchesAny(mg, _kw('kkadaegi', 'mg'));
    var _kwSent = _kw('kkadaegi_sent', 'mg'); if (!_kwSent.length) _kwSent = ['현지배송완료'];  /* [모음전] kkadaegi_sent 기본값 — 팀 DB 에 없으면 0건이 된다 */
    var isMgKkadaegiSent = _matchesAny(mg, _kwSent);  /* [모음전] kkadaegi_sent 판정 */
    var isMgPending      = _matchesAny(mg, _kw('pending', 'mg'));
    var isTrackingFailed = _matchesAny(mkSync, _kw('tracking_failed', 'mk_sync'))
                        || _matchesAny(mg, _kw('tracking_failed', 'mg'));

    // margin 만 중첩 카운트 (다른 카드와 동시 카운트됨)
    if (type === 'margin') return isMargin;
    // completed (legacy alias) — 메모O 카드 + 메모X 재확인 합집합
    if (type === 'completed') {
      if (hasBlackspotMemo || hasSettledMemo) return false;
      if (hasDoneMemo) return true;  // 메모O
      // 메모 X 케이스
      if (mg.indexOf('배송대기중') >= 0) return false;     // 발송 대기
      if (trackingFailed) return false;                    // 송장 재전송 실패 (별도 카드)
      if (siteTrackMismatch || (mgNormalProgress && (smC === 'in_progress' || smC === 'done_rtn'))) return false;
      if (mgCompletedRtn) return true;  // 메모X 재확인
      if (mgInProgress || smC === 'in_progress') return false;
      return smC === 'done_rtn';
    }

    // ★ 우선순위 분류 — 백엔드 _compute_card_counts 와 동일 (키워드 동적화)
    if (isMgKkadaegi)                                            return type === 'kkadaegi';
    if (hasBlackspotMemo || isMgBlackspot)                      return type === 'confirmed_blackspot';
    if (hasSettledMemo)                                         return type === 'memo_settled';
    /* ★ 송장전송실패 위로 이동 — 사용자: '무조건 송장 재전송 실패 카드로' */
    if (isTrackingFailed)                                       return type === 'tracking_failed';
    if (hasDoneMemo)                                            return type === 'completed_memo_yes';
    if (hasNormalMemo)                                          return type === 'normal';
    /* ★ 6순위 [확장]: mg=국내배송중 + sm 분기 (5.5 etc 분기 보다 위로 이동 — 명확한 mg/sm 우선) */
    if (mg.indexOf('국내배송중') >= 0 && (
        sm.indexOf('배송중') >= 0 || sm.indexOf('배송준비') >= 0 || sm.indexOf('발송대기') >= 0 || sm.indexOf('상품준비') >= 0
    ))                                                          return type === 'pending';
    if (mg.indexOf('국내배송중') >= 0 && (
        sm.indexOf('구매확정') >= 0 || sm.indexOf('수취완료') >= 0 || sm.indexOf('배송완료') >= 0 || sm.indexOf('확정') >= 0 || sm.indexOf('배송') >= 0
    ))                                                          return type === 'normal';
    if (isMgPending)                                             return type === 'pending';
    // ★ 8순위 [위로 이동]: 더망고=반품/교환/취소 완료 → 메모 phrase 일치 시 완료(메모O), 아니면 완료(메모X)
    //   ⚠️ site/track mismatch 보다 위 — 반품 시 송장 회수돼도 반품 카드로
    if (mgCompletedRtn) {
      if (hasDoneMemo)                                          return type === 'completed_memo_yes';
      return type === 'completed_memo_no';
    }
    // ★ 9순위 [위로 이동]: 진행중 — 더망고 우선 (메모 phrase 무관)
    //   ⚠️ site/track mismatch 보다 위
    if (mgInProgress || smC === 'in_progress')                  return type === 'inprogress';
    // ★ 10순위: site/track mismatch → 더망고 점검 (반품/진행중 분기 후로 이동)
    if (siteTrackMismatch)                                      return type === 'mango_check';
    // ★ 11순위: 상태 불일치
    if ((mgNormalProgress && (smC === 'in_progress' || smC === 'done_rtn')) ||
        ((mg.indexOf('국내배송') >= 0 || mg.indexOf('해외현지배송') >= 0) &&
         (sm.indexOf('발송대기') >= 0 || sm.indexOf('배송준비') >= 0)))
                                                                 return type === 'status_mismatch';
    // ★ 12순위: 샵마인 종결 → 메모X 재확인
    if (smC === 'done_rtn')                                     return type === 'completed_memo_no';
    // ★ 13순위: 일반 배송/수취 완료 → 정상/완료
    if (smC === 'done_normal')                                  return type === 'normal';
    if (isKkadaegiCode)                                          return type === 'kkadaegi';
    if (needS && needM)                                          return type === 'immediate';
    if (needS && !needM)                                         return type === 'sourcing';
    if (needM && !needS)                                         return type === 'market';
    if (isNormalCode)                                            return type === 'normal';
    if (isPendingCode)                                           return type === 'pending';
    if (isMgKkadaegiSent)                                        return type === 'kkadaegi_sent';  /* [모음전] 기타로 갈 뻔한 '현지배송완료'만 */
    /* ★ 마지막 분기: 메모 unknown korean → etc (위에서 이동) */
    if (_hasUnknownKoreanInMemo(memo, String(r['수령인']||'')))  return type === 'etc';
    /* Fallback — 진짜 미분류 → etc */
    return type === 'etc';
  });
}
/* VERBATIM_END */

/* VERBATIM_BEGIN */
function isHighMargin(marginRate, marginAmt) {
  return marginRate >= window.userSettings.highMarginRate
      && marginAmt  >= window.userSettings.highMarginAmount;
}
/* VERBATIM_END */

/* VERBATIM_BEGIN */
function isAbnormalMarginRow(r) {
  if (!r) return false;
  if (r['_주문미이행'] && !r['_매입흔적']) return false;  /* 주문미이행 only — 마진 왜곡 무시 */
  var rate = Number(r['마진율']) || 0;
  var amt  = Number(r['순마진']) || 0;
  /* 손실 = 순마진 기여<0 (정산0+매입有·키워드 블랙스팟·과다구매 등 모두 포함) 또는 고마진 */
  var contrib = (typeof MR !== 'undefined') ? MR.rowMargin(r) : amt;
  return contrib < 0 || isHighMargin(rate, amt);
}
/* VERBATIM_END */

/* 이상마진 배너 count — the banner's own filter (margin_embed.html:2099-2102), guarded. */
function _abnormalCount() {
  var rows = _getRowsByCardFilter('all');
  /* VERBATIM_BEGIN */
  var abn = (rows || []).filter(function(r){
    if (r['_주문미이행'] && !r['_매입흔적']) return false;
    return !r._excluded && !r['이상가'] && isAbnormalMarginRow(r);
  });
  /* VERBATIM_END */
  return abn.length;
}

// ── report block (glue) — one JSON object to stdout ────────────────────────
function cnt(card){ return _getRowsByCardFilter(card).length; }
const s = (analysisData.summary || {});
const traceCnt = (s.mango_with_trace) || cnt('all');

const result = {
  cards: {
    all: cnt('all'),
    immediate: cnt('immediate'),
    sourcing: cnt('sourcing'),
    market: cnt('market'),
    mango_check: cnt('mango_check'),
    status_mismatch: cnt('status_mismatch'),
    etc: cnt('etc'),
    normal: cnt('normal'),
    pending: cnt('pending'),
    kkadaegi: cnt('kkadaegi'),
    kkadaegi_sent: cnt('kkadaegi_sent'),   /* 2026-07-23 신설 — 더망고 '현지배송완료' */
    tracking_failed: cnt('tracking_failed'),
    confirmed_blackspot: cnt('confirmed_blackspot'),
    memo_settled: cnt('memo_settled'),
    inprogress: cnt('inprogress'),
    completed_memo_yes: cnt('completed_memo_yes'),
    completed_memo_no: cnt('completed_memo_no'),
    margin: cnt('margin'),
  },
  tracking_split: _splitTrackingNormalEtc('tracking_failed'),
  inprogress_split: _splitRtnEx('inprogress'),
  completed_memo_yes_split: _splitRtnEx('completed_memo_yes'),
  completed_memo_no_split: _splitRtnEx('completed_memo_no'),
  banner_trace: traceCnt,
  data_verify: {
    '1-1': s.mango_with_order_no,
    '1-2': (analysisData.unmatched_buy || []).filter(function(b){
        var s_ = String(b['사이트주문번호']||'').trim();
        return !(s_ && ['nan','0','0.0','None'].indexOf(s_) < 0);
      }).length,
    '1-3': _getSuspVirtualRows().length,
  },
  unfulfilled: _getUnfulfilledRows().length,
  abnormal_margin: _abnormalCount(),
};
process.stdout.write(JSON.stringify(result));
