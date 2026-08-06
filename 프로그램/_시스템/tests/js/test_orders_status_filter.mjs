// 실행: node 프로그램/_시스템/tests/js/test_orders_status_filter.mjs
//        (pytest 에서도 돈다 — tests/orders/test_order_status_js.py 가 부른다)
//
// ★ 「주문 관리」 상태는 매입가(`_pp_purchase`)와 **같은 부류**다 — 화면 전용 칸이라
//   행(preview.json)에 값이 없고, 값은 별도 조회(`ostMap`)에만 있다.
//   `filterKey()` 가 `r['_ostatus']` 를 보면 필터 목록이 **「(빈값) 전부」 하나**로
//   뭉개진다(2026-08-06 매입가에서 실제로 났던 사고 — 같은 실수를 반복하지 않는다).
//
//   문자열 검사로는 못 잡는다(코드는 늘 「있다」). 그래서 템플릿의 **진짜 원문**
//   (filterKey · ostFilterKey · ostOf · rowPass · filtered)을 떼어 Node 에서 돌리고,
//   실제로 필터 목록·거르기 결과를 만들어 본다. 마지막에 **뮤테이션** 2종으로
//   이 시험이 진짜 잡는지(RED) 실증한다.
//   (선례: test_orders_purchase_filter.mjs)
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

/** 필터 팝오버(openColPop)가 목록을 만드는 **그 방식 그대로** 항목·건수를 센다. */
function buildHarness(src) {
  return `
    var SHIP=false, xlLoaded=false;
    var colFilter={}, srch='', dmCheckFilter='', ffFilter='', ffReason='', onlyBad=false;
    var clsOf={}, shipCls='go', invResult={}, invMap={}, invSel={};
    var mgMap={}, mgFilter='', ppMap={};
    function dmOf(){return null;} function ffOf(){return null;} function mgOf(){return null;}
    function invKey(r){return r._line_uid;}
    function srchHay(){return '';}
    function ppOf(){return null;} function ppFilterKey(){return '값 없음';}
    var ostMap=env.ostMap, ostFilter='';
    ${extract('ostUid', src)}
    ${extract('ostOf', src)}
    ${extract('ostFilterKey', src)}
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
            setFilter:function(col,ex){colFilter[col]={excluded:new Set(ex)};},
            setOst:function(v){ostFilter=v;}};
  `;
}

console.log('「주문 관리」 상태 열 필터 — ostMap 의 진짜 값을 본다:\n');

// ── 라이브를 축소한 표 ──
//   a·b = 손으로 고른 「배송완료」 · c = 손으로 고른 「오류입고」
//   d·e = 아직 안 고른 줄에 기본 항목(「결제완료」)이 얹혀 보이는 중(is_fallback)
//   f    = 기본 항목도 없던 줄 → 「지정 안 함」
const rows = [
  { _line_uid: 'a', 주문일: '2026-08-05', 판매처: '쿠팡' },
  { _line_uid: 'b', 주문일: '2026-08-05', 판매처: '쿠팡' },
  { _line_uid: 'c', 주문일: '2026-08-04', 판매처: '11번가' },
  { _line_uid: 'd', 주문일: '2026-08-04', 판매처: '스마트스토어' },
  { _line_uid: 'e', 주문일: '2026-08-03', 판매처: '옥션' },
  { _line_uid: 'f', 주문일: '2026-08-03', 판매처: '옥션' },
];
const ostMap = {
  a: { option_id: 2, name: '배송완료', color: 'green', is_fallback: false },
  b: { option_id: 2, name: '배송완료', color: 'green', is_fallback: false },
  c: { option_id: 3, name: '오류입고', color: 'orange', is_fallback: false },
  d: { option_id: 1, name: '결제완료', color: 'blue', is_fallback: true },
  e: { option_id: 1, name: '결제완료', color: 'blue', is_fallback: true },
};

const env = { rows, ostMap };
// eslint-disable-next-line no-new-func
const api = new Function('env', buildHarness(SRC))(env);

const cnt = api.tally('_ostatus');
const keys = Object.keys(cnt).sort();

// ── ① 매입가에서 났던 사고 — 목록이 「(빈값)」 하나로 뭉개지면 안 된다 ──
ok(keys.length > 1,
   `필터 목록이 한 종류(빈값)로 뭉개지지 않는다 — 실제: ${keys.length}종 [${keys}]`);
ok(!keys.includes(''), '「(빈값)」 항목이 생기지 않는다(상태는 rows 가 아니라 ostMap 에 있다)');

