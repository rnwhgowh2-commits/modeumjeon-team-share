/* margin_rules.js — 마진 집계 단일 진실 원천 (정산0/매입0 규칙)
   브라우저: window.MR  /  Node: module.exports
   ⚠️ 규칙은 이 파일에만 정의한다. index.html 인라인에 (정산0||매입0) 재작성 금지. */
(function (root) {
  'use strict';
  function num(v){ var n = Number(String(v).replace(/,/g,'')); return isFinite(n) ? n : 0; }
  // 취소완료·반품완료 확정 — 서버(sell_source._settlement_for)는 **우리 마켓 API 상태**가
  // 취소완료일 때만 정산을 0으로 강제한다. 그런데 사용자가 직접 쓰는 더망고(발송관리)의
  // 확정 상태가 마켓 API 재수집보다 먼저 들어오는 경우가 있어(2026-08-25 라이브 실측:
  // 더망고=반품/교환/취소완료인데 마켓 재수집 지연으로 정산예상금액이 취소 전 값 그대로 —
  // 106건, 유령매출 1,628만원·유령마진 1,419만원), 그 사이 정산이 취소 전 값 그대로 남아
  // 매출·마진에 얹힌다. 더망고·마켓 상태 둘 중 하나라도 최종 취소/반품 확정이면 정산을
  // 신뢰하지 않고 0 으로 본다(거래 무산 = 정산·수수료 없음, 서버 규약과 동일).
  function isFinalCancelStatus(r){
    if (!r) return false;
    var pat = /취소완료|반품완료/;
    var mg  = String(r['더망고주문상태 (사용자 연동)'] || '');
    var mkt = String(r['마켓주문상태 (오픈 마켓 연동)'] || '');
    return pat.test(mg) || pat.test(mkt);
  }
  function settle(r){ return isFinalCancelStatus(r) ? 0 : num(r && r['정산예상금액']); }
  function buy(r){ return num(r && r['구매가격']); }

  function isKeywordBlackspot(r){
    if (!r) return false;
    var memo = String(r['간단메모'] || '');
    var mg   = String(r['더망고주문상태 (사용자 연동)'] || '');
    var kw   = root._MR_BLACKSPOT_KW || { memo:['블랙'], mg:['오류입고'] };
    for (var i=0;i<kw.memo.length;i++) if (memo.indexOf(kw.memo[i]) >= 0) return true;
    for (var j=0;j<kw.mg.length;j++)   if (mg.indexOf(kw.mg[j])   >= 0) return true;
    return false;
  }
  function isExcludedLike(r){
    if (!r) return true;
    if (r._excluded) return true;
    if (r['_주문미이행'] && !r['_매입흔적']) return true;
    return false;
  }
  function isLossRow(r){
    if (!r || isExcludedLike(r)) return false;
    // ★ 사용자 규칙(2026-06-29): 제외된 행만 집계 제외, 그 외는 정산-매입 반영.
    //   정산이 실제로 잡힌 행(원래 있었든 수동 입력했든)은 손실 특례(-매입) 대상 아님 →
    //   블랙스팟/오류입고 키워드보다 우선해 정산-매입으로 집계. (손실 판정은 정산0일 때만)
    if (settle(r) > 0) return false;
    if (isKeywordBlackspot(r)) return true;   // 정산0 + 블랙스팟/오류입고 키워드
    return buy(r) > 0;                          // 정산0 + 매입>0
  }
  function isHighMarginRow(r){
    if (!r || isExcludedLike(r) || isLossRow(r)) return false;
    return settle(r) > 0 && buy(r) === 0;
  }
  function isMarginUncomputable(r){
    if (!r || isExcludedLike(r)) return false;
    if (isLossRow(r)) return false;
    return settle(r) === 0 && buy(r) === 0;
  }
  function classify(r){
    if (!r) return 'none';
    if (r._excluded) return 'excluded';
    if (r['_주문미이행'] && !r['_매입흔적']) return 'unfulfilled';
    if (isLossRow(r)) return 'loss';
    if (isMarginUncomputable(r)) return 'uncomputable';
    if (isHighMarginRow(r)) return 'highmargin';
    return 'normal';
  }

  // 매출 기여: 손실행 0, 그 외 saleAmtFn(r) (없으면 판매가)
  function rowSale(r, saleAmtFn){
    if (isLossRow(r)) return 0;
    return num(saleAmtFn ? saleAmtFn(r) : (r && r['판매가']));
  }
  // 순마진 기여: 손실행 -매입, 그 외 정산-매입
  function rowMargin(r){
    if (isLossRow(r)) return -buy(r);
    return settle(r) - buy(r);
  }

  // rows 집계 — 요약 단일 진실 원천. opts.saleAmt = function(r) (판매가 계산기)
  function summarize(rows, opts){
    opts = opts || {};
    var s = { 총매출:0, 총정산:0, 총매입:0, 총순마진:0, 매출건수:0, 매입건수:0,
              정상:0, 고마진:0, 의심손실:0, 계산불가:0 };
    (rows || []).forEach(function(r){
      var c = classify(r);
      if (c === 'excluded' || c === 'unfulfilled' || c === 'none') return;
      if (c === 'uncomputable') { s.계산불가++; return; }
      var sale    = rowSale(r, opts.saleAmt);
      var margin  = rowMargin(r);
      var settled = isLossRow(r) ? 0 : settle(r);
      s.총매출 += sale; s.총정산 += settled; s.총매입 += buy(r); s.총순마진 += margin;
      s.매입건수++;
      if (sale > 0) s.매출건수++;
      if (c === 'loss') s.의심손실++;
      else if (c === 'highmargin') s.고마진++;
      else s.정상++;
    });
    s.이상마진 = s.고마진 + s.의심손실;
    s.마진율 = s.총매출 > 0 ? (s.총순마진 / s.총매출 * 100) : 0;
    return s;
  }

  var api = { num, settle, buy, isFinalCancelStatus, isKeywordBlackspot, isLossRow, isHighMarginRow,
              isMarginUncomputable, classify, rowSale, rowMargin, summarize };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.MR = api;
})(typeof window !== 'undefined' ? window : globalThis);
