// test_ext_always_polls.js
//  [2026-08-04] 폰 크롤 리모컨 = 확장이 **항상** 서버를 물어야 성립한다.
//  예전엔 폴링 알람을 PC 자동화 화면의 실행 버튼(moum.auto-poll.start)만 만들었다.
//  그래서 크롤이 멈춰 있으면 확장이 /api/crawl/due-bundles 를 아예 안 불렀고
//   ① 폰에서 크롤을 시작시킬 방법이 없었고(리모컨의 존재 이유가 바로 그 순간)
//   ② 서버가 'PC 가 켜져 있나'를 알 길이 없었다(생존 신호가 그 호출에 실린다).
//  본 테스트는 '알람 생성이 모듈 최상위에도 있다'는 불변식을 소스에서 못 박는다.
//  같이: manifest 버전 ↔ MOUM_EXT_VERSION 이 어긋난 전례가 있어(0.7.51 vs 0.7.36)
//  두 곳 일치도 검사한다 — 로드된 확장 버전 진단이 거짓말을 하면 디버깅이 통째로 샌다.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
let pass = 0, fail = 0;
function t(name, fn) { try { fn(); console.log('  ✅ ' + name); pass++; } catch (e) { console.log('  ❌ ' + name + ' — ' + e.message); fail++; } }

const sys = path.join(__dirname, '..', '..');
const extDir = path.join(sys, 'extension', 'moum-crawler');
const bg = fs.readFileSync(path.join(extDir, 'background.js'), 'utf8');
const manifest = JSON.parse(fs.readFileSync(path.join(extDir, 'manifest.json'), 'utf8'));

// `function 이름(` 부터 짝이 맞는 닫는 중괄호까지를 잘라낸다(그 함수의 본문).
function functionBody(src, fnName) {
  const at = src.indexOf('function ' + fnName + '(');
  assert.ok(at >= 0, fnName + ' 함수를 찾지 못함');
  const open = src.indexOf('{', at);
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}' && --depth === 0) return src.slice(open, i + 1);
  }
  throw new Error(fnName + ' 본문의 닫는 중괄호를 찾지 못함');
}

// 주석 줄은 뺀 '진짜 코드'에서만 알람 생성을 센다(설명문에 걸리지 않게).
function alarmCreateLines(src) {
  return src.split('\n').filter(function (ln) {
    const code = ln.replace(/\/\/.*$/, '');
    return /chrome\.alarms\.create\(\s*MOUM_POLL_ALARM/.test(code);
  });
}

console.log('확장은 크롤이 멈춰 있어도 서버를 문다 (폰 리모컨 전제):');

t('크롤 폴링 알람 생성이 소스에 있다', function () {
  assert.ok(alarmCreateLines(bg).length >= 1, 'MOUM_POLL_ALARM 생성이 사라짐');
});

t('알람 생성이 moumAutoPollStart 바깥(모듈 최상위)에도 있다 — 상시 폴링', function () {
  const all = alarmCreateLines(bg).length;
  const inside = alarmCreateLines(functionBody(bg, 'moumAutoPollStart')).length;
  assert.ok(all - inside >= 1,
    '알람 생성이 moumAutoPollStart 안에만 있다 — 실행 버튼을 눌러야만 폴링이 시작된다(폰에서 시작 불가)');
});

t('확장은 /api/crawl/due-bundles 를 부른다 (생존 신호가 실리는 곳)', function () {
  assert.ok(/bgFetch\(\s*["'`]\/api\/crawl\/due-bundles/.test(bg), 'due-bundles 폴링이 사라짐');
});

t('manifest 버전과 MOUM_EXT_VERSION 이 일치한다', function () {
  const m = bg.match(/const\s+MOUM_EXT_VERSION\s*=\s*["']([^"']+)["']/);
  assert.ok(m, 'background.js 에서 MOUM_EXT_VERSION 을 찾지 못함');
  assert.strictEqual(m[1], manifest.version,
    'background.js=' + m[1] + ' vs manifest.json=' + manifest.version + ' — 두 곳이 어긋남');
});

console.log('\n결과: ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