// ── ② 목록은 **항목 이름 + 「지정 안 함」** ──
ok(cnt['배송완료'] === 2, `배송완료 2줄 — 실제: ${cnt['배송완료']}`);
ok(cnt['오류입고'] === 1, `오류입고 1줄 — 실제: ${cnt['오류입고']}`);
ok(cnt['지정 안 함'] === 1, `지정 안 함은 f 한 줄뿐 — 실제: ${cnt['지정 안 함']}`);
ok(keys.length === 4, `숫자·id 를 나열하지 않고 이름 3 + 지정 안 함 = 4묶음 — 실제: ${keys.length}`);

// ── ③ 기본 항목이 보이는 줄은 **그 항목 이름**으로 센다(화면에 그렇게 보인다) ──
ok(cnt['결제완료'] === 2,
   `기본 항목이 얹힌 d·e 는 「결제완료」로 센다(「지정 안 함」이 아니다) — 실제: ${cnt['결제완료']}`);

// ── ④ 고른 값으로 실제로 걸러진다(체크 해제 = 제외) ──
api.setFilter('_ostatus', ['배송완료', '결제완료', '오류입고']);
ok(api.filtered().length === 1, `이름 3개를 빼면 「지정 안 함」 1줄만 — 실제: ${api.filtered().length}`);
api.setFilter('_ostatus', ['지정 안 함']);
ok(api.filtered().length === 5, `「지정 안 함」을 빼면 5줄 — 실제: ${api.filtered().length}`);
api.setFilter('_ostatus', []);

// ── ⑤ 상태별 거르기 알약(rowPass 의 `_ost` 축) ──
api.setOst('2');
ok(api.filtered().length === 2, `「배송완료」 알약 = 2줄 — 실제: ${api.filtered().length}`);
api.setOst('1');
ok(api.filtered().length === 2, `기본 항목이 보이는 줄도 그 알약에 잡힌다 = 2줄 — 실제: ${api.filtered().length}`);
api.setOst('none');
ok(api.filtered().length === 1, `「지정 안 함」 알약 = f 1줄 — 실제: ${api.filtered().length}`);
api.setOst('');
ok(api.filtered().length === 6, `알약을 풀면 전부 6줄 — 실제: ${api.filtered().length}`);

// ══════════════════════════════════════════════════════════════════
//  ⑥ 뮤테이션 — 옛 방식으로 되돌리면 이 시험이 **반드시** 깨진다
//     (안 깨지면 아무것도 안 보는 시험이다 — feedback_test_that_tests_nothing)
// ══════════════════════════════════════════════════════════════════
const OLD = "    function filterKey(col,r){var v=r[col]||''; return col==='주문일'?String(v).slice(0,10):String(v);}";
const mutated = SRC.replace(extract('filterKey'), OLD);
if (mutated === SRC) throw new Error('뮤테이션이 filterKey 를 못 바꿨습니다 — 시험이 무효입니다');
// eslint-disable-next-line no-new-func
const mapi = new Function('env', buildHarness(mutated))({ rows, ostMap });
const mcnt = mapi.tally('_ostatus');
const mkeys = Object.keys(mcnt);
ok(mkeys.length === 1 && mkeys[0] === '' && mcnt[''] === 6,
   `뮤테이션(행에서 직접 읽는 옛 filterKey)이면 「(빈값) 6」 하나로 뭉개진다 — 실제: [${mkeys}]`);

// 뮤테이션 2 — 기본 표시 줄을 「지정 안 함」으로 세면 알약 건수가 틀어진다
const OLD2 = `function ostFilterKey(r){
      var d=ostOf(r);
      return (d&&d.name&&!d.is_fallback)?String(d.name):'지정 안 함';
    }`;
const mutated2 = SRC.replace(extract('ostFilterKey'), OLD2);
if (mutated2 === SRC) throw new Error('뮤테이션2 가 ostFilterKey 를 못 바꿨습니다 — 시험이 무효입니다');
// eslint-disable-next-line no-new-func
const m2 = new Function('env', buildHarness(mutated2))({ rows, ostMap });
const c2 = m2.tally('_ostatus');
ok((c2['결제완료'] || 0) === 0 && c2['지정 안 함'] === 3,
   `뮤테이션2(기본 표시를 「지정 안 함」 취급)면 결제완료 0 · 지정 안 함 3 으로 틀어진다 — 실제: 결제완료 ${c2['결제완료'] || 0} · 지정 안 함 ${c2['지정 안 함']}`);

console.log('\n결과: ' + (fails ? fails + ' 실패' : '전부 통과'));
process.exit(fails ? 1 : 0);
