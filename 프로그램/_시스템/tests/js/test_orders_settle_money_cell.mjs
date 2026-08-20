// 실행: node 프로그램/_시스템/tests/js/test_orders_settle_money_cell.mjs
//
// 노션 주문관리 ⑥ — 「정산예정금」 27·28번 열에도 추정 딱지.
//
// 🔴 여태 이 두 칸은 `MONEY_COLS` 분기로 떨어져 **숫자만** 찍혔다 — 배지가 설 자리
//   자체가 없었다. 같은 화면에서 실마진 칸엔 「추정」이 붙는데, 그 재료인 정산액은
//   실측처럼 검게 보였다(한 화면 안에서 말이 어긋난다).
//
// 🔴 문자열 검사로는 못 잡는다 — 코드에 '추정' 글자가 있는지 보는 것만으로는 **언제**
//   붙는지 못 잰다. 템플릿의 진짜 원문(cellHTML · settleMoneyCell · SETTLE_SRC)을 떼어
//   Node 에서 돌리고 실제 HTML 을 만든다. 마지막에 뮤테이션으로 RED 를 실증한다.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __d = path.dirname(fileURLToPath(import.meta.url));
const TPL = path.join(__d, '..', '..', 'webapp', 'templates', 'orders', 'index.html');
const SRC = fs.readFileSync(TPL, 'utf8').replace(/\r\n/g, '\n');

let fails = 0;
const ok = (cond, msg) => { if (!cond) { console.error('❌', msg); fails += 1; } else { console.log('  ✅', msg); } };

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
    function esc(s){return String(s==null?'':s).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
    ${line('function num(v){', src)}
    ${objDef('SETTLE_SRC', src)}
    ${line('var SETTLE_MONEY_COLS=', src)}
    ${extract('mgSettleSrc', src)}
    ${extract('settleMoneyCell', src)}
    return { settleMoneyCell: settleMoneyCell, SETTLE_MONEY_COLS: SETTLE_MONEY_COLS };
  `;
}

// eslint-disable-next-line no-new-func
const api = new Function(build(SRC))();
const cell = (col, src, v) => api.settleMoneyCell(col, { _settle_source: src }, v);
// 🔴 **낱말로 판정하지 않는다.** 실측 행의 호버 문구가 "…(추정 아님)" 이라
//   `includes('추정')` 은 실측에서도 참이 된다(이 시험이 실제로 그걸 잡아냈다).
//   딱지가 붙었는지는 **배지 요소**로만 본다. (feedback_preservation_check_must_catch_broken)
const chipOf = (html) => {
  const m = /<span class="mg-chip[^"]*">([^<]*)<\/span>/.exec(html);
  return m ? m[1] : '';
};
const N = '정산예정금(배송비포함)';
const M = '정산예정금액';

// ── ① 두 칸이 실제로 이 경로를 타는가 (노션이 짚은 27·28번 열) ──────────────
ok(api.SETTLE_MONEY_COLS[M] && api.SETTLE_MONEY_COLS[N],
   '27·28번 두 칸이 배지 경로를 탄다');

// 🔴 cellHTML 안에서 **MONEY_COLS 보다 먼저** 걸러야 한다 — 순서가 뒤집히면 배지
//   경로가 영영 안 불린다(있는데 안 도는 가장 위험한 실패).
const body = extract('cellHTML');
ok(body.indexOf('SETTLE_MONEY_COLS') < body.indexOf('if(MONEY_COLS[col])'),
   'cellHTML 이 MONEY_COLS 보다 먼저 SETTLE_MONEY_COLS 를 본다(순서)');

// ── ② 추정이면 딱지, 실측이면 딱지 없음 ─────────────────────────────────────
const est = cell(N, 'estimated', 117792);
ok(est.includes('117,792'), '추정이어도 숫자는 그대로 찍힌다');
ok(chipOf(est) === '추정', '추정 정산액에 「추정」 딱지가 붙는다');
ok(est.includes('title='), '추정 사유가 호버로 붙는다');

const real = cell(N, 'real', 117792);
ok(real.includes('117,792') && chipOf(real) === '',
   '실측 정산액엔 딱지가 없다(멀쩡한 값을 의심하게 만들지 않는다)');
ok(real.includes('title='), '실측도 「마켓이 알려준 값」이라는 근거 호버는 있다');

const store = cell(M, 'store', 113924);
ok(store.includes('113,924') && chipOf(store) === '', '저장분 실값도 딱지 없음');

// ── ③ 「없음」의 뜻을 지킨다 ────────────────────────────────────────────────
const noneWithValue = cell(N, 'none', 50000);
ok(noneWithValue.includes('50,000') && chipOf(noneWithValue) === '',
   '값이 있는데 근거만 빈 행에 「없음」 딱지를 붙이지 않는다');
const noneEmpty = cell(N, 'none', '');
ok(noneEmpty.includes('—') && noneEmpty.includes('title='),
   '값이 없으면 — 와 사유 호버');

// ── ④ 취소완료는 취소 딱지 ─────────────────────────────────────────────────
ok(chipOf(cell(N, 'zero_cancel', 0)) === '취소', '취소완료는 「취소」 딱지');

// ── ⑤ N열 호버는 「배송비도 수수료를 뗀다」를 말한다 (2026-08-13 판정) ────────
ok(cell(N, 'real', 1).includes('배송비 정산'),
   'N열 호버가 상품+배송비 정산 구성을 설명한다');
ok(!cell(M, 'real', 1).includes('배송비 정산'),
   'M열(상품분)엔 그 설명을 붙이지 않는다');

// ══════════════════════════════════════════════════════════════════
//  ⑥ 뮤테이션 — 「숫자만 찍는」 옛 코드로 되돌리면 반드시 깨져야 한다.
//     안 깨지면 아무것도 안 보는 시험이다. (feedback_test_that_tests_nothing)
// ══════════════════════════════════════════════════════════════════
const NAIVE = `function settleMoneyCell(col,r,v){
      return (v!==''&&v!=null)?Number(num(v)).toLocaleString():'<span class="muted">—</span>';
    }`;
const mutated = SRC.replace(extract('settleMoneyCell'), NAIVE);
if (mutated === SRC) throw new Error('뮤테이션이 settleMoneyCell 을 못 바꿨습니다 — 시험이 무효입니다');
// eslint-disable-next-line no-new-func
const mapi = new Function(build(mutated))();
ok(chipOf(mapi.settleMoneyCell(N, { _settle_source: 'estimated' }, 117792)) === '',
   '[뮤테이션] 옛 코드는 추정 딱지를 안 붙인다 — 이 시험이 그걸 잡는다');

console.log(fails ? `\n❌ 실패 ${fails}건` : '\n✅ 전부 통과');
process.exit(fails ? 1 : 0);
