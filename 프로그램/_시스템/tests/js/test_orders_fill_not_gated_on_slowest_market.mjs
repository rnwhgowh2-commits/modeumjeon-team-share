// 실행: node 프로그램/_시스템/tests/js/test_orders_fill_not_gated_on_slowest_market.mjs
//        (pytest 에서도 돈다 — tests/orders/test_orders_fill_wiring.py 가 부른다)
//
// ★ 2026-08-06 라이브 버그 고정 — 「매입가가 절대 안 뜬다」
//   주문 표는 마켓이 하나 도착할 때마다 다시 그려지는데(rebuild), 채우기 3종
//   (가격 전후 · 3분류 · 매입가)이 `if(!loading)` 안에 있었다. `loading` 은 **고른 마켓이
//   전부 끝나야** false 라, 옥션 하나가 125초 걸려 실패하고 재시도까지 하는 동안
//   (실측 t=206초) 표는 t=3초에 다 그려진 채 매입가가 전 줄 「확인 불가」였다.
//   사장님이 값을 적어 저장해도 새로고침하면 사라진 것처럼 보였다.
//
//   문자열 검사로는 이걸 못 잡는다(호출문은 멀쩡히 **있었다**). 그래서 여기서는
//   템플릿의 **진짜 load() 원문을 떼어 Node 에서 실행**하고, 느린 마켓을 영영
//   응답 안 하게 잡아 둔 채로 세 요청이 실제로 나가는지 본다.
//   (선례: test_policy_attach_wiring.mjs — 템플릿 원문을 떼어 태우는 방식)
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __d = path.dirname(fileURLToPath(import.meta.url));
const TPL = path.join(__d, '..', '..', 'webapp', 'templates', 'orders', 'index.html');
const SRC = fs.readFileSync(TPL, 'utf8');

