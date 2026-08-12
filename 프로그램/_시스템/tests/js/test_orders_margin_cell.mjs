// 실행: node 프로그램/_시스템/tests/js/test_orders_margin_cell.mjs
//
// 노션 주문관리 b-3 — 「실마진(정산예정금액(배송비포함) − 매입금액) 계산 열.
//   정산예정금액이 추정이면 '추정' 딱지(추정 사유·근거 호버) / 매입금액 없으면 '매입가 없음'」
//
// 🔴 왜 문자열 검사로는 부족한가 — 코드에 '추정' 이라는 글자가 있는지 보는 것만으로는
//   **언제** 그 딱지가 붙는지 못 잰다. 그래서 템플릿의 **진짜 원문**(marginCell ·
//   mgBuy · mgSettleSrc · marginFilterKey)을 떼어 Node 에서 돌리고 실제 HTML 을 만든다.
//   마지막에 **뮤테이션**(「매입가 없으면 0으로 계산」하는 옛날식 코드로 되돌림)으로
//   이 시험이 진짜 잡는지 실증한다. (선례: test_orders_purchase_filter.mjs)
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __d = path.dirname(fileURLToPath(import.meta.url));
const TPL = path.join(__d, '..', '..', 'webapp', 'templates', 'orders', 'index.html');
const SRC = fs.readFileSync(TPL, 'utf8').replace(/\r\n/g, '\n');

let fails = 0;
const ok = (cond, msg) => { if (!cond) { console.error('❌', msg); fails += 1; } else { console.log('  ✅', msg); } };

/** `function 이름(...) { … }` 원문을 중괄호 짝으로 떼어 온다. 사라지면 즉사(베껴 쓰기 금지). */
function extract(name, src = SRC) {
  const m = new RegExp('^\\s*function\\s+' + name + '\\s*\\(', 'm').exec(src);
  if (!m) throw new Error(`${name}() 이(가) orders/index.html 에 없습니다 — 배선이 사라졌습니다`);
  const i = src.indexOf('{', m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j += 1) {
    if (src[j] === '{') depth += 1;
    else if (src[j] === '}') { depth -= 1; if (depth === 0) return src.slice(m.index, j + 1); }
  }
  throw new Error(`${name}() 의 중괄호 짝이 안 맞습니다`);
}

/** `var 이름 = { … };` 처럼 여러 줄에 걸친 정의를 중괄호 짝으로 떼어 온다. */
function objDef(name, src = SRC) {
  const m = new RegExp('^\\s*var\\s+' + name + '\\s*=\\s*\\{', 'm').exec(src);
  if (!m) throw new Error(`${name} 정의가 orders/index.html 에 없습니다`);
  const i = src.indexOf('{', m.index);
  let depth = 0;
  for (let j = i; j < src.length; j += 1) {
    if (src[j] === '{') depth += 1;
    else if (src[j] === '}') { depth -= 1; if (depth === 0) return `${src.slice(m.index, j + 1)};`; }
  }
  throw new Error(`${name} 의 중괄호 짝이 안 맞습니다`);
}

function line(startsWith, src = SRC) {
  const hit = src.split('\n').find((l) => l.trimStart().startsWith(startsWith));
  if (!hit) throw new Error(`정의를 못 찾음: ${startsWith}`);
  return hit;
}

function build(src) {
  return `
    var ppMap = env.ppMap;
    function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
    ${line('function num(v){', src)}
    ${line('var PP_TAG=', src)}
    ${extract('ppUid', src)}
    ${extract('ppOf', src)}
    ${extract('ppWon', src)}
    ${objDef('SETTLE_SRC', src)}
    ${extract('mgSettleSrc', src)}
    ${extract('mgBuy', src)}
    ${extract('marginCell', src)}
    ${extract('marginFilterKey', src)}
    return { marginCell: marginCell, marginFilterKey: marginFilterKey };
  `;
}

const row = (uid, settle, src) => ({
  _line_uid: uid, '정산예정금(배송비포함)': settle, _settle_source: src,
});

// 라이브를 축소한 표.
//  a 실측 정산 + 실매입가        → 깔끔한 실마진, 딱지 없음
//  b 추정 정산 + 실매입가        → 「추정」 딱지
//  c 실측 정산 + 매입가 없음     → 「매입가 없음」 (0 으로 계산 금지)
//  d 실측 정산 + 예상 매입가     → 계산하되 「매입 예상」 딱지
//  e 정산액 없음(none) + 실매입가 → 「정산액 없음」
//  f 실측 정산 + 실매입가, 역마진 → 마이너스 표시
const rows = [
  row('a', 100000, 'real'),
  row('b', 100000, 'estimated'),
  row('c', 100000, 'real'),
  row('d', 100000, 'real'),
  row('e', '', 'none'),
  row('f', 30000, 'real'),
];
const ppMap = {
  a: { price: 60000, tier: 'real' },
  b: { price: 60000, tier: 'real' },
  // c 는 일부러 없음
  d: { price: 60000, tier: 'estimate' },
  e: { price: 60000, tier: 'real' },
  f: { price: 50000, tier: 'real' },
};

// eslint-disable-next-line no-new-func
const api = new Function('env', build(SRC))({ ppMap });
const cell = (i) => api.marginCell(rows[i]);

console.log('실마진 칸 — 재료의 출처를 숨기지 않는다:\n');

