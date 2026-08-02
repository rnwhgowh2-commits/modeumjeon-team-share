const assert = require('assert');
let pass = 0, fail = 0;
function t(name, fn) { try { fn(); console.log('  ✅ ' + name); pass++; } catch (e) { console.log('  ❌ ' + name + ' — ' + e.message); fail++; } }

// ===== 저장 후 창이 다시 뜨던 문제 (optgen/box.html 배포 로직 복제) =====
//   🔴 「옵션 만들기」 화면은 들어오면 창을 자동으로 연다.
//      저장하면 새로고침을 하는데, 그때 자동 열기가 또 돌아 창이 다시 떴다.
//      사장님 눈에는 저장이 안 된 것처럼 보였다(실제로는 저장 정상).

function makeStore(initial) {
  const m = Object.assign({}, initial);
  return {
    getItem: k => (k in m ? m[k] : null),
    setItem: (k, v) => { m[k] = String(v); },
    removeItem: k => { delete m[k]; },
    _all: () => m,
  };
}

// box.html 의 justSaved() + autoOpen() 판정만 떼어낸 것
function shouldAutoOpen(store, code, flashes) {
  let raw;
  try { raw = store.getItem('oum:justSaved'); } catch (e) { return true; }
  if (!raw) return true;
  store.removeItem('oum:justSaved');
  let v;
  try { v = JSON.parse(raw); } catch (e) { return true; }
  if (!v || v.code !== code) return true;
  if (v.msg) flashes.push(v.msg);
  return false;
}

console.log('옵션 만들기 화면 — 저장 후 자동 열기:');

t('저장하고 새로고침해 들어오면 창을 다시 열지 않는다', () => {
  const s = makeStore({ 'oum:justSaved': JSON.stringify({ code: 'AF', msg: '저장 완료' }) });
  assert.strictEqual(shouldAutoOpen(s, 'AF', []), false);
});

t('저장 알림을 대신 띄운다 — 새로고침이 원래 알림을 지우기 때문', () => {
  const f = [];
  const s = makeStore({ 'oum:justSaved': JSON.stringify({ code: 'AF', msg: '저장 완료 — 옛 옵션 3개는 판매만 껐어요' }) });
  shouldAutoOpen(s, 'AF', f);
  assert.deepStrictEqual(f, ['저장 완료 — 옛 옵션 3개는 판매만 껐어요']);
});

t('표시는 한 번뿐 — 그냥 새로고침하면 다시 열린다', () => {
  const s = makeStore({ 'oum:justSaved': JSON.stringify({ code: 'AF', msg: '저장 완료' }) });
  shouldAutoOpen(s, 'AF', []);
  assert.strictEqual(shouldAutoOpen(s, 'AF', []), true, '두 번째 진입은 평소대로 열려야 한다');
});

t('처음 들어오면 평소대로 창이 열린다', () => {
  assert.strictEqual(shouldAutoOpen(makeStore({}), 'AF', []), true);
});

t('다른 상품에서 저장한 흔적이면 이 상품 창은 그대로 열린다', () => {
  const s = makeStore({ 'oum:justSaved': JSON.stringify({ code: 'OTHER', msg: '저장 완료' }) });
  assert.strictEqual(shouldAutoOpen(s, 'AF', []), true);
});

t('흔적이 깨져 있어도 창은 열린다 — 못 열려서 아무것도 못 하는 게 더 나쁘다', () => {
  const s = makeStore({ 'oum:justSaved': '{깨진값' });
  assert.strictEqual(shouldAutoOpen(s, 'AF', []), true);
});

t('저장 기록을 못 읽는 브라우저에서도 창은 열린다', () => {
  const broken = { getItem() { throw new Error('blocked'); }, removeItem() {} };
  assert.strictEqual(shouldAutoOpen(broken, 'AF', []), true);
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