let fails = 0;
const ok = (cond, msg) => { if (!cond) { console.error('❌', msg); fails += 1; } else { console.log('  ✅', msg); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** `function 이름(...) { … }` 원문을 중괄호 짝으로 떼어 온다. 사라지면 즉사(베껴 쓰기 금지). */
function extract(name) {
  const m = new RegExp('^\\s*function\\s+' + name + '\\s*\\(', 'm').exec(SRC);
  if (!m) throw new Error(`${name}() 이(가) orders/index.html 에 없습니다 — 배선이 사라졌습니다`);
  let i = SRC.indexOf('{', m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < SRC.length; j += 1) {
    if (SRC[j] === '{') depth += 1;
    else if (SRC[j] === '}') { depth -= 1; if (depth === 0) return SRC.slice(m.index, j + 1); }
  }
  throw new Error(`${name}() 의 중괄호 짝이 안 맞습니다`);
}

/** 표시줄 사이의 원문을 떼어 온다(줄 세우기 상태 변수 + resetFill/scheduleFill/runFill). */
function cut(startsWith, endStartsWith, what) {
  const all = SRC.split('\n');
  const s = all.findIndex((l) => l.trimStart().startsWith(startsWith));
  const e = all.findIndex((l, i) => i > s && l.trimStart().startsWith(endStartsWith));
  if (s < 0 || e < 0) throw new Error(`${what} 조각을 못 찾음: ${startsWith}`);
  return all.slice(s, e).join('\n');
}

const loadSrc = extract('load');
if (!/preview\.json/.test(loadSrc)) throw new Error('떼어 온 load() 가 주문 조회가 아닙니다');

// ══ 하네스 ═══════════════════════════════════════════════════════
//   화면(DOM)·정렬·렌더는 이 시험의 관심사가 아니라 최소로만 흉내 낸다.
//   관심사는 **어떤 요청이 언제 나가는가** 하나다.
function harness(markets) {
  const calls = [];                 // 나간 요청 전부 (순서대로)
  const gate = {};                  // url키 → [{resolve}] 아직 응답 안 준 것들
  function stall(key, body) {
    return new Promise((resolve) => {
      (gate[key] = gate[key] || []).push(() => resolve({ json: () => Promise.resolve(body()) }));
    });
  }
  function release(key) {           // 잡아 둔 응답을 지금 돌려준다
    const q = gate[key] || []; gate[key] = [];
    q.forEach((fn) => fn());
    return q.length;
  }
  const state = { rowsByMarket: {} };

  const env = {
    SHIP: false,
    calls,
    release,
    fetch(url, opt) {
      const body = opt && opt.body ? JSON.parse(opt.body) : null;
      calls.push({ url, rows: body && body.rows ? body.rows.length : null });
      const mk = /preview\.json\?market=([^&]+)/.exec(url);
      if (mk) {
        const name = mk[1];
        if (!markets[name].respond) return stall('mkt:' + name, () => ({ ok: true, rows: state.rowsByMarket[name] || [], warnings: [] }));
        return Promise.resolve({ json: () => Promise.resolve({ ok: true, rows: state.rowsByMarket[name] || [], warnings: [] }) });
      }
      if (/price-diff/.test(url)) return stall('fill', () => ({ ok: true, diffs: {} }));
      if (/fulfillment/.test(url)) return stall('fill', () => ({ ok: true, marks: {} }));
      if (/purchase-price\/resolve/.test(url)) return stall('fill', () => ({ ok: true, prices: {} }));
      if (/supply-mode\/resolve/.test(url)) return stall('fill', () => ({ ok: true, modes: {} }));
      if (/line-status\/resolve/.test(url)) return stall('fill', () => ({ ok: true, statuses: {}, options: [] }));
      throw new Error('예상 못한 요청: ' + url);
    },
    state,
  };
  Object.keys(markets).forEach((m) => { state.rowsByMarket[m] = markets[m].rows; });

  // 템플릿 원문 + 최소 스텁을 한 스코프에 올린다.
  const script = `
    var SHIP=env.SHIP, fetch=env.fetch;
    var document={getElementById:function(){return {innerHTML:'',classList:{add:function(){},remove:function(){}}};}};
    var loadSeq=0, loading=false, loadDone=0, loadTotal=0, warnAll=[], retryMk=null;
    var loadMks=[], mkState={}, mkCount={}, ordCache={}, cacheShown=false;
    var rows=[], colFilter={}, cur={from:'2026-08-01',to:'2026-08-06'};
    var pdxMap={}, pdxSeq=0, ppMap={}, ppSeq=0, ffMap={}, ffSeq=0, ffFilter='', ffReason='';
    var smMap={}, smSeq=0;
    // 「주문 관리」 상태 — load() 가 매 조회마다 비우고, runFill 이 같은 묶음으로 채운다.
    var ostMap={}, ostOpts=[], ostSeq=0, ostState={}, ostFilter='';
    // 마진 가로 탭 상태 — load() 가 매 조회마다 비운다(주소로 온 탭은 첫 조회 한 번).
    var mgMap={}, mgFilter='', mgPending='';
    var renderCount=0;
    function qparam(){return 'from='+cur.from+'&to='+cur.to;}
    function selMk(){return env.selected.slice();}
    function syncBtn(){} function sortRows(){} function renderWarn(){}
    function render(){renderCount++;} function renderLoadBar(){} function schedulePrefetch(){}
    ${cut('var fillSig=', '// ── M4 가격 전후 조회', '채우기 줄 세우기')}
    ${loadSrc}
    ${extract('loadPriceDiff')}
    ${extract('loadFulfillment')}
    ${extract('loadPurchasePrice')}
    ${extract('loadSupplyMode')}
    ${extract('loadOrderStatus')}
    return {load:load, rowCount:function(){return rows.length;},
            isLoading:function(){return loading;}, renderCount:function(){return renderCount;},
            tab:function(){return mgFilter;},
            setPending:function(v){mgPending=v;}};
  `;
  // eslint-disable-next-line no-new-func
  const api = new Function('env', script)(env);
  env.selected = Object.keys(markets);
  return Object.assign(api, env);
}

const fillCalls = (h) => h.calls.filter((c) => /price-diff|fulfillment|purchase-price\/resolve|supply-mode\/resolve|line-status\/resolve/.test(c.url));
const urlsOf = (cs) => cs.map((c) => c.url.replace(/^\/orders\//, ''));

console.log('주문 표 채우기 배선 — 제일 느린 마켓에 묶이지 않는다:\n');

// 실측 그대로: 빠른 마켓(쿠팡)·중간(스스)·영영 안 오는 마켓(옥션 125초+재시도)
const h = harness({
  coupang:     { respond: true,  rows: [{ _line_uid: 'c|1|1' }, { _line_uid: 'c|2|2' }] },
  smartstore:  { respond: false, rows: [{ _line_uid: 's|1|1' }, { _line_uid: 's|2|2' }, { _line_uid: 's|3|3' }] },
  auction:     { respond: false, rows: [{ _line_uid: 'a|1|1' }] },
});

h.load();
await sleep(700);          // 400ms 묶음 + 여유

ok(h.isLoading() === true, '느린 마켓 2개가 아직 안 왔으니 loading 은 여전히 true (= 옛 게이트는 안 열린다)');
ok(h.rowCount() === 2, '표에는 먼저 온 쿠팡 2줄이 이미 그려져 있다');

let f = fillCalls(h);
ok(f.length === 5, `표가 그려졌으면 채우기 5종이 나간다 — 실제: ${f.length}건 [${urlsOf(f)}]`);
ok(f.some((c) => /price-diff/.test(c.url)), '가격 전후(price-diff.json)가 나갔다');
ok(f.some((c) => /fulfillment/.test(c.url)), '3분류(fulfillment.json)가 나갔다');
ok(f.some((c) => /purchase-price\/resolve/.test(c.url)), '매입가(purchase-price/resolve)가 나갔다 ← 이번 버그');
ok(f.some((c) => /supply-mode\/resolve/.test(c.url)), '공급방식(supply-mode/resolve)이 나갔다');
ok(f.some((c) => /line-status\/resolve/.test(c.url)), '「주문 관리」 상태(line-status/resolve)가 나갔다 — 새 게이트를 따로 만들지 않았다');
ok(f.length === 5 && f.every((c) => c.rows === 2), '보낸 행은 그때까지 도착한 2줄');

// ── 줄 세우기: 도는 중에 새 마켓이 와도 겹쳐 쏘지 않는다 ──
h.release('mkt:smartstore');
await sleep(700);
ok(h.rowCount() === 5, '스스가 도착해 표는 5줄이 됐다');
ok(fillCalls(h).length === 5, `앞 묶음이 도는 중이면 새로 안 쏜다(워커 2개 보호) — 실제: ${fillCalls(h).length}건`);

// ── 이어받기: 앞 묶음이 끝나면 그동안 늘어난 행으로 한 번 더 ──
h.release('fill');
await sleep(50);
h.release('fill');         // done() 이 체인 끝에서 도는 틱을 한 번 더 준다
await sleep(700);
f = fillCalls(h);
ok(f.length === 10, `앞 묶음이 끝나면 늘어난 행으로 이어서 채운다 — 실제: ${f.length}건`);
ok(f.slice(5).length === 5 && f.slice(5).every((c) => c.rows === 5), '두 번째 묶음은 5줄 전부를 보낸다');
ok(h.isLoading() === true && f.length === 10, '옥션은 끝까지 안 왔는데도 채우기는 두 번 다 돌았다 (근본 수정 지점)');

// ── 회귀 방지: 옛 게이트가 되돌아오면 즉사 ──
//   (호출문 자체는 옛 코드에도 있었으므로 「있다」가 아니라 「게이트가 없다」를 못 박는다)
ok(!/if\(!loading\)\{loadPriceDiff/.test(SRC),
   '옛 게이트 `if(!loading){loadPriceDiff...}` 가 되돌아오지 않았다');
ok(/scheduleFill\(seq,/.test(SRC), 'rebuild() 가 scheduleFill 로 채우기를 건다');

// ── 주소로 온 탭(`?mg=nopp`) — 상품관리 판매 이력의 「매입가 미입력 N건 →」 링크 ──
//   설계서 §6.2. 첫 조회에만 걸리고, 그다음 조회부터는 평소대로 비워진다
//   (「옛 기간의 판정을 새 기간에 물려주지 않는다」는 규칙을 안 깬다).
console.log('\n주소로 온 마진 탭 — 첫 조회 한 번만:\n');
const h2 = harness({ coupang: { respond: true, rows: [{ _line_uid: 'c|1|1' }] } });
h2.setPending('nopp');       // 주소 `?mg=nopp` 를 읽어 둔 상태
h2.load();
await sleep(700);
ok(h2.tab() === 'nopp', `첫 조회에 「매입가 미입력」 탭이 걸린다 — 실제: '${h2.tab()}'`);
h2.load();                 // 사장님이 기간을 바꿔 다시 조회
await sleep(700);
ok(h2.tab() === '', `두 번째 조회부터는 평소대로 비운다 — 실제: '${h2.tab()}'`);

console.log('\n결과: ' + (fails ? fails + ' 실패' : '전부 통과'));
process.exit(fails ? 1 : 0);
