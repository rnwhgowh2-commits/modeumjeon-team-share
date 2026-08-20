// 실행: node 프로그램/_시스템/tests/js/test_orders_purchase_upload_ux.mjs
//        (pytest 에서도 돈다 — tests/orders/test_purchase_upload_ux.py 가 부른다)
//
// ★ 2026-08-06 사장님 확정(2안) — 「더망고 매입 엑셀 올리기」 자리·결과 재설계.
//   ① 「매입가 미입력」 탭을 고르면 카드가 **펼쳐진 채 큼직하게**(pp-hero) 뜬다.
//      옛 배치는 늘 접혀 있어 사장님이 도구가 있는 줄도 모르셨다 = 이번 사건의 근본 원인.
//   ② 저장이 끝나면 **끌어놓기 자리가 접힌다**(큰 표 3개가 계속 남아 「보기 안 좋다」).
//      「다시 올리기」로 되연다.
//   ③ 결과 = 요약 한 줄 + 문제 있는 것만 접이식(가장 흔한 것 하나만 열림).
//   ④ 「구매가격 비어 있음」은 고장이 아니라 정상 동작 — 「손볼 것」과 섞어 세지 않는다.
//      (사장님 실사용: 428줄 전부 매칭 · 228줄이 매입 처리 전이었다)
//
//   문자열 검사로는 못 잡는다. 템플릿의 **진짜 원문**(ppSyncMode + 업로드 IIFE)을 떼어
//   가짜 DOM 위에서 실제로 올려 보고, 마지막에 뮤테이션으로 RED 를 실증한다.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __d = path.dirname(fileURLToPath(import.meta.url));
const TPL = path.join(__d, '..', '..', 'webapp', 'templates', 'orders', 'index.html');
const SRC = fs.readFileSync(TPL, 'utf8').replace(/\r\n/g, '\n');

let fails = 0;
const ok = (cond, msg) => { if (!cond) { console.error('❌', msg); fails += 1; } else { console.log('  ✅', msg); } };

/** ppSyncMode + 업로드 IIFE 원문을 통째로 떼어 온다. 배선이 사라지면 즉사. */
const START = '    var ppManual=null';
const ENDMARK = '\n      ppSyncMode();\n    })();';
function block(src) {
  const s = src.indexOf(START);
  if (s < 0) throw new Error('ppManual/ppSyncMode 배선이 orders/index.html 에 없습니다');
  const e = src.indexOf(ENDMARK, s);
  if (e < 0) throw new Error('업로드 IIFE 의 끝(ppSyncMode(); })();)을 못 찾았습니다');
  return src.slice(s, e + ENDMARK.length);
}

// ══ 가짜 DOM — 관심사는 「올린 뒤 무엇이 접히고 무엇이 남는가」 하나다 ══
function mkClassList(el) {
  const s = new Set();
  return {
    add: (c) => { s.add(c); },
    remove: (c) => { s.delete(c); },
    contains: (c) => s.has(c),
    toggle: (c, force) => {
      const on = (force === undefined) ? !s.has(c) : !!force;
      if (on) s.add(c); else s.delete(c);
      el._cls = [...s];
      return on;
    },
    _set: s,
  };
}
function mkEl(id, doc) {
  const el = { id, style: {}, value: '', textContent: '', files: null, _h: {}, _kids: [], _html: '' };
  el.classList = mkClassList(el);
  el.addEventListener = (t, f) => { (el._h[t] = el._h[t] || []).push(f); };
  el.fire = (t, ev) => (el._h[t] || []).forEach((f) => f(ev || { preventDefault() {} }));
  el.click = () => el.fire('click');
  el.querySelectorAll = (sel) => el._kids.filter((k) => k._sel.indexOf(sel) >= 0);
  el.querySelector = (sel) => el.querySelectorAll(sel)[0] || null;
  Object.defineProperty(el, 'innerHTML', {
    get() { return el._html; },
    set(v) {
      el._html = v; el._kids = [];
      // 결과 판 안의 「다시 올리기」 단추 · 접이식 머리를 가짜로 만든다(id 로 찾을 수 있게).
      if (/id="ppAgain"/.test(v)) doc._reg('ppAgain', mkEl('ppAgain', doc));
      else doc._drop('ppAgain');
      const re = /<div class="ppacc( pp-shut)?" data-acc="(\d+)">/g;
      let m;
      while ((m = re.exec(v)) !== null) {
        const accDiv = mkEl('acc' + m[2], doc);
        accDiv._sel = ['.ppacc'];
        if (m[1]) accDiv.classList.add('pp-shut');
        const arrow = mkEl('ar' + m[2], doc); arrow._sel = ['.ppacc-ar'];
        const head = mkEl('acch' + m[2], doc); head._sel = ['.ppacc-h'];
        head.parentNode = accDiv; head._kids = [arrow];
        accDiv._kids = [head, arrow];
        el._kids.push(head, accDiv);
      }
    },
  });
  el._sel = [];
  return el;
}
function mkDoc() {
  const map = {};
  const doc = {
    getElementById: (i) => map[i] || null,
    _reg: (i, e) => { map[i] = e; },
    _drop: (i) => { delete map[i]; },
    _all: map,
  };
  ['ppCard', 'ppHead', 'ppDz', 'ppFile', 'ppFn', 'ppMsg', 'ppOut', 'ppDrop', 'ppChev', 'ppDzSub']
    .forEach((i) => { map[i] = mkEl(i, doc); });
  return doc;
}

