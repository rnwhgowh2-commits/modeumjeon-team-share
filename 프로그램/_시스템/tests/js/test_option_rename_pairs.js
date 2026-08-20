const assert = require('assert');
let pass = 0, fail = 0;
function t(name, fn) { try { fn(); console.log('  ✅ ' + name); pass++; } catch (e) { console.log('  ❌ ' + name + ' — ' + e.message); fail++; } }

// ===== 축 값 이름 정정 짝짓기 (option_url_modal.js 배포 로직 복제) =====
//   설계서 — docs/superpowers/specs/2026-08-02-옵션값-이름바꾸기-design.md
//   🔴 짝이 틀리면 소싱처 URL·재고가 엉뚱한 옵션에 붙는다 → 확실할 때만 짝짓는다.
function parseValues(text) { const out = []; (text || '').split(',').forEach(raw => { const v = raw.trim(); if (v && out.indexOf(v) < 0) out.push(v); }); return out; }

function renamePairsFor(oldVals, newVals) {
  if (!oldVals || !newVals || oldVals.length !== newVals.length) return [];
  const out = [];
  for (let j = 0; j < oldVals.length; j++) {
    const o = String(oldVals[j] || '').trim(), n = String(newVals[j] || '').trim();
    if (o && n && o !== n) out.push({ o, n });
  }
  const same = new Set(oldVals.map(String));
  if (out.length && out.every(p => same.has(p.n))) return [];
  return out;
}

function pendingRenames(srvAxes, axes) {
  if (!srvAxes) return [];
  const out = [];
  for (let ai = 0; ai < axes.length && ai < srvAxes.length; ai++) {
    renamePairsFor(srvAxes[ai], parseValues(axes[ai].values || ''))
      .forEach(p => out.push({ axis: ai, from: p.o, to: p.n }));
  }
  return out;
}

console.log('축 값 이름 정정 — 짝짓기 규칙:');

t('테스트 이름 3개 한 번에 정정 → 짝 3개 (사장님 실제 상황)', () => {
  const r = pendingRenames([['색상1', '색상2', '색상3'], ['250', '260']],
                           [{ values: '블랙,화이트,다크네이비' }, { values: '250,260' }]);
  assert.deepStrictEqual(r, [
    { axis: 0, from: '색상1', to: '블랙' },
    { axis: 0, from: '색상2', to: '화이트' },
    { axis: 0, from: '색상3', to: '다크네이비' },
  ]);
});

t('오타 하나만 고침 → 짝 1개', () => {
  const r = pendingRenames([['블랙', '화이트']], [{ values: '블랙,화이드' }]);
  assert.deepStrictEqual(r, [{ axis: 0, from: '화이트', to: '화이드' }]);
});

t('값이 늘면 짝 0개 — 자리가 밀려 엉뚱하게 짝지어질 수 있다', () => {
  assert.deepStrictEqual(pendingRenames([['블랙']], [{ values: '블랙,화이트' }]), []);
});

t('값이 줄면 짝 0개 — 그 옵션은 「빠진 것」으로 처리돼야 한다', () => {
  assert.deepStrictEqual(pendingRenames([['블랙', '화이트']], [{ values: '블랙' }]), []);
});

t('자리만 맞바꾸면 짝 0개 — 이름이 바뀐 게 아니라 순서만 바뀐 것', () => {
  assert.deepStrictEqual(pendingRenames([['블랙', '화이트']], [{ values: '화이트,블랙' }]), []);
});

t('안 고쳤으면 짝 0개 — 저장할 때마다 헛짝이 가지 않는다', () => {
  assert.deepStrictEqual(pendingRenames([['블랙', '화이트']], [{ values: '블랙,화이트' }]), []);
});

t('두 축을 동시에 고쳐도 축 번호가 각각 맞다', () => {
  const r = pendingRenames([['색상1'], ['250']], [{ values: '블랙' }, { values: '255' }]);
  assert.deepStrictEqual(r, [{ axis: 0, from: '색상1', to: '블랙' },
                             { axis: 1, from: '250', to: '255' }]);
});

t('저장된 값을 모르면(첫 진입 전) 짝 0개', () => {
  assert.deepStrictEqual(pendingRenames(null, [{ values: '블랙' }]), []);
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
