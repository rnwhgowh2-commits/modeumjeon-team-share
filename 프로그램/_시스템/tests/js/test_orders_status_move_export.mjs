// 실행: node 프로그램/_시스템/tests/js/test_orders_status_move_export.mjs
//        (pytest 에서도 돈다 — tests/orders/test_status_move_export_js.py 가 부른다)
//
// ★ 「주문 관리」 상태 열 마무리 두 가지 (사장님 확정 2026-08-06)
//   (a) 순서 바꾸기가 **폰에서 안 됐다** — HTML5 drag&drop 은 터치에서 안 먹는다.
//       → 관리 창에 ▲▼ 단추를 넣었다. 끌기는 그대로 두고 **같은 reorder 길**을 쓴다.
//   (b) 엑셀 내보내기에 상태 값이 **없었다** — 상태는 행이 아니라 ostMap 에만 있어서.
//       → 내보낼 때 행 복사본에 「주문 관리」를 얹어 보낸다.
//
//   문자열 검사로는 못 잡는다. 템플릿의 **진짜 원문**을 떼어 Node 에서 돌리고,
//   마지막에 **뮤테이션**으로 이 시험이 진짜 잡는지(RED) 실증한다.
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

// ══════════════════════════════════════════════════════════════════
console.log('(a) ▲▼ 한 칸 옮기기 — 끌기 없이도 순서가 바뀐다:\n');

function moveHarness(src) {
  return `
    var ostOpts=env.ostOpts, sent=[];
    function ostReorder(ids){sent.push(ids);}     // 서버 호출은 잡아만 둔다
    ${extract('ostMove', src)}
    return {move:ostMove, sent:function(){return sent;}};
  `;
}
{
  const ostOpts = [{ id: 11, name: '결제완료' }, { id: 22, name: '배송완료' },
                   { id: 33, name: '오류입고' }, { id: 44, name: '정산완료' }];
  // eslint-disable-next-line no-new-func
  const api = new Function('env', moveHarness(SRC))({ ostOpts });

  api.move(33, -1);
  ok(String(api.sent()[0]) === '11,33,22,44',
     `가운데 항목을 ▲ 하면 바로 위와 자리를 바꾼다 — 실제: [${api.sent()[0]}]`);

  api.move(11, 1);
  ok(String(api.sent()[1]) === '22,11,33,44',
     `▼ 는 바로 아래와 바꾼다 — 실제: [${api.sent()[1]}]`);

  api.move(11, -1);
  ok(api.sent().length === 2, '맨 위에서 ▲ 는 서버를 부르지 않는다(할 일이 없다)');
  api.move(44, 1);
  ok(api.sent().length === 2, '맨 아래에서 ▼ 는 서버를 부르지 않는다');
  api.move(999, -1);
  ok(api.sent().length === 2, '없는 항목 id 로는 아무 일도 하지 않는다');

  // 문자열 id(HTML data-oid 는 늘 문자열이다)로도 같은 답이 나와야 한다
  api.move('22', 1);
  ok(String(api.sent()[2]) === '11,33,22,44',
     `data-oid 는 문자열인데도 찾아낸다 — 실제: [${api.sent()[2]}]`);
  ok(api.sent()[2].every((x) => typeof x === 'number'),
     '서버로는 숫자 id 를 보낸다(reorder API 규약)');
}

