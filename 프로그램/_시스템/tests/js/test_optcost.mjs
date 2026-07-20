// 실행: node 프로그램/_시스템/tests/js/test_optcost.mjs
// 파이썬 테스트와 별개(런너 불필요). 라이브 접속 없음 — 순수 로직·HTML 산출만 검사.
// toss.js 의 실제 optcost 블록을 그대로 떼어 Node 에서 실행 → 산출 HTML 검사.
// 데이터: 라이브 르무통_메이트에서 확인한 구조를 그대로 재현
//   (색 9 × 사이즈 14 = 126 / 107,700 르무통공홈 101개 / 113,500 무신사 1개 / 확인불가 24개).
import fs from 'fs';

import path from 'path';
import { fileURLToPath } from 'url';
const __d = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(__d, '..', '..', 'webapp', 'static', 'toss.js');
const all = fs.readFileSync(SRC, 'utf8').split('\n');
const s = all.findIndex(l => l.startsWith('const OC_PALETTE'));
const e = all.findIndex(l => l.startsWith('async function openPriceTplModal'));
const block = all.slice(s, e).join('\n');
console.log('떼어낸 코드 줄수:', e - s);

// ── 라이브에서 확인한 값 그대로 ──
const SIZES = ['220','225','230','235','240','245','250','255','260','265','270','275','280','290'];
const COLORS = ['블랙','다크네이비','올리브그린','그레이','아이보리','오렌지','스카이블루','크림핑크','라이트블루'];
const SHORT = new Set(['오렌지','스카이블루','크림핑크','라이트블루']);
const BIG = new Set(['260','265','270','275','280','290']);
const SRC_A = { source_name:'르무통 공홈', source_id:1, source_product_id:5, crawled_price:116900,
                final_purchase_price:107700, url_type:'색상모음전', last_fetched_at:'2026-07-19T10:41:26.6' };
const SRC_B = { source_name:'무신사', source_id:3, source_product_id:59, crawled_price:127900,
                final_purchase_price:113500, url_type:'색상모음전', last_fetched_at:'2026-07-19T10:41:26.6' };
const options = [];
let n = 0;
for (const c of COLORS) for (const sz of SIZES) {
  n++;
  const sku = 'SKU-' + n;
  let sources;
  if (c === '올리브그린' && sz === '265') {
    sources = [{ ...SRC_B, stock_out:false, stock_qty:1 },
               { ...SRC_A, stock_out:true, stock_qty:0 }];          // 공홈 품절 → 무신사로
  } else if (SHORT.has(c) && BIG.has(sz)) {
    sources = [];                                                    // 확인 불가
  } else {
    sources = [{ ...SRC_A, stock_out:false, stock_qty:(n % 800) + 2 },
               { ...SRC_B, stock_out:false, stock_qty:9 }];          // 최저가 = 공홈
  }
  options.push({ sku, color_display:c, size_display:sz, sources, template_purchase_price:95000 });
}

// ── 최소 브라우저 환경 ──
let captured = '';
const host = {
  set innerHTML(v) { captured = v; }, get innerHTML() { return captured; },
  querySelectorAll: () => [], querySelector: () => null,
};
globalThis.window = { BUNDLE_CODE:'르무통_메이트', DATA: { options } };
globalThis.document = {};
globalThis.fetch = async () => ({ json: async () => ({ ok:true, results:{
  g0:{ sale_price:116900, final_price:107700, steps:[
    {name:'리뷰적립금',type:'amount',value:5000,deduct:5000,base_after:111900,base_ratio:1},
    {name:'네이버페이 적립금',type:'rate',value:0.01,deduct:1119,base_after:110781,base_ratio:1},
    {name:'캐시백 (현대카드)',type:'rate',value:0.0273,deduct:3024,base_after:107757,base_ratio:1}]},
  g1:{ sale_price:127900, final_price:113500, steps:[
    {name:'후기 적립',type:'amount',value:500,deduct:500,base_after:127400,base_ratio:1},
    {name:'등급할인',type:'amount',value:5110,deduct:5110,base_after:122290,base_ratio:1},
    {name:'등급적립',type:'amount',value:4560,deduct:4560,base_after:117730,base_ratio:1},
    {name:'무신사머니 결제 적립',type:'amount',value:4170,deduct:4170,base_after:113560,base_ratio:1}]},
}}) });

const run = new Function(`${block}\nreturn { ptmRenderOptCost, ocBuildGroups, ocAxes, ocReceiptHtml, ocPickSource };`)();
const box = { querySelector: sel => (sel === '#ptm-optcost' ? host : null) };

await run.ptmRenderOptCost(box, 95000);

