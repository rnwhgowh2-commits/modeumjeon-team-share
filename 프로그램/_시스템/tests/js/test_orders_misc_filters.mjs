// 실행: node 프로그램/_시스템/tests/js/test_orders_misc_filters.mjs
//        (pytest 에서도 돈다 — tests/orders/test_misc_filters_js.py 가 부른다)
//
// ★ 2026-08-06 매입가(`_pp_purchase`) 필터 사고와 **완전히 같은 부류**가 3곳 더 남아 있었다.
//   화면 전용 칸이라 행(preview.json)에 값이 없고 값은 별도 조회에만 있는데,
//   `filterKey()` 가 `r[col]` 을 보니 목록이 「(빈값) 전부」 하나로 뭉개진다.
//     · 공급방식 `_supply`   → smMap
//     · 가격 전후 `_pdx_purchase` · `_pdx_sale` · `_pdx_margin` → pdxMap
//     · 바로가기 `_links`    → ffMap
//
//   문자열 검사로는 못 잡는다(코드는 늘 「있다」). 그래서 템플릿의 **진짜 원문**을 떼어
//   Node 에서 돌리고, 실제 필터 목록·거르기 결과를 만들어 본다. 마지막에 **뮤테이션**으로
//   이 시험이 진짜 잡는지(RED) 실증한다.
//   (선례: test_orders_purchase_filter.mjs · test_orders_status_filter.mjs)
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

/** `var SM_FKEY={…};` 같은 한 줄짜리 정의를 원문 그대로 떼어 온다. */
function line(startsWith, src = SRC) {
  const hit = src.split('\n').find((l) => l.trimStart().startsWith(startsWith));
  if (!hit) throw new Error(`정의를 못 찾음: ${startsWith}`);
  return hit;
}

/** 필터 팝오버(openColPop)가 목록을 만드는 **그 방식 그대로** 항목·건수를 센다.
 *  (openColPop 첫 줄: `filteredExcept(col).forEach(r => cnt[filterKey(col,r)]++)`) */
function buildHarness(src) {
  return `
    var SHIP=false, xlLoaded=false;
    var colFilter={}, srch='', dmCheckFilter='', ffFilter='', ffReason='', onlyBad=false;
    var clsOf={}, shipCls='go', invResult={}, invMap={}, invSel={};
    var mgMap={}, mgFilter='', ppMap={};
    function dmOf(){return null;} function mgOf(){return null;}
    function invKey(r){return r._line_uid;}
    function srchHay(){return '';}
    // 이 시험의 관심사가 아닌 두 축은 「값 없음」으로 둔다.
    function ppOf(){return null;} function ppFilterKey(){return '값 없음';}
    var ostMap={}, ostFilter='';
    function ostOf(){return null;} function ostFilterKey(){return '지정 안 함';}

    var smMap=env.smMap, smState={}, smSel={};
    var pdxMap=env.pdxMap, ffMap=env.ffMap;
    ${extract('smUid', src)}
    ${extract('smOf', src)}
    ${extract('pdxKey', src)}
    ${extract('pdxOf', src)}
    ${extract('ffOf', src)}
    ${line('var SM_FKEY=', src)}
    ${extract('smFilterKey', src)}
    ${line('var PDX_FKEY=', src)}
    ${extract('pdxPurchaseFilterKey', src)}
    ${extract('pdxSaleFilterKey', src)}
    ${extract('pdxMarginFilterKey', src)}
    ${extract('linkFilterKey', src)}
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
            clearFilters:function(){colFilter={};}};
  `;
}

