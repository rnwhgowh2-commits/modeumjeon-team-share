// 실행: node 프로그램/_시스템/tests/js/test_orders_purchase_filter.mjs
//        (pytest 에서도 돈다 — tests/orders/test_purchase_upload_ux.py 가 부른다)
//
// ★ 2026-08-06 사장님 라이브 신고 — 「매입가」 열 ▼ 필터를 열면 **「(빈값) 462」 하나뿐**.
//   실제로는 200건에 값이 있었다.
//   원인: 매입가는 화면 전용 칸(`_pp_purchase`)이라 행(preview.json)에 값이 없고,
//        값은 별도 조회(`ppMap`)에만 있는데 `filterKey()` 가 `r['_pp_purchase']` 를 봤다.
//
//   문자열 검사로는 못 잡는다(코드는 늘 「있다」). 그래서 템플릿의 **진짜 원문**
//   (filterKey · ppFilterKey · ppOf · rowPass · filtered)을 떼어 Node 에서 돌리고,
//   실제로 필터 목록을 만들어 본다. 마지막에 **뮤테이션**(옛 코드로 되돌림)으로
//   이 시험이 진짜 잡는지(RED) 실증한다.
//   (선례: test_orders_margin_tabs_no_refetch.mjs)
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

/** `var PP_FKEY={…};` 같은 한 줄짜리 정의를 원문 그대로 떼어 온다. */
function line(startsWith, src = SRC) {
  const hit = src.split('\n').find((l) => l.trimStart().startsWith(startsWith));
  if (!hit) throw new Error(`정의를 못 찾음: ${startsWith}`);
  return hit;
}

/** 필터 팝오버(openColPop)가 목록을 만드는 **그 방식 그대로** 항목·건수를 센다.
 *  (openColPop 첫 줄: `filteredExcept(col).forEach(r => cnt[filterKey(col,r)]++)`) */
function buildHarness(src) {
  const script = `
    var SHIP=false, xlLoaded=false;
    var colFilter={}, srch='', dmCheckFilter='', ffFilter='', ffReason='', onlyBad=false;
    var clsOf={}, shipCls='go', invResult={}, invMap={}, invSel={};
    var mgMap={}, mgFilter='';
    function dmOf(){return null;} function ffOf(){return null;} function mgOf(){return null;}
    function invKey(r){return r._line_uid;}
    function srchHay(){return '';}
    var ppMap=env.ppMap;
    // 「주문 관리」 상태 축·필터 — 이 시험의 관심사가 아니라 「값 없음」으로 둔다.
    var ostMap={}, ostFilter='';
    function ostOf(){return null;} function ostFilterKey(){return '지정 안 함';}
    ${extract('ppUid', src)}
    ${extract('ppOf', src)}
    ${line('var PP_FKEY=', src)}
    ${extract('ppFilterKey', src)}
    ${extract('filterKey', src)}
    var rows=env.rows;
    ${extract('rowPass', src)}
    ${extract('filteredExcept', src)}
    ${extract('filtered', src)}
    function tally(col){
      var cnt={}; filteredExcept(col).forEach(function(r){var k=filterKey(col,r);cnt[k]=(cnt[k]||0)+1;});
      return cnt;
    }
    return {tally:tally, filtered:filtered,
            setFilter:function(col,ex){colFilter[col]={excluded:new Set(ex)};}};
  `;
  // eslint-disable-next-line no-new-func
  return script;
}

console.log('매입가 열 필터 — ppMap 의 진짜 값을 본다:\n');

// ── 라이브를 축소한 표: 값 있는 줄 3(실매입가2·사입가1·예상1) + 값 없는 줄 2 ──
const rows = [
  { _line_uid: 'a', 주문일: '2026-08-05', 판매처: '쿠팡' },
  { _line_uid: 'b', 주문일: '2026-08-05', 판매처: '쿠팡' },
  { _line_uid: 'c', 주문일: '2026-08-04', 판매처: '스마트스토어' },
  { _line_uid: 'd', 주문일: '2026-08-04', 판매처: '11번가' },
  { _line_uid: 'e', 주문일: '2026-08-03', 판매처: '옥션' },
  { _line_uid: 'f', 주문일: '2026-08-03', 판매처: '옥션' },   // uid 는 있는데 ppMap 에 없음
];
const ppMap = {
  a: { price: 61320, tier: 'real', label: '실매입가' },
  b: { price: 58000, tier: 'real', label: '실매입가' },
  c: { price: 47500, tier: 'stock', label: '사입가' },
  d: { price: 52100, tier: 'estimate', label: '예상' },
  e: { price: null, tier: null, label: '확인 불가' },
};