function boot(src) {
  const doc = mkDoc();
  const env = { document: doc, reply: null, calls: 0 };
  env.fetch = () => { env.calls += 1; return Promise.resolve({ ok: true, json: () => Promise.resolve(env.reply) }); };
  env.FormData = function FD() { this.append = () => {}; };
  const script = `
    var SHIP=false, mgFilter='', mgCount=null, loadSeq=7, ppLoads=0;
    var document=env.document, fetch=env.fetch, FormData=env.FormData;
    function loadPurchasePrice(){ppLoads++;}
    function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
    ${block(src)}
    return {sync:ppSyncMode,
            setTab:function(t){mgFilter=t;ppSyncMode();},
            setCount:function(c){mgCount=c;ppSyncMode();},
            loads:function(){return ppLoads;}};
  `;
  // eslint-disable-next-line no-new-func
  const api = new Function('env', script)(env);
  return { doc, env, api };
}
const flush = () => new Promise((r) => setTimeout(r, 0));
function drop(doc, f) { doc.getElementById('ppDz').fire('drop', { preventDefault() {}, dataTransfer: { files: [f] } }); }

console.log('매입 엑셀 올리기 — 자리(2안)·저장 후 접힘·결과 요약:\n');

// ── ① 2안 — 「매입가 미입력」 탭에서만 펼쳐진 채 큼직하게 ──
{
  const { doc, api } = boot(SRC);
  const card = doc.getElementById('ppCard');
  ok(!card.classList.contains('on'), '다른 탭(전체)에서는 접힌 한 줄이다');
  ok(!card.classList.contains('pp-hero'), '전체 탭에서는 hero 가 아니다');

  api.setTab('nopp');
  ok(card.classList.contains('on'), '「매입가 미입력」 탭을 고르면 펼쳐진다 ← 이번 약속');
  ok(card.classList.contains('pp-hero'), '그 탭에서는 끌어놓기 자리가 큼직해진다(pp-hero)');
  ok(doc.getElementById('ppChev').textContent === '▴', '펼침 표시(▴)가 같이 바뀐다');

  api.setCount({ abnormal: 0, blackspot: 0, nopp: 365 });
  ok(/365건을 한 번에 채울 수 있어요/.test(doc.getElementById('ppDzSub').textContent),
     '몇 건이 기다리는지 그 자리에서 말한다');

  api.setTab('abnormal');
  ok(!card.classList.contains('on') && !card.classList.contains('pp-hero'),
     '다른 탭으로 옮기면 다시 접힌다(표가 밀리지 않게)');

  // 판정 전(mgCount=null)엔 숫자를 지어내지 않는다
  api.setCount(null); api.setTab('nopp');
  ok(!/건을 한 번에/.test(doc.getElementById('ppDzSub').textContent),
     '판정 전에는 건수를 지어내지 않는다');

  // 손으로 연 건 그 탭 안에서 유지된다
  api.setTab('');
  doc.getElementById('ppHead').click();
  ok(card.classList.contains('on'), '전체 탭에서도 제목 줄을 누르면 펼쳐진다');
  api.sync();
  ok(card.classList.contains('on'), '다시 그려도 손으로 연 상태는 유지된다');
}