// ── 관리 창 원문 확인 — ▲▼ 가 실제로 그려지고 끝줄은 못 누른다 ──
{
  const html = extract('ostModalHTML');
  ok(/class="ost-up"/.test(html) && /class="ost-dn"/.test(html),
     '항목 관리 창이 ▲▼ 단추를 그린다');
  ok(/top\?' disabled':''/.test(html.replace(/\s/g, '').replace(/\(/g, '')) || /disabled/.test(html),
     '끝줄에서는 disabled 로 못 누르게 한다');
  ok(/draggable="true"/.test(html), '끌기(⠿)는 그대로 남아 있다 — 병행이지 교체가 아니다');
  const bind = extract('bindOstModal');
  ok(/bindOstMove\(m\)/.test(bind) && /bindOstDrag\(m\)/.test(bind),
     '창을 그릴 때 ▲▼ 와 끌기 둘 다 배선한다');
  ok(/ostReorder\(ids\)/.test(extract('bindOstDrag')),
     '끌기도 ▲▼ 와 **같은 reorder 길**을 쓴다(두 벌로 갈리지 않는다)');
}

// ══════════════════════════════════════════════════════════════════
console.log('\n(b) 엑셀 내보내기 — 「주문 관리」 값이 행에 얹혀 나간다:\n');

function exportHarness(src) {
  return `
    var ostMap=env.ostMap;
    ${extract('ostUid', src)}
    ${extract('ostOf', src)}
    ${extract('ostExportText', src)}
    ${extract('exportRows', src)}
    return {rows:exportRows, text:ostExportText};
  `;
}
{
  const rows = [
    { _line_uid: 'a', 주문일: '2026-08-05', 판매처: '쿠팡', 상품명: '셔츠' },
    { _line_uid: 'b', 주문일: '2026-08-05', 판매처: '쿠팡', 상품명: '바지' },
    { _line_uid: 'c', 주문일: '2026-08-04', 판매처: '옥션', 상품명: '양말' },
    { _line_uid: '', 주문일: '2026-08-04', 판매처: '옥션', 상품명: '모자' },
  ];
  const ostMap = {
    a: { option_id: 2, name: '배송완료', color: 'green', is_fallback: false },
    b: { option_id: 1, name: '결제완료', color: 'blue', is_fallback: true },
  };
  // eslint-disable-next-line no-new-func
  const api = new Function('env', exportHarness(SRC))({ ostMap });
  const out = api.rows(rows);

  ok(out[0]['주문 관리'] === '배송완료',
     `손으로 고른 줄은 그 이름 그대로 — 실제: ${JSON.stringify(out[0]['주문 관리'])}`);
  ok(out[1]['주문 관리'] === '결제완료 (기본)',
     `기본 항목이 얹힌 줄은 「(기본)」을 붙인다(화면 점선=아직 안 봄과 갈린다) — 실제: ${JSON.stringify(out[1]['주문 관리'])}`);
  ok(out[2]['주문 관리'] === '' && out[3]['주문 관리'] === '',
     `안 고른 줄·식별자 없는 줄은 **빈칸**(지어내지 않는다) — 실제: ${JSON.stringify([out[2]['주문 관리'], out[3]['주문 관리']])}`);

  ok(!('주문 관리' in rows[0]),
     '🔴 원래 행은 건드리지 않는다(srchHay 캐시·필터가 그 행을 그대로 쓴다)');
  ok(out[0]['상품명'] === '셔츠' && out[0]['판매처'] === '쿠팡' && out.length === 4,
     '나머지 값·건수는 그대로 복사된다');

  const doe = extract('doExport');
  ok(/exportRows\(fr\)/.test(doe), '내보내기가 실제로 exportRows 를 거친다');
  ok(/lead_cols\s*:\s*\['주문 관리'\]/.test(doe),
     '서버에 「주문 관리」를 맨 앞 열로 붙여 달라고 알린다');
  ok(/[^_]cols\s*:\s*selCols\(\)/.test(doe),
     '기존 열 구성(selCols=양식)은 그대로 보낸다 — 열 순서·이름을 바꾸지 않는다');
}

// ══════════════════════════════════════════════════════════════════
console.log('\n(c) 뮤테이션(RED 실증):\n');
{
  // 뮤테이션 1 — DOM 이 아니라 ostOpts 를 보는 대신 「자리 바꾸기」를 빼면 순서가 안 바뀐다
  const OLD = `function ostMove(oid,delta){
      var ids=ostOpts.map(function(o){return Number(o.id);});
      ostReorder(ids);
    }`;
  const mutated = SRC.replace(extract('ostMove'), OLD);
  if (mutated === SRC) throw new Error('뮤테이션1 이 ostMove 를 못 바꿨습니다 — 시험이 무효입니다');
  // eslint-disable-next-line no-new-func
  const m = new Function('env', moveHarness(mutated))({
    ostOpts: [{ id: 11 }, { id: 22 }, { id: 33 }, { id: 44 }] });
  m.move(33, -1);
  ok(String(m.sent()[0]) === '11,22,33,44',
     `뮤테이션1(자리 안 바꿈)이면 순서가 그대로 나간다 = 이 시험이 진짜 본다 — 실제: [${m.sent()[0]}]`);

  // 뮤테이션 2 — 기본 표시를 저장된 값처럼 내보내면 「손댐/안 봄」 구분이 사라진다
  const OLD2 = `function ostExportText(r){
      var d=ostOf(r);
      return (d&&d.name)?String(d.name):'';
    }`;
  const mutated2 = SRC.replace(extract('ostExportText'), OLD2);
  if (mutated2 === SRC) throw new Error('뮤테이션2 가 ostExportText 를 못 바꿨습니다 — 시험이 무효입니다');
  // eslint-disable-next-line no-new-func
  const m2 = new Function('env', exportHarness(mutated2))({
    ostMap: { b: { option_id: 1, name: '결제완료', is_fallback: true } } });
  ok(m2.text({ _line_uid: 'b' }) === '결제완료',
     '뮤테이션2(기본을 저장값처럼)면 「(기본)」이 사라져 손댄 줄과 구분이 없어진다');
}

console.log('\n결과: ' + (fails ? fails + ' 실패' : '전부 통과'));
process.exit(fails ? 1 : 0);