// ── 검사 ──
const BD = (await (await globalThis.fetch()).json()).results;
const RC0 = run.ocReceiptHtml(BD.g0);
const RC1 = run.ocReceiptHtml(BD.g1);
const cnt = (re) => (captured.match(re) || []).length;
const checks = [
  ['총 옵션 표기', /옵션 126개 → 가격 2종 · 확인 불가 24개/.test(captured)],
  ['판 = 사이즈 14줄', cnt(/<tr class="oc-row"/g) === 14],
  ['판 = 색상 9열(머리글)', cnt(/<th class="cv"/g) === 9],
  ['격자 칸 = 126', cnt(/<td class="oc-(c|uk)"/g) === 126],
  ['해당없음 칸 = 24 · 표기는 「-」', cnt(/<td class="oc-uk"[^>]*>-<\/td>/g) === 24],
  ['별표·물음표 없음', !/★/.test(captured) && !/>\?</.test(captured)],
  ['색 견본 없음(색상명만)', !/oc-sw/.test(captured)],
  ['색 이름 아래 가격 줄 존재', /oc-prow/.test(captured)],
  ['가격 줄 = 색마다 1칸(9칸)', cnt(/<tr class="oc-prow">[\s\S]*?<\/tr>/g) === 1
     && (captured.match(/<tr class="oc-prow">([\s\S]*?)<\/tr>/) || [,''])[1].match(/<td>/g).length === 9],
  ['섞인 색은 가격 2줄(올리브그린)', (captured.match(/<td>(<span class="p"[^>]*>[^<]*<\/span>){2}<\/td>/g) || []).length >= 1],
  ['확인불가 색은 「확인 불가」 표기', /<span class="p uk">확인 불가<\/span>/.test(captured)],
  ['경고 = 12,700~18,500원 쌉니다', /12,700~18,500원 쌉니다/.test(captured)],
  ['그룹 줄 = 2 + 확인불가 1', cnt(/<div class="oc-g[ "]/g) === 3],
  ['그룹1 = 107,700원 르무통 공홈', /107,700<i>원<\/i><\/span><span class="oc-src">르무통 공홈/.test(captured)],
  ['그룹2 = 113,500원 무신사', /113,500<i>원<\/i><\/span><span class="oc-src">무신사/.test(captured)],
  ['영수증 = 매트릭스와 같은 클래스', /class="cf-receipt"/.test(RC0)],
  ['영수증 최종매입가 107,700원', /최종 매입가<\/span><span class="num">107,700원/.test(RC0)],
  ['영수증 표면 노출가 116,900원', /표면 노출가<\/span><span class="num">116,900원/.test(RC0)],
  ['정률 단계 % 표기', /\(1\.00%\)/.test(RC0) && /\(2\.73%\)/.test(RC0)],
  ['베이스금액 ①② 표기', /베이스금액①/.test(RC0) && /베이스금액②/.test(RC0)],
  ['영수증 실패 시 거짓 표시 없음', /불러오지 못했어요/.test(run.ocReceiptHtml(null))],
  ['무신사 영수증 113,500원', /최종 매입가<\/span><span class="num">113,500원/.test(RC1)],
  ['품절 소싱처 배제(공홈 품절 → 무신사 채택)',
    run.ocPickSource({ sources:[{ ...SRC_A, stock_out:true, final_purchase_price:107700 },
                                { ...SRC_B, stock_out:false, final_purchase_price:113500 }] }).source_name === '무신사'],
  ['가격 없는 소싱처는 폴백 안 함',
    run.ocPickSource({ sources:[{ ...SRC_A, final_purchase_price:null }] }) === null],
  ['확인불가 칩 = 24', cnt(/class="oc-chip[ "]/g) === 24],
];
// 회귀: 모음전 컨텍스트 없는 「템플릿 관리」 경로 → 아무것도 안 그린다(빈칸 유지).
captured = '';
globalThis.window = { DATA: null };  // BUNDLE_CODE 없음 = 템플릿 관리 경로
const t0 = Date.now();
await run.ptmRenderOptCost(box, 95000);
checks.push(['컨텍스트 없으면 렌더 생략', captured === '']);
checks.push(['그때 즉시 종료(헛대기 없음)', Date.now() - t0 < 500]);
// 회귀: 평균 매입가가 실제와 같으면 경고를 띄우지 않는다.
captured = '';
globalThis.window = { BUNDLE_CODE:'x', DATA: { options: options.filter(o => o.sources.length && o.sources[0].final_purchase_price === 107700) } };
await run.ptmRenderOptCost(box, 107700);
checks.push(['어긋남 없으면 경고 없음', !/oc-alert/.test(captured) && /oc-mtx/.test(captured)]);

let bad = 0;
for (const [name, ok] of checks) { if (!ok) bad++; console.log((ok ? '  ✅ ' : '  ❌ ') + name); }
console.log(bad ? `\n실패 ${bad}건` : '\n전체 통과');
process.exit(bad ? 1 : 0);