// ── 라이브를 축소한 표 ──────────────────────────────────────────────
//  pdxKey = 판매처|오픈마켓주문번호|상품명|옵션 (서버 price_diff.row_key 와 같은 규칙)
const mk = (uid, mkt, no, nm, opt, unit) => ({
  _line_uid: uid, 주문일: '2026-08-05', 판매처: mkt,
  오픈마켓주문번호: no, 상품명: nm, 옵션: opt, 단가: unit,
});
const rows = [
  mk('a', '쿠팡', 'O1', '셔츠', 'M', 39000),
  mk('b', '쿠팡', 'O2', '셔츠', 'L', 39000),
  mk('c', '스마트스토어', 'O3', '바지', '28', 51000),
  mk('d', '11번가', 'O4', '코트', 'F', 120000),
  mk('e', '옥션', 'O5', '양말', 'F', 5000),
  Object.assign(mk('', '옥션', 'O6', '모자', 'F', ''), {}),   // 줄 식별자 없음 + 단가 없음
];
const K = (r) => [r.판매처, r.오픈마켓주문번호, r.상품명, r.옵션].join('|');

//  공급방식 — b·c 만 사입으로 바꿔 뒀다. 나머지는 손 안 댐(=무재고 기본).
const smMap = { b: 'stock', c: 'stock' };

//  가격 전후 — 5가지 상황을 한 줄씩
const pdxMap = {
  [K(rows[0])]: { upload_purchase: 20000, current_purchase: 20000, order_sale_price: 39000, margin: 12000, state: 'same' },
  [K(rows[1])]: { upload_purchase: 20000, current_purchase: 26000, order_sale_price: 39000, margin: 6000, state: 'warn' },
  [K(rows[2])]: { upload_purchase: 30000, current_purchase: 44000, order_sale_price: 51000, margin: -1200, state: 'loss' },
  [K(rows[3])]: { upload_purchase: 80000, current_purchase: 71000, order_sale_price: 120000, margin: 21000, state: 'gain' },
  // e = 지금 매입가를 못 읽음(화면에 「확인 불가」) — 마진도 없음
  [K(rows[4])]: { upload_purchase: 3000, current_purchase: null, order_sale_price: 5000, margin: null, state: 'unknown', reason: '지금 소싱처 가격을 못 읽었어요' },
  // f = 올릴 때 값만 없음(비교 불가). 판매가도 pdx 에 없고 행 `단가`도 비었다.
  [K(rows[5])]: { upload_purchase: null, current_purchase: 2000, order_sale_price: null, margin: 900, state: 'unknown' },
};

//  바로가기 — a=소싱처 2 + 상품, b=이력만, c=links 자체가 없음, 나머지는 판정 자체가 없음
const ffMap = {
  [K(rows[0])]: { group: 'fulfill', links: { sources: [{ url: 'https://x/1', label: '무신사' }, { url: 'https://x/2', label: 'SSF' }], product: '/catalog/1' }, sku: 'SKU1' },
  [K(rows[1])]: { group: 'fulfill', links: { sources: [] }, sku: 'SKU2' },
  [K(rows[2])]: { group: 'unfulfill', reason: 'not_ours', links: null, sku: null },
};

const env = { rows, smMap, pdxMap, ffMap };
// eslint-disable-next-line no-new-func
const api = new Function('env', buildHarness(SRC))(env);

// ══════════════════════════════════════════════════════════════════
console.log('① 공급방식(_supply) — smMap 의 진짜 값을 본다:\n');
{
  const cnt = api.tally('_supply');
  const keys = Object.keys(cnt).sort();
  ok(!keys.includes(''), '「(빈값)」 항목이 생기지 않는다(값은 rows 가 아니라 smMap 에 있다)');
  ok(cnt['사입'] === 2, `사입 2줄(b·c) — 실제: ${cnt['사입']}`);
  ok(cnt['무재고'] === 3, `무재고 3줄(a·d·e, 손 안 댄 기본) — 실제: ${cnt['무재고']}`);
  ok(cnt['정할 수 없음'] === 1, `줄 식별자 없는 f 는 「정할 수 없음」 1줄 — 실제: ${cnt['정할 수 없음']}`);
  ok(keys.length === 3, `묶음은 3종뿐(dropship/stock 코드 나열 금지) — 실제: ${keys.length} [${keys}]`);

  api.setFilter('_supply', ['무재고', '정할 수 없음']);
  ok(api.filtered().length === 2, `「사입」만 남기면 2줄 — 실제: ${api.filtered().length}`);
  api.clearFilters();
}

