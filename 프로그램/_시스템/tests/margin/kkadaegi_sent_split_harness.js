/* 세 칸 분류가 겹치지 않고 합이 맞는지 — 실제 파일을 실행해 확인 */
const fs=require('fs');
const src=fs.readFileSync('webapp/static/margin_kkadaegi_sent.js','utf8');
global.window={};
global.fmt=n=>String(n);
global._summaryCardHTML=()=>'<button onclick="event.stopPropagation();showCardBreakdown';
const ROWS=[
 {'샵마인_주문상태':'배송완료','국내송장번호':'123'},
 {'샵마인_주문상태':'구매확정','국내송장번호':''},
 {'샵마인_주문상태':'수취완료','국내송장번호':'9'},
 {'샵마인_주문상태':'구매결정','국내송장번호':''},
 {'샵마인_주문상태':'수취확인후주문취소','국내송장번호':'5'},   /* 취소 → 배송완료 아님 */
 {'샵마인_주문상태':'배송중','국내송장번호':'777'},             /* 송장 있음 */
 {'샵마인_주문상태':'배송중','국내송장번호':''},                /* 미입력 */
 {'샵마인_주문상태':'','국내송장번호':'nan'},                   /* nan = 없음 */
];
global._getRowsByCardFilter=()=>ROWS;
eval(src);
const s=window._splitSentInvoice();
console.log('배송중/구매확정   :', s.done, '(기대 6 — 배송중 2건 포함)');
console.log('송장 입력 완료   :', s.sent, '(기대 1 — 취소건만)');
console.log('송장 미입력      :', s.none, '(기대 1)');
console.log('세 칸 합 = 전체  :', s.done+s.sent+s.none === s.total ? 'OK ('+s.total+')' : '★불일치');
const bar=window._kkadaegiSentCardHTML(8);
console.log('칸 순서          :', [...bar.matchAll(/keep-all">([^<]+)</g)].map(m=>m[1]).join(' | '));
console.log('3칸 그리드       :', /1fr 1fr 1fr/.test(bar)?'OK':'★없음');