const env = { rows, ppMap };
// eslint-disable-next-line no-new-func
const api = new Function('env', buildHarness(SRC))(env);

const cnt = api.tally('_pp_purchase');
const keys = Object.keys(cnt).sort();

// ── ① 이번 버그 — 목록이 「(빈값)」 하나뿐이면 안 된다 ──
ok(keys.length > 1,
   `필터 목록이 한 종류(빈값)로 뭉개지지 않는다 — 실제: ${keys.length}종 [${keys}]`);
ok(!(keys.length === 1 && keys[0] === ''),
   '「(빈값) 6」 하나만 나오는 옛 증상이 재현되지 않는다');

// ── ② 값 있는 줄이 「값 없음」으로 세지지 않는다 ──
const 없음 = cnt['값 없음'] || 0;
ok(없음 === 2, `「값 없음」은 2줄(e·f)이다 — 실제: ${없음}`);
const 있음 = Object.keys(cnt).filter((k) => k !== '값 없음')
  .reduce((a, k) => a + cnt[k], 0);
ok(있음 === 4, `값이 있는 줄은 4줄(a·b·c·d)이다 — 실제: ${있음}`);

// ── ③ 출처를 숨기지 않는다(예상가를 실매입가처럼 보이면 안 된다) ──
ok(cnt['값 있음 · 실매입가'] === 2, `실매입가 2줄 — 실제: ${cnt['값 있음 · 실매입가']}`);
ok(cnt['값 있음 · 사입가'] === 1, `사입가 1줄 — 실제: ${cnt['값 있음 · 사입가']}`);
ok(cnt['값 있음 · 예상'] === 1, `예상 1줄 — 실제: ${cnt['값 있음 · 예상']}`);
ok(keys.length === 4, `숫자를 나열하지 않고 4묶음으로만 낸다(462줄 목록 금지) — 실제: ${keys.length}`);

// ── ④ 고른 값으로 실제로 걸러진다(체크 해제 = 제외) ──
api.setFilter('_pp_purchase', ['값 있음 · 실매입가', '값 있음 · 사입가', '값 있음 · 예상']);
ok(api.filtered().length === 2, `「값 없음」만 남기면 2줄 — 실제: ${api.filtered().length}`);
api.setFilter('_pp_purchase', ['값 없음']);
ok(api.filtered().length === 4, `「값 없음」을 빼면 4줄 — 실제: ${api.filtered().length}`);

// ══════════════════════════════════════════════════════════════════
//  ⑤ 뮤테이션 — 옛 코드(행에서 직접 읽기)로 되돌리면 이 시험이 **반드시** 깨진다
//     (안 깨지면 아무것도 안 보는 시험이다 — feedback_test_that_tests_nothing)
// ══════════════════════════════════════════════════════════════════
const OLD = "    function filterKey(col,r){var v=r[col]||''; return col==='주문일'?String(v).slice(0,10):String(v);}";
const mutated = SRC.replace(extract('filterKey'), OLD);
if (mutated === SRC) throw new Error('뮤테이션이 filterKey 를 못 바꿨습니다 — 시험이 무효입니다');
// eslint-disable-next-line no-new-func
const mapi = new Function('env', buildHarness(mutated))({ rows, ppMap });
const mcnt = mapi.tally('_pp_purchase');
const mkeys = Object.keys(mcnt);
ok(mkeys.length === 1 && mkeys[0] === '' && mcnt[''] === 6,
   `뮤테이션(옛 filterKey)이면 「(빈값) 6」 하나로 뭉개진다 = 이 시험이 진짜 버그를 본다 — 실제: [${mkeys}]`);

console.log('\n결과: ' + (fails ? fails + ' 실패' : '전부 통과'));
process.exit(fails ? 1 : 0);