// ══════════════════════════════════════════════════════════════════
console.log('\n② 매입가 (올릴 때 / 지금)(_pdx_purchase) — pdxMap 의 상태를 본다:\n');
{
  const cnt = api.tally('_pdx_purchase');
  const keys = Object.keys(cnt).sort();
  ok(!keys.includes(''), '「(빈값)」 항목이 생기지 않는다');
  ok(cnt['그대로'] === 1, `그대로 1줄(a) — 실제: ${cnt['그대로']}`);
  ok(cnt['올랐음'] === 1, `올랐음 1줄(b) — 실제: ${cnt['올랐음']}`);
  ok(cnt['올랐음 · 손해 전환'] === 1, `손해 전환 1줄(c) — 실제: ${cnt['올랐음 · 손해 전환']}`);
  ok(cnt['내렸음'] === 1, `내렸음 1줄(d) — 실제: ${cnt['내렸음']}`);
  ok(cnt['확인 불가'] === 1, `지금 값을 못 읽은 e 만 「확인 불가」 1줄 — 실제: ${cnt['확인 불가']}`);
  ok(cnt['비교 불가 · 올릴 때 값 없음'] === 1,
     `올릴 때 값만 없는 f 는 「그대로」에 섞이지 않는다 — 실제: ${cnt['비교 불가 · 올릴 때 값 없음']}`);
  ok(keys.length === 6, `금액을 나열하지 않고 6묶음으로만 낸다 — 실제: ${keys.length}`);

  api.setFilter('_pdx_purchase', ['그대로', '내렸음', '확인 불가', '비교 불가 · 올릴 때 값 없음']);
  ok(api.filtered().length === 2, `「올랐음」 2종만 남기면 2줄(b·c) — 실제: ${api.filtered().length}`);
  api.clearFilters();
}

// ══════════════════════════════════════════════════════════════════
console.log('\n③ 주문 판매가(_pdx_sale) · 지금 사면 마진(_pdx_margin):\n');
{
  const cs = api.tally('_pdx_sale');
  ok(cs['값 있음'] === 5, `판매가 값 있음 5줄(a~e) — 실제: ${cs['값 있음']}`);
  ok(cs['값 없음'] === 1, `pdx 도 행 단가도 빈 f 는 「값 없음」 1줄 — 실제: ${cs['값 없음']}`);
  ok(Object.keys(cs).length === 2, `2묶음 — 실제: ${Object.keys(cs).length}`);

  const cm = api.tally('_pdx_margin');
  const mk2 = Object.keys(cm).sort();
  ok(cm['마이너스'] === 1, `마이너스 1줄(c) — 실제: ${cm['마이너스']}`);
  ok(cm['마진 남음'] === 4, `마진 남음 4줄(a·b·d·f) — 실제: ${cm['마진 남음']}`);
  ok(cm['확인 불가'] === 1, `마진을 못 구한 e 는 「확인 불가」 1줄(0 으로 채우지 않는다) — 실제: ${cm['확인 불가']}`);
  ok(mk2.length === 3, `3묶음 — 실제: ${mk2.length} [${mk2}]`);

  api.setFilter('_pdx_margin', ['마진 남음', '확인 불가']);
  ok(api.filtered().length === 1, `「마이너스」만 남기면 1줄 — 실제: ${api.filtered().length}`);
  api.clearFilters();
}

// ══════════════════════════════════════════════════════════════════
console.log('\n④ 바로가기(_links) — ffMap 의 links 를 본다:\n');
{
  const cnt = api.tally('_links');
  const keys = Object.keys(cnt).sort();
  ok(!keys.includes(''), '「(빈값)」 항목이 생기지 않는다(주소를 나열하지도 않는다)');
  ok(cnt['있음'] === 2, `단추가 그려지는 줄 2(a=소싱처2+품, b=이력📈) — 실제: ${cnt['있음']}`);
  ok(cnt['없음'] === 4, `links 가 없는 c 와 판정 자체가 없는 d·e·f = 4줄 — 실제: ${cnt['없음']}`);
  ok(keys.length === 2, `「있음 / 없음」 2묶음 — 실제: ${keys.length} [${keys}]`);

  api.setFilter('_links', ['없음']);
  ok(api.filtered().length === 2, `「없음」을 빼면 2줄 — 실제: ${api.filtered().length}`);
  api.clearFilters();
}

