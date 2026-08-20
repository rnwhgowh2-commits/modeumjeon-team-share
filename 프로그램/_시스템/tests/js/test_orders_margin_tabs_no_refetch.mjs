// 실행: node 프로그램/_시스템/tests/js/test_orders_margin_tabs_no_refetch.mjs
//        (pytest 에서도 돈다 — tests/orders/test_margin_flags.py 가 부른다)
//
// ★ 2단계 약속 고정 — 「탭을 눌러도 서버를 다시 부르지 않는다」
//   주문 표는 마켓별로 이미 받아 그린 것이라, 가로 탭(전체·이상마진·블랙스팟·매입가
//   미입력)은 **이미 있는 행을 거르기만** 해야 한다. 여기서 fetch 를 한 번이라도
//   부르면 탭을 누를 때마다 소싱처 계산이 다시 돌아 표가 몇십 초씩 멈춘다.
//
//   문자열 검사로는 못 잡는다(코드는 늘 「있다」). 그래서 템플릿의 **진짜 원문**
//   (rowPass · renderMgTabs · filtered)을 떼어 Node 에서 돌리고, fetch 를 폭탄으로
//   깔아 둔 채 탭을 실제로 눌러 본다.
//   (선례: test_orders_fill_not_gated_on_slowest_market.mjs)
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __d = path.dirname(fileURLToPath(import.meta.url));
const TPL = path.join(__d, '..', '..', 'webapp', 'templates', 'orders', 'index.html');
const SRC = fs.readFileSync(TPL, 'utf8');

let fails = 0;
const ok = (cond, msg) => { if (!cond) { console.error('❌', msg); fails += 1; } else { console.log('  ✅', msg); } };

/** `function 이름(...) { … }` 원문을 중괄호 짝으로 떼어 온다. 사라지면 즉사(베껴 쓰기 금지). */
function extract(name) {
  const m = new RegExp('^\\s*function\\s+' + name + '\\s*\\(', 'm').exec(SRC);
  if (!m) throw new Error(`${name}() 이(가) orders/index.html 에 없습니다 — 배선이 사라졌습니다`);
  const i = SRC.indexOf('{', m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < SRC.length; j += 1) {
    if (SRC[j] === '{') depth += 1;
    else if (SRC[j] === '}') { depth -= 1; if (depth === 0) return SRC.slice(m.index, j + 1); }
  }
  throw new Error(`${name}() 의 중괄호 짝이 안 맞습니다`);
}

/** 표시줄 사이의 원문을 떼어 온다(탭 상태 변수 + MG_TABS 정의). */
function cut(startsWith, endStartsWith, what) {
  const all = SRC.split('\n');
  const s = all.findIndex((l) => l.trimStart().startsWith(startsWith));
  const e = all.findIndex((l, i) => i > s && l.trimStart().startsWith(endStartsWith));
  if (s < 0 || e < 0) throw new Error(`${what} 조각을 못 찾음: ${startsWith}`);
  return all.slice(s, e).join('\n');
}

const rowPassSrc = extract('rowPass');
if (!/_mg/.test(rowPassSrc)) throw new Error('rowPass 에 마진 축(_mg)이 없습니다 — 탭이 거르지 않습니다');

// ══ 가짜 DOM — 관심사는 「탭을 눌렀을 때 무엇이 일어나는가」 하나다 ══
function fakeEl() {
  const btns = [];
  const e = {
    style: {}, _html: '',
    querySelectorAll(sel) { return sel.indexOf('.fft') >= 0 ? btns : []; },
    _btns: btns,
  };
  Object.defineProperty(e, 'innerHTML', {
    get() { return e._html; },
    set(v) {
      e._html = v; btns.length = 0;
      const re = /data-mg="([^"]*)"/g;
      let m;
      while ((m = re.exec(v)) !== null) {
        const k = m[1];
        const b = { _k: k, _h: [], getAttribute: () => k };
        b.addEventListener = (t, f) => { if (t === 'click') b._h.push(f); };
        b.click = () => b._h.forEach((f) => f());
        btns.push(b);
      }
    },
  });
  return e;
}

function harness() {
  const calls = [];
  const el = fakeEl();
  const env = {
    calls,
    el,
    fetch(url) { calls.push(url); throw new Error('탭 전환이 서버를 불렀습니다: ' + url); },
  };
  const script = `
    var SHIP=false, xlLoaded=false, fetch=env.fetch;
    var document={getElementById:function(id){return id==='mgTabs'?env.el:null;}};
    var colFilter={}, srch='', dmCheckFilter='', ffFilter='', ffReason='', onlyBad=false;
    var clsOf={}, shipCls='go', invResult={}, invMap={}, invSel={};
    var renderCount=0;
    function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
    function srchHay(){return '';}
    function filterKey(col,r){return String(r[col]||'');}
    function dmOf(){return null;} function ffOf(){return null;} function invKey(r){return r._line_uid;}
    // 「주문 관리」 상태 축 — 이 시험의 관심사가 아니라 「아무것도 안 거른다」로 둔다.
    var ostFilter=''; function ostOf(){return null;}
    var rows=env.rows;
    ${cut('var mgMap={}, mgFilter=', 'function mgOf(', '마진 탭 상태·정의')}
    ${extract('mgOf')}
    ${rowPassSrc}
    ${extract('filtered')}
    ${extract('renderMgTabs')}
    function render(){renderCount++;filtered();renderMgTabs();}
    return {render:render, renderMgTabs:renderMgTabs, filtered:filtered,
            setFlags:function(m){mgMap=m;}, tab:function(){return mgFilter;},
            renderCount:function(){return renderCount;}};
  `;
  // eslint-disable-next-line no-new-func
  return { env, api: null, script };
}