// ── ① 실측끼리면 숫자만, 군더더기 딱지 없음 ──
const A = cell(0);
ok(A.includes('40,000'), `실측 정산 100,000 − 실매입가 60,000 = 40,000 — 실제: ${A}`);
// 🔴 호버 문구에도 「추정 아님」처럼 그 글자가 들어간다 — **딱지(mg-chip)** 만 봐야 한다.
ok(!/mg-chip/.test(A), `정산이 실측·매입가가 실매입가면 딱지가 하나도 안 붙는다 — 실제: ${A}`);
ok(/title="[^"]*추정 아님/.test(A), '대신 호버로 「실측이다」를 밝힌다');

// ── ② 정산이 추정이면 「추정」 딱지 + 사유·근거 호버 ──
const B = cell(1);
ok(B.includes('40,000'), '추정이어도 계산은 한다(숫자를 감추지 않는다)');
ok(/mg-chip[^>]*mg-est[^>]*>추정</.test(B), `정산이 추정이면 「추정」 딱지가 붙는다 — 실제: ${B}`);
ok(/title="[^"]*규칙으로 계산[^"]*"/.test(B),
   '「추정」 칸에 마우스를 올리면 **왜** 추정인지(근거)가 뜬다');
ok(/title="[^"]*정산예정금\(배송비포함\)[^"]*매입가[^"]*"/.test(B),
   '호버에 계산식(정산액 − 매입가)이 그대로 적혀 있다');

// ── ③ 매입가가 없으면 **계산하지 않는다** — 0 으로 채우면 정산액 전액이 마진이 된다 ──
const C = cell(2);
ok(C.includes('매입가 없음'), `매입가가 없으면 「매입가 없음」 — 실제: ${C}`);
ok(!C.includes('100,000'),
   '🔴 매입가를 0 으로 보고 정산액 전액(100,000)을 마진으로 찍지 않는다');
ok(/title="[^"]*매입가/.test(C), '「매입가 없음」에도 무엇을 하면 되는지 안내가 붙는다');

// ── ④ 매입가가 우리 계산값이면 그 사실을 딱지로 밝힌다 ──
const D = cell(3);
ok(D.includes('40,000'), '예상 매입가로도 계산은 한다');
ok(/mg-chip[^>]*mg-buy[^>]*>매입 예상</.test(D),
   `매입가가 예상이면 「매입 예상」 딱지가 붙는다 — 실제: ${D}`);

// ── ⑤ 정산액 자체가 없으면 마진을 지어내지 않는다 ──
const E = cell(4);
ok(E.includes('정산액 없음'), `정산액이 없으면 「정산액 없음」 — 실제: ${E}`);
ok(!/[1-9]/.test(E.replace(/[^0-9]/g, '')) || !E.includes('60,000'),
   '매입가만 있다고 마이너스 마진(−60,000)을 지어내지 않는다');

// ── ⑥ 역마진은 눈에 띄게 ──
const F = cell(5);
ok(F.includes('mg-neg'), `역마진 줄엔 mg-neg 가 붙는다 — 실제: ${F}`);
ok(F.includes('−20,000'), `30,000 − 50,000 = −20,000 — 실제: ${F}`);

// ── ⑦ 헤더 필터가 ppMap 을 본다(「(빈값) 전부」 로 뭉개지지 않는다) ──
const cnt = {};
rows.forEach((r) => { const k = api.marginFilterKey(r); cnt[k] = (cnt[k] || 0) + 1; });
const keys = Object.keys(cnt).sort();
ok(keys.length >= 4, `필터 목록이 여러 묶음으로 갈린다 — 실제: ${keys.length}종 [${keys}]`);
ok(cnt['매입가 없음'] === 1, `「매입가 없음」 1줄(c) — 실제: ${cnt['매입가 없음']}`);
ok(cnt['정산액 추정'] === 1, `「정산액 추정」 1줄(b) — 실제: ${cnt['정산액 추정']}`);
ok(cnt['마이너스'] === 1, `「마이너스」 1줄(f) — 실제: ${cnt['마이너스']}`);
ok(cnt['마진 남음'] === 2, `「마진 남음」 2줄(a·d) — 실제: ${cnt['마진 남음']}`);

// ══════════════════════════════════════════════════════════════════
//  ⑧ 뮤테이션 — 「매입가가 없으면 0으로 보고 그냥 뺀다」는 옛날식 코드로 되돌리면
//     이 시험이 **반드시** 깨져야 한다. 안 깨지면 아무것도 안 보는 시험이다.
//     (feedback_test_that_tests_nothing)
// ══════════════════════════════════════════════════════════════════
const NAIVE = `function marginCell(r){
      var settle=num(r['정산예정금(배송비포함)']);
      var d=ppOf(r); var buy=(d&&d.price!=null)?Number(d.price):0;
      var m=settle-buy;
      return '<span class="mg-val'+(m<0?' mg-neg':'')+'">'+(m<0?'−'+ppWon(Math.abs(m)):ppWon(m))+'</span>';
    }`;
const mutated = SRC.replace(extract('marginCell'), NAIVE);
if (mutated === SRC) throw new Error('뮤테이션이 marginCell 을 못 바꿨습니다 — 시험이 무효입니다');
// eslint-disable-next-line no-new-func
const mapi = new Function('env', build(mutated))({ ppMap });
const mC = mapi.marginCell(rows[2]);
const mB = mapi.marginCell(rows[1]);
ok(mC.includes('100,000') && !mC.includes('매입가 없음'),
   '[뮤테이션] 옛 코드는 매입가 없는 줄을 100,000 마진으로 찍는다 — 이 시험이 그걸 잡는다');
ok(!mB.includes('추정'),
   '[뮤테이션] 옛 코드는 추정 딱지를 안 붙인다 — 이 시험이 그걸 잡는다');

console.log(fails ? `\n❌ 실패 ${fails}건` : '\n✅ 전부 통과');
process.exit(fails ? 1 : 0);