// ══════════════════════════════════════════════════════════════════
//  ⑤ 뮤테이션 — 옛 코드(행에서 직접 읽기)로 되돌리면 이 시험이 **반드시** 깨진다
//     (안 깨지면 아무것도 안 보는 시험이다 — feedback_test_that_tests_nothing)
// ══════════════════════════════════════════════════════════════════
console.log('\n⑤ 뮤테이션(RED 실증):\n');
{
  const OLD = "    function filterKey(col,r){var v=r[col]||''; return col==='주문일'?String(v).slice(0,10):String(v);}";
  const mutated = SRC.replace(extract('filterKey'), OLD);
  if (mutated === SRC) throw new Error('뮤테이션이 filterKey 를 못 바꿨습니다 — 시험이 무효입니다');
  // eslint-disable-next-line no-new-func
  const m = new Function('env', buildHarness(mutated))({ rows, smMap, pdxMap, ffMap });
  ['_supply', '_pdx_purchase', '_pdx_sale', '_pdx_margin', '_links'].forEach((col) => {
    const c = m.tally(col);
    const k = Object.keys(c);
    ok(k.length === 1 && k[0] === '' && c[''] === 6,
       `뮤테이션(옛 filterKey)이면 ${col} 이 「(빈값) 6」 하나로 뭉개진다 — 실제: [${k}]`);
  });
}

// 뮤테이션 2 — 공급방식에서 「정할 수 없음」을 빼고 전부 기본(무재고)으로 세면 건수가 틀어진다
{
  const OLD2 = `function smFilterKey(r){
      var m=smOf(r); return SM_FKEY[m]||String(m);
    }`;
  const mutated2 = SRC.replace(extract('smFilterKey'), OLD2);
  if (mutated2 === SRC) throw new Error('뮤테이션2 가 smFilterKey 를 못 바꿨습니다 — 시험이 무효입니다');
  // eslint-disable-next-line no-new-func
  const m2 = new Function('env', buildHarness(mutated2))({ rows, smMap, pdxMap, ffMap });
  const c2 = m2.tally('_supply');
  ok((c2['정할 수 없음'] || 0) === 0 && c2['무재고'] === 4,
     `뮤테이션2(식별자 없는 줄을 무재고로 취급)면 무재고 4 로 부풀고 「정할 수 없음」이 사라진다 — 실제: 무재고 ${c2['무재고']} · 정할 수 없음 ${c2['정할 수 없음'] || 0}`);
}

// 뮤테이션 3 — 가격 전후에서 「올릴 때 값 없음」을 안 가르면 「그대로」가 부풀거나 확인 불가로 샌다
{
  const OLD3 = `function pdxPurchaseFilterKey(r){
      var d=pdxOf(r);
      if(!d)return '확인 불가';
      return PDX_FKEY[d.state]||'확인 불가';
    }`;
  const mutated3 = SRC.replace(extract('pdxPurchaseFilterKey'), OLD3);
  if (mutated3 === SRC) throw new Error('뮤테이션3 이 pdxPurchaseFilterKey 를 못 바꿨습니다 — 시험이 무효입니다');
  // eslint-disable-next-line no-new-func
  const m3 = new Function('env', buildHarness(mutated3))({ rows, smMap, pdxMap, ffMap });
  const c3 = m3.tally('_pdx_purchase');
  ok((c3['비교 불가 · 올릴 때 값 없음'] || 0) === 0 && c3['확인 불가'] === 2,
     `뮤테이션3(state 만 보기)이면 비교 불가 줄이 사라지고 확인 불가 2 로 뭉친다 — 실제: 비교 불가 ${c3['비교 불가 · 올릴 때 값 없음'] || 0} · 확인 불가 ${c3['확인 불가']}`);
}

console.log('\n결과: ' + (fails ? fails + ' 실패' : '전부 통과'));
process.exit(fails ? 1 : 0);