// ── ②③ 저장 뒤 — 끌어놓기 자리는 접히고 요약 한 줄만 남는다 ──
const BIG = {
  ok: true, parsed: 400, matched: 338, saved: 320,
  unmatched: Array.from({ length: 62 }, (_, i) => ({ 행번호: i + 1, 구매가격: 1000 })),
  ambiguous: Array.from({ length: 15 }, (_, i) => ({ 행번호: i + 100 })),
  skipped_zero: Array.from({ length: 3 }, (_, i) => ({ 행번호: i + 200 })),
};
{
  const { doc, env, api } = boot(SRC);
  env.reply = BIG;
  drop(doc, { name: '더망고.xls' });
  await flush(); await flush();

  const out = doc.getElementById('ppOut'), dz = doc.getElementById('ppDrop');
  ok(dz.style.display === 'none', '저장이 끝나면 끌어놓기 자리가 접힌다 ← 이번 약속');
  ok(/320건 채웠어요/.test(out.innerHTML), '요약 줄이 「320건 채웠어요」로 시작한다');
  ok(/읽은 줄 400 · 저장 320/.test(out.innerHTML), '읽은 줄·저장 건수를 한 줄에 같이 말한다');
  ok(/손볼 것 77건/.test(out.innerHTML),
     '「손볼 것」은 못 찾음+줄 못 정함 77건이다(구매가격 없음을 섞지 않는다)');
  ok(/매입 처리를 기다리는 것 3건/.test(out.innerHTML),
     '구매가격이 빈 줄은 「기다리는 것」으로 따로 말한다');
  ok(/id="ppAgain"[^>]*>다시 올리기|다시 올리기/.test(out.innerHTML), '「다시 올리기」 단추가 있다');
  ok(api.loads() === 1, '저장분을 표에 즉시 반영한다(loadPurchasePrice 1회)');

  // 가장 흔한 것 하나만 열려 있다
  const opened = (out.innerHTML.match(/<div class="ppacc" data-acc=/g) || []).length;
  const shut = (out.innerHTML.match(/<div class="ppacc pp-shut" data-acc=/g) || []).length;
  ok(opened === 1 && shut === 2, `접이식 3개 중 하나만 열려 있다 — 열림 ${opened} · 접힘 ${shut}`);
  ok(/<div class="ppacc" data-acc="0">/.test(out.innerHTML),
     '가장 흔한 「못 찾음」(62건)이 열려 있다');
  ok((out.innerHTML.match(/<span class="why">— /g) || []).length === 3,
     '접이식 제목 3개 모두에 왜 그런지 한 줄이 붙는다');
  ok(/기간 밖이거나 아직 안 불러온 주문/.test(out.innerHTML)
     && /후보가 여럿이라 아무 데도 안 적었어요/.test(out.innerHTML),
     '「못 찾음」·「줄을 못 정함」 사유가 시안 문구 그대로다');

  // 접이식을 눌러 여닫을 수 있다
  const heads = out.querySelectorAll('.ppacc-h');
  ok(heads.length === 3, `접이식 머리 3개가 눌린다 — 실제: ${heads.length}`);
  heads[1].click();
  ok(!heads[1].parentNode.classList.contains('pp-shut'), '접힌 것을 누르면 펼쳐진다');

  // 「다시 올리기」 → 자리를 되연다
  doc.getElementById('ppAgain').click();
  ok(dz.style.display === '', '「다시 올리기」를 누르면 끌어놓기 자리가 되돌아온다');
}

// ── ④ 사장님 실사용 실측 — 428줄 전부 매칭 · 228줄 매입 처리 전 ──
{
  const { doc, env } = boot(SRC);
  env.reply = { ok: true, parsed: 428, matched: 428, saved: 200,
    unmatched: [], ambiguous: [],
    skipped_zero: Array.from({ length: 228 }, (_, i) => ({ 행번호: i + 1 })) };
  drop(doc, { name: '더망고.xls' });
  await flush(); await flush();
  const h = doc.getElementById('ppOut').innerHTML;
  ok(!/손볼 것/.test(h), '손볼 것이 없으면 「손볼 것」을 아예 안 띄운다(정상인데 문제처럼 보이면 안 된다)');
  ok(/매입 처리를 기다리는 것 228건/.test(h), '228건은 「기다리는 것」으로 읽힌다');
  ok(/0원을 실매입가로 저장하면 마진이 거짓/.test(h),
     '왜 안 채웠는지(0원 저장 금지)를 그 자리에서 말한다');
  ok(/매입 처리가 끝나면 다시 올려 주세요/.test(h), '다음에 무엇을 하면 되는지 말한다');
  ok(/<div class="ppacc" data-acc="2">/.test(h), '가장 흔한 「구매가격 비어 있음」이 열려 있다');
}

// ── ⑤ 실패하면 자리를 접지 않는다(다시 올릴 곳이 눈앞에 있어야 한다) ──
{
  const { doc, env } = boot(SRC);
  env.reply = { ok: false, error: '엑셀을 읽지 못했어요' };
  drop(doc, { name: 'x.xls' });
  await flush(); await flush();
  ok(doc.getElementById('ppDrop').style.display !== 'none', '올리기 실패면 끌어놓기 자리가 그대로 있다');
  ok(/올리지 못했어요/.test(doc.getElementById('ppMsg').innerHTML), '실패를 조용히 넘기지 않는다');
}

// ══ ⑥ 뮤테이션 — 「접기」를 빼면 이 시험이 반드시 깨진다 ══
{
  const HIDE = "ppDone=true; drop.style.display='none';   // 저장 끝 → 끌어놓기 자리는 접는다";
  if (SRC.indexOf(HIDE) < 0) throw new Error('접기 코드를 못 찾았습니다 — 뮤테이션 무효');
  const mutated = SRC.replace(HIDE, 'ppDone=true;');
  const { doc, env } = boot(mutated);
  env.reply = BIG;
  drop(doc, { name: '더망고.xls' });
  await flush(); await flush();
  ok(doc.getElementById('ppDrop').style.display !== 'none',
     '뮤테이션(접기 제거)이면 자리가 안 접힌다 = 이 시험이 진짜 동작을 본다');
}

console.log('\n결과: ' + (fails ? fails + ' 실패' : '전부 통과'));
process.exit(fails ? 1 : 0);
