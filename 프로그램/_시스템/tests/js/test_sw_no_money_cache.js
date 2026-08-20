// 오프라인일 때 낡은 가격·재고를 보여주면 안 된다 (설계서 §4.7 A안).
// 앱 껍데기(/static/*)만 캐시하고, 나머지는 인터넷이 있을 때만 보여준다.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
let pass = 0, fail = 0;
function t(name, fn) { try { fn(); console.log('  ✅ ' + name); pass++; } catch (e) { console.log('  ❌ ' + name + ' — ' + e.message); fail++; } }

const sw = fs.readFileSync(
  path.join(__dirname, '..', '..', 'webapp', 'static', 'sw.js'), 'utf8');

console.log('sw.js — 돈 데이터 캐시 금지:');

t('networkFirst(캐시 폴백) 가 사라졌다', function () {
  assert.ok(!/networkFirst/.test(sw), 'networkFirst 가 남아있다 — 낡은 값이 나온다');
});

t('런타임 캐시에 쓰는 코드가 없다', function () {
  assert.ok(!/RUNTIME_CACHE/.test(sw), 'RUNTIME_CACHE 가 남아있다');
});

t('cache.put 은 정적 캐시에만 쓴다', function () {
  const puts = sw.split('\n').filter(function (ln) {
    return /cache\.put\(/.test(ln.replace(/\/\/.*$/, ''));
  });
  assert.ok(puts.length <= 1, 'cache.put 이 ' + puts.length + '곳 — 정적 1곳만 허용');
});

t('캐시 버전이 2026-05-17 에서 올라갔다', function () {
  assert.ok(!/modeumjeon-v1-2026-05-17/.test(sw),
    '버전이 그대로면 이미 깔린 낡은 캐시가 안 지워진다');
});

t('오프라인이면 캐시가 아니라 오프라인 응답을 준다', function () {
  assert.ok(/offline/i.test(sw), '오프라인 안내가 없다');
});

console.log('\n결과: ' + pass + ' passed, ' + fail + ' failed');
if (fail) process.exit(1);