console.log('주문 내역 가로 탭 — 탭 전환은 서버를 다시 부르지 않는다:\n');

// ── 표에 이미 그려진 5줄 + 서버가 한 번 준 판정 ──
const rows = [
  { _line_uid: 'a', 주문상태: '배송완료' },
  { _line_uid: 'b', 주문상태: '배송완료' },
  { _line_uid: 'c', 주문상태: '배송완료' },
  { _line_uid: 'd', 주문상태: '배송완료' },
  { _line_uid: 'e', 주문상태: '배송완료' },
];
const flags = {
  a: { abnormal: false, blackspot: false, nopp: false, basis: 'real', judged: true, reason: '' },
  b: { abnormal: true, blackspot: false, nopp: false, basis: 'real', judged: true, reason: '' },
  c: { abnormal: true, blackspot: true, nopp: false, basis: 'estimate', judged: true, reason: '' },
  d: { abnormal: false, blackspot: false, nopp: true, basis: null, judged: false, reason: '매입가를 못 구했어요' },
  e: { abnormal: false, blackspot: false, nopp: true, basis: 'estimate', judged: true, reason: '' },
};

const h = harness();
h.env.rows = rows;
// eslint-disable-next-line no-new-func
const api = new Function('env', h.script)(h.env);
api.setFlags(flags);

api.render();
ok(h.env.calls.length === 0, '탭을 그리는 것만으로는 서버를 부르지 않는다');
ok(api.filtered().length === 5, '「전체」에서는 5줄 다 보인다');

const btns = h.env.el._btns;
ok(btns.length === 4, `탭은 4개다(전체·이상마진·블랙스팟·매입가 미입력) — 실제: ${btns.length}`);
ok(btns.map((b) => b._k).join(',') === ',abnormal,blackspot,nopp',
   `탭 순서·키가 설계서 §6.1 그대로다 — 실제: [${btns.map((b) => b._k)}]`);

// ── 실제로 눌러 본다 ──
function press(key) {
  const before = h.env.calls.length;
  h.env.el._btns.filter((b) => b._k === key)[0].click();
  return h.env.calls.length - before;
}

ok(press('abnormal') === 0, '「이상마진」을 눌러도 서버 호출 0건 ← 이번 약속');
ok(api.tab() === 'abnormal', '탭 상태가 이상마진으로 바뀌었다');
ok(api.filtered().length === 2, `이상마진은 2줄(b·c) — 실제: ${api.filtered().length}`);

ok(press('blackspot') === 0, '「블랙스팟」을 눌러도 서버 호출 0건');
ok(api.filtered().length === 1, `블랙스팟은 1줄(c) — 실제: ${api.filtered().length}`);

ok(press('nopp') === 0, '「매입가 미입력」을 눌러도 서버 호출 0건');
ok(api.filtered().length === 2, `미입력은 2줄(d·e) — 실제: ${api.filtered().length}`);

ok(press('') === 0, '「전체」로 돌아와도 서버 호출 0건');
ok(api.filtered().length === 5, '전체는 다시 5줄');

// ── 판정 못 한 줄은 이상마진·블랙스팟에 안 들어간다(추측 금지) ──
h.env.el._btns.filter((b) => b._k === 'abnormal')[0].click();
ok(api.filtered().every((r) => r._line_uid !== 'd'),
   '매입가를 못 구한 줄(d)은 이상마진 탭에 없다 — 추측하지 않는다');

// ── 예상 기반 건수를 따로 밝힌다(설계서 §4) ──
ok(/예상 기반 1건/.test(h.env.el.innerHTML),
   '이상마진 탭은 「예상 기반 1건」을 따로 말한다 — 실적에 섞지 않는다');
ok(/판정에서 뺐어요/.test(h.env.el.innerHTML),
   '판정 못 한 줄이 있으면 왜 빠졌는지 말한다 — 「주문이 사라졌다」로 안 보이게');

// ── 0이면 회색 배지 ──
api.setFlags({ a: { abnormal: false, blackspot: false, nopp: false, basis: 'real', judged: true } });
h.env.rows.length = 1;
api.render();
ok(/class="mg-zero">0</.test(h.env.el.innerHTML), '건수가 0이면 배지는 회색(mg-zero)이다');

// ── 회귀 방지 ──
ok(!/data-mg[\s\S]{0,400}?fetch\(/.test(SRC.slice(SRC.indexOf('function renderMgTabs'))),
   'renderMgTabs 안에 fetch 가 없다 (탭 전환 = 거르기만)');
ok(/renderFfTabs\(\);renderMgTabs\(\);/.test(SRC), 'render() 가 마진 탭도 같이 그린다');

console.log('\n결과: ' + (fails ? fails + ' 실패' : '전부 통과'));
process.exit(fails ? 1 : 0);
